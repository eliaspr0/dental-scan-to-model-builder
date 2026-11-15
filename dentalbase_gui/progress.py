"""Live progress panel (shown inside the main window under "Generate"): each processing step as it happens, elapsed
time and an optional detailed log.

Pure UI: it is fed lines from the backend's output by the main window; it never imports the backend."""
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout

from . import theme

# plain-language explanation for each backend stage (keyed by stage number)
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


class StepChip(QLabel):
    """One step in the horizontal stepper: a status glyph and the step name."""
    def __init__(self, k, text):
        super().__init__()
        self.k, self.text_ = k, text
        self.setAlignment(Qt.AlignCenter); self.setWordWrap(True)
        self.set_state(PENDING)

    def set_state(self, state):
        color = {PENDING: '#a1a1a6', RUNNING: theme.ACCENT, DONE: theme.GOOD, FAILED: theme.BAD}[state]
        weight = 600 if state == RUNNING else 400
        self.state = state
        self.setText(f'<span style="color:{color}; font-size:15px; font-weight:700">{GLYPH[state]}</span><br>'
                     f'<span style="font-size:12px; font-weight:{weight}; color:{theme.TEXT if state != PENDING else theme.SECONDARY}">'
                     f'{self.text_}</span>')


class ProgressPanel(QFrame):
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('card')
        self._t0 = time.time(); self._chips = []; self._n_stages = 0
        self._job_i = 0; self._job_n = 1; self._models_per_job = 1; self._model_i = 0; self._stage_i = 0
        lay = QVBoxLayout(self); lay.setContentsMargins(22, 14, 22, 14); lay.setSpacing(8)

        head = QHBoxLayout()
        self.title = QLabel('Progress'); self.title.setObjectName('stepTitle')
        self.lbl_time = QLabel(''); self.lbl_time.setObjectName('help')
        self.btn_cancel = QPushButton('Cancel'); self.btn_cancel.clicked.connect(self.cancel_requested)
        self.btn_hide = QPushButton('Hide'); self.btn_hide.setObjectName('link'); self.btn_hide.setVisible(False)
        self.btn_hide.clicked.connect(self.hide)
        head.addWidget(self.title); head.addSpacing(8); head.addWidget(self.lbl_time); head.addStretch(1)
        head.addWidget(self.btn_hide); head.addWidget(self.btn_cancel)
        lay.addLayout(head)

        self.sub = QLabel(''); self.sub.setObjectName('help'); self.sub.setWordWrap(True); lay.addWidget(self.sub)
        self.bar = QProgressBar(); self.bar.setRange(0, 1000); lay.addWidget(self.bar)

        self.steps_row = QHBoxLayout(); self.steps_row.setSpacing(4); lay.addLayout(self.steps_row)
        self.lbl_now = QLabel(''); self.lbl_now.setObjectName('help'); self.lbl_now.setAlignment(Qt.AlignCenter); lay.addWidget(self.lbl_now)

        self.summary = QLabel(''); self.summary.setWordWrap(True); self.summary.setVisible(False); lay.addWidget(self.summary)

        self.btn_details = QPushButton('Show details'); self.btn_details.setObjectName('link'); self.btn_details.setCheckable(True)
        self.btn_details.toggled.connect(self._toggle_details)
        lay.addWidget(self.btn_details, 0, Qt.AlignLeft)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(5000)
        self.log.setFixedHeight(150); self.log.setVisible(False)
        lay.addWidget(self.log)

        self._timer = QTimer(self); self._timer.timeout.connect(self._tick)
        self.setVisible(False)

    # ---------------------------------------------------------------- control
    def start(self, n_jobs):
        self._t0 = time.time(); self._job_n = max(1, n_jobs); self._job_i = -1
        self.log.clear(); self.summary.setVisible(False); self.summary.setText('')
        self.title.setText('Working…'); self.bar.setValue(0)
        self.btn_hide.setVisible(False); self.btn_cancel.setVisible(True); self.btn_cancel.setEnabled(True)
        self._reset_chips(); self._tick(); self._timer.start(500)
        self.setVisible(True)

    def begin_job(self, label, n_models):
        self._job_i += 1; self._models_per_job = n_models; self._model_i = -1; self._stage_i = 0
        self.title.setText(f'Working on {label}')
        self.sub.setText(f'File {self._job_i + 1} of {self._job_n}')
        self.lbl_now.setText('Starting…')
        self._reset_chips(); self._update_bar()

    def _reset_chips(self):
        for c in self._chips:
            c.setParent(None); c.deleteLater()
        self._chips = []
        for k in range(1, 8):
            c = StepChip(k, STAGE_NAMES[k]); self.steps_row.addWidget(c, 1); self._chips.append(c)
        self._n_stages = 7

    def on_stage(self, i, n, label):
        if i == 1:                                   # a new model starts (pair jobs run two)
            self._model_i += 1
            if self._model_i > 0:
                self._reset_chips()
            if self._models_per_job > 1:
                self.sub.setText(f'File {self._job_i + 1} of {self._job_n} · model {self._model_i + 1} of {self._models_per_job} (upper and lower are processed one after the other)')
        for c in self._chips:
            c.set_state(DONE if c.k < i else RUNNING if c.k == i else PENDING)
        self.lbl_now.setText(f'{label}: {STAGE_HELP.get(i, "")}')
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
        for c in self._chips:
            if ok:
                c.set_state(DONE)
            elif c.state == RUNNING:
                c.set_state(FAILED)
        if ok:
            self._stage_i = self._n_stages; self._model_i = self._models_per_job - 1
            self.bar.setValue(int((self._job_i + 1) / self._job_n * 1000))

    def finish(self, text, ok):
        self._timer.stop(); self._tick()
        self.title.setText('Done' if ok else 'Stopped')
        self.lbl_now.setText('')
        self.summary.setText(text); self.summary.setVisible(True)
        if ok:
            self.bar.setValue(1000)
        self.btn_cancel.setVisible(False); self.btn_hide.setVisible(True)

    def _tick(self):
        s = int(time.time() - self._t0)
        self.lbl_time.setText(f'Elapsed {s // 60}:{s % 60:02d}')

    def _toggle_details(self, on):
        self.log.setVisible(on); self.btn_details.setText('Hide details' if on else 'Show details')
