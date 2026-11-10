from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

from .models import NotificacionCita


ASUNTOS_POR_TIPO = {
    'Agendamiento': 'Confirmación de Cita Agendada',
    'Confirmación': 'Cita Confirmada en Centro Nodo',
    'Cancelación': 'Aviso de Cancelación de Cita',
    'Recordatorio': 'Recordatorio de Próxima Cita',
    'Actualización': 'Actualización de Estado de Cita',
}


def _enviar_correo_registro(cita, tipo, destinatario, nombre_destinatario, asunto, es_para_profesional=False):
    inicio_local = timezone.localtime(cita.fechaHoraInicio)
    fin_local = timezone.localtime(cita.fechaHoraFin)
    videoconsulta = getattr(cita, 'videoconsulta', None)

    context = {
        'cita': cita,
        'paciente': cita.paciente,
        'profesional': cita.profesional,
        'tipo': tipo,
        'asunto': asunto,
        'nombre_destinatario': nombre_destinatario,
        'es_para_profesional': es_para_profesional,
        'fecha_str': inicio_local.strftime('%d/%m/%Y'),
        'hora_inicio_str': inicio_local.strftime('%H:%M'),
        'hora_fin_str': fin_local.strftime('%H:%M'),
        'videoconsulta': videoconsulta,
        'clinic_address': 'Manuel Antonio Matta 549, Osorno',
    }

    text_body = render_to_string('emails/notificacion_cita.txt', context)
    html_body = render_to_string('emails/notificacion_cita.html', context)

    try:
        msg = EmailMultiAlternatives(
            subject=asunto,
            body=text_body,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'Centro Nodo <contacto@centronodo.cl>'),
            to=[destinatario],
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send(fail_silently=False)
        NotificacionCita.objects.create(
            cita=cita,
            tipo=tipo,
            destinatario=destinatario,
            asunto=asunto,
            exitoso=True,
        )
        return True
    except Exception as exc:
        NotificacionCita.objects.create(
            cita=cita,
            tipo=tipo,
            destinatario=destinatario,
            asunto=asunto,
            exitoso=False,
            detalleError=str(exc)[:250],
        )
        return False


def enviar_notificacion_cita(cita, tipo='Agendamiento', notificar_profesional=False):
    """
    Envía notificación por correo electrónico al paciente (si tiene usuario con email)
    y opcionalmente al profesional tratante, dejando traza en NotificacionCita.
    Retorna un diccionario con el resultado del envío.
    """
    fecha_hora_corta = timezone.localtime(cita.fechaHoraInicio).strftime('%d/%m/%Y %H:%M')
    base_asunto = ASUNTOS_POR_TIPO.get(tipo, f'Notificación de Cita ({tipo})')
    asunto_paciente = f"[Centro Nodo] {base_asunto} — {fecha_hora_corta}"

    enviado_paciente = False
    email_paciente = (
        cita.paciente.usuario.email
        if cita.paciente.usuario_id and cita.paciente.usuario.email
        else None
    )

    if email_paciente:
        enviado_paciente = _enviar_correo_registro(
            cita=cita,
            tipo=tipo,
            destinatario=email_paciente,
            nombre_destinatario=f"{cita.paciente.nombres} {cita.paciente.apellidos}",
            asunto=asunto_paciente,
            es_para_profesional=False,
        )

    enviado_profesional = False
    if notificar_profesional:
        email_prof = (
            cita.profesional.usuario.email
            if cita.profesional.usuario_id and cita.profesional.usuario.email
            else None
        )
        if email_prof and email_prof != email_paciente:
            asunto_prof = f"[Agenda Centro Nodo] {tipo} Cita #{cita.id} — {fecha_hora_corta}"
            enviado_profesional = _enviar_correo_registro(
                cita=cita,
                tipo=tipo,
                destinatario=email_prof,
                nombre_destinatario=f"{cita.profesional.nombres} {cita.profesional.apellidos}",
                asunto=asunto_prof,
                es_para_profesional=True,
            )

    return {
        'enviado_paciente': enviado_paciente,
        'email_paciente': email_paciente,
        'enviado_profesional': enviado_profesional,
    }

