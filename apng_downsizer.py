#!/usr/bin/env python3
"""
APNG Bulk Downsizer & MP4 to APNG Converter
Desktop-native, air-gapped. Requires: Python 3.8+, Pillow, PyQt5, apng, opencv-python
Install:  pip install Pillow PyQt5 apng opencv-python
Run:      python3 apng_downsizer.py
"""

import sys
import os
import io
import math
import struct
import zlib
import shutil
import tempfile
import fractions
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QProgressBar, QComboBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QRadioButton, QButtonGroup, QSplitter, QFrame,
    QAbstractItemView, QSizePolicy, QMessageBox, QAction, QMenuBar,
    QStatusBar, QCheckBox, QSlider, QLineEdit, QToolButton, QScrollArea,
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QMimeData, QUrl, QSize, QTimer, QRunnable,
    QThreadPool, pyqtSlot, QObject,
)
from PyQt5.QtGui import (
    QColor, QPalette, QDragEnterEvent, QDropEvent, QFont, QIcon,
    QPixmap, QPainter, QBrush, QPen, QLinearGradient,
)
from PIL import Image, ImageSequence

try:
    from apng import APNG, PNG
    HAS_APNG = True
except ImportError:
    HAS_APNG = False

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


# ─────────────────────── Colours / theme ────────────────────────

DARK_BG       = "#1a1a1a"
DARK_SURFACE  = "#242424"
DARK_RAISED   = "#2e2e2e"
DARK_BORDER   = "#3a3a3a"
ACCENT        = "#5b9bd5"
ACCENT_HOVER  = "#78b4e8"
TEXT_PRIMARY  = "#e8e8e8"
TEXT_MUTED    = "#888888"
SUCCESS       = "#4caf50"
WARNING       = "#ff9800"
ERROR         = "#f44336"
IDLE_DOT      = "#555555"

STYLESHEET = f"""
QWidget {{
    background: {DARK_BG};
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI", "SF Pro Text", "Helvetica Neue", sans-serif;
    font-size: 13px;
}}
QMainWindow {{
    background: {DARK_BG};
}}
QGroupBox {{
    background: {DARK_SURFACE};
    border: 1px solid {DARK_BORDER};
    border-radius: 8px;
    margin-top: 10px;
    padding: 10px 12px 12px 12px;
    font-size: 11px;
    font-weight: 600;
    color: {TEXT_MUTED};
    text-transform: uppercase;
    letter-spacing: 0.8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    top: -1px;
    padding: 0 6px;
    background: {DARK_SURFACE};
}}
QPushButton {{
    background: {DARK_RAISED};
    color: {TEXT_PRIMARY};
    border: 1px solid {DARK_BORDER};
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 13px;
}}
QPushButton:hover {{
    background: #383838;
    border-color: #555;
}}
QPushButton:pressed {{
    background: #1f1f1f;
}}
QPushButton:disabled {{
    color: #444;
    border-color: #2a2a2a;
}}
QPushButton#primaryBtn {{
    background: {ACCENT};
    color: white;
    border: none;
    font-weight: 600;
    padding: 8px 24px;
}}
QPushButton#primaryBtn:hover {{
    background: {ACCENT_HOVER};
}}
QPushButton#primaryBtn:disabled {{
    background: #2a3d50;
    color: #456;
}}
QTableWidget {{
    background: {DARK_SURFACE};
    alternate-background-color: {DARK_BG};
    border: 1px solid {DARK_BORDER};
    border-radius: 8px;
    gridline-color: {DARK_BORDER};
    selection-background-color: #1e3a5f;
    selection-color: {TEXT_PRIMARY};
    font-size: 12px;
}}
QTableWidget::item {{
    padding: 4px 8px;
    border: none;
}}
QHeaderView::section {{
    background: {DARK_RAISED};
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {DARK_BORDER};
    border-right: 1px solid {DARK_BORDER};
    padding: 6px 8px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QProgressBar {{
    background: {DARK_RAISED};
    border: none;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 4px;
}}
QComboBox {{
    background: {DARK_RAISED};
    border: 1px solid {DARK_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    min-width: 140px;
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background: {DARK_RAISED};
    border: 1px solid {DARK_BORDER};
    selection-background-color: #1e3a5f;
}}
QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {DARK_RAISED};
    border: 1px solid {DARK_BORDER};
    border-radius: 6px;
    padding: 5px 10px;
    color: {TEXT_PRIMARY};
}}
QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
    border-color: {ACCENT};
}}
QRadioButton {{
    background: transparent;
    spacing: 8px;
}}
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 7px;
    border: 2px solid {DARK_BORDER};
    background: {DARK_RAISED};
}}
QRadioButton::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QCheckBox {{
    background: transparent;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 2px solid {DARK_BORDER};
    background: {DARK_RAISED};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QSlider::groove:horizontal {{
    background: {DARK_RAISED};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 2px;
}}
QScrollBar:vertical {{
    background: {DARK_BG};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {DARK_BORDER};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QStatusBar {{
    background: {DARK_SURFACE};
    border-top: 1px solid {DARK_BORDER};
    color: {TEXT_MUTED};
    font-size: 12px;
    padding: 3px 8px;
}}
QMenuBar {{
    background: {DARK_SURFACE};
    border-bottom: 1px solid {DARK_BORDER};
    padding: 2px;
}}
QMenuBar::item:selected {{
    background: {DARK_RAISED};
    border-radius: 4px;
}}
QMenu {{
    background: {DARK_RAISED};
    border: 1px solid {DARK_BORDER};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: #1e3a5f;
}}
QMenu::separator {{
    height: 1px;
    background: {DARK_BORDER};
    margin: 4px 8px;
}}
QSplitter::handle {{
    background: {DARK_BORDER};
    width: 1px;
}}
QLabel#mutedLabel {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#sectionLabel {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.6px;
}}
"""


