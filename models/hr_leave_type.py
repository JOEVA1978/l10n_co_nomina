# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    code = fields.Char(
        string="Código",
        copy=False,
        help="Código único para identificar este tipo de tiempo personal/ausencia. Puede ser usado para integraciones o reglas específicas."
    )

    # Restricción para asegurar que el código sea único (recomendado)
    _sql_constraints = [
        ('code_uniq', 'unique (code)',
         "¡El código del tipo de ausencia debe ser único!"),
    ]
