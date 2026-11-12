"""Procesado de las cargas de una empresa: archivos subidos → modelo común en la base de datos."""
import io
from decimal import Decimal

import pandas as pd
from django.db import transaction

from cuadralo import calculos, informe, normalizar
from . import precalculo
from .models import Carga, FilaOperador, FilaPresupuesto, MovimientoContable, Reserva

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
        # Reservas: es la tabla más grande. Si ya hay reservas guardadas, solo se leen los archivos nuevos y sus
        # reservas sustituyen a las que tengan el mismo número; así una subida en directo tarda segundos.
        res_cargas = por_tipo[Carga.RESERVAS]
        nuevas_res = [c for c in res_cargas if c.estado == 'pendiente']
        incremental = Reserva.objects.filter(empresa=empresa).exists()
        if incremental:
            res = normalizar.normalizar_reservas([_abrir(c.archivo, c.nombre_original) for c in nuevas_res], cfg) \
                if nuevas_res else None   # None = no tocar las reservas guardadas
        else:
            res = normalizar.normalizar_reservas([_abrir(c.archivo, c.nombre_original) for c in res_cargas], cfg) \
                if res_cargas else pd.DataFrame()
        lineas = None
        if len(mov):
            lineas = calculos.asignar_lineas(mov, cfg)  # falla si hay cuentas sin línea en el plan de cuentas
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
        if res is not None and incremental:
            numeros = list(res['Nº reserva'].unique())
            for i in range(0, len(numeros), 1000):   # por tandas: SQL Server no admite listas muy largas
                Reserva.objects.filter(empresa=empresa, numero__in=numeros[i:i + 1000]).delete()
        elif res is not None:
            Reserva.objects.filter(empresa=empresa).delete()
        if len(mov):
            MovimientoContable.objects.bulk_create([MovimientoContable(
                empresa=empresa, fecha_registro=f_reg.date(), fecha_documento=f_doc.date(),
                num_documento=_texto(n_doc), num_documento_externo=_texto(n_ext), cuenta=str(cuenta),
                descripcion=_texto(desc)[:255], importe=_d(imp), iva=_d(iva), proveedor=_texto(prov),
                finca=_texto(finca), ceco=_texto(ceco), hotel=_texto(hotel), mes=mes_.date(), linea=_texto(linea),
                bloque=_texto(bloque))
                for f_reg, f_doc, n_doc, n_ext, cuenta, desc, imp, iva, prov, finca, ceco, hotel, mes_, linea, bloque in zip(
                    mov['Fecha de registro'], mov['Fecha de emisión del documento'], mov['Nº documento'],
                    mov['Nº documento externo'], mov['Cuenta contable'], mov['Descripción'],
                    mov['Importe sin IVA'], mov['IVA'], mov['Proveedor'], mov['Finca'], mov['Ceco'],
                    lineas['Id hotel'], lineas['Mes'], lineas['Línea'], lineas['Bloque'])],
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
        if res is not None and len(res):
            fecha = lambda v: None if pd.isna(v) else v.tz_localize('UTC').to_pydatetime()  # Mews da las fechas en UTC
            Reserva.objects.bulk_create([Reserva(
                empresa=empresa, hotel=hotel, numero=numero, estado=estado, estancia=bool(estancia), cancelada=bool(cancelada),
                origen=origen, detalle_origen=detalle, agencia=agencia, canal=canal, tipo_canal=tipo, segmento=segmento,
                tarifa=tarifa, tipo_habitacion=hab, fecha_creacion=fecha(creada), fecha_cancelacion=fecha(cancelacion),
                llegada=llegada.date(), salida=salida.date(), noches=int(noches), adultos=int(adultos), ninos=int(ninos),
                nacionalidad=pais, motivo=motivo, ingresos=_d(ingresos))
                for (hotel, numero, estado, estancia, cancelada, origen, detalle, agencia, canal, tipo, segmento, tarifa, hab,
                     creada, cancelacion, llegada, salida, noches, adultos, ninos, pais, motivo, ingresos) in zip(
                    res['Id hotel'], res['Nº reserva'], res['Estado'], res['Estancia'], res['Cancelada'], res['Origen'],
                    res['Detalle origen'], res['Agencia'], res['Canal'], res['Tipo de canal'], res['Segmento'], res['Tarifa'],
                    res['Tipo de habitación'], res['Fecha de creación'], res['Fecha de cancelación'], res['Llegada'],
                    res['Salida'], res['Noches'], res['Adultos'], res['Niños'], res['Nacionalidad'], res['Motivo'],
                    res['Ingresos alojamiento'])],
                batch_size=TAMANO_LOTE)
        for c in vigentes:
            if c.estado != 'ok':
                c.estado, c.mensaje = 'ok', ''
                c.save(update_fields=['estado', 'mensaje'])
    # Precálculo: las tablas del informe se calculan aquí una vez; la web solo las lee.
    if len(mov) and len(pms):
        res_todas = res if (res is not None and not incremental) else reservas_empresa(empresa)
        precalculo.guardar(empresa, informe.Datos(mov, pms, pres, cfg, res_todas))
        # Las desviaciones de los últimos 3 meses se dejan calculadas (las demás, la primera vez que se piden)
        datos = precalculo.cargar(empresa, cfg)
        for mes in datos.meses[:3]:
            for hotel in datos.nombres:
                datos.desviaciones(hotel, mes)
    n_res = Reserva.objects.filter(empresa=empresa).count()
    return True, (f'{len(mov)} movimientos, {len(pms)} filas del operador, {len(pres)} de presupuesto'
                  f' y {n_res} reservas procesados.')


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


def reservas_empresa(empresa):
    """Reservas de la empresa con los nombres de columna del normalizador."""
    r = pd.DataFrame(list(Reserva.objects.filter(empresa=empresa).values(
        'hotel', 'numero', 'estado', 'estancia', 'cancelada', 'origen', 'detalle_origen', 'agencia', 'canal', 'tipo_canal',
        'segmento', 'tarifa', 'tipo_habitacion', 'fecha_creacion', 'fecha_cancelacion', 'llegada', 'salida', 'noches',
        'adultos', 'ninos', 'nacionalidad', 'motivo', 'ingresos')))
    if len(r) == 0:
        return r
    r = r.rename(columns={
        'hotel': 'Id hotel', 'numero': 'Nº reserva', 'estado': 'Estado', 'estancia': 'Estancia', 'cancelada': 'Cancelada',
        'origen': 'Origen', 'detalle_origen': 'Detalle origen', 'agencia': 'Agencia', 'canal': 'Canal',
        'tipo_canal': 'Tipo de canal', 'segmento': 'Segmento', 'tarifa': 'Tarifa', 'tipo_habitacion': 'Tipo de habitación',
        'fecha_creacion': 'Fecha de creación', 'fecha_cancelacion': 'Fecha de cancelación', 'llegada': 'Llegada',
        'salida': 'Salida', 'noches': 'Noches', 'adultos': 'Adultos', 'ninos': 'Niños', 'nacionalidad': 'Nacionalidad',
        'motivo': 'Motivo', 'ingresos': 'Ingresos alojamiento'})
    r['Ingresos alojamiento'] = r['Ingresos alojamiento'].astype(float)
    for col in ('Llegada', 'Salida'):
        r[col] = pd.to_datetime(r[col])
    for col in ('Fecha de creación', 'Fecha de cancelación'):
        r[col] = pd.to_datetime(r[col], utc=True).dt.tz_localize(None)
    r['Personas'] = r['Adultos'] + r['Niños']
    r['Antelación (días)'] = (r['Llegada'] - r['Fecha de creación'].dt.normalize()).dt.days
    return r
