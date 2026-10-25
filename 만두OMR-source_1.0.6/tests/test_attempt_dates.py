from datetime import date
import sqlite3
import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication
from PIL import Image
from localomr.store import Store,SCHEMA_VERSION,validate_sat_on
from localomr.importer import import_files
from localomr.omr import ReadResult
from localomr.ui import MainWindow,ReviewDialog,ImportWorker
from localomr.report_math import report_history
from localomr.reports import report_pdf
from test_manual_students import setup
from test_math import KEY,CONFIG,scan


@pytest.mark.parametrize('value',['2026-02-30','2026-1-1','20261018',''])
def test_invalid_attempt_dates(value):
    with pytest.raises(ValueError,match='응시일자'):validate_sat_on(value)


def test_import_date_and_duplicate_keep_original_date(setup,tmp_path,monkeypatch):
    db,s,e,*_=setup;path=tmp_path/'scan.png';path.write_bytes(b'original')
    read=ReadResult(None,[{'answer':a,'flag':'clear','levels':[]} for a in KEY],None);read.elective='1'
    monkeypatch.setattr('localomr.importer.load_pages',lambda _:iter([(1,Image.new('RGB',(20,20),'white'))]))
    monkeypatch.setattr('localomr.importer.recognize_math',lambda _:read)
    assert import_files(db.path,e,[path],sat_on='2026-10-01')['added']==1
    row=db.scans(e)[0];assert row['sat_on']=='2026-10-01'
    assert import_files(db.path,e,[path],sat_on='2026-10-02')['duplicate']==1
    assert db.scan(row['id'])['sat_on']=='2026-10-01'
    monkeypatch.setattr('localomr.importer.load_pages',lambda _:iter([(1,Image.new('RGB',(20,20),'gray'))]))
    assert import_files(db.path,e,[path])['added']==1
    assert db.scans(e)[-1]['sat_on']==date.today().isoformat()


def test_manual_dates_survive_edit_and_backup(setup,tmp_path):
    db,s,e,*_=setup
    first=db.save_manual(e,s,'1',KEY,[True]*30,1,sat_on='2026-10-02')
    second=db.save_manual(e,s,'1',KEY,[True]*30,1,first,first,True)
    assert db.scan(second)['sat_on']=='2026-10-02'
    third=db.save_manual(e,s,'1',KEY,[True]*30,1,second,second,True,sat_on='2026-10-03')
    assert db.scan(first)['sat_on']=='2026-10-02' and db.results(e)[0]['day']=='2026-10-03'
    path=tmp_path/'date.omrbackup';db.backup(path);db.restore(path)
    assert db.scan(third)['sat_on']=='2026-10-03'


def test_v3_date_migration_and_registration_date_independence(setup,tmp_path):
    db,s,e,*_=setup;sid=scan(db,e,s);path=tmp_path/'v3.omrbackup';db.backup(path)
    old=sqlite3.connect(path);old.execute('ALTER TABLE scans DROP COLUMN sat_on');old.execute('PRAGMA user_version=3');old.commit();old.close()
    db.restore(path);assert db.scan(sid)['sat_on']=='2026-10-18'
    db.save_exam('시험','시리즈','수학','1','2026-11-01',KEY,[3]*30,e,CONFIG)
    row=db.results(e)[0];assert row['day']=='2026-10-18' and row['exam_day']=='2026-11-01'
    assert db.db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION


def test_history_and_pdf_follow_actual_date(setup,tmp_path):
    import pypdfium2 as pdfium
    db,s,e,*_=setup;first=db.save_manual(e,s,'1',KEY,[True]*30,1,sat_on='2026-10-12')
    other=db.save_exam('시험2','시리즈','수학','2','2026-11-01',KEY,[3]*30,config=CONFIG)
    second=db.save_manual(other,s,'1',KEY,[True]*30,1,sat_on='2026-10-02')
    rows=db.results(student_id=s);assert [r['id'] for r in rows]==[first,second]
    assert [r['day'] for r in report_history(db,rows[0])]==['2026-10-02','2026-10-12']
    path=tmp_path/'dates.pdf';report_pdf(path,db,[first])
    with pdfium.PdfDocument(str(path)) as doc:
        page=doc[1];tp=page.get_textpage();text=tp.get_text_range();tp.close();page.close()
    assert '성적 추이 분석' in text and '응시일자' in text
    assert text.count('2026-10-02')==2 and text.count('2026-10-12')==2 and '2026-11-01' not in text


def test_ui_date_defaults_manual_cache_and_worker_context(setup,monkeypatch):
    db,s,e,*_=setup;window=MainWindow(db);window.score_exam.setCurrentIndex(1);page=window.manual;page.open_student(e,s)
    assert window.score_sat_on.date()==QDate.currentDate() and page.sat_on.date()==QDate.currentDate()
    page.choice.setCurrentIndex(page.choice.findData('1'));page.sat_on.setDate(QDate(2026,10,5));page.full_marks();page.stash();page.refresh()
    assert page.state['sat_on']=='2026-10-05';sid=page.save();assert db.scan(sid)['sat_on']=='2026-10-05'
    captured=[]
    def fake_import(*args):captured.append(args[-1]);return dict(added=0,duplicate=0,failed=0,errors=[],cancelled=False)
    monkeypatch.setattr('localomr.ui.import_files',fake_import)
    worker=ImportWorker(db.path,e,[],sat_on='2026-10-06');worker.run();assert captured==['2026-10-06']
    window.hide();window.deleteLater();QApplication.processEvents()


def test_review_changes_date_without_changing_exam_date(setup):
    db,s,e,*_=setup;sid=scan(db,e,s);db.set_status(sid,'pending');dialog=ReviewDialog(db,sid)
    dialog.sat_on.setDate(QDate(2026,10,3));dialog.persist();db.confirm(sid)
    assert db.results(e)[0]['day']=='2026-10-03' and db.exam(e)['day']=='2026-10-18'
    dialog.dirty=False;dialog.close()
