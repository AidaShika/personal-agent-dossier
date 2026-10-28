#!/usr/bin/env python3
"""Shared library for the OpenClaw adapter of personal-agent-dossier.

Two halves:

1. The SPEC core, byte-for-byte the same implementation the Hermes and Muse
   adapters carry: SPEC 2.1 fingerprint, the three storage forms from SPEC 1,
   SPEC 5 sensitive scan, validation, and appendix-A deterministic rendering.
2. OpenClaw layout knowledge, read off a real OpenClaw 2026.6.35 home:
   - `<home>/openclaw.json` with `agents.defaults.workspace` and
     `agents.list[] = {id, workspace, identity, default}`.
   - one workspace per agent containing SOUL.md (role), AGENTS.md
     (anti_jobs managed block), IDENTITY.md (name), MEMORY.md (memory
     managed block), skills/<name>/SKILL.md.
   - cron jobs live in the shared SQLite state database
     `<home>/state/openclaw.sqlite`, table `cron_jobs`, keyed by
     `(store_key, job_id)`, with `store_key = <cron.store or
     <home>/cron/jobs.json>`. Each row carries both flattened columns and a
     canonical `job_json`. The legacy JSON file is only an import input:
     a gateway start imports it once and renames it `jobs.json.migrated`.
     This adapter writes SQLite when the database/table exists and otherwise
     writes the legacy JSON file, which the platform imports on next start.

Nothing here touches a real home; path handling stays in the scripts.
"""

import datetime
import hashlib
import json
import os
import re
import sqlite3
import uuid
from pathlib import Path

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
# password-value rule SPEC 5.2 names in prose. `dossier_texts` is a superset
# of SPEC's required set: anti_jobs is scanned too because the repository
# checker scans it and an import must not create a home the checker rejects.

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
    """Texts scanned before export/import: role, anti_jobs, memory facts,
    routine prompts."""
    texts = [("role", data.get("role"))]
    for i, a in enumerate(data.get("anti_jobs") or []):
        texts.append((f"anti_jobs[{i}]", a))
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
# Verified on OpenClaw 2026.6.35 (see adapter-report.md for the commands):
#   <home>/openclaw.json   agents.defaults.workspace; agents.list[] entries
#                          {id, workspace, identity, default}
#   <home>/workspace/...   SOUL.md, AGENTS.md, IDENTITY.md, MEMORY.md,
#                          skills/<name>/SKILL.md
#   <home>/state/openclaw.sqlite
#                          cron_jobs table; one row per job, columns plus a
#                          canonical job_json. store_key defaults to
#                          <home>/cron/jobs.json and can be overridden by
#                          cron.store. The gateway computes next_run_at_ms.
#   <home>/cron/jobs.json  legacy import format; the gateway imports it once
#                          and renames it jobs.json.migrated.
#
# A dossier pairs with one OpenClaw agent id. Multi-agent homes keep one
# workspace per agent and one shared cron database, filtered by agent_id.

CONFIG_FILE = "openclaw.json"
WORKSPACE_DIR = "workspace"
SOUL_FILE = "SOUL.md"
AGENTS_FILE = "AGENTS.md"
IDENTITY_FILE = "IDENTITY.md"
MEMORY_FILE = "MEMORY.md"
SKILLS_DIR = "skills"
STATE_DB = "state/openclaw.sqlite"
LEGACY_CRON_FILE = "cron/jobs.json"
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
    """Dossier id for a native-born OpenClaw agent. OpenClaw has platform agent
    ids, but they are short local labels ("main"), so the adapter mints a slug
    form and says so in `excluded` (SPEC section 2). Imported dossiers keep
    the source id."""
    return f"openclaw-{slugify(agent_id)}"


# --- config / agent resolution ----------------------------------------------

def load_config(home):
    p = Path(home) / CONFIG_FILE
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _expand(raw, home):
    """Expand ~ and make a relative path relative to the home directory."""
    p = Path(os.path.expanduser(str(raw).strip()))
    return p if p.is_absolute() else (Path(home) / p)


def _agent_entries(cfg):
    agents = (cfg.get("agents") or {})
    entries = agents.get("list") or []
    if isinstance(entries, dict):  # tolerate an id-keyed map
        entries = [dict(v, id=k) for k, v in entries.items() if isinstance(v, dict)]
    return [e for e in entries if isinstance(e, dict) and e.get("id")]


