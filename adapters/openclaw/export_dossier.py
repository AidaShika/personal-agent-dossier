#!/usr/bin/env python3
"""Export one OpenClaw agent as a personal-agent-dossier/1.0 dossier.

Reads the agent's native slots: SOUL.md (role; the untouched onboard seed
exports as null, it is a template, not a role), AGENTS.md (the adapter's
anti_jobs managed block), IDENTITY.md (name), MEMORY.md (the adapter's
memory managed block), cron/jobs.json (this agentId's jobs), workspace
skills. Fields with no native slot (title, group, refs, excluded) come from
the archived import when there is one, else stay null — null means "not
exported", never "empty".

The dossier is scanned (SPEC 5.2) before anything is written; a hit aborts
the export. The fingerprint is recomputed by the renderer, and drift against
the archived import (if any) is reported on stderr.
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dossier_lib as L


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--home", required=True, help="OpenClaw home dir")
    ap.add_argument("--agent-id", help="agentId to export (default: the only/default agent)")
    ap.add_argument("--out", help="output file (default: stdout)")
    ap.add_argument("--date", help="exported_at override (YYYY-MM-DD)")
    args = ap.parse_args()

    home = Path(args.home).expanduser()
    cfg_path = home / L.CONFIG_FILE
    cfg = {}
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    agents = L.list_agents(cfg, home)
    if args.agent_id:
        agent = args.agent_id
    elif len(agents) == 1:
        agent = agents[0][0]
    elif any(a == L.DEFAULT_AGENT_ID for a, _ in agents):
        agent = L.DEFAULT_AGENT_ID
    elif not agents:
        agent = L.DEFAULT_AGENT_ID
    else:
        print("error: several agents in this home; pick one with --agent-id: "
              + ", ".join(a for a, _ in agents), file=sys.stderr)
        return 2
    workspace = L.resolve_workspace(cfg, home, agent) or (home / L.WORKSPACE_DIR)
    if not workspace.exists():
        print(f"error: workspace not found: {workspace}", file=sys.stderr)
        return 2

    meta, archive = {}, None
    meta_path = home / L.ARCHIVE_ROOT / agent / "import-meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for cand in sorted(meta_path.parent.glob("*.dossier.md")):
            try:
                archive, _ = L.load_dossier_file(str(cand))
                break
            except Exception:
                continue

    notes = []
    soul_path = workspace / L.SOUL_FILE
    role, marker_id, marker_source, _seed = (None, None, None, False)
    if soul_path.exists():
        role, marker_id, marker_source, _seed = L.parse_soul(
            soul_path.read_text(encoding="utf-8"))
    if marker_id and meta and marker_id != meta.get("id"):
        print(f"warning: SOUL marker id {marker_id} != archived id {meta.get('id')}",
              file=sys.stderr)

    agents_path = workspace / L.AGENTS_FILE
    anti = None
    if agents_path.exists():
        anti, _rest = L.extract_agents_block(agents_path.read_text(encoding="utf-8"))

    name = None
    ident_path = workspace / L.IDENTITY_FILE
    if ident_path.exists():
        name = L.parse_identity_name(ident_path.read_text(encoding="utf-8"))
    name = name or meta.get("name") or (archive or {}).get("name") or agent

    mem_entries = None
    mem_path = workspace / L.MEMORY_FILE
    if mem_path.exists():
        parsed = L.parse_memory_block(mem_path.read_text(encoding="utf-8"))
        if parsed is not None:
            mem_entries = [{k: v for k, v in e.items() if not k.startswith("_")}
                           for e in parsed]

    routines = None
    cron_path = home / L.CRON_FILE
    if cron_path.exists():
        store = json.loads(cron_path.read_text(encoding="utf-8"))
        routines = []
        for job in store.get("jobs") or []:
            if job.get("agentId") not in (agent, None):
                continue
            sch = job.get("schedule") or {}
            if sch.get("kind") != "cron":
                notes.append(f"routine {job.get('name')!r}: schedule kind "
                             f"{sch.get('kind')!r} has no cron form; not exported")
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

    skills = None
    skills_dir = workspace / L.SKILLS_DIR
    if skills_dir.exists():
        skills = sorted(d.name for d in skills_dir.iterdir()
                        if d.is_dir() and (d / "SKILL.md").exists())
    arch_skills = (archive or {}).get("skills")
    if arch_skills:
        # Skills travel by name only; the archived list is the set this agent
        # is supposed to have, the workspace shows what is actually installed.
        # Archived order is kept; natively present extras append at the end.
        skills = list(arch_skills) + sorted(s for s in (skills or [])
                                            if s not in arch_skills)

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
    print(f"exported {data['source']}/{dossier_id} fingerprint {fp} "
          f"(routines: {'null' if routines is None else len(routines)}, "
          f"memory: {'null' if mem_entries is None else len(mem_entries)})",
          file=sys.stderr)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
