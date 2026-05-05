---
name: smart-search
description: |
  Intelligent search router for finding information across websites.
  USE WHEN user wants to search, find, lookup, or research information.
  USE WHEN user mentions specific websites (bilibili, zhihu, twitter, weibo, xiaohongshu/小红书, douyin, github, etc.).
  USE WHEN user asks about hot/trending/popular content.
  USE WHEN user wants to access platform-specific content (hot videos, trending topics, popular posts).
  USE WHEN user wants to find and view content on a specific platform.
  USE WHEN user needs to query specific platforms or data sources.
---

# 智能搜索路由器

根据话题和场景，将查询路由到最佳的 opencli 搜索源。此 skill 的核心目标不是记忆命令，而是先定位数据源，再让 Agent 通过 `opencli` 自己读取实时帮助，避免文档漂移。

## 强制预检

每次使用前，必须先做下面两步：

- 运行 `list -f yaml` 获取所有可用站点
- 从返回的站点列表中确认目标站点的**准确名称**（如 `hackernews` 不是 `hn`，`bilibili` 不是 `b站`）

选定站点后，必须再做下面两步：

- 运行 `<site> -h` 查看该站点有哪些子命令（如 `hackernews -h`）
- 若已锁定某个子命令，再运行 `<site> <command> -h` 查看参数、输出列、策略

**关键**：永远不要猜测命令！必须先运行帮助命令确认。

**常见错误**：
- ❌ `hn top` → 正确：`hackernews top`
- ❌ `b站 hot` → 正确：`bilibili hot`
- ❌ `weibo search xxx` → 先运行 `weibo -h` 确认是否有 search 命令
- ❌ `opencli xiaohongshu search Dyson 卷发棒` → 空格导致 "too many arguments"
- ❌ `opencli xiaohongshu search "Dyson 卷发棒"` → 引号容易导致模型过度转义，不推荐
- ✅ `opencli xiaohongshu search Dyson卷发棒` → 去掉空格合并为一个词（推荐）

**搜索关键词格式规则**：

`search` 子命令的查询词只接受**一个参数**。如果关键词包含空格，**不要使用引号包裹**（引号容易导致模型过度转义），而是去除空格合并为一个词。

| 写法 | 结果 |
|------|------|
| `search Dyson 卷发棒` | 报错：too many arguments |
| `search "Dyson 卷发棒"` | 不推荐：引号容易导致模型过度转义 |
| `search Dyson卷发棒` | 推荐：去除空格合并为一个词 |

推荐做法：始终将多词关键词合并为一个词（如 `Dyson卷发棒`），不使用引号。这样更简洁且避免模型在生成命令时对引号进行过度转义。

不要在 skill 文档里硬编码参数或假设命令签名；以实时帮助输出为准。

## 主路由规则

只使用这一条规则，不再维护多套优先级：

1. 当用户明确指定网站、平台或数据源时，直接使用对应网站。
2. 当用户没有指定网站时，优先只选择一个 AI 源：`grok`、`doubao`、`gemini` 三选一。
3. 当 AI 返回内容不足、缺少原始数据、需要权威佐证或需要垂直结果时，再补充 1-2 个专用源。

## 单题预算与频率限制

把“单个用户问题”理解为同一意图链路下的一次问题求解；同一轮追问、澄清、补充条件，若核心问题未变，仍算同一题。

先建立一份站点调用台账。每次真正执行搜索命令后，立刻更新：

- `site`
- `query`
- `count`
- `status`

计数规则：

- `opencli list -f yaml`、`opencli <site> -h`、`opencli <site> <command> -h` 属于预检与帮助，不计入搜索次数
- 一次真正的 `opencli <site> ...` 搜索/查询执行，计为该站点 1 次调用
- 同站点因为报错、超时、验证码、反爬、登录态异常而失败，也算 1 次调用，不要无限重试

频率上限：

- AI 站点硬限制：同一题内，每个 AI 站点最多调用 1 次
- 默认策略仍然是只选 1 个 AI 站点，不要把多个 AI 站点串成常规流程
- 只有当用户明确要求比较多个 AI 站点时，才可以额外调用其他 AI 站点；但每个被点名的 AI 站点仍然最多 1 次
- 非 AI 站点默认最多调用 2 次
- 非 AI 站点第 2 次调用必须有明确理由，例如第一次结果过宽，需要加时间、地区、类别、排序或关键词限定
- 非 AI 站点不要进行第 3 次调用；若信息仍不足，停止扩搜并明确说明缺口

触发限频后的处理：

- 记录：「已跳过：<site> 达到频率上限」
- 优先改用其他同类站点
- 若没有合适替代源，则直接基于已收集信息回答，并说明覆盖范围与缺口

## 查询结束汇报

每次查询结束后，回答末尾必须追加一段简短的“搜索摘要”，至少包含下面三项：

- 使用了什么网站搜索
- 每个网站搜了什么词
- 每个网站搜了几次

如果有被限频跳过的站点，也要明确写出。

建议使用下面的固定格式：

```md
搜索摘要
- 网站：<site1> | 查询词：<term1> | 次数：<n>
- 网站：<site2> | 查询词：<term2>；<term3> | 次数：<n>
- 已跳过：<site3>，原因：达到频率上限
```

## AI 源选择

