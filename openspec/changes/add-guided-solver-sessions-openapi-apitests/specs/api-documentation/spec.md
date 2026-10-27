# Spec Delta

## Purpose

提供与真实服务行为同步的 OpenAPI 描述和浏览器可用的 Swagger 页面，使开发者能够确认鉴权、路径、参数、响应与错误码，并直接试调主要接口。

## ADDED Requirements

### Requirement: 服务提供可读取的 OpenAPI 合同
系统 MUST 提供公开可访问的 OpenAPI 3 描述，覆盖登录、登出、当前用户、资料与检索、现有单次问答、技能、会话和消息流主要接口。每个操作 MUST 描述路径、方法、参数或请求体、成功与常见失败响应及是否需要登录；受保护操作 MUST 声明 HTTP Bearer 安全方案，流式操作 MUST 描述事件顺序、类型与载荷。

#### Scenario: 读取 API 描述
- **WHEN** 未登录客户端读取 OpenAPI 描述
- **THEN** 得到可解析的 OpenAPI 文档，且登录接口标为公开、受保护接口标为 Bearer 鉴权

#### Scenario: 对照实际错误
- **WHEN** 开发者查看跨班资源、无效输入或无令牌的接口定义
- **THEN** 文档列出与实际响应一致的状态码和错误结构

### Requirement: 浏览器可打开并试调 Swagger 页面
系统 MUST 提供浏览器可访问的 Swagger UI 页面，能加载同源 OpenAPI 描述、输入 Bearer Token，并试调登录、检索、技能和会话等主要接口。页面资源 MUST 可由部署环境可靠提供，不依赖运行时访问不受控的第三方 CDN。

#### Scenario: 浏览器试调
- **WHEN** 用户打开 Swagger 页面，登录获取令牌并授权
- **THEN** 可从页面提交受保护请求并查看实际响应

#### Scenario: 未授权试调
- **WHEN** 用户未提供 Bearer Token 试调受保护接口
- **THEN** 页面显示服务返回的 HTTP 401 错误
