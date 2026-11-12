# Cuádralo · instrucciones para Claude Code

Cuádralo es un producto B2B de control de gestión para hoteles: lee el informe mensual del operador (tipo Mews), los movimientos de Business Central y las reservas del PMS (Mews), los cuadra, calcula la cuenta de resultados hasta GOP2, explica cada desviación hasta la factura y lo enseña en una web.
Responde y escribe comentarios, mensajes de commit y textos de la interfaz en español. La usuaria (Lara) no es programadora web: explica cada paso en lenguaje sencillo y dile exactamente qué tiene que hacer ella (qué clic, qué comando).

## Reglas que no se rompen
1. **La IA propone, el código calcula, el equipo aprueba.** Ninguna cifra del informe la escribe un modelo de IA. Todas salen de código Python con fórmulas versionadas.
2. **Solo datos ficticios en este repositorio.** Nunca subas a GitHub, ni pegues en un chat, datos reales de clientes. Los datos reales solo viven en Azure (región UE).
3. **Configuración, no código a medida.** Lo que cambia entre clientes va en el Excel de configuración (plan_cuentas, conceptos_pms, parametros), nunca en `if cliente == ...`.
4. **Ninguna clave en el código.** Las claves van en Azure Key Vault o en variables de entorno; `.env` está en `.gitignore`.
5. **En producción, Azure OpenAI (zona UE) solo redacta** los textos de las desviaciones y los emails a partir del resultado de las reglas. Nunca genera cifras ni HTML.
6. Antes de dar algo por terminado, ejecuta las pruebas (`pytest`) y comprueba que detectan los 11 casos de `casos_plantados`.

## Requisitos de rendimiento (obligatorios en todo el código nuevo)
Un hotel grande puede tener 20.000-50.000 apuntes al mes (hasta ~1,8 millones de filas en 3 años). El código tiene que aguantarlo:
1. **Inserción masiva**: guardar con `bulk_create` (o bulk insert / `fast_executemany`), nunca fila a fila. Construir las filas con `zip` sobre columnas, nunca con `iterrows`.
2. **Lector rápido de Excel**: `pd.read_excel(..., engine='calamine')` (constante `MOTOR_EXCEL` en `normalizar.py`).
3. **Procesado en segundo plano**: subir → "Procesando…" → aviso al terminar. Nada que pueda tardar más de unos segundos se ejecuta mientras la petición web espera (App Service corta a los ~4 minutos).
4. **Índices** por empresa, hotel y mes en todas las tablas de hechos, y por proveedor en los movimientos.
5. **El informe lee resultados ya calculados** (tablas de resultados por empresa, hotel y mes), nunca recalcula todo el histórico al abrir una página.
6. **Paginación y filtros en la base de datos**: ninguna tabla de apuntes carga todas las filas en memoria ni en el navegador.
7. **Prueba con un hotel gigante** ficticio (50.000 apuntes al mes, 34 meses) antes de dar por terminado el paso 3. Objetivo: subir y procesar un mes < 2 min; abrir informe y apuntes < 2 s.

Estado (12 nov 2026, tarde): cumplidos 1, 2, 4 y 5 (precálculo en portal/precalculo.py: al procesar se guardan las tablas del informe en ResultadoEmpresa y las desviaciones por hotel y mes en ResultadoDesviacion; la web solo las lee). 6 en parte: el detalle de facturas y reservas y la página de apuntes filtran y paginan en la base de datos. Pendientes 3 (procesado en segundo plano) y 7 (hotel gigante).

## Aislamiento entre empresas (lo más importante del producto)
- La empresa sale SIEMPRE del perfil del usuario (portal/acceso.py), nunca de la URL. Toda consulta a tablas de clientes filtra por `empresa=request.empresa`.
- Los hoteles visibles salen del perfil (director de hotel = solo el suyo); lo que llega por la URL se valida contra esa lista.
- tests/test_paso6_aislamiento.py recorre todas las URLs (páginas, detalle, apuntes, exportaciones) como otra empresa y como director de hotel. Cualquier URL nueva se añade ahí.
- Segunda barrera: seguridad por filas (row-level security) en Azure SQL (portal/seguridad_bd.py, migración 0006, infra/rls/LEEME.md). ContextoEmpresaMiddleware declara la empresa del usuario en cada petición; sin empresa en la sesión, Azure SQL no devuelve ninguna fila. Tabla nueva con empresa → añadirla a TABLAS_PROTEGIDAS + migración. Tareas fuera de una petición (comandos, segundo plano) → `with contexto_empresa(id)` o `with contexto_interno()`. tests/test_paso7_seguridad_filas.py lo vigila. Estado: rama `seguridad-filas`, pendiente de probar con infra/rls/2_probar.sql en una copia de la base de datos y de unir a main después de la demo del 18 nov.

