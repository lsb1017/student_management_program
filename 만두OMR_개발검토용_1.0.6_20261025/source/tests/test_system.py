import hashlib
import json
import sqlite3
from pathlib import Path
from io import BytesIO
import cv2
import numpy as np
from PIL import Image,ImageDraw,ImageFilter
import pytest
from localomr.store import Store,points_cents
from localomr.omr import recognize,load_pages,png_bytes,pixel_hash,answer_centers,id_centers,WIDTH,HEIGHT
from localomr.reports import sheet_pdf,report_pdf
from localomr.importer import import_files


@pytest.fixture
def store(tmp_path):
    s=Store(tmp_path/'data.sqlite3')
    aid=s.academy('연구학원');cid=s.classroom(aid,'A반');student=s.save_student('123','샘플학생',cid)
    eid=s.save_exam('주간 평가','수학 주간','수학','1','2026-10-18',[1,2,3,4,5],[2,3,4,5,6])
    yield s,student,eid
    s.close()


@pytest.fixture
def sheet(tmp_path):
    p=tmp_path/'sample.pdf';sheet_pdf(p,60,'테스트 전용','000123',[i%5+1 for i in range(60)])
    return next(load_pages(p))[1]


def scan(store,student,eid,tmp_path,answers=None,tag='a'):
    from localomr.omr import ReadResult
    p=tmp_path/(tag+'.png');img=Image.new('RGB',(30,30),'white');img.save(p);source=store.source(p)
    answers=answers or [1,2,3,4,5]
    result=ReadResult(p.read_bytes(),[{'answer':a,'flag':'clear','levels':[]} for a in answers],'000123')
    sid,added=store.add_scan(eid,source,1,tag,p.read_bytes(),result)
    return sid


def confirm(s,sid,student):
    row=s.scan(sid);s.save_review(sid,student,row['answers'],[True]*len(row['answers']),True,'test checked');s.confirm(sid)


def test_basic_pdf_recognition(sheet):
    r=recognize(sheet,60)
    assert not r.error
    assert r.code=='000123'
    assert [a['answer'] for a in r.answers]==[i%5+1 for i in range(60)]
    assert all(a['flag']=='clear' for a in r.answers)


@pytest.mark.parametrize('angle',[90,180,270])
def test_rotated_sheets(sheet,angle):
    r=recognize(sheet.rotate(angle,expand=True),60)
    assert not r.error
    assert [a['answer'] for a in r.answers]==[i%5+1 for i in range(60)]


def test_skew_perspective_jpeg(sheet):
    img=np.array(sheet);h,w=img.shape[:2]
    src=np.float32([[0,0],[w-1,0],[w-1,h-1],[0,h-1]])
    dst=np.float32([[12,25],[w-21,6],[w-1,h-25],[28,h-3]])
    transformed=Image.fromarray(cv2.warpPerspective(img,cv2.getPerspectiveTransform(src,dst),(w,h),borderValue=(255,255,255))).filter(ImageFilter.GaussianBlur(.5))
    buf=BytesIO();transformed.save(buf,format='JPEG',quality=65);transformed=Image.open(BytesIO(buf.getvalue()))
    r=recognize(transformed,60)
    assert not r.error
    assert [a['answer'] for a in r.answers]==[i%5+1 for i in range(60)]


def test_blank_multiple_faint(tmp_path):
    p=tmp_path/'blank.pdf';sheet_pdf(p,5);img=next(load_pages(p))[1]
    from localomr.omr import align
    normal,_=align(img);draw=ImageDraw.Draw(normal)
    for k in (1,2):
        x,y=answer_centers(1)[k-1];draw.ellipse((x-10,y-10,x+10,y+10),fill='black')
    x,y=answer_centers(2)[2];draw.ellipse((x-10,y-10,x+10,y+10),fill=(150,150,150))
    r=recognize(normal,5)
    assert r.answers[0]['flag']=='blank'
    assert r.answers[1]['flag']=='multiple' and r.answers[1]['answer'] is None
    assert r.answers[2]['flag']=='faint'
    assert r.code is None


def test_unknown_sheet_fails():
    r=recognize(Image.new('RGB',(WIDTH,HEIGHT),'white'),10)
    assert r.error and r.normalized is None and all(a['flag']=='failed' for a in r.answers)


def test_missing_marker_fails(sheet):
    # Remove a generous corner; other three registration markers are not enough.
    im=sheet.copy();ImageDraw.Draw(im).rectangle((0,0,140,140),fill='white')
    assert recognize(im,60).error


def test_same_file_duplicate_import(store,tmp_path):
    s,student,eid=store;p=tmp_path/'sample.pdf';sheet_pdf(p,5,'sample','000123',[1,2,3,4,5])
    first=import_files(s.path,eid,[p]);second=import_files(s.path,eid,[p])
    assert first['added']==1 and second['duplicate']==1
    assert len(s.scans(eid))==1 and not s.results(eid)


def test_original_and_corrected_answers_preserved(store,tmp_path):
    s,student,eid=store;sid=scan(s,student,eid,tmp_path,[5,2,3,4,5])
    s.save_review(sid,student,[1,2,3,4,5],[True]*5,True,'오인식 수정')
    row=s.scan(sid)
    assert row['reading'][0]['answer']==5 and row['answers'][0]==1
    s.confirm(sid);assert s.results(eid)[0]['score']==2000
    assert s.rows("SELECT * FROM audit WHERE kind='review_saved'")


