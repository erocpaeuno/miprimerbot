# Sistema de gestión para taller de motocicletas

Aplicación Django para administrar un taller de motocicletas en Lima. La base
técnica y el acceso del personal están preparados; los módulos del negocio se
desarrollarán por fases y se validarán antes de iniciar la siguiente.

## Decisiones confirmadas

- Tipo de taller: motocicletas.
- Operación: un solo taller.
- Ubicación y zona horaria: Lima, Perú (`America/Lima`).
- Moneda: sol peruano (`PEN`, símbolo `S/`).
- Impuesto indicado: IGV del 18 %, configurable como `IGV_RATE=0.18`.
- Mensajería prevista: Telegram.
- Inventario: requerido; catálogo y existencias se implementaron antes de las
  órdenes para integrar el consumo de repuestos.
- Aprobación de presupuesto: respuesta del cliente por Telegram o registro
  manual por el personal.
- Vinculación de Telegram: código aleatorio de un solo uso emitido por recepción
  o administración después de verificar presencialmente al cliente. El DNI no
  se solicita ni se acepta como autenticación en el bot.
- Notificaciones: avisos de presupuesto/trabajo y ofertas solo con
  consentimiento explícito; el bot permite activar, retirar y revocar cada
  consentimiento.
- Caja: una caja para el taller.

## Alcance de los procesos completados

**Proceso 1 — Base técnica: terminado.**

- Proyecto Django modular mínimo.
- Configuración de PostgreSQL por variables de entorno y SQLite para desarrollo
  local.
- Idioma, zona horaria, moneda e IGV inicializados para el contexto indicado.
- Endpoint `/` para comprobar que la aplicación responde.
- Prueba automatizada del endpoint.
- Sin secretos ni servicios externos configurados en el repositorio.

**Proceso 2 — Usuarios, roles y permisos internos: terminado.**

- Usuario interno propio de Django con roles administrador, recepción, técnico
  y caja.
- Inicio y cierre de sesión; el perfil exige autenticación.
- Permisos por rol aplicados mediante el sistema de autorización del servidor.
- La consola administrativa de Django sigue reservada a superusuarios.
- No se crean cuentas para clientes en esta fase.

**Proceso 3 — Clientes y motocicletas: terminado.**

- Registro, búsqueda, consulta y edición de clientes y motocicletas.
- DNI opcional, validado como 8 dígitos y único cuando se registra; solo se
  muestra en las vistas disponibles para administrador y recepción.
- Placa/código normalizado para evitar duplicados con diferencias de formato.
- Kilometraje no negativo, año opcional y relación obligatoria con el cliente.
- Eliminación no ofrecida para conservar la integridad del historial futuro.

**Proceso 4 — Catálogo e inventario: terminado.**

- Catálogo de servicios con precio referencial, duración y opción de desactivar.
- Repuestos con código, unidad, precio, existencias y nivel de reposición.
- Ingresos, salidas y ajustes de conteo; el stock no puede quedar negativo.
- Cada movimiento conserva cantidad, motivo, usuario, fecha y costo unitario
  opcional. Los movimientos se muestran como historial inmutable.
- Recepción y técnicos pueden consultar repuestos; todos los roles internos
  pueden consultar el catálogo de servicios. Solo administración puede
  modificar catálogo, repuestos y movimientos.
- El stock inicial es cero y debe ingresarse mediante un movimiento; editar la
  ficha de un repuesto no modifica existencias.

**Proceso 5 — Órdenes de trabajo: terminado.**

- Órdenes numeradas con cliente, motocicleta, kilometraje, motivo, diagnóstico,
  notas, técnico asignado e historial inmutable de eventos.
- Transiciones controladas: borrador → recibida → diagnóstico → aprobación →
  trabajo → lista → entregada; saltos y cambios directos de estado se rechazan.
- Para solicitar aprobación se exige diagnóstico y al menos una línea de
  presupuesto; las líneas quedan bloqueadas mientras el cliente decide.
