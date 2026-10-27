from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, KeepTogether
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_LEFT

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/pdf/campusclaw-verification-report.pdf'
OUT.parent.mkdir(parents=True, exist_ok=True)
pdfmetrics.registerFont(TTFont('CN', '/System/Library/Fonts/Supplemental/Arial Unicode.ttf'))
INK = colors.HexColor('#183047')
TEAL = colors.HexColor('#087E8B')
MUTED = colors.HexColor('#526579')
styles = {
 'title': ParagraphStyle('title', fontName='CN', fontSize=25, leading=35, textColor=INK, spaceAfter=16),
 'h': ParagraphStyle('h', fontName='CN', fontSize=17, leading=25, textColor=INK, spaceAfter=15),
 'sub': ParagraphStyle('sub', fontName='CN', fontSize=11.5, leading=19, textColor=TEAL, spaceBefore=12, spaceAfter=6),
 'body': ParagraphStyle('body', fontName='CN', fontSize=10.5, leading=18, textColor=INK, spaceAfter=9, wordWrap='CJK'),
 'small': ParagraphStyle('small', fontName='CN', fontSize=8.5, leading=14, textColor=MUTED, spaceAfter=6, wordWrap='CJK'),
 'code': ParagraphStyle('code', fontName='CN', fontSize=8.4, leading=13, textColor=INK, leftIndent=10, rightIndent=8, backColor=colors.HexColor('#F1F5F8'), spaceBefore=4, spaceAfter=10, wordWrap='CJK'),
}
story=[]
def p(text, style='body'):
    story.append(Paragraph(escape(text).replace('\n','<br/>'), styles[style]))
def h(text): p(text,'sub')
def code(text): p(text,'code')
def page(kicker, title):
    if story: story.append(PageBreak())
    p(kicker,'small'); p(title,'h')
