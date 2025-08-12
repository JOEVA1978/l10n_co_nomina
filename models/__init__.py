# -*- coding: utf-8 -*-

# 1. Catálogos y Modelos Base (Sin dependencias internas)
# Estos modelos deben cargarse primero porque otros modelos los utilizan.
from . import l10n_co_nomina_catalogs
from . import hr_payroll_catalogues
from . import l10n_co_nomina_resolution
from . import identification_type
from . import organization_type
from . import regime_type
from . import res_city

# 2. Conector y Mixins (Bases para otros modelos)
# El modelo 'l10n_co_hr_payroll.edi' debe cargarse ANTES que 'hr_payslip'
from . import payroll_api_connector
from . import edi
from . import l10n_co_dian_patch

# 3. Modelos que Heredan de Odoo (Dependen de los modelos base)
# res_company y res_config_settings dependen de l10n_co_nomina_resolution
from . import res_company
from . import res_config_settings
from . import hr_employee
from . import hr_leave_type
from . import hr_contract
from . import hr_salary_rule
from . import hr_rule_input
from . import res_users
from . import account_move

# 4. Modelos de Items Recurrentes
from . import hr_recurring_item_type
from . import hr_recurring_item

# 5. Modelos de Líneas de Nómina
from . import hr_payslip_line
from . import earn_line
from . import deduction_line

# 6. Modelos Principales (Dependen de casi todo lo anterior)
from . import hr_payslip
from . import hr_payslip_edi

# 7. Asistentes (Wizards)
from . import edi_gen
