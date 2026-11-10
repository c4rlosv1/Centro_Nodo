from datetime import datetime, timedelta
from django import forms
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.db.models import Q
from django.utils import timezone

from .models import (
    Usuario,
    Paciente,
    Profesional,
    Cita,
    BloqueoHorario,
    Pago,
    FichaClinica,
    AtencionClinica,
)
from .utils import validar_rut, formatear_rut, limpiar_rut


class LoginForm(forms.Form):
    """
    Formulario de inicio de sesión con soporte para Usuario o Correo Electrónico.
    """
    login_id = forms.CharField(
        label="Usuario o Correo Electrónico",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej. usuario o nombre@centronodo.cl',
            'autocomplete': 'username',
            'required': True,
            'autofocus': True,
        })
    )
    password = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '••••••••',
            'autocomplete': 'current-password',
            'required': True,
        })
    )
    remember_me = forms.BooleanField(
        required=False,
        initial=True,
        label="Mantener sesión iniciada",
        widget=forms.CheckboxInput(attrs={'class': 'form-checkbox'})
    )


class CustomPasswordResetForm(PasswordResetForm):
    """
    Formulario adaptado para solicitar restablecimiento de contraseña.
    """
    email = forms.EmailField(
        label="Correo Electrónico Registrado",
        max_length=254,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'tu-correo@centronodo.cl',
            'autocomplete': 'email',
            'required': True,
            'autofocus': True,
        })
    )


