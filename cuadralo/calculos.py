"""Cuádralo · cálculos deterministas.

Toda cifra del informe sale de aquí (nunca de la IA). Las fórmulas siguen las hojas
estructura_informe y parametros de la configuración del cliente.
"""
import pandas as pd

VERSION_CALCULOS = '2026.11.1'


def parametro(cfg, nombre):
    p = cfg['parametros'].set_index('Parámetro')['Valor']
    return p[nombre]


def asignar_lineas(mov, cfg):
    """Añade a cada movimiento su línea del informe, bloque, hotel y mes.

    Regla del plan de cuentas: si hay fila con el ceco concreto manda esa; si no, la de "(cualquiera)".
    """
    pc = cfg['plan_cuentas'].copy()
    pc['Cuenta contable'] = pc['Cuenta contable'].astype(str)
    m = mov.copy()
    m['Cuenta contable'] = m['Cuenta contable'].astype(str)
    m['Ceco'] = m['Ceco'].fillna('').astype(str)
    especifico = pc[pc['Ceco'] != '(cualquiera)'][['Cuenta contable', 'Ceco', 'Línea del informe', 'Bloque']]
    general = pc[pc['Ceco'] == '(cualquiera)'][['Cuenta contable', 'Línea del informe', 'Bloque']]
    m = m.merge(especifico, on=['Cuenta contable', 'Ceco'], how='left')
    m = m.merge(general, on='Cuenta contable', how='left', suffixes=('', '_general'))
    m['Línea'] = m['Línea del informe'].fillna(m['Línea del informe_general'])
    m['Bloque'] = m['Bloque'].fillna(m['Bloque_general'])
    m = m.drop(columns=['Línea del informe', 'Línea del informe_general', 'Bloque_general'])
    sin_linea = m[m['Línea'].isna()]
    if len(sin_linea):
        cuentas = sorted(sin_linea['Cuenta contable'].unique())
        raise ValueError(f'Cuentas sin línea en el plan de cuentas: {cuentas}')
    finca2hotel = dict(zip(cfg['hoteles']['Finca'], cfg['hoteles']['Id hotel']))
    m['Id hotel'] = m['Finca'].map(finca2hotel)
    m['Mes'] = pd.to_datetime(m['Fecha de registro']).dt.to_period('M').dt.to_timestamp()
    return m


def cuenta_resultados(mov, cfg):
    """Cuenta de resultados hasta GOP2 por hotel y mes (filas) y línea del informe (columnas)."""
    m = asignar_lineas(mov, cfg)
    detalle = m.pivot_table(index=['Id hotel', 'Mes'], columns='Línea',
                            values='Importe sin IVA', aggfunc='sum').fillna(0.0)
    return resultados(detalle, cfg)


def lineas_detalle(cfg):
    est = cfg['estructura_informe']
    return [l for l in est[est['Tipo'] == 'Detalle']['Línea'].tolist() if l != 'Reserva FF&E']


def resultados(detalle, cfg):
    """A partir de las líneas de detalle (columnas) calcula subtotales, GOP, AGOP y GOP2.

    Se usa igual para el real, el presupuesto y el año anterior, y para un hotel o la suma de varios:
    así las tres columnas siempre se calculan con las mismas fórmulas.
    """
    est = cfg['estructura_informe']
    detalle = detalle.copy()
    for linea in lineas_detalle(cfg):
        if linea not in detalle.columns:
            detalle[linea] = 0.0

    def total(bloque):
        lineas = est[(est['Bloque'] == bloque) & (est['Tipo'] == 'Detalle')]['Línea']
        return detalle[[l for l in lineas if l != 'Reserva FF&E']].sum(axis=1)

    r = detalle.copy()
    r['Total ingresos'] = total('Ingresos')
    r['Total consumos'] = total('Consumos')
    r['Total personal'] = total('Personal')
    r['Total otros gastos operativos'] = total('Otros gastos operativos')
    r['GOP'] = r['Total ingresos'] - r['Total consumos'] - r['Total personal'] - r['Total otros gastos operativos']
    r['Reserva FF&E'] = r['Total ingresos'] * float(parametro(cfg, 'reserva_ffe_pct'))
    r['Total ajustes'] = r['Honorarios del operador'] + r['Reserva FF&E']
    r['AGOP'] = r['GOP'] - r['Total ajustes']
    r['Total por debajo del AGOP'] = total('Bajo AGOP')
    r['GOP2'] = r['AGOP'] - r['Total por debajo del AGOP']
    r['% GOP'] = (r['GOP'] / r['Total ingresos']).where(r['Total ingresos'] != 0)
    return r


