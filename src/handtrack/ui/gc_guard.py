"""Run Python's garbage collector on the GUI thread only.

Automatic collection runs in whichever thread happens to allocate when a
threshold is crossed: the model loader, the video engine, the camera reader.
If the garbage holds Qt objects (a widget caught in a reference cycle with a
lambda, a pixmap), their C++ destructors then run on that worker thread while
the GUI thread paints, which crashes the process (an access violation was
caught this way: GC on the "Startup" thread while the splash painted).

So automatic collection is switched off and this timer collects on the GUI
thread instead, using the same per-generation thresholds. Checking the counts
costs nothing; worker threads also no longer pause for collections.
"""

import gc

from PySide6.QtCore import QObject, QTimer


class GuiThreadGC(QObject):
    INTERVAL_MS = 500

    def __init__(self, parent=None):
        super().__init__(parent)
        gc.disable()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check)
        self._timer.start(self.INTERVAL_MS)

    @staticmethod
    def check():
        c0, c1, c2 = gc.get_count()
        t0, t1, t2 = gc.get_threshold()
        if c0 > t0:
            gen = 0
            if c1 > t1:
                gen = 1
                if c2 > t2:
                    gen = 2
            gc.collect(gen)
