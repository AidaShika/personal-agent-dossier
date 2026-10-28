#!/usr/bin/env python3
"""Exporter for personal-agent-dossier/1.0 <- Muse.

Two modes:

1) --snapshot SNAPSHOT.json --out FILE
   Render a dossier from a snapshot JSON the Muse agent assembled from
   sources it can actually read itself (its identity files, its own skill
   list, its cron inventory). The script never reaches into platform stores
   on its own. Fields the snapshot leaves out are written as null for
   routines/memory ("not exported this time" — NOT the same as none) or
   omitted for optional fields, per SPEC sections 2-4.

2) --from-staging DIR --out FILE
   Rebuild a dossier from an importer staging directory (meta.json +
   SKILL.md.draft + memory-test.md + routines-plan.json). This is the
   second half of the round-trip test: import scribe -> stage -> export.

Both modes:
- run the SPEC section 5 sensitive scan over role / memory facts / routine
  prompts and ABORT on any hit (never auto-rewrite)
- recompute the fingerprint from content
- are idempotent: same input and same --date give byte-identical output
  (SPEC section 6); without --date, today's date is used for exported_at
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dossier_lib as dl

MEM_LINE = re.compile(r"^- (?:\[(?P<tag>[^\]]+)\] )?(?P<fact>.*)$")
KIND_WORDS = {"rule", "preference", "decision", "history"}


def parse_memory_test(text):
    """Inverse of the importer's staging format: '- [kind · learned] fact'."""
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = MEM_LINE.match(line)
        if not m:
            continue
        entry = {"fact": m.group("fact"), "kind": "history"}
        tag = (m.group("tag") or "").strip()
        if tag:
            parts = [p.strip() for p in tag.split("·")]
            for p in parts:
                if p in KIND_WORDS:
                    entry["kind"] = p
                elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", p):
                    entry["learned"] = p
        out.append(entry)
    return out


def parse_skill_draft(text):
    """Extract the role section and anti_jobs list from a staged SKILL.md draft."""
    role, anti = "", []
    section = None
    buf = []
    for line in text.splitlines():
        if line.startswith("## "):
            if section == "role":
                role = "\n".join(buf).strip()
            section = "role" if "role" in line else ("anti" if "anti_jobs" in line else None)
            buf = []
            continue
        if section == "role":
            buf.append(line)
        elif section == "anti" and line.startswith("- "):
            anti.append(line[2:])
    if section == "role":
        role = "\n".join(buf).strip()
    return role, anti


def from_staging(stage_dir):
    meta = json.load(open(os.path.join(stage_dir, "meta.json"), encoding="utf-8"))
    skill = open(os.path.join(stage_dir, "SKILL.md.draft"), encoding="utf-8").read()
    role, anti = parse_skill_draft(skill)
    data = {"spec": "personal-agent-dossier/1.0", "source": "muse"}
    for k in ("id", "name", "title", "group", "status", "skills", "refs", "excluded"):
        if meta.get(k) is not None:
            data[k] = meta[k]
    data["role"] = role
    if anti:
        data["anti_jobs"] = anti
    mem_path = os.path.join(stage_dir, "memory-test.md")
    plan = json.load(open(os.path.join(stage_dir, "routines-plan.json"), encoding="utf-8"))
    orig = _orig_meta_nulls(stage_dir)
    mem_text = ""
    if os.path.exists(mem_path):
        mem_text = open(mem_path, encoding="utf-8").read()
    if orig.get("memory_null"):
        data["memory"] = None
    elif mem_text.strip():
        data["memory"] = parse_memory_test(mem_text)
    else:
        data["memory"] = []
    data["routines"] = None if orig.get("routines_null") else plan.get("routines")
    return data


def _orig_meta_nulls(stage_dir):
    """The staging meta.json drops None fields; the dossier copy keeps them.
    Read null-ness of routines/memory back from the staged dossier copy."""
    copy_path = os.path.join(stage_dir, "dossier-copy.md")
    out = {"routines_null": False, "memory_null": False}
    if os.path.exists(copy_path):
        data, _ = dl.load_dossier_file(copy_path)
        out["routines_null"] = data.get("routines") is None
        out["memory_null"] = data.get("memory") is None
    return out


def from_snapshot(path):
    snap = json.load(open(path, encoding="utf-8"))
    data = {"spec": "personal-agent-dossier/1.0", "source": "muse"}
    for k in ("id", "name", "title", "group", "status", "role", "anti_jobs",
              "routines", "memory", "refs", "skills", "excluded"):
        if k in snap:
            data[k] = snap[k]
    return data


def main():
    args = sys.argv[1:]
    date = datetime.date.today().isoformat()
    if "--date" in args:
        i = args.index("--date")
        date = args[i + 1]
        del args[i:i + 2]
    out_path = None
    if "--out" in args:
        i = args.index("--out")
        out_path = args[i + 1]
        del args[i:i + 2]
    if "--snapshot" in args:
        data = from_snapshot(args[args.index("--snapshot") + 1])
    elif "--from-staging" in args:
        data = from_staging(args[args.index("--from-staging") + 1])
    else:
        sys.exit(__doc__)
    data["exported_at"] = date
    hits = dl.scan_fields(dl.dossier_texts(data))
    if hits:
        for where, pat in hits:
            print(f"ABORT: sensitive pattern {pat} in {where}; export stopped, "
                  "nothing written (SPEC 5.2: report, never auto-rewrite)")
        sys.exit(1)
    missing = [k for k in ("id", "name", "status", "role") if not data.get(k)]
    if missing:
        print("ABORT: snapshot/staging is missing required fields:", ", ".join(missing))
        sys.exit(1)
    text = dl.render_dossier(data)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {out_path} fingerprint {dl.fingerprint(data.get('name'), data.get('title'), data.get('role'))}")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
