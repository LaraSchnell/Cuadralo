"""Cuádralo · normalizador.

Convierte los Excels de origen (informe del operador, movimientos de Business Central, presupuesto y reservas)
en el modelo común descrito en 07_estructura_datos.

Cada función recibe una lista de archivos: rutas o archivos abiertos (lo que llega desde la web).
Uso por consola: python -m cuadralo.normalizar datos_origen configuracion_grupo_demo.xlsx salida.xlsx
"""
import glob
import os
import re
import sys

import pandas as pd

MESES_CORTOS = {m: i for i, m in enumerate(
    ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'], 1)}
MESES_LARGOS = {m: i for i, m in enumerate(
    ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
     'septiembre', 'octubre', 'noviembre', 'diciembre'], 1)}


# Lector de Excel: calamine es unas 4 veces más rápido que openpyxl y da los mismos datos
# (medido con 175.000 apuntes: 4 s frente a 17 s). Ver "Requisitos de rendimiento" en CLAUDE.md.
MOTOR_EXCEL = 'calamine'


class ErrorDeCarga(ValueError):
    """Error que se enseña tal cual al usuario: el archivo no tiene el formato esperado."""


def _nombre(archivo):
    return getattr(archivo, 'name', str(archivo))


def leer_con_cabecera(archivo, primera_col, sheet_name=0):
    """Lee un Excel cuya cabecera puede no estar en la fila 1: busca la fila que empieza por `primera_col`."""
    raw = pd.read_excel(archivo, sheet_name=sheet_name, header=None, engine=MOTOR_EXCEL)
    filas = raw.index[raw.iloc[:, 0].astype(str).str.strip() == primera_col]
    if len(filas) == 0:
        raise ErrorDeCarga(f'{_nombre(archivo)}: no encuentro la columna "{primera_col}".')
    fila = filas[0]
    df = raw.iloc[fila + 1:].copy()
    df.columns = raw.iloc[fila].tolist()
    return df.dropna(how='all').reset_index(drop=True), raw


def normalizar_operador(archivos, cfg):
    hoteles = cfg['hoteles']
    conceptos = cfg['conceptos_pms']
    nombre2id = dict(zip(hoteles['Hotel'], hoteles['Id hotel']))
    filas = []
    for i, archivo in enumerate(archivos):
        df, raw = leer_con_cabecera(archivo, 'Hotel')
        titulo = str(raw.iloc[0, 0]).lower()
        mes = next((v for k, v in MESES_LARGOS.items() if k in titulo), None)
        anio = re.search(r'(20\d\d)', titulo)
        if mes is None or anio is None:
            raise ErrorDeCarga(f'{_nombre(archivo)}: no encuentro el mes y el año en el título del informe.')
        fecha = pd.Timestamp(int(anio.group(1)), mes, 1)
        desconocidas = set(df.columns) - {'Hotel'} - set(conceptos['Columna del operador'])
        if desconocidas:
            raise ErrorDeCarga(f'{_nombre(archivo)}: columnas sin mapear {sorted(desconocidas)}.')
        for _, r in df.iterrows():
            if r['Hotel'] not in nombre2id:
                raise ErrorDeCarga(f'{_nombre(archivo)}: hotel desconocido "{r["Hotel"]}".')
            hid = nombre2id[r['Hotel']]
            for _, c in conceptos.iterrows():
                if c['Id hotel'] not in ('(todos)', hid):
                    continue
                filas.append({
                    'Fecha': fecha, 'Id hotel': hid, 'Departamento': c['Departamento'],
                    'Concepto': c['Concepto'], 'Medida': c['Medida'],
                    'Valor': float(r[c['Columna del operador']]),
                    'Línea del informe': c['Línea del informe (para cuadrar con BC)'],
                    'Columna del operador': c['Columna del operador'], 'Archivo': i,
                })
    return pd.DataFrame(filas)


COLUMNAS_BC = ['Nº mov.', 'Fecha registro', 'Fecha documento', 'Nº documento', 'Nº documento externo', 'Nº cuenta',
               'Descripción', 'Importe', 'Importe IVA', 'Nombre origen', 'Cód. dimensión 1 (FINCA)',
               'Cód. dimensión 2 (CECO)', 'Cód. EFE']


def normalizar_bc(archivos):
    """Movimientos de Business Central → mov_contabilidad.

    Columna «Archivo»: posición del archivo en la lista (sirve para avisar de meses repetidos).
    Un mismo movimiento (mismo «Nº mov.», que en Business Central es único) que llega en varios archivos se cuenta
    una sola vez: manda el del archivo más reciente (el último de la lista). Las columnas de más se ignoran.
    """
    partes = []
    for i, a in enumerate(archivos):
        df = leer_con_cabecera(a, 'Nº mov.')[0]
        faltan = [c for c in COLUMNAS_BC if c not in df.columns]
        if faltan:
            raise ErrorDeCarga(f'{_nombre(a)}: al export de Business Central le faltan las columnas {faltan}. '
                               'Revisa que es el informe de movimientos de contabilidad y que no se ha cambiado su diseño.')
        partes.append(df.assign(Archivo=i))
    if not partes:
        return pd.DataFrame()
    bc = pd.concat(partes, ignore_index=True)
    # Qué meses y fincas trae cada archivo, antes de quitar repetidos (para avisar de meses cargados dos veces)
    cobertura = pd.DataFrame({'mes': pd.to_datetime(bc['Fecha registro']).dt.to_period('M'),
                              'hotel': bc['Cód. dimensión 1 (FINCA)'], 'archivo': bc['Archivo']}).drop_duplicates()
    bc = bc.drop_duplicates(subset='Nº mov.', keep='last').reset_index(drop=True)
    cuenta = bc['Nº cuenta'].astype(str)
    signo = cuenta.str.startswith('7').map({True: -1, False: 1})  # BC: ingresos en negativo (haber)
    imp = pd.to_numeric(bc['Importe']) * signo
    iva = pd.to_numeric(bc['Importe IVA']) * signo
    out = pd.DataFrame({
        'Fecha de registro': pd.to_datetime(bc['Fecha registro']),
        'Fecha de emisión del documento': pd.to_datetime(bc['Fecha documento']),
        'Nº documento': bc['Nº documento'],
        'Nº documento externo': bc['Nº documento externo'],
        'Cuenta contable': cuenta.astype(int),
        'Descripción': bc['Descripción'],
        'Importe sin IVA': imp.round(2), 'IVA': iva.round(2), 'Importe total': (imp + iva).round(2),
        'Proveedor': bc['Nombre origen'],
        'Finca': bc['Cód. dimensión 1 (FINCA)'],
        'Ceco': bc['Cód. dimensión 2 (CECO)'],
        'EFE código': bc['Cód. EFE'],
        'Archivo': bc['Archivo'],
    })
    out.attrs['cobertura'] = cobertura
    return out


def normalizar_presupuesto(archivos, cfg):
    nombre2id = dict(zip(cfg['hoteles']['Hotel'], cfg['hoteles']['Id hotel']))
    filas = []
    for i, archivo in enumerate(archivos):
        anio = re.search(r'(20\d\d)', _nombre(archivo))
        if anio is None:
            raise ErrorDeCarga(f'{_nombre(archivo)}: el nombre del archivo debe llevar el año (Presupuesto_2026.xlsx).')
        anio = int(anio.group(1))
        hojas = pd.ExcelFile(archivo, engine=MOTOR_EXCEL).sheet_names
        for hoja in hojas:
            if hasattr(archivo, 'seek'):
                archivo.seek(0)
            df, _ = leer_con_cabecera(archivo, 'Bloque', sheet_name=hoja)
            for _, r in df.iterrows():
                for col in df.columns[2:]:
                    if pd.isna(r[col]):
                        continue
                    filas.append({
                        'Fecha': pd.Timestamp(anio, MESES_CORTOS[str(col).lower()[:3]], 1),
                        'Id hotel': nombre2id[hoja], 'Línea': r['Línea'], 'Tipo': r['Bloque'],
                        'Presupuesto': int(r[col]), 'Archivo': i,
                    })
    return pd.DataFrame(filas)


# Reservas (informe de reservas o API de Mews). Estados de Mews que cuentan como estancia y como cancelación.
ESTADOS_ESTANCIA = {'Processed', 'Started', 'Confirmed'}
ESTADOS_CANCELADA = {'Canceled'}
CAMPOS_RESERVA_OBLIGATORIOS = ['Hotel', 'Nº reserva', 'Estado', 'Origen', 'Llegada', 'Salida', 'Ingresos alojamiento']


def _canal_clave(origen, detalle, agencia):
    if agencia:
        return agencia
    return f'{origen} · {detalle}' if detalle else origen


def normalizar_reservas(archivos, cfg):
    """Reservas → una fila por reserva con canal, segmento, noches, personas e ingresos. Sin nombres de huéspedes.

    Las columnas se traducen con la hoja columnas_reservas y el canal con la hoja canales de la configuración:
    si llega un canal que no está en la configuración, la carga se para y avisa (igual que con el operador).
    """
    if not archivos:
        return pd.DataFrame()
    mapa = dict(zip(cfg['columnas_reservas']['Columna de Mews'], cfg['columnas_reservas']['Campo']))
    canales = cfg['canales'].set_index('Valor en Mews')
    nombre2id = dict(zip(cfg['hoteles']['Hotel'], cfg['hoteles']['Id hotel']))
    partes = []
    for archivo in archivos:
        df = pd.read_excel(archivo, engine=MOTOR_EXCEL).rename(columns=mapa)
        faltan = [c for c in CAMPOS_RESERVA_OBLIGATORIOS if c not in df.columns]
        if faltan:
            raise ErrorDeCarga(f'{_nombre(archivo)}: faltan las columnas {faltan} (revisa la hoja columnas_reservas).')
        hoteles = set(df['Hotel']) - set(nombre2id)
        if hoteles:
            raise ErrorDeCarga(f'{_nombre(archivo)}: hoteles desconocidos {sorted(hoteles)}.')
        partes.append(df)
    df = pd.concat(partes, ignore_index=True)
    # La misma reserva en varios archivos: manda la del más reciente (el último de la lista)
    df = df.drop_duplicates(subset='Nº reserva', keep='last').reset_index(drop=True)
    texto = lambda col: df[col].fillna('').astype(str).str.strip() if col in df.columns else pd.Series('', index=df.index)
    origen, detalle, agencia = texto('Origen'), texto('Detalle origen'), texto('Agencia')
    clave = [_canal_clave(o, d, a) for o, d, a in zip(origen, detalle, agencia)]
    desconocidos = sorted(set(clave) - set(canales.index))
    if desconocidos:
        raise ErrorDeCarga(f'Canales de reserva sin configurar en la hoja canales: {desconocidos}.')
    llegada = pd.to_datetime(df['Llegada']).dt.normalize()
    salida = pd.to_datetime(df['Salida']).dt.normalize()
    creada = pd.to_datetime(df['Fecha de creación']) if 'Fecha de creación' in df.columns else pd.Series(pd.NaT, index=df.index)
    estado = texto('Estado')
    num = lambda col: pd.to_numeric(df[col], errors='coerce').fillna(0) if col in df.columns else pd.Series(0, index=df.index)
    adultos, ninos = num('Adultos').astype(int), num('Niños').astype(int)
    out = pd.DataFrame({
        'Id hotel': df['Hotel'].map(nombre2id), 'Nº reserva': texto('Nº reserva'), 'Estado': estado,
        'Estancia': estado.isin(ESTADOS_ESTANCIA), 'Cancelada': estado.isin(ESTADOS_CANCELADA),
        'Origen': origen, 'Detalle origen': detalle, 'Agencia': agencia,
        'Canal': [canales.loc[k, 'Canal'] for k in clave], 'Tipo de canal': [canales.loc[k, 'Tipo de canal'] for k in clave],
        'Segmento': texto('Segmento'), 'Tarifa': texto('Tarifa'), 'Tipo de habitación': texto('Tipo de habitación'),
        'Fecha de creación': creada,
        'Fecha de cancelación': pd.to_datetime(df['Fecha de cancelación']) if 'Fecha de cancelación' in df.columns else pd.NaT,
        'Llegada': llegada, 'Salida': salida, 'Noches': (salida - llegada).dt.days.clip(lower=0),
        'Adultos': adultos, 'Niños': ninos, 'Personas': adultos + ninos,
        'Nacionalidad': texto('Nacionalidad'), 'Motivo': texto('Motivo'),
        'Ingresos alojamiento': num('Ingresos alojamiento').astype(float).round(2),
        'Antelación (días)': (llegada - creada.dt.normalize()).dt.days,
    })
    return out


def archivos_de(carpeta, sub):
    return sorted(glob.glob(os.path.join(carpeta, sub, '*.xlsx')))


if __name__ == '__main__':
    carpeta, cfg_path, salida = sys.argv[1:4]
    cfg = pd.read_excel(cfg_path, sheet_name=None)
    with pd.ExcelWriter(salida) as w:
        normalizar_bc(archivos_de(carpeta, 'business_central')).to_excel(w, sheet_name='mov_contabilidad', index=False)
        normalizar_operador(archivos_de(carpeta, 'operador'), cfg).to_excel(w, sheet_name='pms', index=False)
        normalizar_presupuesto(archivos_de(carpeta, 'presupuesto'), cfg).to_excel(w, sheet_name='presupuesto', index=False)
        normalizar_reservas(archivos_de(carpeta, 'reservas'), cfg).to_excel(w, sheet_name='reservas', index=False)
    print('Normalizado en', salida)
