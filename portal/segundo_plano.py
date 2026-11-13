"""Procesado en segundo plano.

Al subir o eliminar un archivo, la web responde enseguida («Procesando…») y el trabajo pesado (normalizar,
cargar en SQL y precalcular el informe) se hace en un hilo aparte. Así la petición web nunca espera minutos
(App Service la corta a los ~4 minutos).

- La web corre en un solo proceso (startup.sh), así que basta con un registro en memoria para no lanzar
  dos procesados a la vez de la misma empresa.
- Si llega otra subida mientras se procesa, se marca «otra vuelta» y se repite al terminar.
- Si Azure reinicia la web a mitad, la empresa sigue con necesita_procesar=True y se relanza en la siguiente
  visita de cualquier usuario de esa empresa (ver portal/acceso.py).
- Cualquier error, sea del archivo o inesperado, queda escrito en la carga con un mensaje claro y se avisa
  a n8n si está configurada la variable AVISOS_WEBHOOK_URL.
"""
import json
import logging
import threading
import traceback
import urllib.request

from django.conf import settings
from django.db import close_old_connections, connection

log = logging.getLogger(__name__)

_EN_MARCHA = {}          # empresa_id -> True si hay que dar otra vuelta al terminar
_CANDADO = threading.Lock()


def lanzar(empresa_id):
    """Pide procesar la empresa. En pruebas (PROCESADO_SEGUNDO_PLANO=False) se hace en el momento."""
    from .models import Empresa
    Empresa.objects.filter(id=empresa_id).update(necesita_procesar=True)
    if not getattr(settings, 'PROCESADO_SEGUNDO_PLANO', True):
        _procesar(empresa_id)
        return
    with _CANDADO:
        if empresa_id in _EN_MARCHA:
            _EN_MARCHA[empresa_id] = True
            return
        _EN_MARCHA[empresa_id] = False
    threading.Thread(target=_bucle, args=(empresa_id,), daemon=True, name=f'procesado-{empresa_id}').start()


def en_marcha(empresa_id):
    return empresa_id in _EN_MARCHA


def _bucle(empresa_id):
    try:
        while True:
            close_old_connections()
            _procesar(empresa_id)
            with _CANDADO:
                if not _EN_MARCHA.get(empresa_id):
                    _EN_MARCHA.pop(empresa_id, None)
                    return
                _EN_MARCHA[empresa_id] = False
    finally:
        with _CANDADO:
            _EN_MARCHA.pop(empresa_id, None)
        connection.close()


def _procesar(empresa_id):
    from .models import Carga, Empresa
    from .procesar import procesar_empresa
    empresa = Empresa.objects.get(id=empresa_id)
    Empresa.objects.filter(id=empresa_id).update(necesita_procesar=False)
    pendientes = list(empresa.cargas.filter(estado='pendiente'))
    try:
        ok, mensaje = procesar_empresa(empresa)
    except Exception as e:  # el hueco: cualquier fallo, no solo los de formato, queda explicado en la carga
        log.exception('Fallo inesperado procesando la empresa %s', empresa_id)
        ok, mensaje = False, (f'Error inesperado al procesar ({type(e).__name__}: {e}). '
                              'Avisa al equipo de Cuádralo.')
        Carga.objects.filter(id__in=[c.id for c in pendientes], estado='pendiente').update(estado='error', mensaje=mensaje)
        log.debug(traceback.format_exc())
    if not ok:
        avisar_error(empresa, pendientes, mensaje)


def avisar_error(empresa, cargas, mensaje):
    avisar(empresa, cargas, mensaje, evento='carga_con_error')


def avisar(empresa, cargas, mensaje, evento):
    """Envía el aviso a n8n (que manda el correo): carga_con_error o revision_pendiente.
    Sin AVISOS_WEBHOOK_URL no hace nada."""
    url = getattr(settings, 'AVISOS_WEBHOOK_URL', '')
    if not url:
        return
    datos = {
        'evento': evento,
        'empresa': empresa.nombre,
        'mensaje': mensaje,
        'archivos': [{
            'archivo': c.nombre_original, 'tipo': c.get_tipo_display(), 'subido': c.creada.isoformat(),
            'usuario': c.usuario.username if c.usuario else '', 'email_usuario': c.usuario.email if c.usuario else '',
        } for c in cargas],
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(datos).encode(), headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        log.exception('No se pudo enviar el aviso a n8n')