# ─────────────────────── Data models ────────────────────────────

class FileStatus(Enum):
    IDLE       = "Queued"
    PROCESSING = "Processing…"
    DONE       = "Done"
    ERROR      = "Error"
    SKIPPED    = "Skipped"

class ResizeMode(Enum):
    DIMENSIONS = "dimensions"
    SCALE      = "scale"
    FILESIZE   = "filesize"

class FitMode(Enum):
    CONTAIN = "Contain (keep ratio)"
    STRETCH = "Stretch (exact)"
    COVER   = "Cover (crop)"
    WIDTH   = "Width only"
    HEIGHT  = "Height only"

class OutputFormat(Enum):
    PNG  = ("PNG (keep animation)", "png",  "image/png")
    WEBP = ("WebP",                 "webp", "image/webp")
    JPEG = ("JPEG (static)",        "jpg",  "image/jpeg")
    GIF  = ("GIF (animation)",      "gif",  "image/gif")

@dataclass
class FileItem:
    path: Path
    status: FileStatus = FileStatus.IDLE
    orig_size: int = 0
    out_size: int = 0
    out_path: Optional[Path] = None
    error_msg: str = ""
    frames: int = 0

    def size_delta_str(self) -> str:
        if self.status != FileStatus.DONE or not self.out_size:
            return "—"
        delta = self.out_size - self.orig_size
        pct = (1 - self.out_size / self.orig_size) * 100 if self.orig_size else 0
        sign = "−" if delta < 0 else "+"
        return f"{sign}{abs(pct):.0f}%"

@dataclass
class ResizeConfig:
    mode: ResizeMode = ResizeMode.DIMENSIONS
    target_w: int = 512
    target_h: int = 512
    fit: FitMode = FitMode.CONTAIN
    scale_pct: float = 50.0
    target_kb: int = 500
    max_iter: int = 8
    out_format: OutputFormat = OutputFormat.PNG
    quality: int = 90
    output_dir: Optional[Path] = None
    suffix: str = "_resized"
    overwrite: bool = False
    preserve_metadata: bool = True


# ─────────────────────── APNG & MP4 per-frame resize ──────────────

def get_png_dimensions(data: bytes):
    """Read width/height from raw PNG bytes."""
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError("Not a PNG")
    w = struct.unpack('>I', data[13:17])[0]
    h = struct.unpack('>I', data[17:21])[0]
    return w, h

def resize_pil_image(img: Image.Image, cfg: ResizeConfig) -> Image.Image:
    ow, oh = img.size
    if cfg.mode == ResizeMode.DIMENSIONS:
        tw, th = cfg.target_w, cfg.target_h
        fit = cfg.fit
        if fit == FitMode.STRETCH:
            nw, nh = tw, th
        elif fit == FitMode.WIDTH:
            nw = tw; nh = max(1, round(oh * tw / ow))
        elif fit == FitMode.HEIGHT:
            nh = th; nw = max(1, round(ow * th / oh))
        elif fit == FitMode.CONTAIN:
            r = min(tw / ow, th / oh)
            nw, nh = max(1, round(ow * r)), max(1, round(oh * r))
        elif fit == FitMode.COVER:
            r = max(tw / ow, th / oh)
            nw, nh = max(1, round(ow * r)), max(1, round(oh * r))
            # crop to exact
            img = img.resize((nw, nh), Image.LANCZOS)
            left = (nw - tw) // 2; top = (nh - th) // 2
            return img.crop((left, top, left + tw, top + th))
        else:
            nw, nh = ow, oh
    elif cfg.mode == ResizeMode.SCALE:
        r = cfg.scale_pct / 100.0
        nw, nh = max(1, round(ow * r)), max(1, round(oh * r))
    else:
        nw, nh = ow, oh  # filesize mode: caller handles iteratively

    return img.resize((nw, nh), Image.LANCZOS)

def frame_to_png_bytes(frame: Image.Image) -> bytes:
    buf = io.BytesIO()
    frame.save(buf, format="PNG", optimize=False)
    return buf.getvalue()