def refs(text): p('代码依据：'+text,'small')
def table(rows, widths):
    data=[[Paragraph(escape(str(c)),styles['small']) for c in row] for row in rows]
    t=Table(data,colWidths=widths,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E6F1F2')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),6),('LINEBELOW',(0,0),(-1,-1),0.4,colors.HexColor('#DDE5EC'))]))
    story.append(t);story.append(Spacer(1,10))

p('CAMPUSCLAW  /  技术验证报告','small')
p('个人 AI 应用平台\n项目介绍与功能验证','title')
p('验证日期：2026 年 10 月 27 日  |  验证方式：源代码审查 + 隔离自动化测试','small')
h('一、项目简要介绍')
p('CampusClaw 是基于 Flask、SQLAlchemy 与 SQLite 的教学资料及 AI 应用平台，面向教师和学生提供按班级隔离的资料管理、知识检索与智能辅助。前端使用 HTML、CSS 和 JavaScript，模型接口采用智谱兼容的 Chat Completions 格式，外部工具支持 HTTP 与 MCP 接入。')
table([['建设要求','当前实现'],['多个内置 AI 应用','通用对话、知识问答、解题引导'],['提示词模板','版本化模板、变量替换、应用绑定与发布'],['知识库检索','命名知识库、资料分块、SQLite FTS5 检索与来源引用'],['内置与上传 Skill','内置“解题引导”“资料摘要”；支持 SKILL.md 或受限 ZIP 上传'],['外部工具与 MCP','工具发现、版本化定义、参数校验、调用与结果回填']], [128,355])
h('二、验证范围与证据等级')
p('主要范围为 /apps 平台及 app/platform_* 模块。通过阅读从上下文组装到网络发送的代码，并运行五项专用测试及相关回归测试，核对传输边界上的实际序列化请求。测试使用临时数据库、测试账号与模拟 LLM/MCP 响应，不消耗真实 API 配额，不操作当前业务数据。')
p('证据边界：代码与模拟测试能证明参数构造和执行分支；不能证明真实模型一定选择正确工具，也不能替代真实 MCP 服务的连通性验证。用户此前反馈普通对话返回“测试成功”，仅作为人工观察记录，不作为本次独立采集的接口证据。','small')
refs('README.md；app/platform_resources.py:235-262；tests/conftest.py:12-42。文件路径均相对于项目根目录。')

page('验证项 01','每次对话的 LLM 参数与返回内容')
p('结论：基础请求包含 model、messages、stream、temperature、max_tokens；存在工具时增加 tools 与 tool_choice。提示词模板会在变量渲染后一起发送。')
h('请求构造与真实发送位置')
code('POST  配置项 ZHIPU_API_URL\nAuthorization: Bearer <本次用户 API Key>\nContent-Type: application/json\nAccept: application/json\n\n{\n  "model": "<应用发布配置的模型>",\n  "messages": [\n    {"role": "system", "content": "<平台规则及应用约束>"},\n    {"role": "user", "content": "<模板、上下文与本轮问题>"}\n  ],\n  "stream": false,\n  "temperature": 0.1,\n  "max_tokens": 512\n}')
p('以上为结构示意，0.1 与 512 为未另行配置时的应用默认值，不代表对用户刚才调用的抓包结果。默认接口地址为 https://open.bigmodel.cn/api/paas/v4/chat/completions。请求 JSON 先序列化为 UTF-8 字节，再由 httpx 通过 content=body 发出；API Key 位于请求头，不进入消息正文。','small')
h('提示词与对话上下文')
p('prepare() 读取已发布应用绑定的模板版本，render_template_version() 替换声明变量，将结果写入 <application_template> 块。本轮问题位于 <question> 块；可选知识片段、Skill 信息也在该 user 消息中。模板不是只传 ID，也不是写入 system 消息。')
p('每条用户消息独立组装上下文，不自动重放此前的聊天记录。同一条消息内部发生工具调用时，会继续携带该调用链的 assistant 和 tool 消息。')
h('返回内容与核验结果')
p('服务商原始响应为 JSON；后端读取 choices[0].message.content、tool_calls、finish_reason 及可选 usage。最终页面答案可能去除 <think> 内容并执行引用等校验，因此不等同于原始响应全文。测试返回“可见答案”和 usage.total_tokens=22，确认其被正确解析；这些是模拟值。')
refs('app/platform_runtime.py:55-145、213-257、347-398；app/platform_resources.py:82-90；config.py:43-45。')
p('测试证据：test_validation_1_actual_request_template_response_and_trace。捕获发送字节，核对五个基础字段、模板变量替换结果、响应正文与 usage，并确认追踪中不泄露测试 Key。','small')

page('验证项 02','知识库是否每次全量传递')
p('结论：不是整库注入。每轮根据用户问题，在当前班级及绑定知识库的资料范围内检索，选出相关片段后加入 LLM 上下文。')
h('代码执行过程')
p('1. 根据应用的 knowledge_base_ids 查询关联 material_ids，限制可检索资料。\n2. 提取问题关键词，结合全文检索得分和关键词匹配权重排序。\n3. 去除重叠片段，默认最多选取 4 段。\n4. 默认片段正文总预算为 6000 字符，必要时截断片段。\n5. 将来源编号、资料标题及片段正文放入 <knowledge_source> 块；若整体输入超预算，继续移除排名较低的片段。')
h('边界与例外')
p('知识问答、解题引导应用未命中资料时，本地返回“本班知识库中没有相关资料。”，不会调用 LLM。通用对话即使没有知识片段也可以继续调用模型。')
p('若知识库很小且全部内容恰好被命中，发送片段可能覆盖全库，这不等同于系统采用全量发送策略。当前检索具有关系候选 200、全文检索候选 80 的上限，不能据此宣称大库完整召回或语义向量检索。')
h('验证证据')
table([['检查点','已核对结果'],['资料范围限制','查询同时限制班级与绑定资料集合'],['LLM 上下文','仅循环写入检索所得 sources，不遍历整库拼接正文'],['跨班隔离','专用测试断言其他班级内容不进入模型请求'],['无命中处理','专用测试确认 generated=false，且没有新增模型调用']], [128,355])
refs('app/platform_runtime.py:240-265、344-346；app/qa.py:15-19、122-198；config.py:51-52。')
p('测试证据：test_validation_2_knowledge_only_selected_sources_and_no_hit。专用测试覆盖选中来源、跨班排除、无命中零调用；片段数量和预算上限另由源码核对。','small')

page('验证项 03 / 04','Skill 的传递内容与执行逻辑')
h('验证项 03：绑定是否意味着每次传入完整 Skill？')
p('结论：不意味着。平台采用渐进加载；仅绑定时发送目录摘要，明确选择或模型请求加载后，才发送该版本主指令正文。参考文件另行按需读取。')
table([['状态','LLM 实际获得的内容'],['仅绑定、未选择','skill_catalog：ID、名称、描述、版本、摘要哈希'],['用户显式选择','首次请求额外带 active_skill 主指令正文'],['模型调用 load_skill','主指令正文作为工具结果进入下一次请求'],['读取参考文件','read_skill_reference 仅返回指定文件；未读取文件不发送']], [128,355])
p('主指令是 SKILL.md 去除 YAML 元数据头后的正文，不是压缩包全部字节。必要正文超过输入预算会报错，不会无限扩大上下文。')
h('验证项 04：具体如何执行？')
p('执行链：选择 Skill → 校验绑定与权限 → 加载主指令 → LLM 按指令回答或提出工具调用 → 后端校验并执行 → 结果回填 LLM → 生成最终答案。模型自动选择时，会先调用 load_skill；参考资料由 read_skill_reference 读取。')
p('后端检查工具是否已绑定、参数是否符合 schema、Skill 的 allowed-tools 是否允许调用；allowed-tools 只能收窄能力，不能新增工具。默认每条消息最多 6 次模型调用、8 次工具调用，内部 Skill 工具也计数。')
p('能力限制：当前 Skill 是声明式指令与文本参考，不是任意代码执行环境。上传只接受 SKILL.md，以及 ZIP 内 references/ 下的 .md、.txt；Python、Shell 脚本不受支持。模型能否严格遵循技能指令，需要真实模型进一步验证。')
h('测试结果')
p('第 03 项测试用不同标记区分主指令、已读取参考和未读取参考，确认按阶段进入请求。第 04 项测试完成“目录 → load_skill → read_skill_reference → 最终回答”三次模拟模型调用，并核对执行事件顺序。')
refs('app/platform_runtime.py:218-230、287-331、347-398；app/platform_resources.py:109-166；config.py:11-14。')
p('测试证据：test_validation_3_bound_skill_summary_only_and_explicit_loading；test_validation_4_automatic_skill_execution_chain。','small')

page('验证项 05','MCP 集成后的请求参数与调用链')
p('结论：LLM 接收 function/tool 格式的工具定义，而不是 MCP 协议本身。平台负责 MCP 初始化、发现及调用；只有模型提出 tool_calls 时才真正执行工具。')
h('首次模型请求增加的参数')
code('{\n  "tools": [{\n    "type": "function",\n    "function": {\n      "name": "ext_<连接ID>_<定义ID>",\n      "description": "<工具描述>",\n      "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}\n    }\n  }],\n  "tool_choice": "auto"\n}')
p('此处为结构示意，实际 parameters 使用 MCP 工具的 inputSchema。只将应用绑定的工具提供给模型，不自动发送 MCP URL、认证配置或服务端代码；工具描述和 schema 本身仍会作为模型输入发送。','small')
h('工具执行与第二次模型请求')
p('模型返回 assistant.tool_calls 后，后端将外部工具别名映射为真实工具名，校验参数与权限，重新发现并核对工具定义版本，再通过 MCP SDK 执行 tools/call。当前使用 Streamable HTTP，并要求初始化协议版本匹配 2025-11-25。')
code('messages 继续追加：\n1. {"role": "assistant", "tool_calls": [<模型返回的调用>], ...}\n2. {"role": "tool", "tool_call_id": "<对应调用ID>",\n    "content": "<脱敏、限长后的工具结果 JSON 字符串>"}')
p('第二次请求仍带基础生成参数和工具定义。结果保留文本及可选 structuredContent；非文本块标记为不支持，不原样传入图片或音频。工具结果受长度限制，可能截断，因此并非无条件转发整个 MCP 响应。')
h('验证证据与前提')
p('专用测试验证：SDK 分页发现工具；只发送绑定工具 schema；不发送测试 MCP 地址或凭据；assistant 调用 ID 与 tool_call_id 对应；MCP 结果标记进入下一轮模型请求。实际 MCP 调用参数为真实工具名和模型给出的 arguments。')
p('前提：应用必须使用配置为支持工具调用的模型，MCP 地址须满足部署允许列表。仅配置 LLM API Key 不会自动满足这些条件，也不代表真实 MCP 服务已联通。')
refs('app/platform_runtime.py:232-239、365-398；app/platform_tools.py:194-226、306-344。')

page('验证记录与结论','测试证据、兼容边界与后续验收')
h('本次自动化验证')
p('执行环境：项目现有 .venv；pytest 使用临时数据库。五项专用测试执行结果为 5 passed in 1.67s。另运行平台运行时、工具、边界情况、资源、管理与模型六个测试模块，结果见下方记录。未安装新依赖，未访问真实 LLM/MCP。')
code('专用测试：\n1. test_validation_1_actual_request_template_response_and_trace\n2. test_validation_2_knowledge_only_selected_sources_and_no_hit\n3. test_validation_3_bound_skill_summary_only_and_explicit_loading\n4. test_validation_4_automatic_skill_execution_chain\n5. test_validation_5_mcp_sdk_discovery_call_and_llm_backfill')
p('回归命令：.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_platform_runtime.py tests/test_platform_tools.py tests/test_platform_edge_cases.py tests/test_platform_resources.py tests/test_platform_management.py tests/test_platform_models.py','small')
p('__REGRESSION_RESULT__')
h('重要兼容边界')
p('本报告主要结论针对新平台 /apps。旧 /api/solver/* 路径仍使用 SolverSkill.prompt，将教师提示词逐轮注入，并采用 stream=true 的流式接口；不能把新平台的 Skill 渐进加载和非流式参数结论套用到旧接口。')
p('当前默认模型能力配置为 tools=false；绑定 Skill 或外部工具时会校验并拒绝不支持工具的模型。默认外部工具允许地址列表为空，真实接入前需要配置。上述是部署前提，不应把隔离测试中的 tools=true 配置视为当前运行服务已完成配置。')
h('最终验证结论')
p('五项问题已完成代码层和隔离测试层核验：模板随请求发送；知识库按相关片段传递；Skill 渐进加载；技能由模型指令与后端受控工具循环协作执行；MCP 工具定义进入模型请求，执行结果通过 tool 消息回填。')
p('尚待真实环境验收：选择支持工具调用的实际模型，配置允许的 MCP 服务与凭据，验证真实知识问答质量、模型自主选择 Skill、参考文件读取以及 MCP 调用链。对“刚才那一次”的真实请求完整响应，本次未另行抓取，不编造请求值、用量或外部服务成功证据。')
refs('tests/test_platform_runtime.py:56-157；tests/test_platform_tools.py:75-119；app/platform_config.py:39-45；app/platform_resources.py:190-212；app/solver.py:107；app/solver_stream.py:60-90。')

def footer(c, doc):
    w,h=doc.pagesize
    c.setStrokeColor(colors.HexColor('#DDE5EC')); c.line(56,43,w-56,43)
    c.setFont('CN',8);c.setFillColor(MUTED)
    c.drawString(56,29,'CampusClaw | 项目与技术验证 | 2026-10-27')
    c.drawRightString(w-56,29,str(doc.page))
    c.setFillColor(TEAL);c.rect(0,h-9,w,9,fill=1,stroke=0)

if __name__=='__main__':
    import sys
    result=sys.argv[1] if len(sys.argv)>1 else '未提供回归结果'
    for item in story:
        if isinstance(item,Paragraph) and '__REGRESSION_RESULT__' in item.text:
            item.__init__('回归结果：'+escape(result), styles['body'])
    doc=SimpleDocTemplate(str(OUT),pagesize=(595.28,841.89),rightMargin=56,leftMargin=56,topMargin=43,bottomMargin=59,title='CampusClaw 项目介绍与功能验证报告',author='CampusClaw 项目',pageCompression=1)
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    print(OUT)
