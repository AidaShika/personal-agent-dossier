# Personal Agent Dossier — Specification v1.0

*This is the English translation of `SPEC.md`. If the two ever disagree, the Chinese original prevails for now; translation fixes are welcome.*

Purpose: describe an agent's role, scheduled routines, long-term memory and dependencies in one platform-neutral file, so the agent can be migrated or synced across platforms.

## 1. Storage (two options, same format)

The same content can live in either place, at the user's choice. Fields and rules are identical; importers must read both.

| Form | How it is stored | Good for |
|---|---|---|
| File | One `<slug>.dossier.md` per agent; YAML front matter at the head (machine-readable), Markdown body below (human-readable) | Keeping in git, offline backups, target platforms that cannot read Notion |
| Notion | One page per bot. The page contains a heading "Machine-readable version (personal-agent-dossier/x.y)" (x.y is the spec version; pages created before the rename say agent-dossier/x.y), followed by a single ```yaml code block whose content is exactly the file form's front matter. All other sections are human-readable explanations generated from the YAML (`tools/render_notion.py`), never hand-written | Browsing, searching and filtering in Notion; reviewing as a team |

Rules:
- The YAML is authoritative. Sections of a Notion page outside the YAML block are explanations only; importers must not depend on them.
- A page contains exactly one YAML code block.
- If both forms exist, the one with the newer `exported_at` wins; equal timestamps count as identical.
- Encoding is UTF-8. The `spec` field is required and reads `personal-agent-dossier/1.0`. Importers must also accept the legacy identifiers `agent-dossier/0.1` and `agent-dossier/0.2` (versions from before the rename; v0.2 only added to v0.1 and changed nothing, so 0.1 dossiers remain valid, they just have no `refs`; v1.0 changed no fields or algorithms relative to 0.2, only the identifier).

## 2. Front matter fields

| Field | Required | Type | Meaning |
|---|---|---|---|
| spec | yes | string | Spec version: `personal-agent-dossier/1.0` (legacy `agent-dossier/0.1`, `agent-dossier/0.2` remain readable) |
| id | yes | string | Unique id on the source platform; sync pairs on it, never on display names. If the platform has no native agent id, the adapter mints one and notes its origin in `excluded`. An id is only guaranteed unique within the same `source`; cross-platform pairing compares `source` and `id` together |
| name | yes | string | Display name |
| title | no | string | One-line role tag |
| group | no | string | Section or group |
| status | yes | enum | `active` / `handed-over` / `retired` |
| exported_at | yes | date | Export date (ISO 8601) |
| source | yes | string | Platform exported from, e.g. `grok-bot` |
| fingerprint | yes | string | Role fingerprint; algorithm in section 2.1 |
| role | yes | string | Full role text, preserved verbatim |
| anti_jobs | no | list[string] | Anti-jobs: what this agent explicitly does not do |
| routines | yes | list or null | Scheduled routines; `[]` if there are none; `null` means "not exported this time", see section 3 |
| memory | yes | list or null | Long-term memory; `[]` if there is none; `null` means "not exported this time", see section 4 |
| refs | no | list | Other agents this agent depends on or hands work to (those named in role, anti_jobs or memory), each `{name, id}`. Ids cannot be resolved after a platform move; importers re-match by name. A whole "avoid duplicating each other's work" roster inside role does not count (see section 7). Register in refs only agents this one hands work to or depends on the output of; a passing mention does not count. When in doubt, ask: if that agent disappeared, would my function break? If yes, register it |
| skills | no | list[string] | Names of skills depended on; names only, never copied content |
| excluded | no | string | One line explaining what the export deliberately left out |

Granularity: one dossier corresponds to one independently hand-over-able unit of function. When one platform agent carries several functions (composite platforms), prefer splitting into one dossier per function; when unsure, export the whole agent and explain the granularity choice in `excluded`.

### 2.1 The fingerprint algorithm, exactly

1. For each of `name`, `title`, `role`: replace `\r\n` with `\n`, then strip leading and trailing whitespace by the Unicode White_Space property (this includes the full-width space U+3000 and U+00A0, not just ASCII spaces; Python's `str.strip()` and JavaScript's `trim()` both comply). A missing `title` counts as the empty string.
2. Join the three with the ASCII pipe `|`: `name|title|role`.
3. Encode as UTF-8, take SHA-1, keep the first 12 hex characters.

Step 1's stripping exists so that different YAML spellings (`|` vs `|-`) cannot cause false drift reports over a trailing newline. `tests/fingerprint-vectors.json` holds the standard answers; every implementation must pass `tests/check_vectors.py` before use.

Coverage: the fingerprint covers only name, title and role — not anti_jobs, routines, memory, refs or skills. Equal fingerprints therefore do not mean identical functions; during sync (section 6), anti_jobs and routines must additionally be compared item by item. If the fingerprint algorithm ever changes, the spec version must be bumped, and fingerprints registered in rosters under the old algorithm count as expired.

Note: the "content fingerprint" column of the Grok Bot Notion roster uses exactly this algorithm and is the same value as a dossier's `fingerprint`, so the two can be compared directly to detect drift. Registered values are only comparable within the same spec version.

## 3. Routine entries

| Field | Required | Meaning |
|---|---|---|
| id | yes | The routine's id on the source platform |
| name | yes | Routine name |
| schedule | yes | Cron expression or event-trigger description, with timezone stated |
| prompt | yes | The full prompt, verbatim |
| state | yes | `running` / `paused` / `deleted` |

## 4. Memory entries

| Field | Required | Meaning |
|---|---|---|
| fact | yes | One self-contained fact; not a chat transcript |
| kind | yes | `rule` / `preference` / `decision` / `history` |
| learned | no | Date recorded |

## 5. Redaction rules (exporters must apply them; importers must check again)

1. Addresses, phone numbers, birthdays, family members, ID numbers, bank cards, account passwords, tokens and API keys are never written into a dossier. When a pointer is needed, write `[stored in vault]`.
2. Before exporting, run a regex scan over `fact` and `prompt`: email addresses, Japanese phone numbers, 16-digit card numbers, tokens such as `sk-` / `ghp_`, and the value after `password` / `密码`. On a hit, that dossier is not exported and the hit location is reported; nothing is rewritten automatically. A single-dossier export stops there. In a batch export, the hit dossier is skipped and the rest continue, but the exporter must list the skipped count and names prominently in its summary and exit non-zero whenever anything was skipped — a skip must never look like success. An importer that hits must refuse the import. `role` is scanned too. The reference implementations in `adapters/grok-bot/` use one shared pattern set on both sides; the password pattern is `(?i)(password|passwd|密码)\s*[:：=]\s*\S+`.
3. An agent exports only its own memory, never another agent's.
4. UUIDs appearing in the body (usually other agents' ids) produce a warning, not a stop; they belong in `refs`, with a note that they cannot be resolved after a platform move.

## 6. Sync and migration semantics

- Export is idempotent: exporting the same source twice yields byte-identical output except for `exported_at`.
- Sync pairs on `id`. A differing `fingerprint` means the role changed; output the difference (compare `role` sentence by sentence).
- Import restores every field the target platform can express, verbatim. Fields it cannot express are preserved in the body, and the import report lists each one as lost or degraded, item by item. Importers must never drop a field silently.
- `null` vs `[]`: `null` means "not exported this time"; `[]` means "there are none". Reports must render `null` as "not exported — not the same as none", the original dossier is kept on file, and it must never be treated as empty.
- Deletion: a routine deleted at the source stays in the file marked `state: deleted`; it is not removed outright.

## 6.1 Platform capability levels

Importers declare their level at the top of their report, so readers know which semantics survive.

| Level | Meaning | Example |
|---|---|---|
| L0 | Can read the dossier and restore role and memory as text only; no structured fields | A platform with only notes and prompts |
| L1 | Keeps the full text, can verify fingerprints itself and tag memory by kind, but does not sync by id | A custom skill plus files |
| L2 | Pairs and updates by `id`; can create routines and write memory | Grok Bot (names and descriptions update by id; memory dates and routine ids change) |

## 7. Open questions (for a future v1.1 discussion)

- Rosters of bot names inside `role` go stale over time; should they be split into a dedicated field? (Raised by a third-party platform test.)
- Does memory need layers (short-term, long-term) and expiry times?
- Should hand-over relationships between agents (who succeeds whom) live in the same file, or in a separate `roster` file?
- How should attachments and tool permissions be expressed?

## 8. Changelog

- v1.0 (2026-10-28, owner's decision): project renamed to personal-agent-dossier (to avoid same-named projects, and to put the personal-agent positioning in the name); the spec identifier changed to `personal-agent-dossier/1.0` and the draft marker was dropped. Fields, the fingerprint algorithm and the Appendix A serialization are unchanged; importers must keep accepting `agent-dossier/0.1` and `agent-dossier/0.2`.
- v0.2 patch (2026-10-28, owner's decision): changed only the hit-handling semantics; no fields added, fingerprint algorithm unchanged.
  - 5.2: in batch exports a hit dossier is skipped while the rest continue, with a prominent summary report and a non-zero exit; single exports abort on a hit; imports refuse on a hit. The grok-bot exporter was updated accordingly.
- v0.2 patch (2026-10-28): clarifications only; no fields added, fingerprint algorithm unchanged.
  - 2.1: the fingerprint covers only name, title and role; during sync, anti_jobs and routines are compared item by item; changing the algorithm requires a spec version bump; registered values are comparable only within one spec version.
  - 2: refs gained the decision rule (if that agent disappeared, would my function break?).
  - 2: one dossier corresponds to one independently hand-over-able function unit; composite platforms should split by function.
  - 2: platforms without a native id mint one via the adapter and note the source; cross-platform pairing compares source and id together.
- v0.2 patch (2026-10-28, owner's direction, produced during the Muse adapter's serialization alignment work): added Appendix A "Standard serialization", pinning front-matter field order, block scalars, indentation and quoting rules; importers still must not depend on serialization details.
- v0.2 patch (from a third-party platform's second test round): the scope of refs spelled out; the strip whitespace set defined, with two vector groups added; the adapter task book no longer hard-codes a memory entry count.
- v0.2: Notion pages' human-readable sections are generated from the YAML to prevent drift (found by the Notion-form test); the fingerprint algorithm pinned down with test vectors; `refs` added; import requirements for `null` vs `[]`; platform capability levels; body UUID warnings (all from the Muse file-form test, 2026-10-28).

## Appendix A: Standard serialization (how front matter should be written)

This appendix pins down the byte shape **exporters should produce**. Importers must not depend on it — any valid YAML must remain readable. It constrains producers only, so dossiers from different platforms can be compared with a plain text diff side by side, and the "byte-identical except exported_at" idempotence requirement can be checked across implementations.

1. **Field order**: spec, id, name, title, group, status, exported_at, source, fingerprint, role, refs, anti_jobs, routines, memory, skills, excluded. Absent optional fields are omitted; routines / memory are written as `null` when not exported, never omitted. Within entries: routines use id, name, schedule, prompt, state; memory uses fact, kind, learned; refs use name, id.
2. **Block scalars**: `role` and routine `prompt` use the block scalar `|-` (use `|` when the content itself ends with a newline), with content indented 2 spaces relative to its key. Any other string containing newlines also uses a block scalar.
3. **Lists**: entries are indented 2 spaces under their key (the `key:` line, then two spaces before `- `); in a mapping entry, subsequent keys align with the first key. An empty list is written on one line, e.g. `routines: []`.
4. **Scalars and quoting**: plain, unquoted, never line-wrapped by default. Use double quotes when a value could be misread as another type (pure numbers, strings of digits and spaces, cron expressions containing ` *`, YAML reserved words such as null / true / false / yes / no / on / off), when it contains `: ` or ` #`, or when it starts with a YAML indicator character.
5. **Dates**: always bare ISO form (e.g. `2026-10-28`), never quoted; parsers treat them as strings, not date objects.
6. **File shape**: starts with `---`, the front matter ends with `---`; the body's first line is `# <name> 交接档案` (handover dossier). The rest of the body is human-readable prose and is outside this appendix.
