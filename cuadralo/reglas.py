"""Cuádralo · motor de desviaciones (reglas deterministas, versionadas).

Una línea de la cuenta de resultados es desviación si se mueve más de umbral_desviacion_pct y más de
umbral_desviacion_eur frente al presupuesto o al mismo mes del año anterior. Para cada desviación se
busca la causa en los apuntes contables del mes:

- duplicada:         mismo proveedor e importe con fechas de emisión cercanas
- otro mes:          la fecha de emisión es de un mes anterior al de registro
- proveedor nuevo:   sin apuntes en ese hotel en los 12 meses anteriores
- factura que falta: proveedor que factura todos los meses y este mes no
- subida de precio:  coste por unidad de actividad muy por encima de su mediana y del año anterior
- cuadre:            (ingresos) la línea no cuadra entre operador y contabilidad
- actividad:         (ingresos) volumen y precio frente a la referencia
- falsa alarma:      (gastos variables) la diferencia se explica por la actividad

Ninguna cifra la escribe la IA: este módulo solo calcula. Los textos son plantillas fijas.
"""
import pandas as pd

from .calculos import _div, asignar_lineas, lineas_detalle, parametro

VERSION_REGLAS = '2026.11.1'

DIAS_DUPLICADA = 7
SUBIDA_MIN = 0.15          # +15 % sobre la mediana de los 6 meses anteriores y sobre el año anterior
MESES_RECURRENTE = 3       # factura que falta: el proveedor facturó en cada uno de los 3 meses anteriores
ESTRUCTURAL_MIN = 0.20     # comparativa: +20 % por room night sobre la mediana de los otros hoteles
LINEAS_POR_DESAYUNO = {'Consumo desayunos', 'Personal desayunos'}
LINEAS_POR_ALOJAMIENTO = {'Comisiones canales'}   # se mueven con los ingresos de alojamiento, no con las noches


def _clave_base(linea):
    """Unidad de actividad con la que se mueve un gasto variable (misma columna en real y presupuesto)."""
    if linea in LINEAS_POR_DESAYUNO:
        return 'Desayunos (unidades)', 'desayunos'
    if linea in LINEAS_POR_ALOJAMIENTO:
        return 'Alojamiento', 'ingresos de alojamiento'
    return 'Room nights', 'room nights'


def _ref(df, clave, linea):
    if df is None or len(df) == 0 or clave not in df.index or linea not in df.columns:
        return None
    return float(df.loc[clave, linea])


def _supera(d, ref, pct, eur):
    if ref is None or abs(d) <= eur:
        return False
    return ref == 0 or abs(d / ref) > pct


def _bloques(cfg):
    est = cfg['estructura_informe']
    return dict(zip(est['Línea'], est['Bloque']))


def _variables(cfg):
    pc = cfg['plan_cuentas']
    return set(pc[pc['Tipo de coste'] == 'variable']['Línea del informe'])


def _base(linea, act_fila):
    if act_fila is None:
        return None
    return float(act_fila[_clave_base(linea)[0]])