## Documentación de referencia (en Google Drive de Lara)
- `06_arquitectura_mvp`: arquitectura, flujo, páginas del informe, fases.
- `07_estructura_datos`: tablas del modelo común, columnas y claves.

## Estructura del repositorio (objetivo)
```
datos_origen/            Excels ficticios de origen (operador, business_central, presupuesto, reservas)
configuracion_grupo_demo.xlsx   hoteles, cecos, plan_cuentas, conceptos_pms, estructura_informe, parametros, casos_plantados,
                                columnas_reservas (columnas de Mews → campos) y canales (origen/agencia de Mews → canal)
herramientas/generar_reservas.py  genera las reservas ficticias, cuadradas con el informe del operador
cuadralo/
  normalizar.py          origen → modelo común (paso 1, hecho)
  calculos.py            KPIs, cuadre, comprobación de ratios, cuenta de resultados hasta GOP2, labor cost
  reglas.py              motor de desviaciones (duplicada, otro mes, proveedor nuevo, subida de precio, factura que falta, falsa alarma)
  reservas.py            noches por mes, canales, perfil del cliente y cuadre reservas–operador
  informe.py             contenido del informe para una selección (varios meses, hoteles, ceco, proveedor, canal):
                         tarjetas, gráficos con su texto y tooltip ya escritos, y qué filtra cada clic
  plantillas/            HTML + Chart.js (6 páginas de grupo + una por hotel)
web/                     proyecto Django (login, empresa, subida, ver informe)
tests/                   pytest: cifras de octubre 2026 y los 11 casos sembrados
```

## Informe en la web (desde el 12 nov 2026)
- Filtros: periodo año > mes (varios meses), hotel, ceco, proveedor y canal. Las tarjetas suman los meses elegidos y los gráficos de barras solo enseñan esos meses.
- Cada página: tarjetas arriba, gráficos en el centro (Chart.js, en portal/static/portal/vendor), tablas abajo. Poco texto.
- Cada punto de un gráfico trae desde Python su texto (encima) y su ayuda (tooltip con valor y %): el navegador no calcula cifras.
- Clic en un gráfico o en una fila → vista `detalle` (JSON) con las facturas o las reservas de donde sale la cifra.
- Perfiles: dirección y contabilidad ven todo; el director de hotel ve resumen, ventas, resultados y desviaciones de su hotel.
- Reservas: sin nombres ni datos de contacto de huéspedes. Canal, segmento, país, personas, noches e ingresos.

## Cálculos (fuente de verdad: hoja estructura_informe y parametros)
- Facturación de habitaciones = importe de alojamiento del operador. ADR = alojamiento / room nights. Room nights × ADR del operador solo sirve para comprobar el ratio.
- Ocupación = room nights / (habitaciones × días del mes). RevPAR = alojamiento / (habitaciones × días del mes).
- Captación desayuno = desayunos / (room nights × pax por habitación).
- Cuadre por línea de ingreso: operador − Business Central; cuadra si |diferencia| ≤ tolerancia_cuadre_eur.
- Plan de cuentas: si existe fila con el ceco concreto manda esa; si no, la de "(cualquiera)".
- En el export de Business Central los ingresos (cuentas 7…) vienen en negativo; normalizar.py les cambia el signo.
- GOP = ingresos − consumos − personal − otros gastos operativos. AGOP = GOP − honorarios del operador − reserva FF&E (ingresos × reserva_ffe_pct). GOP2 = AGOP − tributos − amortizaciones − gastos financieros.
- Labor cost = total personal / total ingresos; personal desayunos / desayunos servidos; personal hotel / room nights.
- Desviación: más de umbral_desviacion_pct y más de umbral_desviacion_eur frente a presupuesto o año anterior.

## Cifras de control (octubre 2026, datos ficticios)
| Hotel | Ingresos | GOP | AGOP | GOP2 |
|---|---|---|---|---|
| Mar | 372.727,14 | 169.763,81 | 143.454,00 | 120.501,69 |
| Gracia | 169.324,21 | 65.917,85 | 54.029,75 | 41.119,07 |
| Born | 283.193,02 | 139.183,76 | 119.579,16 | 102.364,93 |
| Sitges | 333.910,13 | 181.016,34 | 157.596,13 | 137.512,86 |
Cuadre esperado (operador − BC): Mar Minibar +7.296,89; Born Minibar −7.296,89; Gracia Alojamiento +1.180,00; Sitges Eventos +1.550,00.

## Stack
Python 3.12, pandas, openpyxl, Django, Azure App Service, Azure SQL (oferta gratuita), Azure Blob Storage, Azure Key Vault, Azure OpenAI (zona UE), Chart.js. Todo en región UE.
