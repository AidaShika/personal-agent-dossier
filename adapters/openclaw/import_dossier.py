#!/usr/bin/env python3
"""Import a personal-agent-dossier into one OpenClaw agent.

Default is a dry run: validate, scan, and print the plan plus the loss list.
`--apply --target-home DIR` writes, and only inside DIR:

  <workspace>/SOUL.md            role (marker line carries dossier id+source)
  <workspace>/AGENTS.md          anti_jobs as a managed block (rest untouched)
  <workspace>/IDENTITY.md        the Name bullet
  <workspace>/MEMORY.md          memory facts as a managed block (rest kept)
  <home>/state/openclaw.sqlite   routines as rows in cron_jobs (agentId set)
                                 or <home>/cron/jobs.json when the DB is absent
  <home>/dossier/<agentId>/      archived original + import-meta.json (pairing)

One dossier pairs with one OpenClaw agent (by agentId). A home may hold
several agents; each keeps its own workspace and its own slice of cron jobs.

Refusals (exit 1): the agent already carries a different dossier; SOUL.md is
neither the onboard seed nor ours (use --replace-soul to override, the old
file is kept as a backup). Validation/scan failures exit 2.
"""

import argparse
import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dossier_lib as L


def _backup_path(path):
    """A free SOUL.md.pre-dossier[.N] path."""
    cand = path.with_name(path.name + ".pre-dossier")
    n = 1
    while cand.exists():
        cand = path.with_name(f"{path.name}.pre-dossier.{n}")
        n += 1
    return cand


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dossier")
    ap.add_argument("--target-home", help="OpenClaw home dir (required for --apply)")
    ap.add_argument("--agent-id", default=L.DEFAULT_AGENT_ID,
                    help="OpenClaw agentId to import as (default: main)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--replace-soul", action="store_true",
                    help="overwrite a foreign SOUL.md (a backup is kept)")
    ap.add_argument("--date", help="import date for meta (YYYY-MM-DD)")
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
    agent = str(args.agent_id).strip() or L.DEFAULT_AGENT_ID
    home = Path(args.target_home).expanduser() if args.target_home else None
    if args.apply and home is None:
        print("error: --apply requires --target-home")
        return 2

    cfg = L.load_config(home) if home else {}
    workspace = L.resolve_workspace(cfg, home, agent) if home else None
    if home and workspace is None:
        print(f"error: agent {agent!r} is not configured in {home / L.CONFIG_FILE}; "
              "add it first (for example: openclaw agents add " + agent + ")")
        return 1

    meta_dir = (home / L.ARCHIVE_ROOT / agent) if home else None
    meta_path = meta_dir / "import-meta.json" if meta_dir else None
    meta = {}
    if meta_path and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            print(f"error: unreadable import meta {meta_path}; refusing to guess")
            return 1
        if (meta.get("source"), meta.get("id")) != (data.get("source"), data.get("id")):
            print(f"error: agent {agent!r} in this home already carries dossier "
                  f"{meta.get('source')}/{meta.get('id')}; refusing a second identity")
            return 1

    soul_path = workspace / L.SOUL_FILE if workspace else None
    soul_state = "no target"
    soul_text = ""
    if soul_path and soul_path.exists():
        soul_text = soul_path.read_text(encoding="utf-8")
        _r, mid, msrc, is_seed = L.parse_soul(soul_text)
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
    losses.append("status: documentary; kept in import-meta.json only")

    routines = data.get("routines")
    routines_exported = routines is not None
    routines = routines or []
    memory = data.get("memory")
    memory_exported = memory is not None
    memory = memory or []

    try:
        existing_jobs, backend = (L.load_cron_jobs(home, cfg) if home else ([], "none"))
    except L.DossierError as e:
        print(f"error: {e}")
        return 2
    default = L.default_agent_id(cfg)
    existing_jobs = [j for j in existing_jobs
                     if j.get("agentId") == agent
                     or (j.get("agentId") in (None, "") and agent == default)]
    existing_by_id = {j.get("id"): j for j in existing_jobs}
    prior_ids = (meta.get("routine_ids") or {}) if isinstance(meta, dict) else {}

    now_ms = int(time.time() * 1000)
    job_plan = []          # (routine, job, note)
    delete_ids = []
    new_routine_ids = {}
    for r in routines:
        rname = r.get("name") or ""
        if (r.get("state") or "running") == "deleted":
            jid = prior_ids.get(rname) or L.job_id_for(data.get("id"), rname)
            delete_ids.append(jid)
            job_plan.append((r, None, "state deleted: existing job removed, none created"))
            continue
        existing = existing_by_id.get(L.job_id_for(data.get("id"), rname)) or \
            next((j for j in existing_jobs if j.get("agentId") == agent
                  and j.get("name") == rname), None)
        job, note = L.build_job(data.get("id"), agent, r, now_ms, existing=existing)
        if job is None:
            losses.append(f"routine {rname!r}: {note}")
        else:
            if note:
                losses.append(f"routine {rname!r}: {note}")
            job_plan.append((r, job, ""))
            new_routine_ids[rname] = job["id"]
    # A routine removed from a re-imported dossier is removed from this agent.
    if routines_exported:
        for rname, jid in prior_ids.items():
            if rname not in new_routine_ids and jid not in delete_ids:
                delete_ids.append(jid)
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
    if not routines_exported:
        losses.append("routines: null = not exported, not 'none'; no cron change is made")
    if not memory_exported:
        losses.append("memory: null = not exported, not 'none'; MEMORY.md is not touched")
    for r in routines:
        if r.get("state") == "deleted":
            losses.append(f"routine {r.get('name')!r}: state deleted is kept in the "
                          "archive but the job is not recreated")
    losses.append("routine delivery: dossier has no field; imported jobs use mode=none")

    print(f"dossier: {data.get('source')}/{data.get('id')}  fingerprint {data.get('fingerprint')}")
    if home:
        print(f"agent:   {agent}  workspace: {workspace}")
        print(f"cron:    {L.cron_backend_label(home, cfg)}")
    else:
        print(f"agent:   {agent}  (no target home)")
    print("plan:")
    print(f"  role      -> SOUL.md ({soul_state})")
    print(f"  anti_jobs -> AGENTS.md managed block ({len(data.get('anti_jobs') or [])} items)")
    print(f"  name      -> IDENTITY.md Name bullet: {data.get('name')!r}")
    print(f"  memory    -> MEMORY.md managed block ({len(memory)} entries"
          + ("" if memory_exported else "; not exported") + ")")
    jobs = [job for _r, job, _n in job_plan if job is not None]
    for r, job, note in job_plan:
        if job:
            sch = job["schedule"]
            print(f"  routine   -> cron job {job['name']!r}: {sch['expr']}"
                  + (f" ({sch['tz']})" if sch.get("tz") else "")
                  + f", enabled={job['enabled']}, id {job['id'][:8]}…")
        else:
            print(f"  routine   -> {note}: {r.get('name')!r}")
    if delete_ids:
        print(f"  routines  -> remove {len(delete_ids)} previously imported job(s)")
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
    if soul_state == "foreign":
        backup = _backup_path(soul_path)
        backup.write_text(soul_text, encoding="utf-8")
        written.append(f"{backup.name} (backup)")
    soul_path.write_text(L.render_soul(data.get("role"), data.get("id"), data.get("source")),
                         encoding="utf-8")
    written.append("SOUL.md")

    agents_path = workspace / L.AGENTS_FILE
    agents_text = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    if data.get("anti_jobs") is not None:
        agents_path.write_text(L.upsert_agents_block(agents_text, data.get("anti_jobs")),
                               encoding="utf-8")
        written.append("AGENTS.md (anti_jobs block)")

    ident_path = workspace / L.IDENTITY_FILE
    if ident_path.exists():
        ident_path.write_text(L.set_identity_name(
            ident_path.read_text(encoding="utf-8"), data.get("name") or ""), encoding="utf-8")
    else:
        ident_path.write_text(f"# IDENTITY.md - Who Am I?\n\n- **Name:** {data.get('name') or ''}\n",
                              encoding="utf-8")
    written.append("IDENTITY.md")

    if memory_exported:
        mem_path = workspace / L.MEMORY_FILE
        mem_text = mem_path.read_text(encoding="utf-8") if mem_path.exists() else ""
        mem_path.write_text(L.upsert_memory_block(mem_text, memory), encoding="utf-8")
        written.append("MEMORY.md (memory block)")

    if routines_exported:
        try:
            backend, nw, nd = L.save_cron_jobs(home, cfg, jobs, delete_ids=delete_ids,
                                               now_ms=now_ms)
        except L.DossierError as e:
            print(f"error: {e}")
            return 2
        written.append(f"{backend} cron ({nw} upserted, {nd} removed)")

    # Archive the exact source bytes, then the pairing map. Remove an older
    # archive file for this agent so export never reads a stale name variant.
    meta_dir.mkdir(parents=True, exist_ok=True)
    slug = L.slugify(data.get("name") or "agent")
    archive_path = meta_dir / f"{slug}.dossier.md"
    archive_path.write_text(original_text, encoding="utf-8")
    for old in meta_dir.glob("*.dossier.md"):
        if old != archive_path:
            old.unlink()
    meta_out = {
        "spec": data.get("spec"), "id": data.get("id"), "source": data.get("source"),
        "name": data.get("name"), "title": data.get("title"),
        "fingerprint": data.get("fingerprint"), "agent_id": agent,
        "workspace": str(workspace),
        "imported_at": args.date or datetime.date.today().isoformat(),
        "routines_exported": routines_exported,
        "memory_exported": memory_exported,
        "routines": new_routine_ids,
        "cron_backend": backend if routines_exported else None,
        "files": written,
    }
    (meta_dir / "import-meta.json").write_text(
        json.dumps(meta_out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    written.append(f"dossier/{agent}/")
    print("\napplied:")
    for w_ in written:
        print(f"  - {w_}")
    if routines_exported and (jobs or delete_ids):
        print("note: a running gateway reloads cron on restart; the imported jobs are "
              "visible to `openclaw cron list` after the gateway starts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