def convert_mp4_to_apng(src_path: Path, cfg: ResizeConfig, out_path: Path) -> int:
    """Reads MP4 frames, resizes them, and builds an APNG."""
    if not HAS_CV2:
        raise RuntimeError("opencv-python library is required to convert MP4 files.")
    if not HAS_APNG:
        raise RuntimeError("apng library not available for export.")

    cap = cv2.VideoCapture(str(src_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0 or math.isnan(fps):
        fps = 30.0

    # APNG delay is represented as a fraction (delay / delay_den) in seconds.
    frac = fractions.Fraction(1.0 / fps).limit_denominator(1000)
    delay = frac.numerator
    delay_den = frac.denominator

    pil_frames = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        # OpenCV reads in BGR, convert to RGBA for consistency with APNG processor
        frame_rgba = cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA)
        img = Image.fromarray(frame_rgba)
        pil_frames.append(img)
    cap.release()

    if not pil_frames:
        raise ValueError("Could not extract any frames from the MP4.")

    frames_out = []

    if cfg.mode == ResizeMode.FILESIZE:
        # Estimate size from scaling the first frame iteratively
        target = cfg.target_kb * 1024
        first_raw = frame_to_png_bytes(pil_frames[0])
        total_est = len(first_raw) * len(pil_frames)
        scale = min(1.0, math.sqrt(target / total_est)) if total_est > 0 else 1.0

        ow, oh = pil_frames[0].size
        for iteration in range(cfg.max_iter):
            nw = max(1, round(ow * scale))
            nh = max(1, round(oh * scale))
            resized_frames = []
            for img in pil_frames:
                resized_frames.append(frame_to_png_bytes(img.resize((nw, nh), Image.LANCZOS)))
            
            total_new = sum(len(f) for f in resized_frames)
            if total_new <= target:
                frames_out = resized_frames
                break
            scale *= math.sqrt(target / total_new) * 0.93
            scale = max(0.05, scale)
        else:
            frames_out = resized_frames  # fallback to best effort
    else:
        for img in pil_frames:
            resized = resize_pil_image(img, cfg)
            frames_out.append(frame_to_png_bytes(resized))

    # Reconstruct as APNG
    new_apng = APNG()
    for raw in frames_out:
        png = PNG.from_bytes(raw)
        new_apng.append(png, delay=delay, delay_den=delay_den)

    new_apng.save(str(out_path))
    return out_path.stat().st_size


def resize_apng_perframe(src_path: Path, cfg: ResizeConfig, out_path: Path) -> int:
    """True per-frame APNG resize using the apng library."""
    if not HAS_APNG:
        raise RuntimeError("apng library not available")

    apng_obj = APNG.open(str(src_path))
    frames_out = []
    delay_pairs = []

    for png_obj, control in apng_obj.frames:
        # Decode PNG bytes → PIL Image
        raw = png_obj.to_bytes()
        img = Image.open(io.BytesIO(raw)).convert("RGBA")

        if cfg.mode == ResizeMode.FILESIZE:
            resized = img  # handled below
        else:
            resized = resize_pil_image(img, cfg)

        new_raw = frame_to_png_bytes(resized)
        frames_out.append(new_raw)
        delay_pairs.append((control.delay, control.delay_den) if control else (1, 10))

    if cfg.mode == ResizeMode.FILESIZE:
        # Estimate scale from total byte count
        total = sum(len(f) for f in frames_out)
        target = cfg.target_kb * 1024
        scale = min(1.0, math.sqrt(target / total)) if total > 0 else 1.0
        first_img = Image.open(io.BytesIO(frames_out[0])).convert("RGBA")
        ow, oh = first_img.size
        for iteration in range(cfg.max_iter):
            nw = max(1, round(ow * scale)); nh = max(1, round(oh * scale))
            resized_frames = []
            for raw in frames_out:
                img = Image.open(io.BytesIO(raw)).convert("RGBA")
                img = img.resize((nw, nh), Image.LANCZOS)
                resized_frames.append(frame_to_png_bytes(img))
            total_new = sum(len(f) for f in resized_frames)
            if total_new <= target:
                frames_out = resized_frames
                break
            scale *= math.sqrt(target / total_new) * 0.93
            scale = max(0.05, scale)
        else:
            frames_out = resized_frames  # best effort

    # Reconstruct APNG
    new_apng = APNG()
    for raw, (delay, delay_den) in zip(frames_out, delay_pairs):
        png = PNG.from_bytes(raw)
        new_apng.append(png, delay=delay, delay_den=delay_den)

    new_apng.save(str(out_path))
    return out_path.stat().st_size

def resize_static(src_path: Path, cfg: ResizeConfig, out_path: Path) -> int:
    """Resize a static PNG/image (or export first frame) via Pillow."""
    img = Image.open(src_path)

    if cfg.mode == ResizeMode.FILESIZE:
        # Iterative scale
        target = cfg.target_kb * 1024
        ow, oh = img.size
        scale = 1.0
        for _ in range(cfg.max_iter):
            nw = max(1, round(ow * scale)); nh = max(1, round(oh * scale))
            resized = img.resize((nw, nh), Image.LANCZOS)
            buf = io.BytesIO()
            fmt = cfg.out_format.value[1].upper()
            if fmt == "JPG": fmt = "JPEG"
            save_kw = {}
            if fmt in ("JPEG", "WEBP"):
                save_kw["quality"] = cfg.quality
            resized.save(buf, format=fmt, **save_kw)
            if buf.tell() <= target:
                break
            scale *= math.sqrt(target / buf.tell()) * 0.93
            scale = max(0.05, scale)
        buf.seek(0)
        out_path.write_bytes(buf.read())
    else:
        resized = resize_pil_image(img, cfg)
        fmt = cfg.out_format.value[1].upper()
        if fmt == "JPG": fmt = "JPEG"
        save_kw = {}
        if fmt in ("JPEG", "WEBP"):
            save_kw["quality"] = cfg.quality
        if fmt == "JPEG" and resized.mode in ("RGBA", "P"):
            resized = resized.convert("RGB")
        resized.save(out_path, format=fmt, **save_kw)

    return out_path.stat().st_size


def process_file(item: FileItem, cfg: ResizeConfig, out_dir: Path) -> FileItem:
    """Process a single file. Returns updated item."""
    try:
        src = item.path
        ext = cfg.out_format.value[1]
        
        is_mp4 = src.suffix.lower() == ".mp4"

        # If MP4, user must output as APNG via this specific flow
        if is_mp4 and cfg.out_format == OutputFormat.PNG:
            ext = "png"
            
        stem = src.stem + cfg.suffix
        out_path = out_dir / f"{stem}.{ext}"

        # Avoid collisions
        if not cfg.overwrite and out_path.exists():
            counter = 1
            while out_path.exists():
                out_path = out_dir / f"{stem}_{counter}.{ext}"
                counter += 1

        if is_mp4:
            if cfg.out_format != OutputFormat.PNG:
                raise ValueError("MP4 conversion currently only supports PNG (APNG) output format.")
            item.out_size = convert_mp4_to_apng(src, cfg, out_path)
            item.status = FileStatus.DONE
            item.out_path = out_path
            return item

        # Detect APNG: check for acTL/fcTL chunks (bounded read — first 64 KB)
        is_apng = False
        try:
            HEADER_READ = 65536  # 64 KB — enough for any valid APNG header
            with open(src, 'rb') as fh:
                data = fh.read(HEADER_READ)
            if b'acTL' in data or b'fcTL' in data:
                is_apng = True
        except Exception:
            pass

        if is_apng and HAS_APNG and cfg.out_format == OutputFormat.PNG:
            # Open to count frames
            apng_obj = APNG.open(str(src))
            item.frames = len(apng_obj.frames)
            item.out_size = resize_apng_perframe(src, cfg, out_path)
        else:
            if is_apng:
                img = Image.open(src)
                item.frames = getattr(img, 'n_frames', 1)
            item.out_size = resize_static(src, cfg, out_path)
            if not is_apng:
                img = Image.open(src)
                item.frames = getattr(img, 'n_frames', 1)

        item.out_path = out_path
        item.status = FileStatus.DONE
    except Exception as e:
        item.status = FileStatus.ERROR
        item.error_msg = str(e)

    return item


# ─────────────────────── Worker thread ─────────────────────────

class WorkerSignals(QObject):
    progress   = pyqtSignal(int, FileItem)   # row, updated item
    finished   = pyqtSignal()
    status_msg = pyqtSignal(str)

class BatchWorker(QThread):
    progress   = pyqtSignal(int, object)
    finished   = pyqtSignal()
    status_msg = pyqtSignal(str)

    def __init__(self, items: List[FileItem], cfg: ResizeConfig, out_dir: Path):
        super().__init__()
        self.items   = items
        self.cfg     = cfg
        self.out_dir = out_dir
        self._abort  = False

    def abort(self):
        self._abort = True

    def run(self):
        for i, item in enumerate(self.items):
            if self._abort:
                break
            item.status = FileStatus.PROCESSING
            self.progress.emit(i, item)
            self.status_msg.emit(f"Processing {item.path.name} …")
            updated = process_file(item, self.cfg, self.out_dir)
            self.items[i] = updated
            self.progress.emit(i, updated)
        self.status_msg.emit("Batch complete.")
        self.finished.emit()


# ─────────────────────── Drop zone widget ──────────────────────

class DropZone(QFrame):
    files_dropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(90)
        self.setFrameShape(QFrame.NoFrame)
        self._hovered = False

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)

        icon = QLabel("⬆")
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"font-size: 28px; color: {TEXT_MUTED}; background: transparent;")

        self.label = QLabel("Drop APNG / PNG / MP4 files here")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet(f"font-size: 13px; color: {TEXT_MUTED}; background: transparent;")

        sub = QLabel("or use File → Add Files")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(f"font-size: 11px; color: #555; background: transparent;")

        layout.addWidget(icon)
        layout.addWidget(self.label)
        layout.addWidget(sub)
        self._update_style()

    def _update_style(self):
        border_color = ACCENT if self._hovered else DARK_BORDER
        bg = "#1e2e3e" if self._hovered else DARK_SURFACE
        self.setStyleSheet(f"""
            QFrame {{
                background: {bg};
                border: 1.5px dashed {border_color};
                border-radius: 8px;
            }}
        """)

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._hovered = True
            self._update_style()

    def dragLeaveEvent(self, e):
        self._hovered = False
        self._update_style()

    def dropEvent(self, e: QDropEvent):
        self._hovered = False
        self._update_style()
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls()
                 if u.toLocalFile().lower().endswith(('.apng', '.png', '.mp4'))]
        if paths:
            self.files_dropped.emit(paths)