def default_agent_id(cfg):
    entries = _agent_entries(cfg)
    if not entries:
        return DEFAULT_AGENT_ID
    for e in entries:
        if e.get("default"):
            return str(e["id"]).strip()
    return str(entries[0]["id"]).strip() or DEFAULT_AGENT_ID


def resolve_workspace(cfg, home, agent_id):
    """Workspace Path for agent_id, or None when the id is not configured.
    Mirrors OpenClaw's resolution: entry.workspace, else the default agent's
    defaults.workspace (or <home>/workspace), else <defaults.workspace>/<id>,
    else <home>/workspace-<id>."""
    home = Path(home)
    aid = str(agent_id).strip()
    defaults = ((cfg.get("agents") or {}).get("defaults") or {})
    base = defaults.get("workspace")
    entry = next((e for e in _agent_entries(cfg) if str(e.get("id")).strip() == aid), None)
    if entry and entry.get("workspace"):
        return _expand(entry["workspace"], home)
    if aid == default_agent_id(cfg):
        return _expand(base, home) if base else home / WORKSPACE_DIR
    if entry is None:
        return None
    if base:
        return _expand(base, home) / aid
    return home / f"workspace-{aid}"


def list_agents(cfg, home):
    """[(agent_id, workspace Path)] in config order, default first."""
    aids = [default_agent_id(cfg)] + [str(e["id"]).strip() for e in _agent_entries(cfg)]
    out, seen = [], set()
    for aid in aids:
        if not aid or aid in seen:
            continue
        ws = resolve_workspace(cfg, home, aid)
        if ws is not None:
            out.append((aid, ws))
            seen.add(aid)
    return out


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
    A leading bracket group counts as a [kind · learned] tag only when every
    part is a valid kind or ISO date; otherwise the whole line is the fact."""
    body = (text or "").replace("\r\n", "\n")
    i, j = body.find(MEM_START), body.find(MEM_END)
    if i == -1 or j == -1 or j < i:
        return None
    out = []
    for ln in body[i + len(MEM_START):j].split("\n"):
        if not (ln.startswith("- ") and ln[2:].strip()):
            continue
        entry = ln[2:].strip()
        item = {"fact": entry, "kind": "history"}
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
        out.append(item)
    return out


def upsert_memory_block(text, entries):
    body = (text or "").replace("\r\n", "\n")
    block = render_memory_block(entries)
    i, j = body.find(MEM_START), body.find(MEM_END)
    if i != -1 and j != -1 and j > i:
        return body[:i] + block + body[j + len(MEM_END):]
    return (body.rstrip() + "\n\n" + block + "\n") if body.strip() else block + "\n"


# --- dossier cron schedule text <-> OpenClaw job schedule ---------------------

_CRON_EXPR_RE = re.compile(
    r"(?<!\S)((?:[0-9A-Za-z*/,?+-]+\s+){4,5}[0-9A-Za-z*/,?+-]+)(?!\S)")
_TZ_RE = re.compile(r"\(\s*([A-Za-z][A-Za-z0-9_+\-/]*)\s*\)")
_TZ_WORD_RE = re.compile(r"\b(UTC[A-Za-z0-9+\-]*|JST|GMT|EST|PST|[A-Z][A-Za-z]+/[A-Za-z_]+)\b")


def split_schedule(schedule):
    """'0 9 * * 1 (Asia/Tokyo)' -> ('0 9 * * 1', 'Asia/Tokyo', note).

    OpenClaw accepts 5-field and 6-field cron expressions (2026.6.35), so both
    are kept verbatim. A schedule that is not a cron expression yields expr
    None: the importer must say so instead of inventing a job.
    """
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
    if len(fields) not in (5, 6):
        return None, tz, f"{len(fields)}-field expression; OpenClaw cron takes 5 or 6 fields"
    return expr, tz, ""


def job_id_for(dossier_id, routine_name):
    """Deterministic OpenClaw job id for a dossier routine, so re-importing
    the same dossier updates the same job instead of duplicating it."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL,
                          f"personal-agent-dossier:openclaw:{dossier_id}:{routine_name}"))


