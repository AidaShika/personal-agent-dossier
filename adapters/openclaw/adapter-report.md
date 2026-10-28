# OpenClaw 适配器报告（personal-agent-dossier/1.0）

## 1. 平台与声明等级

- 平台：**OpenClaw**（2026.6.35 实测）。一个 home（默认 `~/.openclaw`）里可以有多个 agent：`openclaw.json` 的 `agents.list` 是名册（每项含 `id`、`workspace`、`identity`），缺省 agent 的 id 是 `main`、workspace 取 `agents.defaults.workspace`。每个 agent 有自己的 workspace（`SOUL.md`/`AGENTS.md`/`IDENTITY.md`/`MEMORY.md`/`skills/`），定时任务全 home 共用一份 `cron/jobs.json`（`{"version": 1, "jobs": [...]}`），靠 job 的 `agentId` 区分归属。
- 声明等级：**L2**，作用域是「一份档案 = 一个 OpenClaw agent（agentId）」。

### 定级依据（全部实测）

SPEC 6.1 的 L2 是「能按 id 配对并更新职能，能建定时任务和写记忆」。逐项：

1. **按 id 配对并更新职能**：OpenClaw 有原生 agent id 与名册，配对键就是平台的 agentId；适配器另把档案的 `source`+`id` 记在 `<home>/dossier/<agentId>/import-meta.json` 与 `SOUL.md` 首行标记里。同一份档案连导两次：AGENTS.md 的 anti_jobs 受管区块、MEMORY.md 的 memory 受管区块各仍只有一份，cron job 数量不变、id 不变（job id 是按档案 id + routine 名算出的确定性 uuid5）。目标 agent 已有别的 `source`+`id` 时拒绝导入（退出码 1，实测）。
2. **能建定时任务**：routines 写成 `cron/jobs.json` 里 OpenClaw 文档形态的 job 记录（`schedule = {kind: "cron", expr, tz}`、`payload = {kind: "agentTurn", message}`、`sessionTarget: "isolated"`；网关自管的 `state` 不写）。实测把导入后的 home 副本用 `OPENCLAW_STATE_DIR` 挂到真实网关（2026.6.35，仅回环、临时令牌，验完即停并删除）：`openclaw cron list` 列出 `Morning brief`，调度显示 `cron 0 9 * * 1 @ Asia/Tokyo`，网关自己算出的下一次运行是 **2026-11-02 09:00 JST（周一）**，与表达式一致；`cron list --all` 里暂停的例行任务显示为 `disabled`（`enabled: false` 被平台 honoured）。
3. **能写记忆**：memory 写进 workspace `MEMORY.md` 的受管区块——该文件正是 OpenClaw 主会话注入的长期记忆。Hatch 档案 8 条事实导入后逐条在区块内，导出后与原文逐条一致（见第 4 项）。

### 与立项假设的一处更正

仓库 Issue #3 立项时写的是「OpenClaw 没有原生 agent id、上限 L1」。实测不对：`agents.list`、`agents/main/sessions` 的目录形态、job 的 `agentId` 都是原生概念，配对有平台 id 可依，故按 L2 声明。issue 正文未改（那是立项备忘），更正记在这里与适配器 README 里。

### 布局依据的来源

- 本机实跑 `openclaw onboard --non-interactive --accept-risk --auth-choice skip`（OpenClaw 2026.6.35）生成的真实脚手架：`openclaw.json` 的形态、workspace 种子文件（`SOUL.md`/`AGENTS.md`/`IDENTITY.md`/`HEARTBEAT.md`/`TOOLS.md`/`USER.md`/`BOOTSTRAP.md`）与 `agents/main/sessions`。适配器测试用的 fixture 是这份脚手架的副本（配置里的网关令牌未带出，fixture 配置为同形态重写）。
- `cron/jobs.json` 的记录形态来自公开文档与多个真实配置示例交叉核对，并最终由上面第 2 条的网关实测确认。

## 2. 指纹向量结果

- 仓库官方脚本 `tests/check_vectors.py`：**PASS 8 vectors**
- 本适配器自己的实现（与 Hermes/Muse 适配器同一份 SPEC 核心代码）：用其 `check_vectors()` 对同一向量文件实测，同为 **PASS 8 vectors**
- 附带核对：`hatch.dossier.md`（旧标识 `agent-dossier/0.2`）声明指纹 `56cd7b80e6db`，经本适配器往返后仍为 `56cd7b80e6db`；`examples/scribe.dossier.md` 声明 `1e6ed4957379`，往返后不变。

