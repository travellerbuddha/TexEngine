# TEX Pricing Workspace: UX gap analysis and design

Status: DESIGN, revision 3 (no code yet) · Baseline: `main` f855850 (worktree `/home/user/tex-pricing-ws`) · Owner: TEX Commercial
Related: `PRODUCT_SPEC.md` (contracts, pricing), ADR-004 (immutable versions), ADR-006 (op arithmetic, no stacking), ADR-007 (no global child default), ADR-043 (occupancy precedence, CASCADE v2), ADR-045 (selling terms, header lock), ADR-055 (9-place decimals). A new **ADR-061** will record the decisions in §0.

> The Pricing Workspace changes the UX only. The pricing engine, the rule ops, the precedence rules, the payload schema (`tex.contract.v1`) and the save/publish lifecycle stay as they are. The server remains the only place prices are computed.

**Revision 3 fixes** (critic round 2):
- **The Explain ladder is now a true before → after chain in the engine's own order** (§3.13). The Period stage only identifies the period; its amount effect (`PERIOD_ADJUSTMENT`) appears where the engine applies it: after Board, before Rate plan (`engine.py:458-465`). The order is stated on screen and in D14.
- **Occupancy (adults only), Child and Board subtotals now come from the server.** A small additive backend change, **GAP-12**, adds `subtotal_adults`, `subtotal_children` and `subtotal_board` to the internal `nights[]` of the quote. These are running totals the engine already holds; no price changes (§4, slice S5). The client does not add up slot amounts or board supplements (D2).
- **The Playwright step 12 assertion now reads only server fields:** Room 80.00 → 108.00, Occupancy (adults) 108.00 → 216.00 (`nights[].unit` → `subtotal_adults`), Child 216.00 → 270.00 (`subtotal_adults` → `subtotal_children`, child line 54.00 from `CHILD_SLOT.after`), Board 270.00 → 270.00 (`occupancy` → `subtotal_board`), Night cost 270.00 (§5.3).
- **The slice dependencies are complete** (§7). S12 and S13 list S8. Every slice that reads `minor_units` lists S2. `useWorkspaceHistory` moved into S9, so S11 no longer depends on S10 implicitly. The `issueTab` change moved from S4 to S8, so no two slices rewrite the same function in different orders.

Revision 2 fixes (round 1), still in force: the bookengine study is recorded (§1.4); step 1 (choose PERSON) happens in the workspace through a non-modal basis popover (§3.2.1); engine defaults are shown (D12); band codes are replaced by labels (D13); the room-matrix rule for relative entries is decided by the row (D11); the AMBIGUOUS rule is currency-aware (O5); the board mapping follows the owner's table (O1–O3); read-only viewers do not call endpoints they cannot use (§3.14).

---

## 0. Summary and key decisions

The version editor today has ten tabs (Rooms, Periods, Room prices, Child ages, Occupancy, Boards, Rate plans, Offers, Settings, Price check), one per database table. Entering an ORS-style contract means going back and forth between them: about **100 clicks, 7 tab switches, ~35 typed fields, 7 modal dialogs and a forced save** before any price can be checked (§1.3). The backend can already store and price every part of the target model. What is missing is a workspace that matches how a revenue manager thinks about a contract, plus a few API gaps (§4).

| # | Decision |
|---|---|
| D1 | The workspace is a **projection** over the existing `EditorState` (`settings`, the 8 `tables`, `selling`). Every gesture turns into ordinary `period_rates` / `occupancy_rules` / `age_bands` / `rooms` / `periods` / `boards` rows. The save payload, `payloadOf`, the fingerprint and `save_version` stay unchanged. |
| D2 | **The client does no arithmetic on money or rule values.** Resolved prices, occupancy totals, price-test subtotals, bulk adjustments and adjustments of entered base prices are computed by the server. The tools are a **read-only draft overlay** (the unsaved state is applied in memory and never saved), `apply_op_values` and the quote's `nights[]` subtotals (GAP-12). The client only parses, normalises and compares decimal strings. |
| D3 | **There is no autosave** of the version. Save stays explicit (button or Ctrl/Cmd+S), sends the whole payload, is audited, and keeps `settle()`/`overSaved`. Live feedback comes from the overlay, so the forced save before previewing goes away. (The pricing basis is a contract-header field. It is saved by its own explicit Apply, §3.2.1.) |
| D4 | The shorthand parser is **pure, deterministic and locale-independent**. It accepts both `.` and `,` as the decimal mark, never allows grouping separators, and refuses anything ambiguous for the contract currency (§3.4). It lives in a module with no runtime imports and is tested with `node --test`. |
| D5 | The ten technical tabs collapse into four sections: **Pricing · Commercial rules · Offers & promotions · Preview & audit**. The old row editors stay available as **Advanced rule tables** inside Commercial rules, so no capability is lost (weekday periods, priorities, notes, raw rules). |
| D6 | The "base room" stays a UI concept (`TEX Contract Room.is_base`). The workspace makes it exclusive (radio behaviour) and uses it as the default `base_room_type` for new formulas. The engine still follows each rule's `base_room_type`. |
| D7 | A period cell **replaces** the room's All-periods rule for that period and never stacks on it (ADR-006). The UI says so in every override cell. |
| D8 | Special combinations are written as ordinary `TEX Occupancy Rule` rows (`combination "a+c"`, `position`, `age_band`). Valid combinations come from room capacity, the same way as the publish sweep. |
| D9 | Validation issues gain an optional, additive `ref` (room, period, rule, band(s), party, board). Codes and messages do not change. |
| D10 | The parser maps shorthand to ops with the **owner's fixed table** in every grid. The only per-context differences are forced by the DocType op lists (e.g. `-20` on a board becomes `ADD -20`, because SUBTRACT is not a board op). They are listed in §0.1. |
| D11 | **In the room matrix, the row decides how a relative entry is stored, never the cell's current state.** On the base room (the `is_base` row, which derives from nothing) a relative entry adjusts the entered price once: the server computes the result and it is stored as ABSOLUTE. On every other room it always writes a formula from the room's default base (§3.4.5). |
| D12 | **Engine defaults are shown** where no rule exists. An adult position shows "Adult ×1.00 (default)" from the server's `occupancy_defaults`. A child band without a rule shows "No rule · not sellable" (ADR-007). |
| D13 | **Band codes never reach the screen where a label exists.** Labels are saved when a band is created or edited. Codes in server text (rule labels, issue messages, unsellable reasons) are replaced by labels on display (§3.8, §3.13). |
| D14 | **The Explain ladder follows the engine's order and is a before → after chain.** The order is Base → Period (identification) → Room → Occupancy (adults) → Child → Special combination → Board → Period adjustment → Rate plan → Night cost → Cost offers → Markup → FX → Promotion → Tax. Each stage's *before* is the previous stage's *after*, and every value is a server field (§3.13). |

### 0.1 Decisions that need owner sign-off

These points either depart from the owner's shorthand table or interpret it. They are implemented as described, marked in ADR-061 and listed on the owner's review checklist. If the owner decides otherwise, each is a small, isolated change in `shorthand.ts` / `model.ts`.

| # | Point | Proposed behaviour | Why | Alternative if rejected |
|---|---|---|---|---|
| O1 | Board cell, bare `100` | **ABSOLUTE 100**, as the owner's table says. On a board this means **100 per room per night** (boards.py: ABSOLUTE = v per room-night). Before commit the reading line says "HB: 100.00 per room per night (fixed)". | Follows the owner's rule literally. | A bare number means `ADD` (per adult) and `=100` means ABSOLUTE. This was the previous proposal, and it matches how board supplements are usually quoted. |
| O2 | Board cell, `-20` | **ADD -20** (per adult). | `SUBTRACT` is not a board op (tex_board_rule.json:37). ADD with a negative value is the only way to store "HB −€20". | None needed: the stored arithmetic is the same. |
| O3 | Board cell, `50%` | **ADJUST_PERCENT 50** (supplement = 50 % of occupancy). | `PERCENT_OF` is not a board op, and the board engine treats both the same (boards.py:45-58). | Refuse `50%` on boards and require `+50%`. |
| O4 | Base room, relative entry (`x1.1`, `+10%`, `-5`, `+5`, `50%`) | The op and value are parsed exactly as the owner's table says. The server then **applies them once to the entered price**, and the result is stored as ABSOLUTE. The reading line says so before commit. | The base room derives from nothing, so MULTIPLY and the other derived ops cannot be stored as a rule on it (validate.py:91-109, ROOM_RULE_NO_BASE / self-derivation). | Refuse relative entries on the base room (OP_NOT_ALLOWED with "use Adjust…"). |
| O5 | Currency-aware AMBIGUOUS | In a 0- or 2-decimal currency, an **amount** written with 1–3 integer digits and exactly 3 fraction digits (`1.500`) is refused with "Type 1500 for one thousand five hundred, or 1.5 for one and a half". In 3-decimal currencies (KWD, BHD, OMR, JOD, TND) it is accepted. | Users in tr/de locales type `1.500` to mean 1500. Silently storing 1.5 would be a 1000× error. | Drop the guard and rely on the reading line. |

---

## 1. Current state and UX gap

### 1.1 How the editor works today (evidence from the study)

- `VersionEditor.tsx` holds one `EditorState` and renders one of ten tabs, synced to `location.hash` (`VersionEditor.tsx:23,41,47-55,143-147`).
- Every edit replaces a whole table array (`setTable`). Save posts every table and setting to `contracts.save_version`, which replaces each table wholesale and strips row names (`api/contracts.py:206-232`).
- `period_rates` is a room × period matrix. Every cell is a button that opens a modal `RuleDialog` (`RatesTab.tsx:127-134,172-275`). The other tables use the generic `RowsEditor`: one form control per field, and no grid keyboard support, selection or paste (`RowsEditor.tsx:12-294`).
- Resolved prices (`price_matrix`) and the price check (`preview_price`) read only the **saved** draft. The rates grid hides every resolved figure as soon as anything is unsaved (`RatesTab.tsx:32-33`; `api/contracts.py:263-313`).
- Validation returns only `{level, code, message}`. Issues are mapped to tabs by code prefix and cannot point at a cell (`validate.py:36-43`; `util.ts:124-146`).
- The pricing basis can be edited only in the modal contract header dialog, and it is locked after the first publish (`ContractDialogs.tsx:80,168`; `contracts.py:151-152`; `tex_contract.py:62-86`).
- Engine defaults are invisible. An adult position with no rule is priced through the module constant `GLOBAL_ADULT_DEFAULT` (MULTIPLY 1; `occupancy.py:48-50,212-217`), which no screen shows.
- Band codes leak:
  - occupancy rule labels are built as `Child 1 [CHB] @2A+2C × 0.5` (`occupancy.rule_ref`, `occupancy.py:82-96`);
  - sweep messages embed `[CHB]` (`validate.py:457-458`);
  - age-band messages name codes (`ages.py:84-94`);
  - a blank label falls back to the code (`contracts.py:120-126`).
- The quote has no subtotals after the adults, after the children, or after occupancy + board. `nights[]` carries unit, occupancy (the full occupancy total), board (the supplement), cost, cost_net, sell_contract, sell and final (`engine.py:45-62`). The period adjustment is applied to occupancy + board, after the board supplement (`engine.py:458-465`).

### 1.2 Gap against the ORS-style workflow

| Owner requirement | Today | Gap |
|---|---|---|
| Understand and enter the main price without changing pages | Rooms, periods, prices, ages, occupancy and boards are six separate tabs | Six places for one mental model |
| Period columns visible while editing | Periods are rows in their own tab; the columns appear only in "Room prices" | Periods cannot be edited where they are used |
| Base / manual / derived / override distinguishable at a glance | Cell text `= 95`, `× 1.15`, `↳ all periods`; the base badge is on the row only; resolved values disappear when there are unsaved edits | Override, inherited and manual cells look nearly alike, and there is no resolved row while editing |
| Inline shorthand entry | A modal dialog for every cell (3 clicks + typing) | No inline entry and no parser |
| Occupancy inside the workspace, with understandable defaults | A flat 10-column `RowsEditor`; engine defaults not shown | Technical rows and no slot ladder. The ×1 adult default and "no child default" are invisible |
| Period-specific occupancy overrides that are obvious | A "Period" select in a row; the precedence surprise (COMBINATION beats PERIOD) is invisible | Overrides are hidden in a table and precedence is not explained |
| Child ages that do not dominate, with readable labels | A full tab. Rules, issues and reasons show band **codes** | Codes leak (`CHB`); labels are optional and fall back to the code |
| Periods: add, rename, dates, duplicate, copy previous, reorder, bulk | Add and dates only, in the Periods tab. Renaming leaves orphan rules (no FK) | No duplicate, copy, rename cascade or bulk apply |
| Bulk productivity (range selection, fill, paste, bulk %, undo) | None (`grep shiftKey\|onPaste` finds nothing in the grids) | Missing entirely |
| PERSON vs ROOM visibly different | Only a unit badge on the rates tab. The basis is read-only in Settings and editable only in a modal outside the editor | Labels and occupancy semantics do not change, and the basis cannot be chosen in the editor |
| Boards next to the prices | A separate tab. Board rules are barely validated (`validate.py:170-177`) | Disconnected; orphan board rows go unnoticed |
| Live price test with Base → … → Tax, before → after | A strong preview tab, but it uses the saved draft only, shows the first night by default and has English-only sentences. No adults-only, children or occupancy + board subtotals | Needs the unsaved state, a drawer, a ladder in engine order, and server subtotals (GAP-12) |
| About four sections instead of ten tabs | Ten tabs | The IA mirrors the database |

### 1.3 The 13-step acceptance workflow: cost today vs target

**Today:** estimated from the code paths in the frontend study. Assumptions: a native `<select>` takes 2 clicks, a typed date takes 1 click + typing, and the room types already exist in the hotel. These counts were **not measured in a browser**.
**Target:** designed counts for the workspace. The Playwright acceptance spec (§5.3) counts clicks, section switches and modal dialogs, and asserts the budget. The measured numbers are recorded in `IMPLEMENTATION_STATUS.md` at S16.

