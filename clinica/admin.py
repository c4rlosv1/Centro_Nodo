from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import (
    Rol,
    Usuario,
    Paciente,
    Profesional,
    BloqueoHorario,
    Cita,
    Videoconsulta,
    Pago,
    FichaClinica,
    AtencionClinica,
)


@admin.register(Rol)
class RolAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre', 'descripcion')
    search_fields = ('nombre',)


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'rol', 'is_active', 'is_staff')
    list_filter = ('rol', 'is_active', 'is_staff')
    fieldsets = UserAdmin.fieldsets + (
        ('Información Clínica y Roles', {'fields': ('rol', 'activo', 'password_hash')}),
    )


@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ('rut', 'apellidos', 'nombres', 'usuario', 'telefono')
    search_fields = ('rut', 'nombres', 'apellidos')


@admin.register(Profesional)
class ProfesionalAdmin(admin.ModelAdmin):
    list_display = ('rut', 'apellidos', 'nombres', 'especialidad', 'usuario', 'registro_salud')
    search_fields = ('rut', 'nombres', 'apellidos', 'especialidad')


@admin.register(BloqueoHorario)
class BloqueoHorarioAdmin(admin.ModelAdmin):
    list_display = ('profesional', 'fechaHoraInicio', 'fechaHoraFin', 'motivo', 'estado')
    list_filter = ('estado', 'profesional')


@admin.register(Cita)
class CitaAdmin(admin.ModelAdmin):
    list_display = ('id', 'paciente', 'profesional', 'fechaHoraInicio', 'fechaHoraFin', 'estado')
    list_filter = ('estado', 'profesional')
    search_fields = ('paciente__nombres', 'paciente__apellidos', 'paciente__rut')


@admin.register(Videoconsulta)
class VideoconsultaAdmin(admin.ModelAdmin):
    list_display = ('id', 'cita', 'urlSalaWebRTC', 'estadoConexion')
    list_filter = ('estadoConexion',)


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ('id', 'cita', 'monto', 'estado', 'fechaPago')
    list_filter = ('estado',)


class AtencionClinicaInline(admin.StackedInline):
    model = AtencionClinica
    extra = 0


@admin.register(FichaClinica)
class FichaClinicaAdmin(admin.ModelAdmin):
    list_display = ('id', 'paciente', 'fechaCreacion', 'grupoSanguineo')
    search_fields = ('paciente__nombres', 'paciente__apellidos', 'paciente__rut')
    inlines = [AtencionClinicaInline]


@admin.register(AtencionClinica)
class AtencionClinicaAdmin(admin.ModelAdmin):
    list_display = ('id', 'fichaClinica', 'profesional', 'fechaHora', 'motivoConsulta')
    list_filter = ('profesional',)
    search_fields = ('fichaClinica__paciente__rut', 'motivoConsulta', 'diagnostico')
