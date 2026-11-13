"""Paso 6: aislamiento. Un usuario NUNCA ve datos de otra empresa, y un director de hotel NUNCA ve otro hotel.

Recorre todas las páginas, tablas de detalle, apuntes y exportaciones a Excel, también con parámetros
manipulados en la URL (hotel=, hotel_sel=, canal_sel=…), y busca en la respuesta cualquier rastro ajeno.
"""
import io

import openpyxl
import pytest
from django.contrib.auth import get_user_model

from portal.models import Empresa, Perfil

from test_paso2_web import _entrar, _subir_octubre, demo  # noqa: F401  (fixture)

PAGINAS = ['resumen', 'ventas', 'resultados', 'desviaciones', 'cuadre', 'comparativa']
TABLAS = ['informe', 'indicadores', 'ingresos', 'cuenta', 'cuadre', 'ratios', 'desviaciones', 'comparativa', 'coste_rn']


def _texto(r):
    """Texto de una respuesta: HTML, JSON o Excel (todas las celdas de todas las hojas)."""
    if r.get('Content-Type', '').startswith('application/vnd.openxmlformats'):
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        return ' '.join(str(c) for ws in wb.worksheets for fila in ws.iter_rows(values_only=True) for c in fila if c is not None)
    return r.content.decode()


def _urls(meses='meses=2026-10'):
    urls = [f'/?{meses}&p={p}' for p in PAGINAS]
    urls += [f'/?{meses}&hotel={h}&p=resumen' for h in ['MAR', 'BORN', 'GRACIA', 'SITGES', 'GRUPO']]
    urls += [f'/detalle/?{meses}&tipo=facturas', f'/detalle/?{meses}&tipo=reservas']
    urls += [f'/detalle/?{meses}&tipo=facturas&hotel_sel={h}' for h in ['MAR', 'BORN', 'GRACIA', 'SITGES']]
    urls += [f'/detalle/?{meses}&tipo=reservas&hotel_sel={h}&canal_sel=Booking.com' for h in ['MAR', 'BORN', 'GRACIA', 'SITGES']]
    urls += [f'/detalle/?{meses}&tipo=facturas&hotel={h}&linea=Suministros' for h in ['BORN', 'GRACIA']]
    urls += [f'/apuntes/?{meses}', f'/apuntes/?{meses}&hotel=BORN', f'/apuntes/?{meses}&exportar=1', '/cargas/']
    urls += [f'/exportar/{t}/?{meses}' for t in TABLAS]
    urls += [f'/exportar/{t}/?{meses}&hotel=BORN&hotel=GRACIA' for t in TABLAS]
    return urls


def test_otra_empresa_no_ve_nada_del_grupo_en_ninguna_url(client, demo):  # noqa: F811
    # la empresa de prueba solo tiene octubre; el grupo, 33 meses y reservas
    _entrar(client, 'usuario.prueba', 'clave-prueba-123')
    _subir_octubre(client)
    grupo = Empresa.objects.get(slug='grupo-demo')
    for url in _urls() + _urls('meses=2026-09&meses=2026-08') + _urls('mes=2026-09&periodo=acumulado'):
        r = client.get(url)
        assert r.status_code in (200, 404), url
        if r.status_code != 200:
            continue
        t = _texto(r)
        for ajeno in ['septiembre 2026', 'agosto 2026', 'sep 26', 'ago 26', grupo.nombre, 'Agencia Grupos BCN', 'Reservas · ']:
            assert ajeno not in t, (url, ajeno)


def test_director_de_hotel_no_ve_otro_hotel_en_ninguna_url(client, demo):  # noqa: F811
    grupo = Empresa.objects.get(slug='grupo-demo')
    user = get_user_model().objects.create_user('dir.mar', password='clave-mar-12345')
    Perfil.objects.create(usuario=user, empresa=grupo, rol=Perfil.DIRECTOR_HOTEL, hotel='MAR')
    _entrar(client, 'dir.mar', 'clave-mar-12345')
    for url in _urls('meses=2026-09') + _urls('meses=2026-08&meses=2026-09'):
        r = client.get(url)
        assert r.status_code in (200, 404), url
        if r.status_code != 200:
            continue
        t = _texto(r)
        for otro in ['Hotel Born', 'Hotel Gracia', 'Hotel Sitges', 'Todo el grupo']:
            assert otro not in t, (url, otro)


@pytest.mark.parametrize('usuario,clave', [('director.demo', 'clave-director-123')])
def test_no_hay_acceso_sin_entrar_ni_al_panel_del_equipo(client, demo, usuario, clave):  # noqa: F811
    for url in ['/', '/detalle/?tipo=facturas', '/apuntes/', '/exportar/informe/', '/cargas/', '/cargas/1/eliminar/', '/revisar/']:
        r = client.post(url) if 'eliminar' in url else client.get(url)
        assert r.status_code == 302 and '/entrar/' in r['Location'], url
    _entrar(client, usuario, clave)
    r = client.get('/equipo/')
    assert r.status_code == 302 and 'login' in r['Location']   # el panel interno solo para el equipo de Cuádralo
