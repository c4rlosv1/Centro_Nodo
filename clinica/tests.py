import json
from io import StringIO
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.contrib import admin
from django.core import mail
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from clinica.admin import AuditLogAdmin
from clinica.crypto import decrypt_text
from clinica.models import (
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
    AuditLog,
)
from clinica.utils import validar_rut, formatear_rut
from clinica.views import error_403_view, error_500_view


class RutUtilsTests(TestCase):
    def test_rut_valido_y_formateo(self):
        self.assertTrue(validar_rut('19.876.543-0'))
        self.assertTrue(validar_rut('198765430'))
        self.assertTrue(validar_rut('15.342.980-4'))
        self.assertTrue(validar_rut('17654321-3'))
        self.assertEqual(formatear_rut('198765430'), '19.876.543-0')

    def test_rut_invalido(self):
        self.assertFalse(validar_rut('19.876.543-2'))
        self.assertFalse(validar_rut('11.111.111-1'))
        self.assertFalse(validar_rut('abc'))
        self.assertFalse(validar_rut('0-0'))


class ModulosClinicosTests(TestCase):
    def setUp(self):
        self.rol_admin = Rol.objects.create(nombre='Administrador')
        self.rol_prof = Rol.objects.create(nombre='Profesional')
        self.rol_pac = Rol.objects.create(nombre='Paciente')
        self.rol_recep = Rol.objects.create(nombre='Recepcionista')

        self.user_prof = Usuario.objects.create_user(
            username='prof1',
            email='prof1@centronodo.cl',
            password='password123',
            first_name='Andrés',
            last_name='Silva',
            rol=self.rol_prof,
        )
        self.profesional = Profesional.objects.create(
            usuario=self.user_prof,
            rut='15.342.980-4',
            nombres='Andrés',
            apellidos='Silva',
            especialidad='Psiquiatría',
        )

        self.user_recep = Usuario.objects.create_user(
            username='recep1',
            email='recep1@centronodo.cl',
            password='password123',
            first_name='Sofía',
            last_name='Muñoz',
            rol=self.rol_recep,
        )

        self.user_pac = Usuario.objects.create_user(
            username='pac1',
            email='pac1@correo.cl',
            password='password123',
            first_name='Juan',
            last_name='Pérez',
            rol=self.rol_pac,
        )
        self.paciente = Paciente.objects.create(
            usuario=self.user_pac,
            rut='19.876.543-0',
            nombres='Juan',
            apellidos='Pérez',
        )
        self.ficha = FichaClinica.objects.create(paciente=self.paciente)

        self.client = Client()

    def test_crear_paciente_con_rut_valido_y_ficha_automatica(self):
        self.client.force_login(self.user_recep)
        resp = self.client.post(reverse('paciente_crear'), {
            'rut': '12345678-5',
            'nombres': 'María',
            'apellidos': 'Lagos',
            'telefono': '+56911112222',
            'crear_cuenta_web': True,
            'email_cuenta': 'maria.lagos@correo.cl',
            'password_inicial': 'clave123',
        })
        self.assertEqual(resp.status_code, 302)
        nuevo = Paciente.objects.get(rut='12.345.678-5')
        self.assertIsNotNone(nuevo.usuario)
        self.assertEqual(nuevo.usuario.rol, self.rol_pac)
        self.assertTrue(hasattr(nuevo, 'ficha_clinica'))

    def test_crear_paciente_rechaza_rut_invalido(self):
        self.client.force_login(self.user_recep)
        resp = self.client.post(reverse('paciente_crear'), {
            'rut': '12.345.678-9',  # DV incorrecto
            'nombres': 'Pedro',
            'apellidos': 'Error',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Paciente.objects.filter(nombres='Pedro').exists())

    def test_rbac_fichas_bloquea_recepcion_y_oculta_notas_a_paciente(self):
        AtencionClinica.objects.create(
            fichaClinica=self.ficha,
            profesional=self.profesional,
            motivoConsulta='Ansiedad laboral',
            diagnostico='Trastorno adaptativo',
            evolucionNotas='NOTA PRIVADA DEL TERAPEUTA',
            indicacionesTratamiento='Higiene del sueño',
        )

        # Recepcionista no puede ver fichas clínicas
        self.client.force_login(self.user_recep)
        resp_recep = self.client.get(reverse('fichas_lista'))
        self.assertEqual(resp_recep.status_code, 302)

        # Paciente sí puede ver su ficha, pero NO las notas confidenciales
        self.client.force_login(self.user_pac)
        resp_pac = self.client.get(reverse('ficha_detalle', args=[self.ficha.id]))
        self.assertEqual(resp_pac.status_code, 200)
        html_pac = resp_pac.content.decode('utf-8')
        self.assertIn('Higiene del sueño', html_pac)
        self.assertNotIn('NOTA PRIVADA DEL TERAPEUTA', html_pac)

        # Profesional sí ve las notas confidenciales
        self.client.force_login(self.user_prof)
        resp_prof = self.client.get(reverse('ficha_detalle', args=[self.ficha.id]))
        self.assertEqual(resp_prof.status_code, 200)
        self.assertIn('NOTA PRIVADA DEL TERAPEUTA', resp_prof.content.decode('utf-8'))

    def test_agendamiento_colisiones_y_bloqueos(self):
        self.client.force_login(self.user_prof)
        manana = (timezone.localdate() + timedelta(days=2))
        fecha_str = manana.strftime('%Y-%m-%d')

        # 1. Agendar cita de 10:00 a 10:45 con telemedicina
        resp_ok = self.client.post(reverse('agendamiento'), {
            'paciente': self.paciente.id,
            'profesional': self.profesional.id,
            'fecha': fecha_str,
            'hora_inicio': '10:00',
            'duracion_minutos': 45,
            'es_telemedicina': True,
        })
        self.assertEqual(resp_ok.status_code, 302)
        self.assertEqual(Cita.objects.count(), 1)
        cita = Cita.objects.first()
        self.assertTrue(Videoconsulta.objects.filter(cita=cita).exists())

        # 2. Intentar agendar otra cita solapada (10:30 a 11:15) -> debe fallar
        resp_col = self.client.post(reverse('agendamiento'), {
            'paciente': self.paciente.id,
            'profesional': self.profesional.id,
            'fecha': fecha_str,
            'hora_inicio': '10:30',
            'duracion_minutos': 45,
        })
        self.assertEqual(resp_col.status_code, 200)
        self.assertEqual(Cita.objects.count(), 1)

        # 3. Intentar crear un BloqueoHorario encima de la cita (10:15 a 11:00) -> debe fallar
        self.client.post(reverse('bloqueo_crear'), {
            'profesional': self.profesional.id,
            'fecha': fecha_str,
            'hora_inicio': '10:15',
            'hora_fin': '11:00',
            'motivo': 'Reunión',
        })
        self.assertEqual(BloqueoHorario.objects.count(), 0)

        # 4. Crear BloqueoHorario válido de 12:00 a 13:00
        self.client.post(reverse('bloqueo_crear'), {
            'profesional': self.profesional.id,
            'fecha': fecha_str,
            'hora_inicio': '12:00',
            'hora_fin': '13:00',
            'motivo': 'Colación',
        })
        self.assertEqual(BloqueoHorario.objects.count(), 1)

        # 5. Intentar agendar cita durante el bloqueo (12:15 a 13:00) -> debe fallar
        resp_bloq = self.client.post(reverse('agendamiento'), {
            'paciente': self.paciente.id,
            'profesional': self.profesional.id,
            'fecha': fecha_str,
            'hora_inicio': '12:15',
            'duracion_minutos': 45,
        })
        self.assertEqual(resp_bloq.status_code, 200)
        self.assertEqual(Cita.objects.count(), 1)

        # 6. Consultar endpoint JSON de disponibilidad
        resp_json = self.client.get(
            reverse('agendamiento_disponibilidad'),
            {'profesional_id': self.profesional.id, 'fecha': fecha_str}
        )
        self.assertEqual(resp_json.status_code, 200)
        data = resp_json.json()
        self.assertEqual(len(data['ocupados']), 2)

    def test_registrar_atencion_vinculada_marca_cita_realizada(self):
        self.client.force_login(self.user_prof)
        inicio = timezone.now() + timedelta(hours=3)
        cita = Cita.objects.create(
            paciente=self.paciente,
            profesional=self.profesional,
            fechaHoraInicio=inicio,
            fechaHoraFin=inicio + timedelta(minutes=45),
            estado='Confirmada',
        )

        resp = self.client.post(reverse('atencion_crear', args=[self.ficha.id]), {
            'cita': cita.id,
            'profesional': self.profesional.id,
            'motivoConsulta': 'Control mensual',
            'diagnostico': 'Evolución favorable',
            'evolucionNotas': 'Paciente estable',
            'indicacionesTratamiento': 'Continuar terapia quincenal',
        })
        self.assertEqual(resp.status_code, 302)
        cita.refresh_from_db()
        self.assertEqual(cita.estado, 'Realizada')
        self.assertEqual(AtencionClinica.objects.filter(fichaClinica=self.ficha).count(), 1)


class CifradoYPartes3y4Tests(TestCase):
    def setUp(self):
        self.rol_admin = Rol.objects.create(nombre='Administrador')
        self.rol_prof = Rol.objects.create(nombre='Profesional')
        self.rol_pac = Rol.objects.create(nombre='Paciente')
        self.rol_recep = Rol.objects.create(nombre='Recepcionista')

        self.user_admin = Usuario.objects.create_superuser(
            username='admin1',
            email='admin1@centronodo.cl',
            password='password123',
            rol=self.rol_admin,
        )
        self.user_prof = Usuario.objects.create_user(
            username='prof_t',
            email='proft@centronodo.cl',
            password='password123',
            first_name='Camila',
            last_name='Rojas',
            rol=self.rol_prof,
        )
        self.profesional = Profesional.objects.create(
            usuario=self.user_prof,
            rut='17.654.321-3',
            nombres='Camila',
            apellidos='Rojas',
            especialidad='Psicología Clínica',
        )
        self.user_recep = Usuario.objects.create_user(
            username='recep_t',
            email='recept@centronodo.cl',
            password='password123',
            first_name='Sofía',
            last_name='Muñoz',
            rol=self.rol_recep,
        )
        self.user_pac = Usuario.objects.create_user(
            username='pac_t',
            email='pact@correo.cl',
            password='password123',
            first_name='Juan',
            last_name='Pérez',
            rol=self.rol_pac,
        )
        self.paciente = Paciente.objects.create(
            usuario=self.user_pac,
            rut='19.876.543-0',
            nombres='Juan',
            apellidos='Pérez',
        )
        self.ficha = FichaClinica.objects.create(
            paciente=self.paciente,
            antecedentesMedicos='Antecedente de insomnio crónico',
            alergias='Penicilina',
            grupoSanguineo='O+',
        )
        self.user_otro_pac = Usuario.objects.create_user(
            username='pac2_t',
            email='pac2t@correo.cl',
            password='password123',
            rol=self.rol_pac,
        )
        self.otro_paciente = Paciente.objects.create(
            usuario=self.user_otro_pac,
            rut='12.345.678-5',
            nombres='María',
            apellidos='Lagos',
        )
        FichaClinica.objects.create(paciente=self.otro_paciente)
        self.client = Client()

    def test_cifrado_en_reposo_bd_y_descifrado_transparente(self):
        atencion = AtencionClinica.objects.create(
            fichaClinica=self.ficha,
            profesional=self.profesional,
            motivoConsulta='Estrés laboral agudo',
            diagnostico='F43.0 Reacción al estrés agudo',
            evolucionNotas='NOTA SECRETA DE SESION',
            indicacionesTratamiento='Técnicas de respiración diaria',
        )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT antecedentesMedicos, alergias FROM ficha_clinica WHERE id = %s",
                [self.ficha.id],
            )
            raw_ant, raw_aler = cursor.fetchone()
            cursor.execute(
                "SELECT motivoConsulta, diagnostico, evolucionNotas, indicacionesTratamiento FROM atencion_clinica WHERE id = %s",
                [atencion.id],
            )
            raw_motivo, raw_diag, raw_notas, raw_indic = cursor.fetchone()

        self.assertTrue(raw_ant.startswith('enc::'))
        self.assertTrue(raw_aler.startswith('enc::'))
        self.assertTrue(raw_motivo.startswith('enc::'))
        self.assertTrue(raw_diag.startswith('enc::'))
        self.assertTrue(raw_notas.startswith('enc::'))
        self.assertTrue(raw_indic.startswith('enc::'))

        self.assertNotIn('insomnio', raw_ant)
        self.assertNotIn('Penicilina', raw_aler)
        self.assertNotIn('NOTA SECRETA DE SESION', raw_notas)

        ficha_db = FichaClinica.objects.get(pk=self.ficha.id)
        atencion_db = AtencionClinica.objects.get(pk=atencion.id)
        self.assertEqual(ficha_db.antecedentesMedicos, 'Antecedente de insomnio crónico')
        self.assertEqual(atencion_db.evolucionNotas, 'NOTA SECRETA DE SESION')
        self.assertEqual(decrypt_text('Texto plano antiguo'), 'Texto plano antiguo')
        self.assertIn('no válida', decrypt_text('enc::token-corrupto'))

    def test_dashboard_diferenciado_por_rol_y_privacidad(self):
        inicio = timezone.now() + timedelta(hours=2)
        cita = Cita.objects.create(
            paciente=self.paciente,
            profesional=self.profesional,
            fechaHoraInicio=inicio,
            fechaHoraFin=inicio + timedelta(minutes=45),
            estado='Confirmada',
        )
        Videoconsulta.objects.create(cita=cita, urlSalaWebRTC='sala-dash-01')
        Pago.objects.create(
            cita=cita,
            monto=Decimal('35000'),
            metodoPago='Transferencia',
            estado='Pagado',
            numeroComprobante='CMP-TEST-0001',
        )
        AtencionClinica.objects.create(
            fichaClinica=self.ficha,
            profesional=self.profesional,
            motivoConsulta='Consulta control',
            diagnostico='Evolución positiva',
            evolucionNotas='CONFIDENCIAL TERAPEUTA DASH',
            indicacionesTratamiento='Mantener controles mensuales',
        )

        # Profesional
        self.client.force_login(self.user_prof)
        r_prof = self.client.get(reverse('dashboard'))
        self.assertEqual(r_prof.status_code, 200)
        self.assertEqual(r_prof.context['tipo_dashboard'], 'profesional')
        self.assertIn('Próximas Videoconsultas', r_prof.content.decode('utf-8'))

        # Paciente (no debe recibir notas confidenciales ni montos de caja del centro)
        self.client.force_login(self.user_pac)
        r_pac = self.client.get(reverse('dashboard'))
        self.assertEqual(r_pac.status_code, 200)
        self.assertEqual(r_pac.context['tipo_dashboard'], 'paciente')
        html_pac = r_pac.content.decode('utf-8')
        self.assertIn('Mantener controles mensuales', html_pac)
        self.assertNotIn('CONFIDENCIAL TERAPEUTA DASH', html_pac)

        # Recepcionista
        self.client.force_login(self.user_recep)
        r_recep = self.client.get(reverse('dashboard'))
        self.assertEqual(r_recep.status_code, 200)
        self.assertEqual(r_recep.context['tipo_dashboard'], 'administracion')
        self.assertIn('$35.000', r_recep.content.decode('utf-8'))

        # Administrador
        self.client.force_login(self.user_admin)
        r_admin = self.client.get(reverse('dashboard'))
        self.assertEqual(r_admin.status_code, 200)
        self.assertEqual(r_admin.context['tipo_dashboard'], 'administracion')
        self.assertEqual(r_admin.context['total_atenciones'], 1)

    def test_telemedicina_sala_dual_ajax_y_estados(self):
        inicio = timezone.now() + timedelta(hours=1)
        cita = Cita.objects.create(
            paciente=self.paciente,
            profesional=self.profesional,
            fechaHoraInicio=inicio,
            fechaHoraFin=inicio + timedelta(minutes=45),
            estado='Confirmada',
        )
        vc = Videoconsulta.objects.create(cita=cita, urlSalaWebRTC='sala-dual-99', estadoConexion='Pendiente')

        # Recepcionista no tiene acceso a Telemedicina
        self.client.force_login(self.user_recep)
        self.assertEqual(self.client.get(reverse('telemedicina_sala', args=[vc.id])).status_code, 302)

        # Otro paciente tampoco tiene acceso
        self.client.force_login(self.user_otro_pac)
        self.assertEqual(self.client.get(reverse('telemedicina_sala', args=[vc.id])).status_code, 302)

        # Paciente titular ingresa -> estado cambia automáticamente de Pendiente a En espera
        self.client.force_login(self.user_pac)
        r_pac = self.client.get(reverse('telemedicina_sala', args=[vc.id]))
        self.assertEqual(r_pac.status_code, 200)
        vc.refresh_from_db()
        self.assertEqual(vc.estadoConexion, 'En espera')

        # Paciente no puede iniciar sesión ni guardar notas clínicas
        r_pac_estado = self.client.post(reverse('telemedicina_estado', args=[vc.id]), {'estadoConexion': 'En curso'})
        self.assertEqual(r_pac_estado.status_code, 403)
        r_pac_nota = self.client.post(
            reverse('telemedicina_sala', args=[vc.id]),
            {'motivoConsulta': 'x', 'diagnostico': 'y'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r_pac_nota.status_code, 403)

        # Profesional admite al paciente -> Videoconsulta 'En curso' y Cita 'En atención'
        self.client.force_login(self.user_prof)
        r_adm = self.client.post(
            reverse('telemedicina_estado', args=[vc.id]),
            {'estadoConexion': 'En curso'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r_adm.status_code, 200)
        vc.refresh_from_db()
        cita.refresh_from_db()
        self.assertEqual(vc.estadoConexion, 'En curso')
        self.assertEqual(cita.estado, 'En atención')

        # Guardado AJAX #1 de nota clínica en vivo (sin cortar el video)
        r_ajax1 = self.client.post(
            reverse('telemedicina_sala', args=[vc.id]),
            {
                'cita': cita.id,
                'profesional': self.profesional.id,
                'motivoConsulta': 'Duelo reciente',
                'diagnostico': 'Duelo no complicado',
                'evolucionNotas': 'NOTA CONFIDENCIAL EN VIVO',
                'indicacionesTratamiento': 'Control en 15 días',
                'accion_nota': 'guardar',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r_ajax1.status_code, 200)
        self.assertTrue(r_ajax1.json()['ok'])

        # Guardado AJAX #2 actualizado sobre la misma cita (verifica queryset con instancia existente)
        r_ajax2 = self.client.post(
            reverse('telemedicina_sala', args=[vc.id]),
            {
                'cita': cita.id,
                'profesional': self.profesional.id,
                'motivoConsulta': 'Duelo reciente actualizado',
                'diagnostico': 'Duelo no complicado',
                'evolucionNotas': 'NOTA CONFIDENCIAL EDITADA',
                'indicacionesTratamiento': 'Control semanal',
                'accion_nota': 'finalizar',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(r_ajax2.status_code, 200)
        self.assertTrue(r_ajax2.json()['ok'])
        self.assertEqual(AtencionClinica.objects.filter(cita=cita).count(), 1)
        atencion = AtencionClinica.objects.get(cita=cita)
        self.assertEqual(atencion.indicacionesTratamiento, 'Control semanal')
        vc.refresh_from_db()
        cita.refresh_from_db()
        self.assertEqual(vc.estadoConexion, 'Finalizada')
        self.assertEqual(cita.estado, 'Realizada')

        # Al volver el paciente a la sala, NO debe ver evolucionNotas en el HTML
        self.client.force_login(self.user_pac)
        r_pac_after = self.client.get(reverse('telemedicina_sala', args=[vc.id]))
        self.assertNotIn('NOTA CONFIDENCIAL EDITADA', r_pac_after.content.decode('utf-8'))

    def test_telemedicina_senalizacion_webrtc(self):
        inicio = timezone.now() + timedelta(hours=4)
        cita = Cita.objects.create(
            paciente=self.paciente,
            profesional=self.profesional,
            fechaHoraInicio=inicio,
            fechaHoraFin=inicio + timedelta(minutes=45),
        )
        vc = Videoconsulta.objects.create(cita=cita, urlSalaWebRTC='sala-webrtc-01', estadoConexion='En espera')

        # 1. Sala de Espera Virtual bloquea SDP/ICE mientras no esté 'En curso' (HTTP 409)
        self.client.force_login(self.user_prof)
        r_blocked_offer = self.client.post(
            reverse('telemedicina_senal', args=[vc.id]),
            data=json.dumps({'type': 'offer', 'sdp': {'type': 'offer', 'sdp': 'early-offer'}}),
            content_type='application/json',
        )
        self.assertEqual(r_blocked_offer.status_code, 409)

        # GET en sala de espera solo reporta presencia y estado, sin filtrar señales SDP
        self.client.force_login(self.user_pac)
        r_wait_guest = self.client.get(reverse('telemedicina_senal', args=[vc.id])).json()
        self.assertEqual(r_wait_guest['estadoConexion'], 'En espera')
        self.assertIsNone(r_wait_guest['offer'])
        self.assertEqual(r_wait_guest['remote_ice'], [])

        # 2. Especialista admite al paciente ('En curso') -> se habilita el intercambio WebRTC
        self.client.force_login(self.user_prof)
        self.client.post(reverse('telemedicina_estado', args=[vc.id]), {'estadoConexion': 'En curso'})

        r_offer = self.client.post(
            reverse('telemedicina_senal', args=[vc.id]),
            data=json.dumps({'type': 'offer', 'sdp': {'type': 'offer', 'sdp': 'fake-offer'}}),
            content_type='application/json',
        )
        self.assertEqual(r_offer.status_code, 200)

        # Guest obtiene offer y envía answer + ICE
        self.client.force_login(self.user_pac)
        r_get_guest = self.client.get(reverse('telemedicina_senal', args=[vc.id]))
        self.assertEqual(r_get_guest.json()['estadoConexion'], 'En curso')
        self.assertEqual(r_get_guest.json()['offer']['sdp'], 'fake-offer')
        self.client.post(
            reverse('telemedicina_senal', args=[vc.id]),
            data=json.dumps({'type': 'answer', 'sdp': {'type': 'answer', 'sdp': 'fake-answer'}}),
            content_type='application/json',
        )
        self.client.post(
            reverse('telemedicina_senal', args=[vc.id]),
            data=json.dumps({'type': 'ice', 'candidate': {'candidate': 'cand-guest-1'}}),
            content_type='application/json',
        )

        # Host recibe answer, ICE del paciente y peer_online=True
        self.client.force_login(self.user_prof)
        r_get_host = self.client.get(reverse('telemedicina_senal', args=[vc.id])).json()
        self.assertEqual(r_get_host['answer']['sdp'], 'fake-answer')
        self.assertEqual(len(r_get_host['remote_ice']), 1)
        self.assertTrue(r_get_host['peer_online'])

        # 3. Al finalizar sesión se limpia la caché de señalización y se vuelve a bloquear WebRTC
        self.client.post(reverse('telemedicina_estado', args=[vc.id]), {'estadoConexion': 'Finalizada'})
        self.assertIsNone(cache.get(f"webrtc_room_{vc.id}"))
        r_after_end = self.client.post(
            reverse('telemedicina_senal', args=[vc.id]),
            data=json.dumps({'type': 'offer', 'sdp': {'type': 'offer', 'sdp': 'late-offer'}}),
            content_type='application/json',
        )
        self.assertEqual(r_after_end.status_code, 409)

    def test_caja_pagos_liquidaciones_comprobante_y_csv(self):
        inicio = timezone.now() + timedelta(hours=5)
        cita1 = Cita.objects.create(
            paciente=self.paciente,
            profesional=self.profesional,
            fechaHoraInicio=inicio,
            fechaHoraFin=inicio + timedelta(minutes=45),
            estado='Realizada',
        )
        cita2 = Cita.objects.create(
            paciente=self.otro_paciente,
            profesional=self.profesional,
            fechaHoraInicio=inicio + timedelta(hours=2),
            fechaHoraFin=inicio + timedelta(hours=2, minutes=45),
            estado='Realizada',
        )

        # Recepcionista registra pago inmediato para cita1 y pendiente para cita2
        self.client.force_login(self.user_recep)
        r_p1 = self.client.post(reverse('caja'), {
            'cita': cita1.id,
            'monto': '50000',
            'prevision': 'Fonasa',
            'metodoPago': 'Transferencia',
            'estado': 'Pagado',
        })
        self.assertEqual(r_p1.status_code, 302)
        pago1 = Pago.objects.get(cita=cita1)
        self.assertTrue(pago1.numeroComprobante.startswith('CMP-'))
        self.assertEqual(pago1.registradoPor, self.user_recep)

        self.client.post(reverse('caja'), {
            'cita': cita2.id,
            'monto': '50000',
            'prevision': 'Particular',
            'metodoPago': 'Efectivo',
            'estado': 'Pendiente',
        })
        pago2 = Pago.objects.get(cita=cita2)
        # Confirmar pago pendiente
        self.client.post(reverse('pago_cambiar_estado', args=[pago2.id]), {'estado': 'Pagado'})
        pago2.refresh_from_db()
        self.assertEqual(pago2.estado, 'Pagado')

        # Profesional revisa sus honorarios con 30% comisión -> Bruto 100.000, Líquido 70.000
        self.client.force_login(self.user_prof)
        r_prof_caja = self.client.get(reverse('caja'), {'comision': 30})
        self.assertEqual(r_prof_caja.status_code, 200)
        liqs = r_prof_caja.context['liquidaciones']
        self.assertEqual(len(liqs), 1)
        self.assertEqual(liqs[0]['monto_bruto'], Decimal('100000'))
        self.assertEqual(liqs[0]['comision_centro'], Decimal('30000'))
        self.assertEqual(liqs[0]['liquido_profesional'], Decimal('70000'))

        # Paciente ve solo su comprobante, NO el de otro paciente, y NO puede exportar CSV
        self.client.force_login(self.user_pac)
        r_pac_caja = self.client.get(reverse('caja'))
        self.assertEqual(r_pac_caja.status_code, 200)
        self.assertEqual(r_pac_caja.context['pagos'].count(), 1)
        self.assertEqual(self.client.get(reverse('pago_comprobante', args=[pago1.id])).status_code, 200)
        self.assertEqual(self.client.get(reverse('pago_comprobante', args=[pago2.id])).status_code, 302)
        self.assertEqual(self.client.get(reverse('caja_exportar_csv')).status_code, 302)

        # Recepcionista exporta CSV
        self.client.force_login(self.user_recep)
        r_csv = self.client.get(reverse('caja_exportar_csv'))
        self.assertEqual(r_csv.status_code, 200)
        self.assertIn('text/csv', r_csv['Content-Type'])
        csv_text = r_csv.content.decode('utf-8-sig')
        self.assertIn(pago1.numeroComprobante, csv_text)
        self.assertIn('Juan Pérez', csv_text)


class Partes567Tests(TestCase):
    def setUp(self):
        self.rol_admin = Rol.objects.create(nombre='Administrador')
        self.rol_prof = Rol.objects.create(nombre='Profesional')
        self.rol_pac = Rol.objects.create(nombre='Paciente')
        self.rol_recep = Rol.objects.create(nombre='Recepcionista')

        self.user_prof1 = Usuario.objects.create_user(
            username='prof_p5',
            email='profp5@centronodo.cl',
            password='password123',
            first_name='Andrés',
            last_name='Silva',
            rol=self.rol_prof,
        )
        self.profesional1 = Profesional.objects.create(
            usuario=self.user_prof1,
            rut='15.342.980-4',
            nombres='Andrés',
            apellidos='Silva',
            especialidad='Psiquiatría',
            registro_salud='SIS-4455',
        )

        self.user_prof2 = Usuario.objects.create_user(
            username='prof2_p5',
            email='prof2p5@centronodo.cl',
            password='password123',
            first_name='Camila',
            last_name='Rojas',
            rol=self.rol_prof,
        )
        self.profesional2 = Profesional.objects.create(
            usuario=self.user_prof2,
            rut='17.654.321-3',
            nombres='Camila',
            apellidos='Rojas',
            especialidad='Psicología Clínica',
        )

        self.user_recep = Usuario.objects.create_user(
            username='recep_p5',
            email='recepp5@centronodo.cl',
            password='password123',
            rol=self.rol_recep,
        )

        self.user_pac = Usuario.objects.create_user(
            username='pac_p5',
            email='pacp5@correo.cl',
            password='password123',
            first_name='Juan',
            last_name='Pérez',
            rol=self.rol_pac,
        )
        self.paciente = Paciente.objects.create(
            usuario=self.user_pac,
            rut='19.876.543-0',
            nombres='Juan',
            apellidos='Pérez',
        )
        self.ficha = FichaClinica.objects.create(paciente=self.paciente)

        self.user_otro_pac = Usuario.objects.create_user(
            username='pac2_p5',
            email='pac2p5@correo.cl',
            password='password123',
            rol=self.rol_pac,
        )
        self.otro_paciente = Paciente.objects.create(
            usuario=self.user_otro_pac,
            rut='12.345.678-5',
            nombres='María',
            apellidos='Lagos',
        )
        FichaClinica.objects.create(paciente=self.otro_paciente)

        self.paciente_sin_email = Paciente.objects.create(
            usuario=None,
            rut='11.222.333-9',
            nombres='Carlos',
            apellidos='Soto',
        )
        FichaClinica.objects.create(paciente=self.paciente_sin_email)

        self.client = Client()

    def test_documentos_clinicos_y_privacidad(self):
        inicio = timezone.now() - timedelta(hours=2)
        cita = Cita.objects.create(
            paciente=self.paciente,
            profesional=self.profesional1,
            fechaHoraInicio=inicio,
            fechaHoraFin=inicio + timedelta(minutes=45),
            estado='Realizada',
        )
        atencion = AtencionClinica.objects.create(
            fichaClinica=self.ficha,
            cita=cita,
            profesional=self.profesional1,
            motivoConsulta='Consulta por insomnio crónico',
            diagnostico='DIAGNOSTICO SENSIBLE TEST',
            evolucionNotas='EVOLUCION CONFIDENCIAL SOLO CLINICO',
            indicacionesTratamiento='Higiene del sueño y control en 14 días',
        )

        # Recepcionista y otro paciente NO pueden emitir documentos clínicos
        self.client.force_login(self.user_recep)
        self.assertEqual(self.client.get(reverse('atencion_documento', args=[atencion.id])).status_code, 302)

        self.client.force_login(self.user_otro_pac)
        self.assertEqual(self.client.get(reverse('atencion_documento', args=[atencion.id])).status_code, 302)

        # Paciente titular en modo 'indicaciones': ve diagnóstico e indicaciones, NUNCA evolucionNotas
        self.client.force_login(self.user_pac)
        r_ind = self.client.get(reverse('atencion_documento', args=[atencion.id]), {'tipo': 'indicaciones'})
        self.assertEqual(r_ind.status_code, 200)
        html_ind = r_ind.content.decode('utf-8')
        self.assertIn('DIAGNOSTICO SENSIBLE TEST', html_ind)
        self.assertIn('Higiene del sueño y control en 14 días', html_ind)
        self.assertNotIn('EVOLUCION CONFIDENCIAL SOLO CLINICO', html_ind)

        # Paciente titular en modo 'certificado': omite diagnóstico, indicaciones y evolucionNotas
        r_cert = self.client.get(reverse('atencion_documento', args=[atencion.id]), {'tipo': 'certificado'})
        self.assertEqual(r_cert.status_code, 200)
        html_cert = r_cert.content.decode('utf-8')
        self.assertIn('CERTIFICADO DE ASISTENCIA A CONSULTA', html_cert)
        self.assertIn('19.876.543-0', html_cert)
        self.assertIn('SIS-4455', html_cert)
        self.assertNotIn('DIAGNOSTICO SENSIBLE TEST', html_cert)
        self.assertNotIn('Higiene del sueño y control en 14 días', html_cert)
        self.assertNotIn('EVOLUCION CONFIDENCIAL SOLO CLINICO', html_cert)

        # Profesional sí accede pero el entregable impreso jamás incluye evolucionNotas
        self.client.force_login(self.user_prof1)
        r_prof = self.client.get(reverse('atencion_documento', args=[atencion.id]), {'tipo': 'indicaciones'})
        self.assertEqual(r_prof.status_code, 200)
        self.assertNotIn('EVOLUCION CONFIDENCIAL SOLO CLINICO', r_prof.content.decode('utf-8'))

    def test_caja_reporte_liquidacion_y_rbac(self):
        inicio = timezone.now() - timedelta(hours=3)
        c1 = Cita.objects.create(
            paciente=self.paciente,
            profesional=self.profesional1,
            fechaHoraInicio=inicio,
            fechaHoraFin=inicio + timedelta(minutes=45),
            estado='Realizada',
        )
        c2 = Cita.objects.create(
            paciente=self.otro_paciente,
            profesional=self.profesional2,
            fechaHoraInicio=inicio + timedelta(hours=1),
            fechaHoraFin=inicio + timedelta(hours=1, minutes=45),
            estado='Realizada',
        )
        Pago.objects.create(
            cita=c1, monto=Decimal('60000'), metodoPago='Transferencia', estado='Pagado', numeroComprobante='CMP-REP-1'
        )
        Pago.objects.create(
            cita=c2, monto=Decimal('40000'), metodoPago='Débito', estado='Pagado', numeroComprobante='CMP-REP-2'
        )

        # Paciente no puede acceder al reporte financiero de liquidación
        self.client.force_login(self.user_pac)
        self.assertEqual(self.client.get(reverse('caja_reporte_liquidacion')).status_code, 302)

        # Profesional 1 solo ve sus propios honorarios
        self.client.force_login(self.user_prof1)
        r_prof = self.client.get(reverse('caja_reporte_liquidacion'), {'comision': 30})
        self.assertEqual(r_prof.status_code, 200)
        self.assertEqual(r_prof.context['total_recaudado'], Decimal('60000'))
        self.assertEqual(r_prof.context['total_comision'], Decimal('18000'))
        self.assertEqual(r_prof.context['total_liquido'], Decimal('42000'))
        self.assertEqual(len(r_prof.context['liquidaciones']), 1)

        # Recepcionista ve reporte consolidado de ambos especialistas
        self.client.force_login(self.user_recep)
        r_recep = self.client.get(reverse('caja_reporte_liquidacion'), {'comision': 25})
        self.assertEqual(r_recep.status_code, 200)
        self.assertEqual(r_recep.context['total_recaudado'], Decimal('100000'))
        self.assertEqual(r_recep.context['total_comision'], Decimal('25000'))
        self.assertEqual(r_recep.context['total_liquido'], Decimal('75000'))
        self.assertEqual(len(r_recep.context['liquidaciones']), 2)
        html_rep = r_recep.content.decode('utf-8')
        self.assertIn('CMP-REP-1', html_rep)
        self.assertIn('CMP-REP-2', html_rep)

    def test_notificaciones_automaticas_manuales_y_recordatorios(self):
        mail.outbox.clear()
        self.client.force_login(self.user_recep)
        fecha_str = (timezone.localdate() + timedelta(days=3)).strftime('%Y-%m-%d')

        # 1. Al agendar cita se envían correos automáticos al paciente y profesional
        r_ag = self.client.post(reverse('agendamiento'), {
            'paciente': self.paciente.id,
            'profesional': self.profesional1.id,
            'fecha': fecha_str,
            'hora_inicio': '15:00',
            'duracion_minutos': 45,
            'es_telemedicina': True,
        })
        self.assertEqual(r_ag.status_code, 302)
        cita = Cita.objects.first()
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(NotificacionCita.objects.filter(cita=cita, tipo='Agendamiento', exitoso=True).count(), 2)

        # 2. Al confirmar cita se envía correo de Confirmación al paciente
        mail.outbox.clear()
        self.client.post(reverse('cita_cambiar_estado', args=[cita.id]), {'estado': 'Confirmada'})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['pacp5@correo.cl'])
        self.assertTrue(NotificacionCita.objects.filter(cita=cita, tipo='Confirmación', exitoso=True).exists())

        # 3. Envío manual de recordatorio desde Agenda
        mail.outbox.clear()
        r_rec = self.client.post(reverse('cita_enviar_recordatorio', args=[cita.id]))
        self.assertEqual(r_rec.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(NotificacionCita.objects.filter(cita=cita, tipo='Recordatorio', exitoso=True).exists())

        # 4. Paciente sin correo registrado no rompe el flujo de recordatorio manual
        cita_sin_email = Cita.objects.create(
            paciente=self.paciente_sin_email,
            profesional=self.profesional1,
            fechaHoraInicio=timezone.now() + timedelta(hours=10),
            fechaHoraFin=timezone.now() + timedelta(hours=10, minutes=45),
            estado='Agendada',
        )
        mail.outbox.clear()
        r_sin_mail = self.client.post(reverse('cita_enviar_recordatorio', args=[cita_sin_email.id]))
        self.assertEqual(r_sin_mail.status_code, 302)
        self.assertEqual(len(mail.outbox), 0)

        # 5. Al cancelar cita se notifica al paciente y al profesional
        self.client.post(reverse('cita_cambiar_estado', args=[cita.id]), {'estado': 'Cancelada'})
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(NotificacionCita.objects.filter(cita=cita, tipo='Cancelación', exitoso=True).count(), 2)

        # 6. Comando programar recordatorios 24h sin duplicados
        mail.outbox.clear()
        cita_elegible = Cita.objects.create(
            paciente=self.otro_paciente,
            profesional=self.profesional2,
            fechaHoraInicio=timezone.now() + timedelta(hours=12),
            fechaHoraFin=timezone.now() + timedelta(hours=12, minutes=45),
            estado='Confirmada',
        )
        # Cita fuera de ventana (> 24h)
        Cita.objects.create(
            paciente=self.otro_paciente,
            profesional=self.profesional2,
            fechaHoraInicio=timezone.now() + timedelta(hours=40),
            fechaHoraFin=timezone.now() + timedelta(hours=40, minutes=45),
            estado='Agendada',
        )
        # Cita cancelada en ventana (no debe enviarse)
        Cita.objects.create(
            paciente=self.otro_paciente,
            profesional=self.profesional1,
            fechaHoraInicio=timezone.now() + timedelta(hours=8),
            fechaHoraFin=timezone.now() + timedelta(hours=8, minutes=45),
            estado='Cancelada',
        )

        out = StringIO()
        call_command('enviar_recordatorios_citas', horas=24, stdout=out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['pac2p5@correo.cl'])
        self.assertTrue(NotificacionCita.objects.filter(cita=cita_elegible, tipo='Recordatorio', exitoso=True).exists())

        # Segunda ejecución en la misma ventana no duplica recordatorios
        mail.outbox.clear()
        out2 = StringIO()
        call_command('enviar_recordatorios_citas', horas=24, stdout=out2)
        self.assertEqual(len(mail.outbox), 0)


class SuiteCompleta7FasesYSeguridadTests(TestCase):
    """
    Pruebas integrales de seguridad, RBAC, colisiones límite de agenda y flujos
    cruzados a través de las 7 Fases del sistema.
    """

    def setUp(self):
        self.rol_admin = Rol.objects.create(nombre='Administrador')
        self.rol_prof = Rol.objects.create(nombre='Profesional')
        self.rol_pac = Rol.objects.create(nombre='Paciente')
        self.rol_recep = Rol.objects.create(nombre='Recepcionista')

        self.user_prof1 = Usuario.objects.create_user(
            username='prof1_s',
            email='prof1s@centronodo.cl',
            password='password123',
            first_name='Andrés',
            last_name='Silva',
            rol=self.rol_prof,
        )
        self.prof1 = Profesional.objects.create(
            usuario=self.user_prof1,
            rut='15.342.980-4',
            nombres='Andrés',
            apellidos='Silva',
            especialidad='Psiquiatría',
        )

        self.user_prof2 = Usuario.objects.create_user(
            username='prof2_s',
            email='prof2s@centronodo.cl',
            password='password123',
            first_name='Camila',
            last_name='Rojas',
            rol=self.rol_prof,
        )
        self.prof2 = Profesional.objects.create(
            usuario=self.user_prof2,
            rut='17.654.321-3',
            nombres='Camila',
            apellidos='Rojas',
            especialidad='Psicología Clínica',
        )

        self.user_recep = Usuario.objects.create_user(
            username='recep_s',
            email='receps@centronodo.cl',
            password='password123',
            rol=self.rol_recep,
        )

        self.user_pac1 = Usuario.objects.create_user(
            username='pac1_s',
            email='pac1s@correo.cl',
            password='password123',
            first_name='Juan',
            last_name='Pérez',
            rol=self.rol_pac,
        )
        self.pac1 = Paciente.objects.create(
            usuario=self.user_pac1,
            rut='19.876.543-0',
            nombres='Juan',
            apellidos='Pérez',
        )
        self.ficha1 = FichaClinica.objects.create(
            paciente=self.pac1,
            antecedentesMedicos='Antecedente privado pac1',
        )

        self.user_pac2 = Usuario.objects.create_user(
            username='pac2_s',
            email='pac2s@correo.cl',
            password='password123',
            first_name='María',
            last_name='Lagos',
            rol=self.rol_pac,
        )
        self.pac2 = Paciente.objects.create(
            usuario=self.user_pac2,
            rut='12.345.678-5',
            nombres='María',
            apellidos='Lagos',
        )
        self.ficha2 = FichaClinica.objects.create(
            paciente=self.pac2,
            antecedentesMedicos='Antecedente privado pac2',
        )

        self.user_inactivo = Usuario.objects.create_user(
            username='inactivo_s',
            email='inactivos@correo.cl',
            password='password123',
            rol=self.rol_pac,
            activo=False,
        )

        self.client = Client()

    def test_fase0_autenticacion_y_rutas_protegidas(self):
        rutas_privadas = [
            reverse('dashboard'),
            reverse('pacientes_lista'),
            reverse('fichas_lista'),
            reverse('agendamiento'),
            reverse('telemedicina'),
            reverse('caja'),
            reverse('caja_reporte_liquidacion'),
        ]
        for ruta in rutas_privadas:
            resp = self.client.get(ruta)
            self.assertEqual(resp.status_code, 302, f"La ruta {ruta} debe exigir login")
            self.assertIn(reverse('login'), resp.url)

        # Login por username; GET /logout/ rechazado (405) y POST /logout/ cierra sesión con CSRF
        r_user = self.client.post(reverse('login'), {'login_id': 'pac1_s', 'password': 'password123'})
        self.assertEqual(r_user.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user_pac1.id)
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        self.assertIn('_auth_user_id', self.client.session)
        self.client.post(reverse('logout'))
        self.assertNotIn('_auth_user_id', self.client.session)

        # Login por correo electrónico
        r_mail = self.client.post(reverse('login'), {'login_id': 'pac1s@correo.cl', 'password': 'password123'})
        self.assertEqual(r_mail.status_code, 302)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user_pac1.id)
        self.client.post(reverse('logout'))

        # Usuario inactivo no puede iniciar sesión
        r_inact = self.client.post(reverse('login'), {'login_id': 'inactivos@correo.cl', 'password': 'password123'})
        self.assertEqual(r_inact.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_fase1_acceso_cruzado_fichas_y_rut_duplicado(self):
        # 1. Rechazar creación de paciente con RUT ya existente (con distinto formato)
        self.client.force_login(self.user_recep)
        total_antes = Paciente.objects.count()
        r_dup = self.client.post(reverse('paciente_crear'), {
            'rut': '19876543-0',
            'nombres': 'Clon',
            'apellidos': 'Duplicado',
        })
        self.assertEqual(r_dup.status_code, 200)
        self.assertEqual(Paciente.objects.count(), total_antes)

        # 2. Recepcionista NO puede leer ni editar fichas ni registrar atenciones directamente
        self.assertEqual(self.client.get(reverse('ficha_detalle', args=[self.ficha1.id])).status_code, 302)
        self.client.post(
            reverse('ficha_editar_antecedentes', args=[self.ficha1.id]),
            {'grupoSanguineo': 'AB-', 'alergias': 'HACK', 'antecedentesMedicos': 'HACK'},
        )
        self.client.post(
            reverse('atencion_crear', args=[self.ficha1.id]),
            {'profesional': self.prof1.id, 'motivoConsulta': 'x', 'diagnostico': 'y'},
        )
        self.ficha1.refresh_from_db()
        self.assertEqual(self.ficha1.antecedentesMedicos, 'Antecedente privado pac1')
        self.assertEqual(AtencionClinica.objects.filter(fichaClinica=self.ficha1).count(), 0)

        # 3. Paciente 1 entra a /fichas/ -> redirige exclusivamente a su propia ficha
        self.client.force_login(self.user_pac1)
        r_list_pac1 = self.client.get(reverse('fichas_lista'))
        self.assertRedirects(r_list_pac1, reverse('ficha_detalle', args=[self.ficha1.id]))

        # 4. Paciente 2 NO puede ver ni modificar ficha ni perfil del Paciente 1
        self.client.force_login(self.user_pac2)
        self.assertEqual(self.client.get(reverse('ficha_detalle', args=[self.ficha1.id])).status_code, 302)
        self.assertEqual(self.client.get(reverse('paciente_detalle', args=[self.pac1.id])).status_code, 302)
        self.assertEqual(self.client.get(reverse('paciente_crear')).status_code, 302)

        self.client.post(
            reverse('ficha_editar_antecedentes', args=[self.ficha1.id]),
            {'grupoSanguineo': 'O-', 'alergias': 'HACK', 'antecedentesMedicos': 'ALTERADO'},
        )
        self.ficha1.refresh_from_db()
        self.assertEqual(self.ficha1.antecedentesMedicos, 'Antecedente privado pac1')

    def test_fase2_colisiones_paciente_bordes_y_cancelacion(self):
        manana = (timezone.localdate() + timedelta(days=3)).strftime('%Y-%m-%d')
        ayer = (timezone.localdate() - timedelta(days=1)).strftime('%Y-%m-%d')

        self.client.force_login(self.user_recep)

        # 1. Rechazar cita en fecha pasada
        r_past = self.client.post(reverse('agendamiento'), {
            'paciente': self.pac1.id,
            'profesional': self.prof1.id,
            'fecha': ayer,
            'hora_inicio': '10:00',
            'duracion_minutos': 45,
        })
        self.assertEqual(r_past.status_code, 200)
        self.assertEqual(Cita.objects.count(), 0)

        # 2. Cita base: pac1 con prof1 de 14:00 a 14:45
        r_base = self.client.post(reverse('agendamiento'), {
            'paciente': self.pac1.id,
            'profesional': self.prof1.id,
            'fecha': manana,
            'hora_inicio': '14:00',
            'duracion_minutos': 45,
        })
        self.assertEqual(r_base.status_code, 302)
        self.assertEqual(Cita.objects.count(), 1)
        cita_base = Cita.objects.first()

        # 3. Mismo paciente pac1 con OTRO profesional (prof2) en horario solapado (14:15 - 15:00) -> rechazado
        r_same_pac = self.client.post(reverse('agendamiento'), {
            'paciente': self.pac1.id,
            'profesional': self.prof2.id,
            'fecha': manana,
            'hora_inicio': '14:15',
            'duracion_minutos': 45,
        })
        self.assertEqual(r_same_pac.status_code, 200)
        self.assertEqual(Cita.objects.count(), 1)

        # 4. Solapamiento previo parcial (13:30 - 14:15 con prof1) -> rechazado
        r_prev_overlap = self.client.post(reverse('agendamiento'), {
            'paciente': self.pac2.id,
            'profesional': self.prof1.id,
            'fecha': manana,
            'hora_inicio': '13:30',
            'duracion_minutos': 45,
        })
        self.assertEqual(r_prev_overlap.status_code, 200)
        self.assertEqual(Cita.objects.count(), 1)

        # 5. Horario contiguo exacto al término (14:45 - 15:30 con prof1 para pac2) -> permitido
        r_edge = self.client.post(reverse('agendamiento'), {
            'paciente': self.pac2.id,
            'profesional': self.prof1.id,
            'fecha': manana,
            'hora_inicio': '14:45',
            'duracion_minutos': 45,
        })
        self.assertEqual(r_edge.status_code, 302)
        self.assertEqual(Cita.objects.count(), 2)

        # 6. Cancelar cita_base libera el bloque de 14:00 a 14:45 para otro paciente
        self.client.post(reverse('cita_cambiar_estado', args=[cita_base.id]), {'estado': 'Cancelada'})
        cita_base.refresh_from_db()
        self.assertEqual(cita_base.estado, 'Cancelada')

        r_rebook = self.client.post(reverse('agendamiento'), {
            'paciente': self.pac2.id,
            'profesional': self.prof1.id,
            'fecha': manana,
            'hora_inicio': '14:00',
            'duracion_minutos': 45,
        })
        self.assertEqual(r_rebook.status_code, 302)
        self.assertEqual(Cita.objects.filter(estado='Agendada').count(), 2)

        # 7. Bloqueo horario: crear, verificar rechazo y eliminar para liberar el bloque
        self.client.post(reverse('bloqueo_crear'), {
            'profesional': self.prof2.id,
            'fecha': manana,
            'hora_inicio': '16:00',
            'hora_fin': '17:00',
            'motivo': 'Comité',
        })
        bloqueo = BloqueoHorario.objects.first()

        # Paciente no puede eliminar bloqueos ni cancelar citas de otro paciente ni agendar por otro paciente
        self.client.force_login(self.user_pac1)
        self.client.post(reverse('bloqueo_eliminar', args=[bloqueo.id]))
        bloqueo.refresh_from_db()
        self.assertEqual(bloqueo.estado, 'Activo')

        cita_pac2 = Cita.objects.filter(paciente=self.pac2, estado='Agendada').first()
        self.client.post(reverse('cita_cambiar_estado', args=[cita_pac2.id]), {'estado': 'Cancelada'})
        cita_pac2.refresh_from_db()
        self.assertEqual(cita_pac2.estado, 'Agendada')

        # Si pac1 intenta enviar paciente=pac2 en POST, el formulario rechaza el ID ajeno
        total_citas_antes = Cita.objects.count()
        r_forged = self.client.post(reverse('agendamiento'), {
            'paciente': self.pac2.id,
            'profesional': self.prof2.id,
            'fecha': manana,
            'hora_inicio': '11:00',
            'duracion_minutos': 45,
        })
        self.assertEqual(r_forged.status_code, 200)
        self.assertEqual(Cita.objects.count(), total_citas_antes)

        # Y si pac1 envía su propio ID, agenda correctamente
        r_self = self.client.post(reverse('agendamiento'), {
            'paciente': self.pac1.id,
            'profesional': self.prof2.id,
            'fecha': manana,
            'hora_inicio': '11:00',
            'duracion_minutos': 45,
        })
        self.assertEqual(r_self.status_code, 302)
        cita_nueva = Cita.objects.order_by('-id').first()
        self.assertEqual(cita_nueva.paciente, self.pac1)

        # Recepcionista desactiva bloqueo y vuelve a estar disponible 16:00 - 16:45
        self.client.force_login(self.user_recep)
        self.client.post(reverse('bloqueo_eliminar', args=[bloqueo.id]))
        bloqueo.refresh_from_db()
        self.assertEqual(bloqueo.estado, 'Inactivo')
        r_after_unblock = self.client.post(reverse('agendamiento'), {
            'paciente': self.pac1.id,
            'profesional': self.prof2.id,
            'fecha': manana,
            'hora_inicio': '16:00',
            'duracion_minutos': 45,
        })
        self.assertEqual(r_after_unblock.status_code, 302)

    def test_fase4_caja_anulacion_y_permisos_escritura(self):
        inicio = timezone.now() + timedelta(hours=4)
        cita = Cita.objects.create(
            paciente=self.pac1,
            profesional=self.prof1,
            fechaHoraInicio=inicio,
            fechaHoraFin=inicio + timedelta(minutes=45),
            estado='Realizada',
        )
        pago = Pago.objects.create(
            cita=cita,
            monto=Decimal('45000'),
            metodoPago='Transferencia',
            estado='Pagado',
            numeroComprobante='CMP-ANUL-01',
        )

        # Paciente y Profesional NO pueden crear ni anular pagos
        for u in [self.user_pac1, self.user_prof1]:
            self.client.force_login(u)
            self.client.post(reverse('caja'), {
                'cita': cita.id, 'monto': '10000', 'prevision': 'Particular', 'metodoPago': 'Efectivo', 'estado': 'Pagado'
            })
            self.assertEqual(Pago.objects.count(), 1)
            self.client.post(reverse('pago_cambiar_estado', args=[pago.id]), {'estado': 'Anulado'})
            pago.refresh_from_db()
            self.assertEqual(pago.estado, 'Pagado')

        # Recepcionista anula pago y desaparece del cálculo de liquidación/reporte
        self.client.force_login(self.user_recep)
        self.client.post(reverse('pago_cambiar_estado', args=[pago.id]), {'estado': 'Anulado'})
        pago.refresh_from_db()
        self.assertEqual(pago.estado, 'Anulado')

        r_rep = self.client.get(reverse('caja_reporte_liquidacion'))
        self.assertEqual(r_rep.status_code, 200)
        self.assertEqual(r_rep.context['total_recaudado'], Decimal('0'))
        self.assertEqual(len(r_rep.context['liquidaciones']), 0)

    def test_fase5_telemedicina_aislamiento_salas_y_senal_403(self):
        inicio = timezone.now() + timedelta(hours=2)
        c1 = Cita.objects.create(
            paciente=self.pac1, profesional=self.prof1, fechaHoraInicio=inicio, fechaHoraFin=inicio + timedelta(minutes=45)
        )
        c2 = Cita.objects.create(
            paciente=self.pac2, profesional=self.prof2, fechaHoraInicio=inicio, fechaHoraFin=inicio + timedelta(minutes=45)
        )
        vc1 = Videoconsulta.objects.create(cita=c1, urlSalaWebRTC='sala-iso-1', estadoConexion='En curso')
        Videoconsulta.objects.create(cita=c2, urlSalaWebRTC='sala-iso-2', estadoConexion='En curso')

        # Listado filtrado por rol
        self.client.force_login(self.user_pac1)
        r_list = self.client.get(reverse('telemedicina'))
        self.assertEqual(r_list.status_code, 200)
        self.assertEqual(list(r_list.context['videoconsultas']), [vc1])

        # Otro paciente y Recepcionista reciben 403 en endpoints WebRTC de vc1
        for u in [self.user_pac2, self.user_recep]:
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse('telemedicina_senal', args=[vc1.id])).status_code, 403)
            self.assertEqual(
                self.client.post(reverse('telemedicina_estado', args=[vc1.id]), {'estadoConexion': 'Finalizada'}).status_code,
                403,
            )

    def test_fase7_recordatorios_dry_run_no_envia(self):
        mail.outbox.clear()
        Cita.objects.create(
            paciente=self.pac1,
            profesional=self.prof1,
            fechaHoraInicio=timezone.now() + timedelta(hours=6),
            fechaHoraFin=timezone.now() + timedelta(hours=6, minutes=45),
            estado='Agendada',
        )
        out = StringIO()
        call_command('enviar_recordatorios_citas', horas=24, dry_run=True, stdout=out)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(NotificacionCita.objects.count(), 0)
        self.assertIn('[DRY-RUN]', out.getvalue())


class HardeningSeguridadLimitesTests(TestCase):
    """
    Pruebas de endurecimiento (security hardening): límites de caracteres en formularios,
    mitigación de fuzzing/SQLi en parámetros GET, métodos POST obligatorios (anti-CSRF),
    protección CSV Formula Injection, validación WebRTC y reglas de negocio estrictas.
    """

    def setUp(self):
        self.rol_admin = Rol.objects.create(nombre='Administrador')
        self.rol_prof = Rol.objects.create(nombre='Profesional')
        self.rol_pac = Rol.objects.create(nombre='Paciente')
        self.rol_recep = Rol.objects.create(nombre='Recepcionista')

        self.user_prof = Usuario.objects.create_user(
            username='prof_h',
            email='profh@centronodo.cl',
            password='password123',
            first_name='Andrés',
            last_name='Silva',
            rol=self.rol_prof,
        )
        self.prof = Profesional.objects.create(
            usuario=self.user_prof,
            rut='15.342.980-4',
            nombres='Andrés',
            apellidos='Silva',
            especialidad='Psiquiatría',
        )
        self.user_recep = Usuario.objects.create_user(
            username='recep_h',
            email='receph@centronodo.cl',
            password='password123',
            rol=self.rol_recep,
        )
        self.user_pac = Usuario.objects.create_user(
            username='pac_h',
            email='pach@correo.cl',
            password='password123',
            first_name='Juan',
            last_name='Pérez',
            rol=self.rol_pac,
        )
        self.pac = Paciente.objects.create(
            usuario=self.user_pac,
            rut='19.876.543-0',
            nombres='Juan',
            apellidos='Pérez',
        )
        self.ficha = FichaClinica.objects.create(paciente=self.pac)
        self.client = Client()

    def test_configuracion_seguridad_y_headers_http(self):
        self.assertNotIn('*', settings.ALLOWED_HOSTS)
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertEqual(settings.X_FRAME_OPTIONS, 'DENY')
        self.assertLessEqual(settings.DATA_UPLOAD_MAX_MEMORY_SIZE, 2 * 1024 * 1024)

        resp = self.client.get(reverse('login'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get('X-Frame-Options'), 'DENY')
        self.assertEqual(resp.headers.get('X-Content-Type-Options'), 'nosniff')

    def test_vistas_mutadoras_exigen_post(self):
        inicio = timezone.now() + timedelta(hours=3)
        cita = Cita.objects.create(
            paciente=self.pac,
            profesional=self.prof,
            fechaHoraInicio=inicio,
            fechaHoraFin=inicio + timedelta(minutes=45),
        )
        vc = Videoconsulta.objects.create(cita=cita, urlSalaWebRTC='sala-post-only')
        bloqueo = BloqueoHorario.objects.create(
            profesional=self.prof,
            fechaHoraInicio=inicio + timedelta(days=1),
            fechaHoraFin=inicio + timedelta(days=1, hours=1),
            motivo='Comité',
        )
        pago = Pago.objects.create(cita=cita, monto=Decimal('30000'), estado='Pendiente')

        self.client.force_login(self.user_prof)
        endpoints_prof = [
            reverse('logout'),
            reverse('ficha_editar_antecedentes', args=[self.ficha.id]),
            reverse('atencion_crear', args=[self.ficha.id]),
            reverse('cita_cambiar_estado', args=[cita.id]),
            reverse('cita_enviar_recordatorio', args=[cita.id]),
            reverse('bloqueo_crear'),
            reverse('bloqueo_eliminar', args=[bloqueo.id]),
            reverse('telemedicina_estado', args=[vc.id]),
        ]
        for url in endpoints_prof:
            self.assertEqual(self.client.get(url).status_code, 405, f"{url} debe rechazar GET con 405")

        self.client.force_login(self.user_recep)
        self.assertEqual(self.client.get(reverse('pago_cambiar_estado', args=[pago.id])).status_code, 405)

    def test_fuzzing_sqli_en_parametros_get_no_genera_500(self):
        payload_sqli = "' OR '1'='1'; DROP TABLE cita; --"
        query_larga = "A" * 300

        self.client.force_login(self.user_prof)
        self.assertEqual(self.client.get(reverse('pacientes_lista'), {'q': payload_sqli}).status_code, 200)
        self.assertEqual(self.client.get(reverse('pacientes_lista'), {'q': query_larga}).status_code, 200)
        self.assertEqual(self.client.get(reverse('fichas_lista'), {'q': payload_sqli}).status_code, 200)
        self.assertEqual(self.client.get(reverse('ficha_detalle', args=[self.ficha.id]), {'cita_id': payload_sqli}).status_code, 200)

        r_ag = self.client.get(reverse('agendamiento'), {
            'profesional': payload_sqli,
            'fecha': payload_sqli,
            'estado': payload_sqli,
            'paciente_id': payload_sqli,
        })
        self.assertEqual(r_ag.status_code, 200)
        self.assertEqual(r_ag.context['citas'].count(), 0)

        r_disp = self.client.get(reverse('agendamiento_disponibilidad'), {
            'profesional_id': payload_sqli,
            'fecha': '2026-11-12',
        })
        self.assertEqual(r_disp.status_code, 400)

        self.client.force_login(self.user_recep)
        r_caja = self.client.get(reverse('caja'), {
            'fecha': payload_sqli,
            'estado': payload_sqli,
            'metodo': payload_sqli,
            'cita_id': payload_sqli,
            'comision': 'NaN',
        })
        self.assertEqual(r_caja.status_code, 200)
        self.assertEqual(r_caja.context['pagos'].count(), 0)
        self.assertEqual(self.client.get(reverse('caja_exportar_csv'), {'estado': payload_sqli}).status_code, 200)
        self.assertEqual(self.client.get(reverse('caja_reporte_liquidacion'), {'metodo': payload_sqli}).status_code, 200)

    def test_limites_caracteres_y_validacion_estricta_formularios(self):
        # 1. PacienteForm: XSS / caracteres inválidos / longitud excesiva / clave corta
        self.client.force_login(self.user_recep)
        casos_invalidos_pac = [
            {'rut': '12.345.678-5', 'nombres': '<script>alert(1)</script>', 'apellidos': 'Torres'},
            {'rut': '12.345.678-5', 'nombres': 'A', 'apellidos': 'Torres'},
            {'rut': '12.345.678-5', 'nombres': 'N' * 81, 'apellidos': 'Torres'},
            {'rut': '12.345.678-5', 'nombres': 'Pedro', 'apellidos': 'Torres', 'telefono': 'no-es-telefono!!'},
            {'rut': '12.345.678-50000', 'nombres': 'Pedro', 'apellidos': 'Torres'},
            {
                'rut': '12.345.678-5', 'nombres': 'Pedro', 'apellidos': 'Torres',
                'crear_cuenta_web': True, 'email_cuenta': 'pedro@correo.cl', 'password_inicial': '123',
            },
        ]
        for payload in casos_invalidos_pac:
            r = self.client.post(reverse('paciente_crear'), payload)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(Paciente.objects.count(), 1)

        # 2. FichaClinicaForm y AtencionClinicaForm: topes de caracteres
        self.client.force_login(self.user_prof)
        self.client.post(reverse('ficha_editar_antecedentes', args=[self.ficha.id]), {
            'grupoSanguineo': 'O+',
            'alergias': 'A' * 1001,
            'antecedentesMedicos': 'Ok',
        })
        self.ficha.refresh_from_db()
        self.assertNotEqual(self.ficha.grupoSanguineo, 'O+')

        r_at = self.client.post(reverse('atencion_crear', args=[self.ficha.id]), {
            'profesional': self.prof.id,
            'motivoConsulta': 'X' * 1001,
            'diagnostico': 'Ok clínico',
            'evolucionNotas': 'E' * 5001,
            'indicacionesTratamiento': 'I' * 3001,
        })
        self.assertEqual(r_at.status_code, 200)
        self.assertEqual(AtencionClinica.objects.count(), 0)

        # 3. BloqueoHorarioForm: rechaza pasado, exceso de caracteres y solapamiento de bloqueos
        ayer = (timezone.localdate() - timedelta(days=1)).strftime('%Y-%m-%d')
        futuro = (timezone.localdate() + timedelta(days=4)).strftime('%Y-%m-%d')
        self.client.post(reverse('bloqueo_crear'), {
            'profesional': self.prof.id,
            'fecha': ayer,
            'hora_inicio': '10:00',
            'hora_fin': '11:00',
            'motivo': 'Pasado',
        })
        self.assertEqual(BloqueoHorario.objects.count(), 0)

        self.client.post(reverse('bloqueo_crear'), {
            'profesional': self.prof.id,
            'fecha': futuro,
            'hora_inicio': '09:00',
            'hora_fin': '10:00',
            'motivo': 'M' * 151,
        })
        self.assertEqual(BloqueoHorario.objects.count(), 0)

        self.client.post(reverse('bloqueo_crear'), {
            'profesional': self.prof.id,
            'fecha': futuro,
            'hora_inicio': '09:00',
            'hora_fin': '11:00',
            'motivo': 'Bloqueo válido',
        })
        self.assertEqual(BloqueoHorario.objects.count(), 1)

        # Bloqueo solapado -> rechazado
        self.client.post(reverse('bloqueo_crear'), {
            'profesional': self.prof.id,
            'fecha': futuro,
            'hora_inicio': '10:00',
            'hora_fin': '12:00',
            'motivo': 'Solapado',
        })
        self.assertEqual(BloqueoHorario.objects.count(), 1)

        # 4. PagoForm: monto fuera de rango y doble cobro Pagado sobre la misma cita
        cita = Cita.objects.create(
            paciente=self.pac,
            profesional=self.prof,
            fechaHoraInicio=timezone.now() + timedelta(hours=5),
            fechaHoraFin=timezone.now() + timedelta(hours=5, minutes=45),
        )
        self.client.force_login(self.user_recep)
        self.client.post(reverse('caja'), {
            'cita': cita.id, 'monto': '99999999', 'prevision': 'Particular',
            'metodoPago': 'Efectivo', 'estado': 'Pagado',
        })
        self.assertEqual(Pago.objects.count(), 0)

        self.client.post(reverse('caja'), {
            'cita': cita.id, 'monto': '35000', 'prevision': 'Particular',
            'metodoPago': 'Efectivo', 'estado': 'Pagado',
        })
        self.assertEqual(Pago.objects.count(), 1)

        # Segundo intento 'Pagado' sobre la misma cita -> rechazado
        self.client.post(reverse('caja'), {
            'cita': cita.id, 'monto': '35000', 'prevision': 'Particular',
            'metodoPago': 'Débito', 'estado': 'Pagado',
        })
        self.assertEqual(Pago.objects.count(), 1)

    def test_reglas_estado_cita_y_telemedicina_cancelada(self):
        cita_pasada = Cita.objects.create(
            paciente=self.pac,
            profesional=self.prof,
            fechaHoraInicio=timezone.now() - timedelta(hours=3),
            fechaHoraFin=timezone.now() - timedelta(hours=2),
            estado='Agendada',
        )
        cita_realizada = Cita.objects.create(
            paciente=self.pac,
            profesional=self.prof,
            fechaHoraInicio=timezone.now() + timedelta(hours=4),
            fechaHoraFin=timezone.now() + timedelta(hours=4, minutes=45),
            estado='Realizada',
        )
        cita_cancelada = Cita.objects.create(
            paciente=self.pac,
            profesional=self.prof,
            fechaHoraInicio=timezone.now() + timedelta(hours=6),
            fechaHoraFin=timezone.now() + timedelta(hours=6, minutes=45),
            estado='Cancelada',
        )
        vc_cancelada = Videoconsulta.objects.create(cita=cita_cancelada, urlSalaWebRTC='sala-canc')

        # Paciente no puede cancelar cita pasada ni realizada
        self.client.force_login(self.user_pac)
        self.client.post(reverse('cita_cambiar_estado', args=[cita_pasada.id]), {'estado': 'Cancelada'})
        cita_pasada.refresh_from_db()
        self.assertEqual(cita_pasada.estado, 'Agendada')

        self.client.post(reverse('cita_cambiar_estado', args=[cita_realizada.id]), {'estado': 'Cancelada'})
        cita_realizada.refresh_from_db()
        self.assertEqual(cita_realizada.estado, 'Realizada')

        # Profesional no puede revertir cita Realizada a Agendada
        self.client.force_login(self.user_prof)
        self.client.post(reverse('cita_cambiar_estado', args=[cita_realizada.id]), {'estado': 'Agendada'})
        cita_realizada.refresh_from_db()
        self.assertEqual(cita_realizada.estado, 'Realizada')

        # Sala de telemedicina cancelada bloquea acceso y endpoints WebRTC
        self.assertEqual(self.client.get(reverse('telemedicina_sala', args=[vc_cancelada.id])).status_code, 302)
        self.assertEqual(
            self.client.post(reverse('telemedicina_estado', args=[vc_cancelada.id]), {'estadoConexion': 'En curso'}).status_code,
            409,
        )
        self.assertEqual(self.client.get(reverse('telemedicina_senal', args=[vc_cancelada.id])).status_code, 409)

    def test_webrtc_senalizacion_hardening_payload_rol_y_tope_ice(self):
        inicio = timezone.now() + timedelta(hours=2)
        cita = Cita.objects.create(
            paciente=self.pac,
            profesional=self.prof,
            fechaHoraInicio=inicio,
            fechaHoraFin=inicio + timedelta(minutes=45),
            estado='Confirmada',
        )
        vc = Videoconsulta.objects.create(cita=cita, urlSalaWebRTC='sala-hard-01', estadoConexion='En curso')
        url_senal = reverse('telemedicina_senal', args=[vc.id])

        self.client.force_login(self.user_prof)
        # Lista JSON no dict -> 400 (sin HTTP 500)
        self.assertEqual(self.client.post(url_senal, data='[1, 2, 3]', content_type='application/json').status_code, 400)
        # Tipo no reconocido -> 400
        self.assertEqual(self.client.post(url_senal, data=json.dumps({'type': 'evil'}), content_type='application/json').status_code, 400)
        # Body > 64 KB -> 413
        huge_payload = json.dumps({'type': 'offer', 'sdp': {'type': 'offer', 'sdp': 'x' * 70000}})
        self.assertEqual(self.client.post(url_senal, data=huge_payload, content_type='application/json').status_code, 413)
        # SDP > 32 KB -> 400
        oversized_sdp = json.dumps({'type': 'offer', 'sdp': {'type': 'offer', 'sdp': 'x' * 40000}})
        self.assertEqual(self.client.post(url_senal, data=oversized_sdp, content_type='application/json').status_code, 400)
        # Host no puede enviar answer -> 403
        self.assertEqual(
            self.client.post(url_senal, data=json.dumps({'type': 'answer', 'sdp': {'type': 'answer', 'sdp': 'a'}}), content_type='application/json').status_code,
            403,
        )

        # Guest no puede hacer reset ni enviar offer -> 403
        self.client.force_login(self.user_pac)
        self.assertEqual(self.client.post(url_senal, data=json.dumps({'type': 'reset'}), content_type='application/json').status_code, 403)
        self.assertEqual(
            self.client.post(url_senal, data=json.dumps({'type': 'offer', 'sdp': {'type': 'offer', 'sdp': 'o'}}), content_type='application/json').status_code,
            403,
        )

        # Tope máximo de 50 candidatos ICE por peer -> el 51 retorna 429
        for i in range(50):
            r_ice = self.client.post(
                url_senal,
                data=json.dumps({'type': 'ice', 'candidate': {'candidate': f'c-{i}'}}),
                content_type='application/json',
            )
            self.assertEqual(r_ice.status_code, 200)
        r_overflow = self.client.post(
            url_senal,
            data=json.dumps({'type': 'ice', 'candidate': {'candidate': 'c-51'}}),
            content_type='application/json',
        )
        self.assertEqual(r_overflow.status_code, 429)

    def test_csv_exportacion_mitiga_formula_injection(self):
        pac_malicioso = Paciente.objects.create(
            rut='12.345.678-5',
            nombres="=cmd|'/C calc'!A0",
            apellidos='@SUM(1+1)',
        )
        cita = Cita.objects.create(
            paciente=pac_malicioso,
            profesional=self.prof,
            fechaHoraInicio=timezone.now() + timedelta(hours=1),
            fechaHoraFin=timezone.now() + timedelta(hours=1, minutes=45),
        )
        Pago.objects.create(
            cita=cita,
            monto=Decimal('25000'),
            estado='Pagado',
            numeroComprobante='+CMP-INJ',
        )

        self.client.force_login(self.user_recep)
        resp = self.client.get(reverse('caja_exportar_csv'))
        self.assertEqual(resp.status_code, 200)
        csv_body = resp.content.decode('utf-8-sig')
        self.assertIn("'=cmd|'/C calc'!A0 @SUM(1+1)", csv_body)
        self.assertIn("'+CMP-INJ", csv_body)


class AuditoriaClinicaYErroresTests(TestCase):
    def setUp(self):
        self.rol_admin = Rol.objects.create(nombre='Administrador')
        self.rol_prof = Rol.objects.create(nombre='Profesional')
        self.rol_recep = Rol.objects.create(nombre='Recepcionista')
        self.rol_pac = Rol.objects.create(nombre='Paciente')

        self.user_admin = Usuario.objects.create_user(
            username='admin_aud',
            email='admin_aud@centronodo.cl',
            password='password123',
            first_name='Admin',
            last_name='Auditor',
            rol=self.rol_admin,
        )
        self.user_prof = Usuario.objects.create_user(
            username='prof_aud',
            email='prof_aud@centronodo.cl',
            password='password123',
            first_name='Andrés',
            last_name='Silva',
            rol=self.rol_prof,
        )
        self.prof = Profesional.objects.create(
            usuario=self.user_prof,
            rut='15.342.980-4',
            nombres='Andrés',
            apellidos='Silva',
            especialidad='Psiquiatría',
        )
        self.user_recep = Usuario.objects.create_user(
            username='recep_aud',
            email='recep_aud@centronodo.cl',
            password='password123',
            rol=self.rol_recep,
        )
        self.user_pac = Usuario.objects.create_user(
            username='pac_aud',
            email='pac_aud@correo.cl',
            password='password123',
            rol=self.rol_pac,
        )
        self.pac = Paciente.objects.create(
            usuario=self.user_pac,
            rut='19.876.543-0',
            nombres='Juan',
            apellidos='Pérez',
        )
        self.ficha = FichaClinica.objects.create(paciente=self.pac)

        self.user_otro_pac = Usuario.objects.create_user(
            username='otro_pac_aud',
            email='otro_aud@correo.cl',
            password='password123',
            rol=self.rol_pac,
        )
        self.otro_pac = Paciente.objects.create(
            usuario=self.user_otro_pac,
            rut='17.654.321-3',
            nombres='Lucía',
            apellidos='Gómez',
        )
        self.ficha_otra = FichaClinica.objects.create(paciente=self.otro_pac)

        self.client = Client()

    def test_auditoria_registra_login_fichas_certificados_pagos_y_denegados(self):
        # 1. Login fallido y login exitoso + logout
        self.client.post(reverse('login'), {'login_id': 'prof_aud', 'password': 'incorrecta'})
        log_fail = AuditLog.objects.filter(accion='LOGIN_FALLIDO').latest('id')
        self.assertEqual(log_fail.resultado, 'FALLIDO')
        self.assertEqual(log_fail.ipOrigen, '127.0.0.1')

        self.client.post(reverse('login'), {'login_id': 'prof_aud', 'password': 'password123'})
        log_ok = AuditLog.objects.filter(accion='LOGIN_EXITOSO', usuario=self.user_prof).latest('id')
        self.assertEqual(log_ok.rolUsuario, 'Profesional')
        self.assertEqual(log_ok.ipOrigen, '127.0.0.1')

        # 2. Lectura de Ficha Clínica cifrada, edición de antecedentes, creación de atención y certificado
        self.client.get(reverse('ficha_detalle', args=[self.ficha.id]))
        self.assertTrue(
            AuditLog.objects.filter(
                accion='VER_FICHA_CLINICA',
                usuario=self.user_prof,
                entidad='FichaClinica',
                entidadId=str(self.ficha.id),
                resultado='OK',
            ).exists()
        )

        self.client.post(reverse('ficha_editar_antecedentes', args=[self.ficha.id]), {
            'grupoSanguineo': 'O+',
            'alergias': 'Penicilina',
            'antecedentesMedicos': 'Hipertensión controlada',
        })
        self.assertTrue(
            AuditLog.objects.filter(
                accion='EDITAR_ANTECEDENTES_FICHA',
                usuario=self.user_prof,
                entidadId=str(self.ficha.id),
            ).exists()
        )

        texto_sensible_diag = 'DIAGNOSTICO_CONFIDENCIAL_XYZ'
        texto_sensible_evol = 'EVOLUCION_SECRETA_ABC'
        self.client.post(reverse('atencion_crear', args=[self.ficha.id]), {
            'profesional': self.prof.id,
            'motivoConsulta': 'Control clínico',
            'diagnostico': texto_sensible_diag,
            'evolucionNotas': texto_sensible_evol,
            'indicacionesTratamiento': 'Descanso y seguimiento',
        })
        atencion = AtencionClinica.objects.get(fichaClinica=self.ficha)
        log_at = AuditLog.objects.filter(accion='CREAR_ATENCION_CLINICA', entidadId=str(atencion.id)).first()
        self.assertIsNotNone(log_at)
        # Privacidad clínica: nunca filtrar diagnósticos ni notas cifradas hacia la bitácora
        self.assertNotIn(texto_sensible_diag, log_at.descripcion)
        self.assertNotIn(texto_sensible_evol, log_at.descripcion)
        self.assertNotIn(texto_sensible_diag, json.dumps(log_at.datosExtra))
        self.assertNotIn(texto_sensible_evol, json.dumps(log_at.datosExtra))

        self.client.get(reverse('atencion_documento', args=[atencion.id]), {'tipo': 'certificado'})
        log_cert = AuditLog.objects.filter(accion='EMITIR_DOCUMENTO_CLINICO', entidadId=str(atencion.id)).first()
        self.assertIsNotNone(log_cert)
        self.assertEqual(log_cert.datosExtra.get('tipo_doc'), 'certificado')

        # Logout via POST
        self.client.post(reverse('logout'))
        self.assertTrue(AuditLog.objects.filter(accion='LOGOUT', usuario=self.user_prof).exists())

        # 3. Otro paciente intentando leer ficha ajena -> ACCESO_DENEGADO
        self.client.force_login(self.user_otro_pac)
        self.client.get(reverse('ficha_detalle', args=[self.ficha.id]))
        self.assertTrue(
            AuditLog.objects.filter(
                accion='ACCESO_DENEGADO',
                usuario=self.user_otro_pac,
                entidad='FichaClinica',
                entidadId=str(self.ficha.id),
                resultado='DENEGADO',
            ).exists()
        )

        # 4. Recepcionista registra, confirma y anula un pago -> registra eventos en bitácora
        cita = Cita.objects.create(
            paciente=self.pac,
            profesional=self.prof,
            fechaHoraInicio=timezone.now() + timedelta(hours=3),
            fechaHoraFin=timezone.now() + timedelta(hours=3, minutes=45),
        )
        self.client.force_login(self.user_recep)
        self.client.post(reverse('caja'), {
            'cita': cita.id,
            'monto': '40000',
            'prevision': 'Particular',
            'metodoPago': 'Transferencia',
            'estado': 'Pendiente',
        })
        pago = Pago.objects.get(cita=cita)
        self.assertTrue(AuditLog.objects.filter(accion='REGISTRAR_PAGO', entidadId=str(pago.id)).exists())

        self.client.post(reverse('pago_cambiar_estado', args=[pago.id]), {'estado': 'Pagado'})
        self.assertTrue(AuditLog.objects.filter(accion='CONFIRMAR_PAGO', entidadId=str(pago.id)).exists())

        self.client.post(reverse('pago_cambiar_estado', args=[pago.id]), {'estado': 'Anulado'})
        log_anul = AuditLog.objects.filter(accion='ANULAR_PAGO', entidadId=str(pago.id)).first()
        self.assertIsNotNone(log_anul)
        self.assertEqual(log_anul.datosExtra.get('estado_anterior'), 'Pagado')
        self.assertEqual(log_anul.datosExtra.get('estado_nuevo'), 'Anulado')

    def test_auditoria_rbac_panel_admin_filtros_fuzzing_csv_e_inmutabilidad(self):
        AuditLog.objects.create(
            usuario=self.user_prof,
            usuarioUsername='=cmd|evil',
            rolUsuario='Profesional',
            accion='VER_FICHA_CLINICA',
            modulo='Fichas Clínicas',
            entidad='FichaClinica',
            entidadId='99',
            descripcion='@SUM(1+1) lectura de ficha',
            resultado='OK',
            ipOrigen='127.0.0.1',
        )

        # Solo Administrador accede al panel y exportación CSV de auditoría
        for usuario_no_admin in (self.user_prof, self.user_recep, self.user_pac):
            self.client.force_login(usuario_no_admin)
            self.assertEqual(self.client.get(reverse('auditoria')).status_code, 302)
            self.assertEqual(self.client.get(reverse('auditoria_exportar_csv')).status_code, 302)

        self.client.force_login(self.user_admin)
        resp = self.client.get(reverse('auditoria'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Bitácora de Auditoría Clínica', resp.content.decode('utf-8'))

        # Fuzzing / SQLi en filtros GET -> nunca genera HTTP 500
        payload_sqli = "' OR '1'='1'; DROP TABLE audit_log; --"
        resp_fuzz = self.client.get(reverse('auditoria'), {
            'modulo': payload_sqli,
            'resultado': payload_sqli,
            'accion': payload_sqli,
            'fecha_desde': payload_sqli,
            'fecha_hasta': '9999-99-99',
            'q': 'A' * 200,
            'page': payload_sqli,
        })
        self.assertEqual(resp_fuzz.status_code, 200)

        # Exportación CSV sanitizada contra CWE-1236
        resp_csv = self.client.get(reverse('auditoria_exportar_csv'))
        self.assertEqual(resp_csv.status_code, 200)
        csv_body = resp_csv.content.decode('utf-8-sig')
        self.assertIn("'=cmd|evil", csv_body)
        self.assertIn("'@SUM(1+1) lectura de ficha", csv_body)

        # AuditLogAdmin debe ser estrictamente de solo lectura (inmutable)
        ma = AuditLogAdmin(AuditLog, admin.site)
        req_admin = RequestFactory().get('/admin/')
        req_admin.user = self.user_admin
        self.assertFalse(ma.has_add_permission(req_admin))
        self.assertFalse(ma.has_change_permission(req_admin))
        self.assertFalse(ma.has_delete_permission(req_admin))

    @override_settings(DEBUG=False)
    def test_paginas_error_personalizadas_404_403_500_glassmorphism(self):
        # 1. HTTP 404 con DEBUG=False usa templates/404.html
        self.client.force_login(self.user_pac)
        resp_404 = self.client.get('/ruta-inexistente-centro-nodo-404/')
        self.assertEqual(resp_404.status_code, 404)
        html_404 = resp_404.content.decode('utf-8')
        self.assertIn('404', html_404)
        self.assertIn('No encontramos esta sección o expediente', html_404)

        # 2. HTTP 403 renderiza templates/403.html y audita PermissionDenied
        req_403 = RequestFactory().get('/zona-restringida/')
        req_403.user = self.user_pac
        resp_403 = error_403_view(req_403, exception=PermissionDenied("Prohibido"))
        self.assertEqual(resp_403.status_code, 403)
        html_403 = resp_403.content.decode('utf-8')
        self.assertIn('403', html_403)
        self.assertIn('Acceso restringido por confidencialidad', html_403)
        self.assertTrue(AuditLog.objects.filter(accion='ACCESO_DENEGADO', usuario=self.user_pac).exists())

        # 3. HTTP 500 autónomo funciona incluso sin usuario/sesión/context_processors
        req_500 = RequestFactory().get('/fallo-simulado/')
        resp_500 = error_500_view(req_500)
        self.assertEqual(resp_500.status_code, 500)
        html_500 = resp_500.content.decode('utf-8')
        self.assertIn('500', html_500)
        self.assertIn('Ocurrió una incidencia inesperada', html_500)
        self.assertIn('Centro Nodo', html_500)






