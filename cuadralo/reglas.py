"""Cuádralo · motor de reglas deterministas (paso 3).

Todo lo que se detecta aquí sale de reglas con parámetros de la configuración del cliente (hoja parametros).
Los textos explicativos son frases plantilla; en el paso 5 Azure OpenAI solo los redactará mejor,
a partir de estos mismos resultados, sin cambiar ninguna cifra.

Cuatro bloques:
  1. cuadre()               operador frente a Business Central, por línea de ingreso, con la causa.
  2. comprobar_ratios()     ADR, ocupación y captación del operador frente a los recalculados.
  3. alertas_facturas()     duplicada, otro mes, proveedor nuevo, subida de precio, factura que falta.
  4. comparativa_hoteles()  coste estructural alto por room night frente al resto de hoteles.
  5. desviaciones()         líneas que se mueven más de un X % y X € frente a presupuesto o año anterior,
                            con la causa: una alerta de factura, la actividad (falsa alarma) o sin causa.
"""
import numpy as np
import pandas as pd

from .calculos import actividad, parametro

VERSION_REGLAS = '2026.11.1'

# Valores por defecto si la configuración del cliente no los trae (se pueden sobrescribir en la hoja parametros).
POR_DEFECTO = {
    'umbral_desviacion_pct': 0.05,
    'umbral_desviacion_eur': 500,
    'tolerancia_cuadre_eur': 1,
    'tolerancia_ratio_pct': 0.005,
    'dias_duplicado': 7,
    'umbral_subida_precio_pct': 0.15,
    'meses_proveedor_nuevo': 12,
    'importe_minimo_alerta_eur': 500,
    'umbral_comparativa_pct': 0.20,
}

# Qué actividad explica cada línea de coste variable (para comparar coste por unidad).
UNIDAD_SINGULAR = {
    'Room nights': 'room night', 'Desayunos servidos': 'desayuno servido',
    'Ingresos alojamiento': '€ de ingresos de alojamiento', 'Ingresos restauración': '€ de ingresos de restauración',
    'Ingresos totales': '€ de ingresos',
}

DRIVER_LINEA = {
    'Consumo desayunos': 'Desayunos servidos',
    'Consumo restauración': 'Ingresos restauración',
    'Comisiones canales': 'Ingresos alojamiento',
    'Amenities': 'Room nights',
    'Lavandería': 'Room nights',
    'Limpieza': 'Room nights',
    'Personal desayunos': 'Desayunos servidos',
}


def p(cfg, nombre):
    try:
        return float(parametro(cfg, nombre))
    except KeyError:
        return float(POR_DEFECTO[nombre])


def _eur(x):
    texto = f'{abs(x):,.2f}'.replace(',', '§').replace('.', ',').replace('§', '.')
    return f'{"-" if x < 0 else ""}{texto} €'


def _num(x, decimales=2):
    texto = f'{x:,.{decimales}f}'
    return texto.replace(',', '§').replace('.', ',').replace('§', '.')


def _pct(x, signo=False, decimales=1):
    texto = f'{x * 100:{"+" if signo else ""}.{decimales}f}'.replace('.', ',')
    return f'{texto} %'


def _mes(ts):
    meses = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
             'septiembre', 'octubre', 'noviembre', 'diciembre']
    return f'{meses[ts.month - 1]} {ts.year}'


def _serie_operador(pms, concepto, medida):
    s = pms[(pms['Concepto'] == concepto) & (pms['Medida'] == medida)].copy()
    s['Mes'] = pd.to_datetime(s['Fecha']).dt.to_period('M').dt.to_timestamp()
    return s.set_index(['Id hotel', 'Mes'])['Valor']


def drivers(pms):
    """Actividad por hotel y mes que sirve para comparar costes por unidad."""
    terraza = _serie_operador(pms, 'Terraza', 'Importe')
    eventos = _serie_operador(pms, 'Eventos', 'Importe')
    return pd.DataFrame({
        'Room nights': _serie_operador(pms, 'Room nights', 'Cantidad'),
        'Desayunos servidos': _serie_operador(pms, 'Desayunos', 'Cantidad'),
        'Ingresos alojamiento': _serie_operador(pms, 'Alojamiento', 'Importe'),
        'Ingresos restauración': terraza.add(eventos, fill_value=0),
    })


# ---------------------------------------------------------------- 1. Cuadre

