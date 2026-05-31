#!/usr/bin/env python3
"""
FS2 Mission Message Editor
Edits #Messages and send-message/send-message-list/send-message-alt in #Events
for FreeSpace 2 mission (.fs2) files.

Supports both legacy and modern FS2 open mission formats:
  - CRLF and LF line endings
  - $MessageText: and $MessageNew: (with XSTR wrapping)
  - +Persona Index: (integer) and +Persona: (name string)
  - Section headers with trailing tab+comment (e.g. "#Messages\t\t;! 6 total")
  - $Name: with trailing tab+comment (e.g. "$Name: Alpha 1\t\t;! Object #0")
  - send-message-list as triplets (sender, priority, msg, delay, ...)
    OR legacy (sender, priority, then pairs)
"""

import sys
import re
import os
import copy
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTreeWidget, QTreeWidgetItem, QLabel, QLineEdit,
    QTextEdit, QPushButton, QComboBox, QTabWidget, QFileDialog,
    QMessageBox, QScrollArea, QGroupBox, QInputDialog, QMenu, QAction,
    QDialog, QDialogButtonBox, QFormLayout, QListWidget,
    QAbstractItemView, QSpinBox, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QPalette


# ─── HELPERS ──────────────────────────────────────────────────────────────────

def clean(line):
    """Strip CRLF, CR, LF and leading/trailing whitespace."""
    return line.rstrip('\r\n').strip()

def section_name(line):
    """
    Extract section name from a line like '#Messages\t\t;! 6 total'.
    Returns e.g. '#Messages', or '' if not a section header.
    Only considers lines whose first character (before any CR/LF) is '#'.
    Callers that need to distinguish true section headers from #-prefixed
    SEXP tokens should track paren depth and ignore results when depth > 0.
    """
    stripped = line.rstrip('\r\n')
    if not stripped or stripped[0] != '#':
        return ''
    # strip trailing tab-comment
    name = re.split(r'[\t;]', stripped.strip())[0].strip()
    return name

def field_value(line, prefix):
    """
    Extract value from a line starting with prefix (case-insensitive).
    Strips trailing tab+comments.  Returns None if prefix not found.
    """
    s = clean(line)
    if not s.lower().startswith(prefix.lower()):
        return None
    val = s[len(prefix):].strip()
    # strip inline comment after tab
    val = re.split(r'\t+;!', val)[0].strip()
    return val

def extract_xstr(text):
    """
    Extract the plain string from XSTR("...", -1) or return text as-is.
    Also handles bare quoted strings.
    """
    m = re.match(r'XSTR\s*\(\s*"(.*?)"\s*,\s*-?\d+\s*\)', text, re.DOTALL)
    if m:
        return m.group(1)
    # bare quoted
    m2 = re.match(r'^"(.*)"$', text, re.DOTALL)
    if m2:
        return m2.group(1)
    return text

def wrap_xstr(text):
    """Wrap a string back into XSTR format, escaping internal double quotes."""
    safe = text.replace('"', '$quote').replace(';', '$semicolon')
    return f' XSTR("{safe}", -1)'


# ─── FS2 DATA CLASSES ─────────────────────────────────────────────────────────

class FS2Message:
    def __init__(self):
        self.name = ""
        self.team = ""
        self.message_text = ""        # plain text (unwrapped from XSTR)
        self.avi_name = ""
        self.wave = ""
        self.persona = ""             # name string (modern) or "" if none
        self.persona_index = -1       # legacy integer form
        self.multi_team = -1
        self.use_xstr = True          # write back as $MessageNew + XSTR
        self.raw_extra = []

    def __repr__(self):
        return f"<FS2Message {self.name!r}>"


class SendMessageCall:
    def __init__(self):
        self.call_type = "send-message"
        self.message_name = ""
        self.sender = ""
        self.priority = "Normal"
        # send-message-list: list of dicts with keys sender, priority, message, delay
        self.list_entries = []
        # send-message-alt: list of dicts with key message
        self.alt_entries = []
        # send-message-chain: chain name (first arg) + same entries as list
        self.chain_name = ""
        self.raw_sexp = ""
        self.sexp_start = -1
        self.sexp_end = -1


class FS2Event:
    def __init__(self):
        self.name = ""
        self.raw_lines = []
        self.send_message_calls = []


