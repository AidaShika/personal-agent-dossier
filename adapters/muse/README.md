# agent-dossier 适配器：Muse

把 Muse 平台的 agent 导出成 agent-dossier/0.2 档案，以及把档案导入 Muse（先空跑）。

**声明等级：L1**（SPEC 6.1）。Muse 能保存档案全文、能自己校验指纹、能按 kind 给记忆打标签——6.1 节给 L1 的例子正是「自定义 skill + 文件的组合」。不是 L2 的原因：Muse 没有「按 dossier 的 `id` 配对并更新」的 agent 实体——它只有一个主 agent，职能靠自定义 skill（SKILL.md）和侧聊承载，没有可按外部 id 更新名字/描述的 agent 名册。定时任务和记忆在 Muse 上都存在（cron 表达式 + 时区、Markdown 记忆文件），但新建时 id 由平台分配，且真正写入前必须经用户确认，所以导入器只做空跑和暂存。

## 文件

| 文件 | 作用 |
|---|---|
| `dossier_lib.py` | 共享库：SPEC 2.1 指纹、三种存储形式的读取、SPEC 5 脱敏扫描、校验、幂等渲染 |
| `import_dossier.py` | 只读空跑导入器：检查 + 导入计划 + 丢失/降级清单；`--stage DIR` 时只在 DIR 内写暂存件 |
| `export_muse.py` | 导出器：`--snapshot` 从 agent 自备的快照 JSON 渲染档案；`--from-staging` 从暂存目录重建档案（往返测试用） |
| `examples/kubo-snapshot.json`、`examples/kubo.dossier.md` | 本适配器对 Kubo（Muse 主 agent）的一次真实自导出演示：routines/memory 有意写 `null`，原因写在档案的 `excluded` 里 |

## 怎么运行

需要 Python 3 + PyYAML。

```bash
# 指纹自检（必须先过；仓库根目录运行官方脚本同理）
python3 ../../tests/check_vectors.py        # 期望输出 PASS 8 vectors

# 空跑导入（不创建、不修改任何真实东西）
python3 import_dossier.py ../../examples/scribe.dossier.md

# 空跑 + 暂存（暂存只写进指定目录）
python3 import_dossier.py ../../examples/scribe.dossier.md --stage /tmp/stage-scribe

# 往返：从暂存重建档案
python3 export_muse.py --from-staging /tmp/stage-scribe --out /tmp/scribe.roundtrip.md

# 自导出：先由 agent 把能读到的自身信息汇成 snapshot JSON，再渲染
python3 export_muse.py --snapshot examples/kubo-snapshot.json --out examples/kubo.dossier.md
```

两个脚本在脱敏扫描命中时都会中止并报告位置，绝不自动改写（SPEC 5.2）。

## 字段映射（摘要，完整版见 adapter-report.md）

| 档案字段 | Muse 放在哪里 | 还原程度 |
|---|---|---|
| name | 自定义 skill 的目录名（slug 化）+ SKILL.md 内原样保留 | 原样（值） |
| title | 并入 skill 的 description 文本，档案副本里原样保留 | 降级 |
| role | SKILL.md 正文「职能（role）」一节 | 原样 |
| anti_jobs | 同一 SKILL.md 的「反职责（anti_jobs）」一节，文本列表 | 降级（无独立字段） |
| routines | Muse cron 可表达（表达式 + 时区）；导入只出计划，确认后才建，id 由平台新分配 | 降级 |
| memory | 暂存为测试文件，一条一行，fact 原样，kind/learned 退化为行内标签 `[kind · learned]` | fact 原样，kind/learned 降级 |
| skills | 只记名称；本平台有同名 SKILL.md 才算存在 | 降级 |
| refs | 按名字在 Muse 的人物/角色记录里重新对应，源 id 只留作注记 | 降级 |
| group | 无对应概念（skill 与侧聊都没有分组），仅档案副本保留 | 存不下 |
| id / status / exported_at / source / fingerprint | 档案副本里原样保留的文档性字段，平台不消费 | 降级（不能按 id 同步） |

## 已知降级

见上表与 `adapter-report.md` 第 5 项。要点：不能按 id 同步（L1 的定义边界）；kind 与 learned 从结构化字段退化为文本标签；routine id 必然变化；`null` 在导入报告里一律写作「未导出，不等于没有」，并保留原档案副本。
