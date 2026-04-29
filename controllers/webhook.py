import json
from odoo import http, fields
from odoo.http import request


class NiyuSheetsWebhook(http.Controller):

    @http.route('/niyu_sheets/webhook/edit', type='json', auth='public', methods=['POST'], csrf=False)
    def sheet_edit_webhook(self, **payload):
        auth = request.httprequest.headers.get('Authorization', '')
        token = auth.replace('Bearer ', '').strip()
        mapping_key = payload.get('mapping_key')

        mapping = request.env['niyu.sheets.mapping'].sudo().search([
            ('key', '=', mapping_key),
            ('connection_id.webhook_token', '=', token),
            ('active', '=', True),
        ], limit=1)
        if not mapping:
            return {'ok': False, 'error': 'Invalid token or mapping'}

        if mapping.sync_direction != 'two_way':
            self._log(mapping, payload, 'sheet_to_odoo', 'skipped', 'Writeback is disabled')
            return {'ok': False, 'error': 'Writeback is disabled for this mapping'}

        try:
            result = self._apply_sheet_row_to_odoo(mapping, payload)
            self._log(mapping, payload, 'sheet_to_odoo', 'success', result)
            return {'ok': True, 'message': result}
        except Exception as exc:
            self._log(mapping, payload, 'sheet_to_odoo', 'error', str(exc))
            return {'ok': False, 'error': str(exc)}

    def _apply_sheet_row_to_odoo(self, mapping, payload):
        headers = payload.get('headers') or []
        row_values = payload.get('row_values') or []
        row = dict(zip(headers, row_values))

        record_id = row.get('__odoo_id')
        if not record_id:
            return 'Skipped: row has no __odoo_id'

        record = request.env[mapping.model_name].sudo().browse(int(record_id)).exists()
        if not record:
            return 'Skipped: Odoo record no longer exists'

        vals = {}
        for line in mapping.field_line_ids:
            if not line.writeback_allowed:
                continue
            if line.column_label not in row:
                continue
            vals[line.field_name] = row.get(line.column_label)

        if vals:
            record.write(vals)
        return 'Updated %s,%s fields=%s' % (mapping.model_name, record.id, ','.join(vals.keys()))

    def _log(self, mapping, payload, direction, status, message):
        request.env['niyu.sheets.log'].sudo().create({
            'mapping_id': mapping.id,
            'direction': direction,
            'model_name': mapping.model_name,
            'sheet_name': payload.get('sheet_name'),
            'edited_range': payload.get('edited_a1'),
            'status': status,
            'message': message,
            'payload': json.dumps(payload, default=str),
        })
