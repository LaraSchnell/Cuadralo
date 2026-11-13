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
    necesita_procesar = models.BooleanField(
        default=False, help_text='Hay cargas nuevas o eliminadas sin procesar. El procesado en segundo plano lo pone a falso.')

    @property
    def por_confirmar(self):
        return self.propuestas.filter(estado='pendiente').count()

    @property
    def procesando(self):
        return self.necesita_procesar or self.cargas.filter(estado='pendiente').exists()

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
    RESERVAS = 'reservas'
    TIPOS = [
        (OPERADOR, 'Informe del operador (tipo Mews)'),
        (BUSINESS_CENTRAL, 'Movimientos de Business Central'),
        (PRESUPUESTO, 'Presupuesto'),
        (RESERVAS, 'Reservas del PMS (Mews)'),
    ]
    ESTADOS = [('pendiente', 'Procesando…'), ('ok', 'Procesada'), ('error', 'Error'), ('sustituida', 'Sustituida'),
               ('eliminada', 'Eliminada'), ('revisar', 'Por confirmar')]
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='cargas')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    tipo = models.CharField(max_length=20, choices=TIPOS)
    archivo = models.FileField(upload_to=ruta_carga, max_length=300)
    nombre_original = models.CharField(max_length=255)
    creada = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=12, choices=ESTADOS, default='pendiente')
    mensaje = models.TextField(blank=True)
    aviso = models.TextField(blank=True, help_text='Advertencias que no impiden procesar, p. ej. meses que ya venían en otro archivo.')
    huella = models.CharField(max_length=64, blank=True, db_index=True,
                              help_text='Huella SHA-256 del contenido: dos archivos idénticos tienen la misma huella.')
    eliminada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name='cargas_eliminadas')
    eliminada_en = models.DateTimeField(null=True, blank=True)

    @property
    def vigente(self):
        return self.estado in ('pendiente', 'ok')

    class Meta:
        ordering = ['-creada']


class Propuesta(models.Model):
    """Algo que un archivo trae y la configuración no conoce. Cuádralo propone y una persona confirma."""
    ESTADOS = [('pendiente', 'Pendiente'), ('aprobada', 'Confirmada'), ('descartada', 'Descartada')]
    FUENTES = [('ia', 'IA'), ('parecido', 'Parecido de nombres'), ('', 'Sin sugerencia')]
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='propuestas')
    carga = models.ForeignKey(Carga, on_delete=models.CASCADE, related_name='propuestas')
    tipo = models.CharField(max_length=20)
    clase = models.CharField(max_length=12)
    clave = models.CharField(max_length=300, help_text='Lo desconocido (o la columna que falta, si modo = falta).')
    modo = models.CharField(max_length=8, default='nueva')
    texto = models.CharField(max_length=500)
    opciones = models.JSONField(default=list)
    muestras = models.JSONField(default=list)
    sugerencia = models.CharField(max_length=300, blank=True)
    confianza = models.FloatField(null=True, blank=True)
    fuente = models.CharField(max_length=10, choices=FUENTES, blank=True)
    motivo = models.CharField(max_length=300, blank=True)
    estado = models.CharField(max_length=12, choices=ESTADOS, default='pendiente')
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['carga_id', 'clase', 'id']
        indexes = [models.Index(fields=['empresa', 'estado'])]


class MapeoAprobado(models.Model):
    """Lo que una persona confirmó: se añade a la configuración de la empresa (cuadralo/revision.aplicar_mapeos)."""
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name='mapeos')
    tipo = models.CharField(max_length=20)
    clase = models.CharField(max_length=12)
    origen = models.CharField(max_length=300)
    destino = models.CharField(max_length=300)
    sugerencia = models.CharField(max_length=300, blank=True)
    fuente = models.CharField(max_length=10, blank=True)
    confianza = models.FloatField(null=True, blank=True)
    aprobado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    aprobado_en = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('empresa', 'tipo', 'clase', 'origen')]
        verbose_name = 'mapeo confirmado'
        verbose_name_plural = 'mapeos confirmados'


