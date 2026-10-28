#!/usr/bin/env python3
"""Import a personal-agent-dossier into an OpenClaw home.

Default is a dry run: validate, scan, and print the plan plus the loss list.
`--apply --target-home DIR` writes, and only inside DIR:

  <workspace>/SOUL.md            role (marker line carries dossier id+source)
  <workspace>/AGENTS.md          anti_jobs as a managed block (rest untouched)
  <workspace>/IDENTITY.md        the Name bullet
  <workspace>/MEMORY.md          memory facts as a managed block (rest kept)
  <home>/cron/jobs.json          routines as OpenClaw cron jobs (agentId set)
  <home>/dossier/<agentId>/      archived original + import-meta.json (pairing)

One dossier pairs with one OpenClaw agent (by agentId). A home may hold
several agents; each keeps its own workspace and its own slice of jobs.json.
Refusals (exit 1): the agent already carries a different dossier; SOUL.md is
neither the onboard seed nor ours (use --replace-soul to override, the old
file is kept as SOUL.md.pre-dossier). Validation/scan failures exit 2.
"""

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dossier_lib as L


def load_config(home):
    p = home / L.CONFIG_FILE
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"warning: openclaw.json unreadable ({e}); assuming default layout")
    return {"agents": {"defaults": {"workspace": str(home / L.WORKSPACE_DIR)}}}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dossier")
    ap.add_argument("--target-home", help="OpenClaw home dir (required for --apply)")
    ap.add_argument("--agent-id", default=L.DEFAULT_AGENT_ID,
                    help="OpenClaw agentId to import as (default: main)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--replace-soul", action="store_true",
                    help="overwrite a foreign SOUL.md (backup kept)")
    args = ap.parse_args()

    try:
        data, _body = L.load_dossier_file(args.dossier)
    except L.DossierError as e:
        print(f"error: {e}")
        return 2
    errors, warnings = L.validate(data)
    for w in warnings:
        print(f"warning: {w}")
    if errors:
        for e in errors:
            print(f"error: {e}")
        return 2
    original_text = Path(args.dossier).read_text(encoding="utf-8")
    agent = args.agent_id

    home = Path(args.target_home).expanduser() if args.target_home else None
    if args.apply and home is None:
        print("error: --apply requires --target-home")
        return 2
    cfg = load_config(home) if home else None
    workspace = (L.resolve_workspace(cfg, home, agent) or (home / L.WORKSPACE_DIR)) if home else None

    meta_dir = (home / L.ARCHIVE_ROOT / agent) if home else None
    meta_path = meta_dir / "import-meta.json" if meta_dir else None
    meta = None
    if meta_path and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if (meta.get("source"), meta.get("id")) != (data.get("source"), data.get("id")):
            print(f"error: agent {agent!r} in this home already carries dossier "
                  f"{meta.get('source')}/{meta.get('id')}; refusing a second identity")
            return 1

    soul_path = workspace / L.SOUL_FILE if workspace else None
    soul_state = "no target"
    if soul_path and soul_path.exists():
        _r, mid, msrc, is_seed = L.parse_soul(soul_path.read_text(encoding="utf-8"))
        if mid is not None:
            soul_state = "ours" if (mid, msrc) == (data.get("id"), data.get("source")) else "other-dossier"
        elif is_seed:
            soul_state = "seed"
        else:
            soul_state = "foreign"
    if soul_state == "other-dossier":
        print("error: SOUL.md carries a different dossier's marker; refusing")
        return 1
    if soul_state == "foreign" and args.apply and not args.replace_soul:
        print("error: SOUL.md is neither the onboard seed nor written by this adapter; "
              "refusing (add --replace-soul to override; a backup is kept)")
        return 1

    # ---- plan -------------------------------------------------------------
    losses = []
    if data.get("title"):
        losses.append("title: no native slot; kept in the archive copy only")
    if data.get("group"):
        losses.append("group: OpenClaw has no agent grouping; archive only")
    if data.get("refs"):
        losses.append("refs: archive only; ids do not resolve across platforms, "
                      "re-link by name by hand")
    routines = data.get("routines") or []
    now_ms = int(time.time() * 1000)
    job_plan = []
    for r in routines:
        if (r.get("state") or "running") == "deleted":
            job_plan.append((r, None, "state deleted: not created (existing job removed)"))
            continue
        job, note = L.build_job(data.get("id"), agent, r, now_ms)
        if job is None:
            losses.append(f"routine {r.get('name')!r}: {note}")
        else:
            if note:
                losses.append(f"routine {r.get('name')!r}: {note}")
            job_plan.append((r, job, ""))
    losses.append("routine ids: remapped to deterministic uuid5 ids "
                  "(stable across re-imports of the same dossier)")
    skills = data.get("skills") or []
    missing_skills = []
    if workspace:
        for s in skills:
            if not (workspace / L.SKILLS_DIR / s / "SKILL.md").exists():
                missing_skills.append(s)
    if skills:
        losses.append("skills: names only; nothing is created. "
                      + (f"missing in target workspace: {', '.join(missing_skills)}"
                         if missing_skills else "all present in target workspace"))
    mem = data.get("memory") or []
    anti = data.get("anti_jobs") or []

    print(f"dossier: {data.get('source')}/{data.get('id')}  fingerprint {data.get('fingerprint')}")
    print(f"agent:   {agent}" + (f"  workspace: {workspace}" if workspace else "  (no target home)"))
    print(f"plan:")
    print(f"  role      -> SOUL.md ({soul_state})")
    print(f"  anti_jobs -> AGENTS.md managed block ({len(anti)} items)")
    print(f"  name      -> IDENTITY.md Name bullet: {data.get('name')!r}")
    print(f"  memory    -> MEMORY.md managed block ({len(mem)} entries)")
    for r, job, note in job_plan:
        if job:
            sch = job["schedule"]
            print(f"  routine   -> cron job {job['name']!r}: {sch['expr']}"
                  + (f" ({sch['tz']})" if sch.get("tz") else "")
                  + f", enabled={job['enabled']}, id {job['id'][:8]}…")
        else:
            print(f"  routine   -> skipped {r.get('name')!r}: {note}")
    print(f"  archive   -> dossier/{agent}/ (original + import-meta.json)")
    if losses:
        print("losses / downgrades:")
        for x in losses:
            print(f"  - {x}")
    if not args.apply:
        print("\ndry run: nothing written. Re-run with --apply --target-home DIR to write.")
        return 0

    # ---- apply ------------------------------------------------------------
    workspace.mkdir(parents=True, exist_ok=True)
    written = []
    if soul_state == "foreign" and args.replace_soul:
        (workspace / (L.SOUL_FILE + ".pre-dossier")).write_text(
            soul_path.read_text(encoding="utf-8"), encoding="utf-8")
        written.append("SOUL.md.pre-dossier (backup)")
    soul_path.write_text(L.render_soul(data.get("role"), data.get("id"), data.get("source")),
                         encoding="utf-8")
    written.append("SOUL.md")

    agents_path = workspace / L.AGENTS_FILE
    agents_text = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    agents_path.write_text(L.upsert_agents_block(agents_text, anti), encoding="utf-8")
    written.append("AGENTS.md (anti_jobs block)")

    ident_path = workspace / L.IDENTITY_FILE
    if ident_path.exists():
        ident_path.write_text(L.set_identity_name(
            ident_path.read_text(encoding="utf-8"), data.get("name") or ""), encoding="utf-8")
    else:
        ident_path.write_text(f"# IDENTITY.md - Who Am I?\n\n- **Name:** {data.get('name') or ''}\n",
                              encoding="utf-8")
    written.append("IDENTITY.md")

    mem_path = workspace / L.MEMORY_FILE
    mem_text = mem_path.read_text(encoding="utf-8") if mem_path.exists() else ""
    mem_path.write_text(L.upsert_memory_block(mem_text, mem), encoding="utf-8")
    written.append("MEMORY.md (memory block)")

    cron_path = home / L.CRON_FILE
    store = {"version": 1, "jobs": []}
    if cron_path.exists():
        try:
            store = json.loads(cron_path.read_text(encoding="utf-8"))
        except Exception:
            print("error: existing cron/jobs.json is not valid JSON; not touching it")
            return 1
        store.setdefault("version", 1)
        store.setdefault("jobs", [])
    jobs = store["jobs"]
    routine_ids = {}
    for r, job, _note in job_plan:
        if (r.get("state") or "running") == "deleted":
            jid = L.job_id_for(data.get("id"), r.get("name") or "")
            jobs[:] = [j for j in jobs if j.get("id") != jid]
            continue
        if job is None:
            continue
        existing = next((j for j in jobs if j.get("id") == job["id"]), None) or \
            next((j for j in jobs if j.get("agentId") == agent and j.get("name") == job["name"]), None)
        if existing is not None:
            job, _ = L.build_job(data.get("id"), agent, r, now_ms, existing=existing)
            jobs[jobs.index(existing)] = job
        else:
            jobs.append(job)
        routine_ids[r.get("name") or ""] = job["id"]
    cron_path.parent.mkdir(parents=True, exist_ok=True)
    cron_path.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    written.append("cron/jobs.json")

    meta_dir.mkdir(parents=True, exist_ok=True)
    slug = L.slugify(data.get("name") or "agent")
    (meta_dir / f"{slug}.dossier.md").write_text(original_text, encoding="utf-8")
    meta_out = {
        "spec": data.get("spec"), "id": data.get("id"), "source": data.get("source"),
        "name": data.get("name"), "title": data.get("title"),
        "fingerprint": data.get("fingerprint"), "agent_id": agent,
        "workspace": str(workspace),
        "imported_at": datetime.date.today().isoformat(),
        "routines": routine_ids, "files": written,
    }
    (meta_dir / "import-meta.json").write_text(
        json.dumps(meta_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    written.append(f"dossier/{agent}/")
    print("\napplied:")
    for w_ in written:
        print(f"  - {w_}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
