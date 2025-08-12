# l10n_co_nomina/models/payroll_api_connector.py
import requests
import base64
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class L10nCoPayrollApiConnector(models.AbstractModel):
    _name = 'l10n_co_nomina.payroll.api.connector'
    _description = 'Conector para API de Nómina Electrónica Factura Fácil'

    @api.model
    def _get_api_config(self):
        company = self.env.company
        api_url = company.l10n_co_payroll_api_url
        api_token = company.l10n_co_payroll_api_token
        if not api_url or not api_token:
            raise UserError(
                _("La URL o el Token de la API de Nómina no están configurados en la compañía."))
        return api_url, api_token

    @api.model
    def _send_api_request(self, endpoint, method='POST', json_data=None):
        api_url, api_token = self._get_api_config()
        full_url = f"{api_url.rstrip('/')}/api/ubl2.1/{endpoint}"

        headers = {
            'Authorization': f'Bearer {api_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        _logger.info("API Request: %s %s", method, full_url)
        _logger.debug("API JSON Data: %s", json_data)

        try:
            response = requests.request(
                method, full_url, headers=headers, json=json_data, timeout=90)
            if not response.ok: # Si el código no es 2xx
                if response.status_code == 422:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get('message', 'La API rechazó los datos.')
                        errors_dict = error_data.get('errors', {})
                        if errors_dict:
                            # Formatear los errores detallados
                            error_details = "; ".join(
                                [f"{campo}: {', '.join(mensajes)}" for campo, mensajes in errors_dict.items()]
                            )
                            error_msg = f"{error_msg} Detalles: {error_details}"
                        raise UserError(_("Error de Validación de la API (422): %s") % error_msg)
                    except ValueError: # Si la respuesta de error no es un JSON
                        raise UserError(_("Error de Validación de la API (422): %s") % response.text)
                else:
                    # Para otros errores HTTP (401, 404, 500, etc.)
                    response.raise_for_status()

            api_response = response.json()
            _logger.info("API Response (%s): %s", response.status_code, api_response)
            
            return api_response
            
        except requests.exceptions.HTTPError as e:
            _logger.error("Error HTTP de la API de Nómina: %s", e)
            raise UserError(_("La API devolvió un error: %s") % e)
        except requests.exceptions.Timeout:
            _logger.error("API request timed out.")
            raise UserError(_("La API de Nómina no respondió a tiempo."))
        except requests.exceptions.RequestException as e:
            _logger.error("Error de conexión con la API de Nómina: %s", e)
            raise UserError(_("No se pudo conectar con la API de Nómina: %s") % e)
        except ValueError:
            _logger.error("La respuesta de la API no es un JSON válido: %s", response.text)
            raise UserError(_("La API de Nómina devolvió una respuesta inválida."))

    @api.model
    def config_software_payroll(self, software_id, software_pin):
        """ Endpoint: PUT /api/ubl2.1/config/softwarepayroll """
        data = {
            "idpayroll": software_id,
            "pinpayroll": int(software_pin)  # El API espera un entero
        }
        return self._send_api_request("config/softwarepayroll", method='PUT', json_data=data)

    @api.model
    def config_certificate(self):
        """ Endpoint: PUT /api/ubl2.1/config/certificate """
        company = self.env.company
        if not company.l10n_co_payroll_certificate_file or not company.l10n_co_payroll_certificate_password:
            _logger.warning(
                "No se encontró certificado o contraseña para enviar a la API.")
            return

        certificate_b64 = company.l10n_co_payroll_certificate_file.decode(
            'utf-8')
        data = {
            "certificate": certificate_b64,
            "password": company.l10n_co_payroll_certificate_password
        }
        return self._send_api_request("config/certificate", method='PUT', json_data=data)

    @api.model
    def config_resolution_payroll(self, resolution_records):
        """
        Configura las resoluciones de nómina en la API.
        Endpoint: PUT /api/ubl2.1/config/resolution
        Itera sobre los registros del modelo l10n_co_nomina.resolution.
        """
        for res in resolution_records:
            data = {
                "type_document_id": int(res.type_document_id),
                "prefix": res.prefix,
                "from": res.from_number,
                "to": res.to_number,
            }
            # La Nómina Individual (9) puede tener más datos, la Nota de Ajuste (10) no.
            if res.type_document_id == '9':
                # El JSON de ejemplo de la API no muestra estos, pero los añadimos por si acaso
                # data.update({
                #     "resolution": res.resolution_number,
                #     "resolution_date": res.resolution_date.strftime('%Y-%m-%d') if res.resolution_date else None,
                # })
                pass  # Por ahora no se añaden campos extra que no están en los ejemplos de nómina de la API

            self._send_api_request("config/resolution",
                                   method='PUT', json_data=data)

        return True

    @api.model
    def send_payroll_document(self, payslip_record, test_set_id=None):
        """ Endpoint: POST /api/ubl2.1/payroll """
        payroll_json_data = payslip_record._prepare_payroll_json_data()
        endpoint = "payroll"
        if test_set_id:
            endpoint = f"payroll/{test_set_id}"

        api_response = self._send_api_request(
            endpoint, method='POST', json_data=payroll_json_data)

        if api_response:
            # La API devuelve 'cune' o 'zip_key' dependiendo del modo
            cune = api_response.get('cune') or api_response.get('zip_key')
            return cune, api_response
        return None, api_response

    # ... (resto de métodos como get_payroll_status, send_payroll_adjust_note_document, etc.) ...
