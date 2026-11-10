import csv
import json
import uuid
from datetime import datetime, time
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q, Count, Sum
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import (
    Rol,
    Usuario,
    Paciente,
    Profesional,
    Cita,
    BloqueoHorario,
    Videoconsulta,
    Pago,
    FichaClinica,
    AtencionClinica,
    NotificacionCita,
)
from .forms import (
    LoginForm,
    PacienteForm,
    FichaClinicaForm,
    AtencionClinicaForm,
    CitaForm,
    BloqueoHorarioForm,
    PagoForm,
)
from .decorators import rol_requerido
from .notifications import enviar_notificacion_cita
from .utils import limpiar_rut, sanitizar_celda_csv, parse_positive_int

ESTADOS_CITA_VALIDOS = ('Agendada', 'Confirmada', 'En atención', 'Realizada', 'Cancelada')
ESTADOS_PAGO_VALIDOS = ('Pagado', 'Pendiente', 'Anulado')
METODOS_PAGO_VALIDOS = ('Transferencia', 'Débito', 'Crédito', 'Efectivo', 'Bono Fonasa')


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

                if not remember_me:
                    request.session.set_expiry(0)
                else:
                    request.session.set_expiry(1209600)

                nombre_saludo = user.get_full_name() or user.username
                rol_info = f" ({user.rol.nombre})" if user.rol else ""
                messages.success(request, f"¡Bienvenido/a {nombre_saludo}{rol_info} al Centro Nodo!")

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


@require_POST
def logout_view(request):
    """
    Cierra la sesión activa del usuario mediante POST (protegido contra CSRF)
    y redirige al login con mensaje explicativo.
    """
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, "Has cerrado tu sesión de forma segura.")
    return redirect('login')


