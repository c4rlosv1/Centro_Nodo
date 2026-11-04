from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme
from django.conf import settings

from .forms import LoginForm
from .decorators import rol_requerido


def login_view(request):
    """
    Gestiona el inicio de sesión del personal y pacientes de Centro Nodo.
    Permite autenticarse mediante Nombre de Usuario o Correo Electrónico.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    next_url = request.GET.get('next') or request.POST.get('next') or 'dashboard'

    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            login_id = form.cleaned_data['login_id'].strip()
            password = form.cleaned_data['password']
            remember_me = form.cleaned_data.get('remember_me', True)

            user = authenticate(request, username=login_id, password=password)

            if user is not None:
                if not user.is_active:
                    messages.error(request, "Esta cuenta de usuario se encuentra inactiva. Contacte a soporte o administración.")
                    return render(request, 'login.html', {'form': form, 'next': next_url})

                login(request, user)

                # Control de duración de la sesión según 'remember_me'
                if not remember_me:
                    request.session.set_expiry(0)  # Expira al cerrar el navegador
                else:
                    request.session.set_expiry(1209600)  # 2 semanas por defecto

                nombre_saludo = user.get_full_name() or user.username
                rol_info = f" ({user.rol.nombre})" if user.rol else ""
                messages.success(request, f"¡Bienvenido/a {nombre_saludo}{rol_info} al Centro Nodo!")

                # Redirección segura
                if next_url and url_has_allowed_host_and_scheme(
                    url=next_url,
                    allowed_hosts={request.get_host()},
                    require_https=request.is_secure()
                ):
                    return redirect(next_url)
                return redirect('dashboard')
            else:
                messages.error(request, "Credenciales incorrectas. Verifique su usuario/correo y contraseña.")
    else:
        form = LoginForm()

    return render(request, 'login.html', {
        'form': form,
        'next': next_url,
    })


def logout_view(request):
    """
    Cierra la sesión activa del usuario y redirige al login con mensaje explicativo.
    """
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, "Has cerrado tu sesión de forma segura.")
    return redirect('login')


@login_required
def dashboard_view(request):
    """
    Panel principal de la plataforma, accesible para usuarios autenticados.
    """
    return render(request, 'dashboard.html', {
        'usuario': request.user,
    })


@login_required
def agendamiento_view(request):
    """
    Módulo de gestión y agendamiento de citas médicas.
    """
    return render(request, 'agendamiento.html')


@login_required
@rol_requerido(['Profesional', 'Administrador', 'Paciente'])
def telemedicina_view(request):
    """
    Módulo de atención remota por videoconsulta WebRTC.
    """
    return render(request, 'telemedicina.html')