def cuadre(m, pms, cfg, mes):
    """Por hotel y línea de ingreso: importe del operador − importe en Business Central, con la causa."""
    mes = pd.Timestamp(mes)
    tol = p(cfg, 'tolerancia_cuadre_eur')
    op = pms[(pms['Medida'] == 'Importe') & pms['Línea del informe'].notna() & (pms['Línea del informe'] != '')].copy()
    op['Mes'] = pd.to_datetime(op['Fecha']).dt.to_period('M').dt.to_timestamp()
    op = op[op['Mes'] == mes].groupby(['Id hotel', 'Línea del informe'])['Valor'].sum()
    lineas = set(op.index.get_level_values(1))
    bc_mov = m[(m['Mes'] == mes) & m['Línea'].isin(lineas)]
    bc = bc_mov.groupby(['Id hotel', 'Línea'])['Importe sin IVA'].sum()
    bc.index.names = op.index.names
    t = pd.DataFrame({'Operador': op, 'Business Central': bc}).fillna(0.0)
    t['Diferencia'] = (t['Operador'] - t['Business Central']).round(2)
    t['Cuadra'] = t['Diferencia'].abs() <= tol
    t['Causa'] = ''
    t['Detalle'] = ''
    t['Documento'] = ''
    for (hotel, linea), fila in t[~t['Cuadra']].iterrows():
        dif = fila['Diferencia']
        # a) contabilizado en otra finca: otro hotel tiene la diferencia contraria en la misma línea
        espejo = t[(t.index.get_level_values(1) == linea) & (t.index.get_level_values(0) != hotel)
                   & ((t['Diferencia'] + dif).abs() <= tol)]
        abonos = bc_mov[(bc_mov['Id hotel'] == hotel) & (bc_mov['Línea'] == linea)
                        & ((bc_mov['Importe sin IVA'] + dif).abs() <= tol)]
        if len(espejo):
            otro = espejo.index[0][0]
            causa = 'Ingreso contabilizado en otra finca'
            detalle = (f'El operador reporta {_eur(fila["Operador"])} de {linea.lower()}, pero en contabilidad '
                       f'el importe está en la finca del hotel {otro}.' if dif > 0 else
                       f'Contabilidad tiene {_eur(-dif)} de {linea.lower()} que el operador reporta en el hotel {otro}.')
        elif dif > 0 and len(abonos):
            causa = 'Abono no reportado por el operador'
            a = abonos.iloc[0]
            detalle = (f'Abono de {_eur(-a["Importe sin IVA"])} en contabilidad ({a["Nº documento"]}, '
                       f'{a["Descripción"]}) que no aparece en el informe del operador.')
            t.loc[(hotel, linea), 'Documento'] = a['Nº documento']
        elif dif > 0:
            causa = 'Ingreso sin contabilizar'
            detalle = (f'El operador reporta {_eur(fila["Operador"])} de {linea.lower()} y en contabilidad solo hay '
                       f'{_eur(fila["Business Central"])}: faltan {_eur(dif)} por contabilizar.')
        else:
            causa = 'Ingreso contabilizado que el operador no reporta'
            detalle = (f'Contabilidad tiene {_eur(-dif)} más de {linea.lower()} que el informe del operador.')
        t.loc[(hotel, linea), 'Causa'] = causa
        t.loc[(hotel, linea), 'Detalle'] = detalle
    return t.reset_index().rename(columns={'Línea del informe': 'Línea'})


# ---------------------------------------------------------------- 2. Ratios del operador

