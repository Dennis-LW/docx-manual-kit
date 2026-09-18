---
name: docx-manual
description: Produce and maintain customer-facing operation manuals as Word (.docx) files with programmatic screenshots - build a manual from Markdown + screenshots using an existing .docx as the style template, swap outdated screenshots inside a .docx in place, renumber figures, and assemble a "what changed" delta document from sections of existing manuals; plus the screenshot workflows for web (Playwright) and mobile apps (Flutter integration_test + adb). USE THIS SKILL whenever the user mentions an operation manual, user guide, 操作手冊, 情境手冊, 使用說明, 系統手冊, 更新手冊圖片, 換截圖, 差異文件 / 更新功能說明, "put the screenshots into the Word doc", "the UI changed, update the manual", "make a manual for the client", or wants screenshots captured systematically for documentation - even if they only say "docx" and "screenshots" together. Not for one-off Word documents with no screenshots or manuals (use a plain docx skill), and not for slide decks.
---

# docx-manual

Customer manuals are a deliverable that gets re-issued every time the UI changes. The expensive parts are never the prose: they are (1) capturing dozens of consistent screenshots, (2) getting them into a .docx that keeps the client's styling, and (3) doing it again next sprint without redoing everything. This skill makes each of those a script run instead of a manual afternoon.

All scripts live next to this file in `scripts/`. Resolve the path from this skill's directory: as a Claude Code plugin that is `${CLAUDE_PLUGIN_ROOT}/skills/docx-manual/scripts/`; as a Codex CLI skill it is `~/.codex/skills/docx-manual/scripts/`; as a plain copied skill `~/.claude/skills/docx-manual/scripts/`. This file is plain Agent Skills format, so the instructions apply whichever agent is reading them. Scripts need `pip install python-docx Pillow lxml` and every one has `--help`.

## Pick the workflow

| Situation | Go to |
|---|---|
| The client has an existing .docx manual and the UI changed | **A. Refresh screenshots in place** |
| Only a requirements / functional spec exists, no manual yet | **B0. Plan from the spec**, then B |
| Writing a new manual (or a new chapter) from scratch | **B. Build from Markdown** |
| Client wants only "what changed since the last version" | **C. Extract a delta document** |
| No screenshots yet | **D. Capture screenshots** first, then A/B/C |

## Preflight: check tools, let the user install

Run the read-only checks for the workflow you picked before doing anything else, so a missing tool is found now and not after an hour of script writing. Installing changes the user's machine, so never install on your own: list what is missing with the exact command, say what it costs (download size, admin rights), and let the user run it or tell you to.

| Needed for | Check | If missing, tell the user |
|---|---|---|
| Every docx workflow | `python3 -c "import docx, PIL, lxml"` | `pip3 install -r <skill>/requirements.txt` (pure Python, small) |
| Web screenshots | `node --version`; `npx playwright --version`; `ls ~/.cache/ms-playwright` (Chromium present?) | `npm i -D playwright && npx playwright install chromium` (~150 MB download). Alternative: an already-installed Playwright skill, or the user captures the few pages by hand |
| App screenshots | `adb devices` lists a device; `flutter --version` | These are environment problems, not installs: name what is missing (SDK, USB debugging, unlocked device) and stop |

`shots_watch.sh` performs the adb check itself and exits 3 with a clear message; do not read its "locked device" exit 2 as an install problem or vice versa.

Before any of them, read the writing rules in `references/writing-guide.md` once per project: they decide what to shoot (full page vs. cropped block), how captions are phrased, and which demo accounts and data must exist before shooting.

## A. Refresh screenshots in place

The .docx is the source of truth here; do not rebuild it, patch it.

1. Map what is inside: `python scripts/docx_inspect.py MANUAL.docx --figures` prints every image as `media name | pixel size | md5 | caption`. Media names (`image50.png`) are per file - the same screenshot has a different name in another .docx, so always map per document by caption.
2. Decide which figures the UI change affects. Grep captions for the changed component ("彈窗", "dialog", the screen name) and confirm visually: extract candidates and build a contact sheet (Pillow) rather than trusting caption text alone - captions describe intent, not what the pixels show.
3. Re-shoot only those (section D). Same device, same locale, same demo data as the originals so the manual stays visually consistent.
4. Replace: `python scripts/docx_replace_images.py MANUAL.docx --set "caption:訂單已送出=shots/order_success_dialog.png" --set "image53.png=shots/blocked.png"`. The script backs the file up (`<name>.<date>.bak.docx`), resizes the new PNG to the old pixel size so the layout does not move, rewrites the media part only, and re-opens the result to verify. Use `#0`/`#1` after a caption key when two images share one caption (left/right).
5. Verify with `docx_figures_diff.py OLD.bak.docx MANUAL.docx` - it should list exactly the figures you meant as RESHOT and nothing as NEW/REMOVED.

