import json
import sqlite3
from copy import deepcopy
from pathlib import Path
import pytest
from PIL import Image,ImageDraw
from localomr.omr import ReadResult,png_bytes
from localomr.mathomr import recognize_math,centers,id_centers,SIZE,MARKERS
from localomr.examdata import NUMERIC,effective,grade
from localomr.store import Store


KEY=[i%5+1 if i+1 not in NUMERIC else [0,1,12,100,288,47,17,844,622][sorted(NUMERIC).index(i+1)] for i in range(30)]
CONFIG={'form':'math30','primary':'1','cuts':{'1':[83,74,66,56,36,25,15,5]},'topics':['공통']*22+['선택']*8,'skills':['']*30,'variants':{'2':{'key':[2]*6+[25,999],'points':[3]*8,'topics':['미적분']*8,'skills':['']*8}}}


def drawing(key=KEY,code='4241',choice='1',suffix=None):
    im=Image.new('RGB',SIZE,'white');d=ImageDraw.Draw(im)
    for i,(x,y) in enumerate(MARKERS):d.rectangle((x-6,y-(14 if i<2 else 6),x+6,y+(14 if i<2 else 6)),fill='black')
    for x,y in [(650,200),(650,450),(820,300),(850,200),(1020,300),(1051,400),(1262,400),(1321,400),(1491,500),(650,850),(740,1000),(771,900),(1012,950),(1224,900),(1533,950)]:d.line((x,y-10,x,y+10),fill=(50,175,115),width=2)
    def mark(p):
        x,y=p;d.ellipse((x-5,y-12,x+5,y+12),fill='black')
    for q,k in enumerate(key,1):
        if k is None:continue
        if q in NUMERIC:
            for i,ch in enumerate(str(k).rjust(3)):
                if ch!=' ':mark(centers(q)[i][int(ch)])
        else:mark(centers(q)[k-1])
    for i,ch in enumerate(code):mark(id_centers(i)[int(ch)])
    if suffix is not None:mark(id_centers(4)[suffix])
    if choice:mark((1337,{'1':115,'2':156,'3':199}[choice]))
    return im


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_math_corners_digits_and_rotation(rotation):
    r=recognize_math(drawing().rotate(rotation,expand=True))
    assert not r.error
    assert [a['answer'] for a in r.answers]==KEY
    assert all(a['flag']=='clear' for a in r.answers)
    assert r.code=='042411' and r.elective=='1'


def test_suffix_override_and_missing_marker():
    image=drawing(suffix=2);assert recognize_math(image).code=='042412'
    ImageDraw.Draw(image).rectangle((0,0,90,90),fill='white')
    assert recognize_math(image).error


def test_numeric_interior_gap_and_multiple():
    key=KEY.copy();key[18]=102;im=drawing(key);d=ImageDraw.Draw(im)
    x,y=centers(19)[1][0];d.rectangle((x-8,y-15,x+8,y+15),fill='white')
    r=recognize_math(im);assert r.answers[18]['flag']=='incomplete' and r.answers[18]['answer'] is None
    im=drawing();d=ImageDraw.Draw(im);x,y=centers(16)[2][2];d.ellipse((x-5,y-12,x+5,y+12),fill='black')
    assert recognize_math(im).answers[15]['flag']=='multiple'


@pytest.fixture
def store(tmp_path):
    s=Store(tmp_path/'test.sqlite3');aid=s.academy('시험학원');cid=s.classroom(aid,'A반');student=s.save_student('42411','예제학생',cid)
    yield s,student
    s.close()


def exam(s,config=None):return s.save_exam('수학시험','시리즈','수학','1','2026-10-18',KEY,[3]*30,config=config or CONFIG)


def scan(s,eid,student,choice='1',unique='1',answers=None):
    source=s.db.execute("INSERT INTO sources(hash,name,data) VALUES(?,?,?)",(unique,'synthetic',b'synthetic')).lastrowid;s.db.commit()
    values=answers if answers is not None else effective(s.exam(eid),choice)['key']
    read=ReadResult(None,[{'answer':a,'flag':'clear','levels':[]} for a in values],None);read.elective=choice
    sid,_=s.add_scan(eid,source,1,unique,b'image',read,sat_on=s.exam(eid)['day'])
    s.save_review(sid,student,values,[True]*30,True,elective=choice);s.confirm(sid);return sid


def test_grade_boundary_and_updates_do_not_unconfirm(store):
    s,student=store;eid=exam(s);sid=scan(s,eid,student)
    assert s.results()[0]['grade']==1
    config=deepcopy(CONFIG);config['cuts']['1']=[90,80,70,60,50,40,30,20]
    s.save_exam('수학시험','시리즈','수학','1','2026-10-18',KEY,[3]*30,eid,config)
    assert s.scan(sid)['status']=='confirmed' and s.exam(eid)['revision']==1
    assert grade(9000,config['cuts']['1'])==1 and grade(8999,config['cuts']['1'])==2
    assert grade(1999,config['cuts']['1'])==9 and grade(0,[]) is None