# ─────────────────────── Status dot delegate ───────────────────

STATUS_COLORS = {
    FileStatus.IDLE:       IDLE_DOT,
    FileStatus.PROCESSING: WARNING,
    FileStatus.DONE:       SUCCESS,
    FileStatus.ERROR:      ERROR,
    FileStatus.SKIPPED:    TEXT_MUTED,
}

def fmt_bytes(n: int) -> str:
    if n == 0: return "—"
    if n < 1024: return f"{n} B"
    if n < 1048576: return f"{n/1024:.0f} KB"
    return f"{n/1048576:.1f} MB"


# ─────────────────────── Settings panel ────────────────────────

class SettingsPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setMaximumWidth(280)
        self.setMinimumWidth(240)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # ── Resize mode ──
        mode_grp = QGroupBox("Resize Mode")
        ml = QVBoxLayout(mode_grp)
        ml.setSpacing(8)

        self.mode_group = QButtonGroup(self)
        self.rb_dim  = QRadioButton("By dimensions")
        self.rb_scl  = QRadioButton("By scale %")
        self.rb_size = QRadioButton("By target file size")
        self.rb_dim.setChecked(True)
        for i, rb in enumerate([self.rb_dim, self.rb_scl, self.rb_size]):
            self.mode_group.addButton(rb, i)
            ml.addWidget(rb)

        self.mode_group.buttonClicked.connect(self._on_mode_change)
        root.addWidget(mode_grp)

        # ── Dimensions ──
        self.dim_grp = QGroupBox("Dimensions")
        dl = QVBoxLayout(self.dim_grp)
        dl.setSpacing(8)

        wr = QHBoxLayout()
        wr.addWidget(QLabel("Width"))
        self.spin_w = QSpinBox(); self.spin_w.setRange(1, 16384); self.spin_w.setValue(512); self.spin_w.setSuffix(" px")
        wr.addWidget(self.spin_w)
        dl.addLayout(wr)

        hr = QHBoxLayout()
        hr.addWidget(QLabel("Height"))
        self.spin_h = QSpinBox(); self.spin_h.setRange(1, 16384); self.spin_h.setValue(512); self.spin_h.setSuffix(" px")
        hr.addWidget(self.spin_h)
        dl.addLayout(hr)

        dl.addWidget(QLabel("Fit mode"))
        self.combo_fit = QComboBox()
        for fm in FitMode:
            self.combo_fit.addItem(fm.value, fm)
        dl.addWidget(self.combo_fit)
        root.addWidget(self.dim_grp)

        # ── Scale ──
        self.scl_grp = QGroupBox("Scale")
        sl = QVBoxLayout(self.scl_grp)
        self.scale_label = QLabel("Scale: 50%")
        sl.addWidget(self.scale_label)
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(5, 200); self.scale_slider.setValue(50); self.scale_slider.setSingleStep(5)
        self.scale_slider.valueChanged.connect(lambda v: self.scale_label.setText(f"Scale: {v}%"))
        sl.addWidget(self.scale_slider)
        note = QLabel("< 100% shrinks, > 100% enlarges")
        note.setObjectName("mutedLabel"); note.setWordWrap(True)
        sl.addWidget(note)
        self.scl_grp.setVisible(False)
        root.addWidget(self.scl_grp)

        # ── File size ──
        self.fsz_grp = QGroupBox("Target File Size")
        fl = QVBoxLayout(self.fsz_grp)
        fl.setSpacing(8)

        kr = QHBoxLayout()
        kr.addWidget(QLabel("Target KB"))
        self.spin_kb = QSpinBox(); self.spin_kb.setRange(10, 102400); self.spin_kb.setValue(500); self.spin_kb.setSuffix(" KB")
        kr.addWidget(self.spin_kb)
        fl.addLayout(kr)

        ir = QHBoxLayout()
        ir.addWidget(QLabel("Max iterations"))
        self.spin_iter = QSpinBox(); self.spin_iter.setRange(1, 20); self.spin_iter.setValue(8)
        ir.addWidget(self.spin_iter)
        fl.addLayout(ir)

        note2 = QLabel("Iteratively scales until under target.")
        note2.setObjectName("mutedLabel"); note2.setWordWrap(True)
        fl.addWidget(note2)
        self.fsz_grp.setVisible(False)
        root.addWidget(self.fsz_grp)

        # ── Output format ──
        fmt_grp = QGroupBox("Output")
        fml = QVBoxLayout(fmt_grp)
        fml.setSpacing(8)

        fml.addWidget(QLabel("Format"))
        self.combo_fmt = QComboBox()
        for fmt in OutputFormat:
            self.combo_fmt.addItem(fmt.value[0], fmt)
        fml.addWidget(self.combo_fmt)

        qr = QHBoxLayout()
        qr.addWidget(QLabel("Quality"))
        self.spin_q = QSpinBox(); self.spin_q.setRange(1, 100); self.spin_q.setValue(90); self.spin_q.setSuffix("%")
        qr.addWidget(self.spin_q)
        fml.addLayout(qr)

        fml.addWidget(QLabel("Filename suffix"))
        self.suffix_edit = QLineEdit("_resized")
        fml.addWidget(self.suffix_edit)

        self.chk_overwrite = QCheckBox("Overwrite existing files")
        fml.addWidget(self.chk_overwrite)

        root.addWidget(fmt_grp)

        # ── Output dir ──
        dir_grp = QGroupBox("Output Directory")
        dirl = QVBoxLayout(dir_grp)
        self.dir_label = QLabel("Same as source")
        self.dir_label.setObjectName("mutedLabel")
        self.dir_label.setWordWrap(True)
        dirl.addWidget(self.dir_label)

        dir_btns = QHBoxLayout()
        self.btn_pick_dir = QPushButton("Choose…")
        self.btn_pick_dir.clicked.connect(self._pick_dir)
        self.btn_clear_dir = QPushButton("Clear")
        self.btn_clear_dir.clicked.connect(self._clear_dir)
        dir_btns.addWidget(self.btn_pick_dir)
        dir_btns.addWidget(self.btn_clear_dir)
        dirl.addLayout(dir_btns)
        root.addWidget(dir_grp)

        root.addStretch()
        self._out_dir: Optional[Path] = None

    @staticmethod
    def _sanitize_suffix(raw: str) -> str:
        """Strip characters that could cause path traversal or invalid filenames."""
        import re
        # Remove path separators, null bytes, and leading dots beyond one level
        safe = re.sub(r'[/\\:\0*?"<>|]', '', raw)
        # Collapse any remaining dots-only sequences (e.g. '..') to nothing
        safe = re.sub(r'\.{2,}', '', safe)
        return safe if safe else "_resized"

    def _on_mode_change(self, btn):
        mid = self.mode_group.id(btn)
        self.dim_grp.setVisible(mid == 0)
        self.scl_grp.setVisible(mid == 1)
        self.fsz_grp.setVisible(mid == 2)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select output directory")
        if d:
            self._out_dir = Path(d)
            self.dir_label.setText(str(self._out_dir))

    def _clear_dir(self):
        self._out_dir = None
        self.dir_label.setText("Same as source")

    def get_config(self) -> ResizeConfig:
        mode_id = self.mode_group.checkedId()
        mode = [ResizeMode.DIMENSIONS, ResizeMode.SCALE, ResizeMode.FILESIZE][mode_id]
        fit  = self.combo_fit.currentData()
        fmt  = self.combo_fmt.currentData()
        return ResizeConfig(
            mode       = mode,
            target_w   = self.spin_w.value(),
            target_h   = self.spin_h.value(),
            fit        = fit,
            scale_pct  = float(self.scale_slider.value()),
            target_kb  = self.spin_kb.value(),
            max_iter   = self.spin_iter.value(),
            out_format = fmt,
            quality    = self.spin_q.value(),
            output_dir = self._out_dir,
            suffix     = self._sanitize_suffix(self.suffix_edit.text()),
            overwrite  = self.chk_overwrite.isChecked(),
        )


