"""Cuádralo · exportación a Excel de las tablas del informe y de los apuntes.

Las cifras se exportan como números (no como texto), con formato de euros, porcentaje o fecha,
cabecera fija y autofiltro, para que el controller pueda seguir trabajando en Excel.
Todas salen de calculos.py y reglas.py, igual que en la web.
"""
import io
from datetime import datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import calculos as c
from . import reglas as r
from .informe import CAUSAS_DE_FACTURA, ETIQUETA_CAUSA, MESES, TARJETAS, _periodo, mes_texto, texto_causa

FORMATOS = {
    'eur': '#,##0.00 "€"', 'eur0': '#,##0 "€"', 'pct': '0.0%', 'pp': '+0.0" pp";-0.0" pp";0.0" pp"',
    'var': '+0.0%;-0.0%;0.0%', 'int': '#,##0', 'num2': '#,##0.00', 'fecha': 'dd/mm/yyyy', 'texto': '@',
}
MARINO = '0F172A'


# ---------------------------------------------------------------- escritura

def _hoja(wb, nombre, df, formatos, cabecera, ancho_max=60, formato_celda=None):
    ws = wb.create_sheet(nombre[:31])
    for i, linea in enumerate(cabecera, start=1):
        ws.cell(row=i, column=1, value=linea).font = Font(bold=(i == 1), size=13 if i == 1 else 10,
                                                          color=None if i == 1 else '64748B')
    fila0 = len(cabecera) + 2
    for j, col in enumerate(df.columns, start=1):
        cel = ws.cell(row=fila0, column=j, value=col)
        cel.font = Font(bold=True, color='FFFFFF')
        cel.fill = PatternFill('solid', fgColor=MARINO)
        cel.alignment = Alignment(vertical='center', wrap_text=True)
    for i, fila in enumerate(df.itertuples(index=False), start=fila0 + 1):
        for j, (col, v) in enumerate(zip(df.columns, fila), start=1):
            if v is None or (isinstance(v, float) and v != v):
                v = None
            elif isinstance(v, pd.Timestamp):
                v = v.to_pydatetime()
            elif isinstance(v, float):
                v = round(v, 6)   # quita restos de coma flotante (19224.479999… → 19224.48)
            cel = ws.cell(row=i, column=j, value=v)
            f = formato_celda(i - fila0 - 1, col) if formato_celda else None
            f = f or formatos.get(col)
            if f:
                cel.number_format = FORMATOS[f]
            if col in ('Causa', 'Explicación', 'Nota', 'Descripción'):
                cel.alignment = Alignment(wrap_text=True, vertical='top')
    for j, col in enumerate(df.columns, start=1):
        largo = max([len(str(col))] + [len(str(x)) for x in df[col].head(300).tolist() if x is not None])
        ws.column_dimensions[get_column_letter(j)].width = min(max(10, largo + 2), ancho_max)
    ws.freeze_panes = ws.cell(row=fila0 + 1, column=1)
    if len(df):
        ws.auto_filter.ref = f'A{fila0}:{get_column_letter(len(df.columns))}{fila0 + len(df)}'
    return ws


def libro(hojas, empresa, periodo_texto, ficticios):
    """hojas: lista de (nombre, título, DataFrame, formatos[, formato_celda]). Devuelve los bytes del .xlsx."""
    wb = Workbook()
    wb.remove(wb.active)
    for h in hojas:
        nombre, titulo, df, formatos = h[:4]
        cabecera = [titulo, f'{empresa} · {periodo_texto} · generado el {datetime.now():%d/%m/%Y %H:%M}']
        if ficticios:
            cabecera.append('Datos ficticios de demostración')
        _hoja(wb, nombre, df, formatos, cabecera, formato_celda=h[4] if len(h) > 4 else None)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- tablas del informe (numéricas)

def _var(real, ref):
    return (real - ref) / abs(ref) if ref not in (None, 0) and real is not None else None


