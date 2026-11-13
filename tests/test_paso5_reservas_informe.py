"""Paso 5: reservas del PMS (Mews) e informe con varios meses, filtros y tablas de detalle.

Comprueba que las reservas cuadran con el operador, que los canales salen de la configuración, que el
informe suma los meses elegidos y que el detalle de un clic nunca enseña hoteles que el usuario no puede ver.
"""
import json
from pathlib import Path

import pandas as pd
import pytest
from django.contrib.auth import get_user_model

from cuadralo import informe, reservas
from cuadralo.normalizar import ErrorDeCarga, archivos_de, normalizar_operador, normalizar_reservas
from portal.models import Empresa, Perfil, Reserva

from test_paso2_web import _entrar, demo  # noqa: F401  (fixture)

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(scope='module')
def cfg():
    return pd.read_excel(RAIZ / 'configuracion_grupo_demo.xlsx', sheet_name=None)


def test_reservas_sin_nombres_y_con_canal(cfg):
    r = normalizar_reservas([RAIZ / 'datos_origen/reservas/Reservas_2026-10.xlsx'], cfg)
    assert {'Canal', 'Tipo de canal', 'Segmento', 'Personas', 'Nacionalidad', 'Ingresos alojamiento'} <= set(r.columns)
    assert not any('nombre' in c.lower() or 'email' in c.lower() for c in r.columns)
    assert set(r['Canal']) >= {'Booking.com', 'Web propia', 'Teléfono'}


def test_reservas_cuadran_con_el_operador(cfg):
    res = normalizar_reservas(archivos_de(RAIZ / 'datos_origen', 'reservas'), cfg)
    pms = normalizar_operador(archivos_de(RAIZ / 'datos_origen', 'operador'), cfg)
    from cuadralo import calculos
    q = reservas.cuadre_con_operador(reservas.agregar_por_mes(res), calculos.actividad_completa(pms, cfg), 1.0)
    assert len(q) == 4 * 34 and q['Cuadra'].all()


def test_canal_desconocido_para_la_carga(cfg, tmp_path):
    df = pd.read_excel(RAIZ / 'datos_origen/reservas/Reservas_2026-10.xlsx').head(5)
    df.loc[0, 'TravelAgency'] = 'Canal Inventado SL'
    f = tmp_path / 'Reservas_mal.xlsx'
    df.to_excel(f, index=False)
    with pytest.raises(ErrorDeCarga, match='Canal Inventado SL'):
        normalizar_reservas([f], cfg)


def test_estancia_que_cruza_de_mes_reparte_noches_e_ingresos():
    res = pd.DataFrame([{'Id hotel': 'MAR', 'Nº reserva': '1', 'Estancia': True, 'Cancelada': False, 'Canal': 'Booking.com',
                         'Tipo de canal': 'OTA', 'Segmento': 'Ocio', 'Nacionalidad': 'ES', 'Personas': 2,
                         'Llegada': pd.Timestamp('2026-09-29'), 'Salida': pd.Timestamp('2026-10-03'), 'Noches': 4,
                         'Ingresos alojamiento': 400.0}])
    m = reservas.noches_por_mes(res).set_index('Mes')
    assert m.loc[pd.Timestamp('2026-09-01'), 'Noches'] == 2 and m.loc[pd.Timestamp('2026-10-01'), 'Noches'] == 2
    assert m['Ingresos'].sum() == pytest.approx(400.0)


