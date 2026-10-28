#!/usr/bin/env python3
"""Exporter for personal-agent-dossier/1.0 <- Hermes.

Reads one Hermes home (the directory given with --home; nothing else is
touched) and renders a dossier:

  role, anti_jobs   SOUL.md
  memory            memories/MEMORY.md (Hermes' "\\n§\\n" entries)
  routines          cron/jobs.json job records
  id/name/title/... dossier/import-meta.json + dossier/<slug>.dossier.md when
                    the home was populated by import_dossier.py, otherwise the
                    adapter mints an id and says so in `excluded`

Every export:
- recomputes the fingerprint from the live content (never copies it),
- compares it with the archived fingerprint and reports drift,
- runs the SPEC section 5 scan over role / memory facts / routine prompts and
  ABORTS on a hit without writing anything (never auto-rewrites),
- is idempotent: same home and same --date give byte-identical output.

Usage: export_dossier.py --home DIR [--out FILE] [--date YYYY-MM-DD]
                         [--id ID] [--name NAME] [--title TITLE]
"""

import datetime
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dossier_lib as dl


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_text(path, default=""):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return default


def archived_template(home, meta):
    """Fields no live Hermes slot holds (id, name, title, group, status, refs,
    skills, excluded) from the archive this adapter wrote at import time; None
    when the home was never populated from a dossier."""
    if not home.is_dir():
        return None
    candidates = []
    if isinstance(meta, dict) and meta.get("archive"):
        candidates.append(home / str(meta["archive"]))
    arch = home / dl.ARCHIVE_DIR
    if arch.is_dir():
        candidates.extend(sorted(arch.glob("*.dossier.md")))
    for path in candidates:
        if path.exists():
            try:
                data, _ = dl.load_dossier_file(path)
            except Exception:
                continue
            if isinstance(data, dict):
                return data
    return None


def routines_from_home(home, notes):
    """cron/jobs.json -> routine entries. Every job in this home belongs to this
    agent, so every job is exported (not just the ones this adapter created)."""
    data = read_json(home / dl.CRON_FILE, None)
    if data is None:
        return []
    jobs = data.get("jobs") if isinstance(data, dict) else data
    if not isinstance(jobs, list):
        notes.append("cron/jobs.json: unreadable job list, routines exported as none")
        return []
    out = []
    for job in jobs:
        if not isinstance(job, dict):
            continue
        sched = job.get("schedule") if isinstance(job.get("schedule"), dict) else {}
        meta = job.get("dossier") if isinstance(job.get("dossier"), dict) else {}
        tz = meta.get("timezone")
        if sched.get("kind") == "cron" and sched.get("expr"):
            schedule = str(sched["expr"]) + (f" ({tz})" if tz else "")
        elif sched.get("kind") == "once" and sched.get("run_at"):
            schedule = f"once at {sched['run_at']}"
        elif sched.get("kind") == "interval" and sched.get("minutes"):
            schedule = f"every {int(sched['minutes'])}m"
        else:
            schedule = str(job.get("schedule_display") or "?")
        if job.get("state") in ("completed", "error"):
            state = "paused"
            notes.append(f"routine {job.get('name')!r}: job state {job['state']!r} exported as "
                         "'paused' (a finished or failed job is not running and was not deleted)")
        elif job.get("enabled") is False:
            state = "paused"
        else:
            state = "running"
        out.append({
            "id": str(job.get("id") or ""),
            "name": job.get("name") or str(job.get("id") or "cron job"),
            "schedule": schedule,
            "prompt": job.get("prompt") or "",
            "state": state,
        })
    return out


