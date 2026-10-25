from pathlib import Path
from datetime import datetime
import json
import sys
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from .omr import WIDTH, HEIGHT, MARKERS, SIGNATURE, FORM, answer_centers, id_centers


def report_asset(name):
    base=Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    return base/'assets'/name


def fonts():
    if 'Korean' not in pdfmetrics.getRegisteredFontNames():
        regular=Path('C:/Windows/Fonts/malgun.ttf')
        if regular.exists():
            pdfmetrics.registerFont(TTFont('Korean',str(regular)))
            pdfmetrics.registerFont(TTFont('KoreanBold',str(regular.with_name('malgunbd.ttf'))))
        else:
            raise RuntimeError('한글 PDF 출력에 Windows 맑은 고딕 글꼴이 필요합니다.')
    if 'KoreanHand' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('KoreanHand',str(report_asset('NanumDaeGwangYuRi.ttf'))))


def sheet_pdf(path, count=60, title='OMR 답안지', code=None, answers=None):
    fonts()
    c=canvas.Canvas(str(path),pagesize=A4)
    c.setTitle(title)
    c.scale(A4[0]/WIDTH,A4[1]/HEIGHT)
    def text(x,y,s,size=22):
        c.setFont('Korean',size);c.drawString(x,HEIGHT-y,str(s))
    for x,y in MARKERS:
        c.rect(float(x)-12,HEIGHT-float(y)-12,24,24,fill=1,stroke=0)
    for i,bit in enumerate(SIGNATURE):
        if bit:
            c.rect(180+i*24-7,HEIGHT-90-7,14,14,fill=1,stroke=0)
    form_title=title[:28]
    title_size=38
    while pdfmetrics.stringWidth(form_title,'Korean',title_size)>600 and title_size>18:
        title_size-=1
    text(110,170,form_title,title_size)
    text(110,225,'이름: ___________________',24)
    text(110,275,'학원 / 반: ___________________',24)
    text(110,325,'시험 / 회차: __________________',24)
    text(110,385,'학생번호는 왼쪽부터 6자리 모두 마킹하세요.',18)
    text(110,420,'예: 123 → 000123   |   한 문항에 한 개만 마킹',18)
    text(790,143,'학생번호 (6자리)',22)
    for pos in range(6):
        for digit,(x,y) in enumerate(id_centers(pos)):
            if pos==0:
                text(x-35,y+6,str(digit),17)
            c.setLineWidth(1.6);c.circle(x,HEIGHT-y,12,stroke=1,fill=0)
            if code is not None and int(str(code).zfill(6)[pos])==digit:
                c.circle(x,HEIGHT-y,10,fill=1,stroke=0)
    for col in range(3):
        for choice in range(5):
            text(179+col*365+choice*43,524,str(choice+1),19)
    for q in range(count):
        centers=answer_centers(q)
        text(centers[0][0]-65,centers[0][1]+7,str(q+1),22)
        for k,(x,y) in enumerate(centers):
            c.setLineWidth(1.5);c.circle(x,HEIGHT-y,12,fill=0,stroke=1)
            if answers and answers[q]==k+1:
                c.circle(x,HEIGHT-y,10,fill=1,stroke=0)
    text(110,1580,'검은색으로 진하게 채워 주세요. 네 모서리의 검은 사각형을 가리지 마세요.',18)
    text(110,1620,'A4 · 실제 크기(100%) 인쇄 · 150~300dpi 스캔 권장',18)
    text(110,1660,FORM+'  |  '+str(count)+'문항  |  만두OMR',17)
    c.showPage();c.save()


