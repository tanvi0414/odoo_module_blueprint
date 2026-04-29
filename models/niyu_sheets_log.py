from odoo import fields, models


class NiyuSheetsLog(models.Model):
    _name = "niyu.sheets.log"
    _description = "Niyu Google Sheets Sync Log"
    _order = "create_date desc"

    direction = fields.Selection(
        [
            ("odoo_to_sheet", "Odoo to Google Sheets"),
            ("sheet_to_odoo", "Google Sheets to Odoo"),
        ],
        string="Direction",
        required=True,
        default="odoo_to_sheet",
    )

    mapping_id = fields.Many2one(
        "niyu.sheets.mapping",
        string="Mapping",
        ondelete="set null",
    )

    model_name = fields.Char(string="Model Name")
    record_id = fields.Integer(string="Record ID")

    status = fields.Selection(
        [
            ("success", "Success"),
            ("error", "Error"),
            ("skipped", "Skipped"),
        ],
        string="Status",
        required=True,
        default="success",
    )

    message = fields.Text(string="Message")