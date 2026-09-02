# ==========================================
# OM Automation V2
# web/jobs.py
#
# In-memory background job manager. A "job" is one
# Excel batch run (CN / GST / Party / Master). The
# browser starts a job, then polls /api/excel/status/<id>
# for progress + log lines, since a plain HTTP request/
# response can't stream a live progress bar on its own.
# ==========================================

import threading
import time
import uuid

from modules.om_automation.excel.report import ReportManager


class Job:

    def __init__(self, job_id, runner, file_path):
        self.job_id = job_id
        self.runner = runner
        self.file_path = file_path

        self.stop_event = threading.Event()
        self.status = "running"  # running | done | error | stopped
        self.current = 0
        self.total = 0
        self.log = []
        self.output_path = None
        self.output_filename = None
        self.error = None

        self.lock = threading.Lock()

    def add_log(self, message):
        with self.lock:
            self.log.append(message)
            # keep memory bounded for very large batches
            if len(self.log) > 2000:
                self.log = self.log[-2000:]

    def set_progress(self, current, total):
        with self.lock:
            self.current = current
            self.total = total

    def snapshot(self, log_from=0):
        with self.lock:
            return {
                "status": self.status,
                "current": self.current,
                "total": self.total,
                "log": self.log[log_from:],
                "log_count": len(self.log),
                "output_filename": self.output_filename,
                "error": self.error
            }


class JobManager:

    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()

    def start(self, runner, file_path):

        job_id = uuid.uuid4().hex
        job = Job(job_id, runner, file_path)

        with self.lock:
            self.jobs[job_id] = job

        thread = threading.Thread(
            target=self._run, args=(job,), daemon=True
        )
        thread.start()

        return job_id

    def _run(self, job):

        start_time = time.time()

        def progress_cb(current, total):
            job.set_progress(current, total)

        def log_cb(message):
            job.add_log(message)

        try:
            success_rows, error_rows = job.runner(
                job.file_path, progress_cb, log_cb, job.stop_event
            )

            seconds = time.time() - start_time
            report = ReportManager()
            output_path = report.generate(success_rows, error_rows, seconds)

            import os
            job.output_path = output_path
            job.output_filename = os.path.basename(output_path)

            job.add_log(
                f"Done. Success: {len(success_rows)} | Failed: {len(error_rows)}"
            )

            job.status = "stopped" if job.stop_event.is_set() else "done"

        except Exception as e:
            job.error = str(e)
            job.add_log(f"Error: {e}")
            job.status = "error"

    def get(self, job_id):
        with self.lock:
            return self.jobs.get(job_id)

    def stop(self, job_id):
        job = self.get(job_id)
        if job:
            job.stop_event.set()


job_manager = JobManager()
