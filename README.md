# Cuádralo · Control de gestión hotelero (MVP)

Repositorio privado. Solo datos ficticios: nunca subir datos reales de clientes.

- `datos_origen/`: Excels ficticios del Grupo Demo Cuádralo (operador tipo Mews, Business Central, presupuesto).
- `configuracion_grupo_demo.xlsx`: configuración del cliente demo (plan de cuentas, conceptos del operador, parámetros, casos sembrados).
- `cuadralo/normalizar.py`: convierte los Excels de origen al modelo común.
- `cuadralo/comprobar.py`: compara el resultado con el Excel normalizado de referencia.
- `cuadralo/calculos.py`: cuenta de resultados hasta GOP2, KPIs (ocupación, ADR, RevPAR, GOPPAR, CPOR, labor cost…), presupuesto, cuadre operador–contabilidad y comprobación de ratios.
- `cuadralo/reglas.py`: motor de desviaciones (duplicada, otro mes, proveedor nuevo, factura que falta, subida de precio, falsa alarma) y coste estructural por room night.
- `cuadralo/informe.py`: prepara las páginas del informe (tarjetas, gráficos, alertas, frases) con las cifras calculadas.
- `portal/` y `web/`: la web Django (login, empresas, subida, informe de 5 páginas + comparativa de grupo, módulos opcionales con «Me interesa», historial de cargas).
- `infra/crear_recursos.sh`: crea los recursos de Azure desde Cloud Shell.
- `.github/workflows/desplegar.yml`: pruebas y publicación automática en Azure.

## Probar en local
```
pip install -r requirements.txt
set DJANGO_DEBUG=1            (Windows)   |   export DJANGO_DEBUG=1   (Mac/Linux)
python manage.py migrate
python manage.py crear_grupo_demo --hasta 2026-09
python manage.py runserver
pytest
```

Instrucciones para Claude Code en `CLAUDE.md`.
