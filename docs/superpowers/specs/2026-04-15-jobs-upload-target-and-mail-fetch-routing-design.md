# Jobs Upload Target And Mail Fetch Routing Design

**Date:** 2026-04-15

**Status:** Approved by user in chat

## Goal

简化“注册任务”页，只保留任务级的“上传目标”选择，不再在任务页暴露整套 `Sub2API` 覆盖参数；同时在点击“开始注册”后，系统应自动根据当前邮箱账户的真实配置判断验证码应从 `imap` 还是 `graph` 拉取，而不是让任务页再参与这一选择。

## Current Problem

当前实现存在两个直接的使用问题：

1. `webui_frontend/src/pages/Jobs.jsx` 在任务启动表单中展示了整套 `Sub2API 任务覆盖` 配置，包括 `Group IDs`、`Proxy ID`、`模型白名单` 等字段。
2. 这些字段本质上属于全局上传配置，而不是“注册任务”本身的核心启动参数，导致任务页变得冗长、容易误操作，也让“上传目标”和“上传细节配置”混在一起。
3. 用户期望在点击“开始注册”时，系统只需要根据当前选择的邮箱账户自动识别验证码通道。
4. 后端虽然已经在 Outlook 账户上存有 `fetch_method`，但任务入口没有把这种“自动按账户配置判定”的行为显式收敛成更清晰的任务语义。

## Scope

本次仅处理：

- 注册任务页的任务启动表单收口
- 任务启动 payload 的最小化
- WebUI 后端对任务级 `sub2api_upload` 覆盖的忽略/收敛
- 运行时日志中明确当前账户的验证码拉取通道
- 对应前后端测试

明确不处理：

- Settings 页里的 `Sub2API` 全局配置结构
- `Sub2API` 上传实现本身
- Outlook / IMAP 的底层收信实现
- OTP 状态机本身
- 现有邮箱账户配置格式迁移

## User-Facing Design

### Jobs Page Form

`注册任务` 页中的任务启动表单只保留以下字段：

- 注册数量
- 浏览器引擎
- 邮件服务
- 上传目标
- 开始注册

当用户选择 `upload_provider = sub2api` 时，不再在任务页展开任何额外字段。任务页不再承担 `Sub2API` 配置中心的职责。

### Upload Target Semantics

任务页中的“上传目标”只表达“这次注册完成后结果上传到哪里”，允许的值仍然是：

- `none`
- `cpa`
- `sub2api`

但如果选择 `sub2api`，实际使用的上传参数统一来自设置页保存的全局 `sub2api_upload` 配置，不允许在任务页做单任务覆盖。

### Mail Fetch Routing Semantics

点击“开始注册”后，验证码拉取通道不再由任务页提供或覆盖，而是完全由当前邮箱 provider 和账户配置自动决定：

- `imap:*` provider：直接走 IMAP
- `outlook` / `outlook:*` provider：读取所选 Outlook 账户自己的 `fetch_method`
  - `graph` -> 走 Microsoft Graph
  - `imap` -> 走 IMAP XOAUTH2
- 其他邮件 provider：继续保持它们原本的取码逻辑

### Runtime Visibility

为了让自动判定行为对用户可见，任务日志中应增加当前账户的取码通道信息，例如：

- `邮箱 foo@outlook.com 使用 graph 获取验证码`
- `邮箱 bar@hotmail.com 使用 imap 获取验证码`
- `邮箱 baz@gmail.com 使用 imap 获取验证码`

这样用户在任务运行过程中可以直接确认系统判定是否符合预期。

## Backend Design

### Job Request Shape

`POST /api/jobs` 的任务启动请求应收敛为任务级最小参数：

- `count`
- `provider`
- `engine`
- `upload_provider`

后端对请求体中的 `sub2api_upload` 字段保持兼容读取，但不再把它作为任务级覆盖来源。即使旧前端或外部客户端继续发送该字段，本次也应忽略任务覆盖，统一使用全局配置。

### Job Model

`src/webui/server.py` 中的 `_Job` 不再需要承载“任务级 `sub2api_upload` 覆盖”的运行时语义。

可接受的实现方式有两种：

1. 直接移除 `_Job.sub2api_upload`
2. 保留字段用于兼容显示，但运行时完全不使用

推荐第 1 种，避免继续传达“任务级覆盖仍有效”的错误信号。

### Config Merge Rule

