# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
# Importar decimal_precision si no está ya importado globalmente
from odoo.addons import decimal_precision as dp

# --- Modelos Base para Catálogos ---


class L10nCoNominaCatalogBase(models.AbstractModel):
    """ Modelo abstracto base para catálogos simples de Nómina Electrónica CO. """
    _name = 'l10n_co_nomina.catalog.base'
    _description = 'Catálogo Base Nómina Electrónica CO'
    _order = 'sequence, name'

    sequence = fields.Integer(default=10)
    name = fields.Char(string='Nombre', required=True, translate=True)
    code = fields.Char(string='Código', required=True)
    country_id = fields.Many2one('res.country', string='País', default=lambda self: self.env.ref(
        'base.co', raise_if_not_found=False))
    active = fields.Boolean(default=True, string='Activo')

    _sql_constraints = [
        ('code_country_uniq', 'unique (code, country_id)',
         'El código debe ser único por país!')
    ]


class L10nCoNominaEntityBase(models.AbstractModel):
    """ Modelo abstracto base para entidades de Nómina Electrónica CO (EPS, ARL, etc.). """
    _name = 'l10n_co_nomina.entity.base'
    _description = 'Entidad Base Nómina Electrónica CO'
    _order = 'sequence, name'

    sequence = fields.Integer(default=10)
    partner_id = fields.Many2one(
        'res.partner', string='Contacto (Tercero)', required=True, ondelete='restrict')
    name = fields.Char(related='partner_id.display_name',
                       store=True, readonly=True)  # Nombre tomado del partner
    code = fields.Char(string='Código', required=True)
    country_id = fields.Many2one('res.country', string='País', default=lambda self: self.env.ref(
        'base.co', raise_if_not_found=False))
    active = fields.Boolean(default=True, string='Activo')

    _sql_constraints = [
        ('code_country_uniq', 'unique (code, country_id)',
         'El código debe ser único por país!'),
        ('partner_country_uniq', 'unique (partner_id, country_id)',
         'El contacto debe ser único por país!')
    ]

# --- Modelos Específicos ---


class L10nCoNominaWorkerType(models.Model):
    _name = 'l10n_co_nomina.worker.type'
    _description = 'Tipo de Trabajador (Nómina Electrónica)'
    _inherit = 'l10n_co_nomina.catalog.base'


class L10nCoNominaSubtypeWorker(models.Model):
    _name = 'l10n_co_nomina.subtype.worker'
    _description = 'Subtipo de Trabajador (Nómina Electrónica)'
    _inherit = 'l10n_co_nomina.catalog.base'


class L10nCoNominaContractType(models.Model):
    _name = 'l10n_co_nomina.contract.type'
    _description = 'Tipo de Contrato (Nómina Electrónica)'
    _inherit = 'l10n_co_nomina.catalog.base'


class L10nCoNominaArlRiskLevel(models.Model):
    _name = 'l10n_co_nomina.arl.risk.level'
    _description = 'Nivel de Riesgo ARL (Nómina Electrónica)'
    _inherit = 'l10n_co_nomina.catalog.base'

    # === CAMPO AÑADIDO ===
    percentage = fields.Float(
        string='Porcentaje Cotización (%)',
        # Usar precisión estándar de Odoo para tasas de nómina
        digits='Payroll Rate',
        required=True,
        help="Porcentaje de cotización ARL correspondiente a este nivel de riesgo."
    )
    # =====================


class L10nCoNominaCcf(models.Model):
    _name = 'l10n_co_nomina.ccf'
    _description = 'Caja de Compensación Familiar (Nómina Electrónica)'
    _inherit = 'l10n_co_nomina.entity.base'


class L10nCoNominaEps(models.Model):
    _name = 'l10n_co_nomina.eps'
    _description = 'Entidad Promotora de Salud (Nómina Electrónica)'
    _inherit = 'l10n_co_nomina.entity.base'


class L10nCoNominaPensionFund(models.Model):
    _name = 'l10n_co_nomina.pension.fund'
    _description = 'Fondo de Pensión (Nómina Electrónica)'
    _inherit = 'l10n_co_nomina.entity.base'


class L10nCoNominaCesantiasFund(models.Model):
    _name = 'l10n_co_nomina.cesantias.fund'
    _description = 'Fondo de Cesantías (Nómina Electrónica)'
    _inherit = 'l10n_co_nomina.entity.base'