| # | Step | Today: clicks / tab switches / typed / modal dialogs | Target: clicks / section switches / typed / modal dialogs |
|---|---|---|---|
| 1 | Choose PERSON pricing | Not possible in the editor: 4 clicks in the modal header dialog on the contract page (+2 for a new draft), 1 modal | 3 / 0 / 0 / 0 (Basis chip → "Per person" → Apply, in a non-modal popover; unpublished contracts only) |
| 2 | Standard as base room (+ Superior, Deluxe rows) | 3 (+6) / 0 / 0 / 0 | 2 (+4) / 0 / 0 / 0 (the first room gets ★ automatically) |
| 3 | Four stay periods | 13 / 1 / 9 / 0 | 4 / 0 / 5 / 0 (code P1…P4 and start date filled in) |
| 4 | Base person price for 4 periods | 12 / 1 / 4 / 4 | 1 / 0 / 4 / 0 (`70⇥80⇥100⇥130↵`) |
| 5 | Superior = base × 1.15 (P4 × 1.20) | 3 / 0 / 1 / 1 (+4 / 0 / 1 / 1 for P4) | 2 / 0 / 2 / 0 |
| 6 | Deluxe = base × 1.35 (P3–P4 × 1.40) | 3 / 0 / 1 / 1 (+8 / 0 / 2 / 2) | 3 / 0 / 2 / 0 (↓, `x1.35`; click P3, Shift+click P4, `x1.40` Ctrl+Enter) |
| 7 | Third adult × 0.70 | 7 / 1 / 2 / 0 | 2 / 0 / 1 / 0 |
| 8 | Child bands 0–2.99 / 3–6.99 / 7–11.99 | 9 / 1 / 6 / 0 | 5 / 0 / 3 / 0 (bands drawer; "from" and label filled in) |
| 9 | Bands × 0 / × 0.25 / × 0.50 | 18 / 1 / 3 / 0 | 1 / 0 / 3 / 0 (Enter moves down) |
| 10 | 2A+2C: C1 × 0.50, C2 × 0.25 | 9 / 0 / 5 / 0 | 7 / 0 / 2 / 0 (structured builder) |
| 11 | Third adult × 0.80 in one period | 4 / 0 / 1 / 0 | 1 / 0 / 1 / 0 |
| — | Base board + save before the price check | 2 / 1 / 0 / 0 + 1 save | 2 / 0 / 0 / 0, **no save** |
| 12 | Price 2A + child 8 in Deluxe for a stay | 7 / 1 / 3 / 0 | 4 / 0 / 1 / 0 (drawer filled in from the active cell) |
| 13 | See the price and the full explanation | 0–2 + scrolling (first night only) | 0 (ladder visible, all nights) |
| **Σ** | | **≈112 clicks, 7 switches, ≈38 typed, 10 dialogs (incl. the header dialog), 1 forced save** | **≈41 clicks, 0 switches, ≈24 typed, 0 modal dialogs (2 non-blocking drawers, 4 popovers), 0 saves** |

The Playwright budget asserts ≤ 50 clicks, 0 section switches and 0 modal dialogs (§5.3). Keyboard keys (Tab, Enter, arrows) are not counted as clicks.

### 1.4 Old-repository reference (bookengine, UX only)

The owner asked for `travellerbuddha/bookengine` `apps/web/src/components/admin/RateGrid.tsx` (1092 lines) and `RateOccupancyDerivationForm.tsx` (182 lines) to be studied as a **UX reference, not copied**. They were read (read-only) at `/home/user/bookengine`, together with the kit they use (`packages/ui/src/patterns/EditableCell.tsx`, `BulkEditDialog.tsx`, `primitives/undo-toast-logic.ts`, `rate-grid-model.ts`, `rate-grid-csv.ts`).

The old grid is a click-to-edit table over flat daily cells that are written immediately. TEX edits contract **rules** in a **draft** that is saved explicitly and priced by Decimal rules, so no code is reused. The tables below record which concepts were adopted (re-implemented for TEX) and which were rejected.

**Adopted concepts**

| Old concept (evidence) | Where it appears in this design |
|---|---|
| "A preview before, an undo after" for bulk edits (`RateGrid.tsx:81-83`, the D-008 comment) | Adjust… preview and the bulk undo toast (§3.10) |
| A mandatory bulk preview that lists only cells that change: 8 lines + "+N more", confirm disabled when nothing changes or a save is pending (`BulkEditDialog.tsx:41-50,60,70-71`; `rate-grid-model.ts:284-319`) | Adjust… popover (§3.10), with the lines computed by the server (`apply_op_values`) |
| A ten-second undo toast that restores **recorded previous values** and never applies an inverse calculation (`undo-toast-logic.ts:8`; `admin-actions.ts:945-975`) | Toast "Applied to N cells · Undo", visible for 10 s, backed by a persistent Ctrl/Cmd+Z history that also restores recorded rows (§3.10) |
| Select-all on entering edit; Enter commits, Escape reverts, Tab commits and advances (`EditableCell.tsx:56-67,110-126`) | Edit mode (§3.4.1), plus the fixes below |
| Row-scoped bulk via a "⋯" button on the row (`RateGrid.tsx:644-659`) | Row and column header menus and header-click selection (§3.3.5, §3.9, §3.10) |
| Views that keep the row count down (rates / restrictions / allotment / occupancy segments, `rate-grid-model.ts:41-60`) | Collapsible Occupancy and Boards sections under the matrix instead of one mega-matrix (§3.6, §3.12) |
| An "All rooms" form vs a one-room "override" form (`RateOccupancyDerivationForm.tsx:9-19`) | The occupancy **Rooms** scope chip (All rooms / one room) (§3.6.1) |
| Read-only cells state their reason (`RateGrid.tsx:559-569,672-678`) | Read-only state tooltips: "Published versions are immutable", "You can view but not edit this contract" (§3.17) |
| Dense text-xs cells, tabular numbers, 2 px room-block separators, indented sub-rows (`RateGrid.tsx:587-633,686-694`) | Visual direction (§3.18) |
| The bulk value field is focused on open, and the preview updates per keystroke, not on blur (`RateGrid.tsx:219-233,809-829`) | Adjust… popover focus and debounced live preview (§3.10) |
| Stable codes, not display names, as identity in exported data (`rate-grid-csv.ts:23-46`) | TSV copy uses canonical shorthand; rows are identified by `room_type` / `period_code` (§3.10) |

**Rejected concepts (and why)**

| Old behaviour (evidence) | Why rejected | TEX replacement |
|---|---|---|
| Click-only editing, every cell a tab stop, no arrow keys, no typing-to-edit (`EditableCell.tsx:138-146`; `RateGrid.tsx:708-747`) | Slow, with 60 × rows tab stops | Roving-tabindex grid; typing starts an edit (§3.4.1, §3.10) |
| The draft is lost after a failed save (`EditableCell.tsx:52-54,157`) | Loses user input | Invalid or refused entries stay as an error draft (§3.4.1) |
| Locale-dependent money parsing that strips group separators (`money-input-logic.ts:39-55`) | Silent 100× and 1000× errors | Locale-independent parser, no grouping, currency-aware AMBIGUOUS guard (§3.4) |
| Display rounded to whole units (`RateGrid.tsx:241,273`) | Hides real prices | Currency precision from server decimal strings (§3.3.4) |
| JS-number money and `Math.round(base*percent/100)` (`packages/db/src/queries/rate-plans.ts:326`) | Violates Decimal-only money | Server Decimal via the overlay, `apply_op_values` and quote subtotals (D2) |
| Immediate write per cell with an `expected` value token (`admin-actions.ts:832-856`) | TEX edits a draft in memory; nothing is live until publish | Explicit Save with `settle()`/`overSaved` (§3.16). Cross-user concurrency is out of scope (§6) |
| Undo as a server write that restores 0 for a previously absent row (`grid.ts:241-244`) | Can put a room on sale at 0 | Client-side undo on unsaved state; "absent" is restored by deleting the row (§3.10) |
| `RateOccupancyDerivationForm`: percentages **not persisted**, baked absolute amounts, fields defaulting to 0 with an immediate Apply and no preview (`RateOccupancyDerivationForm.tsx:20-27,109-129`) | Destructive, not explainable, and stale when the base changes | Occupancy is persisted as TEX rules, and the resolved totals are shown live before saving (§3.6, §3.7) |
| Bulk edit as a date-range / weekday dialog wizard (`RateGrid.tsx:759-935`) | TEX rates are period rules (columns), not days | Grid gestures over period columns. Date-range splitting stays in the existing ARI rate change (`grid.py:303-374`) |
| CSV import round trip (`rate-grid-csv.ts:132-247`) | Header, duplicate-row and locale pitfalls | TSV clipboard paste, all or nothing (§3.10). CSV is out of scope |
| Flag toggles that fail silently (`RateGrid.tsx:703-705,1079`) | No feedback | Not applicable: every commit is validated and errors are announced |

---

## 2. Target information architecture

```
Contract ▸ Version editor  (tablist "Version sections", hash-synced)
├─ 1 Pricing              #pricing   (default)
│   ├─ Sticky commercial context header (incl. pricing-basis popover)
│   ├─ Room price matrix (period columns)
│   ├─ ▾ Occupancy & child pricing (ladder + special combinations) ── Child ages drawer
│   ├─ ▸ Boards (compact board × period view)
│   └─ Price test / Explain drawer (right side, opened from the header or a cell)
├─ 2 Commercial rules     #rules     (inner tablist "Rule tables")
│   ├─ Rate plans · Settings (stacking, tax flag, change note, selling terms)
│   └─ Advanced rule tables: Rooms · Periods · Room prices · Child ages · Occupancy rules · Boards
│      (the existing RowsEditor/RatesTab views, unchanged; weekdays, priority, notes, raw ops)
├─ 3 Offers & promotions  #offers    (existing OffersTab)
└─ 4 Preview & audit      #preview   (full Price test panel, MatrixCard, all issues, version info)
```

**Hash aliases** keep old links working:
- `#rooms`, `#periods` and `#rates` open `#pricing`.
- `#ages` opens `#pricing` with the Child ages drawer.
- `#occupancy` opens `#pricing` with the occupancy section expanded and scrolled into view.
- `#boards` opens `#pricing` with Boards expanded.
- `#plans` opens `#rules` with the "Rate plans" inner tab; `#settings` opens `#rules` with "Settings".
- `#offers` and `#preview` open their sections.
- Advanced tables can be reached directly as `#rules/rooms`, `#rules/periods`, and so on.

`lists/VersionRows.tsx` switches to the new canonical hashes (`periods → pricing`, `occupancy → occupancy`, `rate_plans → plans`).

The **section issue badges** reuse `countIssues`, with `issueTab` mapping codes to sections:
- **pricing:** ROOM_*, PERIOD_*, NO_PERIODS, NO_ROOMS, ROOM_CAPACITY, INCLUDED_ADULTS, AGE_BANDS*, OCC_*, NO_BASE_BOARD, BOARD_*;
- **rules:** RATE_PLAN_BOARD, SALE_WINDOW, STAY_WINDOW, CURRENCY and anything else;
- **offers:** OFFER_*.

This mapping, including `BOARD_*`, is written once, in S8.

---

## 3. Pricing Workspace design

### 3.1 Layout (desktop ≥ 1280 px)

