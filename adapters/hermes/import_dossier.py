#!/usr/bin/env python3
"""Importer for personal-agent-dossier/1.0 (and legacy agent-dossier/0.1, 0.2) -> Hermes.

Default is a dry run: it reads one dossier (front matter file, bare YAML, or
Notion page text holding exactly one ```yaml block), runs every SPEC check,
and prints the import plan plus the loss/downgrade list. Nothing is created or
modified.

With --apply --target-home DIR it writes the dossier into that Hermes home,
using Hermes' own layout:
  SOUL.md                     role verbatim + anti_jobs section
  memories/MEMORY.md          one entry per fact, "[kind · learned] fact"
  cron/jobs.json              routines as Hermes cron job records
  dossier/<slug>.dossier.md   the archived original (every field, verbatim)
  dossier/import-meta.json    the field map, the minted/kept ids, and the
                              bookkeeping that makes re-import an update by id

--target-home only ever points at the directory given on the command line.
Writing into a live Hermes home replaces that home's identity file, so a
pre-existing SOUL.md that this adapter did not write requires --replace-soul.

Level: this adapter declares L2 for the deployment shape it implements — one
dossier per Hermes home. Sync by id, cron creation and memory writes are real
Hermes mechanisms; see adapter-report.md section 1 for the caveats.

Usage: import_dossier.py FILE [--target-home DIR] [--apply] [--replace-soul]
"""

import datetime
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dossier_lib as dl

LEVEL_LINE = ("platform level: L2 (Hermes: one dossier per home; role -> SOUL.md, "
              "facts -> memories/MEMORY.md, routines -> cron/jobs.json, re-import "
              "updates by id; cron ids and memory dates still change)")

# field -> (where it lands in a Hermes home, fidelity, note)
FIELD_MAP = [
    ("id", "dossier/import-meta.json", "recorded",
     "Hermes has no platform-level agent id; the source id is kept verbatim and "
     "is what a re-import pairs on"),
    ("name", "dossier/import-meta.json, dossier/<slug>.dossier.md", "verbatim",
     "Hermes names an agent by its home directory, not by a display name"),
    ("title", "dossier/import-meta.json, dossier/<slug>.dossier.md", "downgraded",
     "no title slot; kept in the archive, folded into no live field"),
    ("group", "dossier/<slug>.dossier.md", "stored-nowhere-live",
     "Hermes has no sidebar/section grouping"),
    ("status", "dossier/import-meta.json", "recorded",
     "documentary; a retired dossier still imports"),
    ("exported_at", "dossier/import-meta.json", "recorded", "documentary"),
    ("source", "dossier/import-meta.json", "recorded",
     "part of the pairing key together with id"),
    ("fingerprint", "dossier/import-meta.json", "recomputed",
     "recomputed on every import and compared with the file; a mismatch refuses"),
    ("role", "SOUL.md", "verbatim",
     "SOUL.md is Hermes' identity slot and is injected into the system prompt"),
    ("anti_jobs", "SOUL.md (## 反职责（anti_jobs） section)", "downgraded",
     "plain text section, no structured field; content is verbatim"),
    ("routines", "cron/jobs.json", "downgraded",
     "Hermes cron job records; ids are assigned by the adapter, state maps to "
     "enabled/paused, next_run_at is left for Hermes to compute"),
    ("memory", "memories/MEMORY.md", "downgraded",
     "Hermes' §-delimited memory entries; kind/learned become an inline "
     "[kind · learned] tag, fact text is verbatim"),
    ("refs", "dossier/<slug>.dossier.md", "stored-nowhere-live",
     "ids do not resolve on Hermes; names are listed for a human to re-match"),
    ("skills", "dossier/import-meta.json + skills/ presence check", "downgraded",
     "only names travel; a same-named skill must already exist under skills/"),
    ("excluded", "dossier/<slug>.dossier.md", "verbatim", "documentary"),
]


def hermes_paths(home):
    return {
        "soul": home / dl.SOUL_FILE,
        "memory_dir": home / dl.MEMORY_DIR,
        "memory": home / dl.MEMORY_FILE,
        "user_memory": home / dl.USER_MEMORY_FILE,
        "skills": home / dl.SKILLS_DIR,
        "cron_dir": home / dl.CRON_FILE.rsplit("/", 1)[0],
        "cron": home / dl.CRON_FILE,
        "cron_output": home / dl.CRON_OUTPUT_DIR,
        "archive": home / dl.ARCHIVE_DIR,
        "meta": home / dl.ARCHIVE_DIR / "import-meta.json",
    }