- Registro de servicios y repuestos con copia histórica de descripción y precio;
  el total se calcula en el servidor.
- La aprobación pendiente debe registrarse explícitamente con medio y evidencia.
  Cuando el bot está configurado y el cliente consintió avisos, se ofrece
  aprobación directa en el chat privado vinculado; también está disponible el
  registro manual.
- Las existencias no se descuentan al presupuestar: se descuentan al iniciar
  una orden aprobada. El movimiento de inventario se asocia a la orden y se
  confirma en la misma transacción; si no hay suficiente stock, el trabajo no
  inicia.
- Administrador y recepción gestionan órdenes; el técnico solo ve las suyas y
  puede actualizar diagnóstico y trabajo asignado. Caja puede consultar órdenes
  sin ver precios.
- Una orden entregada conserva los importes originales y actualiza el
  kilometraje de la motocicleta.

**Proceso 6 — Mantenimiento: terminado.**

- Cada orden entregada crea un registro histórico inmutable asociado a la
  motocicleta; volver a registrar la misma entrega no duplica el historial.
- Se pueden registrar planes de mantenimiento con vencimiento por fecha,
  kilometraje o ambos. Los planes completados o cancelados no generan alertas.
- Los recordatorios se programan y registran manualmente, con canal, fecha,
  estado y constancia de envío. La aplicación no envía mensajes ni se conecta
  a Telegram en esta fase.
- Solo administración y recepción acceden a este módulo; la lógica de negocio
  también valida permisos al programar y actualizar recordatorios.

**Proceso 7 — Caja y reportes: terminado.**

- Hay una sola caja abierta a la vez. La apertura registra el fondo inicial y
  queda asociada al usuario que la abrió; solo este usuario o administración
  puede operarla.
- Los pagos parciales se registran contra órdenes listas o entregadas, sin
  permitir que el acumulado supere el total referencial de la orden. Se anotan
  medio de pago y referencia; los registros son inmutables.
- Se registran egresos por categoría y medio de pago. Los egresos en efectivo
  no pueden superar el efectivo disponible.
- El cierre conserva efectivo esperado y contado y muestra cualquier diferencia.
  Los cálculos de efectivo consideran fondo inicial, pagos en efectivo y
  egresos en efectivo.
- Reportes por rango de fechas resumen pagos y egresos por medio de pago,
  movimientos y diferencias de cierres.
- El total de la orden sigue siendo referencial: esta fase no emite comprobantes
  ni calcula IGV.

**Proceso 8 — Telegram: implementación lista; activación externa pendiente.**

- Recepción o administración puede emitir un código aleatorio, de un solo uso,
  con vigencia de 15 minutos. El personal debe verificar presencialmente al
  cliente; el DNI no se solicita ni se usa para autenticar en el bot.
- El bot solo acepta vínculo y comandos en chats privados. La vinculación no
  activa mensajes: el cliente debe enviar `/avisos on` y/o `/ofertas on`.
  `/avisos off`, `/ofertas off`, `/baja` y `/desvincular` revocan permisos y
  detienen mensajes pendientes de esas categorías.
- Al solicitar aprobación, el bot encola el presupuesto con botones de aprobar
  o rechazar. Se comprueba que la cuenta vinculada corresponda al cliente y que
  la orden siga esperando aprobación. Rechazar cancela la orden.
- Al pasar una orden a lista, se encola un aviso de trabajo terminado. Las
  campañas de ofertas de administración solo se encolan para clientes con
  consentimiento vigente.
- El webhook verifica el secreto de Telegram y deduplica actualizaciones por
  `update_id`. Los mensajes salientes se guardan en una cola transaccional y se
  despachan con `send_telegram_outbox`; los errores quedan registrados y se
  pueden reintentar hasta cinco veces. Los envíos son de mejor esfuerzo y, si
  la conexión se interrumpe tras la aceptación de Telegram, no se puede
  garantizar entrega exactamente una vez.
