#!/usr/bin/env python3
"""
Open Grade Transfer System (OGTS)

Types scores from a spreadsheet into an Aspen gradebook column by simulating a keyboard,
the same way you would type them by hand: type a score, press Enter (Aspen moves down one
student), repeat. Because it only presses keys, it works in any browser or profile and does not
touch the page, an extension, or the browser's policies.

Workflow
  1. Copy two columns from your spreadsheet: "Last, First" and the score.
  2. In this program: pick the class roster (saved once from Aspen), click "Load grades".
  3. Review the preview, press Go, then click the FIRST student's cell in the Aspen column.
  4. The program matches names to the roster (tolerating extra names, different order,
     small typos) and types each score on the right row.

Run:   python ogts.py            (window)
       python ogts.py --cli ...  (no window; see --help)

Requires: Python 3.9+, and `pip install pyautogui` (or download the ready-made app from the GitHub
Releases page: no Python needed). Everything stays on this computer.

Not affiliated with or endorsed by Follett or Aspen.
"""
import argparse
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

__version__ = "0.1.0"

# ============================================================================
# 1. Name matching (no third-party dependencies, no GUI; unit-tested separately)
# ============================================================================


def norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    s = re.sub(r"['’`]", "", s)
    s = re.sub(r"[^a-z0-9\s-]", " ", s)
    s = s.replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def lev(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i]
        for j in range(1, len(b) + 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (0 if a[i - 1] == b[j - 1] else 1)))
        prev = cur
    return prev[-1]


def name_candidates(raw):
    """Plausible (last, first, swapped) readings of a pasted name.

    "Last, First" is one candidate; the swapped reading ("First, Last") is also tried but can
    never rate better than 'check'. Without a comma ("First Middle Last") every last-name length
    from 1 to 3 words is tried.
    """
    raw = str(raw or "")
    if "," in raw:
        i = raw.index(",")
        a, b = norm(raw[:i]), norm(raw[i + 1:])
        return [(a, b, False), (b, a, True)]
    t = [x for x in norm(raw).split(" ") if x]
    if len(t) <= 1:
        return [(t[0] if t else "", "", False)]
    return [(" ".join(t[-k:]), " ".join(t[:-k]), False) for k in range(1, min(3, len(t) - 1) + 1)]


def split_aspen_name(name):
    if "," in name:
        i = name.index(",")
        last, first = norm(name[:i]), norm(name[i + 1:])
    else:
        last, first = norm(name), ""
    return {"last": last, "first": first, "first_tokens": first.split(" ") if first else []}


def score_pair(cand, st):
    l, f, swapped = cand
    if l == st["last"]:
        last_exact = True
    elif len(l) >= 5 and lev(l, st["last"]) <= 1:
        last_exact = False
    else:
        return 0.0
    ft = f.split(" ") if f else []
    sf = st["first_tokens"]
    if not ft:
        return 1.6 if last_exact else 0.0
    if f == st["first"]:
        fs = 3.0
    elif all(i < len(sf) and t == sf[i] for i, t in enumerate(ft)):
        fs = 2.5  # "Maria" vs "Maria Elena Rose Park"
    elif sf and ft[0] == sf[0]:
        fs = 2.0  # same first name, different middle names
    elif any(t in sf for t in ft):
        fs = 1.2  # preferred name is one of the middle names
    elif len(ft[0]) >= 4 and sf and lev(ft[0], sf[0]) <= 1:
        fs = 1.0  # one-letter typo
    elif len(ft[0]) == 1 and sf and ft[0] == sf[0][0]:
        fs = 0.9  # initial only
    else:
        return 0.0
    s = fs + 1 if last_exact else fs * 0.8
    return min(s, 2.9) if swapped else s


def match_name(raw, roster):
    """roster: list of dicts with idx/last/first/first_tokens. Returns (idx|None, status)."""
    cands = name_candidates(raw)
    scored = []
    for st in roster:
        s = max(score_pair(c, st) for c in cands)
        if s >= 1.7:
            scored.append((s, st["idx"]))
    scored.sort(reverse=True)
    if not scored:
        return None, "none"
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.01:
        return None, "ambig"
    return scored[0][1], ("ok" if scored[0][0] >= 3 else "check")


