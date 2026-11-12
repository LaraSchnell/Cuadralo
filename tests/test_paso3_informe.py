"""Pasos 3-4: motor (cuadre, ratios, desviaciones, comparativa) e informe completo en la web.

Comprueba que se detectan los 11 casos sembrados de casos_plantados, las cifras de control de octubre 2026
y que el director de un hotel no ve nada de los demás hoteles, tampoco dentro de los textos de las causas.
"""
from pathlib import Path

import pandas as pd
import pytest
from django.contrib.auth import get_user_model

from cuadralo import calculos, informe, reglas
from cuadralo.normalizar import archivos_de, normalizar_bc, normalizar_operador, normalizar_presupuesto
from portal.models import Empresa, InteresModulo, Perfil

from test_paso2_web import _entrar, _subir_octubre, demo  # noqa: F401  (fixture)

RAIZ = Path(__file__).resolve().parent.parent
OCT = pd.Timestamp('2026-10-01')
HOTELES = ['MAR', 'GRACIA', 'BORN', 'SITGES']


@pytest.fixture(scope='module')
def datos():
    cfg = pd.read_excel(RAIZ / 'configuracion_grupo_demo.xlsx', sheet_name=None)
    mov = normalizar_bc(archivos_de(RAIZ / 'datos_origen', 'business_central'))
    pms = normalizar_operador(archivos_de(RAIZ / 'datos_origen', 'operador'), cfg)
    pres = normalizar_presupuesto(archivos_de(RAIZ / 'datos_origen', 'presupuesto'), cfg)
    return informe.Datos(mov, pms, pres, cfg)


def _desv(datos, hotel, linea):
    filas = reglas.desviaciones(datos.mov, datos.det_real, datos.det_ppto, datos.act, datos.cuadre, datos.cfg, [hotel], OCT)
    fila = next(f for f in filas if f['Línea'] == linea)
    return fila, {c['tipo']: c for c in fila['Causas']}


# ---------------------------------------------------------------- casos sembrados

def test_cuadre_detecta_los_cuatro_errores_de_ingresos(datos):
    q = datos.cuadre.xs(OCT, level='Mes')
    malas = q[~q['Cuadra']]
    assert len(malas) == 4
    assert malas.loc[('MAR', 'Minibar'), 'Diferencia'] == pytest.approx(7296.89)
    assert malas.loc[('BORN', 'Minibar'), 'Diferencia'] == pytest.approx(-7296.89)
    assert malas.loc[('MAR', 'Minibar'), 'Hotel relacionado'] == 'BORN'                     # caso 1: otra finca
    assert malas.loc[('GRACIA', 'Alojamiento'), 'Diferencia'] == pytest.approx(1180)
    assert malas.loc[('GRACIA', 'Alojamiento'), 'Causa'] == 'abono no reportado por el operador'  # caso 2
    assert malas.loc[('SITGES', 'Eventos'), 'Diferencia'] == pytest.approx(1550)            # caso 3
    assert malas.loc[('SITGES', 'Eventos'), 'Causa'] == 'sin contabilizar'


def test_ratios_del_operador(datos):
    r = datos.ratios[(datos.ratios['Mes'] == OCT) & ~datos.ratios['Correcto']]
    assert len(r) == 2
    adr = r[(r['Id hotel'] == 'BORN') & (r['Ratio'] == 'ADR')].iloc[0]                      # caso 4
    assert adr['Operador'] == pytest.approx(155.63) and adr['Recalculado'] == pytest.approx(151.10, abs=0.01)
    assert adr['Impacto'] == pytest.approx(7062, abs=1)
    cap = r[(r['Id hotel'] == 'SITGES') & (r['Ratio'] == 'Captación de desayunos')].iloc[0]  # caso 5
    assert 'habitaciones' in cap['Nota']


