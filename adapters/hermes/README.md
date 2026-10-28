# personal-agent-dossier 适配器：Hermes

把 Hermes 的 agent（一个 Hermes home）导出成 personal-agent-dossier/1.0 档案，以及把档案导入一个 Hermes home（默认空跑；导入同时接受改名前的 agent-dossier/0.1、0.2）。

**声明等级：L2**（SPEC 6.1），前提是本适配器实现的那种部署形态：**一份档案 = 一个 Hermes home**。在这个形态下，6.1 节 L2 的三件事都实测成立：

- **按 id 配对并更新职能**：档案的 `source`+`id` 记在目标 home 的 `dossier/import-meta.json` 里；同一份档案再导入同一个 home，改的是原地的 `SOUL.md` 和记忆条目，不新建、不重复。实测：改 role 和一条 fact 后再导入，SOUL.md 被替换、记忆 8 条仍是 8 条（旧条目被替换而非追加），cron job id 不变。
- **能建定时任务**：routines 写成 `cron/jobs.json` 里 Hermes 自己的 job 记录形态。实测 `hermes cron list` 能列出导入的任务、`hermes cron doctor` 报「found no issues」、Hermes 自己的 `compute_next_run` 对该记录算出下一个「周一 09:00 +09:00」。
- **能写记忆**：memory 写进 `memories/MEMORY.md`（Hermes 自己的 `\n§\n` 条目格式）。实测 `hermes prompt-size`：一个导入了 3 条事实的 home，memory 块 585 B；清空 MEMORY.md 后同一命令报 0 B——记忆真的进了系统提示。

不到「全宇宙 L2」的那一半原因说明白：Hermes 没有一张按外部 id 索引的 agent 名册，`id ↔ home` 的对应关系是**适配器写在目标 home 里**的，不是平台注册表。所以若把多份档案塞进同一个 home，就只能退化成 L1（`SOUL.md` 只有一个身份槽）——导入器直接拒绝这种情况，不假装能装下。

## 文件

| 文件 | 作用 |
|---|---|
| `dossier_lib.py` | 共享库：SPEC 2.1 指纹、三种存储形式的读取、SPEC 5 脱敏扫描、校验、幂等渲染（附录 A 序列化），以及 `SOUL.md`/`MEMORY.md`/cron 三处 Hermes 布局的读写小件 |
| `import_dossier.py` | 默认只读空跑：检查 + 导入计划 + 丢失/降级清单；`--apply --target-home DIR` 才写，且只写 DIR 之内 |
| `export_dossier.py` | 从指定 Hermes home 导出档案（front matter + 正文），重算指纹并与归档值比对，报告漂移 |
| `adapter-report.md` | 适配器报告：等级依据、映射表、往返与四项验收的结果、降级清单、规范反馈、没测的部分 |

## 怎么运行

需要 Python 3 + PyYAML；装了 `croniter` 时会把 routine 的 `next_run_at` 一并算好（不装也不影响，Hermes 的 ticker 会自己补）。

```bash
# 指纹自检（必须先过）
python3 ../../tests/check_vectors.py        # 期望 PASS 8 vectors

# 空跑（不创建、不修改任何东西）
python3 import_dossier.py ../../examples/scribe.dossier.md

# 空跑 + 指定目标 home：计划里会写出每条记忆的落点、技能缺哪些、记忆字数是否超预算
python3 import_dossier.py my.dossier.md --target-home ~/hermes-agents/scribe

# 真正写进一个 home
python3 import_dossier.py my.dossier.md --apply --target-home ~/hermes-agents/scribe

# 再从那个 home 导出（幂等：同 home + 同 --date，两次字节一致）
python3 export_dossier.py --home ~/hermes-agents/scribe --out /tmp/scribe.dossier.md
```

`--target-home` 只写命令行给出的那个目录。它不会去猜 `~/.hermes`，也不会碰别的 profile；`memories/USER.md`（用户档案）从不写入。

## 字段映射（摘要，完整版见 adapter-report.md）

| 档案字段 | Hermes 放在哪里 | 还原程度 |
|---|---|---|
| role | `SOUL.md`（身份槽，进系统提示） | 原样 |
| anti_jobs | 同一 `SOUL.md` 的「## 反职责（anti_jobs）」小节，文本列表 | 降级（内容原样，结构没了） |
| memory | `memories/MEMORY.md`，一条一行，`\n§\n` 分隔 | fact 原样，kind/learned 降成行内标签 `[kind · learned]` |
| routines | `cron/jobs.json` 里的 Hermes job 记录 | 降级：id 由适配器分配，state → enabled/paused，时区只留在文本里 |
| skills | 只核对 `skills/` 里有没有同名 SKILL.md，不创建 | 降级（只有名字） |
| id / name / title / group / status / source / fingerprint | `dossier/import-meta.json` + `dossier/<slug>.dossier.md` 归档副本 | id 记作配对键；title/group 只在归档里 |
| refs | 归档副本；id 换平台不解析，按名字人工重新对应 | 降级 |
| excluded | 归档副本 | 原样（文本） |

## 已知降级

见上表与 `adapter-report.md` 第 5 项。要点：没有平台级 agent id，配对靠 home 内元数据；title、group、refs 只在归档里；anti_jobs 与 memory 的 kind/learned 都是文本级还原；routine id 必变、时区不跟单条任务走；事件触发的 routine 建不成 Hermes cron，只留在归档；`null` 在导入报告里一律写成「未导出，不等于没有」，导出时也原样保持 `null`，不会变成 `[]`。

## 序列化风格

渲染器按 SPEC 附录 A「标准序列化」实现：`role`/`prompt` 用 `|-` 块标量、列表缩进在键下、字段顺序固定、日期裸写、易误读的串加双引号。导入器不依赖附录 A，任何合法 YAML 都能读。

## 安全边界

- 导入默认空跑；`--apply` 只写 `--target-home` 指定的目录。
- 目标 home 里已有**不是本适配器写的** `SOUL.md` 时，`--apply` 直接拒绝（退出码 1，一个字节都不写）；确认要覆盖时加 `--replace-soul`，旧文件保留为 `SOUL.md.pre-dossier`。
- 同一个 home 里已有别的 `source`+`id` 的档案时拒绝导入（一个 home 一个身份）。
- 导出前、导入前都跑 SPEC 5.2 的脱敏扫描，命中就中止并报位置，绝不自动改写。
