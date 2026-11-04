# 🏥 GESTION NODO - Sistema de Gestión Integral y Telemedicina

Solución web integral orientada a la digitalización clínica, gestión de fichas electrónicas y telemedicina del centro de salud mental **Centro Nodo** (Osorno, Chile).

---

## 🛠️ Tecnologías Utilizadas
* **Backend:** Python 3.11+ / Django 5.x
* **Base de Datos:** MySQL 8.0 (Engine InnoDB) / SQLite (Fallback de desarrollo)
* **Autenticación y Seguridad:** Autenticación personalizada (Username o Email), RBAC por roles, hashing PBKDF2
* **Frontend:** HTML5 semántico, CSS3 modular (soporte tema Claro/Oscuro), JavaScript Vanilla
* **Telemedicina:** WebRTC (Peer-to-Peer)

---

## 🌟 Módulos Principales
1. **Control de Acceso y Roles (RBAC):** Perfiles diferenciados para Médicos/Profesionales, Pacientes y Administradores.
2. **Agendamiento en tiempo real:** Gestión de disponibilidad de especialistas y mitigación de colisiones horarias.
3. **Ficha Clínica Electrónica:** Almacenamiento seguro de historiales médicos y evoluciones de pacientes.
4. **Entorno de Telemedicina:** Plataforma con panel dual (videoconsulta y notas clínicas continuas).
5. **Caja y Liquidaciones:** Registro de pagos por consulta y automatización de cuadratura diaria.

---

## 🚀 Puesta en Marcha Local

### 1. Clonar el repositorio
```bash
git clone https://github.com/negrosson/GESTION-NODO.git
cd GESTION-NODO
```

### 2. Crear y activar el entorno virtual
```bash
# Windows
python -m venv .venv
.\.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Ejecutar migraciones
```bash
python manage.py migrate
```

### 5. Crear roles y usuarios de prueba
```bash
python manage.py crear_roles_y_usuarios
```

### 6. Iniciar el servidor
```bash
python manage.py runserver
```
Abre en tu navegador: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

---

## 🔑 Credenciales de Prueba

| Rol | Usuario / Correo | Contraseña | Perfil |
| :--- | :--- | :--- | :--- |
| **Administrador** | `admin` o `admin@centronodo.cl` | `admin1234` | Superusuario con acceso global |
| **Profesional** | `doctor.silva` o `dr.silva@centronodo.cl` | `medico1234` | Dr. Andrés Silva (Psiquiatría) |
| **Paciente** | `paciente.prueba` o `paciente@correo.cl` | `paciente1234` | Juan Pérez |

---

## 📚 Documentación Técnica
- [Guía Completa de Autenticación y RBAC](docs/AUTENTICACION_Y_LOGIN.md)
- [Registro de Cambios (Changelog)](docs/CHANGELOG.md)