class FS2File:
    def __init__(self):
        self.raw_lines = []
        self.messages = []
        self.events = []
        self.messages_section_start = -1
        self.messages_section_end = -1
        self.events_section_start = -1
        self.events_section_end = -1
        self.ships = []
        self.wings = []
        self.personas = []
        self.filepath = ""

    # ── section finding ────────────────────────────────────────────────────────

    def _find_section(self, name):
        """Return (start_line, end_line) for a section like '#Messages'.
        Tracks parenthesis depth so that #-prefixed SEXP tokens (e.g.
        #Chanticleer used as a sender inside a formula) are never mistaken
        for section boundaries — section headers only appear at depth 0.
        """
        start = end = -1
        depth = 0
        for i, line in enumerate(self.raw_lines):
            depth += line.count('(') - line.count(')')
            if depth < 0:
                depth = 0
            if depth > 0:
                continue          # inside parentheses — cannot be a section header
            sn = section_name(line)
            if sn == name:
                start = i
                depth = 0        # reset in case of stray counts before this section
            elif start != -1 and sn and sn != name:
                end = i
                break
        if start != -1 and end == -1:
            end = len(self.raw_lines)
        return start, end

    # ── load ───────────────────────────────────────────────────────────────────

    def load(self, filepath):
        self.filepath = filepath
        with open(filepath, 'r', encoding='latin-1', errors='replace') as f:
            self.raw_lines = f.readlines()
        self._parse_messages()
        self._parse_events()
        self._parse_context()

    # ── messages ───────────────────────────────────────────────────────────────

    def _parse_messages(self):
        self.messages = []
        start, end = self._find_section('#Messages')
        self.messages_section_start = start
        self.messages_section_end = end
        if start == -1:
            return

        lines = self.raw_lines[start:end]
        i = 0
        msg = None

        while i < len(lines):
            s = clean(lines[i])

            # New message block
            if s.lower().startswith('$name:'):
                if msg is not None:
                    self.messages.append(msg)
                msg = FS2Message()
                val = field_value(lines[i], '$Name:')
                msg.name = val if val else ""
                i += 1
                continue

            if msg is None:
                i += 1
                continue

            # --- fields ---
            if s.lower().startswith('$team:'):
                msg.team = field_value(lines[i], '$Team:') or ""

            elif s.lower().startswith('$messagetext:'):
                # Legacy single-line form
                raw = field_value(lines[i], '$MessageText:') or ""
                msg.message_text = extract_xstr(raw)
                msg.use_xstr = False

            elif s.lower().startswith('$messagenew:'):
                # Modern form: value may start on same line, continues until $end_multi_text
                raw_start = field_value(lines[i], '$MessageNew:') or ""
                msg.use_xstr = True
                # accumulate text
                text_parts = [raw_start] if raw_start else []
                i += 1
                while i < len(lines):
                    s2 = clean(lines[i])
                    if s2.lower() == '$end_multi_text':
                        i += 1
                        break
                    text_parts.append(lines[i].rstrip('\r\n'))
                    i += 1
                full_raw = '\n'.join(text_parts).strip()
                msg.message_text = extract_xstr(full_raw)
                continue

            elif s.lower().startswith('+avi name:'):
                msg.avi_name = field_value(lines[i], '+AVI Name:') or ""

            elif s.lower().startswith('+wave name:'):
                msg.wave = field_value(lines[i], '+Wave Name:') or ""

            elif s.lower().startswith('+persona index:'):
                try:
                    msg.persona_index = int(field_value(lines[i], '+Persona Index:') or "-1")
                except ValueError:
                    pass

            elif s.lower().startswith('+persona:'):
                msg.persona = field_value(lines[i], '+Persona:') or ""

            elif s.lower().startswith('+multi-team:'):
                try:
                    msg.multi_team = int(field_value(lines[i], '+Multi-Team:') or "-1")
                except ValueError:
                    pass

            elif s.lower() == '$end_multi_text':
                pass  # skip stray end markers

            else:
                msg.raw_extra.append(lines[i])

            i += 1

        if msg is not None:
            self.messages.append(msg)

    # ── events ─────────────────────────────────────────────────────────────────

    def _parse_events(self):
        self.events = []
        start, end = self._find_section('#Events')
        self.events_section_start = start
        self.events_section_end = end
        if start == -1:
            return

        lines = self.raw_lines[start:end]
        i = 0
        current = None

        while i < len(lines):
            s = clean(lines[i])
            if s.lower().startswith('$formula:'):
                if current is not None:
                    self.events.append(current)
                current = FS2Event()
                current.raw_lines = [lines[i]]
                i += 1
                while i < len(lines):
                    s2 = clean(lines[i])
                    if s2.lower().startswith('$formula:'):
                        break
                    current.raw_lines.append(lines[i])
                    i += 1
                # find name
                for rl in current.raw_lines:
                    rs = clean(rl)
                    if rs.lower().startswith('+name:'):
                        current.name = field_value(rl, '+Name:') or ""
                        break
                block = ''.join(current.raw_lines)
                current.send_message_calls = self._extract_send_messages(block)
            else:
                if current is not None:
                    current.raw_lines.append(lines[i])
                i += 1

        if current is not None:
            self.events.append(current)

    def _extract_send_messages(self, text):
        calls = []
        pattern = re.compile(r'\(\s*(send-message(?:-chain|-list|-alt)?)\b', re.IGNORECASE)
        for m in pattern.finditer(text):
            call_type = m.group(1).lower()
            start = m.start()
            depth = 0
            end = start
            for j, ch in enumerate(text[start:]):
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth -= 1
                    if depth == 0:
                        end = start + j + 1
                        break
            sexp_raw = text[start:end]
            smc = SendMessageCall()
            smc.call_type = call_type
            smc.raw_sexp = sexp_raw
            smc.sexp_start = start
            smc.sexp_end = end
            self._parse_sexp_args(smc, sexp_raw)
            calls.append(smc)
        return calls

    def _parse_sexp_args(self, smc, sexp_raw):
        tokens = self._tokenize_sexp_inner(sexp_raw[1:-1].strip() if sexp_raw.startswith('(') else sexp_raw)
        if not tokens:
            return
        # tokens[0] = function name
        args = tokens[1:]

        def unquote(t):
            return t.strip('"') if t else t

        ct = smc.call_type
        if ct == 'send-message':
            # (send-message <sender> <priority> <message>)
            if len(args) >= 1: smc.sender = unquote(args[0])
            if len(args) >= 2: smc.priority = unquote(args[1])
            if len(args) >= 3: smc.message_name = unquote(args[2])

        elif ct == 'send-message-list':
            # Modern format: (send-message-list sender priority msg delay sender priority msg delay ...)
            # OR legacy:     (send-message-list sender priority msg delay msg delay ...)
            # Detect by checking if arg[4] looks like a priority keyword
            i = 0
            raw_args = [unquote(a) for a in args if not a.startswith('(')]

            # Heuristic: if every 4th token starting at index 2 is a priority string,
            # it's the triplet (sender+priority per entry) format.
            PRIORITY_WORDS = {'normal', 'high', 'low', 'npb_normal', 'npb_high', 'npb_low', 'none'}
            def looks_like_priority(s):
                return s.lower() in PRIORITY_WORDS

            # Try to detect triplet format: sender, priority, msg, delay, sender, priority, msg, delay...
            # If raw_args[1] looks like priority -> first sender/priority present
            is_triplet = (len(raw_args) >= 2 and looks_like_priority(raw_args[1]))
            if is_triplet:
                # Check if remaining after index 3 also follow triplet pattern
                # i.e., raw_args[4] looks like priority
                if len(raw_args) >= 6 and looks_like_priority(raw_args[5]):
                    # full triplet form
                    i = 0
                    while i + 4 <= len(raw_args):
                        entry = {
                            'sender': raw_args[i],
                            'priority': raw_args[i+1],
                            'message': raw_args[i+2],
                            'delay': raw_args[i+3]
                        }
                        smc.list_entries.append(entry)
                        i += 4
                    # set top-level sender/priority to first entry for display
                    if smc.list_entries:
                        smc.sender = smc.list_entries[0]['sender']
                        smc.priority = smc.list_entries[0]['priority']
                    return
                else:
                    # legacy: global sender+priority, then pairs
                    smc.sender = raw_args[0]
                    smc.priority = raw_args[1]
                    i = 2
                    while i + 1 < len(raw_args):
                        smc.list_entries.append({
                            'sender': smc.sender,
                            'priority': smc.priority,
                            'message': raw_args[i],
                            'delay': raw_args[i+1]
                        })
                        i += 2
            else:
                # fallback: treat as legacy pairs
                if len(raw_args) >= 1: smc.sender = raw_args[0]
                if len(raw_args) >= 2: smc.priority = raw_args[1]
                i = 2
                while i + 1 < len(raw_args):
                    smc.list_entries.append({
                        'sender': smc.sender,
                        'priority': smc.priority,
                        'message': raw_args[i],
                        'delay': raw_args[i+1]
                    })
                    i += 2

        elif ct == 'send-message-alt':
            raw_args = [unquote(a) for a in args if not a.startswith('(')]
            if len(raw_args) >= 1: smc.sender = raw_args[0]
            if len(raw_args) >= 2: smc.priority = raw_args[1]
            for a in raw_args[2:]:
                smc.alt_entries.append({'message': a})

        elif ct == 'send-message-chain':
            # (send-message-chain <chain-name> sender priority msg delay sender priority msg delay ...)
            raw_args = [unquote(a) for a in args if not a.startswith('(')]
            if len(raw_args) >= 1: smc.chain_name = raw_args[0]
            i = 1
            while i + 3 <= len(raw_args):
                smc.list_entries.append({
                    'sender':   raw_args[i],
                    'priority': raw_args[i + 1],
                    'message':  raw_args[i + 2],
                    'delay':    raw_args[i + 3] if i + 3 < len(raw_args) else '0'
                })
                i += 4
            # expose first entry's sender/priority for display
            if smc.list_entries:
                smc.sender   = smc.list_entries[0]['sender']
                smc.priority = smc.list_entries[0]['priority']

    def _tokenize_sexp_inner(self, text):
        """Tokenize a SEXP body into atoms and nested sub-expressions."""
        tokens = []
        i = 0
        while i < len(text):
            c = text[i]
            if c in ' \t\n\r':
                i += 1
            elif c == '(':
                depth = 0
                start = i
                while i < len(text):
                    if text[i] == '(':
                        depth += 1
                    elif text[i] == ')':
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                    i += 1
                tokens.append(text[start:i])
            elif c == '"':
                i += 1
                start = i
                while i < len(text) and text[i] != '"':
                    i += 1
                tokens.append('"' + text[start:i] + '"')
                i += 1
            else:
                start = i
                while i < len(text) and text[i] not in ' \t\n\r()':
                    i += 1
                tokens.append(text[start:i])
        return tokens

    # ── context ────────────────────────────────────────────────────────────────

    def _parse_context(self):
        self.ships = []
        self.wings = []
        self.personas = []
        in_objects = in_wings = in_personas = False
        depth = 0

        for line in self.raw_lines:
            depth += line.count('(') - line.count(')')
            if depth < 0:
                depth = 0
            # Only update section state when outside parentheses
            if depth == 0:
                sn = section_name(line)
                if sn:
                    in_objects  = (sn == '#Objects')
                    in_wings    = (sn == '#Wings')
                    in_personas = (sn == '#Personas')

            s = clean(line)
            if s.lower().startswith('$name:'):
                val = field_value(line, '$Name:')
                if val:
                    if in_objects:
                        self.ships.append(val)
                    elif in_wings:
                        self.wings.append(val)
                    elif in_personas:
                        self.personas.append(val)

            # Also pick up persona names from +Persona: in #Messages
            if s.lower().startswith('+persona:'):
                pname = field_value(line, '+Persona:')
                if pname and pname not in self.personas:
                    self.personas.append(pname)

        self.ships = list(dict.fromkeys(self.ships))
        self.wings = list(dict.fromkeys(self.wings))
        self.personas = list(dict.fromkeys(self.personas))

    # ── known senders ──────────────────────────────────────────────────────────

    def known_senders(self):
        specials = ['NONE', '#Command']
        # combine and deduplicate preserving order
        seen = set()
        result = []
        for s in specials + self.ships:
            if s not in seen:
                seen.add(s)
                result.append(s)
        return result

    def known_avi_names(self):
        """Blank entry plus any AVI names already used in this file."""
        seen = set()
        result = ['']
        seen.add('')
        for m in self.messages:
            if m.avi_name and m.avi_name not in seen:
                seen.add(m.avi_name)
                result.append(m.avi_name)
        return result

    def message_names(self):
        return [m.name for m in self.messages]

    # ── serialise ──────────────────────────────────────────────────────────────

    def _messages_block_text(self):
        lines = ['#Messages\n', '\n']
        for msg in self.messages:
            lines.append(f'$Name: {msg.name}\n')
            lines.append(f'$Team: {msg.team if msg.team else "-1"}\n')
            if msg.use_xstr:
                lines.append(f'$MessageNew: {wrap_xstr(msg.message_text)}\n')
                lines.append('$end_multi_text\n')
            else:
                lines.append(f'$MessageText: {msg.message_text}\n')
            if msg.persona:
                lines.append(f'+Persona: {msg.persona}\n')
            elif msg.persona_index >= 0:
                lines.append(f'+Persona Index: {msg.persona_index}\n')
            if msg.avi_name:
                lines.append(f'+AVI Name: {msg.avi_name}\n')
            if msg.wave:
                lines.append(f'+Wave Name: {msg.wave}\n')
            if msg.multi_team >= 0:
                lines.append(f'+Multi-Team: {msg.multi_team}\n')
            for extra in msg.raw_extra:
                lines.append(extra)
            lines.append('\n')
        return lines

    def _rebuild_event_sexp(self, smc):
        def q(s):
            # Always quote unless it's a plain unquoted keyword or a number
            BARE_OK = {'none', 'true', 'false', 'normal', 'high', 'low',
                       'npb_normal', 'npb_high', 'npb_low'}
            if not s:
                return '""'
            if s.lower() in BARE_OK:
                return s
            # Pure integer/float → no quotes needed
            try:
                float(s)
                return s
            except ValueError:
                pass
            safe = s.replace('"', '$quote').replace(';', '$semicolon')
            return f'"{safe}"'

        if smc.call_type == 'send-message':
            return (f'( send-message\n'
                    f'   {q(smc.sender)}\n'
                    f'   {q(smc.priority)}\n'
                    f'   {q(smc.message_name)}\n'
                    f')')
        elif smc.call_type == 'send-message-list':
            lines = ['( send-message-list']
            for e in smc.list_entries:
                lines.append(f'   {q(e["sender"])}')
                lines.append(f'   {q(e["priority"])}')
                lines.append(f'   {q(e["message"])}')
                lines.append(f'   {e["delay"]}')
            return '\n'.join(lines) + '\n)'
        elif smc.call_type == 'send-message-alt':
            lines = [f'( send-message-alt', f'   {q(smc.sender)}', f'   {q(smc.priority)}']
            for e in smc.alt_entries:
                lines.append(f'   {q(e["message"])}')
            return '\n'.join(lines) + '\n)'
        elif smc.call_type == 'send-message-chain':
            lines = ['( send-message-chain', f'   {q(smc.chain_name)}']
            for e in smc.list_entries:
                lines.append(f'   {q(e["sender"])}')
                lines.append(f'   {q(e["priority"])}')
                lines.append(f'   {q(e["message"])}')
                lines.append(f'   {e["delay"]}')
            return '\n'.join(lines) + '\n)'
        return smc.raw_sexp

    def _rebuild_event_block(self, event):
        block = ''.join(event.raw_lines)
        for smc in sorted(event.send_message_calls, key=lambda c: c.sexp_start, reverse=True):
            if smc.sexp_start >= 0 and smc.sexp_end > smc.sexp_start:
                block = block[:smc.sexp_start] + self._rebuild_event_sexp(smc) + block[smc.sexp_end:]
        return block.splitlines(keepends=True)

    def save(self, filepath=None):
        if filepath is None:
            filepath = self.filepath
        output = list(self.raw_lines)

        # Replace messages section
        if self.messages_section_start >= 0:
            msg_lines = self._messages_block_text()
            output = (output[:self.messages_section_start] +
                      msg_lines +
                      output[self.messages_section_end:])
            self.raw_lines = output
            self.messages_section_start, self.messages_section_end = self._find_section('#Messages')
            self.events_section_start, self.events_section_end = self._find_section('#Events')
            output = list(self.raw_lines)

        # Replace events blocks
        if self.events_section_start >= 0:
            ev_lines = list(output[self.events_section_start:self.events_section_end])
            formula_starts = [i for i, l in enumerate(ev_lines) if clean(l).lower().startswith('$formula:')]
            if len(formula_starts) == len(self.events):
                formula_starts.append(len(ev_lines))
                new_ev = list(ev_lines[:formula_starts[0]])
                for idx, event in enumerate(self.events):
                    new_ev.extend(self._rebuild_event_block(event))
                output = (output[:self.events_section_start] +
                          new_ev +
                          output[self.events_section_end:])

        with open(filepath, 'w', encoding='latin-1', errors='replace') as f:
            f.writelines(output)
        self.filepath = filepath


