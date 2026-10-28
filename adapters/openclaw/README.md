# personal-agent-dossier 适配器：OpenClaw

把 OpenClaw 的一个 agent（由 agentId 标识）导出成 personal-agent-dossier/1.0 档案，以及把档案导入一个 OpenClaw home 里的指定 agent（默认空跑；导入同时接受改名前的 agent-dossier/0.1、0.2）。

**声明等级：L2**（SPEC 6.1），作用域是「一份档案 = 一个 OpenClaw agent」。OpenClaw 有**原生 agent id 与名册**（`openclaw.json` 的 `agents.list`，cron job 自带 `agentId`），一个 home 可以并存多个 agent，每个 agent 有自己的 workspace。配对键不只是适配器自记的元数据：平台本身就按 agentId 识别 agent、按 `agentId` 归属 cron job。一个 home 装多份档案（每个 agent 一份）仍是 L2。

三件事都实测成立：

- **按 id 配对并更新职能**：配对键记在目标 home 的 `dossier/<agentId>/import-meta.json` 与 `SOUL.md` 首行标记里；同一份档案再导入同一个 agent，改的是原地的文件与 job，不新建、不重复。实测连导三次：AGENTS.md 的 anti_jobs 受管区块、MEMORY.md 的 memory 受管区块各仍只有一份，cron job 数量与 id 不变。
- **能建定时任务**：routines 写成 OpenClaw **当前真实的 SQLite cron 存储**——`<home>/state/openclaw.sqlite` 的 `cron_jobs` 表，而不是旧版的 `cron/jobs.json`。实测把导入后的 home 挂到真实网关（OpenClaw 2026.6.35）上：`openclaw cron list` 列出导入的任务并算出下一次运行（周一 09:00 Asia/Tokyo → 2026-11-02 09:00 JST）。
- **能写记忆**：memory 写进 workspace 的 `MEMORY.md` 受管区块（区块外的人工内容保留）。Hatch 档案 8 条事实往返后逐条一致，kind/learned 以行内标签形式还原。

写这份适配器时的一个更正：仓库 Issue #3 立项时以为「OpenClaw 没有原生 agent id、上限 L1」——实测不对，`agents.list` 与 job 的 `agentId` 都是原生概念，故声明 L2。依据写在 `adapter-report.md` 里。

## 文件

| 文件 | 作用 |
|---|---|
| `dossier_lib.py` | 共享库：SPEC 2.1 指纹、三种存储形式的读取、SPEC 5 脱敏扫描、校验、幂等渲染（附录 A 序列化，与 Hermes/Muse 适配器同一实现），以及 OpenClaw 布局（config/agent 解析、SOUL/AGENTS/IDENTITY/MEMORY 受管区块、SQLite `cron_jobs` 与 legacy JSON）的读写小件 |
| `import_dossier.py` | 默认只读空跑：检查 + 导入计划 + 丢失/降级清单；`--apply --target-home DIR` 才写，且只写 DIR 之内 |
| `export_dossier.py` | 从指定 home 的指定 agent 导出档案（front matter + 正文），重算指纹并与归档值比对，报告漂移 |
| `adapter-report.md` | 适配器报告：等级依据、映射表、往返与验收结果、降级清单、规范反馈、没测的部分 |

## 怎么运行

需要 Python 3 + PyYAML。

```bash
# 指纹自检（必须先过）
python3 ../../tests/check_vectors.py        # 期望 PASS 8 vectors

# 空跑（不创建、不修改任何东西）
python3 import_dossier.py ../../examples/scribe.dossier.md

# 空跑 + 指定目标 home 与 agent：计划里会写出每条 routine 的落点、技能缺哪些、cron 后端
python3 import_dossier.py my.dossier.md --target-home ~/.openclaw --agent-id main

# 真正写进一个 home 的某个 agent
python3 import_dossier.py my.dossier.md --apply --target-home ~/.openclaw --agent-id main

# 再从那个 home 导出（幂等：同 home + 同 --date，两次字节一致）
python3 export_dossier.py --home ~/.openclaw --agent-id main --out /tmp/scribe.dossier.md
```