## 3. 映射表

| 档案字段 | OpenClaw 放在哪里 | 还原程度 |
|---|---|---|
| id | `dossier/<agentId>/import-meta.json`（配对键，与 `source` 一起）；`SOUL.md` 首行标记里也有一份 | 降级（档案 id 不是平台 id；平台侧配对靠 agentId） |
| name | workspace `IDENTITY.md` 的 `- **Name:**` 行 | 原样 |
| title | 归档副本 | 存不下（无 title 槽，不参与匹配或显示） |
| group | 归档副本 | 存不下（OpenClaw 没有分区/分组概念） |
| status | `dossier/<agentId>/import-meta.json` | 降级（文档性；`retired` 的档案同样会被导入） |
| exported_at / source | `dossier/<agentId>/import-meta.json` | 文档性；`source` 参与配对键 |
| fingerprint | `dossier/<agentId>/import-meta.json`，导入时重算比对 | 不一致即拒绝导入 |
| role | workspace `SOUL.md`（整文件槽，注入系统提示） | 原样（种子模板可直接替换；人工写过的 SOUL 需 `--replace-soul`） |
| anti_jobs | workspace `AGENTS.md` 的受管区块（标记注释围起的「反职责」小节），区块外内容不动 | 降级（内容原样，无结构化字段） |
| routines.id | `cron/jobs.json` 中按 `uuid5(personal-agent-dossier:openclaw:<档案id>:<routine名>)` 算出的确定性 id | 降级（与源平台 id 不同，但同一档案内稳定） |
| routines.name / prompt | job 记录的 `name` / `payload.message`，原文 | 原样 |
| routines.schedule | `schedule = {kind: "cron", expr, tz}`，`tz` 是原生字段 | 原样（5 字段）；6 字段截前五并注明；事件/散文描述建不成，跳过并注明 |
| routines.state | `running` → `enabled: true`；`paused` → `enabled: false`；`deleted` → 不建（此前建过的会被移除） | 降级 |
| memory.fact | workspace `MEMORY.md` 受管区块，一条一个 bullet | 原样（条目内的换行变空格） |
| memory.kind / learned | 行内标签 `[kind · learned]` | 降级（枚举与日期变文本，与 Hermes 适配器同一约定） |
| refs | 归档副本 | 存不下（id 换平台不解析，按名字人工重新对应；`agents.list` 里的其他 agent 不自动算作 refs） |
| skills | 只做 workspace `skills/` 下的同名存在性核对，不创建；导出时取「原生存在 ∪ 归档清单」（归档顺序优先） | 降级（只有名字） |
| excluded | 归档副本；导出时原样带回（字符串保持字符串），新增说明才追加成列表项 | 原样 |

导入的落点形态：一份档案 → 目标 agent 的 workspace（`SOUL.md` + `AGENTS.md` 受管区块 + `IDENTITY.md` 名字行 + `MEMORY.md` 受管区块）+ `cron/jobs.json` 里该 agentId 名下的 job + `dossier/<agentId>/<slug>.dossier.md`（全字段归档）+ `dossier/<agentId>/import-meta.json`。

## 4. 往返测试与验收（全部真跑）

对象一：`hatch.dossier.md`（真档案，`spec: agent-dossier/0.2`，指纹 `56cd7b80e6db`，routines 为空、memory 8 条、anti_jobs 4 条、skills 5 个）。

1. **dry-run**：退出码 0；计划正确识别目标 workspace 里是 onboard 种子 `SOUL.md`（可替换），丢失清单列全（title/group/refs 只归档、5 个技能名在目标 workspace 缺失）。
2. **apply 到脚手架副本**：六处落点全写；`IDENTITY.md` 名字行变为 `Hatch`（种子里的斜体提示行被正确处理）；`cron/jobs.json` 生成 `{"version": 1, "jobs": []}`。
3. **导出往返**：指纹 `56cd7b80e6db` 不变；字段差异只有 `spec`（0.2 → 1.0）、`source`（grok-bot → openclaw）、`exported_at`——与 Hermes 往返的差异集合相同。仓库 `tools/dossier_check.py` 对导出文件报 OK。
4. **幂等**：同一档案第二次 `--apply`，受管区块各仍一份，job 数不变。

