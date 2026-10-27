# Tasks

## 1. Token 配置与持久化基础

- [x] 1.1 增加固定版本的 JWT 依赖及 `TOKEN_SIGNING_KEY`、`TOKEN_ISSUER`、`TOKEN_AUDIENCE`、`ACCESS_TOKEN_TTL_SECONDS` 配置校验；通过应用工厂测试验证缺少密钥、示例密钥和非正有效期会给出明确启动错误
- [x] 1.2 增加 `auth_tokens` 模型，包含唯一 jti、用户外键、签发时间、过期时间和撤销时间，并建立用户、过期和撤销查询索引；通过模型和全新 SQLite 初始化测试验证必填字段、外键、唯一性及索引
- [x] 1.3 增加过期授权记录清理操作并接入安全的签发或管理流程；通过混合有效、过期和已撤销记录测试验证只删除不再需要的过期记录

## 2. JWT 签发、验证与撤销服务

- [x] 2.1 实现可注入 UTC 时钟的短期访问 Token 签发服务，生成 sub、jti、iat、nbf、exp、iss、aud 和 access 类型声明，并在同一事务创建授权记录；通过确定性单元测试验证声明、有效期和记录一致
- [x] 2.2 实现严格的 Authorization Bearer 解析器，允许大小写不敏感的 Bearer 方案但拒绝空值、多个值、多段凭据和其他方案；通过表驱动测试覆盖合法和恶意 Header
- [x] 2.3 实现固定 HS256、签发者、受众、必需声明和时间验证，并将缺失声明、错误算法、篡改、尚未生效与过期统一映射为 invalid_token；通过构造 Token 测试验证不泄露解析异常或声明内容
- [x] 2.4 将验证后的 sub 和 jti 对应到未撤销授权记录及当前数据库用户，只从数据库读取角色与 class_id；通过用户删除、授权记录缺失、用户不匹配和伪造授权声明测试验证 Token 被拒绝或边界不变
- [x] 2.5 实现当前 Token 的持久化撤销，并验证同一用户两个 Token 中仅被撤销的 Token 失效、另一 Token 仍能使用

## 3. 认证 API 与服务端保护边界

- [x] 3.1 增加 `POST /api/auth/token`，校验 JSON 用户名密码并返回 access_token、Bearer 类型和 expires_in；通过教师、学生、未知用户、错误密码和缺失字段 API 测试验证 200/401 契约及 invalid_credentials 无信息泄漏
- [x] 3.2 重构请求认证入口，使用明确公共端点白名单，并让所有其他 API 只从 Authorization Bearer 加载 `g.user` 和当前授权记录；通过缺失 Token 与格式错误 Token 测试验证稳定的 missing_token/invalid_token 401 响应
- [x] 3.3 增加需要有效 Bearer Token 的 `POST /api/auth/logout` 并撤销当前授权记录；通过登出后重放测试验证立即返回 invalid_token
- [x] 3.4 将 `/api/me`、资料列表、知识检索、详情、文件和上传接口接入 Bearer 身份，同时保留教师 403、跨班级 403、查询班级覆盖防护及检索 400/503 行为；运行现有权限测试的 Bearer 版本验证无回归
- [x] 3.5 移除 `POST /login`、`/logout` 表单和 Flask Session 的授权作用；通过仅携带旧 Session Cookie、Cookie/查询参数/正文 Token 的测试验证所有路径均不能绕过 Bearer Header
- [x] 3.6 保持 `/health`、静态资源、`GET /login`、`GET /materials` 和根跳转可公开访问，并验证健康检查与应用外壳不会触发 Token 验证或返回用户数据

## 4. 浏览器 Bearer 生命周期与应用外壳

- [x] 4.1 增加独立浏览器认证模块，封装 sessionStorage Token 读写、Authorization Header 注入、401 清理和登录跳转；通过前端静态/行为测试验证不使用 Cookie、localStorage、URL 或 DOM 保存 Token
- [x] 4.2 将登录表单改为 JavaScript 调用 Token API，成功后保存当前标签页 Token 并导航资料页，失败时显示安全错误；通过界面测试验证成功、invalid_credentials、网络错误和重复提交状态
- [x] 4.3 将 base/materials 模板改为无用户数据的公共外壳，默认隐藏身份、教师上传和受保护区域，并在 `/api/me` 成功后按数据库角色填充界面；通过未认证 HTML 测试验证不包含用户名、角色、班级、资料、上传权限或 Token
- [x] 4.4 将资料列表、过滤、知识检索、详情和命令面板的数据请求统一改用 authenticatedFetch；通过界面与 API 集成测试验证每个请求携带相同 Bearer Token，401 会清空状态跳转而 403 不会误登出
- [x] 4.5 为上传 XMLHttpRequest 设置 Bearer Header，并保持上传进度、事务回滚和错误提示；通过教师上传、学生 403、Token 过期和索引失败测试验证原有行为
- [x] 4.6 将详情中的原始文件操作改为 Bearer fetch/Blob 下载，安全处理文件名并释放对象 URL；通过同班下载、跨班 403、401 和对象 URL 清理测试验证不再依赖普通受保护链接
- [x] 4.7 将退出按钮改为调用撤销 API，并在成功、401 或网络失败后清除当前标签页 Token及页面受保护状态；通过浏览器状态测试验证无法继续使用已撤销 Token

## 5. 安全、授权与端到端验证

- [x] 5.1 增加 JWT 安全测试矩阵，覆盖错误签名、alg 不匹配、缺少必需声明、错误 iss/aud/type、未来 nbf、过期 exp 和篡改载荷；验证全部返回统一 401 且日志与响应不含密钥或 Token
- [x] 5.2 增加双班级教师/学生 Bearer 测试数据，覆盖角色或 class_id 请求覆盖、其他班资料与分块标识、检索结果链接篡改；验证所有服务和 API 仍以数据库用户保持班级边界
- [x] 5.3 增加登录、当前用户、列表、上传、立即检索、详情、认证文件下载和登出的端到端测试；验证完整浏览器/API 流程无需 Session Cookie 且来源权限保持不变
- [x] 5.4 增加 Token 生命周期测试，覆盖同一用户多 Token、单独撤销、过期记录清理、用户删除和应用重启后的持久化撤销；验证没有刷新 Token或静默续期
- [x] 5.5 审计 HTML、JavaScript、错误响应和测试日志中的敏感信息；通过自动化断言验证 Token 与签发密钥不进入页面、URL、localStorage、Cookie、可见错误或日志

## 6. 运行文档与最终验收

- [x] 6.1 更新 `.env.example`、README 和登录/API 示例，记录 Token 密钥生成、有效期、Bearer curl、sessionStorage 风险、重新登录、撤销和故障排查；验证文档不包含可部署密钥或真实 Token
- [x] 6.2 更新 Docker Compose 传入 Token 配置，并验证 `docker compose config`、全新数据库初始化、容器健康检查及容器内 Token 登录流程成功
- [x] 6.3 运行完整 pytest 套件，验证原有资料、检索、上传、来源追踪、班级隔离、Markdown 和界面功能以及新增 Token 测试全部通过
- [x] 6.4 运行 `openspec validate migrate-auth-to-bearer-tokens --strict`，验证 proposal、spec、design 和 tasks 不存在严格校验错误
- [x] 6.5 一并审查认证实现、模板、前端、配置、测试和文档，验证交付仅迁移登录认证且未削弱原有教师权限、班级隔离、检索失败和文件保护契约
