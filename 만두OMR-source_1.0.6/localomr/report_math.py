from collections import defaultdict
from math import ceil
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from .examdata import ELECTIVES,percentile_label
from .report_charts import radar
from .report_insights import grade_target,clinic_priorities,review_questions
from .classification import course_for,unit_name,detail_for
from .report_insights import analysis_coverage


def report_history(store,result):
    from .history import results as historical_results
    rows=[x for x in store.results(student_id=result['student_id']) if x['series']==result['series'] and x['subject']==result['subject']]
    rows.extend(x for x in historical_results(store,result['student_id'],for_report=True) if x['subject']==result['subject'])
    rows=[x for x in rows if (x['day'],x['exam_id'])<=(result['day'],result['exam_id'])]
    return sorted(rows,key=lambda x:(x['day'],x['exam_id']),reverse=True)[:6][::-1]


def report_math(path,store,sid,question_rates=None):
    from .reports import fonts,report_asset
    fonts();r=next(x for x in store.results() if x['id']==sid);student=r['snapshot']
    all_rows=store.results(r['exam_id']);cohort=[x for x in all_rows if x['elective']==r['elective']]
    if question_rates is None:
        from .history import results as historical_results
        from .report_insights import cohort_error_rates
        question_rates=cohort_error_rates(store.results()+historical_results(store,for_report=True))
    c=canvas.Canvas(str(path),pagesize=A4);w,h=A4;c.setTitle('개인 성적표 · '+student['name'])
    navy='#203752';teal='#DF654F';red='#B43C30';gray='#606A74'

    def txt(x,y,value,size=9,bold=False,color=navy,width=None,center=False,font=None,right=False):
        value=str(value)
        if value in ('—','–','―','-'):value='-';size=min(size,7);bold=False
        font=font or ('KoreanBold' if bold else 'Korean')
        if width:
            while size>6 and pdfmetrics.stringWidth(value,font,size)>width:size-=.3
            while value and pdfmetrics.stringWidth(value,font,size)>width:value=value[:-2]+'…' if len(value)>2 else ''
        c.setFillColor(color);c.setFont(font,size)
        (c.drawRightString if right else c.drawCentredString if center else c.drawString)(x,y,value)

    def wrapped_cell(x,y,value,width,rowh,bold=False,color=navy,size=7.5):
        font='KoreanBold' if bold else 'Korean'
        while True:
            lines=['']
            for char in str(value):
                if char=='\n':lines.append('');continue
                if lines[-1] and pdfmetrics.stringWidth(lines[-1]+char,font,size)>width:lines.append('')
                lines[-1]+=char
            leading=size*1.08
            if size+(len(lines)-1)*leading<=rowh-3 or size<=6:break
            size-=.25
        max_lines=max(1,int((rowh-3-size)/leading)+1)
        if len(lines)>max_lines:
            lines=lines[:max_lines];lines[-1]=lines[-1][:-1]+'…'
        baseline=y+rowh/2-size*.35+(len(lines)-1)*leading/2
        for i,line in enumerate(lines):txt(x,baseline-i*leading,line,size,bold,color,center=True)

    def section(y,title,sub=''):
        c.setFillColor(teal);c.rect(30,y-2,3,12,fill=1,stroke=0);txt(40,y,title,11,True)
        if sub:txt(40+pdfmetrics.stringWidth(title,'KoreanBold',11)+8,y,sub,7,color=gray,width=290)

    def grid(x,y,width,headers,rows,widths=None,rowh=19,wrong=None,highlight=(),wrap=(),headerh=None,fontsize=8):
        widths=widths or [1]*len(headers);unit=width/sum(widths);ws=[a*unit for a in widths]
        headerh=rowh if headerh is None else headerh;height=headerh+rowh*len(rows)
        c.saveState();outline=c.beginPath();outline.roundRect(x,y-height,width,height,4)
        c.clipPath(outline,stroke=0,fill=0)
        c.setFillColor(navy);c.rect(x,y-headerh,width,headerh,fill=1,stroke=0)
        xx=x
        for title,ww in zip(headers,ws):txt(xx+ww/2,y-headerh/2-2.8,title,8,True,'#FFFFFF',ww-7,center=True);xx+=ww
        for i,row in enumerate(rows):
            yy=y-headerh-rowh*(i+1)
            c.setFillColor('#EED6CE' if wrong and i in wrong else '#F2F5F8' if i%2==0 else '#FFFFFF');c.rect(x,yy,width,rowh,fill=1,stroke=0)
            if wrong and i in wrong:c.setFillColor(red);c.rect(x,yy,2,rowh,fill=1,stroke=0)
            xx=x
            for j,(val,ww) in enumerate(zip(row,ws)):
                emphasized=j in highlight or bool(wrong and i in wrong)
                if j in wrap:wrapped_cell(xx+ww/2,yy,val,ww-8,rowh,emphasized,red if emphasized else navy,size=fontsize)
                else:txt(xx+ww/2,yy+rowh/2-fontsize*.35,val,fontsize,emphasized,red if emphasized else navy,ww-7,center=True)
                xx+=ww
        # Draw separators last so the next row's background cannot cover them.
        c.setStrokeColor('#A8B4C1');c.setLineWidth(.55)
        for i in range(len(rows)):c.line(x,y-headerh-rowh*i,x+width,y-headerh-rowh*i)
        c.restoreState();c.saveState();c.setStrokeColor('#8D9AA9');c.setLineWidth(.55)
        c.roundRect(x,y-height,width,height,4,fill=0,stroke=1);c.restoreState()
        return y-height

    def footer(page):
        c.setStrokeColor('#DEE5E9');c.line(30,45,565,45)
        message='수능과 가장 가까운 수학! 수학은 양지용입니다.'
        c.setStrokeColor(teal);c.line(30,45,30+pdfmetrics.stringWidth(message,'Korean',8),45)
        txt(30,29,message,8,color=navy)
        txt(510,29,f'{page} / 2',7,color=gray)

    def grade_cut_table(y):
        cuts=r['cuts'][:5];x=30;width=535;rowh=18;cell=width/6
        c.saveState();outline=c.beginPath();outline.roundRect(x,y-rowh*2,width,rowh*2,4);c.clipPath(outline,stroke=0,fill=0)
        c.setFillColor('#FFFFFF');c.rect(x,y-rowh*2,width,rowh*2,fill=1,stroke=0)
        c.setFillColor(navy);c.rect(x,y-rowh,width,rowh,fill=1,stroke=0);c.rect(x,y-rowh*2,cell,rowh*2,fill=1,stroke=0)
        txt(x+cell/2,y-rowh-2.8,'등급컷',8,True,'#FFFFFF',center=True)
        for i,cut in enumerate(cuts,1):
            txt(x+cell*(i+.5),y-rowh/2-2.8,i,8,True,'#FFFFFF',center=True)
            txt(x+cell*(i+.5),y-rowh*1.5-2.8,cut,8,center=True)
        c.setStrokeColor('#8D9AA9');c.setLineWidth(.5);c.line(x+cell,y-rowh,x+width,y-rowh)
        for i in range(1,6):c.line(x+cell*i,y,x+cell*i,y-rowh*2)
        c.restoreState();c.setStrokeColor('#8D9AA9');c.setLineWidth(.5);c.roundRect(x,y-rowh*2,width,rowh*2,4,fill=0,stroke=1)

    def error_rate(q):
        eligible=all_rows if q<22 else cohort
        return sum(x['answers'][q]!=x['key'][q] for x in eligible)/len(eligible)*100,len(eligible)

    txt(30,791,r['title'],13,True,color='#30363B',width=270)
    txt(565,762,store.report_name(),8.5,True,width=175,right=True)
    from .cheer import draw_cheer
    draw_cheer(c,r,store,y=784,height=50)
    c.setLineWidth(.7);c.setStrokeColor('#E0E4E8');c.line(30,777,565,777)
    c.setLineWidth(1.2);c.setStrokeColor(teal);c.line(30,777,30+min(270,pdfmetrics.stringWidth(r['title'],'KoreanBold',13)),777)
    section(743,'학생정보')
    grid(30,735,535,['학생명','학생번호','학교','시험일','학원명','반'],[[student['name'],student['code'][-5:],student.get('school','') or '—',r['day'],student['academy'],student['classroom']]],[.8,.75,1.1,1.05,1.6,1.3],22)
    common=sum(p for a,k,p in zip(r['answers'][:22],r['key'][:22],r['points'][:22]) if a==k)/100
    choice=r['score']/100-common
    section(667,'성적')
    grid(30,659,535,['원점수 / 만점','내 등급','추정 백분위','공통 / 선택과목 점수'],[[f"{r['score']/100:g} / {r['maximum']/100:g}",r['grade'] or '미설정',percentile_label(r),f"공통 {common:g}점 / {ELECTIVES.get(r['elective'],'선택과목')} {choice:g}점"]],[1,1,1.3,1.6],22,highlight=(0,1,3))
    if r['cuts']:
        grade_cut_table(605)
    else:txt(30,589,'등급컷 미설정',9,color=gray)
    section(547,'단원별 성취도 분석')
    groups=defaultdict(list)
    for q,topic in enumerate(r['topics']):groups[unit_name(topic) or '미분류'].append(q)
    # Bound the printed table without losing totals. Extra categories become an explicit aggregate.
    items=list(groups.items())
    if len(items)>9:items=items[:8]+[('기타 단원 합계',[q for _,qs in items[8:] for q in qs])]
    areas=[];personal=[];means=[]
    for name,qs in items:
        possible=sum(r['points'][q] for q in qs)
        scores=[sum(x['points'][q] for q in qs if x['answers'][q]==x['key'][q])/100 for x in cohort]
        mine=sum(r['points'][q] for q in qs if r['answers'][q]==r['key'][q])/100
        top=sorted(scores,reverse=True)[:max(1,ceil(len(scores)*.3))]
        ratio=mine/(possible/100)*100 if possible else 0
        mean=sum(scores)/len(scores)
        areas.append([name,f'{possible/100:g}',f'{mine:g}',f'{ratio:.1f}%',f'{mean:.1f}',f'{sum(top)/len(top):.1f}'])
        personal.append(ratio);means.append(mean/(possible/100)*100 if possible else 0)
    chart_height=max(160,(len(areas)+1)*20)
    grid(30,539,300,['단원','배점','득점','성취도','평균','상위30%'],areas,[2.2,.7,.7,1,.8,1],20,highlight=(2,3),fontsize=9)
    radar(c,341,539-chart_height+12,224,chart_height-18,[name for name,_ in items],personal,means)
    history=report_history(store,r)
    bottom=539-chart_height-4
    # Approved hand-drawn star precedes the existing coral section bar.
    c.saveState();c.translate(12,bottom-24);c.scale(14/24,14/24)
    c.setStrokeColor(teal);c.setLineWidth(1.25);c.setLineCap(1);c.setLineJoin(1)
    star=c.beginPath();star.moveTo(11,23);star.curveTo(13,18,15,11,20,1)
    star.curveTo(13,5,7,10,1,14);star.curveTo(9,14,16,15,24,15)
    star.curveTo(17,10,10,5,4,0);star.curveTo(6,8,8,16,11,23);c.drawPath(star);c.restoreState()
    priority=review_questions(r,all_rows,history)
    ranked=clinic_priorities(history,r['elective'],question_rates=question_rates)
    additional_review=bool(ranked and ranked[0]['rate_gap']<=1e-10)
    room_for_note=additional_review and chart_height>=180
    title=f'이번 시험의 우선 복습 {len(priority)}문항' if priority else '이번 시험은 모든 문항을 맞혔어요!'
    section(bottom-22,title,'(정답률이 높은데 내가 틀린 문항)' if priority else '')
    review_rows=[[i+1,x['q']+1,unit_name(r['topics'][x['q']]),course_for(r,x['q']) or '미입력',detail_for(r,x['q']) or '—',f"{x['points']/100:g}",f"{x['correct_rate']:.1f}%"] for i,x in enumerate(priority)]
    if not review_rows:review_rows=[['—','—','—','오답이 없습니다.','—','—','—']]
    bottom=grid(30,bottom-30,535,['순위','문항','단원','과목','학습내용','배점','정답률'],review_rows,[.45,.45,1.3,1.3,2.1,.6,.9],22 if room_for_note else 26 if chart_height<=180 else 24,highlight=(1,),wrap=(2,3,4),headerh=19,fontsize=9)
    clinic_gap=20 if chart_height>180 or room_for_note else 32
    section(bottom-clinic_gap,'클리닉 우선순위 분석','(내 오답률과 전체 학생 오답률의 차이가 큰 단원 순)')
    used,_=analysis_coverage(history,r['elective'],question_rates)
    clinic_rows=[[i+1,x['course'],x['topic'],f"{x['wrong']}/{x['total']}",f"{x['wrong_rate']:.1f}%",f"{x['overall_wrong_rate']:.1f}%",f"{round(x['rate_gap'],1) or 0:+.1f}%p"] for i,x in enumerate(ranked)]
    if not clinic_rows:clinic_rows=[['—','—','분석 대상 오답 없음' if used else '비교 자료 없음','—','—','—','—']]
    bottom=grid(30,bottom-clinic_gap-8,535,['순위','과목','단원','누적 오답/문항','내 오답률','전체 오답률','차이*'],clinic_rows,[.5,.9,1.6,1.2,1,1,1],18 if room_for_note else 22 if chart_height<=180 else 20,wrap=(2,),headerh=19,fontsize=9)
    note='* 같은 문항끼리 비교 · 차이 = 내 오답률 - 전체 오답률'
    txt(555,bottom-(31 if additional_review else 10),note,6.8,color=gray,right=True)
    if additional_review:
        txt(40,bottom-16,'전체 학생보다 오답률이 높은 단원은 없습니다. 추가 복습할 단원을 안내합니다.',9,color='#485563')
    footer(1);c.showPage()

    txt(30,795,'누적 성적과 학습 분석',12,True,color='#30363B')
    c.setStrokeColor('#DEE5E9');c.line(30,783,565,783)
    section(765,'회차별 성적')
    rows=[]
    for index,x in enumerate(history,1):
        from .history import mean_for_history
        p=x['estimated_percentile'];av=mean_for_history(store,x)
        rows.append([index,x['title'],x['day'],('확통' if x['elective']=='1' else ELECTIVES.get(x['elective'],'확인 필요' if x.get('historical') else x['subject'])),f"{x['score']/100:g} / {x['maximum']/100:g}",x['grade'] or '—',percentile_label(x),f'{av:.1f}'])
    grid(30,757,535,['순번','시험명','응시일자','선택과목','점수 / 만점','등급','추정 백분위','시험 평균'],rows,[.4,2.4,1.1,.7,1,.7,.85,.7],20,highlight=(4,5),wrap=(1,5))
    section(596,'성적 추이 분석')
    c.saveState();c.setStrokeColor('#8D9AA9');c.setLineWidth(.6)
    c.roundRect(30,457,535,131,6,fill=0,stroke=1);c.restoreState()
    gx,gy,gw,gh=65,504,470,61
    for tick in range(0,101,20):
        y=gy+gh*tick/100;c.setStrokeColor('#DFE6EA');c.line(gx,y,gx+gw,y);txt(35,y-3,tick,7,color=gray)
    coords=[]
    for i,x in enumerate(history):
        xx=gx+gw*(i+.5)/max(1,len(history));mean=mean_for_history(store,x)*10000/x['maximum']
        c.setFillColor('#D5DCE6');c.setStrokeColor('#8190A3');c.setLineWidth(.5);c.rect(xx-18,gy,36,gh*mean/100,fill=1,stroke=1)
        yy=gy+gh*x['score']/x['maximum'];coords.append((xx,yy));txt(xx,gy-12,x['round']+'회',8,width=47,center=True);txt(xx,yy+7,f"{x['score']/x['maximum']*100:.1f}",8,color=red,center=True)
        txt(xx,gy-23,x['day'],7,color=gray,center=True)
    c.setStrokeColor(red);c.setLineWidth(1.7)
    for (x,y),(xx,yy) in zip(coords,coords[1:]):c.line(x,y,xx,yy)
    for x,y in coords:c.setFillColor(red);c.circle(x,y,3,fill=1,stroke=0)
    c.setLineWidth(1);c.setStrokeColor(red);c.line(380,469,398,469);c.setFillColor(red);c.circle(389,469,2.5,fill=1,stroke=0);txt(404,466,'내 점수',8,True)
    c.setFillColor('#D5DCE6');c.setStrokeColor('#8190A3');c.rect(474,466,12,8,fill=1,stroke=1);txt(492,466,'평균 점수',8,True)
    section(439,'문항별 채점표')
    for part in range(2):
        qs=list(range(part*15,min((part+1)*15,len(r['key']))));rows=[];wrong=[]
        for i,q in enumerate(qs):
            rate,qn=error_rate(q);a=r['answers'][q]
            rows.append([q+1,unit_name(r['topics'][q]),f"{r['points'][q]/100:g}",r['key'][q],'—' if a is None else '무효' if a<0 else a,f'{rate:.1f}%'])
            if a!=r['key'][q]:wrong.append(i)
        grid(30+part*273,431,262,['번호','단원','배점','정답','내 답','오답률'],rows,[.5,1.65,.55,.65,.65,.9],15,wrong)
    bottom=191
    section(bottom-32,'오답률 상위 분석')
    hard=sorted(range(len(r['key'])),key=lambda q:-error_rate(q)[0])[:4]
    grid(30,bottom-40,535,['문항번호','단원','과목','학습내용','정답','전체 오답률'],[[q+1,unit_name(r['topics'][q]),course_for(r,q) or '미입력',detail_for(r,q) or '—',r['key'][q],f'{error_rate(q)[0]:.1f}%'] for q in hard],[.6,1.4,.9,2.6,.7,1.1],18,wrap=(1,2,3),headerh=17)
    footer(2);c.save()