def build_job(dossier_id, agent_id, routine, now_ms, existing=None):
    """One cron job record in OpenClaw's job_json shape.
    Returns (job or None, note). `state` is gateway-owned and starts empty;
    createdAtMs is preserved from `existing` when updating."""
    expr, tz, note = split_schedule((routine or {}).get("schedule"))
    if expr is None:
        return None, f"schedule {((routine or {}).get('schedule') or '')!r}: {note}; not created"
    job = {
        "id": (existing or {}).get("id") or job_id_for(dossier_id, routine.get("name") or ""),
        "agentId": agent_id,
        "name": routine.get("name") or "",
        "enabled": (routine.get("state") or "running") != "paused",
        "createdAtMs": (existing or {}).get("createdAtMs") or now_ms,
        "schedule": {"kind": "cron", "expr": expr, **({"tz": tz} if tz else {})},
        "sessionTarget": "isolated",
        "wakeMode": "now",
        "payload": {"kind": "agentTurn", "message": routine.get("prompt") or ""},
        "delivery": {"mode": "none"},
        "state": {},
    }
    return job, note


# --- cron store: SQLite (current) and legacy JSON (import input) --------------

def state_db_path(home):
    return Path(home) / STATE_DB


def cron_store_path(cfg, home):
    """Logical cron store key and legacy import path."""
    raw = ((cfg.get("cron") or {}).get("store") or "").strip()
    if raw:
        return _expand(raw, home)
    return Path(home) / LEGACY_CRON_FILE


def _sqlite_cron_rows(home, cfg):
    """Rows from the shared state DB, or None when the DB/table is absent.
    A read failure raises DossierError instead of looking like "no jobs"."""
    db_path = state_db_path(home)
    if not db_path.exists():
        return None
    key = str(cron_store_path(cfg, home).resolve())
    try:
        # Open read-write even for reads: after a gateway exit the WAL file may
        # need recovery, and SQLite refuses a read-only connection in that
        # state ("unable to open database file"). We still only SELECT here.
        con = sqlite3.connect(db_path, timeout=30)
        try:
            con.execute("PRAGMA busy_timeout = 30000")
            has = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cron_jobs'"
            ).fetchone()
            if not has:
                return None
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute(
                "SELECT * FROM cron_jobs WHERE store_key = ? ORDER BY sort_order, updated_at, job_id",
                (key,))]
        finally:
            con.close()
    except sqlite3.Error as e:
        raise DossierError(f"cannot read cron store {db_path}: {e}")


def _legacy_jobs(path):
    if not Path(path).exists():
        return []
    try:
        store = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return []
    return list(store.get("jobs") or []) if isinstance(store, dict) else []


def load_cron_jobs(home, cfg):
    """[(job dict, backend)] sorted by store order. SQLite wins when present;
    otherwise the legacy JSON file is read."""
    rows = _sqlite_cron_rows(home, cfg)
    if rows is not None:
        out = []
        for row in rows:
            try:
                job = json.loads(row.get("job_json") or "{}")
            except Exception:
                job = {}
            if not isinstance(job, dict) or not job.get("id"):
                job = {
                    "id": row.get("job_id"), "agentId": row.get("agent_id"),
                    "name": row.get("name"), "enabled": bool(row.get("enabled")),
                    "createdAtMs": row.get("created_at_ms"),
                    "schedule": {"kind": row.get("schedule_kind"),
                                 "expr": row.get("schedule_expr"),
                                 **({"tz": row.get("schedule_tz")}
                                    if row.get("schedule_tz") else {})},
                    "sessionTarget": row.get("session_target"),
                    "wakeMode": row.get("wake_mode"),
                    "payload": {"kind": row.get("payload_kind"),
                                "message": row.get("payload_message")},
                    "delivery": {"mode": row.get("delivery_mode") or "none"},
                }
            out.append(job)
        return out, "sqlite"
    return _legacy_jobs(cron_store_path(cfg, home)), "legacy"


_JOB_COLUMNS = [
    "store_key", "job_id", "name", "description", "enabled", "delete_after_run",
    "created_at_ms", "agent_id", "session_key", "schedule_kind", "schedule_expr",
    "schedule_tz", "every_ms", "anchor_ms", "at", "stagger_ms", "session_target",
    "wake_mode", "payload_kind", "payload_message", "payload_model",
    "payload_fallbacks_json", "payload_thinking", "payload_timeout_seconds",
    "payload_allow_unsafe_external_content", "payload_external_content_source_json",
    "payload_light_context", "payload_tools_allow_json", "delivery_mode",
    "delivery_channel", "delivery_to", "delivery_thread_id", "delivery_account_id",
    "delivery_best_effort", "delivery_completion_mode", "delivery_completion_to",
    "failure_delivery_mode", "failure_delivery_channel", "failure_delivery_to",
    "failure_delivery_account_id", "failure_alert_disabled", "failure_alert_after",
    "failure_alert_channel", "failure_alert_to", "failure_alert_cooldown_ms",
    "failure_alert_include_skipped", "failure_alert_mode", "failure_alert_account_id",
    "next_run_at_ms", "job_json", "state_json", "runtime_updated_at_ms",
    "schedule_identity", "sort_order", "updated_at",
]


