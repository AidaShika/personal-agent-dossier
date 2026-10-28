# Agent Dossier 规范 v0.2（草案）

目的：用一份平台无关的文件描述一个 agent 的职能、定时任务、长期记忆和依赖，使它能在不同平台间迁移或同步。

## 1. 存储位置（二选一，格式相同）

同一份内容可以存在两种位置，由用户选择；字段和规则完全一样，导入方必须两种都能读。

| 方式 | 怎么存 | 适合 |
|---|---|---|
| 文件 | 一个 agent 一个 `<slug>.dossier.md`；头部是 YAML front matter（机器读），正文是 Markdown（人读） | 要放进 git、要离线备份、目标平台读不了 Notion |
| Notion | 一个 bot 一个页面；页面里有标题「机器可读版（agent-dossier/x.y）」（x.y 是规范版本），下面是一个 ```yaml 代码块，内容就是文件方式的 front matter；其他段落是给人看的说明，由 YAML 自动生成（`tools/render_notion.py`），不手写 | 想在 Notion 里浏览、搜索和筛选，团队一起看 |

规则：
- 以 YAML 为准。Notion 页面里 YAML 以外的段落只是说明，导入方不得依赖它们。
- 一个页面只能有一个 YAML 代码块。
- 两处同时存在时，以 `exported_at` 较新的为准；相同则视为一致。
- 编码 UTF-8。`spec` 字段必填，写 `agent-dossier/0.2`。导入方应同时接受 `0.1`（v0.2 只增不改，0.1 档案仍然有效，只是没有 `refs`）。

## 2. Front matter 字段

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| spec | 是 | string | 规范版本，写 `agent-dossier/0.2`（`0.1` 仍可读） |
| id | 是 | string | 源平台里的唯一 id；同步时以它为键，不用显示名 |
| name | 是 | string | 显示名 |
| title | 否 | string | 一句话职能标签 |
| group | 否 | string | 分区或分组 |
| status | 是 | enum | `active` / `handed-over` / `retired` |
| exported_at | 是 | date | 导出日期（ISO 8601） |
| source | 是 | string | 导出自哪个平台，如 `grok-bot` |
| fingerprint | 是 | string | 职能指纹，算法见第 2.1 节 |
| role | 是 | string | 职能全文，原样保留 |
| anti_jobs | 否 | list[string] | 反职责：明确不做什么 |
| routines | 是 | list 或 null | 定时任务，没有就写 `[]`；`null` 表示这次没有导出，见第 3 节 |
| memory | 是 | list 或 null | 长期记忆，没有就写 `[]`；`null` 表示这次没有导出，见第 4 节 |
| refs | 否 | list | 本 agent 依赖或会交接给的其他 agent（role、anti_jobs、memory 里点名的），每项 `{name, id}`；换平台后 id 不能解析，导入方按名字重新对应。role 里「避免职能重复」的整份名单不算（见第 7 节） |
| skills | 否 | list[string] | 依赖的 skill 名称，只记名称，不复制内容 |
| excluded | 否 | string | 导出时有意去掉的内容的一句话说明 |

### 2.1 fingerprint 的精确算法
1. `name`、`title`、`role` 各自：把 `\r\n` 换成 `\n`，再去掉首尾空白（按 Unicode 的 White_Space 属性，包含全角空格 U+3000 和 U+00A0，不只是 ASCII 空白；Python 的 `str.strip()`、JavaScript 的 `trim()` 都符合）。`title` 没有时当作空字符串。
2. 用英文竖线 `|` 把三段连起来：`name|title|role`。
3. 按 UTF-8 编码，做 SHA-1，取十六进制前 12 位。

第 1 步的「去掉首尾空白」是为了避免不同 YAML 写法（`|` 与 `|-`）造成末尾换行不同而误报。`tests/fingerprint-vectors.json` 给出了标准答案，任何实现都应先跑 `tests/check_vectors.py` 通过后再用。

说明：Grok Bot 的 Notion 名册里的「内容指纹」列用的就是本节的算法，和档案里的 `fingerprint` 是同一个值，可以直接比较，用来发现漂移。

## 3. routines 条目

| 字段 | 必填 | 说明 |
|---|---|---|
| id | 是 | 任务在源平台的 id |
| name | 是 | 任务名 |
| schedule | 是 | cron 表达式或事件触发描述，写明时区 |
| prompt | 是 | 完整 prompt 原文 |
| state | 是 | `running` / `paused` / `deleted` |

## 4. memory 条目

| 字段 | 必填 | 说明 |
|---|---|---|
| fact | 是 | 一条自包含的事实，不写聊天流水 |
| kind | 是 | `rule`（规则）/ `preference`（偏好）/ `decision`（决定）/ `history`（已做的事） |
| learned | 否 | 记录日期 |

## 5. 脱敏规则（导出方必须执行，导入方必须再检查一次）
1. 地址、电话、生日、家庭成员、证件号、银行卡、账号密码、令牌、API key 不写入文件。需要提示时写 `[已存保管库]`。
2. 导出前对 `fact` 和 `prompt` 跑一遍正则扫描：邮箱、日本电话号码、16 位卡号、`sk-` / `ghp_` 之类令牌、`password`/`密码` 后面跟的值；命中则中止导出并报告命中位置，不自动改写。
3. 其他 agent 的记忆不由本 agent 导出；每个 agent 只导出自己的。
4. 正文里出现 UUID（多半是其他 agent 的 id）只给出警告，不中止；应把它们写进 `refs`，说明换平台后不可解析。

## 6. 同步与迁移语义
- 导出：幂等。同一份源数据连续导出两次，除 `exported_at` 外字节一致。
- 同步：按 `id` 配对；`fingerprint` 不同则视为职能变化，需输出差异（逐句对比 `role`）。
- 导入：目标平台能表达的字段原样还原；不能表达的字段放进正文保留，并在导入报告里逐项列出「丢失或降级」。导入方不得静默丢字段。
- `null` 与 `[]`：`null` 是「这次没导出」，`[]` 是「确实没有」。导入方必须在报告里把 `null` 写成「未导出，不等于没有」，并保留原档案副本，不得把它当成空。
- 删除：源端删掉的 routine 在文件里标 `state: deleted` 保留，不直接移除。

## 6.1 平台能力等级
导入方在报告开头声明自己属于哪一级，读者据此知道哪些语义会保留。

| 等级 | 含义 | 例子 |
|---|---|---|
| L0 | 只能把档案读出来、文字还原 role 和记忆，没有结构化字段 | 只有笔记和提示词的平台 |
| L1 | 能保存全文，并能自己校验指纹、按 kind 打标签，但不按 id 同步 | 自定义 skill + 文件的组合 |
| L2 | 能按 `id` 配对并更新职能，能建定时任务和写记忆 | Grok Bot（名字和描述按 id 更新；记忆日期和 routine id 会变） |

## 7. 尚未定的问题（v0.3 讨论）
- role 里的 bot 名单会随时间过期，是否把它从 role 拆成独立字段（第三方平台测试提出）。
- 记忆是否需要分层（短期、长期）以及过期时间。
- 多个 agent 之间的交接关系（谁接手谁）是否进同一文件还是单独的 `roster` 文件。
- 附件和工具权限的表达方式。

## 8. 变更记录
- v0.2（补丁，来自第三方平台的第二轮测试）：refs 范围写明；strip 的空白字符集写明并加两组向量；任务书不再写死记忆条数。
- v0.2：Notion 页面的人读段落改为由 YAML 生成，避免漂移（Notion 版测试发现）；指纹算法写死并附测试向量；新增 `refs`；`null` 与 `[]` 的导入要求；平台能力等级；正文 UUID 警告（均来自 Muse 文件版测试，2026-10-28）。
