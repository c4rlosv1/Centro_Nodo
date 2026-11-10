import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

ENC_PREFIX = "enc::"


def _get_fernet() -> Fernet:
    """
    Obtiene la instancia Fernet usando CLINICAL_ENCRYPTION_KEY si está definida
    en settings/.env, o derivando una clave de 32 bytes desde SECRET_KEY.
    """
    raw_key = getattr(settings, 'CLINICAL_ENCRYPTION_KEY', None) or settings.SECRET_KEY
    digest = hashlib.sha256(str(raw_key).encode('utf-8')).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


def encrypt_text(value: str) -> str:
    """
    Cifra un texto en claro usando Fernet (AES-128-CBC + HMAC-SHA256)
    y antepone el prefijo 'enc::' para evitar doble cifrado.
    """
    if value is None or value == "":
        return value
    text = str(value)
    if text.startswith(ENC_PREFIX):
        return text
    token = _get_fernet().encrypt(text.encode('utf-8')).decode('utf-8')
    return f"{ENC_PREFIX}{token}"


def decrypt_text(value: str) -> str:
    """
    Descifra un valor con prefijo 'enc::'. Si es texto plano legado
    (sin prefijo), lo retorna intacto para mantener compatibilidad.
    """
    if value is None or value == "":
        return value
    text = str(value)
    if not text.startswith(ENC_PREFIX):
        return text
    token = text[len(ENC_PREFIX):]
    try:
        return _get_fernet().decrypt(token.encode('utf-8')).decode('utf-8')
    except InvalidToken:
        return "[Contenido clínico cifrado: clave de descifrado no válida]"

