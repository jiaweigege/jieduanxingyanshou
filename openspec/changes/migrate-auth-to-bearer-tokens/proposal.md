# Proposal

## Why

当前应用使用 Flask Session Cookie 保存登录状态，API 调用依赖浏览器自动携带 Cookie，无法以明确、统一的凭据支持 Bearer 调用方。需要在保留教师/学生角色、班级隔离、资料权限和现有安全行为的前提下，将认证边界迁移为 `Authorization: Bearer` Token。

## What Changes

- 增加用户名和密码换取短期签名 JWT 的认证 API；Token 必须通过 `Authorization: Bearer <token>` 提交。
- Token 使用固定算法、服务端签发密钥、过期时间、签发时间、主体、受众、签发者和唯一标识，并由持久化授权记录支持可靠登出和撤销。
- 所有受保护 API 只接受有效 Bearer Token，从 Token 主体重新加载用户，并继续以数据库中的当前角色和 `class_id` 作为授权依据。
- 登录页通过 JavaScript 获取 Token，将其保存在当前标签页的 `sessionStorage`，并为资料、检索、上传、详情、下载、当前用户和登出请求统一添加 Bearer Header；不使用 Cookie、URL、`localStorage` 或页面 HTML 传递 Token。
- **BREAKING**：`POST /login` 的 Session 登录流程由 Token 签发 API 取代；原有 Session Cookie 不再授予页面或 API 权限。
- **BREAKING**：`/materials` 改为不包含用户或资料数据的公共应用外壳。浏览器加载后通过带 Bearer Header 的 `/api/me` 建立界面状态；缺少、过期或被撤销的 Token 会在任何受保护数据呈现前跳转到登录页。
- 原始文件下载改为经过认证的 `fetch`/Blob 下载，避免普通链接无法附加 Bearer Header 的问题。
- 增加 Token 签发、解析、过期、篡改、撤销、跨班级授权、前端存储和无敏感信息外壳的测试与运行文档。

## Capabilities

### New Capabilities

- `bearer-token-authentication`：定义 Bearer JWT 的签发、传输、校验、撤销、浏览器生命周期，以及 Token 身份与现有角色/班级授权边界的集成行为。

### Modified Capabilities

- 无。项目当前没有已归档的主规格；本变更以现有 Session 认证实现和未归档的 `class-knowledge` 规划为迁移基线。

## Impact

- 认证路由、请求前置处理、页面保护器、教师权限保护器和当前用户加载方式将发生变化。
- 登录页、资料页、所有受保护的 `fetch`/XMLHttpRequest 调用以及文件下载交互需要统一接入 Bearer Token。
- 用户数据之外将增加可撤销 Token 的持久化记录和相应数据库索引/清理流程。
- 配置和容器环境需要增加独立的 Token 签发密钥、签发者、受众与有效期；依赖中将增加受维护的 JWT 实现。
- 现有 Session 登录测试将替换为 Token 契约测试，同时保留密码哈希、教师上传、班级隔离、检索和来源访问的原有验收行为。
