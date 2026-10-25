import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication,QMessageBox
from localomr.store import Store,SCHEMA_VERSION
from localomr.examdata import effective
from localomr.manualui import ManualPage
from localomr.studentdata import plan_students,read_students,template_path
from localomr.ui import MainWindow,StudentDialog,ReviewDialog
from test_math import KEY,CONFIG,scan

@pytest.fixture
def setup(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    db=Store(tmp_path/'db.sqlite3');cid=db.classroom(db.academy('학원'),'A반');student=db.save_student_contact('학생가','0012',class_id=cid)
    eid=db.save_exam('시험','시리즈','수학','1','2026-10-18',KEY,[3]*30,config=CONFIG)
    warnings=[];monkeypatch.setattr(QMessageBox,'warning',lambda *a:warnings.append(str(a[-1])));monkeypatch.setattr(QMessageBox,'information',lambda *a:None);monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes)
    yield db,student,eid,cid,warnings
    db.close()

def test_phone_code_required_optional_and_update(setup):
    db,s,e,c,w=setup;assert db.student(s)['code']=='000121'
    second=db.save_student_contact('학생나','010-9000-0012',school='예제고',parent_phone='010-3000-0044')
    assert db.student(second)['code']=='000122' and db.student(second)['school']=='예제고' and db.student(second)['classroom']=='미배정'
    db.save_student_contact('학생가','010-1234-0012',student_id=s,class_id=c);assert db.student(s)['code']=='000121'
    db.save_student_contact('학생가','9876',student_id=s,class_id=c);assert db.student(s)['code']=='098761'
    for name,phone in [('','1234'),('이름',''),('이름','12'),('이름','010-abcd-1234')]:
        with pytest.raises(ValueError):db.save_student_contact(name,phone)

def test_batch_students_duplicate_validation_and_atomicity(setup):
    db,s,e,c,w=setup
    rows=[dict(name='학생나',phone='0012',school='예제고'),dict(name='학생다',phone='010-7777-0012',academy='새학원',classroom='B반')]
    plan=plan_students(db,rows);assert [r['code'] for r in plan]==['000122','000123']
    added,skipped=db.import_students(rows);assert len(added)==2 and skipped==0
    assert db.student(added[1])['classroom']=='B반'
    assert db.import_students(rows)==([],2)
    before=len(db.students())
    with pytest.raises(ValueError):db.import_students([dict(name='정상',phone='9999'),dict(name='오류',phone='')])
    assert len(db.students())==before
    with pytest.raises(ValueError):db.import_students([dict(name=f'중복{i}',phone='0012') for i in range(8)])
    assert len(db.students())==before

def test_student_workbook_template_and_parser(setup,tmp_path):
    from openpyxl import load_workbook
    # Test fixture changes only. Deliverable template is authored by Artifact Tool.
    wb=load_workbook(template_path());sheet=wb['학생등록'];assert sheet['B9'].number_format=='@'
    sheet.append(['예제학생','0043','예제고','01012345678','학원','반'])
    path=tmp_path/'students.xlsx';wb.save(path);wb.close()
    rows=read_students(path);assert rows[0]['phone']=='0043' and rows[0]['name']=='예제학생'
    db,*_=setup;ids,_=db.import_students(rows);assert db.student(ids[0])['code']=='000431'

def test_blank_ox_manual_zero_fullmarks_and_reload(setup):
    db,s,e,c,w=setup;p=ManualPage(db);p.refresh();p.load(e,s)
    assert not db.results(e) and all(b.text()=='' for b in p.ox) and all(x.text()=='' for x in p.earned)
    p.choice.setCurrentIndex(p.choice.findData('1'));p.toggle(0)
    assert p.ox[0].text()=='O' and p.inputs[0].text()==str(KEY[0])
    p.toggle(0);assert p.ox[0].text()=='X' and p.inputs[0].text()=='' and p.earned[0].text()=='0'
    p.type_answer(15,'0');assert p.state['answers'][15]==0 and p.state['entered'][15]
    sid=p.save();assert sid and not db.results(e) and db.scan(sid)['status']=='pending'
    p.full_marks();p.save();assert db.results(e)[0]['score']==9000 and len(db.results(e))==1
    p.load(e,s);assert all(b.text()=='O' for b in p.ox)
    p.clear_answers();assert all(b.text()=='' for b in p.ox);p.save();assert db.results(e)[0]['score']==9000
    p.full_marks();p.toggle(0);p.save();assert len(db.results(e))==1 and db.results(e)[0]['score']==8700
    assert not w;p.close()

