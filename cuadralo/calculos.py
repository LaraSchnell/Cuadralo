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
    est = cfg['estructura_informe']
    detalle = m.pivot_table(index=['Id hotel', 'Mes'], columns='Línea',
                            values='Importe sin IVA', aggfunc='sum').fillna(0.0)
    lineas_detalle = est[est['Tipo'] == 'Detalle']['Línea'].tolist()
    for linea in lineas_detalle:
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
