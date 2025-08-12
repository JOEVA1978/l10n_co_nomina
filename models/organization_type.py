# -*- coding: utf-8 -*-
from odoo import fields, models

class OrganizationType(models.Model):
    _name = 'l10n_co_nomina.organization.type'
    _description = 'Tipo de Organización'

    name = fields.Char(string="Nombre", required=True)
    code = fields.Char(string="Código", required=True)