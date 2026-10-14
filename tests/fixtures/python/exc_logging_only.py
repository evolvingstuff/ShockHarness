import logging
import sys
import traceback
import warnings

log = logging.getLogger(__name__)


class Service:
    def __init__(self):
        self.logger = logging.getLogger("svc")

    def run(self):
        try:
            self.work()
        except OSError as exc:
            self.logger.exception("work failed: %s", exc)

    def run_module_logger(self):
        try:
            self.work()
        except OSError as exc:
            log.warning("work failed: %s", exc)
            pass

    def run_print(self):
        try:
            self.work()
        except OSError as exc:
            print("work failed", exc, file=sys.stderr)

    def run_traceback(self):
        try:
            self.work()
        except OSError:
            traceback.print_exc()

    def run_warn(self):
        try:
            self.work()
        except OSError as exc:
            warnings.warn(str(exc))

    def run_then_act(self):
        try:
            self.work()
        except OSError as exc:
            log.warning("work failed: %s", exc)
            self.retry()