def _causas_gasto(apuntes_mes, historico, h, linea, mes, act):
    """Busca la causa de una desviación de gasto en los apuntes del mes. Devuelve una lista de causas."""
    causas, usados = [], set()

    # 1) Duplicada: mismo proveedor e importe, emitidas con DIAS_DUPLICADA días o menos de diferencia
    for (prov, imp), grupo in apuntes_mes.groupby(['Proveedor', 'Importe sin IVA']):
        if len(grupo) < 2 or imp <= 0:
            continue
        g = grupo.sort_values('Fecha de emisión del documento')
        fechas = pd.to_datetime(g['Fecha de emisión del documento'])
        cerca = fechas.diff().dt.days <= DIAS_DUPLICADA
        repetidas = g[cerca | cerca.shift(-1, fill_value=False)]
        if len(repetidas) < 2:
            continue
        externos = repetidas['Nº documento externo'].fillna('').astype(str).str.replace(r'[^0-9A-Za-z]', '', regex=True)
        mismo_externo = externos.nunique() == 1 and externos.iloc[0] != ''
        causas.append({'tipo': 'Duplicada', 'proveedor': prov, 'documento': ' y '.join(repetidas['Nº documento']),
                       'importe': float(imp) * (len(repetidas) - 1),
                       'texto': f'{len(repetidas)} facturas de {prov} por el mismo importe emitidas el '
                                + ' y el '.join(f'{x:%d/%m}' for x in pd.to_datetime(repetidas['Fecha de emisión del documento']))
                                + (', con el mismo nº de factura del proveedor' if mismo_externo else '')})
        usados.update(repetidas.index[1:])

    # 2) Factura de otro mes
    otro_mes = apuntes_mes[pd.to_datetime(apuntes_mes['Fecha de emisión del documento']).dt.to_period('M')
                           < pd.Period(mes, 'M')]
    for idx, a in otro_mes.iterrows():
        causas.append({'tipo': 'Otro mes', 'proveedor': a['Proveedor'], 'documento': a['Nº documento'],
                       'importe': float(a['Importe sin IVA']),
                       'texto': f'Factura emitida el {a["Fecha de emisión del documento"]:%d/%m/%Y} y registrada el '
                                f'{a["Fecha de registro"]:%d/%m/%Y}: pertenece a otro mes'})
        usados.add(idx)

    # 3) Proveedor nuevo en el hotel
    hace_un_anio = mes - pd.DateOffset(months=12)
    previos = historico[(historico['Id hotel'] == h) & (historico['Mes'] < mes) & (historico['Mes'] >= hace_un_anio)]
    conocidos = set(previos['Proveedor'])
    for prov, grupo in apuntes_mes[~apuntes_mes['Proveedor'].isin(conocidos)].groupby('Proveedor'):
        causas.append({'tipo': 'Proveedor nuevo', 'proveedor': prov, 'documento': ', '.join(grupo['Nº documento']),
                       'importe': float(grupo['Importe sin IVA'].sum()),
                       'texto': f'{prov} no tiene apuntes en este hotel en los 12 meses anteriores'})
        usados.update(grupo.index)

    # 4) Factura que falta: proveedor que facturó esta línea en cada uno de los meses anteriores
    linea_hist = historico[(historico['Id hotel'] == h) & (historico['Línea'] == linea)]
    meses_prev = [mes - pd.DateOffset(months=i) for i in range(1, MESES_RECURRENTE + 1)]
    por_prov = linea_hist[linea_hist['Mes'].isin(meses_prev)].groupby('Proveedor')['Mes'].nunique()
    for prov in por_prov[por_prov == MESES_RECURRENTE].index:
        if prov in set(apuntes_mes['Proveedor']):
            continue
        hist = linea_hist[(linea_hist['Proveedor'] == prov) & linea_hist['Mes'].isin(meses_prev)]
        importe = float(hist.groupby('Mes')['Importe sin IVA'].sum().median())
        causas.append({'tipo': 'Factura que falta', 'proveedor': prov, 'documento': '',
                       'importe': -importe,
                       'texto': f'{prov} factura todos los meses (unos {importe:,.0f} €) y este mes no hay ningún apunte'
                                .replace(',', '.')})

    # 5) Subida de precio: coste por unidad de actividad (room night o desayuno)
    restantes = apuntes_mes.drop(index=[i for i in usados if i in apuntes_mes.index])
    for prov, grupo in restantes.groupby('Proveedor'):
        if prov not in conocidos:
            continue
        serie = linea_hist[linea_hist['Proveedor'] == prov].groupby('Mes')['Importe sin IVA'].sum()
        base_mes = _base(linea, act.loc[(h, mes)]) if (h, mes) in act.index else None
        if not base_mes:
            continue
        unit = {}
        for m_, v in serie.items():
            if (h, m_) in act.index:
                b = _base(linea, act.loc[(h, m_)])
                if b:
                    unit[m_] = v / b
        actual = float(grupo['Importe sin IVA'].sum()) / base_mes
        previos6 = [unit[m_] for m_ in unit if mes - pd.DateOffset(months=6) <= m_ < mes]
        anio_ant = unit.get(mes - pd.DateOffset(months=12))
        if len(previos6) < 4:
            continue
        mediana = float(pd.Series(previos6).median())
        sube = _div(actual - mediana, mediana)
        sube_aa = _div(actual - anio_ant, anio_ant) if anio_ant else None
        if sube is None or sube <= SUBIDA_MIN or (sube_aa is not None and sube_aa <= SUBIDA_MIN):
            continue
        # Desde cuándo: primer mes de los 3 anteriores que ya estaba por encima de la base de hace 4-6 meses
        base_antigua = [unit[m_] for m_ in unit if mes - pd.DateOffset(months=6) <= m_ <= mes - pd.DateOffset(months=4)]
        desde = mes
        if base_antigua:
            ref = float(pd.Series(base_antigua).median())
            for i in range(3, 0, -1):
                m_ = mes - pd.DateOffset(months=i)
                if m_ in unit and unit[m_] > ref * (1 + SUBIDA_MIN):
                    desde = m_
                    break
            sube = _div(actual - ref, ref)
        else:
            ref = mediana
        unidad = 'desayuno' if linea in LINEAS_POR_DESAYUNO else 'room night'
        causas.append({'tipo': 'Subida de precio', 'proveedor': prov, 'documento': ', '.join(grupo['Nº documento']),
                       'importe': (actual - ref) * base_mes, 'desde': desde, 'subida': sube,
                       'texto': f'{prov} cuesta un {sube * 100:.0f} % más por {unidad} que antes'.replace('.', ',')})
    return causas