# ─── PRIORITY / TEAM CONSTANTS ────────────────────────────────────────────────

PRIORITIES = ['Normal', 'High', 'Low', 'NPB_Normal', 'NPB_High', 'NPB_Low', 'NONE',
              'NPB_NORMAL', 'NPB_HIGH', 'NPB_LOW']
TEAMS = ['-1', 'Friendly', 'Hostile', 'Neutral', 'Unknown', '']


# ─── MESSAGE EDITOR WIDGET ────────────────────────────────────────────────────

class MessageEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.msg = None
        self.fs2 = None
        self._building = False
        layout = QFormLayout(self)
        layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._on_changed)
        layout.addRow("Name:", self.name_edit)

        self.team_combo = QComboBox()
        self.team_combo.addItems(TEAMS)
        self.team_combo.setEditable(True)
        self.team_combo.currentTextChanged.connect(self._on_changed)
        layout.addRow("Team:", self.team_combo)

        self.text_edit = QTextEdit()
        self.text_edit.setMinimumHeight(80)
        self.text_edit.setMaximumHeight(140)
        self.text_edit.textChanged.connect(self._on_changed)
        layout.addRow("Message Text:", self.text_edit)

        self.persona_edit = QLineEdit()
        self.persona_edit.setPlaceholderText("e.g. Command, Hannah, Large Ship")
        self.persona_edit.textChanged.connect(self._on_changed)
        layout.addRow("Persona:", self.persona_edit)

        self.avi_combo = QComboBox()
        self.avi_combo.setEditable(True)
        self.avi_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.avi_combo.setMinimumContentsLength(0)
        self.avi_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLength)
        self.avi_combo.currentTextChanged.connect(self._on_changed)
        layout.addRow("AVI Name:", self.avi_combo)

        self.wave_edit = QLineEdit()
        self.wave_edit.textChanged.connect(self._on_changed)
        layout.addRow("Wave Name:", self.wave_edit)

        self.multi_team_spin = QSpinBox()
        self.multi_team_spin.setRange(-1, 16)
        self.multi_team_spin.setSpecialValueText("(none)")
        self.multi_team_spin.valueChanged.connect(self._on_changed)
        layout.addRow("Multi-Team:", self.multi_team_spin)

    def load_message(self, msg):
        self._building = True
        self.msg = msg
        self.name_edit.setText(msg.name)
        self.team_combo.setCurrentText(msg.team if msg.team else '-1')
        self.text_edit.setPlainText(msg.message_text)
        self.persona_edit.setText(msg.persona)
        # Populate AVI combo with known names for this file
        if self.fs2 is not None:
            self.avi_combo.blockSignals(True)
            cur = msg.avi_name
            self.avi_combo.clear()
            self.avi_combo.addItems(self.fs2.known_avi_names())
            self.avi_combo.setCurrentText(cur)
            self.avi_combo.blockSignals(False)
        else:
            self.avi_combo.setCurrentText(msg.avi_name)
        self.wave_edit.setText(msg.wave)
        self.multi_team_spin.setValue(msg.multi_team if msg.multi_team >= -1 else -1)
        self._building = False

    def _on_changed(self):
        if self._building or self.msg is None:
            return
        self.msg.name = self.name_edit.text()
        self.msg.team = self.team_combo.currentText()
        self.msg.message_text = self.text_edit.toPlainText()
        self.msg.persona = self.persona_edit.text()
        self.msg.avi_name = self.avi_combo.currentText()
        self.msg.wave = self.wave_edit.text()
        self.msg.multi_team = self.multi_team_spin.value()
        self.changed.emit()