def collect(home, notes):
    """Read what this home exposes. Returns (dossier dict, archived data|None)."""
    soul_path = home / dl.SOUL_FILE
    if not soul_path.exists():
        raise SystemExit(f"no {dl.SOUL_FILE} in {home}: this does not look like a Hermes home")
    role, anti_jobs, residue = dl.parse_soul(read_text(soul_path))
    if residue:
        role = (role + "\n\n" + residue).strip()
        notes.append("SOUL.md: text found after the anti_jobs section is folded back into the "
                     "role (nothing is dropped; the file's structure was changed after import)")

    meta = read_json(home / dl.ARCHIVE_DIR / "import-meta.json", None)
    prev = archived_template(home, meta)

    memory = dl.parse_memory(read_text(home / dl.MEMORY_FILE))
    untagged = [m for m in memory if not m.get("_tagged")]
    routines = routines_from_home(home, notes)

    data: dict = {"spec": "personal-agent-dossier/1.0", "source": "hermes"}
    for key in ("id", "name", "title", "group", "status", "refs", "skills", "excluded"):
        if prev and prev.get(key) is not None:
            data[key] = prev[key]
    data.setdefault("status", "active")

    label = home.name
    if not data.get("name"):
        data["name"] = label
        notes.append(f"name: no archived name in this home; used the home directory name "
                     f"{label!r}")
    if not data.get("id"):
        data["id"] = dl.hermes_id(dict(data), label)
        notes.append(f"id: Hermes has no native agent id; the adapter minted {data['id']!r} "
                     "from the home directory name (SPEC section 2)")

    data["role"] = role
    if anti_jobs:
        data["anti_jobs"] = anti_jobs
    live_memory = [{"fact": m["fact"], **(dict(kind=m["kind"]) if m.get("kind") else {}),
                    **(dict(learned=m["learned"]) if m.get("learned") else {})}
                   for m in memory]
    # null means "not exported last time", not "none" (SPEC section 6): keep it
    # null unless the home now holds entries this agent really has.
    if prev is not None and prev.get("memory") is None and not live_memory:
        data["memory"] = None
        notes.append("memory: the archive says it was never exported (null), and this home still "
                     "has no entries — exported as null, not as an empty list")
    else:
        data["memory"] = live_memory
    if prev is not None and prev.get("routines") is None and not routines:
        data["routines"] = None
        notes.append("routines: the archive says they were never exported (null), and this home "
                     "has no cron jobs — exported as null, not as an empty list")
    else:
        data["routines"] = routines

    if untagged:
        note = (f"没有 kind 标签的 {len(untagged)} 条记忆按 history 导出（Hermes 记忆条目是"
                "纯文本，本身没有 kind 字段）")
        data["excluded"] = "；".join([e for e in [data.get("excluded") or ""] if e] + [note])
    return data, prev


def parse_args(argv):
    opts, positional = {}, []
    i = 0
    flags = {"--home": "home", "--out": "out", "--date": "date",
             "--id": "id", "--name": "name", "--title": "title"}
    while i < len(argv):
        arg = argv[i]
        if arg in flags:
            if i + 1 >= len(argv):
                sys.exit(f"{arg} needs a value")
            opts[flags[arg]] = argv[i + 1]
            i += 2
        else:
            positional.append(arg)
            i += 1
    return opts, positional


def main():
    opts, positional = parse_args(sys.argv[1:])
    if "home" not in opts or positional:
        sys.exit(__doc__)
    home = Path(opts["home"]).expanduser().resolve()

    notes = []
    data, prev = collect(home, notes)
    if opts.get("id"):
        data["id"] = opts["id"]
    if opts.get("name"):
        data["name"] = opts["name"]
    if opts.get("title") is not None:
        data["title"] = opts["title"]
    data["exported_at"] = opts.get("date") or datetime.date.today().isoformat()

    hits = dl.scan_fields(dl.dossier_texts(data))
    if hits:
        for where, pat in hits:
            print(f"ABORT: sensitive pattern {pat} in {where}; export stopped, nothing written "
                  "(SPEC 5.2: report, never auto-rewrite)", file=sys.stderr)
        sys.exit(1)

    missing = [k for k in ("id", "name", "status", "role") if not data.get(k)]
    if missing:
        print("ABORT: this home is missing required content:", ", ".join(missing), file=sys.stderr)
        sys.exit(1)
    if not dl.normalize(data.get("role")):
        print("ABORT: SOUL.md holds no role text", file=sys.stderr)
        sys.exit(1)

    fp = dl.fingerprint(data.get("name"), data.get("title"), data.get("role"))
    if isinstance(prev, dict) and prev.get("fingerprint") and prev["fingerprint"] != fp:
        notes.append(f"drift: archived fingerprint {prev['fingerprint']} -> live {fp}; the role "
                     "changed since import (SPEC section 6 uses this to detect function change)")

    text = dl.render_dossier(data)
    for n in notes:
        print("note:", n, file=sys.stderr)
    if opts.get("out"):
        with open(opts["out"], "w", encoding="utf-8") as f:
            f.write(text)
        mem_n = "null" if data["memory"] is None else len(data["memory"])
        rou_n = "null" if data["routines"] is None else len(data["routines"])
        print(f"wrote {opts['out']} fingerprint {fp} name={data['name']!r} "
              f"id={data['id']!r} memory={mem_n} routines={rou_n}")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