def report_pdf(path, store, scan_ids):
    fonts()
    results={r['id']:r for r in store.results()}
    if not scan_ids or any(i not in results for i in scan_ids):
        raise ValueError('확정된 성적만 성적표로 출력할 수 있습니다.')
    if any(results[i]['config'].get('form')=='math30' for i in scan_ids):
        from tempfile import TemporaryDirectory
        import pypdfium2 as pdfium
        from .report_math import report_math
        from .history import results as historical_results
        from .report_insights import cohort_error_rates
        question_rates=cohort_error_rates(list(results.values())+historical_results(store,for_report=True))
        with TemporaryDirectory(prefix='LocalOMR_report_') as folder:
            merged=pdfium.PdfDocument.new()
            try:
                for index,sid in enumerate(scan_ids):
                    part=Path(folder)/f'{index}.pdf'
                    if results[sid]['config'].get('form')=='math30':report_math(part,store,sid,question_rates=question_rates)
                    else:report_pdf(part,store,[sid])
                    doc=pdfium.PdfDocument(str(part))
                    try:merged.import_pages(doc)
                    finally:doc.close()
                merged.save(str(path))
            finally:merged.close()
        return
    c=canvas.Canvas(str(path),pagesize=A4)
    c.setTitle('만두OMR 성적표')
    w,h=A4
    def line(x,y,s,size=10,bold=False,color='#263549'):
        c.setFillColor(color);c.setFont('KoreanBold' if bold else 'Korean',size);c.drawString(x,y,str(s))
    def fit(x,y,s,max_width,size=10,bold=False,color='#263549'):
        font='KoreanBold' if bold else 'Korean'
        while size>6 and pdfmetrics.stringWidth(str(s),font,size)>max_width:
            size-=.5
        s=str(s)
        if pdfmetrics.stringWidth(s,font,size)>max_width:
            while s and pdfmetrics.stringWidth(s+'...',font,size)>max_width:
                s=s[:-1]
            s+='...'
        line(x,y,s,size,bold,color)
    for sid in scan_ids:
        r=results[sid];s=r['snapshot']
        average,n=store.averages(r['exam_id'])
        class_avg,cn=store.averages(r['exam_id'],s['class_id'])
        c.setFillColor('#173C4B');c.rect(0,h-155,w,155,fill=1,stroke=0)
        line(42,h-48,'LEARNING RECORD',9,False,'#C8E5DE')
        line(42,h-84,'개인 성적표',25,True,'#FFFFFF')
        fit(330,h-48,store.report_name(),220,11,True,'#FFFFFF')
        fit(42,h-119,r['title'],510,12,True,'#FFFFFF')
        fit(42,h-142,f"{r['subject']} · {r['series']} · {r['round']}회 · {r['day']}",510,9,False,'#C8E5DE')
        fit(42,h-193,f"{s['name']}  |  {s['code']}  |  {s.get('school') or '—'}  |  {r['day']}",510,12,True)
        fit(42,h-215,f"학원: {s['academy']}  |  반: {s['classroom']}",510,10)
        c.setFillColor('#F1F6F5');c.roundRect(42,h-326,w-84,88,10,fill=1,stroke=0)
        line(58,h-261,'취득 점수 / 만점',9)
        line(58,h-299,f"{r['score']/100:g} / {r['maximum']/100:g}",24,True,'#126B61')
        line(257,h-261,'반 평균',9)
        line(257,h-297,f'{class_avg:.2f}',21,True)
        line(416,h-261,'시험 평균',9)
        line(416,h-297,f'{average:.2f}',21,True)
        line(42,h-355,'오답 문항',12,True)
        wrong=r['wrong']
        for row_index in range(0,max(1,len(wrong)),15):
            line(42,h-378-(row_index//15)*19,', '.join(map(str,wrong[row_index:row_index+15])) if wrong else '오답 없음',11)
        line(42,h-478,'같은 시리즈 · 과목의 최근 기록',12,True)
        history=[v for v in store.results(student_id=r['student_id']) if v['series']==r['series'] and v['subject']==r['subject'] and (v['day'],v['exam_id'])<=(r['day'],r['exam_id'])][:6][::-1]
        y=h-505
        c.setStrokeColor('#D8E2E5');c.line(42,y+11,w-42,y+11)
        for x,txt in [(42,'응시일자'),(151,'회차'),(254,'점수 / 만점'),(402,'100점 환산')]:
            line(x,y,txt,9,True)
        for v in history:
            y-=25
            line(42,y,v['day'],10)
            fit(151,y,v['round'],90,10)
            line(254,y,f"{v['score']/100:g} / {v['maximum']/100:g}",10)
            line(402,y,f"{v['score']/v['maximum']*100:.1f}",10)
            c.setStrokeColor('#E6ECEE');c.line(42,y-9,w-42,y-9)
        line(42,103,'평균은 해당 시험의 확정 성적만 포함합니다. 결시·검수 대기·대체된 답안은 제외됩니다.',8)
        line(42,85,'과거 기록은 현재 정답 기준입니다. 정답 변경 후 다시 출력하면 결과가 달라질 수 있습니다.',8)
        c.setStrokeColor('#D8E2E5');c.line(42,65,w-42,65)
        first='수능과 가장 가까운 수학! '
        line(42,45,first,8)
        line(42+pdfmetrics.stringWidth(first,'Korean',8),45,'수학은 양지용입니다.',8,True)
        c.showPage()
    c.save()
