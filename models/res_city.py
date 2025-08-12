# -*- coding: utf-8 -*-
from odoo import fields, models

class ResCity(models.Model):
    _inherit = 'res.city'

    apidian_code = fields.Char(string="Código Municipio APIDIAN")