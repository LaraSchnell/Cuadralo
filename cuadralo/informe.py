"""Cuádralo · prepara el contenido del informe para la web.

Recibe el modelo común de una empresa y devuelve un diccionario listo para las plantillas: tarjetas,
gráficos, tablas, cuadre, desviaciones con su causa, alertas y frases de resumen.

Todas las cifras salen de calculos.py y reglas.py. Los textos son plantillas fijas rellenadas con esas
cifras; ningún texto ni número lo genera la IA.
"""
import pandas as pd

from . import calculos as c
from . import reglas as r

MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
         'septiembre', 'octubre', 'noviembre', 'diciembre']
MESES_CORTOS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
MAX_ALERTAS_PORTADA = 5


# ---------------------------------------------------------------- formato español

def num(v, dec=0):
    if v is None or v != v:
        return '—'
    texto = f'{abs(float(v)):,.{dec}f}'.replace(',', '§').replace('.', ',').replace('§', '.')
    return ('−' if float(v) < 0 and round(abs(float(v)), dec) != 0 else '') + texto


def eur(v, dec=0):
    return '—' if v is None or v != v else f'{num(v, dec)} €'


def pct(v, dec=1):
    return '—' if v is None or v != v else f'{num(float(v) * 100, dec)} %'


def con_signo(v, dec=1, unidad='%'):
    if v is None or v != v:
        return None
    s = num(v, dec)
    return ('+' if round(float(v), dec) > 0 else ('±' if round(float(v), dec) == 0 else '')) + s + ' ' + unidad


def mes_texto(ts):
    return f'{MESES[ts.month - 1]} {ts.year}'


# ---------------------------------------------------------------- tarjetas KPI

# nombre, clave en kpis(), formato, tipo de variación, sentido (+1 subir es bueno, −1 subir es malo), fórmula
TARJETAS = {
    'portada': [
        ('Ingresos totales', 'Ingresos totales', 'eur', 'rel', 1, 'Suma de las líneas de ingreso en contabilidad'),
        ('GOP', 'GOP', 'eur', 'rel', 1, 'Ingresos − consumos − personal − otros gastos operativos'),
        ('% GOP', '% GOP', 'pct', 'pp', 1, 'GOP / ingresos totales'),
        ('Ocupación', 'Ocupación', 'pct', 'pp', 1, 'Room nights / (habitaciones × días)'),
        ('ADR', 'ADR', 'eur2', 'rel', 1, 'Ingresos de alojamiento del operador / room nights'),
        ('RevPAR', 'RevPAR', 'eur2', 'rel', 1, 'Ingresos de alojamiento / (habitaciones × días)'),
        ('GOPPAR', 'GOPPAR', 'eur2', 'rel', 1, 'GOP / (habitaciones × días)'),
        ('Labor cost', 'Labor cost', 'pct', 'pp', -1, 'Total personal / ingresos totales. Subir es malo'),
    ],
    'ventas': [
        ('Room nights', 'Room nights', 'num', 'rel', 1, 'Noches vendidas según el operador'),
        ('TRevPAR', 'TRevPAR', 'eur2', 'rel', 1, 'Ingresos totales / (habitaciones × días)'),
        ('Captación de desayunos', 'Captación desayunos', 'pct', 'pp', 1, 'Desayunos / (room nights × pax por habitación)'),
        ('Precio medio desayuno', 'Precio medio desayuno', 'eur2', 'rel', 1, 'Ingresos de desayunos / desayunos servidos'),
    ],
    'resultados': [
        ('AGOP', 'AGOP', 'eur', 'rel', 1, 'GOP − honorarios del operador − reserva FF&E'),
        ('GOP2', 'GOP2', 'eur', 'rel', 1, 'AGOP − tributos − amortizaciones − gastos financieros'),
        ('CPOR', 'CPOR', 'eur2', 'rel', -1, '(Personal hotel + otros gastos operativos) / room nights. Subir es malo'),
        ('Margen de desayunos', 'Margen desayunos', 'eur', 'rel', 1, 'Ingresos − consumo − personal de desayunos'),
    ],
}


def _formato(v, f):
    return {'eur': eur(v), 'eur2': eur(v, 2), 'pct': pct(v), 'num': num(v)}[f]


