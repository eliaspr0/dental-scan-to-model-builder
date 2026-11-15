"""PySide6 desktop GUI for the dental base model generator.

Decoupling: this module never imports the backend (`dentalbase`). It runs `make_base.py` as a subprocess
(QProcess), streams its output into the log and parses the JSON report lines it prints.
"""
import os
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, QSettings, QTimer, Qt, QProcess, QProcessEnvironment, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QMainWindow, QMessageBox, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QFileDialog,
)

from . import jobs as J
from . import theme
from .progress import ProgressPanel
from .stl_io import check_binary_stl, guess_role, is_stl_name, output_path

BACKEND_SCRIPT = Path(__file__).resolve().parent.parent / 'make_base.py'
ROLES = [('single', 'Single arch'), ('upper', 'Upper jaw'), ('lower', 'Lower jaw')]
COL_FILE, COL_ROLE, COL_OUT, COL_STATUS = range(4)


class DropTable(QTableWidget):
    """File table that accepts dropped .stl files (and folders: their top-level .stl files)."""
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setAcceptDrops(True)
        self.setHorizontalHeaderLabels(['Scan', 'Jaw', 'Will be saved as', 'Status'])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setFrameShape(QFrame.NoFrame)
        self.verticalHeader().setDefaultSectionSize(40)
        h = self.horizontalHeader()
        h.setSectionResizeMode(COL_FILE, QHeaderView.Stretch)
        h.setSectionResizeMode(COL_ROLE, QHeaderView.Fixed)
        self.setColumnWidth(COL_ROLE, 130)
        h.setSectionResizeMode(COL_OUT, QHeaderView.Stretch)
        h.setSectionResizeMode(COL_STATUS, QHeaderView.Stretch)
        self._hover = False

    # --- drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            self._hover = True; self.viewport().update(); e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._hover = False; self.viewport().update(); e.accept()

    def dropEvent(self, e):
        self._hover = False; self.viewport().update()
        paths = []
        for url in e.mimeData().urls():
            if not url.isLocalFile():
                continue
            p = url.toLocalFile()
            if os.path.isdir(p):
                paths += [os.path.join(p, n) for n in sorted(os.listdir(p)) if is_stl_name(n)]
            else:
                paths.append(p)
        e.acceptProposedAction()
        if paths:
            self.files_dropped.emit(paths)

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if self.rowCount() == 0 or self._hover:
            p = QPainter(self.viewport()); p.setRenderHint(QPainter.Antialiasing)
            r = QRectF(self.viewport().rect()).adjusted(6, 6, -6, -6)
            accent = QColor(theme.ACCENT)
            if self._hover:
                fill = QColor(accent); fill.setAlpha(28); p.setBrush(fill)
            else:
                p.setBrush(Qt.NoBrush)
            pen = QPen(accent if self._hover else QColor(theme.BORDER), 2, Qt.DashLine); p.setPen(pen)
            p.drawRoundedRect(r, 16, 16)
            p.setPen(QColor(theme.TEXT))
            f = p.font(); f.setPixelSize(20); f.setBold(True); p.setFont(f)
            top = r.adjusted(20, 0, -20, -r.height() / 2 + 6)
            p.drawText(top, Qt.AlignHCenter | Qt.AlignBottom | Qt.TextWordWrap, 'Drop your scan files here')
            f.setPixelSize(14); f.setBold(False); p.setFont(f); p.setPen(QColor(theme.SECONDARY))
            bottom = r.adjusted(30, r.height() / 2 + 14, -30, -10)
            p.drawText(bottom, Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                       'Binary .stl files from your intraoral scanner.\nDrop the upper and lower jaw together to keep them aligned.')
            p.end()


