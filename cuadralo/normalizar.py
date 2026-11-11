"""Cuádralo · normalizador (paso 1 del MVP).
Convierte los Excels de origen (informe del operador, movimientos de Business Central y presupuesto)
en el modelo común descrito en 07_estructura_datos.
Uso: python normalizar.py datos_origen configuracion_grupo_demo.xlsx salida.xlsx"""
import sys, glob, re
import pandas as pd

MESES = {m: i for i, m in enumerate(['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'], 1)}
MESES_LARGOS = {m: i for i, m in enumerate(['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'], 1)}

def leer_con_cabecera(path, primera_col, sheet_name=0):
    """Lee un Excel cuya cabecera puede no estar en la fila 1: busca la fila que empieza por `primera_col`."""
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
    fila = raw.index[raw.iloc[:, 0].astype(str).str.strip() == primera_col][0]
    df = raw.iloc[fila + 1:].copy(); df.columns = raw.iloc[fila].tolist()
    return df.dropna(how='all').reset_index(drop=True), raw

def normalizar_operador(carpeta, cfg):
    hoteles = cfg['hoteles']; conceptos = cfg['conceptos_pms']
    nombre2id = dict(zip(hoteles['Hotel'], hoteles['Id hotel']))
    filas = []
    for path in sorted(glob.glob(f'{carpeta}/operador/*.xlsx')):
        df, raw = leer_con_cabecera(path, 'Hotel')
        titulo = str(raw.iloc[0, 0]).lower()
        mes = next(v for k, v in MESES_LARGOS.items() if k in titulo)
        anio = int(re.search(r'(20\d\d)', titulo).group(1))
        fecha = pd.Timestamp(anio, mes, 1)
        desconocidas = set(df.columns) - {'Hotel'} - set(conceptos['Columna del operador'])
        if desconocidas:
            raise ValueError(f'{path}: columnas sin mapear {desconocidas}')
        for _, r in df.iterrows():
            hid = nombre2id[r['Hotel']]
            for _, c in conceptos.iterrows():
                if c['Id hotel'] not in ('(todos)', hid): continue
                filas.append({'Fecha': fecha, 'Id hotel': hid, 'Departamento': c['Departamento'], 'Concepto': c['Concepto'],
                              'Medida': c['Medida'], 'Valor': float(r[c['Columna del operador']]),
                              'Línea del informe': c['Línea del informe (para cuadrar con BC)'],
                              'Columna del operador': c['Columna del operador']})
    return pd.DataFrame(filas)

def normalizar_bc(carpeta):
    partes = [leer_con_cabecera(p, 'Nº mov.')[0] for p in sorted(glob.glob(f'{carpeta}/business_central/*.xlsx'))]
    bc = pd.concat(partes, ignore_index=True)
    cuenta = bc['Nº cuenta'].astype(str)
    signo = cuenta.str.startswith('7').map({True: -1, False: 1})  # BC: ingresos en negativo (haber)
    imp = pd.to_numeric(bc['Importe']) * signo; iva = pd.to_numeric(bc['Importe IVA']) * signo
    return pd.DataFrame({
        'Fecha de registro': pd.to_datetime(bc['Fecha registro']),
        'Fecha de emisión del documento': pd.to_datetime(bc['Fecha documento']),
        'Nº documento': bc['Nº documento'], 'Nº documento externo': bc['Nº documento externo'],
        'Cuenta contable': cuenta.astype(int), 'Descripción': bc['Descripción'],
        'Importe sin IVA': imp.round(2), 'IVA': iva.round(2), 'Importe total': (imp + iva).round(2),
        'Proveedor': bc['Nombre origen'], 'Finca': bc['Cód. dimensión 1 (FINCA)'], 'Ceco': bc['Cód. dimensión 2 (CECO)'],
        'EFE código': bc['Cód. EFE']})

def normalizar_presupuesto(carpeta, cfg):
    nombre2id = dict(zip(cfg['hoteles']['Hotel'], cfg['hoteles']['Id hotel']))
    filas = []
    for path in sorted(glob.glob(f'{carpeta}/presupuesto/*.xlsx')):
        anio = int(re.search(r'(20\d\d)', path).group(1))
        for hoja in pd.ExcelFile(path).sheet_names:
            df, _ = leer_con_cabecera(path, 'Bloque', sheet_name=hoja)
            for _, r in df.iterrows():
                for col in df.columns[2:]:
                    if pd.isna(r[col]): continue
                    filas.append({'Fecha': pd.Timestamp(anio, MESES[col.lower()[:3]], 1), 'Id hotel': nombre2id[hoja],
                                  'Línea': r['Línea'], 'Tipo': r['Bloque'], 'Presupuesto': int(r[col])})
    return pd.DataFrame(filas)

if __name__ == '__main__':
    carpeta, cfg_path, salida = sys.argv[1:4]
    cfg = pd.read_excel(cfg_path, sheet_name=None)
    with pd.ExcelWriter(salida) as w:
        normalizar_bc(carpeta).to_excel(w, sheet_name='mov_contabilidad', index=False)
        normalizar_operador(carpeta, cfg).to_excel(w, sheet_name='pms', index=False)
        normalizar_presupuesto(carpeta, cfg).to_excel(w, sheet_name='presupuesto', index=False)
    print('Normalizado en', salida)
