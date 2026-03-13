"""
bot.py — Survey automation engine.

Uses undetected-chromedriver to fill SurveyMonkey forms based on a config dict.
Persona data comes exclusively from CSVManager; Faker is NOT used here.

DOM selectors for SurveyMonkey (jp.surveymonkey.com):
  - Question containers:   div[data-question-pk] or div.survey-question-container
  - Radio inputs:          input[type="radio"] inside the question container
  - Dropdown selects:      select inside the question container
  - Text inputs:           input[type="text"], input[type="email"], input[type="tel"]
  - Submit button:         input[type="submit"], button[type="submit"],
                           or button/input containing text 完了 / Submit / Next
"""

import json
import random
import time
import threading
import traceback
from datetime import datetime
from pathlib import Path

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
    WebDriverException,
)

DATA_DIR = Path(__file__).parent / "data"
RUN_LOG = DATA_DIR / "run_log.jsonl"

# ---------------------------------------------------------------------------
# Job reference — set by app.py so the bot can update waiting state
# ---------------------------------------------------------------------------
_job_ref = None


def set_job_ref(job_dict: dict):
    global _job_ref
    _job_ref = job_dict


def _get_job_ref():
    return _job_ref


def _log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _append_log(result: dict):
    """Append a single run result dict as one JSON line to run_log.jsonl."""
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


def _make_driver() -> uc.Chrome:
    """Create a Chrome instance with anti-detection options in incognito mode."""
    opts = uc.ChromeOptions()
    opts.add_argument("--incognito")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,800")
    return uc.Chrome(options=opts)


def _find_question_container(driver, wait: WebDriverWait, question_index: int):
    """
    Find the nth question container (1-based) using the same selector priority
    as the scanner JS. Classic SurveyMonkey skin (fieldset) is listed first.
    Falls back to execute_script() if Selenium selectors fail.
    """
    selectors = [
        'fieldset',
        'div.survey-question',
        'div[class*="sv_q"]:not([class*="sv_q_"])',
        'div[class*="sv-question"]',
        'li[class*="sv_q"]',
        'div[data-question-pk]',
        'div[data-scrollid]',
    ]

    for selector in selectors:
        try:
            elements = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((By.CSS_SELECTOR, selector))
            )
            if elements and question_index - 1 < len(elements):
                _log(f"[BOT] Q{question_index} container via: {selector} ({len(elements)} total)")
                return elements[question_index - 1]
        except TimeoutException:
            continue

    # JS fallback with same priority
    _log(f"[BOT] Q{question_index}: Selenium selectors failed, trying JS fallback")
    container = driver.execute_script("""
        const sels = ['fieldset', 'div.survey-question',
                      'div[class*="sv_q"]', 'div[class*="sv-question"]',
                      'div[data-question-pk]'];
        const idx = arguments[0] - 1;
        for (const sel of sels) {
            const els = document.querySelectorAll(sel);
            if (els.length > idx) return els[idx];
        }
        return null;
    """, question_index)

    if container:
        return container

    raise RuntimeError(f"Cannot find container for question index {question_index}")


def _click_radio(driver, container, option_index: int):
    """
    Find all radio inputs inside a question container and click by 0-based index.
    Falls back to execute_script click when SurveyMonkey intercepts the event.
    """
    for attempt in range(2):
        try:
            radios = container.find_elements(By.CSS_SELECTOR, 'input[type="radio"]')
            if option_index >= len(radios):
                raise IndexError(
                    f"Radio index {option_index} out of range (found {len(radios)})"
                )
            try:
                radios[option_index].click()
            except Exception:
                # SurveyMonkey sometimes intercepts native clicks — use JS
                driver.execute_script("arguments[0].click();", radios[option_index])
            return
        except StaleElementReferenceException:
            if attempt == 1:
                raise
            time.sleep(0.3)


def _select_dropdown(driver, container, option_index: int):
    """Select a <select> option by 0-based index inside a question container.
    Falls back to JS dispatchEvent when Select() fails (React controlled inputs).
    """
    select_el = container.find_element(By.CSS_SELECTOR, "select")
    try:
        Select(select_el).select_by_index(option_index)
    except Exception:
        # React-controlled <select> may need a programmatic change event
        driver.execute_script(
            "arguments[0].selectedIndex = arguments[1]; "
            "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
            select_el,
            option_index,
        )


def _fill_text_group(container, persona: dict):
    """
    Fill text/email/tel inputs inside a text_group question.

    SurveyMonkey groups name, email, phone inside one question block.
    We locate inputs in DOM order and map them to persona fields:
      inputs[0] → name, inputs[1] → email, inputs[2] → phone
    """
    inputs = container.find_elements(
        By.CSS_SELECTOR, 'input[type="text"], input[type="email"], input[type="tel"]'
    )
    field_values = [
        persona.get("name", ""),
        persona.get("email", ""),
        persona.get("phone", ""),
    ]
    for i, inp in enumerate(inputs):
        if i >= len(field_values):
            break
        inp.clear()
        inp.send_keys(field_values[i])
        time.sleep(random.uniform(0.2, 0.5))  # tiny intra-field delay


