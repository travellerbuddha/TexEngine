// The interaction budget of the Pricing Workspace acceptance spec (PRICING_WORKSPACE_UX.md §1.3,
// §5.3): what a user does to enter a contract, counted in the page itself while the budget runs.
// - clicks: every pointer press the page receives (a trusted primary `pointerdown`), plus the
//   gestures Playwright performs without one: a native <select> choice counts 2 (open, pick) and a
//   field filled while it does not have the focus counts 1 (the click that would focus it).
//   Keyboard keys (Tab, Enter, arrows, typing) are never clicks.
// - sectionSwitches: every change of the selected tab of the version editor's "Version sections".
// - modals: every modal dialog that appears (`[aria-modal="true"]`, `role="alertdialog"`, a
//   `<dialog>` opened with showModal()) and every browser dialog (alert, confirm, prompt).
// The counts come from the page (a MutationObserver and a capture listener), so a click or a switch
// made outside the wrappers below is counted too. Attach before the first navigation.
import { expect, type Locator, type Page, type TestInfo } from "@playwright/test"

export interface BudgetCounts {
  clicks: number
  sectionSwitches: number
  modals: number
}

type Event = { kind: "click" | "section" | "modal"; detail: string }

/** The page side: reports pointer presses, section switches and modal dialogs to the binding. */
function observe(sections: string) {
  const w = window as unknown as { __texBudget?: (kind: string, detail: string) => void; __texBudgetOn?: boolean }
  if (w.__texBudgetOn) return
  w.__texBudgetOn = true
  const report = (kind: string, detail: string) => {
    try {
      void w.__texBudget?.(kind, detail)
    } catch {
      /* the binding is gone while the page unloads */
    }
  }
  const describe = (el: Element | null) => {
    if (!el) return ""
    const h = el as HTMLElement
    const named = h.closest("[aria-label],button,a,[role]") as HTMLElement | null
    const text = (named?.getAttribute("aria-label") || named?.textContent || h.tagName).replace(/\s+/g, " ").trim()
    return text.slice(0, 80)
  }
  document.addEventListener(
    "pointerdown",
    (e) => {
      if (e.isTrusted && e.isPrimary) report("click", describe(e.target as Element))
    },
    true,
  )
  const seen = new WeakSet<Element>()
  let section: string | null = null
  const scan = () => {
    let modal: Element[] = []
    try {
      modal = Array.from(document.querySelectorAll('[aria-modal="true"], [role="alertdialog"], dialog:modal'))
    } catch {
      modal = Array.from(document.querySelectorAll('[aria-modal="true"], [role="alertdialog"]'))
    }
    for (const el of modal) {
      if (seen.has(el)) continue
      seen.add(el)
      report("modal", el.getAttribute("aria-label") || (el.textContent ?? "").replace(/\s+/g, " ").trim().slice(0, 80))
    }
    const list = Array.from(document.querySelectorAll('[role="tablist"]')).find((x) => x.getAttribute("aria-label") === sections)
    const tab = list?.querySelector('[role="tab"][aria-selected="true"]')
    const now = tab ? tab.id || tab.getAttribute("aria-controls") || (tab.textContent ?? "") : null
    if (now !== null) {
      if (section !== null && now !== section) report("section", `${section} → ${now}`)
      section = now
    }
  }
  const start = () => {
    scan()
    new MutationObserver(scan).observe(document.documentElement, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["aria-modal", "role", "aria-selected", "open"],
    })
  }
  if (document.documentElement) start()
  else document.addEventListener("DOMContentLoaded", start, { once: true })
}

export class Budget {
  private armed = false
  private readonly events: Event[] = []

  private constructor(private readonly page: Page) {}

