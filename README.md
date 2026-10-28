# agent-dossier

一份平台无关的「agent 档案」格式：把一个 AI agent 的职能、反职责、定时任务、长期记忆和依赖写成一个文件，使它能在不同平台之间交接、迁移和同步。

A platform-neutral file format (YAML) describing an AI agent's role, anti-jobs, scheduled routines, long-term memory and dependencies, so the agent can be handed over, migrated or synced across platforms. The spec is currently written in Chinese; translations are welcome.

## 它解决什么

- 换平台或换人接手时，不用靠聊天记录猜这个 agent 原来做什么、不做什么。
- 导入方必须逐项报告「丢失或降级」，不会悄悄丢字段。
- 档案不含地址、电话、证件、密码等私人信息，导出和导入两端都做扫描。

## 内容

| 路径 | 说明 |
|---|---|
| `SPEC.md` | 格式规范（当前 v0.2 草案） |
| `examples/scribe.dossier.md` | 一份虚构的完整示例（含定时任务和三类记忆） |
| `tests/` | 指纹算法的标准向量和校验脚本，任何实现都应先通过 |
| `tools/render_notion.py` | 把档案生成 Notion 页面正文，人读段落由 YAML 生成，不会漂移 |
| `adapters/grok-bot/` | Grok Bot 平台的导出器和空跑导入器（只读，不会创建任何东西） |
| `skills/agent-dossier-adapter/SKILL.md` | 给 agent 用的适配器编写指南（skill 格式）：把它交给目标平台上的 agent，让它自己写本平台的适配器 |
| `docs/conformance-test.md` | 让新平台验证自己能否读懂并还原档案的测试任务 |

## 快速开始

```bash
python3 tests/check_vectors.py                 # 先确认指纹实现正确
python3 -m venv .venv && .venv/bin/pip install pyyaml
.venv/bin/python adapters/grok-bot/import_dossier.py examples/scribe.dossier.md   # 空跑导入，打印计划和丢失清单
.venv/bin/python tools/render_notion.py examples/scribe.dossier.md > page.md      # 生成 Notion 页面正文
```

## 存储方式

同一份内容可以存成文件（`<slug>.dossier.md`，头部是 YAML front matter），也可以存进 Notion 页面（一个 `yaml` 代码块）。导入方两种都要能读，以 YAML 为准。

## 状态

v0.2 草案。已在两个平台上用文件和 Notion 两条路线各做过一次导入测试，测试发现的问题已并入规范。欢迎提 issue，尤其是新平台的适配和规范里「尚未定的问题」。

## 许可

MIT，见 `LICENSE`。
