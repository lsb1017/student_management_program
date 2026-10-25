import re,sqlite3
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QMessageBox,QFileDialog,QDialog,QLabel,QPushButton
from localomr import storage
from localomr.backupui import BackupNameDialog
from localomr.handoff import revision
from localomr.storageui import StorageDialog
from localomr.busy import ManduProgressBar
from test_v0411 import fixture,add_scan


def test_backup_naming_dialog_scope_and_remembered_choices(fixture):
    app,db,w,e,student,c,warnings=fixture
    aid=db.academy('다른학원');other=db.classroom(aid,'다른반')
    dlg=BackupNameDialog(db,{'backup_academy':'가상학원','backup_classroom':'가상반'},w)
    assert dlg.names()==('가상학원','가상반')
    assert dlg.classroom.findData(other)==-1
    dlg.academy.setCurrentIndex(dlg.academy.findData(aid))
    assert dlg.classroom.findData(c)==-1 and dlg.classroom.findData(other)>0
    dlg.classroom.setCurrentIndex(dlg.classroom.findData(other));assert dlg.names()==('다른학원','다른반')
    assert '_다른학원_다른반.omrbackup' in dlg.filename_preview.text()
    missing=BackupNameDialog(db,{'backup_academy':'삭제된학원','backup_classroom':'가상반'},w)
    assert missing.names()==('전체 학원','전체 반')
    dlg.deleteLater();missing.deleteLater()


def test_backup_cancel_and_named_full_roundtrip(fixture,tmp_path,monkeypatch):
    app,db,w,e,student,c,warnings=fixture
    aid=db.academy('다른학원');cid=db.classroom(aid,'다른반');db.save_student_contact('다른학생','5678',class_id=cid)
    before=revision(db);state=dict(w.handoff.state)
    monkeypatch.setattr(BackupNameDialog,'exec',lambda self:QDialog.DialogCode.Rejected)
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**kw:pytest.fail('Name dialog was cancelled'))
    assert w.backup(other_location=True) is False and revision(db)==before and w.handoff.state==state
    def choose(dlg):
        dlg.academy.setCurrentIndex(dlg.academy.findText('가상학원'));dlg.classroom.setCurrentIndex(dlg.classroom.findData(c));return QDialog.DialogCode.Accepted
    monkeypatch.setattr(BackupNameDialog,'exec',choose)
    defaults=[];path=tmp_path/'named.omrbackup'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**kw:defaults.append(a[2]) or (str(path),''))
    monkeypatch.setattr(QMessageBox,'exec',lambda self:QMessageBox.StandardButton.Ok)
    assert w.backup(other_location=True) is True and not warnings
    assert re.match(r'\d{8}_\d{4}_가상학원_가상반\.omrbackup$',defaults[0])
    with sqlite3.connect(path) as b:
        assert b.execute('SELECT COUNT(*) FROM students').fetchone()[0]==3
        assert b.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert w.handoff.state['backup_academy']=='가상학원' and w.handoff.state['backup_classroom']=='가상반'
    assert revision(db)==before and not w.handoff.needs_backup()
    assert w.handoff.filename('가상학원','가상반').endswith('_2.omrbackup')
    assert '/' not in w.handoff.filename('학원/본원','반:1')


def test_pending_navigation_cancel_move_confirmed_and_other_exam(fixture,tmp_path,monkeypatch):
    app,db,w,e,student,c,warnings=fixture
    pending=add_scan(db,e,student,tmp_path)
    other=db.save_exam('다른시험','다른','수학','1','2026-10-21',[1,2,3],[2,3,4]);add_scan(db,other,student,tmp_path)
    w.refresh();w.startup_backup_ready=True;w.score_exam.setCurrentIndex(w.score_exam.findData(e));w.nav.setCurrentRow(3)
    calls=[]
    monkeypatch.setattr('localomr.popups.ask',lambda *a:calls.append(a) or QMessageBox.StandardButton.Cancel)
    w.nav.setCurrentRow(5)
    assert w.pages.currentIndex()==w.nav.currentRow()==3
    assert '1장' in calls[0][2] and calls[0][3]=='smart_mandu.png' and calls[0][5]==QMessageBox.StandardButton.Cancel
    monkeypatch.setattr('localomr.popups.ask',lambda *a:QMessageBox.StandardButton.Yes)
    w.nav.setCurrentRow(0);assert w.pages.currentIndex()==0
    w.nav.setCurrentRow(3);db.confirm(pending)
    monkeypatch.setattr('localomr.popups.ask',lambda *a:pytest.fail('No pending rows in selected exam'))
    w.nav.setCurrentRow(5);assert w.pages.currentIndex()==5


def test_recent_48_hours_protected_even_through_purge_and_broaden(fixture,tmp_path):
    app,db,w,e,student,c,warnings=fixture
    ids=[]
    for index,hours in enumerate((1,47,49)):
        # Distinct pixel identity so source de-duplication does not merge test pages.
        from localomr.omr import ReadResult
        source=tmp_path/f'input{index}.png';source.write_bytes(b'source'+bytes([index]))
        sid,_=db.add_scan(e,db.source(source),1,f'pixel{index}',b'image',ReadResult(None,[{'answer':a,'flag':'clear','levels':[]} for a in [1,2,3]],None))
        test_student=db.save_student_contact(f'보관검증{index}',f'88{index:02}',class_id=c)
        db.save_review(sid,test_student,[1,2,3],[False]*3,True)
        with db.transaction():
            db.db.execute("UPDATE scans SET status='confirmed',created_at=? WHERE id=?",((datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat(timespec='seconds'),sid))
        ids.append(sid)
    assert [r['id'] for r in storage.candidates(db,2)]==[ids[2]]
    for days in (-1,):
        with pytest.raises(ValueError):storage.candidates(db,days)
        with pytest.raises(ValueError):storage.purge(db,[ids[0]],days)
    with pytest.raises(ValueError):storage.purge(db,[ids[0]],2)
    assert db.scan(ids[0])['raw']==b'image'
    dlg=StorageDialog(db,w);dlg.days.setValue(0);assert dlg.days.value()==0
    dlg.broaden();assert dlg.days.value()==2 and dlg.table.rowCount()==1
    assert not dlg.preview_clean.isEnabled()
    storage.purge(db,[ids[2]],2)
    assert db.scan(ids[2])['raw']==b'' and db.scan(ids[1])['raw']==b'image'
    assert {r['id'] for r in storage.candidates(db,0)}==set(ids[:2])
    storage.purge(db,[ids[0]],0)
    assert db.scan(ids[0])['raw']==b'' and db.scan(ids[1])['raw']==b'image'
    dlg.days.setValue(2);dlg.days.stepDown();dlg.days.stepDown();assert dlg.days.value()==0
    assert dlg.show_all.text()=='모든 시험 · 2일 이상 보기'
    dlg.deleteLater()


def test_progress_sprite_is_transparent_and_timer_stops_hidden(fixture):
    app,db,w,*_=fixture
    bar=ManduProgressBar();bar.resize(300,18);bar.show();app.processEvents()
    assert bar.timer.isActive() and bar.sprite.hasAlphaChannel()
    assert bar.sprite.height()==60
    bar.setRange(0,100);bar.setValue(100);bar.tick();assert not bar.timer.isActive()
    bar.grab();bar.hide();assert not bar.timer.isActive();bar.deleteLater()