# ─────────────────────── File table ────────────────────────────

COL_STATUS  = 0
COL_NAME    = 1
COL_FRAMES  = 2
COL_ORIG    = 3
COL_OUT     = 4
COL_DELTA   = 5
HEADERS = ["", "Filename", "Frames", "Original", "Output", "Δ Size"]

class FileTable(QTableWidget):
    def __init__(self):
        super().__init__(0, len(HEADERS))
        self.setHorizontalHeaderLabels(HEADERS)
        self.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for c in [COL_STATUS, COL_FRAMES, COL_ORIG, COL_OUT, COL_DELTA]:
            self.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.setColumnWidth(COL_STATUS, 14)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(True)
        self.setContextMenuPolicy(Qt.ActionsContextMenu)
        self.setDragDropMode(QAbstractItemView.NoDragDrop)

    def populate_row(self, row: int, item: FileItem):
        # Status dot
        dot_label = QLabel()
        dot_label.setFixedSize(10, 10)
        color = STATUS_COLORS.get(item.status, IDLE_DOT)
        dot_label.setStyleSheet(f"background:{color}; border-radius:5px;")
        dot_label.setToolTip(item.status.value)
        cell_w = QWidget()
        cell_l = QHBoxLayout(cell_w)
        cell_l.setContentsMargins(4,0,0,0)
        cell_l.addWidget(dot_label)
        self.setCellWidget(row, COL_STATUS, cell_w)

        def _item(text, align=Qt.AlignLeft, tooltip=""):
            qi = QTableWidgetItem(text)
            qi.setTextAlignment(align | Qt.AlignVCenter)
            if tooltip: qi.setToolTip(tooltip)
            return qi

        self.setItem(row, COL_NAME,   _item(item.path.name, tooltip=str(item.path)))
        self.setItem(row, COL_FRAMES, _item(str(item.frames) if item.frames else "—", Qt.AlignCenter))
        self.setItem(row, COL_ORIG,   _item(fmt_bytes(item.orig_size), Qt.AlignRight))

        if item.status == FileStatus.DONE:
            self.setItem(row, COL_OUT,   _item(fmt_bytes(item.out_size), Qt.AlignRight))
            delta = item.size_delta_str()
            di = _item(delta, Qt.AlignRight)
            # Colour delta: green = saved, red = grew
            if item.out_size < item.orig_size:
                di.setForeground(QColor(SUCCESS))
            elif item.out_size > item.orig_size:
                di.setForeground(QColor(ERROR))
            self.setItem(row, COL_DELTA, di)
        elif item.status == FileStatus.ERROR:
            ei = _item(item.error_msg or "Error", tooltip=item.error_msg)
            ei.setForeground(QColor(ERROR))
            self.setItem(row, COL_OUT,   ei)
            self.setItem(row, COL_DELTA, _item(""))
        elif item.status == FileStatus.PROCESSING:
            pi = _item("Processing…")
            pi.setForeground(QColor(WARNING))
            self.setItem(row, COL_OUT,   pi)
            self.setItem(row, COL_DELTA, _item(""))
        else:
            self.setItem(row, COL_OUT,   _item("—", Qt.AlignRight))
            self.setItem(row, COL_DELTA, _item("—", Qt.AlignRight))

        self.setRowHeight(row, 28)


