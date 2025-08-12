# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class Contract(models.Model):
    _inherit = 'hr.contract'

    # --- Campos Nómina Electrónica CO ---
    # Campos existentes (asegúrate de que apunten a los nuevos modelos)
    type_worker_id = fields.Many2one(
        'l10n_co_nomina.worker.type',
        string='Tipo Trabajador (NE)',
        tracking=True,
        help="Clasificación del tipo de trabajador según DIAN.")
    subtype_worker_id = fields.Many2one(
        'l10n_co_nomina.subtype.worker',
        string='Subtipo Trabajador (NE)',
        tracking=True,
        help="Clasificación del subtipo de trabajador según DIAN.")
    type_contract_id = fields.Many2one(
        'l10n_co_nomina.contract.type',
        string='Tipo Contrato (NE)',
        tracking=True,
        help="Clasificación del tipo de contrato según DIAN.")

    # Campos Boolean existentes (asegúrate de que existan)
    high_risk_pension = fields.Boolean(
        string='Alto Riesgo Pensión',
        tracking=True,
        help="Indica si el trabajador cotiza por alto riesgo en pensión.")
    integral_salary = fields.Boolean(
        string='Salario Integral',
        tracking=True,
        help="Indica si el contrato maneja salario integral.")

    # Nuevos campos Many2one
    arl_risk_level = fields.Many2one(
        'l10n_co_nomina.arl.risk.level',
        string='Nivel de Riesgo ARL',
        tracking=True,
        help="Nivel de riesgo para cotización ARL.")
    ccf_id = fields.Many2one(
        'l10n_co_nomina.ccf',
        string='Caja de Compensación',
        tracking=True,
        help="Caja de Compensación Familiar a la que está afiliado el empleado.")
    eps_id = fields.Many2one(
        'l10n_co_nomina.eps',
        string='E.P.S.',
        tracking=True,
        help="Entidad Promotora de Salud a la que está afiliado el empleado.")
    pension_id = fields.Many2one(
        'l10n_co_nomina.pension.fund',
        string='Fondo Pensión',
        tracking=True,
        help="Fondo de Pensión al que está afiliado el empleado.")
    # CORREGIDO: Renombrado de pr_cesan_id a cesantias_id
    cesantias_id = fields.Many2one(
        'l10n_co_nomina.cesantias.fund',
        string='Fondo Cesantías',
        tracking=True,
        help="Fondo de Cesantías al que está afiliado el empleado.")

    # Otros campos estándar de Odoo como 'structure_type_id', 'wage', etc. ya existen.
