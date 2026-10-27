# AI 应用平台：五项调用验证

## 验证范围与复现

平台实现包括通用对话、知识问答、解题引导三个内置应用，版本化模板，命名知识库，内置/上传 Skill，HTTP/MCP 工具以及每轮调用追踪。以下结论由隔离数据库、实际序列化边界与模拟提供商/MCP 服务验证，未使用真实个人 Key，也未向真实模型或外部业务服务发送资料。

```bash
.venv/bin/python -m pytest tests/test_platform_config.py tests/test_platform_models.py tests/test_platform_resources.py tests/test_platform_runtime.py tests/test_platform_tools.py tests/test_platform_edge_cases.py tests/test_platform_management.py tests/test_platform_deployment.py -q
.venv/bin/python -m pytest -q
.venv/bin/python apitest/run_all.py
openspec validate add-ai-application-platform --strict
```

`tests/test_platform_runtime.py` 的共享 fixture 禁止真实 socket 连接。LLM 替身接收最终序列化字节；MCP 用例使用官方 SDK，HTTP 传输替身返回 JSON-RPC/JSON/SSE。独立 API 脚本报告位于 `apitest/reports/latest.html`。这些结果验证协议组装、权限和处理逻辑，不代表某个真实模型的回答质量或真实服务可用性。

## 1. 每次传给 LLM 的参数和返回是什么？模板是否发送？

平台在真正发送请求前记录 run_id、call_id、调用序号、URL、脱敏请求头、序列化 body、耗时及响应。绑定模板会先替换变量，渲染后的文本进入 user 消息；不是只发送模板 ID。

下例为模拟请求，`your-model`、问题和模板均为示意：

```json
{
  "model": "your-model",
  "messages": [
    {"role": "system", "content": "平台固定规则及应用约束"},
    {"role": "user", "content": "<application_template>\n请围绕 数据建模 回答。\n</application_template>\n<question>\n如何理解实体关系？\n</question>\n"}
  ],
  "stream": false,
  "temperature": 0.1,
  "max_tokens": 512
}
```

个人 Key 只在本次提供商请求的 Authorization 头使用。追踪显示 `[REDACTED]`，不会把它放入 messages。平台的普通调用使用非流式 JSON；原解题接口继续使用 `stream:true` 的 SSE。

模拟提供商返回示例：

```json
{
  "id": "fake-provider",
  "model": "fake",
  "choices": [{"message": {"role": "assistant", "content": "测试答案"}, "finish_reason": "stop"}],
  "usage": {"total_tokens": 22}
}
```

追踪分别显示原始脱敏响应、解析后的 content/tool_calls/finish_reason/usage 和用户可见结果。缺少 usage 标记为未提供。去除 think 文本、引用校验失败、畸形 JSON 和流中断不会被伪装成成功答案。消息历史用于查看，不自动重放；追踪记录 `history_replayed:false`。

验收依据：`test_validation_1_actual_request_template_response_and_trace` 深比较捕获的 body JSON 与追踪参数，断言模板哨兵确实进入请求，并核对返回文本和 usage。模板变量缺失、表达式或超限时零次模型调用。

## 2. 绑定知识库会发送全部内容吗？

不会因绑定而自动整库发送。系统在“当前用户授权资料 ∩ 已绑定知识库资料”中检索，再排序、去重、选片段。默认最多 4 段，正文总预算 6000 字符；模型整体输入预算还包含模板、来源标题、Skill、工具 schema 和问题。

每个来源含分块 ID、资料 ID、原始行号，以及实际发送的 `sent_start_line`、`sent_end_line`、`sent_start_char`、`sent_end_char` 和 truncated。知识问答和解题引导没有命中时本地返回资料不足，模型调用数为零；通用对话可在无资料时继续。索引失败返回 `retrieval_unavailable`。

小知识库全部相关且落在预算内时，发送内容可能恰好覆盖全库，这是检索命中结果，不是整库注入策略。现有检索仍有 FTS 80/关系候选 200 的上限，追踪显示该限制，不声称召回完整。

验收依据：`test_validation_2_knowledge_only_selected_sources_and_no_hit`、`test_retrieval_limits_before_ranking_and_reports_sent_range` 与 `test_large_bound_library_skips_unbound_candidates_before_top_k`。大库对照中，超过 200 个未绑定候选不能排挤被绑定资料；未绑定、跨班、未选择正文的哨兵均不进入请求。

## 3. 绑定 Skill 会每次发送整个包吗？

平台采用渐进加载：

| 阶段 | 本次模型输入 |
| --- | --- |
| 绑定但未选择/加载 | Skill 名称、用途、标识、版本和摘要 |
| 用户显式选择 | 首次请求带所选版本主指令正文 |
| 模型调用 load_skill | 平台校验后，以工具结果加入该版本主指令正文 |
| 模型请求某个参考文件 | 仅加入已加载 Skill 内指定的 references 文件 |
| 未请求的其他 Skill/文件 | 不自动发送 |

主指令可能在执行时完整发送，但不等于把整个包全部发送。版本在本轮固定，必需正文超预算会报错。上传支持 UTF-8 SKILL.md 或 ZIP，拒绝脚本、路径穿越、符号链接、重复路径和超限内容。

原 `/api/solver/*` 使用的是旧 `SolverSkill.prompt`，仍然每轮完整注入教师 prompt；这一兼容行为和平台 Skill 包机制有明确区分。

验收依据：`test_validation_3_bound_skill_summary_only_and_explicit_loading` 和 `test_validation_4_automatic_skill_execution_chain`。主指令、已读取参考、未读取参考各有不同哨兵，按阶段断言是否出现在出站请求中。

