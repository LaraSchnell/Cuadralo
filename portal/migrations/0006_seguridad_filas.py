"""Seguridad por filas en Azure SQL (segunda barrera de aislamiento entre empresas).

En SQLite no hace nada. Para desactivarla de urgencia sin desplegar: infra/rls/desactivar.sql
en el editor de consultas de Azure.
"""
from django.db import migrations


def activar(apps, schema_editor):
    if schema_editor.connection.vendor != 'microsoft':
        return
    from portal.seguridad_bd import sql_activar
    schema_editor.execute(sql_activar())


def quitar(apps, schema_editor):
    if schema_editor.connection.vendor != 'microsoft':
        return
    from portal.seguridad_bd import sql_quitar
    schema_editor.execute(sql_quitar())


class Migration(migrations.Migration):
    dependencies = [('portal', '0005_precalculo')]
    operations = [migrations.RunPython(activar, quitar)]
