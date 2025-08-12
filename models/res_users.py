# -*- coding: utf-8 -*-
#
#   inencon S.A.S. - Copyright (C) (2024)
#   ... (resto de comentarios de licencia) ...
#

# from odoo import fields, models # No necesitamos importar nada si no añadimos campos

# class ResUsers(models.Model):
#     _inherit = 'res.users'

# --- Campos Relacionados Eliminados ---
# Estos campos apuntaban a campos 'private_*' que ya no existen en hr.employee.
# La información relevante (tipo doc, número, dirección) se consulta directamente
# en hr.employee o su partner asociado.

# private_postal_id = fields.Many2one(related='employee_id.private_postal_id', ...) # ELIMINADO
# private_postal_department_id = fields.Many2one(related='employee_id.private_postal_department_id', ...) # ELIMINADO
# private_postal_municipality_id = fields.Many2one(related='employee_id.private_postal_municipality_id', ...) # ELIMINADO
# private_first_name = fields.Char(related='employee_id.private_first_name', ...) # ELIMINADO (se consulta en employee)
# private_other_names = fields.Char(related='employee_id.private_other_names', ...) # ELIMINADO (se consulta en employee)
# private_surname = fields.Char(related='employee_id.private_surname', ...) # ELIMINADO (se consulta en employee)
# private_second_surname = fields.Char(related='employee_id.private_second_surname', ...) # ELIMINADO (se consulta en employee)
# private_vat = fields.Char(related='employee_id.private_vat', ...) # ELIMINADO (se consulta en employee)
# private_type_document_identification_id = fields.Many2one(related='employee_id.private_type_document_identification_id', ...) # ELIMINADO (se consulta en employee)
