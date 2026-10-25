import json
from pathlib import Path
import numpy as np
import pytest
from PIL import Image,ImageDraw
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QLineEdit
from PySide6.QtTest import QTest
from localomr.mathomr import recognize_math,centers,id_centers,NUMERIC
from localomr.omr import load_pages,ReadResult
from localomr.importer import import_files,reread_selected
from localomr.ui import ImportWorker
from test_math import drawing,KEY,store,exam
from test_inline_review import review,enter
from test_manual_students import setup


@pytest.mark.parametrize('shade,dx,dy',[(150,3,2),(180,-3,-2),(200,2,0)])
def test_gray_offcenter_marks_are_read_without_filling_actual_blanks(shade,dx,dy):
    expected=KEY.copy();expected[5]=None;expected[20]=None
    image=drawing(key=[None]*30,code='',choice=None);d=ImageDraw.Draw(image)
    def mark(p):
        x,y=p;d.ellipse((x+dx-5,y+dy-11,x+dx+5,y+dy+11),fill=(shade,shade,shade))
    for q,value in enumerate(expected,1):
        if value is None:continue
        if q in NUMERIC:
            for i,ch in enumerate(str(value).rjust(3)):
                if ch!=' ':mark(centers(q)[i][int(ch)])
        else:mark(centers(q)[value-1])
    for i,ch in enumerate('0042'):mark(id_centers(i)[int(ch)])
    mark((1337,156))
    result=recognize_math(image)
    assert not result.error and [a['answer'] for a in result.answers]==expected
    assert result.identity_reading['phone_tail']=='0042' and result.elective=='2'


@pytest.mark.parametrize('grayscale',[False,True])
def test_actual_empty_form_at_300dpi_does_not_read_print_as_answers(grayscale):
    path=Path(__file__).parents[1]/'assets/수능수학_기본OMR.pdf'
    _,image=next(load_pages(path));assert max(image.size)>3000
    if grayscale:image=image.convert('L').convert('RGB')
    result=recognize_math(image)
    assert not result.error and all(a['flag']=='blank' for a in result.answers)
    assert result.code is None and result.elective is None


def test_number_choice_cell_no_dropdown_delete_invalid_and_wheel(review):
    window,db,sid,student,eid,warnings=review;grid=window.scan_table;pane=window.review_pane
    grid.setCurrentCell(0,2);assert grid.cellWidget(0,2) is None
    assert '1 확통 / 2 미적분 / 3 기하' in pane.reading.text()
    assert pane.heading.text().startswith('선택과목') and not hasattr(pane,'checked')
    enter(grid,0,2,'3');assert db.scan(sid)['elective']=='3'
    grid.setCurrentCell(0,2);QTest.keyClick(grid,Qt.Key.Key_Delete);QApplication.processEvents()
    assert db.scan(sid)['elective'] is None and grid.item(0,2).text()=='—'
    enter(grid,0,2,'2');assert db.scan(sid)['elective']=='2'
    grid.item(0,2).setText('8');QApplication.processEvents()
    assert db.scan(sid)['elective']=='2' and warnings
    # Wheel over the plain cell scrolls the table; it cannot select another elective.
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtCore import QPoint,QPointF
    point=grid.visualItemRect(grid.item(0,2)).center()
    event=QWheelEvent(QPointF(point),QPointF(grid.viewport().mapToGlobal(point)),QPoint(),QPoint(0,-120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False)
    QApplication.sendEvent(grid.viewport(),event)
    assert db.scan(sid)['elective']=='2'


def test_reread_pending_preserves_manual_and_reviewed_answers_identity_date_and_confirmed(store,tmp_path):
    db,student=store;eid=exam(db);cid=db.student(student)['class_id'];aid=db.student(student)['academy_id']
    path=tmp_path/'page.png';drawing().save(path)
    import_files(db.path,eid,[path],academy_id=aid,class_id=cid,sat_on='2026-10-01')
    sid=db.scans(eid)[0]['id'];before=db.scan(sid)
    old=before['reading'];old[2]['answer']=None
    wrong=before['answers'].copy();wrong[0]=5;wrong[1]=4;wrong[2]=None
    checks=[False]*30;checks[1]=True
    db.db.execute('UPDATE scans SET reading=? WHERE id=?',(json.dumps(old),sid));db.db.commit()
    db.save_review(sid,student,wrong,checks,True,elective='2')
    result=reread_selected(db.path,eid,[sid],academy_id=aid,class_id=cid);assert result['recovered']==1
    after=db.scan(sid);assert after['answers'][:3]==[5,4,KEY[2]] and after['reviewed'][1]
    assert after['elective']=='2' and after['student_id']==student and not after['identity_ok']
    for field in ('raw','pixel_hash','source_id','page','sat_on','created_at'):assert after[field]==before[field]
    db.save_review(sid,student,after['answers'],[True]*30,True,elective='2');db.confirm(sid)
    assert reread_selected(db.path,eid,[sid],class_id=cid)['duplicate']==1 and db.scan(sid)['status']=='confirmed'


def test_duplicate_source_page_survives_different_render_resolution_and_worker_scope(store,tmp_path):
    db,student=store;eid=exam(db);cid=db.student(student)['class_id'];aid=db.student(student)['academy_id']
    path=tmp_path/'page.png';drawing().save(path);import_files(db.path,eid,[path],academy_id=aid,class_id=cid)
    row=db.scan(db.scans(eid)[0]['id']);r=recognize_math(drawing())
    assert db.add_scan(eid,row['source_id'],row['page'],'different-resolution-hash',b'new pixels',r,deduplicate_source_page=True)[1] is False
    assert reread_selected(db.path,eid,[row['id']],academy_id=aid,class_id=999)['recovered']==0
    worker=ImportWorker(db.path,eid,[],aid,cid,retry_ids=[row['id']],reread=True);results=[];worker.result.connect(results.append);worker.run()
    assert results[0]['recovered']==1


def test_pdf_reimport_after_resolution_change_does_not_duplicate(store,tmp_path,monkeypatch):
    db,student=store;eid=exam(db);path=tmp_path/'scan.pdf';drawing().save(path,'PDF')
    image=drawing();result=recognize_math(image)
    monkeypatch.setattr('localomr.importer.load_pages',lambda _:iter([(1,image)]))
    monkeypatch.setattr('localomr.importer.recognize_math',lambda _:result)
    assert import_files(db.path,eid,[path])['added']==1
    monkeypatch.setattr('localomr.importer.load_pages',lambda _:iter([(1,image.resize((3364,2380)))]))
    assert import_files(db.path,eid,[path])['duplicate']==1
    assert len(db.scans(eid))==1