def _wait_for_page_ready(driver, wait: WebDriverWait):
    """
    Wait for SurveyMonkey page to finish rendering.
    Uses EC.any_of() to check ALL selectors simultaneously — 
    returns as soon as ANY one matches, no wasted sequential timeouts.
    """
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By

    # Check all selectors in parallel — return on first match
    try:
        WebDriverWait(driver, 20).until(
            EC.any_of(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'fieldset')),
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="radio"]')),
                EC.presence_of_element_located((By.CSS_SELECTOR, 'select')),
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[class*="sv_q"]')),
                EC.presence_of_element_located((By.CSS_SELECTOR, 'div[class*="sv-question"]')),
            )
        )
        _log("[BOT] Page ready.")
    except TimeoutException:
        _log("[BOT] WARNING: Page ready timeout after 20s. Proceeding anyway.")

    # Extra settle time for any JS re-renders after initial render
    time.sleep(2)


def _click_submit(driver, wait: WebDriverWait):
    """
    Click the survey submission button.

    SurveyMonkey uses different submit elements depending on survey page:
      • input[type="submit"]
      • button[type="submit"]
      • button containing text 完了, Submit, Next, 次へ
    """
    # Try native submit input/button first
    for selector in (
        'input[type="submit"]',
        'button[type="submit"]',
    ):
        try:
            btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
            btn.click()
            return
        except TimeoutException:
            pass

    # Fall back to text-matching for common button labels
    for text in ("完了", "Submit", "Next", "次へ", "送信"):
        try:
            btn = driver.find_element(
                By.XPATH,
                f'//*[self::button or self::input]'
                f'[contains(translate(text(),"abcdefghijklmnopqrstuvwxyz","ABCDEFGHIJKLMNOPQRSTUVWXYZ"), '
                f'"{text.upper()}") or @value="{text}"]',
            )
            btn.click()
            return
        except NoSuchElementException:
            pass

    raise RuntimeError("Submit button not found")


# ---------------------------------------------------------------------------
# SurveyBot
# ---------------------------------------------------------------------------