# ============================================================================
# 2. Parsing the clipboard text
# ============================================================================

NUM = re.compile(r"^-?\d+(\.\d+)?$")


def clean_score(s):
    return str(s if s is not None else "").replace(",", "").strip()


def is_num(s):
    return bool(NUM.match(clean_score(s)))


def parse_delimited(text, d="\t"):
    rows, row, cell, q, i = [], [], "", False, 0
    while i < len(text):
        c = text[i]
        if q:
            if c == '"':
                if i + 1 < len(text) and text[i + 1] == '"':
                    cell += '"'
                    i += 1
                else:
                    q = False
            else:
                cell += c
        elif c == '"' and cell == "":
            q = True
        elif c == d:
            row.append(cell.strip())
            cell = ""
        elif c == "\n":
            row.append(cell.strip())
            rows.append(row)
            row, cell = [], ""
        else:
            cell += c
        i += 1
    row.append(cell.strip())
    rows.append(row)
    return [r for r in rows if any(c != "" for c in r)]


def parse_table(text):
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return []
    if "\t" in text:
        return parse_delimited(text, "\t")
    out = []  # no tabs: "Last, First 85" per line
    for line in text.split("\n"):
        if not line.strip():
            continue
        m = re.match(r"^(.*?)[,;\s]+(-?\d+(?:\.\d+)?)\s*$", line)
        out.append([m.group(1).strip(), m.group(2)] if m else [line.strip(), ""])
    return out


def guess_columns(rows):
    n = max([len(r) for r in rows] + [0])
    if n <= 1:
        return {"n": n, "name_col": 0, "score_col": -1}
    name_col, best = 0, -1
    for c in range(n):
        alpha = sum(1 for r in rows if c < len(r) and re.search(r"[a-z]", r[c], re.I) and not is_num(r[c]))
        if alpha > best:
            best, name_col = alpha, c
    score_col = -1
    for c in range(n - 1, -1, -1):
        if c == name_col:
            continue
        filled = [r for r in rows if c < len(r) and r[c] != ""]
        nums = [r for r in filled if is_num(r[c])]
        if nums and len(nums) >= 0.5 * len(filled):
            score_col = c
            break
    if score_col < 0:
        score_col = -1 if n - 1 == name_col else n - 1
    return {"n": n, "name_col": name_col, "score_col": score_col}


_HEADERS = {"name", "names", "student", "students", "student name", "full name", "roster"}


def parse_roster_ex(text):
    """Return (names, clean).

    The expected input is ONE clean column, one 'Last, First' per line (a header row such as 'Name' is
    ignored). `clean` is False when the text looks like a messy copy from Aspen (extra columns, other
    text mixed in). In that case we still do our best (the first cell of every line that looks like a
    'Last, First' name) so the caller can show the result and let the person confirm it.
    """
    lines = [l.strip(" \t\xa0") for l in str(text or "").replace("\r", "").split("\n")]
    lines = [l for l in lines if l]
    if lines and "," not in lines[0] and "\t" not in lines[0] and norm(lines[0]) in _HEADERS:
        lines = lines[1:]
    clean = bool(lines) and all("\t" not in l and "," in l and l[0].isalpha() and len(l) < 90 for l in lines)
    if clean:
        return [re.sub(r"\s+", " ", l) for l in lines], True
    names = []
    for line in lines:
        if not line[0].isalpha():
            continue
        first = line.split("\t")[0].strip(" \t\xa0")
        if "," in first and len(first) < 90:
            names.append(re.sub(r"\s+", " ", first))
    return names, False


def parse_roster(text):
    return parse_roster_ex(text)[0]


# ============================================================================
# 3. Plan: which score goes to which roster row, and the keystrokes to type it
# ============================================================================


