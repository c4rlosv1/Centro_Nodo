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
  - Paciente `paciente.prueba` (`paciente1234`) asociado a su ficha en la tabla `paciente`.

---

## 🔍 Verificación Realizada
- **Migraciones:** Todas las migraciones iniciales (`admin`, `auth`, `clinica`, `contenttypes`, `sessions`) fueron aplicadas exitosamente sobre la base de datos.
- **Pruebas Automatizadas:**
  - Bloqueo de usuarios anónimos en rutas privadas (redirección a login): **OK**.
  - Login con username: **OK**.
  - Login con email: **OK**.
  - Creación de sesión y renderizado de usuario autenticado: **OK**.
  - Cierre de sesión y destrucción de sesión: **OK**.
  - Generación de token y correo de restablecimiento de contraseña: **OK**.

