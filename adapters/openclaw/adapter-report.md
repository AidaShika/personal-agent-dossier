# OpenClaw 适配器报告（personal-agent-dossier/1.0）

## 1. 平台与声明等级

- 平台：**OpenClaw**（本机实测 2026.6.35，`openclaw --version` = `2026.6.35 (c283867)`）。一个 home（默认 `~/.openclaw`）里可以有多个 agent：`openclaw.json` 的 `agents.list` 是名册（每项含 `id`、`workspace`、`identity`、`default`），缺省 agent 的 id 是 `main`；每个 agent 有自己的 workspace（`SOUL.md`/`AGENTS.md`/`IDENTITY.md`/`MEMORY.md`/`skills/`）。定时任务全 home 共用一份 SQLite 状态库，靠 job 的 `agent_id` 区分归属。
- 声明等级：**L2**，作用域是「一份档案 = 一个 OpenClaw agent（agentId）」。

### 定级依据（全部实测）

SPEC 6.1 的 L2 是「能按 id 配对并更新职能，能建定时任务和写记忆」。逐项：

1. **按 id 配对并更新职能**：OpenClaw 有原生 agent id 与名册，配对键就是平台的 agentId；适配器另把档案的 `source`+`id` 记在 `<home>/dossier/<agentId>/import-meta.json` 与 `SOUL.md` 首行标记里。同一份档案连导三次：AGENTS.md 的 anti_jobs 受管区块、MEMORY.md 的 memory 受管区块各仍只有一份，cron job 数量不变、id 不变（job id 是按档案 id + routine 名算出的确定性 uuid5）。目标 agent 已有别的 `source`+`id` 时拒绝导入（退出码 1，实测）。目标 agent 不在名册里也拒绝，不把档案误写进默认 agent。
2. **能建定时任务**：routines 写成 OpenClaw 自己的 cron 行。实测把导入后的 home 用 `OPENCLAW_STATE_DIR` 挂到真实网关（仅回环、临时令牌，验完即停）：`openclaw cron list --all` 列出 `每周一汇总上周待办`，调度显示 `cron 0 9 * * 1 @ Asia/Tokyo`，网关自己算出的下一次运行是 **2026-11-02 09:00 JST（周一）**。
3. **能写记忆**：memory 写进 workspace `MEMORY.md` 的受管区块——该文件正是 OpenClaw 主会话注入的长期记忆。Hatch 档案 8 条事实导入后逐条在区块内，导出后与原文逐条一致（见第 4 项）。

### 实测到的真实布局（这条推翻了基线版假设）

本机与临时 home 的实测结论：

```
<home>/openclaw.json
  agents.defaults.workspace = <workspace>
  agents.list[] = { id, workspace?, identity?, default? }
<workspace>/SOUL.md / AGENTS.md / IDENTITY.md / MEMORY.md / skills/<name>/SKILL.md
<home>/state/openclaw.sqlite
  table cron_jobs(store_key, job_id, ..., job_json, state_json, ...)
  store_key = <home>/cron/jobs.json   # 逻辑键，不是文件
<home>/cron/jobs.json                 # 旧版导入输入；网关启动时导入一次并改名 .migrated
```

- 用 `openclaw cron add` 建一条测试任务后直接 dump `cron_jobs` 行：`store_key` 是 `<home>/cron/jobs.json`，`job_json` 是标准 job 记录，扁平列由网关自己从 `job_json` 投影；`next_run_at_ms` 由网关计算。
- 关掉网关后手工向 `cron_jobs` 插入一行（`next_run_at_ms` 留空），重启网关，`openclaw cron list --all` 立刻列出该任务并算出了下一次运行——说明适配器写 SQLite 是平台真正读的路径。
- 在只有 legacy `cron/jobs.json` 的全新 home 上启动网关：任务被导入 SQLite，原文件改名为 `jobs.json.migrated`。所以适配器在 DB/表存在时写 SQLite，在 DB 不存在时写 legacy JSON 作为兜底；两条路径都由平台消费。

### 与立项假设的一处更正

仓库 Issue #3 立项时写的是「OpenClaw 没有原生 agent id、上限 L1」。实测不对：`agents.list`、`agents/main/sessions` 的目录形态、job 的 `agentId/agent_id` 都是原生概念，配对有平台 id 可依，故按 L2 声明。issue 正文未改（那是立项备忘），更正记在这里与适配器 README 里。

