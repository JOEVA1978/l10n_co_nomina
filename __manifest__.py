# -*- coding: utf-8 -*-
# ... (licencia) ...
{
    'name': 'Nómina Electrónica DIAN para Colombia',
    'summary': 'Nómina electrónica DIAN para Odoo 17',
    'description': "Gestión de Nómina Electrónica para Colombia (DIAN) en Odoo 17.",
    'author': 'Inencon SAS / Colombia',
    'license': 'LGPL-3',
    'category': 'Human Resources/Payroll',
    'version': '17.0.1.0.0',
    'website': "https://www.inenconsas.com",
    'support': 'info@inenconsas.com',
    'depends': [
        'hr_contract',
        'hr_payroll',
        'hr_payroll_account',  
        'account',
        'l10n_latam_base',
        'hr_holidays',
        'l10n_co',
        'account_edi',
        'l10n_co_edi',
        'mail',
    ],
    'data': [
        'data/resource_calendar_data.xml',
        'data/hr_payroll_structure_data.xml',
        'data/hr_salary_rule_data.xml',
        'data/hr_payroll_sequence.xml',
        'data/hr_payroll_catalogues_data.xml',
        'data/hr_leave_type_data.xml',
        'data/hr_payslip_input_type_data.xml',
        'data/hr_arl_risk_level_data.xml',
        'data/hr_work_entry_type_data.xml',
        'security/ir.model.access.csv',

        # Views
        'views/l10n_co_nomina_catalog_views.xml',
        'views/hr_recurring_item_views.xml',
        'views/hr_contract_views.xml',
        'views/hr_salary_rule_views.xml',
        'views/earn_line_views.xml',
        'views/deduction_line_views.xml',
        'views/hr_payslip_views.xml',
        'views/hr_payslip_edi_views.xml',
        'views/edi_gen_views.xml',
        'views/hr_employee_views.xml',
        'views/res_config_settings_views.xml',
        'views/l10n_co_nomina_resolution_views.xml',
        'views/res_company_views.xml',
        'views/hr_leave_type_views.xml',
        'views/hr_payslip_account_move_report.xml',
        'views/payroll_electronic_templates.xml',
        'views/hr_payslip_report_views.xml',

        # Wizards
        'wizard/edi_gen_wizard_views.xml',

        # Reports
        'report/hr_payslip_edi_report.xml',
    ],
    'installable': True,
    'application': False,
}

