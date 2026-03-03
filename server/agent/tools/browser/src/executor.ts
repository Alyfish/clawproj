/**
 * Browser Action Executor
 *
 * Implements all 7 browser actions the agent can invoke:
 * navigate, search, fill_form, click, extract_data, take_screenshot, get_page_content
 *
 * Every action returns an ActionResult with a screenshot.
 * Checkpoint detection runs BEFORE execution to gate risky pages.
 * No action ever auto-submits a form or clicks payment buttons.
 */

import type { Page, Locator } from 'playwright';
import { SessionManager } from './sessions.js';
import { CheckpointDetector } from './checkpoint.js';
import type { CheckpointResult } from './checkpoint.js';
import {
  snapshotAction,
  clickRefAction,
  typeRefAction,
  selectRefAction,
} from './snapshot.js';
import dns from 'node:dns';
import net from 'node:net';
import { promisify } from 'node:util';

const dnsLookupAll = promisify(dns.resolve);

// ============================================================
// CONSTANTS
// ============================================================

const NAVIGATE_TIMEOUT = 60_000;
const CLICK_TIMEOUT = 10_000;
const MAX_CONTENT_LENGTH = 50_000;
const MAX_SEARCH_RESULTS = 10;
const POST_ACTION_WAIT = 1_000;

// ============================================================
// SSRF PROTECTION (defense-in-depth — Python layer is primary)
// ============================================================

const ALLOWED_PORTS = new Set([80, 443, 8080, 8443]);

const BLOCKED_HOSTNAMES = new Set([
  'localhost',
  'localhost.localdomain',
  '0.0.0.0',
  'metadata.google.internal',
  'metadata.internal',
  'kubernetes.default.svc',
]);

const BLOCKED_HOSTNAME_SUFFIXES = ['.local', '.internal', '.localhost'];

interface SSRFCheckResult {
  allowed: boolean;
  reason: string;
}

function isBlockedIP(ip: string): boolean {
  // Parse octets for IPv4
  const parts = ip.split('.').map(Number);
  if (parts.length === 4 && parts.every((p) => p >= 0 && p <= 255)) {
    const [a, b] = parts;
    if (a === 10) return true; // 10.0.0.0/8
    if (a === 172 && b >= 16 && b <= 31) return true; // 172.16.0.0/12
    if (a === 192 && b === 168) return true; // 192.168.0.0/16
    if (a === 127) return true; // 127.0.0.0/8
    if (a === 169 && b === 254) return true; // 169.254.0.0/16
    if (a === 0) return true; // 0.0.0.0/8
    if (a === 100 && b >= 64 && b <= 127) return true; // 100.64.0.0/10
    if (a >= 224 && a <= 239) return true; // 224.0.0.0/4
    if (a >= 240) return true; // 240.0.0.0/4
    return false;
  }

  // IPv6 checks
  const lower = ip.toLowerCase();
  if (lower === '::1') return true;
  if (lower.startsWith('fe80:')) return true;
  if (lower.startsWith('fc') || lower.startsWith('fd')) return true;

  return false;
}

function checkSSRFSync(url: string): SSRFCheckResult {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return { allowed: false, reason: 'Malformed URL' };
  }

  const scheme = parsed.protocol.replace(':', '');
  if (scheme !== 'http' && scheme !== 'https') {
    return { allowed: false, reason: `Blocked scheme: ${scheme}` };
  }

  const hostname = parsed.hostname.toLowerCase();
  if (!hostname) {
    return { allowed: false, reason: 'Missing hostname' };
  }

  if (BLOCKED_HOSTNAMES.has(hostname)) {
    return { allowed: false, reason: `Blocked hostname: ${hostname}` };
  }

  for (const suffix of BLOCKED_HOSTNAME_SUFFIXES) {
    if (hostname.endsWith(suffix)) {
      return {
        allowed: false,
        reason: `Blocked hostname pattern: ${hostname}`,
      };
    }
  }

  const port = parsed.port
    ? parseInt(parsed.port, 10)
    : scheme === 'https'
      ? 443
      : 80;
  if (!ALLOWED_PORTS.has(port)) {
    return { allowed: false, reason: `Blocked port: ${port}` };
  }

  if (net.isIP(hostname)) {
    if (isBlockedIP(hostname)) {
      return { allowed: false, reason: `Blocked IP: ${hostname}` };
    }
  }

  return { allowed: true, reason: 'OK' };
}

