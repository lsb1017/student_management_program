import json
from pathlib import Path
import pytest
from PIL import Image,ImageDraw
from PySide6.QtWidgets import QApplication,QFileDialog
from localomr.omr import ReadResult
from localomr.mathomr import recognize_math,MARKERS,SIZE
from localomr.importer import import_files,retry_failed
from localomr.ui import MainWindow,ImportWorker
from test_math import drawing,KEY,exam,store
from test_manual_students import setup


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_gray_scanner_markers_still_require_correct_form(rotation):
    image=drawing();draw=ImageDraw.Draw(image)
    for i,(x,y) in enumerate(MARKERS):draw.rectangle((x-6,y-(14 if i<2 else 6),x+6,y+(14 if i<2 else 6)),fill=(145,165,150))
    read=recognize_math(image.rotate(rotation,expand=True))
    assert not read.error and read.code=='042411' and read.elective=='1'
    assert [a['answer'] for a in read.answers]==KEY


def test_gray_markers_without_internal_grid_are_rejected():
    image=Image.new('RGB',SIZE,'white');draw=ImageDraw.Draw(image)
    for i,(x,y) in enumerate(MARKERS):draw.rectangle((x-6,y-(14 if i<2 else 6),x+6,y+(14 if i<2 else 6)),fill=(145,165,150))
    assert recognize_math(image).error


def failed_import(db,eid,path,monkeypatch):
    drawing().save(path)
    failed=ReadResult(None,[{'answer':None,'flag':'failed','levels':[]} for _ in KEY],None,error='old marker threshold')
    with monkeypatch.context() as m:
        m.setattr('localomr.importer.recognize_math',lambda _:failed)
        result=import_files(db.path,eid,[path],sat_on='2026-10-01')
    assert result['failed']==1
    return db.scans(eid)[-1]['id']


def test_duplicate_failed_retry_keeps_original_date_source_and_reviews(store,tmp_path,monkeypatch):
    db,student=store;eid=exam(db);path=tmp_path/'original.png'
    sid=failed_import(db,eid,path,monkeypatch);before=db.scan(sid)
    result=import_files(db.path,eid,[path],sat_on='2026-10-18')
    assert result['retried']==result['recovered']==1 and result['duplicate']==result['failed']==0
    after=db.scan(sid);assert after['status']=='pending' and after['answers']==KEY and not any(after['reviewed'])
    for field in ('id','source_id','page','pixel_hash','raw','sat_on','created_at'):assert after[field]==before[field]
    assert len(db.scans(eid))==1
    assert json.loads(db.rows("SELECT detail FROM audit WHERE kind='scan_retried'")[0]['detail'])['before_error']=='old marker threshold'
    altered=KEY.copy();altered[0]=5;db.save_review(sid,student,altered,[True]*30,True,elective='1');db.confirm(sid)
    assert import_files(db.path,eid,[path])['duplicate']==1 and db.scan(sid)['answers']==altered
    assert retry_failed(db.path,eid,[sid])['duplicate']==1 and db.scan(sid)['status']=='confirmed'


def test_retry_from_saved_original_cancel_and_scope_preservation(store,tmp_path,monkeypatch):
    db,student=store;eid=exam(db);sid=failed_import(db,eid,tmp_path/'original.png',monkeypatch)
    (tmp_path/'original.png').unlink()
    other=db.classroom(db.academy('다른학원'),'B반');aid=db.rows('SELECT academy_id FROM classes WHERE id=?',(other,))[0]['academy_id']
    db.set_import_context(sid,aid,other)
    assert retry_failed(db.path,eid,[sid],cancelled=lambda:True)['cancelled'] and db.scan(sid)['status']=='failed'
    result=retry_failed(db.path,eid,[sid],class_id=db.student(student)['class_id'])
    assert result['recovered']==1
    row=db.scan(sid);assert row['student_id'] is None and row['import_context']['class_id']==other and row['import_context']['identity_reading']['notice']
    assert row['sat_on']=='2026-10-01'


def test_unassigned_failed_visible_in_class_filter_and_retry_worker(setup,tmp_path,monkeypatch):
    db,student,eid,cid,_=setup;sid=failed_import(db,eid,tmp_path/'one.png',monkeypatch)
    window=MainWindow(db);window.score_exam.setCurrentIndex(1);window.score_class.setCurrentIndex(window.score_class.findData(cid));window.refresh_scans()
    assert window.scan_table.rowCount()==1 and window.retry_button.isEnabled()
    assert '시험 전체 1장' in window.scan_summary.text()
    other=db.classroom(db.academy('다른학원'),'다른반');other_aid=db.rows('SELECT academy_id FROM classes WHERE id=?',(other,))[0]['academy_id']
    db.set_import_context(sid,other_aid,other);window.refresh_scans()
    assert window.scan_table.rowCount()==0 and '시험 전체 1장' in window.scan_summary.text() and not window.retry_button.isEnabled()
    db.set_import_context(sid,None,None);window.refresh_scans()
    worker=ImportWorker(db.path,eid,[],class_id=cid,retry_ids=[sid]);results=[];worker.result.connect(results.append);worker.run()
    assert results[0]['recovered']==1 and db.scan(sid)['import_context']['class_id']==cid
    window.refresh_scans();assert window.scan_table.rowCount()==1 and window.retry_button.isEnabled()
    window.hide();window.deleteLater();QApplication.processEvents()


def test_import_requires_academy_and_class_before_file_dialog(setup,monkeypatch):
    db,student,eid,cid,warnings=setup;window=MainWindow(db);window.score_exam.setCurrentIndex(1);opened=[]
    monkeypatch.setattr(QFileDialog,'getOpenFileNames',lambda *a:(opened.append(True) or ([],'')))
    window.import_dialog();assert not opened and '학원과 반' in warnings[-1]
    with pytest.raises(ValueError,match='학원과 반'):window.start_import(eid,[])
    window.score_class.setCurrentIndex(window.score_class.findData(cid))
    window.import_dialog();assert not opened and '학원을 먼저' in warnings[-1]
    aid=db.rows('SELECT academy_id FROM classes WHERE id=?',(cid,))[0]['academy_id']
    window.score_academy.setCurrentIndex(window.score_academy.findData(aid));window.score_class.setCurrentIndex(0)
    window.import_dialog();assert not opened and '반을 먼저' in warnings[-1]
    window.score_class.setCurrentIndex(window.score_class.findData(cid));window.import_dialog()
    assert len(opened)==1 and window.worker is None
    assert window.selected_scoring_context()==(aid,cid)
    window.hide();window.deleteLater();QApplication.processEvents()