def comprobar_ratios(pms, cfg, mes):
    mes = pd.Timestamp(mes)
    tol = p(cfg, 'tolerancia_ratio_pct')
    act = actividad(pms, cfg)

    def op(concepto):
        return _serie_operador(pms, concepto, 'Ratio del operador')

    rn = _serie_operador(pms, 'Room nights', 'Cantidad')
    des = _serie_operador(pms, 'Desayunos', 'Cantidad')
    pax = op('Pax x room')
    filas = []
    for hotel in act.xs(mes, level='Mes').index:
        k = (hotel, mes)
        adr_calc = act.loc[k, 'ADR']
        cap_pers = des[k] / (rn[k] * pax[k])
        cap_hab = des[k] / rn[k]
        comprobaciones = [
            ('ADR', op('ADR')[k], adr_calc, abs(op('ADR')[k] / adr_calc - 1) > tol,
             'Ingresos de alojamiento / room nights'),
            ('Ocupación', op('Ocupación')[k], act.loc[k, 'Ocupación'], abs(op('Ocupación')[k] - act.loc[k, 'Ocupación']) > tol,
             'Room nights / (habitaciones × días del mes)'),
            ('Captación desayuno', op('Captación desayuno')[k], cap_pers, abs(op('Captación desayuno')[k] - cap_pers) > tol,
             'Desayunos / (room nights × pax por habitación)'),
        ]
        for ratio, valor_op, valor_calc, mal, formula in comprobaciones:
            detalle = ''
            if mal:
                if ratio == 'Captación desayuno' and abs(valor_op - cap_hab) <= tol:
                    detalle = (f'El operador calcula la captación sobre habitaciones ({_pct(valor_op)}) y no sobre '
                               f'personas ({_pct(valor_calc)}).')
                elif ratio == 'ADR':
                    detalle = (f'El ADR reportado ({_num(valor_op)} €) es un {_pct(valor_op / valor_calc - 1)} distinto de '
                               f'ingresos / room nights ({_num(valor_calc)} €).')
                else:
                    detalle = f'El operador reporta {_num(valor_op, 4)} y el recalculado es {_num(valor_calc, 4)}.'
            filas.append({'Id hotel': hotel, 'Ratio': ratio, 'Operador': valor_op, 'Recalculado': valor_calc,
                          'Correcto': not mal, 'Fórmula': formula, 'Detalle': detalle})
    return pd.DataFrame(filas)


# ---------------------------------------------------------------- 3. Alertas de facturas

def _gastos(m):
    return m[m['Cuenta contable'].astype(str).str.startswith('6')]


