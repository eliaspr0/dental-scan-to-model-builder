"""PySide6 desktop GUI for the dental base model generator.

Decoupling: this module never imports the backend (`dentalbase`). It runs `make_base.py` as a subprocess
(QProcess), streams its output into the log and parses the JSON report lines it prints.
"""
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QProcess, QProcessEnvironment, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPainter, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QFileDialog,
)

from . import jobs as J
from .stl_io import check_binary_stl, guess_role, is_stl_name, output_path

BACKEND_SCRIPT = Path(__file__).resolve().parent.parent / 'make_base.py'
ROLES = [('single', 'Single arch'), ('upper', 'Upper'), ('lower', 'Lower')]
COL_FILE, COL_ROLE, COL_OUT, COL_STATUS = range(4)


class DropTable(QTableWidget):
    """File table that accepts dropped .stl files (and folders: their top-level .stl files)."""
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(0, 4, parent)
        self.setAcceptDrops(True)
        self.setHorizontalHeaderLabels(['Input file', 'Arch', 'Output file', 'Status'])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        h = self.horizontalHeader()
        h.setSectionResizeMode(COL_FILE, QHeaderView.Stretch)
        h.setSectionResizeMode(COL_ROLE, QHeaderView.Fixed)
        self.setColumnWidth(COL_ROLE, 120)
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
            p = QPainter(self.viewport())
            col = self.palette().color(self.foregroundRole()); col.setAlpha(150 if not self._hover else 230)
            p.setPen(col)
            r = self.viewport().rect().adjusted(20, 40, -20, -20)
            if self._hover:
                p.setPen(QColor('#2a82da'))
            p.drawText(r, Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextWordWrap,
                       'Drop binary .stl scans here\n(or use “Add files…”)\n\nUpper and lower scans of the same patient '
                       'can be processed together as an articulated pair.')
            p.end()


