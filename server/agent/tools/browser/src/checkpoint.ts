import type { Page } from 'playwright';

// ── Types ────────────────────────────────────────────────────────────

export interface CheckpointResult {
  needsApproval: boolean;
  reason: string;
  checkpointType: 'payment' | 'form_submit' | 'captcha' | '2fa' | null;
}

// ── Constants ────────────────────────────────────────────────────────

const PAYMENT_URL_PATTERNS = [
  /\/checkout\//i,
  /\/payment\//i,
  /\/billing\//i,
  /\/purchase\//i,
  /\/order\/confirm/i,
];

const SUBMIT_TEXT_PATTERN =
  /submit|confirm|send|place.?order|complete|pay|purchase|book.?now|checkout|sign.?up|register|apply/i;

// ── Logging ──────────────────────────────────────────────────────────

function log(
  level: 'info' | 'warn' | 'error',
  event: string,
  data?: Record<string, unknown>,
): void {
  console.log(
    JSON.stringify({ level, event, data, timestamp: new Date().toISOString() }),
  );
}

// ── CheckpointDetector ───────────────────────────────────────────────

export class CheckpointDetector {
  async detect(
    page: Page,
    action: string,
    params: Record<string, unknown>,
  ): Promise<CheckpointResult> {
    try {
      // Run checks in order, return first match
      const paymentResult = await this.checkPaymentPage(page);
      if (paymentResult) return paymentResult;

      const formResult = await this.checkFormSubmission(page, action, params);
      if (formResult) return formResult;

      const captchaResult = await this.checkCaptcha(page);
      if (captchaResult) return captchaResult;

      const twoFAResult = await this.check2FA(page);
      if (twoFAResult) return twoFAResult;

      return { needsApproval: false, reason: '', checkpointType: null };
    } catch (error) {
      log('warn', 'checkpoint:detect_error', { error: String(error) });
      return {
        needsApproval: true,
        reason: `Checkpoint detection failed — approval required as safety fallback`,
        checkpointType: null,
      };
    }
  }

  private async checkPaymentPage(page: Page): Promise<CheckpointResult | null> {
    const url = page.url().toLowerCase();

    const urlMatch = PAYMENT_URL_PATTERNS.some((pattern) => pattern.test(url));

    const hasCardFields = await page.evaluate(() => {
      try {
        return !!document.querySelector(
          [
            'input[autocomplete*="cc-"]',
            'input[name*="card"]',
            'input[name*="credit"]',
            'input[data-stripe]',
            '[class*="CardField"]',
            '[class*="card-number"]',
          ].join(', '),
        );
      } catch {
        return false;
      }
    });

    if (urlMatch || hasCardFields) {
      return {
        needsApproval: true,
        reason: 'Payment page detected — approval required before proceeding',
        checkpointType: 'payment',
      };
    }

    return null;
  }

  private async checkFormSubmission(
    page: Page,
    action: string,
    params: Record<string, unknown>,
  ): Promise<CheckpointResult | null> {
    if (action !== 'click') return null;

    const selectorOrText = (params.selector_or_text ??
      params.selector ??
      '') as string;

    // Check if target text matches submission keywords
    if (selectorOrText && SUBMIT_TEXT_PATTERN.test(selectorOrText)) {
      return {
        needsApproval: true,
        reason: `Click on "${selectorOrText}" appears to be a form submission — approval required`,
        checkpointType: 'form_submit',
      };
    }

    // Check if target element is a submit button inside a <form>
    if (selectorOrText) {
      const isFormSubmit = await page.evaluate((sel: string) => {
        try {
          const el = document.querySelector(sel);
          if (!el) return false;

          const isInsideForm = !!el.closest('form');
          if (!isInsideForm) return false;

          const tag = el.tagName.toUpperCase();
          if (tag === 'INPUT' && (el as HTMLInputElement).type === 'submit')
            return true;
          if (
            tag === 'BUTTON' &&
            ((el as HTMLButtonElement).type === 'submit' ||
              !(el as HTMLButtonElement).hasAttribute('type'))
          )
            return true;

          return false;
        } catch {
          return false;
        }
      }, selectorOrText);

      if (isFormSubmit) {
        return {
          needsApproval: true,
          reason: `Click on "${selectorOrText}" is a form submit button — approval required`,
          checkpointType: 'form_submit',
        };
      }
    }

    return null;
  }

  private async checkCaptcha(page: Page): Promise<CheckpointResult | null> {
    const hasCaptcha = await page.evaluate(() => {
      try {
        return !!document.querySelector(
          [
            'iframe[src*="recaptcha"]',
            'iframe[src*="captcha"]',
            'iframe[src*="hcaptcha"]',
            'div.g-recaptcha',
            'div[class*="captcha"]',
            '[data-sitekey]',
            'iframe[title*="challenge"]',
            'div[id*="captcha"]',
          ].join(', '),
        );
      } catch {
        return false;
      }
    });

    if (hasCaptcha) {
      return {
        needsApproval: true,
        reason: 'CAPTCHA detected — manual intervention or approval required',
        checkpointType: 'captcha',
      };
    }

    return null;
  }

  private async check2FA(page: Page): Promise<CheckpointResult | null> {
    const has2FA = await page.evaluate(() => {
      try {
        // Check for OTP/verification inputs by attributes
        const otpInputs = document.querySelector(
          [
            'input[autocomplete="one-time-code"]',
            'input[name*="otp"]',
            'input[name*="2fa"]',
            'input[name*="mfa"]',
            'input[name*="verification"]',
            'input[name*="verify"]',
            'input[name*="token"]',
          ].join(', '),
        );
        if (otpInputs) return true;

        // Check for text content indicating 2FA
        const bodyText = document.body?.innerText?.toLowerCase() ?? '';
        const twoFAKeywords = [
          'two-factor',
          '2-step',
          'verification code',
          'authenticator',
          'enter the code',
        ];
        if (twoFAKeywords.some((kw) => bodyText.includes(kw))) return true;

        // Check for multiple single-digit input fields (common OTP pattern)
        const singleCharInputs = Array.from(
          document.querySelectorAll('input'),
        ).filter((input) => input.maxLength === 1 || input.size === 1);
        if (singleCharInputs.length >= 4 && singleCharInputs.length <= 8)
          return true;

        return false;
      } catch {
        return false;
      }
    });

    if (has2FA) {
      return {
        needsApproval: true,
        reason: '2FA/MFA verification detected — approval required',
        checkpointType: '2fa',
      };
    }

    return null;
  }
}