def alertas_facturas(m, pms, cfg, mes):
    mes = pd.Timestamp(mes)
    g = _gastos(m).copy()
    g['Emisión'] = pd.to_datetime(g['Fecha de emisión del documento'])
    minimo = p(cfg, 'importe_minimo_alerta_eur')
    alertas = []

    def alerta(tipo, fila, detalle, importe=None):
        alertas.append({'Tipo': tipo, 'Id hotel': fila['Id hotel'], 'Línea': fila['Línea'],
                        'Proveedor': fila['Proveedor'], 'Documento': fila.get('Nº documento', ''),
                        'Importe': importe if importe is not None else fila.get('Importe sin IVA', np.nan),
                        'Detalle': detalle})

    del_mes = g[g['Mes'] == mes]

    # Duplicada: mismo proveedor, hotel, cuenta, ceco e importe, emitidas con pocos días de diferencia.
    dias = p(cfg, 'dias_duplicado')
    duplicados = set()
    for _, s in g.groupby(['Proveedor', 'Id hotel', 'Cuenta contable', 'Ceco', 'Importe sin IVA'], dropna=False):
        if len(s) < 2:
            continue
        s = s.sort_values('Emisión')
        separacion = s['Emisión'].diff().dt.days
        for i in np.where(separacion <= dias)[0]:
            fila, anterior = s.iloc[i], s.iloc[i - 1]
            if fila['Mes'] != mes:
                continue
            duplicados.add(fila['Nº documento'])
            alerta('Factura duplicada', fila,
                   f'{fila["Proveedor"]}: dos facturas de {_eur(fila["Importe sin IVA"])} emitidas el '
                   f'{anterior["Emisión"]:%d/%m/%Y} ({anterior["Nº documento"]}) y el {fila["Emisión"]:%d/%m/%Y} '
                   f'({fila["Nº documento"]}). Posible duplicado.')

    # Otro mes: la fecha de emisión es de un mes distinto al de registro.
    otro = del_mes[del_mes['Emisión'].dt.to_period('M') != del_mes['Mes'].dt.to_period('M')]
    for _, fila in otro.iterrows():
        alerta('Factura en otro mes', fila,
               f'{fila["Proveedor"]}: factura emitida el {fila["Emisión"]:%d/%m/%Y} y registrada en {_mes(mes)} '
               f'({fila["Nº documento"]}, {_eur(fila["Importe sin IVA"])}). Corresponde a {_mes(fila["Emisión"])}.')

    # Proveedor nuevo: sin apuntes en todo el grupo en los meses anteriores.
    meses_nuevo = int(p(cfg, 'meses_proveedor_nuevo'))
    desde = mes - pd.DateOffset(months=meses_nuevo)
    previos = set(g[(g['Mes'] >= desde) & (g['Mes'] < mes)]['Proveedor'])
    for prov, s in del_mes.groupby('Proveedor'):
        if prov in previos or s['Importe sin IVA'].sum() < minimo:
            continue
        for _, fila in s.iterrows():
            alerta('Proveedor nuevo', fila,
                   f'{prov} no tenía facturas en los últimos {meses_nuevo} meses. Factura {fila["Nº documento"]} de '
                   f'{_eur(fila["Importe sin IVA"])} ({fila["Descripción"]}).')

    # Subida de precio: coste por unidad de actividad de un proveedor, 3 meses seguidos por encima del año anterior.
    umbral = p(cfg, 'umbral_subida_precio_pct')
    act = drivers(pms)
    sin_dup = g[~g['Nº documento'].isin(duplicados)]
    por_prov = sin_dup.groupby(['Proveedor', 'Id hotel', 'Línea', 'Mes'])['Importe sin IVA'].sum()
    for (prov, hotel, linea), s in por_prov.groupby(level=[0, 1, 2]):
        if linea not in DRIVER_LINEA or hotel not in act.index.get_level_values(0):
            continue
        unidad = (s.droplevel([0, 1, 2]) / act[DRIVER_LINEA[linea]].xs(hotel)).replace([np.inf, -np.inf], np.nan).dropna()
        meses = [mes - pd.DateOffset(months=i) for i in range(3)]
        try:
            cambios = [unidad[x] / unidad[x - pd.DateOffset(years=1)] - 1 for x in meses]
        except KeyError:
            continue
        if all(c > umbral for c in cambios):
            alertas.append({'Tipo': 'Subida de precio', 'Id hotel': hotel, 'Línea': linea, 'Proveedor': prov,
                            'Documento': '', 'Importe': float(s.droplevel([0, 1, 2]).get(mes, np.nan)),
                            'Detalle': (f'{prov}: el coste por {UNIDAD_SINGULAR[DRIVER_LINEA[linea]]} lleva 3 meses por encima del '
                                        f'año anterior ({_pct(cambios[2], signo=True, decimales=0)}, {_pct(cambios[1], signo=True, decimales=0)} y {_pct(cambios[0], signo=True, decimales=0)}).')})

    # Factura que falta: proveedor recurrente (5 de los 6 meses anteriores) sin factura este mes.
    previos6 = [mes - pd.DateOffset(months=i) for i in range(1, 7)]
    for (prov, hotel, cuenta, linea), s in g.groupby(['Proveedor', 'Id hotel', 'Cuenta contable', 'Línea']):
        meses = set(s['Mes'])
        if sum(x in meses for x in previos6) >= 5 and mes not in meses:
            media = s[s['Mes'].isin(previos6)].groupby('Mes')['Importe sin IVA'].sum().mean()
            alertas.append({'Tipo': 'Falta una factura', 'Id hotel': hotel, 'Línea': linea, 'Proveedor': prov,
                            'Documento': '', 'Importe': -media,
                            'Detalle': (f'{prov} factura todos los meses (media de {_eur(media)}) y no hay ninguna '
                                        f'factura en {_mes(mes)}.')})
    return pd.DataFrame(alertas, columns=['Tipo', 'Id hotel', 'Línea', 'Proveedor', 'Documento', 'Importe', 'Detalle'])


# ---------------------------------------------------------------- 4. Comparativa entre hoteles

def comparativa_hoteles(m, pms, cfg, mes, meses_ventana=3):
    """Coste por unidad de actividad de cada línea variable (últimos 3 meses) frente a la mediana del grupo."""
    mes = pd.Timestamp(mes)
    umbral = p(cfg, 'umbral_comparativa_pct')
    act = drivers(pms)
    inicio = mes - pd.DateOffset(months=meses_ventana - 1)
    ventana = m[(m['Mes'] >= inicio) & (m['Mes'] <= mes)]
    act_v = act[(act.index.get_level_values('Mes') >= inicio) & (act.index.get_level_values('Mes') <= mes)].groupby(level=0).sum()
    filas = []
    for linea, driver in DRIVER_LINEA.items():
        coste = ventana[ventana['Línea'] == linea].groupby('Id hotel')['Importe sin IVA'].sum()
        if coste.empty:
            continue
        unidad = (coste / act_v[driver]).dropna()
        if len(unidad) < 3:
            continue
        mediana = unidad.median()
        for hotel, valor in unidad.items():
            filas.append({'Línea': linea, 'Id hotel': hotel, 'Unidad': driver, 'Coste por unidad': valor,
                          'Mediana grupo': mediana, 'Diferencia %': valor / mediana - 1,
                          'Alerta': valor / mediana - 1 > umbral})
    t = pd.DataFrame(filas)
    if len(t):
        t['Detalle'] = np.where(
            t['Alerta'],
            t.apply(lambda r: (f'{r["Línea"]}: {_num(r["Coste por unidad"])} € por {UNIDAD_SINGULAR[r["Unidad"]]} en los últimos '
                               f'{meses_ventana} meses, frente a {_num(r["Mediana grupo"])} € de mediana del grupo '
                               f'({_pct(r["Diferencia %"], signo=True, decimales=0)}). Coste estructural alto.'), axis=1), '')
    return t


