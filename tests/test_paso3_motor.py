"""Paso 3: el motor detecta los 11 casos sembrados y no da falsas alarmas de facturas en el histórico."""
from pathlib import Path

import pandas as pd
import pytest

from cuadralo.calculos import asignar_lineas, cuenta_resultados
from cuadralo.normalizar import archivos_de, normalizar_bc, normalizar_operador, normalizar_presupuesto
from cuadralo.reglas import analizar_mes

RAIZ = Path(__file__).resolve().parent.parent
OCTUBRE = pd.Timestamp('2026-10-01')


@pytest.fixture(scope='module')
def datos():
    cfg = pd.read_excel(RAIZ / 'configuracion_grupo_demo.xlsx', sheet_name=None)
    mov = normalizar_bc(archivos_de(RAIZ / 'datos_origen', 'business_central'))
    pms = normalizar_operador(archivos_de(RAIZ / 'datos_origen', 'operador'), cfg)
    pres = normalizar_presupuesto(archivos_de(RAIZ / 'datos_origen', 'presupuesto'), cfg)
    m = asignar_lineas(mov, cfg)
    pyg = cuenta_resultados(mov, cfg)
    return cfg, m, pms, pres, pyg


@pytest.fixture(scope='module')
def octubre(datos):
    cfg, m, pms, pres, pyg = datos
    return analizar_mes(m, pms, pres, pyg, cfg, OCTUBRE)


def test_los_11_casos_sembrados(datos, octubre):
    cfg = datos[0]
    nombre2id = dict(zip(cfg['hoteles']['Hotel'], cfg['hoteles']['Id hotel']))
    casos = cfg['casos_plantados']
    assert len(casos) == 11
    cuadre, ratios, alertas = octubre['cuadre'], octubre['ratios'], octubre['alertas']
    for _, caso in casos.iterrows():
        hotel, linea = nombre2id[caso['Hotel']], caso['Línea']
        if caso['Página'] == 'Cuadre':
            fila = cuadre[(cuadre['Id hotel'] == hotel) & (cuadre['Línea'] == linea)]
            assert not fila['Cuadra'].iloc[0], caso['Caso']
            assert fila['Causa'].iloc[0] == caso['Caso'], (caso['Caso'], fila['Causa'].iloc[0])
        elif caso['Página'] == 'Ratios':
            fila = ratios[(ratios['Id hotel'] == hotel) & (ratios['Ratio'] == linea)]
            assert not fila['Correcto'].iloc[0], caso['Caso']
        elif caso['Página'] in ('Desviaciones', 'Comparativa'):
            de_la_linea = alertas[(alertas['Id hotel'] == hotel) & (alertas['Línea'] == linea)]
            assert len(de_la_linea), caso['Caso']


def test_cuadre_cifras(octubre):
    c = octubre['cuadre'].set_index(['Id hotel', 'Línea'])
    assert c.loc[('MAR', 'Minibar'), 'Diferencia'] == pytest.approx(7296.89)
    assert c.loc[('BORN', 'Minibar'), 'Diferencia'] == pytest.approx(-7296.89)
    assert c.loc[('GRACIA', 'Alojamiento'), 'Diferencia'] == pytest.approx(1180.00)
    assert c.loc[('SITGES', 'Eventos'), 'Diferencia'] == pytest.approx(1550.00)
    assert (~c['Cuadra']).sum() == 4


def test_solo_las_alertas_esperadas_en_octubre(octubre):
    a = octubre['alertas']
    obtenidas = set(zip(a['Tipo'], a['Id hotel'], a['Línea']))
    assert obtenidas == {
        ('Factura duplicada', 'MAR', 'Consumo desayunos'),
        ('Factura en otro mes', 'GRACIA', 'Suministros'),
        ('Proveedor nuevo', 'MAR', 'Reparaciones y mantenimiento'),
        ('Subida de precio', 'GRACIA', 'Consumo desayunos'),
        ('Falta una factura', 'SITGES', 'Limpieza'),
        ('Coste estructural alto', 'BORN', 'Lavandería'),
    }
    r = octubre['ratios']
    assert set(zip(r[~r['Correcto']]['Id hotel'], r[~r['Correcto']]['Ratio'])) == {('BORN', 'ADR'), ('SITGES', 'Captación desayuno')}


def test_las_desviaciones_de_coste_sembradas_llevan_su_factura(octubre):
    d = octubre['desviaciones']
    for hotel, linea, causa in [('MAR', 'Consumo desayunos', 'Factura duplicada'), ('GRACIA', 'Suministros', 'Factura en otro mes'),
                                ('MAR', 'Reparaciones y mantenimiento', 'Proveedor nuevo'), ('SITGES', 'Limpieza', 'Falta una factura')]:
        fila = d[(d['Id hotel'] == hotel) & (d['Línea'] == linea)]
        assert len(fila) and causa in fila['Causa'].iloc[0], (hotel, linea)


def test_sin_falsas_alarmas_de_facturas_en_el_historico(datos):
    """En 2025 y hasta septiembre de 2026 no hay errores sembrados: solo pueden salir la lavandería de Born
    (coste estructural, es permanente), la luz de Gracia de septiembre (se registró en octubre: caso sembrado)
    y alguna factura que falta en diciembre/enero por el calendario de un proveedor."""
    cfg, m, pms, pres, pyg = datos
    permitidas = {'Coste estructural alto', 'Falta una factura'}
    for mes in pd.date_range('2025-01-01', '2026-09-01', freq='MS'):
        a = analizar_mes(m, pms, pres, pyg, cfg, mes)['alertas']
        assert set(a['Tipo']) <= permitidas, (mes, set(a['Tipo']))
        assert len(a[a['Tipo'] == 'Falta una factura']) <= 1, mes
