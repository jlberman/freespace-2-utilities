"""
APNG Batch Combiner
Combines a batch of APNG files with a target APNG and exports individual new files.
Output plays sequentially: each batch APNG plays fully, then the target plays fully.
Individual files in the batch list can be toggled on/off before running.

Requirements:
    pip install apng Pillow
"""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    from apng import APNG
except ImportError:
    raise SystemExit("Missing dependency: run  pip install apng Pillow  then retry.")


# ─────────────────────────────────────────────────────────────────────────────
# Core logic
# ─────────────────────────────────────────────────────────────────────────────

# Default delay for frames that have no timing info (100ms = 10fps)
DEFAULT_DELAY     = 10   # numerator
DEFAULT_DELAY_DEN = 100  # denominator  →  10/100 = 100 ms


def _frame_kwargs(control) -> dict:
    """
    Return the keyword args needed to re-append a frame, preserving its
    original timing.  Falls back to a sensible default when the source PNG
    carries no explicit control chunk (e.g. a plain static PNG).
    """
    if control is None:
        return {
            "delay":     DEFAULT_DELAY,
            "delay_den": DEFAULT_DELAY_DEN,
            "depose_op": 1,   # APNG_DISPOSE_OP_BACKGROUND
            "blend_op":  0,   # APNG_BLEND_OP_SOURCE
        }
    return {
        "delay":     control.delay,
        "delay_den": control.delay_den,
        "depose_op": control.depose_op,
        "blend_op":  control.blend_op,
    }


MERGE_MODES = ["batch → target", "target → batch", "interleave"]


def combine_apng(target_path: str, batch_path: str, mode: str, batch_speed: float = 1.0) -> APNG:
    target   = APNG.open(target_path)
    batch    = APNG.open(batch_path)
    t_frames = list(target.frames)
    b_frames = list(batch.frames)

    def _sped_up(png, control) -> tuple:
        """Return (png, kwargs) with delay scaled by batch_speed."""
        kw = _frame_kwargs(control)
        if batch_speed != 1.0 and batch_speed > 0:
            # delay / delay_den = seconds per frame; dividing delay by speed shortens it.
            # We keep delay_den fixed and scale the numerator down.
            new_delay = max(1, round(kw["delay"] / batch_speed))
            kw["delay"] = new_delay
        return png, kw

    if mode == "batch → target":
        merged_b = [_sped_up(p, c) for p, c in b_frames]
        merged_t = [(p, _frame_kwargs(c)) for p, c in t_frames]
        merged = merged_b + merged_t
    elif mode == "target → batch":
        merged_t = [(p, _frame_kwargs(c)) for p, c in t_frames]
        merged_b = [_sped_up(p, c) for p, c in b_frames]
        merged = merged_t + merged_b
    elif mode == "interleave":
        merged = []
        for i in range(max(len(t_frames), len(b_frames))):
            if i < len(t_frames):
                p, c = t_frames[i]
                merged.append((p, _frame_kwargs(c)))
            if i < len(b_frames):
                merged.append(_sped_up(*b_frames[i]))
    else:
        raise ValueError(f"Unknown mode: {mode}")

    result = APNG()
    for png, kw in merged:
        result.append(png, **kw)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────────────────────────────────────

