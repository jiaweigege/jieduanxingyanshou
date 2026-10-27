from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageTemplate, Paragraph,
    Spacer, Table, TableStyle,
)


ROOT = Path('/Users/xiaoyuxiao/sspku_xyx/互联网/campusclaw')
OUTPUT = ROOT / 'output/pdf/campusclaw_token_auth_knowledge_qa.pdf'
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
pdfmetrics.registerFont(TTFont('STHeitiEmbedded', '/System/Library/Fonts/STHeiti Medium.ttc', subfontIndex=0))

NAVY = colors.HexColor('#17324D')
BLUE = colors.HexColor('#276A95')
PALE = colors.HexColor('#EAF2F8')
INK = colors.HexColor('#263543')
GRAY = colors.HexColor('#607080')
LINE = colors.HexColor('#D9E3EA')

styles = {
    'title': ParagraphStyle('title', fontName='STHeitiEmbedded', fontSize=22, leading=31,
                            textColor=NAVY, spaceAfter=10),
    'subtitle': ParagraphStyle('subtitle', fontName='STHeitiEmbedded', fontSize=10.5,
                               leading=17, textColor=GRAY, spaceAfter=22),
    'h1': ParagraphStyle('h1', fontName='STHeitiEmbedded', fontSize=14, leading=22,
                        textColor=NAVY, spaceBefore=16, spaceAfter=8, keepWithNext=1),
    'h2': ParagraphStyle('h2', fontName='STHeitiEmbedded', fontSize=11, leading=18,
                        textColor=BLUE, spaceBefore=10, spaceAfter=5, keepWithNext=1),
    'body': ParagraphStyle('body', fontName='STHeitiEmbedded', fontSize=9.3, leading=16,
                          textColor=INK, spaceAfter=6),
    'small': ParagraphStyle('small', fontName='STHeitiEmbedded', fontSize=8.2, leading=13,
                           textColor=INK, spaceAfter=4),
    'table': ParagraphStyle('table', fontName='STHeitiEmbedded', fontSize=8.5, leading=13,
                           textColor=INK),
    'tablehead': ParagraphStyle('tablehead', fontName='STHeitiEmbedded', fontSize=8.5,
                               leading=13, textColor=colors.white),
    'callout': ParagraphStyle('callout', fontName='STHeitiEmbedded', fontSize=10,
                             leading=18, textColor=NAVY),
}


def P(value, style='body'):
    return Paragraph(escape(value), styles[style])


def bullet(value):
    return P('•  ' + value)


def heading(value, level=1):
    return P(value, 'h1' if level == 1 else 'h2')


def table(rows, widths):
    data = [[P(str(cell), 'tablehead' if i == 0 else 'table') for cell in row]
            for i, row in enumerate(rows)]
    t = Table(data, colWidths=widths, hAlign='LEFT', repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), NAVY),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F6F9FB')]),
        ('LINEBELOW', (0, 0), (-1, 0), 0.6, NAVY),
        ('LINEBELOW', (0, 1), (-1, -1), 0.3, LINE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    return t


def callout(value):
    t = Table([[P(value, 'callout')]], colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), PALE),
        ('LINEBEFORE', (0, 0), (0, 0), 3, BLUE),
        ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
    ]))
    return t