def _bool(v):
    return None if v is None else (1 if v else 0)


def _json_or_none(v):
    return None if v is None else json.dumps(v, ensure_ascii=False)


def _row_from_job(store_key, job, now_ms, existing=None, sort_order=0):
    """Flatten a job_json-shaped record into cron_jobs columns, the same
    projection the gateway writes (see openclaw-state-db backfill)."""
    existing = existing or {}
    sched = job.get("schedule") or {}
    payload = job.get("payload") or {}
    delivery = job.get("delivery") or {}
    kind = sched.get("kind")
    job_json = {k: job.get(k) for k in
                ("id", "agentId", "name", "enabled", "createdAtMs", "schedule",
                 "sessionTarget", "wakeMode", "payload", "delivery")}
    job_json = {k: v for k, v in job_json.items() if v is not None}
    job_json["state"] = {}
    schedule_identity = json.dumps(
        {"version": 1, "enabled": job.get("enabled", True), "schedule": sched},
        ensure_ascii=False, separators=(",", ":"))
    return {
        "store_key": store_key,
        "job_id": job["id"],
        "name": job.get("name") or "",
        "description": job.get("description"),
        "enabled": 0 if job.get("enabled") is False else 1,
        "delete_after_run": _bool(job.get("deleteAfterRun")),
        "created_at_ms": existing.get("created_at_ms") or job.get("createdAtMs") or now_ms,
        "agent_id": job.get("agentId"),
        "session_key": job.get("sessionKey"),
        "schedule_kind": kind or "cron",
        "schedule_expr": sched.get("expr") if kind == "cron" else None,
        "schedule_tz": sched.get("tz") if kind == "cron" else None,
        "every_ms": sched.get("everyMs") if kind == "every" else None,
        "anchor_ms": sched.get("anchorMs") if kind == "every" else None,
        "at": sched.get("at") if kind == "at" else None,
        "stagger_ms": sched.get("staggerMs") if kind == "cron" else None,
        "session_target": job.get("sessionTarget") or "isolated",
        "wake_mode": job.get("wakeMode") or "now",
        "payload_kind": payload.get("kind") or "agentTurn",
        "payload_message": payload.get("message"),
        "payload_model": payload.get("model"),
        "payload_fallbacks_json": _json_or_none(payload.get("fallbacks")),
        "payload_thinking": payload.get("thinking"),
        "payload_timeout_seconds": payload.get("timeoutSeconds"),
        "payload_allow_unsafe_external_content": _bool(payload.get("allowUnsafeExternalContent")),
        "payload_external_content_source_json": _json_or_none(payload.get("externalContentSource")),
        "payload_light_context": _bool(payload.get("lightContext")),
        "payload_tools_allow_json": _json_or_none(payload.get("toolsAllow")),
        "delivery_mode": delivery.get("mode") or "none",
        "delivery_channel": delivery.get("channel"),
        "delivery_to": delivery.get("to"),
        "delivery_thread_id": delivery.get("threadId"),
        "delivery_account_id": delivery.get("accountId"),
        "delivery_best_effort": _bool(delivery.get("bestEffort")),
        "delivery_completion_mode": (delivery.get("completionDestination") or {}).get("mode"),
        "delivery_completion_to": (delivery.get("completionDestination") or {}).get("to"),
        "failure_delivery_mode": (delivery.get("failureDestination") or {}).get("mode"),
        "failure_delivery_channel": (delivery.get("failureDestination") or {}).get("channel"),
        "failure_delivery_to": (delivery.get("failureDestination") or {}).get("to"),
        "failure_delivery_account_id": (delivery.get("failureDestination") or {}).get("accountId"),
        "failure_alert_disabled": (1 if job.get("failureAlert") is False else
                                    0 if isinstance(job.get("failureAlert"), dict) else None),
        "failure_alert_after": (job.get("failureAlert") or {}).get("after")
        if isinstance(job.get("failureAlert"), dict) else None,
        "failure_alert_channel": (job.get("failureAlert") or {}).get("channel")
        if isinstance(job.get("failureAlert"), dict) else None,
        "failure_alert_to": (job.get("failureAlert") or {}).get("to")
        if isinstance(job.get("failureAlert"), dict) else None,
        "failure_alert_cooldown_ms": (job.get("failureAlert") or {}).get("cooldownMs")
        if isinstance(job.get("failureAlert"), dict) else None,
        "failure_alert_include_skipped": _bool((job.get("failureAlert") or {}).get("includeSkipped"))
        if isinstance(job.get("failureAlert"), dict) else None,
        "failure_alert_mode": (job.get("failureAlert") or {}).get("mode")
        if isinstance(job.get("failureAlert"), dict) else None,
        "failure_alert_account_id": (job.get("failureAlert") or {}).get("accountId")
        if isinstance(job.get("failureAlert"), dict) else None,
        "next_run_at_ms": None,
        "job_json": json.dumps(job_json, ensure_ascii=False, separators=(",", ":")),
        "state_json": "{}",
        "runtime_updated_at_ms": now_ms,
        "schedule_identity": schedule_identity,
        "sort_order": existing.get("sort_order", sort_order) or 0,
        "updated_at": now_ms,
    }


