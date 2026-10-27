from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle

ROOT = Path('/Users/xiaoyuxiao/sspku_xyx/互联网/campusclaw')
OUT = ROOT / 'output/pdf/campusclaw_token_auth_knowledge_qa.pdf'
pdfmetrics.registerFont(TTFont('STHeitiEmbedded', '/System/Library/Fonts/STHeiti Medium.ttc', subfontIndex=0))

NAVY = colors.HexColor('#17324D')
BLUE = colors.HexColor('#276A95')
PALE = colors.HexColor('#EAF2F8')
INK = colors.HexColor('#263543')
LINE = colors.HexColor('#D9E3EA')

style = {
    'title': ParagraphStyle('title', fontName='STHeitiEmbedded', fontSize=20, leading=28,
                            textColor=NAVY, spaceAfter=8),
    'subtitle': ParagraphStyle('subtitle', fontName='STHeitiEmbedded', fontSize=10,
                               leading=16, textColor=BLUE, spaceAfter=20),
    'h1': ParagraphStyle('h1', fontName='STHeitiEmbedded', fontSize=13, leading=20,
                        textColor=NAVY, spaceBefore=15, spaceAfter=7, keepWithNext=1),
    'h2': ParagraphStyle('h2', fontName='STHeitiEmbedded', fontSize=10.5, leading=17,
                        textColor=BLUE, spaceBefore=9, spaceAfter=5, keepWithNext=1),
    'body': ParagraphStyle('body', fontName='STHeitiEmbedded', fontSize=9.5,
                          leading=16.5, textColor=INK, spaceAfter=7),
    'flow': ParagraphStyle('flow', fontName='STHeitiEmbedded', fontSize=9.5,
                          leading=17, textColor=NAVY),
}

def p(text, kind='body'):
    return Paragraph(escape(text), style[kind])

def flow(text):
    t = Table([[p(text, 'flow')]], colWidths=[170 * mm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), PALE),
        ('LINEBEFORE', (0, 0), (0, 0), 3, BLUE),
        ('LEFTPADDING', (0, 0), (-1, -1), 11),
        ('RIGHTPADDING', (0, 0), (-1, -1), 11),
        ('TOPPADDING', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
    ]))
    return t

def footer(canvas, doc):
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(LINE)
    canvas.line(20 * mm, 18 * mm, width - 20 * mm, 18 * mm)
    canvas.setFont('STHeitiEmbedded', 8)
    canvas.setFillColor(colors.HexColor('#607080'))
    canvas.drawRightString(width - 20 * mm, 13 * mm, str(doc.page))
    canvas.restoreState()

doc = BaseDocTemplate(str(OUT), pagesize=A4, leftMargin=20 * mm,
                      rightMargin=20 * mm, topMargin=25 * mm, bottomMargin=23 * mm,
                      title='基于 Token 的身份认证与知识库问答', author='CampusClaw')
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
              leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
doc.addPageTemplates(PageTemplate(id='main', frames=frame, onPage=footer))

story = [
    p('基于 Token 的身份认证与知识库问答', 'title'),
    p('CampusClaw 实现方案', 'subtitle'),
    p('一、基于 Token 的身份认证', 'h1'),
    flow('用户名和密码 → 签发 JWT → 请求携带 Bearer Token → 校验 JWT 与数据库授权记录 → 加载当前用户 → 按角色和班级授权'),
    Spacer(1, 8),
    p('签发：app/routes.py 的 api_auth_token 校验用户名和密码，调用 app/auth.py 的 issue_access_token 生成短期 HS256 JWT；app/models.py 的 AuthToken 保存 jti、用户和过期时间。JWT 含 sub、jti、iat、nbf、exp、iss、aud 与 access 类型。'),
    p('校验：app/routes.py 的 load_logged_in_user 从 Authorization: Bearer 请求头取 Token；app/auth.py 的 authenticate_access_token 验证 JWT、未撤销的授权记录，并重新读取数据库 User。缺失或失效时返回 401。'),
    p('授权与登出：routes.py 的 teacher_required 根据数据库 role 限制上传；资料与问答用 g.user.class_id 限定本班。api_auth_logout 撤销当前 Token；app/static/js/auth.js 将 Token 保存在当前标签页的 sessionStorage，并为 API 请求添加 Bearer 请求头。'),
    p('二、基于知识库的问答', 'h1'),
    flow('教师上传资料 → 保存正文并分块 → 建立 SQLite FTS5 索引 → 按当前用户班级召回相关片段 → 发送编号来源给智谱模型 → 校验引用并返回回答'),
    Spacer(1, 8),
    p('建库：app/models.py 的 Material.create_from_upload 保存 UTF-8 资料和 KnowledgeEntry；app/retrieval.py 的 chunk_text 按行切分，replace_entry_index 将 KnowledgeChunk 写入 SQLite FTS5 trigram 索引。'),
    p('检索：app/qa.py 的 retrieve_answer_sources 提取词项、结合 FTS 与正文匹配排序、去重，最多取 4 个来源。查询用数据库用户的 class_id 同时约束分块和资料；无命中时 answer_question 直接返回本地提示。'),
    p('生成：routes.py 的 api_knowledge_answer 调用 qa.py 的 answer_question；build_messages 将问题和编号来源组成提示词，ZhipuClient 使用用户本次提交的 API Key 调用智谱。Key 不持久化。'),
    p('返回：qa.py 的 parse_answer 检查回答内容和 [N] 引用编号。结果包含答案与来源；routes.py 的资料详情和下载接口会再次校验当前用户的班级权限。'),
]

doc.build(story)
print(OUT)
