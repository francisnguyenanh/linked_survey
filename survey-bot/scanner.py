"""
scanner.py — Survey DOM scanner.

Opens a SurveyMonkey URL in headless Chrome, waits for questions to render,
then uses BeautifulSoup to extract structured question metadata.

SurveyMonkey-specific DOM notes:
  • Each question lives in a <div class="survey-question ..."> block.
  • The question title is in a <div class="question-header"> or <label>.
  • Radio choices: <input type="radio"> each inside a <label>.
  • Dropdown choices: <select> with <option> children.
  • Text inputs: <input type="text">, <input type="email">, <input type="tel">.
  • Multiple text inputs inside one question block → "text_group".
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import undetected_chromedriver as uc
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

DATA_DIR = Path(__file__).parent / "data"
CONFIGS_DIR = DATA_DIR / "configs"


def _url_slug(url: str) -> str:
    """Convert a URL to a safe filename slug."""
    parsed = urlparse(url)
    slug = (parsed.netloc + parsed.path).strip("/").replace("/", "_")
    slug = re.sub(r"[^a-zA-Z0-9_\-]", "", slug)
    return slug or "survey"


def _extract_text(tag) -> str:
    """Get clean text content from a BeautifulSoup tag."""
    return tag.get_text(separator=" ", strip=True) if tag else ""


class SurveyScanner:
    """Scan a SurveyMonkey survey URL and return structured question metadata."""

    def scan(self, url: str) -> dict:
        """
        Open *url* in headless Chrome, parse all questions with BeautifulSoup,
        save result to data/configs/{slug}_scan.json, and return the result dict.
        """
        CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
        print(f"[SCAN DEBUG] Starting scan for URL: {url}", flush=True)

        driver = self._make_driver()
        try:
            print(f"[SCAN DEBUG] Navigating to URL...", flush=True)
            driver.get(url)
            print(f"[SCAN DEBUG] Page loaded, waiting for question elements...", flush=True)
            
            # Wait until at least one survey question container is present
            wait = WebDriverWait(driver, 20)
            try:
                print(f"[SCAN DEBUG] Waiting for selectors: div.survey-question, div[data-question-pk], div[data-scrollid]", flush=True)
                wait.until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR,
                         "div.survey-question, div[data-question-pk], div[data-scrollid]")
                    )
                )
                print(f"[SCAN DEBUG] Question elements found!", flush=True)
            except TimeoutException:
                # Page loaded but no recognised selector — still try to parse
                print(f"[SCAN DEBUG] TIMEOUT: No recognized selectors found after 20s. Will try to parse anyway.", flush=True)

            page_source = driver.page_source
            print(f"[SCAN DEBUG] Page source retrieved, length: {len(page_source)} bytes", flush=True)
            
            # Debug: Save the raw page source for inspection
            debug_html_path = CONFIGS_DIR / f"{_url_slug(url)}_debug.html"
            debug_html_path.write_text(page_source, encoding="utf-8")
            print(f"[SCAN DEBUG] Raw HTML saved to: {debug_html_path}", flush=True)
        finally:
            driver.quit()
            print(f"[SCAN DEBUG] Driver closed", flush=True)

        soup = BeautifulSoup(page_source, "html.parser")
        print(f"[SCAN DEBUG] BeautifulSoup parsing started...", flush=True)
        questions = self._parse_questions(soup)
        print(f"[SCAN DEBUG] Parsing complete. Found {len(questions)} questions", flush=True)

        result = {
            "url": url,
            "scanned_at": datetime.utcnow().isoformat(),
            "total_questions": len(questions),
            "questions": questions,
        }

        slug = _url_slug(url)
        out_path = CONFIGS_DIR / f"{slug}_scan.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[SCAN DEBUG] Result saved to: {out_path}", flush=True)

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _make_driver(self) -> uc.Chrome:
        opts = uc.ChromeOptions()
        opts.add_argument("--headless=new")   # Chrome 112+ headless
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--window-size=1280,900")
        return uc.Chrome(options=opts)

    def _parse_questions(self, soup: BeautifulSoup) -> list[dict]:
        """
        Find all question containers and dispatch to type-specific parsers.

        SurveyMonkey question containers match one of:
          • div.survey-question          (classic skin)
          • div[data-question-pk]        (modern skin)
          • div[data-scrollid^="page"]   (paged surveys)

        We collect all matching elements, de-duplicate by their HTML position,
        then parse each one.
        """
        # Collect candidate containers (CSS priority order)
        containers = []
        seen_ids = set()
        print(f"[PARSE DEBUG] Starting _parse_questions...", flush=True)

        # Debug: Check body content
        body = soup.find("body")
        print(f"[PARSE DEBUG] Body exists: {body is not None}", flush=True)
        if body:
            print(f"[PARSE DEBUG] Body content length: {len(str(body))} chars", flush=True)

        for selector in (
            "div.survey-question",
            "div[data-question-pk]",
            "div[data-scrollid]",
        ):
            found_by_selector = soup.select(selector)
            print(f"[PARSE DEBUG] Selector '{selector}': found {len(found_by_selector)} elements", flush=True)
            if found_by_selector and len(found_by_selector) > 0:
                print(f"[PARSE DEBUG]   First element: {str(found_by_selector[0])[:200]}", flush=True)
            for tag in found_by_selector:
                uid = id(tag)
                if uid not in seen_ids:
                    seen_ids.add(uid)
                    containers.append(tag)
        
        print(f"[PARSE DEBUG] Total unique containers after deduplication: {len(containers)}", flush=True)

        questions = []
        for idx, container in enumerate(containers, start=1):
            print(f"[PARSE DEBUG] Processing container {idx}/{len(containers)}...", flush=True)
            q = self._parse_one_question(container, idx)
            if q:
                questions.append(q)
                print(f"[PARSE DEBUG] Container {idx} parsed successfully as {q.get('question_type')}", flush=True)
            else:
                print(f"[PARSE DEBUG] Container {idx} returned None (likely not a question)", flush=True)

        print(f"[PARSE DEBUG] Finished parsing. Valid questions: {len(questions)}", flush=True)
        return questions

    def _parse_one_question(self, container, idx: int) -> dict | None:
        """
        Determine question type and extract metadata for a single container.
        Returns None if the container does not look like a real question.
        """
        # --- Question text ---
        # SurveyMonkey places the question title in:
        #   • <div class="question-header">  (classic)
        #   • <legend>                        (accessible markup)
        #   • First <p> or <span class="...question-title...">
        q_text = ""
        for selector in ("div.question-header", "legend", "div.question-body p"):
            tag = container.select_one(selector)
            if tag:
                q_text = _extract_text(tag)
                print(f"[PARSE DEBUG Q{idx}] Question text found via '{selector}': {q_text[:80]}", flush=True)
                break
        if not q_text:
            q_text = _extract_text(container)[:120]  # fallback: first 120 chars
            print(f"[PARSE DEBUG Q{idx}] Question text (fallback): {q_text[:80]}", flush=True)

        # --- Required flag ---
        # SurveyMonkey marks required questions with class "required" on the container
        # or with a <span class="required"> child element.
        required = (
            "required" in (container.get("class") or [])
            or bool(container.select_one("span.required, .question-required"))
        )
        print(f"[PARSE DEBUG Q{idx}] Required: {required}", flush=True)

        # --- Detect type ---
        radios = container.find_all("input", {"type": "radio"})
        selects = container.find_all("select")
        text_inputs = container.find_all(
            "input", {"type": ["text", "email", "tel", "number"]}
        )
        print(f"[PARSE DEBUG Q{idx}] Found: #radios={len(radios)}, #selects={len(selects)}, #text_inputs={len(text_inputs)}", flush=True)

        if radios:
            print(f"[PARSE DEBUG Q{idx}] Type detected: RADIO", flush=True)
            return self._parse_radio(container, idx, q_text, required, radios)
        elif selects:
            print(f"[PARSE DEBUG Q{idx}] Type detected: DROPDOWN", flush=True)
            return self._parse_dropdown(container, idx, q_text, required, selects[0])
        elif len(text_inputs) > 1:
            print(f"[PARSE DEBUG Q{idx}] Type detected: TEXT_GROUP", flush=True)
            return self._parse_text_group(container, idx, q_text, required, text_inputs)
        elif len(text_inputs) == 1:
            print(f"[PARSE DEBUG Q{idx}] Type detected: TEXT", flush=True)
            return self._parse_text(container, idx, q_text, required, text_inputs[0])
        else:
            # Could be a display-only or unsupported element — skip
            print(f"[PARSE DEBUG Q{idx}] Type: NO MATCHING TYPE - skipping", flush=True)
            return None

    def _parse_radio(self, container, idx, q_text, required, radios) -> dict:
        options = []
        for i, inp in enumerate(radios):
            # The visible label is usually in a sibling <label> or parent <label>
            parent_label = inp.find_parent("label")
            if parent_label:
                label_text = _extract_text(parent_label)
            else:
                # Try next sibling label
                label_tag = inp.find_next_sibling("label") or inp.find_next("label")
                label_text = _extract_text(label_tag) if label_tag else f"Option {i}"
            options.append({
                "index": i,
                "value": inp.get("value", str(i)),
                "label": label_text,
            })
        return {
            "question_index": idx,
            "question_text": q_text,
            "question_type": "radio",
            "required": required,
            "options": options,
            "fields": [],
        }

    def _parse_dropdown(self, container, idx, q_text, required, select_tag) -> dict:
        options = []
        for i, opt in enumerate(select_tag.find_all("option")):
            if opt.get("value", "") in ("", None, "--"):
                continue  # skip placeholder
            options.append({
                "index": i,
                "value": opt.get("value", ""),
                "label": _extract_text(opt),
            })
        return {
            "question_index": idx,
            "question_text": q_text,
            "question_type": "dropdown",
            "required": required,
            "options": options,
            "fields": [],
        }

    def _parse_text_group(self, container, idx, q_text, required, inputs) -> dict:
        fields = []
        for inp in inputs:
            placeholder = inp.get("placeholder", "")
            input_type = inp.get("type", "text")
            # Guess field_key from type or placeholder
            if input_type == "email" or "mail" in placeholder.lower():
                field_key = "email"
            elif input_type == "tel" or "phone" in placeholder.lower() or "tel" in placeholder.lower():
                field_key = "phone"
            else:
                field_key = "name"
            fields.append({"field_key": field_key, "placeholder": placeholder})
        return {
            "question_index": idx,
            "question_text": q_text,
            "question_type": "text_group",
            "required": required,
            "options": [],
            "fields": fields,
        }

    def _parse_text(self, container, idx, q_text, required, inp) -> dict:
        placeholder = inp.get("placeholder", "")
        return {
            "question_index": idx,
            "question_text": q_text,
            "question_type": "text",
            "required": required,
            "options": [],
            "fields": [{"field_key": "text", "placeholder": placeholder}],
        }
