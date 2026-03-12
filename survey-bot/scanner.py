"""
scanner.py — Survey DOM scanner.

Opens a visible Chrome window (NOT headless — SurveyMonkey blocks headless),
waits for the React SPA to finish rendering, then uses execute_script() to
extract question metadata directly from the live DOM.

Why not BeautifulSoup on page_source?
  SurveyMonkey is a React SPA — questions are injected by JS after page load.
  driver.page_source only returns the pre-JS HTML skeleton, which has no
  question elements. We must query the live DOM via JavaScript instead.
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

DATA_DIR = Path(__file__).parent / "data"
CONFIGS_DIR = DATA_DIR / "configs"

# JavaScript injected into the live page to extract question data from the DOM.
_JS_EXTRACT = """
return (function() {
  const results = [];

  // Try selector groups in priority order; pick first that returns elements.
  // Classic SurveyMonkey uses <fieldset> and div.survey-question.
  // Modern SurveyJS uses div[class*="sv_q"] etc.
  const selectorGroups = [
    'fieldset',
    'div.survey-question',
    'div[class*="sv_q"]:not([class*="sv_q_"])',
    'div[class*="sv-question"]',
    'li[class*="sv_q"]',
    'div[data-question-pk]',
    'div[data-scrollid]',
    'div[role="group"]',
  ];

  let containers = [];
  let usedSelector = '';

  for (const sel of selectorGroups) {
    const found = document.querySelectorAll(sel);
    if (found.length > 0) {
      containers = Array.from(found);
      usedSelector = sel;
      break;
    }
  }

  // Final fallback: div[id^="question"], filter to top-level only
  if (containers.length === 0) {
    const allQDivs = document.querySelectorAll('div[id^="question"]');
    containers = Array.from(allQDivs).filter(el => {
      const parent = el.parentElement;
      return !parent || !parent.id || !parent.id.startsWith('question');
    });
    usedSelector = 'div[id^="question"] (filtered)';
  }

  if (containers.length === 0) return [];

  containers.forEach((container, idx) => {
    // === Extract question text ===
    let qText = '';

    // For fieldset: legend is the canonical title element
    const legend = container.querySelector('legend');
    if (legend) {
      qText = legend.textContent.trim().substring(0, 300);
    }

    if (!qText) {
      const titleSelectors = [
        '[class*="question-title"]', '[class*="sv_q_title"]',
        '[class*="sv-question__title"]', 'h5', 'h4', 'h3',
        '[class*="question-header"]', 'label[class*="title"]',
        'p.question-text', 'div.question-body > p:first-child',
      ];
      for (const sel of titleSelectors) {
        const el = container.querySelector(sel);
        if (el && el.textContent.trim()) {
          qText = el.textContent.trim().substring(0, 300);
          break;
        }
      }
    }

    if (!qText) {
      qText = (container.textContent || '').trim().substring(0, 150);
    }

    // === Detect question type ===
    const radios = container.querySelectorAll('input[type="radio"]');
    const selects = container.querySelectorAll('select');
    const textInputs = container.querySelectorAll(
      'input[type="text"], input[type="email"], input[type="tel"], input[type="number"], textarea'
    );

    let questionType = null;
    let options = [];
    let fields = [];

    if (radios.length > 0) {
      questionType = 'radio';
      radios.forEach((radio, i) => {
        let label = '';

        // Method 1: radio inside a <label>
        const parentLabel = radio.closest('label');
        if (parentLabel) {
          const clone = parentLabel.cloneNode(true);
          clone.querySelectorAll('input').forEach(el => el.remove());
          label = clone.textContent.trim();
        }

        // Method 2: <label for="radio_id">
        if (!label && radio.id) {
          const labelEl = document.querySelector('label[for="' + radio.id + '"]');
          if (labelEl) label = labelEl.textContent.trim();
        }

        // Method 3: next element sibling
        if (!label && radio.nextElementSibling) {
          label = radio.nextElementSibling.textContent.trim();
        }

        // Method 4: next text node
        if (!label && radio.nextSibling && radio.nextSibling.nodeType === 3) {
          label = radio.nextSibling.textContent.trim();
        }

        options.push({
          index: i,
          value: radio.value || String(i),
          label: label || ('Option ' + i)
        });
      });

    } else if (selects.length > 0) {
      questionType = 'dropdown';
      const sel = selects[0];
      let optIdx = 0;
      Array.from(sel.options).forEach((opt) => {
        if (!opt.value || opt.value === '' || opt.value === '--' || opt.value === '0') {
          optIdx++;
          return;
        }
        options.push({ index: optIdx, value: opt.value, label: opt.text.trim() });
        optIdx++;
      });

    } else if (textInputs.length > 1) {
      questionType = 'text_group';
      textInputs.forEach(inp => {
        const ph = inp.placeholder || '';
        const t = inp.type || 'text';
        const nameAttr = (inp.name || '').toLowerCase();
        let key = 'name';
        if (t === 'email' || ph.toLowerCase().includes('mail') || nameAttr.includes('mail')) {
          key = 'email';
        } else if (t === 'tel' || ph.toLowerCase().includes('phone') ||
                   ph.toLowerCase().includes('tel') || nameAttr.includes('phone')) {
          key = 'phone';
        }
        fields.push({ field_key: key, placeholder: ph });
      });

    } else if (textInputs.length === 1) {
      questionType = 'text';
      fields.push({ field_key: 'text', placeholder: textInputs[0].placeholder || '' });
    }

    if (!questionType) return;

    // === Required flag ===
    const required =
      container.getAttribute('aria-required') === 'true' ||
      container.classList.contains('required') ||
      !!container.querySelector('[aria-required="true"], .required, [required]') ||
      qText.includes('*') ||
      qText.includes('\u5fc5\u9808') ||
      qText.includes('\uff08\u5fc5\u9808\uff09');

    results.push({
      question_index: idx + 1,
      question_text: qText,
      question_type: questionType,
      required: required,
      options: options,
      fields: fields
    });
  });

  return results;
})();
"""


def _url_slug(url: str) -> str:
    """Convert a URL to a safe filename slug."""
    parsed = urlparse(url)
    slug = (parsed.netloc + parsed.path).strip("/").replace("/", "_")
    slug = re.sub(r"[^a-zA-Z0-9_\-]", "", slug)
    return slug or "survey"


class SurveyScanner:
    """Scan a SurveyMonkey survey URL and return structured question metadata."""

    # Selectors used to detect when the SPA has finished rendering.
    # Classic SurveyMonkey skin uses fieldset / div[id^="question"] — listed first.
    _WAIT_SELECTORS = [
        'fieldset',
        'div[id^="question"]',
        'div.survey-question',
        'div[class*="sv_q"]',
        'div[class*="sv-question"]',
        'div[class*="smSurvey"]',
        'input[type="radio"]',
        'select',
    ]

    def scan(self, url: str) -> dict:
        """
        Open *url* in a visible Chrome window, wait for JS rendering to complete,
        extract question data from the live DOM via execute_script(), save the
        result to data/configs/{slug}_scan.json, and return the result dict.
        """
        CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
        slug = _url_slug(url)
        print(f"[SCAN] Starting scan for URL: {url}", flush=True)

        driver = self._make_driver()
        try:
            print(f"[SCAN] Navigating to URL...", flush=True)
            driver.get(url)

            wait = WebDriverWait(driver, 30)

            # Wait for ANY recognised question selector to appear
            detected = False
            for selector in self._WAIT_SELECTORS:
                try:
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                    print(f"[SCAN] Page ready — matched selector: {selector}", flush=True)
                    detected = True
                    break
                except TimeoutException:
                    print(f"[SCAN] Selector not found within timeout: {selector}", flush=True)

            if not detected:
                print(f"[SCAN] WARNING: No selector matched within 30s. Continuing anyway.", flush=True)

            # Extra settle time for React re-renders
            time.sleep(3)

            # Debug: log page title and URL
            print(f"[SCAN] Page title: {driver.title!r}", flush=True)
            print(f"[SCAN] Current URL: {driver.current_url}", flush=True)

            # Probe each selector with live Selenium counts
            for selector in self._WAIT_SELECTORS:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                print(f"[SCAN] Trying selector: {selector!r} → found {len(elements)} elements", flush=True)

            # Log per-selector DOM counts for diagnostics
            debug_counts = driver.execute_script("""
                const sels = ['fieldset', 'div.survey-question', 'div[class*="sv_q"]',
                              'div[class*="sv-question"]', 'div[id^="question"]',
                              'input[type="radio"]', 'select'];
                const result = {};
                sels.forEach(s => { result[s] = document.querySelectorAll(s).length; });
                return result;
            """)
            for sel, count in debug_counts.items():
                print(f"[SCAN] DOM count \u2014 {sel!r}: {count}", flush=True)

            # Extract questions from the live DOM via JavaScript
            print(f"[SCAN] Running JS extraction...", flush=True)
            questions = driver.execute_script(_JS_EXTRACT) or []
            print(f"[SCAN] JS extraction returned {len(questions)} questions", flush=True)

            if not questions:
                print(f"[SCAN] WARNING: JS extraction returned 0 questions. Saving debug HTML.", flush=True)
                debug_html_path = CONFIGS_DIR / f"{slug}_debug.html"
                debug_html_path.write_text(driver.page_source, encoding="utf-8")
                print(f"[SCAN] Debug HTML saved to: {debug_html_path}", flush=True)
                raise RuntimeError(
                    f"Scanner found 0 questions. Check debug HTML at data/configs/{slug}_debug.html"
                )

        finally:
            driver.quit()
            print(f"[SCAN] Driver closed.", flush=True)

        result = {
            "url": url,
            "scanned_at": datetime.utcnow().isoformat(),
            "total_questions": len(questions),
            "questions": questions,
        }

        out_path = CONFIGS_DIR / f"{slug}_scan.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[SCAN] Result saved to: {out_path}", flush=True)

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _make_driver(self) -> uc.Chrome:
        """
        Create a visible (non-headless) Chrome instance.
        SurveyMonkey actively detects and blocks headless User-Agents.
        Use Xvfb on headless Linux servers instead of --headless.
        """
        opts = uc.ChromeOptions()
        # DO NOT add --headless — SurveyMonkey blocks headless Chrome
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--window-size=1280,900")
        opts.add_argument(
            "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        return uc.Chrome(options=opts)