@login_required
def dashboard_view(request):
    """
    Panel principal dinámico diferenciado por rol (Profesional, Paciente, Administrador/Recepcionista).
    """
    user = request.user
    ahora = timezone.now()
    hoy = timezone.localdate()
    tz = timezone.get_current_timezone()
    inicio_hoy = timezone.make_aware(datetime.combine(hoy, time.min), tz)
    fin_hoy = timezone.make_aware(datetime.combine(hoy, time.max), tz)
    inicio_mes = timezone.make_aware(datetime.combine(hoy.replace(day=1), time.min), tz)

    citas_base = Cita.objects.select_related(
        'paciente', 'paciente__ficha_clinica', 'profesional', 'videoconsulta', 'atencion_clinica'
    )
    if user.es_paciente:
        citas_base = citas_base.filter(paciente=user.paciente) if hasattr(user, 'paciente') else Cita.objects.none()
    elif user.es_profesional:
        citas_base = citas_base.filter(profesional=user.profesional) if hasattr(user, 'profesional') else Cita.objects.none()

    proximas_citas = citas_base.filter(
        fechaHoraInicio__gte=ahora
    ).exclude(estado='Cancelada').order_by('fechaHoraInicio')[:6]

    citas_hoy_lista = citas_base.filter(
        fechaHoraInicio__gte=inicio_hoy,
        fechaHoraInicio__lte=fin_hoy
    ).exclude(estado='Cancelada').order_by('fechaHoraInicio')

    context = {
        'usuario': user,
        'proximas_citas': proximas_citas,
        'citas_hoy_lista': citas_hoy_lista,
        'citas_hoy_count': citas_hoy_lista.count(),
    }

    if user.es_profesional:
        if hasattr(user, 'profesional'):
            prof = user.profesional
            context.update({
                'tipo_dashboard': 'profesional',
                'atenciones_realizadas_count': AtencionClinica.objects.filter(profesional=prof).count(),
                'citas_sin_evolucion': citas_base.filter(
                    atencion_clinica__isnull=True,
                    fechaHoraInicio__lte=ahora
                ).exclude(estado='Cancelada').order_by('-fechaHoraInicio')[:5],
                'videoconsultas_pendientes': Videoconsulta.objects.select_related(
                    'cita', 'cita__paciente'
                ).filter(
                    cita__profesional=prof
                ).exclude(cita__estado='Cancelada').exclude(estadoConexion='Finalizada').order_by('cita__fechaHoraInicio')[:4],
            })
        else:
            context.update({
                'tipo_dashboard': 'profesional',
                'atenciones_realizadas_count': 0,
                'citas_sin_evolucion': [],
                'videoconsultas_pendientes': [],
            })
    elif user.es_paciente:
        if hasattr(user, 'paciente'):
            pac = user.paciente
            ficha, _ = FichaClinica.objects.get_or_create(paciente=pac)
            context.update({
                'tipo_dashboard': 'paciente',
                'proxima_cita': proximas_citas[0] if proximas_citas else None,
                'ficha_paciente': ficha,
                'ultimas_indicaciones': ficha.atenciones.select_related('profesional').order_by('-fechaHora')[:3],
                'pagos_pendientes_count': Pago.objects.filter(cita__paciente=pac, estado='Pendiente').count(),
                'sesiones_realizadas_count': Cita.objects.filter(paciente=pac, estado='Realizada').count(),
            })
        else:
            context.update({
                'tipo_dashboard': 'paciente',
                'proxima_cita': None,
                'ficha_paciente': None,
                'ultimas_indicaciones': [],
                'pagos_pendientes_count': 0,
                'sesiones_realizadas_count': 0,
            })
    else:
        # Administrador / Recepcionista
        ingresos_hoy = Pago.objects.filter(
            estado='Pagado',
            fechaPago__gte=inicio_hoy,
            fechaPago__lte=fin_hoy
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0')

        ingresos_mes = Pago.objects.filter(
            estado='Pagado',
            fechaPago__gte=inicio_mes
        ).aggregate(total=Sum('monto'))['total'] or Decimal('0')

        citas_sin_pago_count = Cita.objects.exclude(estado='Cancelada').exclude(
            pagos__estado='Pagado'
        ).distinct().count()

        context.update({
            'tipo_dashboard': 'administracion',
            'total_pacientes': Paciente.objects.count(),
            'total_fichas': FichaClinica.objects.count() if user.es_administrador else None,
            'total_atenciones': AtencionClinica.objects.count() if user.es_administrador else None,
            'ingresos_hoy': ingresos_hoy,
            'ingresos_mes': ingresos_mes,
            'citas_sin_pago_count': citas_sin_pago_count,
        })

    return render(request, 'dashboard.html', context)


# ==============================================================================
# Módulo 1: Gestión de Pacientes
# ==============================================================================

@login_required
@rol_requerido(['Administrador', 'Profesional', 'Recepcionista'])
def pacientes_lista_view(request):
    """
    Listado y búsqueda de pacientes por RUT, nombre o apellido.
    """
    query = request.GET.get('q', '').strip()[:80]
    pacientes = Paciente.objects.select_related('usuario', 'ficha_clinica').annotate(
        total_citas=Count('citas')
    ).order_by('apellidos', 'nombres')

    if query:
        q_limpio = limpiar_rut(query)
        filtro = (
            Q(nombres__icontains=query) |
            Q(apellidos__icontains=query) |
            Q(rut__icontains=query)
        )
        if q_limpio:
            # Permite buscar "19876543" aunque en BD esté guardado "19.876.543-0"
            ids_rut = [
                p.id for p in Paciente.objects.only('id', 'rut')
                if q_limpio in limpiar_rut(p.rut)
            ]
            filtro |= Q(id__in=ids_rut)
        pacientes = pacientes.filter(filtro)

    return render(request, 'pacientes/lista.html', {
        'pacientes': pacientes,
        'query': query,
    })


@login_required
@rol_requerido(['Administrador', 'Profesional', 'Recepcionista'])
def paciente_crear_view(request):
    """
    Crea un nuevo paciente con validación de RUT chileno, crea automáticamente
    su Ficha Clínica única y opcionalmente genera su usuario de acceso web.
    """
    if request.method == 'POST':
        form = PacienteForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                paciente = form.save(commit=False)

                if form.cleaned_data.get('crear_cuenta_web'):
                    email = form.cleaned_data['email_cuenta'].strip()
                    password = form.cleaned_data['password_inicial']
                    rol_paciente, _ = Rol.objects.get_or_create(
                        nombre='Paciente',
                        defaults={'descripcion': 'Pacientes con acceso a sus citas, videoconsultas y fichas'}
                    )

                    base_username = limpiar_rut(paciente.rut).lower()
                    username = base_username
                    contador = 1
                    while Usuario.objects.filter(username=username).exists():
                        username = f"{base_username}_{contador}"
                        contador += 1

                    usuario = Usuario.objects.create_user(
                        username=username,
                        email=email,
                        password=password,
                        first_name=paciente.nombres,
                        last_name=paciente.apellidos,
                        rol=rol_paciente,
                    )
                    paciente.usuario = usuario

                paciente.save()
                # Cada paciente nace con su Ficha Clínica única (1 a 1)
                FichaClinica.objects.get_or_create(paciente=paciente)

            messages.success(
                request,
                f"Paciente {paciente.nombres} {paciente.apellidos} ({paciente.rut}) y su Ficha Clínica fueron creados."
            )
            return redirect('paciente_detalle', paciente_id=paciente.id)
    else:
        form = PacienteForm()

    return render(request, 'pacientes/form.html', {
        'form': form,
        'titulo': 'Registrar Nuevo Paciente',
        'es_edicion': False,
    })


@login_required
@rol_requerido(['Administrador', 'Profesional', 'Recepcionista'])
def paciente_editar_view(request, paciente_id):
    """
    Actualiza los datos demográficos de un paciente existente.
    """
    paciente = get_object_or_404(Paciente, pk=paciente_id)

    if request.method == 'POST':
        form = PacienteForm(request.POST, instance=paciente)
        if form.is_valid():
            with transaction.atomic():
                paciente = form.save()
                if paciente.usuario:
                    paciente.usuario.first_name = paciente.nombres
                    paciente.usuario.last_name = paciente.apellidos
                    paciente.usuario.save(update_fields=['first_name', 'last_name'])

            messages.success(request, f"Datos de {paciente.nombres} {paciente.apellidos} actualizados.")
            return redirect('paciente_detalle', paciente_id=paciente.id)
    else:
        form = PacienteForm(instance=paciente)

    return render(request, 'pacientes/form.html', {
        'form': form,
        'paciente': paciente,
        'titulo': f'Editar Paciente: {paciente.nombres} {paciente.apellidos}',
        'es_edicion': True,
    })


@login_required
def paciente_detalle_view(request, paciente_id):
    """
    Muestra el detalle del paciente, su historial de citas y enlace directo a su Ficha Clínica.
    """
    paciente = get_object_or_404(Paciente.objects.select_related('usuario'), pk=paciente_id)

    es_dueno = request.user.es_paciente and paciente.usuario_id == request.user.id
    if not (request.user.es_staff_clinico or es_dueno):
        messages.warning(request, "No tienes permiso para ver la información de este paciente.")
        return redirect('dashboard')

    ficha, _ = FichaClinica.objects.get_or_create(paciente=paciente)
    citas = paciente.citas.select_related('profesional', 'videoconsulta', 'atencion_clinica').order_by('-fechaHoraInicio')

    return render(request, 'pacientes/detalle.html', {
        'paciente': paciente,
        'ficha': ficha,
        'citas': citas,
        'puede_ver_ficha': (
            request.user.es_administrador or request.user.es_profesional or es_dueno
        ),
    })


# ==============================================================================
# Módulo 2: Fichas Clínicas y Atenciones (Evoluciones)
# ==============================================================================

@login_required
def fichas_lista_view(request):
    """
    Listado de fichas clínicas para personal clínico (Profesional y Administrador).
    Si ingresa un Paciente, redirige automáticamente a su propia Ficha Clínica.
    """
    if request.user.es_paciente and hasattr(request.user, 'paciente'):
        ficha, _ = FichaClinica.objects.get_or_create(paciente=request.user.paciente)
        return redirect('ficha_detalle', ficha_id=ficha.id)

    if not (request.user.es_administrador or request.user.es_profesional):
        messages.warning(request, "El acceso a fichas clínicas está restringido al equipo clínico.")
        return redirect('dashboard')

    query = request.GET.get('q', '').strip()[:80]
    fichas = FichaClinica.objects.select_related('paciente').annotate(
        total_atenciones=Count('atenciones')
    ).order_by('-fechaCreacion')

    if query:
        q_limpio = limpiar_rut(query)
        filtro = (
            Q(paciente__nombres__icontains=query) |
            Q(paciente__apellidos__icontains=query) |
            Q(paciente__rut__icontains=query)
        )
        if q_limpio:
            ids_rut = [
                f.id for f in FichaClinica.objects.select_related('paciente').only('id', 'paciente__rut')
                if q_limpio in limpiar_rut(f.paciente.rut)
            ]
            filtro |= Q(id__in=ids_rut)
        fichas = fichas.filter(filtro)

    return render(request, 'fichas/lista.html', {
        'fichas': fichas,
        'query': query,
    })


@login_required
def ficha_detalle_view(request, ficha_id):
    """
    Visualización del expediente único del paciente (FichaClinica) y su línea de tiempo
    de atenciones médicas (AtencionClinica).
    """
    ficha = get_object_or_404(FichaClinica.objects.select_related('paciente', 'paciente__usuario'), pk=ficha_id)

    es_dueno = request.user.es_paciente and ficha.paciente.usuario_id == request.user.id
    es_clinico = request.user.es_administrador or request.user.es_profesional

    if not (es_clinico or es_dueno):
        messages.warning(request, "No tienes autorización para acceder a esta ficha clínica.")
        return redirect('dashboard')

    atenciones = ficha.atenciones.select_related('profesional', 'cita').order_by('-fechaHora')

    ficha_form = None
    atencion_form = None

    if es_clinico:
        ficha_form = FichaClinicaForm(instance=ficha)
        initial_atencion = {}
        cita_id = parse_positive_int(request.GET.get('cita_id'))
        if cita_id:
            cita_obj = Cita.objects.filter(
                pk=cita_id,
                paciente=ficha.paciente,
                atencion_clinica__isnull=True
            ).first()
            if cita_obj:
                initial_atencion['cita'] = cita_obj
        atencion_form = AtencionClinicaForm(
            paciente=ficha.paciente,
            user=request.user,
            initial=initial_atencion
        )

    return render(request, 'fichas/detalle.html', {
        'ficha': ficha,
        'paciente': ficha.paciente,
        'atenciones': atenciones,
        'es_clinico': es_clinico,
        'ficha_form': ficha_form,
        'atencion_form': atencion_form,
    })


@login_required
@rol_requerido(['Administrador', 'Profesional'])
@require_POST
def ficha_editar_antecedentes_view(request, ficha_id):
    """
    Actualiza antecedentes médicos, alergias y grupo sanguíneo de una Ficha Clínica.
    """
    ficha = get_object_or_404(FichaClinica, pk=ficha_id)

    form = FichaClinicaForm(request.POST, instance=ficha)
    if form.is_valid():
        form.save()
        messages.success(request, "Antecedentes clínicos actualizados correctamente.")
    else:
        for err_list in form.errors.values():
            for err in err_list:
                messages.error(request, err)

    return redirect('ficha_detalle', ficha_id=ficha.id)


@login_required
@rol_requerido(['Administrador', 'Profesional'])
@require_POST
def atencion_crear_view(request, ficha_id):
    """
    Registra una nueva atención/evolución clínica (tabla intermedia AtencionClinica)
    vinculada a la Ficha Clínica del paciente y opcionalmente a una Cita.
    """
    ficha = get_object_or_404(FichaClinica.objects.select_related('paciente'), pk=ficha_id)

    form = AtencionClinicaForm(request.POST, paciente=ficha.paciente, user=request.user)
    if form.is_valid():
        with transaction.atomic():
            atencion = form.save(commit=False)
            atencion.fichaClinica = ficha

            if atencion.cita_id:
                cita_locked = Cita.objects.select_for_update().filter(pk=atencion.cita_id).first()
                if cita_locked and AtencionClinica.objects.filter(cita=cita_locked).exists():
                    messages.error(request, "Esta cita ya tiene una atención clínica registrada.")
                    return redirect('ficha_detalle', ficha_id=ficha.id)

            if request.user.es_profesional and hasattr(request.user, 'profesional'):
                atencion.profesional = request.user.profesional

            atencion.save()

            if atencion.cita:
                atencion.cita.estado = 'Realizada'
                atencion.cita.save(update_fields=['estado'])

        messages.success(request, "Atención clínica registrada exitosamente en la ficha del paciente.")
        return redirect('ficha_detalle', ficha_id=ficha.id)

    # Renderizar la ficha con los errores del formulario de atención
    atenciones = ficha.atenciones.select_related('profesional', 'cita').order_by('-fechaHora')
    return render(request, 'fichas/detalle.html', {
        'ficha': ficha,
        'paciente': ficha.paciente,
        'atenciones': atenciones,
        'es_clinico': True,
        'ficha_form': FichaClinicaForm(instance=ficha),
        'atencion_form': form,
        'abrir_modal_atencion': True,
    })


@login_required
def atencion_documento_view(request, atencion_id):
    """
    Emite el documento clínico entregable (imprimible / PDF vía navegador):
    - tipo='indicaciones': Resumen de Atención e Indicaciones Terapéuticas.
    - tipo='certificado': Certificado de Asistencia Clínica (sin diagnóstico sensible).
    Nunca expone evolucionNotas confidenciales.
    """
    atencion = get_object_or_404(
        AtencionClinica.objects.select_related(
            'fichaClinica',
            'fichaClinica__paciente',
            'fichaClinica__paciente__usuario',
            'profesional',
            'cita',
        ),
        pk=atencion_id
    )
    paciente = atencion.fichaClinica.paciente
    es_clinico = request.user.es_administrador or request.user.es_profesional
    es_dueno = request.user.es_paciente and paciente.usuario_id == request.user.id

    if not (es_clinico or es_dueno):
        messages.warning(request, "No tienes autorización para emitir este documento clínico.")
        return redirect('dashboard')

    tipo_doc = request.GET.get('tipo', 'indicaciones').strip().lower()
    if tipo_doc not in ['indicaciones', 'certificado']:
        tipo_doc = 'indicaciones'

    return render(request, 'fichas/documento_atencion.html', {
        'atencion': atencion,
        'ficha': atencion.fichaClinica,
        'paciente': paciente,
        'profesional': atencion.profesional,
        'tipo_doc': tipo_doc,
        'es_clinico': es_clinico,
    })


# ==============================================================================
# Módulo 3: Agendamiento Real (Cita y BloqueoHorario)
# ==============================================================================

@login_required
def agendamiento_view(request):
    """
    Gestión y reserva real de citas con detección de colisiones de horario
    contra citas activas y bloqueos de disponibilidad de los especialistas.
    """
    user = request.user
    ahora = timezone.now()

    if request.method == 'POST':
        cita_form = CitaForm(request.POST, user=user)
        if cita_form.is_valid():
            with transaction.atomic():
                paciente = cita_form.cleaned_data['paciente']
                profesional = cita_form.cleaned_data['profesional']
                inicio = cita_form.cleaned_data['fechaHoraInicio']
                fin = cita_form.cleaned_data['fechaHoraFin']

                # Seguridad adicional: un paciente solo agenda para sí mismo
                if user.es_paciente and hasattr(user, 'paciente'):
                    paciente = user.paciente

                # Revalidación atómica anti-colisiones dentro de la transacción
                colision_prof = Cita.objects.select_for_update().filter(
                    profesional=profesional,
                    fechaHoraInicio__lt=fin,
                    fechaHoraFin__gt=inicio,
                ).exclude(estado='Cancelada').exists()

                colision_bloq = BloqueoHorario.objects.select_for_update().filter(
                    profesional=profesional,
                    estado='Activo',
                    fechaHoraInicio__lt=fin,
                    fechaHoraFin__gt=inicio,
                ).exists()

                colision_pac = Cita.objects.select_for_update().filter(
                    paciente=paciente,
                    fechaHoraInicio__lt=fin,
                    fechaHoraFin__gt=inicio,
                ).exclude(estado='Cancelada').exists()

                if colision_prof or colision_bloq or colision_pac:
                    messages.error(
                        request,
                        "El bloque horario seleccionado acaba de ser ocupado. Seleccione otro horario disponible."
                    )
                    return redirect('agendamiento')

                cita = Cita.objects.create(
                    paciente=paciente,
                    profesional=profesional,
                    fechaHoraInicio=inicio,
                    fechaHoraFin=fin,
                    estado='Agendada',
                )

                if cita_form.cleaned_data.get('es_telemedicina'):
                    Videoconsulta.objects.create(
                        cita=cita,
                        urlSalaWebRTC=f"sala-{uuid.uuid4().hex[:10]}",
                        estadoConexion='Pendiente',
                    )

            notif = enviar_notificacion_cita(cita, tipo='Agendamiento', notificar_profesional=True)
            fecha_str = timezone.localtime(cita.fechaHoraInicio).strftime('%d/%m/%Y a las %H:%M')
            aviso_correo = " Se envió confirmación por correo al paciente." if notif['enviado_paciente'] else ""
            messages.success(
                request,
                f"Cita #{cita.id} agendada exitosamente para el {fecha_str} con {cita.profesional.nombres} {cita.profesional.apellidos}.{aviso_correo}"
            )
            return redirect('agendamiento')
        else:
            for error in cita_form.non_field_errors():
                messages.error(request, error)
    else:
        initial_cita = {}
        paciente_q = parse_positive_int(request.GET.get('paciente_id'))
        if paciente_q and user.es_staff_clinico:
            initial_cita['paciente'] = paciente_q
        cita_form = CitaForm(user=user, initial=initial_cita)

    # Filtros de listado validados y acotados
    fecha_raw = request.GET.get('fecha', '').strip()[:10]
    profesional_raw = request.GET.get('profesional', '').strip()[:20]
    estado_raw = request.GET.get('estado', '').strip()[:30]
    ver_todas = request.GET.get('ver') == 'todas'

    fecha_filtro = ''
    profesional_id_filtro = parse_positive_int(profesional_raw) if profesional_raw else None
    profesional_filtro = str(profesional_id_filtro) if profesional_id_filtro else ''
    estado_filtro = estado_raw if estado_raw in ESTADOS_CITA_VALIDOS else ''

    citas_qs = Cita.objects.select_related(
        'paciente', 'paciente__usuario', 'profesional', 'videoconsulta', 'atencion_clinica'
    ).prefetch_related('notificaciones').order_by('fechaHoraInicio')

    if user.es_paciente and hasattr(user, 'paciente'):
        citas_qs = citas_qs.filter(paciente=user.paciente)
    elif user.es_profesional and hasattr(user, 'profesional') and not profesional_id_filtro:
        citas_qs = citas_qs.filter(profesional=user.profesional)

    if fecha_raw:
        try:
            fecha_dt = datetime.strptime(fecha_raw, '%Y-%m-%d').date()
            fecha_filtro = fecha_dt.strftime('%Y-%m-%d')
            tz = timezone.get_current_timezone()
            inicio_dia = timezone.make_aware(datetime.combine(fecha_dt, time.min), tz)
            fin_dia = timezone.make_aware(datetime.combine(fecha_dt, time.max), tz)
            citas_qs = citas_qs.filter(fechaHoraInicio__gte=inicio_dia, fechaHoraInicio__lte=fin_dia)
        except ValueError:
            pass
    elif not ver_todas:
        # Mostrar desde inicio del día actual en adelante por defecto
        inicio_hoy = timezone.make_aware(
            datetime.combine(timezone.localdate(), time.min),
            timezone.get_current_timezone()
        )
        citas_qs = citas_qs.filter(fechaHoraInicio__gte=inicio_hoy)

    if not user.es_paciente:
        if profesional_id_filtro:
            citas_qs = citas_qs.filter(profesional_id=profesional_id_filtro)
        elif profesional_raw:
            citas_qs = citas_qs.none()

    if estado_filtro:
        citas_qs = citas_qs.filter(estado=estado_filtro)
    elif estado_raw:
        citas_qs = citas_qs.none()

    # Bloqueos horarios visibles para el equipo clínico
    bloqueos = BloqueoHorario.objects.none()
    bloqueo_form = None
    if user.es_staff_clinico:
        bloqueos = BloqueoHorario.objects.select_related('profesional').filter(
            estado='Activo',
            fechaHoraFin__gte=ahora
        ).order_by('fechaHoraInicio')
        if user.es_profesional and hasattr(user, 'profesional'):
            bloqueos = bloqueos.filter(profesional=user.profesional)
        bloqueo_form = BloqueoHorarioForm(user=user)

    return render(request, 'agendamiento.html', {
        'cita_form': cita_form,
        'bloqueo_form': bloqueo_form,
        'citas': citas_qs,
        'bloqueos': bloqueos,
        'profesionales': Profesional.objects.all().order_by('apellidos', 'nombres'),
        'fecha_filtro': fecha_filtro,
        'profesional_filtro': profesional_filtro,
        'estado_filtro': estado_filtro,
        'ver_todas': ver_todas,
    })


@login_required
@require_POST
def cita_cambiar_estado_view(request, cita_id):
    """
    Actualiza el estado de una cita (Confirmada, En atención, Realizada, Cancelada)
    verificando los permisos del rol actual y transiciones válidas.
    """
    cita = get_object_or_404(Cita.objects.select_related('paciente', 'profesional'), pk=cita_id)

    nuevo_estado = (request.POST.get('estado') or '').strip()
    if nuevo_estado not in ESTADOS_CITA_VALIDOS:
        messages.error(request, "Estado de cita no válido.")
        return redirect('agendamiento')

    user = request.user
    autorizado = False

    if user.es_administrador or user.es_recepcionista:
        autorizado = True
    elif user.es_profesional and hasattr(user, 'profesional') and cita.profesional_id == user.profesional.id:
        autorizado = True
    elif user.es_paciente and hasattr(user, 'paciente') and cita.paciente_id == user.paciente.id:
        # Un paciente solo puede cancelar sus propias citas futuras pendientes
        if (
            nuevo_estado == 'Cancelada'
            and cita.estado in ['Agendada', 'Confirmada']
            and cita.fechaHoraInicio > timezone.now()
        ):
            autorizado = True

    if not autorizado:
        messages.warning(request, "No tienes permisos para realizar esta acción sobre la cita.")
        return redirect('agendamiento')

    if cita.estado == 'Realizada' and nuevo_estado in ['Agendada', 'Confirmada']:
        messages.warning(request, "Una cita ya realizada no puede revertirse a un estado previo.")
        return redirect('agendamiento')

    cita.estado = nuevo_estado
    cita.save(update_fields=['estado'])

    if nuevo_estado == 'Confirmada':
        enviar_notificacion_cita(cita, tipo='Confirmación', notificar_profesional=False)
    elif nuevo_estado == 'Cancelada':
        enviar_notificacion_cita(cita, tipo='Cancelación', notificar_profesional=True)

    messages.success(request, f"Cita #{cita.id} actualizada a estado '{nuevo_estado}'.")
    return redirect('agendamiento')


@login_required
@rol_requerido(['Administrador', 'Profesional', 'Recepcionista'])
@require_POST
def cita_enviar_recordatorio_view(request, cita_id):
    """
    Envía manualmente un recordatorio por correo electrónico al paciente de una cita activa.
    """
    cita = get_object_or_404(
        Cita.objects.select_related('paciente', 'paciente__usuario', 'profesional', 'videoconsulta'),
        pk=cita_id
    )

    if request.user.es_profesional and hasattr(request.user, 'profesional'):
        if cita.profesional_id != request.user.profesional.id:
            messages.warning(request, "Solo puedes enviar recordatorios de tus propias citas.")
            return redirect('agendamiento')

    if cita.estado == 'Cancelada':
        messages.error(request, "No se puede enviar recordatorio para una cita cancelada.")
        return redirect('agendamiento')

    res = enviar_notificacion_cita(cita, tipo='Recordatorio', notificar_profesional=False)
    if res['enviado_paciente']:
        messages.success(request, f"Recordatorio enviado a {res['email_paciente']} para la Cita #{cita.id}.")
    elif not res['email_paciente']:
        messages.warning(
            request,
            f"El paciente {cita.paciente.nombres} {cita.paciente.apellidos} no tiene cuenta con correo electrónico registrada."
        )
    else:
        messages.error(request, "No fue posible enviar el recordatorio por correo electrónico.")

    return redirect('agendamiento')


@login_required
@rol_requerido(['Administrador', 'Profesional', 'Recepcionista'])
@require_POST
def bloqueo_crear_view(request):
    """
    Registra un nuevo bloqueo horario para un especialista validando atómicamente
    que no colisione con citas ya agendadas u otros bloqueos activos.
    """
    form = BloqueoHorarioForm(request.POST, user=request.user)
    if form.is_valid():
        with transaction.atomic():
            profesional = form.cleaned_data['profesional']
            if request.user.es_profesional and hasattr(request.user, 'profesional'):
                profesional = request.user.profesional

            inicio = form.cleaned_data['fechaHoraInicio']
            fin = form.cleaned_data['fechaHoraFin']

            hay_citas = Cita.objects.select_for_update().filter(
                profesional=profesional,
                fechaHoraInicio__lt=fin,
                fechaHoraFin__gt=inicio,
            ).exclude(estado='Cancelada').exists()

            hay_bloqueo = BloqueoHorario.objects.select_for_update().filter(
                profesional=profesional,
                estado='Activo',
                fechaHoraInicio__lt=fin,
                fechaHoraFin__gt=inicio,
            ).exists()

            if hay_citas or hay_bloqueo:
                messages.error(request, "El tramo horario seleccionado colisiona con una cita o bloqueo activo.")
                return redirect('agendamiento')

            BloqueoHorario.objects.create(
                profesional=profesional,
                fechaHoraInicio=inicio,
                fechaHoraFin=fin,
                motivo=form.cleaned_data.get('motivo') or 'Bloqueo de agenda',
                estado='Activo',
            )
        messages.success(
            request,
            f"Bloqueo registrado para {profesional.nombres} {profesional.apellidos}."
        )
    else:
        for error in form.non_field_errors():
            messages.error(request, error)
        for field, errors in form.errors.items():
            if field != '__all__':
                for err in errors:
                    messages.error(request, err)

    return redirect('agendamiento')


@login_required
@rol_requerido(['Administrador', 'Profesional', 'Recepcionista'])
@require_POST
def bloqueo_eliminar_view(request, bloqueo_id):
    """
    Desactiva/elimina un bloqueo horario existente.
    """
    bloqueo = get_object_or_404(BloqueoHorario, pk=bloqueo_id)

    if request.user.es_profesional and hasattr(request.user, 'profesional'):
        if bloqueo.profesional_id != request.user.profesional.id:
            messages.warning(request, "Solo puedes eliminar tus propios bloqueos horarios.")
            return redirect('agendamiento')

    bloqueo.estado = 'Inactivo'
    bloqueo.save(update_fields=['estado'])
    messages.info(request, "Bloqueo horario eliminado correctamente.")

    return redirect('agendamiento')


@login_required
def disponibilidad_json_view(request):
    """
    Endpoint JSON para consultar bloques ocupados (citas activas y bloqueos) de un profesional
    en una fecha específica, sin exponer datos privados de otros pacientes.
    """
    prof_raw = (request.GET.get('profesional_id') or '').strip()
    fecha_str = (request.GET.get('fecha') or '').strip()[:10]

    if not prof_raw or not fecha_str:
        return JsonResponse({'ocupados': []})

    profesional_id = parse_positive_int(prof_raw)
    if not profesional_id:
        return JsonResponse({'ocupados': [], 'error': 'Profesional inválido'}, status=400)

    try:
        fecha_dt = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'ocupados': [], 'error': 'Fecha inválida'}, status=400)

    tz = timezone.get_current_timezone()
    inicio_dia = timezone.make_aware(datetime.combine(fecha_dt, time.min), tz)
    fin_dia = timezone.make_aware(datetime.combine(fecha_dt, time.max), tz)

    citas = Cita.objects.filter(
        profesional_id=profesional_id,
        fechaHoraInicio__lt=fin_dia,
        fechaHoraFin__gt=inicio_dia
    ).exclude(estado='Cancelada').order_by('fechaHoraInicio')

    bloqueos = BloqueoHorario.objects.filter(
        profesional_id=profesional_id,
        estado='Activo',
        fechaHoraInicio__lt=fin_dia,
        fechaHoraFin__gt=inicio_dia
    ).order_by('fechaHoraInicio')

    ocupados = []
    for c in citas:
        ocupados.append({
            'tipo': 'Cita',
            'inicio': timezone.localtime(c.fechaHoraInicio).strftime('%H:%M'),
            'fin': timezone.localtime(c.fechaHoraFin).strftime('%H:%M'),
            'detalle': f"Ocupado ({c.estado})",
        })

    for b in bloqueos:
        ocupados.append({
            'tipo': 'Bloqueo',
            'inicio': timezone.localtime(b.fechaHoraInicio).strftime('%H:%M'),
            'fin': timezone.localtime(b.fechaHoraFin).strftime('%H:%M'),
            'detalle': f"Bloqueado: {b.motivo or 'No disponible'}",
        })

    ocupados.sort(key=lambda x: x['inicio'])
    return JsonResponse({'ocupados': ocupados})