# ---------------------------------------------------------------- 5. Desviaciones por línea

def comparar(pyg, presupuesto, mes):
    """Real frente a presupuesto y frente al mismo mes del año anterior, por hotel y línea."""
    mes = pd.Timestamp(mes)
    anterior = mes - pd.DateOffset(years=1)
    real = pyg.xs(mes, level='Mes')
    aa = pyg.xs(anterior, level='Mes') if anterior in pyg.index.get_level_values('Mes') else None
    pres = None
    if presupuesto is not None and len(presupuesto):
        pr = presupuesto.copy()
        pr['Mes'] = pd.to_datetime(pr['Fecha']).dt.to_period('M').dt.to_timestamp()
        pr = pr[pr['Mes'] == mes]
        if len(pr):
            pres = pr.pivot_table(index='Id hotel', columns='Línea', values='Presupuesto', aggfunc='sum')
    filas = []
    for hotel in real.index:
        for linea in real.columns:
            filas.append({'Id hotel': hotel, 'Línea': linea, 'Real': real.loc[hotel, linea],
                          'Presupuesto': pres.loc[hotel, linea] if pres is not None and hotel in pres.index and linea in pres.columns else np.nan,
                          'Año anterior': aa.loc[hotel, linea] if aa is not None and hotel in aa.index else np.nan})
    return pd.DataFrame(filas)


LINEAS_DERIVADAS = {'Reserva FF&E'}  # se calculan a partir de otras líneas: no se analizan por separado

# Cantidad y precio de cada línea de ingresos (para explicar si la diferencia viene del volumen o del precio).
CANTIDAD_INGRESO = {
    'Alojamiento': ('Room nights', 'Cantidad', 'Room nights', 'ADR'),
    'Desayunos': ('Desayunos', 'Cantidad', 'Desayunos (unidades)', 'precio medio'),
    'Terraza': ('Terraza', 'Cantidad', None, 'ticket medio'),
    'Eventos': ('Eventos', 'Cantidad', None, 'precio medio por evento'),
}


def _actividad_presupuesto(presupuesto, mes):
    """La misma actividad que drivers(), pero según el presupuesto del mes."""
    if presupuesto is None or not len(presupuesto):
        return None
    pr = presupuesto.copy()
    pr['Mes'] = pd.to_datetime(pr['Fecha']).dt.to_period('M').dt.to_timestamp()
    pr = pr[pr['Mes'] == pd.Timestamp(mes)].pivot_table(index='Id hotel', columns='Línea', values='Presupuesto', aggfunc='sum')
    if pr.empty:
        return None
    col = lambda c: pr[c] if c in pr.columns else 0.0
    ingresos = pr[[c for c in ['Alojamiento', 'Desayunos', 'Terraza', 'Eventos', 'Lavandería clientes', 'Parking', 'Minibar'] if c in pr.columns]].sum(axis=1)
    return pd.DataFrame({'Room nights': col('Room nights'), 'Desayunos servidos': col('Desayunos (unidades)'),
                         'Ingresos alojamiento': col('Alojamiento'), 'Ingresos restauración': col('Terraza') + col('Eventos'),
                         'Ingresos totales': ingresos})