def desviaciones(mov, det_real, det_ppto, act, cuadre, cfg, hoteles, mes, hist=None):
    """Desviaciones de un mes para los hoteles indicados, con su causa. Una fila por hotel y línea."""
    pct = float(parametro(cfg, 'umbral_desviacion_pct'))
    eur = float(parametro(cfg, 'umbral_desviacion_eur'))
    bloques, variables = _bloques(cfg), _variables(cfg)
    hist = asignar_lineas(mov, cfg) if hist is None else hist  # se puede pasar ya calculado
    aa = mes - pd.DateOffset(months=12)
    filas = []
    for h in hoteles:
        if (h, mes) not in det_real.index:
            continue
        apuntes_hotel = hist[(hist['Id hotel'] == h) & (hist['Mes'] == mes)]
        for linea in lineas_detalle(cfg):
            real = _ref(det_real, (h, mes), linea) or 0.0
            ppto = _ref(det_ppto, (h, mes), linea)
            anterior = _ref(det_real, (h, aa), linea)
            d_ppto = real - ppto if ppto is not None else None
            d_aa = real - anterior if anterior is not None else None
            vs_ppto = d_ppto is not None and _supera(d_ppto, ppto, pct, eur)
            vs_aa = d_aa is not None and _supera(d_aa, anterior, pct, eur)
            if not (vs_ppto or vs_aa):
                continue
            ingreso = bloques.get(linea) == 'Ingresos'
            d_ref, ref, referencia = (d_ppto, ppto, 'presupuesto') if vs_ppto else (d_aa, anterior, 'año anterior')
            causas = []
            if ingreso:
                if (h, mes, linea) in cuadre.index and not cuadre.loc[(h, mes, linea), 'Cuadra']:
                    c = cuadre.loc[(h, mes, linea)]
                    causas.append({'tipo': 'Cuadre', 'proveedor': '', 'documento': c['Documento'],
                                   'importe': -float(c['Diferencia']), 'hotel_relacionado': c['Hotel relacionado'],
                                   'causa_cuadre': c['Causa'], 'texto': ''})
                elif linea == 'Alojamiento' and (h, mes) in act.index:
                    a = act.loc[(h, mes)]
                    rn_ref = _ref(det_ppto, (h, mes), 'Room nights') if vs_ppto else (
                        float(act.loc[(h, aa), 'Room nights']) if (h, aa) in act.index else None)
                    if rn_ref:
                        adr, adr_ref = _div(a['Alojamiento'], a['Room nights']), _div(ref, rn_ref)
                        causas.append({'tipo': 'Actividad', 'proveedor': '', 'documento': '', 'importe': d_ref,
                                       'var_cantidad': _div(a['Room nights'] - rn_ref, rn_ref), 'cantidad': 'room nights',
                                       'var_precio': _div(adr - adr_ref, adr_ref) if adr_ref else None, 'precio': 'ADR'})
                elif linea == 'Desayunos' and (h, mes) in act.index:
                    a = act.loc[(h, mes)]
                    q_ref = _ref(det_ppto, (h, mes), 'Desayunos (unidades)') if vs_ppto else (
                        float(act.loc[(h, aa), 'Desayunos (unidades)']) if (h, aa) in act.index else None)
                    if q_ref:
                        pm, pm_ref = _div(a['Ingresos desayunos'], a['Desayunos (unidades)']), _div(ref, q_ref)
                        causas.append({'tipo': 'Actividad', 'proveedor': '', 'documento': '', 'importe': d_ref,
                                       'var_cantidad': _div(a['Desayunos (unidades)'] - q_ref, q_ref), 'cantidad': 'desayunos servidos',
                                       'var_precio': _div(pm - pm_ref, pm_ref) if pm_ref else None, 'precio': 'precio medio'})
                if not causas:
                    causas.append({'tipo': 'Ventas', 'proveedor': '', 'documento': '', 'importe': d_ref})
            else:
                apuntes = apuntes_hotel[apuntes_hotel['Línea'] == linea]
                causas = _causas_gasto(apuntes, hist, h, linea, mes, act)
                if not causas and linea in variables and (h, mes) in act.index:
                    clave, unidad = _clave_base(linea)
                    base_real = _base(linea, act.loc[(h, mes)])
                    if vs_ppto:
                        base_ref = _ref(det_ppto, (h, mes), clave)
                    else:
                        base_ref = _base(linea, act.loc[(h, aa)]) if (h, aa) in act.index else None
                    if base_ref:
                        esperado = ref * base_real / base_ref
                        if not _supera(real - esperado, esperado, pct, eur):
                            causas.append({'tipo': 'Falsa alarma', 'proveedor': '', 'documento': '', 'importe': d_ref,
                                           'var_base': _div(base_real - base_ref, base_ref), 'unidad': unidad,
                                           'texto': ''})
                if not causas and real == 0:
                    causas.append({'tipo': 'Sin apuntes', 'proveedor': '', 'documento': '', 'importe': d_ref, 'texto': ''})
            filas.append({
                'Id hotel': h, 'Línea': linea, 'Bloque': bloques.get(linea), 'Ingreso': ingreso,
                'Real': real, 'Presupuesto': ppto, 'Año anterior': anterior,
                'Dif ppto': d_ppto, 'Dif AA': d_aa, 'Var ppto': _div(d_ppto, ppto) if ppto else None,
                'Var AA': _div(d_aa, anterior) if anterior else None,
                'Referencia': referencia, 'Dif ref': d_ref,
                'Favorable': (d_ref > 0) == ingreso,
                'Causas': causas,
                'Falsa alarma': bool(causas) and all(c['tipo'] == 'Falsa alarma' for c in causas),
                'Con causa': any(c['tipo'] not in ('Sin apuntes',) for c in causas),
                'Versión reglas': VERSION_REGLAS,
            })
    return filas


