# -*- coding: utf-8 -*-

from odoo import api, models, _
from odoo.exceptions import UserError
import logging
from hashlib import sha384
from lxml import etree

try:
    import zeep
    from zeep.transports import Transport
except ImportError:
    _logger = logging.getLogger(__name__)
    _logger.warning("La librería 'zeep' no está instalada.")
    zeep = None

_logger = logging.getLogger(__name__)


class AccountEdiXmlUblDianPatch(models.AbstractModel):
    _inherit = 'account.edi.xml.ubl_dian'

    # --- Sobrescritura para _dian_get_security_code (ya la tienes, se mantiene) ---
    def _dian_get_security_code(self, invoice, operation_mode):
        """
        SOBRESCRITO para manejar el TypeError en l10n_co_dian al calcular
        el SoftwareSecurityCode, asegurando que los operandos sean cadenas.
        Se priorizan los campos de nómina electrónica (edi_payroll_id, edi_payroll_pin).
        """
        company = invoice.company_id
        is_payroll_document = getattr(
            invoice, 'is_payroll_document_proxy', False)

        if is_payroll_document:
            _logger.info(
                "PATCH: Documento identificado como Nómina. Usando edi_payroll_id y edi_payroll_pin de la compañía.")
            software_id = str(getattr(company, 'edi_payroll_id', ''))
            software_pin = str(getattr(company, 'edi_payroll_pin', ''))

            _logger.warning(
                "PIN LEÍDO DEL SISTEMA PARA CÁLCULO DE SC: %s", software_pin)

            if not software_id:
                raise UserError(
                    _("El 'Software ID' para Nómina Electrónica no está configurado en la compañía."))
            if not software_pin:
                raise UserError(
                    _("El 'Software PIN' para Nómina Electrónica no está configurado en la compañía."))

            concatenated_for_sc = software_id + software_pin
            software_security_code = sha384(
                concatenated_for_sc.encode('utf-8')).hexdigest()

            _logger.debug(
                f"PATCH: SoftwareSecurityCode calculado para Nómina: {software_security_code}")
            return software_security_code
        else:
            _logger.info(
                "PATCH: Documento no es Nómina. Llamando a super()._dian_get_security_code.")
            try:
                return super(AccountEdiXmlUblDianPatch, self)._dian_get_security_code(invoice, operation_mode)
            except TypeError as e:
                _logger.error(
                    f"PATCH ERROR: super()._dian_get_security_code falló para documento no-nómina: {e}")
                raise UserError(
                    _("Error al calcular el código de seguridad para documento electrónico. Por favor, contacte a soporte."))

    # --- NUEVA SOBRESCRITURA para _dian_get_qr_code_url ---
    def _dian_get_qr_code_url(self, invoice, identifier_from_xml):
        """
        SOBRESCRITO para asegurar que el 'identifier' (UUID/CUNE) sea siempre un string
        antes de concatenarlo a la URL base del QR, evitando TypeError.
        """
        company = invoice.company_id

        # Obtener la URL base del QR de la configuración de la compañía
        qr_url_base = getattr(company, 'l10n_co_edi_qr_code_url', False)
        if not qr_url_base:
            # Si no está configurada, usar la URL por defecto de la DIAN
            _logger.warning(
                "PATCH: URL base del QR para Nómina Electrónica no configurada en la compañía. Usando URL por defecto.")
            qr_url_base = "https://catalogo-vpfe.dian.gov.co/document/searchqr?documentkey="

        # Asegurar que el 'identifier_from_xml' (el CUNE) sea siempre un string,
        # incluso si root.findtext() devolvió None (significa que no lo encontró en el XML).
        clean_identifier = str(identifier_from_xml or '')

        if not clean_identifier:
            _logger.warning(
                "PATCH: No se pudo obtener el CUNE (UUID) del XML para generar la URL del QR. La URL del QR estará incompleta.")
            # Aquí puedes decidir si lanzar un error o devolver solo la URL base
            # Si es un CUNE obligatorio, un error podría ser preferible
            # raise UserError(_("No se pudo generar el código QR: El CUNE (UUID) no se encontró en el XML."))

        _logger.debug(
            f"PATCH: Generando URL QR con base '{qr_url_base}' y CUNE '{clean_identifier}'")
        return qr_url_base + clean_identifier


class ResCompanyDianPayrollPatch(models.Model):
    _inherit = 'res.company'

    def _get_l10n_co_dian_service(self, operation_mode):
        """
        SOBRESCRITO para Nómina Electrónica.
        Si es nómina, construye el cliente del servicio web manualmente.
        Si no, deja que la lógica original de l10n_co_dian funcione.
        """
        self.ensure_one()

        is_payroll_operation = self.env.context.get(
            'is_l10n_co_payroll', False)

        if is_payroll_operation:
            _logger.info(
                "PARCHE NÓMINA: Construyendo servicio DIAN manualmente para nómina.")
            if not zeep:
                raise UserError(
                    _("La librería 'zeep' es necesaria. Por favor, instálela (pip install zeep)."))

            if self.edi_payroll_is_not_test:
                wsdl_url = self.l10n_co_edi_payroll_wsdl_url_prod
            else:
                wsdl_url = self.l10n_co_edi_payroll_wsdl_url_test

            if not wsdl_url:
                raise UserError(
                    _("La URL del WSDL para Nómina Electrónica no está configurada."))

            # Usar edi_payroll_id y edi_payroll_pin como credenciales si se requieren
            software_id = self.edi_payroll_id
            software_pin = self.edi_payroll_pin

            if not software_id or not software_pin:
                raise UserError(
                    _("El Software ID o el PIN para Nómina Electrónica no están configurados en la compañía."))

            transport = Transport(timeout=30, operation_timeout=30)
            try:
                client = zeep.Client(wsdl_url, transport=transport)
                header = zeep.xsd.Element(
                    '{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd}Security',
                    zeep.xsd.ComplexType([
                        zeep.xsd.Attribute(
                            '{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd}mustUnderstand',
                            zeep.xsd.String()),
                        zeep.xsd.Element(
                            '{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd}UsernameToken',
                            zeep.xsd.ComplexType([
                                zeep.xsd.Element(
                                    '{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd}Username',
                                    zeep.xsd.String()),
                                zeep.xsd.Element(
                                    '{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd}Password',
                                    zeep.xsd.String()),
                            ])
                        ),
                    ])
                )
                header_value = header(
                    mustUnderstand='1',
                    UsernameToken={
                        'Username': software_id,
                        'Password': software_pin
                    }
                )
                return client.service, {'soapheaders': [header_value]}
            except Exception as e:
                raise UserError(
                    _("No se pudo conectar al servicio de la DIAN en la URL: %s. Error: %s") % (wsdl_url, e))
        else:
            return super(ResCompanyDianPayrollPatch, self)._get_l10n_co_dian_service(operation_mode)

# ===== FIN DEL NUEVO CÓDIGO A AÑADIR =====

    # Nota: Si l10n_co_dian.py usa super()._dian_get_qr_code_url,
    # asegúrate que tu super no cause un loop infinito o un problema si el método original
    # no espera que se le pase el identifier directamente.
    # En este caso, l10n_co_dian._dian_get_qr_code_url SI recibe el identifier.
