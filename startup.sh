#!/bin/bash
# Arranque en Azure App Service. Pensado para el plan F1, que para la web si en 5 minutos gasta más de
# 3 minutos de CPU o más de 1 GB de memoria: el arranque hace lo mínimo y con un solo proceso de la web.
set -e
python manage.py migrate --noinput

# Archivos estáticos (CSS, JS, Chart.js): solo se vuelven a preparar si han cambiado desde el último arranque.
HUELLA=$(find portal/static -type f -exec md5sum {} + | sort | md5sum | cut -d' ' -f1)
if [ ! -f staticfiles/staticfiles.json ] || [ "$(cat staticfiles/.huella 2>/dev/null)" != "$HUELLA" ]; then
    python manage.py collectstatic --noinput
    echo "$HUELLA" > staticfiles/.huella
fi

# Grupo Demo: empresas, usuarios y, si faltan, los datos hasta septiembre. Un solo proceso, en segundo plano,
# para que la web arranque enseguida. Si los datos ya están, termina en unos segundos.
nohup python manage.py crear_grupo_demo --hasta 2026-09 > /tmp/carga_demo.log 2>&1 &

# Un proceso con 4 hilos en lugar de 2 procesos: los datos del informe se cargan en memoria una sola vez.
gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers 1 --threads 4 web.wsgi
