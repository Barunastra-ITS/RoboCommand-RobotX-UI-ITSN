"""Runs blocking course device calls (``field_devices``) off the GUI thread.

Results come back on the GUI thread through queued signals. ``sync=True``
runs calls inline, for tests.
"""

from typing import Callable, Optional

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal

from robocommand_ui.field_devices import DeviceError

MAX_THREADS = 4


class _Signals(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)


class _Call(QRunnable):
    def __init__(self, fn, args, signals: _Signals):
        super().__init__()
        self._fn, self._args, self._signals = fn, args, signals

    def run(self):
        try:
            result = self._fn(*self._args)
        except DeviceError as e:
            self._emit("failed", str(e))
        except Exception as e:      # a device bug must not kill the worker silently
            self._emit("failed", f"{type(e).__name__}: {e}")
        else:
            self._emit("done", result)

    def _emit(self, name: str, value) -> None:
        try:
            getattr(self._signals, name).emit(value)
        except RuntimeError:        # the app quit while this call was in flight
            pass


class DeviceRunner(QObject):
    def __init__(self, parent=None, sync: bool = False):
        super().__init__(parent)
        self._sync = sync
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(MAX_THREADS)
        self._live = set()          # keeps signal objects alive until their call ends

    def call(self, fn, *args, on_done: Optional[Callable] = None,
             on_error: Optional[Callable[[str], None]] = None) -> None:
        signals = _Signals()
        self._live.add(signals)
        signals.done.connect(lambda result: self._finish(signals, on_done, result))
        signals.failed.connect(lambda err: self._finish(signals, on_error, err))
        job = _Call(fn, args, signals)
        if self._sync:
            job.run()
        else:
            self._pool.start(job)

    def _finish(self, signals, callback, value) -> None:
        self._live.discard(signals)
        if callback is not None:
            callback(value)

    def wait(self, msecs: int = 3000) -> None:
        self._pool.waitForDone(msecs)
