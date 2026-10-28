#!/usr/bin/env python3
"""Standalone checker for personal-agent-dossier files.

Validates any dossier (file form with YAML front matter, or Notion page
form with a single ```yaml block) without a platform adapter:
  - required fields for the declared spec version
  - fingerprint recomputation (SPEC 2.1) and comparison
  - sensitive-pattern scan (SPEC 5) over role / memory facts / routine prompts
  - UUID references in the body (warning only, SPEC 5.4)

Usage: dossier_check.py <file> [<file> ...]
Exit code: 0 when every file has no errors (warnings are allowed), else 1.
Requires: pyyaml.
"""
import hashlib
import re
import sys

import yaml

SPECS = ("personal-agent-dossier/1.0", "agent-dossier/0.1", "agent-dossier/0.2")
REQUIRED = ("spec", "id", "name", "status", "exported_at", "source", "fingerprint", "role")
SCAN = [
    ("email", r"[\w.+-]+@(?!\d{1,3}(?:\.\d{1,3}){3}\b)[\w-]+\.[\w.]+"),
    ("phone-jp", r"0\d{1,3}-\d{3,4}-\d{4}"),
    ("card-16", r"\b\d{16}\b"),
    ("api-token", r"sk-[A-Za-z0-9]{10,}"),
    ("github-token", r"ghp_\w+"),
    ("password-value", r"(?i)(password|passwd|密码)\s*[:：=]\s*\S+"),
]
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def norm(x):
    # SPEC 2.1: CRLF -> LF, then strip Unicode White_Space. Python's
    # str.strip() strips exactly the White_Space characters.
    return (x or "").replace("\r\n", "\n").strip()


def fingerprint(name, title, role):
    payload = "|".join([norm(name), norm(title or ""), norm(role)])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def extract(text):
    """Return (data dict, body str). Accepts file form or Notion yaml-block form."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end == -1:
            raise ValueError("front matter not terminated")
        return yaml.safe_load(text[3:end]), text[end + 4:]
    blocks = re.findall(r"```yaml\n(.*?)```", text, re.S)
    if len(blocks) != 1:
        raise ValueError("expected exactly one yaml block, found %d" % len(blocks))
    block = blocks[0]
    try:
        data = yaml.safe_load(block)
        if not isinstance(data, dict) or "spec" not in data:
            raise ValueError("not a dossier block")
    except Exception:
        data = yaml.safe_load(block.replace("\\[", "[").replace("\\]", "]"))
    return data, text


def check(path):
    errors, warnings = [], []
    try:
        text = open(path, encoding="utf-8").read()
        data, body = extract(text)
    except Exception as e:
        return ["parse: %s" % e], warnings
    if not isinstance(data, dict):
        return ["parse: front matter is not a mapping"], warnings
    spec = data.get("spec")
    if spec not in SPECS:
        errors.append("spec: unsupported value %r" % (spec,))
    for k in REQUIRED:
        if k not in data or data[k] in (None, ""):
            errors.append("field: required field %r missing or empty" % k)
    if "title" not in data:
        warnings.append("field: optional field 'title' absent (treated as empty by the fingerprint)")
    # fingerprint
    if all(k in data for k in ("name", "role", "fingerprint")):
        want = fingerprint(data.get("name", ""), data.get("title") or "", data.get("role", ""))
        if want != data["fingerprint"]:
            errors.append("fingerprint: declared %s, recomputed %s" % (data["fingerprint"], want))
    # routines / memory shape
    for k in ("routines", "memory"):
        if k in data and data[k] is not None and not isinstance(data[k], list):
            errors.append("field: %r must be a list or null" % k)
    # sensitive scan (SPEC 5): role, memory facts, routine prompts, anti_jobs, excluded
    hay = [("role", data.get("role") or "")]
    for i, m in enumerate(data.get("memory") or []):
        hay.append(("memory[%d].fact" % i, (m or {}).get("fact", "")))
    for i, r in enumerate(data.get("routines") or []):
        hay.append(("routines[%d].prompt" % i, (r or {}).get("prompt", "")))
    for i, a in enumerate(data.get("anti_jobs") or []):
        hay.append(("anti_jobs[%d]" % i, a))
    for label, s in hay:
        for name_, pat in SCAN:
            if re.search(pat, s or ""):
                errors.append("scan: %s hit in %s" % (name_, label))
    # body UUIDs (warning only)
    ref_ids = {str(r.get("id")) for r in (data.get("refs") or []) if isinstance(r, dict)}
    for u in sorted(set(UUID_RE.findall(body or ""))):
        if u != str(data.get("id")) and u not in ref_ids:
            warnings.append("body: UUID %s appears in prose but is not in refs (SPEC 5.4)" % u)
    return errors, warnings


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    bad = 0
    for path in argv[1:]:
        errors, warnings = check(path)
        for w in warnings:
            print("%s: WARN %s" % (path, w))
        for e in errors:
            print("%s: FAIL %s" % (path, e))
        if errors:
            bad += 1
        else:
            print("%s: OK" % path)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
