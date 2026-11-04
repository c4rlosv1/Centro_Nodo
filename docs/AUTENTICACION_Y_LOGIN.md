# 🔐 Guía Completa de Autenticación y Control de Acceso (RBAC)
**Sistema de Gestión Clínica y Telemedicina – Centro Nodo (Osorno, Chile)**

---

## 1. Visión General de la Solución

Se ha implementado un sistema completo de autenticación y autorización basado en roles (**Role-Based Access Control - RBAC**) sobre Django 5.x. El sistema permite el acceso seguro y segmentado tanto para especialistas médicos/psicólogos, pacientes y personal administrativo.

### Capacidades Principales Implementadas:
1. **Inicio de Sesión Dual (Username o Email):** Los usuarios pueden autenticarse indistintamente ingresando su nombre de usuario (o RUT) o su correo electrónico registrado.
2. **Control de Acceso Basado en Roles (RBAC):** Decoradores `@login_required` y `@rol_requerido` para restringir vistas según el perfil del usuario.
3. **Persistencia y Duración de Sesión:** Checkbox *"Mantener sesión iniciada"* (expiración en 14 días vs expiración al cerrar el navegador).
4. **Flujo Completo de Recuperación de Contraseña:** Solicitud con token seguro de un solo uso por correo electrónico y restablecimiento guiado.
5. **Interfaz de Usuario Coherente con Modo Oscuro/Claro:** Plantillas diseñadas con CSS variables, animaciones suaves y alertas de error/éxito.
6. **Comando de Carga Inicial (Seeder):** Comando automatizado para poblar roles y usuarios de prueba listos para usar.

---

## 2. Usuarios y Credenciales de Prueba

Para facilitar las pruebas de desarrollo, se crearon los siguientes perfiles con el comando `python manage.py crear_roles_y_usuarios`:

| Rol | Usuario | Correo Electrónico | Contraseña | Perfil Asociado |
| :--- | :--- | :--- | :--- | :--- |
| **Administrador** | `admin` | `admin@centronodo.cl` | `admin1234` | Superusuario con acceso total al admin y módulos. |
| **Profesional** | `doctor.silva` | `dr.silva@centronodo.cl` | `medico1234` | Dr. Andrés Silva (Psiquiatría Adultos) - RUT: `15.342.980-4` |
| **Paciente** | `paciente.prueba` | `paciente@correo.cl` | `paciente1234` | Juan Pérez - RUT: `19.876.543-2` |

> [!TIP]
> Puedes iniciar sesión ingresando el **nombre de usuario** o el **correo electrónico** en el mismo campo.

---

## 3. Arquitectura y Componentes Técnicos

```
                      ┌──────────────────────────────────────────┐
                      │              Cliente Web                 │
                      └────────────────────┬─────────────────────┘
                                           │
                        POST /login/       │
                        (login_id + clave) │
                                           ▼
                      ┌──────────────────────────────────────────┐
                      │    clinica.backends:                     │
                      │    EmailOrUsernameModelBackend           │
                      │    (Busca por username o email)          │
                      └────────────────────┬─────────────────────┘
                                           │
                         Credenciales OK   │
                                           ▼
                      ┌──────────────────────────────────────────┐
                      │    clinica.models.Usuario                │
                      │    (Valida password con PBKDF2)          │
                      └────────────────────┬─────────────────────┘
                                           │
                         Sesión Creada     │
                                           ▼
 ┌─────────────────────────────────────────────────────────────────────────────────┐
 │                            Vistas Protegidas (RBAC)                             │
 │                                                                                 │
 │   @login_required                @rol_requerido(['Profesional', 'Admin'])       │
 │   GET /                          GET /telemedicina/                             │
 │   Dashboard General              Sala Dual WebRTC y Notas                       │
 └─────────────────────────────────────────────────────────────────────────────────┘
```

### Componentes Creados:

### A. Backend de Autenticación (`clinica/backends.py`)
Clase `EmailOrUsernameModelBackend` que intercepta la autenticación de Django:
- Realiza una búsqueda `Q(username__iexact=username) | Q(email__iexact=username)`.
- Si encuentra coincidencia y la contraseña es válida (`check_password`), autoriza al usuario.
- Registrado en `settings.py` dentro de `AUTHENTICATION_BACKENDS`.

