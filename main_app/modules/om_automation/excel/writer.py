# ==========================================
# OM Automation V2
# excel/writer.py
# ==========================================

from modules.om_automation.excel.formatter import formatter


class ExcelWriter:
    """
    Owns worksheet structure (headers + rows).
    Delegates all visual styling to excel.formatter.formatter.
    """

    def __init__(self):
        self.formatter = formatter

    def write_sheet(self, workbook, sheet_name, data, fill=None):

        ws = workbook.create_sheet(sheet_name)

        if len(data) == 0:
            return ws

        headers = list(data[0].keys())
        ws.append(headers)

        self.formatter.format_header(ws)

        for row in data:
            ws.append([row.get(h) for h in headers])

        self.formatter.format_data_borders(ws)

        if fill:
            self.formatter.apply_fill(ws, fill)
        else:
            self.formatter.alternate_rows(ws)

        self.formatter.auto_width(ws)

        return ws
