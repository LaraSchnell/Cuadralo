"""Resultados precalculados de cada empresa.

Al procesar las cargas se calculan una vez las tablas del informe (detalle contable agregado por hotel, mes, línea,
ceco y proveedor; actividad; cuadre; ratios; reservas agregadas) y se guardan en ResultadoEmpresa. La web solo
las lee: no vuelve a leer los apuntes ni a recalcular el histórico al abrir una página.

Las desviaciones de cada hotel y mes se calculan la primera vez que alguien las pide (con los apuntes de ese hotel
de los 14 meses anteriores, leídos de la base de datos) y se guardan en ResultadoDesviacion.

Aislamiento: todo se lee y se guarda SIEMPRE filtrando por la empresa que se recibe; nunca por un dato de la URL.
"""
import pickle

import pandas as pd
from django.db import IntegrityError, transaction

from cuadralo import informe
from .models import MovimientoContable, ResultadoDesviacion, ResultadoEmpresa

VERSION_PRECALCULO = '2026.11.12'   # subirla si cambia lo que se guarda: obliga a recalcular


def guardar(empresa, datos):
    with transaction.atomic():
        ResultadoEmpresa.objects.filter(empresa=empresa).delete()
        ResultadoDesviacion.objects.filter(empresa=empresa).delete()
        ResultadoEmpresa.objects.bulk_create([
            ResultadoEmpresa(empresa=empresa, clave=k, contenido=pickle.dumps(v, protocol=pickle.HIGHEST_PROTOCOL),
                             version=VERSION_PRECALCULO)
            for k, v in datos.tablas().items()])


def hay_precalculo(empresa):
    claves = set(ResultadoEmpresa.objects.filter(empresa=empresa, version=VERSION_PRECALCULO).values_list('clave', flat=True))
    return claves >= set(informe.CLAVES_PRECALCULO)


def cargar(empresa, cfg):
    """Datos de la empresa a partir del precálculo, o None si no existe (o es de una versión anterior)."""
    filas = ResultadoEmpresa.objects.filter(empresa=empresa, version=VERSION_PRECALCULO)
    tablas = {f.clave: pickle.loads(bytes(f.contenido)) for f in filas}
    if not set(informe.CLAVES_PRECALCULO) <= set(tablas):
        return None
    datos = informe.Datos.desde_precalculo(tablas, cfg, None)
    datos._fuente_desviaciones = lambda hotel, mes: _desviaciones(empresa, datos, hotel, mes)
    return datos


def apuntes_hotel(empresa, hotel, desde, hasta):
    """Apuntes de un hotel entre dos meses, con los nombres de columna del modelo común y su línea del informe."""
    return _a_tabla(MovimientoContable.objects.filter(empresa=empresa, hotel=hotel, mes__gte=desde.date(), mes__lte=hasta.date()))


def apuntes_rango(empresa, hoteles, desde, hasta):
    """Apuntes de varios hoteles entre dos fechas de registro (filtrado en la base de datos, nunca toda la tabla)."""
    q = MovimientoContable.objects.filter(empresa=empresa, hotel__in=hoteles)
    if desde is not None:
        q = q.filter(fecha_registro__gte=desde.date())
    if hasta is not None:
        q = q.filter(fecha_registro__lte=hasta.date())
    return _a_tabla(q)


def _a_tabla(q):
    df = pd.DataFrame(list(q.values('fecha_registro', 'fecha_documento', 'num_documento', 'num_documento_externo', 'cuenta',
                                    'descripcion', 'importe', 'iva', 'proveedor', 'finca', 'ceco', 'hotel', 'mes', 'linea',
                                    'bloque')))
    if len(df) == 0:
        return pd.DataFrame(columns=['Fecha de registro', 'Fecha de emisión del documento', 'Nº documento',
                                     'Nº documento externo', 'Cuenta contable', 'Descripción', 'Importe sin IVA', 'IVA',
                                     'Proveedor', 'Finca', 'Ceco', 'Id hotel', 'Mes', 'Línea', 'Bloque'])
    df = df.rename(columns={
        'fecha_registro': 'Fecha de registro', 'fecha_documento': 'Fecha de emisión del documento', 'num_documento': 'Nº documento',
        'num_documento_externo': 'Nº documento externo', 'cuenta': 'Cuenta contable', 'descripcion': 'Descripción',
        'importe': 'Importe sin IVA', 'iva': 'IVA', 'proveedor': 'Proveedor', 'finca': 'Finca', 'ceco': 'Ceco',
        'hotel': 'Id hotel', 'mes': 'Mes', 'linea': 'Línea', 'bloque': 'Bloque'})
    df['Importe sin IVA'] = df['Importe sin IVA'].astype(float)
    df['IVA'] = df['IVA'].astype(float)
    for col in ('Fecha de registro', 'Fecha de emisión del documento', 'Mes'):
        df[col] = pd.to_datetime(df[col])
    return df


def _desviaciones(empresa, datos, hotel, mes):
    guardada = ResultadoDesviacion.objects.filter(empresa=empresa, hotel=hotel, mes=mes.date()).first()
    if guardada is not None:
        return pickle.loads(bytes(guardada.contenido))
    hist = apuntes_hotel(empresa, hotel, mes - pd.DateOffset(months=14), mes)
    desv = informe.calcular_desviaciones(hist, datos.det_real, datos.det_ppto, datos.act, datos.cuadre, datos.cfg, hotel, mes)
    try:
        with transaction.atomic():
            ResultadoDesviacion.objects.create(empresa=empresa, hotel=hotel, mes=mes.date(),
                                               contenido=pickle.dumps(desv, protocol=pickle.HIGHEST_PROTOCOL))
    except IntegrityError:   # otra petición la guardó a la vez
        pass
    return desv
