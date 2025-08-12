# -*- coding: utf-8 -*-
from odoo import fields, models


class L10nCoNominaTypeWorker(models.Model):
    _name = 'l10n_co_nomina.type.worker'
    _description = 'Tipo de Trabajador (Nómina Electrónica)'
    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, help="Código DIAN")


class L10nCoNominaTypeContract(models.Model):
    _name = 'l10n_co_nomina.type.contract'
    _description = 'Tipo de Contrato (Nómina Electrónica)'
    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, help="Código DIAN")


class L10nCoNominaPayrollPeriod(models.Model):
    _name = 'l10n_co_nomina.payroll.period'
    _description = 'Periodo de Nómina (Nómina Electrónica)'
    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        required=True, help="Código DIAN ('1', '3', '4', '5', '6')")

# --- También necesitaríamos añadir datos iniciales (XML) para estos modelos ---
# Ej: <record id="payroll_period_5" model="l10n_co_nomina.payroll.period">
#         <field name="name">Mensual</field>
#         <field name="code">5</field>
#     </record>