class SurveyBot:
    """
    Run a survey config N times, drawing persona rows from CSVManager.

    Parameters
    ----------
    config       : dict   — validated config from ConfigManager
    csv_manager  : CSVManager instance (already loaded)
    stop_event   : threading.Event — set this to request early stop
    """

    def __init__(self, config: dict, csv_manager, stop_event: threading.Event,
                 pause_for_ip_rotation: bool = False, pause_event=None):
        self.config = config
        self.csv_manager = csv_manager
        self.stop_event = stop_event
        self.pause_for_ip_rotation = pause_for_ip_rotation
        self.pause_event = pause_event  # threading.Event
        self.results: list[dict] = []
        self.current_run: int = 0

    # ------------------------------------------------------------------
    def run_all(self, progress_callback=None):
        """
        Loop num_runs times checking stop_event before each run.
        Between runs sleeps sleep_between_runs seconds (1-second ticks so stop
        is responsive).
        Calls progress_callback(result) after each run when provided.
        """
        num_runs = self.config.get("num_runs", 1)
        sleep_sec = self.config.get("sleep_between_runs", 30)

        for i in range(num_runs):
            if self.stop_event.is_set():
                _log("Stop requested — halting run loop.")
                break

            self.current_run = i + 1
            _log(f"▶ Starting run {self.current_run}/{num_runs}")

            result = self.run_once(i)
            self.results.append(result)
            _append_log(result)

            if progress_callback:
                progress_callback(result)

            if result["status"] == "csv_exhausted":
                _log(f"CSV exhausted at run {i} — stopping.")
                break

            if i < num_runs - 1 and not self.stop_event.is_set():
                if self.pause_for_ip_rotation and self.pause_event:
                    # Signal UI that we are waiting for IP rotation
                    _ref = _get_job_ref()
                    if _ref is not None:
                        _ref["waiting_for_ip_rotation"] = True
                        _ref["waiting_since"] = datetime.utcnow().isoformat()
                    _log(f"⏸ Run {i+1} done. Waiting for user to rotate IP...")
                    self.pause_event.clear()
                    # Block until user clicks Continue, checking stop_event each second
                    while not self.pause_event.is_set():
                        if self.stop_event.is_set():
                            _log("Stop requested during IP rotation pause.")
                            return
                        time.sleep(1)
                    _log(f"▶ IP rotation confirmed. Continuing run {i+2}...")
                    # Short stabilization wait after resume
                    for _ in range(5):
                        if self.stop_event.is_set():
                            break
                        time.sleep(1)
                else:
                    for _ in range(sleep_sec):
                        if self.stop_event.is_set():
                            break
                        time.sleep(1)

        _log("Run loop finished.")

    # ------------------------------------------------------------------
    def run_once(self, run_index: int) -> dict:
        """
        Execute one survey submission.

        Returns a result dict:
        {
          "run_index":    int,
          "status":       "success" | "error" | "csv_exhausted",
          "error_msg":    str | None,
          "duration_sec": float,
          "persona":      dict | None,
          "timestamp":    ISO str,
          "config_name":  str,
        }
        """
        started = time.time()
        timestamp = datetime.utcnow().isoformat()
        config_name = self.config.get("config_name", "unknown")

        # Step 1: Fetch persona — if None, stop immediately (no browser)
        persona = self.csv_manager.get_row(run_index)
        if persona is None:
            return {
                "run_index": run_index,
                "status": "csv_exhausted",
                "error_msg": f"CSV exhausted at run {run_index}",
                "duration_sec": round(time.time() - started, 2),
                "persona": None,
                "timestamp": timestamp,
                "config_name": config_name,
            }

        driver = None
        answers = []
        try:
            # Step 2: Launch browser
            driver = _make_driver()
            wait = WebDriverWait(driver, 15)

            # Step 3: Navigate to survey
            url = self.config["url"]
            driver.get(url)

            # Wait for React SPA to finish rendering before filling questions
            _wait_for_page_ready(driver, wait)

            # Step 4: Fill each question
            answers = []
            for q in self.config.get("questions", []):
                q_idx = q["question_index"]
                q_type = q["question_type"]

                container = _find_question_container(driver, wait, q_idx)

                if q_type == "radio":
                    allowed = q.get("allowed_options", [])
                    if not allowed:
                        _log(f"  Q{q_idx}: no allowed_options, skipping")
                        continue
                    chosen = random.choice(allowed)
                    _click_radio(driver, container, chosen)
                    _log(f"  Q{q_idx} radio → index {chosen}")
                    answers.append({
                        "question_index": q_idx,
                        "question_type": "radio",
                        "chosen_option_index": chosen,
                    })

                elif q_type == "dropdown":
                    allowed = q.get("allowed_options", [])
                    if not allowed:
                        _log(f"  Q{q_idx}: no allowed_options, skipping")
                        continue
                    chosen = random.choice(allowed)
                    _select_dropdown(driver, container, chosen)
                    _log(f"  Q{q_idx} dropdown → index {chosen}")
                    answers.append({
                        "question_index": q_idx,
                        "question_type": "dropdown",
                        "chosen_option_index": chosen,
                    })

                elif q_type in ("text_group", "text"):
                    _fill_text_group(container, persona)
                    _log(f"  Q{q_idx} text_group → filled with persona")
                    answers.append({
                        "question_index": q_idx,
                        "question_type": q_type,
                        "filled": {
                            "name": persona.get("name", ""),
                            "email": persona.get("email", ""),
                            "phone": persona.get("phone", ""),
                        },
                    })

                # Human-like delay between fields
                time.sleep(random.uniform(0.8, 2.0))

            # Step 5: Submit
            _click_submit(driver, WebDriverWait(driver, 10))
            _log(f"  Submitted — waiting for confirmation...")

            # Step 6: Wait up to 5s for page change or thank-you text
            initial_url = driver.current_url
            try:
                WebDriverWait(driver, 5).until(
                    lambda d: d.current_url != initial_url
                    or "thank" in d.page_source.lower()
                    or "ありがとう" in d.page_source
                    or "完了" in d.page_source
                )
            except TimeoutException:
                pass  # Some surveys stay on same URL — treat as success

            duration = round(time.time() - started, 2)
            _log(f"  ✅ Run {run_index} success ({duration}s)")
            return {
                "run_index": run_index,
                "status": "success",
                "error_msg": None,
                "duration_sec": duration,
                "persona": persona,
                "answers": answers,
                "timestamp": timestamp,
                "config_name": config_name,
            }

        except Exception as exc:
            duration = round(time.time() - started, 2)
            err = f"{type(exc).__name__}: {exc}"
            _log(f"  ❌ Run {run_index} error: {err}")
            _log(traceback.format_exc())
            return {
                "run_index": run_index,
                "status": "error",
                "error_msg": err,
                "duration_sec": duration,
                "persona": persona,
                "answers": answers,
                "timestamp": timestamp,
                "config_name": config_name,
            }

        finally:
            if driver:
                try:
                    driver.quit()
                except WebDriverException:
                    pass

