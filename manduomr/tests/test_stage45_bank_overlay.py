"""Stages 4·5 simulation: 문항은행·4주 오답노트, 문제지 매칭·손풀이 삽입(배치 오차 측정)."""
import json
from pathlib import Path
import cv2
import numpy as np
import pytest
from PIL import Image,ImageDraw
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from core.store import Store
from core.omr import ReadResult
from core.reports import fonts
from academy.adapters.hwp.converter import FakeHwpConverter
from academy.services import questionbank,wrongnote,overlay
from academy.pdf import compose as geometry

W,H=A4
# question → (page, column, top in points from the page top)
LAYOUT={1:(0,0,150),2:(0,0,470),3:(0,1,150),4:(0,1,470),5:(1,0,80),6:(1,0,400)}


def problem_pdf(path,title='주간지 시즌1 1회',solutions=False):
    fonts();c=canvas.Canvas(str(path),pagesize=A4)
    for page in (0,1):
        c.setFont('Korean',14);c.drawString(60,H-60,title+(' 해설' if solutions else ''))
        for q,(p,column,top) in LAYOUT.items():
            if p!=page:continue
            x=60 if column==0 else W/2+20
            c.setFont('KoreanBold',12);c.drawString(x,H-top,f'{q}.')
            c.setFont('Korean',10)
            c.drawString(x+20,H-top,f'정답 {q%5+1}. 풀이 과정을 적습니다.' if solutions else f'다음 식의 값을 구하시오. (문항 {q})')
            c.drawString(x+20,H-top-16,'x² + 2x + 1 = 0 일 때')
            if not solutions:
                c.setLineWidth(1);c.rect(x,H-(top+280),230,230,stroke=1,fill=0)   # box from top+50 to top+280
                c.drawString(x+6,H-(top+64),'[손풀이]')
        c.showPage()
    c.save();return Path(path)


@pytest.fixture
def bank(tmp_path):
    store=Store(tmp_path/'data'/'academy.sqlite3')
    cid=store.classroom(store.academy('청솔'),'청솔(토)','토')
    a=store.save_student('5678123','김민수',cid);b=store.save_student('1111222','이영희',cid)
    config={'topics':['다항식','다항식','수열','수열','극한','극한'],'difficulties':['중','상','중','중','하','상'],'areas':['대수']*6}
    exams=[store.save_exam(f'주간지 시즌1 {i}회','주간지 시즌1','수학',str(i),f'2026-10-{i+1:02d}',[q%5+1 for q in range(1,7)],[10]*6,config=config,exam_kind='weekly') for i in range(1,6)]
    yield store,cid,a,b,exams,tmp_path
    store.close()


def confirm(store,eid,sid,wrong,tag,class_id):
    key=store.exam(eid)['key'];answers=[None if q in wrong else k for q,k in enumerate(key,1)]
    source=store.db.execute('INSERT INTO sources(hash,name) VALUES(?,?)',(tag,tag)).lastrowid;store.db.commit()
    scan,_=store.add_scan(eid,source,1,tag,b'',ReadResult(None,[{'answer':x,'flag':'clear','levels':[]} for x in answers],None),sat_on=store.exam(eid)['day'],class_id=class_id)
    store.save_review(scan,sid,answers,[True]*6,True);store.confirm(scan)