def build_plan(sheet_text, roster_names):
    roster = []
    for i, n in enumerate(roster_names):
        d = {"idx": i, "name": n}
        d.update(split_aspen_name(n))
        roster.append(d)
    slots = [{"roster": r["name"], "pasted": None, "score": None, "status": "none",
              "include": False, "note": "not in your paste, will be skipped"} for r in roster]
    extras = []
    rows = parse_table(sheet_text)
    info = guess_columns(rows)
    for k, r in enumerate(rows):
        pasted = r[info["name_col"]] if info["name_col"] < len(r) else ""
        value = clean_score(r[info["score_col"]]) if 0 <= info["score_col"] < len(r) else ""
        idx, status = match_name(pasted, roster)
        if k == 0 and idx is None and value and not is_num(value):
            continue  # header row
        if idx is None:
            extras.append({"pasted": pasted, "score": value,
                           "note": "ambiguous: matches more than one student" if status == "ambig"
                           else "no matching student in the roster"})
            continue
        slot = slots[idx]
        if slot["pasted"] is not None:
            extras.append({"pasted": pasted, "score": value,
                           "note": "duplicate: %s already used for %s" % (slot["pasted"], slot["roster"])})
            continue
        slot["pasted"], slot["score"] = pasted, value
        if value == "":
            slot.update(status="blank", include=False, note="no score in paste")
        elif not is_num(value):
            slot.update(status="nan", include=False, note="not a number")
        elif status == "check":
            slot.update(status="check", include=False, note="fuzzy name match: double-click to include")
        else:
            slot.update(status="ok", include=True, note="will type")
    return slots, extras, info


def steps_from_slots(slots):
    steps = []
    for s in slots:
        steps.append(("type", s["score"]) if s["include"] else ("skip", None))
    while steps and steps[-1][0] == "skip":
        steps.pop()  # nothing to do after the last typed score
    return steps


def actions_from_steps(steps, nudge=True):
    """Flat list of ('write'|'press', arg, pause_after). Enter and Down both mean 'next student'."""
    acts = []
    if nudge and len(steps) > 1:
        # Make sure Aspen has put keyboard focus in the clicked cell, even if the click did not.
        acts += [("press", "down", True), ("press", "up", True)]
    for kind, val in steps:
        if kind == "type":
            acts += [("write", val, False), ("press", "enter", True)]
        else:
            acts.append(("press", "down", True))
    return acts


def run_actions(actions, typer, delay=0.3, should_stop=lambda: False, on_progress=None):
    done = 0
    for kind, arg, pause in actions:
        if should_stop():
            break
        if kind == "write":
            typer.write(arg)
        else:
            typer.press(arg)
        done += 1
        if on_progress:
            on_progress(done, len(actions))
        if pause:
            typer.sleep(delay)
    return done


# ============================================================================
# 4. Typing backends
# ============================================================================


class PyAutoGUITyper:
    def __init__(self):
        import pyautogui  # imported lazily so the matching code runs without it
        pyautogui.PAUSE = 0
        pyautogui.FAILSAFE = True  # slam the mouse into a screen corner to abort
        self.pg = pyautogui

    def write(self, text):
        self.pg.write(str(text), interval=0.03)

    def press(self, key):
        self.pg.press(key)

    def sleep(self, s):
        time.sleep(s)


def active_window_title():
    try:
        import pyautogui
        return pyautogui.getActiveWindowTitle()
    except Exception:
        return None  # not supported on this OS (e.g. macOS): the check is skipped


# ============================================================================
# 5. Saved rosters (stored only in your own home folder)
# ============================================================================

STORE = Path(os.environ.get("OGTS_DIR") or (Path.home() / ".ogts")) / "rosters.json"


def load_rosters():
    try:
        return json.loads(STORE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_rosters(d):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(d, indent=1), encoding="utf-8")


# ============================================================================
# 6. Window
# ============================================================================


ROSTER_HELP = (
    "The roster must be ONE clean column of names: one student per line, written 'Last, First', "
    "in the same order Aspen lists your class.\n\n"
    "Copying straight from Aspen is messy because it grabs the neighboring columns too. Easy fix:\n"
    "  1. In Aspen, select the names and copy them.\n"
    "  2. Paste into a new Google Sheet.\n"
    "  3. Delete every column except the names.\n"
    "  4. Select just the names column, copy it, and come back here.\n\n"
    "Another way: export your class list from Aspen with Reports and copy the names column out of it.\n\n"
    "After you copy, this program shows what it found so you can check it before saving."
)


