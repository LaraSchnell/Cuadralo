"""Segunda barrera de aislamiento: seguridad por filas (row-level security) en Azure SQL.

La primera barrera está en Django: cada consulta filtra por `empresa=request.empresa` (portal/acceso.py).
Esta segunda barrera vive en la propia base de datos: aunque una consulta olvidara el filtro, Azure SQL
solo devuelve, y solo deja escribir, las filas de la empresa que la web ha declarado en la sesión.

Cómo funciona:
- En cada petición, ContextoEmpresaMiddleware guarda en la sesión de Azure SQL el id de la empresa del
  usuario (SESSION_CONTEXT 'empresa_id'). Al terminar la petición lo borra.
- La política `seguridad.politica_empresa` filtra todas las tablas de datos de clientes con
  `empresa_id = SESSION_CONTEXT('empresa_id')`. Sin empresa en la sesión no se ve ninguna fila.
- El equipo interno de Cuádralo (superusuario sin perfil de empresa) y los comandos internos
  (carga del Grupo Demo, migraciones de datos) usan `cuadralo_interno = 1`, que ve todas las empresas.
- El director de hotel sigue limitado a su hotel por la web (acceso.py); esta barrera es por empresa.

En SQLite (desarrollo y pruebas) todo esto no hace nada.

Tablas nuevas con datos de clientes: añadirlas a TABLAS_PROTEGIDAS y crear una migración que vuelva
a ejecutar sql_activar(). tests/test_paso7_seguridad_filas.py falla si un modelo con empresa no está
ni aquí ni en TABLAS_SIN_RLS.
"""
from contextlib import contextmanager

from django.db import connection

POLITICA = 'seguridad.politica_empresa'
FUNCION = 'seguridad.fn_empresa'

# Tablas con datos de clientes: filtradas y bloqueadas por empresa en la base de datos.
TABLAS_PROTEGIDAS = [
    'portal_carga',
    'portal_interesmodulo',
    'portal_movimientocontable',
    'portal_filaoperador',
    'portal_filapresupuesto',
    'portal_reserva',
    'portal_resultadoempresa',
    'portal_resultadodesviacion',
]

# Tablas con empresa que NO llevan la barrera, y por qué.
TABLAS_SIN_RLS = {
    'portal_perfil': 'Se lee al iniciar sesión, antes de saber la empresa del usuario.',
    'portal_registroacceso': 'Se escribe al iniciar sesión, antes de fijar la empresa en la sesión.',
}


def sql_activar():
    """Script que crea (o vuelve a crear) la función y la política. Un solo lote, sin GO."""
    predicados = []
    for tabla in TABLAS_PROTEGIDAS:
        predicados += [
            f'ADD FILTER PREDICATE {FUNCION}(empresa_id) ON dbo.{tabla}',
            f'ADD BLOCK PREDICATE {FUNCION}(empresa_id) ON dbo.{tabla} AFTER INSERT',
            f'ADD BLOCK PREDICATE {FUNCION}(empresa_id) ON dbo.{tabla} AFTER UPDATE',
        ]
    politica = f'CREATE SECURITY POLICY {POLITICA}\n' + ',\n'.join(predicados) + '\nWITH (STATE = ON)'
    return f"""-- Cuádralo · activar la seguridad por filas (generado por portal/seguridad_bd.py, no editar a mano)
IF SCHEMA_ID(N'seguridad') IS NULL EXEC(N'CREATE SCHEMA seguridad');
IF OBJECT_ID(N'{POLITICA}', N'SP') IS NOT NULL DROP SECURITY POLICY {POLITICA};
IF OBJECT_ID(N'{FUNCION}', N'IF') IS NOT NULL DROP FUNCTION {FUNCION};
EXEC(N'CREATE FUNCTION {FUNCION}(@empresa_id int)
RETURNS TABLE WITH SCHEMABINDING AS
RETURN SELECT 1 AS permitido
WHERE @empresa_id = CAST(SESSION_CONTEXT(N''empresa_id'') AS int)
   OR CAST(SESSION_CONTEXT(N''cuadralo_interno'') AS int) = 1');
EXEC(N'{politica}');
"""


def sql_quitar():
    return f"""-- Cuádralo · quitar la seguridad por filas (generado por portal/seguridad_bd.py, no editar a mano)
IF OBJECT_ID(N'{POLITICA}', N'SP') IS NOT NULL DROP SECURITY POLICY {POLITICA};
IF OBJECT_ID(N'{FUNCION}', N'IF') IS NOT NULL DROP FUNCTION {FUNCION};
"""


def activa():
    """La barrera solo existe en Azure SQL (mssql-django declara vendor 'microsoft')."""
    return connection.vendor == 'microsoft'


def _ejecutar(sql, parametros):
    with connection.cursor() as cursor:
        cursor.execute(sql, parametros)


def fijar_contexto(empresa_id=None, interno=False):
    """Declara en la sesión de Azure SQL qué empresa ve esta conexión. Sin argumentos: ninguna."""
    if not activa():
        return
    # Variables int declaradas: así el conector no tiene que adivinar el tipo (sql_variant) del parámetro.
    _ejecutar(
        "DECLARE @empresa int = %s, @interno int = %s; "
        "EXEC sp_set_session_context @key=N'empresa_id', @value=@empresa; "
        "EXEC sp_set_session_context @key=N'cuadralo_interno', @value=@interno;",
        [empresa_id, 1 if interno else None],
    )


@contextmanager
def contexto_interno():
    """Para comandos internos (carga del Grupo Demo, tareas en segundo plano): ve todas las empresas."""
    fijar_contexto(interno=True)
    try:
        yield
    finally:
        fijar_contexto()


@contextmanager
def contexto_empresa(empresa_id):
    """Para tareas de una sola empresa fuera de una petición web (p. ej. el procesado en segundo plano)."""
    fijar_contexto(empresa_id=empresa_id)
    try:
        yield
    finally:
        fijar_contexto()


def contexto_de_usuario(user):
    """(empresa_id, interno) que corresponde a un usuario."""
    if user is None or not user.is_authenticated:
        return None, False
    perfil = getattr(user, 'perfil', None)
    if perfil is not None:
        return perfil.empresa_id, False
    return None, bool(user.is_superuser)


class ContextoEmpresaMiddleware:
    """Fija la empresa del usuario en la sesión de Azure SQL al empezar cada petición y la borra al acabar."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not activa():
            return self.get_response(request)
        empresa_id, interno = contexto_de_usuario(getattr(request, 'user', None))
        fijar_contexto(empresa_id=empresa_id, interno=interno)
        try:
            return self.get_response(request)
        finally:
            fijar_contexto()