# ==============================================================================
# Módulo 4: Telemedicina (Panel Dual WebRTC + Notas Clínicas en Vivo)
# ==============================================================================

def _usuario_autorizado_sala(user, videoconsulta):
    if user.es_administrador:
        return True
    if user.es_profesional and hasattr(user, 'profesional'):
        return videoconsulta.cita.profesional_id == user.profesional.id
    if user.es_paciente and hasattr(user, 'paciente'):
        return videoconsulta.cita.paciente_id == user.paciente.id
    return False


@login_required
@rol_requerido(['Profesional', 'Administrador', 'Paciente'])
def telemedicina_view(request):
    """
    Listado de salas de telemedicina activas e históricas según el rol del usuario.
    """
    user = request.user
    videoconsultas = Videoconsulta.objects.select_related(
        'cita', 'cita__paciente', 'cita__paciente__ficha_clinica', 'cita__profesional', 'cita__atencion_clinica'
    ).exclude(cita__estado='Cancelada').order_by('-cita__fechaHoraInicio')

    if user.es_paciente:
        videoconsultas = videoconsultas.filter(cita__paciente=user.paciente) if hasattr(user, 'paciente') else Videoconsulta.objects.none()
    elif user.es_profesional:
        videoconsultas = videoconsultas.filter(cita__profesional=user.profesional) if hasattr(user, 'profesional') else Videoconsulta.objects.none()

    return render(request, 'telemedicina.html', {
        'videoconsultas': videoconsultas,
    })