### B. Modelo de Usuario (`clinica/models.py`)
- Configurado formalmente en `core/settings.py` con `AUTH_USER_MODEL = 'clinica.Usuario'`.
- Propiedades útiles agregadas:
  - `user.rol_nombre`: Devuelve el nombre del rol o *"Sin Rol"*.
  - `user.es_administrador`: `True` si es superusuario o tiene rol Administrador.
  - `user.es_profesional`: `True` si su rol es médico, psiquiatra o psicólogo.
  - `user.es_paciente`: `True` si su rol es paciente.
- Sincronización automática de `activo` con `is_active` en el método `save()`.

### C. Decorador RBAC (`clinica/decorators.py`)
- `@rol_requerido(roles_permitidos)`:
  - Si el usuario no está autenticado, lo redirige a `login`.
  - Si el usuario es `superuser`, tiene acceso irrestricto.
  - Si el rol del usuario no coincide, emite un mensaje de advertencia y redirige al `dashboard`.

### D. Formularios (`clinica/forms.py`)
- `LoginForm`: Campo `login_id` con autocompletado y estilos CSS del sistema, campo `password` con widget seguro y `remember_me`.
- `CustomPasswordResetForm` y `CustomSetPasswordForm`: Formularios de recuperación de clave integrados con las clases CSS del proyecto.

### E. Vistas (`clinica/views.py`)
- `login_view`: Autenticación, validación de estado activo, expiración de sesión y redirección segura (`url_has_allowed_host_and_scheme`).
- `logout_view`: Cierre de sesión y mensaje flash.
- `dashboard_view`, `agendamiento_view`, `telemedicina_view`: Protegidas con decoradores.

### F. Rutas (`core/urls.py`)
- `/login/`: Formulario y procesamiento de login.
- `/logout/`: Cierre de sesión.
- `/password-reset/`: Solicitud de enlace para olvidar contraseña.
- `/password-reset/done/`: Confirmación de envío de correo.
- `/password-reset-confirm/<uidb64>/<token>/`: Ingreso de nueva clave mediante token.
- `/password-reset-complete/`: Confirmación final de cambio de contraseña.

---

## 4. Cómo Probar el Sistema en Desarrollo

### 1. Activar el entorno virtual e iniciar el servidor:
```powershell
# En la raíz del proyecto (x:\Datos Proyectos\centro nodo)
.\.venv\Scripts\activate
python manage.py runserver
```

### 2. Pruebas sugeridas:
1. **Acceso Anónimo:** Entra en tu navegador a `http://127.0.0.1:8000/`. El sistema te redirigirá automáticamente a `http://127.0.0.1:8000/login/?next=/`.
2. **Iniciar Sesión con Correo:** En el formulario de login ingresa `dr.silva@centronodo.cl` y clave `medico1234`.
3. **Observar la Barra de Navegación:** Verás tu nombre *"Andrés"* con el distintivo **PROFESIONAL** y el botón para cerrar sesión.
4. **Recuperación de Contraseña:** Haz clic en *"¿Olvidaste tu contraseña?"* e ingresa `admin@centronodo.cl`. En la terminal de ejecución verás impreso el correo de recuperación con el enlace y token generado por Django.
5. **Cerrar Sesión:** Haz clic en *"Cerrar Sesión"* en el menú superior para verificar que la sesión se destruye y regresa a la pantalla de login.

---

## 5. Guía para Nuevos Módulos (Cómo Proteger Vistas)

Cuando crees nuevas vistas en `clinica/views.py`, puedes aplicar la seguridad así:

```python
from django.contrib.auth.decorators import login_required
from clinica.decorators import rol_requerido

# Vista accesible para cualquier usuario autenticado:
@login_required
def ver_mis_datos(request):
    return render(request, 'mis_datos.html')

# Vista restringida exclusivamente para personal médico:
@login_required
@rol_requerido(['Profesional', 'Administrador'])
def modulo_fichas_clinicas(request):
    return render(request, 'fichas.html')
```

dr.silva@centronodo.cl y clave medico1234