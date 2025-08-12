# -*- coding: utf-8 -*-
#
#   inencon S.A.S. - Copyright (C) (2024)
#
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Lesser General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU Lesser General Public License for more details.
#
#   You should have received a copy of the GNU Lesser General Public License
#   along with this program. If not, see <https://www.gnu.org/licenses/>.
#
#   email: info@inencon.com
#

import logging  # Añadido para _logger
from odoo import fields, models, api, _
from odoo.addons import decimal_precision as dp
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

# Añadido para usar en compute_co_partner
_logger = logging.getLogger(__name__)


class HrSalaryRule(models.Model):
    _inherit = 'hr.salary.rule'

    # El campo input_ids parece ser un campo custom o de una versión anterior.
    # Si no lo usas activamente o causa conflictos, considera eliminarlo o revisarlo.
    # Lo mantenemos por ahora ya que estaba en tu código original.
    input_ids = fields.One2many(
        'hr.rule.input', 'input_id', string='Inputs', copy=True)

    # --- Campos de Clasificación para Nómina Electrónica ---
    type_concept = fields.Selection([
        ('earn', 'Devengo'),
        ('deduction', 'Deducción'),
        ('other', 'Otro')
    ], string="Tipo Concepto (NE)", default="other", required=True,
        help="Clasifica la regla como un devengo, deducción u otro para la Nómina Electrónica.")

    earn_category = fields.Selection([
        ('basic', 'Básico'),
        ('vacation_common', 'Vacaciones Comunes'),
        ('vacation_compensated', 'Vacaciones Compensadas'),
        ('primas', 'Primas Salariales'),
        ('primas_non_salary', 'Primas No Salariales'),
        ('layoffs', 'Cesantías'),
        ('layoffs_interest', 'Intereses de Cesantías'),
        ('licensings_maternity_or_paternity_leaves',
         'Licencia Maternidad/Paternidad'),
        ('licensings_permit_or_paid_licenses', 'Licencia Remunerada'),
        ('licensings_suspension_or_unpaid_leaves',
         'Licencia No Remunerada / Suspensión'),
        ('endowment', 'Dotación'),
        ('sustainment_support', 'Apoyo Sostenimiento'),
        ('telecommuting', 'Auxilio Teletrabajo'),
        ('company_withdrawal_bonus', 'Bonificación Retiro'),
        ('compensation', 'Indemnización'),
        ('refund', 'Reintegro'),
        ('transports_assistance', 'Auxilio Transporte'),
        ('transports_viatic', 'Viático Salarial'),
        ('transports_non_salary_viatic', 'Viático No Salarial'),
        ('daily_overtime', 'Hora Extra Diurna'),
        ('overtime_night_hours', 'Hora Extra Nocturna'),
        ('hours_night_surcharge', 'Recargo Nocturno'),
        ('sunday_holiday_daily_overtime', 'Hora Extra Diurna Dominical/Festivo'),
        ('daily_surcharge_hours_sundays_holidays',
         'Recargo Dominical/Festivo Diurno'),
        ('sunday_night_overtime_holidays', 'Hora Extra Nocturna Dominical/Festivo'),
        ('sunday_holidays_night_surcharge_hours',
         'Recargo Dominical/Festivo Nocturno'),
        ('incapacities_common', 'Incapacidad Común'),
        ('incapacities_professional', 'Incapacidad Profesional'),
        ('incapacities_working', 'Incapacidad Laboral'),
        ('bonuses', 'Bonificación Salarial'),
        ('bonuses_non_salary', 'Bonificación No Salarial'),
        ('assistances', 'Auxilio Salarial'),
        ('assistances_non_salary', 'Auxilio No Salarial'),
        ('legal_strikes', 'Huelga Legal'),
        ('other_concepts', 'Otro Concepto Salarial'),
        ('other_concepts_non_salary', 'Otro Concepto No Salarial'),
        ('compensations_ordinary', 'Compensación Ordinaria'),
        ('compensations_extraordinary', 'Compensación Extraordinaria'),
        ('vouchers', 'Bono Salarial'),
        ('vouchers_non_salary', 'Bono No Salarial'),
        ('vouchers_salary_food', 'Bono Alimentación Salarial'),
        ('vouchers_non_salary_food', 'Bono Alimentación No Salarial'),
        ('commissions', 'Comisiones'),
        # Devengo asociado a pago a tercero? Revisar semántica
        ('third_party_payments', 'Pago a Terceros'),
        ('advances', 'Anticipos')  # Devengo asociado a anticipo? Revisar semántica
        # Requerido si type_concept es 'earn'
    ], string="Categoría Devengo (NE)", default="other_concepts",
        help="Categoría específica del devengo según Anexo Técnico de Nómina Electrónica.")

    deduction_category = fields.Selection([
        ('health', 'Salud'),
        ('pension_fund', 'Fondo de Pensión'),
        ('pension_security_fund', 'Fondo Solidaridad Pensional'),
        ('pension_security_fund_subsistence', 'Fondo Subsistencia'),
        ('voluntary_pension', 'Pensión Voluntaria'),
        ('withholding_source', 'Retención en la Fuente'),
        ('afc', 'AFC'),
        ('cooperative', 'Cooperativa'),
        ('tax_lien', 'Embargo Fiscal'),
        ('complementary_plans', 'Planes Complementarios Salud'),
        ('education', 'Educación'),
        ('refund', 'Reintegro'),
        ('debt', 'Deuda'),
        ('trade_unions', 'Sindicatos'),
        ('sanctions_public', 'Sanción Pública'),
        ('sanctions_private', 'Sanción Privada'),
        ('libranzas', 'Libranzas'),
        ('third_party_payments', 'Pago a Terceros'),
        ('advances', 'Anticipos'),
        ('other_deductions', 'Otras Deducciones')
        # Requerido si type_concept es 'deduction'
    ], string="Categoría Deducción (NE)", default="other_deductions",
        help="Categoría específica de la deducción según Anexo Técnico de Nómina Electrónica.")

    # --- Campos para cálculo EDI ---
    edi_percent_select = fields.Selection([
        ('default', 'Por Defecto (Regla)'),
        ('fix', 'Porcentaje Fijo'),
        ('code', 'Código Python'),
    ], string='Tipo Porcentaje (NE)', index=True, required=True, default='default',
        help="Método para calcular el porcentaje específico para Nómina Electrónica (si aplica).")
    edi_percent_python_compute = fields.Text(string='Código Python Porcentaje (NE)',
                                             default='# result = ...')
    edi_percent_fix = fields.Float(
        string='Porcentaje Fijo (NE)', digits=dp.get_precision('Payroll Rate'), default=0.0)

    # --- Campo para detalle ---
    edi_is_detailed = fields.Boolean(string="Detallado en Entrada?", default=False,
                                     help="Marcar si este concepto se ingresa manualmente con detalle (ej. horas extras, incapacidades) en lugar de calcularse automáticamente por la regla.")

    # --- Campos para cantidad EDI ---
    # *** SELECCIÓN ACTUALIZADA PARA INCLUIR OPCIONES NECESARIAS ***
    edi_quantity_select = fields.Selection([
        ('default', 'Por Defecto (Regla)'),
        ('input', 'Entrada Específica'),             # <-- Opción añadida
        ('worked_days', 'Días Trabajados Específicos'),  # <-- Opción añadida
        ('code', 'Código Python'),                  # <-- Opción añadida
        # ('auto', 'Automático (Días/Horas Trabajados)') # 'auto' podría no ser una opción estándar, usar 'default' o 'code'
    ], string='Cantidad (NE)', index=True, required=True, default='default',
        help="Método para obtener la cantidad (días/horas) para Nómina Electrónica.")

    # *** CAMPOS NUEVOS AÑADIDOS ***
    edi_quantity_input_code = fields.Char(
        string="Código Entrada Cantidad (NE)",
        help="Código de la línea de entrada ('Other Input') a usar cuando 'Cantidad (NE)' es 'Entrada Específica'.")

    edi_quantity_worked_days_code = fields.Char(
        string="Código Días Trabajados Cantidad (NE)",
        help="Código de la línea de 'Worked Days' a usar cuando 'Cantidad (NE)' es 'Días Trabajados Específicos'.")

    # --- Campo para relacionar porcentaje con campo de compañía ---
    # *** CAMPO NUEVO AÑADIDO (Basado en el XML que usaba edi_percent_company_field) ***
    edi_percent_company_field = fields.Char(
        string="Campo Porcentaje Compañía (NE)",
        help="Nombre técnico del campo en res.company que contiene el porcentaje a reportar para NE (usado si Tipo Porcentaje es 'Compañía').")
    # *** REVISAR/ACTUALIZAR Selección edi_percent_select para incluir 'company' si se usa ***
    edi_percent_select = fields.Selection([
        ('default', 'Por Defecto (Regla)'),
        ('fix', 'Porcentaje Fijo'),
        ('code', 'Código Python'),
        ('company', 'Campo de Compañía'),  # <-- Opción añadida
    ], string='Tipo Porcentaje (NE)', index=True, required=True, default='default',
        help="Método para calcular el porcentaje específico para Nómina Electrónica (si aplica).")

    # --- Campos para Partner ---
    co_partner_select = fields.Selection([
        ('default', 'Por Defecto (Regla)'),
        ('code', 'Código Python')
    ], string='Computar Partner (NE)', default='default', required=True,
        help="Permite asignar un tercero específico a esta línea (ej. para pagos a terceros, libranzas).")

    co_partner_python_compute = fields.Text(string='Código Python Partner (NE)',
                                            default='# result = ...')

    # --- Métodos ---
    # (Los métodos compute_co_partner, compute_edi_percent, _get_safe_eval_local_dict se mantienen como estaban)
    def compute_co_partner(self, payslip):
        """Calcula el partner asociado a la línea según la configuración."""
        self.ensure_one()
        if self.co_partner_select == 'code':
            local_dict = self._get_safe_eval_local_dict(payslip)
            try:
                # Usar co_partner_python_compute
                safe_eval(self.co_partner_python_compute or 'result = None',
                          local_dict, mode='exec', nocopy=True)
                partner_id = local_dict.get('result')
                if partner_id and isinstance(partner_id, int):
                    # Verificar existencia es costoso aquí, confiar en el ID por ahora
                    # if self.env['res.partner'].browse(partner_id).exists(): return partner_id
                    return partner_id
                else:
                    # No loguear warning si es None intencionalmente
                    # _logger.warning(...)
                    return None
            except Exception as e:
                _logger.error(
                    'Error en código Python de Partner para regla %s (%s): %s', self.name, self.code, e)
                raise UserError(
                    _('Error en código Python de Partner para regla %s (%s).\nError: %s') % (self.name, self.code, e))
        else:  # default
            # Devolver partner de la regla si existe (campo 'partner_id' estándar de hr.salary.rule)
            # Si no existe, devolver None. No intentar obtener de EPS/Pension aquí por defecto.
            return self.partner_id.id if self.partner_id else None

    def compute_edi_percent(self, payslip):
        """Calcula el porcentaje EDI según la configuración."""
        # Añadida lógica para 'company'
        self.ensure_one()
        if self.edi_percent_select == 'fix':
            return self.edi_percent_fix
        elif self.edi_percent_select == 'code':
            local_dict = self._get_safe_eval_local_dict(payslip)
            try:
                safe_eval(self.edi_percent_python_compute or 'result = 0.0',
                          local_dict, mode='exec', nocopy=True)
                # Asegurar que devuelve float
                return float(local_dict.get('result', 0.0))
            except Exception as e:
                _logger.error(
                    'Error en código Python de Porcentaje EDI para regla %s (%s): %s', self.name, self.code, e)
                raise UserError(
                    _('Error en código Python de Porcentaje EDI para regla %s (%s).\nError: %s') % (self.name, self.code, e))
        elif self.edi_percent_select == 'company':
            # *** NUEVA LÓGICA ***
            if self.edi_percent_company_field and payslip.contract_id and payslip.contract_id.company_id:
                company = payslip.contract_id.company_id
                # Usar getattr de forma segura para obtener el valor del campo
                percent_value = getattr(
                    company, self.edi_percent_company_field, 0.0)
                return float(percent_value) if percent_value else 0.0
            return 0.0
        else:  # default
            # Si la regla principal es porcentaje, devolver ese %
            if self.amount_select == 'percentage':
                return self.amount_percentage
            # Si no, ¿qué devolver? 0 es más seguro que 100 si no aplica.
            return 0.0

    # --- Método Helper para safe_eval (Revisado para asegurar disponibilidad de variables) ---

    def _get_safe_eval_local_dict(self, payslip):
        """Prepara el diccionario local para safe_eval de forma más segura."""
        self.ensure_one()
        employee = payslip.employee_id
        contract = payslip.contract_id
        # Fallback a compañía principal
        company = contract.company_id if contract else self.env.company

        # Objeto 'inputs'
        class BrowsableDict(dict):
            def __getattr__(self, name):
                # Devolver 0.0 o None si no se encuentra para evitar errores
                return self.get(name)

            def __getitem__(self, name):
                return self.get(name)

        inputs_dict = {line.code: line for line in payslip.input_line_ids}
        inputs = BrowsableDict(inputs_dict)

        # Objeto 'worked_days'
        worked_days_dict = {line.code or line.work_entry_type_id.code:
                            line for line in payslip.worked_days_line_ids if line.code or line.work_entry_type_id}
        worked_days = BrowsableDict(worked_days_dict)

        # Objeto 'categories' con totales
        categories_dict = {}
        for line in payslip.line_ids:
            if line.category_id.code:
                # Usar get con default 0.0 y sumar
                categories_dict[line.category_id.code] = categories_dict.get(
                    line.category_id.code, 0.0) + line.total
        categories = BrowsableDict(categories_dict)
        # Añadir acceso directo a los totales como categories.CODE
        # Mantener compatibilidad si se usa categories.dict
        categories.dict = categories_dict

        # Incluir 'ref' para resolver XML IDs si es necesario (usar con cuidado)
        def _ref(xml_id, raise_if_not_found=True):
            return self.env.ref(xml_id, raise_if_not_found=raise_if_not_found)

        return {
            'payslip': payslip,
            'employee': employee,
            'contract': contract,
            'inputs': inputs,
            'worked_days': worked_days,
            'categories': categories,
            'company': company,  # Añadir compañía
            'env': self.env,
            'result': None,
            'ref': _ref,  # Añadir función ref
            # Podrían añadirse utilidades como date, datetime, relativedelta aquí si se usan comúnmente
        }
