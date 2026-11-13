# Cuádralo · Recorrido completo del código (GitHub y Azure)

Actualizado el 13 nov 2026. Este documento sigue **lo que pasa de verdad** en el código, caso por caso, para que lo puedas ir comprobando en GitHub y en Azure a la vez.

---

## 0. Cómo usar este documento

1. Abre dos pestañas: **GitHub** (`github.com/LaraSchnell/Cuadralo`) y **Azure** (`portal.azure.com`).
2. Cada paso dice **qué archivo** abrir y **qué buscar** dentro. En GitHub, abre el archivo y pulsa `Ctrl+F` con el texto entre comillas (por ejemplo, "def subir"). Los números de línea cambian con cada cambio, así que buscamos por nombre.
3. Los enlaces a archivos de este documento funcionan si lo abres desde GitHub (carpeta `docs/`).
4. **Dudas:** escríbelas en la sección final "Mis dudas" o pégamelas en el chat indicando el número de paso (por ejemplo, "2.4").

### Cómo leer un archivo de Python en 30 segundos
- `def nombre(...)`: una función, un paso que se puede llamar desde otro sitio.
- `class Nombre`: en `models.py` es una **tabla de la base de datos**, y cada línea `campo = models...` es una columna.
- El texto entre `"""` triples al principio de una función explica qué hace. Lee eso primero.
- `@perfil_requerido` encima de una función: solo entra un usuario con sesión y perfil (ver Caso 1).

---

## 1. Mapa: dónde vive cada cosa

### 1.1 GitHub (el código)

| Carpeta o archivo | Qué es | En tu mundo (Fabric/Power BI) |
|---|---|---|
| [`web/settings.py`](../web/settings.py) | Configuración de la web: base de datos, Blob, idioma, variables | La configuración del workspace |
| [`web/urls.py`](../web/urls.py) | **La lista de páginas**: qué dirección abre qué función | El menú de páginas del informe |
| [`portal/views.py`](../portal/views.py) | **Lo que hace cada página** (una función por página) | La lógica detrás de cada página |
| [`portal/templates/portal/`](../portal/templates/portal/) | **El HTML de cada página** (lo que se ve) | El diseño visual del informe |
| [`portal/static/portal/`](../portal/static/portal/) | Estilos (`estilo.css`), interacción (`informe.js`) y Chart.js (`vendor/`) | El tema y los visuales |
| [`portal/models.py`](../portal/models.py) | **Las tablas de la base de datos** | El esquema de la base de datos |
| [`portal/acceso.py`](../portal/acceso.py) | Quién es el usuario, de qué empresa y qué puede ver | La seguridad por filas (RLS) de Power BI |
| [`portal/procesar.py`](../portal/procesar.py) | Del archivo subido a las tablas SQL (orquesta los pasos) | El pipeline |
| [`portal/segundo_plano.py`](../portal/segundo_plano.py) | Hace el procesado sin que la web espere | El trigger del pipeline |
| [`portal/precalculo.py`](../portal/precalculo.py) | Guarda el informe ya calculado | La capa gold / refresco del modelo |
| [`cuadralo/normalizar.py`](../cuadralo/normalizar.py) | Traduce cada Excel al modelo común | Notebook bronze → silver |
| [`cuadralo/revision.py`](../cuadralo/revision.py) | Detecta lo que la configuración no conoce | Validación de calidad de datos |
| [`cuadralo/sugerencias.py`](../cuadralo/sugerencias.py), [`cuadralo/ia.py`](../cuadralo/ia.py) | Propone respuestas (parecido de nombres y Azure OpenAI) | — |
| [`cuadralo/calculos.py`](../cuadralo/calculos.py) | KPIs, cuadre, cuenta de resultados hasta GOP2 | Las medidas DAX |
| [`cuadralo/reglas.py`](../cuadralo/reglas.py) | Motor de desviaciones (duplicada, otro mes…) | — |
| [`cuadralo/reservas.py`](../cuadralo/reservas.py) | Noches, canales y cuadre de reservas | Medidas de reservas |
| [`cuadralo/informe.py`](../cuadralo/informe.py) | Arma tarjetas, gráficos y tablas para lo que el usuario ha filtrado | Los visuales con sus medidas |
| [`configuracion_grupo_demo.xlsx`](../configuracion_grupo_demo.xlsx) | El diccionario del cliente: hoteles, plan de cuentas, conceptos… | Tablas de mapeo |
| [`datos_origen/`](../datos_origen/) | Excels ficticios de origen (operador, BC, presupuesto, reservas) | Los archivos de la capa bronze |
| [`tests/`](../tests/) | Pruebas automáticas (64): si alguna falla, no se publica | — |
| [`.github/workflows/desplegar.yml`](../.github/workflows/desplegar.yml) | Qué hace GitHub con cada cambio: probar y publicar | El pipeline de despliegue |
| [`startup.sh`](../startup.sh) | Lo que hace Azure al arrancar la web | — |
| [`infra/crear_recursos.sh`](../infra/crear_recursos.sh) | Script que creó todos los recursos de Azure | Infraestructura |
| [`CLAUDE.md`](../CLAUDE.md) | Instrucciones y estado del proyecto para Claude Code | — |

