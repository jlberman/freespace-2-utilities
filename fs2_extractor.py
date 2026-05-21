#!/usr/bin/env python3
"""
FS2 Dialogue & Briefing Extractor
Air-gapped desktop application — requires only Python 3.8+ (stdlib only).

Usage: python3 fs2_extractor.py
"""

import os
import re
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from collections import defaultdict
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
#  EXTRACTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def clean_dollar_codes(text):
    text = re.sub(r'\$semicolon', ';', text)
    text = re.sub(r'\$\|', '', text)
    text = re.sub(r'(\w)\$(?=[\s,\.;!?\)\n]|$)', r'\\1', text)
    text = re.sub(r'\$[a-zA-Z]{1,2}\{', '', text)
    text = re.sub(r'\$[a-zA-Z]{1,2}(?=\s)', '', text)
    text = re.sub(r'\$\}', '', text)
    text = re.sub(r'\$(?=\s)', '', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'^[ \t]+', '', text, flags=re.MULTILINE)
    return text


def extract_section(content, header):
    m = re.search(r'(?m)^' + re.escape(header) + r'\s*$', content)
    if not m:
        return None
    rest = content[m.end():]
    next_sec = re.search(r'\n#\w', rest)
    end = m.end() + (next_sec.start() if next_sec else len(rest))
    return content[m.start():end].strip()


def parse_senders(content):
    senders = {}

    def add(msg, sender):
        senders.setdefault(msg, set()).add(sender)

    for sender, pri, msg in re.findall(
        r'\(\s*send-message\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\s*\)', content):
        add(msg, sender)

    for m in re.finditer(r'\(\s*send-message-list\s+([\s\S]*?)\n\s*\)', content):
        tokens = re.findall(r'"([^"]*)"|\b(\d+)\b', m.group(1))
        flat = [t[0] if t[0] != '' else t[1] for t in tokens]
        i = 0
        while i + 3 <= len(flat):
            try:
                int(flat[i + 3]); add(flat[i + 2], flat[i]); i += 4
            except (ValueError, IndexError):
                i += 1

    for m in re.finditer(r'\(\s*send-message-chain\s+([\s\S]*?)\n\s*\)', content):
        tokens = re.findall(r'"([^"]*)"|\b(\d+)\b', m.group(1))
        flat = [t[0] if t[0] != '' else t[1] for t in tokens]
        i = 1
        while i + 3 <= len(flat):
            try:
                int(flat[i + 3]); add(flat[i + 2], flat[i]); i += 4
            except (ValueError, IndexError):
                i += 1

    return senders


def relabel_sender(sender, avi_name):
    if sender == '#Command':
        avi = avi_name.lower()
        if avi == 'head-fr04':
            return 'Karpinsky'
        if avi in ('head-merc01',):
            return 'Tejada'
    return sender


def extract_messages_section(content):
    start = content.find('#Messages')
    if start == -1:
        return None
    next_sec = re.search(r'\n#(?!Messages)\w', content[start + 1:])
    end = start + 1 + next_sec.start() if next_sec else len(content)
    return content[start:end]


def parse_command_briefing(section):
    stages = []
    for block in re.split(r'\$Stage Text:', section)[1:]:
        text_match = re.search(r'XSTR\("([\s\S]*?)",\s*-1\)', block)
        text = clean_dollar_codes(text_match.group(1).strip()) if text_match else ""
        wave_match = re.search(r'\+Wave Filename:\s*(.+)', block)
        wave = wave_match.group(1).strip() if wave_match else ""
        stages.append((text, wave))
    return stages


def parse_briefing(section):
    stages = []
    for block in re.split(r'\$start_stage', section)[1:]:
        text_match = re.search(r'\$multi_text\s+XSTR\("([\s\S]*?)",\s*-1\)', block)
        text = clean_dollar_codes(text_match.group(1).strip()) if text_match else ""
        voice_match = re.search(r'\$voice:\s*(.+)', block, re.IGNORECASE)
        voice = voice_match.group(1).strip() if voice_match else ""
        if text:
            stages.append((text, voice))
    return stages


