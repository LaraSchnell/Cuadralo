"""Cuádralo · explorador de apuntes contables: filtros, agrupación y comparación con el año anterior.

Trabaja sobre los movimientos ya asignados a su línea del informe (calculos.asignar_lineas).
Solo filtra y suma: no calcula ningún KPI.
"""
import pandas as pd

AGRUPACIONES = {
    'proveedor': ('Proveedor', 'Proveedor'),
    'linea': ('Línea', 'Línea del informe'),
    'ceco': ('Ceco', 'Ceco'),
    'mes': ('Mes', 'Mes'),
    'hotel': ('Id hotel', 'Hotel'),
    'cuenta': ('Cuenta contable', 'Cuenta contable'),
    'bloque': ('Bloque', 'Bloque'),
}
SIN_CECO = '(sin ceco)'


def preparar(lineas):
    """Columnas auxiliares para filtrar: ceco sin vacíos y fechas como fecha."""
    m = lineas.copy()
    m['Ceco'] = m['Ceco'].replace('', None).fillna(SIN_CECO)
    m['Fecha de registro'] = pd.to_datetime(m['Fecha de registro'])
    m['Fecha de emisión del documento'] = pd.to_datetime(m['Fecha de emisión del documento'])
    m['Cuenta contable'] = m['Cuenta contable'].astype(str)
    return m


def filtrar(m, hoteles, desde=None, hasta=None, proveedor=None, ceco=None, linea=None, bloque=None,
            cuenta=None, texto=None, importe_min=None):
    """Aplica los filtros. `hoteles` es obligatorio: es la lista de hoteles que el usuario puede ver."""
    f = m[m['Id hotel'].isin(hoteles)]
    if desde is not None:
        f = f[f['Fecha de registro'] >= pd.Timestamp(desde)]
    if hasta is not None:
        f = f[f['Fecha de registro'] <= pd.Timestamp(hasta)]
    if proveedor:
        f = f[f['Proveedor'] == proveedor]
    if ceco:
        f = f[f['Ceco'] == ceco]
    if linea:
        f = f[f['Línea'] == linea]
    if bloque:
        f = f[f['Bloque'] == bloque]
    if cuenta:
        f = f[f['Cuenta contable'].str.startswith(str(cuenta).strip())]
    if texto:
        t = str(texto).strip().lower()
        campos = (f['Descripción'].fillna('').astype(str) + ' ' + f['Nº documento'].fillna('').astype(str) + ' '
                  + f['Nº documento externo'].fillna('').astype(str) + ' ' + f['Proveedor'].fillna('').astype(str))
        f = f[campos.str.lower().str.contains(t, regex=False)]
    if importe_min is not None:
        f = f[f['Importe sin IVA'].abs() >= float(importe_min)]
    return f.sort_values(['Fecha de registro', 'Nº documento'])


def agrupar(actual, anterior, por, nombres_hotel=None):
    """Suma por la agrupación elegida, con el mismo filtro un año antes al lado."""
    col, titulo = AGRUPACIONES[por]

    def sumar(df):
        if len(df) == 0:
            return pd.DataFrame(columns=['Importe', 'Apuntes'])
        g = df.copy()
        if col == 'Mes':
            g['Mes'] = g['Fecha de registro'].dt.to_period('M').dt.to_timestamp()
        return g.groupby(col).agg(Importe=('Importe sin IVA', 'sum'), Apuntes=('Importe sin IVA', 'size'))

    a = sumar(actual)
    if col == 'Mes':
        b = sumar(anterior)
        if len(b):
            b.index = b.index + pd.DateOffset(months=12)  # se compara cada mes con el mismo mes del año anterior
    else:
        b = sumar(anterior)
    t = a.join(b.rename(columns={'Importe': 'Año anterior', 'Apuntes': 'Apuntes AA'}), how='outer').fillna(0.0)
    for col_num in ('Importe', 'Año anterior', 'Apuntes'):
        t[col_num] = t[col_num].astype(float)
    t['Diferencia'] = t['Importe'] - t['Año anterior']
    base = t['Año anterior'].abs().replace(0.0, float('nan'))
    t['Var %'] = t['Diferencia'] / base
    t = t.reset_index().rename(columns={col: titulo})
    if col == 'Id hotel' and nombres_hotel:
        t[titulo] = t[titulo].map(lambda h: nombres_hotel.get(h, h))
    if col == 'Mes':
        t = t.sort_values(titulo)
    else:
        t = t.reindex(t['Importe'].abs().sort_values(ascending=False).index)
    t['Apuntes'] = t['Apuntes'].astype(int)
    return t[[titulo, 'Importe', 'Año anterior', 'Diferencia', 'Var %', 'Apuntes']].reset_index(drop=True)


def tabla_detalle(f, nombres_hotel):
    """Apuntes con las columnas que se enseñan y se exportan."""
    return pd.DataFrame({
        'Fecha de registro': f['Fecha de registro'].dt.date,
        'Fecha de emisión': f['Fecha de emisión del documento'].dt.date,
        'Hotel': f['Id hotel'].map(lambda h: nombres_hotel.get(h, h)),
        'Nº documento': f['Nº documento'],
        'Nº documento proveedor': f['Nº documento externo'].fillna(''),
        'Proveedor': f['Proveedor'],
        'Descripción': f['Descripción'],
        'Cuenta contable': f['Cuenta contable'],
        'Ceco': f['Ceco'],
        'Línea del informe': f['Línea'],
        'Bloque': f['Bloque'],
        'Importe sin IVA': f['Importe sin IVA'].astype(float),
    }).reset_index(drop=True)