def actividad(pms, cfg):
    """Room nights, alojamiento, ADR recalculado, ocupación y RevPAR por hotel y mes."""
    p = pms.copy()
    p['Mes'] = pd.to_datetime(p['Fecha']).dt.to_period('M').dt.to_timestamp()
    rn = p[(p['Concepto'] == 'Room nights') & (p['Medida'] == 'Cantidad')].set_index(['Id hotel', 'Mes'])['Valor']
    aloj = p[(p['Concepto'] == 'Alojamiento') & (p['Medida'] == 'Importe')].set_index(['Id hotel', 'Mes'])['Valor']
    a = pd.DataFrame({'Room nights': rn, 'Alojamiento': aloj})
    habitaciones = cfg['hoteles'].set_index('Id hotel')['Habitaciones']
    meses = a.index.get_level_values('Mes')
    dias = pd.Series(meses.days_in_month, index=a.index)
    disponibles = a.index.get_level_values('Id hotel').map(habitaciones).values * dias
    a['Habitaciones disponibles'] = disponibles
    a['ADR'] = a['Alojamiento'] / a['Room nights']
    a['Ocupación'] = a['Room nights'] / a['Habitaciones disponibles']
    a['RevPAR'] = a['Alojamiento'] / a['Habitaciones disponibles']
    return a


# ---------------------------------------------------------------------------
# Paso 3-4: presupuesto, KPIs del informe, cuadre y comprobación de ratios
# ---------------------------------------------------------------------------

def presupuesto_detalle(pres):
    """Presupuesto con las mismas columnas que el real: una fila por hotel y mes, una columna por línea.

    Incluye las líneas de actividad (Room nights, Desayunos (unidades)), que no son euros.
    """
    if pres is None or len(pres) == 0:
        return pd.DataFrame()
    p = pres.copy()
    p['Mes'] = pd.to_datetime(p['Fecha']).dt.to_period('M').dt.to_timestamp()
    return p.pivot_table(index=['Id hotel', 'Mes'], columns='Línea', values='Presupuesto', aggfunc='sum').fillna(0.0)


def detalle_real(mov, cfg):
    m = asignar_lineas(mov, cfg)
    return m.pivot_table(index=['Id hotel', 'Mes'], columns='Línea', values='Importe sin IVA', aggfunc='sum').fillna(0.0)


def actividad_completa(pms, cfg):
    """Actividad del operador por hotel y mes: cantidades e importes que se suman entre hoteles.

    Los ratios no se guardan aquí: se recalculan a partir de estas sumas (ver kpis()).
    """
    p = pms.copy()
    p['Mes'] = pd.to_datetime(p['Fecha']).dt.to_period('M').dt.to_timestamp()

    def serie(concepto, medida):
        s = p[(p['Concepto'] == concepto) & (p['Medida'] == medida)]
        return s.groupby(['Id hotel', 'Mes'])['Valor'].sum()

    a = pd.DataFrame({
        'Room nights': serie('Room nights', 'Cantidad'),
        'Alojamiento': serie('Alojamiento', 'Importe'),
        'Desayunos (unidades)': serie('Desayunos', 'Cantidad'),
        'Ingresos desayunos': serie('Desayunos', 'Importe'),
        'Pax x room': serie('Pax x room', 'Ratio del operador'),
    }).fillna(0.0)
    habitaciones = cfg['hoteles'].set_index('Id hotel')['Habitaciones']
    dias = pd.Series(a.index.get_level_values('Mes').days_in_month, index=a.index)
    a['Habitaciones disponibles'] = a.index.get_level_values('Id hotel').map(habitaciones).values * dias
    a['Personas'] = a['Room nights'] * a['Pax x room']  # base de la captación de desayunos
    return a


