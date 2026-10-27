# Spec Delta

## Purpose

定义用户名密码换取短期 Bearer Token、受保护请求验证、可靠撤销和浏览器端安全生命周期，使现有教师、学生、角色与班级隔离能力不再依赖 Session Cookie。

## ADDED Requirements

### Requirement: 有效凭据签发短期 Bearer Token
系统 MUST 提供公开的 Token 签发接口。有效的教师或学生用户名和密码 MUST 返回短期访问 Token、`Bearer` 类型和有效秒数；无效凭据 MUST 返回 HTTP 401 和稳定错误码，且不得返回 Token 或受保护用户信息。系统 MUST NOT 签发刷新 Token。

#### Scenario: 教师获取访问 Token
- **WHEN** 教师向 Token 签发接口提交有效用户名和密码
- **THEN** 系统返回 HTTP 200、访问 Token、`Bearer` 类型和正数有效秒数

#### Scenario: 学生获取访问 Token
- **WHEN** 学生向 Token 签发接口提交有效用户名和密码
- **THEN** 系统返回 HTTP 200、访问 Token、`Bearer` 类型和正数有效秒数

#### Scenario: 无效登录凭据
- **WHEN** 客户端提交不存在的用户名或错误密码
- **THEN** 系统返回 HTTP 401 和 `invalid_credentials`，且响应不包含 Token、角色、班级或其他受保护信息

### Requirement: 受保护 API 只接受 Authorization Bearer
所有受保护 API MUST 从 `Authorization: Bearer <token>` 请求头读取凭据，并 MUST NOT 将 Session Cookie、普通 Cookie、查询参数、请求正文或其他请求头中的 Token 视为有效认证。缺少 Bearer 凭据 MUST 返回 HTTP 401 和 `missing_token`；格式错误、签名无效、声明无效、过期或已撤销的 Token MUST 返回 HTTP 401 和 `invalid_token`，且所有失败响应 MUST NOT 包含受保护内容。

#### Scenario: 有效 Bearer 请求
- **WHEN** 客户端使用格式正确且有效的 Bearer Token 调用受保护 API
- **THEN** 系统以该 Token 对应用户处理请求

#### Scenario: 缺少 Authorization 请求头
- **WHEN** 客户端未携带 Bearer Token 调用受保护 API
- **THEN** 系统返回 HTTP 401 和 `missing_token`，且不返回受保护内容

#### Scenario: Bearer 格式错误
- **WHEN** 客户端提交空 Token、多个 Token 或不是 Bearer 方案的 Authorization 值
- **THEN** 系统返回 HTTP 401 和 `invalid_token`

#### Scenario: Session Cookie 不能代替 Bearer Token
- **WHEN** 客户端只携带旧 Session Cookie 调用受保护 API
- **THEN** 系统返回 HTTP 401，且不恢复旧 Session 身份

#### Scenario: 其他位置的 Token 被忽略
- **WHEN** 客户端通过 Cookie、查询参数或请求正文提交有效 Token，但没有有效 Authorization Bearer 请求头
- **THEN** 系统返回 HTTP 401，且不使用这些位置的 Token

### Requirement: Token 的密码学声明受到严格验证
访问 Token MUST 使用服务端固定的允许算法和独立的服务端签发密钥，并 MUST 包含且验证主体、唯一标识、签发时间、过期时间、签发者和受众。系统 MUST 拒绝算法不匹配、签名被篡改、声明缺失、签发者错误、受众错误、尚未生效或已过期的 Token。签发密钥 MUST 来自服务端环境，且不得出现在响应、HTML、JavaScript、日志或已提交源代码中。

#### Scenario: 篡改 Token
- **WHEN** 客户端修改已签发 Token 的头部、载荷或签名
- **THEN** 系统返回 HTTP 401 和 `invalid_token`

#### Scenario: Token 已过期
- **WHEN** 客户端使用超过有效期的 Token 调用受保护 API
- **THEN** 系统返回 HTTP 401 和 `invalid_token`

#### Scenario: Token 声明不完整或目标错误
- **WHEN** Token 缺少必需声明，或其签发者、受众、允许算法与服务端配置不符
- **THEN** 系统返回 HTTP 401 和 `invalid_token`

#### Scenario: 缺少 Token 签发密钥
- **WHEN** 应用启动时没有有效的服务端 Token 签发密钥
- **THEN** 应用以明确配置错误停止启动，而不是使用内置或随机的生产密钥

### Requirement: 当前数据库用户决定授权身份
系统 MUST 使用已验证 Token 的主体加载当前用户，并 MUST 使用数据库中的当前角色和 `class_id` 执行授权。Token 或客户端提交的角色、班级和用户资料 MUST NOT 覆盖数据库身份；用户不存在或已失效时，Token MUST 被拒绝。现有教师上传限制、班级隔离、检索范围、详情权限和文件权限 MUST 保持不变。

#### Scenario: Token 对应教师上传
- **WHEN** 有效教师 Token 调用资料上传 API
- **THEN** 系统按数据库中的教师角色和班级执行现有上传流程

