"""Heuristic keyword-based categorization of scanned wildcards, with a
user-editable override file that always wins over the heuristic."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from threading import Lock

from wc_lib.scan import WildcardEntry

_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _tokenize(name: str) -> list[str]:
    return [t for t in _TOKEN_SPLIT_RE.split(name.lower()) if t]


def _keyword_matches(keyword: str, tokens: list[str], lowered_full: str) -> bool:
    # Plain single-word keywords (the vast majority) match as a *prefix* of a
    # whole underscore/slash-delimited token — e.g. "cloth" matches the token
    # "clothes", but "elf" does NOT match inside "self" (they're different
    # tokens; naive substring matching used to wrongly file self-care
    # wildcards under RACE). Keywords that contain a space or "/" are
    # deliberately phrase/path-fragment matches and keep substring matching.
    if " " in keyword or "/" in keyword:
        return keyword in lowered_full
    return any(tok.startswith(keyword) for tok in tokens)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RULES_PATH = DATA_DIR / "category_rules.json"
OVERRIDES_PATH = DATA_DIR / "category_overrides.json"

# Not a keyword category: wildcards whose own content is a whole composed scene
# (nested __wildcard__ chains, or lines dense with clauses) rather than a single
# ingredient. Detected structurally in wc_lib.scan, wins over keyword rules.
PRESET_CATEGORY = "PRESET"

_save_lock = Lock()


def load_rules() -> tuple[list[tuple[str, list[str]]], str]:
    try:
        with open(RULES_PATH, encoding="utf8") as f:
            data = json.load(f)
        rules = [(r["category"], [kw.lower() for kw in r["keywords"]]) for r in data.get("rules", [])]
        fallback = data.get("fallback", "Uncategorized")
        return rules, fallback
    except Exception:
        logger.exception("Failed to load %s, using no rules", RULES_PATH)
        return [], "Uncategorized"


def load_overrides() -> dict[str, str]:
    try:
        with open(OVERRIDES_PATH, encoding="utf8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_override(entry_name: str, category: str) -> None:
    with _save_lock:
        overrides = load_overrides()
        if category:
            overrides[entry_name] = category
        else:
            overrides.pop(entry_name, None)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(OVERRIDES_PATH, "w", encoding="utf8") as f:
            json.dump(overrides, f, ensure_ascii=False, indent=2, sort_keys=True)


def categorize_entry(
    entry: WildcardEntry, rules: list[tuple[str, list[str]]], overrides: dict[str, str], fallback: str
) -> str:
    if entry.name in overrides:
        return overrides[entry.name]
    if entry.kind == "preset":
        return PRESET_CATEGORY
    lowered = entry.name.lower()
    tokens = _tokenize(entry.name)
    for category, keywords in rules:
        if any(_keyword_matches(kw, tokens, lowered) for kw in keywords):
            return category
    return fallback


def all_category_names() -> list[str]:
    """Full configured taxonomy, including categories with zero entries right now."""
    rules, fallback = load_rules()
    return [PRESET_CATEGORY] + [c for c, _ in rules] + [fallback]


def categorize_all(entries: list[WildcardEntry]) -> tuple[dict[str, list[WildcardEntry]], list[str]]:
    rules, fallback = load_rules()
    overrides = load_overrides()

    buckets: dict[str, list[WildcardEntry]] = {}
    for entry in entries:
        category = categorize_entry(entry, rules, overrides, fallback)
        buckets.setdefault(category, []).append(entry)

    category_order = [PRESET_CATEGORY] + [c for c, _ in rules] + [fallback]
    # Preserve rule order, but only include categories that actually have entries,
    # then append any surprise category names left over from overrides.
    ordered = [c for c in category_order if c in buckets]
    ordered += [c for c in buckets if c not in ordered]
    return buckets, ordered