def _div(a, b):
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if b == 0 or a != a or b != b:
        return None
    return a / b


def kpis(r, act, ppto=False):
    """KPIs del informe para un hotel (o la suma de varios) y un mes.

    r: fila de resultados() (real, presupuesto o año anterior). act: actividad del mismo periodo.
    En el presupuesto la actividad sale de sus propias líneas (Room nights, Desayunos (unidades)).
    """
    g = lambda serie, k: float(serie[k]) if serie is not None and k in serie.index else None
    disp = g(act, 'Habitaciones disponibles')
    if ppto:
        rn, aloj = g(r, 'Room nights'), g(r, 'Alojamiento')
        desayunos, ing_des, personas = g(r, 'Desayunos (unidades)'), g(r, 'Desayunos'), None
    else:
        rn, aloj = g(act, 'Room nights'), g(act, 'Alojamiento')
        desayunos, ing_des, personas = g(act, 'Desayunos (unidades)'), g(act, 'Ingresos desayunos'), g(act, 'Personas')
    ing, gop = g(r, 'Total ingresos'), g(r, 'GOP')
    personal_hotel, otros = g(r, 'Personal hotel'), g(r, 'Total otros gastos operativos')
    return {
        'Ingresos totales': ing, 'GOP': gop, '% GOP': _div(gop, ing),
        'AGOP': g(r, 'AGOP'), 'GOP2': g(r, 'GOP2'),
        'Room nights': rn, 'Ocupación': _div(rn, disp), 'ADR': _div(aloj, rn),
        'RevPAR': _div(aloj, disp), 'TRevPAR': _div(ing, disp), 'GOPPAR': _div(gop, disp),
        'Labor cost': _div(g(r, 'Total personal'), ing),
        'CPOR': _div((personal_hotel or 0) + (otros or 0), rn) if personal_hotel is not None else None,
        'Otros gastos operativos': otros,
        'Captación desayunos': _div(desayunos, personas),
        'Precio medio desayuno': _div(ing_des, desayunos),
        'Margen desayunos': (g(r, 'Desayunos') or 0) - (g(r, 'Consumo desayunos') or 0) - (g(r, 'Personal desayunos') or 0)
                            if g(r, 'Desayunos') is not None else None,
    }


def cuadre(mov, pms, cfg):
    """Cuadre por hotel, mes y línea de ingreso: importe del operador − importe en contabilidad."""
    tol = float(parametro(cfg, 'tolerancia_cuadre_eur'))
    p = pms[(pms['Medida'] == 'Importe') & pms['Línea del informe'].notna() & (pms['Línea del informe'] != '')].copy()
    p['Mes'] = pd.to_datetime(p['Fecha']).dt.to_period('M').dt.to_timestamp()
    op = p.groupby(['Id hotel', 'Mes', 'Línea del informe'])['Valor'].sum().rename('Operador')
    op.index = op.index.set_names(['Id hotel', 'Mes', 'Línea'])
    m = asignar_lineas(mov, cfg)
    m = m[m['Bloque'] == 'Ingresos']
    bc = m.groupby(['Id hotel', 'Mes', 'Línea'])['Importe sin IVA'].sum().rename('Contabilidad')
    c = pd.concat([op, bc], axis=1).fillna(0.0)
    c = c[c.index.get_level_values('Mes').isin(op.index.get_level_values('Mes').unique())]
    c['Diferencia'] = (c['Operador'] - c['Contabilidad']).round(2)
    c['Cuadra'] = c['Diferencia'].abs() <= tol
    c['Causa'] = ''
    c['Hotel relacionado'] = ''
    c['Documento'] = ''
    for (h, mes, linea), fila in c[~c['Cuadra']].iterrows():
        d = fila['Diferencia']
        # 1) El mismo importe falta en un hotel y sobra en otro: ingreso contabilizado en otra finca
        otros = c.xs((mes, linea), level=('Mes', 'Línea'))
        espejo = otros[(otros.index != h) & ((otros['Diferencia'] + d).abs() <= tol)]
        if len(espejo):
            c.loc[(h, mes, linea), ['Causa', 'Hotel relacionado']] = [
                'contabilizado en otro hotel' if d > 0 else 'ingreso de otro hotel', espejo.index[0]]
            continue
        # 2) Un abono en contabilidad que el operador no reporta
        apuntes = m[(m['Id hotel'] == h) & (m['Mes'] == mes) & (m['Línea'] == linea) & (m['Importe sin IVA'] < 0)]
        abono = apuntes[(apuntes['Importe sin IVA'] + d).abs() <= tol]
        if len(abono):
            c.loc[(h, mes, linea), ['Causa', 'Documento']] = ['abono no reportado por el operador', abono.iloc[0]['Nº documento']]
            continue
        c.loc[(h, mes, linea), 'Causa'] = 'sin contabilizar' if d > 0 else 'contabilizado y no reportado por el operador'
    return c