def load_meta(home):
    path = hermes_paths(home)["meta"]
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_jobs(home):
    """{'jobs': [...], 'updated_at': ...} from cron/jobs.json; Hermes also
    accepts a bare list, so keep whichever shape we found."""
    path = hermes_paths(home)["cron"]
    data = read_json(path, None)
    if isinstance(data, dict):
        jobs = data.get("jobs")
        return [j for j in jobs if isinstance(j, dict)] if isinstance(jobs, list) else [], data
    if isinstance(data, list):
        return [j for j in data if isinstance(j, dict)], {"jobs": data}
    return [], None


def installed_skills(home):
    """Skill names a Hermes home can load: directory names plus the `name:` of
    each SKILL.md front matter, one level of category dirs deep."""
    root = hermes_paths(home)["skills"]
    names = set()
    if not root.is_dir():
        return names
    for path in root.rglob("SKILL.md"):
        names.add(path.parent.name.lower())
        try:
            head = path.read_text(encoding="utf-8").split("---")[1]
        except Exception:
            continue
        for line in head.splitlines():
            if line.strip().startswith("name:"):
                names.add(line.split(":", 1)[1].strip().strip("'\"\"'").lower())
    return names


def build_plan(data, home, meta, existing_jobs):
    """Returns (plan, loss) lines. Pure read: no writes."""
    plan, loss = [], []
    target = str(home) if home else "<target-home not given>"
    name = data.get("name") or "agent"
    slug = dl.slugify(name)

    soul = hermes_paths(home)["soul"] if home else None
    if soul is not None and soul.exists() and meta is None and soul.read_text(encoding="utf-8").strip():
        plan.append(f"{dl.SOUL_FILE}: exists and was not written by this adapter "
                    f"({len(soul.read_text(encoding='utf-8'))} chars) — --apply will refuse "
                    "unless --replace-soul is given, in which case the old file is kept as "
                    "SOUL.md.pre-dossier")
    else:
        plan.append(f"{dl.SOUL_FILE}: write role verbatim, then a "
                    f"'{dl.ANTI_JOBS_HEADER}' section for anti_jobs — SOUL.md is Hermes' "
                    "identity slot, injected into every session's system prompt")
    loss.append(f"id: Hermes keys an agent by its home directory, not by a dossier id; the "
                f"source id ({data.get('id')!r}) is kept verbatim in "
                "dossier/import-meta.json and dossier/<slug>.dossier.md, and a re-import "
                "pairs on source+id")
    if data.get("title"):
        loss.append(f"title: no title slot in Hermes; {data['title']!r} is kept in the archive "
                    "only (it is not used for matching, pairing, or display)")
    if data.get("group"):
        loss.append(f"group {data['group']!r}: Hermes has no section/grouping concept; kept in "
                    "the archive only")
    if data.get("anti_jobs"):
        loss.append(f"anti_jobs ({len(data['anti_jobs'])}): no structured field on Hermes; kept "
                    "as a plain text section in SOUL.md (content verbatim, structure gone)")

    routines = data.get("routines")
    if routines is None:
        loss.append("routines: not exported (null) — 未导出，不等于没有. The archived copy is "
                    "kept and no cron job is planned.")
    elif not routines:
        plan.append("routines: [] (the dossier says there are none) — cron/jobs.json untouched")
    else:
        for r in routines:
            expr, tz, note = dl.split_schedule(r.get("schedule"))
            state = r.get("state")
            if state == "deleted":
                plan.append(f"routine {r.get('name')!r}: state=deleted — kept in the archive, no "
                            "cron job created (a job this adapter created earlier for it would "
                            "be removed)")
            elif expr is None:
                plan.append(f"routine {r.get('name')!r}: schedule {r.get('schedule')!r} is not a "
                            "cron expression, so no Hermes cron job can carry it — kept in the "
                            "archive")
                loss.append(f"routines[{r.get('name')!r}].schedule: "
                            f"{note or 'not a cron expression'}; Hermes cron needs a cron "
                            "expression, so this routine exists only as archived text")
            else:
                nxt = dl.next_run_iso(expr) if state == "running" else None
                plan.append(f"routine {r.get('name')!r}: Hermes cron job with expr {expr!r}"
                            + (f" (dossier timezone {tz}; Hermes evaluates exprs in the "
                               f"profile timezone)" if tz else "")
                            + (f", first run {nxt}" if nxt else
                               ", next_run_at left empty for Hermes' ticker")
                            + f", state {state!r} -> "
                            + ("enabled" if state == "running" else "paused"))
                if note:
                    loss.append(f"routines[{r.get('name')!r}].schedule: {note}")
        loss.append(f"routines ({len(routines)}): Hermes assigns job ids itself and has no "
                    "per-job timezone, so routine ids change and the dossier's timezone text "
                    "only survives as archived prose; next_run_at is computed with croniter when it "
                    "is available and otherwise left for Hermes' ticker to compute on its "
                    "first scan")

    memory = data.get("memory")
    if memory is None:
        loss.append("memory: not exported (null) — 未导出，不等于没有. The archived copy is kept "
                    "and MEMORY.md is left untouched.")
    elif not memory:
        plan.append("memory: [] (the dossier says there are none) — memories/MEMORY.md untouched")
    else:
        plan.append(f"memory ({len(memory)} facts): memories/MEMORY.md, one entry per fact, "
                    "entries joined by Hermes' own '\\n§\\n' delimiter")
        loss.append(f"memory ({len(memory)}): kind and learned degrade to an inline "
                    "'[kind · learned]' tag — Hermes memory entries are plain text — and "
                    "learned is not used as a sort key by the platform; fact text is verbatim "
                    "except that newlines inside a fact become spaces (one entry per line)")
    if data.get("skills"):
        if home:
            have = installed_skills(home)
            missing = [s for s in data["skills"] if s.lower() not in have
                       and dl.slugify(s) not in have]
            plan.append(f"skills: {len(data['skills'])} names checked against "
                        f"{str(hermes_paths(home)['skills'])} — "
                        + (f"missing: {', '.join(missing)}" if missing else "all present"))
            if missing:
                loss.append(f"skills: {missing} — the dossier carries names only; no skill "
                            "directory is created, so these must be installed separately")
        else:
            loss.append(f"skills {data['skills']}: only names travel; a skill exists on Hermes "
                        "only if a same-named SKILL.md is installed under skills/")
    if data.get("refs"):
        loss.append("refs: ids do not resolve on Hermes; the names are kept in the archive for a "
                    "human to re-match against agents on this platform")
    if data.get("excluded"):
        loss.append("excluded by exporter: " + str(data["excluded"]))

    if home:
        existing = []
        mem_path = hermes_paths(home)["memory"]
        if mem_path.exists():
            existing = [e.strip() for e in
                        mem_path.read_text(encoding="utf-8").split(dl.MEMORY_DELIM) if e.strip()]
        prev_written = set((meta or {}).get("written_memory") or [])
        kept = [e for e in existing if e.strip() not in prev_written]
        new = [e.strip() for e in dl.render_memory(memory or []).split(dl.MEMORY_DELIM)
               if e.strip()]
        final = kept + new
        budget = dl.hermes_memory_budget(home)
        total = len(dl.MEMORY_DELIM.join(final))
        plan.append(f"memory placement: {len(kept)} existing entr"
                    f"{'y' if len(kept) == 1 else 'ies'} kept (entries this adapter wrote "
                    f"earlier are replaced, never duplicated), {len(new)} written; "
                    f"{total}/{budget} chars against the home's memory_char_limit")
        if total > budget:
            loss.append(f"memory size: {total} chars exceeds the home's memory_char_limit "
                        f"({budget}); Hermes injects the store but refuses further additions "
                        "until it fits — the import is not truncated")

    our_ids = set((meta or {}).get("written_jobs", {}).values())
    foreign = [j for j in existing_jobs if j.get("id") not in our_ids]
    if existing_jobs:
        plan.append(f"cron/jobs.json: {len(foreign)} job(s) not written by this adapter are kept "
                    f"as they are, {len(existing_jobs) - len(foreign)} written by it are "
                    "updated or removed")
    plan.append(f"archive: dossier/{slug}.dossier.md (every field verbatim) + "
                "dossier/import-meta.json (field map, ids, bookkeeping)")
    plan.append(f"target home: {target}")
    return plan, loss


