#!/bin/bash
# Arranque en Azure App Service: prepara la base de datos, el cliente demo y lanza la web.
set -e
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py crear_grupo_demo
# Los datos del Grupo Demo se cargan en segundo plano: la web arranca enseguida aunque la carga tarde unos minutos.
nohup python manage.py crear_grupo_demo --hasta 2026-09 > /tmp/carga_demo.log 2>&1 &
gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers 2 web.wsgi
