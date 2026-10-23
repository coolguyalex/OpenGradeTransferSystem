"""Tests use invented names only. Run: python -m pytest"""
import ogts

ROSTER = ["Alder, Riley Jordan", "Baker, Sam", "Cortez-Reyes, Maria Elena", "Diaz, Jamal", "Evans, Priya Anne", "Foster, Liam"]


def test_clean_roster_detected():
    names, clean = ogts.parse_roster_ex("Name\n" + "\n".join(ROSTER))
    assert clean and names == ROSTER


def test_messy_roster_flagged_not_clean():
    messy = "".join("%s \t\t\n20%02d\tM\t9021587\n" % (n, i) for i, n in enumerate(ROSTER))
    names, clean = ogts.parse_roster_ex(messy)
    assert not clean
    assert all(n in names for n in ROSTER)


def test_empty_roster():
    assert ogts.parse_roster_ex("")[0] == []


def plan(sheet):
    return ogts.build_plan(sheet, ROSTER)


def test_exact_and_reordered_names_match():
    slots, extras, _ = plan("Alder, Riley\t88\nSam Baker\t92\n")
    assert slots[0]["include"] and slots[0]["score"] == "88"
    assert slots[1]["include"] and slots[1]["score"] == "92"
    assert not extras


def test_hyphen_and_extra_middle_names():
    slots, _, _ = plan("Cortez Reyes, Maria\t75")
    assert slots[2]["score"] == "75"


def test_one_letter_typo_goes_to_double_check():
    slots, _, _ = plan("Baker, Sam\t90\nFoster, Liem\t80")
    assert slots[5]["status"] in ("check", "ok") and slots[5]["score"] == "80"


def test_non_numeric_and_blank_not_typed():
    slots, _, _ = plan("Diaz, Jamal\tabsent\nEvans, Priya\t")
    assert not slots[3]["include"] and slots[3]["status"] == "nan"
    assert not slots[4]["include"] and slots[4]["status"] == "blank"


def test_unknown_student_is_reported_not_typed():
    slots, extras, _ = plan("Nobody, Zed\t50")
    assert len(extras) == 1 and not any(s["include"] for s in slots)


def test_duplicate_row_is_reported():
    _, extras, _ = plan("Baker, Sam\t90\nBaker, Sam\t91")
    assert len(extras) == 1


def test_header_row_ignored():
    slots, extras, _ = plan("Student\tQuiz\nBaker, Sam\t90")
    assert slots[1]["score"] == "90" and not extras


def test_keystroke_plan_skips_missing_students_and_trims_tail():
    slots, _, _ = plan("Alder, Riley\t88\nCortez-Reyes, Maria\t75")
    steps = ogts.steps_from_slots(slots)
    assert steps == [("type", "88"), ("skip", None), ("type", "75")]
    acts = ogts.actions_from_steps(steps, nudge=False)
    assert acts == [("write", "88", False), ("press", "enter", True), ("press", "down", True),
                    ("write", "75", False), ("press", "enter", True)]


class FakeTyper:
    def __init__(self):
        self.log = []

    def write(self, t):
        self.log.append(("write", t))

    def press(self, k):
        self.log.append(("press", k))

    def sleep(self, s):
        pass


def test_run_actions_replays_in_order():
    t = FakeTyper()
    n = ogts.run_actions([("write", "9", False), ("press", "enter", True)], t)
    assert n == 2 and t.log == [("write", "9"), ("press", "enter")]


def test_sample_files_work_together():
    from pathlib import Path
    base = Path(__file__).parent.parent / "samples"
    names, clean = ogts.parse_roster_ex((base / "sample-roster.txt").read_text())
    slots, extras, _ = ogts.build_plan((base / "sample-grades.txt").read_text(), names)
    assert clean and sum(1 for s in slots if s["include"]) == 4 and not extras
