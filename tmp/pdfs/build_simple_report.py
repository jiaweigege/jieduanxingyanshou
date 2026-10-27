from pathlib import Path
from xml.sax.saxutils import escape
import textwrap
import re
import keyword
import tokenize
import io
from reportlab.platypus import SimpleDocTemplate, Paragraph, XPreformatted, Spacer, PageBreak, Table, TableStyle
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/pdf/campusclaw-verification-report.pdf'
pdfmetrics.registerFont(TTFont('Chinese','/System/Library/Fonts/Supplemental/Arial Unicode.ttf'))
body=ParagraphStyle('body',fontName='Chinese',fontSize=10,leading=16,spaceAfter=8,wordWrap='CJK',textColor=colors.black)
title=ParagraphStyle('title',parent=body,fontSize=17,leading=24,spaceAfter=13)
heading=ParagraphStyle('heading',parent=body,fontSize=12,leading=19,spaceBefore=9,spaceAfter=6)
small=ParagraphStyle('small',parent=body,fontSize=8,leading=12,spaceAfter=5)
mono=ParagraphStyle('code',fontName='Courier',fontSize=8.2,leading=10.8,spaceAfter=0,leftIndent=0)
story=[]
def p(t,s=body): story.append(Paragraph(escape(t),s))
def h(t):p(t,heading)
TOKEN = re.compile(r'''(?P<string>(?:[fFrRbBuU]{0,2})(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'))|(?P<comment>\#.*)|(?P<number>\b\d+(?:\.\d+)?\b)|(?P<name>\b[A-Za-z_]\w*\b)''')
def highlight(code):
    parts=[]
    end=0
    for m in TOKEN.finditer(code):
        parts.append(escape(code[end:m.start()]))
        text=m.group()
        color=None
        if m.lastgroup=='string':color='#A31515'
        elif m.lastgroup=='comment':color='#008000'
        elif m.lastgroup=='number':color='#098658'
        elif keyword.iskeyword(text):color='#0000CC'
        elif re.match(r'\s*\(',code[m.end():]):color='#795E26'
        elif text in {'str','dict','int','len','set','list','bytes'}:color='#267F99'
        token=escape(text)
        parts.append(f'<font color="{color}">{token}</font>' if color else token)
        end=m.end()
    parts.append(escape(code[end:]))
    return ''.join(parts)
def src(file,ranges):
    source=(ROOT/file).read_text()
    lines=source.splitlines()
    shades=[['#202124']*len(line) for line in lines]
    tokens=list(tokenize.generate_tokens(io.StringIO(source).readline))
    for i,t in enumerate(tokens):
        color=None
        if t.type==tokenize.STRING or tokenize.tok_name.get(t.type,'').startswith('FSTRING'):
            color='#A31515'
        elif t.type==tokenize.COMMENT:color='#008000'
        elif t.type==tokenize.NUMBER:color='#098658'
        elif t.type==tokenize.NAME:
            if t.string in {'True','False','None'}:color='#0000FF'
            elif keyword.iskeyword(t.string):color='#AF00DB'
            elif i+1<len(tokens) and tokens[i+1].string=='(':color='#795E26'
            elif t.string in {'str','dict','int','list','bytes'}:color='#267F99'
        if color:
            for row in range(t.start[0],t.end[0]+1):
                if row>len(lines):continue
                start=t.start[1] if row==t.start[0] else 0
                stop=t.end[1] if row==t.end[0] else len(lines[row-1])
                shades[row-1][start:stop]=[color]*(stop-start)
    def markup(chars,cs):
        parts=[]
        for i,ch in enumerate(chars):
            if i==0 or cs[i]!=cs[i-1]:
                if i:parts.append('</font>')
                parts.append(f'<font color="{cs[i]}">')
            parts.append(escape(ch))
        if chars:parts.append('</font>')
        return ''.join(parts)
    p(f'相关源码：{file}',small)
    chunks=[]
    for a,b in ranges:
        part=textwrap.dedent('\n'.join(lines[a-1:b]))
        wrapped=[]
        for index,line in enumerate(part.splitlines()):
            offset=len(lines[a-1+index])-len(line)
            cs=shades[a-1+index][offset:]
            pieces=textwrap.wrap(line,width=94,replace_whitespace=False,drop_whitespace=False) or ['']
            start=0
            for piece in pieces:
                wrapped.append(markup(piece,cs[start:start+len(piece)]))
                start+=len(piece)
        chunks.append('\n'.join(wrapped))
    box=Table([[XPreformatted('\n\n'.join(chunks),mono)]],colWidths=[491.28])
    box.setStyle(TableStyle([
        ('BOX',(0,0),(-1,-1),0.5,colors.black),
        ('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#FAFAFA')),
        ('LEFTPADDING',(0,0),(-1,-1),7),
        ('RIGHTPADDING',(0,0),(-1,-1),7),
        ('TOPPADDING',(0,0),(-1,-1),6),
        ('BOTTOMPADDING',(0,0),(-1,-1),6),
    ]))
    story.append(box)
    story.append(Spacer(1,7))

