# -*- coding: utf-8 -*-
# This module defines HR recurring payroll item types for Odoo.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class HrRecurringItemType(models.Model):
    _name = 'hr.recurring.item.type'
    _description = 'Tipo de Ítem Recurrente de Nómina'
    _order = 'sequence, name'

    sequence = fields.Integer(default=10)
    name = fields.Char(string='Nombre', required=True, translate=True)
    code = fields.Char(string='Código', required=True,
                       help="Código único identificador.")
    item_type = fields.Selection([
        ('earn', 'Devengo'),
        ('deduction', 'Deducción')
    ], string='Tipo', required=True, default='deduction')
    salary_rule_id = fields.Many2one(
        'hr.salary.rule',
        string='Regla Salarial Asociada',
        required=True,
        domain="[('category_id.code', 'in', ['ALW', 'BASIC', 'DED'])]",
        help="Regla salarial relacionada al ítem recurrente."
    )
    rule_category_code = fields.Char(
        related='salary_rule_id.category_id.code', store=True, string="Cat. Regla")
    rule_type_concept = fields.Selection(
        # selection se toma del campo original en hr.salary.rule
        selection=lambda self: self.env['hr.salary.rule']._fields['type_concept'].selection,
        related='salary_rule_id.type_concept', store=True, string="Tipo Concepto (NE)"
    )
    rule_earn_category = fields.Selection(
        # selection se toma del campo original en hr.salary.rule
        selection=lambda self: self.env['hr.salary.rule']._fields['earn_category'].selection,
        related='salary_rule_id.earn_category', store=True, string="Cat. Devengo (NE)"
    )
    rule_deduction_category = fields.Selection(
        # selection se toma del campo original en hr.salary.rule
        selection=lambda self: self.env['hr.salary.rule']._fields['deduction_category'].selection,
        related='salary_rule_id.deduction_category', store=True, string="Cat. Deducción (NE)"
    )

    partner_id = fields.Many2one(
        'res.partner', string='Tercero Asociado', ondelete='restrict')
    notes = fields.Text(string='Notas Internas')
    active = fields.Boolean(string='Activo', default=True)

    _sql_constraints = [
        ('code_unique', 'unique (code)',
         'El código del tipo de ítem recurrente debe ser único.')
    ]

    @api.constrains('item_type', 'salary_rule_id')
    def _check_rule_type_consistency(self):
        for record in self:
            if record.salary_rule_id:
                inferred_type = 'earn' if record.salary_rule_id.category_id.code in [
                    'ALW', 'BASIC', 'GROSS', 'NET'] else 'deduction'
                if record.item_type != inferred_type:
                    raise ValidationError(_(
                        "El tipo de ítem ('%s') no coincide con el tipo inferido de la regla salarial ('%s')."
                    ) % (record.item_type, inferred_type))
