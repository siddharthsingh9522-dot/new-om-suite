# ==========================================
# OM Automation V2
# core/worker.py
# ==========================================

import time
import threading
import traceback

from modules.om_automation.core.processor import Processor
from modules.om_automation.excel.report import ReportManager


class WorkerControl:
    """
    Shared between the Worker's background thread and
    Processor.process_file so pause/stop requests from the
    GUI can take effect between records.
    """

    def __init__(self):
        self.pause_event = threading.Event()
        self.pause_event.set()  # set = running, cleared = paused
        self.stop_event = threading.Event()

    def pause(self):
        self.pause_event.clear()

    def resume(self):
        self.pause_event.set()

    def stop(self):
        self.stop_event.set()
        self.pause_event.set()  # unblock if currently paused

    def reset(self):
        self.pause_event.set()
        self.stop_event.clear()

    def wait_if_paused(self):
        self.pause_event.wait()

    def should_stop(self):
        return self.stop_event.is_set()


class Worker:

    def __init__(self):
        self.processor = Processor()
        self.report_manager = ReportManager()
        self.control = WorkerControl()

        self.thread = None
        self.running = False

    # ----------------------------------

    def start(
        self,
        excel_file,
        progress_callback=None,
        log_callback=None,
        finish_callback=None
    ):

        if self.running:
            return

        self.running = True
        self.control.reset()
        self.processor = Processor()

        self.thread = threading.Thread(
            target=self._run,
            args=(
                excel_file,
                progress_callback,
                log_callback,
                finish_callback
            ),
            daemon=True
        )

        self.thread.start()

    # ----------------------------------

    def _run(
        self,
        excel_file,
        progress_callback,
        log_callback,
        finish_callback
    ):

        start_time = time.time()

        try:
            result = self.processor.process_file(
                excel_file,
                progress=progress_callback,
                logger=log_callback,
                control=self.control
            )

            seconds = time.time() - start_time

            output_path = self.report_manager.generate(
                result["success"],
                result["errors"],
                seconds
            )

            if finish_callback:
                finish_callback({
                    "success": True,
                    "summary": result["summary"],
                    "output_path": output_path,
                    "stopped": self.control.should_stop()
                })

        except Exception as e:
            traceback.print_exc()

            if finish_callback:
                finish_callback({
                    "success": False,
                    "error": str(e)
                })

        finally:
            self.running = False

    # ----------------------------------

    def pause(self):
        self.control.pause()

    def resume(self):
        self.control.resume()

    def stop(self):
        self.control.stop()


worker = Worker()
