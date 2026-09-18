# docx-manual-kit

以程式化截圖產製並維護**交付客戶的 .docx 操作手冊**。以開放的 [Agent Skills](https://agentskills.io) `SKILL.md` 格式提供：**Claude Code**（plugin 或直接放 skill 目錄）與 **OpenAI Codex CLI** 都能用，任何會讀 `SKILL.md` 的 agent 亦可。腳本是純 Python 與 Bash，不依賴任何 agent。

[English](README.md)

手冊每次 UI 改版都要重出。真正花時間的不是文字，而是：拍幾十張一致的截圖、塞進客戶樣式的 Word 檔而不破壞排版、下個 sprint 再來一次。這個工具組把每一件事變成一行指令：

| 情境 | 腳本 |
|---|---|
| 從 Markdown ＋ 截圖產生手冊，樣式繼承既有 .docx | `docx_build.py` |
| 就地換掉 .docx 內過時的截圖（自動備份、維持像素尺寸、驗證可開） | `docx_replace_images.py` |
| 列出所有圖的圖說／尺寸／hash；比對兩個版本差異 | `docx_inspect.py`、`docx_figures_diff.py` |
| 從既有手冊擷取段落組成「更新功能說明」差異文件 | `docx_extract.py` |
| Flutter integration test ＋ adb 拍 APP 截圖 | `shots_watch.sh` ＋ `assets/manual_shots_helpers.dart` |
| Playwright 拍 Web 截圖 | `assets/web_shots.template.js` |
| 裁掉系統列 | `trim_screenshot.py` |

`skills/docx-manual/SKILL.md` 告訴 agent 該走哪條流程；references 說明 .docx 內部細節（Google Docs 匯出的 `w:sdt` 標題、media 名稱各檔獨立、跨文件搬 numbering／table style、清掉未引用圖片）與截圖的坑（FLAG_SECURE 黑圖、`pumpAndSettle` 卡死、鎖定畫面）。

## 需求

- Python ≥ 3.9，`pip install -r requirements.txt`（python-docx、Pillow、lxml）
- APP 截圖：Flutter SDK、adb、已解鎖的實機或模擬器
- Web 截圖：Node ≥ 18 與 Playwright

## 安裝

### 以 Claude Code plugin 安裝（建議）

```bash
claude plugin marketplace add Dennis-LW/docx-manual-kit
claude plugin install docx-manual@docx-manual-kit
```

### 直接放 Claude Code skill 目錄

```bash
git clone https://github.com/Dennis-LW/docx-manual-kit.git
cp -r docx-manual-kit/skills/docx-manual ~/.claude/skills/
```

### Codex CLI

Codex 從 `~/.codex/skills` 讀 skill。clone 後把 skill 目錄 symlink（或複製）過去即可，腳本會從 skill 自己的目錄解析路徑，不需要其他調整：

```bash
git clone https://github.com/Dennis-LW/docx-manual-kit.git
ln -s "$PWD/docx-manual-kit/skills/docx-manual" ~/.codex/skills/docx-manual   # Windows: mklink /D
```

然後 `pip3 install -r docx-manual-kit/requirements.txt`，對 Codex 說法與對 Claude 相同（「彈窗樣式改了，幫我更新手冊截圖」）。

## 快速上手

```bash
# 客戶手冊裡有哪些圖？
python skills/docx-manual/scripts/docx_inspect.py Manual.docx --figures

# 訂單確認彈窗改版：換掉顯示它的圖
python skills/docx-manual/scripts/docx_replace_images.py Manual.docx \
  --set "caption:訂單已送出=shots/order_success_dialog.png"

# 從 Markdown 產新手冊，樣式沿用舊檔
python skills/docx-manual/scripts/docx_build.py manual.md --template Manual.docx --out Manual-v2.docx --images-dir images

# 產出本次 release 的差異文件
python skills/docx-manual/scripts/docx_extract.py --spec release-notes.json --out 更新功能說明.docx
```

裝好 skill 後，直接對 Claude 說「昨天彈窗樣式改了，幫我更新手冊截圖」，它就會照同一套步驟做。

## 目錄

```
skills/docx-manual/
├── SKILL.md                 流程選擇與規則
├── scripts/                 docxkit.py 函式庫 ＋ CLI 工具 ＋ shots_watch.sh
├── references/              寫作規範、docx 內部、Web 截圖、APP 截圖
└── assets/                  manual.example.md、spec 範例、Dart helpers、Playwright 骨架
test/                        docx 工具的 pytest（不依賴外部檔案）
```

## 測試

```bash
pip install -r requirements.txt
python -m pytest test -q
```

## 授權

MIT