async function checkSSRF(url: string): Promise<SSRFCheckResult> {
  const syncResult = checkSSRFSync(url);
  if (!syncResult.allowed) return syncResult;

  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return { allowed: false, reason: 'Malformed URL' };
  }

  const hostname = parsed.hostname.toLowerCase();

  // If raw IP, sync check already handled it
  if (net.isIP(hostname)) return syncResult;

  // DNS resolution check
  try {
    const addresses = (await promisify(dns.lookup)(hostname, {
      all: true,
    })) as dns.LookupAddress[];
    for (const addr of addresses) {
      if (isBlockedIP(addr.address)) {
        log('warn', 'ssrf:dns_blocked', { hostname, resolvedIP: addr.address });
        return {
          allowed: false,
          reason: `Hostname ${hostname} resolves to blocked IP: ${addr.address}`,
        };
      }
    }
  } catch {
    log('warn', 'ssrf:dns_failed', { hostname });
    return { allowed: false, reason: `DNS resolution failed: ${hostname}` };
  }

  return { allowed: true, reason: 'OK' };
}

const SEARCH_INPUT_STRATEGIES: readonly string[] = [
  'input[type="search"]',
  'input[name="q"]',
  'input[name="query"]',
  'input[name="search"]',
  'input[aria-label*="search" i]',
  'input[placeholder*="search" i]',
  'textarea[name="q"]',
] as const;

// ============================================================
// LOGGING
// ============================================================

function log(
  level: 'info' | 'warn' | 'error',
  event: string,
  data?: Record<string, unknown>,
): void {
  console.log(
    JSON.stringify({ level, event, data, timestamp: new Date().toISOString() }),
  );
}

// ============================================================
// TYPES
// ============================================================

export interface ActionResult {
  success: boolean;
  result: any;
  screenshot?: string;
  error?: string;
  needs_approval?: boolean;
  approval_reason?: string;
  checkpoint_type?: string;
}

type BrowserAction =
  | 'navigate'
  | 'search'
  | 'fill_form'
  | 'click'
  | 'extract_data'
  | 'take_screenshot'
  | 'get_page_content'
  | 'wait_for_selector'
  | 'scroll'
  | 'snapshot'
  | 'click_ref'
  | 'type_ref'
  | 'select_ref';

// ============================================================
// ACTION EXECUTOR
// ============================================================

export class ActionExecutor {
  constructor(
    private readonly sessionManager: SessionManager,
    private readonly checkpointDetector: CheckpointDetector,
  ) {}

  // ----------------------------------------------------------
  // PUBLIC API
  // ----------------------------------------------------------