  /** Attach the counters to `page` (before its first navigation; the page may already be open).
   * `sections` is the accessible name of the version editor's section tablist. Counting starts
   * with `start()`. */
  static async attach(page: Page, sections = "Version sections"): Promise<Budget> {
    const b = new Budget(page)
    await page.exposeBinding("__texBudget", (_source, kind: string, detail: string) => b.record(kind as Event["kind"], detail))
    await page.addInitScript(observe, sections)
    // a page already open gets the observer too (addInitScript covers the next documents)
    await page.evaluate(observe, sections).catch(() => undefined)
    page.on("dialog", (d) => b.record("modal", `browser ${d.type()}: ${d.message()}`))
    return b
  }

  private record(kind: Event["kind"], detail: string) {
    if (this.armed) this.events.push({ kind, detail })
  }

  /** Start (or resume) counting. */
  start() {
    this.armed = true
  }

  /** Stop counting (checks and set-up done between the steps are not the user's gestures). */
  async stop() {
    await this.settle()
    this.armed = false
  }

  /** Let the page's last reports arrive (they are sent asynchronously). */
  private async settle() {
    await this.page.evaluate(() => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)))).catch(() => undefined)
  }

  /** Choose in a native <select>: two clicks for a user (open the list, pick the option). */
  async select(locator: Locator, value: string | { label: string } | { value: string }) {
    this.record("click", "select: open")
    this.record("click", "select: pick")
    await locator.selectOption(value)
  }

  /** Type into a field: a user clicks it first unless it already has the focus. */
  async fill(locator: Locator, text: string) {
    const focused = await locator.evaluate((el) => el === document.activeElement)
    if (!focused) this.record("click", "focus a field")
    await locator.fill(text)
  }

  /** The counts so far. */
  async counts(): Promise<BudgetCounts> {
    await this.settle()
    const n = (k: Event["kind"]) => this.events.filter((e) => e.kind === k).length
    return { clicks: n("click"), sectionSwitches: n("section"), modals: n("modal") }
  }

  /** What was counted, in order (for the report when a limit is exceeded). */
  log(): string {
    return this.events.map((e, i) => `${i + 1}. ${e.kind}: ${e.detail}`).join("\n")
  }

  /** Record the counts in the test's annotations and assert the limits. */
  async expectWithin(testInfo: TestInfo, limits: BudgetCounts) {
    const c = await this.counts()
    testInfo.annotations.push(
      { type: "budget: clicks", description: `${c.clicks} (limit ${limits.clicks})` },
      { type: "budget: section switches", description: `${c.sectionSwitches} (limit ${limits.sectionSwitches})` },
      { type: "budget: modal dialogs", description: `${c.modals} (limit ${limits.modals})` },
    )
    await testInfo.attach("budget.txt", { body: `${JSON.stringify(c)}\n${this.log()}\n`, contentType: "text/plain" })
    expect(c.clicks, this.log()).toBeLessThanOrEqual(limits.clicks)
    expect(c.sectionSwitches, this.log()).toBeLessThanOrEqual(limits.sectionSwitches)
    expect(c.modals, this.log()).toBeLessThanOrEqual(limits.modals)
    return c
  }
}

// ─── gestures that count on an optional budget (the flows take `budget?: Budget`) ───────────

/** A menu button's item, e.g. the workspace's "Add room" / "Add board" menus: two clicks (open the
 * menu, pick the item), which the page counts itself. A board is named by its code in the item
 * ("Half board (HB)"). */
export async function pickFrom(menu: Locator, item: string | RegExp) {
  await menu.click()
  const name = typeof item === "string" && /^[A-Z]{2,4}$/.test(item) ? new RegExp(`\\(${item}\\)$`) : item
  await menu.page().getByRole("menuitem", { name, exact: typeof name === "string" }).click()
}

/** selectOption, counted as two clicks on a budget. */
export async function choose(budget: Budget | undefined, locator: Locator, value: string | { label: string } | { value: string }) {
  if (budget) await budget.select(locator, value)
  else await locator.selectOption(value)
}

/** fill, counted as a click on a budget when the field does not have the focus. */
export async function typeIn(budget: Budget | undefined, locator: Locator, text: string) {
  if (budget) await budget.fill(locator, text)
  else await locator.fill(text)
}