## 2. 指纹向量结果

- 仓库官方脚本 `tests/check_vectors.py`：**PASS 8 vectors**，退出码 0。
- 本适配器自己的实现（与 Hermes/Muse 适配器同一份 SPEC 核心代码）：用其 `check_vectors()` 对同一向量文件实测，**8 passed / 0 failed**。
- 附带核对：`hatch.dossier.md`（旧标识 `agent-dossier/0.2`）声明指纹 `56cd7b80e6db`，往返后仍为 `56cd7b80e6db`；`examples/scribe.dossier.md` 声明 `1e6ed4957379`，往返后不变。

## 3. 映射表

| 档案字段 | OpenClaw 放在哪里 | 还原程度 |
|---|---|---|
| id | `dossier/<agentId>/import-meta.json`（配对键，与 `source` 一起）；`SOUL.md` 首行标记里也有一份 | 降级（档案 id 不是平台 id；平台侧配对靠 agentId） |
| name | workspace `IDENTITY.md` 的 `- **Name:**` 行；导出时也读 `agents.list[].identity.name` 作后备 | 原样 |
| title | 归档副本 | 存不下（无 title 槽，不参与匹配或显示） |
| group | 归档副本 | 存不下（OpenClaw 没有分区/分组概念） |
| status | `dossier/<agentId>/import-meta.json` | 降级（文档性；`retired` 的档案同样会被导入） |
| exported_at / source | `dossier/<agentId>/import-meta.json` | 文档性；`source` 参与配对键 |
| fingerprint | `dossier/<agentId>/import-meta.json`，导入时重算比对 | 不一致即拒绝导入 |
| role | workspace `SOUL.md`（整文件槽，注入系统提示） | 原样（种子模板可直接替换；人工写过的 SOUL 需 `--replace-soul`，旧文件备份） |
| anti_jobs | workspace `AGENTS.md` 的受管区块（标记注释围起的「反职责」小节），区块外内容不动 | 降级（内容原样，无结构化字段） |
| routines.id | `cron_jobs.job_id`，按 `uuid5(personal-agent-dossier:openclaw:<档案id>:<routine名>)` 算出 | 降级（与源平台 id 不同，但同一档案内稳定） |
| routines.name / prompt | `cron_jobs.name` / `payload_message`，也是 `job_json.payload.message` 的原文 | 原样 |
| routines.schedule | `cron_jobs.schedule_expr` + `schedule_tz`（`job_json.schedule = {kind: "cron", expr, tz}`） | 原样（5/6 字段都保留；事件/散文描述建不成，跳过并注明） |
| routines.state | `running` → `enabled: true`；`paused` → `enabled: false`；`deleted` → 不建（此前建过的会被移除） | 降级 |
| memory.fact | workspace `MEMORY.md` 受管区块，一条一个 bullet | 原样（条目内的换行变空格） |
| memory.kind / learned | 行内标签 `[kind · learned]` | 降级（枚举与日期变文本，与 Hermes 适配器同一约定） |
| refs | 归档副本 | 存不下（id 换平台不解析，按名字人工重新对应；`agents.list` 里的其他 agent 不自动算作 refs） |
| skills | 只做 workspace `skills/` 下的同名存在性核对，不创建；导出已导入档案时以归档清单为准，原生出生的 agent 取实际安装清单 | 降级（只有名字） |
| excluded | 归档副本；导出时原样带回（字符串保持字符串），新增说明才追加成列表项 | 原样 |

导入的落点形态：一份档案 → 目标 agent 的 workspace（`SOUL.md` + `AGENTS.md` 受管区块 + `IDENTITY.md` 名字行 + `MEMORY.md` 受管区块）+ `state/openclaw.sqlite` 的 `cron_jobs` 中该 agentId 名下的行 + `dossier/<agentId>/<slug>.dossier.md`（全字段归档）+ `dossier/<agentId>/import-meta.json`。

## 4. 往返测试与验收（全部真跑）

测试对象与日志都在 `~/openclaw-adapter-run/`；所有写入只发生在 scratch home，真实 `~/.openclaw` 只读参考。

