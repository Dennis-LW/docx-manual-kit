# Starting from a requirements spec

When the only input is a requirements / functional spec, do not start writing manual prose. A spec says what the system *does*; a manual says which screen the operator is on and what they press. Bridge the two with three planning artefacts first, get them confirmed, then shoot and write. Each artefact is a file in the project so the next sprint edits it instead of redoing it.

## Step 1: Coverage map (spec → chapters)

Walk the spec requirement by requirement and assign each to a screen in the navigation. Output `manuals/coverage.md`:

```markdown
| Req | Spec section | System | Screen / menu item | Manual chapter | Notes |
|---|---|---|---|---|---|
| R-12 | 4.3 高額訂單審核 | Admin web | 訂單管理 → 待審核分頁 | admin §10.4 | needs an order above the threshold |
| R-12 | 4.3 | Customer app | 訂單詳情 → 審核中狀態 | app §7.2 | same requirement, two systems |
| R-30 | 6.1 退貨申請 | Admin web + customer web | 退貨申請 / 申請退貨頁 | scenario S3 | cross-system → scenario manual |
```

Rules that fall out of this table:
- One chapter per navigation item, in navigation order - operators find things by menu, not by requirement number.
- A requirement that touches two systems appears twice; a requirement that is a *flow* across systems becomes a scenario manual (情境手冊) instead of a chapter.
- Requirements with no screen (background jobs, scheduled expiry) go into the "notes / what happens automatically" block of the nearest chapter, not their own chapter.
- Gaps show up here: a requirement you cannot place means the spec is missing the UI, ask before writing.

## Step 2: Manual skeleton (Markdown)

Generate one `.md` per manual from the coverage map, with empty bodies and placeholder figures. Each chapter has the same four blocks so readers learn the rhythm:

```markdown
## 10. 訂單管理

**用途**：<one sentence, from the spec>

![訂單管理列表](admin-10-order-list.png)
> 📸 待補新圖：`admin-10-order-list.png`：列表有 5 筆以上資料，含一筆「待審核」tag

### 10.4 高額訂單審核
1. <step>
2. <step>

![待審核分頁](admin-10-order-list-review-tab.png) ![審核通過確認框](admin-10-order-approve-dialog.png)
> 📸 待補新圖：左：待審核分頁有資料；右：按「審核通過」後的確認框

**注意**：<exceptions, permissions, what happens automatically>
```

Add the front matter every manual needs: title, environment line (which environment, capture date, UI language), how to log in, and at the end a roles & permissions table if the system has roles and an FAQ block to fill from support questions later.

Write the figure lines *now*, with final file names (see writing-guide naming), even though no image exists. The skeleton is then a complete list of what to shoot, and `docx_build.py` will refuse to build until every image exists - that refusal is your progress check.

## Step 3: Shot list and demo data

Extract every `![…](file.png)` plus its `📸` note into `manuals/shots.md`:

```markdown
| File | System | Path to reach it | Required state | Account | Mutates data? |
|---|---|---|---|---|---|
| admin-10-order-list.png | Admin web | 訂單管理 | ≥5 orders, one pending review | admin | no |
| admin-10-order-approve-dialog.png | Admin web | 訂單詳情 → 審核通過 | order pending review | admin | yes - approves; reset via PATCH /orders/:id status=pending |
| app-07-checkout-blocked.png | App | 購物車 → 結帳 | customer account frozen | demo-customer-frozen | no |
```

The "Required state" column is the expensive part and the reason to plan before shooting: every state needs an account or record that is in it, and a way to put it back. Create dedicated demo accounts (obvious names, complete profiles), seed the records, and write down the API call or admin action that flips each state both ways. Group rows by account and state so one login produces many shots; that grouping becomes the `SHOTS` array of the Playwright script or the `SHOT_SET`s of the Flutter test.

Show the coverage map, skeleton and shot list to the client or product owner before shooting. Changing a chapter title costs nothing here and a re-shoot later.

## Step 4: Shoot, then write

Shoot per the web / app references. Then write the step text *against the screenshots*, not against the spec: the spec says "the system validates the passport number", the screenshot shows the exact red text and where it appears, and that is what the operator needs. Keep the spec open only for the "what happens automatically" notes.

Build with `docx_build.py`. The first build usually reveals a few figures that should have been block crops rather than full pages; fix the shot list, re-shoot those, rebuild.

## Step 5: Make the next sprint cheap

- Tag every paragraph you add or change for a release with a stable marker at its start (`[NEW 1.2]`, `v1.2 新增：`). `docx_extract.py` selects on it to produce the client's delta document.
- Keep coverage map, skeleton Markdown, shot list, demo-account notes and the shooting scripts in the project repo; the .docx is a build output.
- When a requirement changes, update the coverage map row first - it tells you which chapters and which shots are affected.
