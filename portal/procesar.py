"""Procesado de las cargas de una empresa: archivos subidos → modelo común en la base de datos."""
import io
from decimal import Decimal

import pandas as pd
from django.db import transaction

from cuadralo import calculos, normalizar
from .models import Carga, FilaOperador, FilaPresupuesto, MovimientoContable


def _abrir(field_file, nombre):
    """Copia el archivo (local o Blob) a memoria con su nombre original, como lo espera el normalizador."""
    with field_file.open('rb') as f:
        buf = io.BytesIO(f.read())
    buf.name = nombre
    return buf


def leer_configuracion(empresa):
    with empresa.configuracion.open('rb') as f:
        return pd.read_excel(io.BytesIO(f.read()), sheet_name=None)


def _d(valor, decimales=2):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return Decimal('0')
    return Decimal(str(round(float(valor), decimales)))


def _texto(valor):
    return '' if valor is None or (isinstance(valor, float) and pd.isna(valor)) else str(valor)


def procesar_empresa(empresa):
    """Normaliza todas las cargas vigentes de la empresa y sustituye su modelo común.

    Si algo falla, no se toca lo que ya había y las cargas nuevas quedan en error con el motivo.
    """
    cfg = leer_configuracion(empresa)
    vigentes = list(empresa.cargas.exclude(estado__in=['sustituida', 'error']).order_by('creada'))
    por_tipo = {t: [c for c in vigentes if c.tipo == t] for t, _ in Carga.TIPOS}
    try:
        mov = normalizar.normalizar_bc([_abrir(c.archivo, c.nombre_original) for c in por_tipo[Carga.BUSINESS_CENTRAL]])
        pms = normalizar.normalizar_operador([_abrir(c.archivo, c.nombre_original) for c in por_tipo[Carga.OPERADOR]], cfg)
        pres = normalizar.normalizar_presupuesto([_abrir(c.archivo, c.nombre_original) for c in por_tipo[Carga.PRESUPUESTO]], cfg)
        if len(mov):
            calculos.asignar_lineas(mov, cfg)  # falla si hay cuentas sin línea en el plan de cuentas
            fincas = set(mov['Finca']) - set(cfg['hoteles']['Finca'])
            if fincas:
                raise normalizar.ErrorDeCarga(f'Fincas que no están en la configuración: {sorted(fincas)}')
    except (ValueError, KeyError) as e:
        pendientes = [c for c in vigentes if c.estado == 'pendiente']
        for c in pendientes:
            c.estado, c.mensaje = 'error', str(e)
            c.save(update_fields=['estado', 'mensaje'])
        return False, str(e)

    with transaction.atomic():
        MovimientoContable.objects.filter(empresa=empresa).delete()
        FilaOperador.objects.filter(empresa=empresa).delete()
        FilaPresupuesto.objects.filter(empresa=empresa).delete()
        MovimientoContable.objects.bulk_create([MovimientoContable(
            empresa=empresa, fecha_registro=r['Fecha de registro'].date(),
            fecha_documento=r['Fecha de emisión del documento'].date(),
            num_documento=_texto(r['Nº documento']), num_documento_externo=_texto(r['Nº documento externo']),
            cuenta=str(r['Cuenta contable']), descripcion=_texto(r['Descripción'])[:255],
            importe=_d(r['Importe sin IVA']), iva=_d(r['IVA']), proveedor=_texto(r['Proveedor']),
            finca=_texto(r['Finca']), ceco=_texto(r['Ceco'])) for _, r in mov.iterrows()], batch_size=500)
        FilaOperador.objects.bulk_create([FilaOperador(
            empresa=empresa, mes=r['Fecha'].date(), hotel=r['Id hotel'], departamento=r['Departamento'],
            concepto=r['Concepto'], medida=r['Medida'], valor=_d(r['Valor'], 4),
            linea_informe=_texto(r['Línea del informe']), columna_operador=r['Columna del operador'])
            for _, r in pms.iterrows()], batch_size=500)
        FilaPresupuesto.objects.bulk_create([FilaPresupuesto(
            empresa=empresa, mes=r['Fecha'].date(), hotel=r['Id hotel'], linea=r['Línea'], tipo=r['Tipo'],
            importe=_d(r['Presupuesto'])) for _, r in pres.iterrows()], batch_size=500)
        for c in vigentes:
            if c.estado != 'ok':
                c.estado, c.mensaje = 'ok', ''
                c.save(update_fields=['estado', 'mensaje'])
    return True, f'{len(mov)} movimientos, {len(pms)} filas del operador y {len(pres)} de presupuesto procesados.'


def registrar_carga(empresa, usuario, tipo, archivo):
    """Guarda un archivo subido. Si ya había uno con el mismo nombre y tipo, el anterior queda sustituido."""
    Carga.objects.filter(empresa=empresa, tipo=tipo, nombre_original=archivo.name).exclude(
        estado='sustituida').update(estado='sustituida')
    return Carga.objects.create(empresa=empresa, usuario=usuario, tipo=tipo, archivo=archivo, nombre_original=archivo.name)


def datos_empresa(empresa):
    """Devuelve el modelo común de la empresa como tablas con los nombres de 07_estructura_datos."""
    mov = pd.DataFrame(list(MovimientoContable.objects.filter(empresa=empresa).values(
        'fecha_registro', 'fecha_documento', 'num_documento', 'cuenta', 'descripcion', 'importe', 'iva',
        'proveedor', 'finca', 'ceco')))
    if len(mov):
        mov = mov.rename(columns={
            'fecha_registro': 'Fecha de registro', 'fecha_documento': 'Fecha de emisión del documento',
            'num_documento': 'Nº documento', 'cuenta': 'Cuenta contable', 'descripcion': 'Descripción',
            'importe': 'Importe sin IVA', 'iva': 'IVA', 'proveedor': 'Proveedor', 'finca': 'Finca', 'ceco': 'Ceco'})
        mov['Importe sin IVA'] = mov['Importe sin IVA'].astype(float)
        mov['Fecha de registro'] = pd.to_datetime(mov['Fecha de registro'])
        mov['Fecha de emisión del documento'] = pd.to_datetime(mov['Fecha de emisión del documento'])
        mov['Ceco'] = mov['Ceco'].replace('', None)
    pms = pd.DataFrame(list(FilaOperador.objects.filter(empresa=empresa).values(
        'mes', 'hotel', 'concepto', 'medida', 'valor', 'linea_informe')))
    if len(pms):
        pms = pms.rename(columns={'mes': 'Fecha', 'hotel': 'Id hotel', 'concepto': 'Concepto', 'medida': 'Medida',
                                  'valor': 'Valor', 'linea_informe': 'Línea del informe'})
        pms['Valor'] = pms['Valor'].astype(float)
        pms['Fecha'] = pd.to_datetime(pms['Fecha'])
        pms['Línea del informe'] = pms['Línea del informe'].replace('', None)
    return mov, pms


def presupuesto_empresa(empresa):
    pres = pd.DataFrame(list(FilaPresupuesto.objects.filter(empresa=empresa).values('mes', 'hotel', 'linea', 'tipo', 'importe')))
    if len(pres):
        pres = pres.rename(columns={'mes': 'Fecha', 'hotel': 'Id hotel', 'linea': 'Línea', 'tipo': 'Tipo', 'importe': 'Presupuesto'})
        pres['Presupuesto'] = pres['Presupuesto'].astype(float)
        pres['Fecha'] = pd.to_datetime(pres['Fecha'])
    return pres
