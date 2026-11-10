from django.core.management.base import BaseCommand
from clinica.models import Rol, Usuario, Profesional, Paciente, FichaClinica


class Command(BaseCommand):
    help = "Crea los roles del sistema y usuarios de prueba iniciales para Centro Nodo"

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Iniciando creación de roles y usuarios de prueba..."))

        # 1. Crear Roles
        roles_data = [
            ("Administrador", "Acceso total a la administración, configuración y reportes de la clínica"),
            ("Profesional", "Especialistas de la salud mental: psicólogos, psiquiatras y terapeutas"),
            ("Paciente", "Pacientes con acceso a sus citas, videoconsultas y fichas"),
            ("Recepcionista", "Personal administrativo encargado de recepción, pagos y agendamiento"),
        ]

        roles = {}
        for nombre, descripcion in roles_data:
            rol, created = Rol.objects.get_or_create(
                nombre=nombre,
                defaults={'descripcion': descripcion}
            )
            roles[nombre] = rol
            status = "creado" if created else "ya existe"
            self.stdout.write(f" - Rol '{nombre}': {status}")

        # 2. Crear Superusuario Administrador
        if not Usuario.objects.filter(username="admin").exists():
            admin_user = Usuario.objects.create_superuser(
                username="admin",
                email="admin@centronodo.cl",
                password="admin1234",
                first_name="Admin",
                last_name="Centro Nodo",
                rol=roles["Administrador"],
            )
            self.stdout.write(self.style.SUCCESS(" + Superusuario 'admin' creado exitosamente."))
        else:
            admin_user = Usuario.objects.get(username="admin")
            admin_user.rol = roles["Administrador"]
            admin_user.save()
            self.stdout.write(" - Superusuario 'admin' ya existe (rol verificado).")

        # 3. Crear Usuario Profesional 1 (Psiquiatra)
        if not Usuario.objects.filter(username="doctor.silva").exists():
            prof_user = Usuario.objects.create_user(
                username="doctor.silva",
                email="dr.silva@centronodo.cl",
                password="medico1234",
                first_name="Andrés",
                last_name="Silva",
                rol=roles["Profesional"],
            )
            Profesional.objects.get_or_create(
                rut="15.342.980-4",
                defaults={
                    'usuario': prof_user,
                    'nombres': "Andrés",
                    'apellidos': "Silva",
                    'especialidad': "Psiquiatría Adultos",
                }
            )
            self.stdout.write(self.style.SUCCESS(" + Usuario 'doctor.silva' (Profesional) creado exitosamente."))
        else:
            self.stdout.write(" - Usuario 'doctor.silva' ya existe.")

        # 4. Crear Usuario Profesional 2 (Psicóloga)
        if not Usuario.objects.filter(username="psicologa.rojas").exists():
            prof2_user = Usuario.objects.create_user(
                username="psicologa.rojas",
                email="p.rojas@centronodo.cl",
                password="medico1234",
                first_name="Camila",
                last_name="Rojas",
                rol=roles["Profesional"],
            )
            Profesional.objects.get_or_create(
                rut="17.654.321-3",
                defaults={
                    'usuario': prof2_user,
                    'nombres': "Camila",
                    'apellidos': "Rojas",
                    'especialidad': "Psicología Clínica",
                }
            )
            self.stdout.write(self.style.SUCCESS(" + Usuario 'psicologa.rojas' (Profesional) creado exitosamente."))
        else:
            self.stdout.write(" - Usuario 'psicologa.rojas' ya existe.")

        # 5. Crear Usuario Recepcionista
        if not Usuario.objects.filter(username="recepcion").exists():
            Usuario.objects.create_user(
                username="recepcion",
                email="recepcion@centronodo.cl",
                password="recepcion1234",
                first_name="Sofía",
                last_name="Muñoz",
                rol=roles["Recepcionista"],
            )
            self.stdout.write(self.style.SUCCESS(" + Usuario 'recepcion' (Recepcionista) creado exitosamente."))
        else:
            self.stdout.write(" - Usuario 'recepcion' ya existe.")

        # 6. Crear Usuario Paciente
        if not Usuario.objects.filter(username="paciente.prueba").exists():
            pac_user = Usuario.objects.create_user(
                username="paciente.prueba",
                email="paciente@correo.cl",
                password="paciente1234",
                first_name="Juan",
                last_name="Pérez",
                rol=roles["Paciente"],
            )
            paciente_obj, _ = Paciente.objects.get_or_create(
                rut="19.876.543-0",
                defaults={
                    'usuario': pac_user,
                    'nombres': "Juan",
                    'apellidos': "Pérez",
                    'telefono': "+56 9 8765 4321",
                }
            )
            FichaClinica.objects.get_or_create(
                paciente=paciente_obj,
                defaults={
                    'antecedentesMedicos': "Sin antecedentes mórbidos relevantes.",
                    'alergias': "Ninguna conocida.",
                    'grupoSanguineo': "O+",
                }
            )
            self.stdout.write(self.style.SUCCESS(" + Usuario 'paciente.prueba' y Ficha Clínica creados exitosamente."))
        else:
            # Corregir RUT del paciente de prueba antiguo si tenía dígito verificador inválido
            pac_existente = Paciente.objects.filter(rut="19.876.543-2").first()
            if pac_existente:
                pac_existente.rut = "19.876.543-0"
                pac_existente.save(update_fields=['rut'])
                self.stdout.write(" ~ RUT de 'paciente.prueba' normalizado a '19.876.543-0'.")
            self.stdout.write(" - Usuario 'paciente.prueba' ya existe.")

        self.stdout.write(self.style.SUCCESS("\n[LISTO] Roles y usuarios de prueba disponibles para iniciar sesión."))
