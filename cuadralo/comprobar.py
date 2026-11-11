"""Compara el resultado de normalizar.py con el Excel normalizado de referencia.
Uso: python comprobar.py salida.xlsx Cuadralo_datos_normalizados.xlsx"""
import sys
import pandas as pd
a = pd.read_excel(sys.argv[1], sheet_name=None); b = pd.read_excel(sys.argv[2], sheet_name=None)
claves = {'mov_contabilidad': ['Fecha de registro', 'Nº documento'], 'pms': ['Fecha', 'Id hotel', 'Columna del operador'],
          'presupuesto': ['Fecha', 'Id hotel', 'Línea']}
ok = True
for hoja, k in claves.items():
    cols = [c for c in b[hoja].columns]
    x = a[hoja][cols].sort_values(k).reset_index(drop=True); y = b[hoja][cols].sort_values(k).reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(x, y, check_dtype=False, check_exact=False, atol=0.005)
        print(f'{hoja}: OK ({len(y)} filas)')
    except AssertionError as e:
        ok = False; print(f'{hoja}: DIFERENCIAS\n{e}')
print('RESULTADO:', 'IGUAL que la referencia' if ok else 'HAY DIFERENCIAS')
