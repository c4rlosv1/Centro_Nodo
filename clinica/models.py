from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from .fields import EncryptedTextField


class Rol(models.Model):
    id = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)

    class Meta:
        app_label = 'clinica'
        db_table = 'rol'

    def __str__(self):
        return self.nombre


class Usuario(AbstractUser):
    id = models.AutoField(primary_key=True)
    rol = models.ForeignKey(Rol, on_delete=models.SET_NULL, null=True, blank=True, related_name='usuarios')
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=255, blank=True, null=True)
    activo = models.BooleanField(default=True)

    groups = models.ManyToManyField(
        'auth.Group',
        verbose_name='groups',
        blank=True,
        related_name='clinica_usuario_set',
        related_query_name='clinica_usuario',
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        verbose_name='user permissions',
        blank=True,
        related_name='clinica_usuario_set',
        related_query_name='clinica_usuario',
    )

    class Meta:
        app_label = 'clinica'
        db_table = 'usuario'

    def __str__(self):
        rol_nombre = self.rol.nombre if self.rol else "Sin Rol"
        return f"{self.username} ({rol_nombre})"

    def save(self, *args, **kwargs):
        # Mantiene sincronizado el estado activo nativo de Django
        if self.activo is not None:
            self.is_active = self.activo
        super().save(*args, **kwargs)

    @property
    def rol_nombre(self):
        return self.rol.nombre if self.rol else "Sin Rol"

    @property
    def es_administrador(self):
        return self.is_superuser or (self.rol and self.rol.nombre.lower() == 'administrador')

    @property
    def es_profesional(self):
        return bool(self.rol and self.rol.nombre.lower() in ['profesional', 'médico', 'medico', 'psicólogo', 'psicologo', 'psiquiatra'])

    @property
    def es_paciente(self):
        return bool(self.rol and self.rol.nombre.lower() == 'paciente')

    @property
    def es_recepcionista(self):
        return bool(self.rol and self.rol.nombre.lower() in ['recepcionista', 'recepción', 'administrativo'])

    @property
    def es_staff_clinico(self):
        return self.es_administrador or self.es_profesional or self.es_recepcionista


class Paciente(models.Model):
    """
    Perfil clínico del paciente.
    Relación 1 a 1 con Usuario (opcional si el paciente es registrado presencialmente sin portal web).
    """
    id = models.AutoField(primary_key=True)
    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.CASCADE,
        related_name='paciente',
        null=True,
        blank=True
    )
    rut = models.CharField(max_length=20, unique=True)
    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    telefono = models.CharField(max_length=30, blank=True, null=True)

    class Meta:
        app_label = 'clinica'
        db_table = 'paciente'

    def __str__(self):
        return f"{self.apellidos}, {self.nombres} ({self.rut})"


class Profesional(models.Model):
    """
    Perfil del profesional de la salud mental (psicólogo, psiquiatra, terapeuta).
    Relación 1 a 1 con Usuario.
    """
    id = models.AutoField(primary_key=True)
    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.CASCADE,
        related_name='profesional'
    )
    rut = models.CharField(max_length=20, unique=True)
    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    especialidad = models.CharField(max_length=100)
    registro_salud = models.CharField(max_length=50, blank=True, null=True)

    class Meta:
        app_label = 'clinica'
        db_table = 'profesional'

    def __str__(self):
        return f"{self.apellidos}, {self.nombres} - {self.especialidad}"


class BloqueoHorario(models.Model):
    """
    Bloqueos de agenda o feriados/permisos del profesional.
    """
    id = models.AutoField(primary_key=True)
    profesional = models.ForeignKey(
        Profesional,
        on_delete=models.CASCADE,
        related_name='bloqueos_horario'
    )
    fechaHoraInicio = models.DateTimeField()
    fechaHoraFin = models.DateTimeField()
    motivo = models.CharField(max_length=255, blank=True, null=True)
    estado = models.CharField(max_length=50, default='Activo')

    class Meta:
        app_label = 'clinica'
        db_table = 'bloqueo_horario'

    def __str__(self):
        return f"Bloqueo {self.profesional} ({self.fechaHoraInicio.strftime('%d/%m/%Y %H:%M')})"


class Cita(models.Model):
    """
    Evento de agendamiento entre un paciente y un profesional.
    """
    id = models.AutoField(primary_key=True)
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE, related_name='citas')
    profesional = models.ForeignKey(Profesional, on_delete=models.CASCADE, related_name='citas')
    fechaHoraInicio = models.DateTimeField()
    fechaHoraFin = models.DateTimeField()
    estado = models.CharField(max_length=50, default='Agendada')  # Agendada, Confirmada, Realizada, Cancelada

    class Meta:
        app_label = 'clinica'
        db_table = 'cita'

    def __str__(self):
        return f"Cita #{self.id}: {self.paciente} con {self.profesional} ({self.fechaHoraInicio.strftime('%d/%m/%Y %H:%M')})"


class Videoconsulta(models.Model):
    """
    Sesión de telemedicina WebRTC asociada a una cita médica.
    """
    id = models.AutoField(primary_key=True)
    cita = models.OneToOneField(Cita, on_delete=models.CASCADE, related_name='videoconsulta')
    urlSalaWebRTC = models.CharField(max_length=255)
    estadoConexion = models.CharField(max_length=50, default='Pendiente')  # Pendiente, En curso, Finalizada

    class Meta:
        app_label = 'clinica'
        db_table = 'videoconsulta'

    def __str__(self):
        return f"Videoconsulta #{self.id} - Cita #{self.cita.id}"


