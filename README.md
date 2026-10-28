# personal-agent-dossier

[![CI](https://github.com/AidaShika/personal-agent-dossier/actions/workflows/ci.yml/badge.svg)](https://github.com/AidaShika/personal-agent-dossier/actions/workflows/ci.yml)

**English** | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [한국어](README.ko.md)

> Move a personal AI agent to a new platform without losing its job.

## The problem

New AI agent platforms appear one after another, and people switch between them all the time. Trying a new platform is easy. Moving the agent is not.

A personal agent that has worked for you for months is more than a prompt. It has a role and explicit anti-jobs (things it must *not* do), scheduled routines, long-term memory, dependencies on other agents, and skills it relies on. All of that usually lives inside the old platform. Copy it by hand and things quietly go missing: a routine's schedule survives but its full prompt doesn't, memory arrives as an undifferentiated blob, and nobody can tell what was lost until the agent misbehaves.

**personal-agent-dossier** packages that hand-over into one portable file: YAML front matter a machine can verify, plus a Markdown body a human can read. The same content can also live in a Notion page. This repository is itself packaged as a skill: an agent that clones it can read `SKILL.md`, pick a route, and export or import an agent by following the instructions.

## What a dossier contains

| Part | Contents |
|---|---|
| Role | The agent's job description, verbatim, plus its anti-jobs |
| Routines | Scheduled tasks: name, schedule (with timezone), full prompt, state |
| Memory | Long-term facts, each tagged `rule` / `preference` / `decision` / `history` |
| Dependencies | Other agents it hands work to or relies on (`refs`), and skill names |
| Fingerprint | A 12-hex-digit SHA-1 over name + title + role, so two platforms can detect drift without diffing prose |
| Provenance | Source platform, export date, and an `excluded` note saying what was deliberately left out |

Two distinctions the format is strict about: `null` means "not exported this time", `[]` means "there are none". An importer must never silently drop a field. Anything the target platform cannot express goes into the import report as an itemized loss/degradation list.

## How this differs from nearby ideas

| | What it does | What it does not do |
|---|---|---|
| A2A / Agent Cards | Runtime discovery and communication between agents | Archive a personal agent's duties and memory for migration |
| `AGENTS.md` / `CLAUDE.md` | Project instructions for coding agents | Per-agent hand-over: routines, memory kinds, fingerprint, loss report |
| Whole-installation export | Moves an entire agent setup, configuration and credentials included | A minimal, secret-free hand-over file that both sides scan before trusting |
| Chat export | Saves the conversation transcript | Structured duties, schedules and memory you can rebuild an agent from |

## Safety by design

- No addresses, phone numbers, birthdays, ID numbers, passwords, tokens or API keys ever go into a dossier.
- Exporters scan role, memory and prompts for sensitive patterns before writing; importers scan again and refuse on a hit. In batch exports a hit dossier is skipped, the rest continue, and the run exits non-zero.
- Importers declare a capability level (L0: text only; L1: full text + self-verified fingerprint; L2: sync by id), so you know in advance what will survive the move.

## Quick start

```bash
pip install -r requirements.txt
python3 tests/check_vectors.py                       # verify the fingerprint algorithm first
python3 tools/dossier_check.py examples/scribe.dossier.md   # validate any dossier file
python3 adapters/grok-bot/import_dossier.py examples/scribe.dossier.md   # dry-run import: plan + loss list
python3 tools/render_notion.py examples/scribe.dossier.md > page.md      # render the Notion page form
```

## Contents

| Path | What it is |
|---|---|
| `SKILL.md` | Entry point of this repository as a skill: routes for export, import, drift check, Notion storage, adapter writing |
| `SPEC.md` / `SPEC.en.md` | The format specification (v1.0, Chinese original with English translation) |
| `examples/scribe.dossier.md` | A fictional, complete example with routines and all memory kinds |
| `tests/` | Standard fingerprint test vectors and the checker every implementation must pass |
| `tools/dossier_check.py` | Standalone validator: fields, fingerprint, sensitive-pattern scan (no adapter needed) |
| `tools/render_notion.py` | Renders a dossier into a Notion page body; human sections are generated from the YAML, so they cannot drift |
| `adapters/` | Per-platform exporters and dry-run importers |
| `skills/personal-agent-dossier-adapter/SKILL.md` | The adapter-writing guide: hand it to an agent on a new platform and it writes its own adapter |
| `docs/conformance-test.md` | The conformance test an importing platform runs to prove it understood the format |

## Adapters

| Platform | Level | Included | Notes |
|---|---|---|---|
| Grok Bot | L2 | Batch exporter, dry-run importer | The platform the format was born on; syncs by agent id |
| Muse | L1 | Exporter, dry-run importer, self-export example | Report: [`adapters/muse/adapter-report.md`](adapters/muse/adapter-report.md) |
| Hermes | L2 (scoped: one dossier = one Hermes home) | Exporter, importer (dry-run + apply) | Written by Hermes Agent itself from the adapter guide; verified end-to-end on a real Grok Bot dossier (round-trip fingerprint unchanged). Report: [`adapters/hermes/adapter-report.md`](adapters/hermes/adapter-report.md) |

Writing an adapter for your platform is the intended way to join: follow the guide in `skills/personal-agent-dossier-adapter/`, pass the fingerprint vectors, run the conformance test, and open a PR that adds your row here together with your adapter report.

## Case study: from Grok Bot to Muse

This format was not designed in the abstract. It grew out of a working roster of 30+ personal bots on the Grok Bot platform, and its first cross-platform trip was a real hand-over:

1. A bot's dossier was exported on the Grok Bot side and imported by Muse, first as a file, then again from a Notion page.
2. Muse declared L1, verified fingerprints against the standard vectors, round-tripped the example and a real 0.1 dossier, and published an itemized list of what its platform degrades.
3. The test findings went back into the spec as clarifications: what the fingerprint does and does not cover, how to decide `refs`, granularity for composite agents, ids on platforms that have none.
4. The Muse adapter then exported its own agent as a worked example (`adapters/muse/examples/kubo.dossier.md`).

## Status and roadmap

v1.0. The spec was renamed from `agent-dossier` at v1.0; importers keep accepting the legacy `agent-dossier/0.1` and `agent-dossier/0.2` identifiers, and fingerprints are unaffected.

Open questions (discussion welcome): splitting rosters out of `role` into a dedicated field, memory layering and expiry, hand-over relationships between agents, and how to express attachments and tool permissions.

## License

MIT, see `LICENSE`.
