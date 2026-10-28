#!/usr/bin/env python3
"""Shared library for the Hermes adapter of personal-agent-dossier.

Implements:
- SPEC section 2.1 fingerprint (CRLF -> LF, strip by Unicode White_Space,
  SHA-1 of "name|title|role" in UTF-8, first 12 hex chars)
- the three storage forms from SPEC section 1 (front matter file, bare YAML,
  Notion page text with exactly one ```yaml block)
- SPEC section 5 sensitive-information scan (export aborts, import refuses)
- deterministic dossier rendering (SPEC section 6 idempotency; appendix A
  standard serialization)
- the small pieces of Hermes layout knowledge both scripts share: how a role
  becomes SOUL.md text and back, how memory entries become MEMORY.md entries
  and back, and how a Hermes cron schedule string is read

Nothing here touches a real Hermes home; path handling stays in the scripts.
"""

import datetime
import hashlib
import json
import re

import yaml

# --- SPEC 2.1 fingerprint ---------------------------------------------------


def normalize(text):
    """CRLF -> LF, then strip leading/trailing Unicode White_Space.

    Python's str.strip() strips exactly the characters whose Unicode
    White_Space property is true (including U+3000 and U+00A0), which is what
    SPEC 2.1 requires.
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
# Same pattern family as tests/ and tools/dossier_check.py, including the
# password-value rule SPEC 5.2 names in prose.

SCAN_PATTERNS = [
    ("email", r"[\w.+-]+@(?!\d{1,3}(?:\.\d{1,3}){3}\b)[\w-]+\.[\w.]+"),
    ("japan-phone", r"0\d{1,3}-\d{3,4}-\d{4}"),
    ("card-16", r"\b\d{16}\b"),
    ("openai-key", r"sk-[A-Za-z0-9]{10,}"),
    ("github-token", r"ghp_\w+"),
    ("password-value", r"(?i)(?:password|passwd|密码)\s*[:：=]\s*\S+"),
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


# --- loading (SPEC section 1: three accepted forms) -------------------------

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


# --- validation -------------------------------------------------------------

REQUIRED = ["spec", "id", "name", "status", "exported_at", "source",
            "fingerprint", "role", "routines", "memory"]
SPECS = ("personal-agent-dossier/1.0", "agent-dossier/0.1", "agent-dossier/0.2")
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


# --- rendering (SPEC section 6 + appendix A) --------------------------------
# Hand-written serializer so the bytes match the rest of the corpus (appendix
# A): role/prompt as block scalars, sequences indented under their key, long
# scalars unwrapped, ISO dates bare, canonical field order.

FIELD_ORDER = ["spec", "id", "name", "title", "group", "status", "exported_at",
               "source", "fingerprint", "role", "refs", "anti_jobs", "routines",
               "memory", "skills", "excluded"]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RESERVED = {"null", "true", "false", "yes", "no", "on", "off", "~"}
_BLOCK_KEYS = {"role", "prompt"}


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


def _scalar(s):
    """Plain YAML scalar when safe (appendix A rule 4), else a JSON-style
    double-quoted string (JSON strings are valid YAML)."""
    s = str(s)
    if _DATE_RE.match(s):
        return s
    needs_quote = (
        s == "" or s != s.strip() or s.lower() in _RESERVED
        or ": " in s or " #" in s or " *" in s or s.endswith(":")
        or s[0] in "!&*?|>%@`\"'#,-?:[]{}"
        or (s[0].isdigit() and all(c in "0123456789 */(),.-" for c in s))
        or any(ord(c) < 0x20 for c in s)
    )
    if needs_quote:
        return json.dumps(s, ensure_ascii=False)
    return s


def _block(lines_out, prefix, text, content_indent):
    """Append a block scalar: `prefix: |-` then content lines indented."""
    style = "|" if text.endswith("\n") else "|-"
    lines_out.append(f"{prefix}: {style}")
    body = text[:-1] if text.endswith("\n") else text
    pad = " " * content_indent
    for line in body.split("\n"):
        lines_out.append(pad + line if line else "")


def _emit_kv(lines_out, key, value, key_col):
    """Emit one `key: value` at column key_col, corpus style."""
    pad = " " * key_col
    if value is None:
        lines_out.append(f"{pad}{key}: null")
    elif isinstance(value, list):
        if not value:
            lines_out.append(f"{pad}{key}: []")
            return
        lines_out.append(f"{pad}{key}:")
        for item in value:
            if isinstance(item, dict):
                pairs = list(item.items())
                first_k, first_v = pairs[0]
                _emit_dash_kv(lines_out, first_k, first_v, key_col)
                for k2, v2 in pairs[1:]:
                    _emit_kv(lines_out, k2, v2, key_col + 4)
            elif isinstance(item, str) and "\n" in item:
                _block(lines_out, f"{pad}  -", item, key_col + 4)
            else:
                lines_out.append(f"{pad}  - {_scalar(item)}")
    elif isinstance(value, str) and ("\n" in value or key in _BLOCK_KEYS):
        _block(lines_out, f"{pad}{key}", value, key_col + 2)
    else:
        lines_out.append(f"{pad}{key}: {_scalar(value)}")


def _emit_dash_kv(lines_out, key, value, list_col):
    """Emit the first key of a mapping inside a sequence: `  - key: value`.
    The dash sits at list_col, the key at list_col + 2."""
    pad = " " * list_col
    if isinstance(value, str) and ("\n" in value or key in _BLOCK_KEYS):
        _block(lines_out, f"{pad}  - {key}", value, list_col + 6)
    elif value is None:
        lines_out.append(f"{pad}  - {key}: null")
    else:
        lines_out.append(f"{pad}  - {key}: {_scalar(value)}")


def render_front_matter(data):
    lines_out = []
    for k, v in canonical(data).items():
        _emit_kv(lines_out, k, v, 0)
    return "\n".join(lines_out) + "\n"


def render_dossier(data, body=None):
    """Render the file form: YAML front matter + human-readable body.
    The fingerprint is recomputed from content, never trusted from input."""
    data = dict(data)
    data["fingerprint"] = fingerprint(data.get("name"), data.get("title"), data.get("role"))
    fm = render_front_matter(data)
    if body is None:
        heading = data.get("name") or "agent"
        body = (f"# {heading} 交接档案\n\n"
                "这份文件由 front matter 提供机器可读的全部字段；正文只做人读说明。\n")
    return f"---\n{fm}---\n\n{body}"


# --- Hermes layout knowledge ------------------------------------------------
# Read off a real Hermes home (~/.hermes) and from hermes-agent's own source:
#   SOUL.md                     identity slot #1, injected into the system prompt
#   memories/MEMORY.md          the agent's own curated notes, entries joined by
#                               "\n§\n" (tools/memory_tool_store.py:ENTRY_DELIMITER)
#   memories/USER.md            the user profile store (not ours to write)
#   skills/<category>/<name>/SKILL.md
#   cron/jobs.json              cron job records (cron/jobs.py:JOBS_FILE)
#   config.yaml, .env, state.db platform state, not dossier content

SOUL_FILE = "SOUL.md"
MEMORY_DIR = "memories"
MEMORY_FILE = "memories/MEMORY.md"
USER_MEMORY_FILE = "memories/USER.md"
SKILLS_DIR = "skills"
CRON_FILE = "cron/jobs.json"
CRON_OUTPUT_DIR = "cron/output"
CONFIG_FILE = "config.yaml"
# Everything the dossier keeps that no native Hermes slot stores (the id, the
# archived original, the per-field map) lives here, inside the target home.
ARCHIVE_DIR = "dossier"

MEMORY_DELIM = "\n§\n"
ANTI_JOBS_HEADER = "## 反职责（anti_jobs）"

# "[rule · 2026-10-21] fact" — the inline tag standing in for the memory
# entry's kind (enum) and learned (date), which Hermes memory has no fields for.
_TAG_RE = re.compile(r"^\[([^\]]*)\]\s?(.*)$", re.S)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def slugify(text):
    s = re.sub(r"[^\w\- ]", "", (text or "agent").lower(), flags=re.UNICODE)
    return re.sub(r"[\s_]+", "-", s.strip()) or "agent"


def hermes_id(data, home_label=""):
    """HERMES's dossier id policy: Hermes has no platform-level agent id, so the
    adapter mints one from the home's directory name and says so in `excluded`
    (SPEC section 2). Imported dossiers keep the source id instead."""
    return f"hermes-{slugify(home_label)}" if home_label else "hermes-home"


# --- SOUL.md <-> role + anti_jobs -------------------------------------------

def render_soul(role, anti_jobs=None):
    """SOUL.md text: the role verbatim, then the anti_jobs list under a header
    (Hermes has no structured anti_jobs slot; the section keeps the text)."""
    parts = [(role or "").rstrip("\n")]
    if anti_jobs:
        parts.append(ANTI_JOBS_HEADER)
        parts.append("\n".join(f"- {a}" for a in anti_jobs))
    return "\n\n".join(parts) + "\n"


def parse_soul(text):
    """Inverse of render_soul. Returns (role, anti_jobs, residue).

    A SOUL.md without the anti_jobs header is all role — nothing is guessed.
    Anything after the header that is not a "- " bullet is returned as
    `residue`: hand-written text added after import, which the exporter folds
    back into the role instead of dropping it."""
    body = (text or "").replace("\r\n", "\n")
    idx = body.find("\n" + ANTI_JOBS_HEADER)
    if idx == -1 and body.startswith(ANTI_JOBS_HEADER):
        idx = 0
        role = ""
        rest = body[len(ANTI_JOBS_HEADER):]
    elif idx != -1:
        role = body[:idx]
        rest = body[idx + 1 + len(ANTI_JOBS_HEADER):]
    else:
        return body.strip(), [], ""
    anti, residue = [], []
    for ln in rest.split("\n"):
        if ln.startswith("- "):
            if ln[2:].strip():
                anti.append(ln[2:].strip())
        elif ln.strip():
            residue.append(ln.rstrip())
    return role.strip(), anti, "\n".join(residue).strip()


# --- memories/MEMORY.md <-> memory entries ----------------------------------

def render_memory(entries):
    """MEMORY.md text: one entry per line, joined by Hermes' "\\n§\\n" delimiter,
    fact verbatim prefixed by the inline "[kind · learned]" tag."""
    lines = []
    for m in entries or []:
        tag_bits = [b for b in ((m or {}).get("kind"), (m or {}).get("learned")) if b]
        tag = f"[{' · '.join(tag_bits)}] " if tag_bits else ""
        fact = ((m or {}).get("fact") or "").replace("\n", " ")
        lines.append(tag + fact)
    return MEMORY_DELIM.join(lines) + "\n" if lines else ""


def parse_memory(text):
    """Inverse of render_memory. A leading bracket group is only read as a tag
    when every part is a valid kind or an ISO date, so a fact that merely
    starts with "[" keeps its text. Each item carries "_tagged" so the exporter
    can say which entries had no kind/learned tag at all."""
    out = []
    for raw in (text or "").split(MEMORY_DELIM):
        entry = raw.strip()
        if not entry:
            continue
        item = {"fact": entry, "kind": "history", "_tagged": False}
        m = _TAG_RE.match(entry)
        if m:
            parts = [p.strip() for p in m.group(1).split("·") if p.strip()]
            if parts and all(p in KIND or _ISO_DATE_RE.match(p) for p in parts):
                item.pop("kind", None)
                for p in parts:
                    if p in KIND:
                        item["kind"] = p
                    else:
                        item["learned"] = p
                item["fact"] = m.group(2).strip()
                item.setdefault("kind", "history")
                item["_tagged"] = True
        out.append(item)
    return out


# --- cron schedule text <-> Hermes job schedule ------------------------------

_CRON_EXPR_RE = re.compile(
    r"(?<!\S)((?:[0-9A-Za-z*/,?-]+\s+){4,5}[0-9A-Za-z*/,?-]+)(?!\S)")
_TZ_RE = re.compile(r"\(\s*([A-Za-z][A-Za-z0-9_+\-/]*)\s*\)")
_TZ_WORD_RE = re.compile(r"\b(UTC[A-Za-z0-9+\-]*|JST|GMT|EST|PST|[A-Z][A-Za-z]+/[A-Za-z_]+)\b")


def split_schedule(schedule):
    """'0 9 * * 1 (Asia/Tokyo)' -> ('0 9 * * 1', 'Asia/Tokyo').

    Returns (expr or None, tz or None, note). A schedule that is not a cron
    expression (an event description, prose) yields expr None: Hermes cron
    cannot express it and the importer must say so instead of inventing one."""
    text = (schedule or "").strip()
    if not text:
        return None, None, "empty schedule"
    tz = None
    m = _TZ_RE.search(text)
    if m:
        tz = m.group(1)
        stripped = text[:m.start()] + text[m.end():]
    else:
        m = _TZ_WORD_RE.search(text)
        if m:
            tz = m.group(1)
        stripped = text
    m = _CRON_EXPR_RE.search(stripped)
    if not m:
        return None, tz, "not a cron expression"
    expr = " ".join(m.group(1).split())
    fields = expr.split()
    if len(fields) == 6:
        # Hermes' parse_schedule hands 5-6 field expressions to croniter, which
        # reads a 6th leading field as seconds; the dossier's schedules are
        # 5-field plus optional year. Keep the first five and say so.
        note = f"6-field expression, kept first five fields ({' '.join(fields[:5])})"
        return " ".join(fields[:5]), tz, note
    return expr, tz, ""


def next_run_iso(expr):
    """Next fire time for a cron expression, or None.

    Hermes' scheduler computes next_run_at itself (croniter, in the profile's
    timezone) and re-arms a job whose next_run_at is empty on its due scan, so
    leaving it empty is safe. Filling it in when croniter happens to be present
    (it is, inside Hermes' own runtime) keeps `hermes cron doctor` quiet from
    the first minute."""
    try:
        from croniter import croniter
    except Exception:
        return None
    try:
        now = datetime.datetime.now().astimezone()
        nxt = croniter(expr, now).get_next(datetime.datetime)
        return nxt.astimezone().isoformat() if nxt.tzinfo else nxt.replace(
            tzinfo=now.tzinfo).isoformat()
    except Exception:
        return None


def hermes_memory_budget(home):
    """memory_char_limit from the target home's config.yaml (read-only), else
    Hermes' default 2200 (tools/memory_tool.py:store_from_config)."""
    path = home / CONFIG_FILE
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        limit = int(((cfg.get("memory") or {}).get("memory_char_limit")) or 2200)
    except Exception:
        limit = 2200
    return limit
