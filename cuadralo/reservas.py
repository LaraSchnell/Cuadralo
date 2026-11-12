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


DIMENSIONES = ['Id hotel', 'Mes', 'Canal', 'Tipo de canal', 'Segmento', 'Nacionalidad']


def agregar_por_mes(res):
    """Reservas agregadas por hotel, mes de estancia, canal, segmento y país: es lo que guarda el precálculo.

    Reservas = reservas con alguna noche en ese mes (una estancia que cruza de mes cuenta en los dos).
    """
    m = noches_por_mes(res)
    if len(m) == 0:
        return pd.DataFrame(columns=DIMENSIONES + ['Reservas', 'Noches', 'Ingresos', 'Personas-noche'])
    return m.groupby(DIMENSIONES, as_index=False).agg(
        Reservas=('Nº reserva', 'nunique'), Noches=('Noches', 'sum'), Ingresos=('Ingresos', 'sum'),
        **{'Personas-noche': ('Personas-noche', 'sum')})


def agregar_llegadas(res):
    """Por hotel, mes de llegada y canal: estancias, cancelaciones, antelación y noches (para % cancelación y medias)."""
    if res is None or len(res) == 0:
        return pd.DataFrame(columns=['Id hotel', 'Mes', 'Canal', 'Estancias', 'Canceladas', 'Suma antelación',
                                     'Con antelación', 'Noches estancias'])
    r = res.copy()
    r['Mes'] = r['Llegada'].dt.to_period('M').dt.to_timestamp()
    r['Es estancia'] = r['Estancia'].astype(int)
    r['Es cancelada'] = r['Cancelada'].astype(int)
    r['Ant'] = r['Antelación (días)'].where(r['Estancia'])
    r['Noches est'] = r['Noches'].where(r['Estancia'], 0)
    return r.groupby(['Id hotel', 'Mes', 'Canal'], as_index=False).agg(
        Estancias=('Es estancia', 'sum'), Canceladas=('Es cancelada', 'sum'),
        **{'Suma antelación': ('Ant', 'sum'), 'Con antelación': ('Ant', 'count'), 'Noches estancias': ('Noches est', 'sum')})


def _sel(df, hoteles, meses, canal=None):
    if df is None or len(df) == 0:
        return df
    f = df[df['Id hotel'].isin(hoteles) & df['Mes'].isin(meses)]
    return f[f['Canal'].isin(canal)] if canal else f


def por_canal(agg, llegadas, hoteles, meses, canal=None):
    """Resumen por canal: reservas, noches, % de noches, ingresos, ADR, antelación media y % de cancelación
    (las cancelaciones y la antelación se cuentan por mes de llegada)."""
    m = _sel(agg, hoteles, meses, canal)
    if m is None or len(m) == 0:
        return pd.DataFrame()
    g = m.groupby('Canal').agg(**{'Tipo de canal': ('Tipo de canal', 'first'), 'Reservas': ('Reservas', 'sum'),
                                  'Noches': ('Noches', 'sum'), 'Ingresos': ('Ingresos', 'sum')})
    g['% noches'] = g['Noches'] / g['Noches'].sum()
    g['% ingresos'] = g['Ingresos'] / g['Ingresos'].sum()
    g['ADR'] = g['Ingresos'] / g['Noches']
    l = _sel(llegadas, hoteles, meses, canal).groupby('Canal')[['Estancias', 'Canceladas', 'Suma antelación', 'Con antelación']].sum()
    l = l.reindex(g.index).fillna(0)
    g['Antelación media (días)'] = (l['Suma antelación'] / l['Con antelación'].replace(0, float('nan')))
    g['% cancelación'] = (l['Canceladas'] / (l['Estancias'] + l['Canceladas']).replace(0, float('nan'))).fillna(0)
    return g.sort_values('Noches', ascending=False).reset_index()


def kpis_reservas(agg, llegadas, hoteles, meses, canal=None):
    """Reservas, estancia media, personas por habitación, antelación media, % de cancelación y % de venta directa."""
    m = _sel(agg, hoteles, meses, canal)
    l = _sel(llegadas, hoteles, meses, canal)
    if m is None or len(m) == 0 or l is None or len(l) == 0:
        return {}
    est, canc = float(l['Estancias'].sum()), float(l['Canceladas'].sum())
    noches = float(m['Noches'].sum())
    return {
        'Reservas': int(est), 'Canceladas': int(canc),
        '% cancelación': canc / (est + canc) if est + canc else None,
        'Estancia media': float(l['Noches estancias'].sum()) / est if est else None,
        'Antelación media': float(l['Suma antelación'].sum()) / float(l['Con antelación'].sum()) if l['Con antelación'].sum() else None,
        'Personas por habitación': float(m['Personas-noche'].sum()) / noches if noches else None,
        '% directo': float(m[m['Tipo de canal'] == 'Directo']['Noches'].sum()) / noches if noches else None,
        'Noches reservas': noches, 'Ingresos reservas': float(m['Ingresos'].sum()),
    }


def cuadre_con_operador(agg, act, tolerancia_eur):
    """Por hotel y mes: noches e ingresos de alojamiento según las reservas frente a lo que reporta el operador."""
    if agg is None or len(agg) == 0:
        return pd.DataFrame()
    r = agg.groupby(['Id hotel', 'Mes']).agg(**{'Noches reservas': ('Noches', 'sum'), 'Ingresos reservas': ('Ingresos', 'sum')})
    o = act[['Room nights', 'Alojamiento']].rename(columns={'Room nights': 'Noches operador', 'Alojamiento': 'Ingresos operador'})
    c = r.join(o, how='inner')
    c['Dif. noches'] = c['Noches reservas'] - c['Noches operador']
    c['Dif. ingresos'] = (c['Ingresos reservas'] - c['Ingresos operador']).round(2)
    c['Cuadra'] = (c['Dif. noches'].abs() < 0.5) & (c['Dif. ingresos'].abs() <= tolerancia_eur)
    return c
