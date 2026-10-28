---
name: personal-agent-dossier-adapter
description: 当你要为自己所在的平台（任意 AI agent 平台）写 personal-agent-dossier 的适配器，也就是把本平台的 agent 导出成档案、或把档案导入本平台时使用。给你规范、步骤、验收标准和报告模板。用户常这样说：给新平台写个适配器；write an adapter for my platform；自分のプラットフォーム用にアダプタを書いて；내 플랫폼용 어댑터를 써줘。
---
# Write a personal-agent-dossier adapter for your platform

中文版：[SKILL.md](SKILL.md)

You are an agent on some platform, and you know how that platform stores its prompts, its memory, and its scheduled tasks better than anyone looking in from outside. That is why you write the adapter, not us. The spec and the tests live in this repository and are maintained here; your part is wiring your platform up to them.

## What you need (all of it is in this repository)

| Path | What it is for |
|---|---|
| `SPEC.md` | The format specification. Read the whole thing first (English translation: `SPEC.en.md`) |
| `tests/fingerprint-vectors.json`, `tests/check_vectors.py` | The expected fingerprint results. Every implementation has to pass these before anything else |
| `examples/scribe.dossier.md` | A made-up example with a scheduled task and three kinds of memory. Your round-trip test subject |
| `docs/conformance-test.md` | The importer conformance test |
| `tools/render_notion.py` | Turns a dossier into a Notion page body (for setups that store dossiers in Notion) |
| `adapters/grok-bot/` | The reference implementation: one exporter, one read-only dry-run importer. Copy the structure, not the paths |

## Steps

1. **Read the spec, then pick a target level.** Section 6.1 defines L0, L1, and L2. If you are not sure you can reach a level, declare the one below it, test, and raise it later.
2. **Fill in the mapping table.** No code yet. For each field, write down where it would live on your platform:

   | Dossier field | Where it lives on my platform | How well it survives (as-is / degraded / no home for it) |
   |---|---|---|
   | id, name, title, role | | |
   | anti_jobs | | |
   | routines | | |
   | memory (kind and learned included) | | |
   | skills, refs, group | | |

   A field with no home on your platform still goes in the table, and later into your loss list. Dropping it without a word is the one thing you must not do.
3. **Get the fingerprint right first.** Code up the algorithm in section 2.1 of the SPEC and run every vector in `tests/fingerprint-vectors.json`. All of them pass before you go on. Traps people actually fall into:
   - Each piece of text gets `\r\n` turned into `\n` first, then leading and trailing Unicode whitespace stripped (the full-width space and the no-break space count).
   - YAML `|` keeps one more trailing newline than `|-`, so strip and be done with it. Never hash the raw bytes.
   - Some platforms glue an agent's name and job title into a single display name (Grok Bot shows "Hatch · Bot设计助手"). Only those platforms split on ` · `: `name` is the part before it, `title` the part after. If your platform keeps them separate, or has no title at all, fill in what you have and leave `title` out.
4. **Write the exporter (your platform → dossier).**
   - Export only what you can read yourself. Another agent's memory is not yours to export.
   - `role` goes in word for word. No tidying, no shortening.
   - Routines or memory you did not export are `null`. `[]` is only for "there really are none".
   - Before anything is written out, scan `role`, the memory facts, and the routine prompts for things that should never travel: email addresses, Japanese phone numbers, 16-digit card numbers, tokens that start `sk-` or `ghp_`, password values. A hit stops the export; report where it is. Do not edit the hit away and carry on.
   - If the text or the `role` mentions another agent's id, that id goes in `refs`.
   - Run the export twice. Apart from `exported_at`, the two outputs have to be byte for byte the same.
5. **Write the importer (dossier → your platform).**
   - Dry run first: print what would happen and the loss list, and touch nothing.
   - Take both shapes: a file with front matter, and a Notion page holding exactly one ` ```yaml ` block. The YAML is what counts. Text fetched back from Notion sometimes arrives with `[rule]` escaped as `\[rule\]`; be ready for that.
   - Check the required fields, the `spec` version (0.1 and 0.2 both import), the recomputed fingerprint, the memory kinds, and run the sensitive-data scan once more.
   - Real writes wait for the user's go-ahead. Memory lands in a test file by default, never straight into the real memory store.
   - Where the dossier says `null`, your report says "not exported", which is not the same as "does not exist".
6. **Round-trip it.** Take `examples/scribe.dossier.md`: import it, export the result, and compare the two dossiers field by field, saying plainly what came back and what changed. Then work through `docs/conformance-test.md` once.
7. **Ship it.** Your adapter goes in `adapters/<platform-name>/` with a short README (declared level, the mapping table, known downgrades, how to run it) and an adapter report; the template for the report is right below.

## Adapter report template (`adapter-report.md`)

1. Platform name, and the level you are declaring (L0 / L1 / L2)
2. Fingerprint vectors: `PASS n vectors`, or which ones failed
3. The mapping table from step 2, filled in
4. Round-trip results: what came back, what changed
5. Loss and downgrade list
6. Notes on the spec itself: anywhere it is ambiguous, or fights with how your platform works (this section only; do not edit `SPEC.md`)
7. What you did not test, and why

## Do not

- Edit `SPEC.md`, the test vectors, or the examples. Problems with the spec belong in section 6 of your report.
- Export another agent's memory or anyone's personal data. Addresses, phone numbers, ID documents, account passwords, and tokens stay out of the repository, out of dossiers, and out of reports.
- Guess how your platform behaves. If you are not sure, try it on the platform and then write down what happened.
- Drop a field without listing it, or read `null` as "empty".
- Send mail or messages, or contact anyone outside.
- Write into a real agent, its memory, or its scheduled tasks before the user has said yes.