def page(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setStrokeColor(LINE)
    canvas.setFont('STHeitiEmbedded', 8)
    canvas.setFillColor(GRAY)
    canvas.line(20 * mm, 18 * mm, w - 20 * mm, 18 * mm)
    canvas.drawRightString(w - 20 * mm, 13 * mm, str(doc.page))
    canvas.restoreState()


doc = BaseDocTemplate(str(OUTPUT), pagesize=A4, leftMargin=20 * mm,
                      rightMargin=20 * mm, topMargin=24 * mm, bottomMargin=23 * mm,
                      title='CampusClaw Token 身份认证与知识库问答实现方案',
                      author='CampusClaw')
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
              leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
doc.addPageTemplates(PageTemplate(id='main', frames=frame, onPage=page))

story = []
story += [P('基于 Token 的身份认证与知识库问答', 'title'),
          P('CampusClaw 现有实现方案', 'subtitle'),
          callout('系统采用短期 JWT + 数据库授权记录完成认证，以数据库用户的当前班级限定资料检索，再把少量带编号的本班来源交给智谱模型生成回答。'),
          Spacer(1, 12)]

story += [heading('1. 方案总览'),
          P('业务链路：用户名/密码 → 签发 Bearer Token → 请求时校验 JWT 与授权记录 → 加载当前用户 → 按 class_id 检索知识分块 → 构造来源上下文 → 智谱生成 → 校验引用并返回。'),
          P('核心原则：认证身份、教师角色和班级范围均由服务端决定。客户端提交的角色、班级、模型等字段不能改变授权与问答范围。'),
          heading('2. 基于 Token 的身份认证'),
          heading('2.1 签发与存储', 2),
          P('POST /api/auth/token 接收 JSON 用户名和密码。User.verify_password 使用密码哈希验证；无效凭据统一返回 401 invalid_credentials。成功时签发 HS256 JWT，同时在 auth_tokens 表新增以 jti 标识的授权记录，返回 access_token、token_type=Bearer 和 expires_in。默认有效期为 1800 秒。'),
          table([
              ['JWT 声明', '作用'],
              ['sub / jti', '用户 ID / 唯一授权编号；jti 对应数据库记录'],
              ['iat / nbf / exp', '签发、生效、过期时间'],
              ['iss / aud / type', '签发者、受众与 access 类型限制'],
          ], [42 * mm, 128 * mm]),
          Spacer(1, 7),
          P('浏览器将 Token 保存在当前标签页的 sessionStorage；auth.js 的 authenticatedFetch 为受保护请求添加 Authorization: Bearer 请求头。上传 XHR 也显式设置该请求头。'),
          heading('2.2 请求校验与授权', 2),
          P('受保护的 /api/* 请求统一经过 before_app_request：严格解析 Authorization；校验 JWT 签名、算法、必需声明、签发者、受众、类型及时间；再检查数据库中 jti 与 sub 匹配、未撤销且未过期，最后重新读取 User。缺少凭据返回 401 missing_token，失效凭据返回 401 invalid_token。'),
          P('业务授权只使用当前数据库 User.role 和 User.class_id。教师上传需要 is_teacher；资料列表、详情、下载和知识检索均限定到当前班级。有效身份访问其他班已有资料时返回 403；不存在的资料返回 404。'),
          heading('2.3 登出与边界', 2),
          P('POST /api/auth/logout 将当前授权记录标记 revoked_at，因此 JWT 即使尚未到期也会立即失效。前端同时清除 sessionStorage。系统目前没有 Refresh Token，过期后需重新登录。'),
          P('这是带服务端状态的 JWT 方案：JWT 提供签名与有效期校验，数据库授权记录提供撤销能力。sessionStorage 可被同源脚本读取，故仍需保持 HTML/Markdown 清洗和脚本来源控制。')]

story += [heading('3. 知识库构建与检索'),
          heading('3.1 上传、分块和索引', 2),
          P('教师上传 UTF-8 的 .txt 或 .md 文件（默认最多 10 MB）。原始文件保存到上传目录，数据库创建 Material 与 KnowledgeEntry；class_id 来自教师用户。正文按行切成目标约 1000 字、最大 1200 字的 KnowledgeChunk，相邻块重叠 2 行，并保存起止行号、正文指纹和稳定 chunk_id。'),
          P('SQLite FTS5 trigram 虚表 knowledge_fts 索引分块正文；knowledge_chunks 保留权威正文和来源关系。上传时关系型数据与 FTS 索引在同一事务内更新，失败则回滚并移除刚写入的文件。现有资料可执行 backfill-knowledge-index 重建索引。'),
          heading('3.2 普通知识检索', 2),
          P('GET /api/knowledge/search?q=... 将查询转成 FTS 短语，使用 BM25 排序、snippet() 返回片段，并合并同一资料中高度重叠的命中。SQL 同时要求分块与资料的 class_id 等于当前数据库用户的 class_id，默认最多返回 20 条。'),
          heading('4. 基于知识库的问答'),
          heading('4.1 请求与来源召回', 2),
          P('POST /api/knowledge/answer 接收 question 与用户本次输入的智谱 api_key。问题先做空白归一化和长度校验；API Key 仅作为当前请求变量使用。'),
          P('问答检索从问题提取英文/数字词与中文 2、3 字片段，结合 FTS5 BM25 命中加分和关系型分块正文的词项匹配排序。FTS 候选最多 80 个，关系候选最多 200 个；去除高度重叠的块后最多选 4 个来源，默认上下文总长不超过 6000 字。'),
          P('所有候选 SQL 均限制 KnowledgeChunk.class_id 与 Material.class_id 为当前用户班级。传给模型的是完整的权威分块正文、资料标题和行号，而非 FTS 摘要。若没有相关来源，直接返回固定的本班未命中提示，不调用模型。'),
          heading('4.2 提示词与模型调用', 2),
          P('系统提示要求仅依据编号资料回答，将资料正文视为不可信数据；信息不足时说明，并以 [1]、[2] 等编号引用。用户问题和来源正文放在有边界的消息块中。智谱调用使用 HTTPS Chat Completions，默认 glm-4-flash、temperature=0.1、非流式、默认 512 输出 Token 和 20 秒超时，不声明工具调用。'),
          P('服务端只把个人 API Key 放入发往智谱的 Authorization Header；不写数据库、环境配置、页面响应、URL、Cookie 或浏览器持久存储。回答接口的所有响应设置 Cache-Control: no-store。'),
          heading('4.3 回答校验与呈现', 2),
          P('服务端要求上游响应具有合法 JSON 结构、非空且不过长的文本，以及至少一个处于当前来源编号范围内的 [N] 引用；不满足条件按 ai_unavailable 处理。前端以纯文本显示问题、回答和来源卡片，详情与原文件仍通过带 Bearer Header 的受保护接口读取。')]

story += [heading('5. 接口与错误约定'),
          table([
              ['接口', '用途 / 关键结果'],
              ['POST /api/auth/token', '凭据换取访问 Token；无效凭据 401'],
              ['POST /api/auth/logout', '撤销当前 Token'],
              ['GET /api/me', '返回当前数据库用户、角色与班级'],
              ['POST /api/materials/upload', '教师上传并建立知识索引'],
              ['GET /api/knowledge/search', '本班全文检索；索引不可用 503'],
              ['POST /api/knowledge/answer', '本班检索并调用智谱；无效问题/Key 400、上游拒绝 Key 422、检索或模型故障 503'],
              ['GET /api/materials/<id>/file', '再次执行班级权限检查后下载原件'],
          ], [65 * mm, 105 * mm]),
          heading('6. 现有限制与演进方向'),
          bullet('检索属于词项匹配，不具备向量语义检索；同义词、跨句改写和长问题的召回质量可能受限。'),
          bullet('关系候选查询按 chunk_id 排序后截取前 200 个；单班资料规模增长后可能漏掉后部相关分块。可改为先取 FTS 候选，再做受控补召回与重排。'),
          bullet('引用校验只验证编号存在，不能证明回答的每个事实都由来源支持；需要更强校验时可增加逐句证据核验。'),
          bullet('问答为同步上游调用，较慢请求会占用 Web Worker；高并发时可评估异步任务、限流与超时策略。'),
          bullet('目前无 Refresh Token、签名密钥轮换或多轮会话；这些能力应按实际部署与产品需求逐项增加。')]

doc.build(story)
print(OUTPUT)