# ─── SEND-MESSAGE EDITOR WIDGET ───────────────────────────────────────────────

class SendMessageEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, fs2_file, parent=None):
        super().__init__(parent)
        self.fs2 = fs2_file
        self.smc = None
        self._building = False
        layout = QVBoxLayout(self)

        top = QFormLayout()
        top.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.type_label = QLabel()
        self.type_label.setFont(QFont("Consolas", 10, QFont.Bold))
        top.addRow("Call Type:", self.type_label)

        self.sender_combo = QComboBox()
        self.sender_combo.setEditable(True)
        self.sender_combo.currentTextChanged.connect(self._on_changed)
        top.addRow("Sender (single):", self.sender_combo)

        self.priority_combo = QComboBox()
        self.priority_combo.addItems(PRIORITIES)
        self.priority_combo.setEditable(True)
        self.priority_combo.currentTextChanged.connect(self._on_changed)
        top.addRow("Priority (single):", self.priority_combo)
        layout.addLayout(top)

        # send-message single
        self.single_group = QGroupBox("Message")
        sg = QFormLayout(self.single_group)
        self.msg_combo = QComboBox()
        self.msg_combo.setEditable(True)
        self.msg_combo.currentTextChanged.connect(self._on_changed)
        sg.addRow("Message Name:", self.msg_combo)
        layout.addWidget(self.single_group)

        # send-message-list
        self.list_group = QGroupBox("Message List  (each entry: sender · priority · message · delay ms)")
        lg = QVBoxLayout(self.list_group)
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        lg.addWidget(self.list_widget)
        lb = QHBoxLayout()
        self.list_add_btn  = QPushButton("Add Entry")
        self.list_edit_btn = QPushButton("Edit Entry")
        self.list_rem_btn  = QPushButton("Remove Entry")
        self.list_up_btn   = QPushButton("▲")
        self.list_dn_btn   = QPushButton("▼")
        for btn in (self.list_add_btn, self.list_edit_btn, self.list_rem_btn, self.list_up_btn, self.list_dn_btn):
            lb.addWidget(btn)
        lg.addLayout(lb)
        self.list_add_btn.clicked.connect(self._list_add)
        self.list_edit_btn.clicked.connect(self._list_edit)
        self.list_rem_btn.clicked.connect(self._list_remove)
        self.list_up_btn.clicked.connect(self._list_up)
        self.list_dn_btn.clicked.connect(self._list_dn)
        layout.addWidget(self.list_group)

        # send-message-chain — shares list_widget for entries, adds chain name field
        self.chain_group = QGroupBox("Message Chain")
        cg = QFormLayout(self.chain_group)
        cg.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.chain_name_combo = QComboBox()
        self.chain_name_combo.setEditable(True)
        self.chain_name_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.chain_name_combo.setMinimumContentsLength(0)
        self.chain_name_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLength)
        self.chain_name_combo.currentTextChanged.connect(self._on_chain_name_changed)
        cg.addRow("Chain Name:", self.chain_name_combo)
        cg.addRow(QLabel("Entries (sender · priority · message · delay):"))
        self.chain_list_widget = QListWidget()
        self.chain_list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        cg.addRow(self.chain_list_widget)
        cb = QHBoxLayout()
        self.chain_add_btn  = QPushButton("Add Entry")
        self.chain_edit_btn = QPushButton("Edit Entry")
        self.chain_rem_btn  = QPushButton("Remove Entry")
        self.chain_up_btn   = QPushButton("▲")
        self.chain_dn_btn   = QPushButton("▼")
        for b in (self.chain_add_btn, self.chain_edit_btn, self.chain_rem_btn,
                  self.chain_up_btn, self.chain_dn_btn):
            cb.addWidget(b)
        cg.addRow(cb)
        self.chain_add_btn.clicked.connect(self._chain_add)
        self.chain_edit_btn.clicked.connect(self._chain_edit)
        self.chain_rem_btn.clicked.connect(self._chain_remove)
        self.chain_up_btn.clicked.connect(self._chain_up)
        self.chain_dn_btn.clicked.connect(self._chain_dn)
        layout.addWidget(self.chain_group)

        # send-message-alt
        self.alt_group = QGroupBox("Alternate Messages")
        ag = QVBoxLayout(self.alt_group)
        self.alt_widget = QListWidget()
        self.alt_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        ag.addWidget(self.alt_widget)
        ab = QHBoxLayout()
        self.alt_add_btn = QPushButton("Add Message")
        self.alt_rem_btn = QPushButton("Remove Message")
        ab.addWidget(self.alt_add_btn)
        ab.addWidget(self.alt_rem_btn)
        ag.addLayout(ab)
        self.alt_add_btn.clicked.connect(self._alt_add)
        self.alt_rem_btn.clicked.connect(self._alt_remove)
        layout.addWidget(self.alt_group)

        # Raw SEXP
        self.raw_group = QGroupBox("Raw SEXP (read-only preview)")
        rg = QVBoxLayout(self.raw_group)
        self.raw_text = QTextEdit()
        self.raw_text.setReadOnly(True)
        self.raw_text.setFont(QFont("Consolas", 9))
        self.raw_text.setMaximumHeight(130)
        rg.addWidget(self.raw_text)
        layout.addWidget(self.raw_group)

    def refresh_combos(self):
        for combo, items in [(self.sender_combo, self.fs2.known_senders()),
                              (self.msg_combo,   self.fs2.message_names())]:
            cur = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(items)
            combo.setCurrentText(cur)
            combo.blockSignals(False)

    def load_call(self, smc):
        self._building = True
        self.smc = smc
        # Block ALL interactive widget signals while populating to prevent
        # _on_changed firing mid-load and causing recursive signal chains
        widgets_to_block = (self.sender_combo, self.priority_combo,
                            self.msg_combo, self.list_widget, self.alt_widget,
                            self.chain_name_combo, self.chain_list_widget)
        for w in widgets_to_block:
            w.blockSignals(True)
        try:
            self.refresh_combos()
            self.type_label.setText(smc.call_type)
            ct = smc.call_type

            self.sender_combo.setCurrentText(smc.sender)
            self.priority_combo.setCurrentText(smc.priority)

            self.single_group.setVisible(ct == 'send-message')
            self.list_group.setVisible(ct == 'send-message-list')
            self.alt_group.setVisible(ct == 'send-message-alt')
            self.chain_group.setVisible(ct == 'send-message-chain')

            if ct == 'send-message':
                self.msg_combo.setCurrentText(smc.message_name)
            elif ct == 'send-message-list':
                self.list_widget.clear()
                for e in smc.list_entries:
                    self.list_widget.addItem(
                        "{sender}  [{priority}]  →  {message}   delay: {delay} ms".format(**e))
            elif ct == 'send-message-alt':
                self.alt_widget.clear()
                for e in smc.alt_entries:
                    self.alt_widget.addItem(e['message'])
            elif ct == 'send-message-chain':
                self.chain_name_combo.blockSignals(True)
                self.chain_name_combo.clear()
                self.chain_name_combo.addItems([e.name for e in self.fs2.events if e.name])
                self.chain_name_combo.setCurrentText(smc.chain_name)
                self.chain_name_combo.blockSignals(False)
                self.chain_list_widget.clear()
                for e in smc.list_entries:
                    self.chain_list_widget.addItem(
                        "{sender}  [{priority}]  →  {message}   delay: {delay} ms".format(**e))

            self.raw_text.setPlainText(smc.raw_sexp)
        finally:
            for w in widgets_to_block:
                w.blockSignals(False)
            self._building = False

    def _refresh_raw_preview(self):
        """Regenerate raw_sexp from current smc state and update the preview widget."""
        if self.smc is None:
            return
        rebuilt = self.fs2._rebuild_event_sexp(self.smc)
        self.smc.raw_sexp = rebuilt
        self.raw_text.blockSignals(True)
        self.raw_text.setPlainText(rebuilt)
        self.raw_text.blockSignals(False)

    def _on_changed(self):
        if self._building or self.smc is None:
            return
        self.smc.sender = self.sender_combo.currentText()
        self.smc.priority = self.priority_combo.currentText()
        if self.smc.call_type == 'send-message':
            self.smc.message_name = self.msg_combo.currentText()
        self._refresh_raw_preview()
        self.changed.emit()

    def _on_chain_name_changed(self, text):
        if self._building or self.smc is None:
            return
        self.smc.chain_name = self.chain_name_combo.currentText()
        self._refresh_raw_preview()
        self.changed.emit()

    def _chain_add(self):
        if not self.smc: return
        dlg = ListEntryDialog(self.fs2.known_senders(), self.fs2.message_names(), self)
        if dlg.exec_() == QDialog.Accepted:
            self.smc.list_entries.append(
                {'sender': dlg.sender, 'priority': dlg.priority,
                 'message': dlg.message, 'delay': dlg.delay})
            self.chain_list_widget.addItem(
                "{sender}  [{priority}]  →  {message}   delay: {delay} ms".format(
                    **self.smc.list_entries[-1]))
            self._refresh_raw_preview()
            self.changed.emit()

    def _chain_remove(self):
        if not self.smc: return
        row = self.chain_list_widget.currentRow()
        if row >= 0:
            self.smc.list_entries.pop(row)
            self.chain_list_widget.takeItem(row)
            self._refresh_raw_preview()
            self.changed.emit()

    def _chain_edit(self):
        if not self.smc: return
        row = self.chain_list_widget.currentRow()
        if row < 0: return
        e = self.smc.list_entries[row]
        dlg = ListEntryDialog(self.fs2.known_senders(), self.fs2.message_names(), self,
                              e['sender'], e['priority'], e['message'], e['delay'])
        if dlg.exec_() == QDialog.Accepted:
            self.smc.list_entries[row] = {
                'sender': dlg.sender, 'priority': dlg.priority,
                'message': dlg.message, 'delay': dlg.delay}
            self.chain_list_widget.item(row).setText(
                "{sender}  [{priority}]  →  {message}   delay: {delay} ms".format(
                    **self.smc.list_entries[row]))
            self._refresh_raw_preview()
            self.changed.emit()

    def _chain_up(self):
        row = self.chain_list_widget.currentRow()
        if not self.smc or row <= 0: return
        self.smc.list_entries[row-1], self.smc.list_entries[row] =             self.smc.list_entries[row], self.smc.list_entries[row-1]
        item = self.chain_list_widget.takeItem(row)
        self.chain_list_widget.insertItem(row-1, item)
        self.chain_list_widget.setCurrentRow(row-1)
        self._refresh_raw_preview()
        self.changed.emit()

    def _chain_dn(self):
        row = self.chain_list_widget.currentRow()
        if not self.smc or row < 0 or row >= self.chain_list_widget.count()-1: return
        self.smc.list_entries[row], self.smc.list_entries[row+1] =             self.smc.list_entries[row+1], self.smc.list_entries[row]
        item = self.chain_list_widget.takeItem(row)
        self.chain_list_widget.insertItem(row+1, item)
        self.chain_list_widget.setCurrentRow(row+1)
        self._refresh_raw_preview()
        self.changed.emit()

    # list entry helpers
    def _list_add(self):
        if not self.smc: return
        dlg = ListEntryDialog(self.fs2.known_senders(), self.fs2.message_names(), self)
        if dlg.exec_() == QDialog.Accepted:
            self.smc.list_entries.append(
                {'sender': dlg.sender, 'priority': dlg.priority,
                 'message': dlg.message, 'delay': dlg.delay})
            self.list_widget.addItem(
                f"{dlg.sender}  [{dlg.priority}]  →  {dlg.message}   delay: {dlg.delay} ms")
            self._refresh_raw_preview()
            self.changed.emit()

    def _list_remove(self):
        if not self.smc: return
        row = self.list_widget.currentRow()
        if row >= 0:
            self.smc.list_entries.pop(row)
            self.list_widget.takeItem(row)
            self._refresh_raw_preview()
            self.changed.emit()

    def _list_edit(self):
        if not self.smc: return
        row = self.list_widget.currentRow()
        if row < 0: return
        e = self.smc.list_entries[row]
        dlg = ListEntryDialog(self.fs2.known_senders(), self.fs2.message_names(), self,
                              e['sender'], e['priority'], e['message'], e['delay'])
        if dlg.exec_() == QDialog.Accepted:
            self.smc.list_entries[row] = {
                'sender': dlg.sender, 'priority': dlg.priority,
                'message': dlg.message, 'delay': dlg.delay}
            self.list_widget.item(row).setText(
                f"{dlg.sender}  [{dlg.priority}]  →  {dlg.message}   delay: {dlg.delay} ms")
            self._refresh_raw_preview()
            self.changed.emit()

    def _list_up(self):
        row = self.list_widget.currentRow()
        if not self.smc or row <= 0: return
        self.smc.list_entries[row-1], self.smc.list_entries[row] = \
            self.smc.list_entries[row], self.smc.list_entries[row-1]
        item = self.list_widget.takeItem(row)
        self.list_widget.insertItem(row-1, item)
        self.list_widget.setCurrentRow(row-1)
        self._refresh_raw_preview()
        self.changed.emit()

    def _list_dn(self):
        row = self.list_widget.currentRow()
        if not self.smc or row < 0 or row >= self.list_widget.count()-1: return
        self.smc.list_entries[row], self.smc.list_entries[row+1] = \
            self.smc.list_entries[row+1], self.smc.list_entries[row]
        item = self.list_widget.takeItem(row)
        self.list_widget.insertItem(row+1, item)
        self.list_widget.setCurrentRow(row+1)
        self._refresh_raw_preview()
        self.changed.emit()

    # alt helpers
    def _alt_add(self):
        if not self.smc: return
        msgs = self.fs2.message_names()
        msg, ok = QInputDialog.getItem(self, "Add Alternate", "Message:", msgs, 0, True)
        if ok and msg:
            self.smc.alt_entries.append({'message': msg})
            self.alt_widget.addItem(msg)
            self._refresh_raw_preview()
            self.changed.emit()

    def _alt_remove(self):
        if not self.smc: return
        row = self.alt_widget.currentRow()
        if row >= 0:
            self.smc.alt_entries.pop(row)
            self.alt_widget.takeItem(row)
            self._refresh_raw_preview()
            self.changed.emit()


