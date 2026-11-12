# Seguridad por filas en Azure SQL

Segunda barrera de aislamiento entre empresas. La primera es el filtro de Django (`portal/acceso.py`).
Con esta, aunque una consulta olvidara el filtro, Azure SQL solo devuelve y solo deja escribir
las filas de la empresa del usuario. Código: `portal/seguridad_bd.py` y la migración `0006_seguridad_filas`.

| Archivo | Para qué |
|---|---|
| `1_activar.sql` | Crea la función y la política (lo mismo que hace la migración). Se puede repetir. |
| `2_probar.sql` | Comprueba, tabla por tabla, que sin empresa no se ve nada, que cada empresa ve solo lo suyo y que no puede escribir en otra. No cambia datos. |
| `3_desactivar_urgencia.sql` | Apaga la política al momento, sin desplegar, si algo falla en la web. |
| `4_quitar.sql` | Borra la función y la política. |

`1_activar.sql` y `4_quitar.sql` se generan desde `portal/seguridad_bd.py`; una prueba comprueba que coinciden.

## Prueba en una base de datos de pruebas (antes de publicar)
1. Portal de Azure → base de datos `cuadralo` → **Copiar** → nombre `cuadralo-pruebas`, mismo servidor, plan Basic.
2. En `cuadralo-pruebas` → **Editor de consultas** → entrar con el usuario de la base de datos.
3. Pegar y ejecutar `1_activar.sql`.
4. Pegar y ejecutar `2_probar.sql`. Todas las filas deben decir **OK** y la última tabla, `fallos = 0`.
5. Borrar `cuadralo-pruebas` al terminar (cuesta dinero mientras exista).

## Si algo falla en producción
Editor de consultas de `cuadralo` → ejecutar `3_desactivar_urgencia.sql`. La web vuelve a funcionar
solo con el filtro de Django, que sigue activo.

## Reglas para el código nuevo
- Tabla nueva con datos de clientes: añadirla a `TABLAS_PROTEGIDAS` y crear una migración que vuelva a ejecutar `sql_activar()`.
- Tarea fuera de una petición web (procesado en segundo plano, comandos): `with contexto_empresa(id):` o, si es interna, `with contexto_interno():`. Sin eso no verá ninguna fila.
- No se puede cambiar la columna `empresa_id` de una tabla protegida sin quitar antes la política.
