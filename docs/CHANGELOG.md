# 📝 Registro de Cambios (Changelog) - Módulo de Autenticación
**Proyecto:** Centro Nodo  
**Fecha:** Noviembre 2026  
**Objetivo:** Implementación completa del sistema de autenticación, control de roles (RBAC) y flujo de recuperación de contraseñas.

---

## 🛠️ Resumen de Modificaciones

### 1. Configuración del Proyecto (`core/settings.py`)
- **Problema previo:** `AUTH_USER_MODEL` no estaba definido, lo que hacía que Django ignorara el modelo de usuario personalizado de la clínica y fallara la vinculación de roles.
- **Cambios realizados:**
  - Se configuró `AUTH_USER_MODEL = 'clinica.Usuario'`.
  - Se agregaron los backends de autenticación: `clinica.backends.EmailOrUsernameModelBackend` y el modelo nativo de Django.
  - Se definieron `LOGIN_URL = 'login'`, `LOGIN_REDIRECT_URL = 'dashboard'` y `LOGOUT_REDIRECT_URL = 'login'`.
  - Se configuró `EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'` para emitir tokens de recuperación de contraseña directamente en consola durante el desarrollo.
  - Se ajustó `LANGUAGE_CODE = 'es-cl'` para mensajes de validación en español.
  - Se añadieron los hosts permitidos para pruebas locales y desarrollo.

### 2. Modelo de Usuario (`clinica/models.py`)
- Se agregaron métodos y propiedades auxiliares a la clase `Usuario`:
  - `rol_nombre`: Devuelve el nombre legible del rol.
  - `es_administrador`: Identifica si es superusuario o rol de administración.
  - `es_profesional`: Identifica especialistas de la salud mental.
  - `es_paciente`: Identifica a pacientes.
  - Sincronización automática entre el campo `activo` y el campo de Django `is_active` en el método `save()`.

### 3. Backend de Autenticación (`clinica/backends.py`) *(Nuevo)*
- Archivo creado con la clase `EmailOrUsernameModelBackend`.
- Permite autenticar usuarios indistintamente mediante su `username` o su `email`, simplificando la usabilidad para doctores y pacientes.

### 4. Formularios de Acceso y Claves (`clinica/forms.py`) *(Nuevo)*
- `LoginForm`: Campo unificado `login_id` con autocompletado y validación, campo `password` con widget seguro y casilla `remember_me`.
- `CustomPasswordResetForm` y `CustomSetPasswordForm`: Integración visual con las clases CSS del proyecto.

### 5. Control de Acceso por Roles (`clinica/decorators.py`) *(Nuevo)*
- Decorador `@rol_requerido(roles_permitidos)`:
  - Valida autenticación.
  - Verifica pertenencia de rol frente a listas permitidas.
  - Muestra alertas y redirige al dashboard si el rol no tiene permisos.

### 6. Vistas y Enrutamiento (`clinica/views.py` y `core/urls.py`)
- Se implementaron las vistas:
  - `login_view`: Autenticación segura, expiración configurable de sesión y redirección protegida ante ataques open-redirect.
  - `logout_view`: Cierre de sesión y emisión de mensaje flash.
- Se protegieron las vistas existentes (`dashboard_view`, `agendamiento_view`, `telemedicina_view`) con `@login_required` y roles específicos.
- Se configuraron las rutas URL para el ciclo completo de autenticación y restablecimiento de contraseña (`/login/`, `/logout/`, `/password-reset/`, etc.).

### 7. Plantillas HTML (`templates/`)
- `templates/login.html` *(Nuevo)*: Tarjeta de inicio de sesión con soporte de tema claro/oscuro, campos responsivos y enlaces de ayuda.
- `templates/password_reset.html` *(Nuevo)*: Formulario de solicitud de reseteo.
- `templates/password_reset_done.html` *(Nuevo)*: Pantalla de confirmación de correo enviado.
- `templates/password_reset_confirm.html` *(Nuevo)*: Formulario de ingreso de nueva contraseña validada.
- `templates/password_reset_complete.html` *(Nuevo)*: Confirmación de cambio exitoso de clave.
- `templates/password_reset_email.html` y `password_reset_subject.txt` *(Nuevos)*: Plantillas del correo emitido al usuario con el enlace seguro.
- `templates/base.html` *(Modificado)*:
  - Se agregó el renderizador dinámico de mensajes flash de Django (`alert-error`, `alert-success`, etc.).
  - Se incluyó en la barra superior el distintivo con avatar, nombre del usuario conectado, su rol (`role-tag`) y botón de cierre de sesión.
  - Si el usuario es anónimo, muestra el botón *"Iniciar Sesión"*.