def _variacion(actual, ref, tipo, sentido):
    if actual is None or ref is None:
        return None
    if tipo == 'pp':
        d = (actual - ref) * 100
        texto = con_signo(d, 1, 'pp')
    else:
        if not ref:
            return None
        d = (actual - ref) / abs(ref) * 100
        texto = con_signo(d, 1, '%')
    if round(d, 1) == 0:
        estado = 'neutro'
    else:
        estado = 'bien' if d * sentido > 0 else 'mal'
    return {'texto': texto, 'estado': estado, 'flecha': '▲' if d > 0.05 else ('▼' if d < -0.05 else '■')}


def tarjetas(grupo, k_real, k_ppto, k_aa):
    out = []
    for nombre, clave, f, tipo, sentido, formula in TARJETAS[grupo]:
        out.append({'nombre': nombre, 'valor': _formato(k_real.get(clave), f), 'formula': formula,
                    'ppto': _variacion(k_real.get(clave), k_ppto.get(clave) if k_ppto else None, tipo, sentido),
                    'aa': _variacion(k_real.get(clave), k_aa.get(clave) if k_aa else None, tipo, sentido)})
    return out


# ---------------------------------------------------------------- agregación

def _suma(df, hoteles, meses):
    """Suma las filas de los hoteles y meses pedidos. Devuelve None si no hay ninguna."""
    if df is None or len(df) == 0:
        return None
    idx = [(h, m) for h in hoteles for m in meses if (h, m) in df.index]
    if not idx:
        return None
    return df.loc[idx].sum()


def _periodo(mes, modo):
    if modo == 'acumulado':
        return [pd.Timestamp(mes.year, m, 1) for m in range(1, mes.month + 1)]
    return [mes]


class Datos:
    """Todo lo calculado una vez para una empresa: se reutiliza en todas las páginas."""

    def __init__(self, mov, pms, pres, cfg):
        self.cfg = cfg
        self.mov = mov
        self.det_real = c.detalle_real(mov, cfg)
        self.det_ppto = c.presupuesto_detalle(pres)
        self.act = c.actividad_completa(pms, cfg)
        self.cuadre = c.cuadre(mov, pms, cfg)
        self.ratios = c.comprobar_ratios(pms, cfg)
        self.nombres = cfg['hoteles'].set_index('Id hotel')['Hotel'].to_dict()
        self.meses = sorted(set(self.act.index.get_level_values('Mes')) & set(self.det_real.index.get_level_values('Mes')),
                            reverse=True)

    def resultados(self, hoteles, meses, cual='real'):
        det = self.det_real if cual == 'real' else self.det_ppto
        s = _suma(det, hoteles, meses)
        if s is None:
            return None
        fila = c.resultados(s.to_frame().T, self.cfg).iloc[0]
        return fila

    def actividad(self, hoteles, meses):
        return _suma(self.act, hoteles, meses)

    def kpis(self, hoteles, meses, cual='real'):
        res = self.resultados(hoteles, meses, cual)
        act = self.actividad(hoteles, meses)
        if res is None or act is None:
            return {}
        if cual == 'ppto':
            # el presupuesto se compara con la misma capacidad (habitaciones × días)
            return c.kpis(res, act, ppto=True)
        return c.kpis(res, act)


# ---------------------------------------------------------------- textos de causas

def texto_causa(causa, referencia, nombre_visible):
    t = causa['tipo']
    if t == 'Cuadre':
        rel = nombre_visible(causa.get('hotel_relacionado'))
        cc = causa.get('causa_cuadre')
        if cc == 'contabilizado en otro hotel':
            return f'El operador lo reporta, pero en contabilidad está registrado en {rel}.'
        if cc == 'ingreso de otro hotel':
            return f'Incluye un ingreso de {rel} registrado en la contabilidad de este hotel.'
        if cc == 'abono no reportado por el operador':
            return f'Abono {causa.get("documento")} en contabilidad que el operador no reporta.'
        if cc == 'sin contabilizar':
            return f'El operador reporta {eur(abs(causa["importe"]))} que no están en contabilidad.'
        return f'Contabilidad registra {eur(abs(causa["importe"]))} que el operador no reporta.'
    if t == 'Actividad':
        partes = []
        if causa.get('var_cantidad') is not None:
            partes.append(f'{causa["cantidad"]} {con_signo(causa["var_cantidad"] * 100)}')
        if causa.get('var_precio') is not None:
            partes.append(f'{causa["precio"]} {con_signo(causa["var_precio"] * 100)}')
        return 'Se explica por la venta: ' + ' y '.join(partes) + f' frente al {referencia}.'
    if t == 'Ventas':
        return 'Variación de ventas. El operador y la contabilidad cuadran en esta línea.'
    if t == 'Falsa alarma':
        return f'Se explica por la actividad: {causa["unidad"]} {con_signo(causa["var_base"] * 100)} frente al {referencia}.'
    if t == 'Sin apuntes':
        return 'No hay ningún apunte este mes; el presupuesto reparte este gasto en todos los meses.'
    if t == 'Subida de precio' and causa.get('desde') is not None:
        return causa['texto'] + f', desde {MESES[causa["desde"].month - 1]}.'
    return causa.get('texto', '') + '.'


