# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    is_payroll_document_proxy = fields.Boolean(default=False, copy=False)

    def is_sale_document(self, include_receipts=False):
        """
        Sobrescribimos este método para asegurar que nuestros asientos de nómina
        nunca sean tratados como factura electrónica, manteniendo compatibilidad con Odoo 18.
        """
        if self.is_payroll_document_proxy:
            return False
        return super(AccountMove, self).is_sale_document(include_receipts=include_receipts)