## 4. 执行具体 Skill 的逻辑是什么？

执行顺序是：选择 → 加载主指令 → 模型按指令回答或请求工具 → 平台校验并执行 → 把结果回填模型 → 生成最终答案。参考文件由单独的内部读取工具按需加载。

SKILL.md 是指令与参考资料，不作为本地程序执行。Skill 的 allowed-tools 只会进一步收窄应用已授予的能力；它不能新增工具、扩大班级范围或执行 shell。状态事件包含 skill_selected、skill_loaded、skill_running、skill_reference、skill_completed/skill_failed；工具事件带前一 LLM call_id、tool_call_id、参数、结果和失败原因。

默认每轮最多 6 次模型调用、8 次工具调用，内部 Skill 工具也计数；单工具默认 10 秒、整轮默认 120 秒。超限终止，不把未完成回答保存成成功。request_id 防止同一消息重复执行，进程中断后的运行不会自动重放。

验收依据：自动 Skill 链测试、版本固定测试、运行中禁用测试、预算测试、并发锁/中断恢复测试，以及跨用户/跨班权限测试。

## 5. 集成 MCP 后，每次 LLM 请求携带什么？

MCP 协议由平台客户端处理；模型收到的是提供商的 function/tool 调用格式。第一轮除 model/messages/stream/temperature/max_tokens 外，增加当前应用允许的 tools 和 `tool_choice:"auto"`。工具定义仅包含模型可用名称、说明及参数 schema，不自动附带 MCP 地址、鉴权字段或实现源码。

以下为模拟调用链的关键片段：

```json
{
  "tools": [{
    "type": "function",
    "function": {
      "name": "ext_1_1",
      "description": "查询授权资料",
      "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    }
  }],
  "tool_choice": "auto"
}
```

模型响应中的调用示例：

```json
{"role":"assistant","content":null,"tool_calls":[{"id":"call-1","type":"function","function":{"name":"ext_1_1","arguments":"{\"query\":\"question\"}"}}]}
```

平台检查当前绑定、工具名和参数 schema，再向 MCP 服务发送 tools/call，其中远端参数为：

```json
{"name":"lookup","arguments":{"query":"question"}}
```

下一次模型 messages 会保留上面助手的 tool_calls，并追加对应结果：

```json
{"role":"tool","tool_call_id":"call-1","content":"脱敏后的限量工具结果及截断元信息"}
```

多个调用逐一匹配 ID。远端 schema 变更使旧绑定失效；未允许工具和无效参数不会执行。MCP 错误、超时、未知结果不自动重放。文本与 JSON 可回填；二进制和资源链接不会自动抓取。默认每个工具结果最多回填 16000 字符，先脱敏再截断。

协议目标固定为 2025-11-25，依赖官方 SDK 1.30.0；使用其 [Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) 和 [Transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) 规范。验收依据：`test_validation_5_mcp_sdk_discovery_call_and_llm_backfill`、多调用匹配、分页发现、SSE、会话失效、协议不匹配和禁止重定向测试。

## 追踪访问、保留与容量

登录后从消息“本次调用”或最近调用进入详情。也可调用：

```text
GET    /api/conversation-runs
GET    /api/conversation-runs/{run_id}
GET    /api/conversation-runs/{run_id}/export
DELETE /api/conversation-runs/{run_id}
```

详细证据只向所有者返回，所有响应 no-store；默认 7 天到期。手动删除/过期清理删除证据但保留已保存的会话答案。Key、登录 Token、MCP/HTTP 凭据及 schema 声明的敏感参数在保存、展示和导出前脱敏，包括流事件中的跨片段回显。

默认请求、响应、事件证据分别有 256 KiB 的记录上限，标注 captured_bytes、total_bytes、truncated；中断时未知总长为 null。流原文超出脱敏缓冲时明确省略原文，不用片段假装完整证据。记录内容仍可能包含用户问题和资料，不等同于匿名数据。

## 部署、备份与回退

平台默认关闭。部署前备份 SQLite 与上传目录，再执行 `flask --app wsgi init-platform`。它仅创建新增表及幂等默认资源，不转换旧表。已有账户、资料与 solver 会话保持原接口可用。开关关闭时 `/apps` 不可访问，旧资料/问答/解题入口继续工作；新增数据保留供恢复。

通过 `cleanup-platform-traces` 物理清理过期证据；通过 `recover-platform-runs` 将超过整轮超时的遗留运行标为 interrupted 并释放锁，不重放工具调用。需要恢复数据库时使用部署前备份，并同时恢复匹配的上传资料。

`test_backup_initialize_toggle_and_rollback_on_database_copy` 在隔离 SQLite 副本演练备份、重复初始化、开关关闭/开启和备份恢复后的旧接口。此次未对现有 `instance/app.db` 执行初始化、清理或恢复。

## 已完成的检查与实际联调状态

- 本次执行结果：235 项 pytest 全部通过；9 个独立 API 用例全部通过；OpenSpec 严格校验、依赖一致性和平台 JavaScript 语法检查通过。
- 自动验证：五项核心验证、资源管理、原接口回归、脱敏、权限、超限及部署副本测试。
- 浏览器离线验证：教师登录、目录选择、创建会话、模拟回答、实际请求追踪、模板新建/绑定/发布、退出、学生登录及管理区隔离。临时服务已停止，临时数据已移除。
- 界面证据：`output/screenshots/ai-platform-trace.jpg`；离线示例可用 `.venv/bin/python scripts/platform_demo.py` 重新运行。
- 真实模型/MCP 服务联调：未进行；没有使用真实个人 Key，也没有验证外部业务服务的在线状态。
