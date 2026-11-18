"""Background task that runs a plain function without freezing QGIS."""
from qgis.core import QgsTask
from qgis.PyQt.QtCore import pyqtSignal


class FuncTask(QgsTask):
    message = pyqtSignal(str)

    def __init__(self, title, func, on_done):
        super().__init__(title, QgsTask.Flag.CanCancel)
        self.func = func            # func(task) -> result ; may call task.isCanceled()
        self.on_done = on_done      # on_done(task, ok)
        self.result = None
        self.error = None

    def run(self):
        try:
            self.result = self.func(self)
        except Exception as exc:  # reported to the user in finished()
            self.error = str(exc)
            return False
        return not self.isCanceled()

    def finished(self, ok):  # main thread
        self.on_done(self, ok)