ETIQUETA_CAUSA = {
    'Cuadre': 'No cuadra', 'Actividad': 'Venta', 'Ventas': 'Venta', 'Falsa alarma': 'Falsa alarma',
    'Sin apuntes': 'Sin apuntes', 'Duplicada': 'Duplicada', 'Otro mes': 'Factura de otro mes',
    'Proveedor nuevo': 'Proveedor nuevo', 'Factura que falta': 'Factura que falta', 'Subida de precio': 'Subida de precio',
}
CAUSAS_DE_FACTURA = {'Duplicada', 'Otro mes', 'Proveedor nuevo', 'Factura que falta', 'Subida de precio', 'Cuadre'}


# ---------------------------------------------------------------- informe completo

def construir(datos, hoteles_visibles, seleccion, mes, modo='mes'):
    """Contenido de las páginas del informe.

    hoteles_visibles: los hoteles que el usuario puede ver (un director de hotel, solo el suyo).
    seleccion: 'GRUPO' o un Id de hotel dentro de hoteles_visibles.
    """
    cfg = datos.cfg
    hoteles = list(hoteles_visibles) if seleccion == 'GRUPO' else [seleccion]
    es_grupo = len(hoteles) > 1
    periodo = _periodo(mes, modo)
    periodo_aa = [m - pd.DateOffset(months=12) for m in periodo]
    nombre = lambda h: datos.nombres.get(h, h)
    nombre_visible = lambda h: nombre(h) if h in hoteles_visibles else 'otro hotel del grupo'

    k_real = datos.kpis(hoteles, periodo)
    k_ppto = datos.kpis(hoteles, periodo, 'ppto')
    k_aa = datos.kpis(hoteles, periodo_aa)
    hay_ppto = bool(k_ppto)

    # ---- serie de 13 meses (siempre mensual)
    meses13 = [mes - pd.DateOffset(months=i) for i in range(12, -1, -1)]

    def serie(clave, cual='real', desplazar=0):
        vals = []
        for m in meses13:
            k = datos.kpis(hoteles, [m - pd.DateOffset(months=desplazar)], cual)
            v = k.get(clave) if k else None
            vals.append(None if v is None else round(float(v), 4))
        return vals

    etiquetas = [MESES_CORTOS[m.month - 1] + (f' {str(m.year)[2:]}' if m.month == 1 or i == 0 else '')
                 for i, m in enumerate(meses13)]
    graficos = {
        'etiquetas': etiquetas,
        'ingresos': serie('Ingresos totales'), 'ingresos_ppto': serie('Ingresos totales', 'ppto'),
        'ingresos_aa': serie('Ingresos totales', desplazar=12), 'gop': serie('GOP'),
        'ocupacion': [None if v is None else v * 100 for v in serie('Ocupación')],
        'ocupacion_aa': [None if v is None else v * 100 for v in serie('Ocupación', desplazar=12)],
        'adr': serie('ADR'), 'adr_aa': serie('ADR', desplazar=12),
    }

    # ---- cuenta de resultados (periodo)
    res = datos.resultados(hoteles, periodo)
    res_p = datos.resultados(hoteles, periodo, 'ppto')
    res_a = datos.resultados(hoteles, periodo_aa)
    est = cfg['estructura_informe']
    bloques = dict(zip(est['Línea'], est['Bloque']))
    pyg = []
    for _, e in est.iterrows():
        linea = e['Línea']
        if res is None or linea not in res.index:
            continue
        real = float(res[linea])
        ppto = float(res_p[linea]) if res_p is not None and linea in res_p.index else None
        aa = float(res_a[linea]) if res_a is not None and linea in res_a.index else None
        ingreso = e['Bloque'] in ('Ingresos',) or e['Tipo'] == 'Resultado'
        sentido = 1 if ingreso else -1
        var = _variacion(real, ppto, 'rel', sentido) if ppto is not None else None
        pyg.append({'linea': linea, 'tipo': e['Tipo'], 'bloque': e['Bloque'], 'real': eur(real),
                    'ppto': eur(ppto) if ppto is not None else '—', 'aa': eur(aa) if aa is not None else '—',
                    'dif': (con_signo(real - ppto, 0, '€') if ppto is not None else '—'),
                    'var': var, 'oculta': e['Tipo'] == 'Detalle'})

    cascada = []
    if res is not None:
        cascada = [
            ('Ingresos', float(res['Total ingresos']), True), ('Consumos', -float(res['Total consumos']), False),
            ('Personal', -float(res['Total personal']), False),
            ('Otros gastos', -float(res['Total otros gastos operativos']), False), ('GOP', float(res['GOP']), True),
            ('Ajustes', -float(res['Total ajustes']), False), ('AGOP', float(res['AGOP']), True),
            ('Bajo AGOP', -float(res['Total por debajo del AGOP']), False), ('GOP2', float(res['GOP2']), True)]

    # ---- coste por room night de cada partida (real frente a presupuesto)
    act = datos.actividad(hoteles, periodo)
    coste_rn = []
    if res is not None and act is not None and act['Room nights']:
        rn_p = float(res_p['Room nights']) if res_p is not None and 'Room nights' in res_p.index else None
        partidas = est[(est['Bloque'] == 'Otros gastos operativos') & (est['Tipo'] == 'Detalle')]['Línea']
        for linea in partidas:
            v = float(res[linea]) / float(act['Room nights'])
            p = float(res_p[linea]) / rn_p if rn_p and res_p is not None and linea in res_p.index else None
            if v or p:
                coste_rn.append({'linea': linea, 'real': round(v, 2), 'ppto': None if p is None else round(p, 2)})
        coste_rn.sort(key=lambda x: -x['real'])

    # ---- ingresos por línea (página de ventas)
    ingresos = [x for x in pyg if x['bloque'] == 'Ingresos']

    # ---- cuadre y ratios (siempre del mes)
    cuadre_filas = []
    for h in hoteles:
        for linea in [l for l in c.lineas_detalle(cfg) if bloques.get(l) == 'Ingresos']:
            if (h, mes, linea) not in datos.cuadre.index:
                continue
            q = datos.cuadre.loc[(h, mes, linea)]
            causa = ''
            if not q['Cuadra']:
                causa = texto_causa({'tipo': 'Cuadre', 'causa_cuadre': q['Causa'], 'hotel_relacionado': q['Hotel relacionado'],
                                     'documento': q['Documento'], 'importe': -float(q['Diferencia'])}, 'presupuesto', nombre_visible)
            cuadre_filas.append({'hotel': nombre(h), 'linea': linea, 'operador': eur(q['Operador'], 2),
                                 'contabilidad': eur(q['Contabilidad'], 2),
                                 'diferencia': '0 €' if q['Cuadra'] else con_signo(q['Diferencia'], 2, '€'),
                                 'cuadra': bool(q['Cuadra']), 'causa': causa})
    diferencias = [f for f in cuadre_filas if not f['cuadra']]
    importe_dif = sum(abs(float(datos.cuadre.loc[(h, mes, l), 'Diferencia'])) for h in hoteles
                      for l in c.lineas_detalle(cfg) if (h, mes, l) in datos.cuadre.index
                      and not datos.cuadre.loc[(h, mes, l), 'Cuadra'])

    ratios = []
    rr = datos.ratios
    if len(rr):
        sel = rr[rr['Id hotel'].isin(hoteles) & (rr['Mes'] == mes)]
        for _, x in sel.iterrows():
            puntos = x['Tipo'] == 'puntos'
            fmt = (lambda v: pct(v)) if x['Ratio'] in ('Ocupación', 'Captación de desayunos') else (lambda v: eur(v, 2))
            nota = x['Nota']
            if not x['Correcto'] and x['Impacto'] == x['Impacto'] and x['Impacto'] is not None:
                nota = f'Si se facturara como room nights × ADR del operador, el alojamiento saldría {eur(x["Impacto"])} más alto.'
            ratios.append({'hotel': nombre(x['Id hotel']), 'ratio': x['Ratio'], 'formula': x['Fórmula'],
                           'operador': fmt(x['Operador']), 'recalculado': fmt(x['Recalculado']),
                           'diferencia': con_signo(x['Diferencia'] * 100, 1, 'pp' if puntos else '%'),
                           'correcto': bool(x['Correcto']), 'nota': nota})
    ratios_mal = [x for x in ratios if not x['correcto']]

    # ---- desviaciones (siempre del mes)
    desv = r.desviaciones(datos.mov, datos.det_real, datos.det_ppto, datos.act, datos.cuadre, cfg, hoteles, mes)
    apuntes = c.asignar_lineas(datos.mov, cfg)
    apuntes = apuntes[apuntes['Mes'] == mes]
    desviaciones, falsas = [], []
    for d in sorted(desv, key=lambda x: -abs(x['Dif ref'])):
        referencia = d['Referencia']
        causas = d['Causas']
        textos = [{'etiqueta': ETIQUETA_CAUSA.get(x['tipo'], x['tipo']), 'texto': texto_causa(x, referencia, nombre_visible),
                   'proveedor': x.get('proveedor', ''), 'documento': x.get('documento', ''),
                   'importe': eur(x['importe']) if x['tipo'] in CAUSAS_DE_FACTURA else ''} for x in causas]
        if not textos:
            textos = [{'etiqueta': 'Sin causa', 'texto': 'Ninguna regla encuentra la causa en las facturas: revisar a mano.',
                       'proveedor': '', 'documento': '', 'importe': ''}]
        ap = apuntes[(apuntes['Id hotel'] == d['Id hotel']) & (apuntes['Línea'] == d['Línea'])]
        ap = ap.reindex(ap['Importe sin IVA'].abs().sort_values(ascending=False).index).head(8)
        fila = {
            'hotel': nombre(d['Id hotel']), 'linea': d['Línea'], 'ingreso': d['Ingreso'],
            'real': eur(d['Real']), 'ppto': eur(d['Presupuesto']) if d['Presupuesto'] is not None else '—',
            'aa': eur(d['Año anterior']) if d['Año anterior'] is not None else '—',
            'dif': con_signo(d['Dif ref'], 0, '€'),
            'var': con_signo((d['Var ppto'] if referencia == 'presupuesto' else d['Var AA']) * 100, 1, '%')
                   if (d['Var ppto'] if referencia == 'presupuesto' else d['Var AA']) is not None else 'nuevo',
            'referencia': referencia, 'favorable': d['Favorable'], 'causas': textos,
            'tiene_causa_factura': any(x['tipo'] in CAUSAS_DE_FACTURA for x in causas),
            'sin_causa': not causas, 'impacto': abs(d['Dif ref']),
            'apuntes': [{'fecha': f'{a["Fecha de registro"]:%d/%m/%Y}', 'doc': a['Nº documento'], 'proveedor': a['Proveedor'],
                         'descripcion': a['Descripción'], 'importe': eur(a['Importe sin IVA'], 2)} for _, a in ap.iterrows()],
        }
        (falsas if d['Falsa alarma'] else desviaciones).append(fila)

    # ---- comparativa entre hoteles (solo si se ve más de un hotel)
    comparativa, estructural = [], []
    if es_grupo:
        for h in hoteles:
            k = datos.kpis([h], periodo)
            kp = datos.kpis([h], periodo, 'ppto')
            if not k:
                continue
            dif_h = sum(1 for f in cuadre_filas if f['hotel'] == nombre(h) and not f['cuadra'])
            comparativa.append({'id': h, 'hotel': nombre(h), 'ingresos': eur(k['Ingresos totales']), 'gop': eur(k['GOP']),
                                'gop_pct': pct(k['% GOP']), 'ocupacion': pct(k['Ocupación']), 'adr': eur(k['ADR'], 2),
                                'revpar': eur(k['RevPAR'], 2), 'labor': pct(k['Labor cost']), 'cpor': eur(k['CPOR'], 2),
                                'gop_vs_ppto': _variacion(k['GOP'], kp.get('GOP') if kp else None, 'rel', 1),
                                'cuadre': dif_h,
                                'desviaciones': sum(1 for x in desviaciones if x['hotel'] == nombre(h) and not x['favorable'])})
        cp = r.coste_por_room_night(datos.det_real, datos.act, cfg, hoteles, mes)
        if len(cp):
            for _, x in cp[cp['Alto']].iterrows():
                estructural.append({'hotel': nombre(x['Id hotel']), 'linea': x['Línea'],
                                    'valor': eur(x['Por room night'], 2), 'mediana': eur(x['Mediana otros'], 2),
                                    'exceso': eur(x['Exceso'])})

    # ---- alertas (máximo 5 en portada), con los 5 campos: qué, cuánto, dónde, umbral, periodo
    p_txt = mes_texto(mes)
    tol = c.parametro(cfg, 'tolerancia_cuadre_eur')
    umbral = f'{num(float(c.parametro(cfg, "umbral_desviacion_pct")) * 100)} % y {eur(c.parametro(cfg, "umbral_desviacion_eur"))}'
    alertas = []
    if len(diferencias) > 1:
        alertas.append({'prioridad': 1, 'impacto': 0, 'tipo': 'Cuadre', 'color': 'mal',
                        'que': f'{len(diferencias)} líneas de ingreso no cuadran',
                        'cuanto': f'{eur(importe_dif)} sumando las diferencias de cada línea',
                        'detalle': ' · '.join(f'{f["linea"]}' + (f' ({f["hotel"]})' if es_grupo else '') + f' {f["diferencia"]}'
                                              for f in diferencias),
                        'donde': 'Ingresos', 'umbral': f'tolerancia {eur(tol)}', 'periodo': p_txt, 'pagina': 'cuadre'})
    for f in diferencias[:1] if len(diferencias) == 1 else []:
        alertas.append({'prioridad': 1, 'impacto': 0, 'tipo': 'Cuadre', 'color': 'mal',
                        'que': f'{f["linea"]} no cuadra' + (f' · {f["hotel"]}' if es_grupo else ''),
                        'cuanto': f'{f["diferencia"]} (operador {f["operador"]}, contabilidad {f["contabilidad"]})',
                        'detalle': f['causa'], 'donde': 'Ingresos', 'umbral': f'tolerancia {eur(tol)}', 'periodo': p_txt,
                        'pagina': 'cuadre'})
    tol_r = f'tolerancia {num(float(c.parametro(cfg, "tolerancia_ratio_pct")) * 100, 1)} %'
    if len(ratios_mal) > 1:
        alertas.append({'prioridad': 2, 'impacto': 0, 'tipo': 'Ratio', 'color': 'aviso',
                        'que': f'{len(ratios_mal)} ratios del operador mal calculados',
                        'cuanto': ' · '.join(f'{x["ratio"]}' + (f' ({x["hotel"]})' if es_grupo else '') + f' {x["diferencia"]}'
                                             for x in ratios_mal),
                        'detalle': 'Revisar con el operador antes de usar sus ratios en ningún informe.',
                        'donde': 'Informe del operador', 'umbral': tol_r, 'periodo': p_txt, 'pagina': 'cuadre'})
    for x in ratios_mal[:1] if len(ratios_mal) == 1 else []:
        alertas.append({'prioridad': 2, 'impacto': 0, 'tipo': 'Ratio', 'color': 'aviso',
                        'que': f'{x["ratio"]} del operador mal calculado' + (f' · {x["hotel"]}' if es_grupo else ''),
                        'cuanto': f'reporta {x["operador"]}, recalculado {x["recalculado"]} ({x["diferencia"]})',
                        'detalle': x['nota'], 'donde': 'Informe del operador', 'umbral': tol_r, 'periodo': p_txt,
                        'pagina': 'cuadre'})
    for d in desviaciones:
        # Una desviación favorable solo es alerta si la explica una factura (p. ej. una factura que falta)
        if (d['favorable'] and not d['tiene_causa_factura']) or any(x['etiqueta'] == 'No cuadra' for x in d['causas']):
            continue
        alertas.append({'prioridad': 3 if d['tiene_causa_factura'] else 4, 'impacto': d['impacto'], 'tipo': 'Desviación',
                        'color': 'mal', 'que': f'{d["linea"]} {d["dif"]} frente al {d["referencia"]}' + (f' · {d["hotel"]}' if es_grupo else ''),
                        'cuanto': f'{d["var"]} (real {d["real"]})', 'detalle': d['causas'][0]['texto'],
                        'donde': d['linea'], 'umbral': umbral, 'periodo': f'{p_txt} frente al {d["referencia"]}',
                        'pagina': 'desviaciones'})
    for e in estructural:
        alertas.append({'prioridad': 4, 'impacto': 0, 'tipo': 'Comparativa', 'color': 'aviso',
                        'que': f'{e["linea"]} cara · {e["hotel"]}', 'cuanto': f'{e["valor"]} por room night frente a {e["mediana"]} en el resto',
                        'detalle': f'Unos {e["exceso"]} al mes por encima de los otros hoteles: coste estructural, no una factura puntual.',
                        'donde': e['linea'], 'umbral': '+20 % sobre la mediana de los otros hoteles', 'periodo': 'últimos 3 meses',
                        'pagina': 'comparativa'})
    alertas.sort(key=lambda a: (a['prioridad'], -a['impacto']))

    # ---- frases de resumen (plantillas fijas con cifras calculadas)
    frases = []
    if k_real and k_aa:
        v_ing = _variacion(k_real['Ingresos totales'], k_aa['Ingresos totales'], 'rel', 1)
        v_gop = _variacion(k_real['% GOP'], k_aa['% GOP'], 'pp', 1)
        if v_ing and v_gop:
            nexo = 'y' if (v_ing['estado'] == v_gop['estado']) else 'pero'
            frases.append(f'Los ingresos {"suben" if v_ing["flecha"] == "▲" else "bajan"} un <b>{v_ing["texto"].lstrip("+−")}</b> '
                          f'frente al mismo periodo del año anterior, {nexo} el % GOP {"sube" if v_gop["flecha"] == "▲" else "baja"} '
                          f'<b>{v_gop["texto"].lstrip("+−")}</b> hasta el {pct(k_real["% GOP"])}.')
    if k_real and k_ppto:
        v_o = _variacion(k_real['Ocupación'], k_ppto['Ocupación'], 'pp', 1)
        v_a = _variacion(k_real['ADR'], k_ppto['ADR'], 'rel', 1)
        if v_o and v_a:
            frases.append(f'Frente al presupuesto, la ocupación ({pct(k_real["Ocupación"])}) va <b>{v_o["texto"]}</b> '
                          f'y el ADR ({eur(k_real["ADR"], 2)}) <b>{v_a["texto"]}</b>.')
    if diferencias:
        frases.append(f'El cuadre con contabilidad tiene <b>{len(diferencias)} diferencia{"s" if len(diferencias) > 1 else ""}</b> '
                      f'por {eur(importe_dif)} en total. Hay que corregirlas antes de dar el mes por cerrado.')
    elif modo == 'mes':
        frases.append('El informe del operador <b>cuadra</b> con la contabilidad en todas las líneas de ingreso.')

    titulo = 'Todo el grupo' if es_grupo else nombre(hoteles[0])
    habitaciones = int(cfg['hoteles'].set_index('Id hotel').loc[hoteles, 'Habitaciones'].sum())
    return {
        'titulo': titulo, 'es_grupo': es_grupo, 'habitaciones': habitaciones,
        'mes': mes, 'mes_texto': p_txt, 'modo': modo,
        'periodo_texto': p_txt if modo == 'mes' else f'enero-{MESES[mes.month - 1]} {mes.year}',
        'hay_ppto': hay_ppto,
        'tarjetas_portada': tarjetas('portada', k_real, k_ppto, k_aa),
        'tarjetas_ventas': tarjetas('ventas', k_real, k_ppto, k_aa),
        'tarjetas_resultados': tarjetas('resultados', k_real, k_ppto, k_aa),
        'graficos': {**graficos, 'cascada': cascada, 'coste_rn': coste_rn},
        'pyg': pyg, 'ingresos': ingresos,
        'cuadre': cuadre_filas, 'diferencias': diferencias, 'importe_diferencias': eur(importe_dif),
        'ratios': ratios, 'ratios_mal': ratios_mal,
        'desviaciones': desviaciones, 'falsas_alarmas': falsas,
        'comparativa': comparativa, 'estructural': estructural,
        'alertas': alertas[:MAX_ALERTAS_PORTADA], 'total_alertas': len(alertas),
        'frases': frases,
    }
