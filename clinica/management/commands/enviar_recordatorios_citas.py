from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone

from clinica.models import Cita
from clinica.notifications import enviar_notificacion_cita


class Command(BaseCommand):
    help = "Envía recordatorios por correo electrónico para citas próximas sin recordatorio previo."

    def add_arguments(self, parser):
        parser.add_argument(
            '--horas',
            type=int,
            default=24,
            help='Ventana de anticipación en horas para enviar recordatorios (por defecto: 24).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Muestra las citas elegibles sin enviar correos reales.',
        )

    def handle(self, *args, **options):
        horas = options['horas']
        dry_run = options['dry_run']
        ahora = timezone.now()
        limite = ahora + timedelta(hours=horas)

        citas = Cita.objects.select_related(
            'paciente', 'paciente__usuario', 'profesional', 'videoconsulta'
        ).filter(
            fechaHoraInicio__gte=ahora,
            fechaHoraInicio__lte=limite,
            estado__in=['Agendada', 'Confirmada'],
        ).exclude(
            notificaciones__tipo='Recordatorio',
            notificaciones__exitoso=True,
        ).order_by('fechaHoraInicio')

        enviados = 0
        sin_email = 0
        errores = 0

        for cita in citas:
            email_pac = cita.paciente.usuario.email if cita.paciente.usuario_id else None
            if not email_pac:
                sin_email += 1
                self.stdout.write(f" - Omitida Cita #{cita.id} ({cita.paciente}): sin correo registrado.")
                continue

            if dry_run:
                self.stdout.write(f" [DRY-RUN] Cita #{cita.id} -> {email_pac} ({timezone.localtime(cita.fechaHoraInicio)})")
                enviados += 1
                continue

            res = enviar_notificacion_cita(cita, tipo='Recordatorio', notificar_profesional=False)
            if res['enviado_paciente']:
                enviados += 1
                self.stdout.write(self.style.SUCCESS(f" + Recordatorio enviado Cita #{cita.id} -> {email_pac}"))
            else:
                errores += 1
                self.stdout.write(self.style.WARNING(f" ! Error enviando Cita #{cita.id} -> {email_pac}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Proceso finalizado: {enviados} recordatorio(s) procesado(s), {sin_email} sin correo, {errores} error(es)."
            )
        )

