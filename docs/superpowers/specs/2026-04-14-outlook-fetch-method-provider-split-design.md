# Outlook Fetch-Method Provider Split Design

**Date:** 2026-04-14

**Status:** Approved by user in chat

## Goal

在现有注册任务入口中，保留现有 `outlook` 混合轮换能力，同时新增显式的 Outlook provider：

- `outlook-imap`
- `outlook-imap:N`
- `outlook-graph`
- `outlook-graph:N`

使用户可以直接在注册页面限制“只使用 IMAP Hotmail”或“只使用 Graph Hotmail”进行注册，而不需要记忆具体邮箱或进入设置页查看每个账户的 `fetch_method`。

## Current Problem

当前系统虽然在账户配置层已经支持 Outlook/Hotmail 的两种取件方式：

- `fetch_method = "imap"`
- `fetch_method = "graph"`

但任务入口和仪表盘只暴露了这些 provider：

- `outlook`
- `outlook:N`
- `outlook:no-token`

这带来两个问题：

1. 用户在启动任务时无法直接限制“只用 IMAP”或“只用 Graph”。
2. `outlook:N` 只暴露邮箱索引，不暴露取件方式，导致用户无法从任务界面判断某个 Outlook 账户到底走的是 IMAP 还是 Graph。

从使用体验看，这等于“系统内部能区分，但用户入口无法控制”，因此无法从任务层面根治“这批任务只能跑 IMAP Hotmail / Graph Hotmail”的诉求。

## Scope

本次只处理 Outlook provider 的选择语义、后端筛选逻辑、任务入口展示和对应测试。

明确不处理：

- Outlook 账户存储结构迁移
- `mail.outlook` 配置格式变更
- Outlook token 刷新实现
- Graph / IMAP 实际收件逻辑
- OTP 状态机本身
- 历史任务数据迁移

## Design

### Provider Set

保留旧 provider：

- `outlook`
- `outlook:N`

新增新 provider：

- `outlook-imap`
- `outlook-imap:N`
- `outlook-graph`
- `outlook-graph:N`

移除现有虚拟 provider：

- `outlook:no-token`

### Provider Semantics

语义拆成两层：

1. 先确定 Outlook provider family
2. 再按 family 决定是否对 `mail.outlook` 账户列表按 `fetch_method` 过滤
3. 最后再应用轮换或固定索引 `:N`

具体规则如下：

- `outlook`
  使用全部 Outlook 账户，不按 `fetch_method` 过滤，保持现有混合轮换语义。

- `outlook:N`
  使用全部 Outlook 账户，不按 `fetch_method` 过滤，固定取原始 Outlook 列表中的第 `N` 个账户，保持现有语义。

- `outlook-imap`
  先筛出 `fetch_method == "imap"` 的 Outlook 账户，再在过滤后的列表中执行轮换。

- `outlook-imap:N`
  先筛出 `fetch_method == "imap"` 的 Outlook 账户，再固定取过滤后列表中的第 `N` 个账户。

- `outlook-graph`
  先筛出 `fetch_method == "graph"` 的 Outlook 账户，再在过滤后的列表中执行轮换。

- `outlook-graph:N`
  先筛出 `fetch_method == "graph"` 的 Outlook 账户，再固定取过滤后列表中的第 `N` 个账户。

### Indexing Rule

新的 `:N` 索引必须始终对“过滤后的结果集”编号，而不是对原始 `mail.outlook` 总列表编号。

示例：

原始 Outlook 列表：

1. A (`imap`)
2. B (`graph`)
3. C (`imap`)

则：

- `outlook:1` -> B
- `outlook-imap:0` -> A
- `outlook-imap:1` -> C
- `outlook-graph:0` -> B

这样用户看到的 provider 文案和实际行为能保持一致，不会出现“显示是第 1 个 IMAP，但实际取原总表第 1 个”的歧义。

## Backend Design

### Shared Outlook Selector

在 `src/webui/server.py` 中，把当前 Outlook 账户选择逻辑收敛到一个统一 helper：

- 解析 provider family：`outlook` / `outlook-imap` / `outlook-graph`
- 从 `mail.outlook` 读取全部 Outlook 账户
- 按 `fetch_method` 过滤：
  - `outlook` -> 不过滤
  - `outlook-imap` -> 仅 `imap`
  - `outlook-graph` -> 仅 `graph`
- 解析可选索引 `:N`
- 对过滤后的结果执行：
  - `family:N` -> 固定索引
  - `family` -> 轮换

### Empty Result Handling

当过滤后没有可用账户时，报清晰错误，不自动回退到混合 `outlook`：

