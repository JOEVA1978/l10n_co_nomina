# -*- coding: utf-8 -*-
# This module defines HR recurring payroll items for Odoo.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class HrEmployeeRecurringItem(models.Model):
    _name = 'hr.employee.recurring.item'
    _description = 'Ítem Recurrente de Nómina por Empleado'
    _order = 'employee_id, contract_id, sequence, date_start desc'

    sequence = fields.Integer(default=10)
    name = fields.Char(string='Descripción',
                       compute='_compute_name', store=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Empleado', required=True, ondelete='cascade')
    contract_id = fields.Many2one(
        'hr.contract',
        string='Contrato',
        required=True,
        ondelete='cascade',
        domain="[('employee_id', '=', employee_id), ('state', 'in', ['open', 'close'])]"
    )
    recurring_item_type_id = fields.Many2one(
        'hr.recurring.item.type', string='Tipo de Ítem', required=True, ondelete='restrict'
    )
    item_type = fields.Selection(
        related='recurring_item_type_id.item_type', store=True, string="Tipo", tracking=True)
    salary_rule_code = fields.Char(
        related='recurring_item_type_id.salary_rule_id.code', store=True, string="Código Regla")
    partner_id = fields.Many2one(
        related='recurring_item_type_id.partner_id', store=True, string="Tercero")

    amount_type = fields.Selection([
        ('fix', 'Valor Fijo'),
        ('percentage', 'Porcentaje')
    ], string='Tipo de Cálculo', required=True, default='fix')
    amount = fields.Monetary(string='Valor/Base %', tracking=True,
                             currency_field='currency_id', default=0.0)
    currency_id = fields.Many2one(
        'res.currency', related='contract_id.company_id.currency_id', store=True)
    percentage = fields.Float(string='Porcentaje (%)', tracking=True,
                              digits='Payroll Rate', default=0.0)
    percentage_base_rule_code = fields.Char(
        string='Regla Salarial', tracking=True)

    date_start = fields.Date(string='Fecha Inicio', tracking=True,
                             required=True, default=fields.Date.context_today)
    date_end = fields.Date(string='Fecha Fin', tracking=True)

    use_installments = fields.Boolean(
        string='Controlar por Cuotas/Saldo', tracking=True)
    number_of_installments = fields.Integer(tracking=True,
                                            string='N° Total Cuotas', default=0)
    initial_installment = fields.Integer(
        string='No. Cuota a Iniciar', default=1, tracking=True)
    current_installment = fields.Integer(
        string='Cuota Actual Procesada', readonly=True, default=0, copy=False)
    remaining_installments = fields.Integer(
        string='Cuotas Restantes', compute='_compute_remaining', store=True, readonly=True)
    total_amount = fields.Monetary(
        string='Monto Total', currency_field='currency_id', default=0.0)
    paid_amount = fields.Monetary(
        string='Monto Pagado', currency_field='currency_id', readonly=True, default=0.0, copy=False)
    remaining_balance = fields.Monetary(
        string='Saldo Pendiente', compute='_compute_remaining', store=True, readonly=True, tracking=True)

    active = fields.Boolean(default=True, string='Activo')
    notes = fields.Text(string='Notas Internas')

    @api.depends('recurring_item_type_id', 'employee_id')
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.recurring_item_type_id.name} - {rec.employee_id.name}" if rec.recurring_item_type_id and rec.employee_id else _(
                'Nuevo Ítem')

    @api.onchange('recurring_item_type_id')
    def _onchange_recurring_item_type_id_set_defaults(self):
        """
        Establece valores por defecto basados en el tipo de ítem recurrente seleccionado.
        Establece percentage_base_rule_code con el código de la regla salarial del tipo.
        """
        if self.recurring_item_type_id and self.recurring_item_type_id.salary_rule_id:
            self.percentage_base_rule_code = self.recurring_item_type_id.salary_rule_id.code
        else:
            self.percentage_base_rule_code = False

    @api.depends('use_installments', 'number_of_installments', 'current_installment', 'total_amount', 'paid_amount')
    def _compute_remaining(self):
        _logger.info(
            "==> INICIANDO _compute_remaining para IDs de Items: %s", self.ids)
        for rec in self:
            _logger.info(
                "    Procesando _compute_remaining para Item ID: %s, Usa Cuotas: %s", rec.id, rec.use_installments)
            if rec.use_installments:
                _logger.info(
                    "      Item ID %s - Datos Base para Cálculo:", rec.id)
                _logger.info("        Nº Total Cuotas: %s",
                             rec.number_of_installments)
                _logger.info("        Cuota Actual Procesada: %s",
                             rec.current_installment)
                _logger.info("        Monto Total: %s", rec.total_amount)
                _logger.info("        Monto Pagado: %s", rec.paid_amount)

                val_rem_installments = max(
                    0, rec.number_of_installments - rec.current_installment)
                val_rem_balance = max(
                    0.0, (rec.total_amount or 0.0) - rec.paid_amount)

                _logger.info("      Item ID %s - VALORES CALCULADOS: Cuotas Restantes=%s, Saldo Pendiente=%s",
                             rec.id, val_rem_installments, val_rem_balance)

                rec.remaining_installments = val_rem_installments
                rec.remaining_balance = val_rem_balance
                _logger.info("      Item ID %s - VALORES ASIGNADOS A REC: rec.remaining_installments=%s, rec.remaining_balance=%s",
                             rec.id, rec.remaining_installments, rec.remaining_balance)
            else:
                rec.remaining_installments = 0
                rec.remaining_balance = 0.0
                _logger.info(
                    "    Item ID %s - 'Usa Cuotas' es False. Estableciendo cuotas/saldo restantes a 0.", rec.id)
        _logger.info(
            "==> FINALIZANDO _compute_remaining para IDs de Items: %s", self.ids)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_end and rec.date_start > rec.date_end:
                raise ValidationError(
                    _('La fecha de fin no puede ser anterior a la fecha de inicio.'))

    @api.constrains('amount_type', 'percentage')
    def _check_percentage_value(self):
        for rec in self:
            if rec.amount_type == 'percentage' and rec.percentage <= 0.0:
                raise ValidationError(
                    _('Debe ingresar un porcentaje mayor que cero para cálculo por porcentaje.'))

    @api.constrains('use_installments', 'number_of_installments', 'total_amount')
    def _check_installments(self):
        for rec in self:
            if rec.use_installments:
                if rec.number_of_installments <= 0:
                    raise ValidationError(
                        _('El número de cuotas debe ser mayor a cero.'))
                if rec.total_amount <= 0.0:
                    raise ValidationError(
                        _('El monto total debe ser mayor a cero para cuotas.'))

    def update_processed_installment(self, payslip_line_amount):
        self.ensure_one()
        if self.use_installments and self.active:
            self.current_installment += 1
            self.paid_amount += payslip_line_amount
            self._compute_remaining()
            if self.remaining_installments <= 0 or self.remaining_balance <= 0.0:
                self.active = False
