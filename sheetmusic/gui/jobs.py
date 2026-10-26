"""One background job at a time, with its results delivered in the GUI thread."""

from PySide6.QtCore import QObject, QThreadPool, Signal, Slot


class _Signals(QObject):
    progress = Signal(object)
    done = Signal(object)
    failed = Signal(object)


class _Relay(QObject):
    """Lives in the GUI thread, so signals emitted by the worker arrive queued here."""

    def __init__(self, on_progress, on_done, on_failed):
        super().__init__()
        self._p, self._d, self._f = on_progress, on_done, on_failed

    @Slot(object)
    def progress(self, v):
        if self._p:
            self._p(v)

    @Slot(object)
    def done(self, v):
        self._d(v)

    @Slot(object)
    def failed(self, e):
        self._f(e)


class Jobs(QObject):
    """One background job at a time. pdfium is not thread safe, so the GUI must not render
    previews while `busy`; `idle` fires when a job ends so the preview can resume."""
    idle = Signal()

    def __init__(self):
        super().__init__()
        self.busy = False
        self._keep: set = set()

    def run(self, fn, on_done, on_failed, on_progress=None) -> None:
        self.busy = True
        sig = _Signals()
        relay = _Relay(on_progress, lambda r: self._finish(on_done, r, sig, relay),
                       lambda e: self._finish(on_failed, e, sig, relay))
        sig.progress.connect(relay.progress)
        sig.done.connect(relay.done)
        sig.failed.connect(relay.failed)
        self._keep.add((sig, relay))

        def work():
            try:
                sig.done.emit(fn(sig.progress.emit))
            except Exception as exc:  # report every failure in the GUI
                sig.failed.emit(exc)
        QThreadPool.globalInstance().start(work)

    def _finish(self, cb, arg, sig, relay):
        self.busy = False
        self._keep.discard((sig, relay))
        cb(arg)
        self.idle.emit()
