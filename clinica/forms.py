from django import forms
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm


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

