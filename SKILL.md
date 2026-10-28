---
name: personal-agent-dossier
description: 当你要把一个 AI agent 的职能、反职责、定时任务和长期记忆导出成平台无关的档案、从档案导入或还原一个 agent、检查两份档案是否漂移，或为你的平台写导出导入适配器时使用。用户也常这样说：把这个助手的活和记忆打包带走、我要换平台了、这个 bot 不用了把它的工作交接出去、两份档案对一下看哪儿对不上；pack up this agent and move it to another platform、I'm switching agents, take its memory with it；このボットの引き継ぎをして、別のプラットフォームに引っ越したい、記憶ごと持っていって；이 봇 더 안 쓰니까 인수인계해줘、플랫폼 옮길 거야 기억까지 챙겨서 내보내줘。不用于：导出聊天记录、agent 之间的实时通信协议（如 A2A）类问题。
---
# personal-agent-dossier

personal-agent-dossier 是一份平台无关的「个人 agent 档案」格式（YAML front matter 加 Markdown 正文，也可以存进 Notion 页面）。用它在不同平台之间交接、迁移和同步 agent。你拿到这个仓库，先读本文件，再按下面的表选路线。

## 用户会怎么说

用户很少说「导出档案」这种书面话。听到下面这类说法，就按标注选路线（具体做法见下一节的表）：

- 「把这个助手的活和记忆打包带走」「我要换平台了」→ 导出
- 「这个 bot 不用了，把它的工作交接出去」「把这份档案导进来」→ 导入（先空跑，等用户确认才真正写入）
- 「两份档案对一下，看哪儿对不上」「这个档案是不是被人改过」→ 校验与漂移检查
- 「给新平台写个适配器，让它也能读这种档案」→ 写适配器

其他语言同理：pack up this agent and move it to another platform、hand this bot's job over to another agent（英文）；このボット、もう使わないから仕事を引き継がせて、別のプラットフォームに引っ越したい、記憶ごと持っていって（日文）；이 봇 더 안 쓰니까 다른 데로 인수인계해줘、플랫폼 옮길 거야, 기억까지 챙겨서 내보내줘（韩文）。

反过来，「把聊天记录导出来」「让两个 agent 互相通信」这类说法不是这个格式的活，不要走进来。

## 先判断你要做哪件事

| 你要做的事 | 怎么做 |
|---|---|
| 导出：把我自己（或我能读到的 agent）写成档案 | 读 `SPEC.md` 第 2、5 节，参考 `adapters/grok-bot/export_dossiers.py` 的结构；没有现成适配器就走下面「为我的平台写适配器」 |
| 导入：从档案还原一个 agent | 先用空跑导入器看计划和丢失清单（`adapters/grok-bot/import_dossier.py`，只读）；真正写入前必须得到用户确认 |
| 检查：两份档案或档案与现状是否漂移 | 按 `SPEC.md` 2.1 节算 `fingerprint`，不同就逐句对比 `role`；相同也要另行逐项比对 `anti_jobs` 与 `routines`（指纹不覆盖它们） |
| Notion 存储 | 用 `tools/render_notion.py` 由 YAML 生成页面正文，页面里只放一个 yaml 代码块，以 YAML 为准 |
| 为我的平台写适配器 | 读 `skills/personal-agent-dossier-adapter/SKILL.md`，按它的七步做并写 `adapter-report.md` |
| 验收一个导入方 | 按 `docs/conformance-test.md` 做一遍 |

## 仓库里有什么

| 路径 | 用途 |
|---|---|
| `SPEC.md` | 格式规范（字段、指纹算法、脱敏规则、同步语义、平台等级） |
| `tests/` | 指纹标准向量和校验脚本，任何实现都要先跑 `python3 tests/check_vectors.py` |
| `examples/scribe.dossier.md` | 虚构示例，用来做往返测试 |
| `tools/render_notion.py` | 档案转 Notion 页面正文 |
| `adapters/<平台>/` | 各平台的导出器和导入器；每个适配器自己写明等级和已知降级 |
| `skills/personal-agent-dossier-adapter/SKILL.md` | 写适配器的分步指南和报告模板 |
| `docs/conformance-test.md` | 导入方一致性测试 |

## 任何路线都必须遵守的几条

1. 以 `SPEC.md` 为准，不凭记忆写字段。规范有问题写进你的报告，不要改规范、测试向量和示例。
2. 先过指纹测试向量，再碰真实数据。
3. 只导出自己能读到的内容，别的 agent 的记忆不导出。
4. 地址、电话、证件、银行卡、账号密码、令牌不进档案、仓库、Notion 和报告。导出前扫描，命中就中止，不自动改写。
5. `null` 是「这次没导出」，`[]` 是「确实没有」，导入时不得混为一谈。
6. 导入方不得静默丢字段，必须逐项列出「丢失或降级」，并在报告开头声明自己是 L0、L1 还是 L2。
7. 没有用户确认，不写入真实的 agent、记忆或定时任务，不发送任何消息。
