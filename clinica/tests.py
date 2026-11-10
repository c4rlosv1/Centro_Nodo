import json
from datetime import timedelta
from decimal import Decimal
from django.db import connection
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

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
)
from clinica.utils import validar_rut, formatear_rut


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
        vc = Videoconsulta.objects.create(cita=cita, urlSalaWebRTC='sala-webrtc-01')

        # Host envía offer
        self.client.force_login(self.user_prof)
        r_offer = self.client.post(
            reverse('telemedicina_senal', args=[vc.id]),
            data=json.dumps({'type': 'offer', 'sdp': {'type': 'offer', 'sdp': 'fake-offer'}}),
            content_type='application/json',
        )
        self.assertEqual(r_offer.status_code, 200)

        # Guest obtiene offer y envía answer + ICE
        self.client.force_login(self.user_pac)
        r_get_guest = self.client.get(reverse('telemedicina_senal', args=[vc.id]))
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