class RegistroIA(models.Model):
    """Cada llamada a la IA: para qué, con qué modelo y servidor, y la huella de lo enviado (nunca el contenido)."""
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    fecha = models.DateTimeField(auto_now_add=True)
    tarea = models.CharField(max_length=40)
    modelo = models.CharField(max_length=100)
    servidor = models.CharField(max_length=200)
    huella_entrada = models.CharField(max_length=64)
    n_preguntas = models.IntegerField(default=0)
    ok = models.BooleanField(default=False)

    class Meta:
        ordering = ['-fecha']
        verbose_name = 'llamada a la IA'
        verbose_name_plural = 'llamadas a la IA'


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


class RegistroActividad(models.Model):
    """Qué página ve o qué exporta cada usuario (RGPD: registro de accesos a los datos)."""
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    fecha = models.DateTimeField(auto_now_add=True)
    accion = models.CharField(max_length=40, help_text='Vista: inicio, detalle, apuntes, exportar, subir, cargas, eliminar…')
    detalle = models.CharField(max_length=500, blank=True, help_text='Página y filtros pedidos (parámetros de la URL).')

    class Meta:
        ordering = ['-fecha']
        indexes = [models.Index(fields=['empresa', 'fecha'])]
        verbose_name = 'actividad de usuario'
        verbose_name_plural = 'actividad de usuarios'


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
    # Asignados al procesar (con el plan de cuentas de la empresa): permiten filtrar en la base de datos
    hotel = models.CharField(max_length=20, blank=True, default='')
    mes = models.DateField(null=True)
    linea = models.CharField(max_length=80, blank=True, default='')
    bloque = models.CharField(max_length=60, blank=True, default='')

    class Meta:
        # Índices por empresa, hotel (finca), mes y proveedor: ver "Requisitos de rendimiento" en CLAUDE.md.
        indexes = [models.Index(fields=['empresa', 'fecha_registro']),
                   models.Index(fields=['empresa', 'finca', 'fecha_registro']),
                   models.Index(fields=['empresa', 'proveedor']),
                   models.Index(fields=['empresa', 'hotel', 'mes', 'linea'])]


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


class Reserva(models.Model):
    """Una reserva del PMS. Sin nombres ni datos de contacto de los huéspedes: no hacen falta para el control de gestión."""
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    hotel = models.CharField(max_length=20)
    numero = models.CharField(max_length=40)
    estado = models.CharField(max_length=20)
    estancia = models.BooleanField()
    cancelada = models.BooleanField()
    origen = models.CharField(max_length=40, blank=True)
    detalle_origen = models.CharField(max_length=40, blank=True)
    agencia = models.CharField(max_length=120, blank=True)
    canal = models.CharField(max_length=80)
    tipo_canal = models.CharField(max_length=40)
    segmento = models.CharField(max_length=60, blank=True)
    tarifa = models.CharField(max_length=80, blank=True)
    tipo_habitacion = models.CharField(max_length=60, blank=True)
    fecha_creacion = models.DateTimeField(null=True)
    fecha_cancelacion = models.DateTimeField(null=True)
    llegada = models.DateField()
    salida = models.DateField()
    noches = models.IntegerField()
    adultos = models.IntegerField()
    ninos = models.IntegerField()
    nacionalidad = models.CharField(max_length=10, blank=True)
    motivo = models.CharField(max_length=40, blank=True)
    ingresos = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        indexes = [models.Index(fields=['empresa', 'hotel', 'llegada']),
                   models.Index(fields=['empresa', 'canal'])]


# ---------- Resultados precalculados (se rehacen cada vez que se procesan las cargas de la empresa) ----------

class ResultadoEmpresa(models.Model):
    """Tablas ya calculadas de una empresa (detalle contable agregado, actividad, cuadre, ratios, reservas agregadas).

    La web las lee tal cual: no vuelve a leer los apuntes ni a recalcular el histórico al abrir una página.
    """
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    clave = models.CharField(max_length=40)
    contenido = models.BinaryField()
    version = models.CharField(max_length=40)
    creado = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('empresa', 'clave')]


class ResultadoDesviacion(models.Model):
    """Desviaciones de un hotel y un mes, con sus causas: se calculan la primera vez que se piden y se guardan."""
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE)
    hotel = models.CharField(max_length=20)
    mes = models.DateField()
    contenido = models.BinaryField()

    class Meta:
        unique_together = [('empresa', 'hotel', 'mes')]