def test_register_hwp_convert_split_and_edit(bank):
    store,cid,a,b,exams,tmp=bank
    pdf=problem_pdf(tmp/'p.pdf');hwp=tmp/'p.hwp';hwp.write_bytes(b'HWP Document File')
    with pytest.raises(ValueError,match='한글'):questionbank.register_edition(store,exams[0],hwp)
    questionbank.register_edition(store,exams[0],hwp,converter=FakeHwpConverter(pdf))
    assert store.rows('SELECT hwp_hash FROM question_sources WHERE exam_id=?',(exams[0],))[0]['hwp_hash']
    questionbank.register_edition(store,exams[0],problem_pdf(tmp/'s.pdf',solutions=True),kind='해설')
    result=questionbank.split_questions(store,exams[0])
    assert result=={'found':[1,2,3,4,5,6],'missing':[]}
    items={i['q_no']:i for i in questionbank.items(store,exams[0])}
    assert items[1]['page']==0 and items[1]['x1']<=W/2+1 and items[3]['x0']>=W/2-1 and items[5]['page']==1
    assert abs(items[1]['y1']-(470-4))<14 and all(i['solution_hash'] for i in items.values())
    questionbank.set_region(store,exams[0],2,0,(40,460,300,760))
    questionbank.split_questions(store,exams[0])
    assert questionbank.items(store,exams[0])[1]['method']=='manual' and questionbank.items(store,exams[0])[1]['y0']==460


def test_similar_candidates_same_unit_and_difficulty(bank):
    store,cid,a,b,exams,tmp=bank
    for eid in exams[:2]:
        questionbank.register_edition(store,eid,problem_pdf(tmp/f'{eid}.pdf'));questionbank.split_questions(store,eid)
    q1=questionbank.items(store,exams[0])[0]
    candidates=questionbank.similar_candidates(store,q1['id'])
    assert [(c['exam_id'],c['q_no']) for c in candidates]==[(exams[1],1)]
    questionbank.link_similar(store,q1['id'],[candidates[0]['id']])
    assert store.rows('SELECT rank FROM similar_links WHERE question_id=?',(q1['id'],))[0]['rank']==1


def test_four_round_wrongnote_with_unregistered_list(bank):
    store,cid,a,b,exams,tmp=bank
    for i,eid in enumerate(exams):
        if i!=2:questionbank.register_edition(store,eid,problem_pdf(tmp/f'w{eid}.pdf'));questionbank.split_questions(store,eid)
        if i!=3:confirm(store,eid,a,[1,4] if i<4 else [2],f'a{i}',cid)   # 4회 결시
    out=wrongnote.build(store,a,exams[4],tmp/'note.pdf')
    assert out['exams']==exams[1:] and out['wrong']==2+2+1
    assert [(m['title'],m['q']) for m in out['missing']]==[('주간지 시즌1 3회',1),('주간지 시즌1 3회',4)]
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(str(out['path'])) as doc:
        text=''.join(p.get_textpage().get_text_range() for p in doc)
        assert len(doc)>=3 and '미응시' in text and '문항 이미지 미등록' in text and '정답과 해설' in text
    batch=store.rows('SELECT * FROM wrongnote_batches WHERE student_id=?',(a,))[0]
    assert json.loads(batch['exam_ids'])==exams[1:] and batch['period_start']=='2026-10-03'
    with pytest.raises(ValueError,match='주간지'):
        other=store.save_exam('모의','모의','수학','1','2026-10-01',[1],[1]);wrongnote.build(store,a,other,tmp/'x.pdf')


def scanned(stamped_pdf,code,angle,shift,flip=False):
    """Render the print file, fill the 학번 bubbles on page 1, then rotate/shift like a scanner."""
    import pypdfium2 as pdfium
    scale=150/72;pages=[];transforms=[]
    doc=pdfium.PdfDocument(str(stamped_pdf))
    for index in range(len(doc)):
        image=doc[index].render(scale=scale).to_pil().convert('RGB')
        if index==0:
            draw=ImageDraw.Draw(image)
            for p,column in enumerate(geometry.id_centers(W,H,[0.70,0.015])):
                x,y=column[int(code[p])];draw.ellipse(((x-3.4)*scale,(y-3.4)*scale,(x+3.4)*scale,(y+3.4)*scale),fill='black')
        w,h=image.size;matrix=cv2.getRotationMatrix2D((w/2,h/2),angle,1.0);matrix[:,2]+=shift
        moved=Image.fromarray(cv2.warpAffine(np.array(image),matrix,(w,h),borderValue=(255,255,255)))
        if flip:moved=moved.rotate(180);flipped=np.array([[-1,0,w],[0,-1,h]],dtype=float)
        pages.append(moved)
        full=np.vstack([matrix,[0,0,1]])
        if flip:full=np.vstack([flipped,[0,0,1]])@full
        transforms.append(full)
    doc.close()
    return pages,transforms


