"""M5 4주 오답노트: 같은 시리즈 주간지 N회차(기본 4)의 확정 오답 → 원문항, 뒤쪽에 정답·해설.

문항은행에 없는 오답은 '미등록'으로 표시하고 생성은 막지 않음. 검수 대기 답안은 쓰지 않음.
"""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import json
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from core.reports import fonts
from core.store import now
from core.classification import unit_name
from academy.config import program_setting


def window(store,end_exam_id,rounds=None):
    """같은 시리즈 주간지 중 기준 회차까지의 최근 N회차(시행일·ID 순)."""
    end=store.exam(end_exam_id);rounds=rounds or program_setting(store,'wrongnote_rounds')
    if end['exam_kind']!='weekly':raise ValueError('오답노트는 주간지 시험으로 만듭니다.')
    exams=[e for e in store.exams() if e['exam_kind']=='weekly' and e['series']==end['series'] and (e['day'],e['id'])<=(end['day'],end['id'])]
    return sorted(exams,key=lambda e:(e['day'],e['id']))[-rounds:]


def collect(store,student_id,end_exam_id,rounds=None):
    exams=window(store,end_exam_id,rounds);entries=[];missing=[]
    for exam in exams:
        result=next((r for r in store.results(exam['id'],student_id)),None)
        if not result:continue
        bank={i['q_no']:i for i in store.rows('SELECT * FROM question_items WHERE exam_id=?',(exam['id'],))}
        for q in result['wrong']:
            item=bank.get(q)
            entry={'exam':exam,'q':q,'key':result['key'][q-1],'answer':result['answers'][q-1],'unit':unit_name(result['topics'][q-1]),
                   'image':item['image_hash'] if item and item['image_hash'] else '','solution':item['solution_hash'] if item else ''}
            if not entry['image']:missing.append({'exam_id':exam['id'],'title':exam['title'],'q':q})
            entries.append(entry)
    return exams,entries,missing


def build(store,student_id,end_exam_id,path,rounds=None):
    fonts();student=store.student(student_id)
    exams,entries,missing=collect(store,student_id,end_exam_id,rounds)
    if not exams:raise ValueError('오답노트를 만들 주간지가 없습니다.')
    w,h=A4;c=canvas.Canvas(str(path),pagesize=A4);c.setTitle('4주 오답노트 · '+student['name'])
    navy='#203752';accent='#DF654F';gray='#606A74'
    def txt(x,y,s,size=10,bold=False,color=navy):
        c.setFillColor(color);c.setFont('KoreanBold' if bold else 'Korean',size);c.drawString(x,y,str(s))
    def footer():
        txt(40,28,f"{student['name']} · {student['code']} · 오답노트",8,color=gray);c.drawRightString(w-40,28,str(c.getPageNumber()))
    # cover
    txt(40,h-80,f'{len(exams)}회차 오답노트',24,True);txt(40,h-110,f"{student['name']} ({student['code']})  ·  {student['academy']} {student['classroom']}",12)
    txt(40,h-132,f"기간 {exams[0]['day']} ~ {exams[-1]['day']}  ·  오답 {len(entries)}문항",11,color=gray)
    y=h-180
    for exam in exams:
        count=sum(1 for e in entries if e['exam']['id']==exam['id'])
        taken=bool(store.results(exam['id'],student_id))
        txt(50,y,f"{exam['day']}  {exam['title']}",11);txt(400,y,f'오답 {count}문항' if taken else '미응시',11,color=accent if taken else gray);y-=22
    if missing:
        y-=12;txt(40,y,f'문항 이미지 미등록 {len(missing)}문항 (문항은행에 등록하면 다음 생성부터 실림)',10,True,accent);y-=18
        for m in missing[:20]:txt(50,y,f"{m['title']} {m['q']}번",9,color=gray);y-=14
    footer();c.showPage()
    # questions
    y=h-50
    def place(digest,top,max_h):
        image=ImageReader(BytesIO(store.file_bytes(digest)));iw,ih=image.getSize()
        scale=min((w-80)/iw,max_h/ih,1.6);dw,dh=iw*scale,ih*scale
        c.drawImage(image,40,top-dh,dw,dh,mask='auto');return dh
    for n,e in enumerate(entries,1):
        need=60 if not e['image'] else 60+min(h*0.55,240)
        if y-need<50:footer();c.showPage();y=h-50
        c.setFillColor(accent);c.rect(40,y-2,3,13,fill=1,stroke=0)
        txt(50,y,f"{n}. {e['exam']['title']} · {e['q']}번 · {e['unit']}",11,True);y-=20
        if e['image']:y-=place(e['image'],y,min(h*0.55,420))+16
        else:
            c.setStrokeColor('#C9D3DA');c.setDash(3,2);c.rect(40,y-40,w-80,40,fill=0,stroke=1);c.setDash()
            txt(54,y-25,'문항 이미지 미등록 — 원문항을 문항은행에 등록해 주세요.',10,color=gray);y-=56
    footer();c.showPage()
    # answers and solutions at the back
    y=h-60;txt(40,y,'정답과 해설',18,True);y-=30
    for n,e in enumerate(entries,1):
        need=40 if not e['solution'] else 40+200
        if y-need<50:footer();c.showPage();y=h-50
        txt(40,y,f"{n}. {e['exam']['title']} {e['q']}번   정답 {e['key']}   (내 답 {'—' if e['answer'] is None else e['answer']})",10,True);y-=18
        if e['solution']:y-=place(e['solution'],y,360)+14
        else:txt(54,y,'해설 미등록',9,color=gray);y-=18
    footer();c.save()
    with store.transaction():
        digest=store.put_file(path,'pdf')
        store.db.execute('INSERT INTO wrongnote_batches(student_id,exam_ids,period_start,period_end,pdf_hash,missing,created_at) VALUES(?,?,?,?,?,?,?)',
                         (student_id,json.dumps([e['id'] for e in exams]),exams[0]['day'],exams[-1]['day'],digest,json.dumps(missing,ensure_ascii=False),now()))
        store.log('wrongnote_built',student_id,{'exam_ids':[e['id'] for e in exams],'wrong':len(entries),'missing':len(missing)})
    return {'path':Path(path),'exams':[e['id'] for e in exams],'wrong':len(entries),'missing':missing}
