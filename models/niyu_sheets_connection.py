import json
import secrets
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class NiyuSheetsConnection(models.Model):
    _name = "niyu.sheets.connection"
    _description = "Niyu Google Sheets Connection"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, default="Google Sheets Connection", tracking=True)
    active = fields.Boolean(default=True)
    auth_mode = fields.Selection([
        ("service_account", "Service Account"),
        ("oauth", "Google OAuth")
    ], default="service_account", required=True)
    service_account_json = fields.Text(string="Service Account JSON", groups="odoo_module_blueprint.group_sheets_manager")
    service_account_email = fields.Char(readonly=True)
    webhook_token = fields.Char(readonly=True, copy=False, groups="odoo_module_blueprint.group_sheets_manager")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    state = fields.Selection([
        ("draft", "Draft"),
        ("connected", "Connected"),
        ("error", "Error")
    ], default="draft", tracking=True)
    last_test_message = fields.Text(readonly=True)

    def action_generate_token(self):
        for rec in self:
            rec.webhook_token = secrets.token_urlsafe(32)

    def action_parse_service_account(self):
        for rec in self:
            if not rec.service_account_json:
                raise UserError(_("Upload/paste the service account JSON first."))
            try:
                data = json.loads(rec.service_account_json)
            except Exception as exc:
                raise UserError(_("Invalid service account JSON: %s") % exc)
            rec.service_account_email = data.get("client_email")
            if not rec.webhook_token:
                rec.action_generate_token()
            rec.state = "connected"
            rec.last_test_message = _("Credential parsed. Share your Google Sheet with: %s") % rec.service_account_email

    def action_test_connection(self):
        # Production version should instantiate google.oauth2.service_account.Credentials
        # and call Drive/Sheets API. Keep this skeleton safe for module planning.
        for rec in self:
            if not rec.service_account_email:
                raise UserError(_("Parse the service account JSON first."))
            rec.state = "connected"
            rec.last_test_message = _("Connection configuration looks valid.")
