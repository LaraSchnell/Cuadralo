"""Panel interno del equipo de Cuádralo (/equipo/). Los clientes no tienen acceso."""
from django.contrib import admin

from .models import (Carga, Empresa, InteresModulo, MapeoAprobado, Perfil, Propuesta, RegistroAcceso,
                     RegistroActividad, RegistroIA)


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'slug', 'datos_ficticios', 'creada')
    prepopulated_fields = {'slug': ('nombre',)}


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'empresa', 'rol', 'hotel')
    list_filter = ('empresa', 'rol')


@admin.register(Carga)
class CargaAdmin(admin.ModelAdmin):
    list_display = ('creada', 'empresa', 'tipo', 'nombre_original', 'usuario', 'estado', 'eliminada_por', 'eliminada_en')
    list_filter = ('empresa', 'tipo', 'estado')


@admin.register(RegistroAcceso)
class RegistroAccesoAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'usuario', 'empresa', 'ip')
    list_filter = ('empresa',)


@admin.register(InteresModulo)
class InteresModuloAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'empresa', 'usuario', 'modulo')
    list_filter = ('modulo', 'empresa')


@admin.register(RegistroActividad)
class RegistroActividadAdmin(admin.ModelAdmin):
    """Quién vio qué página y qué exportó. Solo lectura: es un registro de auditoría."""
    list_display = ('fecha', 'usuario', 'empresa', 'accion', 'detalle')
    list_filter = ('empresa', 'accion')
    search_fields = ('usuario__username', 'detalle')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MapeoAprobado)
class MapeoAprobadoAdmin(admin.ModelAdmin):
    """Lo confirmado en «Revisar y confirmar». Borrar una fila hace que se vuelva a preguntar."""
    list_display = ('empresa', 'tipo', 'clase', 'origen', 'destino', 'fuente', 'confianza', 'aprobado_por', 'aprobado_en')
    list_filter = ('empresa', 'tipo', 'clase')


@admin.register(Propuesta)
class PropuestaAdmin(admin.ModelAdmin):
    list_display = ('creada', 'empresa', 'carga', 'clase', 'clave', 'sugerencia', 'fuente', 'confianza', 'estado')
    list_filter = ('empresa', 'estado', 'fuente')


@admin.register(RegistroIA)
class RegistroIAAdmin(admin.ModelAdmin):
    """Cada llamada a la IA: modelo, servidor y huella de lo enviado (nunca el contenido)."""
    list_display = ('fecha', 'empresa', 'tarea', 'modelo', 'servidor', 'n_preguntas', 'ok')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