- No se ha configurado un token ni registrado un webhook real. Para activar el
  bot se requiere HTTPS público y programar el despachador de la cola.

La activación operativa del bot requiere credenciales privadas, un endpoint
HTTPS público y configurar el proceso que despacha la cola saliente; esta
información no se incluye en el repositorio.

**Proceso 10 — Portal del cliente: implementado; validación en producción
pendiente.**

- Recepción o administración puede emitir un código aleatorio de un solo uso,
  válido por 15 minutos. El personal debe verificar presencialmente la
  identidad y entregar el código directamente al cliente.
- El código se almacena como hash, se invalida al emitir uno nuevo y solo se
  acepta una vez. No se usa el DNI como contraseña ni como autenticación.
- El portal está en `/portal-cliente/`. La sesión dura 12 horas; sus páginas y
  la página que muestra el código usan cabeceras para evitar caché.
- El cliente solo ve sus propias órdenes, motocicletas, diagnóstico y líneas de
  presupuesto; las notas internas del taller y el DNI no se exponen.
- Si una orden espera aprobación, el cliente puede aprobar o rechazar el
  presupuesto. La respuesta se registra en el historial; rechazar cancela la
  orden. Los importes siguen siendo referenciales y no son comprobantes.
- El despliegue público y la prueba operativa de entrega del código quedan
  pendientes hasta contar con infraestructura HTTPS.

**Proceso 9 — Interfaz, seguridad y preparación de despliegue: terminado en
código y documentación; despliegue real pendiente.**

- Se añadió una hoja de estilos compartida y responsive a las 25 páginas
  existentes, con controles de foco visibles y tablas desplazables en móvil.
- Se configuró `STATIC_ROOT` y WhiteNoise para recopilar y servir archivos
  estáticos desde la aplicación.
- La configuración de producción exige clave secreta, dominios permitidos,
  PostgreSQL, HTTPS (directo o mediante proxy explícitamente confiable) y HSTS.
- Se documentaron la preparación de estáticos, comprobaciones de despliegue,
  respaldos y restauración en una base separada. No se ha ejecutado un
  despliegue real ni una restauración de producción.

### Matriz inicial de permisos

| Capacidad | Administrador | Recepción | Técnico | Caja |
|---|---:|---:|---:|---:|
| Administrar personal | Sí | No | No | No |
| Gestionar clientes y motocicletas | Sí | Sí | No | No |
| Consultar catálogo de servicios | Sí | Sí | Sí | Sí |
| Gestionar catálogo de servicios | Sí | No | No | No |
| Gestionar órdenes | Sí | Sí | No | No |
| Ver y actualizar órdenes asignadas | Sí | No | Sí | No |
| Consultar todas las órdenes | Sí | Sí | No | Sí |
| Registrar aprobación recibida | Sí | Sí | No | No |
| Consultar inventario | Sí | Sí | Sí | No |
| Gestionar inventario | Sí | No | No | No |
| Gestionar mantenimiento y recordatorios | Sí | Sí | No | No |
| Registrar pagos, gastos y caja | Sí | No | No | Sí |
| Consultar reportes financieros | Sí | No | No | Sí |
| Gestionar mensajería | Sí | No | No | No |

La matriz documenta los permisos implementados y los previstos para los módulos
pendientes.

## Plan de desarrollo

1. **Base técnica — terminado:** estructura, configuración, salud y prueba.
2. **Usuarios y permisos — terminado:** autenticación, roles internos y matriz
   de capacidades.
3. **Clientes y motocicletas — terminado:** datos del cliente, DNI con acceso
   restringido, vehículos y reglas de unicidad.
4. **Catálogo e inventario — terminado:** servicios, repuestos, unidades,
   existencias y movimientos auditables.
5. **Órdenes de trabajo — terminado:** estados, asignaciones, diagnóstico,
   líneas de servicio/repuesto, precios históricos y aprobación registrada.