- `grok`
  适合实时讨论、英文互联网舆论、Twitter/X 语境、热点追踪。
- `doubao`
  适合中文语境、字节抖音生态、生活方式内容、中文热点与泛中文问答。
- `gemini`
  适合全球网页、英文资料、通用信息检索、背景综述。

如果用户没有指定网站，默认先判断语言和语境，再从这三个里只选一个。

一旦某个 AI 站点已经执行过一次真实查询，就不要在同一题里改写关键词后再次调用该 AI 站点。若答案不足，优先补专用源，不要反复追打同一个 AI 站点。

## AI 查询词建议

当使用 AI 源时，不要只丢一个过短关键词。优先构造成“主题 + 目标 + 限定条件”的查询。

- 主题
  用户真正要查的对象、事件、产品、人物、公司、技术名词。
- 目标
  想要什么结果，例如总结、对比、原因、趋势、推荐、原始线索。
- 限定条件
  语言、地区、时间范围、平台范围、受众、价格带、岗位地点、是否要引用原始来源。

优先使用下面这种表达方式：

- `<主题> + <你要回答的问题>`
- `<主题> + <时间范围/地区/语言>`
- `<主题> + <平台或来源范围>`
- `<主题> + <输出要求>`

避免只输入：

- 单个名词
- 没有时间范围的热点问题
- 没有地区限制的购物、求职、旅游问题
- 没有平台限制的社交媒体问题

## 专用源补充时机

当出现以下任一情况时，再补充专用源：

- AI 给出的是摘要，但你需要原始帖子、原始视频、原始商品或原始职位结果
- AI 覆盖面不足，漏掉垂直站点信息
- 需要更高权威性或更强领域相关性
- 用户明确要求“从某个平台找”

单次查询通常控制在 1 个 AI 源 + 1 到 2 个专用源，避免结果过载。

## 处理不可用的源

当站点不可用时：

- 不要因为单个源失败而中止整个搜索
- 记录：「已跳过：<site> 不可用」
- 回退到同类其他站点，或回退到一个 AI 源
- 始终以 `opencli list -f yaml` 与 `opencli <site> -h` 的实际结果为准

不要假设任何站点“绝对可用”。即使是公开站点，也以当前环境中的 live help 和执行结果为准。

## 参考文件

根据需要读取对应文件：

- **`references/sources-ai.md`** — AI 默认源
- **`references/sources-tech.md`** — 技术 / 学术
- **`references/sources-social.md`** — 社交媒体
- **`references/sources-media.md`** — 媒体 / 娱乐
- **`references/sources-info.md`** — 资讯 / 知识
- **`references/sources-shopping.md`** — 购物
- **`references/sources-travel.md`** — 旅游
- **`references/sources-other.md`** — 其他垂直源

只读与当前查询相关的文件，无需全部加载。

## Skill 组合示例

此 skill 可与其他 skill 组合使用，实现更复杂的功能：

**重要**：当搜索结果中包含URL时，必须使用完整URL（包含所有查询参数如 xsec_token）。使用 `opencli browser open "完整URL"` 打开对应页面。不要截断URL中的查询参数，缺少参数会导致页面无法访问。

### 示例 1：搜索 + 打开视频
用户: "帮我找一下抖音上最火的舞蹈视频"
```
1. load_skill("smart-search")  # 加载搜索 skill
2. opencli("opencli douyin -h")        # 查看帮助
3. opencli("opencli douyin hot")       # 获取热门视频
4. opencli("opencli browser open [ref:1]")  # 使用简化URL打开第一个视频
5. opencli("opencli browser state")    # 查看页面元素
```

### 示例 2：搜索 + 提取数据
用户: "搜索知乎上关于 AI 的热门问题并提取标题"
```
1. load_skill("smart-search")  # 加载搜索 skill
2. opencli("opencli zhihu hot")        # 获取热门问题
3. load_skill("opencli-explorer")  # 加载探索 skill
4. opencli("opencli browser open [ref:1]")   # 使用简化URL打开问题页面
5. opencli("opencli browser get text 1")   # 提取数据
```

### 示例 3：小红书搜索
用户: "看看小红书有什么卷发棒推荐"
```
1. load_skill("smart-search")                    # 加载搜索 skill
2. opencli("opencli xiaohongshu -h")                     # 查看小红书命令
3. opencli("opencli xiaohongshu search 卷发棒 --limit 5")  # 搜索笔记（关键词不含空格，不使用引号）
4. opencli("opencli browser open 完整URL")  # 使用搜索结果中的完整URL打开笔记详情（URL不加引号）
```

**注意**：小红书的 `note`、`comments` 等命令可能未实现。请务必先运行 `opencli xiaohongshu -h` 确认可用命令。搜索结果中的URL必须完整使用（包含查询参数），不要截断。

**小红书工作流程**：
1. 搜索笔记 → 2. 查看搜索结果中的标题、点赞数等信息 → 3. (如需详情) 用 `browser open "完整URL"` 打开笔记页面

### 示例 4：多 skill 协作
用户: "在微博上搜索 AI 并保存前 10 条结果"
```
1. load_skill("smart-search")  # 加载搜索 skill
2. opencli("opencli weibo search AI")  # 搜索
3. load_skill("opencli-explorer")  # 加载探索 skill
4. opencli("opencli browser get html") # 提取数据
5. write results.json         # 保存结果
```
