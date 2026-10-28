# personal-agent-dossier

[![CI](https://github.com/AidaShika/personal-agent-dossier/actions/workflows/ci.yml/badge.svg)](https://github.com/AidaShika/personal-agent-dossier/actions/workflows/ci.yml)

[English](README.md) | **简体中文** | [日本語](README.ja.md) | [한국어](README.ko.md)

> 换平台时，把一个个人 AI agent 的「工作」完整地带走。

![冷启动测试：全新 Hermes 只靠一句话接住另一个平台的 agent](docs/images/cold-start-hermes.png)

*一个刚装好的 Hermes，没给任务书，只给了一句话，它自己就把另一个平台的 agent 搬了过来，搬完再导出，指纹和原来一模一样。完整的故事在后面的案例里。*

## 快速开始

### 把你的 agent 搬到新平台（不用命令行）

```bash
git clone https://github.com/AidaShika/personal-agent-dossier
```

把克隆下来的仓库当作 skill 交给你的 agent（或者让它读 `SKILL.md`），再用大白话跟它说一句：「把你的工作全都打包成一个文件，我要把你搬到另一个平台了。」到了新平台就说：「这个文件里是你之前的工作，接过来吧。」这个文件就是本项目说的档案（dossier）。导入时不会直接写进去，会先空跑一遍，把执行计划摆给你看：哪些东西会丢、丢在哪一处，都列清楚，你确认了才真正写入。跑对的样子是：agent 交回一份 `.dossier.md`，再报出它的指纹——一串用来认内容的短码，对不对得上，你拿它一比就知道。

### 验一验别人给你的文件（一分钟）

```bash
pip install -r requirements.txt
python3 tools/dossier_check.py 路径/任意.dossier.md
```

跑对的样子是：检查器告诉你字段齐全，它重新算出来的指纹和文件里写的一致，敏感信息也扫不出问题。手头还没有自己的文件？先拿仓库自带的 `examples/scribe.dossier.md` 跑一遍，那是个虚构的 agent，专门用来练手。

### 给你的平台搭桥

```bash
python3 tests/check_vectors.py   # 指纹算法必须在 8 条测试用例上全部对齐
```

然后照 `skills/personal-agent-dossier-adapter/` 里的适配器指南做，再跑一遍 `docs/conformance-test.md` 里的一致性测试。跑对的样子是：用例全过，你的导入器把档案导出去再导回来，指纹还是原来那个。


## 要解决的问题

AI agent 平台一个接一个地出，大家换平台也是常事。试一个新平台不难，难的是把 agent 一起搬过去。

一个 agent 用上几个月，早就不是一段提示词了。它有定死的职能，也有明确不碰的反职责；有定时任务，有长期记忆，还依赖别的 agent 和几个 skill。这些东西平时都锁在旧平台里，搬家时靠手工复制，难免悄悄丢东西：定时任务的时间抄过来了，完整的 prompt 却没跟上；记忆倒是搬了，变成没分类的一整坨；更麻烦的是，到底丢了什么谁都说不清，往往等 agent 开始行为异常，才发现是搬家时落下的。

**personal-agent-dossier** 做的事，就是把这场交接收进一个文件里：前面是机器能校验的 YAML front matter，后面是人能读的 Markdown 正文，同一份内容也可以存进 Notion 页面。这个仓库本身还是一个 skill：agent 把它克隆下来，照着 `SKILL.md` 的路线走，就能自己完成导出或导入。

## 一份档案里有什么

| 部分 | 内容 |
|---|---|
| 职能 | 职责全文（原样保留）和反职责 |
| 定时任务 | 任务名、计划（写明时区）、完整 prompt、状态 |
| 长期记忆 | 一条条事实，每条带类型：`rule`（规则）/ `preference`（偏好）/ `decision`（决定）/ `history`（已做的事） |
| 依赖 | 会交接或依赖的其他 agent（`refs`），以及依赖的 skill 名称 |
| 指纹 | 拿 name、title、role 算出的 12 位 SHA-1；两个平台不用逐句比对原文，看看指纹就能知道内容有没有变 |
| 出处 | 导出平台、导出日期，以及说明「有意没带什么」的 `excluded` |

格式里有两条硬规矩。第一，`null` 和 `[]` 不许混用：`null` 表示「这次没导出」，`[]` 表示「本来就没有」。第二，导入方不许偷偷丢字段：在新平台上接不住的东西，要一项一项写进导入报告的「丢失或降级」清单里。

## 和相邻概念的区别

| | 它做什么 | 它不做什么 |
|---|---|---|
| A2A / Agent Card | agent 之间的运行时发现与通信 | 不负责把个人 agent 的职能和记忆归档迁移 |
| `AGENTS.md` / `CLAUDE.md` | 给编程 agent 的项目级说明 | 不是按「交接一个 agent」来设计的，没有定时任务、记忆分类、指纹和丢失清单这些东西 |
| 整机状态导出 | 把整个安装连配置带凭据一起搬走 | 本格式只留交接用得上的最小一份，里面不放任何秘密，导出和导入两端还都要先过一遍扫描 |
| 聊天记录导出 | 保存对话流水 | 光有流水，重建不出成结构的职能、任务和记忆 |

## 安全是设计的一部分

- 地址、电话、生日、证件号、密码、令牌、API key 永远不进档案。
- 导出之前，先拿敏感信息扫描过一遍 role、记忆和 prompt；导入时再扫一遍，扫到了就拒绝。批量导出时，命中的那一份档案跳过、其余的照常导，但这一轮要以非零退出码收尾，不能装作无事发生。
- 导入方要先声明自己的能力等级（L0：只能还原成文字；L1：能保存全文、能自己验指纹；L2：能按 id 同步），这样动手搬之前就知道，哪些东西留得下、哪些留不下。

## 内容

| 路径 | 说明 |
|---|---|
| `SKILL.md` | 本仓库作为 skill 时的入口，里面是导出、导入、漂移检查、Notion 存储、写适配器这几条路线的走法 |
| `SPEC.md` / `SPEC.en.md` | 格式规范 v1.0（中文原版与英文译版） |
| `examples/scribe.dossier.md` | 虚构的完整示例（含定时任务和全部记忆类型） |
| `tests/` | 指纹算法的标准测试向量和校验脚本，不管哪家实现，都得先过这一关 |
| `tools/dossier_check.py` | 独立校验工具：字段、指纹、敏感信息扫描，不需要任何平台适配器 |
| `tools/render_notion.py` | 把档案渲染成 Notion 页面的正文；给人读的段落是直接从 YAML 生成的，不会和档案本身对不上 |
| `adapters/` | 各平台的导出器和空跑导入器 |
| `skills/personal-agent-dossier-adapter/SKILL.md` | 适配器编写指南：把它交给新平台上的 agent，它自己写本平台的适配器 |
| `docs/conformance-test.md` | 给导入方的一致性测试，用来证明它真把这个格式读懂了 |

## 已实现的适配器

| 平台 | 等级 | 内容 | 说明 |
|---|---|---|---|
| Grok Bot | L2 | 批量导出器、空跑导入器 | 这个格式就是在这儿诞生的，同步时按 agent id 对号入座 |
| Muse | L1 | 导出器、空跑导入器、自导出示例 | 报告：[`adapters/muse/adapter-report.md`](adapters/muse/adapter-report.md) |
| Hermes | L2（作用域：一份档案 = 一个 Hermes home） | 导出器、导入器（空跑 + 落地） | 这份适配器是 Hermes Agent 照着适配器指南自己写的；拿一份真实的 Grok Bot 档案从头到尾验过，往返一圈指纹没变。报告：[`adapters/hermes/adapter-report.md`](adapters/hermes/adapter-report.md) |
| OpenClaw | L2（作用域：一份档案 = 一个 OpenClaw agent） | 导出器、导入器（空跑 + 落地） | 这份适配器是 OpenClaw 照着适配器指南自己写的；拿一份真实的 Grok Bot 档案从头到尾验过，往返一圈指纹没变。写的过程里它还发现：现在的 cron 存在 SQLite 里，不是旧版的 JSON 文件。报告：[`adapters/openclaw/adapter-report.md`](adapters/openclaw/adapter-report.md) |

想参与进来，最对路的做法就是给你的平台写一份适配器：照 `skills/personal-agent-dossier-adapter/` 里的指南做，让指纹向量全过，再跑一遍一致性测试，然后提个 PR，把你的平台加进上面这张表，适配器报告也一并附上。

## 真实案例：从 Grok Bot 到 Muse

这个格式不是坐在桌前凭空想出来的。它最早来自 Grok Bot 平台上的一份名册，上面有 30 多个正在用的个人 bot；格式的第一次跨平台交接，搬的也是真东西：

1. 一个 bot 的档案先从 Grok Bot 那边导出，再由 Muse 导入，前后导了两次：一次走文件，一次走 Notion 页面。
2. Muse 先声明自己是 L1，再拿标准向量验自己的指纹算法对不对，又拿示例档案和一份真实的 0.1 档案做了往返测试，最后把自家平台接不住、只能降级的字段一项一项列了出来。
3. 测试里发现的问题，后来都写回规范、变成了澄清条款：指纹到底覆盖什么、又不覆盖什么，`refs` 怎么判定，复合型平台按多大的粒度算一份，碰上没有原生 id 的平台该怎么办。
4. 再往后，Muse 的适配器把自己也导成了一份示例档案，就是 `adapters/muse/examples/kubo.dossier.md`。

![一次导出整个名册](docs/images/export-roster-scale.png)

*先看导出这一侧：Grok Bot 的参考导出器一轮跑下来，把整个名册的 bot 挨个导出。哪个 bot 的档案没过敏感信息扫描，就把哪个拦下来，还要显眼地报出来，不会不声不响地丢掉。*

![Hatch 的档案渲染成的 Notion 页面](docs/images/hatch-notion-page.png)

*Hatch 的档案渲染成的 Notion 页面（英文版）。页面开头是档案生成的六段人读版，机器可读的原件在页面末尾。*

## 状态与路线图

当前是 v1.0。改名发生在这一版：项目原名 agent-dossier，现在叫 personal-agent-dossier。手里还有旧档案的也不用慌，导入方照样认 `agent-dossier/0.1` 和 `agent-dossier/0.2` 这两个旧标识，指纹算法一点没动。

还有几个问题没定下来，欢迎一起讨论：要不要把 role 里的 bot 名单拆出来、单独放一个字段；长期记忆要不要分层、要不要设过期；多个 agent 之间交接工作时，关系怎么记；附件和工具权限又该怎么表达。

## 许可

MIT，见 `LICENSE`。
