# Aspen Paste Grades (v0.1)

Paste `Last, First <tab> score` rows from a spreadsheet into one assignment column of your Aspen gradebook.
No permissions, no network calls, no stored data (the undo buffer lives in the tab's sessionStorage and vanishes when the tab closes).

## Install (pick one)

**C. Bookmark (works on a locked-down managed Chrome)**
Open `install-bookmarklet.html` in Chrome, drag the **Aspen Paste** button to your bookmarks bar, then click that bookmark while on the Aspen Scores page.


**A. Chrome extension (cleanest)**
1. Open `chrome://extensions`, turn on **Developer mode** (top right).
2. Unzip this folder, click **Load unpacked**, choose the folder containing `manifest.json`.

**B. Tampermonkey (if Developer mode is locked by your district)**
1. Install Tampermonkey from the Chrome Web Store.
2. Create a new script, paste in the whole of `aspen-paste.user.js`, save.

## Use
1. In Aspen go to Gradebook > Scores (the grid with one column per assignment).
2. Click the blue **Paste grades** button (bottom right).
3. Pick the assignment column, then paste from your sheet (select name + score cells, copy, paste).
4. Review the table. Green = new, amber = replaces an existing score or fuzzy name match, red = needs your attention.
   Only green rows are pre-checked. Tick "Also replace existing scores" if you want to overwrite placeholder 0s.
   Any row's Aspen student and score can be changed by hand before filling.
5. Press **Fill**. The result line tells you how many cells Aspen confirmed as saved. **Undo last fill** restores the previous scores.

## Important
- Aspen saves each cell to the server the moment it is filled (same as typing and tabbing away). The preview and Undo are the safety net.
- Names are matched as Last, First (Aspen's long middle names are fine; accents, hyphens and "First Last" order are handled). Close-but-not-exact names are flagged for you to confirm.
- Built from a saved copy of one Aspen Scores page. If Aspen changes its markup, the selectors in `readStudents` / `readColumns` are the first place to look.
- This tool handles student grade data only inside your own browser. Check your district's acceptable-use policy on custom extensions/userscripts.
