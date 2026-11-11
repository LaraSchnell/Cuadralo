"""Exportación a Excel y explorador de apuntes: cifras correctas, filtros y aislamiento entre hoteles."""
import io

import openpyxl
import pytest
from django.contrib.auth import get_user_model

from portal.models import Empresa, Perfil
from test_paso2_web import _entrar, _subir_octubre, demo  # noqa: F401  (fixture)


def _xlsx(respuesta):
    assert respuesta.status_code == 200, respuesta.status_code
    assert respuesta['Content-Type'].startswith('application/vnd.openxmlformats')
    return openpyxl.load_workbook(io.BytesIO(respuesta.content))


def _filas(ws):
    """Filas de la tabla (a partir de la cabecera en blanco sobre fondo marino) como diccionarios."""
    filas = list(ws.iter_rows(values_only=True))
    i = next(n for n, f in enumerate(filas) if f[0] is not None and n > 0 and filas[n - 1][0] is None)
    cab = filas[i]
    return [dict(zip(cab, f)) for f in filas[i + 1:]]


@pytest.fixture
def con_octubre(client, demo):  # noqa: F811
    _entrar(client, 'contable.demo', 'clave-contable-123')
    _subir_octubre(client)
    return client


def test_informe_completo_en_excel_con_numeros(con_octubre):
    wb = _xlsx(con_octubre.get('/exportar/informe/?hotel=GRUPO&mes=2026-10'))
    assert wb.sheetnames == ['Indicadores', 'Cuenta de resultados', 'Cuadre', 'Ratios', 'Desviaciones', 'Comparativa', 'Coste por room night']
    assert 'Datos ficticios' in str(wb['Cuadre']['A3'].value)
    gop = next(f for f in _filas(wb['Cuenta de resultados']) if f['Línea'] == 'GOP')
    assert isinstance(gop['Real'], float)
    assert gop['Real'] == pytest.approx(169763.81 + 65917.85 + 139183.76 + 181016.34, abs=0.05)
    comp = {f['Hotel']: f for f in _filas(wb['Comparativa'])}
    assert comp['Hotel Born']['Ingresos'] == pytest.approx(283193.02, abs=0.01)
    assert len([f for f in _filas(wb['Cuadre']) if f['Estado'] == 'No cuadra']) == 4


def test_desviaciones_en_excel_llevan_la_factura(con_octubre):
    wb = _xlsx(con_octubre.get('/exportar/desviaciones/?hotel=MAR&mes=2026-10'))
    filas = _filas(wb['Desviaciones'])
    calderas = next(f for f in filas if f['Proveedor'] == 'Calderas Barcelona SL')
    assert calderas['Causa'] == 'Proveedor nuevo' and calderas['Importe de la causa'] == pytest.approx(6800)
    assert {f['Hotel'] for f in filas} == {'Hotel Mar'}


def test_indicadores_en_excel_porcentajes_en_puntos(con_octubre):
    wb = _xlsx(con_octubre.get('/exportar/indicadores/?hotel=BORN&mes=2026-10'))
    ws = wb['Indicadores']
    ind = {f['Indicador']: f for f in _filas(ws)}
    assert ind['ADR']['Real'] == pytest.approx(151.10, abs=0.01)
    assert ind['Labor cost']['Sentido'] == 'subir es malo'
    # la variación del % GOP está en puntos (−1,2 pp), no en % relativo
    assert ind['% GOP']['Var. vs presupuesto'] == pytest.approx(-1.2, abs=0.1)


def test_tabla_desconocida_o_comparativa_de_un_hotel_da_404(con_octubre):
    assert con_octubre.get('/exportar/inventada/').status_code == 404
    assert con_octubre.get('/exportar/comparativa/?hotel=BORN&mes=2026-10').status_code == 404


def test_apuntes_filtros(con_octubre):
    c = con_octubre
    html = c.get('/apuntes/?hotel=MAR&mes=2026-10&proveedor=Calderas+Barcelona+SL').content.decode()
    assert 'Calderas Barcelona SL' in html and '6.800,00 €' in html
    html = c.get('/apuntes/?hotel=MAR&mes=2026-10&texto=MA26335201').content.decode()
    assert 'FP-5879' in html and 'FP-2193' not in html          # busca también por nº de factura del proveedor
    wb = _xlsx(c.get('/apuntes/?hotel=GRUPO&desde=2026-10-01&hasta=2026-10-31&ceco=DES&agrupar=hotel&exportar=1'))
    apuntes = _filas(wb['Apuntes'])
    assert apuntes and {a['Ceco'] for a in apuntes} == {'DES'}
    resumen = {f['Hotel']: f for f in _filas(wb['Resumen'])}
    assert set(resumen) == {'Hotel Mar', 'Hotel Gracia', 'Hotel Born', 'Hotel Sitges'}
    assert sum(f['Importe'] for f in resumen.values()) == pytest.approx(sum(a['Importe sin IVA'] for a in apuntes), abs=0.01)
    assert all(f['Año anterior'] for f in resumen.values())     # compara con octubre de 2025


def test_apuntes_agrupados_por_mes_comparan_con_el_mismo_mes(con_octubre):
    wb = _xlsx(con_octubre.get('/apuntes/?hotel=SITGES&desde=2026-08-01&hasta=2026-10-31&proveedor=Clean+Services+Catalunya&agrupar=mes&exportar=1'))
    filas = _filas(wb['Resumen'])
    octubre = [f for f in filas if f['Mes'].month == 10][0]
    assert octubre['Importe'] == 0 and octubre['Año anterior'] > 0   # la factura que falta se ve en el Excel


def test_director_de_hotel_solo_exporta_y_ve_su_hotel(client, demo):  # noqa: F811
    _entrar(client, 'contable.demo', 'clave-contable-123')
    _subir_octubre(client)
    client.logout()
    grupo = Empresa.objects.get(slug='grupo-demo')
    user = get_user_model().objects.create_user('dir.mar', password='clave-mar-12345')
    Perfil.objects.create(usuario=user, empresa=grupo, rol=Perfil.DIRECTOR_HOTEL, hotel='MAR')
    _entrar(client, 'dir.mar', 'clave-mar-12345')
    wb = _xlsx(client.get('/exportar/informe/?hotel=BORN&mes=2026-10'))   # pide Born: recibe Mar
    assert 'Comparativa' not in wb.sheetnames
    texto = ' '.join(str(c) for ws in wb for fila in ws.iter_rows(values_only=True) for c in fila if c)
    for otro in ['Hotel Born', 'Hotel Gracia', 'Hotel Sitges']:
        assert otro not in texto
    assert 'otro hotel del grupo' in texto
    wb = _xlsx(client.get('/apuntes/?hotel=GRUPO&desde=2024-01-01&hasta=2026-12-31&exportar=1'))
    assert {a['Hotel'] for a in _filas(wb['Apuntes'])} == {'Hotel Mar'}
    html = client.get('/apuntes/?proveedor=Calderas+Barcelona+SL').content.decode()
    assert 'Hotel Born' not in html and 'Hotel Gracia' not in html


def test_otra_empresa_no_exporta_nada_del_grupo(client, demo):  # noqa: F811
    _entrar(client, 'usuario.prueba', 'clave-prueba-123')
    assert client.get('/exportar/informe/').status_code == 404
    assert 'Todavía no hay datos' in client.get('/apuntes/').content.decode()