def desviaciones(pyg, presupuesto, pms, alertas, cfg, mes, cuadre_mes=None, m=None):
    """Líneas de detalle que se mueven más del umbral (en % y en €) frente a presupuesto o año anterior.

    Causa, por orden:
      1. Factura: hay una alerta de factura o de comparativa en esa línea.
      2. Cuadre: la línea de ingresos no cuadra entre operador y contabilidad.
      3. Ingresos: se explica cuánto viene del volumen y cuánto del precio.
      4. Actividad (falsa alarma): coste variable cuyo importe por unidad de actividad apenas cambia.
      5. Gasto irregular: proveedores que no facturan todos los meses.
      6. Sin causa identificada: hay que revisarla.
    """
    mes = pd.Timestamp(mes)
    umbral_pct, umbral_eur = p(cfg, 'umbral_desviacion_pct'), p(cfg, 'umbral_desviacion_eur')
    est = cfg['estructura_informe']
    lineas = [l for l in est[est['Tipo'] == 'Detalle']['Línea'] if l not in LINEAS_DERIVADAS]
    bloque = dict(zip(est['Línea'], est['Bloque']))
    tipo_coste = cfg['plan_cuentas'].drop_duplicates('Línea del informe').set_index('Línea del informe')['Tipo de coste'].to_dict()
    comp = comparar(pyg, presupuesto, mes)
    comp = comp[comp['Línea'].isin(lineas)]
    act = drivers(pms)
    act['Ingresos totales'] = _serie_operador(pms, 'Total general de la actividad', 'Total de control')
    act_pres = _actividad_presupuesto(presupuesto, mes)
    anterior = mes - pd.DateOffset(years=1)
    driver_de = {**DRIVER_LINEA, 'Honorarios del operador': 'Ingresos totales'}
    filas = []
    for _, r in comp.iterrows():
        for referencia in ('Presupuesto', 'Año anterior'):
            ref = r[referencia]
            if pd.isna(ref) or ref == 0:
                continue
            dif = r['Real'] - ref
            if abs(dif) <= umbral_eur or abs(dif / ref) <= umbral_pct:
                continue
            hotel, linea = r['Id hotel'], r['Línea']
            tipo_causa, causa, explicacion = 'Sin causa', 'Sin causa identificada', 'Revisar con el hotel.'
            de_la_linea = alertas[(alertas['Id hotel'] == hotel) & (alertas['Línea'] == linea)] if len(alertas) else alertas
            cuadre_linea = None
            if cuadre_mes is not None and len(cuadre_mes):
                c = cuadre_mes[(cuadre_mes['Id hotel'] == hotel) & (cuadre_mes['Línea'] == linea) & ~cuadre_mes['Cuadra']]
                cuadre_linea = c.iloc[0] if len(c) else None
            if len(de_la_linea):
                tipo_causa = 'Factura'
                causa = '; '.join(sorted(set(de_la_linea['Tipo'])))
                explicacion = ' '.join(de_la_linea['Detalle'])
            elif cuadre_linea is not None:
                tipo_causa, causa, explicacion = 'Cuadre', cuadre_linea['Causa'], cuadre_linea['Detalle']
            elif bloque.get(linea) == 'Ingresos' and linea in CANTIDAD_INGRESO:
                concepto, medida, linea_pres, nombre_precio = CANTIDAD_INGRESO[linea]
                cant = _serie_operador(pms, concepto, medida)
                cant_hoy = cant.get((hotel, mes), np.nan)
                if referencia == 'Año anterior':
                    cant_ref = cant.get((hotel, anterior), np.nan)
                else:
                    cant_ref = np.nan
                    if linea_pres and presupuesto is not None and len(presupuesto):
                        pr = presupuesto[(presupuesto['Id hotel'] == hotel) & (presupuesto['Línea'] == linea_pres)
                                         & (pd.to_datetime(presupuesto['Fecha']) == mes)]
                        cant_ref = pr['Presupuesto'].sum() if len(pr) else np.nan
                if pd.notna(cant_hoy) and pd.notna(cant_ref) and cant_ref and cant_hoy:
                    var_cant = cant_hoy / cant_ref - 1
                    var_precio = (r['Real'] / cant_hoy) / (ref / cant_ref) - 1
                    tipo_causa, causa = 'Ingresos', 'Volumen y precio'
                    explicacion = (f'{concepto}: {_pct(var_cant, signo=True)}; {nombre_precio}: {_pct(var_precio, signo=True)}.')
                else:
                    tipo_causa, causa = 'Ingresos', 'Variación de ingresos'
                    explicacion = 'No hay cantidad de referencia para separar volumen y precio.'
            elif bloque.get(linea) == 'Ingresos':
                # Ingresos sin cantidad propia (parking, minibar, lavandería): se comparan por room night.
                if referencia == 'Año anterior' and (hotel, anterior) in act.index:
                    u_hoy, u_ref = act.loc[(hotel, mes), 'Room nights'], act.loc[(hotel, anterior), 'Room nights']
                elif referencia == 'Presupuesto' and act_pres is not None and hotel in act_pres.index:
                    u_hoy, u_ref = act.loc[(hotel, mes), 'Room nights'], act_pres.loc[hotel, 'Room nights']
                else:
                    u_hoy = u_ref = np.nan
                tipo_causa, causa = 'Ingresos', 'Variación de ingresos'
                if pd.notna(u_ref) and u_ref and u_hoy:
                    por_rn = (r['Real'] / u_hoy) / (ref / u_ref) - 1
                    explicacion = f'Room nights: {_pct(u_hoy / u_ref - 1, signo=True)}; ingreso por room night: {_pct(por_rn, signo=True)}.'
                else:
                    explicacion = 'No hay actividad de referencia para comparar.'
            elif tipo_coste.get(linea) == 'variable' or linea in driver_de:
                driver = driver_de.get(linea, 'Room nights')
                if referencia == 'Año anterior' and (hotel, anterior) in act.index:
                    u_hoy, u_ref = act.loc[(hotel, mes), driver], act.loc[(hotel, anterior), driver]
                elif referencia == 'Presupuesto' and act_pres is not None and hotel in act_pres.index:
                    u_hoy, u_ref = act.loc[(hotel, mes), driver], act_pres.loc[hotel, driver]
                else:
                    u_hoy = u_ref = np.nan
                if pd.notna(u_ref) and u_ref and u_hoy and abs((r['Real'] / u_hoy) / (ref / u_ref) - 1) <= umbral_pct:
                    tipo_causa, causa = 'Actividad', 'Explicada por la actividad'
                    explicacion = (f'{driver}: {_pct(u_hoy / u_ref - 1, signo=True)}; el importe por unidad apenas cambia. Falsa alarma.')
            if tipo_causa == 'Sin causa' and m is not None and bloque.get(linea) != 'Ingresos':
                hist = m[(m['Id hotel'] == hotel) & (m['Línea'] == linea)
                         & (m['Mes'] < mes) & (m['Mes'] >= mes - pd.DateOffset(months=12))]
                meses_con_gasto = hist['Mes'].nunique()
                if meses_con_gasto <= 9:
                    tipo_causa, causa = 'Calendario', 'Gasto irregular'
                    explicacion = (f'Esta partida solo tuvo facturas en {meses_con_gasto} de los últimos 12 meses: '
                                   f'la diferencia depende de cuándo llega la factura.')
            filas.append({'Id hotel': hotel, 'Línea': linea, 'Referencia': referencia, 'Real': r['Real'],
                          'Comparado con': ref, 'Diferencia': dif, 'Diferencia %': dif / ref,
                          'Tipo de causa': tipo_causa, 'Causa': causa, 'Explicación': explicacion})
    return pd.DataFrame(filas, columns=['Id hotel', 'Línea', 'Referencia', 'Real', 'Comparado con', 'Diferencia',
                                        'Diferencia %', 'Tipo de causa', 'Causa', 'Explicación'])


def analizar_mes(m, pms, presupuesto, pyg, cfg, mes):
    """Todo el análisis de un mes, listo para el informe."""
    alertas = alertas_facturas(m, pms, cfg, mes)
    comparativa = comparativa_hoteles(m, pms, cfg, mes)
    if len(comparativa):
        for _, r in comparativa[comparativa['Alerta']].iterrows():
            alertas.loc[len(alertas)] = {'Tipo': 'Coste estructural alto', 'Id hotel': r['Id hotel'], 'Línea': r['Línea'],
                                         'Proveedor': '', 'Documento': '', 'Importe': np.nan, 'Detalle': r['Detalle']}
    tabla_cuadre = cuadre(m, pms, cfg, mes)
    return {
        'cuadre': tabla_cuadre,
        'ratios': comprobar_ratios(pms, cfg, mes),
        'alertas': alertas,
        'comparativa': comparativa,
        'desviaciones': desviaciones(pyg, presupuesto, pms, alertas, cfg, mes, cuadre_mes=tabla_cuadre, m=m),
        'version_reglas': VERSION_REGLAS,
    }
