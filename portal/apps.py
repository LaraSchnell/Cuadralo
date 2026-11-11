from django.apps import AppConfig


class PortalConfig(AppConfig):
    name = 'portal'
    verbose_name = 'Portal de clientes'

    def ready(self):
        from . import acceso  # noqa: F401  registra la señal de accesos