@login_required
@rol_requerido(['Profesional', 'Administrador', 'Paciente'])
def telemedicina_sala_view(request, videoconsulta_id):
    """
    Entorno Dual de Telemedicina:
    - Panel izquierdo: Videollamada WebRTC P2P con sala de espera y controles multimedia.
    - Panel derecho: Notas clínicas continuas en vivo (cifradas en AtencionClinica) para el especialista,
      o indicaciones médicas previas para el paciente.
    """
    videoconsulta = get_object_or_404(
        Videoconsulta.objects.select_related('cita', 'cita__paciente', 'cita__profesional'),
        pk=videoconsulta_id
    )
    if not _usuario_autorizado_sala(request.user, videoconsulta):
        messages.warning(request, "No tienes autorización para ingresar a esta sala de videoconsulta.")
        return redirect('telemedicina')

    cita = videoconsulta.cita
    if cita.estado == 'Cancelada':
        messages.warning(request, "No es posible ingresar a la sala porque la cita asociada fue cancelada.")
        return redirect('telemedicina')

    ficha, _ = FichaClinica.objects.get_or_create(paciente=cita.paciente)
    es_clinico = request.user.es_administrador or request.user.es_profesional
    atencion_existente = AtencionClinica.objects.filter(cita=cita).first()

    # Si el paciente ingresa y la sala estaba Pendiente, pasa automáticamente a 'En espera'
    if request.user.es_paciente and videoconsulta.estadoConexion == 'Pendiente':
        videoconsulta.estadoConexion = 'En espera'
        videoconsultas_fields = ['estadoConexion']
        videoconsulta.save(update_fields=videoconsultas_fields)

    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        if not es_clinico:
            if is_ajax:
                return JsonResponse({'ok': False, 'error': 'Sin permiso para editar notas clínicas.'}, status=403)
            messages.warning(request, "Solo el equipo clínico puede registrar evoluciones.")
            return redirect('telemedicina_sala', videoconsulta_id=videoconsulta.id)

        form = AtencionClinicaForm(
            request.POST,
            instance=atencion_existente,
            paciente=cita.paciente,
            user=request.user
        )
        if form.is_valid():
            with transaction.atomic():
                atencion = form.save(commit=False)
                atencion.fichaClinica = ficha
                atencion.cita = cita
                if request.user.es_profesional and hasattr(request.user, 'profesional'):
                    atencion.profesional = request.user.profesional
                atencion.save()

                accion = request.POST.get('accion_nota', 'guardar')
                if accion == 'finalizar':
                    cita.estado = 'Realizada'
                    cita.save(update_fields=['estado'])
                    videoconsulta.estadoConexion = 'Finalizada'
                    videoconsulta.save(update_fields=['estadoConexion'])
                    cache.delete(f"webrtc_room_{videoconsulta.id}")
                elif cita.estado in ['Agendada', 'Confirmada']:
                    cita.estado = 'En atención'
                    cita.save(update_fields=['estado'])

            if is_ajax:
                return JsonResponse({
                    'ok': True,
                    'mensaje': 'Nota clínica guardada y cifrada correctamente.',
                    'atencion_id': atencion.id,
                    'estado_cita': cita.estado,
                    'estado_sala': videoconsulta.estadoConexion,
                })
            messages.success(request, "Evolución clínica de telemedicina guardada y cifrada correctamente.")
            return redirect('telemedicina_sala', videoconsulta_id=videoconsulta.id)
        else:
            if is_ajax:
                return JsonResponse({'ok': False, 'errors': form.errors}, status=400)
            messages.error(request, "Revise los campos obligatorios de la nota clínica.")
    else:
        initial_data = {'cita': cita, 'profesional': cita.profesional}
        form = AtencionClinicaForm(
            instance=atencion_existente,
            paciente=cita.paciente,
            user=request.user,
            initial=initial_data if not atencion_existente else None
        )

    atenciones_previas = ficha.atenciones.select_related('profesional').exclude(
        cita=cita
    ).order_by('-fechaHora')[:4]

    return render(request, 'telemedicina_sala.html', {
        'videoconsulta': videoconsulta,
        'cita': cita,
        'paciente': cita.paciente,
        'profesional': cita.profesional,
        'ficha': ficha,
        'es_clinico': es_clinico,
        'atencion_existente': atencion_existente,
        'atencion_form': form,
        'atenciones_previas': atenciones_previas,
        'rol_sala': 'host' if es_clinico else 'guest',
    })


