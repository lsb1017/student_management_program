"""Stage 2 simulation: user-defined OMR forms, manual mini-test/homework entry, two report kinds."""
import cv2
import numpy as np
import pytest
from PIL import Image
from core.store import Store
from core.omr import load_pages,recognize as recognize_local60
from core.reports import sheet_pdf
from academy.forms.generator import define_form,render_pdf,save_generated
from academy.forms.reader import recognize
from academy.forms.external import register_external
from academy.services import grading,entries
from academy.services.report import render,report_kind

ANSWERS=[1,2,3,4,5,4,3,2,1,2,3,4,17,250,7]   # questions 13-15 numeric


def page(layout,tmp_path,code='5678123',answers=ANSWERS,title='주간지 1회'):
    path=tmp_path/f'sheet_{code}.pdf';render_pdf(layout,path,title,code,answers)
    return path,next(load_pages(path))[1]


def test_generated_form_reads_choices_numeric_and_seven_digit_code(tmp_path):
    layout=define_form(15,5,[13,14,15],number=3)
    _,img=page(layout,tmp_path)
    for angle in (0,90,180,270):
        r=recognize(img.rotate(angle,expand=True),layout)
        assert not r.error and [a['answer'] for a in r.answers]==ANSWERS and r.code=='5678123'
        assert all(a['flag']=='clear' for a in r.answers)
    assert recognize_local60(img,15).error   # the 1.0.6 reader fails closed on the new sheet
    assert recognize(img,define_form(15,5,[13,14,15],number=4)).error  # another form number
    p=tmp_path/'local.pdf';sheet_pdf(p,15,'old','000123');old=next(load_pages(p))[1]
    assert recognize(old,layout).error


def test_layout_limits_and_choice_count(tmp_path):
    with pytest.raises(ValueError,match='한 장'):define_form(30,5,list(range(1,31)))
    layout=define_form(60,4)
    _,img=page(layout,tmp_path,answers=[(i%4)+1 for i in range(60)],code='0000001')
    r=recognize(img,layout);assert [a['answer'] for a in r.answers]==[(i%4)+1 for i in range(60)]


def test_blank_multiple_and_incomplete_numeric(tmp_path):
    layout=define_form(15,5,[13,14,15])
    answers=ANSWERS.copy();answers[0]=None
    _,img=page(layout,tmp_path,answers=answers,code='1234567')
    from core.omr import WIDTH
    normal=img.copy()
    r=recognize(normal,layout);assert r.answers[0]['flag']=='blank'
    from academy.pdf.align import warp_markers
    from PIL import ImageDraw
    aligned,_,_=warp_markers(img,layout['markers'],layout['size']);draw=ImageDraw.Draw(aligned)
    x,y=layout['questions'][1]['centers'][0];draw.ellipse((x-10,y-10,x+10,y+10),fill='black')  # 2번: 1 and 2 marked
    x,y=layout['questions'][13]['places'][1][5];draw.rectangle((x-13,y-13+27*0,x+13,y+13),fill='white')  # erase tens of 250
    r=recognize(aligned,layout)
    assert r.answers[1]['flag']=='multiple' and r.answers[13]['flag']=='incomplete'


def test_external_form_aligned_by_features(tmp_path):
    base=define_form(10,5,[10],number=9)
    blank_pdf=tmp_path/'blank.pdf';render_pdf(base,blank_pdf,'외부 양식')
    blank=next(load_pages(blank_pdf))[1].resize((1240,1754))
    blank.save(tmp_path/'blank.png')
    q1=base['questions'][0]['centers'][0];q2=base['questions'][1]['centers'][0];num=base['questions'][9]['places']
    blocks=[{'kind':'choice','first':1,'count':9,'choices':5,'origin':q1,'dx':43,'dy':q2[1]-q1[1]},
            {'kind':'numeric','q':10,'origin':num[0][0],'dx':num[1][0][0]-num[0][0][0],'dy':num[0][1][1]-num[0][0][1]},
            {'kind':'id','digits':7,'origin':base['id']['centers'][0][0],'dx':48,'dy':28}]
    store=Store(tmp_path/'db.sqlite3')
    fid=register_external(store,'학원 기존 OMR',tmp_path/'blank.png',blocks)
    form=store.form(fid);from academy.forms.reader import reference_gray
    answers=[2,3,4,5,1,2,3,4,5,321]
    _,filled=page(base,tmp_path,'7654321',answers)
    arr=np.array(filled.resize((1240,1754)));h,w=arr.shape[:2]
    warped=cv2.warpPerspective(arr,cv2.getPerspectiveTransform(np.float32([[0,0],[w,0],[w,h],[0,h]]),np.float32([[18,10],[w-6,25],[w-20,h-8],[5,h-30]])),(w,h),borderValue=(255,255,255))
    r=recognize(Image.fromarray(warped),form['layout'],reference_gray(store,form))
    assert not r.error and [a['answer'] for a in r.answers]==answers and r.code=='7654321'
    with pytest.raises(ValueError,match='빠짐없이'):register_external(store,'잘못',tmp_path/'blank.png',[{**blocks[0],'first':2},blocks[2]])
    store.close()