### 4.1 Hatch 真档案（`agent-dossier/0.2`，指纹 `56cd7b80e6db`）

1. **dry-run**：退出码 0；正确识别目标 workspace 里是 onboard 种子 `SOUL.md`（可替换）、4 条 anti_jobs、8 条 memory；丢失清单列全（title/group/refs 只归档、5 个技能名在目标 workspace 缺失）。
2. **apply 到 scratch home**：六处落点全写；`IDENTITY.md` 名字行变为 `Hatch`（种子里的斜体提示行被正确处理）；`routines: []`，按计划写了一份空 legacy cron 文件（因为该 home 尚无 state DB），不产生 job。
3. **导出往返**：退出码 0；指纹 **`56cd7b80e6db` 不变**。
4. **字段差异**（逐字段比较 front matter）：

   ```
   spec:   agent-dossier/0.2  ->  personal-agent-dossier/1.0
   source: grok-bot           ->  openclaw
   exported_at: 2026-10-28（两侧相同，未变）
   ```

   只有允许的 `spec`、`source` 两项不同（`exported_at` 本次取同一天，所以没体现在差异里）。
5. **仓库检查器**：`python3 tools/dossier_check.py` 对导出文件报 `OK`，退出码 0。

### 4.2 Scribe 示例（含 1 条带时区 routine，指纹 `1e6ed4957379`）

1. **初始化 scratch home 的 state DB**：启动一次网关、`cron list` 显示 `No cron jobs`，然后停网关。
2. **导入**：退出码 0；计划明确写出 `cron: SQLite .../state/openclaw.sqlite (cron_jobs)`；落库 1 条。
3. **SQLite 行核对**：`store_key=.../cron/jobs.json`、`agent_id=main`、`schedule_expr=0 9 * * 1`、`schedule_tz=Asia/Tokyo`、`enabled=1`、payload message 与档案一致。
4. **平台侧复核**：`OPENCLAW_STATE_DIR=<scratch> openclaw cron list --all --url ws://127.0.0.1:<port> --token <临时令牌>` 输出：

   ```
   3c5558dc-c60a-58a9-8f40-a44d639e5268  每周一汇总上周待办  cron 0 9 * * 1 @ Asia/Tokyo (... in 4d  -  idle  isolated  ...  main  -
   ```

   网关自己算出的 `nextRunAtMs = 1793577600000`，即 **2026-11-02 09:00 JST**。验完停网关、确认端口释放。
5. **导出往返**：退出码 0；`exported openclaw/example-scribe-0001 fingerprint 1e6ed4957379 (routines: 1, memory: 3, cron: sqlite)`。
6. **字段差异**：

   ```
   source:          example                 ->  openclaw
   routines[0].id:  example-routine-0001    ->  3c5558dc-c60a-58a9-8f40-a44d639e5268
   ```

   `schedule`（`0 9 * * 1 (Asia/Tokyo)`）、`prompt`、`state`、3 条 memory、3 条 anti_jobs、skills、title/group/status/excluded 全部一致；`exported_at` 取同一天，未变。routine id 必变是平台分配规则，见第 5 项。
7. **仓库检查器**：`dossier_check.py` 对导出文件报 `OK`，退出码 0。

### 4.3 幂等

同一份 Scribe 档案连导三次（每次 `--apply` 到同一 scratch home），每次之后：

```
cron_rows_main = 1      job_ids = 1（同一个 id）
anti_start_markers = 1  memory_start_markers = 1
memory_bullets = 3      dossier_md_files = 1
```

Hatch 第二次导入：anti=1、memory=1、bullets=8、dossier 文件=1、`cron_jobs` 中 main 的 job=0。同一 home 同 `--date` 连续导出两次，产物字节一致（sha256 `586d9995…d11d8`）。

### 4.4 拒绝路径

