"""Paso 9: informe con el diseño 3b/3d (13 nov 2026).

- La franja «Hasta el presupuesto» sale de los KPIs calculados.
- Los gráficos de barras por mes enseñan los 12 meses hasta el último mes elegido.
- Al pulsar una barra del GOP, la tabla de detalle explica el cálculo con las cifras de control.
- Con un solo hotel, la comparativa compara meses en lugar de hoteles.
"""
import json
import re

import pytest

from cuadralo import informe
from test_paso2_web import _entrar, _subir_octubre, demo  # noqa: F401  (fixture)


def test_franja_hasta_el_presupuesto():
    real = {'GOP': 90.0, 'Ingresos totales': 300.0, 'Room nights': 10.0, 'ADR': 20.0, 'Ocupación': 0.8}
    ppto = {'GOP': 100.0, 'Ingresos totales': 340.0, 'Ocupación': 0.75}
    aa = {'GOP': 80.0}
    bloques = informe.franja_presupuesto(real, ppto, aa)
    assert [b['estado'] for b in bloques] == ['mal', 'bien', 'mal', 'aviso']
    assert bloques[0]['cifra'] == '10 €'            # GOP que falta
    assert bloques[2]['cifra'] == '2'               # 40 € de ingresos que faltan / ADR 20 €
    assert bloques[3]['cifra'] == '4,00 €'          # 40 € / 10 room nights
    assert informe.franja_presupuesto(real, {}, {}) == []


@pytest.mark.django_db
def test_graficos_de_12_meses_y_calculo_de_la_barra(client, demo):  # noqa: F811
    _entrar(client, 'contable.demo', 'clave-contable-123')
    _subir_octubre(client)
    html = client.get('/?meses=2026-10&p=resumen').content.decode()
    graficos = json.loads(re.search(r'<script id="datos-graficos" type="application/json">(.*?)</script>', html, re.S).group(1))
    gop = graficos['gop_mes']
    assert len(gop['etiquetas']) == 12 and gop['etiquetas'][-1].startswith('oct')
    assert gop['series'][0]['colores'][-1] == 'principal' and gop['series'][0]['colores'][0] == 'comparacion'
    assert [s['nombre'] for s in gop['series']] == ['GOP', 'Presupuesto', 'Año anterior']
    assert gop['clic'][-1] == {'tipo': 'calculo', 'que': 'gop', 'mes': '2026-10'}
    assert 'Hasta el presupuesto' in html and 'Qué hacer, por prioridad' in html

    d = client.get('/detalle/?meses=2026-10&tipo=calculo&que=gop&mes_sel=2026-10&hotel_sel=MAR').json()
    assert d['filas'][-1][0] == 'GOP' and d['filas'][-1][1] == '169.764 €'      # cifra de control de Mar
    assert '= 169.764 €' in d['explicacion'][1]
    assert d['clics'][0]['tipo'] == 'facturas' and d['clics'][0]['mes'] == '2026-10'
    assert client.get('/detalle/?meses=2026-10&tipo=calculo&que=otra').status_code == 404


@pytest.mark.django_db
def test_un_solo_hotel_compara_meses(client, demo):  # noqa: F811
    _entrar(client, 'contable.demo', 'clave-contable-123')
    _subir_octubre(client)
    html = client.get('/?meses=2026-10&hotel=MAR&p=comparativa').content.decode()
    assert '¿Cómo evoluciona el hotel mes a mes?' in html and 'Indicadores mes a mes' in html
    grupo = client.get('/?meses=2026-10&p=comparativa').content.decode()
    assert '¿Qué hotel lo hace mejor?' in grupo