p('CampusClaw 项目介绍与功能验证报告',title)
h('一、项目简介')
p('CampusClaw 是面向教学场景的 AI 应用平台，基于 Flask、SQLAlchemy 和 SQLite 构建。教师和学生可以在各自班级内管理、检索资料，并使用通用对话、知识问答和解题引导三个内置应用。平台还支持提示词模板、内置及上传 Skill，以及 HTTP/MCP 工具接入。')
h('二、功能验证')
h('1. LLM 请求、返回内容及提示词模板')
src('app/platform_runtime.py',[(79,83),(87,88),(93,93),(118,120),(123,123),(139,140)])
src('app/platform_runtime.py',[(215,217),(256,257)])
p('每次调用时，后端会发送模型名称 model、消息内容 messages，以及 stream=false、temperature 和 max_tokens 等生成参数；启用工具后，还会附上 tools 和 tool_choice。提示词模板会先完成变量替换，再随消息一起发送，API Key 则放在 Authorization 请求头中。返回内容主要包括回答正文 content、工具调用 tool_calls、结束原因 finish_reason，以及接口提供的用量 usage。')

story.append(PageBreak())
h('2. 绑定知识库后是否发送全部内容')
src('app/platform_runtime.py',[(240,244),(254,255)])
src('app/qa.py',[(160,165),(168,173)])
p('绑定知识库后，系统不会直接把全部资料交给模型，而是根据本轮问题检索相关片段，再将片段的编号、标题和正文加入请求。默认最多选取 4 段，正文总长度不超过 6000 字符。')
h('3. 绑定 Skill 后是否发送全部内容')
src('app/platform_runtime.py',[(219,229),(297,297),(320,320)])
p('绑定 Skill 并不意味着每次都发送整个技能包。系统会先提供名称、描述等目录信息；用户选中技能或模型调用 load_skill 时，再加入主指令正文。参考文件则通过 read_skill_reference 按需读取，不会一次性全部传入。')

story.append(PageBreak())
h('4. 执行具体 Skill 的逻辑')
src('app/platform_runtime.py',[(300,303),(324,326),(349,349),(388,388)])
p('技能选定后，后端会加载主指令，由模型据此回答，或提出读取参考文件、调用工具的请求。后端完成权限和参数校验后执行相应操作，再把结果交回模型，继续生成答案。这里的 Skill 以指令为主，不直接运行 Python 或 Shell 脚本。')
h('5. MCP 集成后发送给 LLM 的参数')
src('app/platform_runtime.py',[(236,237),(239,239),(81,82),(365,365),(397,398)])
src('app/platform_tools.py',[(321,321)])
p('接入 MCP 后，请求会在基础参数之外增加 tools 和 tool_choice="auto"，向模型提供工具的类型、名称、用途和参数格式。模型通过 tool_calls 提出调用请求后，由后端执行 MCP 工具，再将调用记录和结果加入下一次请求；结果消息使用 role="tool"，并通过 tool_call_id 与对应调用关联。MCP 服务地址和认证配置由后端使用，不会自动传给模型。')

def footer(c,d):
    c.setFillColor(colors.black);c.setFont('Chinese',8)
    c.drawCentredString(297.64,27,str(d.page))

doc=SimpleDocTemplate(str(OUT),pagesize=(595.28,841.89),leftMargin=52,rightMargin=52,topMargin=35,bottomMargin=43,title='CampusClaw 项目介绍与功能验证报告',author='CampusClaw 项目')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
print(OUT)