def tabla_kpis(datos, hoteles, mes, modo):
    periodo = _periodo(mes, modo)
    k = datos.kpis(hoteles, periodo)
    p = datos.kpis(hoteles, periodo, 'ppto')
    a = datos.kpis(hoteles, [m - pd.DateOffset(months=12) for m in periodo])
    filas, formatos_fila = [], []
    vistos = set()
    for grupo in ('portada', 'ventas', 'resultados'):
        for nombre, clave, f, tipo, sentido, formula in TARJETAS[grupo]:
            if clave in vistos:
                continue
            vistos.add(clave)
            real, ppto, aa = k.get(clave), p.get(clave) if p else None, a.get(clave) if a else None
            if tipo == 'pp':
                vp = (real - ppto) * 100 if real is not None and ppto is not None else None
                va = (real - aa) * 100 if real is not None and aa is not None else None
            else:
                vp, va = _var(real, ppto), _var(real, aa)
            filas.append({'Indicador': nombre, 'Real': real, 'Presupuesto': ppto, 'Var. vs presupuesto': vp,
                          'Año anterior': aa, 'Var. vs año anterior': va,
                          'Sentido': 'subir es bueno' if sentido > 0 else 'subir es malo', 'Fórmula': formula})
            formatos_fila.append(({'eur': 'eur0', 'eur2': 'eur', 'pct': 'pct', 'num': 'int'}[f], 'pp' if tipo == 'pp' else 'var'))
    df = pd.DataFrame(filas)

    def formato(i, col):
        if col in ('Real', 'Presupuesto', 'Año anterior'):
            return formatos_fila[i][0]
        if col.startswith('Var.'):
            return formatos_fila[i][1]
        return None
    return df, {}, formato


def tabla_pyg(datos, hoteles, mes, modo, solo_bloque=None):
    periodo = _periodo(mes, modo)
    res = datos.resultados(hoteles, periodo)
    res_p = datos.resultados(hoteles, periodo, 'ppto')
    res_a = datos.resultados(hoteles, [m - pd.DateOffset(months=12) for m in periodo])
    filas = []
    for _, e in datos.cfg['estructura_informe'].iterrows():
        linea = e['Línea']
        if res is None or linea not in res.index or (solo_bloque and e['Bloque'] != solo_bloque):
            continue
        real = float(res[linea])
        ppto = float(res_p[linea]) if res_p is not None and linea in res_p.index else None
        aa = float(res_a[linea]) if res_a is not None and linea in res_a.index else None
        filas.append({'Bloque': e['Bloque'], 'Línea': linea, 'Tipo': e['Tipo'], 'Real': real, 'Presupuesto': ppto,
                      'Dif. vs presupuesto': real - ppto if ppto is not None else None, 'Var. vs presupuesto': _var(real, ppto),
                      'Año anterior': aa, 'Dif. vs año anterior': real - aa if aa is not None else None,
                      'Var. vs año anterior': _var(real, aa)})
    fmt = {k: 'eur' for k in ('Real', 'Presupuesto', 'Dif. vs presupuesto', 'Año anterior', 'Dif. vs año anterior')}
    fmt.update({'Var. vs presupuesto': 'var', 'Var. vs año anterior': 'var'})
    return pd.DataFrame(filas), fmt


def tabla_cuadre(datos, hoteles, mes, visibles):
    nombre = lambda h: datos.nombres.get(h, h)
    nv = lambda h: nombre(h) if h in visibles else 'otro hotel del grupo'
    q = datos.cuadre
    filas = []
    for (h, m, linea), x in q.iterrows():
        if h not in hoteles or m != mes:
            continue
        causa = '' if x['Cuadra'] else texto_causa({'tipo': 'Cuadre', 'causa_cuadre': x['Causa'], 'hotel_relacionado': x['Hotel relacionado'],
                                                    'documento': x['Documento'], 'importe': -float(x['Diferencia'])}, 'presupuesto', nv)
        filas.append({'Hotel': nombre(h), 'Línea': linea, 'Operador': float(x['Operador']), 'Contabilidad': float(x['Contabilidad']),
                      'Diferencia': float(x['Diferencia']), 'Estado': 'Cuadra' if x['Cuadra'] else 'No cuadra', 'Causa': causa})
    return pd.DataFrame(filas), {'Operador': 'eur', 'Contabilidad': 'eur', 'Diferencia': 'eur'}


