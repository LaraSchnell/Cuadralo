"""Panel interno del equipo de Cuádralo (/equipo/). Los clientes no tienen acceso."""
from django.contrib import admin

from .models import Carga, Empresa, InteresModulo, Perfil, RegistroAcceso


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
    list_display = ('creada', 'empresa', 'tipo', 'nombre_original', 'usuario', 'estado')
    list_filter = ('empresa', 'tipo', 'estado')


@admin.register(RegistroAcceso)
class RegistroAccesoAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'usuario', 'empresa', 'ip')
    list_filter = ('empresa',)


@admin.register(InteresModulo)
class InteresModuloAdmin(admin.ModelAdmin):
    list_display = ('fecha', 'empresa', 'usuario', 'modulo')
    list_filter = ('modulo', 'empresa')
