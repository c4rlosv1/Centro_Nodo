from django.db import models
from django.contrib.auth.models import AbstractUser


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
    rol = models.ForeignKey(Rol, on_delete=models.SET_NULL, null=True, blank=True)
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
        return self.username


class Paciente(models.Model):
    id = models.AutoField(primary_key=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='pacientes')
    rut = models.CharField(max_length=20, unique=True)
    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)

    class Meta:
        app_label = 'clinica'
        db_table = 'paciente'

    def __str__(self):
        return f"{self.apellidos}, {self.nombres}"


class Profesional(models.Model):
    id = models.AutoField(primary_key=True)
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='profesionales')
    rut = models.CharField(max_length=20, unique=True)
    nombres = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    especialidad = models.CharField(max_length=100)

    class Meta:
        app_label = 'clinica'
        db_table = 'profesional'

    def __str__(self):
        return f"{self.apellidos}, {self.nombres} - {self.especialidad}"


class Cita(models.Model):
    id = models.AutoField(primary_key=True)
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE)
    profesional = models.ForeignKey(Profesional, on_delete=models.CASCADE)
    fechaHoraInicio = models.DateTimeField()
    fechaHoraFin = models.DateTimeField()
    estado = models.CharField(max_length=50)

    class Meta:
        app_label = 'clinica'
        db_table = 'cita'

    def __str__(self):
        return f"Cita {self.id} - {self.paciente}"


class Videoconsulta(models.Model):
    id = models.AutoField(primary_key=True)
    cita = models.ForeignKey(Cita, on_delete=models.CASCADE)
    urlSalaWebRTC = models.CharField(max_length=255)
    estadoConexion = models.CharField(max_length=50)

    class Meta:
        app_label = 'clinica'
        db_table = 'videoconsulta'

    def __str__(self):
        return f"Videoconsulta {self.id} - Cita {self.cita.id}"


class Pago(models.Model):
    id = models.AutoField(primary_key=True)
    cita = models.ForeignKey(Cita, on_delete=models.CASCADE)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(max_length=50)

    class Meta:
        app_label = 'clinica'
        db_table = 'pago'

    def __str__(self):
        return f"Pago {self.id} - ${self.monto}"


class FichaClinica(models.Model):
    id = models.AutoField(primary_key=True)
    cita = models.ForeignKey(Cita, on_delete=models.CASCADE)
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE)
    profesional = models.ForeignKey(Profesional, on_delete=models.CASCADE)
    motivoConsulta = models.TextField()
    diagnostico = models.TextField()

    class Meta:
        app_label = 'clinica'
        db_table = 'ficha_clinica'

    def __str__(self):
        return f"Ficha {self.id} - {self.paciente}"
