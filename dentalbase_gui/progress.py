"""Live progress window: shows each processing step as it happens, elapsed time and (optionally) the raw log.

Pure UI: it is fed lines from the backend's output by the main window; it never imports the backend."""
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout,
)

from . import theme

# plain-language explanation for each backend stage (keyed by stage number; the label itself comes from the backend)
STAGE_HELP = {
    1: 'Loading the STL file and cleaning up stray triangles.',
    2: 'Working out which way the teeth point (the occlusal plane).',
    3: 'Separating teeth from gums by their shape.',
    4: 'Drawing the cut line at your gingiva margin height.',
    5: 'Smoothing the cut line and blending it into the scan. The teeth are not touched.',
    6: 'Adding the straight wall and the flat base.',
    7: 'Saving the file and checking that it is watertight and the teeth are unchanged.',
}
STAGE_NAMES = {1: 'Reading the scan', 2: 'Finding the bite plane', 3: 'Finding the teeth', 4: 'Marking the trimline',
               5: 'Smoothing the trimline', 6: 'Building the base', 7: 'Saving and checking'}
PENDING, RUNNING, DONE, FAILED = range(4)
GLYPH = {PENDING: '○', RUNNING: '●', DONE: '✓', FAILED: '✕'}


class StepRow(QFrame):
    def __init__(self, text, help_text):
        super().__init__()
        lay = QHBoxLayout(self); lay.setContentsMargins(0, 4, 0, 4); lay.setSpacing(12)
        self.glyph = QLabel(GLYPH[PENDING]); self.glyph.setFixedWidth(22); self.glyph.setAlignment(Qt.AlignCenter)
        box = QVBoxLayout(); box.setSpacing(0)
        self.name = QLabel(text); self.name.setObjectName('settingName')
        self.help = QLabel(help_text); self.help.setObjectName('help'); self.help.setWordWrap(True)
        box.addWidget(self.name); box.addWidget(self.help)
        lay.addWidget(self.glyph); lay.addLayout(box, 1)
        self.set_state(PENDING)

    def set_state(self, state):
        color = {PENDING: '#a1a1a6', RUNNING: theme.ACCENT, DONE: theme.GOOD, FAILED: theme.BAD}[state]
        self.glyph.setText(GLYPH[state])
        self.glyph.setStyleSheet(f'color: {color}; font-size: 16px; font-weight: 700;')
        self.name.setStyleSheet('' if state != PENDING else f'color: {theme.SECONDARY};')