6. **Mantenimiento — terminado:** historial por motocicleta, vencimientos y
   registro manual de recordatorios.
7. **Caja y reportes — terminado:** pagos, gastos, cierres y conciliación en
   PEN.
8. **Telegram — código listo; activación externa pendiente:** vínculo seguro,
   aprobación de presupuestos, notificaciones consentidas, webhooks y
   deduplicación de actualizaciones entrantes.
9. **Interfaz y preparación del despliegue — código terminado; operación
   pendiente:** interfaz responsive, configuración de seguridad, respaldos y
   procedimiento de restauración. Aún se requiere desplegar en un servidor
   HTTPS real y validar una restauración en un entorno separado.
10. **Portal del cliente — implementado; verificación de operación pendiente:**
    acceso temporal verificado por personal, consulta privada de órdenes y
    respuesta a presupuestos.
11. **Puesta en producción — configuración Render preparada; activación
    pendiente:** conectar un repositorio Git, elegir un plan, cargar la URL de
    PostgreSQL en el panel seguro y validar el hostname HTTPS. Después, probar
    los flujos y practicar respaldo y restauración en un entorno separado.

Cada fase debe incluir migraciones y pruebas para el comportamiento añadido.
No se comienza la siguiente fase hasta revisar la anterior.

## Requisitos

- Python 3.12 o posterior compatible con Django 5.2.
- PostgreSQL para entornos compartidos o de producción.
- SQLite se utiliza por defecto en desarrollo local.

## Ejecución local

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Abrir `http://127.0.0.1:8000/`; debe responder un estado JSON `ok`.
El acceso interno está en `http://127.0.0.1:8000/cuentas/entrar/`.
El comando `createsuperuser` del bloque anterior crea el administrador inicial,
que puede acceder a `/admin/` y gestionar cuentas del personal. El cierre de
sesión se realiza mediante un formulario POST.

Con una sesión de administrador o recepción:

- Clientes: `/clientes/`
- Motocicletas: `/clientes/motocicletas/`
- Servicios: `/catalogo/servicios/`
- Repuestos: `/inventario/repuestos/`
- Órdenes de trabajo: `/ordenes/`
- Mantenimiento: `/mantenimiento/`
- Caja y reportes: `/caja/` (administración y caja)
- Campañas de ofertas Telegram: `/telegram/ofertas/` (administración)
- Portal del cliente: `/portal-cliente/` (código temporal entregado por el
  personal)

La recepción también puede consultar el catálogo de servicios e inventario. Los
técnicos pueden consultar servicios e inventario, y caja puede consultar
servicios. Solo administración puede crear o modificar servicios, repuestos y
movimientos. Las páginas requieren iniciar sesión y los roles sin permiso
reciben una respuesta `403`.

La recepción crea y administra órdenes y registra confirmaciones recibidas.
Los técnicos consultan únicamente las órdenes asignadas y actualizan diagnóstico
y estado permitido. Si Telegram no está configurado o el cliente no otorgó
consentimiento, se conserva la aprobación manual. Al iniciar trabajo, cada
repuesto presupuestado se descuenta del stock mediante un movimiento asociado
a la orden.

Para dar acceso al portal, abre la ficha del cliente, genera el código temporal
después de verificar presencialmente su identidad y entrégalo directamente.
El cliente lo ingresa en `/portal-cliente/ingresar/`. Cada código vence en 15
minutos, se usa una sola vez y emitir otro invalida el anterior. No envíes el
código en un canal público ni uses el DNI como clave. La sesión del portal
vence en 12 horas.

## Configuración de PostgreSQL

Definir estas variables de entorno antes de iniciar Django. Para producción,
reemplazar los dominios de ejemplo por los nombres reales y usar credenciales
privadas administradas por el entorno de despliegue:

