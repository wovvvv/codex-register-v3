# IMAP Forwarded-Domain Registration Design

**Date:** 2026-04-06

**Status:** Approved by user in staged review

## Goal

让 `IMAP` 邮件后端支持“注册邮箱地址”和“实际收件邮箱”解耦。

目标场景：

- 注册时生成 `random@custom-domain`
- 实际通过某个可登录的 IMAP 收件箱收信
- 继续按 `To:` / `Delivered-To:` 头精准过滤验证码
- 保持现有 `mail_provider=imap:0` 使用方式不变

典型示例：

- 注册邮箱：`random@dfghdfghd.xyz`
- Cloudflare Email Routing：将 `*@dfghdfghd.xyz` 转发到 `sanviewyouzi@gmail.com`
- 实际收件：程序登录 `sanviewyouzi@gmail.com` 的 IMAP 收件箱读取验证码

## Current Problem

当前 `registration.domain` 已经从注册流程传入 `mail_client.generate_email(prefix, domain)`，但 `IMAPMailClient.generate_email()` 并不会使用它。

现状行为：

- 固定模式：返回真实收件箱地址
- Gmail/QQ 别名模式：返回 `local+alias@domain`
- 无法返回 `random@custom-domain`

这意味着：

- `IMAP` 可以收 Gmail/QQ/普通邮箱
- 但不能表达“域名邮箱转发到 Gmail 收件箱”的注册地址生成逻辑

## Design Overview

对每个 `IMAP 服务商` 引入两层职责：

1. 收件层
负责真实 IMAP 登录与收件。

2. 注册地址生成层
负责决定注册时实际填写的邮箱地址。

一个 `IMAP 服务商` 同时描述：

- 去哪个收件箱收邮件
- 注册时生成什么样的邮箱地址

这样仍然可以通过 `mail_provider=imap:0` 选择第一个 IMAP 服务商，不需要新增 provider 类型。

## Data Model

### Existing Provider Fields

保留现有服务商级字段：

- `name`
- `host`
- `port`
- `ssl`
- `folder`
- `auth_type`
- `use_alias`（旧字段，后续只作为兼容输入）
- `accounts[]`

保留现有账户级字段：

- `email`
- `credential`

### New Provider Fields

为每个 IMAP 服务商新增：

- `address_mode`
- `registration_domain`

建议取值：

- `address_mode = "inbox"`
  直接使用收件箱地址注册

- `address_mode = "plus_alias"`
  使用收件箱地址的 `+alias` 变体注册

- `address_mode = "random_local_part"`
  使用随机本地名 + `registration_domain` 注册

`registration_domain` 仅在 `random_local_part` 模式下生效，例如：

- `dfghdfghd.xyz`

### Compatibility Mapping

旧配置兼容规则：

- 若存在旧 `use_alias=true`
  映射为 `address_mode="plus_alias"`

- 若无新字段也无旧别名配置
  默认 `address_mode="inbox"`

- 旧的 Gmail/QQ 自动别名逻辑改为 UI 层默认值/迁移逻辑，不再作为隐藏行为决定最终模式

## WebUI Changes

位置：`IMAP` 页签中，每个服务商的共享配置区域。

### Replace

将现有“别名模式”替换为更清晰的“注册邮箱模式”。

### New UI Fields

每个 IMAP 服务商显示：

- `注册邮箱模式`
  选项：
  - `收件箱地址`
  - `+alias 地址`
  - `自定义域名随机地址`

- `注册域名`
  仅在 `自定义域名随机地址` 时显示

### UX Expectations

- 用户仍然在账户列表里填写真实收件箱，例如 `sanviewyouzi@gmail.com`
- 用户通过 `注册邮箱模式 + 注册域名` 决定“对外注册时用什么地址”
- 老配置载入后，页面应尽量映射到最接近的可见模式

## Runtime Behavior

### Address Generation

`register_one()` 仍继续传递：

- `prefix`
- `domain`

但 `IMAPMailClient.generate_email()` 改为按服务商配置工作：

#### Mode: `inbox`

