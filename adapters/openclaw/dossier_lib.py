#!/usr/bin/env python3
"""Shared library for the OpenClaw adapter of personal-agent-dossier.

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
  and back, and how a dossier cron schedule string is read

The SPEC core above the OpenClaw section is byte-for-byte the same
implementation the Hermes and Muse adapters carry (same fingerprint, same
scan, same appendix-A serializer), so dossiers render identically across
adapters. Nothing here touches a real OpenClaw home; path handling stays
in the scripts.
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


# --- OpenClaw layout knowledge ----------------------------------------------
# Read off a real scaffold created by `openclaw onboard` (OpenClaw 2026.6.35)
# and the public cron/workspace documentation:
#   <home>/openclaw.json          config; agents.defaults.workspace and
#                                  agents.list[] = {id, workspace, identity}
#   <home>/workspace/SOUL.md       persona/role, injected at session start
#   <home>/workspace/AGENTS.md     operating manual, hard boundaries
#   <home>/workspace/IDENTITY.md   "- **Name:** ..." bullet fields
#   <home>/workspace/MEMORY.md     curated long-term memory (main session)
#   <home>/workspace/memory/       daily logs (not dossier content)
#   <home>/workspace/skills/<name>/SKILL.md   workspace skills
#   <home>/cron/jobs.json          {"version": 1, "jobs": [...]}; a job is
#                                  {id, agentId, name, enabled, createdAtMs,
#                                  updatedAtMs, schedule, sessionTarget,
#                                  wakeMode, payload, delivery, state}
# The default agent's id is "main"; its workspace is agents.defaults.workspace
# unless agents.list overrides it. The gateway owns job `state` and computes
# next runs itself, so the adapter never writes `state`.
# Everything the dossier keeps that no native OpenClaw slot stores (the
# archived original, import meta) lives under <home>/dossier/<agentId>/.

CONFIG_FILE = "openclaw.json"
WORKSPACE_DIR = "workspace"
SOUL_FILE = "SOUL.md"
AGENTS_FILE = "AGENTS.md"
IDENTITY_FILE = "IDENTITY.md"
MEMORY_FILE = "MEMORY.md"
SKILLS_DIR = "skills"
CRON_FILE = "cron/jobs.json"
ARCHIVE_ROOT = "dossier"
DEFAULT_AGENT_ID = "main"

# The untouched seed SOUL.md that `openclaw onboard` writes carries this line;
# a SOUL.md still containing it (and no dossier marker) is a template, not a
# role, and may be replaced without --replace-soul.
SEED_SOUL_MARK = "You're not a chatbot. You're becoming someone."

_SOUL_MARKER_RE = re.compile(
    r"^<!-- personal-agent-dossier: id=(\S+) source=(\S+) -->\s*$")
_IDENTITY_NAME_RE = re.compile(r"^- \*\*Name:\*\*\s*(.*?)\s*$", re.M)
_IDENTITY_HINT_RE = re.compile(r"^\s*_\(.*\)_\s*$")

ANTI_START = "<!-- personal-agent-dossier:anti-jobs:start -->"
ANTI_END = "<!-- personal-agent-dossier:anti-jobs:end -->"
ANTI_JOBS_HEADER = "## 反职责（anti_jobs）"
MEM_START = "<!-- personal-agent-dossier:memory:start -->"
MEM_END = "<!-- personal-agent-dossier:memory:end -->"


def slugify(text):
    s = re.sub(r"[^\w\- ]", "", (text or "agent").lower(), flags=re.UNICODE)
    return re.sub(r"[\s_]+", "-", s.strip()) or "agent"


def openclaw_id(agent_id):
    """Dossier id for a native-born OpenClaw agent. OpenClaw has platform
    agent ids (the agentId), but they are short local labels ("main"), not
    dossier-grade identifiers, so the adapter mints a slug form and says so
    in `excluded` (SPEC section 2). Imported dossiers keep the source id."""
    return f"openclaw-{slugify(agent_id)}"


# --- config / agent resolution ----------------------------------------------

def _expand(path, home):
    p = path.replace("~", str(home.parent)) if path.startswith("~") else path
    pp = __import__("pathlib").Path(p)
    return pp if pp.is_absolute() else (home / pp)


def list_agents(cfg, home):
    """[(agent_id, workspace Path)] from openclaw.json: the default agent
    (agents.defaults.workspace) plus every agents.list entry."""
    import pathlib
    home = pathlib.Path(home)
    out = []
    defaults = ((cfg.get("agents") or {}).get("defaults") or {})
    if defaults.get("workspace"):
        out.append((DEFAULT_AGENT_ID, _expand(defaults["workspace"], home)))
    for entry in ((cfg.get("agents") or {}).get("list") or []):
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        ws = entry.get("workspace")
        ws_path = _expand(ws, home) if ws else home / WORKSPACE_DIR
        out = [(a, w) for a, w in out if a != entry["id"]]
        out.append((entry["id"], ws_path))
    return out


def resolve_workspace(cfg, home, agent_id):
    """Workspace Path for agent_id, or None if the config does not know it."""
    for aid, ws in list_agents(cfg, home):
        if aid == agent_id:
            return ws
    return None


# --- SOUL.md <-> role ---------------------------------------------------------

def render_soul(role, dossier_id, source):
    marker = f"<!-- personal-agent-dossier: id={dossier_id} source={source} -->"
    return f"{marker}\n\n{(role or '').rstrip()}\n"


def parse_soul(text):
    """Returns (role, marker_id, marker_source, is_seed).
    role is None when the file is still the untouched onboard seed."""
    body = (text or "").replace("\r\n", "\n")
    marker_id = marker_source = None
    lines = body.split("\n")
    if lines and _SOUL_MARKER_RE.match(lines[0].strip()):
        m = _SOUL_MARKER_RE.match(lines[0].strip())
        marker_id, marker_source = m.group(1), m.group(2)
        body = "\n".join(lines[1:]).lstrip("\n")
    if marker_id is None and SEED_SOUL_MARK in body:
        return None, None, None, True
    return body.strip(), marker_id, marker_source, False


# --- AGENTS.md <-> anti_jobs (managed block) ---------------------------------

def render_agents_block(anti_jobs):
    lines = [ANTI_START, ANTI_JOBS_HEADER, ""]
    lines += [f"- {a}" for a in anti_jobs or []]
    lines.append(ANTI_END)
    return "\n".join(lines)


def extract_agents_block(text):
    """(anti_jobs or None, text without the block)."""
    body = (text or "").replace("\r\n", "\n")
    i, j = body.find(ANTI_START), body.find(ANTI_END)
    if i == -1 or j == -1 or j < i:
        return None, body
    inner = body[i + len(ANTI_START):j]
    anti = [ln[2:].strip() for ln in inner.split("\n")
            if ln.startswith("- ") and ln[2:].strip()]
    rest = (body[:i].rstrip() + "\n" + body[j + len(ANTI_END):].lstrip("\n"))
    return anti, rest.strip() + "\n"


def upsert_agents_block(text, anti_jobs):
    _, rest = extract_agents_block(text or "")
    block = render_agents_block(anti_jobs)
    return (rest.rstrip() + "\n\n" + block + "\n") if rest.strip() else block + "\n"


# --- IDENTITY.md <-> name ------------------------------------------------------

def parse_identity_name(text):
    m = _IDENTITY_NAME_RE.search(text or "")
    if not m:
        return None
    if m.group(1):
        return m.group(1).strip()
    # Seed form: value (or the italic hint) sits on the following line.
    tail = (text or "")[m.end():].lstrip("\n").split("\n", 1)[0].strip()
    if not tail or _IDENTITY_HINT_RE.match(tail):
        return None
    return tail.strip("_").strip() or None


def set_identity_name(text, name):
    body = (text or "").replace("\r\n", "\n")
    m = _IDENTITY_NAME_RE.search(body)
    if not m:
        return body
    line = f"- **Name:** {name}"
    if m.group(1):
        return body[:m.start()] + line + body[m.end():]
    # Seed form: also drop the italic hint line that follows.
    tail = body[m.end():]
    stripped = tail.lstrip("\n")
    first = stripped.split("\n", 1)[0]
    if _IDENTITY_HINT_RE.match(first.strip()):
        tail = "\n" + stripped[len(first):].lstrip("\n")
        return body[:m.start()] + line + ("\n" + tail.lstrip("\n") if tail.strip() else "\n")
    return body[:m.start()] + line + body[m.end():]


# --- MEMORY.md <-> memory entries (managed block) ------------------------------

_TAG_RE = re.compile(r"^\[([^\]]*)\]\s?(.*)$", re.S)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def render_memory_block(entries):
    lines = [MEM_START]
    for e in entries or []:
        tag_bits = [b for b in ((e or {}).get("kind"), (e or {}).get("learned")) if b]
        tag = f"[{' · '.join(tag_bits)}] " if tag_bits else ""
        fact = ((e or {}).get("fact") or "").replace("\n", " ")
        lines.append(f"- {tag}{fact}")
    lines.append(MEM_END)
    return "\n".join(lines)


def parse_memory_block(text):
    """Entries from the managed block, or None if there is no block.
    Same tag rule as the Hermes adapter: a leading bracket group counts as a
    [kind · learned] tag only when every part is a valid kind or ISO date."""
    body = (text or "").replace("\r\n", "\n")
    i, j = body.find(MEM_START), body.find(MEM_END)
    if i == -1 or j == -1 or j < i:
        return None
    out = []
    for ln in body[i + len(MEM_START):j].split("\n"):
        if not (ln.startswith("- ") and ln[2:].strip()):
            continue
        entry = ln[2:].strip()
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


def upsert_memory_block(text, entries):
    body = (text or "").replace("\r\n", "\n")
    block = render_memory_block(entries)
    i, j = body.find(MEM_START), body.find(MEM_END)
    if i != -1 and j != -1 and j > i:
        return body[:i] + block + body[j + len(MEM_END):]
    return (body.rstrip() + "\n\n" + block + "\n") if body.strip() else block + "\n"


# --- cron schedule text <-> OpenClaw job schedule ------------------------------

_CRON_EXPR_RE = re.compile(
    r"(?<!\S)((?:[0-9A-Za-z*/,?-]+\s+){4,5}[0-9A-Za-z*/,?-]+)(?!\S)")
_TZ_RE = re.compile(r"\(\s*([A-Za-z][A-Za-z0-9_+\-/]*)\s*\)")
_TZ_WORD_RE = re.compile(r"\b(UTC[A-Za-z0-9+\-]*|JST|GMT|EST|PST|[A-Z][A-Za-z]+/[A-Za-z_]+)\b")


def split_schedule(schedule):
    """'0 9 * * 1 (Asia/Tokyo)' -> ('0 9 * * 1', 'Asia/Tokyo', note).
    A schedule that is not a cron expression yields expr None: OpenClaw cron
    cannot express it and the importer must say so instead of inventing one.
    A 6-field expression keeps its first five fields, with a note (OpenClaw
    cron expressions are 5-field)."""
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
        note = f"6-field expression, kept first five fields ({' '.join(fields[:5])})"
        return " ".join(fields[:5]), tz, note
    return expr, tz, ""


def job_id_for(dossier_id, routine_name):
    """Deterministic OpenClaw job id for a dossier routine, so re-importing
    the same dossier updates the same job instead of duplicating it."""
    import uuid
    return str(uuid.uuid5(uuid.NAMESPACE_URL,
                          f"personal-agent-dossier:openclaw:{dossier_id}:{routine_name}"))


def build_job(dossier_id, agent_id, routine, now_ms, existing=None):
    """One cron/jobs.json job record in OpenClaw's documented shape.
    Returns (job or None, note). `state` is gateway-owned and never written;
    createdAtMs is preserved from `existing` when updating."""
    expr, tz, note = split_schedule((routine or {}).get("schedule"))
    if expr is None:
        return None, f"schedule {((routine or {}).get('schedule') or '')!r}: {note}; not created"
    job = dict(existing) if existing else {}
    job.update({
        "id": (existing or {}).get("id") or job_id_for(dossier_id, routine.get("name") or ""),
        "agentId": agent_id,
        "name": routine.get("name") or "",
        "enabled": (routine.get("state") or "running") != "paused",
        "createdAtMs": (existing or {}).get("createdAtMs") or now_ms,
        "updatedAtMs": now_ms,
        "schedule": {"kind": "cron", "expr": expr, **({"tz": tz} if tz else {})},
        "sessionTarget": "isolated",
        "wakeMode": "now",
        "payload": {"kind": "agentTurn", "message": routine.get("prompt") or ""},
        "delivery": {"mode": "none"},
    })
    job.pop("state", None)
    return job, note