@login_required
@require_POST
def telemedicina_estado_view(request, videoconsulta_id):
    """
    Actualiza el estado de conexión de una sala WebRTC (En espera, En curso, Finalizada).
    """
    videoconsulta = get_object_or_404(Videoconsulta.objects.select_related('cita'), pk=videoconsulta_id)
    if not _usuario_autorizado_sala(request.user, videoconsulta):
        return JsonResponse({'ok': False, 'error': 'No autorizado'}, status=403)

    if videoconsulta.cita.estado == 'Cancelada':
        return JsonResponse({'ok': False, 'error': 'La cita asociada fue cancelada'}, status=409)

    nuevo_estado = request.POST.get('estadoConexion')
    if not nuevo_estado and request.body and len(request.body) <= 4096:
        try:
            body = json.loads(request.body.decode('utf-8'))
            if isinstance(body, dict):
                nuevo_estado = body.get('estadoConexion')
        except (ValueError, UnicodeDecodeError):
            pass

    estados_validos = ['Pendiente', 'En espera', 'En curso', 'Finalizada']
    if nuevo_estado not in estados_validos:
        return JsonResponse({'ok': False, 'error': 'Estado inválido'}, status=400)

    # Solo el profesional o administrador puede admitir ('En curso') o finalizar
    es_clinico = request.user.es_administrador or request.user.es_profesional
    if nuevo_estado in ['En curso', 'Finalizada'] and not es_clinico:
        return JsonResponse({'ok': False, 'error': 'Solo el profesional puede iniciar o finalizar la sesión'}, status=403)

    videoconsulta.estadoConexion = nuevo_estado
    videoconsulta.save(update_fields=['estadoConexion'])

    if nuevo_estado == 'En curso' and videoconsulta.cita.estado in ['Agendada', 'Confirmada']:
        videoconsulta.cita.estado = 'En atención'
        videoconsulta.cita.save(update_fields=['estado'])
    elif nuevo_estado == 'Finalizada':
        cache.delete(f"webrtc_room_{videoconsulta.id}")
        if videoconsulta.cita.estado == 'En atención':
            videoconsulta.cita.estado = 'Realizada'
            videoconsulta.cita.save(update_fields=['estado'])

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'estadoConexion': videoconsulta.estadoConexion})

    messages.info(request, f"Estado de sala actualizado a '{nuevo_estado}'.")
    return redirect('telemedicina_sala', videoconsulta_id=videoconsulta.id)


