import ipaddress
import logging
from django.conf import settings
from .models import AuditLog

logger = logging.getLogger(__name__)

MODULOS_AUDITORIA = (
    'Autenticación',
    'Pacientes',
    'Fichas Clínicas',
    'Agendamiento',
    'Telemedicina',
    'Caja y Pagos',
    'Seguridad',
)

RESULTADOS_AUDITORIA = ('OK', 'DENEGADO', 'FALLIDO')


def obtener_ip_cliente(request):
    """
    Extrae y valida la dirección IP de origen sin confiar por defecto en cabeceras
    falsificables como X-Forwarded-For, salvo que TRUST_X_FORWARDED_FOR esté habilitado.
    """
    if request is None:
        return None

    candidatos = []
    if getattr(settings, 'TRUST_X_FORWARDED_FOR', False):
        xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if xff:
            candidatos.extend([parte.strip() for parte in xff.split(',') if parte.strip()])

    remote_addr = (request.META.get('REMOTE_ADDR') or '').strip()
    if remote_addr:
        candidatos.append(remote_addr)

    for raw_ip in candidatos:
        try:
            return str(ipaddress.ip_address(raw_ip))
        except ValueError:
            continue
    return None


def registrar_auditoria(
    request=None,
    *,
    usuario=None,
    username_fallback='',
    accion,
    modulo,
    entidad='',
    entidad_id='',
    descripcion,
    resultado='OK',
    datos_extra=None,
):
    """
    Registra un evento en la Bitácora de Auditoría Clínica (AuditLog).
    Captura instantánea de usuario, rol, IP de origen y User-Agent para preservar
    trazabilidad histórica incluso si el usuario cambia de rol o es desactivado.
    """
    try:
        user_obj = usuario
        if user_obj is None and request is not None:
            req_user = getattr(request, 'user', None)
            if req_user is not None and getattr(req_user, 'is_authenticated', False):
                user_obj = req_user

        if user_obj is not None and getattr(user_obj, 'is_authenticated', True):
            usuario_fk = user_obj if getattr(user_obj, 'pk', None) else None
            username_snap = (getattr(user_obj, 'username', '') or username_fallback or 'usuario')[:150]
            rol_rel = getattr(user_obj, 'rol', None)
            if rol_rel:
                rol_snap = rol_rel.nombre[:100]
            elif getattr(user_obj, 'is_superuser', False):
                rol_snap = 'Superusuario'
            else:
                rol_snap = 'Sin Rol'
        else:
            usuario_fk = None
            username_snap = (username_fallback or 'anonimo')[:150]
            rol_snap = 'Anónimo'

        ua = ''
        if request is not None:
            ua = (request.META.get('HTTP_USER_AGENT') or '')[:255]

        res_norm = resultado if resultado in RESULTADOS_AUDITORIA else 'OK'

        return AuditLog.objects.create(
            usuario=usuario_fk,
            usuarioUsername=username_snap,
            rolUsuario=rol_snap,
            accion=str(accion)[:60],
            modulo=str(modulo)[:50],
            entidad=str(entidad or '')[:60],
            entidadId=str(entidad_id or '')[:64],
            descripcion=str(descripcion or '')[:255],
            resultado=res_norm,
            ipOrigen=obtener_ip_cliente(request),
            userAgent=ua,
            datosExtra=datos_extra if isinstance(datos_extra, dict) else {},
        )
    except Exception:
        # Nunca debe interrumpir un flujo crítico de atención si falla la metadata secundaria
        logger.exception("Error inesperado al registrar evento de auditoría: %s", accion)
        return None

