"""Procesado de las cargas de una empresa: archivos subidos → modelo común en la base de datos."""
import hashlib
import io
from decimal import Decimal

import pandas as pd
from django.db import transaction

from cuadralo import calculos, informe, normalizar, revision, sugerencias
from . import precalculo
from .models import (Carga, FilaOperador, FilaPresupuesto, MovimientoContable, Reserva, ResultadoDesviacion,
                     ResultadoEmpresa)

TAMANO_LOTE = 1000  # filas por inserción masiva; mssql-django reparte cada lote para no pasar de 2.100 parámetros


def _abrir(field_file, nombre):
    """Copia el archivo (local o Blob) a memoria con su nombre original, como lo espera el normalizador."""
    with field_file.open('rb') as f:
        buf = io.BytesIO(f.read())
    buf.name = nombre
    return buf


def leer_configuracion(empresa):
    """Excel de configuración de la empresa + lo confirmado en la web (página Revisar y confirmar)."""
    with empresa.configuracion.open('rb') as f:
        cfg = pd.read_excel(io.BytesIO(f.read()), sheet_name=None)
    from .models import MapeoAprobado
    mapeos = MapeoAprobado.objects.filter(empresa=empresa).values_list('tipo', 'clase', 'origen', 'destino')
    return revision.aplicar_mapeos(cfg, list(mapeos))


def revisar_cargas_nuevas(empresa, cfg):
    """Mira los archivos nuevos y, si traen algo desconocido, crea las propuestas y los deja «Por confirmar».

    Devuelve las cargas que se quedan esperando confirmación (no se procesan hasta que alguien confirme).
    """
    from . import segundo_plano
    from .models import Propuesta, RegistroIA
    en_revision = []
    for c in empresa.cargas.filter(estado='pendiente').order_by('creada', 'id'):
        preguntas = revision.detectar(c.tipo, c.nombre_original, _abrir(c.archivo, c.nombre_original), cfg)
        if not preguntas:
            continue
        sugerencias.sugerir(preguntas, registrar_ia=lambda **kw: RegistroIA.objects.create(empresa=empresa, **kw))
        Propuesta.objects.filter(carga=c, estado='pendiente').delete()
        Propuesta.objects.bulk_create([Propuesta(
            empresa=empresa, carga=c, tipo=p['tipo'], clase=p['clase'], clave=p['clave'][:300], modo=p['modo'],
            texto=p['texto'][:500], opciones=p['opciones'], muestras=p['muestras'], sugerencia=p['sugerencia'][:300],
            confianza=p['confianza'], fuente=p['fuente'], motivo=p['motivo'][:300]) for p in preguntas])
        c.estado = 'revisar'
        c.mensaje = f'Hay {len(preguntas)} cosa(s) que este archivo trae y Cuádralo no conoce. Revísalas y confírmalas.'
        c.save(update_fields=['estado', 'mensaje'])
        en_revision.append(c)
    if en_revision:
        segundo_plano.avisar(empresa, en_revision, en_revision[0].mensaje, evento='revision_pendiente')
    return en_revision


def _d(valor, decimales=2):
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return Decimal('0')
    return Decimal(str(round(float(valor), decimales)))


def _texto(valor):
    return '' if valor is None or (isinstance(valor, float) and pd.isna(valor)) else str(valor)


MESES_TXT = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre',
             'noviembre', 'diciembre']


def _mes_txt(ts):
    return f'{MESES_TXT[ts.month - 1]} {ts.year}'


