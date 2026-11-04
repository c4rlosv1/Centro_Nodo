from functools import wraps
from django.contrib import messages
from django.shortcuts import redirect
from django.core.exceptions import PermissionDenied


def rol_requerido(roles_permitidos):
    """
    Decorador para restringir el acceso a vistas según el rol asignado al usuario.
    Si el usuario es superusuario, siempre tiene acceso.
    Si no tiene el rol permitido, muestra un mensaje de advertencia y redirige al dashboard.
    """
    if isinstance(roles_permitidos, str):
        roles_permitidos = [roles_permitidos]

    # Normalizar roles a minúsculas para comparaciones seguras
    roles_permitidos_normalizados = [r.lower() for r in roles_permitidos]

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')

            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)

            rol_actual = request.user.rol.nombre.lower() if request.user.rol else ''

            if rol_actual in roles_permitidos_normalizados:
                return view_func(request, *args, **kwargs)

            messages.warning(
                request,
                f"No tienes los permisos necesarios ({', '.join(roles_permitidos)}) para acceder a esta sección."
            )
            return redirect('dashboard')

        return _wrapped_view
    return decorator