class MainWindow(QMainWindow):
    def __init__(self, show_dialogs=True):
        super().__init__()
        self.show_dialogs = show_dialogs
        self.setWindowTitle('Dental Base Model')
        self.resize(1100, 720)
        self._proc = None
        self._running = False
        self._queue, self._current, self._buf, self._reports = [], None, '', []
        self._total_jobs = self._done_jobs = 0
        self._cancelled = False
        self._last_dir = None
        self._pair_was_possible = False
        self._build_ui()
        self._refresh()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # left: input table
        left = QGroupBox('Input scans (binary STL)')
        lv = QVBoxLayout(left)
        self.table = DropTable()
        self.table.files_dropped.connect(self.add_files)
        lv.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.btn_add = QPushButton('Add files…'); self.btn_add.clicked.connect(self._browse)
        self.btn_remove = QPushButton('Remove selected'); self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear = QPushButton('Clear'); self.btn_clear.clicked.connect(self._clear)
        for b in (self.btn_add, self.btn_remove, self.btn_clear):
            row.addWidget(b)
        row.addStretch(1)
        lv.addLayout(row)
        note = QLabel('Outputs are written next to each input as <b>&lt;name&gt;_output.stl</b> (binary STL).')
        note.setWordWrap(True)
        lv.addWidget(note)

        # right: options
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0)
        opts = QGroupBox('Options'); form = QFormLayout(opts)
        self.sp_offset = self._spin(0.5, 15.0, 0.5, J.DEFAULTS['offset'], ' mm', 1,
                                    'Gingiva margin height: geodesic distance from the crowns to the trimline, where the base starts.')
        self.sp_smooth = self._spin(0.0, 30.0, 1.0, J.DEFAULTS['smooth'], '', 1, '')   # advanced; not shown (CLI --smooth)
        self.sp_smooth.setVisible(False)
        self.sp_sigma = self._spin(0.0, 10.0, 0.5, J.DEFAULTS['loop_sigma'], ' mm', 1,
                                   'Smooths the trimline; the wall is extruded straight down from the smoothed line. The scan follows it only within a narrow strip (about 0.5-2 mm) along the cut edge; everything above that strip, gingiva and teeth, is not modified. 0 = no smoothing.')
        self.sp_thick = self._spin(0.5, 20.0, 0.5, J.DEFAULTS['thickness'], ' mm', 1,
                                   'Base thickness below the lowest point of the scan; the base bottom is flat.')
        form.addRow('Gingiva margin height', self.sp_offset)
        form.addRow('Trimline smoothing', self.sp_sigma)
        form.addRow('Base thickness', self.sp_thick)
        self.btn_reset = QPushButton('Reset to defaults'); self.btn_reset.clicked.connect(self._reset_defaults)
        form.addRow('', self.btn_reset)
        rv.addWidget(opts)

        self.chk_pair = QCheckBox('Articulated pair (shared bite plane)')
        self.chk_pair.setToolTip('Needs one file set to "Upper" and one to "Lower". Both bases are made parallel to the shared '
                                 'bite plane. Outputs always keep the scans\' original coordinates, so articulation is preserved '
                                 'either way. Tooth geometry is never modified.')
        self.chk_pair.toggled.connect(lambda _: self._refresh())
        rv.addWidget(self.chk_pair)
        self.lbl_info = QLabel(); self.lbl_info.setWordWrap(True); self.lbl_info.setStyleSheet('color: gray;')
        rv.addWidget(self.lbl_info)
        rv.addStretch(1)

        self.btn_generate = QPushButton('Generate'); self.btn_generate.setMinimumHeight(40)
        f = self.btn_generate.font(); f.setBold(True); self.btn_generate.setFont(f)
        self.btn_generate.clicked.connect(self.generate)
        self.btn_cancel = QPushButton('Cancel'); self.btn_cancel.clicked.connect(self.cancel); self.btn_cancel.setEnabled(False)
        self.btn_open = QPushButton('Open output folder'); self.btn_open.clicked.connect(self._open_folder); self.btn_open.setEnabled(False)
        rv.addWidget(self.btn_generate)
        h = QHBoxLayout(); h.addWidget(self.btn_cancel); h.addWidget(self.btn_open); rv.addLayout(h)

        top = QHBoxLayout(); top.addWidget(left, 3); top.addWidget(right, 1)

        # bottom: progress + log
        self.progress = QProgressBar(); self.progress.setRange(0, 1); self.progress.setValue(0); self.progress.setFormat('Idle')
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(5000)
        self.log.setPlaceholderText('Log output appears here…')
        self.log.setFixedHeight(170)

        central = QWidget(); cv = QVBoxLayout(central)
        cv.addLayout(top, 1); cv.addWidget(self.progress); cv.addWidget(self.log)
        self.setCentralWidget(central)
        self.statusBar().showMessage('Ready')

    @staticmethod
    def _spin(lo, hi, step, val, suffix, dec, tip):
        s = QDoubleSpinBox(); s.setRange(lo, hi); s.setSingleStep(step); s.setDecimals(dec); s.setValue(val)
        s.setSuffix(suffix); s.setToolTip(tip); return s

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
        self.btn_generate.setEnabled(n > 0 and not running)
        if n == 0:
            self.lbl_info.setText('')
        elif possible and self.chk_pair.isChecked():
            self.lbl_info.setText('Upper + lower will be processed as one articulated pair.')
        elif roles.count('upper') or roles.count('lower'):
            self.lbl_info.setText('Set exactly one file to Upper and one to Lower to enable articulated-pair mode.')
        else:
            self.lbl_info.setText('Tip: mark files as Upper / Lower to enable articulated-pair mode.')

    # ------------------------------------------------------------------ running
    def _set_running(self, running):
        self._running = running
        for w in (self.btn_add, self.btn_remove, self.btn_clear, self.btn_reset, self.sp_offset, self.sp_smooth,
                  self.sp_sigma, self.sp_thick, self.table.horizontalHeader()):
            w.setEnabled(not running)
        self.table.setAcceptDrops(not running)
        for r in range(self.table.rowCount()):
            self.table.cellWidget(r, COL_ROLE).setEnabled(not running)
        self.btn_cancel.setEnabled(running)
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
        self.progress.setRange(0, self._total_jobs); self.progress.setValue(0); self.progress.setFormat('%v / %m jobs done')
        self.btn_open.setEnabled(False)
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
            self._last_out_dir = os.path.dirname(out)
        if ok:
            self._done_jobs += 1
        self.progress.setValue(self._done_jobs)
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
        self.progress.setFormat('Cancelled' if self._cancelled else 'Finished')
        self.statusBar().showMessage('Cancelled' if self._cancelled else 'Finished', 8000)
        self._log('--- ' + ('cancelled' if self._cancelled else 'finished'))
        self.btn_open.setEnabled(getattr(self, '_last_out_dir', None) is not None)

    def _open_folder(self):
        d = getattr(self, '_last_out_dir', None)
        if d:
            QDesktopServices.openUrl(QUrl.fromLocalFile(d))

    def _log(self, text):
        self.log.appendPlainText(text)

    def closeEvent(self, e):
        if self._proc is not None:
            self._cancelled = True; self._proc.kill(); self._proc.waitForFinished(2000)
        e.accept()


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())
