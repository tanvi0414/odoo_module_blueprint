import json

from odoo import fields, models, _
from odoo.exceptions import UserError


class NiyuSheetsMapping(models.Model):
    _name = "niyu.sheets.mapping"
    _description = "Niyu Google Sheets Mapping"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    key = fields.Char(required=True, copy=False, index=True)

    connection_id = fields.Many2one(
        "niyu.sheets.connection",
        required=True,
        ondelete="cascade",
        tracking=True,
    )

    model_id = fields.Many2one(
        "ir.model",
        required=True,
        ondelete="cascade",
        tracking=True,
    )

    model_name = fields.Char(
        related="model_id.model",
        store=True,
        readonly=True,
    )

    domain = fields.Char(default="[]")

    spreadsheet_id = fields.Char(required=True)
    sheet_name = fields.Char(required=True, default="Odoo Data")

    sync_direction = fields.Selection(
        [
            ("odoo_to_sheet", "Odoo to Google Sheets"),
            ("two_way", "Two-way Sync"),
        ],
        default="odoo_to_sheet",
        required=True,
    )

    conflict_policy = fields.Selection(
        [
            ("odoo_wins", "Odoo Wins"),
            ("sheet_wins", "Sheet Wins"),
            ("review", "Send to Review Queue"),
        ],
        default="review",
        required=True,
    )

    realtime_enabled = fields.Boolean(default=True)
    active = fields.Boolean(default=True)

    last_success_at = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)

    field_line_ids = fields.One2many(
        "niyu.sheets.mapping.field",
        "mapping_id",
    )

    def _safe_domain(self):
        self.ensure_one()

        try:
            domain = json.loads(self.domain or "[]")
        except Exception:
            raise UserError(_("Invalid JSON domain. Use [] for all records."))

        if not isinstance(domain, list):
            raise UserError(_("Domain must be a JSON list. Example: []"))

        return domain

    def action_enqueue_full_sync(self):
        for rec in self:
            if not rec.model_name:
                raise UserError(_("Please select an Odoo model first."))

            if not rec.connection_id:
                raise UserError(_("Please select a Google Sheets connection."))

            if not rec.spreadsheet_id:
                raise UserError(_("Please enter the Google Spreadsheet ID."))

            if not rec.sheet_name:
                raise UserError(_("Please enter the Google Sheet tab name."))

            if not rec.field_line_ids:
                raise UserError(_("Please add at least one field mapping line."))

            model = self.env[rec.model_name].sudo()
            records = model.search(rec._safe_domain())

            if not records:
                raise UserError(_("No records found for this mapping/domain."))

            queue_model = self.env["niyu.sheets.queue"].sudo()

            queue_records = queue_model.enqueue(
                mapping=rec,
                record_ids=records.ids,
                reason="manual_sync",
            )

            queue_model.cron_process_queue(
                limit=max(len(records), 1000),
                queue_ids=queue_records.ids,
            )

            error_queue = queue_records.filtered(lambda q: q.state == "error")
            if error_queue:
                raise UserError(error_queue[0].last_error or _("Google Sheets sync failed."))

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Google Sheets Sync Complete"),
                    "message": _("%s records sent to Google Sheets.") % len(records),
                    "type": "success",
                    "sticky": False,
                },
            }

    def action_enqueue_changed_record(self, record_id, reason="write"):
        self.ensure_one()

        queue_records = self.env["niyu.sheets.queue"].sudo().enqueue(
            mapping=self,
            record_ids=[record_id],
            reason=reason,
        )

        self.env["niyu.sheets.queue"].sudo().cron_process_queue(
            limit=1000,
            queue_ids=queue_records.ids,
        )

        return queue_records


class NiyuSheetsMappingField(models.Model):
    _name = "niyu.sheets.mapping.field"
    _description = "Niyu Google Sheets Mapping Field"
    _order = "sequence, id"

    mapping_id = fields.Many2one(
        "niyu.sheets.mapping",
        required=True,
        ondelete="cascade",
    )

    sequence = fields.Integer(default=10)

    field_id = fields.Many2one(
        "ir.model.fields",
        string="Odoo Field",
        required=True,
        ondelete="cascade",
        domain="[('model_id', '=', parent.model_id)]",
    )

    field_name = fields.Char(
        related="field_id.name",
        store=True,
        readonly=True,
    )

    column_label = fields.Char(required=True)
    writeback_allowed = fields.Boolean(default=False)
    required_for_writeback = fields.Boolean(default=False)

    lookup_field = fields.Char(
        help="For many2one fields, use this field to resolve values, e.g. name or default_code."
    )