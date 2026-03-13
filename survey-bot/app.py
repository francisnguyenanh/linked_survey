"""
app.py — Flask web server for survey-bot.

Routes:
  GET  /                  → Dashboard
  GET  /scanner           → Scanner page
  POST /scanner/scan      → Run SurveyScanner, create default config
  GET  /configure/<name>  → Configure a saved config
  POST /configure/save    → Save config (JSON body)
  GET  /config/export/<n> → Download config JSON
  DELETE /config/<name>   → Delete config
  GET  /csv               → CSV management page
  POST /csv/upload        → Upload personas.csv
  GET  /run               → Run control page
  POST /run/start         → Start bot in background thread
  GET  /run/status        → Job status JSON
  POST /run/stop          → Request stop
  GET  /history           → Run history page
  DELETE /history         → Clear run_log.jsonl
"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from bot import SurveyBot, set_job_ref
from config_manager import ConfigManager
from csv_manager import CSVManager
from scanner import SurveyScanner

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CONFIGS_DIR = DATA_DIR / "configs"
PERSONAS_CSV = DATA_DIR / "personas.csv"
RUN_LOG = DATA_DIR / "run_log.jsonl"

# Ensure directories exist at startup
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)

# ---------------------------------------------------------------------------
# Module-level job state (one job at a time)
# ---------------------------------------------------------------------------
job: dict = {
    "running": False,
    "stop_event": None,
    "thread": None,
    "current_run": 0,
    "total_runs": 0,
    "results": [],
    "started_at": None,
    "config_name": None,
    "csv_total_rows": 0,
    "waiting_for_ip_rotation": False,
    "waiting_since": None,
    "pause_for_ip_rotation": False,
    "pause_event": None,
}

config_mgr = ConfigManager()


def _read_run_log(limit: int | None = None) -> list[dict]:
    """Read run_log.jsonl, newest first."""
    if not RUN_LOG.exists():
        return []
    lines = RUN_LOG.read_text(encoding="utf-8").splitlines()
    results = []
    for line in reversed(lines):
        line = line.strip()
        if line:
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        if limit and len(results) >= limit:
            break
    return results


def _job_status_dict() -> dict:
    elapsed = 0.0
    if job["started_at"]:
        try:
            started = datetime.fromisoformat(job["started_at"])
            elapsed = round((datetime.utcnow() - started).total_seconds(), 1)
        except ValueError:
            pass
    return {
        "running": job["running"],
        "current_run": job["current_run"],
        "total_runs": job["total_runs"],
        "results": job["results"],
        "elapsed_sec": elapsed,
        "config_name": job["config_name"],
        "csv_total_rows": job["csv_total_rows"],
        "waiting_for_ip_rotation": job["waiting_for_ip_rotation"],
        "waiting_since": job["waiting_since"],
        "pause_for_ip_rotation": job["pause_for_ip_rotation"],
    }


# ---------------------------------------------------------------------------
@app.route("/")
def index():
    configs = config_mgr.list_all()
    recent = _read_run_log(limit=5)
    return render_template("index.html", configs=configs, recent=recent)


@app.route("/scanner")
def scanner_page():
    return render_template("scanner.html")


@app.route("/scanner/scan", methods=["POST"])
def scanner_scan():
    print(f"[SCANNER ROUTE] /scanner/scan POST request received", flush=True)
    data = request.get_json(force=True) or {}
    url = (data.get("url") or "").strip()
    print(f"[SCANNER ROUTE] URL from request: {url}", flush=True)
    
    if not url:
        print(f"[SCANNER ROUTE] ERROR: URL is empty", flush=True)
        return jsonify({"status": "error", "message": "URL is required"}), 400
    
    try:
        print(f"[SCANNER ROUTE] Starting SurveyScanner.scan()...", flush=True)
        scan_result = SurveyScanner().scan(url)
        print(f"[SCANNER ROUTE] Scan complete. Result: {scan_result}", flush=True)
    except Exception as exc:
        print(f"[SCANNER ROUTE] ERROR during scan: {exc}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(exc)}), 500

    from scanner import _url_slug
    config_name = _url_slug(url)[:40] or "survey"
    print(f"[SCANNER ROUTE] Config name: {config_name}", flush=True)
    
    try:
        print(f"[SCANNER ROUTE] Creating config from scan result...", flush=True)
        config = config_mgr.create_from_scan(scan_result, config_name)
        print(f"[SCANNER ROUTE] Saving config...", flush=True)
        config_mgr.save(config)
        print(f"[SCANNER ROUTE] Config saved successfully", flush=True)
    except Exception as exc:
        print(f"[SCANNER ROUTE] ERROR creating/saving config: {exc}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": f"Config create failed: {exc}"}), 500

    print(f"[SCANNER ROUTE] Returning success response", flush=True)
    return jsonify({"status": "ok", "scan": scan_result, "config_name": config["config_name"]})


@app.route("/configure/<config_name>")
def configure_page(config_name: str):
    try:
        config = config_mgr.load(config_name)
    except FileNotFoundError:
        return f"Config '{config_name}' not found.", 404
    return render_template("configure.html", config=config)


@app.route("/configure/save", methods=["POST"])
def configure_save():
    payload = request.get_json(force=True) or {}
    config_name = payload.get("config_name", "unnamed")
    old_config_name = payload.get("old_config_name", config_name)
    url = payload.get("url", "")
    num_runs = int(payload.get("num_runs", 5))
    sleep_between = int(payload.get("sleep_between_runs", 30))

    # Load existing config: if old_config_name is different (rename case), load from old name
    try:
        existing = config_mgr.load(old_config_name)
    except FileNotFoundError:
        existing = {"questions": []}

    questions_update = {
        str(q["question_index"]): q.get("allowed_options", [])
        for q in payload.get("questions", [])
    }
    questions = []
    for q in existing.get("questions", []):
        q_copy = dict(q)
        qi = str(q["question_index"])
        if qi in questions_update:
            q_copy["allowed_options"] = [int(i) for i in questions_update[qi]]
        questions.append(q_copy)

    config = {
        **existing,
        "config_name": config_name,
        "url": url or existing.get("url", ""),
        "num_runs": num_runs,
        "sleep_between_runs": sleep_between,
        "questions": questions,
    }
    config_mgr.save(config)
    
    # If renaming, delete old config
    if old_config_name != config_name:
        try:
            config_mgr.delete(old_config_name)
        except Exception:
            pass
    
    return jsonify({"status": "ok", "config_name": config_name})


@app.route("/config/export/<config_name>")
def config_export(config_name: str):
    path = CONFIGS_DIR / f"{config_name}.json"
    if not path.exists():
        return f"Config '{config_name}' not found.", 404
    return send_file(str(path), as_attachment=True, download_name=f"{config_name}.json")


@app.route("/config/<config_name>", methods=["DELETE"])
def config_delete(config_name: str):
    config_mgr.delete(config_name)
    return jsonify({"status": "ok"})


@app.route("/csv")
def csv_page():
    preview = []
    total = 0
    if PERSONAS_CSV.exists():
        try:
            mgr = CSVManager()
            mgr.load(str(PERSONAS_CSV))
            preview = mgr.preview(5)
            total = mgr.total_rows()
        except Exception:
            pass
    return render_template("csv.html", preview=preview, total=total)


@app.route("/csv/upload", methods=["POST"])
def csv_upload():
    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No file part in request"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"status": "error", "message": "No file selected"}), 400
    if not f.filename.lower().endswith(".csv"):
        return jsonify({"status": "error", "message": "Only .csv files are accepted"}), 400

    tmp_path = DATA_DIR / "_upload_tmp.csv"
    f.save(str(tmp_path))
    mgr = CSVManager()
    try:
        count = mgr.load(str(tmp_path))
        ok, msg = mgr.validate(["name", "email", "phone"])
        if not ok:
            tmp_path.unlink(missing_ok=True)
            return jsonify({"status": "error", "message": msg}), 400
        tmp_path.replace(PERSONAS_CSV)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        return jsonify({"status": "error", "message": str(exc)}), 400

    return jsonify({"status": "ok", "total_rows": count, "preview": mgr.preview(5)})


@app.route("/run")
def run_page():
    configs = config_mgr.list_all()
    csv_rows = 0
    if PERSONAS_CSV.exists():
        try:
            mgr = CSVManager()
            mgr.load(str(PERSONAS_CSV))
            csv_rows = mgr.total_rows()
        except Exception:
            pass
    return render_template("run.html", configs=configs, csv_rows=csv_rows)


@app.route("/run/start", methods=["POST"])
def run_start():
    if job["running"]:
        return jsonify({"status": "error", "message": "A job is already running"}), 409

    data = request.get_json(force=True) or {}
    config_name = data.get("config_name", "").strip()
    num_runs = int(data.get("num_runs", 5))
    sleep_between = int(data.get("sleep_between_runs", 30))
    pause_for_ip_rotation = bool(data.get("pause_for_ip_rotation", False))
    pause_event = threading.Event()
    pause_event.set()  # pre-set so first run starts immediately without pausing

    try:
        config = config_mgr.load(config_name)
    except FileNotFoundError:
        return jsonify({"status": "error", "message": f"Config '{config_name}' not found"}), 400

    config["num_runs"] = num_runs
    config["sleep_between_runs"] = sleep_between

    if not PERSONAS_CSV.exists():
        return jsonify({"status": "error", "message": "personas.csv not found. Upload one first."}), 400

    csv_mgr = CSVManager()
    try:
        csv_mgr.load(str(PERSONAS_CSV))
    except Exception as exc:
        return jsonify({"status": "error", "message": f"CSV load error: {exc}"}), 400

    csv_rows = csv_mgr.total_rows()
    if csv_rows < num_runs:
        return jsonify({
            "status": "error",
            "message": (
                f"CSV has only {csv_rows} rows but you requested {num_runs} runs. "
                "Add more rows or reduce num_runs."
            ),
        }), 400

    stop_event = threading.Event()
    bot = SurveyBot(
        config=config,
        csv_manager=csv_mgr,
        stop_event=stop_event,
        pause_for_ip_rotation=pause_for_ip_rotation,
        pause_event=pause_event,
    )

    job.update({
        "running": True,
        "stop_event": stop_event,
        "current_run": 0,
        "total_runs": num_runs,
        "results": [],
        "started_at": datetime.utcnow().isoformat(),
        "config_name": config_name,
        "csv_total_rows": csv_rows,
        "waiting_for_ip_rotation": False,
        "waiting_since": None,
        "pause_for_ip_rotation": pause_for_ip_rotation,
        "pause_event": pause_event,
    })

    set_job_ref(job)

    def _on_progress(result: dict):
        job["results"].append(result)
        job["current_run"] = len(job["results"])

    def _run():
        try:
            bot.run_all(progress_callback=_on_progress)
        except Exception as exc:
            app.logger.exception("Bot thread crashed: %s", exc)
        finally:
            job["running"] = False
            job["current_run"] = len(job["results"])
            job["waiting_for_ip_rotation"] = False

    t = threading.Thread(target=_run, daemon=True)
    job["thread"] = t
    t.start()

    return jsonify({"status": "started", "total_runs": num_runs, "csv_rows": csv_rows})


@app.route("/run/status")
def run_status():
    return jsonify(_job_status_dict())


@app.route("/run/stop", methods=["POST"])
def run_stop():
    if job["stop_event"]:
        job["stop_event"].set()
    return jsonify({"status": "stopping"})


@app.route("/run/continue", methods=["POST"])
def run_continue():
    if job.get("pause_event"):
        job["pause_event"].set()
    job["waiting_for_ip_rotation"] = False
    return jsonify({"status": "continued"})


@app.route("/history")
def history_page():
    runs = _read_run_log()
    return render_template("history.html", runs=runs)


@app.route("/history", methods=["DELETE"])
def history_clear():
    if RUN_LOG.exists():
        RUN_LOG.unlink()
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5001)
