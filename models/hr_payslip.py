# -*- coding: utf-8 -*-
#
#     inencon S.A.S. - Copyright (C) (2024)
#
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU Lesser General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU Lesser General Public License for more details.
#
#     email: info@inencon.com
#


import calendar
import logging
from collections import defaultdict
from datetime import date, timedelta, datetime

import math

try:
    from dateutil.relativedelta import relativedelta
except ImportError:
    _logger_fallback = logging.getLogger(__name__)
    _logger_fallback.warning(
        "La librería python-dateutil no está instalada. Algunas funcionalidades pueden no estar disponibles.")
    relativedelta = None

# --- Imports de Odoo ---
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero

# --- Definir _logger principal ---
_logger = logging.getLogger(__name__)


class HrPayslip(models.Model):
    _name = 'hr.payslip'
    _inherit = [
        'hr.payslip',
        'mail.thread',
        'mail.activity.mixin',
        'l10n_co_hr_payroll.edi',  # Hereda de nuestra clase EDI CORREGIDA
        # NUEVA HERENCIA para usar los métodos del conector API
        'l10n_co_nomina.payroll.api.connector',
    ]

    origin_payslip_id = fields.Many2one(
        comodel_name="hr.payslip", string="Nómina Origen (Ajuste)", readonly=True, copy=False)

    # Edi fields
    payment_date = fields.Date("Fecha de Pago", required=True,
                               default=lambda self: fields.Date.context_today(
                                   self),
                               readonly=True, tracking=True)

    # --- Campos de totales ---
    accrued_total_amount = fields.Monetary(
        string="Total Devengado", compute='_compute_totals', store=True, readonly=True, tracking=True)
    deductions_total_amount = fields.Monetary(
        string="Total Deducciones", compute='_compute_totals', store=True, readonly=True, tracking=True)
    total_amount = fields.Monetary(
        # Este es el neto
        string="Total Neto", compute='_compute_totals', store=True, readonly=True, tracking=True)
    worked_days_total = fields.Float(
        string="Total Días Trabajados", compute='_compute_totals', store=True, readonly=True, tracking=True)
    others_total_amount = fields.Monetary(
        string="Total Otros", compute='_compute_totals', store=True, readonly=True, tracking=True,
        help="Total de otros conceptos (bases, aportes empleador, provisiones, etc.)")

    earn_ids = fields.One2many('l10n_co_hr_payroll.earn.line', 'payslip_id', string='Detalle Devengos',
                               copy=True, readonly=True, tracking=True)
    deduction_ids = fields.One2many('l10n_co_hr_payroll.deduction.line', 'payslip_id', string='Detalle Deducciones',
                                    copy=True, readonly=True, tracking=True)

    payslip_edi_ids = fields.Many2many(comodel_name='hr.payslip.edi', string='Nóminas Consolidadas EDI',
                                       relation='hr_payslip_hr_payslip_edi_rel',
                                       readonly=True, copy=False)
    is_settlement = fields.Boolean(string='Es Liquidación Final',
                                   default=False,
                                   help="Marcar si esta nómina corresponde a una liquidación final de contrato.",
                                   readonly=True, copy=False)

    month = fields.Selection([
        ('1', 'Enero'), ('2', 'Febrero'), ('3', 'Marzo'), ('4', 'Abril'),
        ('5', 'Mayo'), ('6', 'Junio'), ('7', 'Julio'), ('8', 'Agosto'),
        ('9', 'Septiembre'), ('10', 'Octubre'), ('11',
                                                 'Noviembre'), ('12', 'Diciembre')
    ], string='Mes', compute='_compute_month_year', store=True, copy=False)
    year = fields.Integer(
        string='Año', compute='_compute_month_year', store=True, copy=False)

    # === Campos EDI (Aseguramos su definición explícita o por herencia del mixin l10n_co_hr_payroll.edi) ===
    # Estos campos son los que la vista XML hr_payslip_api_buttons_views.xml espera.
    # Si el mixin l10n_co_hr_payroll.edi ya los define, esta re-definición es inofensiva
    # y asegura que el ORM los reconozca si hay algún problema de carga con el mixin.
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
    l10n_co_edi_qr_code_url = fields.Char(
        string='URL QR DIAN', copy=False, help="URL para consultar el documento en el portal de la DIAN.")
    l10n_co_edi_xml_file = fields.Binary(
        string='XML DIAN', attachment=True, copy=False, help="Archivo XML de la Nómina Electrónica.")
    l10n_co_edi_pdf_file = fields.Binary(
        string='PDF DIAN', attachment=True, copy=False, help="Representación gráfica en PDF de la Nómina Electrónica.")
    # Si lo usas en el XML, debe estar aquí.
    edi_uuid = fields.Char(string='UUID EDI', copy=False,
                           help="UUID del documento electrónico.")
    edi_payload = fields.Text(string='Payload EDI (Debug)', groups="base.group_no_one",
                              copy=False, help="Contenido del payload enviado/recibido para depuración.")

    @api.depends('date_to')
    def _compute_month_year(self):
        for rec in self:
            if rec.date_to:
                rec.month = str(rec.date_to.month)
                rec.year = rec.date_to.year
            else:
                rec.month = False
                rec.year = False

    @api.depends(
        'earn_ids.amount',
        'deduction_ids.amount',
        'line_ids.total',
        'line_ids.category_id.code',
        'line_ids.salary_rule_id.type_concept',
        'line_ids.salary_rule_id.category_id.code',
        'worked_days_line_ids.number_of_days',
        'worked_days_line_ids.code',
    )
    def _compute_totals(self):
        """Calcula los totales de devengados, deducciones, neto, días trabajados y otros,
           sumando desde earn_ids, deduction_ids y líneas 'other'."""

        for payslip in self:
            accrued = 0.0
            deductions = 0.0
            others = 0.0
            total_neto_calculated = 0.0

            # --- CORRECCIÓN ERROR 2: Obtener redondeo de moneda de forma segura ---
            currency = payslip.currency_id or payslip.contract_id.company_id.currency_id or self.env.company.currency_id
            # Usar un default si no se encuentra o es 0
            current_precision_rounding = currency.rounding if currency and currency.rounding > 0 else 0.01
            # --- FIN CORRECCIÓN ERROR 2 ---

            # --- CORRECCIÓN: Sumar desde line_ids (reglas calculadas) y opcionalmente detalles (earn_ids/deduction_ids) ---
            # Sumar Devengos desde line_ids con categoría ALW, BASIC, GROSS, NET (o las que uses para devengos)
            # Ajusta los códigos de categoría según tu configuración.
            accrued = sum(line.total for line in payslip.line_ids if line.category_id and line.category_id.code in [
                'ALW', 'BASIC', 'IBC', 'BASE_PRESTACIONES', 'LIC_INC',])
            # Opcional: Sumar detalles manuales si son adicionales y no alimentan reglas que ya se sumaron.
            # accrued += sum(payslip.earn_ids.mapped('amount')) if payslip.earn_ids else 0.0

            # Sumar Deducciones desde line_ids con categoría DED (o la que uses para deducciones)
            # Ajusta los códigos de categoría según tu configuración.
            deductions = sum(
                line.total for line in payslip.line_ids if line.category_id and line.category_id.code in ['DED'])
            # Opcional: Sumar detalles manuales si son adicionales.
            # deductions += sum(payslip.deduction_ids.mapped('amount')) if payslip.deduction_ids else 0.0

            # Calcular 'Others' y capturar Neto de line_ids
            net_line_total = 0.0
            net_category_code = 'NET'

            for line in payslip.line_ids:
                # Usar float_is_zero con el redondeo seguro
                if float_is_zero(line.total, precision_rounding=current_precision_rounding):
                    continue  # Saltar líneas con total cero

                # Excluir la línea de Total Neto si existe (basado en categoría)
                if line.category_id and line.category_id.code == net_category_code:
                    net_line_total = line.total
                    continue  # Pasar a la siguiente línea

                # Sumar líneas cuya regla salarial tiene type_concept == 'other' en el total 'Otros'
                if line.salary_rule_id and line.salary_rule_id.type_concept == 'other':
                    # El total de estas reglas 'other' suele ser positivo
                    others += line.total
                # Nota: Las líneas manuales sin regla salarial asociada (line.salary_rule_id is False)
                # no se sumarán aquí a 'others'.

            # --- CORRECCIÓN: Calcular worked_days_total para reflejar días laborados/pagados ---
            # Esta lógica debe alinearse con la forma en que tu regla "Salario Básico" calcula los días pagados.
            # La regla resta las ausencias específicas de un mes de 30 días.
            leave_codes_reducing_salary_payment = [
                'LNR', 'SUS', 'IGE1_2', 'IGE3_90', 'IGE91_180', 'IGE181_MAS',
                # Estos son los códigos de ausencias que reducen el salario, según tu regla.
                'LMA', 'LR', 'ATEP', 'VACDISF'
            ]

            total_absent_days_reducing_salary = 0.0
            for wd_line in payslip.worked_days_line_ids:
                if wd_line.code in leave_codes_reducing_salary_payment:
                    try:
                        total_absent_days_reducing_salary += float(
                            wd_line.number_of_days or 0.0)
                    except (ValueError, TypeError):
                        _logger.warning(
                            "Error convirtiendo number_of_days para worked_day %s en nómina %s", wd_line.code, payslip.name)
                        pass

            # Asumiendo un mes de 30 días para cálculo de nómina en Colombia
            days_in_month_theory = 30.0
            total_paid_days = max(
                0.0, days_in_month_theory - total_absent_days_reducing_salary)

            # --- 4. Calcular Total Neto ---
            # Usar el total de la línea NET si existe, de lo contrario Devengados - Deducciones (ya que deduction.amount es positivo)
            # Usar current_precision_rounding definido arriba
            total_neto_calculated = net_line_total if not float_is_zero(
                net_line_total, precision_rounding=current_precision_rounding) else (accrued - deductions)

            # --- Asignar Totales y Días ---
            # Usar redondeo de moneda para los campos monetarios
            # Usar la variable 'currency' obtenida de forma segura al inicio
            currency = payslip.currency_id if payslip.currency_id else payslip.env.company.currency_id

            payslip.accrued_total_amount = currency.round(
                accrued) if currency else round(accrued, 2)
            # deductions.amount es positivo, lo asignamos directamente al total de deducciones
            payslip.deductions_total_amount = currency.round(
                deductions) if currency else round(deductions, 2)
            payslip.total_amount = currency.round(
                total_neto_calculated) if currency else round(total_neto_calculated, 2)
            # Asignar el total de días pagados/trabajados calculados
            payslip.worked_days_total = total_paid_days
            payslip.others_total_amount = currency.round(
                others) if currency else round(others, 2)

    # =========================================================================
    # MÉTODO compute_sheet - ACTUALIZADO CON CARGA DE RECURRENTES Y LOGS DE DEBUG
    # =========================================================================
    def compute_sheet(self):
        # ¡AJUSTA ESTA LISTA CON TUS CÓDIGOS!
        recurring_input_codes_to_manage = ['LIBRANZA']

        for payslip_rec in self:
            _logger.info(
                "Iniciando compute_sheet para Recibo ID: %s, Número: %s, Empleado: %s (ID: %s), Contrato: %s (ID: %s), Periodo: %s a %s",
                payslip_rec.id,
                payslip_rec.number,
                payslip_rec.employee_id.name if payslip_rec.employee_id else "N/A",
                payslip_rec.employee_id.id if payslip_rec.employee_id else "N/A",
                payslip_rec.contract_id.name if payslip_rec.contract_id else "N/A",
                payslip_rec.contract_id.id if payslip_rec.contract_id else "N/A",
                payslip_rec.date_from,
                payslip_rec.date_to
            )

            # 1. Lógica existente: Asignar número al recibo si es nuevo
            if not payslip_rec.number or payslip_rec.number in ('New', _('New')):
                sequence_code = 'salary.slip.note' if payslip_rec.credit_note else 'salary.slip'
                payslip_rec.number = self.env['ir.sequence'].next_by_code(
                    sequence_code) or _('New')
                _logger.info("Número de secuencia asignado a Recibo ID %s: %s",
                             payslip_rec.id, payslip_rec.number)

            # 2. Borrar "Otras Entradas" auto-generadas previamente (solo en borradores)
            if payslip_rec.state == 'draft':
                inputs_to_delete = payslip_rec.input_line_ids.filtered(
                    lambda inp: inp.input_type_id.code in recurring_input_codes_to_manage
                )
                if inputs_to_delete:
                    _logger.info("Borrando %s 'Otras Entradas' auto-generadas previas para Recibo ID %s (Códigos: %s).",
                                 len(inputs_to_delete), payslip_rec.id, [inp.input_type_id.code for inp in inputs_to_delete])
                    inputs_to_delete.unlink()

            # 3. Cargar Conceptos Recurrentes por Empleado como "Otras Entradas"
            if payslip_rec.employee_id and payslip_rec.contract_id:
                RecurringItemModel = self.env['hr.employee.recurring.item']

                # --- INICIO: LOGS DE DEPURACIÓN ESPECÍFICOS PARA LIBRANZA (O EL ITEM QUE QUIERAS DEPURAR) ---
                # Busca específicamente el item de LIBRANZA para este empleado/contrato para ver sus datos
                # Asumimos que el 'salary_rule_code' en el item recurrente para la libranza es 'LIBRANZA'
                specific_item_to_debug = RecurringItemModel.search([
                    ('employee_id', '=', payslip_rec.employee_id.id),
                    ('contract_id', '=', payslip_rec.contract_id.id),
                    # Código de la regla de Libranza
                    ('salary_rule_code', '=', 'LIBRANZA')
                ], limit=1)  # Asumimos que hay uno o nos interesa el primero para depurar

                if specific_item_to_debug:
                    item_debug = specific_item_to_debug
                    _logger.info(
                        "Recibo ID %s: [DEBUG LIBRANZA] Datos del Item Recurrente LIBRANZA encontrado (ID: %s):", payslip_rec.id, item_debug.id)
                    _logger.info(
                        "  [DEBUG LIBRANZA] Active: %s", item_debug.active)
                    _logger.info("  [DEBUG LIBRANZA] Date Start: %s (<= Payslip Date To: %s?) -> %s",
                                 item_debug.date_start, payslip_rec.date_to, item_debug.date_start <= payslip_rec.date_to if item_debug.date_start else "N/A")
                    _logger.info("  [DEBUG LIBRANZA] Date End: %s (>= Payslip Date From: %s? or False) -> %s",
                                 # Corrección en la condición de log
                                 item_debug.date_end, payslip_rec.date_from, (item_debug.date_end is False or (item_debug.date_end and item_debug.date_end >= payslip_rec.date_from)) if item_debug.date_start else "N/A")
                    _logger.info(
                        "  [DEBUG LIBRANZA] Use Installments: %s", item_debug.use_installments)
                    _logger.info(
                        "  [DEBUG LIBRANZA] N Total Cuotas: %s", item_debug.number_of_installments)
                    _logger.info(
                        "  [DEBUG LIBRANZA] Cuota Actual Procesada: %s", item_debug.current_installment)
                    _logger.info("  [DEBUG LIBRANZA] Remaining Installments (calculado): %s (>0?) -> %s",
                                 item_debug.remaining_installments, item_debug.remaining_installments > 0)
                    _logger.info(
                        "  [DEBUG LIBRANZA] Monto Total: %s", item_debug.total_amount)
                    _logger.info(
                        "  [DEBUG LIBRANZA] Monto Pagado: %s", item_debug.paid_amount)
                    _logger.info("  [DEBUG LIBRANZA] Remaining Balance (calculado): %s (>0.005?) -> %s",
                                 item_debug.remaining_balance, item_debug.remaining_balance > 0.005)
                else:
                    _logger.warning(
                        "Recibo ID %s: [DEBUG LIBRANZA] NO SE ENCONTRÓ NINGÚN item recurrente con salary_rule_code 'LIBRANZA' para el empleado/contrato.", payslip_rec.id)
                # --- FIN: LOGS DE DEPURACIÓN ESPECÍFICOS ---

                domain = [
                    ('employee_id', '=', payslip_rec.employee_id.id),
                    ('contract_id', '=', payslip_rec.contract_id.id),
                    ('active', '=', True),
                    ('date_start', '<=', payslip_rec.date_to),
                    '|', ('date_end', '=', False), ('date_end',
                                                    '>=', payslip_rec.date_from),
                    '|', ('use_installments', '=', False),
                    '&', ('use_installments', '=', True),
                    '|', ('remaining_installments', '>', 0),
                    ('remaining_balance', '>', 0.005)
                ]
                active_recurring_items = RecurringItemModel.search(domain)
                _logger.info("Recibo ID %s: (Búsqueda principal) Se encontraron %s conceptos recurrentes activos para el empleado %s.",
                             payslip_rec.id, len(active_recurring_items), payslip_rec.employee_id.name)

                new_input_vals_list = []
                for item in active_recurring_items:
                    input_code = item.salary_rule_code
                    if not input_code:
                        _logger.warning("Recibo ID %s: Concepto recurrente ID %s (Tipo: %s) no tiene un código de regla salarial. Omitiendo.",
                                        payslip_rec.id, item.id, item.recurring_item_type_id.name)
                        continue

                    current_period_amount = 0.0
                    if item.amount_type == 'fix':
                        current_period_amount = item.amount
                    elif item.amount_type == 'percentage':
                        _logger.warning("Recibo ID %s: Item recurrente porcentual ID %s para regla %s. El cálculo de porcentaje basado en categorías no es soportado en la creación de inputs. Se usará el campo 'amount' como fallback o cero.",
                                        payslip_rec.id, item.id, input_code)
                        current_period_amount = item.amount  # Fallback

                    if item.use_installments:
                        if item.remaining_installments > 0 and item.remaining_balance > 0.005:
                            current_period_amount = min(
                                current_period_amount, item.remaining_balance)
                        else:
                            _logger.info("Recibo ID %s: Item recurrente ID %s (Regla: %s) usa cuotas pero no hay cuotas/saldo pendiente significativo (filtrado por domain, doble chequeo). Omitiendo.",
                                         payslip_rec.id, item.id, input_code)
                            continue

                    if current_period_amount <= 0.005:
                        _logger.info("Recibo ID %s: Monto para input de regla %s es cero o insignificante (%s). Omitiendo.",
                                     payslip_rec.id, input_code, current_period_amount)
                        continue

                    InputTypeModel = self.env['hr.payslip.input.type']
                    input_type = InputTypeModel.search(
                        [('code', '=', input_code)], limit=1)

                    if not input_type:
                        _logger.warning("Recibo ID %s: No se encontró un Tipo de Entrada ('hr.payslip.input.type') con el código '%s' para el item recurrente ID %s. El input no será creado. Por favor, cree este Tipo de Entrada.",
                                        payslip_rec.id, input_code, item.id)
                        continue

                    input_vals = {
                        'payslip_id': payslip_rec.id,
                        'input_type_id': input_type.id,
                        'amount': current_period_amount,
                        'contract_id': payslip_rec.contract_id.id,
                        # 'partner_id': item.partner_id.id if item.partner_id else False, # Si personalizaste hr.payslip.input
                        # 'x_recurring_item_id': item.id, # Si personalizaste hr.payslip.input
                    }
                    new_input_vals_list.append(input_vals)
                    _logger.info("Recibo ID %s: 'Otra Entrada' preparada para regla '%s' con monto %s.",
                                 payslip_rec.id, input_code, current_period_amount)

                if new_input_vals_list:
                    self.env['hr.payslip.input'].create(new_input_vals_list)
                    _logger.info("Recibo ID %s: Creadas %s 'Otras Entradas' desde conceptos recurrentes.",
                                 payslip_rec.id, len(new_input_vals_list))
            else:
                _logger.warning(
                    "Recibo ID %s: No se procesaron conceptos recurrentes porque falta empleado o contrato en el recibo.", payslip_rec.id)

        # 4. Llamar al compute_sheet original de Odoo.
        res = super(HrPayslip, self).compute_sheet()

        # 5. Actualizar el estado de los items recurrentes procesados (CUOTAS)
        for payslip_rec_processed in self:
            if not (payslip_rec_processed.employee_id and payslip_rec_processed.contract_id):
                continue

            # Re-obtener los items que usan cuotas y cuyo código de regla está en nuestra lista gestionada.
            # Solo actualizamos los que son manejados por este mecanismo.
            RecurringItemModel = self.env['hr.employee.recurring.item']
            items_to_check_domain = [
                ('employee_id', '=', payslip_rec_processed.employee_id.id),
                ('contract_id', '=', payslip_rec_processed.contract_id.id),
                ('salary_rule_code', 'in', recurring_input_codes_to_manage),
                # Importante: solo actualiza los que aún podrían estar activos
                ('active', '=', True),
                ('use_installments', '=', True)
            ]
            items_using_installments = RecurringItemModel.search(
                items_to_check_domain)

            # Crear un mapa para fácil acceso: { 'CODIGO_REGLA': item_recurrente_obj }
            # Esto asume un solo item activo por código de regla/empleado/contrato. Si pueden ser múltiples, esta lógica de mapa es muy simple.
            item_map_for_update = {
                item.salary_rule_code: item for item in items_using_installments}

            for line in payslip_rec_processed.line_ids:
                if line.salary_rule_id.code in item_map_for_update:
                    item_to_update = item_map_for_update[line.salary_rule_id.code]
                    # El total de la línea de deducción es negativo
                    amount_deducted = abs(line.total)

                    if amount_deducted > 0.005:  # Solo actualizar si se descontó algo significativo
                        try:
                            # Llamar al método que está en hr.employee.recurring.item
                            item_to_update.update_processed_installment(
                                amount_deducted)
                            _logger.info("Recibo ID %s: Cuota actualizada para item recurrente ID %s (Regla: %s) con monto %s.",
                                         payslip_rec_processed.id, item_to_update.id, line.salary_rule_id.code, amount_deducted)
                        except Exception as e_update:
                            _logger.error("Recibo ID %s: Error actualizando cuota para item recurrente ID %s (Regla: %s): %s",
                                          payslip_rec_processed.id, item_to_update.id, line.salary_rule_id.code, str(e_update))

        _logger.info(
            "Finalizado compute_sheet para el(los) recibo(s) procesado(s) ID(s): %s", self.ids)
        return res

    # =========================================================================
    # MÉTODOS HELPER (Reorganizados y Ajustados)
    # =========================================================================

    def _calculate_days_360_helper(self, start_dt, end_dt):
        """
        Calcula días trabajados/periodo usando base 360.
        Función helper para evitar duplicación.
        """
        # Asegúrate de importar date al inicio del archivo
        # from datetime import date

        # Validaciones básicas
        if not isinstance(start_dt, date) or not isinstance(end_dt, date):
            _logger.warning(
                f"Fechas inválidas para cálculo días 360: {start_dt}, {end_dt}")
            return 0

        if start_dt > end_dt:  # No usar &gt; en Python
            # _logger.warning(f"Fecha inicio ({start_dt}) es posterior a fecha fin ({end_dt}) para cálculo días 360.")
            return 0

        # Implementación base 360 (SUSCEPTIBLE A ERRORES EN BORDES - Revisar ley/contabilidad CO)
        # Método: Año 360, Mes 30. Si día inicio o fin es 31, se toma como 30.
        d1, m1, y1 = start_dt.day, start_dt.month, start_dt.year
        d2, m2, y2 = end_dt.day, end_dt.month, end_dt.year

        # Ajuste común para base 360: si es 31, tratar como 30
        if d1 == 31:
            d1 = 30
        # Corrección: si d1 también es 30 (o 28/29 si febrero), d2 también es 30.
        if d2 == 31:
            # Si d1 es fin de mes de 30/31, o fin de Feb
            if d1 in (30, 31) or (m1 == 2 and d1 == calendar.monthrange(y1, m1)[1]):
                d2 = 30
            # Si no, d2=31 se toma como 30 si es para el mismo mes o si el mes tiene 31 días y d1 no es fin de mes.
            # Esta parte de la lógica 360 puede ser compleja y depende de la convención exacta.
            # Por ahora, simplificamos a que si d2 es 31, se trata como 30.
            else:
                d2 = 30

        # Corrección fórmula días base 360 (sumar 1 para incluir el día final)
        days = ((y2 - y1) * 360) + ((m2 - m1) * 30) + (d2 - d1) + 1
        # Devolver resultado (puede ser negativo si fechas están muy invertidas a pesar de la validación inicial)
        return days

    # --- NUEVO MÉTODO: Obtener IBC Mes Anterior (CRÍTICO - REQUIERE IMPLEMENTACIÓN) ---
    # Este método es CRÍTICO y requiere IMPLEMENTACIÓN DETALLADA Y PROBADA.
    # La lógica de búsqueda y obtención del IBC del recibo anterior puede variar
    # ligeramente dependiendo de tu estructura de datos exacta y si manejas múltiples contratos.
    # Debería ser capaz de buscar el IBC del mes anterior a CUALQUIER fecha dada (date_limit).
    # Se llama desde subsidios de ausencias para obtener la base.
    # También podría llamarse en _calculate_ibc si la lógica de base de vacaciones/incapacidades se implementa allí.

    # --- INICIO NUEVOS HELPERS PARA IBC ---

    def _get_rules_dict(self):
        """Retorna un diccionario con las líneas de reglas salariales del recibo."""
        # Usar line.salary_rule_id.code es más robusto
        return {
            (line.salary_rule_id.code if line.salary_rule_id and line.salary_rule_id.code else line.code): {
                'total': line.total or 0.0,  # Asegurar que total tenga un valor
                'amount': line.amount or 0.0,
                'quantity': line.quantity or 0.0,
                # 'rate': line.rate, # rate no es un campo estándar de hr.payslip.line, comentar si no existe
            } for line in self.line_ids
        }

    def _get_rule_total(self, code, rules_dict):
        """Retorna el total absoluto de una regla salarial por código desde un diccionario de reglas."""
        return abs(rules_dict.get(code, {}).get('total', 0.0))

    def _get_smmlv_and_precision(self):
        smmlv = 0.0
        precision_rounding = 0.01  # Default
        # Asegurar que company_id se obtiene
        company_id = self.company_id or (
            self.contract_id and self.contract_id.company_id)

        if company_id:
            smmlv_value_from_company = getattr(company_id, 'smmlv_value', None)
            if smmlv_value_from_company is not None:
                try:
                    smmlv = float(smmlv_value_from_company)
                except (ValueError, TypeError):
                    _logger.warning(
                        f"[IBC HELPER] Valor de SMMLV en compañía ({company_id.name}) no es un número válido: '{smmlv_value_from_company}' para nómina {self.number if hasattr(self, 'number') else 'N/A'}")
            # else: # Log opcional si el campo no está configurado
                # _logger.info(f"[IBC HELPER] Campo 'smmlv_value' no encontrado/configurado en compañía {company_id.name}. SMMLV será 0 para nómina {self.number if hasattr(self, 'number') else 'N/A'}.")
        else:
            _logger.warning(
                f"[IBC HELPER] No se pudo acceder a company_id para obtener SMMLV en la nómina {self.number if hasattr(self, 'number') else 'N/A'}.")

        if self.currency_id and hasattr(self.currency_id, 'rounding') and self.currency_id.rounding > 0:
            precision_rounding = self.currency_id.rounding
        return smmlv, precision_rounding

    def _get_days_to_liquidate(self):
        days_to_liquidate = 30.0
        # !!! ===================================================================== !!!
        # !!! PERSONALIZA ESTA LISTA con tus códigos de ausencias NO remuneradas    !!!
        # !!! que afectan los días base para topes de IBC (ej. LNR, SUS)          !!!
        # !!! ===================================================================== !!!
        unpaid_leave_codes = ['LNR', 'SUS']
        unpaid_leave_days = 0.0
        if self.worked_days_line_ids:
            for wd_line in self.worked_days_line_ids:
                if wd_line.code in unpaid_leave_codes:
                    try:
                        unpaid_leave_days += float(
                            wd_line.number_of_days or 0.0)
                    except (ValueError, TypeError):
                        _logger.warning(
                            f"Error convirtiendo number_of_days para worked_day {wd_line.code} en nómina {self.number if hasattr(self, 'number') else 'N/A'}")
        days_to_liquidate = min(30.0, max(0.0, 30.0 - unpaid_leave_days))
        return days_to_liquidate
    # --- FIN NUEVOS HELPERS PARA IBC ---

    def _get_previous_month_ibc(self, date_limit):
        """
        Busca el IBC del recibo de nómina del mes calendario ANTERIOR a date_limit para el empleado/contrato.
        Retorna el valor del IBC encontrado o el salario base del contrato actual si no se encuentra un recibo válido
        o la línea IBC no está en el recibo encontrado.
        ¡¡IMPLEMENTACIÓN DETALLADA PENDIENTE!!
        """
        self.ensure_one()  # Procesa un payslip a la vez
        employee = self.employee_id
        contract = self.contract_id  # Usar self.contract_id que es el del payslip actual
        default_wage = 0.0
        # Usar hasattr para acceso seguro
        if contract and hasattr(contract, 'wage'):
            try:
                default_wage = float(contract.wage or 0.0)
            except (ValueError, TypeError):
                pass  # default_wage permanece 0.0

        # Validaciones básicas
        if not employee or not contract or not date_limit or not isinstance(date_limit, date):
            _logger.warning(
                f"[PREV_IBC] No se puede buscar IBC anterior para {self.name}: Faltan datos. Fallback a salario: {default_wage}")
            return default_wage

        # --- 1. Determinar el Periodo Calendario Anterior Relevante ---
        try:
            first_day_of_date_limit_month = date(
                date_limit.year, date_limit.month, 1)
            last_day_of_previous_month = first_day_of_date_limit_month - \
                timedelta(days=1)

        except Exception as e:
            _logger.error(
                f"[PREV_IBC] Error calculando fecha fin mes anterior a {date_limit} para {self.name}: {e}. Fallback a salario: {default_wage}")
            return default_wage

        # --- 2. Buscar el Recibo de Nómina del Periodo Anterior ---
        payslip_env = self.env['hr.payslip']
        search_domain = [
            ('employee_id', '=', employee.id),
            # Considerar si el contrato pudo haber cambiado
            ('contract_id', '=', contract.id),
            ('state', 'in', ('done', 'paid')),  # Debe ser un recibo finalizado
            ('date_to', '>=', date(last_day_of_previous_month.year,
                                   last_day_of_previous_month.month, 1)),
            ('date_to', '<=', last_day_of_previous_month),
        ]

        previous_payslip = payslip_env.search(
            search_domain, order='date_to desc', limit=1)

        # --- 3. Obtener el Valor del IBC del Recibo Encontrado ---
        if not previous_payslip:
            _logger.warning(
                f"[PREV_IBC] No se encontró recibo anterior para {self.name} (contrato {contract.name}) antes de {date_limit.strftime('%Y-%m-%d')}. Fallback a salario: {default_wage}.")
            return default_wage

        # Asegúrate que 'IBC' es el código de tu regla de IBC
        ibc_line = previous_payslip.line_ids.filtered(
            lambda line: line.salary_rule_id and line.salary_rule_id.code == 'IBC')

        if ibc_line:
            try:
                ibc_value = float(ibc_line[0].total or 0.0)
                _logger.info(
                    f"[PREV_IBC] IBC anterior ({previous_payslip.date_to.strftime('%Y-%m-%d')}) para {self.name}: {ibc_value}")
                return ibc_value
            except (ValueError, TypeError):
                _logger.warning(
                    f"[PREV_IBC] Recibo anterior {previous_payslip.name} encontrado, línea IBC encontrada, pero total '{ibc_line[0].total}' no es numérico. Fallback a salario: {default_wage}.")
                return default_wage
        else:
            _logger.warning(
                f"[PREV_IBC] Recibo anterior {previous_payslip.name} encontrado, pero no se encontró línea de regla IBC. Fallback a salario: {default_wage}.")
            return default_wage
    # --- FIN MÉTODO: Obtener IBC Mes Anterior ---

    # --- NUEVO MÉTODO: Calcular Subsidio IGE por Tipo (Pendiente Lógica Acumulada) ---
    def _calculate_ige_subsidy_by_code(self, leave_type_code, leave_days_in_period):
        # Tu código existente, con inicialización de daily_base y percentage y precision_rounding_currency
        self.ensure_one()
        payslip = self
        contract = self.contract_id
        result = 0.0
        daily_base = 0.0
        percentage = 0.0
        precision_rounding_currency = payslip.currency_id.rounding if payslip.currency_id and hasattr(
            payslip.currency_id, 'rounding') and payslip.currency_id.rounding > 0 else 0.01

        if not contract or not leave_days_in_period or not isinstance(leave_days_in_period, (int, float)) or float_is_zero(leave_days_in_period, precision_digits=2) or not payslip.date_from or not isinstance(payslip.date_from, date):
            _logger.warning(
                f"No se puede calcular subsidio IGE ({leave_type_code}) para {payslip.name}: Faltan datos (contrato, días válidos, fecha).")
            return result

        previous_month_ibc = self._get_previous_month_ibc(payslip.date_from)

        if previous_month_ibc > 0:
            daily_base = previous_month_ibc / 30.0
            if not isinstance(daily_base, (int, float)):
                daily_base = 0.0

            if leave_type_code == 'IGE1_2':
                percentage = 0.0
            elif leave_type_code == 'IGE3_90':
                percentage = 66.67
            elif leave_type_code == 'IGE91_180':
                percentage = 50.0
            elif leave_type_code == 'IGE181_MAS':
                percentage = 50.0

            result = daily_base * leave_days_in_period * (percentage / 100.0)

            # Usa la precisión de la moneda
            if not float_is_zero(result, precision_rounding=precision_rounding_currency):
                result = payslip.currency_id.round(result) if payslip.currency_id and hasattr(
                    # Asegurar que round existe
                    payslip.currency_id, 'round') else round(result, 2)
            else:
                result = 0.0
        _logger.info(
            f"Cálculo subsidio IGE ({leave_type_code}, {leave_days_in_period} días) para {payslip.name}: IBC Anterior={previous_month_ibc:.2f}, Daily Base={daily_base:.2f}, Porcentaje={percentage:.2f}, Resultado={result:.2f}")
        return result

    # --- NUEVO MÉTODO: Calcular Subsidio ATEP (Pendiente Lógica Acumulada/Detalle) ---
    def _calculate_atep_subsidy(self, incapacity_days_in_period):
        # Tu código existente, con inicialización de daily_base
        self.ensure_one()
        payslip = self
        contract = self.contract_id
        result = 0.0
        daily_base = 0.0
        precision_rounding_currency = payslip.currency_id.rounding if payslip.currency_id and hasattr(
            payslip.currency_id, 'rounding') and payslip.currency_id.rounding > 0 else 0.01

        if not contract or not incapacity_days_in_period or not isinstance(incapacity_days_in_period, (int, float)) or float_is_zero(incapacity_days_in_period, precision_digits=2) or not payslip.date_from or not isinstance(payslip.date_from, date):
            _logger.warning(
                f"No se puede calcular subsidio ATEP para {payslip.name}: Faltan datos (contrato, días válidos, fecha).")
            return result

        previous_month_ibc = self._get_previous_month_ibc(payslip.date_from)

        if previous_month_ibc > 0:
            daily_base = previous_month_ibc / 30.0
            if not isinstance(daily_base, (int, float)):
                daily_base = 0.0
            percentage = 100.0
            result = daily_base * incapacity_days_in_period * \
                (percentage / 100.0)
            if not float_is_zero(result, precision_rounding=precision_rounding_currency):
                result = payslip.currency_id.round(result) if payslip.currency_id and hasattr(
                    payslip.currency_id, 'round') else round(result, 2)
            else:
                result = 0.0
        _logger.info(
            f"Cálculo subsidio ATEP ({incapacity_days_in_period} días) para {payslip.name}: IBC Anterior={previous_month_ibc:.2f}, Daily Base={daily_base:.2f}, Resultado={result:.2f}")
        return result

    # --- NUEVO MÉTODO: Calcular Subsidio LMA (Pendiente Lógica Acumulada/Detalle) ---
    def _calculate_lma_subsidy(self, leave_days_in_period):
        # Tu código existente, con inicialización de daily_base
        self.ensure_one()
        payslip = self
        contract = self.contract_id
        result = 0.0
        daily_base = 0.0
        precision_rounding_currency = payslip.currency_id.rounding if payslip.currency_id and hasattr(
            payslip.currency_id, 'rounding') and payslip.currency_id.rounding > 0 else 0.01

        if not contract or not leave_days_in_period or not isinstance(leave_days_in_period, (int, float)) or float_is_zero(leave_days_in_period, precision_digits=2) or not payslip.date_from or not isinstance(payslip.date_from, date):
            _logger.warning(
                f"No se puede calcular subsidio LMA para {payslip.name}: Faltan datos (contrato, días válidos, fecha).")
            return result

        previous_month_ibc = self._get_previous_month_ibc(payslip.date_from)

        if previous_month_ibc > 0:
            daily_base = previous_month_ibc / 30.0
            if not isinstance(daily_base, (int, float)):
                daily_base = 0.0
            percentage = 100.0
            result = daily_base * leave_days_in_period * (percentage / 100.0)
            if not float_is_zero(result, precision_rounding=precision_rounding_currency):
                result = payslip.currency_id.round(result) if payslip.currency_id and hasattr(
                    payslip.currency_id, 'round') else round(result, 2)
            else:
                result = 0.0
        _logger.info(
            f"Cálculo subsidio LMA ({leave_days_in_period} días) para {payslip.name}: IBC Anterior={previous_month_ibc:.2f}, Daily Base={daily_base:.2f}, Resultado={result:.2f}")
        return result

    def _calculate_days_for_cesantias_intereses(self, period_start_date, period_end_date_calculation, worked_days_dict):
        # Tu código existente
        self.ensure_one()
        days_in_period_360 = self._calculate_days_360_helper(
            period_start_date, period_end_date_calculation)
        days_in_period_360 = max(0, days_in_period_360)

        # !!! PERSONALIZA unpaid_leave_codes si es diferente para cesantías !!!
        unpaid_leave_codes = ['LNR', 'SUS']
        unpaid_leave_days = 0.0
        for code in unpaid_leave_codes:  # Renombrada variable de bucle
            wd_line = worked_days_dict.get(code)
            if wd_line:
                try:
                    unpaid_leave_days += float(wd_line.number_of_days or 0.0)
                except (ValueError, TypeError):
                    pass
        days_to_liquidate = max(0, days_in_period_360 - unpaid_leave_days)
        return days_to_liquidate
    # --- FIN NUEVO MÉTODO HELPER (que ya tenías, solo lo moví con los otros helpers) ---    def _calculate_days_for_cesantias_intereses(self, period_start_date, period_end_date_calculation, worked_days_dict):
        """
        Calcula los días a liquidar para Cesantías e Intereses de Cesantías.
        Usa base 360 y descuenta ausencias no remuneradas (simplificado).
        """
        self.ensure_one()
        # Calcular días base 360 en el periodo
        days_in_period_360 = self._calculate_days_360_helper(
            period_start_date, period_end_date_calculation)
        days_in_period_360 = max(0, days_in_period_360)

        # Descontar Ausencias No Remuneradas (Simplificado - solo este recibo)
        unpaid_leave_codes = ['LNR', 'SUS']  # Ajustar
        unpaid_leave_days = 0.0
        for code in unpaid_leave_codes:
            wd_line = worked_days_dict.get(code)
            if wd_line:
                try:
                    unpaid_leave_days += float(wd_line.number_of_days or 0.0)
                except (ValueError, TypeError):
                    pass

        days_to_liquidate = max(0, days_in_period_360 - unpaid_leave_days)
        return days_to_liquidate

    # --- FIN NUEVO MÉTODO HELPER ---
