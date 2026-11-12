"""Modelo de datos de la web.

Regla de aislamiento: todo lo que pertenece a un cliente cuelga de una Empresa, y cada consulta
de la web se filtra por la empresa del usuario (ver portal/acceso.py).
"""
from django.conf import settings
from django.db import models


def ruta_configuracion(instance, filename):
    return f'{instance.slug}/configuracion/{filename}'


def ruta_carga(instance, filename):
    return f'{instance.empresa.slug}/{instance.tipo}/{filename}'


class Empresa(models.Model):
    nombre = models.CharField(max_length=200)
    slug = models.SlugField(unique=True, help_text='Nombre corto; también es la carpeta de sus archivos.')
    configuracion = models.FileField(upload_to=ruta_configuracion,
                                     help_text='Excel de configuración: hoteles, plan de cuentas, conceptos del operador, parámetros.')
    datos_ficticios = models.BooleanField(default=False, help_text='Empresa de demostración: el informe lo indica en cada página.')
    creada = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.nombre


class Perfil(models.Model):
    DIRECCION = 'direccion'
    CONTABILIDAD = 'contabilidad'
    DIRECTOR_HOTEL = 'director_hotel'
    ROLES = [
        (DIRECCION, 'Dirección (ve todo el grupo)'),
        (CONTABILIDAD, 'Contabilidad (ve todo y sube archivos)'),
        (DIRECTOR_HOTEL, 'Director de hotel (solo su hotel)'),
    ]
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='perfil')
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='perfiles')
    rol = models.CharField(max_length=20, choices=ROLES)
    hotel = models.CharField(max_length=20, blank=True, help_text='Solo para director de hotel: Id del hotel (p. ej. MAR).')

    @property
    def puede_subir(self):
        return self.rol == self.CONTABILIDAD

    def __str__(self):
        return f'{self.usuario} · {self.empresa} · {self.get_rol_display()}'


class Carga(models.Model):
    OPERADOR = 'operador'
    BUSINESS_CENTRAL = 'business_central'
    PRESUPUESTO = 'presupuesto'
    TIPOS = [
        (OPERADOR, 'Informe del operador (tipo Mews)'),
        (BUSINESS_CENTRAL, 'Movimientos de Business Central'),
        (PRESUPUESTO, 'Presupuesto'),
    ]
    ESTADOS = [('pendiente', 'Pendiente'), ('ok', 'Procesada'), ('error', 'Error'), ('sustituida', 'Sustituida')]
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='cargas')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    tipo = models.CharField(max_length=20, choices=TIPOS)
    archivo = models.FileField(upload_to=ruta_carga, max_length=300)
    nombre_original = models.CharField(max_length=255)
    creada = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=12, choices=ESTADOS, default='pendiente')
    mensaje = models.TextField(blank=True)

    class Meta:
        ordering = ['-creada']


class InteresModulo(models.Model):
    """Clics en «Me interesa» de los módulos opcionales: así medimos qué módulo piden antes de construirlo."""
    MODULOS = [('reputacion', 'Reputación'), ('canales', 'Canales y marketing'), ('personas', 'Personas'),
               ('operaciones', 'Operaciones')]
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    modulo = models.CharField(max_length=20, choices=MODULOS)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']
        unique_together = [('empresa', 'usuario', 'modulo')]
        verbose_name = 'interés en un módulo'
        verbose_name_plural = 'interés en módulos opcionales'


class RegistroAcceso(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, null=True)
    fecha = models.DateTimeField(auto_now_add=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha']


# ---------- Modelo común (resultado de normalizar los archivos de cada empresa) ----------

class MovimientoContable(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    fecha_registro = models.DateField()
    fecha_documento = models.DateField()
    num_documento = models.CharField(max_length=50)
    num_documento_externo = models.CharField(max_length=80, blank=True)
    cuenta = models.CharField(max_length=20)
    descripcion = models.CharField(max_length=255)
    importe = models.DecimalField(max_digits=14, decimal_places=2)
    iva = models.DecimalField(max_digits=14, decimal_places=2)
    proveedor = models.CharField(max_length=200)
    finca = models.CharField(max_length=20)
    ceco = models.CharField(max_length=20, blank=True)

    class Meta:
        # Índices por empresa, hotel (finca), mes y proveedor: ver "Requisitos de rendimiento" en CLAUDE.md.
        indexes = [models.Index(fields=['empresa', 'fecha_registro']),
                   models.Index(fields=['empresa', 'finca', 'fecha_registro']),
                   models.Index(fields=['empresa', 'proveedor'])]


class FilaOperador(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    mes = models.DateField()
    hotel = models.CharField(max_length=20)
    departamento = models.CharField(max_length=60)
    concepto = models.CharField(max_length=80)
    medida = models.CharField(max_length=40)
    valor = models.DecimalField(max_digits=16, decimal_places=4)
    linea_informe = models.CharField(max_length=80, blank=True)
    columna_operador = models.CharField(max_length=120)

    class Meta:
        indexes = [models.Index(fields=['empresa', 'mes']),
                   models.Index(fields=['empresa', 'hotel', 'mes'])]


class FilaPresupuesto(models.Model):
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    mes = models.DateField()
    hotel = models.CharField(max_length=20)
    linea = models.CharField(max_length=80)
    tipo = models.CharField(max_length=60)
    importe = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        indexes = [models.Index(fields=['empresa', 'hotel', 'mes'])]
