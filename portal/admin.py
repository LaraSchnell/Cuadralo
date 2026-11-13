"""Panel interno del equipo de Cuádralo (/equipo/). Los clientes no tienen acceso."""
from django.contrib import admin

from .models import Carga, Empresa, InteresModulo, Perfil, RegistroAcceso, RegistroActividad


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
