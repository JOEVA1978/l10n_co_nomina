# -*- coding: utf-8 -*-
from odoo import models, fields

class IdentificationType(models.Model):
    _name = 'l10n_co_nomina.identification.type'
    _description = 'Tipo de Documento de Identificación'

    name = fields.Char(string="Nombre", required=True)
    code = fields.Char(string="Código", required=True)