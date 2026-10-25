import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from localomr.store import Store
from localomr.identity import resolve_student
from localomr.bulk_confirm import candidates
from localomr.batchui import BatchOutputDialog
from localomr.studentdata import plan_students,read_students,template_path
from localomr.drive_backup import DriveClient,digest,protect,API
from test_v0411 import fixture,add_scan

def test_backup_inspection_closes_connection_before_download_rename(tmp_path,monkeypatch):
    from localomr import backup_tools
    db=Store(tmp_path/'original.sqlite3');part=tmp_path/'incoming.part';db.backup(part);db.close()
    real=backup_tools.sqlite3.connect;opened=[]
    def keep_reference(*args,**kwargs):
        connection=real(*args,**kwargs);opened.append(connection);return connection
    monkeypatch.setattr(backup_tools.sqlite3,'connect',keep_reference)
    backup_tools.inspect_backup(part)
    with pytest.raises(backup_tools.sqlite3.ProgrammingError):opened[0].execute('SELECT 1')
    destination=part.with_suffix('.omrbackup');part.replace(destination);destination.unlink()

def test_membership_identity_history_and_manual(fixture,tmp_path):
    app,db,w,e,s,c,warnings=fixture
    other=db.classroom(db.student(s)['academy_id'],'수Ⅰ+수Ⅱ')
    db.set_student_classes(s,[c,other]);student=db.student(s)
    assert student['class_id']==c and len(db.memberships(s))==2
    read=SimpleNamespace(code=student['code'],identity_reading=None)
    found,_=resolve_student(db.db,read,student['academy_id'],other)
    assert found['id']==s and found['class_id']==other
    sid=add_scan(db,e,s,tmp_path)
    # Existing snapshot keeps the old class; a new auto-linked page uses the attended class.
    from localomr.omr import ReadResult
    rr=ReadResult(None,[{'answer':a,'flag':'clear','levels':[]} for a in [1,2,3]],student['code'])
    scan,_=db.add_scan(e,db.source(tmp_path/'image.png'),2,'second-class',b'',rr,academy_id=student['academy_id'],class_id=other)
    ready,skipped,_=candidates(db,[scan],student['academy_id'],other)
    assert ready==[scan] and not skipped, skipped
    db.save_review(scan,s,[1,2,3],[True]*3,True);db.confirm(scan)
    assert db.scan(scan)['snapshot']['class_id']==other
    db.set_student_classes(s,[c])
    assert db.results(e)[0]['snapshot']['class_id']==other
    assert resolve_student(db.db,read,student['academy_id'],other)[0] is None
    db.set_student_classes(s,[c,other]);second=db.save_exam('수기 시험','통합','수학','2','2026-10-23',[1,2,3],[2,3,4])
    manual=db.save_manual(second,s,None,[1,2,3],[True]*3,1,class_id=other)
    assert db.scan(manual)['snapshot']['class_id']==other
    assert db.db.execute('PRAGMA foreign_key_check').fetchone() is None

def test_workbook_link_is_explicit_and_preserves_student(fixture):
    app,db,w,e,s,c,warnings=fixture
    original=db.student(s)
    row={'name':original['name'],'phone':'5678','academy':original['academy'],'classroom':'추가반;두번째반','student_code':original['code'][1:]}
    assert plan_students(db,[row])[0]['action']=='link'
    added,skipped=db.import_students([row]);assert added==[s] and skipped==0
    assert db.student(s)==original and len(db.memberships(s))==3
    row['student_code']='99999'
    with pytest.raises(ValueError):db.import_students([row])
    row.pop('student_code');assert plan_students(db,[row])[0]['action']=='skip'
    fresh={'name':'새 학생','phone':'01055556666','academy':'가상학원','classroom':'수학반;실모반'}
    ids,_=db.import_students([fresh]);assert len(db.memberships(ids[0]))==2

def test_batch_scope_header_and_numeric_score_sort(fixture):
    app,db,w,e,s,c,warnings=fixture
    other=db.classroom(db.academy('다른학원'),'다른반');ss=db.save_student_contact('정렬학생','3333',class_id=other)
    db.save_manual(e,s,None,[1,2,3],[True]*3,1);db.save_manual(e,ss,None,[None,None,3],[True]*3,1)
    d=BatchOutputDialog(db,e,w,academy_id=db.student(s)['academy_id'],class_id=c)
    assert d.selected_classes()==[c]
    d.classes.header_clicked(0);assert len(d.selected_classes())==2
    d.classes.header_clicked(0);assert not d.selected_classes();d.close()
    w.refresh_results();w.result_table.sortItems(7,Qt.SortOrder.DescendingOrder)
    assert w.result_table.item(0,1).text()==db.student(s)['name']
    w.result_table.item(0,0).setCheckState(Qt.CheckState.Checked)
    selected=w.result_table.checked_ids();w.result_table.sortItems(7,Qt.SortOrder.AscendingOrder)
    assert w.result_table.checked_ids()==selected and w.result_table.item(0,1).text()=='정렬학생'
    assert w.result_choice.isHidden()

