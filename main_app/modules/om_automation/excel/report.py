# ==========================================
# OM Automation V2
# excel/report.py
# ==========================================

import os
from datetime import datetime

from openpyxl import Workbook

from modules.om_automation.config import OUTPUT_DIR, REPORT_COLUMNS
from modules.om_automation.excel.writer import ExcelWriter
from modules.om_automation.excel.formatter import formatter


class ReportManager:

    def __init__(self):
        self.writer = ExcelWriter()

    # -----------------------------------------

    def timestamp(self):
        return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # -----------------------------------------

    def ensure_output(self):
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    # -----------------------------------------

    def summary(self, success, failed, total, seconds):

        percentage = 0

        if total > 0:
            percentage = round(success * 100 / total, 2)

        return {
            "Date": datetime.now().strftime("%d-%m-%Y"),
            "Time": datetime.now().strftime("%H:%M:%S"),
            "Total": total,
            "Success": success,
            "Failed": failed,
            "Success Rate (%)": percentage,
            "Duration (s)": round(seconds, 2)
        }

    # -----------------------------------------

    def _ordered(self, rows):
        """
        Reindex each row dict so every sheet shares the same
        column order (config.REPORT_COLUMNS), while still
        keeping any extra keys a row might carry (e.g. "Error").
        """

        ordered_rows = []

        for row in rows:
            ordered = {col: row.get(col, "") for col in REPORT_COLUMNS}
            ordered_rows.append(ordered)

        return ordered_rows

    # -----------------------------------------

    def generate(self, success_rows, error_rows, seconds, filename=None):
        """
        Builds the final workbook with three sheets:
        Success Report, Error Report, Summary.

        Returns the full path to the saved .xlsx file.
        """

        self.ensure_output()

        total = len(success_rows) + len(error_rows)

        summary_data = self.summary(
            success=len(success_rows),
            failed=len(error_rows),
            total=total,
            seconds=seconds
        )

        wb = Workbook()

        # openpyxl creates a default blank sheet - remove it,
        # our named sheets are added via write_sheet().
        default_sheet = wb.active
        wb.remove(default_sheet)

        if success_rows:
            self.writer.write_sheet(
                wb,
                "Success Report",
                self._ordered(success_rows),
                fill=formatter.success_fill
            )

        if error_rows:
            self.writer.write_sheet(
                wb,
                "Error Report",
                self._ordered(error_rows),
                fill=formatter.error_fill
            )

        self.writer.write_sheet(
            wb,
            "Summary",
            [summary_data]
        )

        if filename is None:
            filename = f"OM_Report_{self.timestamp()}.xlsx"

        output_path = os.path.join(OUTPUT_DIR, filename)
        wb.save(output_path)

        return output_path