def save_cron_jobs(home, cfg, jobs, delete_ids=(), now_ms=None):
    """Upsert `jobs` and delete `delete_ids` in the real cron store.

    Returns (backend, written_count, deleted_count). If the SQLite DB/table
    exists, rows are written there; otherwise the legacy JSON file is written
    and the platform imports it on next start. Only rows whose store_key
    matches this home's cron store are touched.
    """
    now_ms = now_ms or int(datetime.datetime.now().timestamp() * 1000)
    store_path = cron_store_path(cfg, home)
    key = str(store_path.resolve())
    rows = _sqlite_cron_rows(home, cfg)
    if rows is not None:
        db_path = state_db_path(home)
        con = sqlite3.connect(db_path, timeout=30)
        try:
            con.execute("PRAGMA busy_timeout = 30000")
            existing = {}
            con.row_factory = sqlite3.Row
            for r in con.execute("SELECT * FROM cron_jobs WHERE store_key = ?", (key,)):
                existing[r["job_id"]] = dict(r)
            written = deleted = 0
            for job in jobs:
                cols = _row_from_job(key, job, now_ms, existing.get(job["id"]),
                                     sort_order=len(existing))
                placeholders = ", ".join("?" for _ in _JOB_COLUMNS)
                updates = ", ".join(f"{c}=excluded.{c}" for c in _JOB_COLUMNS
                                    if c not in ("store_key", "job_id"))
                con.execute(
                    f"INSERT INTO cron_jobs ({', '.join(_JOB_COLUMNS)}) VALUES ({placeholders}) "
                    f"ON CONFLICT(store_key, job_id) DO UPDATE SET {updates}",
                    [cols[c] for c in _JOB_COLUMNS])
                written += 1
            for jid in delete_ids:
                cur = con.execute(
                    "DELETE FROM cron_jobs WHERE store_key = ? AND job_id = ?", (key, jid))
                deleted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            con.commit()
        finally:
            con.close()
        return "sqlite", written, deleted

    # Legacy JSON: merge by id, keep foreign jobs untouched.
    store = {"version": 1, "jobs": []}
    if store_path.exists():
        try:
            store = json.loads(store_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise DossierError(f"legacy cron store unreadable: {e}")
        store.setdefault("version", 1)
        store.setdefault("jobs", [])
    by_id = {j.get("id"): j for j in store["jobs"] if isinstance(j, dict)}
    for job in jobs:
        by_id[job["id"]] = job
    for jid in delete_ids:
        by_id.pop(jid, None)
    store["jobs"] = list(by_id.values())
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    return "legacy", len(jobs), len(delete_ids)


def cron_backend_label(home, cfg):
    """Human label for the plan, without writing anything."""
    rows = _sqlite_cron_rows(home, cfg)
    if rows is not None:
        return f"SQLite {state_db_path(home)} (cron_jobs)"
    return f"legacy JSON {cron_store_path(cfg, home)} (imported on next gateway start)"
