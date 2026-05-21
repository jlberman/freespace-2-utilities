import sys
from pathlib import Path
from apng import APNG

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QProgressBar, QTextEdit, QGroupBox,
    QTabWidget, QListWidget, QListWidgetItem, QAbstractItemView, QSizePolicy
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QColor, QPalette

# ─────────────────────── Theme & Styles ────────────────────────

DARK_BG       = "#1a1a1a"
DARK_SURFACE  = "#242424"
DARK_RAISED   = "#2e2e2e"
DARK_BORDER   = "#3a3a3a"
ACCENT        = "#5b9bd5"
TEXT_PRIMARY  = "#e8e8e8"
TEXT_MUTED    = "#888888"

STYLESHEET = f"""
QWidget {{
    background: {DARK_BG};
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}}
QTabWidget::pane {{
    border: 1px solid {DARK_BORDER};
    border-radius: 8px;
    background: {DARK_SURFACE};
}}
QTabBar::tab {{
    background: {DARK_RAISED};
    border: 1px solid {DARK_BORDER};
    border-bottom: none;
    border-radius: 6px 6px 0 0;
    padding: 6px 20px;
    color: {TEXT_MUTED};
}}
QTabBar::tab:selected {{
    background: {DARK_SURFACE};
    color: {TEXT_PRIMARY};
    border-bottom: 1px solid {DARK_SURFACE};
}}
QTabBar::tab:hover:!selected {{
    background: #383838;
}}
QGroupBox {{
    background: {DARK_SURFACE};
    border: 1px solid {DARK_BORDER};
    border-radius: 8px;
    margin-top: 10px;
    padding: 10px;
    font-weight: bold;
    color: {TEXT_MUTED};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    top: -5px;
    padding: 0 5px;
}}
QPushButton {{
    background: {DARK_RAISED};
    border: 1px solid {DARK_BORDER};
    border-radius: 6px;
    padding: 6px 16px;
}}
QPushButton:hover {{ background: #383838; }}
QPushButton:disabled {{ color: #555; background: #1a1a1a; }}
QPushButton#primaryBtn {{
    background: {ACCENT};
    color: white;
    font-weight: bold;
    padding: 10px;
}}
QPushButton#primaryBtn:hover {{ background: #78b4e8; }}
QPushButton#primaryBtn:disabled {{ background: #2a3d50; color: #888; }}
QPushButton#dangerBtn {{
    background: #6b2828;
    border-color: #8b3a3a;
    color: #e8e8e8;
}}
QPushButton#dangerBtn:hover {{ background: #7f3030; }}
QProgressBar {{
    background: {DARK_RAISED};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 4px;
}}
QTextEdit {{
    background: {DARK_SURFACE};
    border: 1px solid {DARK_BORDER};
    border-radius: 6px;
    padding: 5px;
    font-family: "Consolas", monospace;
    font-size: 12px;
}}
QListWidget {{
    background: {DARK_SURFACE};
    border: 1px solid {DARK_BORDER};
    border-radius: 6px;
    padding: 4px;
    font-family: "Consolas", monospace;
    font-size: 12px;
}}
QListWidget::item {{
    padding: 3px 6px;
    border-radius: 4px;
}}
QListWidget::item:selected {{
    background: #2a3d50;
    color: {TEXT_PRIMARY};
}}
QListWidget::item:hover:!selected {{
    background: {DARK_RAISED};
}}
"""

# ─────────────────────── Background Worker ─────────────────────

class WorkerSignals(QObject):
    log = pyqtSignal(str)
    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal(int, int)  # success, total

class ReverserWorker(QThread):
    """Processes a pre-built list of (input_file, output_file) pairs."""

    def __init__(self, file_pairs: list):
        super().__init__()
        self.file_pairs = file_pairs  # list of (Path src, Path dst)
        self.signals = WorkerSignals()
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        total = len(self.file_pairs)

        if total == 0:
            self.signals.log.emit("No files queued for processing.")
            self.signals.finished.emit(0, 0)
            return

        self.signals.log.emit(f"Processing {total} file(s)...\n")
        success_count = 0

        for i, (src, dst) in enumerate(self.file_pairs):
            if not self._is_running:
                self.signals.log.emit("\n[!] Processing stopped by user.")
                break

            # Ensure output directory exists
            dst.parent.mkdir(parents=True, exist_ok=True)

            try:
                im = APNG.open(str(src))

                if len(im.frames) <= 1:
                    self.signals.log.emit(f"[-] Skipped (static image): {src.name}")
                else:
                    reversed_frames = list(im.frames)[::-1]
                    out_im = APNG()

                    for png, control in reversed_frames:
                        delay = control.delay if control else 100
                        delay_den = control.delay_den if control else 1000
                        out_im.append(png, delay=delay, delay_den=delay_den)

                    out_im.save(str(dst))
                    self.signals.log.emit(f"[+] Reversed: {src.name}  →  {dst.name}")
                    success_count += 1

            except Exception as e:
                self.signals.log.emit(f"[!] Error processing {src.name}: {e}")

            self.signals.progress.emit(i + 1, total)

        self.signals.finished.emit(success_count, total)