def coste_por_room_night(det_real, act, cfg, hoteles, mes, meses=3):
    """Coste por room night de cada partida operativa y hotel (mediana de los últimos `meses` meses).

    Se usa la mediana de varios meses para que un gasto puntual (una avería, una factura de otro mes)
    no parezca un coste estructural. Aviso si supera en ESTRUCTURAL_MIN la mediana de los otros hoteles.
    """
    est = cfg['estructura_informe']
    lineas = est[(est['Bloque'] == 'Otros gastos operativos') & (est['Tipo'] == 'Detalle')]['Línea'].tolist()
    periodo = [mes - pd.DateOffset(months=i) for i in range(meses)]
    eur = float(parametro(cfg, 'umbral_desviacion_eur'))
    filas = []
    for linea in lineas:
        valores, rn_mes = {}, {}
        for h in hoteles:
            claves = [(h, m) for m in periodo if (h, m) in det_real.index and (h, m) in act.index
                      and float(act.loc[(h, m), 'Room nights']) > 0]
            if not claves or (h, mes) not in act.index:
                continue
            # Mediana de los costes mensuales por room night: un gasto puntual no la mueve
            valores[h] = float(pd.Series([(_ref(det_real, k, linea) or 0.0) / float(act.loc[k, 'Room nights'])
                                          for k in claves]).median())
            rn_mes[h] = float(act.loc[(h, mes), 'Room nights'])
        for h, v in valores.items():
            otros = [x for k, x in valores.items() if k != h and x > 0]
            mediana = float(pd.Series(otros).median()) if otros else None
            exceso = (v - mediana) * rn_mes[h] if mediana else None
            alto = bool(mediana) and v > mediana * (1 + ESTRUCTURAL_MIN) and exceso > eur
            filas.append({'Id hotel': h, 'Línea': linea, 'Por room night': v, 'Mediana otros': mediana,
                          'Exceso': exceso, 'Alto': alto})
    return pd.DataFrame(filas)
