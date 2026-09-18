# docx-manual-kit

Produce and maintain **customer-facing operation manuals as .docx** with programmatic screenshots. Ships as a skill in the open [Agent Skills](https://agentskills.io) `SKILL.md` format: works with **Claude Code** (plugin or plain skill) and **OpenAI Codex CLI**, and with any agent that reads `SKILL.md`. The scripts are plain Python and Bash with no agent dependency.

[繁體中文](README.zh-TW.md)

Manuals are re-issued every time the UI changes. The expensive parts are capturing dozens of consistent screenshots, getting them into a Word file that keeps the client's styling, and doing it again next sprint. This kit turns each into a script run:

| Workflow | Script |
|---|---|
| Build a manual from Markdown + screenshots, inheriting styles from an existing .docx | `docx_build.py` |
| Swap outdated screenshots inside a .docx in place (backup, same pixel size, verified) | `docx_replace_images.py` |
| List every figure with its caption / size / hash; diff two versions | `docx_inspect.py`, `docx_figures_diff.py` |
| Assemble a "what changed" delta document from sections of existing manuals | `docx_extract.py` |
| Capture app screenshots from a Flutter integration test via adb | `shots_watch.sh` + `assets/manual_shots_helpers.dart` |
| Capture web screenshots with Playwright | `assets/web_shots.template.js` |
| Crop system bars | `trim_screenshot.py` |

The skill file (`skills/docx-manual/SKILL.md`) tells the agent which workflow applies and the references explain the .docx internals (Google Docs `w:sdt` headings, per-file media names, cross-document numbering/style import, orphan image pruning) and the screenshot pitfalls (secure-screen black frames, `pumpAndSettle` hangs, lock screens).

## Requirements

- Python ≥ 3.9 with `pip install -r requirements.txt` (python-docx, Pillow, lxml)
- For app screenshots: Flutter SDK, adb, an unlocked device or emulator
- For web screenshots: Node ≥ 18 and Playwright

## Install

### As a Claude Code plugin (recommended)

```bash
claude plugin marketplace add Dennis-LW/docx-manual-kit
claude plugin install docx-manual@docx-manual-kit
```

### As a plain Claude Code skill

```bash
git clone https://github.com/Dennis-LW/docx-manual-kit.git
cp -r docx-manual-kit/skills/docx-manual ~/.claude/skills/
```

### Codex CLI

Codex reads skills from `~/.codex/skills`. Clone the repo and symlink (or copy) the skill there; the scripts resolve from the skill directory, so nothing else changes:

```bash
git clone https://github.com/Dennis-LW/docx-manual-kit.git
ln -s "$PWD/docx-manual-kit/skills/docx-manual" ~/.codex/skills/docx-manual   # Windows: mklink /D
```

Then `pip3 install -r docx-manual-kit/requirements.txt` and ask Codex the same way you would ask Claude ("the dialog style changed, update the manual screenshots").

## Quick start

```bash
# what is in the client's manual?
python skills/docx-manual/scripts/docx_inspect.py Manual.docx --figures

# the order-confirmation dialog changed: replace the figures that show it
python skills/docx-manual/scripts/docx_replace_images.py Manual.docx \
  --set "caption:訂單已送出=shots/order_success_dialog.png" \
  --set "caption:訂單已送出（左）#0=shots/order_success_dialog.png"

# build a new manual from Markdown, styled like the old one
python skills/docx-manual/scripts/docx_build.py manual.md --template Manual.docx --out Manual-v2.docx --images-dir images

# delta document for a release
python skills/docx-manual/scripts/docx_extract.py --spec release-notes.json --out Update-Notes.docx
```

With the skill installed you just tell Claude "the dialog style changed yesterday, update the manual screenshots" and it follows the same steps.

## Layout

```
skills/docx-manual/
├── SKILL.md                 workflow selection + rules
├── scripts/                 docxkit.py library + CLI tools + shots_watch.sh
├── references/              writing-guide, docx-internals, web-screenshots, app-screenshots
└── assets/                  manual.example.md, spec examples, Dart helpers, Playwright skeleton
test/                        pytest for the docx tools (no external files needed)
```

## Test

```bash
pip install -r requirements.txt
python -m pytest test -q
```

## License

MIT