# ─────────────────────── Shared Log / Progress Widget ──────────

class LogProgressWidget(QWidget):
    """Reusable log + progress bar + start/stop buttons block."""

    started = pyqtSignal()
    stopped = pyqtSignal()

    def __init__(self, start_label="▶ Start", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        log_group = QGroupBox("Processing Log")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_group, stretch=1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        self.btn_start = QPushButton(start_label)
        self.btn_start.setObjectName("primaryBtn")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self.started)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stopped)

        btn_row.addWidget(self.btn_start, stretch=1)
        btn_row.addWidget(self.btn_stop)
        layout.addLayout(btn_row)

    def log(self, message: str):
        self.log_text.append(message)
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def set_running(self, running: bool):
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    def reset(self):
        self.log_text.clear()
        self.progress_bar.setValue(0)


# ─────────────────────── Batch Tab ─────────────────────────────

class BatchTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.input_path = None
        self.output_path = None
        self.worker = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)

        # Directories
        dir_group = QGroupBox("Directories")
        dir_layout = QVBoxLayout(dir_group)

        in_row = QHBoxLayout()
        self.lbl_input = QLabel("Input: Not Selected")
        self.lbl_input.setStyleSheet(f"color: {TEXT_MUTED};")
        btn_input = QPushButton("Choose Input Folder…")
        btn_input.clicked.connect(self._choose_input)
        in_row.addWidget(self.lbl_input, stretch=1)
        in_row.addWidget(btn_input)
        dir_layout.addLayout(in_row)

        out_row = QHBoxLayout()
        self.lbl_output = QLabel("Output: Not Selected")
        self.lbl_output.setStyleSheet(f"color: {TEXT_MUTED};")
        btn_output = QPushButton("Choose Output Folder…")
        btn_output.clicked.connect(self._choose_output)
        out_row.addWidget(self.lbl_output, stretch=1)
        out_row.addWidget(btn_output)
        dir_layout.addLayout(out_row)

        layout.addWidget(dir_group)

        # Log / progress / buttons
        self.lp = LogProgressWidget("▶ Start Batch Reversal")
        self.lp.started.connect(self._start_processing)
        self.lp.stopped.connect(self._stop_processing)
        layout.addWidget(self.lp, stretch=1)

    # ── Directory pickers ──

    def _choose_input(self):
        d = QFileDialog.getExistingDirectory(self, "Select Input Directory")
        if d:
            self.input_path = Path(d)
            self.lbl_input.setText(f"Input: {self.input_path}")
            self.lbl_input.setStyleSheet(f"color: {TEXT_PRIMARY};")
            if not self.output_path:
                self.output_path = self.input_path / "Reversed_APNGs"
                self.lbl_output.setText(f"Output: {self.output_path}")
                self.lbl_output.setStyleSheet(f"color: {TEXT_PRIMARY};")
            self._check_ready()

    def _choose_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self.output_path = Path(d)
            self.lbl_output.setText(f"Output: {self.output_path}")
            self.lbl_output.setStyleSheet(f"color: {TEXT_PRIMARY};")
            self._check_ready()

    def _check_ready(self):
        if self.input_path and self.output_path:
            self.lp.btn_start.setEnabled(True)

    # ── Processing ──

    def _start_processing(self):
        self.lp.reset()
        self.lp.set_running(True)

        files = (
            list(self.input_path.glob("*.png"))
            + list(self.input_path.glob("*.apng"))
        )
        pairs = [(f, self.output_path / f"reversed_{f.name}") for f in files]

        self.worker = ReverserWorker(pairs)
        self.worker.signals.log.connect(self.lp.log)
        self.worker.signals.progress.connect(self.lp.set_progress)
        self.worker.signals.finished.connect(self._on_finished)
        self.worker.start()

    def _stop_processing(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.lp.btn_stop.setEnabled(False)

    def _on_finished(self, success_count, total):
        self.lp.set_running(False)
        self.lp.btn_start.setEnabled(bool(self.input_path and self.output_path))
        if total > 0:
            self.lp.log("-" * 40)
            self.lp.log(
                f"Batch complete! Successfully reversed {success_count} of {total} file(s)."
            )
            self.lp.log(f"Saved to: {self.output_path}")


# ─────────────────────── Files Tab ─────────────────────────────

class FilesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.output_path = None
        self.worker = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(15, 15, 15, 15)

        # ── File list group ──
        files_group = QGroupBox("Selected Files")
        files_layout = QVBoxLayout(files_group)

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.setMinimumHeight(120)
        files_layout.addWidget(self.file_list)

        list_btns = QHBoxLayout()
        btn_add = QPushButton("Add File(s)…")
        btn_add.clicked.connect(self._add_files)
        btn_remove = QPushButton("Remove Selected")
        btn_remove.setObjectName("dangerBtn")
        btn_remove.clicked.connect(self._remove_selected)
        btn_clear = QPushButton("Clear All")
        btn_clear.clicked.connect(self._clear_files)
        list_btns.addWidget(btn_add)
        list_btns.addWidget(btn_remove)
        list_btns.addStretch()
        list_btns.addWidget(btn_clear)
        files_layout.addLayout(list_btns)

        layout.addWidget(files_group)

        # ── Output folder ──
        out_group = QGroupBox("Output")
        out_layout = QHBoxLayout(out_group)
        self.lbl_output = QLabel("Output: Not Selected")
        self.lbl_output.setStyleSheet(f"color: {TEXT_MUTED};")
        btn_output = QPushButton("Choose Output Folder…")
        btn_output.clicked.connect(self._choose_output)
        out_layout.addWidget(self.lbl_output, stretch=1)
        out_layout.addWidget(btn_output)
        layout.addWidget(out_group)

        # ── Log / progress / buttons ──
        self.lp = LogProgressWidget("▶ Reverse Selected Files")
        self.lp.started.connect(self._start_processing)
        self.lp.stopped.connect(self._stop_processing)
        layout.addWidget(self.lp, stretch=1)

        self.file_list.model().rowsInserted.connect(self._check_ready)
        self.file_list.model().rowsRemoved.connect(self._check_ready)

    # ── File list management ──

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select APNG / PNG Files",
            "",
            "Animated PNG Files (*.apng *.png);;All Files (*)",
        )
        existing = {
            self.file_list.item(i).data(Qt.UserRole)
            for i in range(self.file_list.count())
        }
        for f in files:
            p = Path(f)
            if str(p) not in existing:
                item = QListWidgetItem(p.name)
                item.setData(Qt.UserRole, str(p))
                item.setToolTip(str(p))
                self.file_list.addItem(item)

        # Auto-set output dir from first file's parent if not yet chosen
        if files and not self.output_path:
            self.output_path = Path(files[0]).parent / "Reversed_APNGs"
            self.lbl_output.setText(f"Output: {self.output_path}")
            self.lbl_output.setStyleSheet(f"color: {TEXT_PRIMARY};")

    def _remove_selected(self):
        for item in self.file_list.selectedItems():
            self.file_list.takeItem(self.file_list.row(item))

    def _clear_files(self):
        self.file_list.clear()

    # ── Output picker ──

    def _choose_output(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if d:
            self.output_path = Path(d)
            self.lbl_output.setText(f"Output: {self.output_path}")
            self.lbl_output.setStyleSheet(f"color: {TEXT_PRIMARY};")
            self._check_ready()

    def _check_ready(self, *_):
        ready = self.file_list.count() > 0 and self.output_path is not None
        self.lp.btn_start.setEnabled(ready)

    # ── Processing ──

    def _start_processing(self):
        self.lp.reset()
        self.lp.set_running(True)

        pairs = []
        for i in range(self.file_list.count()):
            src = Path(self.file_list.item(i).data(Qt.UserRole))
            dst = self.output_path / f"reversed_{src.name}"
            pairs.append((src, dst))

        self.worker = ReverserWorker(pairs)
        self.worker.signals.log.connect(self.lp.log)
        self.worker.signals.progress.connect(self.lp.set_progress)
        self.worker.signals.finished.connect(self._on_finished)
        self.worker.start()

    def _stop_processing(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.lp.btn_stop.setEnabled(False)

    def _on_finished(self, success_count, total):
        self.lp.set_running(False)
        self._check_ready()
        if total > 0:
            self.lp.log("-" * 40)
            self.lp.log(
                f"Done! Successfully reversed {success_count} of {total} file(s)."
            )
            self.lp.log(f"Saved to: {self.output_path}")


# ─────────────────────── Main GUI Window ───────────────────────

class ReverserWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("APNG Reverser")
        self.setMinimumSize(640, 540)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(15, 15, 15, 15)

        tabs = QTabWidget()
        tabs.addTab(BatchTab(), "  📁  Batch (Folder)  ")
        tabs.addTab(FilesTab(), "  🖼  Individual Files  ")
        root.addWidget(tabs)


# ─────────────────────── Application Entry ─────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("APNG Reverser")
    app.setStyleSheet(STYLESHEET)

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(DARK_BG))
    palette.setColor(QPalette.WindowText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Base, QColor(DARK_SURFACE))
    app.setPalette(palette)

    window = ReverserWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
