# -*- coding: utf-8 -*-
#
#   inencon S.A.S. - Copyright (C) (2024)
#   ... (resto de comentarios de licencia) ...
#

import datetime as dt
import json  # Necesario para _get_consolidated_payroll_data si procesamos detalles
import logging
from collections import defaultdict  # Útil para agregar datos

import babel
from dateutil.relativedelta import relativedelta  # Asegurar importación
from odoo import api, fields, models, tools, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class HrPayslipEdi(models.Model):
    _name = "hr.payslip.edi"
    _inherit = [
        'mail.thread',
        'mail.activity.mixin',
        'l10n_co_hr_payroll.edi'  # Hereda de nuestra clase EDI CORREGIDA
    ]
    _description = "Nómina Electrónica Consolidada"  # Descripción actualizada

    # --- Campos Mantenidos / Ajustados ---
    note = fields.Text(string='Nota Interna',
                       readonly=True)
    contract_id = fields.Many2one(
        'hr.contract', string='Contrato', readonly=True,
        help="Contrato asociado a este periodo consolidado (usualmente el activo en el mes).")
    credit_note = fields.Boolean(string='Es Nota de Ajuste?', readonly=True,
                                 help="Indica si esta nómina consolidada es un ajuste a una anterior.")
    origin_payslip_id = fields.Many2one(comodel_name="hr.payslip.edi", string="Nómina EDI Origen (Ajuste)", readonly=True,
                                        copy=False)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('done', 'Hecho'),
        ('cancel', 'Cancelado'),
    ], string='Estado', index=True, readonly=True, copy=False, default='draft', tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Empleado', required=True, readonly=True, tracking=True)
    company_id = fields.Many2one('res.company', string='Compañía', readonly=True, copy=False,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        related='company_id.currency_id', string='Moneda', readonly=True, store=True)
    number = fields.Char(string='Referencia', readonly=True, copy=False)
    name = fields.Char(string='Nombre Nómina EDI',
                       compute='_compute_name', store=True)
    date = fields.Date("Fecha Documento", required=True, readonly=True,
                       default=fields.Date.context_today, copy=False, tracking=True)
    payslip_ids = fields.Many2many(comodel_name='hr.payslip', string='Nóminas Individuales',
                                   relation='hr_payslip_hr_payslip_edi_rel', readonly=True, copy=False,
                                   help="Nóminas individuales que componen este consolidado mensual.")
    month = fields.Selection([
        ('1', 'Enero'), ('2', 'Febrero'), ('3', 'Marzo'), ('4', 'Abril'),
        ('5', 'Mayo'), ('6', 'Junio'), ('7', 'Julio'), ('8', 'Agosto'),
        ('9', 'Septiembre'), ('10', 'Octubre'), ('11',
                                                 'Noviembre'), ('12', 'Diciembre')
    ], string='Mes', index=True, copy=False, required=True, readonly=True, tracking=True,
        default=lambda self: str((fields.Date.context_today(self) - dt.timedelta(days=1)).month))
    year = fields.Integer(string='Año', index=True, copy=False, required=True, readonly=True, tracking=True,
                          default=lambda self: (fields.Date.context_today(self) - dt.timedelta(days=1)).year)

    # --- Campos EDI (Aseguramos su definición para claridad y funcionalidad) ---
    edi_is_valid = fields.Boolean(string='EDI Válido', copy=False,
                                  help="Indica si el documento EDI ha sido validado por la DIAN.")
    edi_state = fields.Selection([
        ('to_send', 'Por Enviar'),
        ('sent', 'Enviado'),
        ('received', 'Recibido DIAN'),
        ('accepted', 'Aceptado DIAN'),
        ('rejected', 'Rechazado DIAN'),
        ('error', 'Error'),
        ('cancel', 'Cancelado'),
    ], string='Estado EDI', default='to_send', copy=False, tracking=True, help="Estado actual del documento EDI.")
    l10n_co_edi_cune = fields.Char(
        string='CUNE', copy=False, help="Código Único de Nómina Electrónica (CUNE).")
    # Mantener este si lo usas en el XML
    edi_uuid = fields.Char(string='UUID EDI', copy=False,
                           help="UUID del documento electrónico.")
    l10n_co_edi_qr_code_url = fields.Char(
        string='URL QR DIAN', copy=False, help="URL para consultar el documento en el portal de la DIAN.")
    l10n_co_edi_xml_file = fields.Binary(
        string='XML DIAN', attachment=True, copy=False, help="Archivo XML de la Nómina Electrónica.")
    l10n_co_edi_pdf_file = fields.Binary(
        string='PDF DIAN', attachment=True, copy=False, help="Representación gráfica en PDF de la Nómina Electrónica.")
    edi_payload = fields.Text(string='Payload EDI (Debug)', groups="base.group_no_one",
                              copy=False, help="Contenido del payload enviado/recibido para depuración.")

    @api.depends('month', 'year', 'employee_id')
    def _compute_name(self):
        for rec in self:
            if rec.month and rec.year and rec.employee_id:
                month_name = dict(
                    rec._fields['month'].selection).get(rec.month)
                rec.name = f"Nómina Consolidada {rec.employee_id.name} - {month_name} {rec.year}"
            else:
                rec.name = _('Nueva Nómina Consolidada')

    @api.depends('date')
    def _compute_month_year(self):
        for rec in self:
            if rec.date:
                rec.month = str(rec.date.month)
                rec.year = rec.date.year
            else:
                rec.month = False
                rec.year = False

    # Métodos placeholder para la lógica de la API de Nómina Consolidada
    @api.model
    # Dentro de la clase HrPayslipEdi en models/hr_payslip_edi.py

    def validate_dian(self):
        """
        Acción del botón "Validar DIAN".
        Prepara los datos consolidados y los envía a la API de APIDIAN.
        """
        for rec in self:
            if not rec.company_id.edi_payroll_enable:
                _logger.info("Nómina electrónica no habilitada para la compañía %s", rec.company_id.name)
                continue
            if not rec.company_id.edi_payroll_consolidated_enable:
                _logger.info("Validación consolidada no habilitada para la compañía %s", rec.company_id.name)
                continue
            if rec.edi_is_valid:
                _logger.info("La nómina EDI %s ya fue validada ante la DIAN (CUNE: %s)", rec.name, rec.edi_uuid)
                continue
            if rec.state not in ('done',):
                raise UserError(_("Solo se pueden validar nóminas EDI en estado 'Hecho'."))
            if not rec.payslip_ids:
                raise UserError(_("No hay nóminas individuales asociadas a este consolidado."))

            try:
                # 1. Preparar el JSON consolidado (este método ya lo tienes bien)
                consolidated_json_data = rec._get_consolidated_payroll_data()

                # 2. Enviar los datos usando el conector
                test_set_id = rec.company_id.l10n_co_payroll_test_set_id if not rec.company_id.edi_payroll_is_not_test else None
                
                identifier, api_response = self.env['l10n_co_nomina.payroll.api.connector'].send_payroll_document(
                    rec, # Pasamos el registro actual para que el conector pueda acceder a sus datos si es necesario
                    test_set_id=test_set_id
                )

                # 3. Procesar la respuesta (similar a hr.payslip)
                if identifier:
                    vals_to_write = {
                        'edi_payload': json.dumps(consolidated_json_data, indent=2), # Guardar el JSON para debug
                    }
                    if len(identifier) > 36: # Es un CUNE (síncrono)
                        vals_to_write.update({
                            'l10n_co_edi_cune': identifier,
                            'edi_is_valid': True,
                            'edi_state': 'accepted',
                            'l10n_co_edi_qr_code_url': api_response.get('qr_code_url', ''),
                            'l10n_co_edi_xml_file': base64.b64encode(api_response.get('xml_file', b'')),
                            'l10n_co_edi_pdf_file': base64.b64encode(api_response.get('pdf_file', b'')),
                        })
                        rec.message_post(body=_("Nómina Consolidada ACEPTADA por la DIAN (síncrono). CUNE: %s") % identifier)
                    else: # Es un ZipKey (asíncrono)
                        vals_to_write.update({
                            'edi_zip_key': identifier,
                            'edi_is_valid': False,
                            'edi_state': 'sent',
                        })
                        rec.message_post(body=_("Nómina Consolidada ENVIADA a la DIAN (asíncrono). ZipKey: %s.") % identifier)
                    
                    rec.write(vals_to_write)
                else:
                    rec.write({'edi_state': 'error'})
                    rec.message_post(body=_("El envío no devolvió un CUNE o ZipKey."))

            except Exception as e:
                _logger.error("Fallo al validar Nómina EDI %s: %s", rec.name, e, exc_info=True)
                rec.write({'edi_state': 'error'})
                rec.message_post(body=_("Error al validar: %s") % e)


    def get_dian_status(self):
        """
        Acción del botón "Consultar Estado".
        Consulta el estado de una nómina enviada de forma asíncrona usando el ZipKey.
        """
        for rec in self:
            if not rec.edi_zip_key:
                raise UserError(_("Este documento no tiene un ZipKey para consultar (probablemente se procesó de forma síncrona o no se ha enviado)."))
            
            _logger.info("Consultando estado en APIDIAN para ZipKey: %s", rec.edi_zip_key)
            
            try:
                # Llamar al conector para consultar el estado
                api_response = self.env['l10n_co_nomina.payroll.api.connector'].get_payroll_status(rec.edi_zip_key)

                # Procesar la respuesta del status (esto es un ejemplo, debes adaptarlo a la respuesta real)
                if api_response and api_response.get('success'):
                    # Si la respuesta de estado indica éxito
                    if api_response.get('is_valid'):
                        rec.write({
                            'l10n_co_edi_cune': api_response.get('cune'),
                            'edi_is_valid': True,
                            'edi_state': 'accepted',
                            'l10n_co_edi_qr_code_url': api_response.get('qr_code_url', ''),
                            'l10n_co_edi_xml_file': base64.b64encode(api_response.get('xml_file', b'')),
                            'l10n_co_edi_pdf_file': base64.b64encode(api_response.get('pdf_file', b'')),
                            'edi_status_message': api_response.get('message', 'Aceptado'),
                        })
                        rec.message_post(body=_("Consulta exitosa: La DIAN ACEPTÓ el documento. CUNE: %s") % api_response.get('cune'))
                    else: # Si la respuesta indica rechazo
                        rec.write({
                            'edi_is_valid': False,
                            'edi_state': 'rejected',
                            'edi_status_message': api_response.get('message', 'Rechazado'),
                            'edi_errors_messages': json.dumps(api_response.get('errors'), indent=2),
                        })
                        rec.message_post(body=_("Consulta exitosa: La DIAN RECHAZÓ el documento. Razón: %s") % api_response.get('message'))
                else:
                    # La consulta a la API falló
                    rec.message_post(body=_("La consulta de estado falló: %s") % api_response.get('message'))
            
            except Exception as e:
                _logger.error("Fallo al consultar estado para ZipKey %s: %s", rec.edi_zip_key, e, exc_info=True)
                rec.message_post(body=_("Error consultando estado: %s") % e)

    @api.model
    def get_status_consolidated(self):
        """
        Método placeholder para consultar el estado de la nómina consolidada en la DIAN.
        Implementación detallada pendiente.
        """
        self.ensure_one()
        _logger.info(
            "Método get_status_consolidated llamado para Nómina Consolidada ID: %s. Lógica de consulta a API pendiente.", self.id)
        raise UserError(
            _("La funcionalidad de consulta de estado de Nómina Consolidada a la DIAN aún no está implementada."))

    # Métodos placeholder para los botones de vista web/PDF
    @api.model
    def dian_preview_consolidated(self):
        """
        Método placeholder para la vista web de la nómina consolidada.
        """
        self.ensure_one()
        if not self.l10n_co_edi_qr_code_url:
            raise UserError(
                _("No hay URL de QR disponible para previsualizar."))
        return {
            'type': 'ir.actions.act_url',
            'url': self.l10n_co_edi_qr_code_url,
            'target': 'new',
        }

    @api.model
    def l10n_co_edi_xml_file_download(self):
        """
        Método para descargar el archivo XML de la nómina consolidada.
        """
        self.ensure_one()
        if not self.l10n_co_edi_xml_file:
            raise UserError(_("No hay archivo XML disponible para descargar."))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/l10n_co_edi_xml_file/%s' % (self._name, self.id, 'nomina_consolidada.xml'),
            'target': 'self',
        }

    @api.model
    def l10n_co_edi_pdf_file_download(self):
        """
        Método para descargar el archivo PDF de la nómina consolidada.
        """
        self.ensure_one()
        if not self.l10n_co_edi_pdf_file:
            raise UserError(_("No hay archivo PDF disponible para descargar."))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/l10n_co_edi_pdf_file/%s' % (self._name, self.id, 'nomina_consolidada.pdf'),
            'target': 'self',
        }

    @api.depends('employee_id', 'month', 'year')
    def _compute_name(self):
        """Genera un nombre descriptivo para la nómina consolidada."""
        for rec in self:
            if not (rec.employee_id and rec.month and rec.year):
                rec.name = False
                continue
            try:
                date_ym = dt.date(rec.year, int(rec.month), 1)
                locale = self.env.context.get(
                    'lang') or self.env.user.lang or 'es_CO'
                month_year_str = tools.ustr(babel.dates.format_date(
                    date=date_ym, format='MMMM yyyy', locale=locale)).capitalize()
                rec.name = _(
                    'Nómina Electrónica %s - %s') % (rec.employee_id.name, month_year_str)
            except Exception as e:
                _logger.error("Error calculando nombre de nómina EDI: %s", e)
                rec.name = _(
                    'Nómina Electrónica %s - %s/%s') % (rec.employee_id.name, rec.month, rec.year)

    def unlink(self):
        if any(self.filtered(lambda payslip: payslip.state not in ('draft', 'cancel'))):
            raise UserError(
                _('No puede eliminar una Nómina EDI que no esté en estado Borrador o Cancelado.'))
        return super(HrPayslipEdi, self).unlink()

    def action_payslip_draft(self):
        self.write({'state': 'draft'})
        return True

    def action_payslip_cancel(self):
        # Permitir cancelar solo si no está validada ante la DIAN
        if any(rec.edi_is_valid for rec in self):
            raise UserError(
                _("No puede cancelar una Nómina Electrónica que ya fue validada ante la DIAN."))
        self.write({'state': 'cancel'})
        return True

    # --- Método compute_sheet (Simplificado) ---
    def compute_sheet(self):
        """Prepara la nómina EDI para ser procesada (ej. asigna fecha)."""
        for rec in self:
            if not rec.date:
                rec.date = fields.Date.context_today(self)
        return True

    # --- MÉTODO _get_consolidated_payroll_data (AJUSTADO) ---
    def _get_consolidated_payroll_data(self):
        """
        Agrega los datos de las nóminas individuales (payslip_ids)
        para generar un diccionario con la información consolidada del mes.
        """
        self.ensure_one()
        _logger.info("Agregando datos para Nómina EDI: %s", self.name)

        if not self.payslip_ids:
            raise UserError(
                _("Esta nómina EDI no tiene nóminas individuales asociadas."))

        # --- Inicializar estructuras para datos agregados ---
        consolidated_data = {
            'earn': {'basic': {'worked_days': 0, 'worker_salary': 0.0}},
            'deduction': {},
            'payment_dates': [],
            'sequence': {}, 'employer': {}, 'employee': {}, 'period': {},
            'payment': {}, 'information': {}, 'notes': [],
            # Guardar referencias para _prepare_xml_data
            'contract_id': self.contract_id,
            'employee_id': self.employee_id,
            'company_id': self.company_id,
            'accrued_total_numeric': 0.0,
            'deductions_total_numeric': 0.0,
        }
        earn_details = defaultdict(list)
        deduction_details = defaultdict(list)
        aggregated_values = defaultdict(
            lambda: {'total': 0.0, 'quantity': 0.0, 'rates': []})

        # --- Tomar datos estáticos y de periodo ---
        sequence_number_str = ''.join(filter(str.isdigit, self.number or ''))
        sequence_number = int(
            sequence_number_str) if sequence_number_str else 0
        prefix = (self.number or '').replace(sequence_number_str,
                                             '') if sequence_number_str else (self.number or '')
        consolidated_data['sequence'] = {
            'prefix': prefix, 'number': sequence_number}

        try:
            month_start = dt.date(self.year, int(self.month), 1)
            month_end = month_start + relativedelta(months=1, days=-1)
            consolidated_data['period'] = {
                'settlement_start_date': month_start.strftime('%Y-%m-%d'),
                'settlement_end_date': month_end.strftime('%Y-%m-%d'),
            }
        except ValueError:
            raise UserError(
                _("Mes o año inválido para la nómina EDI: %s/%s") % (self.month, self.year))

        # Acceder a los campos heredados del mixin edi
        # payment_form_code = self.payment_form_id.code if self.payment_form_id else '' # ELIMINADO
        payment_method_code = self.payment_method_id.code if self.payment_method_id else ''

        # AJUSTADO: Se quita 'code' (Forma de Pago)
        consolidated_data['payment'] = {
            'method_code': payment_method_code,
        }
        payment_dates_set = set(slip.payment_date.strftime(
            '%Y-%m-%d') for slip in self.payslip_ids if slip.payment_date)
        consolidated_data['payment_dates'] = [
            {'date': d} for d in sorted(list(payment_dates_set))]

        monthly_period = self.env['l10n_co_nomina.payroll.period'].search(
            [('code', '=', '5')], limit=1)
        consolidated_data['information'] = {
            'payroll_period_code': monthly_period.code or '5',
            'currency_code_alpha': self.company_id.currency_id.name or 'COP',
            'trm': 0.0,
        }

        # --- Iterar sobre las nóminas individuales para agregar datos ---
        total_worked_days_calc = 0.0

        days_in_month_theory = 30.0
        total_absent_days_in_month = 0

        for payslip in self.payslip_ids:
            total_absent_days_in_month += sum(
                leave_line.number_of_days for leave_line in payslip.worked_days_line_ids
                if leave_line.code in ['LNR', 'SUS', 'IGE1_2', 'IGE3_90', 'IGE91_180', 'IGE181_MAS', 'LMA', 'LR', 'ATEP', 'VACDISF']
            )
            # Aunque no se usa directamente para worked_days, mantener por si se necesita en otros cálculos
            total_worked_days_calc += self.calculate_time_worked(
                payslip.date_from, payslip.date_to)

            for earn_line in payslip.earn_ids:
                category = earn_line.category
                key = ('earn_detail', category)
                aggregated_values[key]['total'] += abs(earn_line.total)
                aggregated_values[key]['quantity'] += abs(earn_line.quantity)

            for ded_line in payslip.deduction_ids:
                category = ded_line.category
                key = ('ded_detail', category)
                aggregated_values[key]['total'] += abs(ded_line.amount)
                aggregated_values[key]['quantity'] += 1

            for line in payslip.line_ids:
                # CORRECCIÓN: Usar los campos personalizados para type_concept y edi_is_detailed
                rule = line.salary_rule_id
                concept_type = getattr(rule, 'type_concept', None)
                is_detailed = getattr(rule, 'edi_is_detailed', False)

                if concept_type == 'earn':
                    consolidated_data['accrued_total_numeric'] += line.total
                    if not is_detailed:
                        category = getattr(rule, 'earn_category', None)
                        if category:
                            key = ('earn_calc', category)
                            aggregated_values[key]['total'] += line.total
                            qty = line.edi_quantity if hasattr(
                                line, 'edi_quantity') and line.edi_quantity else line.quantity
                            aggregated_values[key]['quantity'] += qty
                            rate = line.edi_rate if hasattr(
                                line, 'edi_rate') and line.edi_rate != 100.0 else line.rate
                            if rate != 100.0:
                                aggregated_values[key]['rates'].append(rate)
                elif concept_type == 'deduction':
                    consolidated_data['deductions_total_numeric'] += abs(
                        line.total)
                    if not is_detailed:
                        category = getattr(rule, 'deduction_category', None)
                        if category:
                            key = ('ded_calc', category)
                            aggregated_values[key]['total'] += abs(line.total)
                            qty = line.edi_quantity if hasattr(
                                line, 'edi_quantity') and line.edi_quantity else line.quantity
                            aggregated_values[key]['quantity'] += qty
                            rate = line.edi_rate if hasattr(
                                line, 'edi_rate') and line.edi_rate != 100.0 else line.rate
                            if rate != 100.0:
                                aggregated_values[key]['rates'].append(rate)

        consolidated_worked_days = max(
            0.0, days_in_month_theory - total_absent_days_in_month)

        # --- Construir diccionarios 'earn' y 'deduction' finales ---
        earn_final = consolidated_data['earn']
        deduction_final = consolidated_data['deduction']

        # 1. Básico
        earn_final['basic']['worked_days'] = round(total_worked_days_calc)
        earn_final['basic']['worker_salary'] = aggregated_values[(  # CORRECCIÓN: Usar los días consolidados calculados
            'earn_calc', 'basic')]['total']

        # 2. Transporte
        transport_total = aggregated_values[(
            'earn_calc', 'transports_assistance')]['total']
        transport_total += aggregated_values[(
            'earn_detail', 'transports_assistance')]['total']
        viatic_s_total = aggregated_values[('earn_calc', 'transports_viatic')]['total'] + \
            aggregated_values[('earn_detail', 'transports_viatic')]['total']
        viatic_ns_total = aggregated_values[('earn_calc', 'transports_non_salary_viatic')]['total'] + \
            aggregated_values[(
                'earn_detail', 'transports_non_salary_viatic')]['total']

        transports_list = []
        if transport_total > 0:
            transports_list.append({'assistance': transport_total})
        if viatic_s_total > 0:
            transports_list.append({'viatic': viatic_s_total})
        if viatic_ns_total > 0:
            transports_list.append({'non_salary_viatic': viatic_ns_total})
        if transports_list:
            earn_final['transports'] = transports_list

        # 3. Salud, Pensión y FSP (desde calculados)
        health_data = aggregated_values[('ded_calc', 'health')]
        if health_data['total'] > 0:
            rates = health_data['rates']
            deduction_final['health'] = {
                'percentage': rates[-1] if rates else 0.0,
                'payment': health_data['total']
            }

        pension_data = aggregated_values[('ded_calc', 'pension_fund')]
        if pension_data['total'] > 0:
            rates = pension_data['rates']
            deduction_final['pension_fund'] = {
                'percentage': rates[-1] if rates else 0.0,
                'payment': pension_data['total']
            }

        fsp_data = aggregated_values[('ded_calc', 'pension_security_fund')]
        fsp_subs_data = aggregated_values[(
            'ded_calc', 'pension_security_fund_subsistence')]
        if fsp_data['total'] > 0 or fsp_subs_data['total'] > 0:
            fsp_rates = fsp_data['rates']
            fsp_subs_rates = fsp_subs_data['rates']
            deduction_final['pension_security_fund'] = {
                'percentage': fsp_rates[-1] if fsp_rates else 0.0,
                'payment': fsp_data['total'],
                'percentage_subsistence': fsp_subs_rates[-1] if fsp_subs_rates else 0.0,
                'payment_subsistence': fsp_subs_data['total']
            }

        # 4. Cesantías y sus Intereses (desde calculados)
        layoffs_data = aggregated_values[('earn_calc', 'layoffs')]
        layoffs_interest_data = aggregated_values[(
            'earn_calc', 'layoffs_interest')]
        if layoffs_data['total'] > 0 or layoffs_interest_data['total'] > 0:
            layoffs_rates = layoffs_interest_data['rates']
            earn_final['layoffs'] = {
                'payment': layoffs_data['total'],
                'percentage': layoffs_rates[-1] if layoffs_rates else 0.0,
                'interest_payment': layoffs_interest_data['total']
            }

        # 5. Primas (desde calculados)
        primas_s_data = aggregated_values[('earn_calc', 'primas')]
        primas_ns_data = aggregated_values[('earn_calc', 'primas_non_salary')]
        if primas_s_data['total'] > 0 or primas_ns_data['total'] > 0:
            earn_final['primas'] = {
                'quantity': round(primas_s_data['quantity']),
                'payment': primas_s_data['total'],
                'non_salary_payment': primas_ns_data['total']
            }

        # 6. Horas Extras y Recargos (desde calculados y detalles)
        overtimes_surcharges_list = []
        overtime_categories = [
            'daily_overtime', 'overtime_night_hours', 'hours_night_surcharge',
            'sunday_holiday_daily_overtime', 'daily_surcharge_hours_sundays_holidays',
            'sunday_night_overtime_holidays', 'sunday_holidays_night_surcharge_hours'
        ]
        time_code_map = {
            'daily_overtime': 1, 'overtime_night_hours': 2, 'hours_night_surcharge': 3,
            'sunday_holiday_daily_overtime': 4, 'daily_surcharge_hours_sundays_holidays': 5,
            'sunday_night_overtime_holidays': 6, 'sunday_holidays_night_surcharge_hours': 7,
        }
        for category in overtime_categories:
            calc_data = aggregated_values[('earn_calc', category)]
            detail_data = aggregated_values[('earn_detail', category)]
            total_quantity = calc_data['quantity'] + detail_data['quantity']
            total_payment = calc_data['total'] + detail_data['total']

            if total_quantity > 0 or total_payment > 0:
                overtimes_surcharges_list.append({
                    'quantity': round(total_quantity, 2),
                    'time_code': time_code_map.get(category),
                    'payment': total_payment,
                })
        if overtimes_surcharges_list:
            earn_final['overtimes_surcharges'] = overtimes_surcharges_list

        # 7. Incapacidades (desde calculados y detalles)
        incapacities_list = []
        incapacity_categories = ['incapacities_common',
                                 'incapacities_professional', 'incapacities_working']
        incapacity_code_map = {
            'incapacities_common': 1, 'incapacities_professional': 2, 'incapacities_working': 3,
        }
        for category in incapacity_categories:
            calc_data = aggregated_values[('earn_calc', category)]
            detail_data = aggregated_values[('earn_detail', category)]
            total_quantity = calc_data['quantity'] + detail_data['quantity']
            total_payment = calc_data['total'] + detail_data['total']

            if total_quantity > 0 or total_payment > 0:
                incapacities_list.append({
                    'quantity': round(total_quantity),
                    'incapacity_code': incapacity_code_map.get(category),
                    'payment': total_payment,
                })
        if incapacities_list:
            earn_final['incapacities'] = incapacities_list

        # 8. Licencias (Maternidad/Paternidad, Remuneradas, No Remuneradas)
        licensings_list_map = defaultdict(list)
        licensing_categories = ['licensings_maternity_or_paternity_leaves',
                                'licensings_permit_or_paid_licenses', 'licensings_suspension_or_unpaid_leaves']
        for category in licensing_categories:
            calc_data = aggregated_values[('earn_calc', category)]
            detail_data = aggregated_values[('earn_detail', category)]
            total_quantity = calc_data['quantity'] + detail_data['quantity']
            total_payment = calc_data['total'] + detail_data['total']

            if total_quantity > 0 or total_payment > 0:
                licensing_type_key = category
                licensings_list_map[licensing_type_key].append({
                    'quantity': round(total_quantity),
                    'payment': total_payment if category != 'licensings_suspension_or_unpaid_leaves' else 0.0,
                })

        if licensings_list_map:
            earn_final['licensings'] = dict(licensings_list_map)

        # 9. Vacaciones (Comunes y Compensadas)
        vacation_common_data = aggregated_values[(
            'earn_calc', 'vacation_common')]
        vacation_common_detail = aggregated_values[(
            'earn_detail', 'vacation_common')]
        vacation_comp_data = aggregated_values[(
            'earn_calc', 'vacation_compensated')]
        vacation_comp_detail = aggregated_values[(
            'earn_detail', 'vacation_compensated')]

        vacation_common_list = []
        vacation_comp_list = []

        total_qty_common = vacation_common_data['quantity'] + \
            vacation_common_detail['quantity']
        total_pay_common = vacation_common_data['total'] + \
            vacation_common_detail['total']
        if total_qty_common > 0 or total_pay_common > 0:
            vacation_common_list.append({
                'quantity': round(total_qty_common),
                'payment': total_pay_common,
            })

        total_qty_comp = vacation_comp_data['quantity'] + \
            vacation_comp_detail['quantity']
        total_pay_comp = vacation_comp_data['total'] + \
            vacation_comp_detail['total']
        if total_qty_comp > 0 or total_pay_comp > 0:
            vacation_comp_list.append({
                'quantity': round(total_qty_comp),
                'payment': total_pay_comp,
            })

        if vacation_common_list or vacation_comp_list:
            earn_final['vacation'] = {}
            if vacation_common_list:
                earn_final['vacation']['common'] = vacation_common_list
            if vacation_comp_list:
                earn_final['vacation']['compensated'] = vacation_comp_list

        # 10. Huelgas Legales
        strike_data = aggregated_values[('earn_calc', 'legal_strikes')]
        strike_detail = aggregated_values[('earn_detail', 'legal_strikes')]
        total_qty_strike = strike_data['quantity'] + strike_detail['quantity']
        if total_qty_strike > 0:
            earn_final['legal_strikes'] = [{
                'quantity': round(total_qty_strike),
            }]

        # 11. Deducciones Calculadas Restantes
        deduction_mapping = {
            'voluntary_pension': 'voluntary_pension',
            'withholding_source': 'withholding_source',
            'afc': 'afc',
            'cooperative': 'cooperative',
            'tax_lien': 'tax_lien',
            'complementary_plans': 'complementary_plans',
            'education': 'education',
            'refund': 'refund',
            'debt': 'debt',
        }
        for category, key_in_dict in deduction_mapping.items():
            data = aggregated_values[('ded_calc', category)]
            total_payment = data['total']
            if total_payment > 0:
                deduction_final[key_in_dict] = total_payment

        # 12. Sindicatos (Calculado)
        trade_union_data = aggregated_values[('ded_calc', 'trade_unions')]
        if trade_union_data['total'] > 0:
            rates = trade_union_data['rates']
            deduction_final['trade_unions'] = [{
                'percentage': rates[-1] if rates else 0.0,
                'payment': trade_union_data['total'],
            }]

        # 13. Sanciones (Calculado)
        sanction_pub_data = aggregated_values[('ded_calc', 'sanctions_public')]
        sanction_priv_data = aggregated_values[(
            'ded_calc', 'sanctions_private')]
        if sanction_pub_data['total'] > 0 or sanction_priv_data['total'] > 0:
            deduction_final['sanctions'] = [{
                'payment_public': sanction_pub_data['total'],
                'payment_private': sanction_priv_data['total'],
            }]

        # 14. Libranzas (Detalle) - Sumar totales
        libranzas_total = aggregated_values[(
            'ded_detail', 'libranzas')]['total']
        if libranzas_total > 0:
            deduction_final['libranzas'] = [{
                'description': 'Libranzas Consolidadas Mes',
                'payment': libranzas_total,
            }]

        # 15. Otros Pagos a Terceros (Deducción - Detalle) - Sumar totales
        ded_third_party_total = aggregated_values[(
            'ded_detail', 'third_party_payments')]['total']
        if ded_third_party_total > 0:
            deduction_final['third_party_payments'] = [{
                'payment': ded_third_party_total,
            }]

        # 16. Anticipos (Deducción - Detalle y Calculado?) - Sumar totales
        ded_advances_total = aggregated_values[(
            'ded_calc', 'advances')]['total'] + aggregated_values[('ded_detail', 'advances')]['total']
        if ded_advances_total > 0:
            deduction_final['advances'] = [{
                'payment': ded_advances_total,
            }]

        # 17. Otras Deducciones (Detalle) - Sumar totales
        ded_others_total = aggregated_values[(
            'ded_detail', 'other_deductions')]['total']
        if ded_others_total > 0:
            deduction_final['other_deductions'] = [{
                'payment': ded_others_total,
            }]

        # 18. Bonificaciones (Salarial y No Salarial - Calculado y Detalle)
        bonus_s_total = aggregated_values[(
            'earn_calc', 'bonuses')]['total'] + aggregated_values[('earn_detail', 'bonuses')]['total']
        bonus_ns_total = aggregated_values[('earn_calc', 'bonuses_non_salary')]['total'] + \
            aggregated_values[('earn_detail', 'bonuses_non_salary')]['total']
        if bonus_s_total > 0 or bonus_ns_total > 0:
            earn_final['bonuses'] = [{
                'payment': bonus_s_total,
                'non_salary_payment': bonus_ns_total,
            }]

        # 19. Auxilios (Salarial y No Salarial - Calculado y Detalle)
        assist_s_total = aggregated_values[(
            'earn_calc', 'assistances')]['total'] + aggregated_values[('earn_detail', 'assistances')]['total']
        assist_ns_total = aggregated_values[('earn_calc', 'assistances_non_salary')]['total'] + \
            aggregated_values[(
                'earn_detail', 'assistances_non_salary')]['total']
        if assist_s_total > 0 or assist_ns_total > 0:
            earn_final['assistances'] = [{
                'payment': assist_s_total,
                'non_salary_payment': assist_ns_total,
            }]

        # 20. Otros Conceptos (Salarial y No Salarial - Calculado y Detalle)
        other_s_total = aggregated_values[('earn_calc', 'other_concepts')]['total'] + \
            aggregated_values[('earn_detail', 'other_concepts')]['total']
        other_ns_total = aggregated_values[('earn_calc', 'other_concepts_non_salary')]['total'] + \
            aggregated_values[(
                'earn_detail', 'other_concepts_non_salary')]['total']
        if other_s_total > 0 or other_ns_total > 0:
            earn_final['other_concepts'] = [{
                'description': 'Otros Conceptos Consolidados Mes',
                'payment': other_s_total,
                'non_salary_payment': other_ns_total,
            }]

        # 21. Compensaciones (Ordinaria y Extraordinaria - Calculado y Detalle)
        comp_ord_total = aggregated_values[('earn_calc', 'compensations_ordinary')]['total'] + \
            aggregated_values[(
                'earn_detail', 'compensations_ordinary')]['total']
        comp_ext_total = aggregated_values[('earn_calc', 'compensations_extraordinary')]['total'] + \
            aggregated_values[(
                'earn_detail', 'compensations_extraordinary')]['total']
        if comp_ord_total > 0 or comp_ext_total > 0:
            earn_final['compensations'] = [{
                'ordinary': comp_ord_total,
                'extraordinary': comp_ext_total,
            }]

        # 22. Vales/Bonos (Salarial, No Salarial, Alimentación - Calculado y Detalle)
        voucher_s_total = aggregated_values[(
            'earn_calc', 'vouchers')]['total'] + aggregated_values[('earn_detail', 'vouchers')]['total']
        voucher_ns_total = aggregated_values[('earn_calc', 'vouchers_non_salary')]['total'] + \
            aggregated_values[('earn_detail', 'vouchers_non_salary')]['total']
        voucher_food_s_total = aggregated_values[(
            'earn_calc', 'vouchers_salary_food')]['total'] + aggregated_values[('earn_detail', 'vouchers_salary_food')]['total']
        voucher_food_ns_total = aggregated_values[(
            'earn_calc', 'vouchers_non_salary_food')]['total'] + aggregated_values[('earn_detail', 'vouchers_non_salary_food')]['total']
        if voucher_s_total > 0 or voucher_ns_total > 0 or voucher_food_s_total > 0 or voucher_food_ns_total > 0:
            earn_final['vouchers'] = [{
                'payment': voucher_s_total,
                'non_salary_payment': voucher_ns_total,
                'salary_food_payment': voucher_food_s_total,
                'non_salary_food_payment': voucher_food_ns_total,
            }]

        # 23. Comisiones (Calculado y Detalle)
        commissions_total = aggregated_values[(
            'earn_calc', 'commissions')]['total'] + aggregated_values[('earn_detail', 'commissions')]['total']
        if commissions_total > 0:
            earn_final['commissions'] = [{
                'payment': commissions_total,
            }]

        # 24. Pagos a Terceros (Devengo - Calculado y Detalle)
        earn_third_party_total = aggregated_values[(
            'earn_calc', 'third_party_payments')]['total'] + aggregated_values[('earn_detail', 'third_party_payments')]['total']
        if earn_third_party_total > 0:
            earn_final['third_party_payments'] = [{
                'payment': earn_third_party_total,
            }]

        # 25. Anticipos (Devengo - Calculado y Detalle)
        earn_advances_total = aggregated_values[(
            'earn_calc', 'advances')]['total'] + aggregated_values[('earn_detail', 'advances')]['total']
        if earn_advances_total > 0:
            earn_final['advances'] = [{
                'payment': earn_advances_total,
            }]

        # 26. Otros Devengos Calculados
        other_earn_mapping = {
            'endowment': 'endowment',
            'sustainment_support': 'sustainment_support',
            'telecommuting': 'telecommuting',
            'company_withdrawal_bonus': 'company_withdrawal_bonus',
            'compensation': 'compensation',
            'refund': 'refund',
        }
        for category, key_in_dict in other_earn_mapping.items():
            data = aggregated_values[('earn_calc', category)]
            total_payment = data['total']
            if total_payment > 0:
                earn_final[key_in_dict] = total_payment

        # --- Fin de la agregación ---
        notes_list = consolidated_data['notes']
        for slip in self.payslip_ids:
            if slip.note and slip.note not in [n['text'] for n in notes_list]:
                notes_list.append({'text': slip.note})
        if self.note and self.note not in [n['text'] for n in notes_list]:
            notes_list.append({'text': self.note})
        consolidated_data['notes'] = notes_list

        _logger.info("Datos agregados para Nómina EDI: %s", self.name)
        return consolidated_data

    # --- Método validate_dian_generic (Adaptado) ---
    def validate_dian_generic(self):
        """ Inicia el proceso de validación EDI para esta nómina consolidada."""
        for rec in self:
            if not rec.company_id.edi_payroll_enable:
                _logger.info(
                    "Nómina electrónica no habilitada para la compañía %s", rec.company_id.name)
                continue
            if not rec.company_id.edi_payroll_consolidated_enable:
                _logger.info(
                    "Validación consolidada no habilitada para la compañía %s", rec.company_id.name)
                continue
            if rec.edi_is_valid:
                _logger.info(
                    "La nómina EDI %s ya fue validada ante la DIAN (UUID: %s)", rec.name, rec.edi_uuid)
                continue
            if rec.state not in ('done',):
                raise UserError(
                    _("Solo se pueden validar nóminas EDI en estado 'Hecho'."))
            if not rec.payslip_ids:
                raise UserError(
                    _("No hay nóminas individuales asociadas a este consolidado."))

            try:
                consolidated_data = rec._get_consolidated_payroll_data()
            except Exception as e:
                raise UserError(
                    _("Error al consolidar datos de nóminas individuales: %s") % e)

            _logger.info(
                "Iniciando validación DIAN para nómina EDI: %s", rec.name)
            # Llamada al método heredado
            rec._validate_dian_generic(consolidated_data)

    # --- Método validate_dian (Mantenido) ---
    def validate_dian(self):
        """Acción para disparar la validación del consolidado."""
        self.validate_dian_generic()

    # --- Método action_payslip_done (Adaptado) ---
    def action_payslip_done(self):
        """Confirma la nómina EDI y opcionalmente la valida."""
        for rec in self:
            if rec.state != 'draft':
                continue

            if not rec.number or rec.number in ('New', _('New')):
                sequence_code = 'salary.slip.edi.note' if rec.credit_note else 'salary.slip.edi'
                rec.number = self.env['ir.sequence'].next_by_code(
                    sequence_code)
                if not rec.number:
                    raise UserError(
                        _("Debe crear una secuencia con el código '%s'") % sequence_code)

            if not rec.contract_id and rec.payslip_ids:
                active_contracts = self.env['hr.contract'].search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('state', 'in', ('open', 'close')),
                    ('date_start', '<=', dt.date(rec.year, int(rec.month), 1) +
                     relativedelta(months=1, days=-1)),
                    '|', ('date_end', '=', False),
                    ('date_end', '>=', dt.date(rec.year, int(rec.month), 1))
                ], order='date_start desc', limit=1)
                if active_contracts:
                    rec.contract_id = active_contracts.id
                else:
                    # Fallback al contrato del último payslip si no se encuentra activo
                    rec.contract_id = rec.payslip_ids[-1].contract_id.id if rec.payslip_ids else False

            rec.write({'state': 'done'})

            # Validación automática si está habilitada y no se usa estado intermedio
            if rec.company_id.edi_payroll_enable \
                    and rec.company_id.edi_payroll_consolidated_enable \
                    and not rec.company_id.edi_payroll_enable_validate_state:
                try:
                    rec.validate_dian_generic()
                except Exception as e:
                    # Loggear el error pero no detener el flujo si falla la validación automática
                    _logger.error(
                        "Fallo en validación automática DIAN para %s: %s", rec.name, e)
                    rec.message_post(
                        body=_("Fallo en la validación automática DIAN: %s") % e)

        return True

    # --- Método refund_sheet (Adaptado) ---
    def refund_sheet(self):
        """Crea una nota de ajuste para esta nómina EDI."""
        new_edi_payslips = self.env['hr.payslip.edi']
        for payslip_edi in self:
            if payslip_edi.credit_note:
                raise UserError(
                    _("No se puede crear una nota de ajuste sobre otra nota de ajuste."))
            if not payslip_edi.edi_is_valid:
                raise UserError(
                    _("Solo se pueden crear notas de ajuste sobre nóminas EDI validadas por la DIAN."))

            default_values = {
                'credit_note': True,
                'name': _('Ajuste: ') + payslip_edi.name,
                'origin_payslip_id': payslip_edi.id,
                'number': _('New'),
                'state': 'draft',
                'payslip_ids': [(6, 0, payslip_edi.payslip_ids.ids)],
                'edi_is_valid': False, 'edi_uuid': False, 'edi_status_code': False,
                'edi_status_message': False, 'edi_errors_messages': False,
                'edi_xml_attachment_id': False, 'edi_response_attachment_id': False,
                # Copiar otros campos relevantes si es necesario
                'employee_id': payslip_edi.employee_id.id,
                'month': payslip_edi.month,
                'year': payslip_edi.year,
                # Fecha actual para la nota
                'date': fields.Date.context_today(self),
                'contract_id': payslip_edi.contract_id.id,
                # 'payment_form_id': payslip_edi.payment_form_id.id, # ELIMINADO
                'payment_method_id': payslip_edi.payment_method_id.id,  # Se copia payment_method_id
            }
            new_edi_payslip = payslip_edi.copy(default_values)
            new_edi_payslips += new_edi_payslip

        action = self.env["ir.actions.actions"]._for_xml_id(
            "l10n_co_nomina.action_hr_payslip_edi")
        if len(new_edi_payslips) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': new_edi_payslips.id,
                'views': [(False, 'form')],
            })
        else:
            action['domain'] = [('id', 'in', new_edi_payslips.ids)]

        return action

    # CORRECCIÓN: Se añade el método que faltaba para el reporte PDF.
    def _get_edi_payload_html_template_name(self):
        """
        ## CORRECCIÓN DEFINITIVA Y CLAVE ##
        Sobrescribe el método de Odoo que elige la plantilla para el campo 'edi_payload_html'.
        En lugar de devolver la plantilla de factura por defecto de Odoo, devolvemos nuestra
        propia plantilla simple y segura, eliminando el error 'is_sale_document' de raíz.
        """
        return 'l10n_co_nomina.hr_payslip_edi_payload_template'

    def _get_edi_report_id(self):
        """
        Este método también es importante y debe permanecer.
        Asegura que cualquier acción de reporte directa use el reporte de nómina consolidada.
        """
        if self.payslip_ids:  # Verifica que es un documento de nómina
            return self.env.ref('l10n_co_nomina.action_hr_payslip_edi_co_report')
        return super()._get_edi_report_id()

# --- Métodos status_zip y status_document_log (Eliminados/Comentados) ---
# def status_zip(self):
#     ... # ELIMINADO/COMENTADO
# def status_document_log(self):
#     ... # ELIMINADO/COMENTADO

# --- Método get_json_delete_request (Eliminado) ---
# def get_json_delete_request(self, requests_data):
#     ... # ELIMINADO