def test_elective_key_change_affects_only_relevant_answers(store):
    s,student=store;eid=exam(s);sid=scan(s,eid,student)
    second=s.save_student('000002','두번째',s.student(student)['class_id']);sid2=scan(s,eid,second,'2','2')
    config=deepcopy(CONFIG);config['variants']['2']['key'][0]=3
    s.save_exam('수학시험','시리즈','수학','1','2026-10-18',KEY,[3]*30,eid,config)
    assert s.scan(sid)['status']=='confirmed'
    assert s.scan(sid2)['status']=='pending' and s.scan(sid2)['score']==8700


def test_unregistered_elective_cannot_confirm(store):
    s,student=store;eid=exam(s)
    with pytest.raises(ValueError,match='선택과목'):scan(s,eid,student,'3')


def test_estimated_percentile_independent_of_cohort(store):
    s,student=store;eid=exam(s);scan(s,eid,student)
    second=s.save_student('2','두번째',s.student(student)['class_id']);scan(s,eid,second,'1','2')
    third=s.save_student('3','세번째',s.student(student)['class_id']);answers=KEY.copy();answers[0]=None;scan(s,eid,third,'1','3',answers)
    other=s.save_student('4','다른과목',s.student(student)['class_id']);scan(s,eid,other,'2','4')
    rows=s.results(eid);top=next(r for r in rows if r['student_id']==student)
    assert top['estimated_percentile']==100
    assert next(r for r in rows if r['student_id']==third)['estimated_percentile']==pytest.approx(96+4*4/7)


def test_duplicate_suffix_allocation(store):
    s,student=store;assert s.allocate_student_code('4241')=='042412'
    assert s.allocate_student_code('0123')=='001231'


def test_cut_validation(store):
    s,_=store
    for cuts in ([90,90,70,60,50,40,30,20],[100,80,70,60,50,40,30,20],[80,70]):
        config=deepcopy(CONFIG);config['cuts']['1']=cuts
        with pytest.raises(ValueError):exam(s,config)


def test_v1_restore_migrates_preserving_data(tmp_path):
    original=Store(tmp_path/'old.sqlite3');a=original.academy('과거');c=original.classroom(a,'반');original.save_student('123','학생',c);original.close()
    db=sqlite3.connect(tmp_path/'old.sqlite3')
    for table,col in [('exams','config'),('scans','elective'),('scans','choice_reading'),('students','school')]:db.execute(f'ALTER TABLE {table} DROP COLUMN {col}')
    db.execute('PRAGMA user_version=1');db.commit();db.close()
    current=Store(tmp_path/'current.sqlite3');current.restore(tmp_path/'old.sqlite3')
    from localomr.store import SCHEMA_VERSION
    assert current.students()[0]['name']=='학생' and current.db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION
    current.close()


def test_math_pdf_import_and_report(store,tmp_path):
    from localomr.importer import import_files
    from localomr.reports import report_pdf
    import pypdfium2 as pdfium
    s,student=store;eid=exam(s)
    path=tmp_path/'math.pdf';drawing().save(path,'PDF',resolution=144)
    imported=import_files(s.path,eid,[path],class_id=s.student(student)['class_id']);assert imported['added']==1 and not imported['failed']
    sid=s.scans(eid)[0]['id'];row=s.scan(sid)
    assert row['answers']==KEY and row['student_id']==student and row['elective']=='1'
    s.save_review(sid,student,row['answers'],[True]*30,True,elective='1');s.confirm(sid)
    output=tmp_path/'report.pdf';report_pdf(output,s,[sid])
    with pdfium.PdfDocument(str(output)) as doc:
        assert len(doc)==2
        page=doc[0];tp=page.get_textpage();text=tp.get_text_range();assert '추정 백분위' in text and '100.0' in text and '공식' not in text.split('추정 백분위')[0];tp.close();page.close()


def test_exam_editor_elective_roundtrip(store,monkeypatch):
    import os
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtWidgets import QApplication,QMessageBox
    from localomr.examui import ExamEditor
    app=QApplication.instance() or QApplication([])
    def fail(*args):raise AssertionError(str(args[-1]))
    monkeypatch.setattr(QMessageBox,'warning',fail)
    s,_=store;cfg=deepcopy(CONFIG);cfg['variants']['3']=deepcopy(cfg['variants']['2']);eid=exam(s,cfg);editor=ExamEditor(s,eid)
    editor.select_section('2');editor.keys.item(0,6).setText('4');editor.save()
    saved=s.exam(eid);assert effective(saved,'1')['key']==KEY
    assert effective(saved,'2')['key'][22]==4
    assert saved['config']['cuts']['1']==CONFIG['cuts']['1']
    editor.close()
