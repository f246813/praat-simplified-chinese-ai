import type { Page } from '@playwright/test';

/**
 * Grow the mount window until every loaded message is mounted.
 *
 * Not a test file: `tests/browser` only collects `*.spec.ts`. Fixtures that live above the
 * steady window have to be revealed the way a reader would reveal them, so the specs stay
 * honest about what the window does instead of mounting everything up front.
 */
export async function revealAllHistory(page: Page) {
  const reveal = page.locator('.history-reveal button');
  for (let round = 0; round < 12; round++) {
    if (!(await reveal.count())) return;
    await reveal.evaluate(el => (el as HTMLElement).click());
    await page.waitForTimeout(150);
  }
  throw new Error('the history window never opened fully');
}
