#!/usr/bin/env python3
"""Shared library for the Muse adapter of agent-dossier.

Implements:
- SPEC section 2.1 fingerprint (CRLF -> LF, strip by Unicode White_Space,
  SHA-1 of "name|title|role" in UTF-8, first 12 hex chars)
- the three storage forms from SPEC section 1 (front matter file, bare YAML,
  Notion page text with exactly one ```yaml block)
- SPEC section 5 sensitive-information scan (export aborts, import refuses)
- deterministic dossier rendering (SPEC section 6: idempotent export,
  byte-identical except exported_at for identical input)
"""
import datetime
import hashlib
import re

import yaml

# --- SPEC 2.1 fingerprint -------------------------------------------------

def normalize(text):
    """CRLF -> LF, then strip leading/trailing Unicode White_Space.

    Python's str.strip() strips exactly the characters whose Unicode
    White_Space property is true (including U+3000 and U+00A0), which is
    what SPEC 2.1 requires.
    """
    return (text or "").replace("\r\n", "\n").strip()


def fingerprint(name, title, role):
    joined = "|".join([normalize(name), normalize(title), normalize(role)])
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


def check_vectors(vectors):
    """vectors: list of dicts with name/title/role/fingerprint.
    Returns (passed_count, list_of_failed_vectors)."""
    failed = [v for v in vectors
              if fingerprint(v.get("name"), v.get("title"), v.get("role")) != v.get("fingerprint")]
    return len(vectors) - len(failed), failed


# --- SPEC 5 sensitive scan --------------------------------------------------
# Same pattern family as the grok-bot reference implementation, plus the
# password-value pattern that SPEC 5.2 names in prose (the reference
# implementation's code does not include it; see adapter-report.md).

SCAN_PATTERNS = [
    ("email", r"[\w.+-]+@(?!\d{1,3}(?:\.\d{1,3}){3}\b)[\w-]+\.[\w.]+"),
    ("japan-phone", r"0\d{1,3}-\d{3,4}-\d{4}"),
    ("card-16", r"\b\d{16}\b"),
    ("openai-key", r"sk-[A-Za-z0-9]{10,}"),
    ("github-token", r"ghp_\w+"),
    ("password-value", r"(?:password|passwd|密码)\s*[:：=]\s*\S+"),
]

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def scan_fields(named_texts):
    """named_texts: list of (where, text). Returns list of (where, pattern_name)."""
    hits = []
    for where, text in named_texts:
        if not text:
            continue
        for name, pat in SCAN_PATTERNS:
            if re.search(pat, str(text)):
                hits.append((where, name))
    return hits


def dossier_texts(data):
    """All texts SPEC 5.2 requires scanning: role, memory facts, routine prompts."""
    texts = [("role", data.get("role"))]
    for i, m in enumerate(data.get("memory") or []):
        texts.append((f"memory[{i}].fact", (m or {}).get("fact")))
    for i, r in enumerate(data.get("routines") or []):
        texts.append((f"routines[{i}].prompt", (r or {}).get("prompt")))
    return texts


# --- loading (SPEC section 1: two storage forms) ---------------------------

class DossierError(Exception):
    pass


