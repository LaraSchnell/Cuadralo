"""Aislamiento entre empresas.

Cada vista de cliente usa `perfil_requerido` y toma la empresa SOLO del perfil del usuario,
nunca de la URL ni del formulario. Así un usuario no puede pedir datos de otra empresa.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.signals import user_logged_in
from django.core.exceptions import PermissionDenied
from django.dispatch import receiver


def perfil_requerido(vista):
    @login_required
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        perfil = getattr(request.user, 'perfil', None)
        if perfil is None:
            raise PermissionDenied('Tu usuario no pertenece a ninguna empresa.')
        request.perfil = perfil
        request.empresa = perfil.empresa
        _relanzar_si_quedo_a_medias(request.empresa)
        _registrar_actividad(request, vista.__name__)
        return vista(request, *args, **kwargs)
    return envoltura


def _relanzar_si_quedo_a_medias(empresa):
    """Si Azure reinició la web en mitad de un procesado, se relanza en la siguiente visita."""
    from . import segundo_plano
    if empresa.necesita_procesar and not segundo_plano.en_marcha(empresa.id):
        segundo_plano.lanzar(empresa.id)
        empresa.refresh_from_db(fields=['necesita_procesar'])


def _registrar_actividad(request, accion):
    """Registro de quién ve qué: página, filtros y exportaciones (RGPD). Nunca guarda cifras ni datos."""
    from .models import RegistroActividad
    detalle = request.get_full_path()[:500]
    RegistroActividad.objects.create(usuario=request.user, empresa=request.empresa, accion=accion[:40], detalle=detalle)


@receiver(user_logged_in)
def registrar_acceso(sender, request, user, **kwargs):
    from .models import RegistroAcceso
    perfil = getattr(user, 'perfil', None)
    ip = None
    if request is not None:
        ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR')
        if ip and ip.count(':') == 1:  # App Service añade el puerto: "1.2.3.4:5678"
            ip = ip.split(':')[0]
    RegistroAcceso.objects.create(usuario=user, empresa=perfil.empresa if perfil else None, ip=ip or None)