返回真实收件箱地址，例如：

- `sanviewyouzi@gmail.com`

#### Mode: `plus_alias`

返回：

- `local+random@gmail.com`

仍复用现有 Gmail/QQ 别名逻辑。

#### Mode: `random_local_part`

返回：

- `random@registration_domain`

例如：

- `a8k3v1mx@dfghdfghd.xyz`

随机本地名优先使用注册流程传入的 `prefix`；若为空则退回内部随机生成。

### Mail Polling

`poll_code(email)` 的核心策略保持不变：

- 始终登录真实收件箱
- 始终按传入的“注册邮箱地址”过滤 `To:` / `Delivered-To:`

因此对于域名转发场景：

- 登录的是 `sanviewyouzi@gmail.com`
- 过滤目标是 `random@dfghdfghd.xyz`

这样可以避免多个并发注册任务抢错验证码。

## Error Handling

### Configuration Errors

以下情况应在保存或运行前明确报错：

- `address_mode="random_local_part"` 但 `registration_domain` 为空
- `registration_domain` 格式明显非法
- `auth_type` 与账户凭据不匹配导致无法登录

### Logging

增加可诊断日志：

- 当前 IMAP 服务商名称
- 当前真实收件箱账号
- 当前生成的注册邮箱
- 当前 `To:` 过滤目标
- 某封邮件因 `To:` 不匹配被跳过的原因

### Non-goals

本次不处理：

- Cloudflare Email Routing 配置自动探测
- 对转发是否为 catch-all 的在线验证
- Microsoft/Outlook 路线与 IMAP 路线统一

## File Impact

### Backend

- `src/mail/imap.py`
  增加新模式、兼容旧字段、使用 `registration_domain`

- `src/webui/server.py`
  如批量导入或默认结构需要补字段，保持新旧格式兼容

- `src/settings_db.py`
  若需要默认 provider 结构，补充默认字段说明

### Frontend

- `webui_frontend/src/pages/Settings.jsx`
  IMAP 服务商 UI 增加新字段，替换旧“别名模式”表达

## Backward Compatibility

必须保证以下旧场景不变：

1. 固定 Gmail/QQ IMAP 收件箱
2. Gmail/QQ `+alias`
3. 普通 IMAP 邮箱固定地址收件
4. 现有 `mail_provider=imap:0` / `imap:0:1` 的 provider 选择规则

## Verification Plan

### Unit-Level

验证 `generate_email()` 在三种模式下的输出：

- `inbox`
- `plus_alias`
- `random_local_part`

### Filtering-Level

验证同一收件箱中存在多封不同 `To:` 目标邮件时，只返回当前注册邮箱对应的验证码。

### Compatibility-Level

验证旧配置未设置新字段时，行为与当前版本一致。

### Integration-Level

使用代表性配置验证：

- 收件箱：`sanviewyouzi@gmail.com`
- 模式：`random_local_part`
- 注册域名：`dfghdfghd.xyz`
- provider：`imap:0`

预期：

- 生成地址形如 `random@dfghdfghd.xyz`
- 程序仍登录 Gmail IMAP 收件箱
- 验证码按 `To:` 精确匹配

## Usage After Implementation

用户最终配置方式：

1. 在 `IMAP 服务商 1` 中填写 Gmail 收件箱登录信息
2. 将 `注册邮箱模式` 设为 `自定义域名随机地址`
3. 将 `注册域名` 设为 `dfghdfghd.xyz`
4. 将全局 `mail_provider` 设为 `imap:0`

这样：

- `imap:0` 仍表示“使用第 1 个 IMAP 服务商”
- 该服务商内部同时管理收件箱和注册地址生成策略

## Scope Boundary

本 spec 仅覆盖：

- IMAP 服务商数据结构扩展
- IMAP WebUI 配置项扩展
- 注册地址生成逻辑扩展
- 现有 `To:` 过滤逻辑在域名转发场景下的继续使用

不覆盖：

- 新 provider 类型
- 外部邮件路由平台 API 集成
- 多域名自动轮换策略
