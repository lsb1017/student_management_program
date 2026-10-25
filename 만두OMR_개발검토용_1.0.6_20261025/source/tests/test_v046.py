from pathlib import Path
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox,QFileDialog
from localomr.ui import MainWindow
from localomr.handoff import Handoff
from localomr import __version__
from test_math import store,exam,scan
from test_v043 import app


def test_local_handoff_tracks_backup_and_restore_without_db_mutation(store,tmp_path):
    db,_=store;h=Handoff(db);before=db.db.total_changes
    h.state['location']='중계/김조교';h.save()
    assert db.db.total_changes==before and '_중계_김조교.omrbackup' in h.filename()
    assert not h.needs_backup();db.set_report_name('작업1');assert h.needs_backup()
    path=db.backup(tmp_path/'first.omrbackup');h.recorded('outgoing',path)
    assert not Handoff(db).needs_backup()
    db.set_report_name('작업2');assert Handoff(db).needs_backup()
    db.restore(path);h.recorded('incoming',path)
    loaded=Handoff(db)
    assert loaded.state['location']=='중계/김조교' and not loaded.needs_backup()
    assert 'first.omrbackup' in loaded.summary() and '드라이브 업로드 상태' in loaded.summary()


def test_exit_reminder_cancel_save_cancel_then_success(store,tmp_path,app,monkeypatch):
    db,_=store;w=MainWindow(db);w.score_exam.setCurrentIndex(1);db.set_report_name('종료 검증')
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Cancel)
    event=QCloseEvent();w.closeEvent(event);assert not event.isAccepted()
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('automatic backup must not prompt')))
    event=QCloseEvent();w.closeEvent(event);assert event.isAccepted()
    assert list((db.path.parent/'backups'/'automatic').glob('*.omrbackup'))
    w.hide();w.deleteLater()


def test_backup_failure_keeps_window_and_dirty_state(store,tmp_path,app,monkeypatch):
    db,_=store;w=MainWindow(db);w.score_exam.setCurrentIndex(1);db.set_report_name('미백업')
    path=tmp_path/'existing.omrbackup';path.write_bytes(b'keep')
    from localomr.store import Store
    monkeypatch.setattr(Store,'backup',lambda *a:(_ for _ in ()).throw(ValueError('저장 실패')))
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**kw:(str(path),''))
    event=QCloseEvent();w.closeEvent(event)
    assert not event.isAccepted() and w.handoff.needs_backup() and path.read_bytes()==b'keep'
    w.hide();w.deleteLater()


def test_no_change_no_exit_prompt_and_restore_keeps_local_location(store,tmp_path,app,monkeypatch):
    db,_=store;path=db.backup(tmp_path/'평촌.omrbackup');w=MainWindow(db)
    w.handoff.state['backup_academy']='중계';w.save_handoff_preferences()
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a:(str(path),''));w.restore()
    assert '평촌.omrbackup' in w.handoff_label.text() and w.handoff.state['backup_academy']=='중계'
    assert __version__ in w.windowTitle()
    monkeypatch.setattr(QMessageBox,'question',lambda *a:(_ for _ in ()).throw(AssertionError('no changes')))
    event=QCloseEvent();w.closeEvent(event);assert event.isAccepted()
    w.hide();w.deleteLater()
