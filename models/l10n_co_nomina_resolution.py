# -*- coding: utf-8 -*-

from odoo import fields, models, api, _
from odoo.exceptions import ValidationError


class PayrollResolution(models.Model):
    _name = 'l10n_co_nomina.resolution'
    _description = 'Resolución de Nómina Electrónica APIDIAN'

    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        string="Compañía"
    )
    type_document_id = fields.Selection(
        [
            ('9', 'Nómina Individual'),
            ('10', 'Nota de Ajuste de Nómina')
        ],
        string="Tipo de Documento",
        required=True
    )
    prefix = fields.Char(
        string="Prefijo",
        required=True,
        help="Prefijo autorizado por la DIAN para numeración de nómina electrónica."
    )
    resolution_number = fields.Char(
        string="Número de Resolución",
        help="Número de la resolución otorgada por la DIAN. Opcional para control interno."
    )
    resolution_date = fields.Date(
        string="Fecha de Resolución",
        help="Fecha en que la DIAN expidió la resolución. Opcional."
    )
    from_number = fields.Integer(
        string="Desde",
        required=True,
        help="Número inicial autorizado en la resolución."
    )
    to_number = fields.Integer(
        string="Hasta",
        required=True,
        help="Número final autorizado en la resolución."
    )
    state = fields.Selection(
        [
            ('active', 'Activa'),
            ('inactive', 'Inactiva')
        ],
        string="Estado",
        default='active',
        help="Estado de vigencia de la resolución en la plataforma."
    )

    _sql_constraints = [
        (
            'unique_resolution_by_range',
            'UNIQUE(company_id, type_document_id, prefix, from_number, to_number)',
            '¡Ya existe una resolución para este rango, tipo de documento y prefijo en esta compañía!'
        ),
    ]

    @api.constrains('company_id', 'type_document_id', 'prefix', 'from_number', 'to_number')
    def _check_overlapping_ranges(self):
        """
        Evita que se creen resoluciones con rangos solapados para el mismo prefijo, tipo de documento y compañía.
        """
        for rec in self:
            domain = [
                ('company_id', '=', rec.company_id.id),
                ('type_document_id', '=', rec.type_document_id),
                ('prefix', '=', rec.prefix),
                ('id', '!=', rec.id),
                ('state', '=', 'active'),
                # Check for overlap: (A <= y) and (B >= x)
                ('from_number', '<=', rec.to_number),
                ('to_number', '>=', rec.from_number),
            ]
            overlapping = self.env['l10n_co_nomina.resolution'].search(domain)
            if overlapping:
                raise ValidationError(_(
                    "El rango de numeración definido (%s - %s) para el prefijo %s y tipo %s se solapa con otra resolución activa en la misma compañía."
                ) % (rec.from_number, rec.to_number, rec.prefix, rec.type_document_id))
