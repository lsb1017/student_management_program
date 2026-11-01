"""주간지 성적표: 1.0.6 모의고사(2쪽) 양식을 기본으로 아래 항목만 바꿈(ARCHITECTURE.md).

추가: 미니테스트 점수, 과제 완성도(A/B/C) — 기존 등급컷 표 자리.
제외: 등급, 추정 백분위, 등급컷, 클리닉 우선순위, 오답률 순위(오답률 상위 분석).
변경: "공통/선택과목 점수" → "단원별 점수(대수/미적/확통)" — 문항별 과목(영역) 기준.
Works for any question count of a user-defined form.
"""
from collections import defaultdict,OrderedDict
from math import ceil
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from core.report_charts import radar
from core.report_insights import review_questions
from core.classification import unit_name,course_for,detail_for
from core.reports import fonts
from core.cheer import draw_cheer


def course_label(result,q):
    raw=str((result.get('areas') or [''])[q] if q<len(result.get('areas') or []) else '').strip()
    return raw or course_for(result,q) or '미입력'


def weekly_history(store,result):
    rows=[x for x in store.results(student_id=result['student_id']) if x['series']==result['series'] and x['subject']==result['subject']]
    rows=[x for x in rows if (x['day'],x['exam_id'])<=(result['day'],result['exam_id'])]
    return sorted(rows,key=lambda x:(x['day'],x['exam_id']),reverse=True)[:6][::-1]