```text
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<clave aleatoria privada>
DJANGO_ALLOWED_HOSTS=taller.example.pe
DJANGO_CSRF_TRUSTED_ORIGINS=https://taller.example.pe
DB_ENGINE=postgresql
DB_NAME=taller_motos
DB_USER=<usuario de base de datos>
DB_PASSWORD=<contraseña>
DB_HOST=<servidor PostgreSQL>
DB_PORT=5432
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SECURE_HSTS_SECONDS=31536000
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=False
DJANGO_SECURE_HSTS_PRELOAD=False
```

La aplicación rechaza el inicio de producción si falta la clave, la lista de
dominios o HSTS, o si se selecciona SQLite. También acepta `DATABASE_URL` como
URL PostgreSQL, que tiene prioridad sobre `DB_NAME`, `DB_USER`, `DB_PASSWORD`,
`DB_HOST` y `DB_PORT`. `DJANGO_CSRF_TRUSTED_ORIGINS`
debe contener orígenes completos con `https://` cuando se envían formularios
desde otros orígenes. Para TLS terminado en un proxy, configura
`DJANGO_USE_X_FORWARDED_PROTO=True` únicamente si el proxy de confianza elimina
y sobrescribe `X-Forwarded-Proto`; no confíes en ese encabezado enviado
directamente por clientes. Conserva la redirección HTTPS activa.

### Preparar y comprobar el despliegue

1. Provisiona PostgreSQL y un servidor WSGI, configura las variables anteriores
   en el entorno del servicio y limita el usuario de base de datos a la base
   propia de la aplicación.
2. Con el código desplegado y las mismas variables de entorno del servicio,
   ejecuta:

   ```powershell
   python manage.py check --deploy
   python manage.py migrate
   python manage.py collectstatic --noinput
   ```

3. Configura el proxy para servir la aplicación solo por HTTPS y servir los
   archivos de `STATIC_ROOT` con el prefijo `/static/`. Ejecuta la aplicación
   con un servidor WSGI de producción, no con `runserver`.
4. Crea la cuenta administradora inicial con `python manage.py createsuperuser`
   y prueba inicio de sesión, formularios protegidos por CSRF, redirección
   HTTPS y carga de CSS antes de habilitar el servicio.
5. Si se activa Telegram, configura sus secretos fuera del repositorio y sigue
   la sección **Activar Telegram**. El proceso de salida debe ejecutarse
   periódicamente en el mismo entorno que comparte la base de datos.

No habilites HSTS con subdominios o `preload` hasta confirmar que todos los
subdominios funcionan permanentemente con HTTPS. `check --deploy` debe
ejecutarse con la configuración de producción; hacerlo con el entorno local
puede mostrar advertencias esperadas.

### Despliegue en Render

El archivo [render.yaml](./render.yaml) prepara un servicio web, recopilación
de estáticos, migraciones al iniciar y Gunicorn. WhiteNoise sirve los archivos
estáticos recopilados. No aprovisiona otra base: reutiliza la instancia
PostgreSQL ya creada.

1. Sube el código a un repositorio Git privado y crea un Blueprint en Render
   conectado a ese repositorio. Este directorio de trabajo todavía no está
   conectado a un repositorio Git.
2. Al crear el Blueprint, elige el plan del servicio y configura `DATABASE_URL`
   con la URL interna de PostgreSQL si la base está en Render y en la misma
   región. Cárgala únicamente en el panel seguro de Render, no en `render.yaml`,
   `.env.example`, Git ni mensajes. La configuración detecta la URL sin
   registrar sus credenciales.
3. Render asignará un hostname HTTPS. La aplicación incorpora el hostname
   entregado por Render a `ALLOWED_HOSTS` y a los orígenes CSRF. Si luego
   agregas un dominio propio, define en el panel
   `DJANGO_ALLOWED_HOSTS` con todos los hostnames y
   `DJANGO_CSRF_TRUSTED_ORIGINS` con sus orígenes `https://`.
4. Comprueba el health check `/`, login, formularios, CSS y órdenes. La
   configuración inicia con HSTS de una hora; súbelo solo cuando el hostname
   definitivo y todos los subdominios aplicables estén validados con HTTPS.