def simplify_formula(formula):
    formula = formula.strip()
    if re.match(r'^\(\s*true\s*\)\s*$', formula):
        return "Always"
    events = re.findall(r'is-event-true(?:-delay)?\s+\d*\s*"([^"]+)"', formula)
    not_events = re.findall(r'not\s*\(\s*is-event-true(?:-delay)?\s+\d*\s*"([^"]+)"', formula)
    destroyed = re.findall(r'is-destroyed(?:-delay)?\s+\d*\s*"([^"]+)"', formula)
    if events or not_events or destroyed:
        parts = []
        for e in events: parts.append(f'"{e}"=true')
        for e in not_events: parts.append(f'"{e}"=false')
        for e in destroyed: parts.append(f'"{e}"=destroyed')
        return " & ".join(parts)
    return formula


def parse_debriefing(section):
    stages = []
    blocks = re.split(r'\$Formula:', section)[1:]
    for block in blocks:
        formula_raw = re.match(r'\s*([\s\S]*?)(?=\n\$[Mm]ulti)', block)
        formula = simplify_formula(formula_raw.group(1)) if formula_raw else ""
        text_match = re.search(r'\$[Mm]ulti[ _]text\s+XSTR\("([\s\S]*?)",\s*-1\)', block)
        text = clean_dollar_codes(text_match.group(1).strip()) if text_match else ""
        voice_match = re.search(r'\$Voice:\s*(.+)', block, re.IGNORECASE)
        voice = voice_match.group(1).strip() if voice_match else ""
        rec_match = re.search(r'\$Recommendation text:\s*\n\s*XSTR\("([\s\S]*?)",\s*-1\)', block)
        rec = clean_dollar_codes(rec_match.group(1).strip()) if rec_match else ""
        if text:
            stages.append((formula, text, voice, rec))
    return stages


def mission_sort_key(mission_num):
    m = re.match(r'(\d+)(\w*)', str(mission_num))
    return (int(m.group(1)), m.group(2)) if m else (999, str(mission_num))


