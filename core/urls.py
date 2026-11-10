from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views

from clinica.views import (
    dashboard_view,
    agendamiento_view,
    cita_cambiar_estado_view,
    bloqueo_crear_view,
    bloqueo_eliminar_view,
    disponibilidad_json_view,
    telemedicina_view,
    telemedicina_sala_view,
    telemedicina_estado_view,
    telemedicina_senal_view,
    caja_view,
    pago_cambiar_estado_view,
    pago_comprobante_view,
    caja_exportar_csv_view,
    login_view,
    logout_view,
    pacientes_lista_view,
    paciente_crear_view,
    paciente_editar_view,
    paciente_detalle_view,
    fichas_lista_view,
    ficha_detalle_view,
    ficha_editar_antecedentes_view,
    atencion_crear_view,
)
from clinica.forms import CustomPasswordResetForm, CustomSetPasswordForm

urlpatterns = [
    path('admin/', admin.site.urls),

    # Autenticación y Control de Sesiones
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),

    # Recuperación de Contraseñas
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='password_reset.html',
        form_class=CustomPasswordResetForm,
        email_template_name='password_reset_email.html',
        subject_template_name='password_reset_subject.txt',
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='password_reset_done.html',
    ), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='password_reset_confirm.html',
        form_class=CustomSetPasswordForm,
    ), name='password_reset_confirm'),
    path('password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='password_reset_complete.html',
    ), name='password_reset_complete'),

    # Panel Principal
    path('', dashboard_view, name='dashboard'),

    # Módulo de Pacientes
    path('pacientes/', pacientes_lista_view, name='pacientes_lista'),
    path('pacientes/nuevo/', paciente_crear_view, name='paciente_crear'),
    path('pacientes/<int:paciente_id>/', paciente_detalle_view, name='paciente_detalle'),
    path('pacientes/<int:paciente_id>/editar/', paciente_editar_view, name='paciente_editar'),

    # Módulo de Fichas Clínicas y Atenciones (Evoluciones)
    path('fichas/', fichas_lista_view, name='fichas_lista'),
    path('fichas/<int:ficha_id>/', ficha_detalle_view, name='ficha_detalle'),
    path('fichas/<int:ficha_id>/editar-antecedentes/', ficha_editar_antecedentes_view, name='ficha_editar_antecedentes'),
    path('fichas/<int:ficha_id>/nueva-atencion/', atencion_crear_view, name='atencion_crear'),

    # Módulo de Agendamiento Real
    path('agendamiento/', agendamiento_view, name='agendamiento'),
    path('agendamiento/disponibilidad/', disponibilidad_json_view, name='agendamiento_disponibilidad'),
    path('agendamiento/cita/<int:cita_id>/estado/', cita_cambiar_estado_view, name='cita_cambiar_estado'),
    path('agendamiento/bloqueos/nuevo/', bloqueo_crear_view, name='bloqueo_crear'),
    path('agendamiento/bloqueos/<int:bloqueo_id>/eliminar/', bloqueo_eliminar_view, name='bloqueo_eliminar'),

    # Módulo de Telemedicina (Panel Dual WebRTC + Notas Clínicas)
    path('telemedicina/', telemedicina_view, name='telemedicina'),
    path('telemedicina/sala/<int:videoconsulta_id>/', telemedicina_sala_view, name='telemedicina_sala'),
    path('telemedicina/sala/<int:videoconsulta_id>/estado/', telemedicina_estado_view, name='telemedicina_estado'),
    path('telemedicina/sala/<int:videoconsulta_id>/senal/', telemedicina_senal_view, name='telemedicina_senal'),

    # Módulo de Caja, Pagos y Liquidaciones
    path('caja/', caja_view, name='caja'),
    path('caja/pago/<int:pago_id>/estado/', pago_cambiar_estado_view, name='pago_cambiar_estado'),
    path('caja/comprobante/<int:pago_id>/', pago_comprobante_view, name='pago_comprobante'),
    path('caja/exportar/', caja_exportar_csv_view, name='caja_exportar_csv'),
]