5. El comando de inicio ejecuta migraciones antes de Gunicorn. Mantén una sola
   instancia web durante la primera puesta en marcha; si escalas el servicio,
   ejecuta las migraciones una sola vez antes de iniciar instancias nuevas.

El archivo de Blueprint no incorpora credenciales ni configura Telegram. Los
secretos de Telegram se añadirán manualmente en el panel de Render cuando el
bot vaya a activarse. No se ha creado un servicio real ni validado el despliegue
porque todavía falta conectar el repositorio y configurar `DATABASE_URL`.

### Respaldo y restauración de PostgreSQL

- Programa `pg_dump` con frecuencia acorde a la operación (por ejemplo,
  diariamente), conserva varias generaciones cifradas fuera del servidor de
  la aplicación y restringe su acceso. No coloques contraseñas en scripts,
  historial de comandos ni en el repositorio; utiliza el gestor de secretos o
  el archivo de credenciales protegido de PostgreSQL.
- Ejemplo de respaldo en formato comprimido desde PowerShell:

  ```powershell
  New-Item -ItemType Directory -Force .\backups
  $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $backupFile = ".\backups\taller-$timestamp.dump"
  pg_dump --format=custom --host=<servidor> --username=<usuario> `
    --dbname=taller_motos --file="$backupFile"
  ```

- Para verificar un respaldo, crea una base de datos vacía y restaura allí
  (nunca sobre la base operativa):

  ```powershell
  createdb --host=<servidor-de-pruebas> --username=<usuario> taller_motos_restore
  pg_restore --host=<servidor-de-pruebas> --username=<usuario> `
    --dbname=taller_motos_restore --no-owner .\backups\taller.dump
  ```

- Configura temporalmente la aplicación contra la base restaurada y ejecuta
  `python manage.py check` y verificaciones funcionales antes de declarar
  válida la recuperación. Documenta el responsable, fecha y resultado de cada
  simulacro. Estos pasos describen el procedimiento; aún no se ha probado una
  restauración en infraestructura real.

## Activar Telegram

1. Crea el bot con BotFather y configura las variables como secretos del
   entorno del servicio (no las guardes en el repositorio):

   ```text
   TELEGRAM_BOT_TOKEN=<token privado del bot>
   TELEGRAM_BOT_USERNAME=<nombre del bot, sin @>
   TELEGRAM_WEBHOOK_SECRET=<secreto aleatorio de 1 a 256 caracteres A-Z, a-z, 0-9, _ o ->
   ```

2. Despliega la aplicación detrás de HTTPS y registra el endpoint:

   ```powershell
   python manage.py set_telegram_webhook --url https://<dominio>/telegram/webhook/
   ```

3. Programa `python manage.py send_telegram_outbox --retry-failed` para
   ejecutarse periódicamente (por ejemplo, cada minuto) en el mismo entorno
   que accede a la base de datos. El webhook guarda respuestas y mensajes en
   una cola; el comando los envía y registra fallos. Reintenta hasta cinco
   veces; después de eso, inspecciona el fallo y, si corresponde, reencola con
   `python manage.py requeue_telegram_message --message-id <id>`.
4. En la ficha del cliente, personal autorizado genera un código tras verificar
   presencialmente su identidad y se lo entrega al cliente. El cliente abre el
   bot y envía `/start <código>`. Después puede elegir `/avisos on` y
   `/ofertas on`; ninguno se activa por defecto.

El bot opera en chats privados. No se debe compartir el código de vínculo con
terceras personas: permite asociar ese chat al cliente hasta su vencimiento o
primer uso.

`IGV_RATE` puede sobrescribirse si cambia la tasa aplicable. La configuración
actual solo establece el valor; los cálculos de impuestos se implementarán y
probarán junto con precios y órdenes, no en esta base técnica.

## Validación

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test
```
