# Hermes 适配器报告（personal-agent-dossier/1.0）

## 1. 平台与声明等级

- 平台：**Hermes Agent**（Nous Research；一个 Hermes home 就是一个 agent 的运行根：`SOUL.md` 是身份槽，`memories/` 是长期记忆，`skills/` 是技能，`cron/jobs.json` 是定时任务，多 agent 用 `profiles/` 各开一个 home）
- 声明等级：**L2**，作用域是「一份档案 = 一个 Hermes home」这一种部署形态（也是本适配器唯一实现的写入形态）

### 定级依据（全部在本平台实测）

SPEC 6.1 的 L2 是「能按 id 配对并更新职能，能建定时任务和写记忆」。三条逐项实测：

1. **按 id 配对并更新职能**：导入时把档案的 `source`+`id` 与字段映射写进目标 home 的 `dossier/import-meta.json`；同一份档案再次 `--apply` 到同一个 home，是**原地更新**而不是新建。实测用一份改了 role、改了一条 memory 的 Hatch 副本（同 `source`+`id`，指纹从 `56cd7b80e6db` 变为 `1e7026c01b59`）再导入：`SOUL.md` 被替换为新 role，记忆仍是 8 条（旧条目被替换，没有重复），`import-meta.json` 的指纹随之更新；再导出得到 `1e7026c01b59`，与改后档案一致。
2. **能建定时任务**：routines 写成 `cron/jobs.json` 里 Hermes 自己的 job 记录形态（字段与 `cron/jobs.py:create_job` 产出的记录一致）。实测 `hermes cron list` 能列出导入的任务（`[active]`，`Schedule: 0 9 * * 1 (Asia/Tokyo)`）；`hermes cron doctor` 报 **found no issues**；Hermes 自己的 `load_jobs()` + `compute_next_run()` 对该记录算出 `2026-11-02T09:00:00+09:00`。
3. **能写记忆**：memory 写进 `memories/MEMORY.md`，用的是 Hermes 自己的条目格式（`tools/memory_tool_store.py:ENTRY_DELIMITER = "\n§\n"`）。实测 `hermes prompt-size`（用一份 3 条事实的 Scribe 副本导入的 home）：`memory` 块 585 B，把 `MEMORY.md` 清空后同一命令报 0 B；`SOUL.md` 追加 3,000 字后 `stable (identity/guidance/skills)` 档从 5,457 B 涨到 8,038 B。即角色与记忆确实是进系统提示的那两块，不是躺在磁盘上的文本。

### 为什么不到「无条件的 L2」

Hermes 没有一张按**外部** id 索引的 agent 名册（Grok Bot 那种「按 id 找 bot、改 name/description」的实体）。`id ↔ home` 的对应表是**适配器**写在目标 home 里的 `dossier/import-meta.json`，平台本身不认这个 id。由此有两个直接后果，都写进了实现：

- **多份档案共用一个 home 就只有 L1**：`SOUL.md` 只有一个身份槽，第二个 agent 的 role 无处可放。导入器检测到 home 里已有别的 `source`+`id` 时直接拒绝（退出码 1），不假装能装下。
- **id 的解释范围**：`id` 只在「同一个 home + 同一 source」内可配对。跨平台、跨 home 配对仍需按 SPEC 第 2 节的规则比 `source`+`id`，再人工确认。

## 2. 指纹向量结果

- 仓库官方脚本 `tests/check_vectors.py`：**PASS 8 vectors**
- 本适配器自己的实现（`adapters/hermes/dossier_lib.py`，按 SPEC 2.1 独立写）：**PASS 8 vectors**
- 附带核对：`hatch.dossier.md`（旧标识 `agent-dossier/0.2`）声明指纹 `56cd7b80e6db`，重算一致；`examples/scribe.dossier.md` 声明 `1e6ed4957379`，重算一致；从 scratch-home 导出的 Hatch 档案指纹同为 `56cd7b80e6db`。

## 3. 映射表