def test_varios_meses_suman_y_los_graficos_resaltan_esos_meses(client, demo):  # noqa: F811
    _entrar(client, 'director.demo', 'clave-director-123')
    html = client.get('/?meses=2026-08&meses=2026-09&p=ventas').content.decode()
    assert 'agosto-septiembre 2026 (2 meses)' in html
    datos = json.loads(html.split('id="datos-graficos" type="application/json">')[1].split('</script>')[0])
    # Desde el 13 nov los gráficos por mes enseñan los 12 meses hasta el último elegido y resaltan los elegidos
    ocu = datos['ocupacion_mes']
    assert len(ocu['etiquetas']) == 12 and ocu['etiquetas'][-2:] == ['ago 26', 'sep 26']
    assert ocu['series'][0]['colores'][-2:] == ['principal', 'principal'] and ocu['series'][0]['colores'][-3] == 'comparacion'
    assert datos['canales'] and 'noches' in datos['canales']['series'][0]['ayudas'][0]
    # el tooltip trae el valor y el porcentaje
    assert '%' in datos['canales']['series'][0]['ayudas'][0] and '€' in datos['canales']['series'][0]['ayudas'][0]


def test_detalle_de_reservas_explica_la_ocupacion(client, demo):  # noqa: F811
    _entrar(client, 'director.demo', 'clave-director-123')
    d = client.get('/detalle/?meses=2026-09&tipo=reservas&mes_sel=2026-09&hotel_sel=BORN').json()
    assert 'Hotel Born' in d['titulo'] and d['total_filas'] > 0
    assert any(t.startswith('Ocupación =') for t in d['explicacion'])
    f = client.get('/detalle/?meses=2026-09&tipo=facturas&linea=Suministros').json()
    assert f['total_filas'] > 0 and 'Suministros' in f['titulo']


def test_filtros_de_proveedor_y_canal(client, demo):  # noqa: F811
    _entrar(client, 'director.demo', 'clave-director-123')
    r = client.get('/?meses=2026-09&proveedor=Endesa Energía&canal=Booking.com&p=resultados')
    assert r.status_code == 200
    html = r.content.decode()
    assert 'Endesa Energía' in html and 'Canal Booking.com' in html
    d = client.get('/detalle/?meses=2026-09&proveedor=Endesa Energía&tipo=facturas').json()
    assert d['total_filas'] > 0 and all(f[4] == 'Endesa Energía' for f in d['filas'])


def test_director_de_hotel_no_ve_detalle_de_otros_hoteles(client, demo):  # noqa: F811
    grupo = Empresa.objects.get(slug='grupo-demo')
    user = get_user_model().objects.create_user('dir.mar', password='clave-mar-12345')
    Perfil.objects.create(usuario=user, empresa=grupo, rol=Perfil.DIRECTOR_HOTEL, hotel='MAR')
    _entrar(client, 'dir.mar', 'clave-mar-12345')
    for url in ['/detalle/?meses=2026-09&tipo=reservas&hotel_sel=BORN', '/detalle/?meses=2026-09&tipo=facturas&hotel=BORN',
                '/detalle/?meses=2026-09&tipo=reservas&hotel=GRUPO']:
        d = client.get(url).json()
        assert all(f[1] == 'Hotel Mar' for f in d['filas']), url
    html = client.get('/?meses=2026-09&hotel=BORN&p=ventas').content.decode()
    assert 'Hotel Born' not in html and 'Hotel Gracia' not in html


def test_otra_empresa_no_ve_reservas_del_grupo(client, demo):  # noqa: F811
    _entrar(client, 'usuario.prueba', 'clave-prueba-123')
    assert client.get('/detalle/?tipo=reservas').status_code == 404   # sin datos propios
    assert Reserva.objects.filter(empresa__slug='prueba-aislamiento').count() == 0


def test_subir_reservas_nuevas_es_incremental(client, demo):  # noqa: F811
    grupo = Empresa.objects.get(slug='grupo-demo')
    antes = Reserva.objects.filter(empresa=grupo).count()
    _entrar(client, 'contable.demo', 'clave-contable-123')
    with open(RAIZ / 'datos_origen/reservas/Reservas_2026-10.xlsx', 'rb') as f:
        r = client.post('/subir/', {'tipo': 'reservas', 'archivos': [f]}, follow=True)
    assert r.status_code == 200
    nuevas = len(pd.read_excel(RAIZ / 'datos_origen/reservas/Reservas_2026-10.xlsx'))
    assert Reserva.objects.filter(empresa=grupo).count() == antes + nuevas