def test_scan_data_loaded_preserved_and_manual_replaces_without_losing_image(setup):
    db,s,e,c,w=setup;answers=KEY.copy();answers[0]=None;scan(db,e,s,'1','scan',answers)
    original=db.official_id(e,s);p=ManualPage(db);p.refresh();p.load(e,s)
    assert p.state['answers']==answers and p.ox[0].text()=='X' and p.earned[0].text()=='0'
    p.toggle(0);new=p.save();assert new!=original and db.scan(original)['status']=='superseded' and db.scan(original)['raw']
    assert db.results(e)[0]['score']==9000;p.close()

def test_choice_change_clears_only_tail_and_unsaved_survives_switch(setup):
    db,s,e,c,w=setup;other=db.save_student_contact('다른학생','8888');p=ManualPage(db);p.refresh();p.load(e,s);p.choice.setCurrentIndex(1);p.full_marks()
    p.choice.setCurrentIndex(2);assert p.state['answers'][:22]==KEY[:22] and p.state['answers'][22:]==[None]*8
    p.load(e,other);assert not any(p.state['entered']);p.load(e,s);assert all(p.state['entered'][:22]) and p.has_unsaved();p.discard_all();p.close()

def test_manual_stale_revision_and_duplicate_guard(setup):
    db,s,e,c,w=setup;sid=db.save_manual(e,s,'1',KEY,[True]*30,1)
    with pytest.raises(ValueError,match='변경'):db.save_manual(e,s,'1',KEY,[True]*30,1)
    with pytest.raises(ValueError,match='DUPLICATE'):db.save_manual(e,s,'1',KEY,[True]*30,1,expected_official_id=sid)
    key=KEY.copy();key[0]=2;db.save_exam('시험','시리즈','수학','1','2026-10-18',key,[3]*30,e,CONFIG)
    with pytest.raises(ValueError,match='정답'):db.save_manual(e,s,'1',KEY,[True]*30,1)
    p=ManualPage(db);p.refresh();p.load(e,s);p.full_marks();assert p.save();assert db.results(e)[0]['score']==9000;p.close()

def test_contact_and_manual_backup_round_trip(setup,tmp_path):
    db,s,e,c,w=setup;sid=db.save_manual(e,s,'1',KEY,[True]*30,1);backup=tmp_path/'copy.omrbackup';db.backup(backup)
    db.save_student_contact('학생가','0012',parent_phone='01011112222',student_id=s,class_id=c);db.restore(backup)
    assert db.student(s)['phone']=='0012' and not db.student(s)['parent_phone'] and db.scan(sid)['input_mode']=='manual'
    assert db.db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION

def test_chunked_source_export_cancel_and_old_blob(setup,tmp_path):
    db,*_=setup;p=tmp_path/'big.pdf';content=b'abcdefgh'*400000;p.write_bytes(content)
    sid=db.source(p);assert db.db.execute('SELECT length(data) FROM sources WHERE id=?',(sid,)).fetchone()[0]==0
    assert db.db.execute('SELECT COUNT(*) FROM source_parts WHERE source_id=?',(sid,)).fetchone()[0]>1
    exported=tmp_path/'export.pdf';db.export_source(sid,exported);assert exported.read_bytes()==content and db.source(p)==sid
    backup=tmp_path/'chunks.omrbackup';db.backup(backup);db.restore(backup);db.export_source(sid,exported);assert exported.read_bytes()==content
    with pytest.raises(InterruptedError):db.source(p,lambda:True)
    legacy=db.db.execute("INSERT INTO sources(hash,name,data) VALUES('legacy','old',?)",(b'old bytes',)).lastrowid;db.db.commit();db.export_source(legacy,exported);assert exported.read_bytes()==b'old bytes'

def test_import_context_outside_student_requires_manual_connection(setup):
    db,s,e,c,w=setup;scan(db,e,s);sid=db.official_id(e,s);db.set_status(sid,'pending')
    other=db.classroom(db.academy('학원'),'B반');assert db.set_import_context(sid,None,other)
    data=db.scan(sid);assert data['student_id'] is None and '소속' in data['import_context']['notice'] and not data['identity_ok']

def test_student_dialog_and_mainwindow_manual_navigation(setup):
    db,s,e,c,w=setup;dialog=StudentDialog(db);dialog.name.setText('신입');dialog.phone.setText('4455');dialog.save();assert dialog.student_id
    window=MainWindow(db);window.score_exam.setCurrentIndex(1);window.show();QApplication.processEvents();assert window.pages.count()==7
    sid=db.save_manual(e,s,'1',KEY,[True]*30,1);window.refresh();window.review_answer(sid);assert window.nav.currentRow()==4 and window.manual.current==(e,s)
    # QWidget teardown only; the fixture owns this database.
    window.hide();window.deleteLater();QApplication.processEvents();assert not w