- `outlook-imap` -> `没有配置 fetch_method=imap 的 Outlook 账户`
- `outlook-graph` -> `没有配置 fetch_method=graph 的 Outlook 账户`

固定索引越界时，也必须基于过滤后的列表总数报错，例如：

- `outlook-imap:3 out of range — 2 account(s) configured`

### Mail Client Construction

最终创建 `OutlookMailClient` 的方式不变：

- `email`
- `client_id`
- `tenant_id`
- `refresh_token`
- `access_token`
- `fetch_method`
- `proxy`

也就是说，本次只是 provider 入口和账户筛选语义变化，不改具体客户端实现。

### Compatibility

后端仍然只读取现有 `mail.outlook` 配置，不新增新的 settings section。

这保证：

- 已有 Outlook 配置无需迁移
- 历史 provider `outlook` / `outlook:N` 继续可用
- 新 provider 只是对现有配置做运行时过滤

## Frontend Design

### Provider Options

在 `webui_frontend/src/lib/cfworkerConfig.js` 的 provider option 构建逻辑中：

- 删除 `outlook:no-token`
- 保留 `outlook`
- 新增 `outlook-imap`
- 新增 `outlook-graph`
- 在 Jobs 和 Dashboard 中，继续展示固定索引项

推荐展示文案：

- `Outlook（全部 X 账户轮换）`
- `Outlook IMAP（X 账户轮换）`
- `Outlook Graph（X 账户轮换）`

固定项建议直接带上取件方式前缀：

- `└ IMAP: noqlub26832o@hotmail.com`
- `└ Graph: abc@hotmail.com`

### Surface Areas

需要同步更新：

- Jobs 页面 provider 下拉框
- Dashboard 快速启动 provider 下拉框
- 相关 provider option 测试

设置页的 Outlook 账户编辑能力不需要拆成两个列表；继续由账户自身的 `fetch_method` 字段决定其归属。

### Task Display

任务列表和仪表盘中展示的 provider 字符串直接保留真实值：

- `outlook`
- `outlook-imap`
- `outlook-graph:2`

不再通过旧的 `outlook:no-token` 逻辑包装特殊标签。

这样从任务记录层面也能直接看出该任务限制的是哪类 Hotmail。

## Data Model

不新增表，不新增 settings section，不迁移历史数据。

继续复用已有 Outlook 账户结构：

- `email`
- `password`
- `client_id`
- `tenant_id`
- `refresh_token`
- `access_token`
- `fetch_method`
- `proxy`

其中 `fetch_method` 继续作为唯一分流依据，默认值仍为 `graph`。

## Implementation Areas

后端：

- `src/webui/server.py`
  重构 Outlook provider 解析与账户筛选逻辑，新增 fetch-method family 语义。

前端：

- `webui_frontend/src/lib/cfworkerConfig.js`
  更新 provider option 构建逻辑。

测试：

- `test/test_outlook_provider_split.py`
  新增或补充后端 provider 过滤测试。
- `webui_frontend/src/lib/providerOptions.test.js`
  更新前端 provider options 测试。

## Testing

### Backend Tests

至少覆盖以下情况：

- `outlook` 返回全部 Outlook 账户
- `outlook:1` 固定取原始列表索引
- `outlook-imap` 仅返回 `fetch_method=imap`
- `outlook-graph` 仅返回 `fetch_method=graph`
- `outlook-imap:0` / `outlook-graph:0` 对过滤后的结果索引
- `outlook-imap` 在无匹配账户时返回明确错误
- `outlook-graph:N` 越界时报基于过滤后结果的错误

### Frontend Tests

至少覆盖以下情况：

- `outlook:no-token` 不再出现在 Settings / Dashboard / Jobs 选项中
- `outlook-imap` / `outlook-graph` 出现在 Dashboard / Jobs 中
- 固定项标签携带 `IMAP` / `Graph` 前缀
- 旧的 `outlook` 和 `outlook:N` 仍保留

## Risks

- 新旧 provider 并存后，若解析代码写散，容易导致 `outlook` 与 `outlook-imap` 的索引语义不一致，因此必须收敛到统一 selector。
- 前端固定项一旦按过滤后结果编号，标签和后端必须使用同一套排序规则，否则用户看到的 `outlook-imap:1` 可能与后端实际命中不一致。
- 当前工作区已有大量未提交改动，实现阶段必须保持小范围增量修改，不回退现有文件内容。

## Non-Goals

- 不解决本轮排查中暴露出的 OTP `pending` 后复用同一 page 导致重试偏移的问题
- 不解决 Graph token refresh 的历史异常
- 不新增“按 token 状态过滤”的 Outlook provider 变体
