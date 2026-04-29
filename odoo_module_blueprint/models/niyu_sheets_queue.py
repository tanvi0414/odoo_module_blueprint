from collections import defaultdict
import json
from datetime import date, datetime

from odoo import api, fields, models


class NiyuSheetsQueue(models.Model):
    _name = "niyu.sheets.queue"
    _description = "Niyu Google Sheets Sync Queue"
    _order = "create_date asc"

    mapping_id = fields.Many2one(
        "niyu.sheets.mapping",
        required=True,
        ondelete="cascade",
    )

    model_name = fields.Char(required=True)
    record_id = fields.Integer(required=True, index=True)
    reason = fields.Char(default="write")

    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("done", "Done"),
            ("error", "Error"),
        ],
        default="pending",
        index=True,
    )

    attempt_count = fields.Integer(default=0)
    last_error = fields.Text()

    @api.model
    def enqueue(self, mapping, record_ids, reason="write"):
        rows = []

        for record_id in set(record_ids):
            rows.append({
                "mapping_id": mapping.id,
                "model_name": mapping.model_name,
                "record_id": record_id,
                "reason": reason,
                "state": "pending",
            })

        return self.create(rows) if rows else self.browse()

    @api.model
    def cron_process_queue(self, limit=250, queue_ids=None):
        domain = [("state", "=", "pending")]

        if queue_ids:
            domain.append(("id", "in", queue_ids))

        pending = self.search(domain, limit=limit)

        grouped = defaultdict(lambda: self.browse())

        for item in pending:
            grouped[item.mapping_id.id] |= item

        for mapping_id, queue_items in grouped.items():
            mapping = queue_items[0].mapping_id

            try:
                record_ids = queue_items.mapped("record_id")
                self._push_records_to_google(mapping, record_ids)

                queue_items.write({
                    "state": "done",
                    "last_error": False,
                })

                mapping.write({
                    "last_success_at": fields.Datetime.now(),
                    "last_error": False,
                })

                self._create_sync_logs(
                    mapping=mapping,
                    queue_items=queue_items,
                    status="success",
                    message="Record sent to Google Sheets.",
                )

            except Exception as exc:
                error_message = str(exc)

                queue_items.write({
                    "state": "error",
                    "attempt_count": queue_items[0].attempt_count + 1,
                    "last_error": error_message,
                })

                mapping.write({
                    "last_error": error_message,
                })

                self._create_sync_logs(
                    mapping=mapping,
                    queue_items=queue_items,
                    status="error",
                    message=error_message,
                )

    def _create_sync_logs(self, mapping, queue_items, status, message):
        log_vals = []

        for item in queue_items:
            log_vals.append({
                "direction": "odoo_to_sheet",
                "mapping_id": mapping.id,
                "model_name": item.model_name,
                "record_id": item.record_id,
                "status": status,
                "message": message,
            })

        if log_vals:
            self.env["niyu.sheets.log"].sudo().create(log_vals)

    def _get_sheets_service(self, connection):
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError:
            raise ValueError(
                "Google API libraries are not installed inside the Odoo Docker container. "
                "Install google-api-python-client and google-auth."
            )

        if not connection.service_account_json:
            raise ValueError("Missing Google service account JSON on the connection.")

        try:
            info = json.loads(connection.service_account_json)
        except Exception:
            raise ValueError("Invalid service account JSON. Paste the full JSON file content.")

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=scopes,
        )

        return build(
            "sheets",
            "v4",
            credentials=credentials,
            cache_discovery=False,
        )

    def _ensure_sheet_exists(self, service, spreadsheet_id, sheet_name):
        spreadsheet = service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
        ).execute()

        existing_sheets = [
            sheet["properties"]["title"]
            for sheet in spreadsheet.get("sheets", [])
        ]

        if sheet_name in existing_sheets:
            return True

        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": sheet_name,
                            }
                        }
                    }
                ]
            },
        ).execute()

        return True

    def _sheet_range(self, sheet_name, cell_range):
        safe_sheet_name = sheet_name.replace("'", "''")
        return "'%s'!%s" % (safe_sheet_name, cell_range)

    def _convert_value_for_sheet(self, value):
        if value is False or value is None:
            return ""

        if isinstance(value, models.BaseModel):
            if not value:
                return ""

            if len(value) == 1:
                return value.display_name or ""

            return ", ".join(value.mapped("display_name"))

        if isinstance(value, (datetime, date)):
            return value.isoformat()

        return str(value)

    def _push_records_to_google(self, mapping, record_ids):
        if not mapping.spreadsheet_id:
            raise ValueError("Missing spreadsheet ID on mapping.")

        if not mapping.sheet_name:
            raise ValueError("Missing sheet name on mapping.")

        if not mapping.field_line_ids:
            raise ValueError("No field mappings found.")

        service = self._get_sheets_service(mapping.connection_id)

        self._ensure_sheet_exists(
            service=service,
            spreadsheet_id=mapping.spreadsheet_id,
            sheet_name=mapping.sheet_name,
        )

        records = self.env[mapping.model_name].sudo().browse(record_ids).exists()

        if not records:
            return True

        field_lines = mapping.field_line_ids.sorted("sequence")

        headers = ["__odoo_id"]
        headers += [
            line.column_label or line.field_name or "Column"
            for line in field_lines
        ]

        rows = [headers]

        for record in records:
            row = [record.id]

            for line in field_lines:
                field_name = line.field_name

                if not field_name:
                    row.append("")
                    continue

                if field_name not in record._fields:
                    row.append("")
                    continue

                value = record[field_name]
                row.append(self._convert_value_for_sheet(value))

            rows.append(row)

        clear_range = self._sheet_range(mapping.sheet_name, "A:Z")
        target_range = self._sheet_range(mapping.sheet_name, "A1")

        service.spreadsheets().values().clear(
            spreadsheetId=mapping.spreadsheet_id,
            range=clear_range,
            body={},
        ).execute()

        service.spreadsheets().values().update(
            spreadsheetId=mapping.spreadsheet_id,
            range=target_range,
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()

        return True