def _repetidos(df, cargas, col_fecha, col_hotel, quitar_antiguos):
    """Meses y hoteles que llegan en más de un archivo del mismo tipo.

    Devuelve {carga: aviso} para la carga más reciente de cada repetición y, si quitar_antiguos, deja solo las filas
    del archivo más reciente para ese mes y hotel (así nada se cuenta dos veces). En Business Central no hace falta
    quitar nada: los movimientos repetidos ya se han quitado por «Nº mov.».
    """
    avisos = {}
    if not len(df):
        return df, avisos
    mes = df[col_fecha].dt.to_period('M')
    pares = df.attrs.get('cobertura')
    if pares is None:
        pares = pd.DataFrame({'mes': mes, 'hotel': df[col_hotel], 'archivo': df['Archivo']}).drop_duplicates()
    for (m, h), grupo in pares.groupby(['mes', 'hotel']):
        archivos = sorted(grupo['archivo'])
        if len(archivos) < 2:
            continue
        nueva = cargas[archivos[-1]]
        antiguas = ', '.join(f'«{cargas[a].nombre_original}»' for a in archivos[:-1])
        avisos.setdefault(nueva, {}).setdefault(antiguas, set()).add((m.to_timestamp(), h))
        if quitar_antiguos:
            df = df[~((mes == m) & (df[col_hotel] == h) & (df['Archivo'] != archivos[-1]))]
            mes = df[col_fecha].dt.to_period('M')
    textos = {}
    for carga, por_archivo in avisos.items():
        partes = []
        for antiguas, pares_ in por_archivo.items():
            meses = sorted({m for m, _ in pares_})
            hoteles = sorted({str(h) for _, h in pares_})
            partes.append(f'{", ".join(_mes_txt(m) for m in meses)} ({", ".join(hoteles)}) ya venía en {antiguas}')
        textos[carga] = ('Revisa si has cargado dos veces el mismo mes: ' + '; '.join(partes) +
                         '. No se cuenta dos veces: se usan los datos de este archivo, el más reciente.')
    return df, textos


def procesar_empresa(empresa):
    """Normaliza todas las cargas vigentes de la empresa y sustituye su modelo común.

    Si algo falla, no se toca lo que ya había y las cargas nuevas quedan en error con el motivo.
    Normalmente se llama desde el procesado en segundo plano (portal/segundo_plano.py), nunca mientras la web espera.
    """
    cfg = leer_configuracion(empresa)
    revisar_cargas_nuevas(empresa, cfg)
    vigentes = list(empresa.cargas.filter(estado__in=['pendiente', 'ok']).order_by('creada', 'id'))
    por_tipo = {t: [c for c in vigentes if c.tipo == t] for t, _ in Carga.TIPOS}
    try:
        cargas_bc, cargas_op, cargas_pres = (por_tipo[Carga.BUSINESS_CENTRAL], por_tipo[Carga.OPERADOR],
                                             por_tipo[Carga.PRESUPUESTO])
        mov = normalizar.normalizar_bc([_abrir(c.archivo, c.nombre_original) for c in cargas_bc], cfg)
        pms = normalizar.normalizar_operador([_abrir(c.archivo, c.nombre_original) for c in cargas_op], cfg)
        pres = normalizar.normalizar_presupuesto([_abrir(c.archivo, c.nombre_original) for c in cargas_pres], cfg)
        # Meses repetidos entre archivos del mismo tipo: aviso y, en operador y presupuesto, manda el más reciente
        mov, av_bc = _repetidos(mov, cargas_bc, 'Fecha de registro', 'Finca', quitar_antiguos=False)
        pms, av_op = _repetidos(pms, cargas_op, 'Fecha', 'Id hotel', quitar_antiguos=True)
        pres, av_pres = _repetidos(pres, cargas_pres, 'Fecha', 'Id hotel', quitar_antiguos=True)
        avisos = {**av_bc, **av_op, **av_pres}
        for tabla in (mov, pms, pres):
            tabla.attrs.clear()
            if 'Archivo' in tabla.columns:
                tabla.drop(columns='Archivo', inplace=True)
        mov, pms, pres = mov.reset_index(drop=True), pms.reset_index(drop=True), pres.reset_index(drop=True)
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
        mensaje = str(e) if isinstance(e, normalizar.ErrorDeCarga) else \
            f'El archivo no tiene el formato esperado ({type(e).__name__}: {e}). Revisa que el tipo elegido es el correcto.'
        pendientes = [c for c in vigentes if c.estado == 'pendiente']
        for c in pendientes:
            c.estado, c.mensaje = 'error', mensaje
            c.save(update_fields=['estado', 'mensaje'])
        return False, mensaje

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
    # Precálculo: las tablas del informe se calculan aquí una vez; la web solo las lee.
    if len(mov) and len(pms):
        res_todas = res if (res is not None and not incremental) else reservas_empresa(empresa)
        precalculo.guardar(empresa, informe.Datos(mov, pms, pres, cfg, res_todas))
        # Las desviaciones de los últimos 3 meses se dejan calculadas (las demás, la primera vez que se piden)
        datos = precalculo.cargar(empresa, cfg)
        for mes in datos.meses[:3]:
            for hotel in datos.nombres:
                datos.desviaciones(hotel, mes)
    else:
        # Sin contabilidad o sin operador no hay informe: se borra el anterior para no enseñar datos eliminados
        ResultadoDesviacion.objects.filter(empresa=empresa).delete()
        ResultadoEmpresa.objects.filter(empresa=empresa).delete()
    # Las cargas pasan a «Procesada» al final, con el informe ya guardado: así la web nunca lee un informe a medias
    for c in vigentes:
        aviso = avisos.get(c, '')
        if c.estado != 'ok' or c.mensaje or c.aviso != aviso:
            c.estado, c.mensaje, c.aviso = 'ok', '', aviso
            c.save(update_fields=['estado', 'mensaje', 'aviso'])
    n_res = Reserva.objects.filter(empresa=empresa).count()
    return True, (f'{len(mov)} movimientos, {len(pms)} filas del operador, {len(pres)} de presupuesto'
                  f' y {n_res} reservas procesados.')


