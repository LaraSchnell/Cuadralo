"""Cuádralo · normalizador.

Convierte los Excels de origen (informe del operador, movimientos de Business Central y presupuesto)
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


class ErrorDeCarga(ValueError):
    """Error que se enseña tal cual al usuario: el archivo no tiene el formato esperado."""


def _nombre(archivo):
    return getattr(archivo, 'name', str(archivo))


def leer_con_cabecera(archivo, primera_col, sheet_name=0):
    """Lee un Excel cuya cabecera puede no estar en la fila 1: busca la fila que empieza por `primera_col`."""
    raw = pd.read_excel(archivo, sheet_name=sheet_name, header=None)
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
    for archivo in archivos:
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
                    'Columna del operador': c['Columna del operador'],
                })
    return pd.DataFrame(filas)


def normalizar_bc(archivos):
    partes = [leer_con_cabecera(a, 'Nº mov.')[0] for a in archivos]
    if not partes:
        return pd.DataFrame()
    bc = pd.concat(partes, ignore_index=True)
    cuenta = bc['Nº cuenta'].astype(str)
    signo = cuenta.str.startswith('7').map({True: -1, False: 1})  # BC: ingresos en negativo (haber)
    imp = pd.to_numeric(bc['Importe']) * signo
    iva = pd.to_numeric(bc['Importe IVA']) * signo
    return pd.DataFrame({
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
    })


def normalizar_presupuesto(archivos, cfg):
    nombre2id = dict(zip(cfg['hoteles']['Hotel'], cfg['hoteles']['Id hotel']))
    filas = []
    for archivo in archivos:
        anio = re.search(r'(20\d\d)', _nombre(archivo))
        if anio is None:
            raise ErrorDeCarga(f'{_nombre(archivo)}: el nombre del archivo debe llevar el año (Presupuesto_2026.xlsx).')
        anio = int(anio.group(1))
        hojas = pd.ExcelFile(archivo).sheet_names
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
                        'Presupuesto': int(r[col]),
                    })
    return pd.DataFrame(filas)


def archivos_de(carpeta, sub):
    return sorted(glob.glob(os.path.join(carpeta, sub, '*.xlsx')))


if __name__ == '__main__':
    carpeta, cfg_path, salida = sys.argv[1:4]
    cfg = pd.read_excel(cfg_path, sheet_name=None)
    with pd.ExcelWriter(salida) as w:
        normalizar_bc(archivos_de(carpeta, 'business_central')).to_excel(w, sheet_name='mov_contabilidad', index=False)
        normalizar_operador(archivos_de(carpeta, 'operador'), cfg).to_excel(w, sheet_name='pms', index=False)
        normalizar_presupuesto(archivos_de(carpeta, 'presupuesto'), cfg).to_excel(w, sheet_name='presupuesto', index=False)
    print('Normalizado en', salida)
