"""Arranque en Azure: los archivos estáticos se preparan con el mismo modo estricto que en producción.

El 12 nov la web dejó de arrancar porque Chart.js mencionaba un archivo .map que no existe: en desarrollo
no se notaba, pero en Azure collectstatic (CompressedManifestStaticFilesStorage) se paraba con error.
"""
from django.core.management import call_command
from django.test import override_settings


def test_collectstatic_como_en_azure(tmp_path, settings):
    almacenes = dict(settings.STORAGES)
    almacenes['staticfiles'] = {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'}
    with override_settings(STATIC_ROOT=tmp_path, STORAGES=almacenes):
        call_command('collectstatic', '--noinput', verbosity=0)
    assert (tmp_path / 'staticfiles.json').exists()