`--target-home` 只写命令行给出的那个目录。workspace 路径以目标 home 的 `openclaw.json` 为准（`agents.list` 里该 agent 的 workspace；默认 agent 取 `agents.defaults.workspace`；非默认 agent 在未写 workspace 时按 OpenClaw 的规则落到 `workspace-<id>`）。`USER.md`（用户档案）从不写入；`AGENTS.md`/`MEMORY.md` 只动受管区块。

目标 agent 必须已经在 `openclaw.json` 里配置（默认单 agent 的 id 是 `main`）。不认识的 agentId 会拒绝导入，避免把档案误写进默认 agent 的 workspace；需要新 agent 时先用 `openclaw agents add <id>`。

## 字段映射（摘要，完整版见 adapter-report.md）

| 档案字段 | OpenClaw 放在哪里 | 还原程度 |
|---|---|---|
| role | workspace `SOUL.md`（进系统提示），首行带档案 id+source 标记 | 原样 |
| anti_jobs | workspace `AGENTS.md` 的受管区块（硬边界小节） | 内容原样，结构降为文本列表 |
| name | workspace `IDENTITY.md` 的 `- **Name:**` 行（导出时也认 `agents.list[].identity.name`） | 原样 |
| memory | workspace `MEMORY.md` 受管区块，一条一个 bullet | fact 原样，kind/learned 降成行内标签 `[kind · learned]` |
| routines | `state/openclaw.sqlite` 的 `cron_jobs` 行（旧 home 没有该表时写 legacy `cron/jobs.json`，平台下次启动会导入） | 降级：id 换成确定性 uuid5，state → enabled，时区进 `schedule.tz`（原生字段） |
| skills | 只核对 workspace `skills/` 里有没有同名 SKILL.md，不创建；导出已导入档案时以归档清单准 | 降级（只有名字） |
| id / title / group / status / source / fingerprint | `<home>/dossier/<agentId>/import-meta.json` + 归档副本 | id 是配对键；title/group 只在归档里 |
| refs | 归档副本；id 换平台不解析，按名字人工重新对应 | 降级 |
| excluded | 归档副本 | 原样（文本） |

## 已知降级

见上表与 `adapter-report.md` 第 5 项。要点：title、group、refs 只在归档里；anti_jobs 与 memory 的 kind/learned 都是文本级还原；routine id 必变（但同一档案内稳定）、事件触发的 routine 建不成 cron；`SOUL.md` 是整文件槽位，导入后人工改过 SOUL 再导入会被覆盖（AGENTS.md/MEMORY.md 的受管区块之外则保留）；导出时 `null` 一律是「未导出，不等于没有」，不会变成 `[]`。routines 的投递方式档案里没有这个概念，导入一律 `mode: none`。

## 序列化风格

渲染器按 SPEC 附录 A「标准序列化」实现，与其他适配器共用同一份代码：`role`/`prompt` 用 `|-` 块标量、列表缩进在键下、字段顺序固定、日期裸写、易误读的串加双引号。导入器不依赖附录 A，任何合法 YAML 都能读。

## 安全边界

- 导入默认空跑；`--apply` 只写 `--target-home` 指定的目录、只动目标 agent 的 workspace 与它名下的 job。
- 目标 workspace 已有**不是本适配器写的** `SOUL.md`（且不是 onboard 的未填种子）时，`--apply` 直接拒绝（退出码 1，一个字节都不写）；确认要覆盖时加 `--replace-soul`，旧文件保留为 `SOUL.md.pre-dossier`（已有同名备份时自动加序号，不覆盖旧备份）。
- 同一个 agent 已有别的 `source`+`id` 的档案时拒绝导入（一个 agent 一个身份）。
- 导出前、导入前都跑 SPEC 5.2 的脱敏扫描（范围含 role、anti_jobs、memory facts、routine prompts），命中就中止并报位置，绝不自动改写。
- 目标 agent 不在 `openclaw.json` 名册里时拒绝导入；不猜 workspace、不静默写进默认 agent。
- SQLite 只按 `store_key` 动这个 home 的 cron 行；其他 agent、其他 home 的 job 不碰。读 SQLite 时使用读写连接（只执行 SELECT），因为网关退出后 WAL 可能需要恢复，只读连接会打不开。
