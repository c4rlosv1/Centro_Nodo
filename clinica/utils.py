import re
from django.core.exceptions import ValidationError


def limpiar_rut(rut: str) -> str:
    """
    Elimina puntos, espacios y guiones de un RUT, retornando cuerpo + DV en mayúsculas.
    Ejemplo: '19.876.543-k' -> '19876543K'
    """
    if not rut:
        return ''
    return re.sub(r'[^0-9kK]', '', str(rut)).upper()


def calcular_dv(cuerpo: str) -> str:
    """
    Calcula el dígito verificador de un RUT chileno mediante algoritmo Módulo 11.
    """
    suma = 0
    multiplicador = 2
    for digito in reversed(cuerpo):
        suma += int(digito) * multiplicador
        multiplicador = 2 if multiplicador == 7 else multiplicador + 1

    resto = suma % 11
    resultado = 11 - resto

    if resultado == 11:
        return '0'
    if resultado == 10:
        return 'K'
    return str(resultado)


def validar_rut(rut: str) -> bool:
    """
    Retorna True si el RUT chileno es estructural y matemáticamente válido.
    """
    rut_limpio = limpiar_rut(rut)
    if len(rut_limpio) < 2:
        return False

    cuerpo = rut_limpio[:-1]
    dv = rut_limpio[-1]

    if not cuerpo.isdigit() or int(cuerpo) == 0:
        return False

    # Rechazar secuencias repetitivas obvias (ej. 11111111-1)
    if len(set(cuerpo)) == 1 and len(cuerpo) >= 7:
        return False

    return calcular_dv(cuerpo) == dv


def formatear_rut(rut: str) -> str:
    """
    Formatea un RUT chileno al estándar XX.XXX.XXX-X.
    Ejemplo: '198765430' -> '19.876.543-0'
    """
    rut_limpio = limpiar_rut(rut)
    if len(rut_limpio) < 2:
        return rut

    cuerpo = rut_limpio[:-1]
    dv = rut_limpio[-1]

    # Insertar puntos cada 3 dígitos desde la derecha
    cuerpo_formateado = f"{int(cuerpo):,}".replace(',', '.')
    return f"{cuerpo_formateado}-{dv}"


def validar_rut_django(value: str):
    """
    Validador compatible con formularios y modelos de Django.
    """
    if not validar_rut(value):
        raise ValidationError(
            "El RUT ingresado no es válido. Verifique el número y su dígito verificador (ej. 19.876.543-0)."
        )

