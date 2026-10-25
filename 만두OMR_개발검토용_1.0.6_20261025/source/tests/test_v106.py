import json
import pytest
from PySide6.QtWidgets import QDialog,QFileDialog,QMessageBox
from PySide6.QtCore import Qt
from localomr.studentmerge import preview,merge
from localomr.store import Store
from localomr.ui import StudentDialog
from localomr.backupui import BackupNameDialog
from test_v0411 import fixture

def add_scan(db,e,student,tmp_path):
    from localomr.omr import ReadResult
    number=db.db.execute('SELECT COUNT(*) FROM scans').fetchone()[0]+1
    p=tmp_path/('image'+str(number)+'.png');p.write_bytes(('synthetic'+str(number)).encode())
    reading=ReadResult(None,[{'answer':a,'flag':'clear','levels':[]} for a in [1,2,3]],None)
    sid,_=db.add_scan(e,db.source(p),number,'synthetic'+str(number),b'',reading)
    db.save_review(sid,student,[1,2,3],[False]*3,True)
    return sid

def setup_pair(db,c):
    other=db.classroom(db.student(1)['academy_id'],'수12')
    return db.save_student_contact('옮길학생','9876',class_id=other),other

def test_merge_preserves_answers_confirmation_memberships_and_backup(fixture,tmp_path):
    app,db,w,e,keep,c,_=fixture;source,other=setup_pair(db,c)
    scan=add_scan(db,e,source,tmp_path);db.confirm(scan);before=db.scan(scan)
    p=preview(db,keep,source);assert not p['removed']
    backup=merge(db,keep,source,p['fingerprint']);assert backup.exists()
    after=db.scan(scan)
    for key in ['score','answers','status','reviewed','identity_ok']:assert after[key]==before[key]
    assert after['student_id']==keep and after['snapshot']['class_id']==c
    assert {m['class_id'] for m in db.memberships(keep)}=={c,other}
    assert not db.db.execute('SELECT 1 FROM students WHERE id=?',(source,)).fetchone()
    restored=Store(tmp_path/'restore.sqlite3');restored.restore(backup);assert restored.student(source);restored.close()

def test_merge_deletes_only_source_duplicates_and_manual(fixture,tmp_path):
    app,db,w,e,keep,c,_=fixture;source,_=setup_pair(db,c)
    a=add_scan(db,e,keep,tmp_path);db.confirm(a)
    b=add_scan(db,e,source,tmp_path);db.confirm(b)
    e2=db.save_exam('수기시험','시리즈','수학','8','2026-10-24',[1,2,3],[2,3,4])
    m=db.save_manual(e2,source,None,[1,2,3],[True]*3,1)
    k=db.save_manual(e2,keep,None,[1,2,3],[True]*3,1)
    p=preview(db,keep,source);assert set(p['delete_scans'])=={b,m};assert all(r['title'] for r in p['removed'])
    merge(db,keep,source,p['fingerprint'])
    assert db.scan(a)['status']=='confirmed' and db.scan(k)['status']=='confirmed'
    assert db.scan(b)['status']==db.scan(m)['status']=='deleted'