### 1.2 Azure (dónde corre)

Todo está en el grupo de recursos **`cuadralo-rg`**, región Spain Central. Los nombres llevan un sufijo aleatorio de 5 letras (lo verás en el portal).

| Recurso | Nombre | Qué guarda o hace | Variables en la web que lo conectan |
|---|---|---|---|
| App Service (web) | `cuadralo-demo-<sufijo>` | Ejecuta el código de GitHub | — |
| Plan de App Service | `cuadralo-plan` | La "máquina" de la web (F1 gratis o B1) | — |
| Azure SQL (servidor + base) | `cuadralo-sql-<sufijo>` / `cuadralo` | Todas las tablas de `models.py` | `AZURE_SQL_SERVER`, `AZURE_SQL_DATABASE`, `AZURE_SQL_USER`, `AZURE_SQL_PASSWORD` |
| Cuenta de almacenamiento | `cuadralost<sufijo>`, contenedor `cargas` | Los Excels originales (Blob) | `AZURE_STORAGE_ACCOUNT_NAME`, `AZURE_STORAGE_ACCOUNT_KEY`, `AZURE_STORAGE_CONTAINER` |
| Key Vault | `cuadralo-kv-<sufijo>` | Las contraseñas y claves (la web las lee por referencia) | Las variables de arriba apuntan aquí |
| Azure OpenAI (pendiente) | El que crees | Propuestas de la IA | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT` |

**Cómo se conectan GitHub y Azure:** en [`web/settings.py`](../web/settings.py) busca "AZURE_SQL_SERVER" y "AZURE_STORAGE_ACCOUNT_NAME". Si esas variables existen (en Azure sí), la web usa Azure SQL y Blob. Si no existen (en tu ordenador o en las pruebas), usa una base de datos local (SQLite) y una carpeta `media/`. **El mismo código funciona en los dos sitios.**

---

## 2. Caso 1 · Entrar en la web

| Paso | Qué pasa | GitHub: dónde mirarlo | Azure: dónde verlo |
|---|---|---|---|
| 1.1 | El usuario abre la web sin sesión y le manda a `/entrar/` | [`web/urls.py`](../web/urls.py): busca "entrar/". Usa la pantalla de login que trae Django | — |
| 1.2 | Ve el formulario de usuario y contraseña | [`portal/templates/registration/login.html`](../portal/templates/registration/login.html) | — |
| 1.3 | Django comprueba la contraseña contra la tabla de usuarios | Viene con Django (tabla `auth_user`) | SQL: tabla `auth_user` |
| 1.4 | Se apunta el acceso: usuario, empresa, fecha, IP | [`portal/acceso.py`](../portal/acceso.py): busca "RegistroAcceso" | SQL: tabla `portal_registroacceso` · Web: `/equipo/` → Registros de acceso |
| 1.5 | En **cada página**, se mira su perfil: empresa, rol y hotel | [`portal/acceso.py`](../portal/acceso.py): busca "def perfil_requerido". Pone `request.empresa` y `request.perfil` | SQL: tabla `portal_perfil` |
| 1.6 | Se apunta qué página pide (registro de actividad) | [`portal/acceso.py`](../portal/acceso.py): busca "def _registrar_actividad" | SQL: `portal_registroactividad` · `/equipo/` → Actividad de usuarios |

**Roles:** Dirección (ve todo el grupo) · Contabilidad o gestión (ve todo, sube archivos y confirma) · Director de hotel (solo su hotel; no ve el historial de cargas). Si un hotel no tiene contable, a su director se le da el rol **Contabilidad o gestión**.

**Quién da de alta a los usuarios:** vosotros, en `/equipo/` (el panel de administración de Django). Se crea el usuario y su **Perfil** (empresa + rol: dirección, contabilidad o director de hotel + hotel). Ver la tabla `Perfil` en [`portal/models.py`](../portal/models.py): busca "class Perfil".

**Regla de oro del aislamiento:** la empresa sale SIEMPRE del perfil, nunca de la dirección de la página. Por eso un usuario no puede cambiar la URL para ver otra empresa.

---

## 3. Caso 2 · Subir un Excel

| Paso | Qué pasa | GitHub | Azure |
|---|---|---|---|
| 2.1 | El usuario de contabilidad abre "Subir archivos" | [`web/urls.py`](../web/urls.py): "subir/" → función `subir` | — |
| 2.2 | Ve la página: elige tipo y archivos. **Informe del operador** = resumen mensual por hotel (room nights, ingresos por departamento, ratios). **Reservas del PMS** = el detalle reserva a reserva de Mews (canal, país, fechas, noches), sin datos personales | [`portal/templates/portal/subir.html`](../portal/templates/portal/subir.html) | — |
| 2.3 | Pulsa Subir: la función comprueba permiso, tipo y que sea .xlsx | [`portal/views.py`](../portal/views.py): busca "def subir" | — |
| 2.4 | Calcula la **huella** del archivo y mira si ya existe uno idéntico | [`portal/procesar.py`](../portal/procesar.py): "def huella_de" y "def carga_identica" | — |
| 2.5 | Si es idéntico: no lo sube y avisa "no se ha subido: es idéntico a…" | [`portal/views.py`](../portal/views.py): dentro de `subir`, "messages.warning" | — |
| 2.6 | Si es nuevo: lo registra y **guarda el original en el Blob** | [`portal/procesar.py`](../portal/procesar.py): "def registrar_carga". El archivo se guarda al crear la `Carga` (campo `archivo`), en la ruta de "def ruta_carga" de [`portal/models.py`](../portal/models.py) | Cuenta de almacenamiento → Contenedores → `cargas` → carpeta de la empresa → tipo → archivo |
| 2.7 | Se crea la fila de la carga (estado "Procesando…") | Tabla `Carga` en [`portal/models.py`](../portal/models.py): "class Carga" | SQL: `portal_carga` |
| 2.8 | Lanza el procesado en segundo plano y responde al momento | [`portal/segundo_plano.py`](../portal/segundo_plano.py): "def lanzar" | — |
| 2.9 | Redirige al historial de cargas, que se refresca cada 5 s mientras procesa | [`portal/templates/portal/cargas.html`](../portal/templates/portal/cargas.html): busca "location.reload" · vista "def cargas" | — |

**"Sustituye" y "no pisa" son dos cosas distintas:**
- **En el informe sí sustituye:** si subes un archivo con el mismo nombre y tipo, el anterior pasa a "Sustituida" y sus datos dejan de contar.
- **En el Blob no se borra nada:** los dos archivos quedan guardados (el nuevo con un sufijo en el nombre), para poder auditar. Lo controla "overwrite_files" en [`web/settings.py`](../web/settings.py), que está en `False`.

---

## 4. Caso 3 · Procesar el archivo (lo que pasa sin que el usuario espere)

Todo empieza en [`portal/segundo_plano.py`](../portal/segundo_plano.py) → "def _procesar", que llama a `procesar_empresa` de [`portal/procesar.py`](../portal/procesar.py). Abre esa función ("def procesar_empresa") y verás los pasos en este orden:

| Paso | Qué pasa | GitHub | Resultado |
|---|---|---|---|
| 3.1 | Lee la configuración de la empresa: su Excel **más** lo confirmado en "Revisar y confirmar" | [`portal/procesar.py`](../portal/procesar.py): "def leer_configuracion" | Diccionario con las hojas (hoteles, plan_cuentas…) |
| 3.2 | **Revisión:** mira los archivos nuevos por si traen algo desconocido | "def revisar_cargas_nuevas" → [`cuadralo/revision.py`](../cuadralo/revision.py) "def detectar" | Si hay algo: el archivo queda "Por confirmar" (Caso 4) y no se procesa todavía |
| 3.3 | Lee todos los archivos vigentes (estado Procesando o Procesada) desde el Blob | "def _abrir" | Los archivos en memoria |
| 3.4 | **Normaliza** cada tipo al modelo común | [`cuadralo/normalizar.py`](../cuadralo/normalizar.py): "def normalizar_bc", "def normalizar_operador", "def normalizar_presupuesto", "def normalizar_reservas" | Tablas comunes (lección 3) |
| 3.5 | Avisa de meses repetidos y evita contar dos veces | [`portal/procesar.py`](../portal/procesar.py): "def _repetidos" | Campo `aviso` de la carga |
| 3.6 | Asigna a cada apunte su línea del informe con el plan de cuentas, y valida fincas. Una cuenta nueva ya no llega aquí: la detecta el paso 3.2 y se pregunta en "Revisar y confirmar" | [`cuadralo/calculos.py`](../cuadralo/calculos.py): "def asignar_lineas" | Si una cuenta no tiene línea: error claro |
| 3.7 | **Carga en Azure SQL**: borra lo anterior de la empresa e inserta todo por lotes de 1.000 | [`portal/procesar.py`](../portal/procesar.py): busca "bulk_create" y "transaction.atomic" | SQL: `portal_movimientocontable`, `portal_filaoperador`, `portal_filapresupuesto`, `portal_reserva` |
| 3.8 | **Precálculo**: calcula todo el informe y lo guarda | [`portal/precalculo.py`](../portal/precalculo.py): "def guardar". Los cálculos los hace la clase `Datos` de [`cuadralo/informe.py`](../cuadralo/informe.py) | SQL: `portal_resultadoempresa` (tablas del informe) y `portal_resultadodesviacion` |
| 3.9 | Marca las cargas como "Procesada" **al final**, con el informe ya guardado | [`portal/procesar.py`](../portal/procesar.py): busca "Las cargas pasan a «Procesada» al final" | `portal_carga.estado = ok` |
| 3.10 | Si algo falla: la carga queda en "Error" con el motivo, y se avisa a n8n | [`portal/segundo_plano.py`](../portal/segundo_plano.py): "except Exception" y "def avisar" | `portal_carga.mensaje` |

**Importante para entender el rendimiento:** en los pasos 3.3 a 3.8 hoy se **vuelve a leer, normalizar y cargar todo el histórico de la empresa** en cada subida (las reservas ya son incrementales). Con el Grupo Demo tarda segundos, pero con un hotel muy grande habrá que procesar solo los meses afectados (pendiente).

**Para verlo en Azure mientras pasa:** App Service → *Supervisión* → **Secuencia de registro (Log stream)**. Ahí salen los mensajes de la web en directo, también los errores.

---

## 5. Caso 4 · Revisar y confirmar lo desconocido

| Paso | Qué pasa | GitHub | Azure |
|---|---|---|---|
| 4.1 | La revisión crea una pregunta por cada cosa desconocida (columna, hotel, finca, cuenta, canal, hoja, año) | [`cuadralo/revision.py`](../cuadralo/revision.py): "def _operador", "def _business_central", "def _presupuesto", "def _reservas" | — |
| 4.2 | Propone una respuesta por parecido de nombres | [`cuadralo/sugerencias.py`](../cuadralo/sugerencias.py): "def por_parecido" | — |
| 4.3 | Si Azure OpenAI está configurado, la IA propone (solo textos, nunca cifras) y solo vale una opción válida | [`cuadralo/ia.py`](../cuadralo/ia.py): "def proponer" y "def _minimo" | Recurso Azure OpenAI |
| 4.4 | Se guardan las preguntas y el archivo queda "Por confirmar" | [`portal/procesar.py`](../portal/procesar.py): "def revisar_cargas_nuevas" | SQL: `portal_propuesta`, `portal_registroia` |
| 4.5 | El usuario ve "Revisar y confirmar" en el menú y abre la página | [`portal/templates/portal/revisar.html`](../portal/templates/portal/revisar.html) · menú en [`base.html`](../portal/templates/portal/base.html): busca "revisar" | — |
| 4.6 | Confirma: se guarda lo elegido con quién y cuándo, y se relanza el procesado | [`portal/views.py`](../portal/views.py): "def revisar" | SQL: `portal_mapeoaprobado` · `/equipo/` → Mapeos confirmados |
| 4.7 | La próxima vez ya no pregunta: lo confirmado se suma a la configuración | [`cuadralo/revision.py`](../cuadralo/revision.py): "def aplicar_mapeos" | — |

---

## 6. Caso 5 · Abrir el informe

| Paso | Qué pasa | GitHub |
|---|---|---|
| 5.1 | El usuario abre `/` (la página de inicio) | [`web/urls.py`](../web/urls.py): `''` → `inicio` · [`portal/views.py`](../portal/views.py): "def inicio" |
| 5.2 | Se lee lo que ha elegido (meses, hotel, ceco, proveedor, canal) y se valida contra lo que puede ver | [`portal/views.py`](../portal/views.py): "class Seleccion" |
| 5.3 | Se cargan los **datos ya calculados** (no se recalcula nada). Se guardan en memoria mientras no cambien las cargas | [`portal/views.py`](../portal/views.py): "def obtener_datos" → [`portal/precalculo.py`](../portal/precalculo.py) "def cargar" |
| 5.4 | Se arma el contenido: tarjetas, gráficos con su texto y ayuda, tablas y alertas | [`cuadralo/informe.py`](../cuadralo/informe.py): "def construir" |
| 5.5 | Cada perfil ve unas páginas (el director de hotel, 4 de su hotel) | [`portal/views.py`](../portal/views.py): "def paginas_de" |
| 5.6 | El HTML dibuja lo que llega de Python | [`portal/templates/portal/inicio.html`](../portal/templates/portal/inicio.html) y las piezas [`_tarjeta.html`](../portal/templates/portal/_tarjeta.html), [`_detalle.html`](../portal/templates/portal/_detalle.html) |
| 5.7 | Chart.js pinta los gráficos en el navegador **sin calcular cifras** | [`portal/static/portal/informe.js`](../portal/static/portal/informe.js) y [`vendor/`](../portal/static/portal/vendor/) |
| 5.8 | Formato de números en español (1.234,56 €) | [`portal/templatetags/cifras.py`](../portal/templatetags/cifras.py) |

**Por qué abre en menos de 1 segundo:** todo lo pesado se hizo en el paso 3.8. Abrir una página solo lee resultados de `portal_resultadoempresa`.

---

## 7. Caso 6 · Clic hasta la factura, apuntes y exportar

| Paso | Qué pasa | GitHub |
|---|---|---|
| 6.1 | Clic en una barra o una fila: el navegador pide `/detalle/` con lo que se ha pinchado | [`informe.js`](../portal/static/portal/informe.js): busca "detalle" |
| 6.2 | La vista busca en SQL las facturas o reservas de esa cifra con **todos los filtros de la página**: empresa, hoteles que puede ver, meses elegidos, ceco, proveedor, canal y la línea o barra pinchada. Enseña las 300 de mayor importe; el resto, en Excel | [`portal/views.py`](../portal/views.py): "def detalle" y "MAX_FILAS_DETALLE" |
| 6.3 | La tabla de abajo enseña esas filas | [`_detalle.html`](../portal/templates/portal/_detalle.html) |
| 6.4 | Página "Apuntes y proveedores": filtra y pagina en la base de datos | [`portal/views.py`](../portal/views.py): "def apuntes" · [`apuntes.html`](../portal/templates/portal/apuntes.html) |
| 6.5 | Exportar a Excel | [`portal/views.py`](../portal/views.py): "def exportar" y "def _excel" |

Las reglas que explican cada desviación (factura duplicada de Makro, otro mes, proveedor nuevo…) están en [`cuadralo/reglas.py`](../cuadralo/reglas.py): "def _causas_gasto". Las veremos en la lección 5.

---

## 8. Caso 7 · Duplicados, eliminar una carga y errores

| Situación | Qué pasa | GitHub |
|---|---|---|
| Archivo idéntico con otro nombre | No se carga y avisa | [`portal/views.py`](../portal/views.py) "def subir" + [`procesar.py`](../portal/procesar.py) "def carga_identica" |
| Mismo nombre y tipo | El anterior pasa a "Sustituida" | [`procesar.py`](../portal/procesar.py) "def registrar_carga" |
| Mismo mes y hotel en dos archivos | Aviso y nada se cuenta dos veces (BC por Nº mov., resto el más reciente) | [`procesar.py`](../portal/procesar.py) "def _repetidos" · [`normalizar.py`](../cuadralo/normalizar.py) busca "drop_duplicates" |
| Eliminar | Solo contabilidad. Queda el registro, se borra del Blob y se reprocesa | [`views.py`](../portal/views.py) "def eliminar_carga" + [`procesar.py`](../portal/procesar.py) "def eliminar_carga" |
| Error | Mensaje claro en la carga y aviso a n8n (`AVISOS_WEBHOOK_URL`) | [`segundo_plano.py`](../portal/segundo_plano.py) "def avisar" |

---

## 9. Caso 8 · Publicar un cambio

| Paso | Qué pasa | Dónde verlo |
|---|---|---|
| 8.1 | Claude Code (o tú) sube un cambio a la rama `main` de GitHub | GitHub → pestaña **Commits** |
| 8.2 | GitHub Actions instala Python y ejecuta **todas las pruebas** (~10 min) | [`.github/workflows/desplegar.yml`](../.github/workflows/desplegar.yml) · GitHub → pestaña **Actions** |
| 8.3 | Si alguna prueba falla, **no se publica nada** | Actions: cruz roja |
| 8.4 | Si pasan, se publica en el App Service | Actions: tick verde · Azure: App Service → *Centro de implementación* → Registros |
| 8.5 | Azure arranca la web: migra la base de datos, prepara estilos y lanza la web con 1 proceso y 4 hilos | [`startup.sh`](../startup.sh) |
| 8.6 | Si faltan datos del Grupo Demo, se cargan en segundo plano | [`portal/management/commands/crear_grupo_demo.py`](../portal/management/commands/crear_grupo_demo.py) |

**Las pruebas que protegen lo más importante:**
- [`tests/test_paso6_aislamiento.py`](../tests/test_paso6_aislamiento.py): nadie ve datos de otra empresa.
- [`tests/test_paso3_informe.py`](../tests/test_paso3_informe.py): las cifras de octubre y los 11 casos sembrados.
- [`tests/test_paso7_cargas.py`](../tests/test_paso7_cargas.py): duplicados, eliminar y errores.
- [`tests/test_paso8_revision.py`](../tests/test_paso8_revision.py): Revisar y confirmar, e IA.

---

## 10. Azure: qué mirar en cada recurso

| Quiero ver… | Dónde en Azure |
|---|---|
| Si la web está encendida y su dirección | App Service → *Información general* (Estado, Dominio predeterminado) |
| Los errores en directo | App Service → *Supervisión* → **Secuencia de registro** |
| Las variables (conexiones, claves) | App Service → *Configuración* → **Variables de entorno** |
| Qué versión de GitHub está publicada | App Service → *Centro de implementación* → Registros |
| Los Excels originales subidos | Cuenta de almacenamiento → *Contenedores* → `cargas` |
| Las tablas y sus datos | Azure SQL → base `cuadralo` → **Editor de consultas**. Prueba: `SELECT TOP 20 * FROM portal_carga ORDER BY creada DESC` |
| Las claves guardadas | Key Vault → *Secretos* |
| El gasto | Suscripción → *Administración de costos* |

Consultas útiles en el Editor de consultas (solo lectura, no cambian nada):

```sql
-- Últimas cargas con su estado y mensaje
SELECT TOP 20 id, nombre_original, tipo, estado, mensaje, aviso, creada FROM portal_carga ORDER BY creada DESC;

