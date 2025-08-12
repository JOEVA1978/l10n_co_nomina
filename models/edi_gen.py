# -*- coding: utf-8 -*-
#
#   inencon S.A.S. - Copyright (C) (2024)
#
#   Este programa es software libre: puede redistribuirlo y/o modificarlo
#   bajo los términos de la GNU LGPL v3 o (a su elección) cualquier versión posterior.
#

import logging
from odoo import fields, models, api, _

_logger = logging.getLogger(__name__)


class EdiGen(models.TransientModel):
    _name = 'l10n_co_hr_payroll.edi_gen'
    _description = 'Generar Nóminas Electrónicas EDI'

    # ----------------------------
    # Campos del wizard
    # ----------------------------
    month = fields.Selection([
        ('1', 'Enero'), ('2', 'Febrero'), ('3', 'Marzo'), ('4', 'Abril'),
        ('5', 'Mayo'), ('6', 'Junio'), ('7', 'Julio'), ('8', 'Agosto'),
        ('9', 'Septiembre'), ('10', 'Octubre'), ('11',
                                                 'Noviembre'), ('12', 'Diciembre')
    ], string='Mes', required=True, default=lambda self: str(fields.Date.context_today(self).month))

    year = fields.Integer(
        string='Año', required=True,
        default=lambda self: fields.Date.context_today(self).year
    )

    payroll_type = fields.Selection([
        ('102', 'Nómina Individual (102)'),
        ('103', 'Nómina Individual de Ajuste (103)'),
    ], string='Tipo de Documento NE', required=True, default='102')

    # ---------------------------------------------------------------------------------
    # MÉTODO PRINCIPAL: Generar registros hr.payslip.edi según los criterios del wizard
    # ---------------------------------------------------------------------------------
    def generate(self):
        self.ensure_one()
        _logger.info(
            f"[EDI] Iniciando generación EDI - Mes: {self.month}, Año: {self.year}, Tipo: {self.payroll_type}"
        )

        payslip_env = self.env['hr.payslip']
        edi_payslip_env = self.env['hr.payslip.edi']
        company = self.env.company
        periodicidad = getattr(company, 'payroll_periodicity', 'quincenal')

        # --- Filtrar nóminas según payroll_type ---
        payslip_domain = [
            ('year', '=', int(self.year)),
            ('month', '=', self.month),
            ('state', 'in', ('done', 'paid')),
        ]
        if self.payroll_type == '102':
            payslip_domain += [
                ('credit_note', '=', False),
                ('origin_payslip_id', '=', False),
            ]
            _logger.info("[EDI] Filtrado: Nómina Individual (102)")
        elif self.payroll_type == '103':
            payslip_domain += [
                ('credit_note', '=', True),
                ('origin_payslip_id', '!=', False),
            ]
            _logger.info("[EDI] Filtrado: Nómina Ajuste (103)")

        payslips = payslip_env.search(payslip_domain)
        _logger.info(f"[EDI] Nóminas a procesar encontradas: {len(payslips)}")

        # Eliminar EDI draft antiguos de ese mes/año/tipo
        edi_draft_domain = [
            ('year', '=', int(self.year)),
            ('month', '=', self.month),
            ('state', '=', 'draft'),
        ]
        edi_payslips_draft = edi_payslip_env.search(edi_draft_domain)
        if edi_payslips_draft:
            _logger.info(
                f"[EDI] Borrando {len(edi_payslips_draft)} EDI en borrador antiguos.")
            edi_payslips_draft.unlink()

        # Agrupar payslips por empleado
        payslips_by_employee = {}
        for payslip in payslips:
            emp_id = payslip.employee_id.id
            payslips_by_employee.setdefault(emp_id, []).append(payslip)

        edi_created = []
        for emp_id, payslip_list in payslips_by_employee.items():
            crear_edi = False
            # Valida periodicidad
            if periodicidad == 'quincenal' and len(payslip_list) == 2:
                crear_edi = True
            elif periodicidad == 'mensual' and len(payslip_list) == 1:
                crear_edi = True

            if crear_edi:
                # Previene duplicados
                existing_edi = edi_payslip_env.search([
                    ('year', '=', int(self.year)),
                    ('month', '=', self.month),
                    ('employee_id', '=', emp_id),
                    # ('document_type', '=', self.payroll_type), # Si tu modelo lo tiene
                ], limit=1)
                if existing_edi:
                    continue

                new_edi = edi_payslip_env.create({
                    'year': int(self.year),
                    'month': self.month,
                    'employee_id': emp_id,
                    # 'document_type': self.payroll_type,
                })
                # Asociar los payslips al EDI
                new_edi.payslip_ids = [(6, 0, [ps.id for ps in payslip_list])]
                # Asignar último contrato
                if payslip_list:
                    new_edi.contract_id = payslip_list[-1].contract_id.id
                edi_created.append(new_edi)
            else:
                _logger.warning(
                    f"[EDI] Empleado {emp_id} no tiene la cantidad adecuada de payslips: encontrados {len(payslip_list)}"
                )

        _logger.info(
            "[EDI] Proceso de generación EDI completado correctamente.")

        # Acción de retorno
        action = {
            "name": _("Nóminas Electrónicas Generadas"),
            "type": "ir.actions.act_window",
            "res_model": "hr.payslip.edi",
            "views": [[False, "list"], [False, "form"]],
            "domain": [('year', '=', int(self.year)), ('month', '=', self.month)],
            "context": {'search_default_year': int(self.year), 'search_default_month': self.month},
        }
        return action
