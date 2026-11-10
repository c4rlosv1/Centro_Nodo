from django.db import models
from .crypto import ENC_PREFIX, encrypt_text, decrypt_text


class EncryptedTextField(models.TextField):
    """
    Campo de texto de Django con cifrado simétrico automático en reposo.
    Almacena en BD el token cifrado ('enc::...') y expone texto plano en Python.
    """
    description = "TextField cifrado en reposo mediante cryptography.fernet"

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return decrypt_text(value)

    def to_python(self, value):
        if value is None:
            return value
        if isinstance(value, str) and value.startswith(ENC_PREFIX):
            return decrypt_text(value)
        return value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        return encrypt_text(str(value))

