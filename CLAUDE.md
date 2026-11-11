# Cuádralo · instrucciones para Claude Code

Cuádralo es un producto B2B de control de gestión para hoteles: lee el informe mensual del operador (tipo Mews) y los movimientos de Business Central, los cuadra, calcula la cuenta de resultados hasta GOP2, explica cada desviación hasta la factura y lo enseña en una web.
Responde y escribe comentarios, mensajes de commit y textos de la interfaz en español. La usuaria (Lara) no es programadora web: explica cada paso en lenguaje sencillo y dile exactamente qué tiene que hacer ella (qué clic, qué comando).

## Reglas que no se rompen
1. **La IA propone, el código calcula, el equipo aprueba.** Ninguna cifra del informe la escribe un modelo de IA. Todas salen de código Python con fórmulas versionadas.
2. **Solo datos ficticios en este repositorio.** Nunca subas a GitHub, ni pegues en un chat, datos reales de clientes. Los datos reales solo viven en Azure (región UE).
3. **Configuración, no código a medida.** Lo que cambia entre clientes va en el Excel de configuración (plan_cuentas, conceptos_pms, parametros), nunca en `if cliente == ...`.
4. **Ninguna clave en el código.** Las claves van en Azure Key Vault o en variables de entorno; `.env` está en `.gitignore`.
5. **En producción, Azure OpenAI (zona UE) solo redacta** los textos de las desviaciones y los emails a partir del resultado de las reglas. Nunca genera cifras ni HTML.
6. Antes de dar algo por terminado, ejecuta las pruebas (`pytest`) y comprueba que detectan los 11 casos de `casos_plantados`.

## Documentación de referencia (en Google Drive de Lara)
- `06_arquitectura_mvp`: arquitectura, flujo, páginas del informe, fases.
- `07_estructura_datos`: tablas del modelo común, columnas y claves.

## Estructura del repositorio (objetivo)
```
datos_origen/            Excels ficticios de origen (operador, business_central, presupuesto)
configuracion_grupo_demo.xlsx   hoteles, cecos, plan_cuentas, conceptos_pms, estructura_informe, parametros, casos_plantados
cuadralo/
  normalizar.py          origen → modelo común (paso 1, hecho)
  calculos.py            cuenta de resultados hasta GOP2, actividad (ocupación, ADR, RevPAR)
  reglas.py              cuadre, ratios del operador, alertas de facturas, comparativa entre hoteles y desviaciones con su causa
  informe.py             rellena las plantillas HTML con los resultados
  plantillas/            HTML + Chart.js (6 páginas de grupo + una por hotel)
web/                     proyecto Django (login, empresa, subida, ver informe)
tests/                   pytest: cifras de octubre 2026 y los 11 casos sembrados
```

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
Python 3.12, pandas, openpyxl, Django, Azure App Service, Azure SQL Basic (unos 5 $/mes; la oferta gratuita no estaba disponible para esta cuenta), región Spain Central, Azure Blob Storage, Azure Key Vault, Azure OpenAI (zona UE), Chart.js. Todo en región UE.
