"""Paso 2: la web completa con datos ficticios. Incluye la prueba de aislamiento entre empresas."""
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from portal.models import Empresa, FilaOperador, MovimientoContable, Perfil

RAIZ = Path(__file__).resolve().parent.parent
OCTUBRE = [
    ('operador', RAIZ / 'datos_origen/operador/Informe_operador_2026-10.xlsx'),
    ('business_central', RAIZ / 'datos_origen/business_central/BC_movimientos_contabilidad_2026-10.xlsx'),
]


@pytest.fixture
def demo(db, settings, tmp_path, monkeypatch):
    settings.STORAGES = {**settings.STORAGES, 'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage',
                                                           'OPTIONS': {'location': str(tmp_path)}}}
    monkeypatch.setenv('DEMO_PASSWORD_DIRECTOR', 'clave-director-123')
    monkeypatch.setenv('DEMO_PASSWORD_CONTABLE', 'clave-contable-123')
    monkeypatch.setenv('DEMO_PASSWORD_PRUEBA', 'clave-prueba-123')
    call_command('crear_grupo_demo', '--hasta', '2026-09')


def _entrar(client, usuario, clave):
    assert client.login(username=usuario, password=clave)


def _subir_octubre(client):
    for tipo, ruta in OCTUBRE:
        with open(ruta, 'rb') as f:
            r = client.post('/subir/', {'tipo': tipo, 'archivos': [f]}, follow=True)
        assert r.status_code == 200


def test_sin_usuario_redirige_a_entrar(client, demo):
    r = client.get('/')
    assert r.status_code == 302 and '/entrar/' in r['Location']


def test_contable_sube_octubre_y_ve_las_cifras_de_control(client, demo):
    _entrar(client, 'contable.demo', 'clave-contable-123')
    _subir_octubre(client)
    html = client.get('/?mes=2026-10').content.decode()
    for cifra in ['372.727 €', '169.764 €', '169.324 €', '65.918 €', '283.193 €', '139.184 €', '333.910 €', '181.016 €']:
        assert cifra in html, cifra
    assert 'octubre 2026' in html


def test_director_ve_el_informe_pero_no_puede_subir(client, demo):
    _entrar(client, 'director.demo', 'clave-director-123')
    assert client.get('/').status_code == 200
    assert client.get('/subir/').status_code == 403


def test_aislamiento_otra_empresa_no_ve_nada_del_grupo(client, demo):
    """Prueba de aislamiento: el usuario de otra empresa no ve cifras, hoteles ni cargas del Grupo Demo."""
    _entrar(client, 'usuario.prueba', 'clave-prueba-123')
    html = client.get('/').content.decode() + client.get('/?mes=2026-09').content.decode()
    assert 'Hotel Mar' not in html and 'Grupo Demo' not in html
    assert 'Todavía no hay datos' in html
    cargas = client.get('/cargas/').content.decode()
    assert 'Informe_operador' not in cargas and 'BC_movimientos' not in cargas
    prueba = Empresa.objects.get(slug='prueba-aislamiento')
    assert MovimientoContable.objects.filter(empresa=prueba).count() == 0
    assert FilaOperador.objects.filter(empresa=prueba).count() == 0


def test_aislamiento_subir_en_otra_empresa_no_toca_el_grupo(client, demo):
    grupo = Empresa.objects.get(slug='grupo-demo')
    antes = MovimientoContable.objects.filter(empresa=grupo).count()
    _entrar(client, 'usuario.prueba', 'clave-prueba-123')
    _subir_octubre(client)
    assert MovimientoContable.objects.filter(empresa=grupo).count() == antes


def test_director_de_hotel_solo_ve_su_hotel(client, demo):
    grupo = Empresa.objects.get(slug='grupo-demo')
    user = get_user_model().objects.create_user('dir.mar', password='clave-mar-12345')
    Perfil.objects.create(usuario=user, empresa=grupo, rol=Perfil.DIRECTOR_HOTEL, hotel='MAR')
    _entrar(client, 'dir.mar', 'clave-mar-12345')
    html = client.get('/').content.decode()
    assert 'Hotel Mar' in html
    assert 'Hotel Gracia' not in html and 'Hotel Born' not in html and 'Total grupo' not in html


def test_archivo_con_columna_desconocida_se_rechaza_con_motivo(client, demo, tmp_path):
    import openpyxl
    wb = openpyxl.load_workbook(OCTUBRE[0][1])
    wb.active.cell(row=3, column=22, value='Spa')
    malo = tmp_path / 'Informe_operador_2026-10_spa.xlsx'
    wb.save(malo)
    _entrar(client, 'contable.demo', 'clave-contable-123')
    with open(malo, 'rb') as f:
        r = client.post('/subir/', {'tipo': 'operador', 'archivos': [f]}, follow=True)
    assert 'columnas sin mapear' in r.content.decode()