def tabla_ratios(datos, hoteles, mes):
    rr = datos.ratios
    if not len(rr):
        return pd.DataFrame(), {}
    sel = rr[rr['Id hotel'].isin(hoteles) & (rr['Mes'] == mes)]
    filas, fmts = [], []
    for _, x in sel.iterrows():
        puntos = x['Tipo'] == 'puntos'
        es_pct = x['Ratio'] in ('Ocupación', 'Captación de desayunos')
        filas.append({'Hotel': datos.nombres.get(x['Id hotel']), 'Ratio': x['Ratio'], 'Fórmula': x['Fórmula'],
                      'Operador': float(x['Operador']), 'Recalculado': float(x['Recalculado']),
                      'Diferencia': float(x['Diferencia']) * (100 if puntos else 1),
                      'Estado': 'Correcto' if x['Correcto'] else 'Revisar',
                      'Impacto en alojamiento': float(x['Impacto']) if x['Impacto'] == x['Impacto'] and x['Impacto'] is not None else None,
                      'Nota': x['Nota']})
        fmts.append(('pct' if es_pct else 'eur', 'pp' if puntos else 'var'))

    def formato(i, col):
        if col in ('Operador', 'Recalculado'):
            return fmts[i][0]
        if col == 'Diferencia':
            return fmts[i][1]
        return 'eur0' if col == 'Impacto en alojamiento' else None
    return pd.DataFrame(filas), {}, formato


def tabla_desviaciones(datos, hoteles, mes, visibles):
    nombre = lambda h: datos.nombres.get(h, h)
    nv = lambda h: nombre(h) if h in visibles else 'otro hotel del grupo'
    desv = r.desviaciones(datos.mov, datos.det_real, datos.det_ppto, datos.act, datos.cuadre, datos.cfg, hoteles, mes)
    filas = []
    for d in sorted(desv, key=lambda x: -abs(x['Dif ref'])):
        causas = d['Causas'] or [{'tipo': 'Sin causa'}]
        for x in causas:
            sin = x['tipo'] == 'Sin causa'
            filas.append({
                'Hotel': nombre(d['Id hotel']), 'Línea': d['Línea'], 'Bloque': d['Bloque'],
                'Referencia que salta': d['Referencia'], 'Real': d['Real'], 'Presupuesto': d['Presupuesto'],
                'Dif. vs presupuesto': d['Dif ppto'], 'Var. vs presupuesto': d['Var ppto'],
                'Año anterior': d['Año anterior'], 'Dif. vs año anterior': d['Dif AA'], 'Var. vs año anterior': d['Var AA'],
                'Favorable': 'Sí' if d['Favorable'] else 'No', 'Falsa alarma': 'Sí' if d['Falsa alarma'] else 'No',
                'Causa': 'Sin causa' if sin else ETIQUETA_CAUSA.get(x['tipo'], x['tipo']),
                'Explicación': 'Ninguna regla encuentra la causa en las facturas: revisar a mano.' if sin else texto_causa(x, d['Referencia'], nv),
                'Proveedor': x.get('proveedor', ''), 'Documento': x.get('documento', ''),
                'Importe de la causa': x['importe'] if x['tipo'] in CAUSAS_DE_FACTURA else None,
                'Versión reglas': d['Versión reglas']})
    fmt = {k: 'eur' for k in ('Real', 'Presupuesto', 'Dif. vs presupuesto', 'Año anterior', 'Dif. vs año anterior', 'Importe de la causa')}
    fmt.update({'Var. vs presupuesto': 'var', 'Var. vs año anterior': 'var'})
    return pd.DataFrame(filas), fmt


