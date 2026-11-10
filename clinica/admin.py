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
    NotificacionCita,
    AuditLog,
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
    list_display = ('id', 'cita', 'monto', 'prevision', 'metodoPago', 'estado', 'numeroComprobante', 'fechaPago')
    list_filter = ('estado', 'metodoPago', 'prevision')
    search_fields = ('numeroComprobante', 'cita__paciente__rut', 'cita__paciente__apellidos')


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
    list_display = ('id', 'fichaClinica', 'profesional', 'fechaHora')
    list_filter = ('profesional',)
    search_fields = ('fichaClinica__paciente__rut', 'fichaClinica__paciente__nombres', 'fichaClinica__paciente__apellidos')


@admin.register(NotificacionCita)
class NotificacionCitaAdmin(admin.ModelAdmin):
    list_display = ('id', 'cita', 'tipo', 'destinatario', 'exitoso', 'enviadoEn')
    list_filter = ('tipo', 'exitoso')
    search_fields = ('destinatario', 'asunto', 'cita__paciente__rut')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'fechaHora', 'usuarioUsername', 'rolUsuario', 'modulo', 'accion', 'resultado', 'ipOrigen')
    list_filter = ('resultado', 'modulo', 'accion', 'rolUsuario')
    search_fields = ('usuarioUsername', 'accion', 'descripcion', 'entidad', 'entidadId', 'ipOrigen')
    readonly_fields = (
        'fechaHora', 'usuario', 'usuarioUsername', 'rolUsuario', 'accion',
        'modulo', 'entidad', 'entidadId', 'descripcion', 'resultado',
        'ipOrigen', 'userAgent', 'datosExtra',
    )
    ordering = ('-fechaHora', '-id')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

