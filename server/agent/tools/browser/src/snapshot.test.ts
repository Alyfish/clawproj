/**
 * Tests for the AI Snapshot system.
 *
 * Uses real headless Chromium via Playwright to test the DOM walker
 * and ref-based interaction actions.
 */

import { describe, it, expect, beforeAll, afterAll, beforeEach } from 'vitest';
import {
  chromium,
  type Browser,
  type BrowserContext,
  type Page,
} from 'playwright';
import {
  snapshotAction,
  clickRefAction,
  typeRefAction,
  selectRefAction,
} from './snapshot.js';

// No-op screenshot for tests (avoids file I/O overhead)
const noopScreenshot = async () => undefined;

describe('snapshot', () => {
  let browser: Browser;
  let context: BrowserContext;
  let page: Page;

  beforeAll(async () => {
    browser = await chromium.launch({ headless: true });
  });

  afterAll(async () => {
    await browser.close();
  });

  beforeEach(async () => {
    context = await browser.newContext({
      viewport: { width: 1280, height: 720 },
    });
    page = await context.newPage();
  });

  // ----------------------------------------------------------
  // SNAPSHOT GENERATION
  // ----------------------------------------------------------

  describe('DOM walker', () => {
    it('assigns refs to interactive elements', async () => {
      await page.setContent(`
        <html><body>
          <h1>Test Page</h1>
          <a href="/about">About</a>
          <button>Click Me</button>
          <input type="text" placeholder="Name" />
          <select><option>A</option><option>B</option></select>
        </body></html>
      `);

      const result = await snapshotAction(page, {}, noopScreenshot);
      expect(result.success).toBe(true);
      expect(result.result.element_count).toBe(4);
      expect(result.result.snapshot).toContain('[1] link "About"');
      expect(result.result.snapshot).toContain('[2] button "Click Me"');
      expect(result.result.snapshot).toContain('[3] input "Name"');
      expect(result.result.snapshot).toContain('[4] select');
    });

    it('skips hidden elements', async () => {
      await page.setContent(`
        <html><body>
          <button style="display:none">Hidden</button>
          <button style="visibility:hidden">Invisible</button>
          <button aria-hidden="true">AriaHidden</button>
          <button>Visible</button>
        </body></html>
      `);

      const result = await snapshotAction(page, {}, noopScreenshot);
      expect(result.result.element_count).toBe(1);
      expect(result.result.snapshot).toContain('Visible');
      expect(result.result.snapshot).not.toContain('"Hidden"');
      expect(result.result.snapshot).not.toContain('"Invisible"');
      expect(result.result.snapshot).not.toContain('"AriaHidden"');
    });

    it('skips elements inside hidden parents', async () => {
      await page.setContent(`
        <html><body>
          <div style="display:none">
            <button>Inside Hidden Div</button>
            <a href="/hidden">Hidden Link</a>
          </div>
          <button>Standalone Visible</button>
        </body></html>
      `);

      const result = await snapshotAction(page, {}, noopScreenshot);
      expect(result.result.element_count).toBe(1);
      expect(result.result.snapshot).toContain('Standalone Visible');
      expect(result.result.snapshot).not.toContain('Inside Hidden Div');
      expect(result.result.snapshot).not.toContain('Hidden Link');
    });

    it('truncates snapshot at approximately 6000 chars', async () => {
      const buttons = Array.from(
        { length: 300 },
        (_, i) =>
          `<button>Button number ${i} with some extra descriptive text to pad</button>`,
      ).join('\n');
      await page.setContent(`<html><body>${buttons}</body></html>`);

      const result = await snapshotAction(page, {}, noopScreenshot);
      // Allow small tolerance for truncation message
      expect(result.result.snapshot.length).toBeLessThanOrEqual(6200);
      expect(result.result.snapshot).toContain('more interactive elements');
    });

    it('includes ARIA labels', async () => {
      await page.setContent(`
        <html><body>
          <button aria-label="Close dialog">X</button>
        </body></html>
      `);

      const result = await snapshotAction(page, {}, noopScreenshot);
      expect(result.result.snapshot).toContain('aria="Close dialog"');
    });

    it('includes page text section', async () => {
      await page.setContent(`
        <html><body>
          <h1>Welcome to the App</h1>
          <p>Some descriptive paragraph text here.</p>
          <button>Go</button>
        </body></html>
      `);

      const result = await snapshotAction(page, {}, noopScreenshot);
      expect(result.result.snapshot).toContain(
        '--- Page Text (above fold) ---',
      );
      expect(result.result.snapshot).toContain('Welcome to the App');
    });

    it('handles input types and values', async () => {
      await page.setContent(`
        <html><body>
          <input type="email" placeholder="Email" value="user@test.com" />
          <input type="password" placeholder="Password" />
        </body></html>
      `);

      const result = await snapshotAction(page, {}, noopScreenshot);
      expect(result.result.snapshot).toContain(
        'input[email] "Email" value="user@test.com"',
      );
      expect(result.result.snapshot).toContain('input[password] "Password"');
    });

    it('includes select options', async () => {
      await page.setContent(`
        <html><body>
          <select name="color">
            <option value="r">Red</option>
            <option value="g" selected>Green</option>
            <option value="b">Blue</option>
          </select>
        </body></html>
      `);

      const result = await snapshotAction(page, {}, noopScreenshot);
      expect(result.result.snapshot).toContain('value="Green"');
      expect(result.result.snapshot).toContain('"Red"');
      expect(result.result.snapshot).toContain('"Green"');
      expect(result.result.snapshot).toContain('"Blue"');
    });

    it('detects cursor:pointer elements', async () => {
      await page.setContent(`
        <html><body>
          <div style="cursor:pointer" onclick="alert(1)">Clickable Card</div>
          <div>Not clickable</div>
        </body></html>
      `);

      const result = await snapshotAction(page, {}, noopScreenshot);
      // "Clickable Card" should appear as a numbered ref
      expect(result.result.snapshot).toMatch(/\[\d+\].*Clickable Card/);
      // "Not clickable" should NOT appear as a numbered ref (may appear in page text)
      expect(result.result.snapshot).not.toMatch(/\[\d+\].*Not clickable/);
    });

    it('includes page URL and title', async () => {
      await page.setContent(`
        <html><head><title>My Page</title></head>
        <body><button>OK</button></body></html>
      `);

      const result = await snapshotAction(page, {}, noopScreenshot);
      expect(result.result.snapshot).toContain('[Page] My Page');
      expect(result.result.snapshot).toContain('[URL]');
      expect(result.result.url).toBeDefined();
      expect(result.result.title).toBe('My Page');
    });

    it('handles role=checkbox with checked state', async () => {
      await page.setContent(`
        <html><body>
          <div role="checkbox" aria-checked="true" aria-label="Accept terms">Terms</div>
        </body></html>
      `);

      const result = await snapshotAction(page, {}, noopScreenshot);
      expect(result.result.snapshot).toContain('checkbox "Accept terms"');
      expect(result.result.snapshot).toContain('[checked]');
    });

    it('handles role=tab with selected state', async () => {
      await page.setContent(`
        <html><body>
          <div role="tab" aria-selected="true">Overview</div>
          <div role="tab" aria-selected="false">Details</div>
        </body></html>
      `);

      const result = await snapshotAction(page, {}, noopScreenshot);
      expect(result.result.snapshot).toContain('tab "Overview" [selected]');
      expect(result.result.snapshot).toContain('tab "Details"');
      // The non-selected tab should NOT have [selected]
      const lines = result.result.snapshot.split('\n');
      const detailsLine = lines.find((l: string) =>
        l.includes('tab "Details"'),
      );
      expect(detailsLine).not.toContain('[selected]');
    });

    it('uses label elements for input descriptions', async () => {
      await page.setContent(`
        <html><body>
          <label for="email-input">Email Address</label>
          <input type="text" id="email-input" />
        </body></html>
      `);

      const result = await snapshotAction(page, {}, noopScreenshot);
      expect(result.result.snapshot).toContain('"Email Address"');
    });
  });

  // ----------------------------------------------------------
  // CLICK_REF
  // ----------------------------------------------------------

  describe('click_ref', () => {
    it('clicks element by ref number', async () => {
      await page.setContent(`
        <html><body>
          <button id="btn" onclick="document.title='clicked'">Click Me</button>
        </body></html>
      `);

      await snapshotAction(page, {}, noopScreenshot);
      const result = await clickRefAction(page, { ref: 1 }, noopScreenshot);
      expect(result.success).toBe(true);
      expect(result.result.clicked).toContain('[1]');
      expect(await page.title()).toBe('clicked');
    });

    it('returns error for invalid ref', async () => {
      await page.setContent(`<html><body><button>OK</button></body></html>`);
      await snapshotAction(page, {}, noopScreenshot);
      const result = await clickRefAction(page, { ref: 99 }, noopScreenshot);
      expect(result.success).toBe(false);
      expect(result.error).toContain('not found');
    });

    it('returns error when no snapshot taken', async () => {
      await page.setContent(`<html><body><button>OK</button></body></html>`);
      // Clear any refs
      await page.evaluate(() => {
        (window as any).__clawbot_refs = undefined;
      });
      const result = await clickRefAction(page, { ref: 1 }, noopScreenshot);
      expect(result.success).toBe(false);
      expect(result.error).toContain('snapshot');
    });

    it('returns error for missing ref param', async () => {
      await page.setContent(`<html><body><button>OK</button></body></html>`);
      const result = await clickRefAction(page, {}, noopScreenshot);
      expect(result.success).toBe(false);
      expect(result.error).toContain('ref');
    });

    it('reports new URL after clicking a link', async () => {
      await page.setContent(`
        <html><body>
          <a href="about:blank">Navigate Away</a>
        </body></html>
      `);

      await snapshotAction(page, {}, noopScreenshot);
      const result = await clickRefAction(page, { ref: 1 }, noopScreenshot);
      expect(result.success).toBe(true);
      expect(result.result.new_url).toBeDefined();
    });
  });

  // ----------------------------------------------------------
  // TYPE_REF
  // ----------------------------------------------------------

  describe('type_ref', () => {
    it('types text into input by ref', async () => {
      await page.setContent(`
        <html><body>
          <input type="text" id="name" placeholder="Name" />
        </body></html>
      `);

      await snapshotAction(page, {}, noopScreenshot);
      const result = await typeRefAction(
        page,
        { ref: 1, text: 'Alice', clear: true },
        noopScreenshot,
      );
      expect(result.success).toBe(true);
      expect(result.result.typed_into).toContain('[1]');
      const value = await page.locator('#name').inputValue();
      expect(value).toBe('Alice');
    });

    it('appends text when clear is false', async () => {
      await page.setContent(`
        <html><body>
          <input type="text" id="name" placeholder="Name" value="Hello " />
        </body></html>
      `);

      await snapshotAction(page, {}, noopScreenshot);
      const result = await typeRefAction(
        page,
        { ref: 1, text: 'World', clear: false },
        noopScreenshot,
      );
      expect(result.success).toBe(true);
      const value = await page.locator('#name').inputValue();
      expect(value).toBe('Hello World');
    });

    it('clears before typing by default', async () => {
      await page.setContent(`
        <html><body>
          <input type="text" id="name" placeholder="Name" value="Old Value" />
        </body></html>
      `);

      await snapshotAction(page, {}, noopScreenshot);
      const result = await typeRefAction(
        page,
        { ref: 1, text: 'New' },
        noopScreenshot,
      );
      expect(result.success).toBe(true);
      const value = await page.locator('#name').inputValue();
      expect(value).toBe('New');
    });

    it('returns error for missing text param', async () => {
      await page.setContent(`
        <html><body><input type="text" placeholder="Name" /></body></html>
      `);
      await snapshotAction(page, {}, noopScreenshot);
      const result = await typeRefAction(page, { ref: 1 }, noopScreenshot);
      expect(result.success).toBe(false);
      expect(result.error).toContain('text');
    });

    it('types into textarea', async () => {
      await page.setContent(`
        <html><body>
          <textarea id="msg" placeholder="Message"></textarea>
        </body></html>
      `);

      await snapshotAction(page, {}, noopScreenshot);
      const result = await typeRefAction(
        page,
        { ref: 1, text: 'Hello world' },
        noopScreenshot,
      );
      expect(result.success).toBe(true);
      const value = await page.locator('#msg').inputValue();
      expect(value).toBe('Hello world');
    });
  });

  // ----------------------------------------------------------
  // SELECT_REF
  // ----------------------------------------------------------

  describe('select_ref', () => {
    it('selects option in dropdown by value', async () => {
      await page.setContent(`
        <html><body>
          <select id="color">
            <option value="r">Red</option>
            <option value="g">Green</option>
            <option value="b">Blue</option>
          </select>
        </body></html>
      `);

      await snapshotAction(page, {}, noopScreenshot);
      const result = await selectRefAction(
        page,
        { ref: 1, value: 'g' },
        noopScreenshot,
      );
      expect(result.success).toBe(true);
      const selected = await page.locator('#color').inputValue();
      expect(selected).toBe('g');
    });

    it('selects option by label text', async () => {
      await page.setContent(`
        <html><body>
          <select id="color">
            <option value="r">Red</option>
            <option value="g">Green</option>
            <option value="b">Blue</option>
          </select>
        </body></html>
      `);

      await snapshotAction(page, {}, noopScreenshot);
      const result = await selectRefAction(
        page,
        { ref: 1, value: 'Green' },
        noopScreenshot,
      );
      expect(result.success).toBe(true);
      const selected = await page.locator('#color').inputValue();
      expect(selected).toBe('g');
    });

    it('toggles checkbox on', async () => {
      await page.setContent(`
        <html><body>
          <input type="checkbox" id="agree" />
        </body></html>
      `);

      await snapshotAction(page, {}, noopScreenshot);
      const result = await selectRefAction(
        page,
        { ref: 1, value: 'true' },
        noopScreenshot,
      );
      expect(result.success).toBe(true);
      const checked = await page.locator('#agree').isChecked();
      expect(checked).toBe(true);
    });

    it('toggles checkbox off', async () => {
      await page.setContent(`
        <html><body>
          <input type="checkbox" id="agree" checked />
        </body></html>
      `);

      await snapshotAction(page, {}, noopScreenshot);
      const result = await selectRefAction(
        page,
        { ref: 1, value: 'false' },
        noopScreenshot,
      );
      expect(result.success).toBe(true);
      const checked = await page.locator('#agree').isChecked();
      expect(checked).toBe(false);
    });

    it('returns error for non-select/checkbox element', async () => {
      await page.setContent(`
        <html><body>
          <button>Not a select</button>
        </body></html>
      `);

      await snapshotAction(page, {}, noopScreenshot);
      const result = await selectRefAction(
        page,
        { ref: 1, value: 'something' },
        noopScreenshot,
      );
      expect(result.success).toBe(false);
      expect(result.error).toContain('not a select');
    });

    it('returns error for missing value param', async () => {
      await page.setContent(`
        <html><body><select><option>A</option></select></body></html>
      `);
      await snapshotAction(page, {}, noopScreenshot);
      const result = await selectRefAction(page, { ref: 1 }, noopScreenshot);
      expect(result.success).toBe(false);
      expect(result.error).toContain('value');
    });
  });
});