# =========================================================================
    # MÉTODOS DE CÁLCULO DE PRESTACIONES/SUBSIDIOS - CORREGIDOS
    # (Sintaxis, acceso a campos, y notas sobre complejidad pendiente)
    # =========================================================================

    # --- MÉTODO PARA CALCULAR PRIMA ---
    def _calculate_prima_servicios(self):
        """
        Calcula el valor de la prima de servicios.
        ¡¡ATENCIÓN!! Implementación SIMPLIFICADA.
        Requiere lógica detallada para promedios, base 360 y ausencias.
        """
        self.ensure_one()  # Asegura que se procesa un payslip a la vez
        payslip = self
        contract = self.contract_id
        # Usar line.salary_rule_id.code para más precisión en las claves del category_map
        category_map = {
            (line.salary_rule_id.code if line.salary_rule_id and line.salary_rule_id.code else line.code): line.total
            for line in payslip.line_ids
        }
        worked_days_dict = {wd.code: wd for wd in payslip.worked_days_line_ids}

        result = 0.0  # Inicializar resultado
        contract_wage = 0.0  # Inicializar
        if contract and hasattr(contract, 'wage'):  # Acceso seguro a contract.wage
            try:
                contract_wage = float(contract.wage or 0.0)
            except (ValueError, TypeError):
                pass  # contract_wage permanece 0.0

        if not contract or contract_wage <= 0 or not payslip.date_to or not payslip.date_from:
            _logger.warning(
                f"No se puede calcular prima para {payslip.name}: Faltan datos (contrato, salario válido, fechas).")
            return result

        # --- 1. Determinar Fechas del Periodo ---
        period_end_date = payslip.date_to
        is_final_settlement = payslip.is_settlement
        period_start_date = date(1, 1, 1)  # Placeholder
        period_end_date_calculation = date(1, 1, 1)  # Placeholder

        try:
            if not contract.date_start:  # Validación adicional
                _logger.warning(
                    f"Contrato {contract.name} no tiene fecha de inicio para cálculo de prima en {payslip.name}.")
                return 0.0

            if 1 <= period_end_date.month <= 6:
                period_start_date = date(period_end_date.year, 1, 1)
                period_end_date_calculation = date(
                    period_end_date.year, 6, 30) if not is_final_settlement else period_end_date
            elif 7 <= period_end_date.month <= 12:
                period_start_date = date(period_end_date.year, 7, 1)
                period_end_date_calculation = date(
                    period_end_date.year, 12, 31) if not is_final_settlement else period_end_date
            else:
                _logger.info(
                    f"La fecha fin de nómina ({period_end_date}) no está en un rango semestral esperado para prima en {payslip.name}.")
                return 0.0

            period_start_date = max(period_start_date, contract.date_start)
            # Asegurar que fin no sea antes que inicio
            period_end_date_calculation = max(
                period_start_date, period_end_date_calculation)

            if not is_final_settlement and payslip.date_to.month not in (6, 12):
                _logger.info(
                    f"No es mes de pago de prima ni liquidación para {payslip.name}")
                return 0.0
        except Exception as e:
            _logger.error(
                f"Error determinando fechas para prima en {payslip.name}: {e}", exc_info=True)
            return 0.0

        # --- 2. Calcular Días Base 360 en el Periodo de Cálculo ---
        days_in_period_360 = 0
        try:
            days_in_period_360 = self._calculate_days_360_helper(
                period_start_date, period_end_date_calculation)
            days_in_period_360 = max(0, days_in_period_360)
        except Exception as e:
            _logger.error(
                f"Error calculando días base 360 para prima en {payslip.name}: {e}", exc_info=True)
            return 0.0

        # --- 3. Descontar Ausencias No Remuneradas en el Periodo de Cálculo (Simplificado) ---
        # !!! PERSONALIZA unpaid_leave_codes SI ES DIFERENTE PARA PRIMA !!!
        unpaid_leave_codes = ['LNR', 'SUS']
        unpaid_leave_days_in_this_payslip = 0.0
        for code_unpaid in unpaid_leave_codes:  # Renombrada variable de bucle
            wd_line = worked_days_dict.get(code_unpaid)
            if wd_line:
                try:
                    unpaid_leave_days_in_this_payslip += float(
                        wd_line.number_of_days or 0.0)
                except (ValueError, TypeError):
                    _logger.warning(
                        f"Valor no numérico en worked_days '{code_unpaid}' para prima en {payslip.name}")

        days_to_liquidate = max(
            0, days_in_period_360 - unpaid_leave_days_in_this_payslip)  # Simplificado

        # --- 4. Calcular Salario Base Promedio (SIMPLIFICADO) ---
        base_salary = contract_wage
        # !!! ASEGÚRATE QUE 'AUXTRANS' ES EL CÓDIGO DE TU REGLA DE AUXILIO DE TRANSPORTE !!!
        aux_trans = category_map.get('AUXTRANS', 0.0)
        # Obtener smmlv para la condición de auxilio
        smmlv_prima, precision_prima = self._get_smmlv_and_precision()

        # Simplificación: Si el salario actual (contract_wage) es < 2 SMMLV, suma el auxilio de este mes.
        # La lógica correcta de promedio para salario variable es más compleja y requiere historial.
        # Ajuste con precisión
        if aux_trans > 0 and smmlv_prima > 0 and contract_wage < (2 * smmlv_prima - precision_prima):
            base_salary += aux_trans

        # --- 5. Aplicar Fórmula Prima ---
        if days_to_liquidate > 0 and base_salary > 0:
            result = (base_salary * days_to_liquidate) / 360.0
        else:
            result = 0.0
        _logger.info(
            f"Cálculo Prima (Simplificado) para {payslip.name}: Periodo={period_start_date.strftime('%Y-%m-%d')} a {period_end_date_calculation.strftime('%Y-%m-%d')}, Base={base_salary}, Días Liq={days_to_liquidate}, Resultado={result}")

        return payslip.currency_id.round(result) if payslip.currency_id and hasattr(payslip.currency_id, 'round') else round(result, 2)
    # --- FIN MÉTODO PRIMA ---

    # --- MÉTODO PARA CALCULAR CESANTÍAS ---
    def _calculate_cesantias(self):
        self.ensure_one()
        payslip = self
        contract = self.contract_id
        category_map = {(line.salary_rule_id.code if line.salary_rule_id and line.salary_rule_id.code else line.code)
                         : line.total for line in payslip.line_ids}
        worked_days_dict = {wd.code: wd for wd in payslip.worked_days_line_ids}
        result = 0.0
        contract_wage = 0.0
        if contract and hasattr(contract, 'wage'):
            try:
                contract_wage = float(contract.wage or 0.0)
            except (ValueError, TypeError):
                pass

        if not contract or contract_wage <= 0 or not payslip.date_to or not payslip.date_from:
            _logger.warning(
                f"No se puede calcular cesantías para {payslip.name}: Faltan datos.")
            return result

        period_end_date = payslip.date_to
        is_final_settlement = payslip.is_settlement
        period_start_date = date(1, 1, 1)
        period_end_date_calculation = date(1, 1, 1)

        try:
            if not contract.date_start:
                _logger.warning(
                    f"Contrato {contract.name} no tiene fecha de inicio para cálculo de cesantías en {payslip.name}.")
                return 0.0
            period_start_date = max(
                date(period_end_date.year, 1, 1), contract.date_start)
            period_end_date_calculation = period_end_date
            if not is_final_settlement:
                if payslip.date_to.month == 12:
                    period_end_date_calculation = date(
                        period_end_date.year, 12, 31)
                else:
                    _logger.info(
                        f"No es liquidación ni mes de pago anual de cesantías (Diciembre) para {payslip.name}")
                    return 0.0
            period_start_date = max(
                period_start_date, contract.date_start)  # Re-asegurar
            period_end_date_calculation = max(
                period_start_date, period_end_date_calculation)
        except Exception as e:
            _logger.error(
                f"Error determinando fechas para cesantías en {payslip.name}: {e}", exc_info=True)
            return 0.0

        days_in_period_360 = 0
        try:
            if period_start_date > period_end_date_calculation:
                days_in_period_360 = 0
            else:
                days_in_period_360 = self._calculate_days_360_helper(
                    period_start_date, period_end_date_calculation)
            days_in_period_360 = max(0, days_in_period_360)
        except Exception as e:
            _logger.error(
                f"Error calculando días base 360 cesantías en {payslip.name}: {e}", exc_info=True)
            return 0.0

        # !!! PERSONALIZA unpaid_leave_codes SI ES DIFERENTE PARA CESANTÍAS !!!
        unpaid_leave_codes = ['LNR', 'SUS']
        unpaid_leave_days_in_this_payslip = 0.0
        for code_unpaid_ces in unpaid_leave_codes:
            wd_line = worked_days_dict.get(code_unpaid_ces)
            if wd_line:
                try:
                    unpaid_leave_days_in_this_payslip += float(
                        wd_line.number_of_days or 0.0)
                except:
                    pass  # Simplificado
        days_to_liquidate = max(
            0, days_in_period_360 - unpaid_leave_days_in_this_payslip)

        base_salary = contract_wage
        # !!! ASEGÚRATE QUE 'AUXTRANS' ES EL CÓDIGO DE TU REGLA DE AUXILIO DE TRANSPORTE !!!
        aux_trans = category_map.get('AUXTRANS', 0.0)
        smmlv_ces, precision_ces = self._get_smmlv_and_precision()

        # Simplificación: Cesantías usualmente SÍ incluye auxilio de transporte si el empleado tiene derecho.
        # La condición de < 2 SMMLV para tener derecho al auxilio ya se evaluó en la regla AUXTRANS.
        if aux_trans > 0:  # Si se pagó auxilio, se incluye en la base de cesantías
            base_salary += aux_trans

        if days_to_liquidate > 0 and base_salary > 0:
            result = (base_salary * days_to_liquidate) / 360.0
        else:
            result = 0.0
        _logger.info(
            f"Cálculo Cesantías (Simplificado) para {payslip.name}: Periodo={period_start_date.strftime('%Y-%m-%d')} a {period_end_date_calculation.strftime('%Y-%m-%d')}, Base={base_salary}, Días Liq={days_to_liquidate}, Resultado={result}")
        return payslip.currency_id.round(result) if payslip.currency_id and hasattr(payslip.currency_id, 'round') else round(result, 2)
    # --- FIN MÉTODO CESANTÍAS ---

    # ---MÉTODO PARA CALCULAR INTERESES CESANTÍAS ---
    def _calculate_intereses_cesantias(self):
        self.ensure_one()
        payslip = self
        contract = self.contract_id
        category_map = {(line.salary_rule_id.code if line.salary_rule_id and line.salary_rule_id.code else line.code)
                         : line.total for line in payslip.line_ids}
        worked_days_dict = {wd.code: wd for wd in payslip.worked_days_line_ids}

        # !!! ================================================================================== !!!
        # !!! CRÍTICO: CAMBIA 'CESANTIA_CALC' por el código REAL de tu regla de Cesantías       !!!
        # !!! Este código DEBE COINCIDIR con el 'code' de la regla salarial que calcula Cesantías !!!
        # !!! ================================================================================== !!!
        codigo_regla_cesantias = 'CESANTIA_CALC'  # <-- ¡¡¡PERSONALIZA ESTO!!!
        calculated_cesantias = category_map.get(codigo_regla_cesantias, 0.0)

        result = 0.0
        days_to_liquidate = 0
        precision_rounding_currency = payslip.currency_id.rounding if payslip.currency_id and hasattr(
            payslip.currency_id, 'rounding') and payslip.currency_id.rounding > 0 else 0.01

        if not float_is_zero(calculated_cesantias, precision_rounding=precision_rounding_currency) and contract:
            period_end_date = payslip.date_to
            is_final_settlement = payslip.is_settlement
            try:
                if not contract.date_start:
                    _logger.warning(
                        f"Contrato {contract.name} no tiene fecha de inicio para cálculo de Intereses Cesantías en {payslip.name}.")
                    return 0.0

                period_start_date_ic = max(
                    date(period_end_date.year, 1, 1), contract.date_start)
                period_end_date_calculation_ic = period_end_date
                if not is_final_settlement:
                    if payslip.date_to.month == 12:  # Solo en Diciembre si no es liquidación
                        period_end_date_calculation_ic = date(
                            period_end_date.year, 12, 31)
                    # Si no es Diciembre y no es liquidación, no se calculan intereses (usualmente)
                    else:
                        _logger.info(
                            f"No es liquidación ni mes de cálculo anual de Intereses Cesantías para {payslip.name}")
                        return 0.0

                period_end_date_calculation_ic = max(
                    period_start_date_ic, period_end_date_calculation_ic)
                days_to_liquidate = self._calculate_days_for_cesantias_intereses(
                    period_start_date_ic, period_end_date_calculation_ic, worked_days_dict)
            except Exception as e:
                _logger.error(
                    f"Error calculando días para Intereses Cesantías en {payslip.name}: {e}", exc_info=True)
                days_to_liquidate = 0

            if days_to_liquidate > 0:
                interest_rate = 0.12
                result = (calculated_cesantias *
                          days_to_liquidate * interest_rate) / 360.0

        _logger.info(
            f"Cálculo Intereses Cesantías para {payslip.name}: Cesantías Base={calculated_cesantias:.2f}, Días Liq={days_to_liquidate}, Resultado={result:.2f}")
        return payslip.currency_id.round(result) if payslip.currency_id and hasattr(payslip.currency_id, 'round') else round(result, 2)
    # --- FIN MÉTODO INTERESES CESANTÍAS ---

    # =========================================================================
    # MÉTODO DE CÁLCULO IBC (NUEVA VERSIÓN INTEGRADA)
    # =========================================================================
    def _calculate_ibc(self, categories):  # 'categories' es crucial para este enfoque
        self.ensure_one()
        _logger.info(
            f"========= [IBC LOG] INICIANDO _calculate_ibc para {self.employee_id.name if self.employee_id else 'N/A EMP'}, Nómina: {self.number} =========")

        # Log inicial de líneas, puede ser útil para depurar otros aspectos o si categories.get() falla.
        _logger.info(
            f"[IBC LOG] Total de líneas en self.line_ids al inicio: {len(self.line_ids)}")
        if not self.line_ids and not categories:  # Si no hay líneas Y categories está vacío
            _logger.warning(
                f"[IBC LOG] ALERTA: self.line_ids Y categories ESTÁN VACÍOS al inicio de _calculate_ibc para la nómina {self.number}.")
        elif not self.line_ids:
            _logger.warning(
                f"[IBC LOG] ALERTA: self.line_ids ESTÁ VACÍO al inicio de _calculate_ibc para la nómina {self.number}.")

        final_ibc = 0.0  # Valor a retornar

        if not self.contract_id:
            _logger.warning(
                f"[IBC LOG] No hay contrato (contract_id) asociado al payslip {self.number}. Devolviendo IBC 0.")
            return 0.0

        # --- 1. Obtener valores base usando los MÉTODOS HELPER ---
        smmlv, precision_rounding = self._get_smmlv_and_precision()
        # Días para aplicar topes, considerando ausencias no remuneradas
        days_to_liquidate = self._get_days_to_liquidate()

        is_integral = False
        if hasattr(self.contract_id, 'integral_salary'):
            is_integral = self.contract_id.integral_salary
        else:  # Log si el campo crucial no existe
            _logger.error(
                f"[IBC LOG] CRÍTICO: Campo 'integral_salary' no encontrado en el contrato {self.contract_id.name} ({self.number}). Asumiendo NO integral.")

        is_apprentice = False
        if hasattr(self.contract_id, 'type_worker_id') and self.contract_id.type_worker_id and hasattr(self.contract_id.type_worker_id, 'code'):
            # Códigos DIAN para aprendiz
            if self.contract_id.type_worker_id.code in ['12', '19']:
                is_apprentice = True

        if is_apprentice:
            _logger.info(
                f"[IBC LOG] Empleado {self.employee_id.name if self.employee_id else 'N/A EMP'} (nómina {self.number}) es aprendiz. IBC es 0.")
            return 0.0

        _logger.info(
            f"[IBC LOG] Datos para IBC (nómina {self.number}): SMMLV={smmlv}, DaysToLiq={days_to_liquidate}, IsIntegral={is_integral}, Precision={precision_rounding}")

        # --- 2. Lógica de Cálculo según Tipo de Contrato ---
        is_integral = False
        if hasattr(self.contract_id, 'integral_salary'):
            is_integral = self.contract_id.integral_salary
        else:
            _logger.error(
                f"[IBC LOG] CRÍTICO: Campo 'integral_salary' no encontrado en el contrato {self.contract_id.name} ({self.number}). Asumiendo NO integral.")

        is_apprentice = False
        if hasattr(self.contract_id, 'type_worker_id') and self.contract_id.type_worker_id and hasattr(self.contract_id.type_worker_id, 'code'):
            if self.contract_id.type_worker_id.code in ['12', '19']:
                is_apprentice = True

        if is_apprentice:
            _logger.info(
                f"[IBC LOG] Empleado {self.employee_id.name if self.employee_id else 'N/A EMP'} (nómina {self.number}) es aprendiz. IBC es 0.")
            return 0.0

        _logger.info(
            f"[IBC LOG] Datos para IBC (nómina {self.number}): SMMLV={smmlv}, DaysToLiq={days_to_liquidate}, IsIntegral={is_integral}, Precision={precision_rounding}")

        if is_integral:
            _logger.info(
                f"[IBC LOG] Calculando IBC para SALARIO INTEGRAL (nómina {self.number}).")
            integral_salary_total = 0.0
            if hasattr(self.contract_id, 'wage'):
                try:
                    integral_salary_total = float(self.contract_id.wage or 0.0)
                except (ValueError, TypeError):
                    _logger.error(
                        f"[IBC LOG] Error al convertir contract.wage a float para integral: '{self.contract_id.wage}' en nómina {self.number}", exc_info=True)
            else:
                _logger.warning(
                    f"[IBC LOG] Campo 'wage' no encontrado en el contrato {self.contract_id.name} para empleado integral.")

            ibc_base_integral = integral_salary_total * 0.70
            temp_result = ibc_base_integral  # Usamos temp_result para la base antes de topes
            _logger.info(
                f"[IBC LOG] Base Integral (70% de {integral_salary_total}): {temp_result}")

            # --- Aplicación de Topes y Redondeo para INTEGRAL ---
            if smmlv > 0.0:
                min_ibc_integral = smmlv
                max_ibc_integral = 25 * smmlv
                _logger.info(
                    f"[IBC LOG] Topes para Integral (nómina {self.number}): Min={min_ibc_integral}, Max={max_ibc_integral}, Base antes de topes={temp_result}")

                if temp_result < min_ibc_integral:
                    _logger.info(
                        f"[IBC LOG] (Integral) Aplicando tope mínimo: {min_ibc_integral} (base era {temp_result})")
                    temp_result = min_ibc_integral
                if temp_result > max_ibc_integral:
                    _logger.info(
                        f"[IBC LOG] (Integral) Aplicando tope máximo: {max_ibc_integral} (base era {temp_result})")
                    temp_result = max_ibc_integral

            # Asignación a final_ibc y Redondeo PILA
            final_ibc = math.ceil(max(0.0, temp_result))
            _logger.info(
                f"[IBC LOG] IBC Integral Final (después de topes y ceil) para nómina {self.number}: {final_ibc}")
            # --- FIN Aplicación de Topes y Redondeo para INTEGRAL ---

        else:  # Empleado Regular (No integral, No aprendiz)
            _logger.info(
                f"[IBC LOG] Calculando IBC para EMPLEADO REGULAR (nómina {self.number}).")

            if days_to_liquidate <= precision_rounding:
                final_ibc = 0.0  # Asignar directamente a final_ibc
                _logger.info(
                    f"[IBC LOG] (Regular) Days to liquidate ({days_to_liquidate}) es <= precision_rounding ({precision_rounding}), IBC Regular es 0 para nómina {self.number}.")
                temp_result = final_ibc  # Para que la lógica de topes y ceil no se aplique o de 0
            else:
                # --- USO DE CATEGORIES.GET('IBC', 0.0) PARA LA SUMA BASE DE REGULARES ---
                # 'IBC' DEBE SER EL CÓDIGO DE LA CATEGORÍA que agrupa los conceptos base del IBC para regulares.
                # Esta categoría NO debería incluir AUXTRANS si se va a sumar condicionalmente.
                codigo_categoria_ibc_regular = 'IBC'  # CONFIRMADO POR TI

                ibc_sum_base_categorias = categories.get(
                    codigo_categoria_ibc_regular, 0.0)
                _logger.info(
                    f"[IBC LOG] (Regular) Suma obtenida de categories.get('{codigo_categoria_ibc_regular}', 0.0): {ibc_sum_base_categorias}")

                # Lógica para Auxilio de Transporte (condicional)
                # !!! PERSONALIZA el código de tu regla de Auxilio de Transporte si es diferente !!!
                codigo_auxilio_transporte = 'AUXTRANS'

                # Usamos la suma de la categoría (que NO debería incluir AUXTRANS)
                # como base para el tope del auxilio.
                salario_para_tope_auxtrans = ibc_sum_base_categorias

                linea_aux_trans_list = self.line_ids.filtered(
                    lambda l: (
                        l.salary_rule_id.code if l.salary_rule_id and l.salary_rule_id.code else l.code) == codigo_auxilio_transporte
                )

                temp_result = ibc_sum_base_categorias  # Empezamos con la suma de la categoría

                if linea_aux_trans_list and smmlv > 0.0:
                    # Asumimos una sola línea de AUXTRANS
                    linea_aux_trans = linea_aux_trans_list[0]
                    total_aux_trans = 0.0
                    try:
                        total_aux_trans = float(linea_aux_trans.total or 0.0)
                    except (ValueError, TypeError):
                        _logger.warning(
                            f"[IBC LOG] (Regular) Total de AUXTRANS ('{linea_aux_trans.total}') no es numérico en nómina {self.number}")

                    _logger.info(
                        f"[IBC LOG] (Regular) Verificando AUXTRANS (nómina {self.number}): Salario para tope (de cat. '{codigo_categoria_ibc_regular}')={salario_para_tope_auxtrans}, 2*SMMLV={2*smmlv}, Total AuxTrans en nómina={total_aux_trans}")
                    # Si salario base < 2 SMMLV
                    if salario_para_tope_auxtrans < (2 * smmlv - precision_rounding):
                        temp_result += total_aux_trans  # Sumar el auxilio
                        _logger.info(
                            f"[IBC LOG] (Regular) Sumando AUXTRANS ({total_aux_trans}) a nómina {self.number}. Nueva suma base: {temp_result}")
                    else:
                        _logger.info(
                            f"[IBC LOG] (Regular) NO se suma AUXTRANS porque salario_para_tope_auxtrans ({salario_para_tope_auxtrans}) >= 2*SMMLV.")
                elif linea_aux_trans_list and smmlv <= 0.0:
                    _logger.warning(
                        f"[IBC LOG] (Regular) AUXTRANS encontrado pero SMMLV es {smmlv}. No se puede evaluar condición de 2 SMMLV.")

        # --- 3. Aplicación de Topes y Redondeo (Común si es_integral o es_regular con días > 0) ---
        # Si es aprendiz o regular con days_to_liquidate <= 0, ya se retornó 0.0 o final_ibc es 0.0
        # Para integral, temp_result es ibc_base_integral (70%)
        # Para regular, temp_result es ibc_final_regular_bruto (suma_cat_ibc + auxilio si aplica)

        # Si final_ibc ya es 0.0 (por aprendiz, o regular con 0 días a liquidar), no aplicar topes.
        # La variable 'temp_result' contendrá la base calculada para integral o regular antes de topes.
        # Si es integral, ya se aplicaron topes arriba y se asignó a final_ibc.
        # Si es regular y days_to_liquidate > 0, temp_result es la base a la que se aplican topes.

        if not is_integral and days_to_liquidate > precision_rounding:  # Solo aplicar topes de regular aquí
            if smmlv > 0.0:
                min_ibc = (smmlv / 30.0) * days_to_liquidate
                max_ibc = 25 * smmlv
                _logger.info(
                    f"[IBC LOG] (Topes para nómina {self.number}): Min={min_ibc}, Max={max_ibc}, Base antes de topes={temp_result}")

                if temp_result < min_ibc:
                    _logger.info(
                        f"[IBC LOG] Aplicando tope mínimo: {min_ibc} (base era {temp_result})")
                    temp_result = min_ibc
                if temp_result > max_ibc:
                    _logger.info(
                        f"[IBC LOG] Aplicando tope máximo: {max_ibc} (base era {temp_result})")
                    temp_result = max_ibc

            final_ibc = math.ceil(max(0.0, temp_result))
            _logger.info(
                f"[IBC LOG] IBC Regular Final (después de topes y ceil) para nómina {self.number}: {final_ibc}")

        elif not is_integral and days_to_liquidate <= precision_rounding:
            # Ya se manejó arriba y final_ibc es 0.0, pero para asegurar
            final_ibc = 0.0

        # Para el caso integral, final_ibc ya fue calculado y redondeado.
        # Para el caso regular, final_ibc se calcula aquí arriba.
        # Si es aprendiz, ya se retornó 0.0.

        _logger.info(
            f"========= [IBC LOG] FINALIZANDO _calculate_ibc para {self.employee_id.name if self.employee_id else 'N/A EMP'}, nómina {self.number}, devolviendo: {final_ibc} =========")
        return final_ibc

    # --- MÉTODO PARA CALCULAR RETEFUENTE ---

    # rules_dict se puede pasar o calcular aquí
    def _calculate_retefuente(self, categories, rules_dict=None):
        self.ensure_one()
        _logger.info(
            f"========= [RETEFUENTE LOG] Iniciando cálculo para {self.employee_id.name if self.employee_id else 'N/A EMP'}, Nómina: {self.number} =========")

        retencion_final_pesos = 0.0

        if not self.contract_id:
            _logger.warning(
                f"[RETEFUENTE LOG] No hay contrato para nómina {self.number}. Retefuente es 0.")
            return 0.0

        smmlv, precision_rounding = self._get_smmlv_and_precision()
        uvt_value = 0.0
        company_obj = self.contract_id.company_id
        if company_obj and hasattr(company_obj, 'uvt_value'):
            try:
                uvt_val_comp = getattr(company_obj, 'uvt_value', None)
                if uvt_val_comp is not None:
                    uvt_value = float(uvt_val_comp or 0.0)
            except (ValueError, TypeError):
                pass

        if uvt_value <= 0:
            _logger.warning(
                f"[RETEFUENTE LOG] UVT no configurada o es cero (Valor: {uvt_value}). No se puede calcular Retefuente para {self.number}.")
            return 0.0

        _logger.info(
            f"[RETEFUENTE LOG] Nómina {self.number}: SMMLV={smmlv:.2f}, UVT={uvt_value:.2f}, Precision={precision_rounding:.4f}")

        # Si rules_dict no se pasa, lo construimos.
        # Esto es útil si la regla que llama a este método no puede acceder fácilmente al objeto 'rules'
        if not rules_dict:
            if not self.line_ids:  # Chequeo crucial
                _logger.warning(
                    f"[RETEFUENTE LOG] ALERTA: self.line_ids está VACÍO. No se pueden obtener totales de reglas para INCRNGO. Retefuente será 0.")
                return 0.0
            rules_dict = self._get_rules_dict()
            _logger.info(
                f"[RETEFUENTE LOG] rules_dict construido desde self.line_ids: {rules_dict}")

        # --- PASO 1: Obtener Ingresos Totales Gravables del Mes ---
        # 'TOTAL_RET' es el CÓDIGO DE LA CATEGORÍA donde tu regla 'TOTAL_RET' guarda su resultado.
        codigo_categoria_total_ingresos = 'TOTAL_RET'  # CONFIRMADO POR TI
        ingresos_gravables_mes = categories.get(
            codigo_categoria_total_ingresos, 0.0)
        _logger.info(
            f"[RETEFUENTE LOG] Total Ingresos Gravables Mes (de cat. '{codigo_categoria_total_ingresos}'): {ingresos_gravables_mes:.2f}")

        if abs(ingresos_gravables_mes) < precision_rounding:
            _logger.info(
                f"[RETEFUENTE LOG] Ingresos gravables son cero. Retefuente es 0.")
            return 0.0

        # --- PASO 2: Calcular Ingresos No Constitutivos de Renta Ni Ganancia Ocasional (INCRNGO) ---
        # Usando tus helpers para obtener los totales de las reglas de deducción del empleado
        cod_regla_salud_emp = 'SALUD_EMP'          # ¡PERSONALIZA SI ES DIFERENTE!
        cod_regla_pension_emp = 'PENSION_EMP'      # ¡PERSONALIZA SI ES DIFERENTE!
        cod_regla_fsp_sol = 'FSP_SOL'              # ¡PERSONALIZA SI ES DIFERENTE!
        cod_regla_fsp_sub = 'FSP_SUB'              # ¡PERSONALIZA SI ES DIFERENTE!

        aporte_salud_empleado = self._get_rule_total(
            cod_regla_salud_emp, rules_dict)
        aporte_pension_empleado = self._get_rule_total(
            cod_regla_pension_emp, rules_dict)
        aporte_fsp_empleado = self._get_rule_total(
            cod_regla_fsp_sol, rules_dict) + self._get_rule_total(cod_regla_fsp_sub, rules_dict)

        incrngo = aporte_salud_empleado + aporte_pension_empleado + aporte_fsp_empleado
        _logger.info(
            f"[RETEFUENTE LOG] INCRNGO (SaludEmp={aporte_salud_empleado:.2f}, PensionEmp={aporte_pension_empleado:.2f}, FSPEmp={aporte_fsp_empleado:.2f}): {incrngo:.2f}")

        # --- PASO 3: Calcular Deducciones Adicionales (Vivienda, Prepagada, Dependientes) ---
        # ¡DEBES IMPLEMENTAR LA OBTENCIÓN DE ESTOS VALORES Y SUS TOPES INDIVIDUALES EN UVT!
        # Estos podrían venir de inputs (self.input_line_ids) o de otros campos.
        deduccion_intereses_vivienda = 0.0
        deduccion_medicina_prepagada = 0.0
        deduccion_dependientes = 0.0
        # Ejemplo de cómo obtener de un input:
        # input_interes_vivienda = self.input_line_ids.filtered(lambda x: x.code == 'INPUT_INTERES_VIVIENDA')
        # if input_interes_vivienda: deduccion_intereses_vivienda = min(input_interes_vivienda[0].amount, 100 * uvt_value)

        deducciones_legales_adicionales = deduccion_intereses_vivienda + \
            deduccion_medicina_prepagada + deduccion_dependientes
        _logger.info(
            f"[RETEFUENTE LOG] Deducciones Legales Adicionales: {deducciones_legales_adicionales:.2f}")

        # --- PASO 4: Calcular Renta Exenta (25%) y aplicar Límite Global 40% ---
        ingreso_base_para_limites_y_exentas = max(
            0.0, ingresos_gravables_mes - incrngo)
        _logger.info(
            f"[RETEFUENTE LOG] Ingreso Base para Límites y Exentas (Ingresos - INCRNGO): {ingreso_base_para_limites_y_exentas:.2f}")

        base_para_25_exento = max(
            0.0, ingreso_base_para_limites_y_exentas - deducciones_legales_adicionales)
        renta_exenta_25_calculada = base_para_25_exento * 0.25

        tope_renta_exenta_uvt_mensual = (
            790.0 / 12.0) if relativedelta else 65.833333  # Aprox si dateutil no está
        tope_renta_exenta_pesos = tope_renta_exenta_uvt_mensual * uvt_value
        renta_exenta_25_final = min(
            renta_exenta_25_calculada, tope_renta_exenta_pesos)
        _logger.info(
            f"[RETEFUENTE LOG] Renta Exenta 25% (Calculada={renta_exenta_25_calculada:.2f}, Tope Indiv.={tope_renta_exenta_pesos:.2f}): {renta_exenta_25_final:.2f}")

        # Límite Global del 40% y 1340 UVT anuales (Art. 336 ET)
        limite_del_40_porciento = ingreso_base_para_limites_y_exentas * 0.40
        limite_1340_uvt_anual_pesos = 1340.0 * uvt_value
        limite_1340_uvt_mensual_pesos_proporcional = (
            limite_1340_uvt_anual_pesos / 12.0) if relativedelta else (1340.0/12.0 * uvt_value)

        limite_global_aplicable = min(
            limite_del_40_porciento, limite_1340_uvt_mensual_pesos_proporcional)
        _logger.info(
            f"[RETEFUENTE LOG] Límite Global Aplicable (min entre 40% de {ingreso_base_para_limites_y_exentas:.2f} = {limite_del_40_porciento:.2f}; y 1340 UVT anual/12 = {limite_1340_uvt_mensual_pesos_proporcional:.2f}): {limite_global_aplicable:.2f}")

        total_deducciones_y_exentas_para_limitar = deducciones_legales_adicionales + \
            renta_exenta_25_final

        deducciones_y_exentas_efectivas = min(
            total_deducciones_y_exentas_para_limitar, limite_global_aplicable)
        _logger.info(
            f"[RETEFUENTE LOG] Total Deducciones y Exentas Efectivas (Antes Límite Global={total_deducciones_y_exentas_para_limitar:.2f}, Después Límite Global={deducciones_y_exentas_efectivas:.2f})")

        # --- PASO 5: Calcular Base Gravable en Pesos y UVT ---
        base_gravable_pesos = ingreso_base_para_limites_y_exentas - \
            deducciones_y_exentas_efectivas
        base_gravable_pesos = max(0.0, base_gravable_pesos)
        _logger.info(
            f"[RETEFUENTE LOG] Base Gravable en Pesos Final: {base_gravable_pesos:.2f}")

        base_gravable_uvt = 0.0
        if uvt_value > 0:
            base_gravable_uvt = base_gravable_pesos / uvt_value
        _logger.info(
            f"[RETEFUENTE LOG] Base Gravable en UVT Final: {base_gravable_uvt:.2f}")

        # --- PASO 6: Aplicar Tabla de Retención (Art. 383 ET) ---
        retencion_uvt = 0.0
        # ¡¡¡VERIFICA ESTA TABLA CON LA NORMATIVA VIGENTE PARA EL AÑO DE LA NÓMINA!!!
        # Los valores de UVT base y sumandos fijos en UVT pueden cambiar.
        if base_gravable_uvt <= 95.0:
            retencion_uvt = 0.0
        elif base_gravable_uvt <= 150.0:
            retencion_uvt = (base_gravable_uvt - 95.0) * 0.19
        elif base_gravable_uvt <= 360.0:
            retencion_uvt = ((base_gravable_uvt - 150.0) * 0.28) + 10.0
        elif base_gravable_uvt <= 640.0:
            retencion_uvt = ((base_gravable_uvt - 360.0) * 0.33) + 69.0
        elif base_gravable_uvt <= 945.0:
            retencion_uvt = ((base_gravable_uvt - 640.0) * 0.35) + 162.0
        elif base_gravable_uvt <= 2300.0:
            retencion_uvt = ((base_gravable_uvt - 945.0) * 0.37) + 268.0
        else:
            retencion_uvt = ((base_gravable_uvt - 2300.0) * 0.39) + 770.0
        _logger.info(
            f"[RETEFUENTE LOG] Retención calculada en UVT (Art. 383): {retencion_uvt:.7f}")

        # --- PASO 7: Convertir Retención a Pesos y Redondear ---
        retencion_pesos_sin_redondear = retencion_uvt * uvt_value

        if retencion_pesos_sin_redondear > 0:
            # Redondeo DIAN: Usualmente al múltiplo de 1000 más cercano, generalmente hacia abajo (truncar).
            retencion_final_pesos = math.floor(
                retencion_pesos_sin_redondear / 1000.0) * 1000.0
        else:
            retencion_final_pesos = 0.0

        _logger.info(
            f"[RETEFUENTE LOG] Retención Final en Pesos (después de redondeo DIAN): {retencion_pesos_sin_redondear:.2f} -> {retencion_final_pesos:.2f}")
        _logger.info(
            f"========= [RETEFUENTE LOG] FINALIZANDO cálculo, devolviendo: {retencion_final_pesos} =========")
        return retencion_final_pesos

    # --- Tus métodos de validación DIAN y acciones ---
    def validate_dian_generic(self):
        # Tu código existente
        for rec in self:
            if not (rec.company_id and rec.company_id.edi_payroll_enable):
                continue
            if rec.company_id.edi_payroll_consolidated_enable:
                continue
            if rec.edi_is_valid:
                continue
            if rec.state not in ('done', 'paid'):
                raise UserError(
                    _("Solo se pueden validar nóminas en estado 'Hecho' o 'Pagado'."))
            _logger.info(
                "Iniciando validación DIAN para nómina individual: %s", rec.name)
            try:
                xml_data = rec._prepare_xml_data(consolidated_data=None)
            except Exception as e:
                raise UserError(
                    _("Error al preparar datos para Nómina Electrónica: %s") % e)
            rec._validate_dian_generic(xml_data=xml_data)

    def validate_dian(self):
        self.validate_dian_generic()

    @api.returns('mail.message', lambda self: False)
    def action_payslip_done(self):
        res = super(HrPayslip, self).action_payslip_done()
        return res

    @api.returns('self', lambda value: value.id)
    def refund_sheet(self):
        self.ensure_one()
        res = super(HrPayslip, self).refund_sheet()
        new_payslip_id_to_write = None
        if isinstance(res, dict) and res.get('res_id'):
            new_payslip_id_val = res.get('res_id')
            if isinstance(new_payslip_id_val, list):
                if new_payslip_id_val:
                    new_payslip_id_to_write = new_payslip_id_val[0]
            else:
                new_payslip_id_to_write = new_payslip_id_val
            if new_payslip_id_to_write:
                new_payslip_record = self.browse(new_payslip_id_to_write)
                if new_payslip_record.credit_note:
                    new_payslip_record.write({'origin_payslip_id': self.id})
        elif isinstance(res, models.BaseModel) and res._name == 'hr.payslip':
            new_payslips_found = res.filtered(lambda p: p.credit_note)
            if new_payslips_found:
                new_payslips_found.write({'origin_payslip_id': self.id})
        return res

    def action_generate_draft_account_move(self):
        self.ensure_one()
        _logger.info(
            "Iniciando action_generate_draft_account_move para recibo %s (ID: %s)", self.name, self.id)

        # Verificar si ya existe un asiento contable para este recibo
        if self.move_id:
            _logger.info(
                "El recibo %s ya tiene un asiento contable asociado (ID: %s). Redirigiendo al existente.", self.name, self.move_id.id)
            # Si ya existe, simplemente redirigir al usuario a ese asiento
            return {
                'name': _('Journal Entry'),
                'view_mode': 'form',
                'res_model': 'account.move',
                'res_id': self.move_id.id,
                'type': 'ir.actions.act_window',
                'target': 'current',
            }

        # Si no existe, intentar crearlo
        try:
            # Llama al método estándar de Odoo hr_payroll para crear el asiento contable.
            self._action_create_account_move()
            _logger.info(
                "Asiento contable borrador creado para recibo %s (Move ID: %s)", self.name, self.move_id.id)

            # Después de la creación, si el move_id se ha establecido, marca la bandera de nómina
            if self.move_id:
                self.move_id.is_payroll_document_proxy = True
                _logger.info(
                    "Marcado asiento contable %s como proxy de documento de nómina.", self.move_id.name)

                # Retorna una acción para abrir el asiento contable recién creado
                return {
                    'name': _('Journal Entry'),
                    'view_mode': 'form',
                    'res_model': 'account.move',
                    'res_id': self.move_id.id,
                    'type': 'ir.actions.act_window',
                    'target': 'current',
                }
            else:
                _logger.warning(
                    "No se creó ningún asiento contable por _action_create_account_move para el recibo %s. Posiblemente un error interno o configuración.", self.name)
                raise UserError(
                    _("No se pudo crear el asiento contable. Por favor, revise la configuración de nómina y los logs del servidor."))

        except Exception as e:
            _logger.error(
                "Error al crear el asiento contable borrador para el recibo %s: %s", self.name, e, exc_info=True)
            raise UserError(
                _("Fallo al crear el asiento contable borrador: %s") % e)

    def action_print_payslip_account_move(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(
                _("Este recibo de nómina no tiene un asiento contable asociado."))

        # Nombre técnico completo de tu acción de reporte
        report_action_name = 'l10n_co_nomina.action_report_hr_payslip_account_move'

        return self.env.ref(report_action_name).report_action(self.move_id)

    def dian_pdf_view(self):
        """
        Este método es llamado por el botón 'DIAN Pdf View'.
        Su función es encontrar el reporte PDF correcto que creamos para la nómina
        y ejecutarlo, evitando el error 'is_sale_document'.
        """
        self.ensure_one()

        # 1. Busca el nombre de la acción de reporte que creamos en el archivo XML.
        #    El formato es: nombre_del_modulo.id_del_record
        report_action_ref = 'l10n_co_nomina.action_report_hr_payslip_l10n_co_nomina'

        # 2. Obtiene la acción de reporte desde la base de datos.
        report_action = self.env.ref(report_action_ref)

        if not report_action or not report_action.exists():
            raise UserError(
                _("No se encontró la acción de reporte: %s", report_action_ref))

        # 3. Llama al reporte, pasándole el recibo de nómina actual (self).
        #    Esto generará el PDF usando nuestra plantilla segura.
        return report_action.report_action(self)

    # =========================================================================
    # NUEVO MÉTODO: PREPARAR JSON PARA LA API DE NÓMINA ELECTRÓNICA
    # =========================================================================

    def _prepare_payroll_json_data(self):
        self.ensure_one()

        def _clean_dict(d):
            return {k: v for k, v in d.items() if v is not None and v != ''}

        def _safe_int(val):
            try:
                return int(val)
            except (ValueError, TypeError):
                return None

        def _pct(v, default):
            """Devuelve porcentaje en 0-100. Si viene como factor (<=1), lo convierte."""
            if v is None:
                return default
            try:
                val = float(v)
            except Exception:
                return default
            return val * 100.0 if 0 < val <= 1 else val
        
        def _get_municipality_id_from_employee(emp):
            city = getattr(getattr(emp, 'address_id', False), 'city_id', False)
            if not city:
                return None
            # Prioriza el código APIDIAN si existe
            apidian_code = _safe_int(getattr(city, 'apidian_code', None))
            if apidian_code:
                return apidian_code
            # Como alternativa, usa el código DANE
            dane_code = _safe_int(getattr(city, 'l10n_co_edi_code', None))
            if dane_code:
                return dane_code
            return None

        payslip = self
        company = payslip.company_id
        employee = payslip.employee_id
        contract = payslip.contract_id

        if not all([company, employee, contract]):
            raise UserError(
                _("Faltan datos esenciales (Compañía, Empleado o Contrato) en el recibo de nómina."))

        _logger.info(
            f"Preparando JSON para Nómina Individual: {payslip.number}")

        # --- 1. Agregar y Estructurar Datos de Líneas ---
        # Usamos un defaultdict para simplificar la agregación
        aggregated_values = defaultdict(
            lambda: {'total': 0.0, 'quantity': 0.0, 'details': []})

        for line in payslip.line_ids:
            rule = line.salary_rule_id
            if not rule:
                continue

            concept_type = getattr(rule, 'type_concept', None)
            if concept_type == 'earn':
                category = getattr(rule, 'earn_category', None)
                if category:
                    # Los totales de devengos son positivos
                    aggregated_values[category]['total'] += line.total
                    aggregated_values[category]['quantity'] += line.quantity
            elif concept_type == 'deduction':
                category = getattr(rule, 'deduction_category', None)
                if category:
                    # Los totales de deducción en Odoo son negativos, los necesitamos positivos para la API
                    aggregated_values[category]['total'] += abs(line.total)
                    aggregated_values[category]['quantity'] += line.quantity

        # --- 2. Construir los diccionarios para el JSON final ---

        # -- SECCIÓN DE DEVENGADOS (Accrued) --
        accrued_data = {}
        accrued_data['worked_days'] = int(payslip.worked_days_total)
        accrued_data['salary'] = str(aggregated_values['basic']['total'])

        # Transporte
        transportation_allowance = aggregated_values['transports_assistance']['total']
        viatic_s = aggregated_values['transports_viatic']['total']
        viatic_ns = aggregated_values['transports_non_salary_viatic']['total']
        if transportation_allowance > 0:
            accrued_data['transportation_allowance'] = str(transportation_allowance)
        if viatic_s > 0:
            accrued_data['viatic_salary'] = str(viatic_s)
        if viatic_ns > 0:
            accrued_data['viatic_non_salary'] = str(viatic_ns)

        # Horas Extras y Recargos (La API espera una lista)
        def _pct(v, default):
            """Devuelve porcentaje en 0-100. Si viene como factor (<=1), lo convierte."""
            if v is None:
                return default
            try:
                val = float(v)
            except Exception:
                return default
            # si alguien guardó 0.25 en vez de 25
            return val * 100.0 if 0 < val <= 1 else val

        hed_config = {
            'daily_overtime': _pct(company.daily_overtime, 25.0),
            'overtime_night_hours': _pct(company.overtime_night_hours, 75.0),
            'hours_night_surcharge': _pct(company.hours_night_surcharge, 35.0),
            'sunday_holiday_daily_overtime': _pct(company.sunday_holiday_daily_overtime, 100.0),
            'daily_surcharge_hours_sundays_holidays': _pct(company.daily_surcharge_hours_sundays_holidays, 75.0),
            'sunday_night_overtime_holidays': _pct(company.sunday_night_overtime_holidays, 150.0),
            'sunday_holidays_night_surcharge_hours': _pct(company.sunday_holidays_night_surcharge_hours, 110.0),
        }

        hed_list = []
        for cat, pct in hed_config.items():
            total_cat = aggregated_values[cat]['total']
            qty_cat = aggregated_values[cat]['quantity']
            if total_cat > 0:
                # APIDIAN acepta enteros; si tienes decimales, puedes redondear
                hed_list.append({
                    "quantity": qty_cat,
                    "percentage": float(pct),   # o deja pct si quieres float
                    "payment": str(total_cat),
                })

        if hed_list:
            accrued_data['HEDs'] = hed_list

        # Vacaciones
        vac_common = aggregated_values['vacation_common']
        vac_comp = aggregated_values['vacation_compensated']
        if vac_common['total'] > 0:
            accrued_data['common_vacation'] = [
                {"quantity": vac_common['quantity'], "payment": str(vac_common['total'])}]
        if vac_comp['total'] > 0:
            accrued_data['paid_vacation'] = [
                {"quantity": vac_comp['quantity'], "payment": str(vac_comp['total'])}]

        # Primas
        primas_s = aggregated_values['primas']
        primas_ns = aggregated_values['primas_non_salary']
        if primas_s['total'] > 0 or primas_ns['total'] > 0:
            accrued_data['service_bonus'] = [{"quantity": int(round(primas_s['quantity'])), "payment": str(
                primas_s['total']), "paymentNS": str(primas_ns['total'])}]

        # Cesantías
        layoffs = aggregated_values['layoffs']
        layoffs_interest = aggregated_values['layoffs_interest']
        if layoffs['total'] > 0 or layoffs_interest['total'] > 0:
            accrued_data['severance'] = [{
                "payment": str(layoffs['total']),
                "percentage": "12.00",  # Asumido, podrías hacerlo dinámico
                "interest_payment": str(layoffs_interest['total'])
            }]

        # Incapacidades
        incapacity_categories = {'incapacities_common': 1,
                                 'incapacities_professional': 2, 'incapacities_working': 3}
        incapacity_list = []
        for cat, code in incapacity_categories.items():
            if aggregated_values[cat]['total'] > 0:
                incapacity_list.append({
                    "type": code,
                    "quantity": aggregated_values[cat]['quantity'],
                    "payment": str(aggregated_values[cat]['total'])
                })
        if incapacity_list:
            accrued_data['work_disabilities'] = incapacity_list
        
        # Licencias (Agrupadas)
        licensing_maternity = aggregated_values['licensings_maternity_or_paternity_leaves']['total']
        licensing_paid = aggregated_values['licensings_permit_or_paid_licenses']['total']
        # La licencia no remunerada es informativa, no suma al devengado
        if licensing_maternity > 0:
            accrued_data['maternity_leave'] = str(licensing_maternity)
        if licensing_paid > 0:
            accrued_data['paid_leave'] = str(licensing_paid)

        # Otros conceptos... (Bonos, auxilios, etc.)
        # Se agrupan aquí los que son listas de diccionarios en la API
        bonuses_s = aggregated_values['bonuses']['total']
        bonuses_ns = aggregated_values['bonuses_non_salary']['total']
        if bonuses_s > 0 or bonuses_ns > 0:
            accrued_data['bonuses'] = [{"salary_bonus": str(
                bonuses_s), "non_salary_bonus": str(bonuses_ns)}]

        assist_s = aggregated_values['assistances']['total']
        assist_ns = aggregated_values['assistances_non_salary']['total']
        if assist_s > 0 or assist_ns > 0:
            accrued_data['aid'] = [{"salary_assistance": str(
                assist_s), "non_salary_assistance": str(assist_ns)}]
        
        single_earn_mapping = {
            'endowment': 'endowment',
            'sustainment_support': 'sustainment_support',
            'telecommuting': 'telecommuting',
            'company_withdrawal_bonus': 'withdrawal_bonus',
            'compensation': 'compensation', # Nota: También existe en deducciones
            'refund': 'refund',
            'commissions': 'commissions',
            'third_party_payments': 'third_party_payment',
            'advances': 'advances'
        }
        for odoo_cat, api_key in single_earn_mapping.items():
            if aggregated_values[odoo_cat]['total'] > 0:
                accrued_data[api_key] = str(aggregated_values[odoo_cat]['total'])

        # Total devengado final
        accrued_data['accrued_total'] = str(payslip.accrued_total_amount)

        # -- SECCIÓN DE DEDUCCIONES (Deductions) --
        deductions_data = {}
        deductions_data['eps_deduction'] = str(
            aggregated_values['health']['total'])
        deductions_data['pension_deduction'] = str(
            aggregated_values['pension_fund']['total'])
    
        tipo_cotizante = int(contract.type_worker_id.code) if contract.type_worker_id and contract.type_worker_id.code.isdigit() else 1
        deductions_data['eps_type_law_deductions_id'] = tipo_cotizante
        deductions_data['pension_type_law_deductions_id'] = tipo_cotizante

        # FSP
        fsp_sol = aggregated_values['pension_security_fund']['total']
        fsp_sub = aggregated_values['pension_security_fund_subsistence']['total']
        if fsp_sol > 0 or fsp_sub > 0:
            deductions_data['fondosp_deduction_SP'] = str(fsp_sol)
            deductions_data['fondosp_deduction_sub'] = str(fsp_sub)

        # Sindicatos
        trade_unions = aggregated_values['trade_unions']['total']
        if trade_unions > 0:
            deductions_data['labor_union'] = [{"deduction": str(trade_unions)}]

        # Libranzas y Sanciones (Ejemplo de cómo manejar detalles si los tuvieras en deduction_ids)
        libranzas_bucket = aggregated_values.get(('ded_detail', 'libranzas'), {'details': []})
        libranzas_details = libranzas_bucket.get('details', [])
        if libranzas_details:
            deductions_data['orders'] = [
                {"description": d.get('description', ''), "deduction": str(d.get('payment', 0))}
                for d in libranzas_details
            ]

        sanctions_public = aggregated_values['sanctions_public']['total']
        sanctions_private = aggregated_values['sanctions_private']['total']
        if sanctions_public > 0 or sanctions_private > 0:
            deductions_data['sanction'] = [{"public_sanction": str(sanctions_public), "private_sanction": str(sanctions_private)}]

        # Otros campos de deducción (mapeo directo)
        single_ded_mapping = {
            'voluntary_pension': 'voluntary_pension', 'withholding_source': 'withholding_at_source',
            'afc': 'afc', 'cooperative': 'cooperative', 'tax_lien': 'tax_liens',
            'complementary_plans': 'supplementary_plan', 'education': 'education',
            'refund': 'refund', 'debt': 'debt',
            'third_party_payments': 'third_party_payment',
            'advances': 'advances',
            'other_deductions': 'other_deduction'
        }
        for odoo_cat, api_key in single_ded_mapping.items():
            if aggregated_values[odoo_cat]['total'] > 0:
                deductions_data[api_key] = str(
                    aggregated_values[odoo_cat]['total'])

        # Total deducciones final
        deductions_data['deductions_total'] = str(
            payslip.deductions_total_amount)
        
        # --- 2.5 Construir el diccionario del trabajador (worker_data) ---

        # Mapeo para Tipo de Documento
        identification_type_obj = employee.private_type_document_identification_id
        doc_code_str = identification_type_obj.l10n_co_document_code if identification_type_obj else 'national_citizen_id'
        document_code_map = {'national_citizen_id': 3, 'rut': 6, 'passport': 7, 'foreign_id_card': 5}
        payroll_doc_type_code = document_code_map.get(doc_code_str, 3)

        # Mapeo para Nivel de Riesgo ARL
        arl_code_str = contract.arl_risk_level.code if contract.arl_risk_level else ''
        arl_level_map = {'clase_i': 1, 'clase_ii': 2, 'clase_iii': 3, 'clase_iv': 4, 'clase_v': 5}
        arl_level_code = arl_level_map.get(arl_code_str, 1)
        
        doc_apidian_id = payroll_doc_type_code 

        worker_data = {
            "type_worker_id": int(contract.type_worker_id.code) if contract.type_worker_id else 1,
            "sub_type_worker_id": int(contract.subtype_worker_id.code) if contract.subtype_worker_id else 1,
            "payroll_type_document_identification_id": doc_apidian_id,
            "type_document_identification_id": doc_apidian_id,  # <— antes usaba variable inexistente
            "municipality_id": _get_municipality_id_from_employee(employee),
            "type_contract_id": int(contract.type_contract_id.code) if contract.type_contract_id else 1,
            "high_risk_pension": bool(contract.high_risk_pension),
            "integral_salary": bool(contract.integral_salary),
            "salary": str(contract.wage),
            "identification_number": employee.identification_id,
            "surname": employee.private_surname or '',
            "second_surname": employee.private_second_surname or '',
            "first_name": employee.private_first_name or '',
            "middle_name": employee.private_other_names or '',
            "address": employee.address_id.street if employee.address_id else 'N/A',
            "arl_level": arl_level_code,
            "payment_method_id": int(payslip.payment_method_id.code) if payslip.payment_method_id else 42,
        }

        # --- Validaciones previas para evitar 422 en APIDIAN ---
        if not worker_data.get("payroll_type_document_identification_id"):
            raise UserError(_("Falta el ID de tipo de documento (APIDIAN) del trabajador."))

        if not worker_data.get("municipality_id"):
            raise UserError(_("Falta el municipality_id (APIDIAN/DANE) del trabajador. "
                            "Asigne en la ciudad el código APIDIAN (apidian_code) o al menos el DANE (l10n_co_edi_code)."))
        
        # --- 3. Ensamblar el JSON Completo ---

        resolution = payslip.company_id.l10n_co_nomina_default_resolution_id
        if not resolution:
            raise UserError(_("No hay resolución de nómina configurada en la compañía."))

        resolution_number_str = resolution.resolution_number or ''
        prefix = resolution.prefix or ''

        consecutive = 1 

        # Validar rango si la resolución lo tiene (ajusta los nombres de campos a tu modelo)
        range_from = getattr(resolution, 'from_number', None)
        range_to = getattr(resolution, 'to_number', None)
        if (range_from is not None) and (range_to is not None):
            if not (range_from <= consecutive <= range_to):
                raise UserError(_("El consecutivo %s está fuera del rango de la resolución (%s - %s).") % (consecutive, range_from, range_to))

        # Mapeo de Periodo de Pago
        schedule_pay_mapping = {'monthly': 4, 'semi-monthly': 3, 'bi-weekly': 3, 'weekly': 2}
        payroll_period_code = schedule_pay_mapping.get(contract.schedule_pay, 4)

        # --- Normaliza account_type (Odoo -> APIDIAN) ---
        account_type_map = {
            'saving': 'AHORROS',
            'savings': 'AHORROS',
            'ahorros': 'AHORROS',
            'ca': 'AHORROS',
            'current': 'CORRIENTE',
            'checking': 'CORRIENTE',
            'corriente': 'CORRIENTE',
            'cc': 'CORRIENTE',
        }
        raw_acc_type = getattr(employee.bank_account_id, 'acc_type', None) if employee.bank_account_id else None
        acc_type_txt = account_type_map.get(str(raw_acc_type).lower()) if raw_acc_type else None

        payroll_json = {
            "resolution_number": resolution_number_str,
            "prefix": prefix,
            "consecutive": consecutive,
            "type_document_id": 10 if payslip.credit_note else 9,
            "payroll_period_id": payroll_period_code,
            "worker_code": employee.barcode or employee.identification_id,
            "period": {
                "admision_date": contract.date_start.strftime('%Y-%m-%d') if contract.date_start else None,
                "settlement_start_date": payslip.date_from.strftime('%Y-%m-%d'),
                "settlement_end_date": payslip.date_to.strftime('%Y-%m-%d'),
                "worked_time": str(payslip.worked_days_total),
                "issue_date": fields.Date.context_today(payslip).strftime('%Y-%m-%d'),
            },
            "worker": worker_data,

            "payment": {
                "payment_method_id": int(payslip.payment_method_id.code) if payslip.payment_method_id else 42,
                "bank_name": employee.bank_account_id.bank_id.name if employee.bank_account_id else None,
                "account_type": acc_type_txt,  # texto normalizado para APIDIAN
                "account_number": employee.bank_account_id.acc_number if employee.bank_account_id else None,
            },
            "payment_dates": [{"payment_date": payslip.payment_date.strftime('%Y-%m-%d')}] if payslip.payment_date else [],
            "accrued": accrued_data,
            "deductions": deductions_data,
            "notes": payslip.note or "Generado desde Odoo",
            "sendmail": True,
            "sendmailtome": False,
        }

        # Limpiar claves con valores nulos o vacíos para un JSON más limpio (sin eliminar 0/False)
        for section in ['worker', 'payment', 'accrued', 'deductions', 'period']:
            if section in payroll_json:
                payroll_json[section] = _clean_dict(payroll_json[section])
        if not payroll_json.get('payment_dates'):
            payroll_json.pop('payment_dates', None)

        _logger.info("JSON de nómina individual preparado para envío: %s", payroll_json)
        return payroll_json

    # =========================================================================
    # MODIFICAR MÉTODO validate_dian_generic PARA USAR LA NUEVA API
    # =========================================================================
    # xml_data ya no se usará directamente
    # En l10n_co_nomina/models/hr_payslip.py

    def _validate_dian_generic(self):
        self.ensure_one()
        payslip = self

        # --- Validaciones Previas ---
        if not (payslip.company_id and payslip.company_id.edi_payroll_enable):
            _logger.info(
                "Nómina Electrónica no habilitada para la compañía %s.", payslip.company_id.name)
            return
        if payslip.edi_is_valid:
            _logger.info(
                "La nómina %s ya fue validada por DIAN.", payslip.name)
            return
        if payslip.state not in ('done', 'paid'):
            raise UserError(
                _("Solo se pueden validar nóminas en estado 'Hecho' o 'Pagado'."))

        _logger.info(
            "Iniciando envío de Nómina Electrónica %s a APIDIAN.", payslip.name)

        try:
            # 1. Determinar si estamos en modo de prueba y obtener el TestSetId
            test_set_id = None
            if not payslip.company_id.edi_payroll_is_not_test:  # Si "Entorno en Producción" NO está marcado
                test_set_id = payslip.company_id.l10n_co_payroll_test_set_id
                if not test_set_id:
                    raise UserError(_(
                        "El entorno está configurado para pruebas (Habilitación), pero no se ha proporcionado un 'ID del Set de Pruebas DIAN' en los Ajustes de Nómina."))
            
            # 2. Preparar el JSON de la nómina (tu código original)
            # payroll_json_data = payslip._prepare_payroll_json_data() # Esta línea no es necesaria aquí, se llama dentro del conector

            # 3. Llamar al conector, pasándole el test_set_id (tu código original)
            identifier, api_response = self.env['l10n_co_nomina.payroll.api.connector'].send_payroll_document(
                payslip,
                test_set_id=test_set_id
            )

            # 4. Procesar la respuesta de la API (tu código original, sin cambios)
            if identifier:
                # Si el 'identifier' NO es un UUID de 36 caracteres, asumimos que es un CUNE (síncrono)
                if len(identifier) > 36:
                    payslip.write({
                        'l10n_co_edi_cune': identifier,
                        'edi_is_valid': True,
                        'edi_state': 'accepted',
                        'l10n_co_edi_qr_code_url': api_response.get('qr_code_url', ''),
                        'l10n_co_edi_xml_file': base64.b64encode(api_response.get('xml_file', b'')),
                        'l10n_co_edi_pdf_file': base64.b64encode(api_response.get('pdf_file', b'')),
                    })
                    payslip.message_post(body=_(
                        "Nómina Electrónica ACEPTADA por la DIAN (síncrono). CUNE: %s") % identifier)
                # Si SÍ es un UUID, es un zip_key (asíncrono)
                else:
                    payslip.write({
                        'edi_zip_key': identifier,
                        'edi_is_valid': False,
                        'edi_state': 'sent',
                    })
                    payslip.message_post(body=_(
                        "Nómina Electrónica ENVIADA a la DIAN (asíncrono). ZipKey: %s. Use el botón 'Consultar Estado' para obtener el resultado final.") % identifier)
            else:
                _logger.warning(
                    "El envío para la nómina %s no devolvió CUNE ni ZIP_KEY.", payslip.name)
                payslip.write({'edi_state': 'error'})

        except UserError as e:
            _logger.error(
                "Error de usuario al enviar Nómina Electrónica %s: %s", payslip.name, str(e))
            payslip.write({'edi_state': 'error'})
            raise e
        except Exception as e:
            _logger.error("Error inesperado al enviar Nómina Electrónica %s: %s",
                          payslip.name, e, exc_info=True)
            payslip.write({'edi_state': 'error'})
            raise UserError(
                _("Ocurrió un error inesperado al enviar la Nómina Electrónica: %s") % e)
    
    # =========================================================================
    # NUEVO MÉTODO: PREPARAR JSON PARA NOTAS DE AJUSTE/ELIMINACIÓN
    # =========================================================================

    # En l10n_co_nomina/models/hr_payslip.py

    def _prepare_payroll_adjust_json_data(self, predecessor_cune, type_note):
        self.ensure_one()
        payslip = self

        # 1. Obtener la base del JSON. Si es para Reemplazar, generamos el cuerpo completo.
        if type_note == 1:  # Reemplazar
            # ¡Reutilizamos el método de la nómina individual para obtener el cuerpo completo!
            adjust_json = payslip._prepare_payroll_json_data()
        else:  # Eliminar (type_note == 2)
            # Para eliminar, solo se necesitan los datos básicos.
            adjust_json = {
                "period": {
                    "admision_date": payslip.contract_id.date_start.strftime('%Y-%m-%d') if payslip.contract_id.date_start else None,
                    "settlement_start_date": payslip.date_from.strftime('%Y-%m-%d'),
                    "settlement_end_date": payslip.date_to.strftime('%Y-%m-%d'),
                    "worked_time": str(payslip.worked_days_total),
                    "issue_date": fields.Date.context_today(payslip).strftime('%Y-%m-%d'),
                },
                "prefix": payslip.number.lstrip('0123456789.-'),
                "consecutive": int(''.join(filter(str.isdigit, payslip.number))),
                "payroll_period_id": int(payslip.contract_id.payroll_period_id.code) if payslip.contract_id.payroll_period_id else 4,
                "notes": payslip.note or "Nota de Eliminación generada desde Odoo",
            }

        # 2. Añadir/Sobrescribir los campos específicos de la Nota de Ajuste
        adjust_json.update({
            "type_document_id": 10,  # Código para Nota de Ajuste
            "type_note": type_note,
            "predecessor": {
                "predecessor_number": payslip.origin_payslip_id.number if payslip.origin_payslip_id else '',
                "predecessor_cune": predecessor_cune,
                "predecessor_issue_date": payslip.origin_payslip_id.date.strftime('%Y-%m-%d') if payslip.origin_payslip_id and payslip.origin_payslip_id.date else '',
            },
            # Asegurarnos de que el prefijo sea el de la nota de ajuste
            "prefix": self.env.company.l10n_co_payroll_note_prefix or "NA",
        })

        _logger.info(
            "JSON de nota de ajuste de nómina preparado: %s", adjust_json)
        return adjust_json
    # =========================================================================
    # MÉTODOS PARA DESCARGAR ARCHIVOS EDI (XML y PDF)
    # =========================================================================

    def l10n_co_edi_xml_file_download(self):
        """
        Método para descargar el archivo XML de la nómina individual.
        """
        self.ensure_one()
        if not self.l10n_co_edi_xml_file:
            raise UserError(
                _("No hay archivo XML disponible para descargar para esta nómina."))

        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/l10n_co_edi_xml_file/%s' % (self._name, self.id, 'nomina_electronica.xml'),
            'target': 'self',
        }

    def l10n_co_edi_pdf_file_download(self):
        """
        Método para descargar el archivo PDF de la nómina individual.
        """
        self.ensure_one()
        if not self.l10n_co_edi_pdf_file:
            raise UserError(
                _("No hay archivo PDF disponible para descargar para esta nómina."))

        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s/%s/l10n_co_edi_pdf_file/%s' % (self._name, self.id, 'nomina_electronica.pdf'),
            'target': 'self',
        }

    def validate_dian(self):
        """
        Acción del botón "Validar DIAN" para la nómina individual.
        Llama al método genérico de validación.
        """
        # El método _validate_dian_generic ya maneja el bucle, pero es buena práctica
        # iterar aquí por si se seleccionan varias nóminas desde la vista de lista.
        for payslip in self:
            payslip._validate_dian_generic()
        return True

    def get_dian_status(self):
        """
        Acción del botón "Consultar Estado DIAN" para la nómina individual.
        Consulta el estado de una nómina enviada de forma asíncrona.
        """
        for payslip in self:
            if not payslip.edi_zip_key:
                raise UserError(
                    _("Este recibo de nómina no tiene un ZipKey para consultar."))

            _logger.info(
                "Consultando estado en APIDIAN para ZipKey: %s", payslip.edi_zip_key)

            try:
                # Llamar al conector para consultar el estado
                api_response = self.env['l10n_co_nomina.payroll.api.connector'].get_payroll_status(
                    payslip.edi_zip_key)

                # Procesar la respuesta del status
                if api_response and api_response.get('success'):
                    if api_response.get('is_valid'):
                        payslip.write({
                            'l10n_co_edi_cune': api_response.get('cune'),
                            'edi_is_valid': True,
                            'edi_state': 'accepted',
                            'edi_status_message': api_response.get('message', 'Aceptado'),
                        })
                        payslip.message_post(body=_(
                            "Consulta exitosa: La DIAN ACEPTÓ el documento. CUNE: %s") % api_response.get('cune'))
                    else:
                        payslip.write({
                            'edi_is_valid': False,
                            'edi_state': 'rejected',
                            'edi_status_message': api_response.get('message', 'Rechazado'),
                            'edi_errors_messages': json.dumps(api_response.get('errors'), indent=2),
                        })
                        payslip.message_post(body=_(
                            "Consulta exitosa: La DIAN RECHAZÓ el documento. Razón: %s") % api_response.get('message'))
                else:
                    payslip.message_post(
                        body=_("La consulta de estado falló: %s") % api_response.get('message'))

            except Exception as e:
                _logger.error("Fallo al consultar estado para ZipKey %s: %s",
                              payslip.edi_zip_key, e, exc_info=True)
                payslip.message_post(
                    body=_("Error consultando estado: %s") % e)
        return True

    # Puedes crear un nuevo botón o acción para enviar notas de ajuste
    # Por ejemplo, en hr_payslip_edi_views.xml
    # <button name="action_send_payroll_adjust_note" string="Enviar Nota de Ajuste DIAN" type="object" ... />
    # Y el método Python:
    # def action_send_payroll_adjust_note(self):
    #     self.ensure_one()
    #     # Aquí necesitas obtener el CUNE del recibo original
    #     predecessor_cune = self.origin_payslip_id.l10n_co_edi_cune if self.origin_payslip_id else ''
    #     if not predecessor_cune:
    #         raise UserError(_("No se encontró el CUNE del recibo original para la nota de ajuste."))
    #
    #     # Determinar si es una nota de reemplazo (1) o eliminación (2)
    #     # Esto dependerá de tu lógica de negocio para las notas de ajuste.
    #     type_note = 1 # Ejemplo: 1 para reemplazar
    #
    #     self.env['l10n_co_nomina.payroll.api.connector'].send_payroll_adjust_note_document(self, predecessor_cune, type_note)
    #     self.write({'edi_state': 'adjust_sent'}) # O el estado que corresponda