def test_proveedor_nuevo_calderas(datos):                                                  # caso 6
    _, causas = _desv(datos, 'MAR', 'Reparaciones y mantenimiento')
    assert causas['Proveedor nuevo']['proveedor'] == 'Calderas Barcelona SL'
    assert causas['Proveedor nuevo']['importe'] == pytest.approx(6800)


def test_duplicada_makro(datos):                                                           # caso 7
    _, causas = _desv(datos, 'MAR', 'Consumo desayunos')
    d = causas['Duplicada']
    assert 'Makro' in d['proveedor'] and d['importe'] == pytest.approx(2899.18)
    assert '22/10' in d['texto'] and 'mismo nº de factura del proveedor' in d['texto']


def test_factura_de_otro_mes_gracia(datos):                                                # caso 8
    _, causas = _desv(datos, 'GRACIA', 'Suministros')
    assert causas['Otro mes']['proveedor'] == 'Endesa Energía'


def test_subida_de_precio_cafes_moka(datos):                                               # caso 9
    _, causas = _desv(datos, 'GRACIA', 'Consumo desayunos')
    s = causas['Subida de precio']
    assert s['proveedor'] == 'Cafès Moka SL'
    assert s['subida'] == pytest.approx(0.25, abs=0.06)
    assert s['desde'] == pd.Timestamp('2026-08-01')


def test_factura_que_falta_clean_services(datos):                                          # caso 10
    _, causas = _desv(datos, 'SITGES', 'Limpieza')
    assert 'Clean Services' in causas['Factura que falta']['proveedor']


def test_lavanderia_de_born_es_estructural(datos):                                         # caso 11
    cp = reglas.coste_por_room_night(datos.det_real, datos.act, datos.cfg, HOTELES, OCT)
    altos = cp[cp['Alto']]
    assert list(zip(altos['Id hotel'], altos['Línea'])) == [('BORN', 'Lavandería')]
    born = altos.iloc[0]
    assert born['Por room night'] == pytest.approx(4.10, abs=0.15) and born['Mediana otros'] == pytest.approx(3.20, abs=0.05)


def test_gasto_variable_que_sigue_a_la_actividad_es_falsa_alarma(datos):
    fila, causas = _desv(datos, 'MAR', 'Comisiones canales')
    assert fila['Falsa alarma'] and 'Falsa alarma' in causas


# ---------------------------------------------------------------- cifras de control

def test_kpis_de_born_en_octubre(datos):
    k = datos.kpis(['BORN'], [OCT])
    assert k['Ingresos totales'] == pytest.approx(283193.02, abs=0.01)
    assert k['GOP'] == pytest.approx(139183.76, abs=0.01)
    assert k['AGOP'] == pytest.approx(119579.16, abs=0.01)
    assert k['GOP2'] == pytest.approx(102364.93, abs=0.01)
    assert k['ADR'] == pytest.approx(151.10, abs=0.01)          # alojamiento / room nights, nunca el del operador
    assert k['Ocupación'] == pytest.approx(1559 / (60 * 31))
    assert k['GOPPAR'] == pytest.approx(139183.76 / (60 * 31))


def test_grupo_suma_los_cuatro_hoteles(datos):
    g = datos.kpis(HOTELES, [OCT])
    assert g['Ingresos totales'] == pytest.approx(372727.14 + 169324.21 + 283193.02 + 333910.13, abs=0.05)


def test_presupuesto_y_resultado_usan_las_mismas_formulas(datos):
    p = datos.resultados(['BORN'], [OCT], 'ppto')
    assert p['GOP'] == pytest.approx(p['Total ingresos'] - p['Total consumos'] - p['Total personal'] - p['Total otros gastos operativos'])
    ffe = float(calculos.parametro(datos.cfg, 'reserva_ffe_pct'))
    assert p['Reserva FF&E'] == pytest.approx(p['Total ingresos'] * ffe)


