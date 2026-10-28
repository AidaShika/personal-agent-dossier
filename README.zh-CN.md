# personal-agent-dossier

[![CI](https://github.com/AidaShika/personal-agent-dossier/actions/workflows/ci.yml/badge.svg)](https://github.com/AidaShika/personal-agent-dossier/actions/workflows/ci.yml)

[English](README.md) | **简体中文** | [日本語](README.ja.md) | [한국어](README.ko.md)

> 换平台时，把一个个人 AI agent 的「工作」完整地带走。

## 要解决的问题

AI agent 平台一个接一个地出，大家也经常换平台。试新平台很容易，难的是把 agent 搬过去。

一个用了几个月的个人 agent，早就不只是一段提示词了：它有明确的职能和反职责（明确不做的事）、定时任务、长期记忆、对其他 agent 的依赖，还有它要用的 skill。这些东西通常都锁在旧平台里。靠手工复制，总会悄悄丢东西：定时任务留下了时间、丢了完整 prompt；记忆变成没有分类的一整坨；而且没人说得清到底丢了什么，直到 agent 行为出问题才发现。

**personal-agent-dossier** 把这次交接打包成一个文件：机器能校验的 YAML front matter，加人能读的 Markdown 正文；同一份内容也能存进 Notion 页面。这个仓库本身还是一个 skill：agent 克隆下来，读 `SKILL.md` 按路线走，就能完成导出或导入。

## 一份档案里有什么

| 部分 | 内容 |
|---|---|
| 职能 | 职责全文（原样保留）和反职责 |
| 定时任务 | 任务名、计划（写明时区）、完整 prompt、状态 |
| 长期记忆 | 一条条事实，每条带类型：`rule`（规则）/ `preference`（偏好）/ `decision`（决定）/ `history`（已做的事） |
| 依赖 | 会交接或依赖的其他 agent（`refs`），以及依赖的 skill 名称 |
| 指纹 | 对 name + title + role 算出的 12 位 SHA-1，两个平台不用逐句比对就能发现漂移 |
| 出处 | 导出平台、导出日期，以及说明「有意没带什么」的 `excluded` |

格式里有两条硬规矩：`null` 是「这次没导出」，`[]` 是「确实没有」，不许混；导入方不许静默丢字段，接不住的东西必须逐项写进导入报告的「丢失或降级」清单。

## 和相邻概念的区别

| | 它做什么 | 它不做什么 |
|---|---|---|
| A2A / Agent Card | agent 之间的运行时发现与通信 | 不负责把个人 agent 的职能和记忆归档迁移 |
| `AGENTS.md` / `CLAUDE.md` | 给编程 agent 的项目级说明 | 没有按 agent 的交接语义：定时任务、记忆分类、指纹、丢失清单 |
| 整机状态导出 | 把整个安装连配置带凭据一起搬走 | 本格式只做最小、无秘密的交接文件，且导出导入两端都要先扫描 |
| 聊天记录导出 | 保存对话流水 | 不能从流水里重建出结构化的职能、任务和记忆 |

## 安全是设计的一部分

- 地址、电话、生日、证件号、密码、令牌、API key 永远不进档案。
- 导出前对 role、记忆和 prompt 跑敏感信息扫描，导入时再扫一遍、命中拒绝。批量导出时命中的档案跳过、其余继续，但整轮以非零退出码结束，不许静默成功。
- 导入方要声明能力等级（L0：只能文字还原；L1：保存全文并自验指纹；L2：按 id 同步），搬之前就知道什么能留下。

## 快速开始

```bash
pip install -r requirements.txt
python3 tests/check_vectors.py                       # 先验证指纹算法
python3 tools/dossier_check.py examples/scribe.dossier.md   # 校验任意一份档案
python3 adapters/grok-bot/import_dossier.py examples/scribe.dossier.md   # 空跑导入：看计划和丢失清单
python3 tools/render_notion.py examples/scribe.dossier.md > page.md      # 生成 Notion 页面形式
```

## 内容

| 路径 | 说明 |
|---|---|
| `SKILL.md` | 本仓库作为 skill 的入口：导出、导入、漂移检查、Notion 存储、写适配器的路线表 |
| `SPEC.md` / `SPEC.en.md` | 格式规范 v1.0（中文原版与英文译版） |
| `examples/scribe.dossier.md` | 虚构的完整示例（含定时任务和全部记忆类型） |
| `tests/` | 指纹算法的标准向量和校验脚本，任何实现都应先通过 |
| `tools/dossier_check.py` | 独立校验工具：字段、指纹、敏感信息扫描，不需要任何平台适配器 |
| `tools/render_notion.py` | 把档案渲染成 Notion 页面正文，人读段落由 YAML 生成，不会漂移 |
| `adapters/` | 各平台的导出器和空跑导入器 |
| `skills/personal-agent-dossier-adapter/SKILL.md` | 适配器编写指南：把它交给新平台上的 agent，它自己写本平台的适配器 |
| `docs/conformance-test.md` | 导入方一致性测试：证明自己真读懂了这个格式 |

## 已实现的适配器

| 平台 | 等级 | 内容 | 说明 |
|---|---|---|---|
| Grok Bot | L2 | 批量导出器、空跑导入器 | 格式的发源地平台，按 agent id 同步 |
| Muse | L1 | 导出器、空跑导入器、自导出示例 | 报告：[`adapters/muse/adapter-report.md`](adapters/muse/adapter-report.md) |
| Hermes | L2（作用域：一份档案 = 一个 Hermes home） | 导出器、导入器（空跑 + 落地） | 由 Hermes Agent 本人按适配器指南写成；已用一份真实 Grok Bot 档案全程验证（往返指纹不变）。报告：[`adapters/hermes/adapter-report.md`](adapters/hermes/adapter-report.md) |

给新平台写适配器是预期的参与方式：按 `skills/personal-agent-dossier-adapter/` 的指南做，过指纹向量、跑一致性测试，然后提 PR 把你的平台加进这张表，并附上适配器报告。

## 真实案例：从 Grok Bot 到 Muse

这个格式不是凭空设计的。它来自 Grok Bot 平台上一个 30 多个个人 bot 的在用名册，第一次跨平台交接就是一次真实迁移：

1. 一个 bot 的档案从 Grok Bot 侧导出，由 Muse 导入，先是文件形式，后来又从 Notion 页面导入一次。
2. Muse 声明 L1，用标准向量验证指纹实现，对示例档案和一份真实 0.1 档案做了往返测试，并逐项列出自己平台接不住、会降级的字段。
3. 测试发现的问题回写进规范成为澄清：指纹覆盖什么、不覆盖什么，`refs` 的判定，复合型平台的粒度，没有原生 id 的平台怎么办。
4. Muse 适配器随后把自己导出成一份示例档案（`adapters/muse/examples/kubo.dossier.md`）。

## 状态与路线图

v1.0。项目在 v1.0 时由 agent-dossier 改名为 personal-agent-dossier；导入方继续接受旧标识 `agent-dossier/0.1`、`agent-dossier/0.2`，指纹不受影响。

尚未定的问题（欢迎讨论）：把 role 里的 bot 名单拆成独立字段、记忆分层与过期、多个 agent 之间的交接关系、附件和工具权限的表达方式。

## 许可

MIT，见 `LICENSE`。
