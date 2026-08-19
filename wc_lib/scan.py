"""Standalone wildcard scanner. Deliberately does not import sd-dynamic-prompts or
sd-webui-prompt-studio-neo so this extension stays fully decoupled from both.

Only .txt and .yaml/.yml files are treated as wildcards. Everything else found in a
wildcards folder (.json, .html, .jpeg, .card, .csv, .safetensors, ...) is metadata
clutter from model downloads and is ignored on purpose.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

_NESTED_TOKEN_RE = re.compile(r"__([^_].*?)__")

logger = logging.getLogger(__name__)

IGNORED_TXT_NAMES = {"put wildcards here.txt"}


@dataclass(frozen=True)
class WildcardEntry:
    name: str  # e.g. "HHP-BDSM/Apparatus/BDSMLib/Breath"
    token: str  # e.g. "__HHP-BDSM/Apparatus/BDSMLib/Breath__"
    source: Path
    source_type: str  # "txt" or "yaml"
    kind: str = "atomic"  # "atomic" (one ingredient) or "preset" (a whole composed scene)


# A .txt wildcard is treated as a "preset" (a whole scene per line, not a single
# ingredient meant to be combined with others) when either:
#  - it nests other wildcards from more than one distinct "family" (e.g.
#    __character__ + __locations__ + __poses__ span different concepts, vs.
#    __body_eye_details__ + __body_nose_details__, which are all just facets of
#    the same "body" ingredient delegating to sub-variants of itself), or
#  - its lines are dense multi-clause sentences on average.
# Calibrated against this project's real library: atomic files like lighting/camera
# tags sit at 0-3 commas/line and 0-1 nested families; full-scene packs like
# "AnimaWildcradAnima_02" or "full_scene_plus_character*" sit at 25-34 commas/line
# or reference 5 distinct nested families.
_PRESET_AVG_COMMA_THRESHOLD = 10
_PRESET_MIN_NESTED_FAMILIES = 2


def _nested_tokens(text: str) -> set[str]:
    return set(_NESTED_TOKEN_RE.findall(text))


def _nested_family_count(tokens: set[str]) -> int:
    families = {t.split("_")[0].split("/")[0] for t in tokens}
    return len(families)


def _classify_txt_lines(lines: list[str], nested: set[str]) -> str:
    if not lines:
        return "atomic"
    if _nested_family_count(nested) >= _PRESET_MIN_NESTED_FAMILIES:
        return "preset"
    avg_commas = sum(line.count(",") for line in lines) / len(lines)
    return "preset" if avg_commas > _PRESET_AVG_COMMA_THRESHOLD else "atomic"


def find_wildcard_root() -> Path | None:
    """Locate the wildcards folder the same way sd-dynamic-prompts does:
    modules.shared.opts.wildcard_dir if set, otherwise the first
    extensions/*/wildcards folder found (preferring sd-dynamic-prompts)."""
    try:
        from modules.shared import opts

        custom = getattr(opts, "wildcard_dir", None)
        if custom:
            p = Path(custom)
            if p.is_dir():
                return p
    except Exception:
        logger.exception("Could not read shared.opts.wildcard_dir")

    # extensions/sd-webui-wildcard-composer/wc_lib/scan.py -> extensions/
    ext_root = Path(__file__).resolve().parent.parent.parent

    preferred = ext_root / "sd-dynamic-prompts" / "wildcards"
    if preferred.is_dir():
        return preferred

    for candidate in sorted(ext_root.glob("*/wildcards")):
        if candidate.is_dir():
            return candidate

    return None


def _scan_txt(root: Path) -> list[WildcardEntry]:
    # Two passes. Pass 1 classifies each file on its own content. Pass 2
    # propagates "preset" through references: a file that only chains other
    # __wildcard__ tokens which are themselves presets is a preset too, even
    # if those references happen to share a naming prefix (e.g.
    # full_scene_plus_character_compose_all_all.txt just dispatches between
    # __full_scene_plus_character_compose__ and
    # __full_scene_plus_character_compose_nsfw__ — both already presets, both
    # sharing the "full" family word, so the family-diversity check alone
    # can't see it).
    raw = []  # (name, path, kind, nested_refs)
    for path in root.rglob("*.txt"):
        if not path.is_file() or path.name in IGNORED_TXT_NAMES:
            continue
        name = path.relative_to(root).with_suffix("").as_posix()
        try:
            text = path.read_text(encoding="utf8", errors="replace")
            lines = [line for line in text.splitlines() if line.strip()]
            nested = _nested_tokens(text)
            kind = _classify_txt_lines(lines, nested)
        except Exception:
            logger.exception("Could not read %s for preset/atomic classification", path)
            nested = set()
            kind = "atomic"
        raw.append((name, path, kind, nested))

    kind_by_name = {name: kind for name, _, kind, _ in raw}
    for _ in range(4):  # a few rounds is plenty for realistic reference chains
        changed = False
        for name, _, kind, refs in raw:
            if kind_by_name[name] == "atomic" and any(kind_by_name.get(ref) == "preset" for ref in refs):
                kind_by_name[name] = "preset"
                changed = True
        if not changed:
            break

    return [
        WildcardEntry(name=name, token=f"__{name}__", source=path, source_type="txt", kind=kind_by_name[name])
        for name, path, _, _ in raw
    ]


def _is_umi_format(data: dict) -> bool:
    """UMI tag-list format (name -> {Tags: [...]}) is not a wildcard pantry; skip it."""
    for item in data:
        try:
            if not (data[item] and "Tags" in data[item] and isinstance(data[item]["Tags"], list)):
                return False
        except Exception:
            return False
    return True


def _clean_pantry(node: dict) -> None:
    """Recursively drop keys whose values aren't a string, a list of strings, or a
    non-empty dict of the same."""
    for key, value in list(node.items()):
        if isinstance(value, dict):
            _clean_pantry(value)
            if not value:
                del node[key]
        elif not (isinstance(value, str) or (isinstance(value, list) and all(isinstance(v, str) for v in value))):
            del node[key]


def _flatten_pantry(node: dict, prefix: str = ""):
    for key, value in node.items():
        path = f"{prefix}/{key}" if prefix else str(key)
        if isinstance(value, dict):
            yield from _flatten_pantry(value, path)
        else:
            yield path


def _scan_yaml(root: Path) -> list[WildcardEntry]:
    entries = []
    yaml_files = list(root.rglob("*.yaml")) + list(root.rglob("*.yml"))
    for path in yaml_files:
        if not path.is_file():
            continue
        try:
            with open(path, encoding="utf8") as f:
                data = yaml.safe_load(f)
        except (yaml.YAMLError, UnicodeDecodeError) as e:
            logger.warning("Skipping unreadable wildcard yaml %s: %s", path, e)
            continue

        if not data or not isinstance(data, dict) or _is_umi_format(data):
            continue

        _clean_pantry(data)
        for name in _flatten_pantry(data):
            entries.append(WildcardEntry(name=name, token=f"__{name}__", source=path, source_type="yaml"))
    return entries


def scan_wildcards(root: Path | None = None) -> list[WildcardEntry]:
    if root is None:
        root = find_wildcard_root()
    if root is None or not root.is_dir():
        return []

    entries = _scan_txt(root) + _scan_yaml(root)

    # De-dupe by name (a .txt and a .yaml pantry entry could theoretically collide);
    # keep the first occurrence deterministically by sorting first.
    seen = {}
    for entry in sorted(entries, key=lambda e: e.name):
        seen.setdefault(entry.name, entry)
    return sorted(seen.values(), key=lambda e: e.name)