class CustomSetPasswordForm(SetPasswordForm):
    """
    Formulario para establecer la nueva contraseña tras el enlace con token.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.update({'class': 'form-control'})


# ==============================================================================
# Formularios Clínicos: Pacientes, Fichas y Atenciones
# ==============================================================================

class PacienteForm(forms.ModelForm):
    """
    Formulario para crear y editar pacientes con validación matemática de RUT chileno
    y creación opcional de cuenta de acceso web.
    """
    crear_cuenta_web = forms.BooleanField(
        required=False,
        initial=False,
        label="Crear cuenta de acceso al portal web para este paciente",
        widget=forms.CheckboxInput(attrs={'class': 'form-checkbox', 'id': 'id_crear_cuenta_web'})
    )
    email_cuenta = forms.EmailField(
        required=False,
        label="Correo Electrónico de Acceso",
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'paciente@correo.cl'
        })
    )
    password_inicial = forms.CharField(
        required=False,
        label="Contraseña Inicial",
        min_length=6,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Mínimo 6 caracteres'
        })
    )

    class Meta:
        model = Paciente
        fields = ['rut', 'nombres', 'apellidos', 'telefono']
        labels = {
            'rut': 'RUT',
            'nombres': 'Nombres',
            'apellidos': 'Apellidos',
            'telefono': 'Teléfono de Contacto',
        }
        widgets = {
            'rut': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. 19.876.543-0'}),
            'nombres': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. María José'}),
            'apellidos': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. González Pérez'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. +56 9 1234 5678'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Si es edición y ya tiene usuario o simplemente editando datos del paciente,
        # ocultar campos de creación de cuenta si ya existe usuario.
        if self.instance and self.instance.pk and self.instance.usuario_id:
            self.fields.pop('crear_cuenta_web', None)
            self.fields.pop('email_cuenta', None)
            self.fields.pop('password_inicial', None)

    def clean_rut(self):
        rut_raw = self.cleaned_data.get('rut', '').strip()
        if not validar_rut(rut_raw):
            raise forms.ValidationError(
                "El RUT ingresado no es válido. Verifique los dígitos y el dígito verificador."
            )

        rut_formateado = formatear_rut(rut_raw)
        rut_limpio = limpiar_rut(rut_raw)

        # Verificar unicidad tanto formateado como sin puntos
        qs = Paciente.objects.all()
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)

        for existente in qs.only('id', 'rut'):
            if limpiar_rut(existente.rut) == rut_limpio:
                raise forms.ValidationError(f"Ya existe un paciente registrado con el RUT {rut_formateado}.")

        return rut_formateado

    def clean(self):
        cleaned_data = super().clean()
        crear_cuenta = cleaned_data.get('crear_cuenta_web')
        email = (cleaned_data.get('email_cuenta') or '').strip()
        password = cleaned_data.get('password_inicial')

        if crear_cuenta:
            if not email:
                self.add_error('email_cuenta', "Debe ingresar un correo electrónico para la cuenta web.")
            elif Usuario.objects.filter(email__iexact=email).exists():
                self.add_error('email_cuenta', "Este correo ya está registrado en otra cuenta de usuario.")

            if not password:
                self.add_error('password_inicial', "Debe asignar una contraseña inicial para el paciente.")

        return cleaned_data


class FichaClinicaForm(forms.ModelForm):
    """
    Formulario para actualizar los antecedentes generales del expediente clínico del paciente.
    """
    GRUPOS_SANGUINEOS = [
        ('', 'No informado'),
        ('O+', 'O+'),
        ('O-', 'O-'),
        ('A+', 'A+'),
        ('A-', 'A-'),
        ('B+', 'B+'),
        ('B-', 'B-'),
        ('AB+', 'AB+'),
        ('AB-', 'AB-'),
    ]

    grupoSanguineo = forms.ChoiceField(
        choices=GRUPOS_SANGUINEOS,
        required=False,
        label="Grupo Sanguíneo",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = FichaClinica
        fields = ['grupoSanguineo', 'alergias', 'antecedentesMedicos']
        labels = {
            'alergias': 'Alergias Conocidas',
            'antecedentesMedicos': 'Antecedentes Médicos y Psicológicos Generales',
        }
        widgets = {
            'alergias': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Ej. Penicilina, látex o "Ninguna conocida"'
            }),
            'antecedentesMedicos': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Historial médico relevante, diagnósticos previos, medicación crónica...'
            }),
        }


class AtencionClinicaForm(forms.ModelForm):
    """
    Formulario para registrar una nueva evolución/atención clínica en la tabla intermedia
    que vincula FichaClinica, Cita y Profesional.
    """
    class Meta:
        model = AtencionClinica
        fields = [
            'cita',
            'profesional',
            'motivoConsulta',
            'diagnostico',
            'evolucionNotas',
            'indicacionesTratamiento',
        ]
        labels = {
            'cita': 'Cita Asociada (Opcional)',
            'profesional': 'Profesional Tratante',
            'motivoConsulta': 'Motivo de Consulta',
            'diagnostico': 'Diagnóstico / Impresión Clínica',
            'evolucionNotas': 'Notas de Evolución (Confidencial - Uso Clínico)',
            'indicacionesTratamiento': 'Indicaciones / Tratamiento para el Paciente',
        }
        widgets = {
            'cita': forms.Select(attrs={'class': 'form-control'}),
            'profesional': forms.Select(attrs={'class': 'form-control'}),
            'motivoConsulta': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Motivo principal por el cual consulta el paciente en esta sesión...'
            }),
            'diagnostico': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Evaluación clínica, código CIE-10 / DSM-5 o hipótesis diagnóstica...'
            }),
            'evolucionNotas': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Observaciones terapéuticas, progreso y notas reservadas de la sesión...'
            }),
            'indicacionesTratamiento': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Indicaciones terapéuticas, pautas, derivaciones o fármacos...'
            }),
        }

    def __init__(self, *args, paciente=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cita'].required = False

        if paciente is not None:
            # Mostrar citas de este paciente sin atención asociada (o la cita actual si se está editando)
            filtro_cita = Q(atencion_clinica__isnull=True)
            if self.instance and self.instance.pk and self.instance.cita_id:
                filtro_cita |= Q(pk=self.instance.cita_id)
            self.fields['cita'].queryset = Cita.objects.filter(
                filtro_cita,
                paciente=paciente,
            ).exclude(estado='Cancelada').order_by('-fechaHoraInicio')
            self.fields['cita'].empty_label = "Atención espontánea (sin cita vinculada)"

        # Si el usuario logueado es Profesional y tiene perfil, fijar profesional automáticamente
        if user is not None and hasattr(user, 'profesional'):
            self.fields['profesional'].queryset = Profesional.objects.filter(pk=user.profesional.pk)
            self.fields['profesional'].initial = user.profesional


# ==============================================================================
# Formularios de Agendamiento Real (Cita y BloqueoHorario)
# ==============================================================================

class CitaForm(forms.Form):
    """
    Formulario de agendamiento de citas con validación anti-colisiones
    contra citas existentes y bloqueos horarios.
    """
    DURACIONES = [
        (30, '30 minutos'),
        (45, '45 minutos (Sesión estándar)'),
        (60, '60 minutos (1 hora)'),
        (90, '90 minutos (Evaluación extendida)'),
    ]

    paciente = forms.ModelChoiceField(
        queryset=Paciente.objects.all().order_by('apellidos', 'nombres'),
        label="Paciente",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    profesional = forms.ModelChoiceField(
        queryset=Profesional.objects.all().order_by('apellidos', 'nombres'),
        label="Especialista / Profesional",
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_cita_profesional'})
    )
    fecha = forms.DateField(
        label="Fecha de la Cita",
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
            'id': 'id_cita_fecha'
        })
    )
    hora_inicio = forms.TimeField(
        label="Hora de Inicio",
        widget=forms.TimeInput(attrs={
            'class': 'form-control',
            'type': 'time',
            'id': 'id_cita_hora_inicio'
        })
    )
    duracion_minutos = forms.TypedChoiceField(
        choices=DURACIONES,
        coerce=int,
        initial=45,
        label="Duración",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    es_telemedicina = forms.BooleanField(
        required=False,
        initial=False,
        label="Modalidad Telemedicina (Generar sala de videoconsulta WebRTC)",
        widget=forms.CheckboxInput(attrs={'class': 'form-checkbox'})
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Configurar fecha mínima en HTML5 como hoy
        hoy_str = timezone.localdate().strftime('%Y-%m-%d')
        self.fields['fecha'].widget.attrs['min'] = hoy_str

        if user is not None:
            if user.es_paciente and hasattr(user, 'paciente'):
                self.fields['paciente'].queryset = Paciente.objects.filter(pk=user.paciente.pk)
                self.fields['paciente'].initial = user.paciente
            elif user.es_profesional and hasattr(user, 'profesional'):
                self.fields['profesional'].initial = user.profesional

    def clean(self):
        cleaned_data = super().clean()
        paciente = cleaned_data.get('paciente')
        profesional = cleaned_data.get('profesional')
        fecha = cleaned_data.get('fecha')
        hora_inicio = cleaned_data.get('hora_inicio')
        duracion = cleaned_data.get('duracion_minutos')

        if not (paciente and profesional and fecha and hora_inicio and duracion):
            return cleaned_data

        tz = timezone.get_current_timezone()
        inicio_naive = datetime.combine(fecha, hora_inicio)
        inicio = timezone.make_aware(inicio_naive, tz)
        fin = inicio + timedelta(minutes=duracion)

        if inicio < timezone.now():
            raise forms.ValidationError(
                "No es posible agendar citas en una fecha u hora que ya pasó."
            )

        # 1. Verificar colisión con otras citas del mismo profesional
        colision_profesional = Cita.objects.filter(
            profesional=profesional,
            fechaHoraInicio__lt=fin,
            fechaHoraFin__gt=inicio
        ).exclude(estado='Cancelada').first()

        if colision_profesional:
            h_ini = timezone.localtime(colision_profesional.fechaHoraInicio).strftime('%H:%M')
            h_fin = timezone.localtime(colision_profesional.fechaHoraFin).strftime('%H:%M')
            raise forms.ValidationError(
                f"Conflicto de horario: {profesional.nombres} {profesional.apellidos} ya tiene una cita "
                f"agendada entre las {h_ini} y las {h_fin}."
            )

        # 2. Verificar colisión con BloqueoHorario del profesional
        colision_bloqueo = BloqueoHorario.objects.filter(
            profesional=profesional,
            estado='Activo',
            fechaHoraInicio__lt=fin,
            fechaHoraFin__gt=inicio
        ).first()

        if colision_bloqueo:
            b_ini = timezone.localtime(colision_bloqueo.fechaHoraInicio).strftime('%d/%m %H:%M')
            b_fin = timezone.localtime(colision_bloqueo.fechaHoraFin).strftime('%H:%M')
            motivo = f" ({colision_bloqueo.motivo})" if colision_bloqueo.motivo else ""
            raise forms.ValidationError(
                f"Horario bloqueado: El especialista registró un bloqueo desde {b_ini} hasta {b_fin}{motivo}."
            )

        # 3. Verificar colisión con otra cita del mismo paciente
        colision_paciente = Cita.objects.filter(
            paciente=paciente,
            fechaHoraInicio__lt=fin,
            fechaHoraFin__gt=inicio
        ).exclude(estado='Cancelada').first()

        if colision_paciente:
            h_ini = timezone.localtime(colision_paciente.fechaHoraInicio).strftime('%H:%M')
            h_fin = timezone.localtime(colision_paciente.fechaHoraFin).strftime('%H:%M')
            raise forms.ValidationError(
                f"El paciente {paciente.nombres} {paciente.apellidos} ya tiene otra cita agendada "
                f"entre las {h_ini} y las {h_fin}."
            )

        cleaned_data['fechaHoraInicio'] = inicio
        cleaned_data['fechaHoraFin'] = fin
        return cleaned_data


class BloqueoHorarioForm(forms.Form):
    """
    Formulario para registrar bloqueos de disponibilidad en la agenda de un especialista.
    """
    profesional = forms.ModelChoiceField(
        queryset=Profesional.objects.all().order_by('apellidos', 'nombres'),
        label="Especialista",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    fecha = forms.DateField(
        label="Fecha del Bloqueo",
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    hora_inicio = forms.TimeField(
        label="Hora Inicio",
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'})
    )
    hora_fin = forms.TimeField(
        label="Hora Fin",
        widget=forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'})
    )
    motivo = forms.CharField(
        required=False,
        max_length=255,
        label="Motivo del Bloqueo",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej. Capacitación, Colación, Reunión clínica, Licencia...'
        })
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        hoy_str = timezone.localdate().strftime('%Y-%m-%d')
        self.fields['fecha'].widget.attrs['min'] = hoy_str

        if user is not None and user.es_profesional and hasattr(user, 'profesional'):
            self.fields['profesional'].queryset = Profesional.objects.filter(pk=user.profesional.pk)
            self.fields['profesional'].initial = user.profesional

    def clean(self):
        cleaned_data = super().clean()
        profesional = cleaned_data.get('profesional')
        fecha = cleaned_data.get('fecha')
        hora_inicio = cleaned_data.get('hora_inicio')
        hora_fin = cleaned_data.get('hora_fin')

        if not (profesional and fecha and hora_inicio and hora_fin):
            return cleaned_data

        if hora_fin <= hora_inicio:
            raise forms.ValidationError("La hora de término debe ser posterior a la hora de inicio.")

        tz = timezone.get_current_timezone()
        inicio = timezone.make_aware(datetime.combine(fecha, hora_inicio), tz)
        fin = timezone.make_aware(datetime.combine(fecha, hora_fin), tz)

        # Validar que no existan citas activas en el tramo que se quiere bloquear
        citas_conflicto = Cita.objects.filter(
            profesional=profesional,
            fechaHoraInicio__lt=fin,
            fechaHoraFin__gt=inicio
        ).exclude(estado='Cancelada')

        if citas_conflicto.exists():
            primera = citas_conflicto.first()
            h_ini = timezone.localtime(primera.fechaHoraInicio).strftime('%H:%M')
            h_fin = timezone.localtime(primera.fechaHoraFin).strftime('%H:%M')
            raise forms.ValidationError(
                f"No se puede bloquear este horario porque ya existe {citas_conflicto.count()} cita(s) activa(s) "
                f"(ej. {primera.paciente.nombres} {primera.paciente.apellidos} de {h_ini} a {h_fin}). "
                f"Cancele o reprograme la cita primero."
            )

        cleaned_data['fechaHoraInicio'] = inicio
        cleaned_data['fechaHoraFin'] = fin
        return cleaned_data


# ==============================================================================
# Formulario de Caja y Pagos
# ==============================================================================

class PagoForm(forms.ModelForm):
    """
    Formulario para registrar cobros y pagos por consulta médica.
    """
    PREVISIONES = [
        ('Particular', 'Particular'),
        ('Fonasa', 'Fonasa'),
        ('Isapre', 'Isapre'),
    ]
    METODOS_PAGO = [
        ('Transferencia', 'Transferencia Electrónica'),
        ('Débito', 'Tarjeta de Débito'),
        ('Crédito', 'Tarjeta de Crédito'),
        ('Efectivo', 'Efectivo'),
        ('Bono Fonasa', 'Bono Fonasa'),
    ]
    ESTADOS_PAGO = [
        ('Pagado', 'Pagado (Ingreso inmediato)'),
        ('Pendiente', 'Pendiente de pago'),
    ]

    prevision = forms.ChoiceField(
        choices=PREVISIONES,
        label="Previsión de Salud",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    metodoPago = forms.ChoiceField(
        choices=METODOS_PAGO,
        label="Medio de Pago",
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    estado = forms.ChoiceField(
        choices=ESTADOS_PAGO,
        label="Estado del Pago",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    class Meta:
        model = Pago
        fields = ['cita', 'monto', 'prevision', 'metodoPago', 'estado', 'numeroComprobante', 'observaciones']
        labels = {
            'cita': 'Cita Médica',
            'monto': 'Monto (CLP $)',
            'numeroComprobante': 'N° Comprobante / Boleta (Opcional)',
            'observaciones': 'Observaciones',
        }
        widgets = {
            'cita': forms.Select(attrs={'class': 'form-control'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '500', 'placeholder': 'Ej. 35000'}),
            'numeroComprobante': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Se autogenera si se deja vacío'}),
            'observaciones': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej. Bono electrónico o detalle adicional'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cita'].queryset = Cita.objects.select_related('paciente', 'profesional').exclude(
            estado='Cancelada'
        ).order_by('-fechaHoraInicio')

    def clean_monto(self):
        monto = self.cleaned_data.get('monto')
        if monto is None or monto <= 0:
            raise forms.ValidationError("El monto del pago debe ser mayor a $0.")
        return monto