Why patch instead of rebuild: client manuals are often Google Docs / Word exports with hand-tuned styling that a regenerator would flatten. Replacing bytes inside `word/media/` keeps every run, table, and header untouched.

## B0. Plan from the spec

A spec says what the system does; a manual says which screen the operator is on and what they press. Do not write prose from the spec. Follow `references/from-spec.md`: map each requirement to a screen and chapter (coverage table), generate the Markdown skeleton with placeholder figure lines and final file names, derive the shot list with the state / account / reset method each shot needs, and get those three artefacts confirmed before shooting. Then continue with D and B. The skeleton's missing images double as the progress check: `docx_build.py` refuses to build until every figure exists.

## B. Build from Markdown

Write the manual as Markdown (one file per manual), keep screenshots in an `images/` folder, and pick one .docx whose styles you want to inherit (the client's previous manual, or a blank doc saved from their template). Then:

```bash
python scripts/docx_build.py manual.md --template client-template.docx --out Manual-v2.docx --images-dir images
```

Supported Markdown: `#`/`##`/`###` headings, paragraphs with `**bold**`/`*italic*`, bullet and numbered lists, pipe tables, `![caption](path)` figures (auto-numbered `圖 N：` - change with `--figure-format "Figure {n}: "`), two images on one line for a left/right pair sharing one caption, `---` horizontal rule, `<!-- pagebreak -->`, and `>` notes. See `assets/manual.example.md` for one of everything.

The template's body is cleared but its styles, numbering, headers/footers and page setup are kept, so the output looks like the client's document. If the template is a Google Docs export, headings may be wrapped in `w:sdt`; the scripts read text through `w:t` so that is transparent.

Keep the Markdown in the project repo. Next sprint you edit the text, re-shoot the changed images with the same file names, and rebuild - nothing is hand-edited in Word.

## C. Extract a delta document

Clients who know the old manual want a short "what changed" file, not a re-read. Assemble it from the existing manuals with a spec instead of copy-pasting in Word:

```bash
python scripts/docx_extract.py --spec delta.json --out Update-Notes.docx
```

The spec (example in `assets/extract_spec.example.json`) names a `package` document (its styles become the output's, and it supplies the heading/paragraph/table/HR templates), other `sources`, and an ordered `parts` list: headings, free paragraphs, ranges of source elements selected by the text a paragraph starts with (`start`/`end` prefixes), single figures by caption, tables, HRs and page breaks. Elements pulled from a non-package source are imported properly (image relationships, list numbering, table styles, hyperlinks) - the three things that silently break when you deep-copy XML across documents. Figures are renumbered in order of appearance and unreferenced images are pruned, otherwise the delta file ships with every picture of the full manual inside it.

Tag changed paragraphs in the full manuals with a stable marker (`v2.3 新增：`, `[NEW 2.3]`) when you write them; the delta spec then selects by that marker instead of by fragile section numbers.

## D. Capture screenshots

Screenshots are the bulk of the work, so they are automated, repeatable, and driven by demo data you control.

- **Web back-offices and member sites**: Playwright. Rules, viewport sizes and a skeleton script are in `references/web-screenshots.md` (`assets/web_shots.template.js`). Key rule: never take one giant `fullPage` capture of a long admin page; capture one viewport per logical section so figures stay legible on A4.
- **Flutter / native mobile apps**: an integration test drives the app on a real device or emulator and prints a marker when a screen is ready; a host-side watcher (`scripts/shots_watch.sh`) takes a native screenshot at each marker so status bars and dialogs look exactly like production. Pattern, stubs and the pitfalls (secure-screen black frames, shimmer animations that hang `pumpAndSettle`, image pickers) are in `references/app-screenshots.md`; the Dart helpers to copy into the project are `assets/manual_shots_helpers.dart`.
- Crop system bars only if the client wants it: `scripts/trim_screenshot.py`. Keep the untrimmed originals; manuals usually embed full screenshots at a fixed pixel size.

Shooting writes real data in the test environment (bookings, submissions, generated codes). Say so in the report, and prefer dedicated demo accounts whose state you can reset via the backend API (many "state X" screens - pending review, expired plan - are reachable only by flipping a flag server-side, then flipping it back).

## Reporting back

When the run touches a client file, the final message should say: which figures changed (by caption), where the backup is, what test-environment data was created or mutated, and what could not be re-shot and why (feature hidden behind a flag, account state unavailable). That list is what the next person needs to finish the job.

## Reference files

- `references/from-spec.md` - starting with only a requirements spec: coverage map, Markdown skeleton, shot list and demo data before any shooting.
- `references/writing-guide.md` - what to shoot, caption format, demo accounts, placeholders for pending figures. Read once per project.
- `references/docx-internals.md` - the OOXML facts these scripts rely on; read before hand-editing XML or debugging a broken output.
- `references/web-screenshots.md` - Playwright workflow.
- `references/app-screenshots.md` - Flutter/adb workflow.
