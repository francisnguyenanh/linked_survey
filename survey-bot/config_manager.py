"""
config_manager.py — Load, save, and manage survey run configurations.

Each config is stored as a JSON file under data/configs/{config_name}.json.
"""

import json
import re
from datetime import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
CONFIGS_DIR = DATA_DIR / "configs"


def _safe_name(name: str) -> str:
    """Sanitise a config name so it is safe as a filename."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", name)


class ConfigManager:

    def __init__(self):
        CONFIGS_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # create_from_scan
    # ------------------------------------------------------------------
    def create_from_scan(self, scan: dict, config_name: str) -> dict:
        """
        Generate a ready-to-use config dict from a scan result.

        For radio / dropdown questions all option indices are added to
        allowed_options so the bot can pick any of them by default.
        text_group questions get data_source = "csv".
        """
        questions = []
        for q in scan.get("questions", []):
            q_type = q["question_type"]
            entry = {
                "question_index": q["question_index"],
                "question_type": q_type,
                "question_text": q.get("question_text", ""),
            }
            if q_type in ("radio", "dropdown"):
                opts = q.get("options", [])
                entry["options"] = opts
                # Default: allow ALL options (bot picks randomly)
                entry["allowed_options"] = [o["index"] for o in opts]
            elif q_type == "text_group":
                entry["data_source"] = "csv"
                entry["fields"] = q.get("fields", [])
                entry["options"] = []
            elif q_type == "text":
                # plain text - store empty value by default
                entry["value"] = ""
                entry["fields"] = q.get("fields", [])
                entry["options"] = []
            questions.append(entry)

        config = {
            "config_name": _safe_name(config_name),
            "url": scan.get("url", ""),
            "num_runs": 5,
            "sleep_between_runs": 30,
            "created_at": datetime.utcnow().isoformat(),
            "questions": questions,
        }
        return config

    # ------------------------------------------------------------------
    def save(self, config: dict):
        """Persist a config dict to data/configs/{config_name}.json."""
        name = _safe_name(config.get("config_name", "unnamed"))
        config["config_name"] = name
        path = CONFIGS_DIR / f"{name}.json"
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, config_name: str) -> dict:
        """Load and return a config dict. Raises FileNotFoundError if missing."""
        path = CONFIGS_DIR / f"{_safe_name(config_name)}.json"
        if not path.exists():
            raise FileNotFoundError(f"Config '{config_name}' not found.")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_all(self) -> list[str]:
        """Return config names (without .json extension), sorted alphabetically."""
        return sorted(
            p.stem for p in CONFIGS_DIR.glob("*.json")
            if not p.name.endswith("_scan.json")
        )

    def delete(self, config_name: str):
        """Delete a config file. Silent if it does not exist."""
        path = CONFIGS_DIR / f"{_safe_name(config_name)}.json"
        if path.exists():
            path.unlink()