@pytest.mark.parametrize('identity,reviewed',[(False,[True]*5),(False,[True,True,False,True,True])])
def test_cannot_confirm_without_identity(store,tmp_path,identity,reviewed):
    s,student,eid=store;sid=scan(s,student,eid,tmp_path)
    s.save_review(sid,student,[1,2,3,4,5],reviewed,identity)
    with pytest.raises(ValueError):s.confirm(sid)
    assert not s.results(eid)


def test_replacement_is_explicit_and_one_official(store,tmp_path):
    s,student,eid=store;first=scan(s,student,eid,tmp_path,tag='first');confirm(s,first,student)
    second=scan(s,student,eid,tmp_path,[5,2,3,4,5],tag='second');s.save_review(second,student,[5,2,3,4,5],[True]*5,True)
    with pytest.raises(ValueError,match='DUPLICATE'):s.confirm(second)
    assert s.scan(first)['status']=='confirmed' and len(s.results(eid))==1
    s.confirm(second,replace=True)
    assert s.scan(first)['status']=='superseded' and s.results(eid)[0]['id']==second
    assert s.averages(eid)==(18,1)


def test_class_snapshot_survives_transfer(store,tmp_path):
    s,student,eid=store;sid=scan(s,student,eid,tmp_path);confirm(s,sid,student);old=s.student(student)['class_id']
    aid=s.academy('새 학원');new=s.classroom(aid,'B반');s.save_student('123','샘플학생',new,student)
    assert s.scan(sid)['snapshot']['class_id']==old
    assert s.averages(eid,old)==(20,1) and s.averages(eid,new)==(None,0)


def test_key_change_regrades_and_reopens(store,tmp_path):
    s,student,eid=store;sid=scan(s,student,eid,tmp_path);confirm(s,sid,student)
    s.save_exam('주간 평가','수학 주간','수학','1','2026-10-18',[5,2,3,4,5],[2,3,4,5,6],eid)
    row=s.scan(sid)
    assert row['score']==1800 and row['status']=='pending' and row['reviewed']==[False,True,True,True,True]
    assert row['key_revision']==2 and s.averages(eid)==(None,0)
    confirm(s,sid,student);assert s.averages(eid)==(18,1)


def test_point_change_preserves_verified_answers(store,tmp_path):
    s,student,eid=store;sid=scan(s,student,eid,tmp_path);confirm(s,sid,student)
    s.save_exam('주간 평가','수학 주간','수학','1','2026-10-18',[1,2,3,4,5],['2.25',3,4,5,6],eid)
    assert s.scan(sid)['status']=='confirmed' and s.averages(eid)==(20.25,1)


def test_question_count_cannot_change_after_import(store,tmp_path):
    s,student,eid=store;scan(s,student,eid,tmp_path)
    with pytest.raises(ValueError):s.save_exam('주간 평가','수학 주간','수학','1','2026-10-18',[1],[5],eid)
    assert len(s.exam(eid)['key'])==5


def test_backup_round_trip_includes_images_and_audit(store,tmp_path):
    s,student,eid=store;sid=scan(s,student,eid,tmp_path);confirm(s,sid,student)
    before=s.scan(sid);backup=s.backup(tmp_path/'backup.omrbackup')
    s.set_status(sid,'excluded');s.save_student('999','추가학생',s.student(student)['class_id'])
    safety=s.restore(backup)
    assert safety.exists() and len(s.students())==1 and s.averages(eid)==(20,1)
    assert s.scan(sid)['raw']==before['raw']
    assert s.rows("SELECT * FROM audit WHERE kind='review_saved'")


def test_invalid_restore_keeps_live_data(store,tmp_path):
    s,student,eid=store;p=tmp_path/'invalid.omrbackup';p.write_bytes(b'not a database')
    with pytest.raises(sqlite3.DatabaseError):s.restore(p)
    assert len(s.students())==1 and len(s.exams())==1


@pytest.mark.parametrize('bad',['NaN','Infinity','-1','1.123','abc'])
def test_invalid_points(bad):
    with pytest.raises(ValueError):points_cents(bad)


def test_inactive_and_homonym_students(store):
    s,student,eid=store;cid=s.student(student)['class_id'];second=s.save_student('124','샘플학생',cid)
    assert len(s.students('샘플학생'))==2 and second!=student
    with pytest.raises(sqlite3.IntegrityError):s.save_student('123','다른학생',cid)


def test_pdf_report_one_a4_page_per_student(store,tmp_path):
    s,student,eid=store;sid=scan(s,student,eid,tmp_path);confirm(s,sid,student);out=tmp_path/'report.pdf';report_pdf(out,s,[sid])
    import pypdfium2
    with pypdfium2.PdfDocument(out) as doc:
        assert len(doc)==1
        page=doc[0];w,h=page.get_size();assert abs(w-595.28)<1 and abs(h-841.89)<1
        textpage=page.get_textpage();text=textpage.get_text_range();textpage.close();page.close()
        assert '개인 성적표' in text and '샘플학생' in text and '20 / 20' in text


def test_cancel_keeps_already_imported_pages(store,tmp_path):
    s,student,eid=store;p=tmp_path/'sample.pdf';sheet_pdf(p,5)
    result=import_files(s.path,eid,[p],cancelled=lambda:True)
    assert result['cancelled'] and result['added']==0