def test_merge_stale_plan_and_backup_failure_change_nothing(fixture,tmp_path,monkeypatch):
    app,db,w,e,keep,c,_=fixture;source,_=setup_pair(db,c);p=preview(db,keep,source)
    scan=add_scan(db,e,source,tmp_path)
    with pytest.raises(ValueError):merge(db,keep,source,p['fingerprint'])
    p=preview(db,keep,source)
    monkeypatch.setattr(db,'backup',lambda *a:(_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):merge(db,keep,source,p['fingerprint'])
    assert db.scan(scan)['student_id']==source and db.student(source)

def test_merge_transaction_rollback(fixture,tmp_path,monkeypatch):
    app,db,w,e,keep,c,_=fixture;source,_=setup_pair(db,c);scan=add_scan(db,e,source,tmp_path)
    p=preview(db,keep,source);original=db.log
    def fail(kind,*args):
        if kind=='students_merged':raise RuntimeError('injected failure')
        return original(kind,*args)
    monkeypatch.setattr(db,'log',fail)
    with pytest.raises(RuntimeError):merge(db,keep,source,p['fingerprint'])
    assert db.scan(scan)['student_id']==source and db.student(source)

def test_merge_undo_cannot_recreate_duplicate(fixture,tmp_path):
    app,db,w,e,keep,c,_=fixture;source,_=setup_pair(db,c)
    a=add_scan(db,e,keep,tmp_path);db.confirm(a);b=add_scan(db,e,source,tmp_path);db.confirm(b)
    db.delete_scans(e,[b]);p=preview(db,keep,source);merge(db,keep,source,p['fingerprint'])
    with pytest.raises(ValueError,match='중복'):db.restore_deleted_scans(e)
    assert db.scan(b)['status']=='deleted' and db.scan(a)['status']=='confirmed'

def test_named_automatic_backup_cancel_and_minute_filename(fixture,monkeypatch):
    app,db,w,*_=fixture
    monkeypatch.setattr(BackupNameDialog,'exec',lambda self:QDialog.DialogCode.Rejected)
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:pytest.fail('no path dialog'))
    assert w.backup() is False
    monkeypatch.setattr(BackupNameDialog,'exec',lambda self:QDialog.DialogCode.Accepted)
    monkeypatch.setattr(BackupNameDialog,'names',lambda self:('강북청솔','수12'))
    files=[];monkeypatch.setattr(w.drive,'enqueue',lambda p:files.append(p) or True)
    assert w.backup() and w.backup()
    import re
    assert re.fullmatch(r'\d{8}_\d{4}_강북청솔_수12(?:_\d+)?\.omrbackup',files[0].name)
    assert files[0]!=files[1] and all(p.exists() for p in files)

def test_duplicate_registration_adds_membership_without_new_student(fixture,monkeypatch):
    app,db,w,e,keep,c,_=fixture;old=db.student(keep);extra=db.classroom(old['academy_id'],'추가반')
    d=StudentDialog(db,parent=w);d.name.setText(old['name']);d.phone.setText(old['phone'])
    for n in range(d.extra_classes.count()):
        item=d.extra_classes.item(n)
        if item.data(Qt.ItemDataRole.UserRole)==extra:item.setCheckState(Qt.CheckState.Checked)
    monkeypatch.setattr(QMessageBox,'exec',lambda self:0)
    monkeypatch.setattr(QMessageBox,'clickedButton',lambda self:next(b for b in self.buttons() if b.text()=='기존 학생에게 반 추가'))
    count=len(db.students());d.save()
    assert d.student_id==keep and len(db.students())==count and db.in_class(keep,extra)

def test_merge_history_preserves_unique_and_removes_linked_duplicate(fixture,tmp_path):
    from test_history import add_history
    app,db,w,e,keep,c,_=fixture;source,_=setup_pair(db,c)
    scan=add_scan(db,e,keep,tmp_path);db.confirm(scan)
    add_history(db,source,'이전 중복',linked=e);add_history(db,source,'고유 이전 시험')
    p=preview(db,keep,source);assert len(p['delete_history'])==1
    merge(db,keep,source,p['fingerprint'])
    rows=db.rows('SELECT r.*,e.title FROM historical_results r JOIN historical_exams e ON e.id=r.exam_id')
    assert len(rows)==1 and rows[0]['student_id']==keep and rows[0]['title']=='고유 이전 시험'

def test_merge_confirmation_cancel_keeps_both_students(fixture,monkeypatch):
    from localomr.mergeui import MergeStudentsDialog
    app,db,w,e,keep,c,_=fixture;source,_=setup_pair(db,c)
    dialog=MergeStudentsDialog(db,w);dialog.keep.setCurrentIndex(dialog.keep.findData(keep));dialog.source.setCurrentIndex(dialog.source.findData(source))
    seen=[]
    def cancel(box):
        seen.append(box.defaultButton().text());return 0
    monkeypatch.setattr(QMessageBox,'exec',cancel)
    dialog.apply();assert seen==['취소'] and db.student(source) and db.student(keep)
    assert not (db.path.parent/'backups'/'before_student_merge').exists()