对象二：自造的例行任务档案（3 条 routines：周一 09:00 带时区、暂停中、事件触发）。

5. **routines 落点**：cron 两条建成（事件触发那条在计划与丢失清单里明示跳过）；`tz` 进 `schedule.tz`；暂停 → `enabled: false`；记录里无 `state` 键（网关自管）。导出后两条 schedule/state/prompt 与原文一致，指纹不变。
6. **平台复核**：见第 1 节第 2 条（真实网关列出任务、算出下一次周一 09:00、disabled 状态正确）。
7. **拒绝路径**：workspace 里放人工写的 `SOUL.md` 后 `--apply` 退出码 1 且一字未写；加 `--replace-soul` 后旧文件存为 `SOUL.md.pre-dossier` 再写入。对已导入 Routina 的 agent 再导 Hatch（不同 `source`+`id`）退出码 1。role 里塞邮箱地址的档案在校验阶段被 SPEC 5.2 扫描拦下，退出码 2 并报位置。

对象三：`examples/scribe.dossier.md`（仓库示例）：往返指纹 `1e6ed4957379` 不变，字段差异只有 `source`、`exported_at` 与 routines 的 id（`example-routine-0001` → 确定性 uuid5，其余字段逐字一致）。CI 里有对应的 dry-run + 往返冒烟两步。

## 5. 降级清单（汇总）

- title、group、refs 只进归档，平台无槽。refs 不从 `agents.list` 猜——同 home 的其他 agent 与本 agent 是什么关系，档案没说就不编。
- anti_jobs 是 AGENTS.md 里的一段文本小节；memory 的 kind/learned 是行内标签。两者内容不丢，结构丢。
- `SOUL.md` 是整文件槽：导入后若人工改过 SOUL，下一次导入会整体覆盖（标记能证明它出自本适配器，故不再拒绝）；AGENTS.md/MEMORY.md 只覆盖受管区块，区块外的人工内容保留。改 SOUL 前请先导出一份档案。
- routine id 必变（确定性 uuid5，同一档案内稳定）；投递方式（delivery）档案里没有这个概念，导入一律 `{"mode": "none"}`，导出不回读。
- 非 cron 形态的 schedule（`every`/`at` 是平台有但档案无对应表达，事件/散文描述是两边都难）互导时跳过并注明。
- skills 只有名字；导出时是「原生存在 ∪ 归档清单」，装没装以 workspace 为准、该有哪些以归档为准，两个集合的差就是待补清单。
- 原生出生（从未导入过）的 OpenClaw agent 导出时：id 由适配器按 `openclaw-<agentId>` 铸造并写进 `excluded` 说明；未填的种子 SOUL 导出为 `role: null`（模板不是角色）；没有受管区块的 MEMORY.md 导出为 `memory: null`（人工散记不冒充档案事实）。

## 6. 规范反馈

- Issue #3 的立项前提（「无原生 agent id 故上限 L1」）与实测不符，建议后续立项的平台先用半小时实测脚手架再定级——这次的定级依据全部来自真实 `onboard` 产物与一次网关实跑，没有一条来自文档转述。
- SPEC 没有规定「平台有原生 agent id」时档案 id 的取法（Grok 用平台 UUID、OpenClaw 的 agentId 是本地短标签）。本适配器的取法：导入的档案保留源 id，原生出生的用 `openclaw-<agentId>` 铸造并声明。此条与 Muse 适配器报告里「无原生 id 规则」一条同根，建议在 SPEC 里合并成一条正式规则。
- `excluded` 在语料里字符串与列表两种形态都有，规范未定型。本适配器导出时保持归档的原始形态（字符串不拆），仅在有新增说明时才转成列表；建议 SPEC 明确 `excluded` 的类型，或校验器对两形态都正式接受（目前校验器不查此字段）。

## 7. 没测的部分

- 网关只短暂起过一次做 `cron list` 复核，没有让导入的 job 真到点执行过（需要配模型与渠道，超出适配器验收范围）。
- 多 agent 同 home 并存只测了名册解析与 `--agent-id` 选目标，没有实测两个 agent 先后导入两份不同档案后互不干扰（机制上 workspace 与 job 的 agentId 都隔离，风险低，但未实测，明说）。
- OpenClaw 版本迭代快（2026.6.x），`cron/jobs.json` 形态若随版本变化，本报告的实测结论只对 2026.6.35 成立。