# ─────────────────────── Stats bar ─────────────────────────────

class StatsBar(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(24)
        self._labels = {}
        for key, default in [("Total", "0"), ("Done", "0"), ("Errors", "0"), ("Avg reduction", "—")]:
            vl = QVBoxLayout()
            vl.setSpacing(1)
            lbl = QLabel(key)
            lbl.setObjectName("sectionLabel")
            val = QLabel(default)
            val.setStyleSheet("font-size: 22px; font-weight: 600;")
            vl.addWidget(lbl)
            vl.addWidget(val)
            layout.addLayout(vl)
            self._labels[key] = val
        layout.addStretch()

    def update(self, items: List[FileItem]):
        total = len(items)
        done  = sum(1 for i in items if i.status == FileStatus.DONE)
        err   = sum(1 for i in items if i.status == FileStatus.ERROR)
        reds  = [(1 - i.out_size / i.orig_size) * 100
                 for i in items if i.status == FileStatus.DONE and i.orig_size]
        avg   = f"{sum(reds)/len(reds):.0f}%" if reds else "—"
        self._labels["Total"].setText(str(total))
        self._labels["Done"].setText(str(done))
        self._labels["Errors"].setText(str(err))
        self._labels["Avg reduction"].setText(avg)


# ─────────────────────── Main window ───────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("APNG Bulk Downsizer")
        self.resize(1020, 700)
        self.setMinimumSize(700, 500)

        self._items: List[FileItem] = []
        self._worker: Optional[BatchWorker] = None

        self._build_menu()
        self._build_ui()
        self._build_status_bar()

    def _build_menu(self):
        mb = self.menuBar()
        file_m = mb.addMenu("File")

        a_add = QAction("Add Files…", self)
        a_add.setShortcut("Ctrl+O")
        a_add.triggered.connect(self._add_files_dialog)
        file_m.addAction(a_add)

        a_dir = QAction("Add Folder…", self)
        a_dir.setShortcut("Ctrl+Shift+O")
        a_dir.triggered.connect(self._add_folder_dialog)
        file_m.addAction(a_dir)

        file_m.addSeparator()

        a_clear = QAction("Clear Queue", self)
        a_clear.triggered.connect(self._clear_queue)
        file_m.addAction(a_clear)

        file_m.addSeparator()

        a_quit = QAction("Quit", self)
        a_quit.setShortcut("Ctrl+Q")
        a_quit.triggered.connect(self.close)
        file_m.addAction(a_quit)

        batch_m = mb.addMenu("Batch")

        self.a_process = QAction("Process Queue", self)
        self.a_process.setShortcut("Ctrl+Return")
        self.a_process.triggered.connect(self._start_batch)
        self.a_process.setEnabled(False)
        batch_m.addAction(self.a_process)

        self.a_stop = QAction("Stop", self)
        self.a_stop.setShortcut("Escape")
        self.a_stop.triggered.connect(self._stop_batch)
        self.a_stop.setEnabled(False)
        batch_m.addAction(self.a_stop)

        batch_m.addSeparator()

        a_reveal = QAction("Reveal Output Folder", self)
        a_reveal.triggered.connect(self._reveal_output)
        batch_m.addAction(a_reveal)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(10)

        # Drop zone
        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self._add_paths)
        root.addWidget(self.drop_zone)

        # Splitter: table | settings
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)

        self.table = FileTable()
        ll.addWidget(self.table)

        # Table context actions
        self.act_remove = QAction("Remove selected", self.table)
        self.act_remove.triggered.connect(self._remove_selected)
        self.table.addAction(self.act_remove)

        self.act_open = QAction("Open output file", self.table)
        self.act_open.triggered.connect(self._open_selected_output)
        self.table.addAction(self.act_open)

        self.act_retry = QAction("Retry selected", self.table)
        self.act_retry.triggered.connect(self._retry_selected)
        self.table.addAction(self.act_retry)

        # Stats
        self.stats = StatsBar()
        ll.addWidget(self.stats)

        # Progress
        prog_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setMaximumHeight(6)
        prog_row.addWidget(self.progress)
        ll.addLayout(prog_row)

        # Action buttons
        btn_row = QHBoxLayout()
        self.btn_process = QPushButton("▶  Process Batch")
        self.btn_process.setObjectName("primaryBtn")
        self.btn_process.setEnabled(False)
        self.btn_process.clicked.connect(self._start_batch)
        btn_row.addWidget(self.btn_process)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_batch)
        btn_row.addWidget(self.btn_stop)

        self.btn_download_all = QPushButton("⬇  Download All Outputs")
        self.btn_download_all.setEnabled(False)
        self.btn_download_all.clicked.connect(self._reveal_output)
        btn_row.addWidget(self.btn_download_all)

        btn_row.addStretch()

        self.btn_clear = QPushButton("Clear Queue")
        self.btn_clear.clicked.connect(self._clear_queue)
        btn_row.addWidget(self.btn_clear)

        ll.addLayout(btn_row)
        splitter.addWidget(left)

        # Settings panel (right)
        self.settings = SettingsPanel()
        splitter.addWidget(self.settings)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([720, 260])
        root.addWidget(splitter)

    def _build_status_bar(self):
        self.sb = QStatusBar()
        self.setStatusBar(self.sb)
        self.sb.showMessage("Ready — drop APNG/PNG/MP4 files to begin")

        apng_label = QLabel(f"apng lib: {'✓' if HAS_APNG else '✗'}")
        apng_label.setStyleSheet(f"color: {SUCCESS if HAS_APNG else WARNING}; padding-right: 8px;")
        
        cv2_label = QLabel(f"cv2 (MP4): {'✓' if HAS_CV2 else '✗'}")
        cv2_label.setStyleSheet(f"color: {SUCCESS if HAS_CV2 else WARNING}; padding-right: 8px;")
        
        self.sb.addPermanentWidget(apng_label)
        self.sb.addPermanentWidget(cv2_label)

    # ── File management ──────────────────────────────────────

    def _add_files_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add APNG / PNG / MP4 files", "",
            "Images / Video (*.png *.apng *.mp4);;All Files (*)"
        )
        self._add_paths([Path(p) for p in paths])

    def _add_folder_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "Add folder (scans recursively)")
        if d:
            paths = list(Path(d).rglob("*.png")) + list(Path(d).rglob("*.apng")) + list(Path(d).rglob("*.mp4"))
            self._add_paths(paths)

    def _add_paths(self, paths: List[Path]):
        existing = {(i.path.name, i.path.stat().st_size) for i in self._items}
        added = 0
        for p in paths:
            if not p.exists(): continue
            key = (p.name, p.stat().st_size)
            if key in existing: continue
            existing.add(key)
            item = FileItem(path=p, orig_size=p.stat().st_size)
            # Quick frame count
            try:
                if p.suffix.lower() == ".mp4":
                    if HAS_CV2:
                        cap = cv2.VideoCapture(str(p))
                        item.frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                        cap.release()
                    else:
                        item.frames = 0
                else:
                    img = Image.open(p)
                    item.frames = getattr(img, 'n_frames', 1)
            except Exception:
                item.frames = 0
            self._items.append(item)
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.populate_row(row, item)
            added += 1

        if added:
            self._refresh_ui()
            self.sb.showMessage(f"Added {added} file(s). Queue: {len(self._items)}")

    def _clear_queue(self):
        if self._worker and self._worker.isRunning():
            return
        self._items.clear()
        self.table.setRowCount(0)
        self._refresh_ui()
        self.sb.showMessage("Queue cleared.")

    def _remove_selected(self):
        rows = sorted(set(i.row() for i in self.table.selectedItems()), reverse=True)
        for row in rows:
            self.table.removeRow(row)
            del self._items[row]
        self._refresh_ui()

    def _retry_selected(self):
        rows = set(i.row() for i in self.table.selectedItems())
        for row in rows:
            if self._items[row].status in (FileStatus.ERROR, FileStatus.DONE):
                self._items[row].status = FileStatus.IDLE
                self._items[row].out_size = 0
                self._items[row].out_path = None
                self._items[row].error_msg = ""
                self.table.populate_row(row, self._items[row])
        self._refresh_ui()

    def _open_selected_output(self):
        rows = set(i.row() for i in self.table.selectedItems())
        for row in rows:
            item = self._items[row]
            if item.out_path and item.out_path.exists():
                import subprocess, platform
                if platform.system() == "Darwin":
                    subprocess.run(["open", str(item.out_path)])
                elif platform.system() == "Windows":
                    os.startfile(str(item.out_path))
                else:
                    subprocess.run(["xdg-open", str(item.out_path)])

    def _reveal_output(self):
        done = [i for i in self._items if i.out_path and i.out_path.exists()]
        if not done:
            self.sb.showMessage("No output files yet.")
            return
        # Reveal the first output's parent folder
        out_dir = done[0].out_path.parent
        import subprocess, platform
        if platform.system() == "Darwin":
            subprocess.run(["open", str(out_dir)])
        elif platform.system() == "Windows":
            subprocess.run(["explorer", str(out_dir)])
        else:
            subprocess.run(["xdg-open", str(out_dir)])

    # ── Batch processing ──────────────────────────────────────

    def _start_batch(self):
        pending = [i for i in self._items if i.status == FileStatus.IDLE]
        if not pending:
            self.sb.showMessage("No queued files to process.")
            return

        cfg = self.settings.get_config()

        self.progress.setVisible(True)
        self.progress.setMaximum(len(pending))
        self.progress.setValue(0)

        self._worker = BatchWorker(pending, cfg, cfg.output_dir or pending[0].path.parent)
        self._worker.progress.connect(self._on_file_progress)
        self._worker.finished.connect(self._on_batch_done)
        self._worker.status_msg.connect(self.sb.showMessage)
        self._worker.start()

        self._set_running(True)

    def _stop_batch(self):
        if self._worker:
            self._worker.abort()
            self.sb.showMessage("Stopping…")

    def _on_file_progress(self, worker_idx: int, item: FileItem):
        # Find row by matching original path
        for row in range(len(self._items)):
            if self._items[row].path == item.path:
                self._items[row] = item
                self.table.populate_row(row, item)
                if item.status in (FileStatus.DONE, FileStatus.ERROR, FileStatus.SKIPPED):
                    done = sum(1 for i in self._items if i.status in (FileStatus.DONE, FileStatus.ERROR, FileStatus.SKIPPED))
                    self.progress.setValue(done)
                break
        self.stats.update(self._items)

    def _on_batch_done(self):
        self._set_running(False)
        self.progress.setVisible(False)
        self.stats.update(self._items)
        self._refresh_ui()
        done = sum(1 for i in self._items if i.status == FileStatus.DONE)
        err  = sum(1 for i in self._items if i.status == FileStatus.ERROR)
        self.sb.showMessage(f"Done — {done} succeeded, {err} errors.")

    def _set_running(self, running: bool):
        self.btn_process.setEnabled(not running)
        self.a_process.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        self.a_stop.setEnabled(running)
        self.drop_zone.setEnabled(not running)

    def _refresh_ui(self):
        has_items = len(self._items) > 0
        has_pending = any(i.status == FileStatus.IDLE for i in self._items)
        has_done = any(i.status == FileStatus.DONE for i in self._items)
        self.btn_process.setEnabled(has_pending)
        self.a_process.setEnabled(has_pending)
        self.btn_clear.setEnabled(has_items)
        self.btn_download_all.setEnabled(has_done)
        self.stats.update(self._items)


# ─────────────────────── Entry point ───────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("APNG Bulk Downsizer")
    app.setOrganizationName("local")
    app.setStyleSheet(STYLESHEET)

    # Set palette for deeper dark mode
    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(DARK_BG))
    palette.setColor(QPalette.WindowText,      QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Base,            QColor(DARK_SURFACE))
    palette.setColor(QPalette.AlternateBase,   QColor(DARK_BG))
    palette.setColor(QPalette.Text,            QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Button,          QColor(DARK_RAISED))
    palette.setColor(QPalette.ButtonText,      QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.Highlight,       QColor("#1e3a5f"))
    palette.setColor(QPalette.HighlightedText, QColor(TEXT_PRIMARY))
    palette.setColor(QPalette.ToolTipBase,     QColor(DARK_RAISED))
    palette.setColor(QPalette.ToolTipText,     QColor(TEXT_PRIMARY))
    app.setPalette(palette)

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()