from decimal import Decimal, InvalidOperation
from django import template

register = template.Library()


@register.filter
def clp(value):
    """
    Formatea un monto numérico como peso chileno (CLP), por ejemplo: 35000 -> '$35.000'.
    """
    if value is None or value == '':
        return '$0'
    try:
        numero = int(Decimal(str(value)).quantize(Decimal('1')))
    except (InvalidOperation, ValueError, TypeError):
        return '$0'
    signo = '-' if numero < 0 else ''
    formateado = f"{abs(numero):,}".replace(',', '.')
    return f"{signo}${formateado}"

