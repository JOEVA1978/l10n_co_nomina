# -*- coding: utf-8 -*-
from odoo import fields, models

class RegimeType(models.Model):
    _name = 'l10n_co_nomina.regime.type'
    _description = 'Tipo de Régimen'

    name = fields.Char(string="Nombre", required=True)
    code = fields.Char(string="Código", required=True)