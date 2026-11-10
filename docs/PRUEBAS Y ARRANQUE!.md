# 1. Ejecutar las 31 pruebas automatizadas (7 Fases + Seguridad/Límites + Auditoría y Errores 403/404/500)
.\.venv\Scripts\python.exe manage.py test clinica -v 2

# 2. Verificar integridad del proyecto y que no falten migraciones
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run

# 3. Probar recordatorios de citas próximas (simulación sin enviar)
.\.venv\Scripts\python.exe manage.py enviar_recordatorios_citas --horas 24 --dry-run

# 4. Probar envío real de recordatorios (se imprimen en consola si no hay SMTP en .env)
.\.venv\Scripts\python.exe manage.py enviar_recordatorios_citas --horas 24



INICIAR:
# Activar el entorno virtual (opcional si usas la ruta directa .\.venv\Scripts\python.exe)
.\.venv\Scripts\Activate.ps1

# (Opcional) Verificar migraciones y asegurar usuarios de prueba
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py crear_roles_y_usuarios

# Levantar el servidor de desarrollo
.\.venv\Scripts\python.exe manage.py runserver


USUARIOS :

| Rol | Usuario | Correo | Contraseña |
| --- | --- | --- | --- |
| Administrador | `admin` | `admin@centronodo.cl` | `admin1234` |
| Profesional | `doctor.silva` | `dr.silva@centronodo.cl` | `medico1234` |
| Profesional | `psicologa.rojas` | `p.rojas@centronodo.cl` | `medico1234` |
| Recepcionista | `recepcion` | `recepcion@centronodo.cl` | `recepcion1234` |
| Paciente | `paciente.prueba` | `paciente@correo.cl` | `paciente1234` |