def test_membership_upgrade_backup_roundtrip(tmp_path):
    path=tmp_path/'old.sqlite3';db=Store(path);c=db.classroom(db.academy('보존'),'기존반');s=db.save_student_contact('보존학생','1234',class_id=c)
    with db.transaction():db.db.execute('DROP TABLE student_classes');db.db.execute('PRAGMA user_version=9')
    db.close();up=Store(path)
    assert len(up.memberships(s))==1
    other=up.classroom(up.student(s)['academy_id'],'추가반');up.set_student_classes(s,[c,other])
    backup=up.backup(tmp_path/'roundtrip.omrbackup');restored=Store(tmp_path/'restored.sqlite3');restored.restore(backup)
    assert restored.memberships(s)==up.memberships(s)
    assert list((tmp_path/'backups').glob('before_upgrade_v9_*.omrbackup'))
    up.close();restored.close()

def test_drive_token_encrypted_and_folder_validation(tmp_path):
    client=DriveClient(tmp_path,tmp_path/'client.json')
    client.save_token({'access_token':'synthetic-access','refresh_token':'synthetic-refresh'})
    data=client.token_path.read_bytes();assert b'synthetic' not in data
    assert json.loads(protect(data,True))['refresh_token']=='synthetic-refresh'
    assert client.folder_id('https://drive.google.com/drive/folders/abc_DEF123')=='abc_DEF123'
    with pytest.raises(ValueError):client.folder_id("a' or trashed=false")

def test_drive_upload_verified_and_retry_idempotent(tmp_path,monkeypatch):
    client=DriveClient(tmp_path,tmp_path/'client.json');file=tmp_path/'sample.omrbackup';file.write_bytes(b'backup-test')
    calls=[]
    def request(url,method='GET',body=None,headers=None,raw=False):
        calls.append((url,method,body))
        if method=='GET':raise ValueError('not found (404)')
        if method=='POST':return b'',{'Location':'https://www.googleapis.com/upload/test'}
        return {'id':'remote','md5Checksum':digest(file,'md5')}
    monkeypatch.setattr(client,'request',request)
    assert client.upload(file,'folder123','rev','remote')['id']=='remote'
    metadata=next(body for _,method,body in calls if method=='POST');assert metadata['parents']==['folder123'] and metadata['appProperties']['revision']=='rev'
    monkeypatch.setattr(client,'request',lambda *a,**k:{'id':'remote','md5Checksum':digest(file,'md5')})
    assert client.upload(file,'folder123','rev','remote')['id']=='remote'

def test_drive_queue_preserves_local_and_retries(fixture,tmp_path,monkeypatch):
    app,db,w,*_=fixture;drive=w.drive
    drive.state.update(folder='folder123',folder_name='시험용');drive.client.token_path.write_bytes(b'test')
    monkeypatch.setattr(drive,'upload_next',lambda:None)
    file=tmp_path/'local.omrbackup';file.write_bytes(b'local-backup')
    assert drive.enqueue(file)
    entry=drive.state['outbox'][0];file.write_bytes(b'changed-later')
    assert Path(entry['path']).read_bytes()==b'local-backup'
    assert json.loads(drive.path.read_text('utf-8'))['outbox'][0]['path']==entry['path']
    assert file.read_bytes()==b'changed-later'

def test_drive_retry_failure_then_success(fixture,tmp_path,monkeypatch):
    app,db,w,*_=fixture;d=w.drive
    d.state.update(folder='folder123');d.client.token_path.write_bytes(b'test')
    p=tmp_path/'backup.omrbackup';p.write_bytes(b'keep')
    def synchronous(fn,done,status,failed=None):
        try:result=fn()
        except ValueError as exc:
            if failed:failed(str(exc))
        else:done(result)
    monkeypatch.setattr(d,'run',synchronous)
    monkeypatch.setattr(d.client,'request',lambda *a,**k:{'ids':['remote']})
    monkeypatch.setattr(d.client,'upload',lambda *a,**k:(_ for _ in ()).throw(ValueError('offline')))
    d.enqueue(p);assert len(d.state['outbox'])==1 and d.retry.isActive()
    assert d.state['outbox'][0]['remote_id']=='remote' and p.read_bytes()==b'keep'
    d.retry.stop();monkeypatch.setattr(d.client,'upload',lambda *a,**k:{'id':'remote'})
    d.upload_next();assert not d.state['outbox'] and d.state['last_id']=='remote' and p.read_bytes()==b'keep'

def test_latest_backup_never_silently_restores(fixture,monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from localomr.handoff import revision
    app,db,w,*_=fixture;d=w.drive;w.show();d.state.update(folder='folder123');d.client.token_path.write_bytes(b'test')
    monkeypatch.setattr(d,'run',lambda fn,done,*a,**k:done(fn()))
    seen=[];monkeypatch.setattr(QMessageBox,'exec',lambda box:seen.append(box.text()) or 0)
    monkeypatch.setattr(d.client,'download',lambda *a:(_ for _ in ()).throw(AssertionError('must require approval')))
    monkeypatch.setattr(d.client,'latest',lambda *a:{'id':'same','name':'same.omrbackup','appProperties':{'revision':revision(db)}})
    d.check_latest();assert not seen and w.startup_backup_ready
    monkeypatch.setattr(d.client,'latest',lambda *a:{'id':'new','name':'new.omrbackup','appProperties':{'revision':'different'}})
    d.check_latest();assert len(seen)==1
    db.set_report_name('로컬 수정');d.check_latest();assert len(seen)==1

def test_template_has_explicit_membership_column():
    from openpyxl import load_workbook
    book=load_workbook(template_path(),read_only=True)
    sheet=book['학생등록'];assert sheet['G8'].value=='기존 학생번호';assert ';' in sheet['A5'].value
    book.close()