def weekly_report(path,store,sid):
    from academy.services.entries import entry_for
    fonts();r=next(x for x in store.results() if x['id']==sid);student=r['snapshot']
    all_rows=store.results(r['exam_id']);n=len(r['key'])
    c=canvas.Canvas(str(path),pagesize=A4);c.setTitle('주간지 성적표 · '+student['name'])
    navy='#203752';teal='#DF654F';red='#B43C30';gray='#606A74'

    def txt(x,y,value,size=9,bold=False,color=navy,width=None,center=False,right=False):
        value=str(value)
        if value in ('—','–','―','-'):value='-';size=min(size,7);bold=False
        font='KoreanBold' if bold else 'Korean'
        if width:
            while size>5 and pdfmetrics.stringWidth(value,font,size)>width:size-=.3
            while value and pdfmetrics.stringWidth(value,font,size)>width:value=value[:-2]+'…' if len(value)>2 else ''
        c.setFillColor(color);c.setFont(font,size)
        (c.drawRightString if right else c.drawCentredString if center else c.drawString)(x,y,value)

    def section(y,title,sub=''):
        c.setFillColor(teal);c.rect(30,y-2,3,12,fill=1,stroke=0);txt(40,y,title,11,True)
        if sub:txt(40+pdfmetrics.stringWidth(title,'KoreanBold',11)+8,y,sub,7,color=gray,width=290)

    def grid(x,y,width,headers,rows,widths=None,rowh=19,wrong=None,highlight=(),headerh=None,fontsize=8):
        widths=widths or [1]*len(headers);unit=width/sum(widths);ws=[a*unit for a in widths]
        headerh=rowh if headerh is None else headerh;height=headerh+rowh*len(rows)
        c.saveState();outline=c.beginPath();outline.roundRect(x,y-height,width,height,4);c.clipPath(outline,stroke=0,fill=0)
        c.setFillColor(navy);c.rect(x,y-headerh,width,headerh,fill=1,stroke=0)
        xx=x
        for title,ww in zip(headers,ws):txt(xx+ww/2,y-headerh/2-2.8,title,min(8,fontsize),True,'#FFFFFF',ww-7,center=True);xx+=ww
        for i,row in enumerate(rows):
            yy=y-headerh-rowh*(i+1)
            c.setFillColor('#EED6CE' if wrong and i in wrong else '#F2F5F8' if i%2==0 else '#FFFFFF');c.rect(x,yy,width,rowh,fill=1,stroke=0)
            if wrong and i in wrong:c.setFillColor(red);c.rect(x,yy,2,rowh,fill=1,stroke=0)
            xx=x
            for j,(val,ww) in enumerate(zip(row,ws)):
                emphasized=j in highlight or bool(wrong and i in wrong)
                txt(xx+ww/2,yy+rowh/2-fontsize*.35,val,fontsize,emphasized,red if emphasized else navy,ww-7,center=True);xx+=ww
        c.setStrokeColor('#A8B4C1');c.setLineWidth(.55)
        for i in range(len(rows)):c.line(x,y-headerh-rowh*i,x+width,y-headerh-rowh*i)
        c.restoreState();c.saveState();c.setStrokeColor('#8D9AA9');c.setLineWidth(.55)
        c.roundRect(x,y-height,width,height,4,fill=0,stroke=1);c.restoreState()
        return y-height

    def footer(page):
        c.setStrokeColor('#DEE5E9');c.line(30,45,565,45)
        message='수능과 가장 가까운 수학! 수학은 양지용입니다.'
        c.setStrokeColor(teal);c.line(30,45,30+pdfmetrics.stringWidth(message,'Korean',8),45)
        txt(30,29,message,8,color=navy);txt(510,29,f'{page} / 2',7,color=gray)

    def error_rate(q):
        return sum(x['answers'][q]!=x['key'][q] for x in all_rows)/len(all_rows)*100

    # ---- page 1 ----
    txt(30,791,r['title'],13,True,color='#30363B',width=270)
    txt(565,762,store.report_name(),8.5,True,width=175,right=True)
    draw_cheer(c,r,store,y=784,height=50)
    c.setLineWidth(.7);c.setStrokeColor('#E0E4E8');c.line(30,777,565,777)
    c.setLineWidth(1.2);c.setStrokeColor(teal);c.line(30,777,30+min(270,pdfmetrics.stringWidth(r['title'],'KoreanBold',13)),777)
    section(743,'학생정보')
    grid(30,735,535,['학생명','학번','학교','시험일','학원명','반'],[[student['name'],student['code'],student.get('school','') or '—',r['day'],student['academy'],student['classroom']]],[.8,.75,1.1,1.05,1.6,1.3],22)
    courses=OrderedDict()
    for q in range(n):
        label=course_label(r,q);earned=r['points'][q] if r['answers'][q]==r['key'][q] else 0
        courses.setdefault(label,0);courses[label]+=earned
    by_course=' / '.join(f'{name} {value/100:g}점' for name,value in courses.items())
    class_avg,_=store.averages(r['exam_id'],student.get('class_id'));exam_avg,_=store.averages(r['exam_id'])
    section(667,'성적')
    grid(30,659,535,['원점수 / 만점','반 평균','시험 평균','단원별 점수'],[[f"{r['score']/100:g} / {r['maximum']/100:g}",f'{class_avg:.1f}' if class_avg is not None else '—',f'{exam_avg:.1f}',by_course]],[1,.8,.8,2.4],22,highlight=(0,3))
    entry=entry_for(store,student.get('class_id'),r['day'],r['student_id'])
    mini='미제출' if not entry or entry['mini_score'] is None else f"{entry['mini_score']:g}"
    work=entry['homework'] if entry else '미제출'
    grid(30,605,535,['미니테스트 점수','과제 완성도'],[[mini,work]],[1,1],18,highlight=(0,1))
    section(547,'단원별 성취도 분석')
    groups=defaultdict(list)
    for q,topic in enumerate(r['topics']):groups[unit_name(topic) or '미분류'].append(q)
    items=list(groups.items())
    if len(items)>9:items=items[:8]+[('기타 단원 합계',[q for _,qs in items[8:] for q in qs])]
    areas=[];personal=[];means=[]
    for name,qs in items:
        possible=sum(r['points'][q] for q in qs)
        scores=[sum(x['points'][q] for q in qs if x['answers'][q]==x['key'][q])/100 for x in all_rows]
        mine=sum(r['points'][q] for q in qs if r['answers'][q]==r['key'][q])/100
        top=sorted(scores,reverse=True)[:max(1,ceil(len(scores)*.3))]
        ratio=mine/(possible/100)*100 if possible else 0;mean=sum(scores)/len(scores)
        areas.append([name,f'{possible/100:g}',f'{mine:g}',f'{ratio:.1f}%',f'{mean:.1f}',f'{sum(top)/len(top):.1f}'])
        personal.append(ratio);means.append(mean/(possible/100)*100 if possible else 0)
    chart_height=max(160,(len(areas)+1)*20)
    grid(30,539,300,['단원','배점','득점','성취도','평균','상위30%'],areas,[2.2,.7,.7,1,.8,1],20,highlight=(2,3),fontsize=9)
    radar(c,341,539-chart_height+12,224,chart_height-18,[name for name,_ in items],personal,means)
    history=weekly_history(store,r)
    bottom=539-chart_height-4
    priority=review_questions(r,all_rows,history)
    title=f'이번 시험의 우선 복습 {len(priority)}문항' if priority else '이번 시험은 모든 문항을 맞혔어요!'
    section(bottom-22,title,'(정답률이 높은데 내가 틀린 문항)' if priority else '')
    rows=[[i+1,x['q']+1,unit_name(r['topics'][x['q']]),course_label(r,x['q']),detail_for(r,x['q']) or '—',f"{x['points']/100:g}",f"{x['correct_rate']:.1f}%"] for i,x in enumerate(priority)]
    if not rows:rows=[['—','—','—','오답이 없습니다.','—','—','—']]
    grid(30,bottom-30,535,['순위','문항','단원','과목','학습내용','배점','정답률'],rows,[.45,.45,1.3,1.3,2.1,.6,.9],24,highlight=(1,),headerh=19,fontsize=9)
    footer(1);c.showPage()

    # ---- page 2 ----
    txt(30,795,'누적 성적과 학습 분석',12,True,color='#30363B')
    c.setStrokeColor('#DEE5E9');c.line(30,783,565,783)
    section(765,'회차별 성적')
    rows=[]
    for index,x in enumerate(history,1):
        av=store.averages(x['exam_id'])[0] or 0
        rows.append([index,x['title'],x['day'],f"{x['score']/100:g} / {x['maximum']/100:g}",f"{x['score']/x['maximum']*100:.1f}",f'{av:.1f}'])
    grid(30,757,535,['순번','시험명','응시일자','점수 / 만점','100점 환산','시험 평균'],rows,[.4,2.6,1.1,1,.9,.8],20,highlight=(3,))
    section(596,'성적 추이 분석')
    c.saveState();c.setStrokeColor('#8D9AA9');c.setLineWidth(.6);c.roundRect(30,457,535,131,6,fill=0,stroke=1);c.restoreState()
    gx,gy,gw,gh=65,504,470,61
    for tick in range(0,101,20):
        y=gy+gh*tick/100;c.setStrokeColor('#DFE6EA');c.line(gx,y,gx+gw,y);txt(35,y-3,tick,7,color=gray)
    coords=[]
    for i,x in enumerate(history):
        xx=gx+gw*(i+.5)/max(1,len(history));mean=(store.averages(x['exam_id'])[0] or 0)*10000/x['maximum']
        c.setFillColor('#D5DCE6');c.setStrokeColor('#8190A3');c.setLineWidth(.5);c.rect(xx-18,gy,36,gh*mean/100,fill=1,stroke=1)
        yy=gy+gh*x['score']/x['maximum'];coords.append((xx,yy));txt(xx,gy-12,x['round']+'회',8,width=47,center=True);txt(xx,yy+7,f"{x['score']/x['maximum']*100:.1f}",8,color=red,center=True)
        txt(xx,gy-23,x['day'],7,color=gray,center=True)
    c.setStrokeColor(red);c.setLineWidth(1.7)
    for (x,y),(xx,yy) in zip(coords,coords[1:]):c.line(x,y,xx,yy)
    for x,y in coords:c.setFillColor(red);c.circle(x,y,3,fill=1,stroke=0)
    c.setLineWidth(1);c.setStrokeColor(red);c.line(380,469,398,469);c.setFillColor(red);c.circle(389,469,2.5,fill=1,stroke=0);txt(404,466,'내 점수',8,True)
    c.setFillColor('#D5DCE6');c.setStrokeColor('#8190A3');c.rect(474,466,12,8,fill=1,stroke=1);txt(492,466,'평균 점수',8,True)
    section(439,'문항별 채점표')
    half=ceil(n/2);rowh=min(15,round(370/max(1,half),2));size=8 if rowh>=13 else 6.5
    for part in range(2):
        qs=list(range(part*half,min((part+1)*half,n)));rows=[];wrong=[]
        for i,q in enumerate(qs):
            a=r['answers'][q]
            rows.append([q+1,unit_name(r['topics'][q]),f"{r['points'][q]/100:g}",r['key'][q],'—' if a is None else '무효' if a<0 else a,f'{error_rate(q):.1f}%'])
            if a!=r['key'][q]:wrong.append(i)
        if rows:grid(30+part*273,431,262,['번호','단원','배점','정답','내 답','오답률'],rows,[.5,1.65,.55,.65,.65,.9],rowh,wrong,fontsize=size,headerh=15)
    footer(2);c.save()
