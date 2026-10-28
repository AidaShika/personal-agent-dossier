#!/usr/bin/env python3
"""Dry-run importer for personal-agent-dossier/1.0 (and legacy agent-dossier/0.1, 0.2) -> Muse.

Reads one dossier (file form with front matter, bare YAML, or Notion page
text holding exactly one ```yaml block), runs all SPEC checks, and prints:
- the checks and warnings
- the import plan: what a real import WOULD create on Muse
- the loss/downgrade list (nothing is dropped silently, SPEC section 6)

It never creates or modifies real agents, skills, memory, or cron jobs.
With --stage DIR it additionally writes staging artifacts *inside DIR only*
(dossier copy, SKILL.md draft, memory test file, routines plan, meta.json);
export_muse.py can rebuild a dossier from that staging directory, which is
how the round-trip test works. Real writes always need the user's explicit
confirmation, outside this script.

Muse declares level L1 (SPEC 6.1): it can store the full text, verify
fingerprints itself, and tag memory by kind, but it has no agent entity
keyed by the dossier `id`, so it cannot pair/update by id (that is L2).

Usage: import_dossier.py FILE [--stage DIR]
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dossier_lib as dl

LEVEL_LINE = ("platform level: L1 (Muse: full text kept, fingerprint "
              "self-verified, memory tagged by kind; no id-keyed agent entity, "
              "so no pairing/update by id)")


def slugify(name):
    s = re.sub(r"[^\w\- ]", "", (name or "agent").lower(), flags=re.UNICODE)
    return re.sub(r"[\s_]+", "-", s.strip()) or "agent"


def build_plan(data):
    """What a real import on Muse would do. Returns (plan, loss) lines."""
    plan, loss = [], []
    name = data.get("name") or "agent"
    slug = slugify(name)
    plan.append(f"custom skill draft at ~/workspace/custom-skills/{slug}/SKILL.md "
                f"(directory name is a slug of the name; the name itself is kept "
                f"verbatim in the file)")
    plan.append("role stored verbatim as the SKILL.md body section '职能（role）'")
    if data.get("anti_jobs"):
        plan.append(f"anti_jobs ({len(data['anti_jobs'])}): stored as a '反职责（anti_jobs）' "
                    "section in the same SKILL.md, as a text list")
        loss.append("anti_jobs: no dedicated field on Muse; kept as text in the "
                    "skill file (content intact, structure degraded)")
    if data.get("title"):
        loss.append("title: Muse skill front matter has no title field; the title is "
                    "folded into the description text and kept verbatim in the "
                    "archived dossier copy")
    loss.append("id: Muse has no agent entity keyed by this id; the source id is "
                "kept verbatim in the archived dossier copy and in meta, but cannot "
                "be used for pairing or updates (this is why Muse is L1, not L2)")
    if data.get("group"):
        loss.append(f"group {data['group']!r}: Muse has no skill/chat grouping; "
                    "kept only in the archived dossier copy")
    routines = data.get("routines")
    if routines is None:
        loss.append("routines: not exported (null) — 未导出，不等于没有. "
                    "The original dossier copy is kept; no cron is planned.")
    elif routines:
        for r in routines:
            if r.get("state") == "deleted":
                plan.append(f"routine {r.get('name')!r}: state=deleted, kept in the "
                            "plan file only, no cron created")
            else:
                plan.append(f"routine {r.get('name')!r}: a Muse cron CAN express it "
                            f"({r.get('schedule')}), state running/paused maps to "
                            "enabled/disabled — but creating it needs the user's "
                            "confirmation; this importer does not create it")
        loss.append(f"routines ({len(routines)}): cron ids are assigned by Muse at "
                    "creation time, so routine ids change; schedule text with an "
                    "explicit timezone is kept verbatim in the plan")
    memory = data.get("memory")
    if memory is None:
        loss.append("memory: not exported (null) — 未导出，不等于没有. "
                    "The original dossier copy is kept; memory starts unstaged.")
    elif memory:
        plan.append(f"memory ({len(memory)} facts): staged one per line in a memory "
                    "test file, fact text verbatim, tagged [kind · learned]; "
                    "writing into real memory needs the user's confirmation")
        loss.append("memory.kind/learned: Muse memory files are free text, so kind "
                    "(enum) and learned (date) degrade to an inline text tag "
                    "'[kind · learned]'; fact text itself is verbatim")
    if data.get("skills"):
        loss.append(f"skills {data['skills']}: only names travel; a skill exists on "
                    "Muse only if a same-named SKILL.md is installed — missing ones "
                    "must be installed separately")
    if data.get("refs"):
        loss.append("refs: after migration ids do not resolve; Muse re-matches by "
                    "name against its people/role records and keeps the source id "
                    "as a note only")
    if data.get("excluded"):
        loss.append("excluded by exporter: " + str(data["excluded"]))
    loss.append("status/exported_at/source/fingerprint: documentary fields; kept "
                "verbatim in the archived dossier copy, not consumed by the platform")
    return plan, loss


def stage(data, stage_dir, src_label):
    """Write staging artifacts inside stage_dir only. Returns list of filenames."""
    os.makedirs(stage_dir, exist_ok=True)
    written = []

    def w(fname, text):
        with open(os.path.join(stage_dir, fname), "w", encoding="utf-8") as f:
            f.write(text)
        written.append(fname)

    w("dossier-copy.md", dl.render_dossier(data))
    name = data.get("name") or "agent"
    desc = data.get("title") or f"{name} 的职能档案（由 personal-agent-dossier 导入，待人工补全触发说明）"
    lines = ["---", f"name: {slugify(name)}",
             f"description: {desc}", "---", "",
             f"# {name}", "", "## 职能（role）", "", data.get("role") or "", ""]
    if data.get("anti_jobs"):
        lines += ["## 反职责（anti_jobs）", ""]
        lines += [f"- {a}" for a in data["anti_jobs"]]
        lines.append("")
    w("SKILL.md.draft", "\n".join(lines))
    if data.get("memory"):
        mem_lines = []
        for m in data["memory"]:
            tag = m.get("kind") or ""
            if m.get("learned"):
                tag = f"{tag} · {m['learned']}" if tag else str(m["learned"])
            mem_lines.append(f"- [{tag}] {m.get('fact', '')}" if tag
                             else f"- {m.get('fact', '')}")
        w("memory-test.md", "\n".join(mem_lines) + "\n")
    else:
        w("memory-test.md", "")
    routines = data.get("routines")
    w("routines-plan.json", json.dumps(
        {"note": "plan only — creating crons needs user confirmation; "
                 "null means not exported, not none",
         "routines": routines}, ensure_ascii=False, indent=2) + "\n")
    meta = {k: data.get(k) for k in ("spec", "id", "name", "title", "group", "status",
                                     "source", "anti_jobs", "skills", "refs", "excluded")
            if data.get(k) is not None}
    meta["staged_from"] = src_label
    w("meta.json", json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    return written


def main():
    args = sys.argv[1:]
    stage_dir = None
    if "--stage" in args:
        i = args.index("--stage")
        stage_dir = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        sys.exit(__doc__)
    try:
        data, _body = dl.load_dossier_file(args[0])
    except dl.DossierError as e:
        print("FAIL: " + str(e))
        sys.exit(1)
    errors, warnings = dl.validate(data)
    print("DRY RUN " + os.path.basename(args[0]))
    print(LEVEL_LINE)
    print("checks:", "PASS" if not errors else "FAIL")
    for e in errors:
        print("  FAIL", e)
    for wtext in warnings:
        print("  WARN", wtext)
    if errors:
        sys.exit(1)
    plan, loss = build_plan(data)
    for p in plan:
        print("plan:", p)
    for l in loss:
        print("loss/downgrade:", l)
    if stage_dir:
        written = stage(data, stage_dir, os.path.basename(args[0]))
        print("staged (inside %s only): %s" % (stage_dir, ", ".join(written)))
        print("note: staging is not an import. Nothing outside the staging "
              "directory was created or changed.")


if __name__ == "__main__":
    main()
