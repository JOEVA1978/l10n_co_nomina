# -*- coding: utf-8 -*-
#
#   inencon S.A.S. - Copyright (C) (2024)
#   ... (resto de comentarios de licencia) ...
#

from odoo import api, fields, models, _
# from odoo.exceptions import UserError # Descomentar si añadimos validaciones


class Employee(models.Model):
    _inherit = "hr.employee"

    # --- Campos de Nombre Estructurado (Mantenidos) ---
    private_first_name = fields.Char("Primer Nombre", compute="_compute_names", store=True, inverse="_inverse_names",
                                     groups="hr.group_hr_user", tracking=True)
    private_other_names = fields.Char("Otros Nombres", compute="_compute_names", store=True, inverse="_inverse_names",
                                      groups="hr.group_hr_user", tracking=True)
    private_surname = fields.Char("Primer Apellido", compute="_compute_names", store=True, inverse="_inverse_names",
                                  groups="hr.group_hr_user", tracking=True)
    private_second_surname = fields.Char("Segundo Apellido", compute="_compute_names", store=True,
                                         inverse="_inverse_names", groups="hr.group_hr_user", tracking=True)

    # --- Campo private_vat REINCORPORADO ---
    private_vat = fields.Char("NIT/Cédula Privado", tracking=True, groups="hr.group_hr_user",
                              help="Campo mantenido por compatibilidad con vistas existentes. Usar preferentemente el campo estándar 'Identificación No'.")

    # --- Campo private_type_document_identification_id REINCORPORADO ---
    # Apunta al modelo estándar LATAM para evitar dependencia de inencon.
    private_type_document_identification_id = fields.Many2one(
        'l10n_latam.identification.type',
        string='Tipo Documento Privado',
        tracking=True,
        groups="hr.group_hr_user",
        help="Campo mantenido por compatibilidad con vistas existentes. Usar preferentemente el campo estándar 'Tipo de Documento'.")

    # --- Campos Postales REINCORPORADOS como Char (Placeholder) ---
    # Añadidos como Char para satisfacer la vista XML sin depender de l10n_co_edi_inencon.
    # No tendrán la funcionalidad de cálculo original.
    private_postal_id = fields.Char("Código Postal (Privado)", tracking=True, groups="hr.group_hr_user",
                                    help="Campo mantenido por compatibilidad con vistas. Funcionalidad original eliminada.")
    private_postal_department_id = fields.Char("Departamento Postal (Privado)", tracking=True, groups="hr.group_hr_user",
                                               help="Campo mantenido por compatibilidad con vistas. Funcionalidad original eliminada.")
    private_postal_municipality_id = fields.Char("Municipio Postal (Privado)", tracking=True, groups="hr.group_hr_user",
                                                 help="Campo mantenido por compatibilidad con vistas. Funcionalidad original eliminada.")

    # --- Métodos de Nombre (Mantenidos y Refinados) ---

    @api.onchange('private_surname', 'private_second_surname', 'private_first_name', 'private_other_names')
    def _inverse_names(self):
        """Actualiza el campo 'name' estándar basado en los campos estructurados."""
        for rec in self:
            rec.name = self._calculate_name(
                rec.private_surname,
                rec.private_second_surname,
                rec.private_first_name,
                rec.private_other_names
            )

    @api.model
    def _calculate_name(self, surname, second_surname, first_name, other_names):
        """Construye el nombre completo en el formato Apellido1 Apellido2, Nombre1 Nombre2."""
        parts = []
        surname_part = []
        if surname:
            surname_part.append(surname.strip())
        if second_surname:
            surname_part.append(second_surname.strip())
        if surname_part:
            parts.append(' '.join(surname_part))

        name_part = []
        if first_name:
            name_part.append(first_name.strip())
        if other_names:
            name_part.append(other_names.strip())

        if parts and name_part:
            parts.append(',')
            parts.append(' '.join(name_part))
        elif name_part:
            parts.append(' '.join(name_part))

        return ' '.join(parts).replace(' ,', ',')

    @api.depends('name')
    def _compute_names(self):
        """Intenta extraer partes estructuradas si se modifica el campo 'name' directamente."""
        for rec in self:
            if rec.name and not (rec.private_first_name or rec.private_other_names or rec.private_surname or rec.private_second_surname):
                parts = rec.name.split(',')
                surname_part = parts[0].strip() if len(parts) > 0 else ''
                name_part = parts[1].strip() if len(parts) > 1 else (
                    '' if len(parts) > 0 else rec.name.strip())

                surnames = surname_part.split()
                names = name_part.split()

                if len(parts) > 1:
                    rec.private_surname = surnames[0] if surnames else ''
                    rec.private_second_surname = ' '.join(
                        surnames[1:]) if len(surnames) > 1 else ''
                    rec.private_first_name = names[0] if names else ''
                    rec.private_other_names = ' '.join(
                        names[1:]) if len(names) > 1 else ''
                elif len(names) > 0:
                    rec.private_first_name = names[0]
                    rec.private_other_names = ''
                    rec.private_surname = names[1] if len(names) > 1 else ''
                    rec.private_second_surname = ' '.join(
                        names[2:]) if len(names) > 2 else ''
                else:
                    rec.private_first_name = rec.name
                    rec.private_other_names = ''
                    rec.private_surname = ''
                    rec.private_second_surname = ''
            elif not rec.name:
                rec.private_first_name = False
                rec.private_other_names = False
                rec.private_surname = False
                rec.private_second_surname = False

    # --- Método Postal (Eliminado) ---
    # El método _compute_private_postal original dependía de modelos de l10n_co_edi_inencon
    # y de campos como private_zip/private_country_id que no están aquí.
    # @api.depends('private_zip', 'private_country_id')
    # def _compute_private_postal(self): # ELIMINADO
    #     ...