class ProgressDialog(QDialog):
    cancel_requested = Signal()
    open_folder_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Generating…')
        self.setMinimumWidth(560)
        self.setModal(False)
        self._t0 = time.time(); self._rows = []; self._n_stages = 0
        self._job_i = 0; self._job_n = 1; self._models_per_job = 1; self._model_i = 0; self._stage_i = 0
        lay = QVBoxLayout(self); lay.setContentsMargins(26, 22, 26, 20); lay.setSpacing(10)

        self.title = QLabel(''); self.title.setObjectName('stepTitle')
        self.sub = QLabel(''); self.sub.setObjectName('help'); self.sub.setWordWrap(True)
        lay.addWidget(self.title); lay.addWidget(self.sub)

        self.bar = QProgressBar(); self.bar.setRange(0, 1000); lay.addWidget(self.bar)
        self.lbl_time = QLabel('Elapsed 0:00'); self.lbl_time.setObjectName('help'); lay.addWidget(self.lbl_time)

        self.steps_box = QVBoxLayout(); self.steps_box.setSpacing(0)
        lay.addLayout(self.steps_box)

        self.summary = QLabel(''); self.summary.setWordWrap(True); self.summary.setVisible(False); lay.addWidget(self.summary)

        self.btn_details = QPushButton('Show details'); self.btn_details.setObjectName('link'); self.btn_details.setCheckable(True)
        self.btn_details.toggled.connect(self._toggle_details)
        lay.addWidget(self.btn_details, 0, Qt.AlignLeft)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(5000)
        self.log.setMinimumHeight(180); self.log.setVisible(False)
        lay.addWidget(self.log)

        row = QHBoxLayout(); row.addStretch(1)
        self.btn_open = QPushButton('Show in folder'); self.btn_open.setVisible(False)
        self.btn_open.clicked.connect(self.open_folder_requested)
        self.btn_cancel = QPushButton('Cancel'); self.btn_cancel.clicked.connect(self.cancel_requested)
        self.btn_close = QPushButton('Close'); self.btn_close.setObjectName('primary'); self.btn_close.setVisible(False)
        self.btn_close.clicked.connect(self.close)
        for b in (self.btn_open, self.btn_cancel, self.btn_close):
            row.addWidget(b)
        lay.addLayout(row)

        self._timer = QTimer(self); self._timer.timeout.connect(self._tick); self._timer.start(500)

    # ---------------------------------------------------------------- control
    def start(self, n_jobs):
        self._t0 = time.time(); self._job_n = max(1, n_jobs); self._job_i = -1
        self.log.clear(); self.summary.setVisible(False); self.summary.setText('')
        self.btn_open.setVisible(False); self.btn_close.setVisible(False); self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(True)
        self.setWindowTitle('Generating…'); self._timer.start(500)

    def begin_job(self, label, n_models):
        self._job_i += 1; self._models_per_job = n_models; self._model_i = -1; self._stage_i = 0
        self.title.setText(f'Working on {label}')
        self.sub.setText(f'File {self._job_i + 1} of {self._job_n}' + (' · upper and lower are processed one after the other' if n_models > 1 else ''))
        self._reset_steps()
        self._update_bar()

    def _reset_steps(self):
        for r in self._rows:
            r.setParent(None)
        self._rows = []

    def on_stage(self, i, n, label):
        if i == 1:                                   # a new model starts (pair jobs run two)
            self._model_i += 1
            self._reset_steps(); self._rows = []
            for k in range(1, n + 1):
                r = StepRow(f'{k}. ' + STAGE_NAMES.get(k, ''), STAGE_HELP.get(k, '')); self.steps_box.addWidget(r); self._rows.append(r)
            self._n_stages = n
            if self._models_per_job > 1:
                self.sub.setText(f'File {self._job_i + 1} of {self._job_n} · model {self._model_i + 1} of {self._models_per_job}')
        if not self._rows:
            return
        for k, r in enumerate(self._rows, start=1):
            if k == i:
                r.name.setText(f'{k}. {label}')
            r.set_state(DONE if k < i else RUNNING if k == i else PENDING)
        self._stage_i = i
        self._update_bar()

    def on_text(self, text):
        self.log.appendPlainText(text)

    def _update_bar(self):
        within = 0.0
        if self._n_stages and self._stage_i:
            within = (self._model_i + (self._stage_i - 1) / self._n_stages) / max(1, self._models_per_job)
        v = (max(self._job_i, 0) + within) / self._job_n
        self.bar.setValue(int(min(v, 1.0) * 1000))

    def finish_job(self, ok):
        for r in self._rows:
            if ok:
                r.set_state(DONE)
            elif r.glyph.text() == GLYPH[RUNNING]:
                r.set_state(FAILED)
        if ok:
            self._stage_i = self._n_stages; self._model_i = self._models_per_job - 1
            self.bar.setValue(int((self._job_i + 1) / self._job_n * 1000))

    def finish(self, text, ok):
        self._timer.stop(); self._tick()
        self.title.setText('Done' if ok else 'Stopped')
        self.setWindowTitle('Done' if ok else 'Stopped')
        self.summary.setText(text); self.summary.setVisible(True)
        if ok:
            self.bar.setValue(1000)
        self.btn_cancel.setVisible(False); self.btn_close.setVisible(True); self.btn_open.setVisible(ok)

    def _tick(self):
        s = int(time.time() - self._t0)
        self.lbl_time.setText(f'Elapsed {s // 60}:{s % 60:02d}')

    def _toggle_details(self, on):
        self.log.setVisible(on); self.btn_details.setText('Hide details' if on else 'Show details')
        self.adjustSize()