def tabla_comparativa(datos, hoteles, mes, modo):
    periodo = _periodo(mes, modo)
    filas = []
    for h in hoteles:
        k = datos.kpis([h], periodo)
        if not k:
            continue
        kp = datos.kpis([h], periodo, 'ppto')
        filas.append({'Hotel': datos.nombres.get(h), 'Ingresos': k['Ingresos totales'], 'GOP': k['GOP'], '% GOP': k['% GOP'],
                      'GOP vs presupuesto': _var(k['GOP'], kp.get('GOP') if kp else None),
                      'AGOP': k['AGOP'], 'GOP2': k['GOP2'], 'Room nights': k['Room nights'], 'Ocupación': k['Ocupación'],
                      'ADR': k['ADR'], 'RevPAR': k['RevPAR'], 'TRevPAR': k['TRevPAR'], 'GOPPAR': k['GOPPAR'],
                      'Labor cost': k['Labor cost'], 'CPOR': k['CPOR']})
    fmt = {'Ingresos': 'eur0', 'GOP': 'eur0', 'AGOP': 'eur0', 'GOP2': 'eur0', '% GOP': 'pct', 'GOP vs presupuesto': 'var',
           'Room nights': 'int', 'Ocupación': 'pct', 'ADR': 'eur', 'RevPAR': 'eur', 'TRevPAR': 'eur', 'GOPPAR': 'eur',
           'Labor cost': 'pct', 'CPOR': 'eur'}
    return pd.DataFrame(filas), fmt


def tabla_coste_rn(datos, hoteles, mes):
    cp = r.coste_por_room_night(datos.det_real, datos.act, datos.cfg, hoteles, mes)
    if not len(cp):
        return pd.DataFrame(), {}
    df = pd.DataFrame({'Hotel': cp['Id hotel'].map(datos.nombres), 'Partida': cp['Línea'],
                       '€ por room night (mediana 3 meses)': cp['Por room night'],
                       'Mediana del resto de hoteles': cp['Mediana otros'], 'Exceso al mes': cp['Exceso'],
                       'Coste estructural alto': cp['Alto'].map({True: 'Sí', False: 'No'})})
    return df, {'€ por room night (mediana 3 meses)': 'eur', 'Mediana del resto de hoteles': 'eur', 'Exceso al mes': 'eur0'}


TABLAS = {
    'indicadores': 'Indicadores',
    'ingresos': 'Ingresos por línea',
    'cuenta': 'Cuenta de resultados',
    'cuadre': 'Cuadre operador–contabilidad',
    'ratios': 'Ratios del operador',
    'desviaciones': 'Desviaciones',
    'comparativa': 'Comparativa entre hoteles',
    'coste_rn': 'Coste por room night',
}


def hojas_informe(datos, que, hoteles, visibles, mes, modo):
    """Devuelve la lista de hojas para `que` (una tabla o 'informe' = todas)."""
    es_grupo = len(hoteles) > 1
    p_txt = mes_texto(mes) if modo == 'mes' else f'enero-{MESES[mes.month - 1]} {mes.year}'

    def una(clave):
        if clave == 'indicadores':
            return ('Indicadores', f'Indicadores · {p_txt}', *tabla_kpis(datos, hoteles, mes, modo))
        if clave == 'ingresos':
            return ('Ingresos', f'Ingresos por línea · {p_txt}', *tabla_pyg(datos, hoteles, mes, modo, 'Ingresos'))
        if clave == 'cuenta':
            return ('Cuenta de resultados', f'Cuenta de resultados hasta GOP2 · {p_txt}', *tabla_pyg(datos, hoteles, mes, modo))
        if clave == 'cuadre':
            return ('Cuadre', f'Cuadre operador–contabilidad · {mes_texto(mes)}', *tabla_cuadre(datos, hoteles, mes, visibles))
        if clave == 'ratios':
            return ('Ratios', f'Ratios del operador · {mes_texto(mes)}', *tabla_ratios(datos, hoteles, mes))
        if clave == 'desviaciones':
            return ('Desviaciones', f'Desviaciones y causas · {mes_texto(mes)}', *tabla_desviaciones(datos, hoteles, mes, visibles))
        if clave == 'comparativa':
            return ('Comparativa', f'Comparativa entre hoteles · {p_txt}', *tabla_comparativa(datos, hoteles, mes, modo))
        if clave == 'coste_rn':
            return ('Coste por room night', f'Coste por room night · {mes_texto(mes)}', *tabla_coste_rn(datos, hoteles, mes))
        raise KeyError(clave)

    if que == 'informe':
        claves = ['indicadores', 'cuenta', 'cuadre', 'ratios', 'desviaciones'] + (['comparativa', 'coste_rn'] if es_grupo else [])
        return [una(k) for k in claves]
    if que in ('comparativa', 'coste_rn') and not es_grupo:
        raise KeyError(que)
    return [una(que)]