class MainWindow(QMainWindow):
    def __init__(self, show_dialogs=True):
        super().__init__()
        self.show_dialogs = show_dialogs
        self.setWindowTitle('Dental Base Model')
        self.resize(1140, 800); self.setMinimumSize(1000, 760)
        self._proc = None
        self._running = False
        self._queue, self._current, self._buf, self._reports = [], None, '', []
        self._total_jobs = self._done_jobs = 0
        self._cancelled = False
        self._last_dir = None
        self._summaries = []
        self._pair_was_possible = False
        self._build_ui()
        self._refresh()

    # ------------------------------------------------------------------ UI
    @staticmethod
    def _card(number, title, subtitle):
        card = QFrame(); card.setObjectName('card')
        v = QVBoxLayout(card); v.setContentsMargins(22, 18, 22, 20); v.setSpacing(10)
        head = QHBoxLayout(); head.setSpacing(10)
        n = QLabel(str(number)); n.setObjectName('stepNumber'); n.setAlignment(Qt.AlignCenter)
        t = QLabel(title); t.setObjectName('stepTitle')
        head.addWidget(n); head.addWidget(t); head.addStretch(1)
        v.addLayout(head)
        if subtitle:
            sub = QLabel(subtitle); sub.setObjectName('help'); sub.setWordWrap(True); v.addWidget(sub)
        return card, v

    def _setting(self, layout, name, spin, help_text):
        row = QHBoxLayout(); lbl = QLabel(name); lbl.setObjectName('settingName')
        row.addWidget(lbl, 1); row.addWidget(spin)
        layout.addLayout(row)
        h = QLabel(help_text); h.setObjectName('help'); h.setWordWrap(True); layout.addWidget(h)

    def _build_ui(self):
        settings = QSettings('DentalBaseModel', 'gui')
        root = QWidget(); root.setObjectName('root')
        outer = QVBoxLayout(root); outer.setContentsMargins(32, 26, 32, 22); outer.setSpacing(14)

        title = QLabel('Dental Base Model'); title.setObjectName('title')
        sub = QLabel('Turn an intraoral scan into a watertight, flat-based model that is ready to 3D print. '
                     'Your teeth are never changed.'); sub.setObjectName('subtitle'); sub.setWordWrap(True)
        outer.addWidget(title); outer.addWidget(sub)

        # first-time welcome banner (can be dismissed for good)
        self.banner = QFrame(); self.banner.setObjectName('banner')
        bl = QHBoxLayout(self.banner); bl.setContentsMargins(16, 10, 10, 10)
        bt = QLabel('<b>First time here?</b> It takes three steps: <b>1</b> add your scan, <b>2</b> check the settings '
                    '(the defaults work well), <b>3</b> press Generate. A new file is saved next to your scan.')
        bt.setWordWrap(True); bl.addWidget(bt, 1)
        bd = QPushButton('Got it'); bd.setObjectName('link'); bd.setCursor(Qt.PointingHandCursor)
        bd.clicked.connect(lambda: (self.banner.setVisible(False), settings.setValue('hide_welcome', True)))
        bl.addWidget(bd)
        self.banner.setVisible(not settings.value('hide_welcome', False, type=bool))
        outer.addWidget(self.banner)

        # ---- step 1: files
        card1, v1 = self._card(1, 'Add your scans', 'Drag one or two .stl files into the box, or choose them from your computer. '
                               'If you add both an upper and a lower scan, they are kept aligned the way they bite together.')
        self.table = DropTable(); self.table.files_dropped.connect(self.add_files)
        v1.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.btn_add = QPushButton('Choose files…'); self.btn_add.clicked.connect(self._browse)
        self.btn_remove = QPushButton('Remove selected'); self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear = QPushButton('Clear all'); self.btn_clear.clicked.connect(self._clear)
        for b in (self.btn_add, self.btn_remove, self.btn_clear):
            row.addWidget(b)
        row.addStretch(1)
        v1.addLayout(row)
        self.lbl_info = QLabel(); self.lbl_info.setObjectName('help'); self.lbl_info.setWordWrap(True); v1.addWidget(self.lbl_info)
        hint = QLabel('Tip: the <b>Jaw</b> column is filled in from the file name (upper / lower). Change it if it is wrong.')
        hint.setObjectName('help'); hint.setWordWrap(True); v1.addWidget(hint)

        # ---- step 2: settings
        card2, v2 = self._card(2, 'Choose your settings', 'The defaults are a good starting point. Hover over a value for more detail.')
        self.sp_offset = self._spin(0.5, 15.0, 0.5, J.DEFAULTS['offset'], ' mm', 1,
                                    'Gingiva margin height: surface distance from the teeth to the trimline, where the base starts.')
        self.sp_smooth = self._spin(0.0, 30.0, 1.0, J.DEFAULTS['smooth'], '', 1, '')   # advanced; not shown (CLI --smooth)
        self.sp_smooth.setVisible(False)
        self.sp_sigma = self._spin(0.0, 5.0, 0.5, J.DEFAULTS['loop_sigma'], ' mm', 1,
                                   'Smoothing of the cut line and the wall below it. 0 follows the scan exactly (the wall looks rippled). '
                                   'Only a narrow strip along the cut edge is blended; gingiva above it and the teeth are not modified.')
        self.sp_thick = self._spin(0.5, 20.0, 0.5, J.DEFAULTS['thickness'], ' mm', 1,
                                   'Thickness of the flat base under the lowest point of the model.')
        self._setting(v2, 'Gingiva margin height', self.sp_offset,
                      'How much gum to keep around the teeth, measured along the surface. The base starts at this line. '
                      'Larger = more gum. Typical: 3–6 mm.')
        self._setting(v2, 'Trimline smoothing', self.sp_sigma,
                      'Smooths the cut line and the wall below it. 0 = follow the scan exactly (rippled wall); higher = smoother. '
                      'Gum near the teeth and the teeth themselves stay exactly as scanned. Typical: 1–3 mm.')
        self._setting(v2, 'Base thickness', self.sp_thick,
                      'Thickness of the flat base under the lowest point of the model. Typical: 0.5–5 mm.')
        sep = QFrame(); sep.setObjectName('separator'); v2.addWidget(sep)
        self.chk_pair = QCheckBox('Upper and lower belong together (articulated pair)')
        self.chk_pair.setToolTip('Needs one scan set to "Upper jaw" and one to "Lower jaw". Both bases are made parallel to the shared '
                                 'bite plane. Outputs always keep the scans\' original coordinates, so articulation is preserved '
                                 'either way. Tooth geometry is never modified.')
        self.chk_pair.toggled.connect(lambda _: self._refresh())
        v2.addWidget(self.chk_pair)
        ph = QLabel('Makes the two bases parallel so the models sit flat and still bite together.'); ph.setObjectName('help'); ph.setWordWrap(True)
        v2.addWidget(ph)
        self.btn_reset = QPushButton('Reset to defaults'); self.btn_reset.setObjectName('link'); self.btn_reset.setCursor(Qt.PointingHandCursor)
        self.btn_reset.clicked.connect(self._reset_defaults)
        v2.addWidget(self.btn_reset, 0, Qt.AlignLeft)

        # ---- step 3: generate (bottom bar)
        card3 = QFrame(); card3.setObjectName('card')
        h3 = QHBoxLayout(card3); h3.setContentsMargins(22, 14, 22, 14); h3.setSpacing(12)
        n3 = QLabel('3'); n3.setObjectName('stepNumber'); n3.setAlignment(Qt.AlignCenter)
        col3 = QVBoxLayout(); col3.setSpacing(0)
        t3 = QLabel('Generate'); t3.setObjectName('stepTitle')
        self.lbl_result = QLabel('Results are saved next to each scan with “_output” added to the name. You can watch every step while it runs.')
        self.lbl_result.setObjectName('help'); self.lbl_result.setWordWrap(True)
        col3.addWidget(t3); col3.addWidget(self.lbl_result)
        h3.addWidget(n3, 0, Qt.AlignTop); h3.addLayout(col3, 1)
        self.btn_open = QPushButton('Show results in folder'); self.btn_open.clicked.connect(self._open_folder); self.btn_open.setEnabled(False)
        self.btn_generate = QPushButton('Generate'); self.btn_generate.setObjectName('primary'); self.btn_generate.setMinimumHeight(46)
        self.btn_generate.setMinimumWidth(200); self.btn_generate.setCursor(Qt.PointingHandCursor); self.btn_generate.clicked.connect(self.generate)
        h3.addWidget(self.btn_open); h3.addWidget(self.btn_generate)

        card2.setMinimumWidth(400); card2.setMaximumWidth(440)
        cols = QHBoxLayout(); cols.setSpacing(18); cols.addWidget(card1, 1); cols.addWidget(card2, 0)
        outer.addLayout(cols, 1)
        outer.addWidget(card3)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame); scroll.setWidget(root)
        scroll.setStyleSheet('QScrollArea { background: #ffffff; }')     # small screens: scroll instead of squeezing
        self.setCentralWidget(scroll)

        self.dialog = ProgressPanel()                 # lives inside the window, under the Generate bar
        self.dialog.cancel_requested.connect(self.cancel)
        outer.addWidget(self.dialog)
        QTimer.singleShot(0, lambda: card2.setMinimumHeight(card2.height()))   # keep the settings text from being squeezed
        self.statusBar().showMessage('Ready')

    @staticmethod
    def _spin(lo, hi, step, val, suffix, dec, tip):
        s = QDoubleSpinBox(); s.setRange(lo, hi); s.setSingleStep(step); s.setDecimals(dec); s.setValue(val)
        s.setSuffix(suffix); s.setToolTip(tip); s.setAlignment(Qt.AlignRight); s.setButtonSymbols(QDoubleSpinBox.PlusMinus); return s

    def options(self):
        return J.Options(self.sp_offset.value(), self.sp_smooth.value(), self.sp_sigma.value(), self.sp_thick.value())

    def _reset_defaults(self):
        self.sp_offset.setValue(J.DEFAULTS['offset']); self.sp_smooth.setValue(J.DEFAULTS['smooth'])
        self.sp_sigma.setValue(J.DEFAULTS['loop_sigma']); self.sp_thick.setValue(J.DEFAULTS['thickness'])

    # ------------------------------------------------------------------ files
    def _notify(self, title, text, warn=True):
        self._log(('⚠ ' if warn else '') + text.replace('\n', '\n  '))
        self.statusBar().showMessage(text.splitlines()[0], 8000)
        if self.show_dialogs:
            (QMessageBox.warning if warn else QMessageBox.information)(self, title, text)

    def paths(self):
        return [self.table.item(r, COL_FILE).data(Qt.UserRole) for r in range(self.table.rowCount())]

    def files_with_roles(self):
        out = []
        for r in range(self.table.rowCount()):
            out.append((self.table.item(r, COL_FILE).data(Qt.UserRole), self.table.cellWidget(r, COL_ROLE).currentData()))
        return out

    def add_files(self, paths):
        rejected, have = [], set(self.paths())
        for p in paths:
            p = os.path.abspath(p)
            if p in have:
                continue
            if not is_stl_name(p):
                rejected.append(f'{os.path.basename(p)}: not an .stl file'); continue
            ok, msg = check_binary_stl(p)
            if not ok:
                rejected.append(f'{os.path.basename(p)}: {msg}'); continue
            self._add_row(p, msg); have.add(p)
        if rejected:
            self._notify('Some files were skipped', 'Skipped (only binary .stl files are supported):\n' + '\n'.join(rejected))
        self._refresh()

    def _add_row(self, path, info):
        r = self.table.rowCount(); self.table.insertRow(r)
        it = QTableWidgetItem(os.path.basename(path)); it.setData(Qt.UserRole, path); it.setToolTip(f'{path}\n{info}')
        self.table.setItem(r, COL_FILE, it)
        combo = QComboBox()
        for key, label in ROLES:
            combo.addItem(label, key)
        combo.setCurrentIndex([k for k, _ in ROLES].index(guess_role(path)))
        combo.currentIndexChanged.connect(lambda _: self._refresh())
        self.table.setCellWidget(r, COL_ROLE, combo)
        out = QTableWidgetItem(os.path.basename(output_path(path))); out.setToolTip(output_path(path))
        self.table.setItem(r, COL_OUT, out)
        self.table.setItem(r, COL_STATUS, QTableWidgetItem(f'Ready · {info}'))

    def _browse(self):
        files, _ = QFileDialog.getOpenFileNames(self, 'Select binary STL scans', self._last_dir or '', 'STL files (*.stl *.STL)')
        if files:
            self._last_dir = os.path.dirname(files[0]); self.add_files(files)

    def _remove_selected(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)
        self._refresh()

    def _clear(self):
        self.table.setRowCount(0); self._refresh()

    def _refresh(self):
        roles = [r for _, r in self.files_with_roles()]
        possible = roles.count('upper') == 1 and roles.count('lower') == 1
        if possible and not self._pair_was_possible:
            self.chk_pair.blockSignals(True); self.chk_pair.setChecked(True); self.chk_pair.blockSignals(False)
        if not possible:
            self.chk_pair.blockSignals(True); self.chk_pair.setChecked(False); self.chk_pair.blockSignals(False)
        self._pair_was_possible = possible
        running = self._running
        self.chk_pair.setEnabled(possible and not running)
        n = len(roles)
        self.table.horizontalHeader().setVisible(n > 0)
        self.btn_generate.setEnabled(n > 0 and not running)
        if n == 0:
            self.lbl_info.setText('')
        elif possible and self.chk_pair.isChecked():
            self.lbl_info.setText('Upper + lower will be processed together as one aligned pair.')
        elif roles.count('upper') or roles.count('lower'):
            self.lbl_info.setText('To process an aligned pair, set exactly one scan to Upper jaw and one to Lower jaw.')
        else:
            self.lbl_info.setText('')

    # ------------------------------------------------------------------ running
    def _set_running(self, running):
        self._running = running
        for w in (self.btn_add, self.btn_remove, self.btn_clear, self.btn_reset, self.sp_offset, self.sp_smooth,
                  self.sp_sigma, self.sp_thick, self.table.horizontalHeader()):
            w.setEnabled(not running)
        self.table.setAcceptDrops(not running)
        for r in range(self.table.rowCount()):
            self.table.cellWidget(r, COL_ROLE).setEnabled(not running)
        if running:
            self.btn_generate.setEnabled(False)
        self._refresh()

    def _row_of(self, path):
        for r in range(self.table.rowCount()):
            if self.table.item(r, COL_FILE).data(Qt.UserRole) == path:
                return r
        return -1

    def _set_status(self, path, text):
        r = self._row_of(path)
        if r >= 0:
            self.table.item(r, COL_STATUS).setText(text)

    def generate(self):
        if self._running or not self.paths():
            return
        files = self.files_with_roles()
        pair = self.chk_pair.isChecked() and self.chk_pair.isEnabled()
        plan = J.plan_jobs(files, pair)
        existing = [o for j in plan for o in j.outputs if os.path.exists(o)]
        if existing and self.show_dialogs:
            ok = QMessageBox.question(self, 'Overwrite outputs?', f'{len(existing)} output file(s) already exist and will be overwritten:\n\n'
                                      + '\n'.join(os.path.basename(p) for p in existing[:8]) + ('\n…' if len(existing) > 8 else ''))
            if ok != QMessageBox.Yes:
                return
        for p, _ in files:                       # re-validate right before running (files may have changed on disk)
            good, msg = check_binary_stl(p)
            if not good:
                self._notify('Invalid input', f'{os.path.basename(p)}: {msg}'); return
        self._queue, self._reports, self._cancelled = list(plan), [], False
        self._total_jobs, self._done_jobs = len(plan), 0
        self.btn_open.setEnabled(False)
        self._summaries = []
        was_hidden = not self.dialog.isVisible()
        self.dialog.start(self._total_jobs)
        if was_hidden and not self.isMaximized() and not self.isFullScreen():
            want = self.height() + self.dialog.sizeHint().height() + 64       # make room for the panel (+ result lines)
            scr = self.screen().availableGeometry().height() - 40 if self.screen() else want
            self.resize(self.width(), min(want, scr))
        for p, _ in files:
            self._set_status(p, 'Queued')
        self._log(f'--- Generating {self._total_jobs} job(s) with {self.options()}')
        self._set_running(True)
        self._start_next()

    def _start_next(self):
        if self._cancelled or not self._queue:
            return self._finish()
        job = self._queue.pop(0); self._current = job; self._reports = []; self._buf = ''
        for p in job.inputs:
            self._set_status(p, 'Running…')
        self.statusBar().showMessage(f'Processing: {job.label}')
        self._log(f'=== {job.label}')
        self.dialog.begin_job(' + '.join(os.path.basename(p) for p in job.inputs), len(job.inputs))
        args = J.build_args(job, self.options(), str(BACKEND_SCRIPT))
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.MergedChannels)
        env = QProcessEnvironment.systemEnvironment(); env.insert('PYTHONUNBUFFERED', '1'); self._proc.setProcessEnvironment(env)
        self._proc.setWorkingDirectory(str(BACKEND_SCRIPT.parent))
        self._proc.readyReadStandardOutput.connect(self._on_output)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)
        self._proc.start(args[0], args[1:])

    def _on_output(self):
        self._consume(bytes(self._proc.readAllStandardOutput()).decode('utf-8', 'replace'))

    def _consume(self, text, flush=False):
        self._buf += text
        lines = self._buf.split('\n')
        self._buf = '' if flush else lines.pop()
        for ln in lines:
            ln = ln.rstrip()
            if not ln:
                continue
            st = J.parse_stage(ln)
            if st is not None:
                self.dialog.on_stage(*st)
                continue
            rep = J.parse_report(ln)
            if rep is not None:
                self._reports.append(rep)
                self._log('  report: ' + J.summarize(rep))
            else:
                self._log('  ' + ln)

    def _on_error(self, err):
        if err == QProcess.FailedToStart:
            self._log(f'⚠ Could not start the backend: {self._proc.errorString()}')
            self._job_done(ok=False, reason='could not start backend (is the Python environment installed?)')

    def _on_finished(self, code, status):
        self._consume('', flush=True)
        if self._cancelled:
            return self._job_done(ok=False, reason='cancelled')
        if code != 0 or status != QProcess.NormalExit:
            return self._job_done(ok=False, reason=f'backend failed (exit code {code}); see log')
        self._job_done(ok=True)

    def _job_done(self, ok, reason=''):
        job, self._current = self._current, None
        proc, self._proc = self._proc, None
        if proc is not None:
            proc.deleteLater()
        if job is None:
            return
        for i, (inp, out) in enumerate(zip(job.inputs, job.outputs)):
            if not ok:
                self._set_status(inp, ('Cancelled' if reason == 'cancelled' else 'Failed') + (f' · {reason}' if reason != 'cancelled' else ''))
                continue
            good, msg = check_binary_stl(out) if os.path.exists(out) else (False, 'output file missing')
            if not good:
                self._set_status(inp, f'Failed · {msg}'); self._log(f'⚠ {os.path.basename(out)}: {msg}'); continue
            rep = self._reports[i] if i < len(self._reports) else None
            bad = rep is not None and (not rep.get('watertight') or rep.get('euler') not in (None, 2))
            self._set_status(inp, ('Done, check mesh · ' if bad else 'Done ✓ · ') + (J.summarize(rep) if rep else msg))
            self._summaries.append(f'{os.path.basename(out)}: ' + (J.summarize(rep) if rep else msg) + (' (please check the model)' if bad else ''))
            self._last_out_dir = os.path.dirname(out)
        self.dialog.finish_job(ok)
        if ok:
            self._done_jobs += 1
        self._start_next()

    def cancel(self):
        if self._proc is None:
            return
        self._cancelled = True
        self._log('--- cancelling…')
        for j in self._queue:
            for p in j.inputs:
                self._set_status(p, 'Cancelled')
        self._queue = []
        self._proc.kill()

    def _finish(self):
        self._queue = []
        self._set_running(False)
        self.statusBar().showMessage('Cancelled' if self._cancelled else 'Finished', 8000)
        self._log('--- ' + ('cancelled' if self._cancelled else 'finished'))
        have_out = getattr(self, '_last_out_dir', None) is not None
        self.btn_open.setEnabled(have_out)
        ok = (not self._cancelled) and self._done_jobs == self._total_jobs
        msg = ('\n'.join('✓ ' + t for t in self._summaries) if self._summaries else 'Nothing was produced.')
        if self._cancelled:
            msg = 'Cancelled.' + ('\n' + msg if self._summaries else '')
        elif not ok:
            msg = 'Some files could not be processed. Open “Show details” to see why.\n' + msg
        self.dialog.finish(msg, ok and have_out)
        self.statusBar().showMessage('Finished' if ok else 'Stopped', 8000)
        self.lbl_result.setText(('Finished. ' if ok else 'Stopped. ') + f'{self._done_jobs} of {self._total_jobs} done. Results are next to your scans (“_output”).')

    def _open_folder(self):
        d = getattr(self, '_last_out_dir', None)
        if d:
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def _log(self, text):
        self.dialog.on_text(text)

    def closeEvent(self, e):
        if self._proc is not None:
            self._cancelled = True; self._proc.kill(); self._proc.waitForFinished(2000)
        e.accept()


def apply_theme(app):
    app.setStyle('Fusion')                              # consistent rendering of the style sheet on every platform
    pal = app.palette()
    for role, col in ((pal.ColorRole.Window, '#ffffff'), (pal.ColorRole.Base, '#ffffff'), (pal.ColorRole.Text, theme.TEXT),
                      (pal.ColorRole.WindowText, theme.TEXT), (pal.ColorRole.ButtonText, theme.TEXT),
                      (pal.ColorRole.Button, '#ffffff'), (pal.ColorRole.Highlight, theme.ACCENT)):
        pal.setColor(role, QColor(col))
    app.setPalette(pal)
    app.setStyleSheet(theme.STYLE)


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
