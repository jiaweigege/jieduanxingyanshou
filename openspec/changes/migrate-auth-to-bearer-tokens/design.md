# Design

## Context

现有 Flask 应用在请求前从签名 Session Cookie 的 `user_id` 加载 `g.user`，`POST /login` 建立 Session，模板据此渲染用户、班级和教师控件。所有 `/api/` 路由共享这一隐式身份；前端 `fetch` 和 XMLHttpRequest 依赖同源 Cookie，文件则使用普通链接下载。参见 `proposal.md` 的迁移动机和 `specs/bearer-token-authentication/spec.md` 的行为契约。

Bearer Header 不会由浏览器自动添加到顶层页面导航或普通下载链接。因此不能在不引入 Cookie 的情况下继续让 `GET /materials` 同时承担服务端身份验证和受保护模板渲染；资料页必须成为无敏感数据外壳，所有身份与数据通过带 Header 的 API 获取。

## Goals / Non-Goals

**Goals：**

- 建立一个统一、可测试的 Bearer 认证入口，供浏览器和非浏览器 API 调用方使用。
- 在 Token 过期、篡改、撤销和用户状态变化时保持明确、无泄漏的失败行为。
- 保留数据库用户作为角色和班级归属的唯一授权来源，避免把可能过期的授权信息固化在 JWT 中。
- 保持现有资料、检索、上传、来源访问、Markdown 安全和班级隔离契约。
- 让登出立即使当前 Token 失效，同时不强制撤销该用户其他登录实例。

**Non-Goals：**

- OAuth、OIDC、第三方身份提供商、单点登录或 API Key。
- 刷新 Token、静默续期、长期“记住我”或跨标签页同步。
- 密码重置、多因素认证、设备管理或管理员撤销界面。
- 在 JWT 中缓存角色、班级或其他授权资料。
- 改变教师/学生角色模型或现有班级数据边界。

## Decisions

### 使用短期 HS256 JWT 和固定验证策略

引入受维护的 JWT 库，使用独立环境变量 `TOKEN_SIGNING_KEY` 和固定的 HS256 算法。配置还包括 `TOKEN_ISSUER`、`TOKEN_AUDIENCE` 和 `ACCESS_TOKEN_TTL_SECONDS`，默认有效期建议为 30 分钟。Token 包含 `sub`（用户 ID 字符串）、`jti`、`iat`、`nbf`、`exp`、`iss`、`aud` 和固定 `type=access`；验证时显式要求全部声明并固定允许算法，不能根据 Token 头部动态选择算法。

选择对称签名是因为当前系统是单个 Flask 服务，没有跨服务公钥分发需求。相比不透明随机 Token，JWT 能提供明确的过期和签发语义；相比 RSA/ECDSA，它减少课程规模部署的密钥管理复杂度。若未来出现独立签发者或多个验证服务，再迁移到非对称签名。

### 使用持久化 Token 授权记录支持即时撤销

新增 `auth_tokens` 表，保存唯一 `jti`、`user_id`、签发时间、过期时间和可空的撤销时间，并为用户、过期时间和撤销状态建立索引。签发 JWT 与创建授权记录在同一事务中完成。每次认证在验证 JWT 后查询对应记录，要求记录存在、用户一致、未撤销且未过期；随后从 `users` 表加载当前用户。

该设计让登出能够立即撤销当前 Token，也能防止仅凭一个由旧环境签发但没有本地授权记录的 JWT 获得访问。代价是每次请求多一次本地 SQLite 查询，但应用本来就需要加载用户，课程规模下可接受。定期或在签发时批量清理已过期授权记录，避免表无限增长。

评估过仅维护登出黑名单的方案；其写入更少，但无法区分本服务实际签发的 Token 与使用泄漏密钥伪造的记录，也使生命周期审计较弱，因此不采用。

### Token 只通过 Authorization Header 传输

认证解析器严格处理一个 `Authorization` 值，方案名称按 HTTP 规则大小写不敏感，但必须只有一个非空 Token。认证器不读取 Flask Session、Cookie、查询参数或正文。公共端点使用明确白名单：健康检查、静态资产、登录页、资料页外壳和 Token 签发接口；其他 API 默认要求 Bearer 身份。

认证成功后设置 `g.user` 和 `g.auth_token`，现有服务方法继续接收当前数据库用户。教师保护器仍检查 `g.user.is_teacher`，检索和资料服务仍从 `g.user.class_id` 确定范围。401 表示身份缺失或失效，403 继续表示有效身份缺少目标授权。

### 使用独立认证 API 并移除 Session 登录授权