-- Cuántos apuntes hay por empresa y finca
SELECT empresa_id, finca, COUNT(*) AS apuntes FROM portal_movimientocontable GROUP BY empresa_id, finca;

-- Quién ha visto qué hoy
SELECT TOP 50 fecha, usuario_id, accion, detalle FROM portal_registroactividad ORDER BY fecha DESC;

-- Lo confirmado en Revisar y confirmar
SELECT tipo, clase, origen, destino, fuente, confianza, aprobado_en FROM portal_mapeoaprobado;
```

---

### 10.1 Qué guarda cada tabla

| Tabla | Qué es | Cuándo se llena |
|---|---|---|
| `portal_empresa`, `portal_perfil`, `auth_user` | Empresas, usuarios y su rol | Alta de clientes |
| `portal_carga` | Cada archivo subido y su estado | Al subir |
| `portal_movimientocontable` | Apuntes de Business Central normalizados | Al procesar |
| `portal_filaoperador` | El informe del operador ya en filas (hotel, mes, concepto, medida, valor) | Al procesar |
| `portal_filapresupuesto` | El presupuesto en filas (hotel, mes, línea, importe) | Al procesar |
| `portal_reserva` | Reservas de Mews, una fila por reserva | Al procesar reservas |
| `portal_resultadoempresa` | **El informe ya calculado**: una fila por tabla del informe (cuenta de resultados, KPIs, cuadre…). Se guarda comprimido en formato de Python, por eso se ve "raro" en SQL: no está pensado para leerlo a mano, sino para que la web lo abra en menos de un segundo | Al final de cada procesado |
| `portal_resultadodesviacion` | Desviaciones ya explicadas por hotel y mes (mismo formato comprimido) | Al procesar (últimos 3 meses) y la primera vez que se pide otro mes |
| `portal_propuesta`, `portal_mapeoaprobado` | Preguntas de "Revisar y confirmar" y lo confirmado | Solo cuando llega algo desconocido |
| `portal_registroia` | Llamadas a la IA | Solo con Azure OpenAI conectado |
| `portal_interesmodulo` | Clics en "Me interesa" de los módulos futuros (reputación, personas, operaciones) | Cuando un usuario los pulsa |
| `portal_registroacceso`, `portal_registroactividad` | Quién entra y qué ve o exporta | Siempre |

Todas las tablas de datos de clientes llevan la columna `empresa_id`.

## 11. Glosario y equivalencias

| Palabra | Qué significa aquí | Equivalente |
|---|---|---|
| Django | El "marco" de la web en Python: usuarios, páginas, base de datos | — |
| Vista (`views.py`) | La función que responde a una página | La lógica de una página |
| Plantilla (`templates`) | El HTML de una página, con huecos que rellena Python | El diseño de un informe |
| Modelo (`models.py`) | Una tabla de la base de datos | Una tabla SQL |
| Migración (`migrations/`) | El cambio de estructura de las tablas, que se aplica solo al arrancar | Un script `ALTER TABLE` |
| Blob | Almacén de archivos de Azure | La sección Files del lakehouse |
| Precálculo | Resultados del informe guardados ya calculados | El modelo semántico importado |
| Huella | Firma del contenido de un archivo: dos archivos iguales tienen la misma | Un checksum |
| Carga | Cada archivo subido, con su estado | Una ejecución de ingesta |
| Propuesta / Mapeo | Pregunta sobre algo desconocido / respuesta confirmada | Tabla de mapeo |
| GitHub Actions | Lo que GitHub ejecuta solo con cada cambio | Pipeline de despliegue |

---

## 12. Mis dudas

Escribe aquí tus dudas con el número de paso. Ejemplo: "3.7 · ¿Por qué se borra todo antes de insertar?"

- 