@pytest.fixture
def weekly(tmp_path):
    store=Store(tmp_path/'data'/'academy.sqlite3')
    aid=store.academy('청솔');cid=store.classroom(aid,'청솔(토)','토')
    students=[store.save_student(code,name,cid) for code,name in (('5678123','김민수'),('1111222','이영희'),('3333444','박철수'))]
    fid=save_generated(store,'주간지 15문항',15,5,[13,14,15])
    config={'form':'custom','form_id':fid,'topics':['다항식']*4+['수열']*4+['극한']*4+['확률']*3,
            'areas':['대수']*8+['미적분Ⅰ']*4+['확률과 통계']*3,'skills':[f'학습내용{i}' for i in range(15)]}
    eid=store.save_exam('주간지 시즌1 1회','주간지 시즌1','수학','1','2026-11-01',ANSWERS,[6]*12+[8,8,12],config=config,exam_kind='weekly',form_id=fid)
    yield store,aid,cid,students,eid,fid
    store.close()


def test_weekly_flow_import_link_confirm_and_report(weekly,tmp_path):
    store,aid,cid,students,eid,fid=weekly
    layout=store.form(fid)['layout'];files=[]
    for code,answers in (('5678123',ANSWERS),('1111222',[1,2,3,4,5,4,3,2,1,1,1,1,17,250,8]),('3333444',[2]*12+[1,2,3])):
        path,_=page(layout,tmp_path,code,answers);files.append(path)
    summary=grading.import_pdf(store,eid,files,aid,cid,'2026-11-01')
    assert summary['added']==3 and not summary['failed'] and not summary['errors']
    scans=store.scans(eid)
    assert {s['student_id'] for s in scans}==set(students)
    done,skipped=grading.confirm_clear(store,eid,[s['id'] for s in scans])
    assert len(done)==3 and not skipped
    # 6점×12 + 8+8+12 = 100점. 2번 학생: 10~12번(6점×3)·15번(12점) 오답 → 70점. 3번 학생: 2·8·10번만 정답 → 18점.
    assert sorted(r['score'] for r in store.results(eid))==[1800,7000,10000]
    top=next(r for r in store.results(eid) if r['student_id']==students[0]);assert top['score']==top['maximum']==10000
    entries.save(store,cid,'2026-11-01',[{'student_id':students[0],'mini_score':'18.5','homework':'a'},{'student_id':students[1],'mini_score':'','homework':''}])
    assert entries.entry_for(store,cid,'2026-11-01',students[1])['homework']=='미제출'
    assert report_kind(store.exam(eid))=='weekly'
    out=render(store,[top['id']],tmp_path/'weekly.pdf')
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(str(out)) as doc:
        assert len(doc)==2;texts=[]
        for p in doc:
            tp=p.get_textpage();texts.append(tp.get_text_range());tp.close();p.close()
    text=''.join(texts)
    for label in ('미니테스트 점수','과제 완성도','18.5','A','단원별 점수','대수 48점','미적분Ⅰ 24점','확률과 통계 28점','단원별 성취도 분석','문항별 채점표','성적 추이 분석','5678123','만점 달성!'):
        assert label in text,label
    for removed in ('등급컷','추정 백분위','클리닉 우선순위','오답률 상위 분석','내 등급'):
        assert removed not in text,removed


def test_entries_validation_paste_and_excel_roundtrip(weekly,tmp_path):
    store,aid,cid,students,eid,fid=weekly
    with pytest.raises(ValueError,match='A, B, C'):entries.save(store,cid,'2026-11-01',[{'student_id':students[0],'mini_score':'10','homework':'D'}])
    with pytest.raises(ValueError,match='0~1,000'):entries.save(store,cid,'2026-11-01',[{'student_id':students[0],'mini_score':'-3','homework':'A'}])
    assert entries.parse_paste('10\tA\r\n\tB\r\n')==[['10','A'],['','B']]
    entries.save(store,cid,'2026-11-01',[{'student_id':s,'mini_score':str(10+i),'homework':'ABC'[i]} for i,s in enumerate(students)])
    path=entries.export_xlsx(store,cid,'2026-11-01',tmp_path/'entries.xlsx')
    values,unmatched=entries.import_xlsx(store,cid,'2026-11-08',path)
    assert not unmatched and sorted((v['mini_score'],v['homework']) for v in values)==[(10,'A'),(11,'B'),(12,'C')]
    entries.save(store,cid,'2026-11-08',values)
    grid=entries.grid(store,cid,'2026-11-08');assert {r['name']:r['homework'] for r in grid}=={'김민수':'A','이영희':'B','박철수':'C'}
    assert entries.session(store,cid,'2026-11-08')['link_key']!=entries.session(store,cid,'2026-11-01')['link_key']


def test_mock_report_through_service_matches_ported_report(tmp_path):
    from test_core_math import KEY,CONFIG,scan
    store=Store(tmp_path/'m.sqlite3');cid=store.classroom(store.academy('학림'),'학림(수)','수');student=store.save_student('4241001','예제학생',cid)
    eid=store.save_exam('모의고사 1회','모의','수학','1','2026-10-18',KEY,[3]*30,config=CONFIG)
    sid=scan(store,eid,student)
    assert store.exam(eid)['exam_kind']=='mock' and report_kind(store.exam(eid))=='mock'
    from core.reports import report_pdf
    render(store,[sid],tmp_path/'service.pdf');report_pdf(tmp_path/'core.pdf',store,[sid])
    from test_regression_v106 import page_texts
    assert page_texts(tmp_path/'service.pdf')==page_texts(tmp_path/'core.pdf')
    store.close()
