import os

import pytest

os.environ.setdefault('DJANGO_DEBUG', '1')


@pytest.fixture(autouse=True)
def _procesado_en_el_momento(settings):
    """En las pruebas el procesado se hace en el momento, no en un hilo aparte (ver portal/segundo_plano.py)."""
    settings.PROCESADO_SEGUNDO_PLANO = False
