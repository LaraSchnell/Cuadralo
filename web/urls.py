from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from portal import views

admin.site.site_header = 'Cuádralo · administración interna'

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('subir/', views.subir, name='subir'),
    path('cargas/', views.cargas, name='cargas'),
    path('entrar/', auth_views.LoginView.as_view(), name='login'),
    path('salir/', auth_views.LogoutView.as_view(), name='logout'),
    path('equipo/', admin.site.urls),
]