def write_text_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def apply_import(data, home, replace_soul):
    """Write the dossier into *home*. Returns (written paths, notes)."""
    paths = hermes_paths(home)
    meta = load_meta(home)
    notes, written = [], []
    slug = dl.slugify(data.get("name") or "agent")

    # SOUL.md — identity slot. Never clobber a soul this adapter did not write,
    # and refuse before creating anything at all.
    soul_text = dl.render_soul(data.get("role"), data.get("anti_jobs"))
    if paths["soul"].exists():
        old = paths["soul"].read_text(encoding="utf-8")
        if old != soul_text:
            if meta is None and not replace_soul:
                raise SystemExit(
                    "refusing to overwrite an existing SOUL.md this adapter did not write; "
                    "nothing was written; re-run with --replace-soul to keep the old file as "
                    "SOUL.md.pre-dossier first")
            if meta is None:
                backup = paths["soul"].with_name(dl.SOUL_FILE + ".pre-dossier")
                backup.write_text(old, encoding="utf-8")
                notes.append(f"old SOUL.md kept as {backup.name}")
            write_text_atomic(paths["soul"], soul_text)
            written.append(str(paths["soul"]))
    else:
        write_text_atomic(paths["soul"], soul_text)
        written.append(str(paths["soul"]))

    for key in ("memory_dir", "skills", "cron_dir", "cron_output", "archive"):
        paths[key].mkdir(parents=True, exist_ok=True)

    # memories/MEMORY.md — Hermes' §-delimited store.
    existing = []
    if paths["memory"].exists():
        existing = [e.strip() for e in
                    paths["memory"].read_text(encoding="utf-8").split(dl.MEMORY_DELIM) if e.strip()]
    prev_written = set((meta or {}).get("written_memory") or [])
    kept = [e for e in existing if e.strip() not in prev_written]
    new_entries = [e.strip() for e in
                   dl.render_memory(data.get("memory") or []).split(dl.MEMORY_DELIM) if e.strip()]
    final = kept + new_entries
    mem_text = dl.MEMORY_DELIM.join(final)
    if mem_text:
        mem_text += "\n"
    if final or paths["memory"].exists():
        current = paths["memory"].read_text(encoding="utf-8") if paths["memory"].exists() else ""
        if current != mem_text:
            write_text_atomic(paths["memory"], mem_text)
            written.append(str(paths["memory"]))
    if data.get("memory") is None and paths["memory"].exists():
        notes.append("memory was null (not exported): MEMORY.md left exactly as it was")

    # cron/jobs.json — Hermes job records.
    jobs, raw = load_jobs(home)
    prev_jobs = dict((meta or {}).get("written_jobs") or {})
    now = datetime.datetime.now().astimezone().isoformat()
    changed = False
    for r in data.get("routines") or []:
        rid = str(r.get("id"))
        prev_id = prev_jobs.get(rid)
        if r.get("state") == "deleted":
            if prev_id:
                jobs = [j for j in jobs if j.get("id") != prev_id]
                prev_jobs.pop(rid, None)
                changed = True
                notes.append(f"removed cron job {prev_id} for deleted routine {r.get('name')!r}")
            continue
        expr, tz, _note = dl.split_schedule(r.get("schedule"))
        if expr is None:
            continue
        job_id = prev_id or uuid.uuid4().hex[:12]
        running = r.get("state") == "running"
        record = {
            "id": job_id,
            "name": r.get("name") or job_id,
            "prompt": r.get("prompt") or "",
            "skills": [],
            "skill": None,
            "model": None,
            "provider": None,
            "base_url": None,
            "script": None,
            "no_agent": False,
            "monitor_script": None,
            "monitor_url": None,
            "monitor_state": None,
            "context_from": None,
            "schedule": {"kind": "cron", "expr": expr,
                         "display": r.get("schedule") or expr},
            "schedule_display": r.get("schedule") or expr,
            "repeat": {"times": None, "completed": 0},
            "enabled": running,
            "state": "scheduled" if running else "paused",
            "paused_at": None if running else now,
            "paused_reason": None if running else (
                "imported from a dossier as paused; enable after review"),
            "created_at": now,
            # None is Hermes' own "recompute" signal (its ticker arms the job on
            # the next due scan, cron/jobs.py:_recover_missing_next_run); filled
            # in when croniter is importable so `hermes cron doctor` stays quiet.
            "next_run_at": None if not running else dl.next_run_iso(expr),
            "last_run_at": None,
            "last_status": None,
            "last_error": None,
            "last_delivery_error": None,
            "last_delivery_unverified": None,
            "last_failure": None,
            "failure_streak": 0,
            "deliver": "local",
            "origin": None,
            "enabled_toolsets": None,
            "workdir": None,
            "dossier": {"source": data.get("source"), "id": str(data.get("id")),
                        "routine_id": rid, "timezone": tz},
        }
        idx = next((i for i, j in enumerate(jobs) if j.get("id") == job_id), None)
        if idx is None:
            jobs.append(record)
        else:
            created_at = jobs[idx].get("created_at")
            if created_at:
                record["created_at"] = created_at
            jobs[idx] = record
        prev_jobs[rid] = job_id
        changed = True
    if changed or (paths["cron"].exists() and raw is None):
        payload = {"jobs": jobs, "updated_at": now}
        write_text_atomic(paths["cron"], json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        written.append(str(paths["cron"]))

    # dossier/ — the archive: every field verbatim, plus the field map.
    archive_path = paths["archive"] / f"{slug}.dossier.md"
    write_text_atomic(archive_path, dl.render_dossier(data))
    written.append(str(archive_path))

    meta_out = {
        "spec": data.get("spec"),
        "id": str(data.get("id")),
        "name": data.get("name"),
        "title": data.get("title"),
        "group": data.get("group"),
        "status": data.get("status"),
        "exported_at": data.get("exported_at"),
        "source": data.get("source"),
        "fingerprint": data.get("fingerprint"),
        "imported_at": now,
        "slug": slug,
        "home": str(home),
        "archive": f"{dl.ARCHIVE_DIR}/{slug}.dossier.md",
        "written_memory": new_entries,
        "written_jobs": prev_jobs,
        "field_map": [{"field": f, "where": w, "fidelity": fid, "note": n}
                      for f, w, fid, n in FIELD_MAP],
    }
    write_text_atomic(paths["meta"], json.dumps(meta_out, indent=2, ensure_ascii=False) + "\n")
    written.append(str(paths["meta"]))
    return written, notes


def main():
    args = sys.argv[1:]
    apply = "--apply" in args
    if apply:
        args.remove("--apply")
    replace_soul = "--replace-soul" in args
    if replace_soul:
        args.remove("--replace-soul")
    home = None
    if "--target-home" in args:
        i = args.index("--target-home")
        if i + 1 >= len(args):
            sys.exit("--target-home needs a directory")
        home = Path(args[i + 1]).expanduser().resolve()
        del args[i:i + 2]
    if len(args) != 1:
        sys.exit(__doc__)
    if apply and home is None:
        sys.exit("--apply needs --target-home DIR (this adapter never guesses a home)")

    src = args[0]
    try:
        data, _body = dl.load_dossier_file(src)
    except dl.DossierError as e:
        print("FAIL: " + str(e))
        sys.exit(1)
    errors, warnings = dl.validate(data)
    print(("APPLY " if apply else "DRY RUN ") + os.path.basename(src))
    print(LEVEL_LINE)
    print("checks:", "PASS" if not errors else "FAIL")
    for e in errors:
        print("  FAIL", e)
    for w in warnings:
        print("  WARN", w)
    if errors:
        sys.exit(1)

    meta = load_meta(home) if home else None
    if home and not home.exists():
        print("target home:", home, "(does not exist yet; --apply creates it)")
    if meta and (str(meta.get("source")) != str(data.get("source"))
                 or str(meta.get("id")) != str(data.get("id"))):
        print(f"FAIL: {home} already holds a dossier for source={meta.get('source')!r} "
              f"id={meta.get('id')!r}; one Hermes home carries one agent identity "
              "(its SOUL.md), so import this dossier into its own home")
        sys.exit(1)

    existing_jobs, _raw = load_jobs(home) if home else ([], None)
    plan, loss = build_plan(data, home, meta, existing_jobs)
    for p in plan:
        print("plan:", p)
    for l in loss:
        print("loss/downgrade:", l)

    if not apply:
        print("note: dry run only. Nothing was created or modified. Re-run with "
              "--apply --target-home DIR to write this dossier into a Hermes home.")
        return

    written, notes = apply_import(data, home, replace_soul)
    for n in notes:
        print("applied note:", n)
    for w in written:
        print("wrote:", w)
    print(f"applied: {len(written)} file(s) under {home}; nothing outside it was touched.")
    print("note: memories/USER.md is the user profile store and is never written by this "
          "importer; no other profile's files are touched.")


if __name__ == "__main__":
    main()
