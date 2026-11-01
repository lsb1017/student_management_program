"""Offscreen UI simulation: start session, visit every page, drive the main screens, close → upload."""
import json
import pytest
from PySide6.QtWidgets import QApplication,QMessageBox,QDialog
from PySide6.QtCore import Qt
from academy.app import App
from academy.ui.common import STYLE
from academy.ui.main_window import MainWindow
from academy.ui.start import StartDialog


@pytest.fixture
def qt(monkeypatch):
    app=QApplication.instance() or QApplication([]);app.setStyleSheet(STYLE)
    shown=[]
    monkeypatch.setattr(QMessageBox,'information',lambda *a,**k:shown.append(a[2] if len(a)>2 else ''))
    monkeypatch.setattr(QMessageBox,'warning',lambda *a,**k:shown.append('WARN '+(a[2] if len(a)>2 else '')))
    return app,shown


def test_start_dialog_pages_and_close_uploads(qt,tmp_path,monkeypatch):
    app,shown=qt
    drive=tmp_path/'drive';a=App(tmp_path/'pc_a',drive)
    start=StartDialog(a);start.operator.setText('조교A');start.academy.setCurrentText('청솔')
    start.start();assert start.session and start.session.mode=='online'
    window=MainWindow(a,start.service,start.session);window.show()
    store=window.store
    assert store.rows("SELECT name FROM operators")[0]['name']=='조교A'
    for i in range(window.nav.count()):
        window.nav.setCurrentRow(i);app.processEvents()
    assert not [s for s in shown if str(s).startswith('WARN')]
    # 학생·분반 → 수기 입력 화면이 분반 학생을 행으로 보여 줌
    cid=store.classroom(store.academy('청솔'),'청솔(토)','토')
    s1=store.save_student_contact('김민수','010-1111-5678',class_id=cid);s2=store.save_student_contact('이영희','010-2222-1234',class_id=cid)
    window.nav.setCurrentRow(4);entries_page=window.pages[4];entries_page.refresh();entries_page.load()
    assert entries_page.table.rowCount()==2
    QApplication.clipboard().setText('15\tA\n\tC\n')
    entries_page.table.setCurrentCell(0,2);entries_page.paste();entries_page.save()
    grid={r['name']:(r['mini_score'],r['homework']) for r in __import__('academy.services.entries',fromlist=['x']).grid(store,cid,entries_page.day.date().toString('yyyy-MM-dd'))}
    assert grid=={'김민수':(15.0,'A'),'이영희':(None,'C')}
    window.nav.setCurrentRow(1);assert window.pages[1].table.rowCount()==2
    window.nav.setCurrentRow(8);settings=window.pages[8];settings.edits['viewer_url'].setText('https://script.google.com/macros/s/X/exec');settings.save()
    assert store.setting('viewer_url')=='https://script.google.com/macros/s/X/exec'
    window.close();assert window.closing_done
    assert list(drive.glob('*_청솔.omrbackup')) and not list((drive/'locks').iterdir())
    # second PC sees the same data
    b=App(tmp_path/'pc_b',drive);start=StartDialog(b);start.operator.setText('조교B');start.academy.setCurrentText('청솔');start.start()
    assert len(start.session.store.students())==2
    start.service.close_session(start.session.store,'청솔');start.session.store.close()


def test_review_confirms_the_selected_answer(qt,tmp_path,monkeypatch):
    from core.omr import ReadResult
    app,shown=qt
    a=App(tmp_path/'pc',tmp_path/'drive');start=StartDialog(a);start.operator.setText('A');start.academy.setCurrentText('청솔');start.start()
    window=MainWindow(a,start.service,start.session);store=window.store
    cid=store.classroom(store.academy('청솔'),'청솔(토)','토')
    ids=[store.save_student(c,n,cid) for c,n in (('1111111','가'),('2222222','나'))]
    eid=store.save_exam('시험','시리즈','수학','1','2026-11-01',[1,2,3],[1,1,1],exam_kind='weekly')
    for i,sid in enumerate(ids):
        source=store.db.execute('INSERT INTO sources(hash,name) VALUES(?,?)',(f's{i}','s')).lastrowid;store.db.commit()
        store.add_scan(eid,source,1,f'p{i}',b'',ReadResult(None,[{'answer':1,'flag':'clear','levels':[]}]*3,None),sat_on='2026-11-01',class_id=cid)
    window.nav.setCurrentRow(3);page=window.pages[3];page.refresh();page.exam.setCurrentIndex(page.exam.findData(eid));page.load_scans()
    page.table.selectRow(1);page.show_scan()
    page.student.setCurrentIndex(page.student.findData(ids[1]));page.identity.setChecked(True);page.confirm()
    statuses={s['id']:s['status'] for s in store.scans(eid)}
    second=page.table.item(1,0).data(Qt.ItemDataRole.UserRole)
    assert statuses[second]=='confirmed' and list(statuses.values()).count('confirmed')==1
    assert page.table.current_id()==second
    window.closing_done=True;store.close()


def test_upload_failure_on_close_can_leave_lock(qt,tmp_path,monkeypatch):
    app,shown=qt
    a=App(tmp_path/'pc',tmp_path/'drive');start=StartDialog(a);start.operator.setText('A');start.academy.setCurrentText('청솔');start.start()
    window=MainWindow(a,start.service,start.session);store=window.store;store.classroom(store.academy('청솔'),'반')
    start.service.remote.fail.add('upload_backup')
    def choose_leave(box):
        for b in box.buttons():
            if b.text()=='잠금 유지한 채 종료':box.clickedButton=lambda b=b:b
        return 0
    monkeypatch.setattr(QMessageBox,'exec',choose_leave)
    window.close();assert window.closing_done and start.service.holding_lock()