def red_box(image):
    arr=np.array(image.convert('RGB')).astype(int)
    mask=(arr[:,:,0]>180)&(arr[:,:,1]<90)&(arr[:,:,2]<90)
    ys,xs=np.nonzero(mask)
    return (xs.min(),ys.min(),xs.max(),ys.max()) if len(xs) else None


def test_overlay_matching_alignment_and_position_error(bank):
    store,cid,a,b,exams,tmp=bank
    eid=exams[0];questionbank.register_edition(store,eid,problem_pdf(tmp/'o.pdf'));questionbank.split_questions(store,eid)
    detected=overlay.detect_slots(store,eid);assert detected['found']==[1,2,3,4,5,6]
    slot=store.rows('SELECT * FROM solution_slots WHERE exam_id=? AND q_no=1',(eid,))[0]
    assert abs(slot['x0']-60)<2 and abs(slot['y0']-200)<2 and abs(slot['x1']-290)<2 and abs(slot['y1']-430)<2
    for q in range(1,7):
        sol=Image.new('RGB',(400,300),'white');ImageDraw.Draw(sol).rectangle((0,0,399,299),fill=(220,30,30))
        sol.save(tmp/f'sol{q}.png');overlay.register_hand_solution(store,eid,q,tmp/f'sol{q}.png','조교')
    printed=overlay.worksheet_pdf(store,eid,tmp/'print.pdf')
    pa,ta=scanned(printed,'5678123',1.2,(14,-9))
    pb,tb=scanned(printed,'1111222',-0.8,(-6,11),flip=True)
    scan_pdf=tmp/'scan.pdf';pages=pa+pb;pages[0].save(scan_pdf,'PDF',resolution=150,save_all=True,append_images=pages[1:])
    imported=overlay.import_worksheets(store,eid,scan_pdf)
    assert len(imported['worksheets'])==2 and not imported['unreadable_pages']
    rows=store.rows('SELECT * FROM worksheets ORDER BY id')
    assert [r['student_id'] for r in rows]==[a,b] and all(r['status']=='matched' and r['pages']==2 for r in rows)
    out=overlay.compose(store,rows[0]['id'],tmp/'result.pdf')
    assert out['questions']==[1,2,3,4,5,6]
    import pypdfium2 as pdfium
    scale=150/72
    with pdfium.PdfDocument(str(out['path'])) as doc:
        assert len(doc)==2
        rendered=doc[0].render(scale=scale).to_pil()
    # expected: slot of q1 (points) → print px → the simulated scanner transform
    corners=np.float32([[[slot['x0']*scale,slot['y0']*scale]],[[slot['x1']*scale,slot['y1']*scale]]])
    expected=cv2.perspectiveTransform(corners,ta[0]).reshape(-1,2)
    found=red_box(rendered.crop((0,0,rendered.width//2,int(470*scale))))
    assert found is not None
    error=max(abs(found[0]-expected[0][0]),abs(found[1]-expected[0][1]))
    assert error<6, f'배치 오차 {error:.1f}px (150dpi)'
    # 오답 문항만: 이영희 3번만 오답
    confirm(store,eid,b,[3],'b-only3',cid)
    wrong_only=overlay.compose(store,rows[1]['id'],tmp/'wrong.pdf',target='wrong')
    assert wrong_only['questions']==[3]
    assert store.rows('SELECT status FROM worksheets WHERE id=?',(rows[1]['id'],))[0]['status']=='composed'
