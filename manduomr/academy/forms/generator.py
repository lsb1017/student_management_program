"""M1 사용자 정의 OMR 양식: 문항 수·선택지 수·숫자형 답란·7자리 학번을 받아 양식 PDF와 판독 좌표를 만듦.

Geometry follows LocalOMR-60 (A4 at 150 dpi, four corner squares, bubble radius 12) so the
1.0.6 bubble thresholds apply unchanged. The signature strip starts with 1,1,0,1, which the
LocalOMR-60 reader (1,0,1,1,...) rejects, and then carries the 12-bit form number.
"""
from __future__ import annotations
import json
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from core.omr import WIDTH,HEIGHT,MARKERS
from core.reports import fonts

HEADER=(1,1,0,1)
FORM_BITS=12
TOP,BOTTOM=560,1545
COLUMN_X=(120,485,850)
CHOICE_DX,ROW_H=43,48
NUMERIC_DX,NUMERIC_DY,NUMERIC_H=40,27,30+10*27+12


def signature(number):
    if not 1<=number<2**FORM_BITS:raise ValueError('양식 번호가 범위를 벗어났습니다.')
    return list(HEADER)+[(number>>(FORM_BITS-1-i))&1 for i in range(FORM_BITS)]


def signature_centers():
    return [(180+i*24,90) for i in range(len(HEADER)+FORM_BITS)]


def id_centers(digits=7):
    return [[(800+pos*48,185+d*28) for d in range(10)] for pos in range(digits)]


def define_form(question_count,choice_count=5,numeric_questions=(),id_digits=7,number=1):
    """Lay questions out column by column. Raises ValueError when they do not fit one A4 page."""
    if not 1<=int(question_count)<=60:raise ValueError('문항 수는 1~60입니다.')
    if not 2<=int(choice_count)<=5:raise ValueError('선택지 수는 2~5개입니다.')
    if int(id_digits)!=7:raise ValueError('사용자 정의 양식의 학번 칸은 7자리입니다.')
    numeric=sorted({int(q) for q in numeric_questions})
    if any(not 1<=q<=question_count for q in numeric):raise ValueError('숫자형 문항 번호가 문항 수를 넘습니다.')
    questions=[];column=0;y=TOP
    for q in range(1,question_count+1):
        height=NUMERIC_H if q in numeric else ROW_H
        if y+height>BOTTOM:
            column+=1;y=TOP
            if column>=len(COLUMN_X):raise ValueError('한 장에 들어가지 않습니다. 문항 수 또는 숫자형 문항을 줄여 주세요.')
        x0=COLUMN_X[column]
        if q in numeric:
            places=[[(x0+80+p*NUMERIC_DX,y+30+d*NUMERIC_DY) for d in range(10)] for p in range(3)]
            questions.append({'q':q,'kind':'numeric','places':places,'label':(x0,y+14)})
        else:
            questions.append({'q':q,'kind':'choice','centers':[(x0+65+k*CHOICE_DX,y+12) for k in range(choice_count)],'label':(x0,y+19)})
        y+=height
    return {'version':1,'reader':'markers','size':[WIDTH,HEIGHT],'markers':MARKERS.tolist(),'signature':signature(number),
            'form_number':number,'choice_count':int(choice_count),'numeric':numeric,'question_count':int(question_count),
            'radius':8,'id':{'digits':7,'centers':id_centers(7)},'questions':questions}


