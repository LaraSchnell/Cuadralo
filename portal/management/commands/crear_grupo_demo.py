"""Crea el cliente ficticio Grupo Demo Cuádralo, sus usuarios y una segunda empresa para la prueba de aislamiento.

Uso:
  python manage.py crear_grupo_demo                  # empresas y usuarios, sin datos
  python manage.py crear_grupo_demo --hasta 2026-09  # además carga el histórico hasta septiembre de 2026
                                                     # (octubre se sube en directo en la demo)
Contraseñas: variables DEMO_PASSWORD_DIRECTOR, DEMO_PASSWORD_CONTABLE y DEMO_PASSWORD_PRUEBA.
Si no existen, se generan y se muestran una sola vez.
"""
import os
import re
import secrets
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from portal.models import Carga, Empresa, Perfil
from portal import precalculo
from portal.seguridad_bd import contexto_interno
from portal.procesar import procesar_empresa, registrar_carga

USUARIOS = [
    ('grupo-demo', 'director.demo', Perfil.DIRECCION, 'DEMO_PASSWORD_DIRECTOR'),
    ('grupo-demo', 'contable.demo', Perfil.CONTABILIDAD, 'DEMO_PASSWORD_CONTABLE'),
    ('prueba-aislamiento', 'usuario.prueba', Perfil.CONTABILIDAD, 'DEMO_PASSWORD_PRUEBA'),
]


class Command(BaseCommand):
    help = 'Crea el Grupo Demo Cuádralo (datos ficticios) y la empresa de prueba de aislamiento.'

    def add_arguments(self, parser):
        parser.add_argument('--hasta', help='Carga los datos de origen hasta este mes (AAAA-MM), ambos incluidos.')

    def handle(self, *args, **opciones):
        # Comando interno: con la seguridad por filas activa necesita ver y escribir en todas las empresas.
        with contexto_interno():
            self._handle(**opciones)

    def _handle(self, **opciones):
        empresas = {}
        for slug, nombre in [('grupo-demo', 'Grupo Demo Cuádralo'), ('prueba-aislamiento', 'Hotel Prueba Aislamiento')]:
            empresa, creada = Empresa.objects.get_or_create(slug=slug, defaults={'nombre': nombre, 'datos_ficticios': True})
            if not empresa.datos_ficticios:
                empresa.datos_ficticios = True
                empresa.save(update_fields=['datos_ficticios'])
            if creada or not empresa.configuracion:
                with open(settings.CONFIG_DEMO, 'rb') as f:
                    empresa.configuracion.save('configuracion.xlsx', File(f), save=True)
            empresas[slug] = empresa
            self.stdout.write(f'Empresa: {nombre}')

        User = get_user_model()
        for slug, usuario, rol, variable in USUARIOS:
            user, creado = User.objects.get_or_create(username=usuario)
            if not os.environ.get(variable) and not settings.DEBUG:
                raise CommandError(f'En Azure la contraseña de {usuario} debe venir de la variable {variable}.')
            if creado or os.environ.get(variable):
                clave = os.environ.get(variable) or secrets.token_urlsafe(12)
                user.set_password(clave)
                user.save()
                if not os.environ.get(variable):
                    self.stdout.write(self.style.WARNING(f'  {usuario}: contraseña generada {clave}  (guárdala, no se vuelve a mostrar)'))
            Perfil.objects.update_or_create(usuario=user, defaults={'empresa': empresas[slug], 'rol': rol})
            self.stdout.write(f'  Usuario {usuario} ({rol}) en {empresas[slug].nombre}')

        if opciones.get('hasta'):
            self.cargar(empresas['grupo-demo'], opciones['hasta'])

    def cargar(self, empresa, hasta):
        # Solo se cargan los tipos de archivo que la empresa aún no tiene (p. ej. las reservas, que llegaron después).
        ya = set(empresa.cargas.values_list('tipo', flat=True))
        faltan = {t for t, _ in Carga.TIPOS} - ya
        if not faltan:
            if precalculo.hay_precalculo(empresa):
                self.stdout.write('El Grupo Demo ya tiene datos cargados: no se vuelven a cargar.')
            else:   # datos de una versión anterior: se reprocesan para guardar el precálculo
                ok, mensaje = procesar_empresa(empresa)
                self.stdout.write((self.style.SUCCESS if ok else self.style.ERROR)(mensaje))
            return
        contable = get_user_model().objects.get(username='contable.demo')
        base = Path(settings.DATOS_DEMO)
        for tipo, carpeta in [(Carga.OPERADOR, 'operador'), (Carga.BUSINESS_CENTRAL, 'business_central'),
                              (Carga.PRESUPUESTO, 'presupuesto'), (Carga.RESERVAS, 'reservas')]:
            if tipo not in faltan:
                continue
            for ruta in sorted((base / carpeta).glob('*.xlsx')):
                meses = re.findall(r'(20\d\d-\d\d)', ruta.name)
                if tipo != Carga.PRESUPUESTO and meses and meses[-1] > hasta:
                    continue
                with open(ruta, 'rb') as f:
                    registrar_carga(empresa, contable, tipo, File(f, name=ruta.name))
        ok, mensaje = procesar_empresa(empresa)
        self.stdout.write((self.style.SUCCESS if ok else self.style.ERROR)(mensaje))