`_run_job()` 中构建运行时配置时，不再执行“全局 `sub2api_upload` + 任务级 `sub2api_upload`”的 merge。运行时应直接使用 `settings_db.build_config()` 返回的全局 `sub2api_upload`。

这意味着：

- Settings 页中的 `sub2api_upload` 仍然是唯一生效来源
- Jobs 页不再能改变 `group_ids`、`priority`、`model_whitelist` 等上传参数

### Mail Client Routing

`_run_job()` 内部的 mail client 选择逻辑继续保留现有 provider 解析方式，但应把“验证码拉取通道”显式记录到任务日志。

具体规则：

- Provider 为 `imap:*` 时，日志写明当前邮箱使用 `imap`
- Provider 为 Outlook 账户时，构建 `OutlookMailClient` 后读取账户的 `fetch_method`，日志写明当前邮箱使用 `graph` 或 `imap`
- 其他 provider 可不额外区分，或根据现有客户端类型写出固定通道说明，但本次重点是 IMAP/Outlook 自动判定透明化

## Frontend Design

### Jobs.jsx

`webui_frontend/src/pages/Jobs.jsx` 需要做三类变化：

1. 移除 `EMPTY_SUB2API_UPLOAD_CONFIG`、`normalizeSub2APIUploadConfig`、`serializeSub2APIUploadConfig` 在任务页中的使用
2. 移除 `jobGroupIdsText`、`jobModelWhitelistText` 以及所有 `Sub2API 任务覆盖` 表单控件
3. `startJob()` 只发送任务级最小 payload，不再附带 `sub2api_upload`

### Settings Page Compatibility

`webui_frontend/src/pages/Settings.jsx` 和 `webui_frontend/src/lib/sub2apiUploadConfig.js` 保持不变，继续作为全局 `Sub2API` 配置入口。

这保证：

- 既有设置数据继续生效
- 用户仍然可以在设置页维护 `Sub2API` 参数
- UI 职责边界更清晰

## Data And Compatibility

不新增表，不迁移历史数据。

兼容行为如下：

- 已保存在数据库中的 `sub2api_upload` 全局配置继续生效
- 已有任务历史记录不需要迁移
- 如果旧客户端仍发送 `sub2api_upload`，后端应忽略任务级覆盖而不是报错

## Implementation Areas

前端：

- `webui_frontend/src/pages/Jobs.jsx`
- `webui_frontend/src/lib/providerOptions.test.js`

后端：

- `src/webui/server.py`
- `test/test_sub2api_upload.py`
- 与 Outlook 任务路由相关的测试文件

## Testing

### Frontend Tests

至少覆盖：

- `Jobs.jsx` 源码中不再出现 `Sub2API 任务覆盖`
- `Jobs.jsx` 源码中不再出现 `Group IDs`
- `Jobs.jsx` 源码中不再出现 `模型白名单`

### Backend Tests

至少覆盖：

- `api_start_job()` 在请求体带有 `sub2api_upload` 时，不再把这些字段作为任务级覆盖保存或使用
- `_run_job()` 使用全局 `sub2api_upload`，不再 merge 任务级覆盖
- Outlook 账户运行任务时，会按账户自己的 `fetch_method` 选择 `graph` 或 `imap`
- 任务日志包含当前账户实际使用的验证码拉取通道

## Risks And Guardrails

### Risk: Frontend/Backend Version Skew

如果前端已更新但后端未更新，任务页虽然不再发送 `sub2api_upload`，但实际问题不大；如果后端已更新但旧前端仍发送 `sub2api_upload`，后端忽略该字段即可安全兼容。

### Risk: User Cannot Discover Active Fetch Method

如果只自动判定但不记录日志，用户仍然无法确认当前到底走了 `graph` 还是 `imap`。因此日志补充不是装饰，而是这次交互设计的一部分。

## Success Criteria

满足以下条件即视为完成：

1. `注册任务` 页只保留“上传目标”选择，不再展示任何 `Sub2API 任务覆盖` 字段。
2. 任务启动请求不再携带任务级 `sub2api_upload` 配置。
3. 后端不再应用任务级 `sub2api_upload` 覆盖，统一使用全局设置。
4. 开始注册后，系统会根据当前邮箱账户自动判定验证码来源是 `imap` 还是 `graph`。
5. 任务日志能看出当前邮箱实际走的是哪条验证码通道。
6. 相关前后端测试通过。
