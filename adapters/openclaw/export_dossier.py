#!/usr/bin/env python3
"""Export one OpenClaw agent as a personal-agent-dossier/1.0 dossier.

Reads the agent's native slots: SOUL.md (role; an untouched onboard seed has
no role), AGENTS.md (the adapter's anti_jobs managed block), IDENTITY.md
(name), MEMORY.md (the adapter's memory managed block), the shared cron store
(SQLite cron_jobs, or the legacy JSON import file), workspace skills. Fields
with no native slot (title, group, refs, status, excluded) come from the
archived import when there is one, else stay absent/null — null means "not
exported", never "empty".

The dossier is scanned (SPEC 5.2) before anything is written; a hit aborts the
export and no output file is produced. The fingerprint is recomputed by the
renderer, and drift against the archived import (if any) is reported on stderr.
"""

import argparse
import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dossier_lib as L


def _load_archive(home, agent):
    meta, archive = {}, None
    meta_path = Path(home) / L.ARCHIVE_ROOT / agent / "import-meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        for cand in sorted(meta_path.parent.glob("*.dossier.md")):
            try:
                archive, _ = L.load_dossier_file(str(cand))
                break
            except Exception:
                continue
    return meta, archive


def _pick_agent(cfg, home, requested):
    agents = L.list_agents(cfg, home)
    if requested:
        return str(requested).strip()
    if len(agents) == 1:
        return agents[0][0]
    default = L.default_agent_id(cfg)
    if any(a == default for a, _ in agents):
        return default
    if not agents:
        return L.DEFAULT_AGENT_ID
    print("error: several agents in this home; pick one with --agent-id: "
          + ", ".join(a for a, _ in agents), file=sys.stderr)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--home", required=True, help="OpenClaw home dir")
    ap.add_argument("--agent-id", help="agentId to export (default: the only/default agent)")
    ap.add_argument("--out", help="output file (default: stdout)")
    ap.add_argument("--date", help="exported_at override (YYYY-MM-DD)")
    args = ap.parse_args()

    home = Path(args.home).expanduser()
    cfg = L.load_config(home)
    agent = _pick_agent(cfg, home, args.agent_id)
    if agent is None:
        return 2
    workspace = L.resolve_workspace(cfg, home, agent)
    if workspace is None or not workspace.exists():
        print(f"error: agent {agent!r} is not configured or its workspace is missing: "
              f"{workspace}", file=sys.stderr)
        return 2

    meta, archive = _load_archive(home, agent)
    notes = []

    # role
    soul_path = workspace / L.SOUL_FILE
    role, marker_id, marker_source, is_seed = (None, None, None, False)
    if soul_path.exists():
        role, marker_id, marker_source, is_seed = L.parse_soul(
            soul_path.read_text(encoding="utf-8"))
    if marker_id and meta and marker_id != meta.get("id"):
        print(f"warning: SOUL marker id {marker_id} != archived id {meta.get('id')}",
              file=sys.stderr)
    if role is None and archive:
        role = archive.get("role")
        notes.append("SOUL.md is an unfilled seed; role taken from the archived copy")
    if role is None:
        print("error: SOUL.md is an unfilled onboard seed and there is no archived role; "
              "write the agent's role first", file=sys.stderr)
        return 2

    # name
    name = None
    ident_path = workspace / L.IDENTITY_FILE
    if ident_path.exists():
        name = L.parse_identity_name(ident_path.read_text(encoding="utf-8"))
    entry = next((e for e in (cfg.get("agents") or {}).get("list") or []
                  if isinstance(e, dict) and str(e.get("id")) == agent), None)
    if not name and entry and isinstance(entry.get("identity"), dict):
        name = (entry["identity"].get("name") or "").strip() or None
    name = name or meta.get("name") or (archive or {}).get("name") or agent

    # anti_jobs
    anti = None
    agents_path = workspace / L.AGENTS_FILE
    if agents_path.exists():
        anti, _rest = L.extract_agents_block(agents_path.read_text(encoding="utf-8"))
    if anti is None and archive and archive.get("anti_jobs") is not None:
        # No managed block: do not resurrect archived content silently.
        notes.append("AGENTS.md has no anti_jobs managed block; anti_jobs is absent")

    # memory
    mem_entries = None
    mem_path = workspace / L.MEMORY_FILE
    if mem_path.exists():
        parsed = L.parse_memory_block(mem_path.read_text(encoding="utf-8"))
        if parsed is not None:
            mem_entries = [{k: v for k, v in e.items() if not k.startswith("_")}
                           for e in parsed]
        else:
            notes.append("MEMORY.md exists but has no memory managed block; memory is absent")
    if mem_entries is None and archive and archive.get("memory") is None:
        # Keep the "not exported" marker instead of turning it into [].
        mem_entries = None

    # routines
    try:
        all_jobs, backend = L.load_cron_jobs(home, cfg)
    except L.DossierError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    default = L.default_agent_id(cfg)
    mine = [j for j in all_jobs
            if j.get("agentId") == agent
            or (j.get("agentId") in (None, "") and agent == default)]
    routines = []
    for job in mine:
        sch = job.get("schedule") or {}
        if sch.get("kind") != "cron":
            notes.append(f"routine {job.get('name')!r}: schedule kind "
                         f"{sch.get('kind')!r} has no dossier cron form; not exported")
            continue
        sched_text = sch.get("expr") or ""
        if sch.get("tz"):
            sched_text += f" ({sch['tz']})"
        routines.append({
            "id": job.get("id"),
            "name": job.get("name"),
            "schedule": sched_text,
            "prompt": (job.get("payload") or {}).get("message"),
            "state": "running" if job.get("enabled", True) else "paused",
        })
    if not routines:
        archived_routines = (archive or {}).get("routines")
        if archived_routines is None:
            routines = None
        elif archived_routines == []:
            routines = []
        else:
            # Keep deleted routines from the archive (they have no live job).
            routines = [dict(r) for r in archived_routines
                        if isinstance(r, dict) and r.get("state") == "deleted"]
    else:
        # Preserve archived deleted routines alongside live jobs.
        seen_ids = {r["id"] for r in routines}
        seen_names = {str(r.get("name")) for r in routines}
        for r in (archive or {}).get("routines") or []:
            if (isinstance(r, dict) and r.get("state") == "deleted"
                    and r.get("id") not in seen_ids and str(r.get("name")) not in seen_names):
                routines.append(dict(r))

    # skills: the archived list is the set this agent is supposed to have.
    # Native-born agents (no archive) export what is installed. Do not append
    # unrelated workspace skills to an imported dossier: that would make the
    # round-trip differ for a reason the dossier never stated.
    native_skills = None
    skills_dir = workspace / L.SKILLS_DIR
    if skills_dir.exists():
        native_skills = sorted(d.name for d in skills_dir.iterdir()
                               if d.is_dir() and (d / "SKILL.md").exists())
    arch_skills = (archive or {}).get("skills")
    if arch_skills:
        skills = list(arch_skills)
    else:
        skills = native_skills

    dossier_id = meta.get("id") or (archive or {}).get("id") or L.openclaw_id(agent)
    if not meta and not archive:
        notes.append(f"dossier id minted by the adapter as {dossier_id!r}: OpenClaw "
                     "agentIds are local labels, not dossier-grade identifiers")
    excluded = (archive or {}).get("excluded")
    if notes:
        base = [excluded] if isinstance(excluded, str) and excluded else list(excluded or [])
        excluded = base + [n for n in notes if n not in base]

    data = {
        "spec": "personal-agent-dossier/1.0",
        "id": dossier_id,
        "name": name,
        "title": (archive or {}).get("title"),
        "group": (archive or {}).get("group"),
        "status": (archive or {}).get("status") or "active",
        "exported_at": args.date or datetime.date.today().isoformat(),
        "source": "openclaw",
        "role": role,
        "refs": (archive or {}).get("refs"),
        "anti_jobs": anti,
        "routines": routines,
        "memory": mem_entries,
        "skills": skills,
        "excluded": excluded or None,
    }
    data["fingerprint"] = L.fingerprint(data.get("name"), data.get("title"), data.get("role"))
    errors, warnings = L.validate(data)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 2

    text = L.render_dossier(data)
    fp = L.fingerprint(data.get("name"), data.get("title"), data.get("role"))
    if archive and archive.get("fingerprint") != fp:
        print(f"drift: archived fingerprint {archive.get('fingerprint')} -> now {fp} "
              "(native slots changed since import)", file=sys.stderr)
    elif archive:
        print(f"fingerprint unchanged vs archive: {fp}", file=sys.stderr)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=out.name + ".", dir=str(out.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, out)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    else:
        sys.stdout.write(text)
    print(f"exported {data['source']}/{dossier_id} fingerprint {fp} "
          f"(routines: {'null' if routines is None else len(routines)}, "
          f"memory: {'null' if mem_entries is None else len(mem_entries)}, "
          f"cron: {backend})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
