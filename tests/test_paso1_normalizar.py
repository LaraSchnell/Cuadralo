"""Paso 1: los Excels de origen normalizados son idénticos a la referencia."""
from pathlib import Path

import pandas as pd

from cuadralo.normalizar import archivos_de, normalizar_bc, normalizar_operador, normalizar_presupuesto

RAIZ = Path(__file__).resolve().parent.parent
REF = pd.read_excel(RAIZ / 'tests/datos/referencia_normalizada.xlsx', sheet_name=None)
CFG = pd.read_excel(RAIZ / 'configuracion_grupo_demo.xlsx', sheet_name=None)


def _igual(a, b, claves):
    cols = list(b.columns)
    a = a[cols].sort_values(claves).reset_index(drop=True)
    b = b[cols].sort_values(claves).reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_dtype=False, check_exact=False, atol=0.005)


def test_business_central():
    _igual(normalizar_bc(archivos_de(RAIZ / 'datos_origen', 'business_central')), REF['mov_contabilidad'],
           ['Fecha de registro', 'Nº documento'])


def test_operador():
    _igual(normalizar_operador(archivos_de(RAIZ / 'datos_origen', 'operador'), CFG), REF['pms'],
           ['Fecha', 'Id hotel', 'Columna del operador'])


def test_presupuesto():
    _igual(normalizar_presupuesto(archivos_de(RAIZ / 'datos_origen', 'presupuesto'), CFG), REF['presupuesto'],
           ['Fecha', 'Id hotel', 'Línea'])