```
┌ DE-27 · Summer Germany — V3 ● Draft · Unsaved ──────── [Price test] [Validate] [Publish] [Discard] [Save ⌃S] ┐
│ Market DE · Contract EUR · Sell EUR · Basis Per person ▾ · Base room Standard ★ · Base occ. per person ·      │
│ Sale 01.01–31.07.27 · Stay 01.04–31.10.27 · Live check ⛔0 ⚠2                                                  │  ← sticky
├ [Pricing] [Commercial rules] [Offers & promotions] [Preview & audit] ─────────────────────────────────────────┤  ← sticky
│ Room prices · per person per night · EUR      [Fill →] [Fill ↓] [Adjust…] [↶] [↷]  [Show resolved ✓] [⌨ ?]    │
│                          │ All periods │ P1 · Apr  ⋯ │ P2 · May  ⋯ │ P3 · Jun  ⋯ │ P4 · Jul  ⋯ │ + Period     │  ← sticky
│                          │ default     │ 01–30 Apr   │ 01–31 May   │ 01–30 Jun   │ 01–31 Jul   │              │
│ ★ STANDARD  BASE         │             │             │             │             │             │              │
│   Base person price      │      —      │      70.00  │      80.00  │     100.00  │     130.00  │              │
│ SUPERIOR  Standard ×1.15 │             │             │             │             │             │              │
│   Formula                │   ×1.15     │   ↳ ×1.15   │   ↳ ×1.15   │   ↳ ×1.15   │ ◆ ×1.20     │              │
│   Resolved               │             │      80.50  │      92.00  │     115.00  │     156.00  │              │
│ DELUXE  Standard ×1.35   │   ×1.35     │   ↳ ×1.35   │   ↳ ×1.35   │ ◆ ×1.40     │ ◆ ×1.40     │              │
│   Resolved               │             │      94.50  │     108.00  │     140.00  │     182.00  │              │
│ + Add room                                                                                                      │
├ ▾ Occupancy & child pricing   Rooms [All rooms ▾]   Child 1 = oldest ▾   [Child ages…]                           │
│ 1 Adult (single use)     │   ×1.50     │   ↳         │   ↳         │   ↳         │   ↳         │                │
│ 2 Adults         BASE    │   ×1.00 each (default) = 2 × base person price                                     │
│ 3rd adult                │   ×0.70     │   ↳ ×0.70   │   ↳ ×0.70   │   ↳ ×0.70   │ ◆ ×0.80 OVERRIDE │           │
│ 4th adult                │   ×1.00 default (no rule)                                                           │
│ Infant 0–2.99            │   ×0.00     │   ↳         │ …                                                         │
│ Child 3–6.99             │   ×0.25     │   ↳         │ …                                                         │
│ Child 7–11.99            │   ×0.50     │   ↳         │ …                                                         │
│ Special combinations                                                                    [+ Add combination]    │
│  2 Adults + 2 Children → Child 1 ×0.50 · Child 2 ×0.25   (7–11.99 · 3–6.99) · all rooms · all periods  [Edit]   │
│ Resolved · Standard · [2 adults + 1 child 7–11.99 ▾]  │ 175.00 │ 200.00 │ 250.00 │ 325.00 │                        │
├ ▸ Boards   UAI BASE · AI −5 % · HB −20.00 per adult                                                          │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

The **period columns of the matrix, the occupancy ladder and the boards grid share one column template** (a CSS grid with the same `grid-template-columns`), so P1…Pn line up vertically across all three.

### 3.2 Sticky commercial context header

One compact bar, sticky under the app shell (`top: var(--shell-h)`), with two lines at ≥ 1280 px. Below that width the chips wrap, and on phones they collapse into a "Details" disclosure.

| Chip | Source | Editing |
|---|---|---|
| Contract (code · name) | `doc.contract_doc` | Link to the contract page |
| Market | `contract_doc.market` | Read-only (fixed after the first publish; otherwise via "Edit header" on the contract page) |
| Contract currency | `contract_doc.contract_currency` | Read-only, as above |
| Sell currency | `doc.selling.sell_currency` | A popover with a `SellingTerms` field when `selling_editable`; otherwise read-only with "Edited on the contract header" |
| **Pricing basis** | `contract_doc.pricing_basis` | **Basis popover** (non-modal, §3.2.1) while `doc.can_edit_contract && !doc.basis_locked`; otherwise read-only, with 🔒 "Fixed after the first publish" when locked |
| Base room | The `rooms` row with `is_base=1` | A select (the "Set as base" action, §3.3.5) |
| Base occupancy | PERSON: "Per person" (each adult ×1.00 by default, §3.6.2). ROOM: the effective `included_adults` of the base room (from the server, GAP-3) | ROOM: a popover stepper writing `rooms[base].included_adults` |
| Sale validity / Stay validity | `doc.selling` | Popover (as for sell currency) |
| Version / status | `version_no`, `StatusBadge`, "Unsaved", "Read-only" | — |
| Live check | Issue counts (§3.14, §3.15) | A click opens the issue list popover |

The actions keep today's accessible names and states:
- **Save**: the name starts with "Save", `shortcut="Ctrl S"`, `aria-busy`, disabled when there is nothing to save;
- **Discard**;
- **Validate**;
- **Publish**: disabled while there are unsaved changes ("Save your changes first");
- a new **Price test** button, hidden without `can_preview`.

The texts "Published", "Read-only" and "Published versions are immutable" stay on frozen versions.

#### 3.2.1 Pricing basis popover (acceptance step 1)

- **Trigger:** the Basis chip (`aria-haspopup="dialog"`, name "Pricing basis: Per person").
- **Content:**
  - a `Segmented` radiogroup **Per person / Per room**;
  - a one-line consequence, e.g. "Prices in this contract are read as prices per person per night; occupancy is priced per guest";
  - a notice: "This changes the contract header for every version of this contract. It is saved and audited immediately.";
  - **Apply** / Cancel.
- **Apply** calls the **existing** `contracts.save_contract({name: contract_doc.name, pricing_basis})`. That endpoint already updates only the fields present in `data` (`api/contracts.py:76-98`) and requires `contract.edit`. Its controller refuses a basis change once any version was published (`tex_contract.py:62-86`, G-50). No new endpoint is needed.
- **On success**, the returned contract patches `doc.contract_doc.pricing_basis` locally, and the live preview refetches. The version's `EditorState` is not touched, so unsaved rule edits survive.
- **On refusal**, the server message is shown inline in the popover.
- **Visibility:** shown only when `doc.can_edit_contract` and `!doc.basis_locked` (new `get_version` flags, GAP-10). The server re-checks both. The header dialog on the contract page keeps working unchanged.
- It is a popover, not a modal, so step 1 stays within the 0-modal budget. The E2E spec exercises it (§5.3).

### 3.3 The room price matrix

#### 3.3.1 Structure

- **Grid:** `role="grid"`, `aria-label="Room prices by period"` (the caption the E2E helpers use), `aria-rowcount`/`aria-colcount`, a sticky header row (period headers) and a sticky first column (row headers). It keeps AriGrid's z-index ladder: corner 4, headers 2, cells 1.
- **Columns:** row header | **All periods** (the default column, `period_code ''`) | one column per `periods` row, in table order | "+ Period".
- **Rows**, for each contract room in `rooms` table order:
  - **Base room** (`is_base=1`): one row, "★ STANDARD · BASE". Its label is **"Base person price"** (PERSON) or **"Base room price · N adults included"** (ROOM).
  - **Derived room** (it has an All-periods rule with a derived op, or any derived period rule): two rows, **Formula** (editable) and **Resolved** (read-only). The row header states the default derivation in words: "SUPERIOR · Standard ×1.15".
  - **Manual room** (only ABSOLUTE rules): one row, "DELUXE · Manual price", plus a Resolved row when an All-periods ABSOLUTE is used.
- **"Show resolved" toggle:** per viewer, stored in `localStorage` with try/catch, on by default.

#### 3.3.2 Mapping cells to `period_rates`

A cell is identified by `(room_type, period_code)`, where `''` is All periods. At most one non-INHERIT row exists per identity, and the `ROOM_RULE_DUPLICATE` validation stays the backstop. **The row decides how a relative entry is stored (D11); the cell's current state never does.**

| Row | Entry | Row written |
|---|---|---|
| Base room (`is_base`) | `100` / `=100` in a period cell | `{room_type: STD, period_code: P, op: ABSOLUTE, value: "100", base_room_type: null}` |
| Base room | `70` in the All-periods cell | `{STD, '', ABSOLUTE, "70"}` (every period without its own row inherits it) |
| Base room | A relative entry (`x1.1`, `+10%`, `-10%`, `+5`, `-5`, `50%`) on a cell that resolves to an entered price | **Adjust once** (§3.4.5): the server computes the amount (`apply_op_values`), and the row becomes `ABSOLUTE <result>` |
| Base room | A relative entry on a cell with no entered price | Refused: "Enter a price first; the base room derives from no other room." |
| Any other room | `100` / `=245` | `{room, P, ABSOLUTE, "245", base_room_type: null}` (on a derived room this is a "fixed price" override) |
| Any other room | A relative entry (`x1.15`, `50%`, `+10%`, `-10%`, `+25`, `-25`) in any cell, **whatever the cell held** (fixed price, manual price, INHERIT, nothing) | A formula: `{room, P, <op>, "<value>", base_room_type: <default base>}`. Typing `x1.20` into Superior P4 while it holds `= 245` stores `MULTIPLY 1.2` from Standard, which restores a formula |
| Any other room | A relative entry while the contract has no base room and the room has no default base | Refused: "Choose a base room first (row menu → Set as base)." |
| Any row | Empty input or Delete | Remove that identity's row. A period cell falls back to the default. An All-periods cell leaves the room without a default (the `missing` state if no period row covers it) |
| Any row | A period entry equal to the default (same op, value and base, compared as canonical strings) | The period row is **removed**, not duplicated: "same as default" |

The **default base** of a room is the `base_room_type` of its All-periods rule if there is one, else the `is_base` room. **Chained derivation** (Deluxe from Superior) is set with the row menu "Derive from…". To change the **entered** prices of a manual room or a fixed override by a percentage, the user selects them and uses **Adjust…** (§3.10), which is explicit that it targets entered prices.

#### 3.3.3 Cell states (classification is a pure function `cellState(tables, room, period)`)

| State | When | Visual (never colour alone) | Screen-reader text |
|---|---|---|---|
| `manual` | Its own ABSOLUTE row on a base or manual room | Solid ink on white; amount formatted with currency precision | "entered price" |
| `formula-default` | All-periods derived rule | `×1.15` in ink colour | "formula for all periods" |
| `inherited` | No own row, and a default exists | `↳ ×1.15` in muted grey | "follows all periods" |
| `period-override` | Its own row differs from the default | `◆ ×1.20` on an amber tint with a corner triangle; tooltip "P4 replaces the default ×1.15: Standard ×1.20" | "period override" |
| `fixed-override` | Its own ABSOLUTE on a derived room | `= 245.00` with a pin icon on an amber tint | "fixed price overriding the formula" |
| `inherit-rule` | Its own INHERIT row | `↳` plus a small "inherit" tag | "inherits" |
| `missing` | No row resolves (server `NO_ROOM_PRICE`) | Red dashed outline, "—" | "no price" |
| `error` | An issue `ref` points here, or the resolved cell has an error | Red underline plus a ⚠ icon; message via `aria-describedby` | The message |
| `resolved` | Resolved row | Tabular numerals on a zinc-50 background, read-only | "resolved price" |
| `stale` | The resolved value belongs to an older state than the one on screen | Opacity 0.55 plus a spinner in the column header | "updating" |
| selection / active | — | 2 px focus ring on the active cell; blue-50 range tint; `aria-selected` | — |

#### 3.3.4 Resolved values

Resolved values come **only from the server**: `price_matrix(version, data=<unsaved payload>)` (§3.14, §4 GAP-1). The response carries:
- `cells`: the unit as an exact decimal string;
- `sources`: the winning rule, its scope, the derivation chain and the overridden rules (§4 GAP-2).

The matrix shows the amount with the contract currency's minor units through the existing `Money`/format helpers (display only). A cell whose `sources` scope is `PERIOD` while the client state says inherited is a bug signal and is logged in dev builds.

#### 3.3.5 Rooms in the matrix

- **+ Add room:** a select of the hotel's room types not yet in the contract. The first room added becomes base (★).
- **Row header menu (⋯):**
  - **Set as base**: exclusive. The previous base keeps its ABSOLUTE rows and becomes a manual room. A checkbox "Re-point formulas that use Standard to Deluxe" is on by default.
  - **Derive from…**: changes `base_room_type` on the room's All-periods rule and, optionally, on its period rules.
  - **Capacity…**: a drawer with `max_adults`, `max_children`, `max_occupants`, `min_adults` and `included_adults` (0 = from the room type). The effective value from the server is shown as the placeholder.
  - **Move up / down.**
  - **Remove room**: confirms inline with the number of dependent rows ("removes 5 prices, 2 occupancy rules, 1 board rule") and removes them.

### 3.4 Inline entry and the shorthand grammar

#### 3.4.1 Editing model

- **Navigation mode** (the active cell has focus):
  - arrows move;
  - typing a printable character starts **edit mode** with that character, replacing the content;
  - **F2** or **Enter** edits the current text with all of it selected (the old EditableCell's select-all, §1.4);
  - **Delete/Backspace** clears the selected cells.
- **Edit mode:** an `<input>` inside the cell, `aria-label="Price: {room} · {period}"`.
  - **Enter** commits and moves down; **Shift+Enter** commits and moves up.
  - **Tab / Shift+Tab** commit and move right / left.
  - **Escape** reverts and returns to navigation.
  - **Ctrl/Cmd+Enter** commits to **every selected cell** (bulk formula). Each cell follows its own row's rule from §3.3.2.
  - **Alt+Enter**, or the ▾ button, opens the advanced popover (§3.5).
  - On blur the entry commits if it is valid; otherwise it is kept as an error draft and never lost.
- **Reading line:** while the user types, a one-line reading appears under the cell. It is rendered from the parse result plus context, with no arithmetic. Examples:
  - "Superior in P4 = Standard × 1.20 (replaces the fixed price 245.00)"
  - "Standard P1: adjust 70.00 by +10 % (calculated on commit)"
  - "3rd adult pays × 0.70 of the base person price"
  - "HB: 100.00 per room per night (fixed)"
- **Invalid entries** show the error inline (`aria-invalid`, message via `aria-describedby`, a polite live region) and do not commit. Escape discards them.

#### 3.4.2 Normalisation (applied in this order)

1. Treat U+00A0, U+202F and U+2009 as spaces, and U+2212 (−) and U+2013 (–) as `-`. Map `×`, `x`, `X` and `*` to the multiply marker. No other Unicode folding: full-width digits and Arabic-Indic digits are a SYNTAX error.
2. Trim spaces at both ends. An input longer than 40 characters, or one containing a line break or tab, is a SYNTAX error. Paste splits lines and tabs first (§3.10).
3. Spaces are allowed **only** between a prefix (`=`, `+`, `-`, `×`) and the number, and between the number and `%`. A space inside the number (`1 000`) is a SYNTAX error.

#### 3.4.3 Grammar (EBNF, after normalisation)

```
entry     = "" | body ;                         (* "" → CLEAR *)
body      = absolute | multiply | percentOf | adjustPct | add | subtract | baseKw ;
absolute  = [ "=" , ws ] , num ;                (* a bare number must not start with a sign *)
multiply  = mul , ws , num ;                    mul = "×" ;   (* after normalisation *)
percentOf = num , ws , "%" ;
adjustPct = sign , ws , num , ws , "%" ;
add       = "+" , ws , num ;
subtract  = "-" , ws , num ;
baseKw    = "base" ;                            (* case-insensitive; board context only *)
sign      = "+" | "-" ;
ws        = { " " } ;
num       = digits , [ sep , digits ] ;         (* no leading or trailing separator *)
digits    = digit , { digit } ;   digit = "0" … "9" ;
sep       = "." | "," ;                         (* the decimal mark; at most one; grouping is never allowed *)
```

**Signature:** `parseShorthand(input, ctx, opts?: {minorUnits?: number})`. `minorUnits` is the contract currency's minor units from the server (`contract_doc.minor_units`, GAP-10), which is `money.minor_units`: KWD/BHD/OMR/JOD/TND = 3, JPY/KRW/VND = 0, default 2. When omitted it defaults to 2, the same default as `money.py`.

**Number rules** (`normaliseDecimal`: pure string handling, never `parseFloat`):
- **Canonical form:** strip leading integer zeros (keep one `0`), strip trailing fraction zeros, and drop the mark if nothing follows it. The result always uses `.` as the mark (`"007,50"` becomes `"7.5"`).
- **PLACES:** more than 9 fraction digits after stripping (`DB_PLACES`, ADR-055).
- **DIGITS:** more than 15 significant digits (`DB_SAFE_DIGITS`), counted after stripping leading integer zeros and trailing fraction zeros (e.g. `123456.789012345` has 15 and is accepted).
- **RANGE:** more than 12 integer digits (the width of a Float(21,9) column). RANGE is checked before DIGITS.
- **AMBIGUOUS** (currency-aware, owner sign-off O5):
  - It applies only to **amount ops** (room/occupancy ABSOLUTE, ADD, SUBTRACT; board ABSOLUTE and ADD; period-adjust ADD/SUBTRACT), and only when `minorUnits < 3`.
  - It refuses a number whose integer part is 1–3 digits and not zero, written with **exactly 3 fraction digits as typed** (`1.500`, `1,500`, `12.345`).
  - Message: "Is this 1500 or 1.5? Type 1500 for one thousand five hundred, or 1.5 for one and a half. Thousands separators are not used."
  - The number is not ambiguous under the grammar itself. The guard protects users who type a thousands separator from habit.
  - In 3-decimal currencies `12.345` is a normal price and is accepted. Factors and percentages are exempt: `x1.150` and `1.125%` are fine.
- **Negative zero:** a sign lives in the op, never in the value, except for ADJUST_PERCENT and board ADD, where the value keeps its sign. `-0`, `-0%` and `-0.00` normalise to the value `"0"`; the canonical output never contains `-0`.

#### 3.4.4 Op mapping per context

The owner's table (`100`/`=245` → ABSOLUTE, `x1.15`/`×1.15` → MULTIPLY, `50%` → PERCENT_OF, `±10%` → ADJUST_PERCENT, `+25` → ADD, `-25` → SUBTRACT) is applied in every context. A cell marked **(O*n*)** is forced by the DocType op list and awaits sign-off (§0.1).

| Input | `room` (period_rates) | `occupancy` (occupancy_rules) | `board` (boards) | `period_adjust` (periods.adjustment_op) |
|---|---|---|---|---|
| `100`, `=100` | ABSOLUTE 100 | ABSOLUTE 100 (fixed slot price) | ABSOLUTE 100 per room-night (O1) | OP_NOT_ALLOWED (no ABSOLUTE) |
| `x1.15`, `×1.15`, `X 1,15`, `*1.15` | MULTIPLY 1.15 | MULTIPLY 1.15 | OP_NOT_ALLOWED | MULTIPLY 1.15 |
| `50%` | PERCENT_OF 50 | PERCENT_OF 50 | ADJUST_PERCENT 50 (O3) | OP_NOT_ALLOWED |
| `+10%` | ADJUST_PERCENT 10 | ADJUST_PERCENT 10 | ADJUST_PERCENT 10 | ADJUST_PERCENT 10 |
| `-10%` | ADJUST_PERCENT -10 | ADJUST_PERCENT -10 | ADJUST_PERCENT -10 | ADJUST_PERCENT -10 |
| `+25` | ADD 25 | ADD 25 (slot = slot unit + 25) | ADD 25 per adult | ADD 25 |
| `-25` | SUBTRACT 25 | SUBTRACT 25 | ADD -25 per adult (O2) | SUBTRACT 25 |
| `base` | SYNTAX | SYNTAX | → `is_base = 1` | SYNTAX |
| `` (empty) | CLEAR (remove row) | CLEAR | CLEAR | CLEAR (no adjustment) |
| `=-5`, `x-1`, `+-5`, `--5`, `-5%%` | SYNTAX | SYNTAX | SYNTAX | SYNTAX |

On the base room row the room-context result is applied once instead of being stored (O4, §3.4.5). The parse result itself is the same.

**Allowed op sets** follow the DocType `Select` options:
- period rate: ABSOLUTE, MULTIPLY, ADJUST_PERCENT, PERCENT_OF, ADD, SUBTRACT, INHERIT;
- occupancy rule: the same plus FIXED;
- board rule: ADD, ADJUST_PERCENT, ABSOLUTE;
- period adjustment: ADJUST_PERCENT, MULTIPLY, ADD, SUBTRACT.

**INHERIT and FIXED are reachable only through the advanced popover.**

**Which table and row:** the context comes from the grid region (matrix → `period_rates`, ladder → `occupancy_rules`, boards grid → `boards`, period header "Night adjustment" → `periods`). The row identity comes from the cell (§3.3.2, §3.6.2, §3.12).

**Semantics the UI states on screen** (backend facts):
- An occupancy `+25` means the slot unit + 25, not 25. A fixed 25 is `=25`.
- A replacing op on a whole combination (`1 Adult ×1.50`) replaces the combination total.
- A room period cell replaces the default and never stacks: `SUP@P4 +10%` means Standard × 1.10.
- On a board, a bare number is per room per night; `+`/`-` amounts are per adult (children at the board's child %).

#### 3.4.5 Relative entry on the base room (adjust once)

This applies **only to the base room row** (D11, O4). A relative entry on a cell that resolves to an entered price means "change this entered price once".

1. The client calls `apply_op_values(version, values:[current], op, value)` with the op and value the parser produced.
2. While the call is pending, the cell shows "70.00 → …".
3. The cell then commits `ABSOLUTE <server result>`, rounded HALF_UP to the contract currency (as the ARI grid rate change does, `grid.py:361-365`).
4. On error the draft stays in the cell with the message.

With Ctrl/Cmd+Enter over a selection, all base-room cells are sent in one `apply_op_values` call and every other selected cell receives the formula. The whole operation is one history entry. Bulk "Adjust…" (§3.10) uses the same endpoint for entered prices in any row.

#### 3.4.6 Formatting (the inverse)

`editText(op, value, ctx, {decimalMark})` gives ASCII text with the viewer's decimal mark: `245`, `x1.15`, `50%`, `+10%`, `-10%`, `+25`, `-25`; on boards `20` (ABSOLUTE) / `+20` / `-20` (ADD) / `+5%` / `BASE`. `displayText` uses typographic `×` and `−`.

**Round trip:** `parse(editText(op, v, ctx), ctx) = (op, v)` for every op the parser can produce in `ctx`. The only documented exception is FIXED → ABSOLUTE (`=245`), which has identical arithmetic. FIXED keeps a small tag in the cell so users can tell the two apart.

### 3.5 Advanced rule popover

A non-modal `Popover`, opened with Alt+Enter, the cell's ▾ button, Shift+F10 or the context-menu key. Its accessible name is **"Edit price: {room} · {period}"** (the legacy dialog name, for helper continuity), or "Edit rule: {slot} · {period}" in the ladder. It contains:

- **Rule**: a select with the `rates.op.*` labels and `op_help` text;
- **Value**: `DecimalInput`, 9 places;
- **Derived from**: derived ops only; defaults to the default base;
- **Applies to**: this period / all periods / selected periods (a multi-select of period chips that writes one row per period);
- for occupancy only: the **Rooms** scope (all / chosen rooms, one row per room), **Always wins (override)** (`is_override`, with the help text "beats special combinations and every other rule for this guest") and **Note**;
- the reading sentence;
- **Apply**, **Remove**, **Cancel**.

The popover never re-interprets: the op chosen is the op stored. Focus returns to the cell on close.

### 3.6 Occupancy & child pricing (inside the workspace)

#### 3.6.1 Section header

- A **Rooms** scope chip: "All rooms" (rules with `room_type` blank) or one contract room (rules with that `room_type`). A dot on the chip marks scopes that have their own rules.
- **Child 1 = oldest ▾** (`child_ordering`).
- ROOM basis only: **Extra adults priced from** (per-person share / room price, `room_basis_extra_unit`) and **Children fill empty included places** (`room_basis_children_fill_included`).
- The **Child ages…** button (§3.8).
- A summary when collapsed: "Adults: 1A ×1.50 · 3rd ×0.70 | Children: Infant ×0 · 3–6.99 ×0.25 · 7–11.99 ×0.50 | 1 special combination · 1 period override".
- The section is expanded by default on a draft with no occupancy rules, and remembers its state per viewer.

#### 3.6.2 The ladder (same period columns as the matrix)

| Ladder row | Row identity in `occupancy_rules` (plus the scope's `room_type`, and `period_code` = the column, `''` for All periods) |
|---|---|
| **1 Adult (single use)** | `{target: COMBINATION, combination: "1+0", position: 0, age_band: ''}`. The single-use total, e.g. ×1.50. The popover can switch it to "also when children travel" = `{ADULT, position 1, combination "1+*"}` |
| **2 Adults · BASE** (PERSON, no rules for positions 1–2) | Read-only: "×1.00 each (default) = 2 × base person price". If a rule exists for position 1 or 2, the row splits into editable **Adult 1** / **Adult 2** rows |
| **3rd adult**, **4th adult**, … up to the largest effective `max_adults` in scope | `{ADULT, position n, combination '', age_band ''}` |
| One row per age band, showing its **label** ("Infant 0–2.99") | `{CHILD, position 0, age_band <code>, combination ''}` |
| Optional position rows ("Child 2 · 7–11.99"), added through the popover | `{CHILD, position n, age_band <code>}` |

**Engine defaults are shown, not left blank (D12).** `price_matrix` returns `occupancy_defaults` (GAP-3): `adult = {rule_id "GLOBAL:ADULT", op "MULTIPLY", value "1", source "global-default", note}`, taken from `occupancy.GLOBAL_ADULT_DEFAULT`, and `child = null` (ADR-007: there is no global child default).
- An adult position with **no** version or inherited rule shows "×1.00 default" in muted italics, with the tooltip "Engine default: every adult pays the full base person price. Type a value to set a rule." Typing into it creates a version rule. The displayed `1.00` is the server's value formatted for display; the client does no arithmetic.
- The "1 Adult (single use)" row with no rule shows "×1.00 default (no single-use rule)".
- A child band row with no rule shows "No rule · not sellable" in the `missing` style, because the engine raises `NO_CHILD_RULE`.
- ROOM basis: positions up to the effective `included_adults` show "included in the room price"; later positions show the default "×1.00 of {extra unit}".

**ROOM basis changes the rows:**
- "Adults included: 2 (per room)" (information; edited via Capacity);
- "Extra adult (3rd)" = ADULT position 3, priced from the unit chosen in the header;
- "Single use (1 adult)" = COMBINATION `1+0` (e.g. `80%`);
- child rows priced from the slot unit.

**Period cells** follow §3.3.3: `↳` when inherited from All periods, or `◆ OVERRIDE` for a period row (the owner's example: "3rd adult: All periods ×0.70, P4 ×0.80 OVERRIDE"). A rule for several periods is simply several rows, one per column; the popover's "Selected periods" and bulk selection both write them.

**Precedence is shown, not hidden.** A period cell that a special combination outranks for some party shows ⓘ "Special combinations win over period rules unless the rule is marked Always wins", with a link to the combination card. This is computed from the grouping in §3.7.4, not by re-implementing ranking.

A value from an inherited pricing policy is shown in italics with the policy source ("from Hotel policy"). Typing into it creates a version rule, which outranks the policy by origin (ADR-043). Ladder cells use the `occupancy` context, and relative entries are always stored as rules there.

**Resolved line:** "Resolved · {room} · [sample party ▾]" gives per-period occupancy totals from `price_matrix(..., parties, party_room)` (§4 GAP-2b). The sample parties are the valid combinations (§3.7.2), with children at each band's lower edge. The client never sums.

### 3.7 Special combination builder

#### 3.7.1 UI (inline panel under the ladder, no modal)

```
Adults [ 2 ▴▾ ]   Children [ 2 ▴▾ ]      quick: 1A 2A 3A 4A 1A+1C 1A+2C 2A+1C 2A+2C 2A+3C 3A+1C 3A+2C (valid ones only)
Rooms  [ All rooms ▾ ]   Periods [ All periods ▾ ]
Child 1 (oldest)   Age band [ Child 7–11.99 ▾ | Any ]   Rule [ Multiply ▾ ]   Value [ 0.50 ]
Child 2            Age band [ Child 3–6.99 ▾ | Any ]    Rule [ Multiply ▾ ]   Value [ 0.25 ]
+ Adult rule (e.g. Adult 3 in this combination)    + Whole-stay price for this combination
Reads: 2 Adults + 2 Children → Child 1 ×0.50 · Child 2 ×0.25                              [Cancel] [Save combination]
```

The value fields accept shorthand in the `occupancy` context, so the Rule select follows what is typed. "Any" children (`2+*`) and "any adults" (`*+1`) are available under "More".

#### 3.7.2 Valid combinations

The builder computes them from the **effective capacity** of the scoped rooms (from the server, §4 GAP-3), exactly like the publish sweep (`validate.py:429-461`): adults from `max(1, min_adults)` to `max_adults`, children from `0` to `max_children`, and `a + c ≤ max_occupants`. The quick chips show the union and grey out combinations that no scoped room can host, with a tooltip naming the rooms that can. Nothing is hard-coded.

#### 3.7.3 Persistence (the existing representation)

For each (room in scope) × (period in scope), where "all" means blank:
- Child i → `{target CHILD, position i, age_band <code or ''>, combination "a+c", room_type, period_code, op, value, is_override 0, note ''}`
- Adult rule → `{target ADULT, position n, combination "a+c", …}`
- Whole-stay price → `{target COMBINATION, combination "a+c", op, value}`

The combination string is `"{a}+{c}"`, with `*` for "any" (the server's `parse_combination`). Child positions follow `child_ordering`, and the builder labels them "Child 1 (oldest)".

#### 3.7.4 Grouping for display (pure, deterministic)

1. Take every row with a non-blank `combination`. Group by `(combination, room_type, period_code, is_override)` into **cells**. Each cell has a *signature*: the sorted list of `(target, position, age_band, op, value, note)`.
2. Merge cells with the same combination, override flag and signature into one **card**, which holds the set of rooms R and the set of periods P.
3. If the card's (room, period) pairs are exactly R × P, show one card. Otherwise split it by room.
4. Order cards by adults, then children, then the room order and period order of the tables.

Editing a card deletes its rows and inserts the rebuilt ones in a single history entry. Rows the builder cannot express, such as a combination with a note, are still shown and are edited in the popover.

**Display:** "2 Adults + 2 Children → Child 1 ×0.50 · Child 2 ×0.25" (i18n with plurals), with band labels, room scope and period scope as secondary text. `◆` marks cards scoped to periods.

**Limit, stated in the help text:** each child's band condition is independent (`occupancy.py:113-124`). "Child 1 is 7–11.99" applies whatever child 2's age is; joint conditions cannot be expressed.

### 3.8 Child age bands drawer

The drawer opens from "Child ages…" in the occupancy header, or from `#ages`. Its width is `md`. It contains:

