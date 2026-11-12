"""Cuádralo · cálculos con las reservas del PMS: noches por mes, canales, perfil del cliente y cuadre con el operador.

Todas las cifras salen de aquí (nunca de la IA). Las noches de una estancia que cruza de un mes a otro se
reparten entre los dos meses, y sus ingresos en proporción a las noches de cada mes.
"""
import pandas as pd


def noches_por_mes(res):
    """Una fila por reserva válida (estancia) y mes, con sus noches, ingresos y personas-noche de ese mes."""
    if res is None or len(res) == 0:
        return pd.DataFrame(columns=['Id hotel', 'Mes', 'Nº reserva', 'Canal', 'Tipo de canal', 'Segmento',
                                     'Nacionalidad', 'Noches', 'Ingresos', 'Personas-noche', 'Habitaciones'])
    r = res[res['Estancia'] & (res['Noches'] > 0)].copy()
    r['Mes'] = r['Llegada'].dt.to_period('M').dt.to_timestamp()
    ultimo = (r['Salida'] - pd.Timedelta(days=1)).dt.to_period('M').dt.to_timestamp()
    simples = r[ultimo == r['Mes']].copy()
    simples['Noches mes'] = simples['Noches']
    partes = [simples]
    cruzan = r[ultimo != r['Mes']]
    filas = []
    for _, x in cruzan.iterrows():  # pocas reservas: las que cruzan un fin de mes
        for dia in pd.date_range(x['Llegada'], x['Salida'] - pd.Timedelta(days=1), freq='D'):
            filas.append({**x.to_dict(), 'Mes': dia.to_period('M').to_timestamp(), 'Noches mes': 1})
    if filas:
        f = pd.DataFrame(filas).groupby(['Nº reserva', 'Id hotel', 'Mes'], as_index=False).agg(
            {**{c: 'first' for c in r.columns if c not in ('Nº reserva', 'Id hotel', 'Mes')}, 'Noches mes': 'sum'})
        partes.append(f)
    m = pd.concat(partes, ignore_index=True)
    m['Ingresos'] = m['Ingresos alojamiento'] * m['Noches mes'] / m['Noches']
    m['Personas-noche'] = m['Personas'] * m['Noches mes']
    m['Habitaciones'] = 1
    return m.rename(columns={'Noches': 'Noches estancia'}).rename(columns={'Noches mes': 'Noches'})[
        ['Id hotel', 'Mes', 'Nº reserva', 'Canal', 'Tipo de canal', 'Segmento', 'Nacionalidad', 'Noches', 'Ingresos',
         'Personas-noche', 'Habitaciones']]


def por_canal(res_mes, res, hoteles, meses):
    """Resumen por canal para los hoteles y meses pedidos: reservas, noches, % de noches, ingresos, ADR,
    antelación media y % de cancelación (las cancelaciones se cuentan por mes de llegada)."""
    m = res_mes[res_mes['Id hotel'].isin(hoteles) & res_mes['Mes'].isin(meses)]
    if len(m) == 0:
        return pd.DataFrame()
    g = m.groupby('Canal').agg(**{'Tipo de canal': ('Tipo de canal', 'first'), 'Reservas': ('Nº reserva', 'nunique'),
                                  'Noches': ('Noches', 'sum'), 'Ingresos': ('Ingresos', 'sum')})
    g['% noches'] = g['Noches'] / g['Noches'].sum()
    g['% ingresos'] = g['Ingresos'] / g['Ingresos'].sum()
    g['ADR'] = g['Ingresos'] / g['Noches']
    r = res[res['Id hotel'].isin(hoteles)].copy()
    r['Mes'] = r['Llegada'].dt.to_period('M').dt.to_timestamp()
    r = r[r['Mes'].isin(meses)]
    validas = r[r['Estancia']]
    g['Antelación media (días)'] = validas.groupby('Canal')['Antelación (días)'].mean()
    total = r[r['Estancia'] | r['Cancelada']].groupby('Canal').size()
    canceladas = r[r['Cancelada']].groupby('Canal').size()
    g['% cancelación'] = (canceladas.reindex(g.index).fillna(0) / total.reindex(g.index)).fillna(0)
    return g.sort_values('Noches', ascending=False).reset_index()


def kpis_reservas(res_mes, res, hoteles, meses):
    """Reservas, estancia media, personas por habitación, antelación media y % de cancelación del periodo."""
    m = res_mes[res_mes['Id hotel'].isin(hoteles) & res_mes['Mes'].isin(meses)]
    r = res[res['Id hotel'].isin(hoteles)].copy() if res is not None and len(res) else pd.DataFrame()
    if len(m) == 0 or len(r) == 0:
        return {}
    r['Mes'] = r['Llegada'].dt.to_period('M').dt.to_timestamp()
    r = r[r['Mes'].isin(meses)]
    validas, canceladas = r[r['Estancia']], r[r['Cancelada']]
    directo = m[m['Tipo de canal'] == 'Directo']
    return {
        'Reservas': int(validas['Nº reserva'].nunique()),
        'Canceladas': int(len(canceladas)),
        '% cancelación': len(canceladas) / (len(validas) + len(canceladas)) if len(validas) + len(canceladas) else None,
        'Estancia media': validas['Noches'].mean() if len(validas) else None,
        'Antelación media': validas['Antelación (días)'].mean() if len(validas) else None,
        'Personas por habitación': m['Personas-noche'].sum() / m['Noches'].sum() if m['Noches'].sum() else None,
        '% directo': directo['Noches'].sum() / m['Noches'].sum() if m['Noches'].sum() else None,
        'Noches reservas': float(m['Noches'].sum()), 'Ingresos reservas': float(m['Ingresos'].sum()),
    }


def cuadre_con_operador(res_mes, act, tolerancia_eur):
    """Por hotel y mes: noches e ingresos de alojamiento según las reservas frente a lo que reporta el operador."""
    if len(res_mes) == 0:
        return pd.DataFrame()
    r = res_mes.groupby(['Id hotel', 'Mes']).agg(**{'Noches reservas': ('Noches', 'sum'), 'Ingresos reservas': ('Ingresos', 'sum')})
    o = act[['Room nights', 'Alojamiento']].rename(columns={'Room nights': 'Noches operador', 'Alojamiento': 'Ingresos operador'})
    c = r.join(o, how='inner')
    c['Dif. noches'] = c['Noches reservas'] - c['Noches operador']
    c['Dif. ingresos'] = (c['Ingresos reservas'] - c['Ingresos operador']).round(2)
    c['Cuadra'] = (c['Dif. noches'].abs() < 0.5) & (c['Dif. ingresos'].abs() <= tolerancia_eur)
    return c
