# Writing guide for operation manuals

The audience is a non-technical operator at the client (front desk, finance, customer service). Every rule below exists because a real reader got lost without it.

## What to shoot

- **Full-page figure** for introducing a screen: home, a list page, a detail page. One per screen, taken at the standard size for that platform (see the screenshot references). Readers use it to recognise where they are.
- **Block figure** for every key operation: the button, the field, the status dropdown, the dialog, the red validation text. Crop to the component (or draw a red frame on the full page) so the reader can match it at a glance. A manual section with a step-by-step procedure needs at least one block figure; a wall of full pages is not a manual.
- **Dialogs and toasts** must be shot in the state the text describes (success dialog with a real order number, blocked dialog with the real reason). Never fake them with mock-ups: the client compares the picture against their screen.
- **Left/right pairs** ("before/after", "form / result", "list / detail") go in one figure with one caption when they belong to one step. It halves the page count.
- Shoot in the language the client operates in. Mixed-language screenshots read as unfinished.

## Captions

- One numbering scheme per document, sequential in order of appearance: `圖 12：訂單管理 - 付款方式欄`, `Figure 12: Order list - payment column`. Sub-numbers (`圖 10-3`) are allowed inside a chapter when the chapter is stable and the client references them, but the delta-document builder renumbers everything flat.
- Caption = screen name, then ` - ` and the specific thing shown. For pairs: `圖 45：訂單已送出（左）與訂單列表（右）`.
- The caption names what is *shown*, the body text says what to *do*. Do not put instructions in captions.
- Mark changed content with a stable textual tag at the start of the paragraph (`v2.3 新增：`, `v2.3 異動：`, `[NEW 2.3]`). It lets readers skim, and it is what `docx_extract.py` selects on when you produce the delta document.

## Demo data and accounts

Screenshots must be reproducible next sprint, so the data behind them is part of the deliverable:

- Create **dedicated demo accounts** in the test environment for the manual (`demo-operator@…`, `demo-customer@…`) with complete profiles and obvious display names (`手冊示範-一般客戶`). Never shoot with shared team accounts whose state drifts.
- Record, in the project's manual README: each account, its password policy, which manual sections it serves, and which screenshot runs **mutate** it (creating a booking, submitting a form for review). A run that changes state should be re-runnable: know the backend call that resets the state (re-approve, cancel, delete) and write it down.
- Some screens exist only in a transient state (pending review, expired plan, unbound child). Reach them by flipping the state through the backend API or an admin action, shoot, then flip back. Document the flip.
- Screenshots contain test data (names, phones). Before external distribution decide whether they need masking; use obviously fake values in demo accounts so they never need it.

## Placeholders while writing

Write the text first and mark every figure that still needs a shot; then run all shots in one batch. Use one blockquote marker so they can be grepped:

```
> 📸 待重擷（全圖）：商品列表排序 chips 改版
> 📸 待重擷（區塊）：狀態下拉，框選「已出貨」
> 📸 待補新圖：`app-07-delete-account.png`：刪除帳號確認頁
```

Keep a progress table (manual → text rewritten ✅ / screenshots redone ⬜) in the README; it is the hand-off document between sessions.

## File naming

`<system-prefix>-<section>-<screen>[-<block>].png`, e.g. `hq-10-member-list.png`, `hq-10-member-list-review-tab.png`, `app_booking_success.png`. Prefixes per system (`hq-`, `clinic-`, `member-`, `app-`, scenario `s1-`…). Block crops add a descriptive suffix rather than a new number. Re-shoots keep the **same file name** so a Markdown rebuild picks them up without edits.

## Structure of a manual

1. Title, environment note (which environment, capture date, UI language), how to log in.
2. One chapter per menu item / screen, in the order of the navigation. Each: purpose (one sentence), full-page figure, numbered steps with block figures, notes/exceptions.
3. Roles & permissions table when the system has roles.
4. FAQ of the questions support actually receives.

A **scenario manual** (情境手冊) is different: one end-to-end business flow across systems (customer places an order → store confirms → warehouse ships → customer sees the tracking number), each step showing which system and which account acts. Write these when operators need to understand hand-offs between teams.