- `templates/dashboard.html` *(Modificado)*: Saludo personalizado al usuario autenticado mostrando su nombre y rol.

### 8. Estilos CSS (`static/css/style.css`)
- Se agregaron estilos para:
  - `.auth-wrapper`, `.auth-card`, `.auth-header`: Tarjetas centradas de autenticación con barra de acento degradada.
  - `.form-control`, `.field-error`, `.field-help`: Entradas de texto estilizadas con foco en color primario y mensajes de error.
  - `.messages-container`, `.alert-*`: Alertas de feedback visual animadas (éxito, error, advertencia, info).
  - `.user-badge`, `.role-tag`, `.btn-logout`, `.btn-login-nav`: Componentes de sesión en el menú de navegación superior.

### 9. Comando de Semillero Inicial (`clinica/management/commands/crear_roles_y_usuarios.py`) *(Nuevo)*
- Permite poblar la base de datos con:
  - Roles iniciales: `Administrador`, `Profesional`, `Paciente`, `Recepcionista`.
  - Superusuario `admin` (`admin1234`).
  - Profesional médico `doctor.silva` (`medico1234`) asociado a su ficha en la tabla `profesional`.
  - Paciente `paciente.prueba` (`paciente1234`) asociado a su ficha en la tabla `paciente` y su `FichaClinica`.

### 10. Refactorización del Modelo Entidad-Relación (`clinica/models.py`)
- **Corrección de Relación Usuario - Perfiles:**
  - `Paciente.usuario`: Ajustado a `OneToOneField(Usuario)` (1 a 1, con opción `null=True` para pacientes registrados sin cuenta web inicial).
  - `Profesional.usuario`: Ajustado a `OneToOneField(Usuario)` (1 a 1 estricto).
- **Separación de Expediente y Consulta Médica:**
  - `FichaClinica`: Rediseñada como expediente permanente del paciente (1 a 1 con `Paciente`), eliminando la clave foránea `cita_id`.
  - `AtencionClinica` *(Nueva Entidad Intermedia)*: Vincula la `FichaClinica` con la `Cita` y el `Profesional` tratante, almacenando el motivo, diagnóstico, notas confidenciales de evolución e indicaciones terapéuticas.
- **Incorporación de `BloqueoHorario`:**
  - Soporte para que los especialistas marquen tramos de indisponibilidad horaria.
- **Integración con Django Admin (`clinica/admin.py`):**
  - Registro de todas las entidades clínicas y de agendamiento con filtros, búsquedas y edición en línea de atenciones clínicas.

### 11. Documentación para Desarrolladores (`docs/`)
- `docs/DIAGRAMA_ER_CORREGIDO.md`: Análisis técnico detallado de los errores corregidos y nuevo diagrama en notación Mermaid.
- `docs/COMO_SUBIR_CAMBIOS_A_GITHUB.md`: Manual paso a paso para que cualquier integrante del equipo pueda confirmar y subir cambios usando la terminal o la interfaz visual de VS Code.

### 12. Módulos Funcionales: Pacientes, Fichas Clínicas, Atenciones y Agendamiento Real
- **Validación de RUT Chileno (`clinica/utils.py`):**
  - Algoritmo Módulo 11 (`validar_rut`, `formatear_rut`, `limpiar_rut`) integrado en formularios de pacientes.
- **Módulo de Pacientes (`clinica/views.py`, `templates/pacientes/`):**
  - Directorio con búsqueda por RUT (con o sin puntos) y nombres.
  - Alta y edición de pacientes, creación automática de `FichaClinica` única y creación opcional de cuenta web con rol `Paciente`.
  - Ficha de detalle del paciente con historial de citas.
- **Módulo de Fichas Clínicas y Atenciones (`clinica/views.py`, `templates/fichas/`):**
  - Edición de antecedentes generales (`grupoSanguineo`, `alergias`, `antecedentesMedicos`).
  - Línea de tiempo cronológica de `AtencionClinica` con registro directo vinculado opcionalmente a una `Cita` (actualizando la cita a estado `Realizada`).
  - Control estricto de privacidad: `Recepcionista` no tiene acceso a fichas; `Paciente` solo ve su propia ficha sin `evolucionNotas` confidenciales.
- **Módulo de Agendamiento Real (`clinica/views.py`, `templates/agendamiento.html`):**
  - Validación anti-colisiones contra citas activas del profesional, bloqueos horarios (`BloqueoHorario`) y citas del paciente.
  - Creación automática de sala `Videoconsulta` al marcar modalidad Telemedicina.
  - Gestión de estados (`Agendada`, `Confirmada`, `Realizada`, `Cancelada`) y bloqueos horarios.
  - Endpoint JSON `/agendamiento/disponibilidad/` para mostrar horarios ocupados/bloqueados en tiempo real.