class APNGCombinerApp(tk.Tk):
    PAD   = 10
    BTN_W = 14

    BG        = "#1a1a2e"
    PANEL     = "#16213e"
    ACCENT    = "#0f3460"
    HIGHLIGHT = "#e94560"
    FG        = "#eaeaea"
    FG_DIM    = "#888aaa"
    ENTRY_BG  = "#0d1b2a"
    CHECK_ON  = "#4caf7d"
    ROW_ODD   = "#0d1b2a"
    ROW_EVEN  = "#111827"
    ROW_SEL   = "#1e3a5f"

    def __init__(self):
        super().__init__()
        self.title("APNG Batch Combiner")
        self.resizable(True, True)
        self.configure(bg=self.BG)
        self.minsize(760, 600)

        # Each entry: {"path": str, "enabled": BooleanVar, "row_frame": Frame, "check": Checkbutton}
        self._batch_entries: list[dict] = []

        self._target_path = tk.StringVar()
        self._output_dir  = tk.StringVar()
        self._merge_mode  = tk.StringVar(value="batch → target")
        self._prefix      = tk.StringVar(value="combined_")
        self._batch_speed = tk.DoubleVar(value=1.5)
        self._status      = tk.StringVar(value="Ready.")
        self._progress    = tk.DoubleVar(value=0.0)

        self._build_styles()
        self._build_ui()

    # ── Styles ────────────────────────────────────────────────────────────────

    def _build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("TFrame",       background=self.BG)
        style.configure("TLabel",
            background=self.BG, foreground=self.FG,
            font=("Courier New", 10))
        style.configure("Header.TLabel",
            background=self.BG, foreground=self.HIGHLIGHT,
            font=("Courier New", 13, "bold"))
        style.configure("Dim.TLabel",
            background=self.BG, foreground=self.FG_DIM,
            font=("Courier New", 9))
        style.configure("Status.TLabel",
            background=self.BG, foreground=self.FG_DIM,
            font=("Courier New", 9, "italic"))
        style.configure("TButton",
            background=self.ACCENT, foreground=self.FG,
            font=("Courier New", 10, "bold"),
            borderwidth=0, focusthickness=0, padding=(8, 5))
        style.map("TButton",
            background=[("active", self.HIGHLIGHT)],
            foreground=[("active", "#ffffff")])
        style.configure("Run.TButton",
            background=self.HIGHLIGHT, foreground="#ffffff",
            font=("Courier New", 11, "bold"), padding=(10, 7))
        style.map("Run.TButton",
            background=[("active", "#c73652"), ("disabled", "#444")])
        style.configure("TRadiobutton",
            background=self.BG, foreground=self.FG,
            font=("Courier New", 10))
        style.map("TRadiobutton", background=[("active", self.BG)])
        style.configure("TEntry",
            fieldbackground=self.ENTRY_BG, foreground=self.FG,
            insertcolor=self.FG, font=("Courier New", 10))
        style.configure("green.Horizontal.TProgressbar",
            troughcolor=self.PANEL, background=self.HIGHLIGHT, thickness=6)
        style.configure("TLabelframe",
            background=self.BG, foreground=self.FG_DIM,
            font=("Courier New", 9))
        style.configure("TLabelframe.Label",
            background=self.BG, foreground=self.FG_DIM,
            font=("Courier New", 9, "italic"))
        style.configure("TScrollbar",
            troughcolor=self.PANEL, background=self.ACCENT,
            borderwidth=0, arrowsize=12)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        P = self.PAD

        # Title
        hdr = ttk.Frame(self, padding=(P, P, P, 4))
        hdr.pack(fill="x")
        ttk.Label(hdr, text="◈  APNG Batch Combiner", style="Header.TLabel").pack(side="left")
        ttk.Label(hdr, text="sequential playback · export", style="Dim.TLabel").pack(side="left", padx=12)
        tk.Frame(self, bg=self.HIGHLIGHT, height=1).pack(fill="x", padx=P)

        # Body
        body = ttk.Frame(self, padding=P)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, P))
        left.rowconfigure(1, weight=1)
        self._build_target_section(left)
        self._build_batch_section(left)

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        self._build_options_section(right)
        self._build_output_section(right)

        # Bottom bar
        tk.Frame(self, bg=self.ACCENT, height=1).pack(fill="x", padx=P)
        btm = ttk.Frame(self, padding=(P, 6, P, P))
        btm.pack(fill="x")
        ttk.Button(btm, text="▶  Run", style="Run.TButton",
                   command=self._run_batch).pack(side="right")
        ttk.Button(btm, text="✕  Clear All",
                   command=self._clear_all).pack(side="right", padx=(0, 6))
        ttk.Progressbar(btm, variable=self._progress, maximum=100,
                        style="green.Horizontal.TProgressbar",
                        length=200).pack(side="left", padx=(0, P))
        ttk.Label(btm, textvariable=self._status, style="Status.TLabel").pack(side="left")

    def _build_target_section(self, parent):
        P = self.PAD
        lf = ttk.LabelFrame(parent, text=" Target APNG ", padding=(P, 6))
        lf.pack(fill="x", pady=(0, P))
        row = ttk.Frame(lf)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self._target_path).pack(side="left", expand=True, fill="x")
        ttk.Button(row, text="Browse", width=self.BTN_W,
                   command=self._browse_target).pack(side="left", padx=(6, 0))
        ttk.Label(lf, text="This APNG plays after each enabled batch file (by default).",
                  style="Dim.TLabel").pack(anchor="w", pady=(4, 0))

    def _build_batch_section(self, parent):
        P = self.PAD
        lf = ttk.LabelFrame(parent, text=" Batch APNG Files ", padding=(P, 6))
        lf.pack(fill="both", expand=True)

        # ── Toolbar
        tb = ttk.Frame(lf)
        tb.pack(fill="x", pady=(0, 6))
        ttk.Button(tb, text="+ Add Files",   command=self._add_batch_files).pack(side="left")
        ttk.Button(tb, text="+ Add Folder",  command=self._add_batch_folder).pack(side="left", padx=4)
        ttk.Button(tb, text="Remove Selected", command=self._remove_highlighted).pack(side="left", padx=4)

        # Select-all / deselect-all / invert on the right
        ttk.Button(tb, text="✓ All",   command=self._select_all,   width=7).pack(side="right")
        ttk.Button(tb, text="✗ None",  command=self._deselect_all, width=7).pack(side="right", padx=(0, 4))
        ttk.Button(tb, text="⇌ Invert", command=self._invert_sel,  width=8).pack(side="right", padx=(0, 4))

        # ── Column headers
        hdr = tk.Frame(lf, bg=self.ACCENT)
        hdr.pack(fill="x")
        tk.Label(hdr, text="  ✓", bg=self.ACCENT, fg=self.FG_DIM,
                 font=("Courier New", 8), width=3, anchor="w").pack(side="left")
        tk.Label(hdr, text="Filename", bg=self.ACCENT, fg=self.FG_DIM,
                 font=("Courier New", 8), anchor="w").pack(side="left", padx=4)
        tk.Label(hdr, text="Full Path", bg=self.ACCENT, fg=self.FG_DIM,
                 font=("Courier New", 8), anchor="w").pack(side="left", padx=(0, 4))

        # ── Scrollable list canvas
        container = tk.Frame(lf, bg=self.ENTRY_BG,
                             highlightbackground=self.ACCENT, highlightthickness=1)
        container.pack(fill="both", expand=True)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(container, bg=self.ENTRY_BG,
                                 highlightthickness=0, bd=0)
        vsb = ttk.Scrollbar(container, orient="vertical",
                            command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._list_frame = tk.Frame(self._canvas, bg=self.ENTRY_BG)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._list_frame, anchor="nw")

        self._list_frame.bind("<Configure>", self._on_frame_configure)
        self._canvas.bind("<Configure>",     self._on_canvas_configure)
        self._canvas.bind("<MouseWheel>",    self._on_mousewheel)
        self._canvas.bind("<Button-4>",      self._on_mousewheel)
        self._canvas.bind("<Button-5>",      self._on_mousewheel)

        # Count label
        self._count_label = ttk.Label(lf, text="0 files  |  0 enabled",
                                       style="Dim.TLabel")
        self._count_label.pack(anchor="w", pady=(4, 0))

    def _build_options_section(self, parent):
        P = self.PAD
        lf = ttk.LabelFrame(parent, text=" Playback Order ", padding=(P, 6))
        lf.pack(fill="x", pady=(0, P))
        descs = {
            "batch → target": "batch plays first, then target",
            "target → batch": "target plays first, then batch",
            "interleave":     "alternating frames from each",
        }
        for mode in MERGE_MODES:
            r = ttk.Frame(lf)
            r.pack(fill="x", pady=2)
            ttk.Radiobutton(r, text=mode,
                            variable=self._merge_mode, value=mode).pack(side="left")
            ttk.Label(r, text=descs[mode], style="Dim.TLabel").pack(side="left", padx=8)

        lf2 = ttk.LabelFrame(parent, text=" Output Filename Prefix ", padding=(P, 6))
        lf2.pack(fill="x", pady=(0, P))
        ttk.Entry(lf2, textvariable=self._prefix).pack(fill="x")
        ttk.Label(lf2, text="e.g.  combined_  →  combined_frame01.png",
                  style="Dim.TLabel").pack(anchor="w", pady=(4, 0))

        lf3 = ttk.LabelFrame(parent, text=" Batch File Speed ", padding=(P, 6))
        lf3.pack(fill="x", pady=(0, P))
        speed_row = ttk.Frame(lf3)
        speed_row.pack(fill="x")
        self._speed_label = ttk.Label(speed_row, text="1.5×", width=5)
        self._speed_label.pack(side="right")
        ttk.Scale(
            speed_row, from_=0.25, to=4.0,
            variable=self._batch_speed, orient="horizontal",
            command=self._on_speed_change,
        ).pack(side="left", fill="x", expand=True)
        ttk.Label(lf3, text="Divides each batch frame's delay (higher = faster playback).",
                  style="Dim.TLabel").pack(anchor="w", pady=(4, 0))

    def _build_output_section(self, parent):
        P = self.PAD
        lf = ttk.LabelFrame(parent, text=" Output Directory ", padding=(P, 6))
        lf.pack(fill="x")
        row = ttk.Frame(lf)
        row.pack(fill="x")
        ttk.Entry(row, textvariable=self._output_dir).pack(side="left", expand=True, fill="x")
        ttk.Button(row, text="Browse", width=self.BTN_W,
                   command=self._browse_output).pack(side="left", padx=(6, 0))
        ttk.Label(lf, text="Leave blank to save next to each source file.",
                  style="Dim.TLabel").pack(anchor="w", pady=(4, 0))

    # ── Canvas helpers ────────────────────────────────────────────────────────

    def _on_frame_configure(self, _event=None):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    def _on_mousewheel(self, event):
        if event.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self._canvas.yview_scroll(1, "units")
        else:
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ── Row rendering ─────────────────────────────────────────────────────────

    def _rebuild_rows(self):
        """Re-render all rows with alternating colours."""
        for widget in self._list_frame.winfo_children():
            widget.destroy()

        for i, entry in enumerate(self._batch_entries):
            bg = self.ROW_ODD if i % 2 == 0 else self.ROW_EVEN

            row = tk.Frame(self._list_frame, bg=bg, cursor="arrow")
            row.pack(fill="x", pady=0)
            entry["row_frame"] = row

            # Checkbox
            cb = tk.Checkbutton(
                row,
                variable=entry["enabled"],
                bg=bg,
                activebackground=bg,
                selectcolor=self.ACCENT,
                fg=self.CHECK_ON,
                activeforeground=self.CHECK_ON,
                relief="flat", bd=0,
                command=self._update_count,
            )
            cb.pack(side="left", padx=(4, 0))
            entry["check"] = cb

            # Filename (bold)
            fname = os.path.basename(entry["path"])
            tk.Label(row, text=fname, bg=bg, fg=self.FG,
                     font=("Courier New", 9, "bold"),
                     anchor="w", width=22).pack(side="left", padx=(2, 6))

            # Full path (dim)
            tk.Label(row, text=entry["path"], bg=bg, fg=self.FG_DIM,
                     font=("Courier New", 8), anchor="w").pack(side="left", fill="x", expand=True)

            # Click row → highlight (visual feedback only)
            for widget in (row, cb):
                widget.bind("<Button-1>", lambda e, f=row, en=entry: self._highlight_row(f, en))

        self._on_frame_configure()
        self._update_count()

    def _highlight_row(self, frame: tk.Frame, entry: dict):
        """Toggle a visual highlight on click (distinct from the checkbox)."""
        current = frame.cget("bg")
        new_bg  = self.ROW_SEL if current != self.ROW_SEL else (
            self.ROW_ODD if self._batch_entries.index(entry) % 2 == 0 else self.ROW_EVEN
        )
        frame.config(bg=new_bg)
        for child in frame.winfo_children():
            try:
                child.config(bg=new_bg, activebackground=new_bg)
            except tk.TclError:
                pass

    # ── Interaction helpers ───────────────────────────────────────────────────

    def _on_speed_change(self, value):
        self._speed_label.config(text=f"{float(value):.2f}×")

    def _browse_target(self):
        p = filedialog.askopenfilename(
            title="Select target APNG",
            filetypes=[("APNG files", "*.apng *.png"), ("All files", "*.*")])
        if p:
            self._target_path.set(p)

    def _browse_output(self):
        d = filedialog.askdirectory(title="Select output directory")
        if d:
            self._output_dir.set(d)

    def _add_batch_files(self):
        paths = filedialog.askopenfilenames(
            title="Select APNG files",
            filetypes=[("APNG files", "*.apng *.png"), ("All files", "*.*")])
        self._add_paths(paths)

    def _add_batch_folder(self):
        d = filedialog.askdirectory(title="Select folder of APNG files")
        if not d:
            return
        paths = [
            os.path.join(d, f) for f in sorted(os.listdir(d))
            if f.lower().endswith((".apng", ".png"))
        ]
        self._add_paths(paths)

    def _add_paths(self, paths):
        existing = {e["path"] for e in self._batch_entries}
        added = False
        for p in paths:
            if p not in existing:
                self._batch_entries.append({
                    "path":    p,
                    "enabled": tk.BooleanVar(value=True),
                    "row_frame": None,
                    "check":   None,
                })
                existing.add(p)
                added = True
        if added:
            self._rebuild_rows()

    def _remove_highlighted(self):
        """Remove rows whose background is the highlight colour (clicked rows)."""
        to_keep = []
        for entry in self._batch_entries:
            rf = entry.get("row_frame")
            if rf and rf.winfo_exists() and rf.cget("bg") == self.ROW_SEL:
                continue  # drop it
            to_keep.append(entry)
        if len(to_keep) != len(self._batch_entries):
            self._batch_entries = to_keep
            self._rebuild_rows()

    def _select_all(self):
        for e in self._batch_entries:
            e["enabled"].set(True)
        self._update_count()

    def _deselect_all(self):
        for e in self._batch_entries:
            e["enabled"].set(False)
        self._update_count()

    def _invert_sel(self):
        for e in self._batch_entries:
            e["enabled"].set(not e["enabled"].get())
        self._update_count()

    def _update_count(self):
        total   = len(self._batch_entries)
        enabled = sum(1 for e in self._batch_entries if e["enabled"].get())
        self._count_label.config(
            text=f"{total} file{'s' if total != 1 else ''}  |  {enabled} enabled")

    def _clear_all(self):
        self._batch_entries.clear()
        for w in self._list_frame.winfo_children():
            w.destroy()
        self._target_path.set("")
        self._output_dir.set("")
        self._progress.set(0)
        self._status.set("Ready.")
        self._update_count()

    # ── Batch run ─────────────────────────────────────────────────────────────

    def _run_batch(self):
        target = self._target_path.get().strip()
        if not target:
            messagebox.showwarning("No Target", "Please select a target APNG file.")
            return
        if not os.path.isfile(target):
            messagebox.showerror("File Not Found", f"Target not found:\n{target}")
            return

        active = [e for e in self._batch_entries if e["enabled"].get()]
        if not active:
            messagebox.showwarning("Nothing Enabled",
                                   "No files are enabled. Check at least one file in the list.")
            return

        out_dir = self._output_dir.get().strip() or None
        if out_dir:
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as e:
                messagebox.showerror("Output Error", f"Cannot create output dir:\n{e}")
                return

        threading.Thread(
            target=self._worker,
            args=(target, [e["path"] for e in active],
                  self._merge_mode.get(), self._prefix.get().strip(),
                  out_dir, self._batch_speed.get()),
            daemon=True,
        ).start()

    def _worker(self, target, batch_paths, mode, prefix, out_dir, batch_speed):
        total   = len(batch_paths)
        errors  = []
        success = 0

        self._set_status("Starting…")
        self._progress.set(0)

        for i, batch_path in enumerate(batch_paths, 1):
            base     = os.path.splitext(os.path.basename(batch_path))[0]
            out_name = f"{prefix}{base}.png"
            dest     = os.path.join(out_dir or os.path.dirname(batch_path), out_name)

            self._set_status(f"[{i}/{total}] {os.path.basename(batch_path)}")
            try:
                result = combine_apng(target, batch_path, mode, batch_speed)
                result.save(dest)
                success += 1
            except Exception as exc:
                errors.append((batch_path, str(exc)))

            self._progress.set(i / total * 100)

        if errors:
            err_lines = "\n".join(
                f"• {os.path.basename(p)}: {msg}" for p, msg in errors[:10])
            if len(errors) > 10:
                err_lines += f"\n… and {len(errors) - 10} more."
            self._set_status(f"Done with {len(errors)} error(s). {success}/{total} exported.")
            self.after(0, lambda: messagebox.showwarning(
                "Completed with Errors",
                f"{success} file(s) exported successfully.\n\nErrors:\n{err_lines}"))
        else:
            self._set_status(f"✓ All {success} file(s) exported successfully.")
            self.after(0, lambda: messagebox.showinfo(
                "Done", f"{success} file(s) exported successfully."))

    def _set_status(self, msg: str):
        self.after(0, lambda: self._status.set(msg))


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = APNGCombinerApp()
    app.mainloop()