RATIOS = [
    # (concepto del operador, nombre, cómo se recalcula, tipo de tolerancia)
    ('ADR', 'ADR', 'Alojamiento / room nights', 'relativa'),
    ('Ocupación', 'Ocupación', 'Room nights / (habitaciones × días)', 'puntos'),
    ('Captación desayuno', 'Captación de desayunos', 'Desayunos / (room nights × pax por habitación)', 'puntos'),
    ('Precio medio desayuno', 'Precio medio del desayuno', 'Ingresos de desayunos / desayunos servidos', 'relativa'),
]


def comprobar_ratios(pms, cfg):
    """Compara los ratios que reporta el operador con los recalculados a partir de sus propias cantidades."""
    tol = float(parametro(cfg, 'tolerancia_ratio_pct'))
    act = actividad_completa(pms, cfg)
    p = pms[pms['Medida'] == 'Ratio del operador'].copy()
    p['Mes'] = pd.to_datetime(p['Fecha']).dt.to_period('M').dt.to_timestamp()
    rep = p.pivot_table(index=['Id hotel', 'Mes'], columns='Concepto', values='Valor', aggfunc='sum')
    filas = []
    for (h, mes), a in act.iterrows():
        calc = {'ADR': _div(a['Alojamiento'], a['Room nights']),
                'Ocupación': _div(a['Room nights'], a['Habitaciones disponibles']),
                'Captación desayuno': _div(a['Desayunos (unidades)'], a['Personas']),
                'Precio medio desayuno': _div(a['Ingresos desayunos'], a['Desayunos (unidades)'])}
        for concepto, nombre, formula, tipo in RATIOS:
            if (h, mes) not in rep.index or concepto not in rep.columns or calc[concepto] is None:
                continue
            reportado = rep.loc[(h, mes), concepto]
            if reportado != reportado:
                continue
            dif = reportado - calc[concepto] if tipo == 'puntos' else _div(reportado - calc[concepto], calc[concepto])
            correcto = abs(dif) <= tol
            nota, impacto = '', None
            if not correcto and concepto == 'ADR':
                impacto = a['Room nights'] * (reportado - calc[concepto])
                nota = 'Si se facturara como room nights × ADR del operador, el alojamiento saldría inflado'
            if not correcto and concepto == 'Captación desayuno':
                sobre_hab = _div(a['Desayunos (unidades)'], a['Room nights'])
                if sobre_hab is not None and abs(reportado - sobre_hab) <= tol:
                    nota = 'Calculada sobre habitaciones, no sobre personas'
            filas.append({'Id hotel': h, 'Mes': mes, 'Ratio': nombre, 'Fórmula': formula, 'Tipo': tipo,
                          'Operador': reportado, 'Recalculado': calc[concepto], 'Diferencia': dif,
                          'Correcto': correcto, 'Nota': nota, 'Impacto': impacto})
    return pd.DataFrame(filas)