| 档案字段 | Hermes 放在哪里 | 还原程度 |
|---|---|---|
| id | `dossier/import-meta.json`（配对键，与 `source` 一起）；归档副本里也有一份 | 降级（平台无 agent id，配对表由适配器维护） |
| name | `dossier/import-meta.json` + 归档副本；Hermes 用 home 目录名标识 agent，不用显示名 | 降级（值原样留存，平台不消费） |
| title | 归档副本（`import-meta.json` 里也有） | 存不下（无 title 槽，不参与匹配或显示） |
| group | 归档副本 | 存不下（Hermes 没有分区/分组概念） |
| status | `dossier/import-meta.json` | 降级（文档性；`retired` 的档案同样会被导入） |
| exported_at / source | `dossier/import-meta.json` | 文档性；`source` 参与配对键 |
| fingerprint | `dossier/import-meta.json`，并在每次导入时重算比对 | 不一致即拒绝导入 |
| role | `SOUL.md`（身份槽，注入系统提示） | 原样 |
| anti_jobs | 同一 `SOUL.md` 的 `## 反职责（anti_jobs）` 小节，`- ` 列表 | 降级（内容原样，无结构化字段） |
| routines.id | `cron/jobs.json` 里由适配器分配的 12 位 hex；同一档案再导入时沿用 | 降级（与源平台 id 不同，但同一 home 内稳定） |
| routines.name / prompt | job 记录的 `name` / `prompt`，原文 | 原样 |
| routines.schedule | `schedule = {kind: "cron", expr, display}`，`display` 保留原文（含时区）；`next_run_at` 在装了 croniter 时算出，否则留给 ticker | 降级（Hermes 无单任务时区，expr 按 profile 时区求值） |
| routines.state | `running` → `enabled: true`/`scheduled`；`paused` → `enabled: false`/`paused`；`deleted` → 不建（此前建过的会被移除） | 降级 |
| memory.fact | `memories/MEMORY.md`，一条一行，`\n§\n` 分隔 | 原样（条目内的换行变空格，见第 5 项） |
| memory.kind / learned | 行内标签 `[kind · learned]` | 降级（枚举与日期变文本） |
| refs | 归档副本 | 存不下（id 换平台不解析，按名字人工重新对应） |
| skills | 只做 `skills/` 下的同名存在性核对，不创建目录 | 降级（只有名字） |
| excluded | 归档副本 | 原样（文本） |

导入的落点形态：一份档案 → `SOUL.md`（role + anti_jobs）+ `memories/MEMORY.md`（facts）+ `cron/jobs.json`（routines，有才写）+ `dossier/<slug>.dossier.md`（全字段归档）+ `dossier/import-meta.json`（字段映射、id、写入记录）。空目录 `skills/`、`cron/output/` 一并建好，让 home 的形态与真实 Hermes home 一致。

## 4. 往返测试与四项验收

### 四项验收（全部真跑，命令与结果照录）

对象：`~/hermes-adapter-run/hatch.dossier.md`（真档案，`spec: agent-dossier/0.2`，指纹 `56cd7b80e6db`）。日志留在 `~/hermes-adapter-run/accept{1,2,3}-*.log`。

**1) dry-run**：`python3 import_dossier.py ~/hermes-adapter-run/hatch.dossier.md`

- 退出码 0；`checks: PASS`；1 条预期内 WARN：role 里点名 Big Boss 的 UUID，按 SPEC 5.4 只提示不拦截（该 UUID 已在 `refs` 里，所以没有「未登记」的附加提示）
- 5 条 plan、8 条 loss/downgrade；没有创建或修改任何文件（dry-run 后 `scratch-home` 仍不存在）

**2) `--apply` 到一个全新的 home**：`--apply --target-home ~/hermes-adapter-run/scratch-home`