def test_variaciones_de_porcentajes_en_puntos_y_costes_al_reves():
    v = informe._variacion(0.30, 0.28, 'pp', -1)   # labor cost sube 2 puntos: malo
    assert v['texto'] == '+2,0 pp' and v['estado'] == 'mal'
    v = informe._variacion(110, 100, 'rel', 1)
    assert v['texto'] == '+10,0 %' and v['estado'] == 'bien'


def test_portada_maximo_cinco_alertas_y_cuadre_primero(datos):
    i = informe.construir(datos, HOTELES, 'GRUPO', OCT)
    assert len(i['alertas']) <= 5
    assert i['alertas'][0]['tipo'] == 'Cuadre'
    for a in i['alertas']:
        assert a['que'] and a['cuanto'] and a['donde'] and a['umbral'] and a['periodo']


# ---------------------------------------------------------------- web

def test_contable_ve_todas_las_paginas(client, demo):  # noqa: F811
    _entrar(client, 'contable.demo', 'clave-contable-123')
    _subir_octubre(client)
    html = client.get('/?mes=2026-10').content.decode()
    for texto in ['¿Cómo ha ido el periodo?', '¿Cuadra lo que dice el operador con la contabilidad?',
                  '¿Cuánto ganamos y dónde se va el dinero?', '¿Qué se ha desviado y por qué?', '¿Qué hotel lo hace mejor?',
                  'Calderas Barcelona SL', 'Abono AB-3413', 'Lavandería · Hotel Born', 'Datos ficticios']:
        assert texto in html, texto
    born = client.get('/?mes=2026-10&hotel=BORN').content.decode()
    assert '283.193 €' in born and '151,10 €' in born
    assert client.get('/?mes=2026-10&periodo=acumulado').status_code == 200


def test_director_de_hotel_no_ve_otros_hoteles_ni_en_las_causas(client, demo):  # noqa: F811
    _entrar(client, 'contable.demo', 'clave-contable-123')
    _subir_octubre(client)
    client.logout()
    grupo = Empresa.objects.get(slug='grupo-demo')
    user = get_user_model().objects.create_user('dir.mar', password='clave-mar-12345')
    Perfil.objects.create(usuario=user, empresa=grupo, rol=Perfil.DIRECTOR_HOTEL, hotel='MAR')
    _entrar(client, 'dir.mar', 'clave-mar-12345')
    for url in ['/?mes=2026-10', '/?mes=2026-10&hotel=GRUPO', '/?mes=2026-10&hotel=BORN', '/?mes=2026-10&p=comparativa']:
        html = client.get(url).content.decode()
        assert 'Hotel Mar' in html, url
        for otro in ['Hotel Gracia', 'Hotel Born', 'Hotel Sitges', 'Todo el grupo']:
            assert otro not in html, (url, otro)
        assert 'otro hotel del grupo' in html          # el minibar está en otra finca, sin decir cuál
        assert 'id="comparativa"' not in html


def test_interes_en_modulos_se_guarda_por_empresa(client, demo):  # noqa: F811
    _entrar(client, 'director.demo', 'clave-director-123')
    assert client.get('/interes/').status_code == 405
    assert client.post('/interes/', {'modulo': 'inventado'}).status_code == 400
    assert client.post('/interes/', {'modulo': 'reputacion'}).status_code == 200
    assert client.post('/interes/', {'modulo': 'reputacion'}).status_code == 200   # dos clics cuentan una vez
    grupo = Empresa.objects.get(slug='grupo-demo')
    assert InteresModulo.objects.filter(empresa=grupo, modulo='reputacion').count() == 1
    assert 'Anotado' in client.get('/?p=reputacion').content.decode()


def test_empresa_sin_presupuesto_ni_anio_anterior(client, demo):  # noqa: F811
    _entrar(client, 'usuario.prueba', 'clave-prueba-123')
    _subir_octubre(client)
    html = client.get('/').content.decode()
    assert 'Sin presupuesto' in html and 'Sin año anterior' in html
    assert 'No hay presupuesto cargado' in html