- **人工写的 SOUL.md**：目标 workspace 放 `This is my hand-written soul.`（无标记、无种子句）。`--apply` 退出码 **1**，报 `SOUL.md is neither the onboard seed nor written by this adapter; refusing (add --replace-soul to override; a backup is kept)`；SOUL 字节未变，没有生成 MEMORY.md/dossier/cron。加 `--replace-soul` 后退出码 **0**，旧文件保存在 `SOUL.md.pre-dossier`，内容逐字一致。
- **敏感信息**：用 `dossier_lib` 构造两份改版并重算指纹：
  - role 里放 `contact me at someone@example.com` → 退出码 **2**，`error: sensitive pattern email in role; refused`
  - memory[0].fact 里放 `password: hunter2` → 退出码 **2**，`error: sensitive pattern password-value in memory[0].fact; refused`
  两次都没有写入目标 scratch home。
- **一个 agent 两份身份**：已在 Hatch 的 agent 再导 Scribe → 退出码 **1**，`error: agent 'main' in this home already carries dossier grok-bot/…; refusing a second identity`。

### 4.5 原生出生的 agent 导出

用种子 workspace 写一个非种子 role（`Native test agent.`）和 `IDENTITY.md` Name `Native`，没有 import meta。导出退出码 0；`role` 原样、`id` 为 `openclaw-main`，`excluded` 里写明 id 是适配器铸造的。未填种子的 SOUL 不会被冒充成 role（导出会报错要求先写职能）。

### 4.6 一次真实 bug 与修复后回归

首次全量跑时发现：网关退出后，只读方式打开 `state/openclaw.sqlite` 会报 `unable to open database file`（WAL 需要恢复，`mode=ro` 无法完成），导致“停网关后立刻导入/导出”这条顺序失败。修复：`_sqlite_cron_rows()` 改用读写连接但只执行 SELECT（`PRAGMA busy_timeout=30000`），读失败不再静默退回 legacy，而是明确报错。

修复后按同一顺序回归（全新 scratch home、不手工 touch SQLite）：初始化 DB → 停网关 → 空跑 → apply → 重启网关 `cron list` → 停网关 → 立刻导出 → 检查器，**7/7 全绿**，日志里零次 `unable to open database file`。导出 stderr：

```
fingerprint unchanged vs archive: 1e6ed4957379
exported openclaw/example-scribe-0001 fingerprint 1e6ed4957379 (routines: 1, memory: 3, cron: sqlite)
```

## 5. 降级清单（汇总）

- title、group、refs 只进归档，平台无槽。refs 不从 `agents.list` 猜——同 home 的其他 agent 与本 agent 是什么关系，档案没说就不编。
- anti_jobs 是 AGENTS.md 里的一段文本小节；memory 的 kind/learned 是行内标签。两者内容不丢，结构丢。
- `SOUL.md` 是整文件槽：导入后若人工改过 SOUL，下一次导入会整体覆盖（标记能证明它出自本适配器，故不再拒绝）；AGENTS.md/MEMORY.md 只覆盖受管区块，区块外的人工内容保留。改 SOUL 前请先导出一份档案。
- routine id 必变（确定性 uuid5，同一档案内稳定）；投递方式（delivery）档案里没有这个概念，导入一律 `{"mode": "none"}`，导出不回读。
- 非 cron 形态的 schedule（`every`/`at` 是平台有但档案无对应表达；事件/散文描述是两边都难）互导时跳过并注明。OpenClaw 支持 5 字段与 6 字段 cron，适配器两种都原样保留（基线版会截成 5 字段，本版已改）。
- skills 只有名字；已导入的档案导出时按归档清单，原生出生的 agent 导出实际安装清单。装没装以 workspace 为准、该有哪些以归档为准，两个集合的差就是待补清单。
- 原生出生（从未导入过）的 OpenClaw agent 导出时：id 由适配器按 `openclaw-<agentId>` 铸造并写进 `excluded` 说明；未填的种子 SOUL 导出为错误（模板不是角色）；没有受管区块的 MEMORY.md 导出为 `memory: null`（人工散记不冒充档案事实）。
- `null` 语义：routines/memory 的 `null` 表示“这次没导出”，不是“空”。导入 `null` 时不创建/不清理对应存储，归档里记下标记；导出时原样还原成 `null`，不会退化成 `[]`。

## 6. 相对基线版的改动

基线版（`adapters/openclaw/` 已提交的那一版）可以当参考，但有几处与本机真实形态不符，本版按实测改了：