def _dates_to_str(obj):
    """yaml parses ISO dates into datetime.date; the dossier treats them as
    strings, so normalize on load to keep comparisons and rendering stable."""
    if isinstance(obj, dict):
        return {k: _dates_to_str(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_dates_to_str(v) for v in obj]
    if isinstance(obj, datetime.date):
        return obj.isoformat()
    return obj


def load_dossier_text(text):
    """Parse any of the three accepted forms. Returns (data: dict, body: str|None).
    Raises DossierError on structural problems."""
    blocks = re.findall(r"```ya?ml\n(.*?)\n```", text, re.S)
    if len(blocks) > 1:
        raise DossierError("more than one yaml block (SPEC section 1)")
    if blocks:
        # Notion round-trips can escape [rule] as \[rule\]; undo that inside
        # the machine-readable block only.
        block = blocks[0].replace("\\[", "[").replace("\\]", "]")
        data = yaml.safe_load(block)
    elif text.startswith("---\n") or text.startswith("---\r\n"):
        m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", text, re.S)
        if not m:
            raise DossierError("front matter not closed")
        data = yaml.safe_load(m.group(1))
        body = m.group(2)
        if not isinstance(data, dict):
            raise DossierError("front matter is not a mapping")
        return _dates_to_str(data), body
    else:
        data = yaml.safe_load(text)
        if not (isinstance(data, dict) and "spec" in data):
            raise DossierError("no dossier found (need front matter, one yaml block, or bare yaml)")
        return _dates_to_str(data), None
    if not isinstance(data, dict):
        raise DossierError("yaml block is not a mapping")
    return _dates_to_str(data), None


def load_dossier_file(path):
    with open(path, encoding="utf-8") as f:
        return load_dossier_text(f.read())


# --- validation --------------------------------------------------------------

REQUIRED = ["spec", "id", "name", "status", "exported_at", "source",
            "fingerprint", "role", "routines", "memory"]
SPECS = ("agent-dossier/0.1", "agent-dossier/0.2")
STATUS = {"active", "handed-over", "retired"}
KIND = {"rule", "preference", "decision", "history"}
ROUTINE_STATE = {"running", "paused", "deleted"}


def validate(data):
    """Returns (errors, warnings). Errors block import/export."""
    errors, warnings = [], []
    for k in REQUIRED:
        if k not in data:
            errors.append(f"missing required field: {k}")
    if errors:
        return errors, warnings
    if data["spec"] not in SPECS:
        errors.append(f"unsupported spec {data['spec']!r}")
    if data["status"] not in STATUS:
        errors.append(f"bad status {data['status']!r}")
    fp = fingerprint(data.get("name"), data.get("title"), data.get("role"))
    if fp != data.get("fingerprint"):
        errors.append(f"fingerprint mismatch: file says {data.get('fingerprint')}, "
                      f"content hashes to {fp}")
    for where, pat in scan_fields(dossier_texts(data)):
        errors.append(f"sensitive pattern {pat} in {where}; refused")
    for i, m in enumerate(data.get("memory") or []):
        if (m or {}).get("kind") not in KIND:
            errors.append(f"memory[{i}] kind invalid: {(m or {}).get('kind')!r}")
    for i, r in enumerate(data.get("routines") or []):
        if (r or {}).get("state") not in ROUTINE_STATE:
            errors.append(f"routines[{i}] state invalid: {(r or {}).get('state')!r}")
    # SPEC 5.4: UUIDs in role (usually other agents' ids) warn, never block.
    refs_ids = {str(r.get("id")) for r in (data.get("refs") or []) if isinstance(r, dict)}
    for u in sorted(set(UUID_RE.findall(data.get("role") or "")) - {str(data.get("id"))}):
        note = "" if u in refs_ids else " and it is not listed in refs"
        warnings.append(f"role mentions id {u}{note}; ids do not resolve on another platform")
    return errors, warnings


# --- rendering (SPEC section 6: idempotent export) ---------------------------

FIELD_ORDER = ["spec", "id", "name", "title", "group", "status", "exported_at",
               "source", "fingerprint", "role", "anti_jobs", "routines",
               "memory", "refs", "skills", "excluded"]


def canonical(data):
    """Order fields per FIELD_ORDER, drop None-valued optional fields, and
    normalize nested entries so rendering is deterministic."""
    out = {}
    for k in FIELD_ORDER:
        if k not in data:
            continue
        v = data[k]
        if v is None and k not in ("routines", "memory"):
            continue
        if k == "routines" and v is not None:
            v = [{kk: r.get(kk) for kk in ("id", "name", "schedule", "prompt", "state")
                  if r.get(kk) is not None} for r in v]
        if k == "memory" and v is not None:
            v = [{kk: m.get(kk) for kk in ("fact", "kind", "learned")
                  if m.get(kk) is not None} for m in v]
        if k == "refs" and v is not None:
            v = [{kk: r.get(kk) for kk in ("name", "id") if r.get(kk) is not None}
                 for r in v]
        out[k] = v
    return out


def render_dossier(data, body=None):
    """Render the file form: YAML front matter + human-readable body.
    The fingerprint is recomputed from content, never trusted from input."""
    data = dict(data)
    data["fingerprint"] = fingerprint(data.get("name"), data.get("title"), data.get("role"))
    fm = yaml.safe_dump(canonical(data), allow_unicode=True, sort_keys=False,
                        default_flow_style=False, width=10 ** 6)
    # PyYAML quotes date-looking strings; the dossier writes ISO dates bare
    # (they parse back to the same string via _dates_to_str on load).
    fm = re.sub(r"^(\s*(?:exported_at|learned): )'(\d{4}-\d{2}-\d{2})'$", r"\1\2",
                fm, flags=re.M)
    if body is None:
        heading = data.get("name") or "agent"
        lines = [f"# {heading} 交接档案", ""]
        if data.get("title"):
            lines += [f"职能：{data['title']}", ""]
        lines.append("由 Muse 适配器导出（agent-dossier，平台等级 L1）。"
                     "机器可读字段以上方 front matter 为准，正文只做人读说明。")
        body = "\n".join(lines) + "\n"
    return f"---\n{fm}---\n\n{body}"
