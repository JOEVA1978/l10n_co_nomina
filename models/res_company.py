# -*- coding: utf-8 -*-
from odoo import fields, models, api


class ResCompany(models.Model):
    _inherit = 'res.company'

    # === Campos de Parámetros de Nómina (Existentes) ===
    smmlv_value = fields.Monetary("SMMLV", currency_field='currency_id')
    uvt_value = fields.Monetary("UVT", currency_field='currency_id')
    stm_value = fields.Monetary(
        "Monthly transportation allowance", currency_field='currency_id')

    # === Campos de Porcentajes de Horas Extras (Existentes) ===
    daily_overtime = fields.Float("% Daily overtime", default=25.0)
    overtime_night_hours = fields.Float("% Overtime night hours", default=75.0)
    hours_night_surcharge = fields.Float(
        "% Hours night surcharge", default=35.0)
    sunday_holiday_daily_overtime = fields.Float(
        "% Sunday and Holiday daily overtime", default=100.0)
    daily_surcharge_hours_sundays_holidays = fields.Float(
        "% Daily hours on sundays and holidays", default=75.0)
    sunday_night_overtime_holidays = fields.Float(
        "% Sunday night overtime and holidays", default=150.0)
    sunday_holidays_night_surcharge_hours = fields.Float(
        "% Sunday and holidays night surcharge hours", default=110.0)

    # === NUEVOS CAMPOS para la Configuración de la API de Nómina Electrónica (APIDIAN) ===
    # Estos campos son específicos para la integración con la APIDIAN
    l10n_co_payroll_api_url = fields.Char(
        string="URL API Nómina Electrónica (APIDIAN)",
        help="URL base de la APIDIAN para Nómina Electrónica (ej. http://89.117.148.104:81)"
    )
    l10n_co_payroll_api_token = fields.Char(
        string="Token API Nómina Electrónica (APIDIAN)",
        groups="base.group_system",  # Solo visible para administradores del sistema
        help="Token de autorización Bearer para la APIDIAN. Se obtiene al configurar la compañía en la API."
    )
    l10n_co_payroll_software_id = fields.Char(
        string="Software ID DIAN (API Nómina)",
        help="ID del software asignado por la DIAN para Nómina Electrónica, usado por la API."
    )
    l10n_co_payroll_software_pin = fields.Char(
        string="Software PIN DIAN (API Nómina)",
        help="PIN del software asignado por la DIAN para Nómina Electrónica, usado por la API."
    )
    l10n_co_payroll_certificate_file = fields.Binary(
        string="Certificado Digital (.p12)",
        help="Cargue aquí el archivo del certificado digital (.p12) de la compañía."
    )
    certificate_filename = fields.Char(string="Nombre del Archivo del Certificado")
    
    l10n_co_payroll_certificate_password = fields.Char(
        string="Contraseña Certificado .p12 (API)",
        help="Contraseña del certificado digital .p12, usado por la API. (Opcional si la API gestiona el certificado)."
    )
    type_document_identification_id = fields.Many2one(
        'l10n_co_nomina.identification.type', 
        string='Tipo de Documento de Identificación (Compañía)'
    )
    type_organization_id = fields.Many2one(
        'l10n_co_nomina.organization.type', 
        string='Tipo de Organización (Compañía)'
    )
    type_regime_id = fields.Many2one(
        'l10n_co_nomina.regime.type', 
        string='Tipo de Régimen (Compañía)'
    )
    l10n_co_payroll_resolution_ids = fields.One2many(
        'l10n_co_nomina.resolution', 'company_id',
        string="Resoluciones de Nómina (API)"
    )
    l10n_co_payroll_default_type_document_id = fields.Selection(
        [('9', 'Nómina Individual'), ('10', 'Nota de Ajuste de Nómina')],
        string='Tipo de Documento por Defecto (Nómina Electrónica)'
    )
    l10n_co_nomina_default_resolution_id = fields.Many2one(
        'l10n_co_nomina.resolution',
        string="Resolución de Nómina por Defecto",
        help="Seleccione la resolución que se usará por defecto para los documentos de nómina electrónica."
    )
    l10n_co_payroll_test_set_id = fields.Char(
        string="ID del Set de Pruebas DIAN",
        help="Introduce el Identificador del Set de Pruebas (TestSetId) proporcionado por la DIAN para el ambiente de habilitación."
    )
    edi_payroll_is_not_test = fields.Boolean(
        string="Entorno en Producción (Nómina)",
        help="Marque esta casilla cuando haya completado el set de pruebas y la DIAN lo haya habilitado para producción."
    )
    edi_payroll_enable = fields.Boolean(
        string="Habilitar Nómina Electrónica DIAN",
        default=False
    )
    
    ley_1607 = fields.Boolean(string="Aplica Exoneración Ley 1607 de 2012")

    payroll_periodicity = fields.Selection([
        ('mensual', 'Mensual'),
        ('quincenal', 'Quincenal')
    ], default='quincenal', string="Periodicidad de Nómina")