- **Dashboard Dinámico y Telemedicina (`templates/dashboard.html`, `templates/telemedicina.html`):**
  - Métricas reales por rol y listado de videoconsultas programadas.
  - Zona horaria configurada a `America/Santiago` en `core/settings.py`.
- **Pruebas Automatizadas (`clinica/tests.py`):**
  - 7 pruebas unitarias y de integración cubriendo RUT, RBAC, fichas y colisiones de agenda (`manage.py test clinica`).

### 13. Cifrado en Reposo, Dashboards por Rol, Telemedicina Dual y Caja/Liquidaciones (Partes 3 y 4)
- **Cifrado Simétrico en Reposo (`clinica/crypto.py`, `clinica/fields.py`, `core/settings.py`):**
  - Implementación de `EncryptedTextField` basado en `cryptography.fernet` (AES-128-CBC + HMAC-SHA256) usando `CLINICAL_ENCRYPTION_KEY` (con respaldo en `SECRET_KEY` y prefijo `enc::`).
  - Cifrado transparente de `FichaClinica` (`antecedentesMedicos`, `alergias`) y `AtencionClinica` (`motivoConsulta`, `diagnostico`, `evolucionNotas`, `indicacionesTratamiento`), manteniendo compatibilidad con texto legado sin prefijo.
  - Ajuste en `clinica/admin.py` retirando columnas cifradas de `search_fields`.
- **Dashboards Diferenciados por Rol (`clinica/views.py`, `templates/dashboard.html`):**
  - **Profesional:** citas de hoy, atenciones registradas, pendientes de cierre/evolución clínica y salas de telemedicina activas.
  - **Paciente:** próxima consulta destacada con acceso directo a videoconsulta, sesiones realizadas, pagos pendientes y últimas indicaciones (ocultando estrictamente `evolucionNotas`).
  - **Administrador / Recepcionista:** agenda del día con confirmación rápida, pacientes registrados, recaudación del día/mes y citas pendientes de cobro.
- **Entorno Dual de Telemedicina (`clinica/views.py`, `templates/telemedicina_sala.html`, `core/urls.py`):**
  - Panel izquierdo con videollamada **WebRTC Peer-to-Peer**, sala de espera virtual (`Pendiente` → `En espera` → `En curso` → `Finalizada`), controles de micrófono, cámara y compartir pantalla, más señalización SDP Offer/Answer e ICE Candidates vía `django.core.cache` (`/telemedicina/sala/<id>/senal/`).
  - Panel derecho con ficha clínica continua y guardado en vivo vía **AJAX** (`X-Requested-With: XMLHttpRequest`) para que el especialista registre y cifre evoluciones sin cortar la videollamada, y botón de cierre/finalización de sesión.
- **Módulo de Caja, Pagos y Liquidaciones (`clinica/models.py`, `clinica/forms.py`, `clinica/views.py`, `templates/caja/`):**
  - Ampliación del modelo `Pago` (migración `0004`) con `prevision`, `metodoPago`, `numeroComprobante`, `observaciones` y `registradoPor`.
  - Registro de cobros con correlativo automático de comprobante (`CMP-YYYYMMDD-XXXX`), cambios de estado (`Pagado` / `Pendiente` / `Anulado`), detección de citas sin cobro, cuadratura por medio de pago, cálculo configurable de comisión/liquidación líquida para especialistas y exportación a CSV (`;`, UTF-8 BOM para Excel).
  - Comprobante de pago imprimible y exportable a PDF desde el navegador (`templates/caja/comprobante.html` con reglas `@media print` en `static/css/style.css`).
  - Filtro de formato monetario chileno `|clp` en `clinica/templatetags/clinica_extras.py`.


---

## 🔍 Verificación Realizada
- **Migraciones:** Todas las migraciones (`0001` a `0004` de `clinica` + `admin`, `auth`, `contenttypes`, `sessions`) aplicadas exitosamente.
- **Pruebas Automatizadas:**
  - Bloqueo de usuarios anónimos en rutas privadas (redirección a login): **OK**.
  - Login con username y con email, cierre de sesión y reseteo de contraseña: **OK**.
  - Suite completa `python manage.py test clinica -v 2` (**12 pruebas** cubriendo RUT, Pacientes, Fichas/RBAC, Agendamiento anti-colisiones, Bloqueos, Atenciones, Cifrado en reposo en BD cruda, Dashboards por rol, Telemedicina Dual/AJAX/WebRTC y Caja/Liquidaciones/Comprobante/CSV): **OK**.