@login_required
def telemedicina_senal_view(request, videoconsulta_id):
    """
    Endpoint de señalización WebRTC (SDP Offer/Answer + ICE Candidates) mediante Django cache
    con validación estricta de tamaño, estructura y rol para evitar DoS o inyección de señalización.
    """
    videoconsulta = get_object_or_404(Videoconsulta.objects.select_related('cita'), pk=videoconsulta_id)
    if not _usuario_autorizado_sala(request.user, videoconsulta):
        return JsonResponse({'ok': False, 'error': 'No autorizado'}, status=403)

    if videoconsulta.cita.estado == 'Cancelada':
        return JsonResponse({'ok': False, 'error': 'La cita asociada fue cancelada'}, status=409)

    cache_key = f"webrtc_room_{videoconsulta.id}"
    room_data = cache.get(cache_key) or {
        'offer': None,
        'answer': None,
        'host_ice': [],
        'guest_ice': [],
        'host_online': False,
        'guest_online': False,
    }

    rol_local = 'host' if (request.user.es_administrador or request.user.es_profesional) else 'guest'

    if request.method == 'POST':
        if len(request.body) > 65536:
            return JsonResponse({'ok': False, 'error': 'Payload de señalización excede el límite permitido.'}, status=413)

        try:
            payload = json.loads(request.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({'ok': False, 'error': 'JSON inválido'}, status=400)

        if not isinstance(payload, dict):
            return JsonResponse({'ok': False, 'error': 'Formato de señal inválido (se esperaba un objeto JSON).'}, status=400)

        tipo = payload.get('type')
        if tipo not in ('reset', 'presence', 'offer', 'answer', 'ice'):
            return JsonResponse({'ok': False, 'error': 'Tipo de señal WebRTC no válido.'}, status=400)

        if tipo in ('offer', 'answer', 'ice') and videoconsulta.estadoConexion != 'En curso':
            return JsonResponse({
                'ok': False,
                'error': 'Sala de espera activa: la señalización WebRTC inicia cuando el especialista admite al paciente.'
            }, status=409)

        if tipo == 'reset':
            if rol_local != 'host':
                return JsonResponse({'ok': False, 'error': 'Solo el profesional puede reiniciar la señalización.'}, status=403)
            if videoconsulta.estadoConexion != 'En curso':
                return JsonResponse({'ok': False, 'error': 'La sala debe estar en curso para reiniciar la señalización.'}, status=409)
            room_data = {'offer': None, 'answer': None, 'host_ice': [], 'guest_ice': [], 'host_online': True, 'guest_online': False}
        elif tipo == 'presence':
            room_data[f'{rol_local}_online'] = True
        elif tipo == 'offer':
            if rol_local != 'host':
                return JsonResponse({'ok': False, 'error': 'Solo el profesional puede emitir offer.'}, status=403)
            sdp = payload.get('sdp')
            if not isinstance(sdp, dict) or sdp.get('type') != 'offer' or not isinstance(sdp.get('sdp'), str) or len(sdp['sdp']) > 32768:
                return JsonResponse({'ok': False, 'error': 'SDP offer inválido o excede límite de caracteres.'}, status=400)
            room_data['offer'] = {'type': 'offer', 'sdp': sdp['sdp']}
            room_data['answer'] = None
            room_data['host_ice'] = []
            room_data['guest_ice'] = []
        elif tipo == 'answer':
            if rol_local != 'guest':
                return JsonResponse({'ok': False, 'error': 'Solo el paciente puede emitir answer.'}, status=403)
            sdp = payload.get('sdp')
            if not isinstance(sdp, dict) or sdp.get('type') != 'answer' or not isinstance(sdp.get('sdp'), str) or len(sdp['sdp']) > 32768:
                return JsonResponse({'ok': False, 'error': 'SDP answer inválido o excede límite de caracteres.'}, status=400)
            room_data['answer'] = {'type': 'answer', 'sdp': sdp['sdp']}
        elif tipo == 'ice':
            cand = payload.get('candidate')
            if not isinstance(cand, dict) or not isinstance(cand.get('candidate'), str) or len(json.dumps(cand)) > 2048:
                return JsonResponse({'ok': False, 'error': 'Candidato ICE inválido.'}, status=400)
            ice_list = room_data.setdefault(f'{rol_local}_ice', [])
            if len(ice_list) >= 50:
                return JsonResponse({'ok': False, 'error': 'Límite de candidatos ICE excedido.'}, status=429)
            ice_list.append(cand)

        cache.set(cache_key, room_data, timeout=3600)
        return JsonResponse({'ok': True})

    # GET: devolver estado de la señalización y estado de sala
    room_data[f'{rol_local}_online'] = True
    cache.set(cache_key, room_data, timeout=3600)

    sala_en_curso = videoconsulta.estadoConexion == 'En curso'
    return JsonResponse({
        'ok': True,
        'estadoConexion': videoconsulta.estadoConexion,
        'rol': rol_local,
        'offer': room_data['offer'] if sala_en_curso else None,
        'answer': room_data['answer'] if sala_en_curso else None,
        'remote_ice': (room_data['guest_ice'] if rol_local == 'host' else room_data['host_ice']) if sala_en_curso else [],
        'peer_online': room_data['guest_online'] if rol_local == 'host' else room_data['host_online'],
    })


# ==============================================================================
# Módulo 5: Caja, Pagos y Liquidaciones
# ==============================================================================

def _aplicar_filtros_caja(request, pagos_qs):
    tz = timezone.get_current_timezone()
    fecha_raw = request.GET.get('fecha', '').strip()[:10]
    estado_raw = request.GET.get('estado', '').strip()[:30]
    metodo_raw = request.GET.get('metodo', '').strip()[:30]

    fecha_filtro = ''
    if fecha_raw:
        try:
            f_dt = datetime.strptime(fecha_raw, '%Y-%m-%d').date()
            fecha_filtro = f_dt.strftime('%Y-%m-%d')
            ini_d = timezone.make_aware(datetime.combine(f_dt, time.min), tz)
            fin_d = timezone.make_aware(datetime.combine(f_dt, time.max), tz)
            pagos_qs = pagos_qs.filter(fechaPago__gte=ini_d, fechaPago__lte=fin_d)
        except ValueError:
            pass

    estado_filtro = estado_raw if estado_raw in ESTADOS_PAGO_VALIDOS else ''
    if estado_filtro:
        pagos_qs = pagos_qs.filter(estado=estado_filtro)
    elif estado_raw:
        pagos_qs = pagos_qs.none()

    metodo_filtro = metodo_raw if metodo_raw in METODOS_PAGO_VALIDOS else ''
    if metodo_filtro:
        pagos_qs = pagos_qs.filter(metodoPago=metodo_filtro)
    elif metodo_raw:
        pagos_qs = pagos_qs.none()

    return pagos_qs, fecha_filtro, estado_filtro, metodo_filtro


@login_required
def caja_view(request):
    """
    Módulo de Caja, Registro de Pagos, Cuadratura Diaria y Liquidación de Honorarios.
    - Administrador y Recepcionista: acceso completo.
    - Profesional: ve únicamente sus citas pagadas y su cálculo de honorarios.
    - Paciente: ve únicamente sus propios pagos y comprobantes.
    """
    user = request.user
    puede_cobrar = user.es_administrador or user.es_recepcionista

    if request.method == 'POST':
        if not puede_cobrar:
            messages.warning(request, "Solo administración y recepción pueden registrar pagos en caja.")
            return redirect('caja')

        form = PagoForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                cita_locked = Cita.objects.select_for_update().get(pk=form.cleaned_data['cita'].pk)
                if cita_locked.estado == 'Cancelada':
                    messages.error(request, "No es posible registrar cobros sobre una cita cancelada.")
                    return redirect('caja')
                if form.cleaned_data['estado'] == 'Pagado' and cita_locked.pagos.filter(estado='Pagado').exists():
                    messages.error(request, f"La Cita #{cita_locked.id} ya registra un pago confirmado.")
                    return redirect('caja')

                pago = form.save(commit=False)
                pago.registradoPor = user
                if not pago.numeroComprobante:
                    fecha_tag = timezone.localtime().strftime('%Y%m%d')
                    ultimo_id = Pago.objects.select_for_update().order_by('-id').values_list('id', flat=True).first() or 0
                    correlativo = ultimo_id + 1
                    pago.numeroComprobante = f"CMP-{fecha_tag}-{correlativo:04d}"
                pago.save()

            messages.success(
                request,
                f"Pago #{pago.id} (${int(pago.monto):,}) registrado con comprobante {pago.numeroComprobante}."
            )
            return redirect('caja')
        else:
            for field, errors in form.errors.items():
                for err in errors:
                    messages.error(request, err)
    else:
        initial_pago = {}
        cita_q = parse_positive_int(request.GET.get('cita_id'))
        if cita_q and puede_cobrar:
            initial_pago['cita'] = cita_q
        form = PagoForm(initial=initial_pago) if puede_cobrar else None

    # Filtros
    hoy = timezone.localdate()
    tz = timezone.get_current_timezone()
    inicio_hoy = timezone.make_aware(datetime.combine(hoy, time.min), tz)
    fin_hoy = timezone.make_aware(datetime.combine(hoy, time.max), tz)
    inicio_mes = timezone.make_aware(datetime.combine(hoy.replace(day=1), time.min), tz)

    try:
        comision_pct = int(request.GET.get('comision', 30))
        if comision_pct < 0 or comision_pct > 100:
            comision_pct = 30
    except ValueError:
        comision_pct = 30

    pagos_qs = Pago.objects.select_related(
        'cita', 'cita__paciente', 'cita__profesional', 'registradoPor'
    ).order_by('-fechaPago')

    if user.es_paciente:
        pagos_qs = pagos_qs.filter(cita__paciente=user.paciente) if hasattr(user, 'paciente') else Pago.objects.none()
    elif user.es_profesional:
        pagos_qs = pagos_qs.filter(cita__profesional=user.profesional) if hasattr(user, 'profesional') else Pago.objects.none()

    pagos_qs, fecha_filtro, estado_filtro, metodo_filtro = _aplicar_filtros_caja(request, pagos_qs)

    # Totales (respetando alcance del rol)
    pagos_alcance = Pago.objects.all()
    if user.es_paciente:
        pagos_alcance = pagos_alcance.filter(cita__paciente=user.paciente) if hasattr(user, 'paciente') else Pago.objects.none()
    elif user.es_profesional:
        pagos_alcance = pagos_alcance.filter(cita__profesional=user.profesional) if hasattr(user, 'profesional') else Pago.objects.none()

    total_hoy = pagos_alcance.filter(
        estado='Pagado', fechaPago__gte=inicio_hoy, fechaPago__lte=fin_hoy
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0')

    total_mes = pagos_alcance.filter(
        estado='Pagado', fechaPago__gte=inicio_mes
    ).aggregate(total=Sum('monto'))['total'] or Decimal('0')

    pendientes_agg = pagos_alcance.filter(estado='Pendiente').aggregate(
        total=Sum('monto'), cantidad=Count('id')
    )

    # Cuadratura por medio de pago (sobre el filtro actual en estado Pagado)
    desglose_metodos = pagos_qs.filter(estado='Pagado').values('metodoPago').annotate(
        total=Sum('monto'), cantidad=Count('id')
    ).order_by('-total')

    # Citas pendientes de cobro (solo para Recepción / Admin)
    citas_sin_pago = []
    if puede_cobrar:
        citas_sin_pago = Cita.objects.select_related('paciente', 'profesional').exclude(
            estado='Cancelada'
        ).exclude(pagos__estado='Pagado').distinct().order_by('-fechaHoraInicio')[:8]

    # Liquidación de honorarios por profesional (Admin/Recepción ve todos; Profesional ve el suyo)
    liquidaciones = []
    if not user.es_paciente:
        pagos_liquidables = pagos_qs.filter(estado='Pagado')
        resumen_prof = {}
        for p in pagos_liquidables:
            prof = p.cita.profesional
            if prof.id not in resumen_prof:
                resumen_prof[prof.id] = {
                    'profesional': prof,
                    'cantidad_citas': 0,
                    'monto_bruto': Decimal('0'),
                }
            resumen_prof[prof.id]['cantidad_citas'] += 1
            resumen_prof[prof.id]['monto_bruto'] += p.monto

        factor_comision = Decimal(comision_pct) / Decimal('100')
        for item in resumen_prof.values():
            comision_centro = (item['monto_bruto'] * factor_comision).quantize(Decimal('1'))
            liquido_prof = item['monto_bruto'] - comision_centro
            item['comision_centro'] = comision_centro
            item['liquido_profesional'] = liquido_prof
            liquidaciones.append(item)

        liquidaciones.sort(key=lambda x: x['monto_bruto'], reverse=True)

    return render(request, 'caja/index.html', {
        'pago_form': form,
        'puede_cobrar': puede_cobrar,
        'pagos': pagos_qs,
        'citas_sin_pago': citas_sin_pago,
        'total_hoy': total_hoy,
        'total_mes': total_mes,
        'pendientes_total': pendientes_agg['total'] or Decimal('0'),
        'pendientes_count': pendientes_agg['cantidad'] or 0,
        'desglose_metodos': desglose_metodos,
        'liquidaciones': liquidaciones,
        'comision_pct': comision_pct,
        'fecha_filtro': fecha_filtro,
        'estado_filtro': estado_filtro,
        'metodo_filtro': metodo_filtro,
    })


@login_required
@rol_requerido(['Administrador', 'Recepcionista'])
@require_POST
def pago_cambiar_estado_view(request, pago_id):
    """
    Permite confirmar un pago pendiente ('Pagado') o anular un registro ('Anulado').
    """
    pago = get_object_or_404(Pago, pk=pago_id)
    nuevo_estado = (request.POST.get('estado') or '').strip()
    if nuevo_estado in ESTADOS_PAGO_VALIDOS:
        with transaction.atomic():
            pago_locked = Pago.objects.select_for_update().select_related('cita').get(pk=pago.pk)
            if nuevo_estado == 'Pagado' and pago_locked.cita.pagos.filter(estado='Pagado').exclude(pk=pago_locked.pk).exists():
                messages.error(request, f"La Cita #{pago_locked.cita_id} ya tiene otro pago confirmado.")
                return redirect('caja')
            pago_locked.estado = nuevo_estado
            if nuevo_estado == 'Pagado':
                pago_locked.fechaPago = timezone.now()
            pago_locked.save(update_fields=['estado', 'fechaPago'])
        messages.success(request, f"Pago #{pago.id} actualizado a '{nuevo_estado}'.")
    else:
        messages.error(request, "Estado de pago inválido.")
    return redirect('caja')


@login_required
def pago_comprobante_view(request, pago_id):
    """
    Comprobante de pago imprimible / descargable en PDF vía navegador.
    """
    pago = get_object_or_404(
        Pago.objects.select_related('cita', 'cita__paciente', 'cita__profesional', 'registradoPor'),
        pk=pago_id
    )
    user = request.user
    autorizado = (
        user.es_administrador
        or user.es_recepcionista
        or (user.es_profesional and hasattr(user, 'profesional') and pago.cita.profesional_id == user.profesional.id)
        or (user.es_paciente and hasattr(user, 'paciente') and pago.cita.paciente_id == user.paciente.id)
    )
    if not autorizado:
        messages.warning(request, "No tienes permiso para ver este comprobante.")
        return redirect('dashboard')

    return render(request, 'caja/comprobante.html', {'pago': pago})


@login_required
@rol_requerido(['Administrador', 'Recepcionista', 'Profesional'])
def caja_exportar_csv_view(request):
    """
    Exporta el detalle de pagos en formato CSV compatible con Excel (UTF-8 BOM)
    y sanitizado contra CSV Formula Injection (CWE-1236).
    """
    user = request.user
    pagos = Pago.objects.select_related('cita', 'cita__paciente', 'cita__profesional').order_by('-fechaPago')
    if user.es_profesional:
        pagos = pagos.filter(cita__profesional=user.profesional) if hasattr(user, 'profesional') else Pago.objects.none()

    pagos, _, _, _ = _aplicar_filtros_caja(request, pagos)

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = f'attachment; filename="caja_centro_nodo_{timezone.localdate()}.csv"'

    writer = csv.writer(response, delimiter=';')
    writer.writerow(['ID', 'Comprobante', 'Fecha Pago', 'Paciente', 'RUT', 'Profesional', 'Previsión', 'Medio de Pago', 'Monto (CLP)', 'Estado'])
    for p in pagos:
        writer.writerow([
            p.id,
            sanitizar_celda_csv(p.numeroComprobante or f"#{p.id}"),
            timezone.localtime(p.fechaPago).strftime('%d/%m/%Y %H:%M'),
            sanitizar_celda_csv(f"{p.cita.paciente.nombres} {p.cita.paciente.apellidos}"),
            sanitizar_celda_csv(p.cita.paciente.rut),
            sanitizar_celda_csv(f"{p.cita.profesional.nombres} {p.cita.profesional.apellidos}"),
            sanitizar_celda_csv(p.prevision),
            sanitizar_celda_csv(p.metodoPago),
            int(p.monto),
            sanitizar_celda_csv(p.estado),
        ])
    return response


@login_required
@rol_requerido(['Administrador', 'Recepcionista', 'Profesional'])
def caja_reporte_liquidacion_view(request):
    """
    Reporte imprimible / exportable a PDF desde navegador de la cuadratura por medio de pago
    y liquidación de honorarios de especialistas.
    """
    user = request.user

    try:
        comision_pct = int(request.GET.get('comision', 30))
        if comision_pct < 0 or comision_pct > 100:
            comision_pct = 30
    except ValueError:
        comision_pct = 30

    pagos_qs = Pago.objects.select_related(
        'cita', 'cita__paciente', 'cita__profesional'
    ).order_by('-fechaPago')

    if user.es_profesional:
        pagos_qs = pagos_qs.filter(cita__profesional=user.profesional) if hasattr(user, 'profesional') else Pago.objects.none()

    pagos_qs, fecha_filtro, estado_filtro, metodo_filtro = _aplicar_filtros_caja(request, pagos_qs)

    pagos_pagados = pagos_qs.filter(estado='Pagado')
    total_recaudado = pagos_pagados.aggregate(total=Sum('monto'))['total'] or Decimal('0')
    desglose_metodos = pagos_pagados.values('metodoPago').annotate(
        total=Sum('monto'), cantidad=Count('id')
    ).order_by('-total')

    resumen_prof = {}
    for p in pagos_pagados:
        prof = p.cita.profesional
        if prof.id not in resumen_prof:
            resumen_prof[prof.id] = {
                'profesional': prof,
                'cantidad_citas': 0,
                'monto_bruto': Decimal('0'),
            }
        resumen_prof[prof.id]['cantidad_citas'] += 1
        resumen_prof[prof.id]['monto_bruto'] += p.monto

    factor_comision = Decimal(comision_pct) / Decimal('100')
    liquidaciones = []
    total_comision = Decimal('0')
    total_liquido = Decimal('0')

    for item in resumen_prof.values():
        comision_centro = (item['monto_bruto'] * factor_comision).quantize(Decimal('1'))
        liquido_prof = item['monto_bruto'] - comision_centro
        item['comision_centro'] = comision_centro
        item['liquido_profesional'] = liquido_prof
        total_comision += comision_centro
        total_liquido += liquido_prof
        liquidaciones.append(item)

    liquidaciones.sort(key=lambda x: x['monto_bruto'], reverse=True)

    return render(request, 'caja/reporte_liquidacion.html', {
        'fecha_emision': timezone.localtime(),
        'fecha_filtro': fecha_filtro,
        'estado_filtro': estado_filtro,
        'metodo_filtro': metodo_filtro,
        'comision_pct': comision_pct,
        'desglose_metodos': desglose_metodos,
        'liquidaciones': liquidaciones,
        'pagos_pagados': pagos_pagados,
        'total_recaudado': total_recaudado,
        'total_comision': total_comision,
        'total_liquido': total_liquido,
    })