class Pago(models.Model):
    """
    Registro del pago o copago asociado a una consulta médica.
    """
    id = models.AutoField(primary_key=True)
    cita = models.ForeignKey(Cita, on_delete=models.CASCADE, related_name='pagos')
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    prevision = models.CharField(max_length=50, default='Particular')  # Particular, Fonasa, Isapre
    metodoPago = models.CharField(max_length=50, default='Transferencia')  # Efectivo, Débito, Crédito, Transferencia, Bono Fonasa
    estado = models.CharField(max_length=50, default='Pendiente')  # Pendiente, Pagado, Anulado
    numeroComprobante = models.CharField(max_length=50, blank=True, null=True)
    observaciones = models.CharField(max_length=255, blank=True, null=True)
    registradoPor = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pagos_registrados'
    )
    fechaPago = models.DateTimeField(default=timezone.now, blank=True)

    class Meta:
        app_label = 'clinica'
        db_table = 'pago'

    def __str__(self):
        return f"Pago #{self.id} - Cita #{self.cita.id} (${self.monto} - {self.estado})"


class FichaClinica(models.Model):
    """
    Expediente médico general y único del paciente en Centro Nodo.
    Relación 1 a 1 con Paciente. Los campos clínicos se almacenan cifrados en reposo.
    """
    id = models.AutoField(primary_key=True)
    paciente = models.OneToOneField(Paciente, on_delete=models.CASCADE, related_name='ficha_clinica')
    fechaCreacion = models.DateTimeField(default=timezone.now)
    antecedentesMedicos = EncryptedTextField(blank=True, null=True)
    alergias = EncryptedTextField(blank=True, null=True)
    grupoSanguineo = models.CharField(max_length=10, blank=True, null=True)

    class Meta:
        app_label = 'clinica'
        db_table = 'ficha_clinica'

    def __str__(self):
        return f"Ficha Clínica #{self.id} - {self.paciente}"


class AtencionClinica(models.Model):
    """
    TABLA INTERMEDIA entre Ficha Clínica y Cita.
    Representa el acto médico / evolución clínica de cada consulta realizada.
    Sus campos clínicos sensibles se almacenan cifrados mediante Fernet.
    """
    id = models.AutoField(primary_key=True)
    fichaClinica = models.ForeignKey(FichaClinica, on_delete=models.CASCADE, related_name='atenciones')
    cita = models.OneToOneField(Cita, on_delete=models.SET_NULL, null=True, blank=True, related_name='atencion_clinica')
    profesional = models.ForeignKey(Profesional, on_delete=models.CASCADE, related_name='atenciones_realizadas')
    fechaHora = models.DateTimeField(default=timezone.now)
    motivoConsulta = EncryptedTextField()
    diagnostico = EncryptedTextField()
    evolucionNotas = EncryptedTextField(blank=True, null=True)
    indicacionesTratamiento = EncryptedTextField(blank=True, null=True)


    class Meta:
        app_label = 'clinica'
        db_table = 'atencion_clinica'

    def __str__(self):
        return f"Atención #{self.id} - Ficha #{self.fichaClinica.id} ({self.profesional.nombres})"


class NotificacionCita(models.Model):
    """
    Registro de correos electrónicos y recordatorios enviados asociados a una cita médica.
    """
    id = models.AutoField(primary_key=True)
    cita = models.ForeignKey(Cita, on_delete=models.CASCADE, related_name='notificaciones')
    tipo = models.CharField(max_length=50)  # Agendamiento, Confirmación, Cancelación, Recordatorio, Actualización
    destinatario = models.EmailField()
    asunto = models.CharField(max_length=255)
    enviadoEn = models.DateTimeField(default=timezone.now)
    exitoso = models.BooleanField(default=True)
    detalleError = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        app_label = 'clinica'
        db_table = 'notificacion_cita'

    def __str__(self):
        return f"Notificación {self.tipo} - Cita #{self.cita.id} ({self.destinatario})"


class AuditLog(models.Model):
    """
    Bitácora inmutable de auditoría clínica y seguridad para trazabilidad de accesos
    a fichas cifradas, emisión de documentos y operaciones críticas (Ley N° 20.584).
    """
    id = models.AutoField(primary_key=True)
    fechaHora = models.DateTimeField(default=timezone.now, db_index=True)
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registros_auditoria'
    )
    usuarioUsername = models.CharField(max_length=150, blank=True, default='anonimo')
    rolUsuario = models.CharField(max_length=100, blank=True, default='Anónimo')
    accion = models.CharField(max_length=60, db_index=True)
    modulo = models.CharField(max_length=50, db_index=True)
    entidad = models.CharField(max_length=60, blank=True, default='')
    entidadId = models.CharField(max_length=64, blank=True, default='', db_index=True)
    descripcion = models.CharField(max_length=255)
    resultado = models.CharField(max_length=20, default='OK', db_index=True)  # OK, DENEGADO, FALLIDO
    ipOrigen = models.GenericIPAddressField(null=True, blank=True)
    userAgent = models.CharField(max_length=255, blank=True, default='')
    datosExtra = models.JSONField(default=dict, blank=True)

    class Meta:
        app_label = 'clinica'
        db_table = 'audit_log'
        ordering = ['-fechaHora', '-id']
        verbose_name = 'Registro de Auditoría Clínica'
        verbose_name_plural = 'Bitácora de Auditoría Clínica'

    def __str__(self):
        return f"[{self.fechaHora:%d/%m/%Y %H:%M}] {self.usuarioUsername} -> {self.accion} ({self.resultado})"

