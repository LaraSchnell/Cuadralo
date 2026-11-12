"""Paso 7: seguridad por filas en Azure SQL (segunda barrera de aislamiento).

Aquí no hay Azure SQL (las pruebas usan SQLite), así que se comprueba:
- que la web declara en cada petición la empresa correcta, y la borra al terminar;
- que ninguna tabla con datos de clientes se queda fuera de la política;
- que los scripts de infra/rls coinciden con lo que crea la migración.
La prueba contra Azure SQL de verdad es infra/rls/2_probar.sql, en una base de datos de pruebas.
"""
from pathlib import Path

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model

from portal import seguridad_bd
from portal.models import Empresa, Perfil

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def llamadas(monkeypatch):
    """Simula Azure SQL: guarda cada (empresa_id, interno) que la web declara en la sesión."""
    registro = []
    monkeypatch.setattr(seguridad_bd, 'activa', lambda: True)
    monkeypatch.setattr(seguridad_bd, '_ejecutar', lambda sql, p: registro.append(tuple(p)))
    return registro


def _usuario(nombre, empresa=None, superusuario=False):
    User = get_user_model()
    if superusuario:
        user = User.objects.create_superuser(nombre, password='clave-larga-12345')
    else:
        user = User.objects.create_user(nombre, password='clave-larga-12345')
    if empresa is not None:
        Perfil.objects.create(usuario=user, empresa=empresa, rol=Perfil.CONTABILIDAD)
    return user


@pytest.mark.django_db
def test_cada_peticion_declara_la_empresa_del_usuario_y_la_borra_al_terminar(client, llamadas):
    a = Empresa.objects.create(slug='hotel-a', nombre='Hotel A')
    b = Empresa.objects.create(slug='hotel-b', nombre='Hotel B')
    client.force_login(_usuario('contable.a', a))
    client.get('/cargas/')
    assert llamadas[0] == (a.id, None)
    assert llamadas[-1] == (None, None)
    assert (b.id, None) not in llamadas

    llamadas.clear()
    client.force_login(_usuario('contable.b', b))
    client.get('/cargas/')
    assert llamadas[0] == (b.id, None)
    assert llamadas[-1] == (None, None)


@pytest.mark.django_db
def test_sin_sesion_no_se_declara_ninguna_empresa(client, llamadas):
    client.get('/entrar/')
    assert llamadas and all(p == (None, None) for p in llamadas)


@pytest.mark.django_db
def test_solo_el_superusuario_sin_empresa_es_interno(client, llamadas):
    client.force_login(_usuario('equipo.cuadralo', superusuario=True))
    client.get('/entrar/')
    assert llamadas[0] == (None, 1)

    # un superusuario que además es usuario de una empresa solo ve esa empresa
    a = Empresa.objects.create(slug='hotel-a', nombre='Hotel A')
    llamadas.clear()
    client.force_login(_usuario('jefe.a', a, superusuario=True))
    client.get('/entrar/')
    assert llamadas[0] == (a.id, None)


@pytest.mark.django_db
def test_un_usuario_normal_sin_empresa_no_ve_nada(client, llamadas):
    client.force_login(_usuario('sin.empresa'))
    client.get('/entrar/')
    assert llamadas[0] == (None, None)


def test_contexto_interno_se_borra_aunque_falle(llamadas):
    with pytest.raises(ValueError):
        with seguridad_bd.contexto_interno():
            raise ValueError('fallo en mitad de la carga')
    assert llamadas == [(None, 1), (None, None)]


def test_contexto_empresa_para_tareas_en_segundo_plano(llamadas):
    with seguridad_bd.contexto_empresa(7):
        pass
    assert llamadas == [(7, None), (None, None)]


def test_ninguna_tabla_con_empresa_se_queda_fuera_de_la_politica():
    con_empresa = {m._meta.db_table for m in apps.get_app_config('portal').get_models()
                   if any(f.name == 'empresa' for f in m._meta.fields)}
    revisadas = set(seguridad_bd.TABLAS_PROTEGIDAS) | set(seguridad_bd.TABLAS_SIN_RLS)
    assert con_empresa - revisadas == set(), 'Tabla nueva con empresa: añádela a TABLAS_PROTEGIDAS (y una migración)'
    assert set(seguridad_bd.TABLAS_PROTEGIDAS) <= con_empresa


def test_la_politica_filtra_y_bloquea_cada_tabla_protegida():
    sql = seguridad_bd.sql_activar()
    for tabla in seguridad_bd.TABLAS_PROTEGIDAS:
        assert f'FILTER PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.{tabla},' in sql or \
               f'FILTER PREDICATE seguridad.fn_empresa(empresa_id) ON dbo.{tabla}\n' in sql
        assert f'ON dbo.{tabla} AFTER INSERT' in sql
        assert f'ON dbo.{tabla} AFTER UPDATE' in sql
    assert 'WITH (STATE = ON)' in sql


def test_los_scripts_de_infra_coinciden_con_la_migracion():
    assert (RAIZ / 'infra/rls/1_activar.sql').read_text() == seguridad_bd.sql_activar()
    assert (RAIZ / 'infra/rls/4_quitar.sql').read_text() == seguridad_bd.sql_quitar()
    probar = (RAIZ / 'infra/rls/2_probar.sql').read_text()
    for tabla in seguridad_bd.TABLAS_PROTEGIDAS:
        assert f"N'{tabla}'" in probar, tabla
