"""Generic background-worker infrastructure.

Every long-running operation in the app (scans, cleans, package cache
sizing, process listing) MUST run through FunctionWorker rather than being
called directly from a UI event handler. This is the one mechanism that
guarantees "never freeze the UI" instead of that being a hope per-caller.

Usage:
    worker = FunctionWorker(cache_scanner.scan_known_cache_locations)
    worker.signals.finished.connect(on_result)
    worker.signals.error.connect(on_error)
    worker.signals.progress.connect(on_progress)
    QThreadPool.globalInstance().start(worker)
"""
from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot


class WorkerSignals(QObject):
    started = pyqtSignal()
    finished = pyqtSignal(object)      # the function's return value
    error = pyqtSignal(str)            # formatted traceback
    progress = pyqtSignal(str)         # free-text progress message


class FunctionWorker(QRunnable):
    """Wrap any callable so it runs on QThreadPool instead of the UI thread.

    If the callable accepts a `should_stop` and/or `progress_cb` keyword
    argument, they are supplied automatically so scanners/cleaners get
    cancellation and live progress for free.
    """

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self._stop_requested = False

        import inspect
        params = inspect.signature(fn).parameters
        if "should_stop" in params and "should_stop" not in kwargs:
            self.kwargs["should_stop"] = lambda: self._stop_requested
        if "progress_cb" in params and "progress_cb" not in kwargs:
            self.kwargs["progress_cb"] = lambda msg: self.signals.progress.emit(str(msg))

    def request_stop(self) -> None:
        self._stop_requested = True

    @pyqtSlot()
    def run(self) -> None:
        self.signals.started.emit()
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception:  # noqa: BLE001 - we deliberately catch everything here
            self.signals.error.emit(traceback.format_exc())
            return
        self.signals.finished.emit(result)


class PollingWorker(QRunnable):
    """Repeatedly calls `fn` every `interval_ms`, emitting each result.

    Used for the Dashboard's live metrics and the Process tab's live
    refresh, both of which need to keep running until explicitly stopped
    rather than completing once.
    """

    def __init__(self, fn: Callable[[], Any], interval_ms: int = 1000) -> None:
        super().__init__()
        self.fn = fn
        self.interval_ms = interval_ms
        self.signals = WorkerSignals()
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    @pyqtSlot()
    def run(self) -> None:
        from PyQt6.QtCore import QThread

        self.signals.started.emit()
        while not self._stop_requested:
            try:
                result = self.fn()
            except Exception:  # noqa: BLE001
                self.signals.error.emit(traceback.format_exc())
                return
            self.signals.finished.emit(result)
            QThread.msleep(self.interval_ms)
