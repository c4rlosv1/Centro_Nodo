from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views

from clinica.views import (
    dashboard_view,
    agendamiento_view,
    telemedicina_view,
    login_view,
    logout_view,
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

    # Módulos de la Clínica
    path('', dashboard_view, name='dashboard'),
    path('agendamiento/', agendamiento_view, name='agendamiento'),
    path('telemedicina/', telemedicina_view, name='telemedicina'),
]