- **Bands:** a compact list, one line per band: **Label**, From (years, 2 places), Up to (not incl.), an **Infant** switch, and delete.
  - "Add band" fills From from the previous Up to (2.99 → 3, the existing rule) and focuses Up to. Enter adds the next band.
  - The first band starting at 0 with Up to ≤ 3 gets Infant on by default. The switch stays visible and can be turned off.
  - **Labels are saved, not only displayed.** When a band is created, and whenever a band is committed with a blank label, the drawer writes the generated label into `age_bands.label`: `rates.bands.label_infant` "Infant {from}–{to}" or `rates.bands.label_child` "Child {from}–{to}", in the editor's language at that moment. After that it is ordinary data the user can edit. Existing bands with a blank label are not changed silently: the drawer shows a notice "2 bands have no name" with **Name them** (one history entry).
  - **Band codes are hidden.** A new band gets the next free code from `INF, CHA, CHB, …`, stable across edits. An "Advanced" disclosure shows and edits the code; renaming a code rewrites `occupancy_rules.age_band` references.
  - An `AgeStrip` shows coverage in months (the existing `yearsToMonths` display helper). Gaps and overlaps are marked; the server check `AGE_BANDS` stays the authority.
- **Inherited bands:** when the version has no bands of its own, the drawer shows the **inherited** policy bands (from the server, GAP-3) read-only, with "Customise for this contract". That copies them with the same codes and labels, so inherited rules keep matching. A label equal to its code (the server's fallback in `age_bands_of`) is replaced by the generated label.
- **Child rules:** `age_basis` (arrival / booking date), `children_over_max_as_adults`, `infants_count_as_occupants`.

**Band labels everywhere (D13).**
- The pure helper `bandLabel(band)` returns the label, or the generated label when the label is blank or equal to the code.
- The pure helper `displayBandCodes(text, bands, {codes?})` replaces band codes in server text:
  - **always:** `[CODE]` → `[Label]` for each known band. This covers occupancy rule labels such as `Child 1 [CHB] @2A+2C × 0.5` and sweep messages such as `STD 2A+2C [CHB]: …`;
  - **when `codes` is given** (from `ref.age_band` / `ref.age_bands` on issues, or all band codes for a `NO_CHILD_RULE` reason): every whole-token occurrence of those codes (`(?<![A-Za-z0-9_])CODE(?![A-Za-z0-9_])`). Example: "age bands CHA and CHB overlap" → "age bands Child 3–6.99 and Child 7–11.99 overlap".
- Unknown codes (e.g. from `OCC_UNKNOWN_BAND`) have no label and stay as they are.
- The helper is used in the ladder, the builder, issue lists, the price-test ladder, the "Why this price" list and unsellable reasons, in all six languages.

### 3.9 Period management in columns

- **Header cell:** a code chip (P1), the name, a compact date range (`01–30 Apr`), a weekday badge if the period is weekday-limited, a `◆` badge if it has a night adjustment, and a **⋯ Menu**.
- **+ Period:** adds a column in inline edit, with code `P{n+1}` (the next free code), start = last end + 1 day, and end = start + the previous period's length − 1. The typed end date commits.
- **Menu actions:**
  - **Rename…**: changes code and name; the code must be unique. A rename rewrites `period_code` in `period_rates`, `occupancy_rules` and `boards` (pure `renamePeriod`) as one history entry.
  - **Dates…**: from/to, weekdays, priority (advanced).
  - **Night adjustment…**: `period_adjust` shorthand. The popover states that the adjustment is applied to occupancy + board, after the board supplement (`engine.py:458-465`), and the price test shows it in that position (§3.13).
  - **Duplicate**: a new code, dates right after the source with the same length, and copies of the source's period-scoped rows in all three tables.
  - **Copy previous period's prices**: replaces this column's period rows in the three tables with copies of the left neighbour's.
  - **Move left / right**: changes table order only. Column order has **no pricing effect** (`rooms.period_for`), so reordering is always safe; the menu says so.
  - **Delete…**: confirms inline with the dependent row counts, then removes them.
- **Bulk apply:** clicking a column header selects that column's editable cells in the matrix; Shift or Ctrl selects several columns. Typing then applies to all of them (Ctrl/Cmd+Enter).
- **Timeline:** a thin `PeriodStrip` above the header shows gaps and overlaps against the stay window.
- **Overlap guard:** overlapping periods are allowed when they can be resolved (weekday, then priority, then the shorter range, then the code). They are flagged by the existing `PERIOD_OVERLAP` check.

### 3.10 Bulk productivity

The keyboard grid is a new shared hook, `useGridNavigation` + `useGridSelection` (in `frontend/src/tex/ui/grid*.ts`). It is modelled on AriGrid's roving tabindex (the old RateGrid has no keyboard grid, §1.4), but AriGrid itself is **not** refactored in this project. The selection reducer is pure and unit-tested.

| Gesture | Action |
|---|---|
| Arrows / Home / End / Ctrl+Home/End / PageUp/PageDown | Move the active cell (roving tabindex, one tab stop per grid) |
| Shift+Arrow, Shift+Click | Extend the rectangular range from the anchor |
| Ctrl/Cmd+Click | Add a separate cell or range |
| Click on a row or column header | Select that row's or column's editable cells |
| Ctrl/Cmd+A | Select every editable cell of the grid |
| Type / F2 / Enter | Edit (§3.4.1) |
| Ctrl/Cmd+Enter in edit mode | **Bulk formula:** apply the parsed entry to every selected editable cell, each following its row's rule (§3.3.2) |
| Delete / Backspace | Clear the selected cells (CLEAR semantics) |
| Ctrl+R / toolbar "Fill →" | **Fill right:** each row's leftmost selected cell is copied to the rest of the selection (**copy across periods**) |
| Ctrl+D / toolbar "Fill ↓" | **Fill down / copy down rooms:** the top row is copied down. Allowed between rows of the same kind (formula ↔ formula, price ↔ price). Copying a price into a formula row is offered as a "fixed price override" with an inline confirmation line |
| Ctrl/Cmd+C | Copy TSV of the canonical `editText` (resolved rows copy the exact server amounts) |
| Ctrl/Cmd+V | Paste TSV (see below) |
| Toolbar "Adjust…" | A popover with an op (+ %, − %, + amount, − amount, ×) and a value; the value field has focus on open. It applies to the selected **entered prices** (`manual`/`fixed-override` in any row) through `apply_op_values`. A preview list is refreshed per keystroke (debounced): the first 8 "70.00 → 77.00" lines, then "+N more", listing only cells that change. Formula cells are skipped and counted ("3 formula cells skipped"). The confirm button is disabled while pending or when nothing changes (adopted from the old BulkEditDialog, §1.4) |
| Ctrl/Cmd+Z, Ctrl+Shift+Z / Ctrl+Y | Undo / redo |
| Escape (navigation) | Clear the selection |

**Paste rules** (deterministic, all or nothing):
- A single value fills every selected cell.
- A block is anchored at the active cell and must fit inside the editable region. Otherwise it is refused with "The pasted block is 3×4 but only 3×2 editable cells are available here".
- Each cell is parsed in its context, with the contract currency's minor units. If any cell fails, nothing is applied and a toast names up to three failures ("P3 · Superior: 'abc' is not a price or formula").
- Resolved rows are never paste targets.

**Undo history:** the pure module `workspace/history.ts` implements a client-side linear command log. The React binding `useWorkspaceHistory` is created in S9 together with the first mutations; S10 adds the undo/redo UI.
- **Every** workspace mutation goes through `commit(label, patch)`, where `patch` holds the *before* and *after* arrays of the affected tables only. Drawers and popovers use it too. (The pricing basis is not part of the version and is not in the history; it has its own Apply, §3.2.1.)
- The log keeps at most 100 entries and is cleared by Discard and by loading another version. It survives Save: undoing after a save makes the state dirty again.
- Bulk operations show a toast "Applied to 8 cells · Undo", visible for 10 seconds (the old RateGrid's undo toast, §1.4) and announced in a polite live region.
- Undo restores recorded rows and never computes an inverse. Restoring "no rule" removes the row; it never writes 0.
- Undo does not call the server.

### 3.11 PERSON vs ROOM basis

| Element | PERSON | ROOM |
|---|---|---|
| Matrix unit badge | "per person per night" | "per room per night" |
| Base row label | "Base person price" | "Base room price · N adults included" (N editable per room) |
| Derived resolved row | "Resolved (per person)" | "Resolved (room, N adults)" |
| Header "Base occupancy" | "Per person" | Included adults of the base room |
| Occupancy ladder | 1 Adult (single use), 2 Adults BASE (×1.00 each, default), 3rd adult …, bands | Adults included (per room), Extra adult (3rd …), Single use, bands; "Extra adults priced from" select; "Children fill empty places" switch |
| Reading sentences | "… of the base person price" | "… of the per-person share (room ÷ N)" or "… of the room price" |
| Price test, Occupancy (adults) stage | before = person unit, after = all adults | before = room price, after = room price + extra adults (the `ROOM_BASIS` line says how many adults the room price covers) |

The basis switch in the header (§3.2.1) changes all of these immediately after Apply.

### 3.12 Boards in the workspace

A collapsible "Boards" section below occupancy. Collapsed, it shows a chip summary: "UAI BASE · AI −5 % · HB −20.00 per adult". Expanded, it shows a compact grid:

- **Rows:** one per board (in `boards` order), plus indented rows for room-scoped rules ("HB · Deluxe only").
- **Columns:** All periods plus the period columns (the shared template).
- **Cells** use the `board` shorthand context (§3.4.4): a bare `20` = ABSOLUTE 20 per room-night (O1), `+20` = ADD per adult, `-20` = ADD −20 per adult (O2), `±5%` / `5%` = ADJUST_PERCENT (O3). The reading line always names the unit ("per room per night" / "per adult per night; children 50 %"). `BASE` sets `is_base` exclusively. The radio behaviour is UI-only; `NO_BASE_BOARD` stays the server check.
- **Row popover:** child % (`child_percent`, default 50), infants free, label, room scope.
- **Add board:** a select of RO/BB/HB/FB/AI/UAI. The first board is base.
- **Context:** selecting a matrix cell highlights the matching period column in Boards. Hovering or focusing a board cell shows "applies to {room scope} in {period}".

The board grid stays about 10 rows high whatever the number of rooms, because room-specific rules exist only where they were entered.

### 3.13 Price Test / Explain drawer

The existing Preview calculator is **extracted** into `PriceTestPanel` and reused in two places: in the right-side **Drawer** (`lg`, non-modal on desktop) and full-size in "Preview & audit". Nothing is deleted.

**Inputs:**
- stay dates (check-in/out) and sale date (`sale_at`);
- room, board and rate plan;
- adults;
- children: an age in years (0–17), with an optional "exact" toggle for **months** or **date of birth** (§4 GAP-6);
- market, channel, currency and promo codes.

**Prefill from context:** room = the active matrix row's room; dates = the active period's start (clamped to the stay window) for 3 nights; board = the base board. Pressing **Calculate** (or Enter) prices the stay. After the first calculation, a "live" toggle re-prices on every settled edit (debounced).

**Unsaved state:** requests send `data` when the viewer can edit (§4 GAP-1), and the notice becomes "Priced with your unsaved changes" (info). **No save is needed.**

**Output:**
- **FINAL PRICE**: total, plus cost and margin for users with cost access.
- The **Explain ladder** (D14), described below.
- The full "Why this price" list and the "Show in grid" links, described after the ladder.

#### 3.13.1 The Explain ladder: engine order, true before → after chain

The ladder lists stages **in the order the engine computes them**: per night in `engine.py:452-476`, then at stay level. It covers all of the owner's stages (Base, Period, Room, Occupancy, Child, Board, Markup, FX, Promotion, Tax) plus the stages the engine really has in between. **Every value shown is a server field.** Explanation `before`/`after` values, `nights[]` fields and `totals` are displayed as served (6 dp strings, formatted to currency precision for display). The client never adds, subtracts or multiplies.

| # | Stage | Scope | before → after (server fields) | Explanation steps shown as detail lines |
|---|---|---|---|---|
| 1 | **Base** | night | after = the `after` of the night's first `ROOM_ABSOLUTE` step: the root of the derivation chain (Standard 80.00 for Deluxe in P2) | `ROOM_ABSOLUTE` |
| 2 | **Period** | night | **Identification only, no amount:** "P2 · May (01–31 May)" from the `PERIOD` step params. The engine uses the period to choose rules; any amount effect is shown at stage 9 | `PERIOD` |
| 3 | **Room** | night | Each `ROOM_DERIVED` step before → after, in chain order (80.00 → 108.00). A room priced by its own entered price shows "entered price, no derivation". The last after equals `nights[].unit` | `ROOM_DERIVED` (with its `overridden` rules) |
| 4 | **Occupancy (adults)** | night | before = `nights[].unit`, after = `nights[].subtotal_adults` (GAP-12). ROOM basis: the `ROOM_BASIS` line says the room price covers N adults, and after = room price + extra adult slots | `ROOM_BASIS`, `ADULT_SLOT` (one line per adult with its amount) |
| 5 | **Child** | night | before = `nights[].subtotal_adults`, after = `nights[].subtotal_children` (GAP-12). Shown only when children travel | `CHILD_SLOT` (one line per child with its amount, e.g. 54.00), `CHILD_INCLUDED`, `CHILD_AS_ADULT` |
| 6 | **Special combination** | night | Only when a combination rule won: `COMBINATION_RULE` before → after (its before equals `subtotal_children`, and its after equals `nights[].occupancy`) | `COMBINATION_RULE` |
| — | *Occupancy total* | night | The closing line of 4–6: `nights[].occupancy` (`OCCUPANCY_TOTAL` or the combination after) | `OCCUPANCY_TOTAL` |
| 7 | **Board** | night | before = `nights[].occupancy`, after = `nights[].subtotal_board` (GAP-12). Supplement = `nights[].board`; a base board shows "included" and before = after | `BOARD_BASE` / `BOARD_SUPPLEMENT` |
| 8 | **Period adjustment** | night | Only when the period has one: `PERIOD_ADJUSTMENT` before → after (its before equals `subtotal_board`). The label says "Period P2 adjustment (applied to occupancy + board)" | `PERIOD_ADJUSTMENT` |
| 9 | **Rate plan** | night | Only when applied: `RATE_PLAN_ADJUSTMENT` before → after | `RATE_PLAN_ADJUSTMENT` |
| 10 | **Night cost** | night | after = `nights[].cost` (the contract cost of the night) | `NIGHT_COST` |
| 11 | **Cost offers** | night + stay | Only when any applied: `nights[].cost` → `nights[].cost_net`; stay-level `PROMO_APPLIED` (stage `cost_offer`) before → after | `PROMO_APPLIED` / `PROMO_REJECTED` (cost_offer) |
| 12 | **Markup** | night | `MARKUP` / `MARKUP_STACK` before → after (= `nights[].cost_net` → `nights[].sell_contract`); `NO_MARKUP` shows before = after | `MARKUP*`, `NO_MARKUP` |
| 13 | **FX** | night | `nights[].sell_contract` → `nights[].sell`, with the rate from `fx` | FX steps |
| 14 | **Promotion** | night + stay | `nights[].sell` → `nights[].final`; stay-level `PROMO_APPLIED` / `COUPON_APPLIED` before → after; rejected promotions with their reason | `PROMO_*`, `COUPON_APPLIED` |
| 15 | **Tax** | stay | before = `totals.subtotal`, after = `totals.total`; the tax amount is `totals.tax`. When prices include tax, before = after and the tax is shown as "included" | `TAX` |
| — | **FINAL PRICE** | stay | `totals.total` | `TOTAL` |

**Why the Period stage carries no amount.** The engine applies the period adjustment to occupancy + board (`amount = occ.total + brd`, then `adjustment_op`, `engine.py:458-465`), not to the base price. Showing it second would break the before → after chain. The ladder therefore shows the period's **identity** at stage 2, in the owner's reading order, and its **amount effect** at stage 8, where the engine applies it. A small caption under the ladder states the order: "Stages are shown in the order the engine applies them."

**Chain check (explainability guard).** The pure mapper `explainLadder()` also returns `chainBreaks`: the stages whose *before* differs from the previous stage's *after*. The check covers the per-night stages 1 and 3–14 (stage 2 has no amount) and the stay-level stages separately. The values are compared as **canonical decimal strings** (`normaliseDecimal` from S1, trailing zeros stripped), which is string handling, not arithmetic. With the GAP-12 fields the chain is complete by construction. A break is logged in dev builds and fails the unit test on the recorded fixtures. It is never "fixed" by computing on the client.

**Missing data.** A quote without the GAP-12 fields (for example a stored snapshot from before this change) shows stages 4, 5 and 7 with only the detail lines and a blank before/after. Nothing is calculated to fill the gap.

**Night selector:** it **defaults to "All nights"**. Nights whose stage values are string-identical are collapsed into one group ("Nights 1–3 · P2"). Otherwise each night gets its own block. The stay-level stages 11 (stay part) and 14–15 follow the night blocks.

#### 3.13.2 "Why this price", Show in grid, localisation

- The full "Why this price" list below the ladder keeps its DOM ("Rule applied:", level badge, label, overridden). **Rule labels and reasons pass through `displayBandCodes`** (§3.8) in every language, so `Child [CHD] 50% of` renders as `Child [Child] 50% of` when the band is labelled "Child". The existing E2E assertions that name band codes (`contract-admin.spec.ts:109-110`) are updated to the labels in the same slice (S14).
- **Show in grid** on a step jumps to the matrix, ladder, combination card or board cell whose row has that `rule_id`. In overlay mode, rule ids are `~<_key>` (§4 GAP-1); saved rows carry `_name`.
- Explanation sentences are localised from `code` + `params` where a `rates.explain.<CODE>` template exists (§3.20), with room ids mapped to room names and band codes to labels. Otherwise the server's `text` is shown after `displayBandCodes`; for English this is the only change to the server text. Stage labels are localised (`rates.pt.stage.*`).

The drawer and panel are shown only when `doc.can_preview` is true (§4 GAP-10). Otherwise the button is hidden and the panel shows the existing `needs_cost` notice.

### 3.14 Live server feedback and money exactness

`useDraftPreview(doc, state)` picks **one of three modes** from server flags, so no viewer ever calls an endpoint the server would refuse:

| Mode | When | Matrix / parties | Validation |
|---|---|---|---|
| `overlay` | `doc.editable` (Draft and `contract.edit`) | POST `price_matrix` with `data = overlayPayloadOf(state)`, debounced 300 ms | POST `validate_version` with `data`, debounced 1200 ms |
| `saved` | Not editable and `!doc.cost_hidden` (the viewer has `price.view_cost` or `contract.edit`, which is exactly what `price_matrix` requires, `api/contracts.py:127-130,296-297`) | GET `price_matrix` without `data`, once per `doc.modified` | **Never calls `validate_version`** (it requires `contract.edit`, `contracts.py:426`). Shows `doc.validation_report` when present (stored at publish), labelled "Checked when published"; otherwise the live-check chip is hidden |
| `catalogue` | `doc.cost_hidden` (agents with `price.view` only) | **No calls.** The workspace renders the catalogue (rooms, boards, rate plans; "Amounts are not shown to your role") | None |

- In `overlay` mode, results are tagged with the fingerprint they were computed for, stale requests are aborted, and results for an older fingerprint are shown in the `stale` style until the new ones arrive.
- The Price test uses `preview_price` only when `doc.can_preview`.
- **Money-exactness statement:** the client never performs arithmetic on money or rule values.
  - (a) Resolved prices, occupancy totals, validation and quotes come from the server (`price_matrix`, `validate_version`, `preview_price`).
  - (b) **Price-test subtotals** come from the server: `nights[].unit`, `subtotal_adults`, `subtotal_children`, `occupancy`, `subtotal_board`, `cost`, `cost_net`, `sell_contract`, `sell`, `final`, the explanation `before`/`after` values and `totals` (GAP-12). The client never adds slot amounts or board supplements.
  - (c) Adjustments of entered base prices and bulk adjustments come from `apply_op_values` (server `Decimal` via `ops.apply_op` + `money.quantize`).
  - (d) The parser only validates and canonicalises decimal **strings**. The ladder's chain check compares canonical strings.
  - (e) Display uses the existing format helpers on server decimal strings. Values above 15 significant digits are shown as the raw string. Engine defaults (×1.00) are server values formatted for display.
  - (f) The only numbers the client computes are integers: capacity loops, counts, positions and date offsets.

### 3.15 Validation display

- **Live check:** in `overlay` mode, the overlay's `validate_version(name, data)` runs while editing. The header chip shows its counts and opens a popover with the grouped `IssueList`.
- The **Validate** button still validates the *saved* draft (editors only), and **Publish** still requires a clean state (unchanged).
- **Anchoring:** an issue with a `ref` (§4 GAP-4) marks its cell:
  - `ref.room_type`/`ref.period` point to a matrix cell;
  - `ref.rule_id` points to the row with that `_key` or `_name`;
  - `ref.age_band` points to a ladder row;
  - `ref.adults/children` point to a combination card;
  - a board ref points to the board grid.

  The cell gets the `error` state and the message through `aria-describedby`. Clicking an issue in the popover focuses its cell.
- **Unanchored issues** (header, selling) stay in the list.
- **Every issue message passes through `displayBandCodes`** with `codes = ref.age_band / ref.age_bands` (and the bracket rule for sweep messages), so no band code is shown where a label exists.
- Issues go stale on edit; the live check refreshes them, and the chip shows the `stale` style meanwhile.

### 3.16 Save, discard and concurrency (preserved)

- These are **unchanged**: `EditorState`, `stateFromDoc`, `payloadOf`, `fingerprint`, `onSave` (one save at a time, whole payload), `settle()` with `overSaved` per table, per setting and for selling, Discard = `load(doc)`, Ctrl/Cmd+S and `beforeunload`. The in-flight-save E2E test must stay green.
- **New: stable row keys.**
  - `settle()` calls `keepKeys(saved, sent)`: for each table whose saved length equals the sent length, `saved[i]._key = sent[i]._key`. This is safe because the server keeps order (`v.set(table, rows)` in posted order).
  - `toRow` keeps the server `name` as `_name`, which `fromRow` and the fingerprint ignore.
  - Selection, focus, the open offer accordion and issue anchoring therefore survive a save.
- Discard also clears the undo history and the live results.
- The basis popover saves the **contract header**, not the version. It does not touch `EditorState`, `dirty` or the fingerprint, so it cannot interfere with `settle()`.
- Two users editing one draft is still last-writer-wins, because `save_version` has no version token. This is out of scope and documented in §6.

### 3.17 Security

- Every edit affordance depends on `doc.editable`, which the server computes (Draft and `contract.edit` on the version's hotel). Published versions render the workspace **read-only**: no inputs, no "Edit price:" triggers, no menus that mutate, and the grid has `aria-readonly="true"`. Read-only cells state their reason in a tooltip.
- The basis popover depends on `doc.can_edit_contract` and `!doc.basis_locked`. `save_contract` re-checks `contract.edit`, and the controller refuses a basis change after publish.
- The price test depends on `doc.can_preview` (price.view_cost on the version's hotel, from the server). This also fixes `PreviewTab`'s gating on the shell-selected hotel.
- A catalogue response (`cost_hidden`) renders a "no amounts" view without errors and without calling cost endpoints (§3.14).
- All writes still go through `save_version` (drafts only), `save_contract` (header), `new_draft` and `publish_version`.
- Every new or extended endpoint keeps `scope.property_of` + `scope.require`. Using the overlay additionally requires `contract.edit` and Draft status. The overlay never saves; an integration test asserts that nothing is written or audited.
- The GAP-12 subtotal fields are internal quote data. The guest projection (`to_dict(internal=False)`) and `quoting.strip_internal` reduce `nights[]` to date and amount, so users without cost access never see them.
- Row caps protect the overlay (5,000 rows) and `apply_op_values` (500 values).
- Nothing in the UI is authoritative. The server re-checks everything.

### 3.18 Visual direction (original TEX identity)

- **Density:** 28 px data rows, 13 px `tabular-nums`, 12 px secondary text, 1 px zinc-200 hairlines, 2 px separators between room blocks, 8 px section gaps, no card-in-card layouts. The matrix sits on the page surface, not in a floating card.
- **Identity:**
  - a thin TEX accent bar on the base row, and the ★ glyph;
  - period columns tinted by position in the stay (alternating zinc-25/white);
  - override amber (`◆`, corner triangle) and a pin for fixed overrides;
  - derived rows in slate ink, resolved rows on zinc-50, engine defaults in muted italics;
  - a dotted top border on weekday-limited periods;
  - in the price-test ladder, a two-column before → after layout with a hairline between stages, and a thin vertical connector showing the chain.
- **Controls:** `sm` buttons, icon buttons with titles, native selects in popovers only, and popovers instead of modals for all routine edits (including the pricing basis).
- Sticky header, sticky period headers and a sticky first column. No excessive whitespace: the owner example (4 periods × 3 rooms) fits one 1440×900 screen together with the occupancy ladder.

### 3.19 Accessibility

- **Grid semantics:** `role="grid"`, `rowheader`, `columnheader`, `aria-selected`, `aria-readonly` on resolved rows, one tab stop per grid, `focus-visible` rings.
- **Cell labels:** every cell has a full `aria-label`, e.g. "Superior · P4 (01–31 Jul): period override, × 1.20 of Standard; resolved EUR 156.00". A default cell reads "4th adult · all periods: engine default, × 1.00".
- **States:** every state has a glyph or text as well as colour, and works in `forced-colors`.
- **Errors:** via `aria-invalid` + `aria-describedby`. Bulk results and undo are announced in a polite live region.
- **Popover:** `role="dialog"`, non-modal, labelled; Esc closes it and focus returns. **Menu:** `role="menu"` with roving items. **Tooltip:** a focusable trigger with `aria-describedby`, not hover-only; it replaces `title` attributes in new code.
- **Price-test ladder:** a `table` with row headers per stage and "before" / "after" column headers. A stage without an amount says "no amount (period used to choose rules)".
- A "Keyboard shortcuts" popover lists every key.
- **Touch:** tap selects, double-tap edits, a long press opens the popover.
- `prefers-reduced-motion` disables transitions.

### 3.20 i18n (six languages)

- Every new string goes through `t()`, with keys in `frontend/src/tex/i18n/locales/rates/{en,tr,de,ru,ro,pl}.json`, identical `{placeholders}`, and plural objects (`one/few/many/other`) wherever a count appears.
- **Namespaces:**
  - `rates.section.*` (the 4 sections);
  - `rates.ws.*` (header, basis popover, matrix, periods, rooms, toolbar, states);
  - `rates.sh.*` (parser errors and reading sentences);
  - `rates.occ.ladder.*` (including defaults);
  - `rates.combo.*`, `rates.bands.*`, `rates.boards.*`;
  - `rates.pt.*` (the price test, ladder stage names and the order caption);
  - `rates.kbd.*`;
  - optionally `rates.explain.<CODE>`.
- **Ordinals** ("3rd adult") use a small `tOrdinal` helper (`Intl.PluralRules({type:"ordinal"})`, falling back to `other`).
- Existing `rates.tab.*` keys are **kept**, because the policy editor uses `rates.tab.ages` and `rates.tab.occupancy`.
- The i18n check script gains a literal-key scan: keys used as `t("…")` string literals in `src/tex` must exist in `en.json`.

### 3.21 Responsive

- Below 768 px the matrix scrolls horizontally inside its own container, with the sticky first column. The page itself never scrolls horizontally, and the header collapses to "Details".
- On phones, single-cell editing is supported (tap, type, Enter). Bulk tools are hidden below 768 px.
- The read-only view is covered by a mobile E2E spec.

---

## 4. Backend gaps and minimal changes

The pricing semantics, ops, precedence and payload stay the same. Every change is additive and read-only, or a stricter input check.

| Gap | Evidence | Minimal change | Semantics risk |
|---|---|---|---|
| **GAP-1** No live matrix, validation or quote for unsaved edits | `price_matrix`, `validate_version` and `preview_price` read the saved draft (`api/contracts.py:263-313`; `contracts.py:424-432`). Saves are on demand and audited (`api/contracts.py:208-210`) | `_overlay(name, data)` in `api/contracts.py` applies the payload in memory with the **same** cleaning as `save_version` (shared `_clean_rows`, `_set_selling`, settings). It assigns `child.name = "~" + _key` (or `"~{table}-{i}"`) so rule ids map back to rows. It runs `_require_values`, `decimals.check_inputs(v)` and Frappe's side-effect-free child checks (`_validate_selects`), caps the row count, and **never saves**. `price_matrix`, `validate_version` (split into `svc.validate_doc(version)`) and `preview_price` get an optional `data` argument; with `data`, `contract.edit` and Draft status are also required | None to pricing. The overlay must not write: a test asserts that `modified`, the audit count and child rows are unchanged |
| **GAP-2** `price_matrix` has no provenance, and `adults` is dead | `api/contracts.py:291-313` | Pure `kamra/tex/pricing/matrix.py: unit_source(terms, rt, period)` runs `rooms.room_unit` with an `Explanation` and returns `{rule_id, scope: PERIOD\|ALL, op, value, base_room_type, chain, overridden}`. `price_matrix` adds `rooms[].sources{period: …}`. `adults` stays accepted and is documented as unused | None (additive keys) |
| **GAP-2b** No resolved occupancy totals for the ladder | Only the price check prices a party | Optional `parties=[{adults, children:[band_code]}]` (≤ 12) + `party_room` on `price_matrix`. `matrix.party_total()` builds the same representative `Party` as the publish sweep (children at each band's lower edge) and calls `occupancy.price_occupancy`. It returns `party_cells[i]{cells{period: total}, slots{period:[…]}, errors{period: msg}}` | None (read-only) |
| **GAP-3** Inherited bands and rules, engine defaults and effective capacity are invisible | `get_version` returns only the version's own rows (`api/contracts.py:158`). Policies are merged in `build_terms` (`contracts.py:358-364`). The adult default is a module constant (`occupancy.py:48-50`), applied at `occupancy.py:215-216`. There is no child default (`occupancy.py:245-249`, ADR-007) | Extra `price_matrix` keys from the built terms: `age_bands[{code, label, from_months, to_months, is_infant, source}]` (label as in terms, which equals the code when blank, `contracts.py:123`), `inherited_rules[…with source]` (non-version origin only), `rooms[].capacity{max_adults, max_children, max_occupants, min_adults, included_adults}`, and **`occupancy_defaults: {adult: {rule_id, target, op, value, source, note}` from `occupancy.GLOBAL_ADULT_DEFAULT`, `child: null}`**. Same gate (`_sees_cost`) | None (reads the engine's own constant) |
| **GAP-4** Issues cannot be anchored, and they print band codes | `validate.py:36-43`; `ages.py:84-94`; `validate.py:457-458`; `occupancy.py:82-96` | `Issue.ref: dict \| None = None`; `to_dict` adds `"ref"` only when set. Populated for ROOM_RULE_*, room_unit errors, PERIOD_*, AGE_BANDS (`age_bands`: every band code, so the client can replace them), OCC_*, BOARD_* and sweep issues (`room_type, period, rule_id, age_band, adults, children, board`). Messages unchanged; the client replaces codes with labels (§3.8) | Low: tests comparing whole `Issue` objects must be checked (none were found comparing `to_dict`) |
| **GAP-5** Board rules are barely validated; ties are resolved by the random row name | `boards.py:24-30`; `validate.py:170-177` | New validation ERRORs `BOARD_UNKNOWN_ROOM`, `BOARD_UNKNOWN_PERIOD` and `BOARD_DUPLICATE` (same board, room and period), mirroring the ROOM_RULE_* checks. The engine is unchanged; `issueTab` maps `BOARD_` to pricing (S8) | Validation only: drafts with such rows cannot be published (they were silently mispriced) |
| **GAP-6** Preview children are whole years only; `'7.5'` raises and `7.5` is truncated | `api/contracts.py:277`; `model.py:395-401` | Each child is an int or a digit string (years 0–17), an integral float, `{age_months: 0..215}` or `{dob: 'YYYY-MM-DD'}` (checked with `ages.check_child_dob` against check-in and the site's today). Anything else → `frappe.throw` with a clear message. At most 12 children | None: ints behave exactly as before |
| **GAP-7** No server path for relative or bulk changes on entered prices | `grid.apply_rate_change` splits periods (`grid.py:303-374`); the frontend has no decimal arithmetic | `POST contracts.apply_op_values(version, values, op, value)`: `contract.edit`, Draft only, op ∈ {ABSOLUTE, MULTIPLY, PERCENT_OF, ADJUST_PERCENT, ADD, SUBTRACT}. Each result = `money.quantize(ops.apply_op(op, v, reference=cur, current=cur), currency)` via pure `matrix.adjust_amount`. Per-item errors `NO_VALUE`/`NEGATIVE`; ≤ 500 values; no writes | None (a pure computation mirroring `grid.py:361-365`) |
| **GAP-8** A blank value is silently saved as 0 | Frappe `flt` (`base_document.py:552-553`); `money.db_dec(None)=0`; `validate.py:147-148` unreachable | `_require_values(v)` in `save_version` and the overlay refuses `period_rates`/`occupancy_rules` rows whose op is not INHERIT and whose value is blank, and non-base `boards` rows with a blank `adult_amount`. Row-numbered message via `_()`. The UI deletes a row on clear instead | Stricter input only; rows stored as 0 load as "0" and are unaffected |
| **GAP-10** No preview/publish/header capability flags or currency minor units on the version | `api/contracts.py:151-170,271`; `PreviewTab.tsx:44`; basis lock predicate `tex_contract.py:62-86` (`is_published`); `money.minor_units` (`money.py:17-23,77`) | `get_version` adds `can_preview` (price.view_cost on the hotel), `can_publish` (contract.publish), `can_edit_contract` (contract.edit on the hotel, whatever the version status), `basis_locked` (`svc.is_published(contract)`) and `contract_doc.minor_units` (`money.minor_units(contract_currency)`). The catalogue returns `can_preview/can_publish/can_edit_contract: false` | None |
| **GAP-12** The quote has no server subtotal after the adults, after the children, or after occupancy + board, so the Explain ladder cannot show Occupancy, Child and Board as before → after without client arithmetic | `nights[]` = date, period, unit, occupancy (`occ.total`, children and any combination included), board (the supplement), cost, cost_net, sell_contract, sell, final (`engine.py:45-62,606-609`). `ADULT_SLOT`/`CHILD_SLOT` carry only slot amounts (`occupancy.py:212-252`); `OCCUPANCY_TOTAL` carries only the total (`occupancy.py:277-279`). The board step carries only the supplement (`boards.py:60-62`). The period adjustment starts from `occ.total + brd` (`engine.py:458-465`) | (1) `OccupancyResult` gains keyword fields `after_adults` and `after_children` (default `ZERO`). They hold running totals `price_occupancy` already has: `base_total + Σ adult slots`, and the pre-combination `total` (`occupancy.py:254`). (2) `NightPrice` gains keyword fields `subtotal_adults`, `subtotal_children` and `subtotal_board` (default `ZERO`). The engine fills them from `occ.after_adults`, `occ.after_children` and `occ.total + brd` (the value it already holds as `amount` before the period adjustment) through the existing `partial` tuple. (3) `NightPrice.to_dict` adds the three keys with `to_str6`. The internal quote dict only carries them; the guest view and `strip_internal` project `nights[]` to date/amount, so they never reach guests or agents. No explanation step, price, total or `engine_version` changes | None to prices: the same Decimal values, reported. Additive internal keys; old stored quotes lack them, and the ladder then leaves those before/after cells blank |
| GAP-9 (deferred) Per-band board child % | Present in the payload (`model.py:164`), missing from the DocType | Not in this project | — |
| GAP-11 (deferred) The base room is not a server concept | `is_base` is UI-only (`model.py:100-108`) | The UI enforces exclusivity; no engine change | — |

The pricing-basis change needs **no backend change**: `save_contract` already accepts a partial `data` with only `pricing_basis`, and the controller enforces the lock. An integration test pins that behaviour (S2).

**ADR-061** records GAP-1's overlay (read-only, same cleaning, `~key` rule ids, no autosave), GAP-12 (reported subtotals, internal only), D1–D14 and the sign-off items O1–O5.

---

## 5. Test plan

### 5.1 Pure frontend unit tests (no new dependencies)

- **Runner:** `node --test` (Node 22.18+/24, native type stripping). The script `"test:unit": "node --test --disable-warning=ExperimentalWarning \"tests/unit/**/*.test.ts\""` runs in the CI frontend job after `npm run build`.
- Tests live in `frontend/tests/unit/`, outside `tsconfig` `include`, so `tsc -b` needs no `@types/node`. They import modules with explicit `.ts` extensions.
- Modules under test have **no runtime imports** (only `import type`, or each other with `.ts` extensions) and use erasable syntax only.

Test files:
- **`shorthand.test.ts`** (table-driven):
  - every owner example; `×`, `x`, `X`, `*`; spaces and NBSP; the decimal comma; U+2212; `-0`, `+0%`, `-0%`, `x0`; leading zeros;
  - refusals: `70.`, `.5`, `1e5`, `1 000`, `1.2.3`, `=-5`, `x-1`, `+-5`, `--5`, `%`, `x`, `=`, `abc`, `10%%`;
  - limits: 9 places OK / 10 refused (PLACES); `123456789012` OK / `1234567890123` refused (RANGE); `123456.789012345` (15 significant digits) OK / `1234567.123456789` (16) refused (DIGITS);
  - AMBIGUOUS: `1.500` and `1,500` refused as amounts with minorUnits 2 (and by default) and 0; `12.345` accepted as ABSOLUTE `12.345` with minorUnits 3; `x1.500` → MULTIPLY `1.5`; `1.125%` → PERCENT_OF; `1500` and `1.5` accepted;
  - every context mapping in §3.4.4, including board `20` → ABSOLUTE, `+20` → ADD, `-20` → ADD `-20`, `50%` → ADJUST_PERCENT; the OP_NOT_ALLOWED cases;
  - the round-trip property over a fixed list; `displayText` / `editText` with both decimal marks.
- **`workspace-model.test.ts`:**
  - `cellState` classification;
  - the upsert and clear rules of §3.3.2, including "same as default removes the period row";
  - the **row rule for relative entries**: base room → `needsServer`; a non-base fixed override receiving `x1.20` becomes MULTIPLY `1.2` from the default base; a manual non-base room receiving `x1.35` becomes a formula; no base room → error;
  - `renamePeriod` / `duplicatePeriod` / `copyPreviousPeriod` / `deletePeriodDeps`;
  - `setBaseRoom` exclusivity and re-pointing; default base resolution; the board projection and `applyBoardEntry`.
- **`workspace-occupancy.test.ts`:** the ladder projection per scope and basis, **including default cells** (adult positions without rules carry the server default; child bands without rules are `missing`); `validCombinations(capacity)` equal to the sweep rule; `persistCombination` rows; `groupCombinations` cards (cross product vs split); band code generation and the rename cascade.
- **`bands.test.ts`:** `bandLabel` (label, blank label, label equal to code); the `displayBandCodes` bracket rule (`Child 1 [CHB] @2A+2C × 0.5`, `STD 2A+2C [CHB]: …`); the token rule with `codes` (`age bands CHA and CHB overlap at …`); no replacement of unknown codes or substrings (`CHBX`); idempotence.
- **`grid-selection.test.ts`:** the selection reducer (anchor, range, separate ranges, header select, clamp) and fill-right/fill-down planning.
- **`history.test.ts`:** commit, undo, redo, a cap of 100, clear on reset.
- **`edits.test.ts`:** `keepKeys`.
- **`explain-ladder.test.ts`** (S14), on recorded, trimmed quote fixtures:
  - **(a) Deluxe 2A + child 8, 3 nights in P2, BB base.** The stage order is Base, Period, Room, Occupancy (adults), Child, Board, Night cost, Markup, FX, Promotion, Tax. Values: Base after `80`; Period with no amount; Room `80 → 108`; Occupancy `108 → 216`; Child `216 → 270` with a child line `54`; Board `270 → 270`; Night cost `270` (strings as served, compared canonically). No Special combination, Period adjustment or Rate plan stage. `chainBreaks` is empty, and the three nights collapse into one group.
  - **(b) A 2A+2C party with a combination rule.** A Special combination stage whose before equals `subtotal_children`.
  - **(c) A period with a night adjustment.** Period adjustment appears after Board and before Rate plan, and its before equals `subtotal_board`.
  - **(d) ROOM basis.** Occupancy before = room price and the `ROOM_BASIS` line is present.
  - **(e) A quote without the GAP-12 fields.** Stages 4, 5 and 7 have blank before/after and are not computed.
  - **(f) A synthetic break.** It is reported by `chainBreaks`.
- **`clipboard.test.ts`, `workspace-issues.test.ts`** (slices S10, S15).

### 5.2 Backend tests

- **Unit, pure** (`python -m pytest kamra/tex/tests/unit -q`, or the bench `unittest discover`):
  - `test_matrix.py`:
    - `unit_source` with the fixture terms: R-SUP generic ×1.15 → ALL, chain [SUP, STD]; R-SUITE-P3A ABSOLUTE 245 → PERIOD with the generic rule overridden; INHERIT skipped; a cycle → Unsellable;
    - `party_total` matching engine totals;
    - `adjust_amount`: 70 +10% → 77.00; 80.55 +10% → 88.61 HALF_UP; 100 ×1.155 → 115.50; JPY rounding; KWD 3-place rounding; 10 − 20 → NEGATIVE; −0% unchanged.
  - `test_validate_refs.py`: `ref` present for the listed codes (AGE_BANDS carries `age_bands`); BOARD_UNKNOWN_ROOM/PERIOD/DUPLICATE; messages byte-identical to before.
  - **`test_engine.py` (GAP-12):**
    - the spec example's totals and explanation text unchanged;
    - `nights[i].subtotal_children == nights[i].occupancy` when no combination rule applies;
    - with the fixture O-2A2C combination, `subtotal_children` equals the `COMBINATION_RULE` step's `before` and differs from `occupancy`;
    - `subtotal_board == occupancy + board` (asserted in Python with Decimal) and equal to `PERIOD_ADJUSTMENT.before` for a period with an adjustment;
    - under ROOM basis (room 200, 3 adults) `subtotal_adults == 270` and `unit == 200`;
    - PERSON 2A + one child: `after_adults` / `after_children` on `OccupancyResult`;
    - `to_dict(internal=False)["nights"]` has only `date` and `amount`;
    - `quoting.strip_internal` removes the new keys;
    - `test_contracts_restrictions.py:87` (quote equality) and `test_fx_record.py` still pass.
  - TestPurity keeps `kamra/tex/pricing` frappe-free.
- **Integration** (`bench --site test.localhost run-tests --module kamra.tex.tests.integration.test_pricing_workspace_api`):
  - The overlay `price_matrix`/`validate_version`/`preview_price` reflect unsaved data; the DB, `modified` and the audit trail are unchanged.
  - `~key` rule ids appear in sources, issue refs and explanations.
  - Refusals: a published version + `data`; no `contract.edit` + `data`; a user from another hotel; blank values (in save and in the overlay); a value with more than 9 places (the same message as save); over the row cap.
  - `price_matrix` returns `occupancy_defaults.adult` equal to `GLOBAL_ADULT_DEFAULT` (`op MULTIPLY`, `value "1"`) and `child: null`. The `age_bands` label equals the code when blank.
  - Viewer paths: a user with `price.view_cost` but no `contract.edit` gets `price_matrix` without `data` and a PermissionError from `validate_version` (this documents why the UI never calls it). An agent gets a PermissionError from `price_matrix` (existing G-11 behaviour).
  - `apply_op_values`: gate, Draft only, results and errors.
  - Preview children: ints (totals unchanged), `{age_months}`, `{dob}`, `7.5` refused, `"7"` accepted.
  - **Preview subtotals (GAP-12):** on a fixture draft priced for 2A + child 8, `nights[0]` carries `subtotal_adults`, `subtotal_children` and `subtotal_board` as 6-dp strings consistent with `occupancy` and `board`. A quote passed through `quoting.strip_internal` has none of them.
  - Flags: `can_preview`/`can_publish`/`can_edit_contract`/`basis_locked`/`minor_units` for the Revenue Manager, a contract.edit-only profile and a KWD contract.
  - `save_contract({name, pricing_basis})` changes only the basis on an unpublished contract and is refused after publish (existing controller).
  - GAP-3 keys with inherited policy bands (`create_contract(age_bands=[])`).
- **Must stay green:** `test_critical_journey`, `test_money_fields`, `test_age_bands`, `test_audit_trail`, `test_security_regressions`, `test_commercial_flows`, `test_concurrency`, `test_pricing_policies`, `test_snapshot_integrity`, all unit tests (419 at baseline), the eval harness (76/76) and the frontdesk journey (13/13).

### 5.3 Playwright

- **New: `frontend/e2e/pricing-workspace.spec.ts`** (desktop). It runs the 13 steps on a fresh contract created through the API **with `pricing_basis: "ROOM"`**, then on its auto-created draft.
  - **(1) Basis in the UI:** click the Basis chip, choose "Per person", click Apply. Assert that the header reads "Per person", the base row label becomes "Base person price", `contracts.get_contract` returns `PERSON`, no `role=dialog[aria-modal=true]` or `alertdialog` opened, and the draft is still clean.
  - **(2)** Add Standard (★ automatically), Superior and Deluxe.
  - **(3)** Add P1–P4 (Apr–Jul of next year).
  - **(4)** `70⇥80⇥100⇥130↵`.
  - **(5)** Superior All periods `x1.15`, and P4 `x1.20` (the override state is asserted).
  - **(6)** Deluxe `×1.35`, then select P3:P4 and type `x1.40` + Ctrl+Enter (bulk). The resolved rows read 80.50 / 92.00 / 115.00 / 156.00 and 94.50 / 108.00 / 140.00 / 182.00.
  - **(7)** 3rd adult `x0.70`; the 4th adult row shows "×1.00 default".
  - **(8)** Child ages drawer: 2.99 / 6.99 / 11.99. Labels are shown and no codes are visible anywhere on the page (`getByText(/\b(INF|CHA|CHB)\b/)` count 0).
  - **(9)** `x0` / `x0.25` / `x0.5` down the band rows.
  - **(10)** Builder 2A+2C: child 1 7–11.99 `×0.50`, child 2 3–6.99 `×0.25`. The card text is asserted.
  - **(11)** 3rd adult P4 `x0.80`, with an OVERRIDE marker.
  - Board BB base.
  - **(12) Price test:** Deluxe, 2 adults, child 8, 3 nights in P2, with **no `save_version` request observed**. The ladder is asserted **from server values only**:
    - Base 80.00;
    - Period "P2" with no amount;
    - Room 80.00 → 108.00;
    - Occupancy (adults) 108.00 → 216.00 (`nights[].unit` → `nights[].subtotal_adults`);
    - Child 216.00 → 270.00 (`subtotal_adults` → `subtotal_children`), with the child line 54.00 (`CHILD_SLOT.after`);
    - Board 270.00 → 270.00, "included" (`occupancy` → `subtotal_board`);
    - Night cost 270.00;
    - no Period adjustment or Rate plan stage;
    - the three nights shown as one group "Nights 1–3".

    The spec also reads the `preview_price` response it observed and checks that the displayed values equal the served `nights[0]` fields (formatted), which proves the page did not compute them.
  - **(13)** The ladder stages, the order caption and a "Rule applied:" entry are visible. The child rule label shows the band label, not the code.
  - Then Save, and verify through `contracts.get_version` the exact strings: `"1.15"`, `"1.2"`, `"1.35"`, `"1.4"`, `"0.7"`, `"0.8"`, combination `"2+2"` with positions 1 and 2, and bands 2.99/6.99/11.99 **with non-empty labels**.
  - **Interaction budget:** a `Budget` helper counts clicks, section switches and modal dialogs. It asserts ≤ 50 clicks, 0 section switches and 0 modal dialogs, and writes the counts to `testInfo.annotations`.
  - **Edge checks:**
    - `abc` shows an error and does not commit;
    - Escape reverts;
    - Ctrl+Z after the bulk restores `×1.35`;
    - a paste of a 2×2 TSV block;
    - relative `+10%` on the base P1 becomes `77.00` (server);
    - `x1.20` typed into a Superior cell holding `=245` restores a formula;
    - `1.500` in a price cell shows the AMBIGUOUS message.
- **New: `frontend/e2e/pricing-workspace-mobile.spec.ts`** (desktop + Pixel 7):
  - A published version renders read-only (no textbox, `aria-readonly`, no "Edit price:", no Basis popover trigger), with no horizontal page scroll at 375 px and **no request to `validate_version`**.
  - An agent without cost access sees a catalogue with no amounts and no page errors (`trackErrors`). There is **no request to `price_matrix`, `validate_version` or `preview_price`**, and no 403 response.
- **Migrated: `frontend/e2e/flows/contracts.ts`.**
  - **Slice S8 (compatibility step):** `openTab(id)` routes to the new sections, with the old table ids opening "Commercial rules → Rule tables → <label>". It returns `page.getByRole("tabpanel", {name})`, so `addRooms`/`addPeriod`/`setBaseRate`/`addOccupancyRules`/`addBoard`/`expectPublishedReadOnly` keep working through the Advanced rule tables. `previewPrice` targets "Preview & audit".
  - **Slice S14:** `contract-admin.spec.ts:109-110` change from `Child \[CHD\]` / `Child \[INF\]` to the labels that spec gives those bands (`Child \[Child\]`, `Child \[Infant\]`).
  - **Slice S16 (primary path):**
    - The same exported functions, with unchanged signatures, switch to the workspace path: "Add room", "+ Period", typed cells, the ladder and bands drawer, the boards section, and the Price test drawer. A `{advanced: true}` option is kept.
    - `expectPublishedReadOnly` asserts the read-only matrix.
    - `editor-edits.spec.ts` keeps the Discard test and the in-flight-save test (adding a period column while `save_version` is held).
    - `entry-branding.spec.ts` `#plans` asserts "Commercial rules" plus the selected "Rate plans" inner tab.
    - `contract-admin` and `critical-journey` run through the helpers.
- **Delivery:** `npm run build`, then commit `kamra/public/frontend` + `kamra/public/tex`, because CI runs Playwright against the committed bundles.

---

## 6. Risks and deliberately out of scope

**Risks**
1. **Overlay cost:** `build_terms` plus a matrix on every settled edit. Mitigated by debounce and abort, row caps, and one room for parties. Watch contracts with more than 20 rooms × 20 periods.
2. **Precedence surprises:** a COMBINATION rule beats a PERIOD rule, and a room period cell replaces the default. The UI states both, but users may still expect stacking.
3. **Period renames** rewrite codes in three tables because there is no foreign key. The pure function is tested, and orphans are caught by the new BOARD_* checks and the existing ROOM_RULE/OCC_UNKNOWN_PERIOD checks.
4. **E2E breakage** when the layout changes. Mitigated by the S8 compatibility helpers and by keeping accessible names ("Version sections", "Room prices by period", "Edit price: …", "Save", "Draft saved"). Two explanation regexes change deliberately (band labels, S14).
5. **Committed bundles:** CI's browser tests only see the new UI once the bundles are rebuilt and committed (final slice).
6. **Keyboard conflicts:** Ctrl+R and Ctrl+D are browser shortcuts. They are intercepted only while the grid has focus, and toolbar buttons exist for both.
7. **Undo after save** makes the state dirty again (intended). Undo history is per tab and in memory. The basis change cannot be undone from the history (it is a saved header change); the popover can switch it back while unpublished.
8. **AMBIGUOUS** may annoy users in 2-decimal currencies who type `12.500`; the message says exactly what to type. In 3-decimal currencies, a user who types `1.500` meaning 1500 is not stopped; the reading line shows the parsed amount before commit.
9. **Owner sign-off O1** (a bare board number = per room-night): if users expect per-adult, board prices could be entered wrongly. The reading line names the unit on every entry.
10. **Band-code replacement** works on server text by pattern. It is limited to known codes and to the bracket and ref-scoped token rules, and it is unit-tested. A band code that equals another word in the same message would also be replaced (acceptable; codes are short upper-case ids).
11. **i18n volume:** about 280 new keys × 6 languages. The literal-key scan catches keys missing from `en.json`.
12. **GAP-5 ERRORs** can block publishing drafts that already contain orphan or duplicate board rows. This is correct, but it is a behaviour change to announce.
13. **The ladder order differs from the owner's list** in one place: the period's amount effect appears after Board, not second, because that is where the engine applies it. The period's identity stays second. This is stated on screen and is the only honest before → after chain; a different display order would need an engine change, which is out of scope.
14. **GAP-12 touches `engine.py`.** The change adds three reported fields and changes no arithmetic. The quote-equality, snapshot and FX-record tests guard it, and no price, total, explanation text or `engine_version` changes. Stored quotes from before the change lack the fields; the ladder shows blanks for those stages rather than computing them.

**Out of scope (deliberately)**
- Any change to pricing semantics, ops, precedence or the payload; autosave of versions; a server-side "base room" (GAP-11); per-band board child % (GAP-9).
- Optimistic concurrency between users on `save_version` (last writer wins remains; a future `expected_modified`).
- Reordering the engine's pipeline to match the owner's stage list (the ladder shows the real order instead).
- Refactoring AriGrid/ExtrasGrid onto the new grid hook (later cleanup).
- CSV import/export of the matrix; full localisation of every explanation code (templates are added where cheap; band codes are always mapped).
- Joint multi-child conditions (the engine cannot express them); changing the pricing basis after the first publish (impossible by design; duplicate the contract instead).
- Redesigning offers (they are only moved) and the pricing-policy editor (`RowsEditor` untouched).
- Reusing any code from the bookengine repository (UX reference only, §1.4).

---

## 7. Implementation slices

The ordered slice plan is S1–S16. The parser and the backend gaps come first (S1–S5, GAP-12 in S5); the Playwright acceptance spec and the E2E migration come last (S16). The worktree is `/home/user/tex-pricing-ws`.

Each slice lists **every** slice it directly needs in `depends_on`, so it can be scheduled by dependencies as well as run in numeric order. This was checked file by file:
- any slice that reads `contract_doc.minor_units` or sends overlay `data` lists S2;
- any slice that uses `useDraftPreview` or edits `PricingSection.tsx` lists S8;
- any slice that uses Popover/Menu/Tooltip lists S7;
- `useWorkspaceHistory` is created in S9.

Each slice is one or more small commits with its tests green. `docs/tex-engine/IMPLEMENTATION_STATUS.md` is updated at S2 (ADR-061), S5 (GAP-12), S8, S15 and S16.