新增 `POST /api/auth/token`，接受 JSON 用户名和密码并返回 `access_token`、`token_type` 和 `expires_in`。新增 `POST /api/auth/logout`，撤销当前授权记录。`GET /login` 只返回登录外壳；原有 `POST /login` Session 流程停止使用，并且 `/logout` 表单流程由 API 登出替代。

登录失败统一返回 `invalid_credentials`，不区分用户不存在与密码错误。Token 验证失败对外只给稳定错误码，不返回解析异常、声明值或密钥信息。

### 浏览器使用 sessionStorage 和统一请求封装

新增浏览器认证模块，封装 Token 读写、`Authorization` Header、401 处理和跳转。登录表单由 JavaScript 拦截，通过认证 API 获取 Token，写入 `sessionStorage` 后跳转 `/materials`。选择 `sessionStorage` 而不是 `localStorage`，使 Token 只在当前标签页生命周期内保存；两者都能被同源脚本读取，因此继续依赖现有 Markdown 清洗、禁止不可信脚本和不引入第三方脚本来控制 XSS 风险。

所有现有 `fetch` 改用统一的 `authenticatedFetch`。上传 XMLHttpRequest 显式设置 Authorization Header。文件操作不再直接导航受保护 URL，而是认证获取 Blob，从 `Content-Disposition` 提取或使用 API 返回的安全文件名，创建短期对象 URL 触发下载并立即释放。

不把 Token 放入 URL、DOM dataset、日志、错误消息或模板。登出先调用撤销 API，无论网络结果如何都清理当前标签页 Token 和页面内受保护数据，再跳转登录页。

### 资料页改为先认证再渲染的无敏感数据外壳

服务端渲染 `/materials` 时不再传入用户对象；用户名、班级标签、教师上传按钮和所有资料区域初始隐藏或为空。页面初始化首先检查 Token，然后调用 `/api/me`。成功后才填充身份标签、按角色启用教师控件并加载资料；失败则清空状态并跳转登录页。

这会替代原先“顶层 GET 由服务端根据 Session 重定向”的具体机制，但继续满足核心安全目标：未认证的 HTML 和首屏不含受保护信息，且任何数据请求都必须携带 Bearer Token。

### 配置、容器与测试时钟可控

应用启动时必须验证 `TOKEN_SIGNING_KEY` 非空且不是示例占位值，并验证有效期为正整数。Docker Compose 显式传入 Token 配置；`.env.example` 只提供需要替换的占位说明，不包含可用于部署的密钥。

Token 服务的时间来源通过一个小型可替换函数集中管理，使测试能够确定性覆盖签发、临界过期和清理，无需真实等待。生产代码仍使用 UTC 时间。

## Risks / Trade-offs

- [风险] `sessionStorage` 中的 Bearer Token 可被同源 XSS 读取。→ 继续使用严格 Markdown 清洗和文本 DOM 渲染，不加入第三方脚本；测试确保 Token 不进入 HTML/DOM/日志，并将有效期限制为短期。
- [风险] 每次请求查询 `auth_tokens` 增加数据库访问。→ 使用 `jti` 唯一索引和紧凑记录；用户加载与 Token 记录可在一个请求事务内完成。
- [风险] Token 到期会中断正在进行的上传或操作。→ 不提供隐式续期；前端对 401 清理状态并要求重新登录，避免隐藏的长期凭据。
- [风险] 公共 `/materials` 外壳可能被误认为已认证页面。→ HTML 不含任何用户或资料数据，受保护控件默认不可见，且初始化必须先完成 `/api/me`。
- [风险] 普通 `<a>` 下载无法携带 Header。→ 使用认证 fetch/Blob 下载，并覆盖大文件错误、401、403 和对象 URL 清理测试。
- [风险] 迁移会立即使现有 Session 登录失效。→ 在发布说明中明确要求所有用户重新登录，并在同一版本中同步部署登录页、外壳和 API 变更。

## Migration Plan

1. 增加 JWT 依赖、Token 配置校验、`auth_tokens` 表和索引，先在测试数据库验证初始化及现有用户数据不变。
2. 实现 Token 签发、严格验证、撤销与过期记录清理，并为现有授权服务提供 `g.user`。
3. 将所有受保护 API 和教师保护器切换到 Bearer 身份，完整运行班级隔离、上传、检索和来源权限测试。
4. 将登录页、资料页外壳、统一请求封装、上传和文件下载一次性切换到 Bearer 流程；禁止混合 Session/Bearer 过渡模式。
5. 更新 Docker 与运行文档，配置新的签发密钥并部署；现有用户数据和密码哈希无需迁移，但所有浏览器必须重新登录。
6. 回滚时恢复上一版本及其 Session 流程；若需要避免旧 Session Cookie 在回滚后重新生效，应同步轮换原 `SECRET_KEY`。`auth_tokens` 表可保留为无害数据，也可在确认回滚稳定后单独删除。
