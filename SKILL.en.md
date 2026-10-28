---
name: personal-agent-dossier
description: 当你要把一个 AI agent 的职能、反职责、定时任务和长期记忆导出成平台无关的档案、从档案导入或还原一个 agent、检查两份档案是否漂移，或为你的平台写导出导入适配器时使用。用户也常这样说：把这个助手的活和记忆打包带走、我要换平台了、这个 bot 不用了把它的工作交接出去、两份档案对一下看哪儿对不上；pack up this agent and move it to another platform、I'm switching agents, take its memory with it；このボットの引き継ぎをして、別のプラットフォームに引っ越したい、記憶ごと持っていって；이 봇 더 안 쓰니까 인수인계해줘、플랫폼 옮길 거야 기억까지 챙겨서 내보내줘。不用于：导出聊天记录、agent 之间的实时通信协议（如 A2A）类问题。
---
# personal-agent-dossier

中文版：[SKILL.md](SKILL.md)

personal-agent-dossier is a platform-neutral format for handing one personal agent's job over to another: YAML front matter, a Markdown body, and it can also live inside a Notion page. Agents use it to hand work over, move to a new platform, and stay in sync across platforms. If you have just arrived in this repository, read this file first and pick a route from the table below.

## How users actually ask

People almost never say "export a dossier". They say things like this (routes marked; how to do each one is in the table further down):

- 「把这个助手的活和记忆打包带走」「我要换平台了」→ Export
- 「这个 bot 不用了，把它的工作交接出去」「把这份档案导进来」→ Import (dry run first; write for real only after the user confirms)
- 「两份档案对一下，看哪儿对不上」「这个档案是不是被人改过」→ Check a dossier, or check for drift
- 「给新平台写个适配器，让它也能读这种档案」→ Write an adapter

Other languages sound the same: "pack up this agent and move it to another platform", "hand this bot's job over to another agent" (English); このボット、もう使わないから仕事を引き継がせて、別のプラットフォームに引っ越したい、記憶ごと持っていって (Japanese); 이 봇 더 안 쓰니까 다른 데로 인수인계해줘、플랫폼 옮길 거야, 기억까지 챙겨서 내보내줘 (Korean).

Exporting chat history, or getting two agents to talk to each other, is a different job. This format does not cover either.

## First, decide what you are doing

| Job | How |
|---|---|
| Export: turn yourself (or an agent you can read) into a dossier | Read sections 2 and 5 of `SPEC.en.md` and follow the shape of `adapters/grok-bot/export_dossiers.py`. No adapter for your platform yet? See "Write an adapter for my platform" below |
| Import: bring an agent back from a dossier | Run the dry-run importer first and look at its plan and loss list (`adapters/grok-bot/import_dossier.py`, read-only). Ask the user before writing anything for real |
| Check: has a dossier drifted from another dossier, or from how the agent is now? | Work out the `fingerprint` the way section 2.1 of the SPEC describes. If it differs, compare `role` line by line. If it matches, still compare `anti_jobs` and `routines` one item at a time; the fingerprint does not cover them |
| Store dossiers in Notion | Generate the page body from the YAML with `tools/render_notion.py`. One yaml code block per page, and the YAML is what counts |
| Write an adapter for my platform | Read `skills/personal-agent-dossier-adapter/SKILL.en.md`, work through its seven steps, and write an `adapter-report.md` |
| Test an importer against the spec | Work through `docs/conformance-test.md` once |

## What is in this repository

| Path | What it is for |
|---|---|
| `SPEC.md` | The format itself: fields, the fingerprint algorithm, the sensitive-data rules, sync semantics, platform levels. English translation: `SPEC.en.md` |
| `tests/` | Standard fingerprint test vectors and the scripts that check them. Every implementation runs `python3 tests/check_vectors.py` first |
| `examples/scribe.dossier.md` | A made-up example dossier, used for round-trip tests |
| `tools/render_notion.py` | Turns a dossier into a Notion page body |
| `adapters/<platform>/` | One folder per platform, with its exporter and importer. Each adapter states its own level and its known downgrades |
| `skills/personal-agent-dossier-adapter/SKILL.md` | Step-by-step guide to writing an adapter, plus the report template (English: `SKILL.en.md`, same folder) |
| `docs/conformance-test.md` | The importer conformance test |

## Rules that apply to every route

1. Go by `SPEC.md` (or `SPEC.en.md`), not by memory. If the spec is wrong or unclear, say so in your report. Do not edit the spec, the test vectors, or the examples.
2. Pass the fingerprint test vectors before you touch real data.
3. Export only what you can read yourself. Another agent's memory is not yours to export.
4. Home addresses, phone numbers, ID documents, bank card numbers, account passwords, and tokens stay out of dossiers, this repository, Notion, and reports. Scan before you export. If the scan hits, stop; do not quietly edit the hit away.
5. `null` means "not exported this time". `[]` means "there really are none". An importer that mixes the two up is broken.
6. Importers do not drop fields quietly. Every loss or downgrade gets listed, one by one, and the report opens by declaring the importer's level: L0, L1, or L2.
7. No writing into a real agent, its memory, or its scheduled tasks without the user's go-ahead, and no sending messages either.