def render_pdf(layout,path,title='OMR 답안지',code=None,answers=None):
    """Printable sheet. code/answers pre-fill bubbles (used by tests and sample sheets)."""
    fonts()
    c=canvas.Canvas(str(path),pagesize=A4);c.setTitle(title);c.scale(A4[0]/WIDTH,A4[1]/HEIGHT)
    def text(x,y,s,size=22):
        c.setFont('Korean',size);c.drawString(x,HEIGHT-y,str(s))
    def bubble(x,y,filled=False):
        c.setLineWidth(1.5);c.circle(x,HEIGHT-y,12,stroke=1,fill=0)
        if filled:c.circle(x,HEIGHT-y,10,fill=1,stroke=0)
    for x,y in layout['markers']:c.rect(float(x)-12,HEIGHT-float(y)-12,24,24,fill=1,stroke=0)
    for (x,y),bit in zip(signature_centers(),layout['signature']):
        if bit:c.rect(x-7,HEIGHT-y-7,14,14,fill=1,stroke=0)
    form_title=title[:28];size=38
    while pdfmetrics.stringWidth(form_title,'Korean',size)>600 and size>18:size-=1
    text(110,170,form_title,size)
    text(110,225,'이름: ___________________',24)
    text(110,275,'분반 / 날짜: _________________',24)
    text(110,330,'학번 7자리를 왼쪽부터 모두 마킹하세요.',18)
    text(110,365,'한 문항에 한 개만 마킹 · 숫자형은 백·십·일의 자리',18)
    text(790,143,'학번 (7자리)',22)
    for pos,column in enumerate(layout['id']['centers']):
        for digit,(x,y) in enumerate(column):
            if pos==0:text(x-35,y+6,str(digit),17)
            bubble(x,y,code is not None and int(str(code)[pos])==digit)
    for item in layout['questions']:
        q=item['q'];lx,ly=item['label'];text(lx,ly,str(q),22)
        value=answers[q-1] if answers and q-1<len(answers) else None
        if item['kind']=='choice':
            for k,(x,y) in enumerate(item['centers']):
                text(x-5,y-16,str(k+1),13);bubble(x,y,value==k+1)
        else:
            digits=str(value).rjust(3) if value is not None else '   '
            for p,column in enumerate(item['places']):
                text(column[0][0]-8,column[0][1]-18,'백십일'[p],13)
                for d,(x,y) in enumerate(column):
                    bubble(x,y,digits[p]!=' ' and int(digits[p])==d)
            for d in range(10):text(item['places'][0][d][0]-38,item['places'][0][d][1]+6,str(d),13)
    text(110,1590,'검은색으로 진하게 채워 주세요. 네 모서리의 검은 사각형을 가리지 마세요.',18)
    text(110,1630,'A4 · 실제 크기(100%) 인쇄 · 150~300dpi 스캔 권장',18)
    text(110,1670,f"사용자 정의 양식 #{layout['form_number']}  |  {layout['question_count']}문항  |  선택지 {layout['choice_count']}개",17)
    c.showPage();c.save()
    return path


def save_generated(store,name,question_count,choice_count=5,numeric_questions=(),pdf_dir=None):
    """Register a generated form: store the layout and PDF (file box) and return the form id."""
    from core.store import pack,now
    import tempfile
    from pathlib import Path
    name=str(name).strip()
    if not name or len(name)>60:raise ValueError('양식 이름을 1~60자로 입력하세요.')
    define_form(question_count,choice_count,numeric_questions)  # validate before writing
    with store.transaction():
        fid=store.db.execute("INSERT INTO omr_forms(name,question_count,choice_count,numeric_questions,id_digits,layout_json,source,created_at) VALUES(?,?,?,?,7,'{}','generated',?)",
                             (name,int(question_count),int(choice_count),pack(sorted({int(q) for q in numeric_questions})),now())).lastrowid
        layout=define_form(question_count,choice_count,numeric_questions,number=fid)
        with tempfile.TemporaryDirectory() as folder:
            pdf=render_pdf(layout,Path(folder)/'form.pdf',name)
            digest=store.put_file(pdf,'pdf')
        store.db.execute('UPDATE omr_forms SET layout_json=?,pdf_hash=? WHERE id=?',(json.dumps(layout),digest,fid))
        store.log('omr_form_created',fid,{'name':name,'question_count':question_count,'choice_count':choice_count,'numeric':sorted(numeric_questions)})
    return fid