- 退出码 0；写入 4 个文件：`SOUL.md`（656 字符）、`memories/MEMORY.md`（631 字符 / 8 条）、`dossier/hatch.dossier.md`、`dossier/import-meta.json`
- `routines: []`，所以按计划**没有**写 `cron/jobs.json`（档案自己说没有定时任务，不是「没导出」）
- 报告行：`applied: 4 file(s) under ...; nothing outside it was touched.`；真实的 `~/.hermes` 只做过只读参考（`SOUL.md`、`memories/` 的 mtime 仍停在会话前）

**3) 从 scratch-home 导出并比对指纹**：`export_dossier.py --home ~/hermes-adapter-run/scratch-home --out ... --date 2026-10-28`

- 退出码 0；`wrote ... fingerprint 56cd7b80e6db name='Hatch' id='bd3eda99-…' memory=8 routines=0`
- **指纹一致**：原档案声明 / 原档案重算 / 导出档案声明 / 导出档案重算，四个值都是 `56cd7b80e6db`
- 逐字段比对：id、name、title、group、status、exported_at、role、refs、anti_jobs、routines、memory、skills、excluded **全部相同**；不同的只有两处，且都是如实的变化：`spec`（`agent-dossier/0.2` → `personal-agent-dossier/1.0`，导出恒写当前标识）与 `source`（`grok-bot` → `hermes`）

**4) 仓库自带测试**

- `python3 tests/check_vectors.py` → `PASS 8 vectors`，退出码 0
- `python3 tools/dossier_check.py ~/hermes-adapter-run/hatch.roundtrip.dossier.md ~/hermes-adapter-run/hatch.dossier.md` → 两份都是 `OK`，退出码 0
- 顺带：`python3 adapters/hermes/import_dossier.py examples/scribe.dossier.md`（空跑）退出码 0

### 其他实测

