# -*- coding: utf-8 -*-

from odoo import fields, models, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__) 


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    module_l10n_co_hr_payroll = fields.Boolean(string='Colombian Payroll')

    # === Campos de Parámetros de Nómina (se mantienen igual) ===
    smmlv_value = fields.Monetary(related="company_id.smmlv_value",
                                  string="SMMLV", readonly=False, currency_field='currency_id')
    uvt_value = fields.Monetary(related="company_id.uvt_value",
                                string="UVT", readonly=False, currency_field='currency_id')
    stm_value = fields.Monetary(related="company_id.stm_value",
                                string="Monthly transportation allowance", readonly=False, currency_field='currency_id')

    # === Campos de Porcentajes de Horas Extras (se mantienen igual) ===
    daily_overtime = fields.Float(
        related="company_id.daily_overtime", string="% Daily overtime", readonly=False)
    overtime_night_hours = fields.Float(
        related="company_id.overtime_night_hours", string="% Overtime night hours", readonly=False)
    hours_night_surcharge = fields.Float(
        related="company_id.hours_night_surcharge", string="% Hours night surcharge", readonly=False)
    sunday_holiday_daily_overtime = fields.Float(
        related="company_id.sunday_holiday_daily_overtime", string="% Sunday and Holiday daily overtime", readonly=False)
    daily_surcharge_hours_sundays_holidays = fields.Float(
        related="company_id.daily_surcharge_hours_sundays_holidays", string="% Daily hours on sundays and holidays", readonly=False)
    sunday_night_overtime_holidays = fields.Float(
        related="company_id.sunday_night_overtime_holidays", string="% Sunday night overtime and holidays", readonly=False)
    sunday_holidays_night_surcharge_hours = fields.Float(
        related="company_id.sunday_holidays_night_surcharge_hours", string="% Sunday and holidays night surcharge hours", readonly=False)

    # === CAMPOS RELATED para la Configuración de la API de Nómina Electrónica (APIDIAN) ===
    l10n_co_payroll_api_url = fields.Char(
        related='company_id.l10n_co_payroll_api_url',
        string="URL API Nómina Electrónica (APIDIAN)",
        readonly=False
    )
    l10n_co_payroll_api_token = fields.Char(
        related='company_id.l10n_co_payroll_api_token',
        string="Token API Nómina Electrónica (APIDIAN)",
        readonly=False,
        groups="base.group_system"
    )
    l10n_co_payroll_software_id = fields.Char(
        related='company_id.l10n_co_payroll_software_id',
        string="Software ID DIAN (API Nómina)",
        readonly=False
    )
    l10n_co_payroll_software_pin = fields.Char(
        related='company_id.l10n_co_payroll_software_pin',
        string="Software PIN DIAN (API Nómina)",
        readonly=False
    )
    l10n_co_payroll_certificate_file = fields.Binary(
        related='company_id.l10n_co_payroll_certificate_file',
        string="Certificado Digital .p12 (API)",
        readonly=False
    )
    l10n_co_payroll_certificate_password = fields.Char(
        related='company_id.l10n_co_payroll_certificate_password',
        string="Contraseña Certificado .p12 (API)",
        readonly=False
    )
    type_document_id = fields.Selection(
        related='company_id.l10n_co_payroll_default_type_document_id',
        string='Tipo de Documento por Defecto',
        readonly=False
    )

    ley_1607 = fields.Boolean(
        related='company_id.ley_1607',
        string="Aplica Exoneración Ley 1607 de 2012",
        readonly=False
    )

    payroll_periodicity = fields.Selection(
        related="company_id.payroll_periodicity",
        string="Periodicidad de Nómina",
        readonly=False,
    )
    l10n_co_nomina_default_resolution_id = fields.Many2one(
        related='company_id.l10n_co_nomina_default_resolution_id',
        readonly=False,
        string="Resolución de Nómina por Defecto"
    )
    prefix = fields.Char(
        string="Prefijo (de la resolución por defecto)",
        related='company_id.l10n_co_nomina_default_resolution_id.prefix',
        readonly=True
    )
    edi_payroll_is_not_test = fields.Boolean(
        related='company_id.edi_payroll_is_not_test',
        string="Entorno en Producción (Nómina)",
        readonly=False
    )

    l10n_co_payroll_test_set_id = fields.Char(
        related='company_id.l10n_co_payroll_test_set_id',
        string="ID del Set de Pruebas DIAN",
        readonly=False
    )
    edi_payroll_enable = fields.Boolean(
        related='company_id.edi_payroll_enable',
        string="Habilitar Nómina Electrónica DIAN",
        readonly=False
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        # No se necesita añadir los campos 'related' aquí.
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        # No se necesita el método company.write({}) para los campos 'related'.
        # Odoo guarda los valores en res.company automáticamente.

    # ... (al final de la clase ResConfigSettings) ...

    def action_sync_apidian_config(self):
        """
        Llamado por el botón en la vista de configuración.
        Envía toda la configuración de la compañía a la API de APIDIAN.
        """
        self.ensure_one()
        _logger.info(
            "Iniciando sincronización de configuración con APIDIAN...")
        company = self.env.company
        connector = self.env['l10n_co_nomina.payroll.api.connector']

        try:
            # 1. Configurar Software de Nómina
            if company.l10n_co_payroll_software_id and company.l10n_co_payroll_software_pin:
                _logger.info("Enviando configuración de Software de Nómina...")
                connector.config_software_payroll(
                    company.l10n_co_payroll_software_id,
                    company.l10n_co_payroll_software_pin
                )

            # 2. Configurar Certificado Digital (Usando el método que crearemos en el conector)
            if company.l10n_co_payroll_certificate_file and company.l10n_co_payroll_certificate_password:
                _logger.info("Enviando Certificado Digital...")
                connector.config_certificate()  # Este método lo crearemos a continuación

            # 3. Configurar Resoluciones (Iterando sobre el nuevo modelo)
            if company.l10n_co_payroll_resolution_ids:
                _logger.info("Enviando %d resoluciones...", len(
                    company.l10n_co_payroll_resolution_ids))
                # Pasamos el recordset completo al método del conector
                connector.config_resolution_payroll(
                    company.l10n_co_payroll_resolution_ids)

            _logger.info("Sincronización con APIDIAN completada exitosamente.")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Éxito'),
                    'message': _('La configuración se ha sincronizado correctamente con la API.'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            _logger.error(
                "Error durante la sincronización con APIDIAN: %s", str(e))
            raise UserError(
                _("Fallo la sincronización con la API: %s") % str(e))
