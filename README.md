# Open Grade Transfer System

**Type a column of grades from your spreadsheet into Aspen for you.**

You copy two columns from your spreadsheet (student name + score). The program matches the names to your Aspen class list, shows you a preview, and then types each score into the right student's box, just like you would by hand, only faster. It is smart about names: *"Riley Alder"*, *"Alder, Riley"* and *"Alder, Riley Jordan"* all match the same student.

Everything runs on your own computer. Nothing is uploaded anywhere.

> This is an independent, free project. It is **not** made by, affiliated with, or endorsed by Follett or Aspen.

---

## 1. Get the program (no Python, no installing)

1. Go to the **[Releases page](../../releases/latest)** of this repository.
2. Download the file for your computer:
   - **Windows:** `OpenGradeTransferSystem-Windows.exe`
   - **Mac:** `OpenGradeTransferSystem-Mac.zip` (double-click it to unzip)
3. Double-click to open it. That's it.

**The first time you open it, your computer may warn you.** That is normal for small free programs that aren't from a big company.

| Computer | What you see | What to do |
|---|---|---|
| Windows | "Windows protected your PC" | Click **More info**, then **Run anyway** |
| Mac | "cannot be opened because the developer cannot be verified" | **Right-click** (or Control-click) the app, choose **Open**, then **Open** again |
| Mac | Typing does nothing the first time | Open **System Settings > Privacy & Security > Accessibility**, switch on **OpenGradeTransferSystem**, then reopen the app |

If your school computer blocks programs you download, you will need your IT department to allow it (or use a personal computer). The program only presses keys on your keyboard, but school computers are often locked down.

---

## 2. One-time setup: save your class roster

The program needs to know your students **in the same order Aspen lists them**, so it can tell which box belongs to whom.

### The roster must be ONE clean column of names

One student per line, written **Last, First**, nothing else:

```
Alder, Riley Jordan
Baker, Sam
Cortez-Reyes, Maria Elena
```

**Do not copy straight from Aspen.** Aspen's table is messy: copying the names also grabs the columns next to them (IDs, grades, blank cells), and the program can't reliably tell what is a name.

**The easy fix: use a Google Sheet as a cleaning step**

1. In Aspen, select your class's names and copy them (Ctrl+C on Windows, Cmd+C on Mac).
2. Open a new Google Sheet and paste (Ctrl+V / Cmd+V) into cell A1.
3. Delete every column except the one with the names.
4. Click the letter at the top of that column to select just the names, and copy it.
5. In this program, click **Save roster from clipboard...**

**Another way:** export your class list from Aspen using its **Reports** feature, open the file, and copy just the names column.

When you save, the program shows you how many names it found plus the first and last few, and asks you to confirm. If something looks wrong, say No and redo the copy. If the program thinks extra columns got mixed in, it warns you in red-flag wording.

Give the roster a name like `P1` or `Period 3`. Next time, just pick it from the dropdown. You only do this once per class (again if students are added or dropped).

Don't want your roster saved? Use **Use clipboard roster once (don't save)**. (Check your school's policy on student data; saved rosters live in a small file in a folder called `.ogts` in your home folder, and you can delete a roster any time with the **Delete** button.)

---

## 3. Every time you enter grades

1. **In your spreadsheet,** select the **name column and the score column** (two columns next to each other, no extra columns) and copy. Names can be any normal style: `Last, First` or `First Last`. A header row is fine.
2. **In this program,** pick your class from the dropdown, then click **Load grades from clipboard**.
3. **Read the preview.** Every student in your Aspen list appears with the grade the program will type.
   - Green / **YES**: will be typed.
   - **no**: will be skipped (no score, "absent" or other text, or the student wasn't in your paste). Skipped students are simply stepped over, so their boxes stay as they were.
   - Yellow "fuzzy match": the name was close but not exact (a typo, a nickname). It is **not typed unless you double-click the row** to switch it to YES.
   - Red text at the bottom lists spreadsheet rows that matched nobody. Fix the spelling in your sheet and load again if you want them included.
4. **Open Aspen** to your gradebook and the assignment column you want to fill.
5. Click **Go** here. A countdown starts (about 8 seconds). During it, **click the FIRST student's box** in the Aspen column.
6. Hands off! The program types down the column. Watch it go, then glance over the column to check it.

### IMPORTANT: there is no undo
Typed scores are saved by Aspen as they go. **The first time, try it on a short test**: copy just 3 students into your spreadsheet selection and run those, or use the **Practice in the box below** button, which types into a box inside this program instead of Aspen so you can see exactly what would happen.

### To stop in an emergency
Slam your mouse into any **corner of the screen**, or click **Cancel** on the little strip.

---

## Troubleshooting

| Problem | Try this |
|---|---|
| "I couldn't find any names on the clipboard" | Re-copy the names using the Google Sheet method above. |
| Scores landed one row off | The first box you clicked must be the first student **in your roster**. If you skip students at the top, the roster/Aspen order must still match. |
| Nothing is typed (Mac) | Give the app **Accessibility** permission (table above), then reopen it. |
| Nothing is typed (Windows) | Make sure the Aspen window is the front window when typing starts. The program checks that "Aspen" is in the window's title and refuses to type otherwise. |
| A student is missing from the preview | Their name isn't in the roster you saved. Re-save the roster. |
| A name shows as "fuzzy match" | Double-click it to include it, or fix the spelling in your sheet. |
| Roster order changed in Aspen (new student, sorting) | Re-copy your roster using the steps above and save it again. |

---

## For developers

Pure Python 3.9+, one file (`ogts.py`), one dependency (`pyautogui`). It simulates keystrokes, so it needs no access to Aspen's code or your login.

```
pip install -r requirements.txt
python ogts.py                       # the window
python ogts.py --cli --roster samples/sample-roster.txt --grades samples/sample-grades.txt        # dry run
python -m pytest                     # tests (invented names only)
```

- `.github/workflows/build.yml` runs the tests, opens the window in a virtual screen as a smoke test, builds the Windows `.exe` and Mac `.app` with PyInstaller, checks that each built app launches, and attaches them to a GitHub Release whenever you push a tag like `v0.1.0`.
- The Mac build is for Apple-silicon Macs.
- `extras/chrome-extension/` holds an older browser-based version (a Chrome extension/bookmarklet). It works only where the browser lets you run it, which managed school Chrome profiles often don't.
- Please never commit real student names. Tests and samples use invented names.

## License
MIT. Free to use, change and share.