- **Scribe 往返**（`examples/scribe.dossier.md` → 导入 → 再导出）：整文件逐行 diff 只有三处不同——`source`（example → hermes）、routine id（`example-routine-0001` → 平台分配的 12 位 hex）、以及人读正文那句话（导出器按模板重生成，SPEC 第 1 节说正文不属机器可读部分）。带时区的 `schedule: "0 9 * * 1 (Asia/Tokyo)"` 字节一致，指纹 `1e6ed4957379` 不变，memory 3 条（rule / preference / decision，均带 learned）逐字还原。`tools/dossier_check.py` 判 OK。
- **幂等**：同一 home 连续 `--apply` 两次，`SOUL.md` 与 `MEMORY.md` 字节一致、cron job id 不变、无重复条目；同一 home 同 `--date` 连续导出两次，产物字节一致（SPEC 第 6 节）。
- **`null` 语义**：用一份 routines/memory 都是 `null` 的 Hatch 副本导入，报告两处都写「未导出，不等于没有」，不写 `MEMORY.md`、不建 cron；再从该 home 导出，`routines: null`、`memory: null` 原样保持（没有退化成 `[]`）——归档里的 null 标记被读回来了。
- **Notion 形式**：构造一页带标题、唯一一个 ` ```yaml ` 块、块内 `[` `]` 被转义成 `\[` `\]` 的文本（并把 role 改成含 `[rule]` 后重算指纹 `09ad7923ea0f`）：导入 `checks: PASS`，说明转义还原正确（不还原的话 role 会多出反斜杠、指纹对不上）。同一文本再塞第二个 yaml 块：`FAIL: more than one yaml block`，退出码 1。
- **安全闸门**：① 目标 home 有手写的 `SOUL.md`（无适配器元数据）时 `--apply` 拒绝、退出码 1、**一个字节都不写**（连空目录都不建）；② 加 `--replace-soul` 后成功，原文件保留为 `SOUL.md.pre-dossier`；③ 同一 home 塞第二份不同 `source`+`id` 的档案被拒绝，退出码 1。
- **脱敏**：memory 里带 `password: …` 的档案导入被拒（`sensitive pattern password-value in memory[0].fact`，退出码 1）；`SOUL.md` 里带邮箱的 home 导出中止（`sensitive pattern email in role`，退出码 1）且**没有**产生输出文件。Hatch、Scribe、Notion 构造页、null 版与改版六份输入扫描零命中。
- **边缘 routine**：事件触发型 schedule（「每次收到新邮件时（Asia/Tokyo）」）不建 cron、只留归档并在 loss 里写明；6 字段 cron 表达式只取前五个字段，同样在 loss 里写明；`paused` 的 routine 建成 paused job，`next_run_at` 留空；`completed`/`error` 的 job 导出成 `paused` 并在 stderr 说明（不是 running 也不是 deleted）。

## 5. 丢失或降级清单

1. **id 不能当平台注册表用**：Hermes 没有按外部 id 索引的 agent；配对靠目标 home 里的 `dossier/import-meta.json`（`source`+`id`）。这是「一份档案一个 home」这一前提的由来，也是多档案共用一个 home 时只能算 L1 的原因。
2. **title 与 group 存不下**：只在归档副本与元数据里，不参与显示、匹配或同步。
3. **anti_jobs 降级**：`SOUL.md` 里的文本小节，内容逐条原样，但没有结构化字段，导出时靠小节标题还原。
4. **memory.kind / learned 降级**：枚举与日期变成条目开头的 `[kind · learned]` 文本标签；`fact` 原文保留，但**条目内的换行会被换成空格**（Hermes 记忆一条一行）。真实 Hatch 的 8 条事实都没有内部换行，所以这一份没有实际变形。无可辨认标签的记忆条目导出时按 `history` 处理，这一条会写进档案的 `excluded`，不静默。
5. **记忆有字数预算**：目标 home 的 `memory.memory_char_limit`（默认 2200 字符）是 Hermes 注入上限。Hatch 8 条 631 字符，富余；超预算时适配器**不截断**，只把实际字数与上限写进导入计划与 loss 清单（Hermes 此后会拒绝继续加条目）。
6. **routines.id 必变**：Hermes 的 job id 是平台分配的 12 位 hex；同一 home 内重复导入保持稳定，但换 home 或换平台就不再指向同一个任务。
7. **routines.schedule 的时区不跟任务走**：Hermes 按 profile 时区（`HERMES_TIMEZONE` → `config.yaml` 的 `timezone` → 服务器本地时区）求值，没有单任务时区。源档案里的 `(Asia/Tokyo)` 作为 `display` 文本保留，但不改变求值区；目标 home 时区不同时需人工改表达式（适配器不做这个换算）。
8. **6 字段 cron 表达式只取前五个字段**，第 6 个字段（秒或年，各家不同）丢弃并在 loss 里标明。
9. **事件触发的 routine 建不成 cron**：Hermes cron 只吃 cron 表达式/间隔/一次性时间；非表达式的 schedule 只留在归档里。
10. **`state: deleted` 的 routine 不回建**；若此前由本适配器建过对应 job，会把它移除并在输出里说明。
11. **refs 的 id 不解析**：只在归档里留名字，换平台后要人工重新对应（同名不同人时尤其要核对）。
12. **skills 只剩名字**：不会凭空造 skill；目标 home 里没有同名 `SKILL.md` 就等于没有，缺失清单在 dry-run 里直接列出。
13. **status / exported_at / source / fingerprint 不被平台消费**：只活在元数据与归档里（fingerprint 例外，每次导入/导出都重算比对）。
14. **`SOUL.md` 是单身份槽**：一个 home 只能装一份档案的 role；多档案请各开一个 home（`profiles/`）。
15. **角色过长会被系统提示截断**：Hermes 的上下文文件有约 20,000 字符的注入上限（`agent/prompt_builder.py:CONTEXT_FILE_MAX_CHARS`），超长时进提示的是头尾摘录，磁盘上的 `SOUL.md` 仍是全文。本适配器不切分 role，只在此说明（未实测）。

## 6. 规范反馈

以下只写在这里，没有改 `SPEC.md`。

1. **§6.1 的 L2 没有说 id 配对的「作用域」。** Hermes 能按 `source`+`id` 原地更新，但那张对应表是适配器自己写在目标存储里的，不是平台注册表。按字面读，这既像 L2 又像 L1。建议在 6.1 补一句：L2 的「按 id 配对」是指目标平台实例内可配对，并建议适配器在报告里点明 id 映射存放在哪里；否则同一个平台会被两个认真的实现者判成两个等级。
2. **能力等级表没有「一个存储能装几个 agent」这一维。** Hermes 的 role 落在**提示槽**（`SOUL.md`）而不是 skill 文件，一个 home 只装得下一个身份。这一维直接决定了等级上限，比「能存全文」更硬。建议在表里加一行或一句。
3. **§5.2 要求扫 `role`、`fact`、`prompt`，但仓库自己的 `tools/dossier_check.py` 还扫 `anti_jobs`。** 结果是一份档案可能通过某个适配器的导入，却被仓库检查器判失败（或反过来）。建议把「必须扫的字段集」在一处钉死，再让参考实现、检查器和适配器都指向它。
4. **`routines.schedule` 是自由文本，导入方必须自己决定它是不是 cron。** 「cron 表达式或事件触发描述」两种形态混在一个字符串里，导入方只能靠正则猜；猜错就是静默建错任务。本适配器选择「解析不出就绝不建、只报降级」，但这是实现选择，不是规范规定。建议给 `schedule` 加可选的 `kind: cron|event`，或至少写明「不是 cron 表达式时不得创建任务」。
5. **`null` 的持久化责任没写清。** 目标平台（Hermes）的记忆存储永远存在，没有原生的「这次没导出」标记；适配器只能把 null 记在自己的元数据里，等下次导出再读回来。建议规范明说：导入方有义务把 routines/memory 的 null 标记持久化到目标存储，否则第 6 节的 `null` 语义在往返里必然丢失（本适配器为此专门写了 `import-meta.json`，并且实测了这条往返）。
6. **memory 条目「文字原样」与「目标平台一行一条」会打架。** 一条 fact 内若含换行，落到 Hermes 会变成一行（换行→空格），而 SPEC 只对 `prompt` 提到「完整原文」。建议说明：目标平台对条目形态有限制时，允许压平并必须在报告里声明（本适配器就声明了）。

## 7. 没测的部分，以及为什么

- **真实 ticker 触发导入的 cron**：没跑。`hermes cron tick` 会真的执行到期的 job（起一个 agent turn），超出本次范围。改为用只读手段验证：`hermes cron list` 能列出、`hermes cron doctor` 报无问题、Hermes 自己的 `load_jobs()`+`compute_next_run()` 算出 `2026-11-02T09:00:00+09:00`。
- **完整 `hermes chat` 会话**：没跑（要发一次模型请求，且与本任务无关）。记忆注入改用 `hermes prompt-size` 的块大小变化验证（585 B → 0 B），身份槽用「`SOUL.md` 追加 3,000 字 → `stable` 档 +2,581 B」验证。
- **`SOUL.md` 超 20k 字符被截断**：读代码得出（`agent/prompt_builder.py:CONTEXT_FILE_MAX_CHARS = 20_000`），没有真造一份超长档案去打它。
- **真实 Notion 页面**：没碰。Notion 形式用构造文本验证（转义还原、双块拒绝），未连接用户的 Notion。
- **`tools/render_notion.py` 生成方向**：没测，本适配器只做文件形式导出。
- **写入真实的 `~/.hermes`**：按约定不做。真实 home 只读参考过布局（`SOUL.md`、`memories/`、`skills/`、`cron/`、`config.yaml` 的键名、`hermes-agent` 源码里的存储格式），全部写入都发生在 `~/hermes-adapter-run/scratch-home` 与 `~/hermes-adapter-run/probe3`。
- **Windows 路径与多 profile 并发**：没测，只在 macOS + 单 profile 上跑过。
- **Hatch 的 routines 是 `[]`**：真档案因此没有走 cron 路径；cron 路径是用 `examples/scribe.dossier.md` 和一份合成的边缘档案（事件触发 + 6 字段 cron + paused）测的。