def huella_de(archivo):
    """Huella SHA-256 del contenido: dos archivos idénticos tienen la misma, aunque se llamen distinto."""
    h = hashlib.sha256()
    for trozo in archivo.chunks():
        h.update(trozo)
    archivo.seek(0)
    return h.hexdigest()


def carga_identica(empresa, huella):
    """Carga vigente de la empresa con exactamente el mismo contenido, o None."""
    return (Carga.objects.filter(empresa=empresa, huella=huella, estado__in=['pendiente', 'ok', 'revisar'])
            .select_related('usuario').first())


def registrar_carga(empresa, usuario, tipo, archivo, huella=None):
    """Guarda un archivo subido. Si ya había uno con el mismo nombre y tipo, el anterior queda sustituido."""
    Carga.objects.filter(empresa=empresa, tipo=tipo, nombre_original=archivo.name).exclude(
        estado__in=['sustituida', 'eliminada']).update(estado='sustituida')
    if huella is None and hasattr(archivo, 'chunks'):
        huella = huella_de(archivo)
    return Carga.objects.create(empresa=empresa, usuario=usuario, tipo=tipo, archivo=archivo,
                                nombre_original=archivo.name, huella=huella or '')


def eliminar_carga(carga, usuario):
    """Quita una carga del informe. El registro queda (quién y cuándo) y el archivo se borra del Blob."""
    from django.utils import timezone
    if carga.tipo == Carga.RESERVAS:
        # Las reservas se cargan de forma incremental: se rehacen enteras con los archivos que quedan
        Reserva.objects.filter(empresa=carga.empresa).delete()
    carga.propuestas.filter(estado='pendiente').update(estado='descartada')
    if carga.archivo:
        carga.archivo.delete(save=False)
    carga.estado, carga.eliminada_por, carga.eliminada_en = 'eliminada', usuario, timezone.now()
    carga.save(update_fields=['estado', 'eliminada_por', 'eliminada_en', 'archivo'])


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