#### Scenario: 学生 Token 尝试上传
- **WHEN** 有效学生 Token 调用资料上传 API
- **THEN** 系统返回 HTTP 403，且不创建文件、资料、知识条目或索引

#### Scenario: 客户端伪造其他班级
- **WHEN** A 班用户使用有效 Token 并在请求中提交 B 班标识
- **THEN** 系统仍只使用数据库中的 A 班身份，且不返回或修改 B 班数据

#### Scenario: Token 主体用户不存在
- **WHEN** Token 签发后其主体用户已不存在
- **THEN** 系统返回 HTTP 401 和 `invalid_token`

### Requirement: 登出立即撤销当前 Token
系统 MUST 提供需要 Bearer Token 的登出接口，并持久化撤销当前 Token。成功登出 MUST 返回成功响应；同一 Token 的后续请求 MUST 返回 HTTP 401 和 `invalid_token`。撤销一个 Token MUST NOT 撤销同一用户其他仍有效的 Token。

#### Scenario: 有效 Token 登出
- **WHEN** 客户端使用有效 Bearer Token 调用登出接口
- **THEN** 系统撤销该 Token 并返回成功响应

#### Scenario: 重用已登出 Token
- **WHEN** 客户端在成功登出后再次使用同一 Token
- **THEN** 系统返回 HTTP 401 和 `invalid_token`

#### Scenario: 单独撤销一个登录实例
- **WHEN** 同一用户持有两个有效 Token并撤销其中一个
- **THEN** 被撤销 Token 失效，另一个未被撤销且未过期的 Token 仍可使用

### Requirement: 浏览器只在当前标签页保存 Token
浏览器登录界面 MUST 通过 Token 签发接口登录，并 MUST 将访问 Token 保存到 `sessionStorage`。浏览器 MUST NOT 将 Token 写入 Cookie、`localStorage`、URL、DOM、可见页面内容或持久化缓存。关闭当前标签页后，Token MUST 不再由浏览器持久保存；Token 过期后用户 MUST 重新登录。

#### Scenario: 浏览器登录成功
- **WHEN** 用户在登录页提交有效凭据
- **THEN** 浏览器将访问 Token 保存到 `sessionStorage` 并导航到资料页

#### Scenario: 浏览器登录失败
- **WHEN** 用户在登录页提交无效凭据
- **THEN** 浏览器显示登录错误，且不保存 Token 或受保护用户数据

#### Scenario: Token 不进入持久化浏览器存储
- **WHEN** 浏览器完成登录并使用应用
- **THEN** Token 只存在于当前标签页的 `sessionStorage` 和请求 Authorization Header 中

### Requirement: 资料页外壳不包含受保护数据
`GET /materials` MUST 可以在不携带 Authorization Header 时返回应用外壳，但该 HTML MUST NOT 包含用户名、角色、班级、资料、知识正文、检索结果、上传权限或 Token。浏览器 MUST 在展示受保护状态前使用 Bearer Token 调用当前用户 API；Token 缺失或被拒绝时 MUST 清除本地认证状态并跳转到登录页。

#### Scenario: 未认证访问资料页外壳
- **WHEN** 浏览器直接请求 `/materials` 且无法在导航请求中携带 Bearer Header
- **THEN** 系统只返回无受保护数据的应用外壳

#### Scenario: 外壳建立已认证状态
- **WHEN** 资料页脚本发现当前标签页中有 Token
- **THEN** 脚本先用 Bearer Token 请求当前用户身份，再显示班级信息、教师控件或加载资料

#### Scenario: 外壳没有 Token
- **WHEN** 资料页脚本未发现 Token
- **THEN** 脚本在加载或显示任何受保护数据前跳转到登录页

#### Scenario: 外壳持有无效 Token
- **WHEN** 当前用户 API 返回 HTTP 401
- **THEN** 浏览器清除 Token 和已加载的受保护状态并跳转到登录页

### Requirement: 浏览器所有受保护操作携带 Bearer Token
浏览器 MUST 为当前用户、资料列表、知识检索、上传、详情、文件和登出请求添加同一个 Authorization Bearer Header。原始文件 MUST 通过带认证 Header 的请求获取并以受控 Blob 下载，不得通过无法附加 Header 的普通受保护链接访问。HTTP 403 MUST 保持为授权失败，不得被误当作登录失效。

#### Scenario: 加载资料与知识检索
- **WHEN** 已登录浏览器加载资料或执行知识检索
- **THEN** 对应 API 请求携带当前 Bearer Token，并继续保持服务端班级边界

#### Scenario: 教师上传资料
- **WHEN** 已登录教师通过页面上传资料
- **THEN** 上传请求携带 Bearer Token，并保持现有上传进度、事务和错误行为

#### Scenario: 下载受保护原始文件
- **WHEN** 用户点击授权资料的原始文件操作
- **THEN** 浏览器使用带 Bearer Header 的请求获取文件并触发下载

#### Scenario: 跨班访问被拒绝
- **WHEN** 有效 Token 请求其他班级的资料详情或文件
- **THEN** 系统与不存在的资料一样返回 HTTP 404，且浏览器不清除仍有效的 Token
