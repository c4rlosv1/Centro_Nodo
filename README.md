# 🏥 GESTION NODO - Sistema de Gestión Integral y Telemedicina

Solución web integral orientada a la digitalización clínica, gestión de fichas electrónicas y telemedicina del centro de salud mental **Centro Nodo** (Osorno, Chile).

---

## 🛠️ Tecnologías Utilizadas
* **Backend:** Python 3.11+ / Django 5.x
* **Base de Datos:** MySQL 8.0 (Engine InnoDB) / SQLite (Fallback de desarrollo)
* **Autenticación y Seguridad:** Autenticación personalizada (Username o Email), RBAC por roles, hashing PBKDF2 y cifrado simétrico en reposo (`cryptography` Fernet) para fichas clínicas
* **Frontend:** HTML5 semántico, CSS3 modular (soporte tema Claro/Oscuro e impresión), JavaScript Vanilla
* **Telemedicina:** WebRTC (Peer-to-Peer) con señalización y panel dual en vivo

---

## 🌟 Módulos Principales
1. **Control de Acceso y Roles (RBAC):** Perfiles y dashboards diferenciados para Médicos/Profesionales, Pacientes, Recepcionistas y Administradores.
2. **Agendamiento en tiempo real:** Gestión de disponibilidad de especialistas, bloqueos horarios, detección de colisiones y recordatorios por correo.
3. **Ficha Clínica Electrónica Cifrada:** Almacenamiento cifrado en reposo (`EncryptedTextField`) de historiales médicos, alergias y evoluciones clínicas (`AtencionClinica`).
4. **Entorno Dual de Telemedicina:** Videoconsulta WebRTC P2P con Sala de Espera Virtual (compuerta previa a la admisión) y notas clínicas continuas vía AJAX sin interrumpir el video.
5. **Caja, Pagos y Liquidaciones:** Registro de pagos por consulta, cuadratura por medio de pago, cálculo de comisiones/honorarios, comprobantes, reporte consolidado PDF/imprimible y exportación a CSV.
6. **Documentos Clínicos Imprimibles (PDF):** Emisión de Certificados de Asistencia (sin exponer diagnóstico) y Resumen de Atención e Indicaciones Terapéuticas desde la ficha clínica o el panel del paciente.
7. **Notificaciones y Recordatorios de Citas:** Correos multiparte automáticos al agendar, confirmar o cancelar, recordatorio manual desde agenda y comando programable `manage.py enviar_recordatorios_citas`.

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

### 3. Configurar variables de entorno (opcional en desarrollo)
```bash
copy .env.example .env
# Ajustar CLINICAL_ENCRYPTION_KEY, datos MySQL (Laragon) y variables SMTP si deseas correos reales
```

### 4. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 5. Ejecutar migraciones
```bash
python manage.py migrate
```

### 6. Crear roles y usuarios de prueba
```bash
python manage.py crear_roles_y_usuarios
```

### 7. Iniciar el servidor
```bash
python manage.py runserver
```
Abre en tu navegador: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)

### 8. Recordatorios programados de citas (opcional / Cron)
```bash
# Vista previa sin enviar correos
python manage.py enviar_recordatorios_citas --horas 24 --dry-run

# Envío efectivo (con registro en NotificacionCita para no duplicar)
python manage.py enviar_recordatorios_citas --horas 24
```

---

## 🔑 Credenciales de Prueba

| Rol | Usuario / Correo | Contraseña | Perfil |
| :--- | :--- | :--- | :--- |
| **Administrador** | `admin` o `admin@centronodo.cl` | `admin1234` | Superusuario con acceso global |
| **Profesional** | `doctor.silva` o `dr.silva@centronodo.cl` | `medico1234` | Dr. Andrés Silva (Psiquiatría) |
| **Profesional** | `psicologa.rojas` o `p.rojas@centronodo.cl` | `medico1234` | Ps. Camila Rojas (Psicología Clínica) |
| **Recepcionista** | `recepcion` o `recepcion@centronodo.cl` | `recepcion1234` | Sofía Muñoz (Admisión y Agenda) |
| **Paciente** | `paciente.prueba` o `paciente@correo.cl` | `paciente1234` | Juan Pérez (RUT: `19.876.543-0`) |

---

## 📚 Documentación Técnica
- [Guía Completa de Autenticación y RBAC](docs/AUTENTICACION_Y_LOGIN.md)
- [Diagrama Entidad-Relación Corregido](docs/DIAGRAMA_ER_CORREGIDO.md)
- [Registro de Cambios (Changelog)](docs/CHANGELOG.md)
- [Guía para Subir Cambios a GitHub](docs/COMO_SUBIR_CAMBIOS_A_GITHUB.md)
