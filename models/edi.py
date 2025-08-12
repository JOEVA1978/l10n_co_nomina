# -*- coding: utf-8 -*-
#
#   inencon S.A.S. / Adaptado - Copyright (C) (2024)
#
#   This file is part of l10n_co_nomina.
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Lesser General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU Lesser General Public License for more details.
#
#   You should have received a copy of the GNU Lesser General Public License
#   along with this program. If not, see <https://www.gnu.org/licenses/>.
#
#   email: info@inencon.com
#

from types import SimpleNamespace
from collections import OrderedDict, defaultdict
from hashlib import sha384
import json
import logging
import calendar
# Importar timezone aquí para uso general
from datetime import datetime, date, timedelta, timezone

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_round

_logger = logging.getLogger(__name__)


class Edi(models.AbstractModel):
    _name = "l10n_co_hr_payroll.edi"
    _description = "EDI Mixin for Colombian Payroll"

    # --- Campos EDI Base ---
    edi_sync = fields.Boolean(
        string="Sync", default=False, copy=False, readonly=True,
        help="Indica si el envío se intentó de forma síncrona.")
    edi_is_not_test = fields.Boolean(
        string="En Producción", copy=False, readonly=True,
        default=lambda self: self.env.company.edi_payroll_is_not_test,
        help="Indica si el documento se envió al ambiente de producción de la DIAN.")

    payment_method_id = fields.Many2one(
        comodel_name="l10n_co_edi.payment.option",
        string="Medio de Pago (NE)",
        readonly=True, copy=True, tracking=True)

    # --- Campos de Respuesta EDI ---
    edi_is_valid = fields.Boolean(
        string="Validado DIAN", copy=False, readonly=True, tracking=True)
    edi_number = fields.Char(string="Número DIAN", copy=False, readonly=True,
                             help="Número asignado por la DIAN (si aplica).")
    edi_uuid = fields.Char(string="CUNE", copy=False, readonly=True, index=True,
                           help="Código Único de Nómina Electrónica asignado por la DIAN.")
    edi_issue_date = fields.Date(
        string="Fecha Emisión DIAN", copy=False, readonly=True,
        help="Fecha de generación reportada a la DIAN.")
    edi_zip_key = fields.Char(string="ZipKey DIAN", copy=False, readonly=True,
                              help="Clave del archivo ZIP devuelto por la DIAN (si aplica).")
    edi_status_code = fields.Char(
        string="Código Estado DIAN", copy=False, readonly=True, tracking=True)
    edi_status_message = fields.Char(
        string="Mensaje Estado DIAN", copy=False, readonly=True, tracking=True)
    edi_errors_messages = fields.Text(
        string="Mensajes Error DIAN", copy=False, readonly=True)
    edi_xml_name = fields.Char(
        string="Nombre Archivo XML", copy=False, readonly=True)
    edi_zip_name = fields.Char(
        string="Nombre Archivo Zip", copy=False, readonly=True)
    edi_qr_code = fields.Char(string="Código QR (URL)", copy=False, readonly=True,
                              help="URL del código QR generado por la DIAN.")
    edi_pdf_download_link = fields.Char(
        string="Enlace Descarga PDF DIAN", copy=False, readonly=True)

    # --- Campos de Adjuntos (Usando ir.attachment) ---
    edi_xml_attachment_id = fields.Many2one(
        'ir.attachment', string='Adjunto XML Firmado', copy=False, readonly=True)
    edi_response_attachment_id = fields.Many2one(
        'ir.attachment', string='Adjunto Respuesta DIAN', copy=False, readonly=True)

    # --- Campo para Payload (para depuración) ---
    edi_payload = fields.Text(string="Payload Enviado (Debug)", copy=False, readonly=True,
                              help="Contenido JSON/Dict que se intentó enviar (para depuración).")

    # --- Métodos Helper ---

    def _format_date_hours(self, date_obj, hours_float):
        """
        Formatea fecha y hora para campos XML como HoraInicio/HoraFin.
        Genera formato YYYY-MM-DD HH:MM:SS-05:00 (asume offset Colombia).
        """
        if not date_obj or hours_float is None:
            return ''
        try:
            time_delta = timedelta(hours=hours_float)
            base_time = datetime.min.time()
            dt_naive = datetime.combine(date_obj, base_time) + time_delta

            # Intentar obtener offset de la compañía o usar el fijo
            tz_co = self.env['res.partner']._get_tz_offset(-5.0)
            if not tz_co:
                _logger.warning(
                    "No se pudo obtener el offset de TZ -5.0, usando offset fijo de datetime.timezone.")
                tz_co = timezone(timedelta(hours=-5))

            # Asegurarse de que dt_naive sea aware para astimezone, o si no, hacerlo.
            # Odoo's fields.Datetime.context_timestamp ya devuelve un datetime aware
            # sin embargo, datetime.combine + timedelta no, por eso se ajusta
            if dt_naive.tzinfo is None or dt_naive.tzinfo.utcoffset(dt_naive) is None:
                # Si el dt_naive no tiene información de zona horaria, se asume UTC para convertir.
                # Mejor es usar self.env.user.company_id.partner_id.tz para el timezone de la compañía.
                # O bien, asegurarse de que date_obj venga ya con un timezone.
                # Para simplificar y mantener la lógica original de -05:00:
                dt_co = dt_naive.replace(tzinfo=timezone.utc).astimezone(tz_co)
            else:
                dt_co = dt_naive.astimezone(tz_co)

            offset_str = dt_co.strftime('%z')
            formatted_offset = f"{offset_str[:3]}:{offset_str[3:]}"
            return dt_co.strftime('%Y-%m-%d %H:%M:%S') + formatted_offset
        except Exception as e:
            _logger.warning(
                "No se pudo formatear fecha/hora para XML: %s, %s. Error: %s", date_obj, hours_float, e)
            return ''

    def dian_preview(self):
        """Abre la URL de consulta del documento en el catálogo de la DIAN."""
        self.ensure_one()
        if not self.edi_uuid:
            raise UserError(
                _("Esta nómina aún no tiene un CUNE asignado por la DIAN."))
        # La URL base ahora se toma de la configuración de la compañía si existe.
        qr_url_base = self.company_id.l10n_co_edi_qr_code_url or 'https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey='
        url = qr_url_base + self.edi_uuid
        return {
            'type': 'ir.actions.act_url',
            'target': 'new',
            'url': url,
        }

    def dian_pdf_view(self):
        """Intenta abrir la URL de descarga del PDF desde el catálogo de la DIAN."""
        self.ensure_one()
        url = self.edi_pdf_download_link
        if not url:
            if not self.edi_uuid:
                raise UserError(
                    _("Esta nómina aún no tiene un CUNE asignado por la DIAN."))
            # Fallback si el link no vino en la respuesta, intentar construirlo
            # Nota: La URL base de la DIAN podría cambiar en el futuro.
            url = 'https://catalogo-vpfe.dian.gov.co/Document/DownloadPayrollPDF/' + self.edi_uuid

        if not url:
            raise UserError(
                _("No hay un enlace de descarga de PDF disponible para esta nómina."))

        return {
            'type': 'ir.actions.act_url',
            'target': 'new',
            'url': url,
        }

    # --- Métodos Principales del Flujo EDI ---

    def _validate_dian_generic(self, consolidated_data=None):
        """
        Orquesta el proceso de validación usando el flujo estándar de Odoo EDI,
        creando un registro temporal en account.move.
        """
        for rec in self:
            _logger.info(
                f"Iniciando _validate_dian_generic (flujo estándar) para {rec.display_name}...")
            temp_move = self.env['account.move']
            try:
                # 1. Preparar y renderizar el XML
                xml_data = rec._prepare_xml_data(consolidated_data)
                xml_content = self.env['ir.qweb']._render(
                    rec._get_xml_template_ref(), xml_data)
                xml_content_bytes = xml_content.encode(
                    'utf-8') if isinstance(xml_content, str) else xml_content

                attachment = self.env['ir.attachment'].create({
                    'name': f"{xml_data.get('cune')}.xml",
                    'datas': base64.b64encode(xml_content_bytes),
                    'mimetype': 'application/xml'
                })

                # 2. Obtener el Diario y crear un registro proxy en account.move
                payroll_journal = rec.company_id.edi_payroll_journal_id
                if not payroll_journal:
                    raise UserError(
                        _("No se ha configurado un 'Diario para Nómina Electrónica' en la compañía."))

                temp_move = self.env['account.move'].create({
                    'journal_id': payroll_journal.id,
                    'move_type': 'entry',
                    'is_payroll_document_proxy': True,  # Nuestra bandera
                })

                # 3. Llamar al método _post del framework EDI de Odoo
                # Este método se encarga de firmar, enviar y procesar la respuesta.
                edi_result = temp_move._post(attachment)

                if edi_result.get('error'):
                    raise UserError(edi_result['error'])

                # 4. Actualizar nuestro registro con la respuesta
                self.edi_is_valid = edi_result.get('success', False)
                self.message_post(
                    body=f"Resultado de la DIAN: {edi_result.get('message', 'Sin mensaje.')}")

            except Exception as e:
                _logger.exception(
                    "Fallo durante el flujo estándar de envío a la DIAN: %s", e)
                raise UserError(_("Fallo durante el envío a la DIAN: %s") % e)
            finally:
                # 5. Asegurarnos de borrar siempre el registro temporal
                if temp_move:
                    temp_move.unlink()

    def _process_raw_dian_response(self, response, cune, signed_xml_bytes):
        """
        Procesa la respuesta cruda del Web Service de la DIAN (objeto suds/zeep)
        y actualiza el registro de nómina EDI.
        """
        self.ensure_one()
        _logger.info("Procesando respuesta cruda de la DIAN: %s", response)

        # La estructura de la respuesta varía, esto es un ejemplo basado en la FE
        # Debes adaptarlo a la respuesta real del servicio de Nómina Electrónica
        is_valid = False
        status_code = getattr(response, 'statusCode', '99')
        status_message = ''
        error_messages = []

        if hasattr(response, 'IsValid') and response.IsValid:
            is_valid = True
            status_message = getattr(
                response, 'StatusDescription', 'Aceptado')
        else:
            status_message = getattr(
                response, 'StatusDescription', 'Rechazado')
            if hasattr(response, 'ErrorMessage') and response.ErrorMessage:
                # Las respuestas de la DIAN a menudo vienen en un array
                errors = response.ErrorMessage
                if not isinstance(errors, list):
                    errors = [errors]
                for error in errors:
                    error_messages.append(str(error))

        # Crear adjuntos
        xml_attachment = self.env['ir.attachment'].create({
            'name': f"{cune}.xml",
            'type': 'binary',
            'datas': base64.b64encode(signed_xml_bytes),
            'res_model': self._name,
            'res_id': self.id,
        })

        vals_to_write = {
            'edi_is_valid': is_valid,
            'edi_uuid': cune,
            'edi_status_code': str(status_code),
            'edi_status_message': status_message,
            'edi_errors_messages': '\n'.join(error_messages) if error_messages else False,
            'edi_xml_attachment_id': xml_attachment.id,
            'edi_issue_date': fields.Date.today(),
        }
        self.write(vals_to_write)

        if is_valid:
            self.message_post(
                body=_("Nómina Electrónica aceptada por la DIAN. CUNE: %s") % cune)
        else:
            self.message_post(body=_("La DIAN rechazó el documento: %s") % (
                status_message or '\n'.join(error_messages)))

    def _process_dian_edi_framework_response(self, dian_document, original_payload):
        """Procesa la respuesta del framework l10n_co_dian y actualiza el registro."""
        self.ensure_one()
        _logger.info("Procesando respuesta de l10n_co_dian para %s (DIAN Doc ID: %s)",
                     self.display_name, dian_document.id)

        # El estado de éxito para nómina en l10n_co_dian.document suele ser 'done' o 'accepted'.
        # Es crucial verificar la implementación de l10n_co_dian para el estado exacto de "aceptado".
        success_state = 'done'
        _logger.info(
            f"Estado de éxito esperado para nómina: '{success_state}' (Estado actual del documento DIAN: {dian_document.state})")

        is_valid = dian_document.state == success_state

        response_data = dian_document.message_json or {}
        status_code = response_data.get('status_code', dian_document.state)
        status_message = response_data.get(
            'status_message', dian_document.message or '')
        errors = response_data.get('errors', [])
        error_messages = '; '.join([
            f"{err.get('code', 'N/A')}: {err.get('message', 'N/A')}" for err in errors
        ]) if isinstance(errors, list) else str(errors)

        xml_attachment = dian_document.attachment_id
        response_attachment = dian_document.response_attachment_id
        issue_date = fields.Date.to_date(
            response_data.get('issue_date')) or getattr(self, 'date', date.today())

        vals_to_write = {
            'edi_is_valid': is_valid,
            'edi_uuid': dian_document.identifier or False,  # CUNE
            'edi_status_code': status_code,  # Usar estado DIAN o el estado del documento Odoo
            'edi_status_message': status_message,
            'edi_errors_messages': error_messages,
            'edi_xml_attachment_id': xml_attachment.id if xml_attachment else False,
            'edi_response_attachment_id': response_attachment.id if response_attachment else False,
            'edi_zip_key': dian_document.zip_key or False,
            'edi_payload': original_payload,  # Guardar payload para depuración
            # Número DIAN
            'edi_number': response_data.get('number') or dian_document.name or False,
            'edi_issue_date': issue_date,  # Fecha DIAN
            # URL QR
            'edi_qr_code': response_data.get('qr_url') or getattr(dian_document, 'qr_url', False),
            # URL PDF
            'edi_pdf_download_link': response_data.get('pdf_url') or False,
        }
        self.write(vals_to_write)

        # Manejo de éxito/error basado en la respuesta
        if is_valid:
            _logger.info("Validación DIAN (vía l10n_co_dian) exitosa para %s. CUNE: %s",
                         self.display_name, self.edi_uuid)
            self.message_post(
                body=_("Nómina Electrónica aceptada por la DIAN. CUNE: %s") % self.edi_uuid)
        else:
            error_msg_log = f"La DIAN rechazó el documento (vía l10n_co_dian). Estado: {dian_document.state}, Mensaje: {status_message}, Errores: {error_messages or 'N/A'}"
            _logger.warning(error_msg_log)
            error_msg_user = _("La DIAN rechazó el documento. Estado: %s, Mensaje: %s, Errores: %s") % (
                dian_document.state,
                status_message or _('Sin mensaje'),
                error_messages or _('N/A')
            )
            self.message_post(body=error_msg_user)
            always_validate = getattr(
                self.company_id, 'edi_payroll_always_validate', False)
            if not always_validate:
                raise UserError(error_msg_user)

    def _prepare_xml_data(self, consolidated_data=None):
        """
        Prepara el diccionario de datos para la plantilla QWeb XML.
        Obtiene datos de `consolidated_data` o del registro `self` (payslip).
        Formatea los valores según los requisitos de la DIAN.
        Calcula totales y CUNE.
        """
        self.ensure_one()
        _logger.info("Preparando datos XML para: %s", self.display_name)

        def format_value(value, precision=2):
            """Formatea números, fechas, booleanos a string para XML. Maneja None."""
            if value is None:
                return ''
            if isinstance(value, float):
                return f"{value:.{precision}f}"
            if isinstance(value, int):
                return str(value)
            if isinstance(value, date):
                return value.strftime('%Y-%m-%d')
            if isinstance(value, bool):
                return str(value).lower()
            return str(value)

        payslip_obj = self
        company = self.company_id
        employee = self.employee_id
        contract = self.contract_id

        if not all([company, employee, contract]):
            raise UserError(
                _("Faltan datos esenciales (Compañía, Empleado o Contrato) en la nómina %s.") % payslip_obj.name)

        source_data = {}

        if consolidated_data:
            _logger.info(
                "Usando datos consolidados para XML para %s.", self.display_name)
            # Asume que consolidated_data ya tiene la estructura necesaria y los totales
            source_data = consolidated_data
        else:  # Lógica para Nómina Individual
            _logger.info(
                "Usando datos de payslip individual para XML para %s.", self.display_name)
            if not hasattr(payslip_obj, 'line_ids') or not hasattr(payslip_obj, 'contract_id'):
                raise UserError(
                    _("El registro %s no parece ser una nómina válida para generar el XML.") % payslip_obj.display_name)

            source_data = {
                'earn': {'basic': {}}, 'deduction': {}, 'payment_dates': [],
                'sequence': {}, 'period': {}, 'payment': {}, 'information': {},
                'notes': [], 'contract_id': contract, 'employee_id': employee, 'company_id': company,
                'accrued_total_numeric': 0.0, 'deductions_total_numeric': 0.0
            }

            # Secuencia, Periodo, Pago, Info general
            sequence_number_str = ''.join(
                filter(str.isdigit, payslip_obj.number or ''))
            sequence_number = int(
                sequence_number_str) if sequence_number_str else 0
            prefix = (payslip_obj.number or '').replace(
                sequence_number_str, '') if sequence_number_str else (payslip_obj.number or '')
            source_data['sequence'] = {
                'prefix': prefix, 'number': sequence_number}
            source_data['period'] = {
                'settlement_start_date': payslip_obj.date_from, 'settlement_end_date': payslip_obj.date_to}
            source_data['payment'] = {
                'method_code': payslip_obj.payment_method_id.code or ''}
            if hasattr(payslip_obj, 'payment_date') and payslip_obj.payment_date:
                source_data['payment_dates'] = [
                    {'date': payslip_obj.payment_date}]

            payroll_period_code = getattr(
                getattr(contract, 'payroll_period_id', None), 'code', '')
            currency_name = company.currency_id.name or 'COP'
            source_data['information'] = {
                'payroll_period_code': payroll_period_code,
                'currency_code_alpha': currency_name, 'trm': 0.0
            }
            if payslip_obj.note:
                source_data['notes'] = [{'text': payslip_obj.note}]

            # --- Agregar Devengos y Deducciones NUMÉRICOS a source_data (agregados por categoría) ---
            aggregated_values = defaultdict(
                lambda: {'total': 0.0, 'quantity': 0.0, 'rates': [], 'details': []})

            # Procesar line_ids (Calculados por reglas)
            for line in payslip_obj.line_ids:
                rule = line.salary_rule_id
                if not rule:
                    continue

                concept_type = getattr(rule, 'type_concept', None)
                is_detailed = getattr(rule, 'edi_is_detailed', False)

                if concept_type == 'earn':
                    earn_category = getattr(rule, 'earn_category', None)
                    if not earn_category:
                        continue
                    # Si es la categoría 'basic', la manejamos aparte para los días y salario base
                    if earn_category == 'basic':
                        _logger.debug(
                            f"Línea Salario Básico ({rule.name}/{rule.code}) encontrada: Cantidad={line.quantity}, Total={line.total}")
                        source_data['earn']['basic']['worked_days'] = line.quantity
                        source_data['earn']['basic']['worker_salary'] = line.total
                    else:
                        key = ('earn_calc', earn_category)
                        aggregated_values[key]['total'] += line.total
                        aggregated_values[key]['quantity'] += getattr(
                            line, 'edi_quantity', line.quantity)
                        rate = getattr(line, 'edi_rate', line.rate)
                        if rate != 100.0:
                            aggregated_values[key]['rates'].append(rate)
                    # Sumar al total devengado
                    source_data['accrued_total_numeric'] += line.total
                elif concept_type == 'deduction':
                    ded_category = getattr(rule, 'deduction_category', None)
                    if not ded_category:
                        continue
                    key = ('ded_calc', ded_category)
                    # Deducciones son positivas en XML
                    aggregated_values[key]['total'] += abs(line.total)
                    aggregated_values[key]['quantity'] += getattr(
                        line, 'edi_quantity', line.quantity)
                    rate = getattr(line, 'edi_rate', line.rate)
                    if rate != 100.0:
                        aggregated_values[key]['rates'].append(rate)
                    # Sumar al total deducciones
                    source_data['deductions_total_numeric'] += abs(line.total)

            # Procesar earn_ids (Detalles manuales) - Tienen prioridad para detalles, pero su total se suma
            if hasattr(payslip_obj, 'earn_ids'):
                for earn_line in payslip_obj.earn_ids:
                    category = earn_line.category
                    if not category:
                        continue
                    key = ('earn_detail', category)
                    amount = abs(earn_line.total)
                    quantity = abs(earn_line.quantity)
                    aggregated_values[key]['total'] += amount
                    aggregated_values[key]['quantity'] += quantity
                    aggregated_values[key]['details'].append({
                        'payment': amount, 'quantity': quantity,
                        'start': earn_line.date_start, 'end': earn_line.date_end,
                        'time_start': earn_line.time_start, 'time_end': earn_line.time_end,
                        'description': earn_line.name,
                    })
                    # Solo sumar al total global si no es básico, para evitar duplicidad si ya viene de rule line
                    if category != 'basic':
                        source_data['accrued_total_numeric'] += amount

            # Procesar deduction_ids (Detalles manuales)
            if hasattr(payslip_obj, 'deduction_ids'):
                for ded_line in payslip_obj.deduction_ids:
                    category = ded_line.category
                    if not category:
                        continue
                    key = ('ded_detail', category)
                    amount = abs(ded_line.amount)
                    aggregated_values[key]['total'] += amount
                    # Asumimos 1 por cada línea manual
                    aggregated_values[key]['quantity'] += 1
                    aggregated_values[key]['details'].append({
                        'payment': amount, 'description': ded_line.name,
                    })
                    source_data['deductions_total_numeric'] += amount

            # --- Construir estructura detallada en source_data['earn'] y source_data['deduction'] ---
            # Ahora usamos los valores agregados de aggregated_values
            earn_final = source_data['earn']
            deduction_final = source_data['deduction']

            # Transporte (Sumar calculado + detalle)
            transport_total = aggregated_values[('earn_calc', 'transports_assistance')]['total'] + \
                aggregated_values[(
                    'earn_detail', 'transports_assistance')]['total']
            viatic_s_total = aggregated_values[('earn_calc', 'transports_viatic')]['total'] + \
                aggregated_values[(
                    'earn_detail', 'transports_viatic')]['total']
            viatic_ns_total = aggregated_values[('earn_calc', 'transports_non_salary_viatic')]['total'] + \
                aggregated_values[(
                    'earn_detail', 'transports_non_salary_viatic')]['total']

            transports_item = {}
            if transport_total > 0:
                transports_item['assistance'] = transport_total
            if viatic_s_total > 0:
                transports_item['viatic'] = viatic_s_total
            if viatic_ns_total > 0:
                transports_item['non_salary_viatic'] = viatic_ns_total
            if transports_item:
                # Tu plantilla espera una lista, aunque con un solo item
                earn_final['transports'] = [transports_item]

            # Horas Extras / Recargos (Priorizar detalles, luego calculados)
            overtimes_surcharges_list = []
            overtime_categories = [
                'daily_overtime', 'overtime_night_hours', 'hours_night_surcharge',
                'sunday_holiday_daily_overtime', 'daily_surcharge_hours_sundays_holidays',
                'sunday_night_overtime_holidays', 'sunday_holidays_night_surcharge_hours'
            ]
            time_code_map = {cat: i + 1 for i,
                             cat in enumerate(overtime_categories)}
            processed_categories_for_overtimes = set()

            for category in overtime_categories:
                details = aggregated_values[(
                    'earn_detail', category)]['details']
                if details:
                    processed_categories_for_overtimes.add(category)
                    for detail in details:
                        if detail['quantity'] > 0 or detail['payment'] > 0:
                            overtimes_surcharges_list.append({
                                'quantity': detail['quantity'],
                                'time_code': time_code_map.get(category),
                                'payment': detail['payment'],
                                'start': self._format_date_hours(detail['start'], detail['time_start']),
                                'end': self._format_date_hours(detail['end'], detail['time_end']),
                                'percentage': 0.0,  # Asumir 0 o buscar de regla
                            })
            for category in overtime_categories:
                if category not in processed_categories_for_overtimes:
                    calc_data = aggregated_values[('earn_calc', category)]
                    if calc_data['total'] > 0:
                        overtimes_surcharges_list.append({
                            'quantity': calc_data['quantity'],
                            'time_code': time_code_map.get(category),
                            'payment': calc_data['total'],
                            'percentage': calc_data['rates'][-1] if calc_data['rates'] else 0.0,
                        })
            if overtimes_surcharges_list:
                earn_final['overtimes_surcharges'] = overtimes_surcharges_list

            # Vacaciones (Priorizar detalles, luego calculados)
            vacation_common_list = []
            vacation_comp_list = []
            processed_vac_common = False
            details_vc = aggregated_values[(
                'earn_detail', 'vacation_common')]['details']
            if details_vc:
                processed_vac_common = True
                for detail in details_vc:
                    if detail['quantity'] > 0 or detail['payment'] > 0:
                        vacation_common_list.append({
                            'quantity': round(detail['quantity']), 'payment': detail['payment'],
                            'start': detail['start'], 'end': detail['end']
                        })
            if not processed_vac_common:
                calc_data_vc = aggregated_values[(
                    'earn_calc', 'vacation_common')]
                if calc_data_vc['total'] > 0:
                    vacation_common_list.append({
                        'quantity': round(calc_data_vc['quantity']), 'payment': calc_data_vc['total'],
                    })

            processed_vac_comp = False
            details_vcomp = aggregated_values[(
                'earn_detail', 'vacation_compensated')]['details']
            if details_vcomp:
                processed_vac_comp = True
                for detail in details_vcomp:
                    if detail['quantity'] > 0 or detail['payment'] > 0:
                        vacation_comp_list.append(
                            {'quantity': round(detail['quantity']), 'payment': detail['payment']})
            if not processed_vac_comp:
                calc_data_vcomp = aggregated_values[(
                    'earn_calc', 'vacation_compensated')]
                if calc_data_vcomp['total'] > 0:
                    vacation_comp_list.append({'quantity': round(
                        calc_data_vcomp['quantity']), 'payment': calc_data_vcomp['total']})

            if vacation_common_list or vacation_comp_list:
                earn_final['vacation'] = {}
                if vacation_common_list:
                    earn_final['vacation']['common'] = vacation_common_list
                if vacation_comp_list:
                    earn_final['vacation']['compensated'] = vacation_comp_list

            # Primas (Sumar calculado + detalle)
            primas_s_data_total = aggregated_values[(
                'earn_calc', 'primas')]['total'] + aggregated_values[('earn_detail', 'primas')]['total']
            primas_ns_data_total = aggregated_values[(
                'earn_calc', 'primas_non_salary')]['total'] + aggregated_values[('earn_detail', 'primas_non_salary')]['total']
            primas_s_data_qty = aggregated_values[(
                'earn_calc', 'primas')]['quantity'] + aggregated_values[('earn_detail', 'primas')]['quantity']

            if primas_s_data_total > 0 or primas_ns_data_total > 0:
                earn_final['primas'] = {
                    'quantity': round(primas_s_data_qty),
                    'payment': primas_s_data_total,
                    'non_salary_payment': primas_ns_data_total
                }

            # Cesantías (Sumar calculado + detalle)
            layoffs_data_total = aggregated_values[(
                'earn_calc', 'layoffs')]['total'] + aggregated_values[('earn_detail', 'layoffs')]['total']
            layoffs_interest_data_total = aggregated_values[(
                'earn_calc', 'layoffs_interest')]['total'] + aggregated_values[('earn_detail', 'layoffs_interest')]['total']
            layoffs_interest_rates = aggregated_values[('earn_calc', 'layoffs_interest')]['rates'] or aggregated_values[(
                'earn_detail', 'layoffs_interest')]['rates']

            if layoffs_data_total > 0 or layoffs_interest_data_total > 0:
                earn_final['layoffs'] = {
                    'payment': layoffs_data_total,
                    'percentage': layoffs_interest_rates[-1] if layoffs_interest_rates else 0.0,
                    'interest_payment': layoffs_interest_data_total
                }

            # Incapacidades (Priorizar detalles, luego calculados)
            incapacities_list = []
            incapacity_categories = ['general_sickness',
                                     'work_accident_sickness', 'maternity_leave']
            incapacity_code_map = {'general_sickness': 1,
                                   'work_accident_sickness': 2, 'maternity_leave': 3}
            processed_categories_for_incapacities = set()

            for category in incapacity_categories:
                details = aggregated_values[(
                    'earn_detail', category)]['details']
                if details:
                    processed_categories_for_incapacities.add(category)
                    for detail in details:
                        if detail['quantity'] > 0 or detail['payment'] > 0:
                            incapacities_list.append({
                                'quantity': round(detail['quantity']),
                                'incapacity_code': incapacity_code_map.get(category),
                                'payment': detail['payment'],
                                'start': detail['start'],
                                'end': detail['end'],
                            })
            for category in incapacity_categories:
                if category not in processed_categories_for_incapacities:
                    calc_data = aggregated_values[('earn_calc', category)]
                    if calc_data['total'] > 0:
                        incapacities_list.append({
                            'quantity': round(calc_data['quantity']),
                            'incapacity_code': incapacity_code_map.get(category),
                            'payment': calc_data['total'],
                        })
            if incapacities_list:
                earn_final['incapacities'] = incapacities_list

            # Licencias (Priorizar detalles, luego calculados)
            licensings_dict = defaultdict(list)
            license_categories = [
                ('paid_leave', 'paid'), ('unpaid_leave', 'unpaid'),
                ('maternity_leave_paid',
                 'maternity_paid'), ('maternity_leave_unpaid', 'maternity_unpaid'),
                ('paternity_leave', 'paternity')
            ]
            processed_categories_for_licenses = set()

            for category_key, license_type in license_categories:
                details = aggregated_values[(
                    'earn_detail', category_key)]['details']
                if details:
                    processed_categories_for_licenses.add(category_key)
                    for detail in details:
                        if detail['quantity'] > 0 or detail['payment'] > 0:
                            licensings_dict[license_type].append({
                                'quantity': round(detail['quantity']),
                                'payment': detail['payment'],
                                'start': detail['start'],
                                'end': detail['end'],
                            })
            for category_key, license_type in license_categories:
                if category_key not in processed_categories_for_licenses:
                    calc_data = aggregated_values[('earn_calc', category_key)]
                    if calc_data['total'] > 0:
                        licensings_dict[license_type].append({
                            'quantity': round(calc_data['quantity']),
                            'payment': calc_data['total'],
                        })
            if licensings_dict:
                earn_final['licensings'] = dict(
                    licensings_dict)  # Convertir a dict normal

            # Huelgas (Priorizar detalles, luego calculados)
            legal_strikes_list = []
            details_ls = aggregated_values[(
                'earn_detail', 'legal_strikes')]['details']
            if details_ls:
                for detail in details_ls:
                    if detail['quantity'] > 0:
                        legal_strikes_list.append({
                            'quantity': round(detail['quantity']),
                            'start': detail['start'],
                            'end': detail['end'],
                        })
            calc_data_ls = aggregated_values[('earn_calc', 'legal_strikes')]
            # Solo si no hay detalles y si hay calculados
            if not legal_strikes_list and calc_data_ls['quantity'] > 0:
                legal_strikes_list.append({
                    'quantity': round(calc_data_ls['quantity']),
                })
            if legal_strikes_list:
                earn_final['legal_strikes'] = legal_strikes_list

            # Bonificaciones, Auxilios, Compensaciones, Vales, Comisiones, Pagos a Terceros, Anticipos (Sumar calculado + detalle)
            list_earn_cats_to_process = {
                'bonuses': [('bonuses', 'payment'), ('bonuses_non_salary', 'non_salary_payment')],
                'assistances': [('assistances', 'payment'), ('assistances_non_salary', 'non_salary_payment')],
                'compensations': [('compensations_ordinary', 'ordinary'), ('compensations_extraordinary', 'extraordinary')],
                'vouchers': [('vouchers', 'payment'), ('vouchers_non_salary', 'non_salary_payment'),
                             ('vouchers_salary_food', 'salary_food_payment'), ('vouchers_non_salary_food', 'non_salary_food_payment')],
                'commissions': [('commissions', 'payment')],
                'third_party_payments': [('third_party_payments', 'payment')],
                'advances': [('advances', 'payment')],
                # Estos requieren descripción
                'other_concepts': [('other_concepts', 'payment', 'description'), ('other_concepts_non_salary', 'non_salary_payment', 'description')],
            }

            for final_key, categories_and_fields in list_earn_cats_to_process.items():
                if final_key == 'other_concepts':  # Manejo especial para otros conceptos
                    other_concepts_processed_details = set()
                    other_concepts_list = []
                    # Priorizar detalles con descripción
                    for cat_key, field_name, desc_field in categories_and_fields:
                        details = aggregated_values[(
                            'earn_detail', cat_key)]['details']
                        for detail in details:
                            if detail['payment'] > 0 and detail.get('description'):
                                # Usar tupla (description, payment) como clave para evitar duplicados EXACTOS si la descripción es única
                                if (detail['description'], detail['payment']) not in other_concepts_processed_details:
                                    other_concepts_list.append({
                                        'description': detail['description'],
                                        field_name: detail['payment']
                                    })
                                    other_concepts_processed_details.add(
                                        (detail['description'], detail['payment']))
                    # Añadir totales calculados si no hay detalles con esa categoría/descripción
                    for cat_key, field_name, desc_field in categories_and_fields:
                        calc_data = aggregated_values[('earn_calc', cat_key)]
                        if calc_data['total'] > 0:
                            # Buscar si ya se incluyó un detalle con la misma "categoría" (implícitamente, por nombre de regla)
                            # Esto es más complejo, por ahora solo agregamos si no hay detalles.
                            # Para un sistema más robusto, necesitarías asociar la descripción de la regla de nómina.
                            # Para simplificar, si hay detalles, estos "ganan". Si no hay detalles para esa categoría, se usa el total calculado.
                            found_in_details = False
                            for item in other_concepts_list:
                                # Si tiene el mismo tipo de pago, asumimos que puede ser el mismo concepto
                                if item.get(field_name):
                                    found_in_details = True
                                    break
                            if not found_in_details:
                                other_concepts_list.append({
                                    # Descripción genérica para calculados
                                    'description': _(f"Concepto {cat_key} calculado"),
                                    field_name: calc_data['total']
                                })
                    if other_concepts_list:
                        earn_final[final_key] = other_concepts_list
                else:  # Lógica para los demás que tienen solo 'payment' o 'non_salary_payment'
                    item_dict = {}
                    total_sum_for_group = 0.0
                    for cat_key, field_name in categories_and_fields:
                        total_val = aggregated_values[('earn_calc', cat_key)]['total'] + \
                            aggregated_values[(
                                'earn_detail', cat_key)]['total']
                        if total_val > 0:
                            item_dict[field_name] = total_val
                            total_sum_for_group += total_val
                    if total_sum_for_group > 0:
                        earn_final[final_key] = [
                            item_dict]  # Envolver en lista

            # Otros Devengos Únicos (Endowment, SustainmentSupport, Telecommuting, CompanyWithdrawalBonus, Compensation, Refund)
            single_earn_cats = ['endowment', 'sustainment_support',
                                'telecommuting', 'company_withdrawal_bonus', 'compensation', 'refund']
            for category in single_earn_cats:
                total_val = aggregated_values[('earn_calc', category)]['total'] + \
                    aggregated_values[('earn_detail', category)]['total']
                if total_val > 0:
                    earn_final[category] = total_val

            # --- DEDUCCIONES (DEDUCTION) ---
            # Salud
            health_data_total = aggregated_values[(
                'ded_calc', 'health')]['total'] + aggregated_values[('ded_detail', 'health')]['total']
            health_rates = aggregated_values[('ded_calc', 'health')]['rates'] or aggregated_values[(
                'ded_detail', 'health')]['rates']
            if health_data_total > 0:
                deduction_final['health'] = {
                    'percentage': health_rates[-1] if health_rates else 0.0,
                    'payment': health_data_total,
                }

            # Pensión
            pension_data_total = aggregated_values[(
                'ded_calc', 'pension_fund')]['total'] + aggregated_values[('ded_detail', 'pension_fund')]['total']
            pension_rates = aggregated_values[('ded_calc', 'pension_fund')]['rates'] or aggregated_values[(
                'ded_detail', 'pension_fund')]['rates']
            if pension_data_total > 0:
                deduction_final['pension_fund'] = {
                    'percentage': pension_rates[-1] if pension_rates else 0.0,
                    'payment': pension_data_total,
                }

            # Fondo Solidaridad Pensional (FSP)
            fsp_data_total = aggregated_values[('ded_calc', 'pension_security_fund')]['total'] + \
                aggregated_values[(
                    'ded_detail', 'pension_security_fund')]['total']
            fsp_subs_data_total = aggregated_values[('ded_calc', 'pension_security_fund_subsistence')]['total'] + \
                aggregated_values[(
                    'ded_detail', 'pension_security_fund_subsistence')]['total']
            fsp_rates = aggregated_values[('ded_calc', 'pension_security_fund')]['rates'] or aggregated_values[(
                'ded_detail', 'pension_security_fund')]['rates']
            fsp_subs_rates = aggregated_values[('ded_calc', 'pension_security_fund_subsistence')]['rates'] or aggregated_values[(
                'ded_detail', 'pension_security_fund_subsistence')]['rates']

            if fsp_data_total > 0 or fsp_subs_data_total > 0:
                deduction_final['pension_security_fund'] = {
                    'percentage': fsp_rates[-1] if fsp_rates else 0.0, 'payment': fsp_data_total,
                    'percentage_subsistence': fsp_subs_rates[-1] if fsp_subs_rates else 0.0,
                    'payment_subsistence': fsp_subs_data_total
                }

            # Sindicatos (Priorizar detalles, luego calculados)
            trade_unions_list = []
            trade_union_categories = ['trade_unions']
            processed_categories_for_trade_unions = set()

            for category in trade_union_categories:
                details = aggregated_values[(
                    'ded_detail', category)]['details']
                if details:
                    processed_categories_for_trade_unions.add(category)
                    for detail in details:
                        if detail['payment'] > 0:
                            trade_unions_list.append({
                                # Usar descripción si existe
                                'description': detail['description'],
                                'payment': detail['payment'],
                                'percentage': 0.0,  # Asumir 0 o buscar de regla
                            })
            for category in trade_union_categories:
                if category not in processed_categories_for_trade_unions:
                    calc_data = aggregated_values[('ded_calc', category)]
                    if calc_data['total'] > 0:
                        trade_unions_list.append({
                            'description': _(f"Cuota sindical calculada"),
                            'payment': calc_data['total'],
                            'percentage': calc_data['rates'][-1] if calc_data['rates'] else 0.0,
                        })
            if trade_unions_list:
                deduction_final['trade_unions'] = trade_unions_list

            # Sanciones (Sumar calculado + detalle)
            sanctions_public_total = aggregated_values[(
                'ded_calc', 'sanctions_public')]['total'] + aggregated_values[('ded_detail', 'sanctions_public')]['total']
            sanctions_private_total = aggregated_values[(
                'ded_calc', 'sanctions_private')]['total'] + aggregated_values[('ded_detail', 'sanctions_private')]['total']
            sanctions_list = []
            if sanctions_public_total > 0 or sanctions_private_total > 0:
                sanctions_list.append({
                    'payment_public': sanctions_public_total,
                    'payment_private': sanctions_private_total,
                })
            if sanctions_list:
                deduction_final['sanctions'] = sanctions_list

            # Libranzas (Priorizar detalles, luego calculados - si se agregan por nombre en reglas)
            libranzas_list = []
            details_lib = aggregated_values[(
                'ded_detail', 'libranzas')]['details']
            if details_lib:
                for detail in details_lib:
                    if detail['payment'] > 0:
                        libranzas_list.append(
                            {'description': detail['description'], 'payment': detail['payment']})
            # Si hay reglas de nómina para libranzas sin detalles manuales, también se pueden agregar aquí
            calc_data_lib = aggregated_values[('ded_calc', 'libranzas')]
            # Solo si no hay detalles manuales
            if not libranzas_list and calc_data_lib['total'] > 0:
                libranzas_list.append({
                    'description': _("Libranza calculada"),
                    'payment': calc_data_lib['total']
                })
            if libranzas_list:
                deduction_final['libranzas'] = libranzas_list

            # Pagos a Terceros, Anticipos, Otras Deducciones (Sumar calculado + detalle)
            list_ded_cats_to_process = {
                'third_party_payments': [('third_party_payments', 'payment')],
                'advances': [('advances', 'payment')],
                # Requiere descripción
                'other_deductions': [('other_deductions', 'payment', 'description')],
            }

            for final_key, categories_and_fields in list_ded_cats_to_process.items():
                if final_key == 'other_deductions':  # Manejo especial para otras deducciones
                    other_deductions_processed_details = set()
                    other_deductions_list = []
                    for cat_key, field_name, desc_field in categories_and_fields:
                        details = aggregated_values[(
                            'ded_detail', cat_key)]['details']
                        for detail in details:
                            if detail['payment'] > 0 and detail.get('description'):
                                if (detail['description'], detail['payment']) not in other_deductions_processed_details:
                                    other_deductions_list.append({
                                        'description': detail['description'],
                                        field_name: detail['payment']
                                    })
                                    other_deductions_processed_details.add(
                                        (detail['description'], detail['payment']))
                    for cat_key, field_name, desc_field in categories_and_fields:
                        calc_data = aggregated_values[('ded_calc', cat_key)]
                        if calc_data['total'] > 0 and not any(item.get(field_name) for item in other_deductions_list):
                            other_deductions_list.append({
                                'description': _(f"Deducción {cat_key} calculada"),
                                field_name: calc_data['total']
                            })
                    if other_deductions_list:
                        deduction_final[final_key] = other_deductions_list
                else:  # Lógica para los demás
                    item_dict = {}
                    total_sum_for_group = 0.0
                    for cat_key, field_name in categories_and_fields:
                        total_val = aggregated_values[('ded_calc', cat_key)]['total'] + \
                            aggregated_values[('ded_detail', cat_key)]['total']
                        if total_val > 0:
                            item_dict[field_name] = total_val
                            total_sum_for_group += total_val
                    if total_sum_for_group > 0:
                        deduction_final[final_key] = [item_dict]

            # Otras Deducciones Únicas (VoluntaryPension, WithholdingSource, AFC, Cooperative, TaxLien, ComplementaryPlans, Education, Refund, Debt)
            single_ded_cats = ['voluntary_pension', 'withholding_source', 'afc',
                               'cooperative', 'tax_lien', 'complementary_plans', 'education', 'refund', 'debt']
            for category in single_ded_cats:
                total_val = aggregated_values[('ded_calc', category)]['total'] + \
                    aggregated_values[('ded_detail', category)]['total']
                if total_val > 0:
                    deduction_final[category] = total_val
            # --- FIN DE LA LÓGICA DE MAPEADO DETALLADO ---

        # --- Mapeo común de source_data a xml_data (formateo para XML) ---
        xml_data = {'company': company,
                    'employee': employee, 'contract': contract}
        is_production = getattr(company, 'edi_payroll_is_not_test', False)
        xml_data['environment'] = {'code': '1' if is_production else '2'}
        is_adjustment_note = getattr(payslip_obj, 'credit_note', False)
        xml_data['tip_xml'] = '103' if is_adjustment_note else '102'
        xml_data['cune'] = ''  # Placeholder, se calculará al final

        now_co = fields.Datetime.context_timestamp(payslip_obj, datetime.now())
        issue_date_obj = getattr(payslip_obj, 'date', date.today())

        # Determinar la fecha final para el cálculo de los días trabajados en el contrato
        # Si la fecha de fin de contrato es anterior o igual a la fecha de fin del periodo de nómina,
        # se usa la fecha de fin de contrato. De lo contrario, se usa la fecha de fin de periodo.
        period_end_for_time_worked = source_data.get(
            'period', {}).get('settlement_end_date', None)
        contract_time_worked = 0
        if contract and contract.date_start and period_end_for_time_worked:
            # Asegurarse de que date_end del contrato no sea None antes de comparar
            if contract.date_end and contract.date_end <= period_end_for_time_worked:
                contract_time_worked = self.calculate_time_worked(
                    contract.date_start, contract.date_end)
            else:
                contract_time_worked = self.calculate_time_worked(
                    contract.date_start, period_end_for_time_worked)

        xml_data['period'] = {
            'date_issue': format_value(issue_date_obj),
            'time_issue': now_co.strftime('%H:%M:%S-05:00'),  # Asume -05:00
            'settlement_start_date': format_value(source_data.get('period', {}).get('settlement_start_date')),
            'settlement_end_date': format_value(source_data.get('period', {}).get('settlement_end_date')),
            'admission_date': format_value(contract.date_start if contract else None),
            'withdrawal_date': format_value(contract.date_end if contract and contract.date_end else None),
            'amount_time': format_value(contract_time_worked, 0),
        }
        xml_data['information'] = {
            'payroll_period_code': format_value(source_data.get('information', {}).get('payroll_period_code')),
            'currency_code_alpha': format_value(source_data.get('information', {}).get('currency_code_alpha', 'COP')),
            'trm': format_value(source_data.get('information', {}).get('trm', 0.0)),
        }

        employer_partner = company.partner_id
        if not employer_partner:
            raise UserError(
                _("La compañía %s no tiene un Partner asociado.") % company.name)
        xml_data['employer'] = {
            'name': format_value(company.name),
            'id_number': format_value(employer_partner._get_vat_without_verification_code()),
            'dv': format_value(getattr(employer_partner, 'l10n_co_verification_code', '')),
            'country_code': format_value(employer_partner.country_id.code or 'CO'),
            'department_code': format_value(getattr(employer_partner.state_id, 'l10n_co_edi_code', '')),
            'municipality_code': format_value(getattr(employer_partner.city_id, 'l10n_co_edi_code', '')),
            'address': format_value(employer_partner.street),
            'language_code': 'es',
        }

        main_partner = employee.address_id
        if not main_partner:
            raise UserError(
                _("El empleado %s no tiene un 'Contacto Principal' (Dirección de Trabajo) asignado.") % employee.name)

        # Lógica para separar nombres y apellidos desde el campo 'name' del partner
        full_name = main_partner.name or ''
        surname, second_surname, first_name, other_names = '', '', '', ''

        if ',' in full_name:
            parts = full_name.split(',', 1)
            last_names_part = parts[0].strip()
            first_names_part = parts[1].strip()

            last_names = last_names_part.split()
            surname = last_names[0] if last_names else ''
            second_surname = ' '.join(last_names[1:]) if len(
                last_names) > 1 else ''

            first_names = first_names_part.split()
            first_name = first_names[0] if first_names else ''
            other_names = ' '.join(first_names[1:]) if len(
                first_names) > 1 else ''
        else:
            name_parts = full_name.split()
            if len(name_parts) >= 3:
                first_name = name_parts[0]
                other_names = ' '.join(name_parts[1:-2])
                surname = name_parts[-2]
                second_surname = name_parts[-1]
            elif len(name_parts) == 2:
                first_name = name_parts[0]
                surname = name_parts[1]
            elif len(name_parts) == 1:
                first_name = name_parts[0]

        xml_data['employee'] = {
            'type_worker_code': format_value(getattr(getattr(contract, 'type_worker_id', None), 'code', '')),
            'subtype_worker_code': format_value(getattr(getattr(contract, 'subtype_worker_id', None), 'code', '')),
            'high_risk_pension': format_value(getattr(contract, 'high_risk_pension', False)),
            'integral_salary': format_value(getattr(contract, 'integral_salary', False)),
            'contract_code': format_value(getattr(getattr(contract, 'type_contract_id', None), 'code', '')),
            'salary': format_value(getattr(contract, 'wage', 0.0)),
            'id_code': format_value(getattr(getattr(main_partner, 'l10n_latam_identification_type_id', None), 'l10n_co_document_code', '')),
            'id_number': format_value(main_partner.vat),
            'surname': format_value(surname), 'second_surname': format_value(second_surname),
            'first_name': format_value(first_name), 'other_names': format_value(other_names),
            'address': format_value(main_partner.street),
            'country_code': format_value(getattr(main_partner.country_id, 'code', 'CO')),
            'department_code': format_value(getattr(getattr(main_partner, 'state_id', None), 'l10n_co_edi_code', '')),
            'municipality_code': format_value(getattr(getattr(main_partner, 'city_id', None), 'l10n_co_edi_code', '')),
            'worker_code': format_value(employee.barcode),
        }

        bank_account = employee.bank_account_id
        xml_data['payment'] = {
            'method_code': format_value(source_data.get('payment', {}).get('method_code')),
            'bank': format_value(getattr(getattr(bank_account, 'bank_id', None), 'name', '')),
            'account_type': format_value(getattr(bank_account, 'l10n_co_edi_account_type', '')),
            'account_number': format_value(getattr(bank_account, 'acc_number', '')),
        }
        xml_data['payment_dates'] = [{'date': format_value(
            pd.get('date'))} for pd in source_data.get('payment_dates', [])]
        xml_data['sequence'] = {
            'prefix': format_value(source_data.get('sequence', {}).get('prefix')),
            'number': format_value(source_data.get('sequence', {}).get('number'), 0),
        }
        xml_data['provider'] = {
            'nit': format_value(getattr(company, 'l10n_co_edi_provider_nit', '')),
            'dv': format_value(getattr(company, 'l10n_co_edi_provider_dv', '')),
            'software_id': format_value(getattr(company, 'edi_payroll_id', '')),
        }

        # Asegurarse de que xml_data['earn'] y xml_data['deduction'] existan antes de asignar
        xml_data['earn'] = xml_data.get('earn', {})
        xml_data['deduction'] = xml_data.get('deduction', {})

        # Re-aplicar el mapeo de earn_final y deduction_final a xml_data['earn'] y xml_data['deduction']
        # Esto es necesario porque la lógica de `source_data` se hizo para recolectar,
        # ahora se debe mapear y formatear a la estructura final de `xml_data`.

        # Asignar los datos ya estructurados y agregados de source_data['earn'] a xml_data['earn']
        # y aplicar el formateo de valores.
        for key, value in source_data.get('earn', {}).items():
            if isinstance(value, dict):
                xml_data['earn'][key] = {sub_key: format_value(
                    sub_val) for sub_key, sub_val in value.items()}
            elif isinstance(value, list):
                formatted_list = []
                for item in value:
                    if isinstance(item, dict):
                        formatted_list.append({sub_key: format_value(
                            sub_val) for sub_key, sub_val in item.items()})
                    else:
                        formatted_list.append(format_value(item))
                xml_data['earn'][key] = formatted_list
            else:
                xml_data['earn'][key] = format_value(value)

        # Asignar los datos ya estructurados y agregados de source_data['deduction'] a xml_data['deduction']
        # y aplicar el formateo de valores.
        for key, value in source_data.get('deduction', {}).items():
            if isinstance(value, dict):
                xml_data['deduction'][key] = {sub_key: format_value(
                    sub_val) for sub_key, sub_val in value.items()}
            elif isinstance(value, list):
                formatted_list = []
                for item in value:
                    if isinstance(item, dict):
                        formatted_list.append({sub_key: format_value(
                            sub_val) for sub_key, sub_val in item.items()})
                    else:
                        formatted_list.append(format_value(item))
                xml_data['deduction'][key] = formatted_list
            else:
                xml_data['deduction'][key] = format_value(value)

        # Totales (Calcular y Formatear)
        accrued_total_numeric = source_data.get('accrued_total_numeric', 0.0)
        deductions_total_numeric = source_data.get(
            'deductions_total_numeric', 0.0)

        total_calc = accrued_total_numeric - deductions_total_numeric
        total_calc_rounded_for_diff = float_round(
            total_calc, precision_digits=2)
        rounding_calc = total_calc_rounded_for_diff - total_calc

        xml_data['accrued_total'] = format_value(accrued_total_numeric)
        xml_data['deductions_total'] = format_value(deductions_total_numeric)
        xml_data['total'] = format_value(total_calc_rounded_for_diff)
        xml_data['rounding'] = format_value(rounding_calc)

        xml_data['notes'] = [{'text': format_value(
            n.get('text'))} for n in source_data.get('notes', [])]

        # Datos para Nota de Ajuste
        if is_adjustment_note:
            origin_payslip_edi = getattr(
                payslip_obj, 'origin_payslip_id', None)
            if origin_payslip_edi and origin_payslip_edi.edi_uuid:
                # Asumir Reemplazar por defecto (o '2' para Eliminar, depende de tu lógica de negocio)
                note_type = '1'
                xml_data['note_type'] = format_value(note_type)

                origin_seq_number_str = ''.join(
                    filter(str.isdigit, origin_payslip_edi.number or ''))
                origin_seq_number = int(
                    origin_seq_number_str) if origin_seq_number_str else 0
                origin_prefix = (origin_payslip_edi.number or '').replace(
                    origin_seq_number_str, '') if origin_seq_number_str else (origin_payslip_edi.number or '')

                xml_data['predecessor'] = {
                    'sequence_number': format_value(origin_seq_number, 0),
                    'sequence_prefix': format_value(origin_prefix),
                    'cune': format_value(origin_payslip_edi.edi_uuid),
                    'issue_date': format_value(origin_payslip_edi.date),
                }
            else:
                _logger.warning(
                    "Nota de ajuste %s no tiene referencia a nómina EDI origen válida con CUNE.", payslip_obj.display_name)
                xml_data['predecessor'] = {}

        # --- Calcular y añadir CUNE (Usa los datos YA FORMATEADOS en xml_data) ---
        try:
            cune_fields_dict = self._payroll_get_cune_fields(xml_data)
            cune_value = self._payroll_calculate_cune(cune_fields_dict)
            xml_data['cune'] = format_value(cune_value)
        except Exception as e:
            _logger.exception(
                "Error calculando CUNE en _prepare_xml_data para %s", self.display_name)
            raise UserError(
                _("No se pudo calcular el CUNE para %s. Error: %s") % (self.display_name, e))
        # --- Fin Calcular y añadir CUNE ---

        _logger.info("Datos XML preparados para: %s", self.display_name)
        return xml_data

    def _get_xml_template_ref(self):
        """Devuelve la referencia a la plantilla QWeb XML correcta."""
        self.ensure_one()
        _logger.info("Obteniendo plantilla XML para %s...", self.display_name)
        is_credit_note = getattr(self, 'credit_note', False)
        if is_credit_note:
            return 'l10n_co_nomina.nomina_individual_ajuste_xml_template'
        else:
            return 'l10n_co_nomina.nomina_individual_xml_template'

    # --- Métodos CUNE ---
    def _payroll_get_cune_fields(self, payroll_data):
        """
        Reúne y formatea los campos necesarios para calcular el CUNE
        leyendo la configuración directamente desde los campos personalizados
        en el modelo de la Compañía (res.company).
        """
        self.ensure_one()
        company = self.company_id
        if not company:
            raise UserError(
                _("No se pudo determinar la compañía para calcular el CUNE."))

        def format_float_cune(amount_str):
            """Formato específico para valores numéricos en el cálculo del CUNE."""
            try:
                float_amount = float(amount_str)
            except (ValueError, TypeError):
                float_amount = 0.0
            return f"{float_amount:.2f}"

        software_pin = company.edi_payroll_pin
        if not software_pin:
            raise UserError(
                _("No se ha configurado el 'Software PIN' en la compañía (Nómina -> Ajustes -> Ajustes DIAN)."))

        # Construir NumNom desde los datos ya formateados en payroll_data
        num_nom = f"{payroll_data.get('sequence', {}).get('prefix', '')}{payroll_data.get('sequence', {}).get('number', '')}"

        # Crear OrderedDict con ORDEN CORRECTO (crucial para el CUNE)
        cune_fields = OrderedDict()
        cune_fields['NumNom'] = num_nom
        cune_fields['FecNom'] = payroll_data.get(
            'period', {}).get('date_issue', '')
        cune_fields['HorNom'] = payroll_data.get(
            'period', {}).get('time_issue', '')
        cune_fields['TipXML'] = payroll_data.get('tip_xml', '')
        cune_fields['NitEmp'] = payroll_data.get(
            'employer', {}).get('id_number', '')
        cune_fields['NumEmp'] = payroll_data.get(
            'employee', {}).get('id_number', '')

        cune_fields['ValDev'] = format_float_cune(
            payroll_data.get('accrued_total', '0.00'))
        cune_fields['ValDed'] = format_float_cune(
            payroll_data.get('deductions_total', '0.00'))
        cune_fields['ValTol'] = format_float_cune(
            payroll_data.get('total', '0.00'))

        cune_fields['SoftwarePin'] = software_pin
        cune_fields['TipAmb'] = payroll_data.get(
            'environment', {}).get('code', '')

        _logger.debug("Campos para CUNE (Ordenado) para %s: %s",
                      self.display_name, cune_fields)
        # Validar campos no vacíos (importante para CUNE)
        for key, value in cune_fields.items():
            if value is None or str(value).strip() == '':
                _logger.error(
                    "Falta el campo CUNE '%s' para %s. Valor: %s", key, self.display_name, value)
                raise UserError(
                    _("Falta el campo '%s' requerido para calcular el CUNE para %s.") % (key, self.display_name))

        return cune_fields

    def _payroll_calculate_cune(self, cune_fields_ordered_dict):
        """Calcula el CUNE aplicando SHA384 a la cadena concatenada."""
        _logger.info("Calculando CUNE...")
        # Concatenar los valores en el orden definido
        concatenated_string = "".join(str(value)
                                      for value in cune_fields_ordered_dict.values())
        _logger.debug("Cadena concatenada para CUNE: %s", concatenated_string)
        # Calcular SHA384 y obtener hexadecimal
        cune_hash = sha384(concatenated_string.encode('utf-8')).hexdigest()
        _logger.info("CUNE Calculado: %s", cune_hash)
        return cune_hash

    # --- Método calculate_time_worked (Lógica 30 días/mes) ---
    @api.model
    def calculate_time_worked(self, start_date, end_date):
        """
        Calcula días trabajados basado en 30 días por mes según especificación DIAN.
        Incluye corrección para Febrero y días 31.
        Maneja correctamente si las fechas de entrada son texto o objetos date.
        """
        try:
            if isinstance(start_date, str):
                start_date = fields.Date.to_date(start_date)
            if isinstance(end_date, str):
                end_date = fields.Date.to_date(end_date)
        except (ValueError, TypeError):
            _logger.warning(
                "Fechas inválidas para calculate_time_worked: start=%s, end=%s", start_date, end_date)
            return 0

        if not start_date or not end_date or end_date < start_date:
            return 0

        start_day = start_date.day
        start_month = start_date.month
        start_year = start_date.year
        end_day = end_date.day
        end_month = end_date.month
        end_year = end_date.year

        # Ajustar días 31 a 30
        if start_day == 31:
            start_day = 30
        if end_day == 31:
            end_day = 30

        # Ajuste especial si ambos son fin de Febrero del mismo año (o si el final es fin de Febrero)
        # y no son día 30, se ajusta a 30.
        start_last_day_month = calendar.monthrange(start_year, start_month)[1]
        end_last_day_month = calendar.monthrange(end_year, end_month)[1]

        if start_month == 2 and start_day == start_last_day_month:
            # Forzar a 30 si es el último día de febrero (ej. 28 o 29)
            start_day = 30
        if end_month == 2 and end_day == end_last_day_month:
            # Forzar a 30 si es el último día de febrero (ej. 28 o 29)
            end_day = 30

        # Cálculo basado en 360 días año, 30 días mes
        days_diff = (end_year - start_year) * 360 + \
                    (end_month - start_month) * 30 + (end_day - start_day)

        # Sumar 1 para incluir el día inicial
        total_days = days_diff + 1

        return total_days if total_days > 0 else 0

# Añadir este modelo temporal al archivo edi.py (o en un archivo models/l10n_co_payroll_temp_model.py)