class ListEntryDialog(QDialog):
    def __init__(self, senders, message_names, parent=None,
                 cur_sender="", cur_priority="Normal", cur_msg="", cur_delay="0"):
        super().__init__(parent)
        self.setWindowTitle("Edit List Entry")
        self.sender = cur_sender
        self.priority = cur_priority
        self.message = cur_msg
        self.delay = cur_delay
        layout = QFormLayout(self)

        self.sender_combo = QComboBox(); self.sender_combo.setEditable(True)
        self.sender_combo.addItems(senders); self.sender_combo.setCurrentText(cur_sender)
        layout.addRow("Sender:", self.sender_combo)

        self.priority_combo = QComboBox(); self.priority_combo.setEditable(True)
        self.priority_combo.addItems(PRIORITIES); self.priority_combo.setCurrentText(cur_priority)
        layout.addRow("Priority:", self.priority_combo)

        self.msg_combo = QComboBox(); self.msg_combo.setEditable(True)
        self.msg_combo.addItems(message_names); self.msg_combo.setCurrentText(cur_msg)
        layout.addRow("Message:", self.msg_combo)

        self.delay_edit = QLineEdit(cur_delay)
        layout.addRow("Delay (ms):", self.delay_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _accept(self):
        self.sender = self.sender_combo.currentText()
        self.priority = self.priority_combo.currentText()
        self.message = self.msg_combo.currentText()
        # Validate delay is a non-negative integer; default to 0 if not
        raw_delay = self.delay_edit.text().strip()
        try:
            self.delay = str(max(0, int(raw_delay)))
        except ValueError:
            self.delay = '0'
            self.delay_edit.setText('0')
        self.accept()


# ─── MAIN WINDOW ─────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.fs2 = None
        self.dirty = False
        self.setWindowTitle("FS2 Message Editor")
        self.resize(1200, 820)
        self._build_ui()
        self._build_menu()
        self.statusBar().showMessage("Open a .fs2 file to begin.")

    def _build_menu(self):
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        def act(label, shortcut, fn, enabled=True):
            a = QAction(label, self)
            if shortcut: a.setShortcut(shortcut)
            a.triggered.connect(fn)
            a.setEnabled(enabled)
            fm.addAction(a)
            return a
        act("&Open...", "Ctrl+O", self.open_file)
        self.save_action    = act("&Save",      "Ctrl+S",       self.save_file,    False)
        self.save_as_action = act("Save &As...", "Ctrl+Shift+S", self.save_file_as, False)
        fm.addSeparator()
        act("&Quit", "Ctrl+Q", self.close)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        QVBoxLayout(central).addWidget(self._make_tabs())

    def _make_tabs(self):
        self.tabs = QTabWidget()

        # ── Messages ──────────────────────────────────────────────────────────
        msg_tab = QWidget()
        ml = QHBoxLayout(msg_tab)
        sp = QSplitter(Qt.Horizontal)
        ml.addWidget(sp)

        left = QWidget()
        ll = QVBoxLayout(left); ll.setContentsMargins(0,0,0,0)
        lbl = QLabel("Messages"); lbl.setFont(QFont("Segoe UI", 10, QFont.Bold))
        ll.addWidget(lbl)
        self.msg_list = QListWidget()
        self.msg_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.msg_list.currentRowChanged.connect(self._msg_selected)
        self.msg_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.msg_list.customContextMenuRequested.connect(self._msg_ctx)
        ll.addWidget(self.msg_list, stretch=1)
        br = QHBoxLayout()
        for label, fn in [("+ Add", self._add_message),
                           ("Duplicate", self._dup_message),
                           ("− Remove", self._del_message)]:
            btn = QPushButton(label); btn.clicked.connect(fn); br.addWidget(btn)
        ll.addLayout(br, stretch=0)
        # Move up/down buttons
        br2 = QHBoxLayout()
        self.msg_up_btn = QPushButton("▲ Up")
        self.msg_dn_btn = QPushButton("▼ Down")
        for b in (self.msg_up_btn, self.msg_dn_btn):
            b.setEnabled(False)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            br2.addWidget(b)
        self.msg_up_btn.clicked.connect(self._msg_move_up)
        self.msg_dn_btn.clicked.connect(self._msg_move_dn)
        ll.addLayout(br2, stretch=0)
        sp.addWidget(left)

        self.msg_editor = MessageEditor()
        self.msg_editor.changed.connect(self._on_msg_changed)
        sc = QScrollArea(); sc.setWidget(self.msg_editor); sc.setWidgetResizable(True)
        sp.addWidget(sc)
        sp.setSizes([280, 720])
        self.tabs.addTab(msg_tab, "📨 Messages")

        # ── Events ────────────────────────────────────────────────────────────
        evt_tab = QWidget()
        el = QHBoxLayout(evt_tab)
        sp2 = QSplitter(Qt.Horizontal)
        el.addWidget(sp2)

        left2 = QWidget()
        ll2 = QVBoxLayout(left2); ll2.setContentsMargins(0,0,0,0)
        lbl2 = QLabel("Events & Send-Message Calls"); lbl2.setFont(QFont("Segoe UI", 10, QFont.Bold))
        ll2.addWidget(lbl2)
        self.evt_search = QLineEdit(); self.evt_search.setPlaceholderText("Filter events…")
        self.evt_search.textChanged.connect(self._filter_events)
        ll2.addWidget(self.evt_search)
        self.evt_tree = QTreeWidget(); self.evt_tree.setHeaderHidden(True)
        self.evt_tree.currentItemChanged.connect(self._evt_selected)
        ll2.addWidget(self.evt_tree)

        # buttons to add/remove send-message calls on the selected event
        evtbr = QHBoxLayout()
        self.add_sm_btn   = QPushButton("+ send-message")
        self.add_sml_btn  = QPushButton("+ send-message-list")
        self.add_smc_btn  = QPushButton("+ send-message-chain")
        self.del_smc_btn  = QPushButton("− Remove call")
        for b in (self.add_sm_btn, self.add_sml_btn, self.add_smc_btn, self.del_smc_btn):
            b.setEnabled(False)
            evtbr.addWidget(b)
        self.add_sm_btn.clicked.connect(lambda: self._add_smc_to_event('send-message'))
        self.add_sml_btn.clicked.connect(lambda: self._add_smc_to_event('send-message-list'))
        self.add_smc_btn.clicked.connect(lambda: self._add_smc_to_event('send-message-chain'))
        self.del_smc_btn.clicked.connect(self._remove_smc_from_event)
        ll2.addLayout(evtbr)
        sp2.addWidget(left2)

        self.right_scroll = QScrollArea()
        self.smc_placeholder = QLabel("Select a send-message call from the tree.")
        self.smc_placeholder.setAlignment(Qt.AlignCenter)
        self.smc_placeholder.setStyleSheet("color: gray; font-size: 14px;")
        self.right_scroll.setWidget(self.smc_placeholder)
        self.right_scroll.setWidgetResizable(True)
        sp2.addWidget(self.right_scroll)
        sp2.setSizes([360, 640])
        self.smc_editor = None
        self.tabs.addTab(evt_tab, "⚡ Events / Send-Message")

        # ── Context ───────────────────────────────────────────────────────────
        ctx_tab = QWidget()
        cl = QVBoxLayout(ctx_tab)
        cl.addWidget(QLabel("Auto-detected entities usable as senders:"))
        ch = QHBoxLayout()
        self.ctx_ships_list = QListWidget()
        grp = QGroupBox("Ships / Objects")
        gl = QVBoxLayout(grp); gl.addWidget(self.ctx_ships_list)
        ch.addWidget(grp)
        cl.addLayout(ch)
        self.tabs.addTab(ctx_tab, "🔍 Context / Senders")

        return self.tabs

    # ── file ops ──────────────────────────────────────────────────────────────

    def open_file(self):
        if self.dirty:
            if QMessageBox.question(self, "Unsaved changes", "Discard?",
                                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
        path, _ = QFileDialog.getOpenFileName(self, "Open FS2 Mission", "",
                                              "FS2 Mission (*.fs2);;All Files (*)")
        if not path: return
        self.fs2 = FS2File()
        try:
            self.fs2.load(path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load:\n{e}")
            return
        self.smc_editor = None
        self.right_scroll.setWidget(self.smc_placeholder)
        self._populate_all()
        self.save_action.setEnabled(True)
        self.save_as_action.setEnabled(True)
        self.setWindowTitle(f"FS2 Message Editor — {os.path.basename(path)}")
        self.statusBar().showMessage(
            f"Loaded: {len(self.fs2.messages)} messages, {len(self.fs2.events)} events | "
            f"{len(self.fs2.ships)} ships"
        )
        self.dirty = False

    def save_file(self):
        if not self.fs2: return
        try:
            self.fs2.save()
            self.dirty = False
            self.statusBar().showMessage(f"Saved: {self.fs2.filepath}")
            t = self.windowTitle()
            if t.startswith("* "): self.setWindowTitle(t[2:])
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Save failed:\n{e}")

    def save_file_as(self):
        if not self.fs2: return
        path, _ = QFileDialog.getSaveFileName(self, "Save As", self.fs2.filepath,
                                              "FS2 Mission (*.fs2);;All Files (*)")
        if not path: return
        try:
            self.fs2.save(path)
            self.dirty = False
            self.setWindowTitle(f"FS2 Message Editor — {os.path.basename(path)}")
            self.statusBar().showMessage(f"Saved as: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Save failed:\n{e}")

    # ── population ────────────────────────────────────────────────────────────

    def _populate_all(self):
        self.msg_editor.fs2 = self.fs2
        self._populate_messages()
        self._populate_events()
        self._populate_context()

    def _populate_messages(self):
        self.msg_list.blockSignals(True)
        self.msg_list.clear()
        self.msg_list.blockSignals(False)
        for m in self.fs2.messages:
            self.msg_list.addItem(m.name or "(unnamed)")
        n = len(self.fs2.messages)
        self.msg_up_btn.setEnabled(False)
        self.msg_dn_btn.setEnabled(False)

    def _populate_events(self):
        self.evt_tree.blockSignals(True)
        self.evt_tree.clear()
        for event in self.fs2.events:
            ei = QTreeWidgetItem(self.evt_tree)
            n = event.name or "(unnamed event)"
            c = len(event.send_message_calls)
            ei.setText(0, f"⚡ {n}  [{c} call(s)]")
            ei.setData(0, Qt.UserRole, ('event', event))
            ei.setForeground(0, QColor("#4a90d9") if c else QColor("#888"))
            for smc in event.send_message_calls:
                si = QTreeWidgetItem(ei)
                icon = {'send-message':'💬','send-message-list':'📋',
                        'send-message-alt':'🔀','send-message-chain':'⛓'}.get(smc.call_type,'?')
                if smc.call_type == 'send-message':
                    lbl = f"{icon} {smc.call_type}  →  {smc.message_name or '?'}  (from: {smc.sender or '?'})"
                elif smc.call_type in ('send-message-list', 'send-message-chain'):
                    chain_info = f' [{smc.chain_name}]' if smc.call_type == 'send-message-chain' and smc.chain_name else ''
                    lbl = f"{icon} {smc.call_type}{chain_info}  [{len(smc.list_entries)} msgs]"
                else:
                    lbl = f"{icon} {smc.call_type}  [{len(smc.alt_entries)} alts]  (from: {smc.sender or '?'})"
                si.setText(0, lbl)
                si.setData(0, Qt.UserRole, ('smc', smc))
        self.evt_tree.expandAll()
        self.evt_tree.blockSignals(False)

    def _populate_context(self):
        self.ctx_ships_list.clear()
        for s in self.fs2.ships:
            self.ctx_ships_list.addItem(s)

    # ── selection ─────────────────────────────────────────────────────────────

    def _msg_selected(self, row):
        n = len(self.fs2.messages) if self.fs2 else 0
        has = self.fs2 is not None and 0 <= row < n
        self.msg_up_btn.setEnabled(has and row > 0)
        self.msg_dn_btn.setEnabled(has and row < n - 1)
        if not has:
            return
        self.msg_editor.load_message(self.fs2.messages[row])

    def _evt_selected(self, current, _prev):
        if current is None:
            self.add_sm_btn.setEnabled(False)
            self.add_sml_btn.setEnabled(False)
            self.add_smc_btn.setEnabled(False)
            self.del_smc_btn.setEnabled(False)
            return
        data = current.data(0, Qt.UserRole)
        if data is None:
            return
        kind, obj = data
        if kind == 'event':
            # Event node selected: can add calls, cannot remove
            self.add_sm_btn.setEnabled(True)
            self.add_sml_btn.setEnabled(True)
            self.add_smc_btn.setEnabled(True)
            self.del_smc_btn.setEnabled(False)
        elif kind == 'smc':
            # Call node selected: can add (to parent event) and remove this call
            self.add_sm_btn.setEnabled(True)
            self.add_sml_btn.setEnabled(True)
            self.add_smc_btn.setEnabled(True)
            self.del_smc_btn.setEnabled(True)
            try:
                if self.smc_editor is None or self.smc_editor.fs2 is not self.fs2:
                    self.smc_editor = SendMessageEditor(self.fs2)
                    self.smc_editor.changed.connect(self._on_smc_changed)
                    self.right_scroll.setWidget(self.smc_editor)
                    self.smc_editor.show()
                self.smc_editor.load_call(obj)
            except Exception as exc:
                import traceback
                msg = type(exc).__name__ + ": " + str(exc)
                QMessageBox.critical(self, "Error loading call",
                    msg + "\n\n" + traceback.format_exc())

    def _filter_events(self, text):
        text = text.lower()
        root = self.evt_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            item.setHidden(bool(text) and text not in item.text(0).lower())

    # ── message CRUD ──────────────────────────────────────────────────────────

    def _msg_move_up(self):
        row = self.msg_list.currentRow()
        if not self.fs2 or row <= 0:
            return
        msgs = self.fs2.messages
        msgs[row - 1], msgs[row] = msgs[row], msgs[row - 1]
        self.msg_list.blockSignals(True)
        item = self.msg_list.takeItem(row)
        self.msg_list.insertItem(row - 1, item)
        self.msg_list.blockSignals(False)
        self.msg_list.setCurrentRow(row - 1)
        self._mark_dirty()

    def _msg_move_dn(self):
        row = self.msg_list.currentRow()
        if not self.fs2 or row < 0 or row >= len(self.fs2.messages) - 1:
            return
        msgs = self.fs2.messages
        msgs[row], msgs[row + 1] = msgs[row + 1], msgs[row]
        self.msg_list.blockSignals(True)
        item = self.msg_list.takeItem(row)
        self.msg_list.insertItem(row + 1, item)
        self.msg_list.blockSignals(False)
        self.msg_list.setCurrentRow(row + 1)
        self._mark_dirty()

    def _add_message(self):
        if not self.fs2: return
        name, ok = QInputDialog.getText(self, "New Message", "Message Name:")
        if not ok or not name: return
        msg = FS2Message(); msg.name = name; msg.use_xstr = True
        self.fs2.messages.append(msg)
        self.msg_list.addItem(name)
        self.msg_list.setCurrentRow(len(self.fs2.messages)-1)
        self._mark_dirty()

    def _dup_message(self):
        row = self.msg_list.currentRow()
        if not self.fs2 or row < 0: return
        new_msg = copy.deepcopy(self.fs2.messages[row])
        new_msg.name += "_copy"
        self.fs2.messages.insert(row+1, new_msg)
        self.msg_list.insertItem(row+1, new_msg.name)
        self.msg_list.setCurrentRow(row+1)
        self._mark_dirty()

    def _del_message(self):
        row = self.msg_list.currentRow()
        if not self.fs2 or row < 0: return
        msg = self.fs2.messages[row]
        if QMessageBox.question(self, "Delete", f"Delete '{msg.name}'?",
                                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes: return
        self.fs2.messages.pop(row)
        self.msg_list.takeItem(row)
        self._mark_dirty()

    def _msg_ctx(self, pos):
        menu = QMenu()
        menu.addAction("Add Message", self._add_message)
        menu.addAction("Duplicate", self._dup_message)
        menu.addAction("Delete", self._del_message)
        menu.addSeparator()
        menu.addAction("Move Up", self._msg_move_up)
        menu.addAction("Move Down", self._msg_move_dn)
        menu.exec_(self.msg_list.mapToGlobal(pos))

    # ── change tracking ───────────────────────────────────────────────────────

    def _selected_event(self):
        """Return the FS2Event for the currently selected tree item (event or smc child)."""
        item = self.evt_tree.currentItem()
        if item is None:
            return None, None
        data = item.data(0, Qt.UserRole)
        if data is None:
            return None, None
        kind, obj = data
        if kind == 'event':
            return obj, item
        elif kind == 'smc':
            parent = item.parent()
            if parent is None:
                return None, None
            pdata = parent.data(0, Qt.UserRole)
            if pdata and pdata[0] == 'event':
                return pdata[1], parent
        return None, None

    def _add_smc_to_event(self, call_type):
        if not self.fs2:
            return
        event, _ = self._selected_event()
        if event is None:
            return

        smc = SendMessageCall()
        smc.call_type = call_type
        smc.sender = '#Command'
        smc.priority = 'Normal'
        if call_type == 'send-message':
            smc.message_name = self.fs2.message_names()[0] if self.fs2.messages else ''
        elif call_type == 'send-message-list':
            smc.list_entries = []
        elif call_type == 'send-message-chain':
            smc.chain_name = 'new chain'
            smc.list_entries = []

        new_sexp = self.fs2._rebuild_event_sexp(smc)
        smc.raw_sexp = new_sexp

        block = ''.join(event.raw_lines)
        insert_pos = block.rfind(')')
        if insert_pos == -1:
            insert_pos = len(block)
        injection = chr(10) + "   " + new_sexp + chr(10)
        block = block[:insert_pos] + injection + block[insert_pos:]
        event.raw_lines = block.splitlines(keepends=True)
        event.send_message_calls = self.fs2._extract_send_messages(block)

        self._populate_events()
        self._mark_dirty()

        # Select and load the newly added call (from freshly re-parsed list)
        root = self.evt_tree.invisibleRootItem()
        for i in range(root.childCount()):
            ei = root.child(i)
            edata = ei.data(0, Qt.UserRole)
            if edata and edata[1] is event:
                if ei.childCount() > 0:
                    new_tree_item = ei.child(ei.childCount() - 1)
                    self.evt_tree.blockSignals(True)
                    self.evt_tree.setCurrentItem(new_tree_item)
                    self.evt_tree.blockSignals(False)
                    # Load the live smc object into the editor
                    new_smc = event.send_message_calls[-1]
                    if self.smc_editor is None or self.smc_editor.fs2 is not self.fs2:
                        self.smc_editor = SendMessageEditor(self.fs2)
                        self.smc_editor.changed.connect(self._on_smc_changed)
                        self.right_scroll.setWidget(self.smc_editor)
                        self.smc_editor.show()
                    self.smc_editor.load_call(new_smc)
                break

    def _remove_smc_from_event(self):
        if not self.fs2:
            return
        item = self.evt_tree.currentItem()
        if item is None:
            return
        data = item.data(0, Qt.UserRole)
        if data is None or data[0] != 'smc':
            return
        smc = data[1]
        parent = item.parent()
        if parent is None:
            return
        pdata = parent.data(0, Qt.UserRole)
        if pdata is None or pdata[0] != 'event':
            return
        event = pdata[1]

        r = QMessageBox.question(self, "Remove call",
            "Remove this " + smc.call_type + " call from the event?",
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return

        block = ''.join(event.raw_lines)
        if smc.sexp_start >= 0 and smc.sexp_end > smc.sexp_start:
            pre = block[:smc.sexp_start].rstrip(' 	')
            post = block[smc.sexp_end:]
            if pre.endswith(chr(10)):
                pass  # keep the newline
            block = pre + post
        event.raw_lines = block.splitlines(keepends=True)
        event.send_message_calls = self.fs2._extract_send_messages(block)

        # Reset the right panel so it doesn't show the now-deleted call
        self.smc_editor = None
        self.right_scroll.setWidget(self.smc_placeholder)

        self._populate_events()
        self._mark_dirty()

    def _on_msg_changed(self):
        row = self.msg_list.currentRow()
        if self.fs2 and 0 <= row < len(self.fs2.messages):
            self.msg_list.item(row).setText(self.fs2.messages[row].name or "(unnamed)")
        self._mark_dirty()

    def _on_smc_changed(self):
        # Update just the label of the selected tree item, never rebuild the whole tree
        item = self.evt_tree.currentItem()
        if item is not None:
            data = item.data(0, Qt.UserRole)
            if data and data[0] == 'smc':
                smc = data[1]
                icon = {'send-message': '💬', 'send-message-list': '📋',
                        'send-message-alt': '🔀', 'send-message-chain': '⛓'}.get(smc.call_type, '?')
                if smc.call_type == 'send-message':
                    lbl = f"{icon} {smc.call_type}  \u2192  {smc.message_name or '?'}  (from: {smc.sender or '?'})"
                elif smc.call_type in ('send-message-list', 'send-message-chain'):
                    chain_info = f' [{smc.chain_name}]' if smc.call_type == 'send-message-chain' and smc.chain_name else ''
                    lbl = f"{icon} {smc.call_type}{chain_info}  [{len(smc.list_entries)} msgs]"
                else:
                    lbl = f"{icon} {smc.call_type}  [{len(smc.alt_entries)} alts]  (from: {smc.sender or '?'})"
                self.evt_tree.blockSignals(True)
                item.setText(0, lbl)
                self.evt_tree.blockSignals(False)
        self._mark_dirty()

    def _mark_dirty(self):
        self.dirty = True
        t = self.windowTitle()
        if not t.startswith("* "):
            self.setWindowTitle("* " + t)

    def closeEvent(self, event):
        if self.dirty:
            if QMessageBox.question(self, "Unsaved", "Quit without saving?",
                                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                event.ignore(); return
        event.accept()


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(40, 44, 52))
    pal.setColor(QPalette.WindowText,      QColor(220, 220, 220))
    pal.setColor(QPalette.Base,            QColor(30, 33, 40))
    pal.setColor(QPalette.AlternateBase,   QColor(45, 50, 60))
    pal.setColor(QPalette.Text,            QColor(220, 220, 220))
    pal.setColor(QPalette.Button,          QColor(55, 60, 72))
    pal.setColor(QPalette.ButtonText,      QColor(220, 220, 220))
    pal.setColor(QPalette.Highlight,       QColor(60, 110, 180))
    pal.setColor(QPalette.HighlightedText, Qt.white)
    app.setPalette(pal)
    app.setStyleSheet("""
        QGroupBox { font-weight:bold; border:1px solid #555; border-radius:4px;
                    margin-top:8px; padding-top:6px; }
        QGroupBox::title { subcontrol-origin:margin; left:8px; }
        QPushButton { padding:4px 12px; border-radius:4px; }
        QPushButton:hover { background:#4a5268; }
        QTabBar::tab { padding:6px 16px; }
        QTabBar::tab:selected { background:#3a4060; }
        QTreeWidget::item:selected, QListWidget::item:selected { background:#3a5090; }
    """)

    win = MainWindow()
    win.show()

    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        win.fs2 = FS2File()
        try:
            win.fs2.load(sys.argv[1])
            win._populate_all()
            win.save_action.setEnabled(True)
            win.save_as_action.setEnabled(True)
            win.setWindowTitle(f"FS2 Message Editor — {os.path.basename(sys.argv[1])}")
            win.statusBar().showMessage(
                f"Loaded: {len(win.fs2.messages)} messages, {len(win.fs2.events)} events | "
                f"{len(win.fs2.ships)} ships"
            )
        except Exception as e:
            QMessageBox.critical(win, "Error", f"Failed to load:\n{e}")

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
