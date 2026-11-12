"""Procesado de las cargas de una empresa: archivos subidos → modelo común en la base de datos."""
import io
from decimal import Decimal

import pandas as pd
from django.db import transaction

from cuadralo import calculos, normalizar
from .models import Carga, FilaOperador, FilaPresupuesto, MovimientoContable

TAMANO_LOTE = 1000  # filas por inserción masiva; mssql-django reparte cada lote para no pasar de 2.100 parámetros


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

    # Las filas se construyen recorriendo columnas con zip (no con iterrows, que es unas 10 veces más lento)
    # y se guardan con inserción masiva (bulk_create). Ver "Requisitos de rendimiento" en CLAUDE.md.
    with transaction.atomic():
        MovimientoContable.objects.filter(empresa=empresa).delete()
        FilaOperador.objects.filter(empresa=empresa).delete()
        FilaPresupuesto.objects.filter(empresa=empresa).delete()
        if len(mov):
            MovimientoContable.objects.bulk_create([MovimientoContable(
                empresa=empresa, fecha_registro=f_reg.date(), fecha_documento=f_doc.date(),
                num_documento=_texto(n_doc), num_documento_externo=_texto(n_ext), cuenta=str(cuenta),
                descripcion=_texto(desc)[:255], importe=_d(imp), iva=_d(iva), proveedor=_texto(prov),
                finca=_texto(finca), ceco=_texto(ceco))
                for f_reg, f_doc, n_doc, n_ext, cuenta, desc, imp, iva, prov, finca, ceco in zip(
                    mov['Fecha de registro'], mov['Fecha de emisión del documento'], mov['Nº documento'],
                    mov['Nº documento externo'], mov['Cuenta contable'], mov['Descripción'],
                    mov['Importe sin IVA'], mov['IVA'], mov['Proveedor'], mov['Finca'], mov['Ceco'])],
                batch_size=TAMANO_LOTE)
        if len(pms):
            FilaOperador.objects.bulk_create([FilaOperador(
                empresa=empresa, mes=fecha.date(), hotel=hotel, departamento=dep, concepto=concepto,
                medida=medida, valor=_d(valor, 4), linea_informe=_texto(linea), columna_operador=columna)
                for fecha, hotel, dep, concepto, medida, valor, linea, columna in zip(
                    pms['Fecha'], pms['Id hotel'], pms['Departamento'], pms['Concepto'], pms['Medida'],
                    pms['Valor'], pms['Línea del informe'], pms['Columna del operador'])],
                batch_size=TAMANO_LOTE)
        if len(pres):
            FilaPresupuesto.objects.bulk_create([FilaPresupuesto(
                empresa=empresa, mes=fecha.date(), hotel=hotel, linea=linea, tipo=tipo, importe=_d(importe))
                for fecha, hotel, linea, tipo, importe in zip(
                    pres['Fecha'], pres['Id hotel'], pres['Línea'], pres['Tipo'], pres['Presupuesto'])],
                batch_size=TAMANO_LOTE)
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
        'fecha_registro', 'fecha_documento', 'num_documento', 'num_documento_externo', 'cuenta', 'descripcion',
        'importe', 'iva', 'proveedor', 'finca', 'ceco')))
    if len(mov):
        mov = mov.rename(columns={
            'fecha_registro': 'Fecha de registro', 'fecha_documento': 'Fecha de emisión del documento',
            'num_documento': 'Nº documento', 'num_documento_externo': 'Nº documento externo',
            'cuenta': 'Cuenta contable', 'descripcion': 'Descripción',
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
    return mov, pms


def presupuesto_empresa(empresa):
    pres = pd.DataFrame(list(FilaPresupuesto.objects.filter(empresa=empresa).values('mes', 'hotel', 'linea', 'tipo', 'importe')))
    if len(pres):
        pres = pres.rename(columns={'mes': 'Fecha', 'hotel': 'Id hotel', 'linea': 'Línea', 'tipo': 'Tipo',
                                    'importe': 'Presupuesto'})
        pres['Presupuesto'] = pres['Presupuesto'].astype(float)
    return pres