def run_gui(smoke=False):
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog

    root = tk.Tk()
    root.title("Open Grade Transfer System")
    root.geometry("760x640")

    rosters = load_rosters()
    state = {"slots": [], "extras": [], "roster_names": [], "running": False, "stop": False}

    # ---------- layout ----------
    main = ttk.Frame(root, padding=10)
    main.pack(fill="both", expand=True)

    ttk.Label(main, text="1. Class roster: one clean column of 'Last, First' names, in Aspen's order",
              font=("", 10, "bold")).pack(anchor="w")
    r1 = ttk.Frame(main)
    r1.pack(fill="x", pady=(2, 8))
    roster_var = tk.StringVar()
    combo = ttk.Combobox(r1, textvariable=roster_var, values=sorted(rosters), width=18, state="readonly")
    combo.pack(side="left")
    roster_info = ttk.Label(r1, text="")
    roster_info.pack(side="left", padx=8)
    r1b = ttk.Frame(main)
    r1b.pack(fill="x", pady=(0, 8))

    ttk.Label(main, text="2. Your grades (copy the name + score columns in your spreadsheet first)",
              font=("", 10, "bold")).pack(anchor="w")
    r2 = ttk.Frame(main)
    r2.pack(fill="x", pady=(2, 4))
    summary = ttk.Label(r2, text="Nothing loaded yet.")
    summary.pack(side="left", padx=8)

    cols = ("include", "roster", "pasted", "score", "note")
    tree = ttk.Treeview(main, columns=cols, show="headings", height=14)
    for c, w, t in (("include", 60, "Type?"), ("roster", 220, "Aspen roster"), ("pasted", 190, "Pasted as"),
                    ("score", 60, "Score"), ("note", 200, "Note")):
        tree.heading(c, text=t)
        tree.column(c, width=w, anchor="w")
    tree.tag_configure("ok", foreground="#1a7f37")
    tree.tag_configure("check", foreground="#9a6700", background="#fff7e0")
    tree.tag_configure("bad", foreground="#b42318", background="#fdecea")
    tree.tag_configure("skip", foreground="#777777")
    tree.pack(fill="both", expand=True)
    extras_lbl = ttk.Label(main, text="", foreground="#b42318", wraplength=700, justify="left")
    extras_lbl.pack(anchor="w", pady=(4, 0))

    ttk.Label(main, text="3. Go", font=("", 10, "bold")).pack(anchor="w", pady=(8, 0))
    ttk.Label(main, wraplength=700, justify="left",
              text="Press Go, then CLICK the first student's cell in the Aspen column you want to fill. "
                   "Typing starts when the countdown ends and saves to Aspen immediately, just like typing by "
                   "hand. To abort, move the mouse into a corner of the screen.").pack(anchor="w")
    r3 = ttk.Frame(main)
    r3.pack(fill="x", pady=6)
    ttk.Label(r3, text="Seconds per student:").pack(side="left")
    delay_var = tk.StringVar(value="0.3")
    ttk.Spinbox(r3, from_=0.15, to=2.0, increment=0.05, textvariable=delay_var, width=5).pack(side="left", padx=4)
    go_btn = ttk.Button(r3, text="Go")
    go_btn.pack(side="left", padx=12)
    practice_btn = ttk.Button(r3, text="Practice in the box below")
    practice_btn.pack(side="left")
    practice_box = tk.Text(main, height=3, width=40)
    practice_box.pack(fill="x")

    strip = ttk.Frame(root, padding=8)  # compact status shown while typing
    strip_lbl = ttk.Label(strip, text="", wraplength=320, justify="left")
    strip_lbl.pack(side="left")
    cancel_btn = ttk.Button(strip, text="Cancel")
    cancel_btn.pack(side="right")

    # ---------- roster handling ----------
    def set_roster(names, label):
        state["roster_names"] = names
        roster_info.config(text="%s: %d students" % (label, len(names)))
        refresh_plan()

    def on_pick(_e=None):
        names = rosters.get(roster_var.get(), [])
        set_roster(names, roster_var.get())

    combo.bind("<<ComboboxSelected>>", on_pick)

    def read_clipboard():
        try:
            return root.clipboard_get()
        except tk.TclError:
            return ""

    def show_roster_help():
        messagebox.showinfo("How to get your roster", ROSTER_HELP)

    def roster_from_clipboard():
        names, clean = parse_roster_ex(read_clipboard())
        if not names:
            messagebox.showwarning("No roster found",
                                   "I couldn't find any 'Last, First' names on the clipboard.\n\n" + ROSTER_HELP)
            return None
        sample = names[:3] + (["..."] + names[-2:] if len(names) > 5 else names[3:])
        msg = "Found %d names:\n\n%s\n\n" % (len(names), "\n".join(sample))
        if clean:
            msg += "Is this your whole class, in the same order Aspen shows it?"
        else:
            msg += ("WARNING: this did not look like a single clean column of names (extra columns or other "
                    "text were mixed in), so I picked out what looked like names. Check the list carefully.\n"
                    "Use it anyway?")
        if not messagebox.askyesno("Check your roster", msg, icon="question" if clean else "warning"):
            return None
        return names

    def save_roster():
        names = roster_from_clipboard()
        if names is None:
            return
        label = simpledialog.askstring("Save roster", "Name for this class (for example P1):", parent=root)
        if not label:
            return
        rosters[label] = names
        save_rosters(rosters)
        combo.config(values=sorted(rosters))
        roster_var.set(label)
        set_roster(names, label)

    def use_once():
        names = roster_from_clipboard()
        if names is not None:
            roster_var.set("")
            set_roster(names, "(clipboard, not saved)")

    def delete_roster():
        label = roster_var.get()
        if label and messagebox.askyesno("Delete roster", "Delete saved roster %s?" % label):
            rosters.pop(label, None)
            save_rosters(rosters)
            combo.config(values=sorted(rosters))
            roster_var.set("")
            set_roster([], "none")

    ttk.Button(r1b, text="Save roster from clipboard...", command=save_roster).pack(side="left")
    ttk.Button(r1b, text="Use clipboard roster once (don't save)", command=use_once).pack(side="left", padx=6)
    ttk.Button(r1b, text="Delete", command=delete_roster).pack(side="left")
    ttk.Button(r1b, text="How do I get the roster?", command=show_roster_help).pack(side="left", padx=6)

    # ---------- grades / preview ----------
    def refresh_plan():
        for i in tree.get_children():
            tree.delete(i)
        if not state["roster_names"] or not state.get("sheet"):
            return
        slots, extras, info = build_plan(state["sheet"], state["roster_names"])
        state["slots"], state["extras"] = slots, extras
        for i, s in enumerate(slots):
            tag = {"ok": "ok", "check": "check", "blank": "bad", "nan": "bad"}.get(s["status"], "skip")
            tree.insert("", "end", iid=str(i), tags=(tag,),
                        values=("YES" if s["include"] else "no", s["roster"], s["pasted"] or "", s["score"] or "", s["note"]))
        update_summary()

    def update_summary():
        n_type = sum(1 for s in state["slots"] if s["include"])
        n_skip = len(state["slots"]) - n_type
        summary.config(text="%d will be typed, %d skipped, %d pasted rows unmatched" % (n_type, n_skip, len(state["extras"])))
        if state["extras"]:
            extras_lbl.config(text="Not matched: " + "; ".join("%s (%s)" % (e["pasted"], e["note"]) for e in state["extras"]))
        else:
            extras_lbl.config(text="")

    def load_grades():
        text = read_clipboard()
        if not text.strip():
            messagebox.showwarning("Clipboard is empty", "Copy the name and score columns in your spreadsheet first.")
            return
        state["sheet"] = text
        if not state["roster_names"]:
            messagebox.showinfo("Pick a roster", "Choose or save a class roster first (step 1), then load grades again.")
            return
        refresh_plan()

    ttk.Button(r2, text="Load grades from clipboard", command=load_grades).pack(side="left")

    def toggle(_e=None):
        sel = tree.selection()
        if not sel:
            return
        s = state["slots"][int(sel[0])]
        if s["status"] in ("ok", "check"):
            s["include"] = not s["include"]
            tree.set(sel[0], "include", "YES" if s["include"] else "no")
            update_summary()

    tree.bind("<Double-1>", toggle)

    # ---------- typing ----------
    def compact(on):
        if on:
            main.pack_forget()
            strip.pack(fill="both", expand=True)
            root.update_idletasks()
            w, h = 360, 90
            root.geometry("%dx%d+%d+%d" % (w, h, root.winfo_screenwidth() - w - 20, root.winfo_screenheight() - h - 80))
            root.attributes("-topmost", True)
        else:
            strip.pack_forget()
            main.pack(fill="both", expand=True)
            root.attributes("-topmost", False)
            root.geometry("760x640")

    def finish(msg, compact_mode):
        state["running"] = False
        if compact_mode:
            compact(False)
        root.lift()
        messagebox.showinfo("Open Grade Transfer System", msg)

    def start(practice):
        if state["running"]:
            return
        steps = steps_from_slots(state["slots"])
        n_type = sum(1 for k, _ in steps if k == "type")
        if not n_type:
            messagebox.showwarning("Nothing to type", "Load grades first. No rows are marked to be typed.")
            return
        if not practice and not messagebox.askyesno(
                "Ready?",
                "This will type %d scores into whichever window is in front.\n\n"
                "Aspen saves each score immediately and this program cannot undo it. "
                "Try a 3-student test column first.\n\nContinue?" % n_type):
            return
        try:
            delay = max(0.1, float(delay_var.get()))
        except ValueError:
            delay = 0.3
        try:
            typer = PyAutoGUITyper()
        except ImportError:
            messagebox.showerror("pyautogui missing", "Install it with:  pip install pyautogui")
            return
        acts = actions_from_steps(steps)
        state.update(running=True, stop=False)
        use_compact = not practice
        if use_compact:
            compact(True)
        secs = 5 if practice else 8

        def tick(left):
            if state["stop"]:
                return finish("Cancelled. Nothing more was typed.", use_compact)
            if left > 0:
                strip_lbl.config(text="Switch to Aspen and CLICK the first student's cell in the column.\nTyping starts in %d..." % left)
                if practice:
                    root.title("Click the practice box. Typing in %d..." % left)
                return root.after(1000, tick, left - 1)
            root.title("Open Grade Transfer System")
            if not practice:
                title = active_window_title()
                if title is not None and "aspen" not in title.lower():
                    return finish("The front window is '%s', not Aspen, so nothing was typed." % title, use_compact)
            strip_lbl.config(text="Typing... (move the mouse into a screen corner to abort)")
            step(0)

        def step(i):
            if state["stop"] or i >= len(acts):
                done_all = i >= len(acts)
                return finish("Typed %d scores. Check the column in Aspen." % n_type if done_all
                              else "Stopped early. Check the column in Aspen to see how far it got.", use_compact)
            kind, arg, pause = acts[i]
            try:
                typer.write(arg) if kind == "write" else typer.press(arg)
            except Exception as e:  # includes pyautogui.FailSafeException
                return finish("Stopped: %s\nCheck the column in Aspen to see how far it got." % e, use_compact)
            root.after(int(delay * 1000) if pause else 20, step, i + 1)

        if practice:
            practice_box.delete("1.0", "end")
        tick(secs)

    def do_cancel():
        state["stop"] = True

    cancel_btn.config(command=do_cancel)
    go_btn.config(command=lambda: start(False))
    practice_btn.config(command=lambda: start(True))

    if rosters:
        first = sorted(rosters)[0]
        roster_var.set(first)
        on_pick()
    if smoke:  # used by automated tests: exercise the window without a person
        results = []
        names, clean = parse_roster_ex("Name\nAlder, Riley Jordan\nBaker, Sam Owen\nCortez, Maria Elena")
        results.append(("clean roster parsed", clean and len(names) == 3))
        set_roster(names, "smoke")
        state["sheet"] = "Cortez, Maria\t91\nAlder, Riley\t88\nBaker, Sam\tabsent"
        refresh_plan()
        rows = tree.get_children()
        results.append(("preview shows every roster row", len(rows) == 3))
        results.append(("scores queued to type", sum(1 for x in state["slots"] if x["include"]) >= 2))
        before = state["slots"][0]["include"]
        tree.selection_set(rows[0])
        toggle()
        results.append(("double-click toggle flips a row", state["slots"][0]["include"] != before))
        compact(True)
        root.update()
        compact(False)
        root.update()
        results.append(("compact strip switches on and off", True))
        rosters["smoke"] = names
        save_rosters(rosters)
        results.append(("roster persists to disk", load_rosters().get("smoke") == names))
        try:
            PyAutoGUITyper()
            results.append(("keyboard library loads", True))
        except Exception as e:
            results.append(("keyboard library loads (%s)" % e, False))
        root.destroy()
        return results
    root.mainloop()