1. **cron 存储从 JSON 改为 SQLite**。基线写 `cron/jobs.json`；2026.6.35 的网关只把该文件当 legacy 导入输入，不直接读。本版在 `state/openclaw.sqlite` 的 `cron_jobs` 表存在时写行（含 `job_json` 与扁平列），不存在时写 legacy JSON 兜底。验收里 `openclaw cron list` 能直接看到导入的任务，就是这条的证据。
2. **workspace 解析按平台规则**。基线对所有 agent 都回退到 `<home>/workspace`，非默认 agent 会写错地方。本版：`agents.list[].workspace` → 默认 agent 的 `agents.defaults.workspace`（或 `<home>/workspace`）→ 非默认 agent 的 `<defaults.workspace>/<id>` → `<home>/workspace-<id>`；不认识的 agentId 拒绝导入。`~` 展开也不再是 `home.parent`。
3. **默认 agent 解析**。baseline 无条件把 `main` 加进名册；本版按 `agents.list[]` 的 `default: true` 或第一项决定默认 agent。
4. **6 字段 cron 不再截断**。基线固定截前五字段；OpenClaw 2026.6.35 支持 5/6 字段，本版原样保留。
5. **已导入档案的 skills 不再混入原生额外技能**。基线把 workspace 里所有额外 skill 追加到归档清单，Hatch 往返会多出 `personal-agent-dossier-adapter`；本版已导入档案只回归档清单，原生出生的 agent 才回实际安装清单。
6. **routines 的 `null` 与 `[]` 分开保存**。基线只要 cron 文件存在就导出 `[]`；本版用归档/import-meta 记住“这次没导出”，`null` 不会变成空列表。
7. **读 cron 失败不再静默当空**。基线读 JSON 失败会当成没有任务；本版读 SQLite 失败明确报错，不会把“读不到”伪装成“没有 job”。
8. **SOUL 备份不覆盖旧备份**。`SOUL.md.pre-dossier` 已存在时自动加序号。
9. **脱敏扫描范围扩到 anti_jobs**，与仓库 `tools/dossier_check.py` 的扫描字段对齐。
10. **导出时把 `agents.list[].identity.name` 作为 name 的后备**；`IDENTITY.md` 仍是主槽。

## 7. 规范反馈

- Issue #3 的立项前提（「无原生 agent id 故上限 L1」）与实测不符，建议后续立项的平台先用半小时实测脚手架再定级——这次的定级依据全部来自真实 `onboard` 产物、SQLite dump 与一次网关实跑，没有一条来自文档转述。
- SPEC 没有规定「平台有原生 agent id」时档案 id 的取法（Grok 用平台 UUID、OpenClaw 的 agentId 是本地短标签）。本适配器的取法：导入的档案保留源 id，原生出生的用 `openclaw-<agentId>` 铸造并声明。建议与 Muse 报告里「无原生 id 规则」合并成一条正式规则。
- `routines.schedule` 是自由文本，导入方必须自己决定它是不是 cron。本适配器选择「解析不出就绝不建、只报降级」，但这是实现选择，不是规范规定。建议给 `schedule` 加可选的 `kind: cron|event`。
- `null` 的持久化责任没写清。本适配器把 routines/memory 的 null 标记写进 `import-meta.json` 并在导出时读回；建议规范明说导入方有此义务。
- 平台存储会随版本变化（这次就撞上 JSON → SQLite）。建议适配器报告固定写清实测的平台版本与存储位置，复核的人才知道结论的边界。

## 8. 没测的部分

- 网关只短暂起过做 `cron list` 复核，没有让导入的 job 真到点执行过（需要配模型与渠道，超出适配器验收范围）。
- 多 agent 同 home 并存只测了名册解析、`--agent-id` 选目标与 job 的 agent 过滤；没有实测两个 agent 先后导入两份不同档案后互不干扰（机制上 workspace 与 `cron_jobs.agent_id` 都隔离，风险低，但未实测，明说）。
- 真实 `~/.openclaw` 从未写入；它只做过只读参考（config 键名、workspace 种子、state DB 表结构）。所有导入都在 `~/openclaw-adapter-run/scratch-*`。
- Windows 路径与多 profile 并发没测，只在 macOS + 单 home 上跑过。
- OpenClaw 版本迭代快（2026.6.x），`cron_jobs` 形态若随版本变化，本报告的实测结论只对 2026.6.35 成立。