def process_files(fs2_files, options, progress_cb=None):
    """
    Core extraction. Returns dict with keys 'messages' and 'briefings' (text strings).
    options: dict with boolean keys: messages, briefings, debriefings, command_briefings
    """
    missions = []
    total = len(fs2_files)

    for idx, fpath in enumerate(fs2_files):
        if progress_cb:
            progress_cb(idx, total, f"Reading {os.path.basename(fpath)}…")
        try:
            content = Path(fpath).read_text(encoding='utf-8', errors='replace')
        except Exception as e:
            continue
        content = content.replace('\r\n', '\n').replace('\r', '\n')

        mn_match = re.search(r'\$Name:\s+XSTR\("([^"]+)"', content)
        mission_name = mn_match.group(1) if mn_match else os.path.basename(fpath)
        num_match = re.search(r'(\d+\w*)\.fs2$', fpath, re.IGNORECASE)
        mission_num = num_match.group(1) if num_match else "??"

        missions.append((mission_num, mission_name, content, fpath))

    missions.sort(key=lambda x: mission_sort_key(x[0]))

    messages_lines = []
    briefings_lines = []

    for idx, (mission_num, mission_name, content, fpath) in enumerate(missions):
        if progress_cb:
            progress_cb(len(fs2_files) + idx, len(fs2_files) + len(missions),
                        f"Extracting {mission_name}…")

        header = f"Mission {mission_num}: {mission_name}"
        sep = "=" * 70

        # ── MESSAGES ─────────────────────────────────────────────────────────
       
        # ── BRIEFINGS ────────────────────────────────────────────────────────
        brf_section_lines = []

        if options.get('command_briefings', True):
            cb = extract_section(content, '#Command Briefing')
            if cb:
                stages = parse_command_briefing(cb)
                if stages:
                    brf_section_lines.append("[ COMMAND BRIEFING ]")
                    brf_section_lines.append("")
                    for i, (text, wave) in enumerate(stages, 1):
                        brf_section_lines.append(f"Stage {i}:")
                        brf_section_lines.append(text)
                        if wave:
                            brf_section_lines.append(wave)
                        brf_section_lines.append("")

        if options.get('briefings', True):
            br = extract_section(content, '#Briefing')
            if br:
                stages = parse_briefing(br)
                if stages:
                    brf_section_lines.append("[ BRIEFING ]")
                    brf_section_lines.append("")
                    for i, (text, voice) in enumerate(stages, 1):
                        brf_section_lines.append(f"Stage {i}:")
                        brf_section_lines.append(text)
                        if voice:
                            brf_section_lines.append(voice)
                        brf_section_lines.append("")

        if options.get('messages', True):
            msg_section = extract_messages_section(content)
            if msg_section:
                senders = parse_senders(content)
                msg_lines = []
                for block in msg_section.split('\n$Name:')[1:]:
                    blines = block.strip().splitlines()
                    msg_name = blines[0].strip()
                    sender_set = senders.get(msg_name, set())
                    if not sender_set:
                        continue
                    text_match = re.search(r'\$MessageNew:\s+XSTR\("([^"]+)"', block)
                    msg_text = clean_dollar_codes(text_match.group(1)) if text_match else ""
                    wave_match = re.search(r'\+Wave Name:\s*(.+)', block)
                    wave_name = wave_match.group(1).strip() if wave_match else ""
                    avi_match = re.search(r'\+AVI Name:\s*(.+)', block)
                    avi_name = avi_match.group(1).strip() if avi_match else ""
                    relabelled = sorted(set(relabel_sender(s, avi_name) for s in sender_set))
                    sender_str = ", ".join(relabelled)
                    msg_lines.append(f"{sender_str}:  {msg_text}")
                    if wave_name:
                        msg_lines.append(wave_name)
                    msg_lines.append("")

                if msg_lines:
                    messages_lines += [sep, header, sep, ""]
                    messages_lines += msg_lines
        

        if options.get('debriefings', True):
            db = extract_section(content, '#Debriefing_info')
            if db:
                stages = parse_debriefing(db)
                if stages:
                    brf_section_lines.append("[ DEBRIEFING ]")
                    brf_section_lines.append("")
                    for i, (formula, text, voice, rec) in enumerate(stages, 1):
                        brf_section_lines.append(f"Stage {i}:")
                        if formula:
                            brf_section_lines.append(f"[Condition: {formula}]")
                        brf_section_lines.append(text)
                        if rec:
                            brf_section_lines.append(f"[Recommendation: {rec}]")
                        if voice:
                            brf_section_lines.append(voice)
                        brf_section_lines.append("")

        if brf_section_lines:
            briefings_lines += [sep, header, sep, ""]
            briefings_lines += brf_section_lines

    if progress_cb:
        progress_cb(1, 1, "Done.")

    return {
        'messages': '\n'.join(messages_lines),
        'briefings': '\n'.join(briefings_lines),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  GUI
# ─────────────────────────────────────────────────────────────────────────────

DARK_BG      = "#0f1117"
PANEL_BG     = "#181c26"
ACCENT       = "#4af0a8"
ACCENT_DIM   = "#1e4d38"
TEXT_MAIN    = "#d4dde8"
TEXT_DIM     = "#5a6a7a"
TEXT_BRIGHT  = "#eef4ff"
BORDER       = "#252d3d"
BUTTON_BG    = "#1e2738"
BUTTON_HOV   = "#263348"
ERROR        = "#f05050"
WARN         = "#f0b840"
FONT_MONO    = ("Courier New", 10)
FONT_UI      = ("Segoe UI", 10) if sys.platform == "win32" else ("Helvetica", 10)
FONT_TITLE   = ("Segoe UI", 13, "bold") if sys.platform == "win32" else ("Helvetica", 13, "bold")
FONT_SMALL   = ("Segoe UI", 8) if sys.platform == "win32" else ("Helvetica", 9)


class FS2ExtractorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FS2 Dialogue & Briefing Extractor")
        self.configure(bg=DARK_BG)
        self.minsize(860, 620)
        self.geometry("980x700")

        self.fs2_files = []
        self.output_dir = tk.StringVar()
        self.opt_messages = tk.BooleanVar(value=True)
        self.opt_briefings = tk.BooleanVar(value=True)
        self.opt_debriefings = tk.BooleanVar(value=True)
        self.opt_command_briefings = tk.BooleanVar(value=True)
        self.opt_single_file = tk.BooleanVar(value=False)

        self._build_ui()
        self._style_ttk()

    def _style_ttk(self):
        style = ttk.Style(self)
        style.theme_use('default')
        style.configure("TProgressbar",
                        troughcolor=PANEL_BG,
                        background=ACCENT,
                        bordercolor=BORDER,
                        lightcolor=ACCENT,
                        darkcolor=ACCENT)
        style.configure("Vertical.TScrollbar",
                        background=BUTTON_BG,
                        troughcolor=PANEL_BG,
                        bordercolor=BORDER,
                        arrowcolor=TEXT_DIM)
        style.configure("Horizontal.TScrollbar",
                        background=BUTTON_BG,
                        troughcolor=PANEL_BG,
                        bordercolor=BORDER,
                        arrowcolor=TEXT_DIM)

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header bar
        header = tk.Frame(self, bg=PANEL_BG, height=52)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        tk.Label(header, text="FS2  EXTRACTOR", font=FONT_TITLE,
                 fg=ACCENT, bg=PANEL_BG).pack(side="left", padx=18, pady=14)
        tk.Label(header, text="Dialogue · Briefings · Debriefings",
                 font=FONT_SMALL, fg=TEXT_DIM, bg=PANEL_BG).pack(side="left", pady=17)

        # Main split: left panel + right preview
        body = tk.Frame(self, bg=DARK_BG)
        body.pack(fill="both", expand=True, padx=0, pady=0)

        left = tk.Frame(body, bg=DARK_BG, width=300)
        left.pack(side="left", fill="y", padx=(12, 6), pady=10)
        left.pack_propagate(False)

        right = tk.Frame(body, bg=DARK_BG)
        right.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=10)

        self._build_left(left)
        self._build_right(right)

        # Status bar
        self.status_var = tk.StringVar(value="Ready — select .fs2 files to begin.")
        bar = tk.Frame(self, bg=PANEL_BG, height=28)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        tk.Label(bar, textvariable=self.status_var,
                 font=FONT_SMALL, fg=TEXT_DIM, bg=PANEL_BG,
                 anchor="w").pack(side="left", padx=10, pady=5)

    def _section_label(self, parent, text):
        tk.Label(parent, text=text.upper(), font=FONT_SMALL,
                 fg=ACCENT, bg=DARK_BG, anchor="w").pack(fill="x", pady=(10, 3))
        tk.Frame(parent, bg=ACCENT_DIM, height=1).pack(fill="x")

    def _build_left(self, parent):
        # ── File list ─────────────────────────────────────────────────────
        self._section_label(parent, "Input Files")

        list_frame = tk.Frame(parent, bg=PANEL_BG, bd=0,
                              highlightthickness=1,
                              highlightbackground=BORDER)
        list_frame.pack(fill="both", expand=True, pady=(4, 0))

        sb = tk.Scrollbar(list_frame, bg=PANEL_BG, troughcolor=PANEL_BG,
                          relief="flat", bd=0)
        sb.pack(side="right", fill="y")

        self.file_list = tk.Listbox(list_frame,
                                    bg=PANEL_BG, fg=TEXT_MAIN,
                                    selectbackground=ACCENT_DIM,
                                    selectforeground=ACCENT,
                                    activestyle="none",
                                    borderwidth=0, highlightthickness=0,
                                    font=FONT_MONO,
                                    yscrollcommand=sb.set)
        self.file_list.pack(fill="both", expand=True, padx=4, pady=4)
        sb.config(command=self.file_list.yview)

        btn_row = tk.Frame(parent, bg=DARK_BG)
        btn_row.pack(fill="x", pady=(4, 0))
        self._btn(btn_row, "Add Files", self._add_files).pack(side="left", fill="x", expand=True, padx=(0, 2))
        self._btn(btn_row, "Add Folder", self._add_folder).pack(side="left", fill="x", expand=True, padx=(2, 0))
        self._btn(parent, "Clear List", self._clear_files, dim=True).pack(fill="x", pady=(2, 0))

        # ── Options ───────────────────────────────────────────────────────
        self._section_label(parent, "Extract")

        opts = tk.Frame(parent, bg=DARK_BG)
        opts.pack(fill="x", pady=(4, 0))

        self._check(opts, "In-mission Dialogue", self.opt_messages)
        self._check(opts, "Command Briefings", self.opt_command_briefings)
        self._check(opts, "Mission Briefings", self.opt_briefings)
        self._check(opts, "Debriefings", self.opt_debriefings)

        self._section_label(parent, "Output")

        out_row = tk.Frame(parent, bg=DARK_BG)
        out_row.pack(fill="x", pady=(4, 2))
        self.out_entry = tk.Entry(out_row, textvariable=self.output_dir,
                                  bg=PANEL_BG, fg=TEXT_MAIN,
                                  insertbackground=ACCENT,
                                  relief="flat", bd=4,
                                  font=FONT_MONO)
        self.out_entry.pack(side="left", fill="x", expand=True)
        self._btn(out_row, "…", self._pick_output, small=True).pack(side="left", padx=(3, 0))

        self._check(parent, "Combine into single output file", self.opt_single_file)

        # ── Run ───────────────────────────────────────────────────────────
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=8)

        self.run_btn = self._btn(parent, "▶  EXTRACT", self._run, accent=True)
        self.run_btn.pack(fill="x", ipady=6)

        self.progress = ttk.Progressbar(parent, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(6, 0))

    def _build_right(self, parent):
        self._section_label(parent, "Preview")

        tab_row = tk.Frame(parent, bg=DARK_BG)
        tab_row.pack(fill="x", pady=(4, 0))

        self.active_tab = tk.StringVar(value="messages")
        for label, key in [("Dialogue", "messages"), ("Briefings", "briefings")]:
            b = tk.Button(tab_row, text=label, font=FONT_UI,
                          bg=PANEL_BG, fg=TEXT_DIM,
                          activebackground=ACCENT_DIM, activeforeground=ACCENT,
                          relief="flat", bd=0, padx=12, pady=4,
                          cursor="hand2",
                          command=lambda k=key: self._switch_tab(k))
            b.pack(side="left", padx=(0, 2))
            setattr(self, f"tab_{key}_btn", b)

        self._switch_tab("messages")

        text_frame = tk.Frame(parent, bg=PANEL_BG,
                              highlightthickness=1,
                              highlightbackground=BORDER)
        text_frame.pack(fill="both", expand=True, pady=(4, 0))

        xsb = tk.Scrollbar(text_frame, orient="horizontal",
                           bg=PANEL_BG, troughcolor=PANEL_BG, relief="flat", bd=0)
        xsb.pack(side="bottom", fill="x")
        ysb = tk.Scrollbar(text_frame, bg=PANEL_BG, troughcolor=PANEL_BG,
                           relief="flat", bd=0)
        ysb.pack(side="right", fill="y")

        self.preview = tk.Text(text_frame,
                               bg=PANEL_BG, fg=TEXT_MAIN,
                               insertbackground=ACCENT,
                               relief="flat", bd=6,
                               font=FONT_MONO,
                               wrap="none",
                               state="disabled",
                               xscrollcommand=xsb.set,
                               yscrollcommand=ysb.set)
        self.preview.pack(fill="both", expand=True)
        xsb.config(command=self.preview.xview)
        ysb.config(command=self.preview.yview)

        # Tag styling for preview
        self.preview.tag_configure("header",
                                   foreground=ACCENT, font=(FONT_MONO[0], FONT_MONO[1], "bold"))
        self.preview.tag_configure("section",
                                   foreground=WARN)
        self.preview.tag_configure("meta",
                                   foreground=TEXT_DIM)

        save_row = tk.Frame(parent, bg=DARK_BG)
        save_row.pack(fill="x", pady=(5, 0))
        self._btn(save_row, "Save Preview to File…", self._save_preview).pack(side="left")
        self.preview_label = tk.Label(save_row, text="", font=FONT_SMALL,
                                      fg=TEXT_DIM, bg=DARK_BG)
        self.preview_label.pack(side="right", padx=4)

        self._results = {}

    # ── Widget helpers ────────────────────────────────────────────────────────

    def _btn(self, parent, text, cmd, accent=False, dim=False, small=False):
        bg = ACCENT if accent else BUTTON_BG
        fg = DARK_BG if accent else (TEXT_DIM if dim else TEXT_MAIN)
        font = FONT_SMALL if small else FONT_UI
        b = tk.Button(parent, text=text, command=cmd,
                      bg=bg, fg=fg, activebackground=BUTTON_HOV,
                      activeforeground=TEXT_BRIGHT,
                      relief="flat", bd=0,
                      font=font, cursor="hand2",
                      padx=8, pady=4)
        b.bind("<Enter>", lambda e: b.config(bg=BUTTON_HOV if not accent else ACCENT))
        b.bind("<Leave>", lambda e: b.config(bg=bg))
        return b

    def _check(self, parent, label, var):
        f = tk.Frame(parent, bg=DARK_BG)
        f.pack(fill="x", pady=1)
        cb = tk.Checkbutton(f, text=label, variable=var,
                             bg=DARK_BG, fg=TEXT_MAIN,
                             selectcolor=ACCENT_DIM,
                             activebackground=DARK_BG,
                             activeforeground=TEXT_BRIGHT,
                             font=FONT_UI, anchor="w",
                             relief="flat", bd=0)
        cb.pack(fill="x")

    def _switch_tab(self, key):
        self.active_tab.set(key)
        for k in ("messages", "briefings"):
            btn = getattr(self, f"tab_{k}_btn", None)
            if btn:
                if k == key:
                    btn.config(fg=ACCENT, bg=ACCENT_DIM)
                else:
                    btn.config(fg=TEXT_DIM, bg=PANEL_BG)
        # Refresh preview content if results exist
        if hasattr(self, '_results') and self._results:
            self._render_preview(key)

    # ── File management ───────────────────────────────────────────────────────

    def _add_files(self):
        files = filedialog.askopenfilenames(
            title="Select .fs2 mission files",
            filetypes=[("FreeSpace 2 Mission", "*.fs2"), ("All files", "*.*")])
        self._add_to_list(files)

    def _add_folder(self):
        folder = filedialog.askdirectory(title="Select folder containing .fs2 files")
        if folder:
            found = sorted(str(p) for p in Path(folder).rglob("*.fs2"))
            self._add_to_list(found)

    def _add_to_list(self, paths):
        existing = set(self.fs2_files)
        added = 0
        for p in paths:
            if p not in existing:
                self.fs2_files.append(p)
                self.file_list.insert("end", os.path.basename(p))
                existing.add(p)
                added += 1
        self._status(f"{added} file(s) added. Total: {len(self.fs2_files)}")

    def _clear_files(self):
        self.fs2_files.clear()
        self.file_list.delete(0, "end")
        self._status("File list cleared.")

    def _pick_output(self):
        folder = filedialog.askdirectory(title="Select output directory")
        if folder:
            self.output_dir.set(folder)

    # ── Extraction ────────────────────────────────────────────────────────────

    def _run(self):
        if not self.fs2_files:
            messagebox.showwarning("No files", "Please add at least one .fs2 file.")
            return
        if not any([self.opt_messages.get(), self.opt_briefings.get(),
                    self.opt_debriefings.get(), self.opt_command_briefings.get()]):
            messagebox.showwarning("Nothing selected", "Please select at least one output type.")
            return

        out_dir = self.output_dir.get().strip()
        if not out_dir:
            messagebox.showwarning("No output folder", "Please select an output directory.")
            return
        if not os.path.isdir(out_dir):
            messagebox.showwarning("Bad output folder", "The output directory does not exist.")
            return

        self.run_btn.config(state="disabled")
        self.progress["value"] = 0
        self._results = {}

        options = {
            'messages': self.opt_messages.get(),
            'briefings': self.opt_briefings.get(),
            'debriefings': self.opt_debriefings.get(),
            'command_briefings': self.opt_command_briefings.get(),
        }

        def worker():
            def progress_cb(done, total, msg):
                pct = int((done / max(total, 1)) * 100)
                self.after(0, lambda: self.progress.config(value=pct))
                self.after(0, lambda: self._status(msg))

            try:
                results = process_files(self.fs2_files, options, progress_cb)
                self.after(0, lambda: self._on_done(results, out_dir))
            except Exception as e:
                self.after(0, lambda: self._on_error(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self, results, out_dir):
        self._results = results
        saved = []

        if self.opt_single_file.get():
            combined = ""
            if results.get('messages'):
                combined += "╔══════════════════════════════════════╗\n"
                combined += "║         IN-MISSION DIALOGUE          ║\n"
                combined += "╚══════════════════════════════════════╝\n\n"
                combined += results['messages'] + "\n\n"
            if results.get('briefings'):
                combined += "╔══════════════════════════════════════╗\n"
                combined += "║      BRIEFINGS & DEBRIEFINGS         ║\n"
                combined += "╚══════════════════════════════════════╝\n\n"
                combined += results['briefings']
            out_path = os.path.join(out_dir, "fs2_extracted.txt")
            Path(out_path).write_text(combined, encoding='utf-8')
            saved.append(out_path)
        else:
            if results.get('messages'):
                p = os.path.join(out_dir, "fs2_dialogue.txt")
                Path(p).write_text(results['messages'], encoding='utf-8')
                saved.append(p)
            if results.get('briefings'):
                p = os.path.join(out_dir, "fs2_briefings.txt")
                Path(p).write_text(results['briefings'], encoding='utf-8')
                saved.append(p)

        self.run_btn.config(state="normal")
        self.progress["value"] = 100

        tab = self.active_tab.get()
        self._render_preview(tab)

        msg_count = results['messages'].count('\n:  ')
        brf_count = results['briefings'].count('Stage ')
        self._status(f"Done. {msg_count} dialogue lines, {brf_count} briefing stages. "
                     f"Saved {len(saved)} file(s) to {out_dir}")

        if saved:
            messagebox.showinfo("Extraction complete",
                                f"Saved {len(saved)} file(s):\n" + "\n".join(
                                    [os.path.basename(p) for p in saved]) +
                                f"\n\nOutput directory:\n{out_dir}")

    def _on_error(self, msg):
        self.run_btn.config(state="normal")
        messagebox.showerror("Extraction error", f"An error occurred:\n\n{msg}")
        self._status(f"Error: {msg}")

    # ── Preview ───────────────────────────────────────────────────────────────

    def _render_preview(self, tab):
        key = 'messages' if tab == 'messages' else 'briefings'
        text = self._results.get(key, "")
        count = len([l for l in text.splitlines() if l.strip()])

        self.preview.config(state="normal")
        self.preview.delete("1.0", "end")

        if not text:
            self.preview.insert("end", "(no content)\n", "meta")
        else:
            for line in text.splitlines():
                if line.startswith("====="):
                    self.preview.insert("end", line + "\n", "header")
                elif line.startswith("[ ") and line.endswith(" ]"):
                    self.preview.insert("end", line + "\n", "section")
                elif line.startswith("[Condition:") or line.startswith("[Recommendation:"):
                    self.preview.insert("end", line + "\n", "meta")
                elif re.match(r'^Stage \d+:', line):
                    self.preview.insert("end", line + "\n", "section")
                elif re.match(r'.+\.ogg$', line, re.IGNORECASE):
                    self.preview.insert("end", line + "\n", "meta")
                else:
                    self.preview.insert("end", line + "\n")

        self.preview.config(state="disabled")
        self.preview_label.config(text=f"{count} lines")

    def _save_preview(self):
        tab = self.active_tab.get()
        key = 'messages' if tab == 'messages' else 'briefings'
        text = self._results.get(key, "")
        if not text:
            messagebox.showinfo("Nothing to save", "Run an extraction first.")
            return
        default = "fs2_dialogue.txt" if key == 'messages' else "fs2_briefings.txt"
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=default,
            filetypes=[("Text file", "*.txt"), ("All files", "*.*")])
        if path:
            Path(path).write_text(text, encoding='utf-8')
            self._status(f"Saved: {path}")

    def _status(self, msg):
        self.status_var.set(msg)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = FS2ExtractorApp()
    app.mainloop()