# ============================================================================
# 7. Command line (no window)
# ============================================================================


def run_cli(args):
    roster = parse_roster(Path(args.roster).read_text(encoding="utf-8"))
    sheet = Path(args.grades).read_text(encoding="utf-8")
    slots, extras, _ = build_plan(sheet, roster)
    print("%-34s %-26s %-7s %s" % ("ASPEN ROSTER", "PASTED AS", "SCORE", "ACTION"))
    for s in slots:
        print("%-34s %-26s %-7s %s" % (s["roster"][:33], (s["pasted"] or "")[:25], s["score"] or "",
                                       "TYPE" if s["include"] else s["note"]))
    for e in extras:
        print("UNMATCHED: %s -> %s (%s)" % (e["pasted"], e["score"], e["note"]))
    steps = steps_from_slots(slots)
    n = sum(1 for k, _ in steps if k == "type")
    print("\n%d scores would be typed." % n)
    if not args.go or not n:
        print("(dry run: add --go to type them)")
        return
    typer = PyAutoGUITyper()
    print("Click the FIRST student's cell in Aspen now. Typing starts in %d seconds." % args.wait)
    time.sleep(args.wait)
    title = active_window_title()
    if title is not None and "aspen" not in title.lower():
        sys.exit("Front window is '%s', not Aspen. Nothing typed." % title)
    run_actions(actions_from_steps(steps), typer, delay=args.delay)
    print("Done. Check the column in Aspen.")