  async execute(
    sessionId: string,
    action: string,
    params: Record<string, any>,
  ): Promise<ActionResult> {
    // Step 1: Get page from session
    const page = this.sessionManager.getPage(sessionId);
    if (!page) {
      return {
        success: false,
        result: null,
        error: `No active browser session for sessionId: ${sessionId}`,
      };
    }

    // Step 2: Checkpoint detection BEFORE action
    try {
      const checkpoint = await this.checkpointDetector.detect(
        page,
        action,
        params,
      );
      if (checkpoint.needsApproval) {
        const screenshot = await this.captureScreenshot(page);
        log('info', 'checkpoint:detected', {
          action,
          type: checkpoint.checkpointType,
          reason: checkpoint.reason,
        });
        return {
          success: false,
          result: null,
          screenshot,
          needs_approval: true,
          approval_reason: checkpoint.reason,
          checkpoint_type: checkpoint.checkpointType ?? undefined,
        };
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      log('warn', 'checkpoint:detection_failed', { action, error: message });
      // Proceed — detector failure is not a safety block
    }

    // Step 3: Dispatch to action handler
    const dispatch: Record<
      BrowserAction,
      (p: Page, pr: Record<string, any>) => Promise<ActionResult>
    > = {
      navigate: (p, pr) => this.navigate(p, pr),
      search: (p, pr) => this.search(p, pr),
      fill_form: (p, pr) => this.fillForm(p, pr),
      click: (p, pr) => this.click(p, pr),
      extract_data: (p, pr) => this.extractData(p, pr),
      take_screenshot: (p, pr) => this.takeScreenshot(p, pr),
      get_page_content: (p, pr) => this.getPageContent(p, pr),
      wait_for_selector: (p, pr) => this.waitForSelector(p, pr),
      scroll: (p, pr) => this.scroll(p, pr),
      snapshot: (p, pr) =>
        snapshotAction(p, pr, (pg) => this.captureScreenshot(pg)),
      click_ref: (p, pr) =>
        clickRefAction(p, pr, (pg) => this.captureScreenshot(pg)),
      type_ref: (p, pr) =>
        typeRefAction(p, pr, (pg) => this.captureScreenshot(pg)),
      select_ref: (p, pr) =>
        selectRefAction(p, pr, (pg) => this.captureScreenshot(pg)),
    };

    const handler = dispatch[action as BrowserAction];
    if (!handler) {
      const screenshot = await this.captureScreenshot(page);
      return {
        success: false,
        result: null,
        screenshot,
        error: `Unknown browser action: "${action}". Valid actions: ${Object.keys(dispatch).join(', ')}`,
      };
    }

    log('info', `action:${action}:start`, { sessionId, params });
    const startMs = Date.now();

    try {
      const result = await handler(page, params);

      const durationMs = Date.now() - startMs;
      log(result.success ? 'info' : 'warn', `action:${action}:end`, {
        sessionId,
        success: result.success,
        durationMs,
        ...(result.error ? { error: result.error } : {}),
      });

      return result;
    } catch (err) {
      const durationMs = Date.now() - startMs;
      const message = err instanceof Error ? err.message : String(err);
      log('error', `action:${action}:end`, {
        sessionId,
        success: false,
        durationMs,
        error: message,
      });

      const screenshot = await this.captureScreenshot(page);
      return {
        success: false,
        result: null,
        screenshot,
        error: message,
      };
    }
  }

  // ----------------------------------------------------------
  // ACTION: navigate
  // ----------------------------------------------------------

  private async navigate(
    page: Page,
    params: Record<string, any>,
  ): Promise<ActionResult> {
    const url = (params.url as string | undefined)?.trim();
    if (!url) {
      const screenshot = await this.captureScreenshot(page);
      return {
        success: false,
        result: null,
        screenshot,
        error: 'Missing required parameter: url',
      };
    }

    // SSRF check (defense-in-depth — Python layer is primary)
    const ssrfResult = await checkSSRF(url);
    if (!ssrfResult.allowed) {
      const screenshot = await this.captureScreenshot(page);
      return {
        success: false,
        result: null,
        screenshot,
        error: `Blocked: ${ssrfResult.reason}`,
      };
    }

    try {
      await page.goto(url, {
        waitUntil: 'networkidle',
        timeout: NAVIGATE_TIMEOUT,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes('Timeout') || message.includes('timeout')) {
        log('warn', 'action:navigate:networkidle_timeout', { url });
        await page.goto(url, {
          waitUntil: 'domcontentloaded',
          timeout: NAVIGATE_TIMEOUT,
        });
      } else {
        throw err;
      }
    }

    // Post-redirect SSRF check
    const finalUrl = page.url();
    const postRedirectCheck = await checkSSRF(finalUrl);
    if (!postRedirectCheck.allowed) {
      log('warn', 'ssrf:post_redirect_blocked', { originalUrl: url, finalUrl });
      await page.goto('about:blank');
      const screenshot = await this.captureScreenshot(page);
      return {
        success: false,
        result: null,
        screenshot,
        error: `Blocked after redirect: ${postRedirectCheck.reason}`,
      };
    }

    const screenshot = await this.captureScreenshot(page);
    return {
      success: true,
      result: { url: page.url(), title: await page.title() },
      screenshot,
    };
  }

  // ----------------------------------------------------------
  // ACTION: search
  // ----------------------------------------------------------

  private async search(
    page: Page,
    params: Record<string, any>,
  ): Promise<ActionResult> {
    const site = (params.site as string | undefined)?.trim();
    const query = (params.query as string | undefined)?.trim();

    if (!site || !query) {
      const screenshot = await this.captureScreenshot(page);
      return {
        success: false,
        result: null,
        screenshot,
        error: 'Missing required parameters: site and query',
      };
    }

    // SSRF check (defense-in-depth)
    const ssrfResult = await checkSSRF(site);
    if (!ssrfResult.allowed) {
      const screenshot = await this.captureScreenshot(page);
      return {
        success: false,
        result: null,
        screenshot,
        error: `Blocked: ${ssrfResult.reason}`,
      };
    }

    // Navigate to site
    try {
      await page.goto(site, {
        waitUntil: 'networkidle',
        timeout: NAVIGATE_TIMEOUT,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (message.includes('Timeout') || message.includes('timeout')) {
        log('warn', 'action:search:networkidle_timeout', { site });
        await page.goto(site, {
          waitUntil: 'domcontentloaded',
          timeout: NAVIGATE_TIMEOUT,
        });
      } else {
        throw err;
      }
    }

    // Find search input via strategies
    let searchInput: Locator | null = null;
    for (const strategy of SEARCH_INPUT_STRATEGIES) {
      const locator = page.locator(strategy);
      const count = await locator.count();
      if (count > 0) {
        const first = locator.first();
        try {
          if (await first.isVisible()) {
            searchInput = first;
            break;
          }
        } catch {
          // Element became stale, try next strategy
        }
      }
    }

    if (!searchInput) {
      const screenshot = await this.captureScreenshot(page);
      return {
        success: false,
        result: null,
        screenshot,
        error: 'Could not find search input on this page',
      };
    }

    // Fill and submit search
    await searchInput.fill('');
    await searchInput.fill(query);
    await searchInput.press('Enter');
    await page.waitForLoadState('domcontentloaded').catch(() => {});
    await page.waitForTimeout(POST_ACTION_WAIT);

    // Extract results
    const results = await page.evaluate((maxResults: number) => {
      const links = Array.from(document.querySelectorAll('a[href]'));
      return links
        .filter((a) => {
          const href = a.getAttribute('href') || '';
          if (!href.startsWith('http')) return false;
          if (href.includes('javascript:')) return false;
          const text = (a.textContent || '').trim();
          return text.length > 0;
        })
        .slice(0, maxResults)
        .map((a) => ({
          title: (a.textContent || '').trim().slice(0, 200),
          url: a.getAttribute('href') || '',
        }));
    }, MAX_SEARCH_RESULTS);

    const screenshot = await this.captureScreenshot(page);
    return {
      success: true,
      result: {
        query,
        site,
        resultsCount: results.length,
        results,
      },
      screenshot,
    };
  }

  // ----------------------------------------------------------
  // ACTION: fill_form
  // ----------------------------------------------------------

  private async fillForm(
    page: Page,
    params: Record<string, any>,
  ): Promise<ActionResult> {
    const fields = params.fields as
      | Array<{ selector: string; value: string }>
      | undefined;

    if (!fields || !Array.isArray(fields) || fields.length === 0) {
      const screenshot = await this.captureScreenshot(page);
      return {
        success: false,
        result: null,
        screenshot,
        error: 'Missing or empty required parameter: fields',
      };
    }

    const details: Array<{
      selector: string;
      status: 'filled' | 'error';
      error?: string;
    }> = [];
    let filledCount = 0;

    for (const field of fields) {
      try {
        const locator = page.locator(field.selector);
        if ((await locator.count()) === 0) {
          details.push({
            selector: field.selector,
            status: 'error',
            error: 'Element not found',
          });
          continue;
        }

        const first = locator.first();
        const info = await first.evaluate((el) => ({
          tag: el.tagName.toLowerCase(),
          type: (el.getAttribute('type') || '').toLowerCase(),
        }));

        if (info.tag === 'select') {
          await first.selectOption(field.value);
        } else if (info.type === 'checkbox') {
          await first.setChecked(
            field.value === 'true' || field.value === 'on',
          );
        } else if (info.type === 'radio') {
          await first.setChecked(true);
        } else if (info.type === 'file') {
          await first.setInputFiles(field.value);
        } else {
          await first.fill(field.value);
        }

        filledCount++;
        details.push({ selector: field.selector, status: 'filled' });
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        details.push({
          selector: field.selector,
          status: 'error',
          error: message,
        });
      }
    }

    // NEVER submit the form — only fill fields

    const screenshot = await this.captureScreenshot(page);
    return {
      success: filledCount > 0,
      result: { filledCount, totalFields: fields.length, details },
      screenshot,
      ...(filledCount === 0 ? { error: 'Failed to fill any form fields' } : {}),
    };
  }

  // ----------------------------------------------------------
  // ACTION: click
  // ----------------------------------------------------------

  private async click(
    page: Page,
    params: Record<string, any>,
  ): Promise<ActionResult> {
    const selectorOrText = (
      params.selector_or_text as string | undefined
    )?.trim();

    if (!selectorOrText) {
      const screenshot = await this.captureScreenshot(page);
      return {
        success: false,
        result: null,
        screenshot,
        error: 'Missing required parameter: selector_or_text',
      };
    }

    const element = await this.findElement(page, selectorOrText);
    if (!element) {
      const screenshot = await this.captureScreenshot(page);
      return {
        success: false,
        result: null,
        screenshot,
        error: `Could not find element matching: "${selectorOrText}"`,
      };
    }

    await element.click({ timeout: CLICK_TIMEOUT });
    await page.waitForLoadState('domcontentloaded').catch(() => {});

    const screenshot = await this.captureScreenshot(page);
    return {
      success: true,
      result: {
        clicked: true,
        selector: selectorOrText,
        currentUrl: page.url(),
        title: await page.title(),
      },
      screenshot,
    };
  }

  // ----------------------------------------------------------
  // ACTION: extract_data
  // ----------------------------------------------------------

  private async extractData(
    page: Page,
    params: Record<string, any>,
  ): Promise<ActionResult> {
    const selectors = params.selectors as
      | Array<{ name: string; selector: string }>
      | undefined;

    if (!selectors || !Array.isArray(selectors) || selectors.length === 0) {
      const screenshot = await this.captureScreenshot(page);
      return {
        success: false,
        result: null,
        screenshot,
        error: 'Missing or empty required parameter: selectors',
      };
    }

    const extracted: Record<string, string | string[] | null> = {};

    for (const { name, selector } of selectors) {
      try {
        const locator = page.locator(selector);
        const count = await locator.count();

        if (count === 0) {
          extracted[name] = null;
        } else if (count === 1) {
          extracted[name] = (await locator.innerText()).trim();
        } else {
          const texts = await locator.allInnerTexts();
          extracted[name] = texts.map((t) => t.trim());
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        extracted[name] = null;
        log('warn', 'action:extract_data:field_error', {
          name,
          selector,
          error: message,
        });
      }
    }

    const fieldsFound = Object.values(extracted).filter(
      (v) => v !== null,
    ).length;

    const screenshot = await this.captureScreenshot(page);
    return {
      success: true,
      result: {
        extracted,
        fieldsRequested: selectors.length,
        fieldsFound,
      },
      screenshot,
    };
  }

  // ----------------------------------------------------------
  // ACTION: take_screenshot
  // ----------------------------------------------------------

  private async takeScreenshot(
    page: Page,
    _params: Record<string, any>,
  ): Promise<ActionResult> {
    const buffer = await page.screenshot({ type: 'png', fullPage: true });
    const base64 = buffer.toString('base64');

    return {
      success: true,
      result: {
        format: 'png',
        fullPage: true,
        sizeBytes: buffer.length,
      },
      screenshot: base64,
    };
  }

  // ----------------------------------------------------------
  // ACTION: get_page_content
  // ----------------------------------------------------------

  private async getPageContent(
    page: Page,
    _params: Record<string, any>,
  ): Promise<ActionResult> {
    const [rawText, title, url, description] = await Promise.all([
      page.evaluate(() => document.body?.innerText ?? ''),
      page.title(),
      Promise.resolve(page.url()),
      page.evaluate(() => {
        const meta = document.querySelector('meta[name="description"]');
        return meta ? (meta.getAttribute('content') ?? '') : '';
      }),
    ]);

    const content = this.truncate(rawText);
    const truncated = rawText.length > MAX_CONTENT_LENGTH;

    const screenshot = await this.captureScreenshot(page);
    return {
      success: true,
      result: {
        url,
        title,
        description,
        content,
        contentLength: rawText.length,
        truncated,
      },
      screenshot,
    };
  }

  // ----------------------------------------------------------
  // ACTION: wait_for_selector
  // ----------------------------------------------------------

  private async waitForSelector(
    page: Page,
    params: Record<string, any>,
  ): Promise<ActionResult> {
    const selector = (params.selector as string | undefined)?.trim();
    if (!selector) {
      const screenshot = await this.captureScreenshot(page);
      return {
        success: false,
        result: null,
        screenshot,
        error: 'Missing required parameter: selector',
      };
    }

    const timeout = Math.min(
      Math.max(Number(params.timeout) || 10_000, 1_000),
      30_000,
    );

    try {
      await page.waitForSelector(selector, {
        state: 'visible',
        timeout,
      });
    } catch {
      const screenshot = await this.captureScreenshot(page);
      return {
        success: false,
        result: null,
        screenshot,
        error: `Selector "${selector}" did not appear within ${timeout}ms`,
      };
    }

    const elementText = await page
      .locator(selector)
      .first()
      .innerText()
      .catch(() => '');

    const screenshot = await this.captureScreenshot(page);
    return {
      success: true,
      result: {
        selector,
        found: true,
        preview: this.truncate(elementText, 500),
      },
      screenshot,
    };
  }

  // ----------------------------------------------------------
  // ACTION: scroll
  // ----------------------------------------------------------

  private async scroll(
    page: Page,
    params: Record<string, any>,
  ): Promise<ActionResult> {
    const direction = (params.direction as string) || 'down';
    const amount = Math.min(Math.max(Number(params.amount) || 800, 100), 5000);
    const selector = (params.selector as string | undefined)?.trim();

    if (selector) {
      try {
        const locator = page.locator(selector).first();
        await locator.scrollIntoViewIfNeeded({ timeout: 10_000 });
      } catch {
        const screenshot = await this.captureScreenshot(page);
        return {
          success: false,
          result: null,
          screenshot,
          error: `Could not scroll to element: "${selector}"`,
        };
      }
    } else {
      const delta = direction === 'up' ? -amount : amount;
      await page.evaluate((d: number) => window.scrollBy(0, d), delta);
    }

    await page.waitForTimeout(POST_ACTION_WAIT);

    const screenshot = await this.captureScreenshot(page);
    return {
      success: true,
      result: {
        direction,
        amount,
        ...(selector ? { scrolledTo: selector } : {}),
      },
      screenshot,
    };
  }

  // ----------------------------------------------------------
  // HELPERS
  // ----------------------------------------------------------

  private async findElement(
    page: Page,
    selectorOrText: string,
  ): Promise<Locator | null> {
    // Strategy 1: CSS selector
    try {
      const cssLocator = page.locator(selectorOrText);
      if ((await cssLocator.count()) > 0) {
        return cssLocator.first();
      }
    } catch {
      // Invalid CSS selector — fall through to text strategies
    }

    // Strategy 2: Text match (partial, case-insensitive)
    try {
      const textLocator = page.getByText(selectorOrText, { exact: false });
      if ((await textLocator.count()) > 0) {
        return textLocator.first();
      }
    } catch {
      // Fall through
    }

    // Strategy 3: Button by accessible name
    try {
      const buttonLocator = page.getByRole('button', {
        name: selectorOrText,
      });
      if ((await buttonLocator.count()) > 0) {
        return buttonLocator.first();
      }
    } catch {
      // Fall through
    }

    // Strategy 4: Link by accessible name
    try {
      const linkLocator = page.getByRole('link', { name: selectorOrText });
      if ((await linkLocator.count()) > 0) {
        return linkLocator.first();
      }
    } catch {
      // Fall through
    }

    return null;
  }

  private async captureScreenshot(page: Page): Promise<string | undefined> {
    try {
      const buffer = await page.screenshot({ type: 'png', fullPage: true });
      return buffer.toString('base64');
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      log('warn', 'screenshot:capture_failed', { error: message });
      return undefined;
    }
  }

  private truncate(
    text: string,
    maxLength: number = MAX_CONTENT_LENGTH,
  ): string {
    if (text.length <= maxLength) {
      return text;
    }
    return (
      text.slice(0, maxLength) + `\n... [truncated, ${text.length} total chars]`
    );
  }
}
