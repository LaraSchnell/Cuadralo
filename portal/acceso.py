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
        return vista(request, *args, **kwargs)
    return envoltura


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