def selftest(path):
    """Run inside the packaged app by the build: proves matching, the window toolkit and the keyboard
    library were all bundled. Writes PASS/FAIL lines to `path`."""
    lines, ok = [], True

    def check(label, cond):
        nonlocal ok
        lines.append(("PASS " if cond else "FAIL ") + label)
        ok = ok and bool(cond)

    try:
        names, clean = parse_roster_ex("Alder, Riley Jordan\nBaker, Sam Owen")
        slots, _, _ = build_plan("Alder, Riley\t88", names)
        check("matching works", clean and slots[0]["include"] and slots[0]["score"] == "88")
    except Exception as e:
        check("matching works: %s" % e, False)
    try:
        import tkinter
        tkinter.Tk().destroy()
        check("window toolkit (tkinter) works", True)
    except Exception as e:
        check("window toolkit (tkinter) works: %s" % e, False)
    try:
        PyAutoGUITyper()
        check("keyboard library (pyautogui) loads", True)
    except Exception as e:
        check("keyboard library (pyautogui) loads: %s" % e, False)
    Path(path).write_text("\n".join(lines) + "\nversion " + __version__ + "\n", encoding="utf-8")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="Open Grade Transfer System: type spreadsheet scores into Aspen by simulating a keyboard.")
    ap.add_argument("--cli", action="store_true", help="no window: use files instead")
    ap.add_argument("--roster", help="text file with the Aspen name column (one 'Last, First' per line)")
    ap.add_argument("--grades", help="text file with 'Last, First<TAB>score' rows")
    ap.add_argument("--go", action="store_true", help="actually type (otherwise a dry run is printed)")
    ap.add_argument("--wait", type=int, default=8, help="seconds to click into Aspen before typing")
    ap.add_argument("--delay", type=float, default=0.3, help="seconds between students")
    ap.add_argument("--selftest", metavar="OUTFILE", help="(for builds) check the app works; write results to OUTFILE")
    ap.add_argument("--gui-smoketest", action="store_true", help="(for tests) open the window, exercise it, close it")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args()
    if args.version:
        print(__version__)
        return
    if args.selftest:
        sys.exit(selftest(args.selftest))
    if args.gui_smoketest:
        res = run_gui(smoke=True)
        for label, ok in res:
            print(("PASS " if ok else "FAIL ") + label)
        sys.exit(0 if all(ok for _, ok in res) else 1)
    if args.cli:
        if not (args.roster and args.grades):
            ap.error("--cli needs --roster and --grades")
        run_cli(args)
    else:
        run_gui()


if __name__ == "__main__":
    main()
