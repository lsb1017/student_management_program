"""Stage 1 simulation: two PCs sharing one simulated Drive folder.

통과 기준(ARCHITECTURE.md 1단계): PC 2대 이어받기, 동시 시작 잠금. 실제 Drive 실측은 별도로 필요함.
"""
from datetime import datetime,timedelta
from pathlib import Path
import pytest
from PIL import Image
from core.omr import ReadResult
from academy.adapters.gdrive.fake import FakeBackupFolder
from academy.services.backup import BackupService,SessionBlocked,DriveUnavailable,BackupInvalid,UploadFailed


class Clock:
    def __init__(self):self.value=datetime(2026,11,1,18,30)
    def __call__(self):return self.value
    def tick(self,minutes=1):self.value+=timedelta(minutes=minutes)


@pytest.fixture
def world(tmp_path):
    clock=Clock();drive=tmp_path/'drive'
    def pc(name):
        return BackupService(tmp_path/name/'data',FakeBackupFolder(drive),pc_id='pc-'+name,pc_name=name.upper(),clock=clock)
    return clock,pc('a'),pc('b'),drive


def add_work(store,tmp_path,tag):
    """A student, an exam and a scan with an image, so the file box travels too."""
    cid=store.classroom(store.academy('청솔'),'청솔(토)','토')
    sid=store.save_student_contact('학생'+tag,'010-1234-56'+tag[-2:].rjust(2,'0'),class_id=cid)
    eid=store.save_exam('주간지 '+tag,'주간지','수학',tag,'2026-11-01',[1,2,3],[3,3,4])
    image=tmp_path/f'{tag}.png';Image.new('RGB',(40,40),(10*len(tag),200,30)).save(image)
    source=store.source(image)
    result=ReadResult(image.read_bytes(),[{'answer':a,'flag':'clear','levels':[]} for a in (1,2,3)],None)
    scan,_=store.add_scan(eid,source,1,'pixel-'+tag,image.read_bytes(),result)
    store.save_review(scan,sid,[1,2,3],[True]*3,True);store.confirm(scan)
    return sid,eid,scan


def test_two_pc_handoff_with_files(world,tmp_path):
    clock,a,b,drive=world
    session=a.open_session('조교A','청솔');assert session.mode=='online' and not session.restored
    sid,eid,scan=add_work(session.store,tmp_path,'11')
    raw=session.store.scan(scan)['raw']
    assert a.close_session(session.store,'청솔')=='20261101_1830_청솔.omrbackup';session.store.close()
    # The source file and the page image have the same bytes: one file-box object, uploaded once.
    assert not list((drive/'locks').iterdir()) and len(list((drive/'files').iterdir()))==1
    clock.tick()
    session=b.open_session('조교B','청솔');store=session.store
    assert session.restored=='20261101_1830_청솔.omrbackup'
    assert store.student(sid)['name']=='학생11' and store.scan(scan)['raw']==raw and store.results(eid)[0]['score']==1000
    add_work(store,tmp_path,'22')
    b.close_session(store,'청솔');store.close();clock.tick()
    session=a.open_session('조교A','청솔')
    assert session.restored=='20261101_1831_청솔.omrbackup' and len(session.store.students())==2
    a.close_session(session.store,'청솔');session.store.close()


def test_running_pc_blocks_other_with_operator_and_time(world):
    clock,a,b,drive=world
    session=a.open_session('김조교','청솔')
    with pytest.raises(SessionBlocked,match='김조교님이 18:30부터 작업 중'):b.open_session('이조교','청솔')
    a.close_session(session.store,'청솔');session.store.close()
    b.open_session('이조교','청솔').store.close()


def test_simultaneous_start_only_earliest_lock_proceeds(world):
    clock,a,b,drive=world
    outcome={}
    real_list=b.remote.list_locks;calls={'n':0}
    def stale_first_listing():
        calls['n']+=1
        return [] if calls['n']==1 else real_list()   # B listed before A created its lock
    b.remote.list_locks=stale_first_listing
    def b_starts_between():
        try:b.open_session('B','청솔');outcome['b']='started'
        except SessionBlocked as exc:outcome['b']=exc
    a.remote.hooks['after_create_lock']=b_starts_between
    session=a.open_session('A','청솔')
    assert isinstance(outcome['b'],SessionBlocked) and session.mode=='online'
    locks=list((drive/'locks').iterdir());assert len(locks)==1 and 'pc-a' in locks[0].name
    assert not b.holding_lock() and a.holding_lock()
    session.store.close()


def test_upload_failure_keeps_lock_and_next_start_uploads_first(world,tmp_path):
    clock,a,b,drive=world
    session=a.open_session('A','청솔');add_work(session.store,tmp_path,'31')
    a.remote.fail.add('upload_backup')
    with pytest.raises(UploadFailed,match='잠금을 유지'):a.close_session(session.store,'청솔')
    session.store.close()
    assert a.holding_lock() and list((drive/'locks').iterdir())
    with pytest.raises(SessionBlocked):b.open_session('B','청솔')
    a.remote.offline=True
    offline=a.open_session('A','청솔');assert offline.mode=='offline' and offline.warnings;offline.store.close()
    a.remote.offline=False;a.remote.fail.clear();clock.tick()
    resumed=a.open_session('A','청솔')
    assert resumed.uploaded_first and not resumed.restored and list(drive.glob('*.omrbackup'))
    a.close_session(resumed.store,'청솔');resumed.store.close()
    session=b.open_session('B','청솔');assert len(session.store.students())==1;session.store.close()


def test_drive_unreachable_without_lock_refuses_to_start(world):
    clock,a,b,drive=world
    a.remote.offline=True
    with pytest.raises(DriveUnavailable,match='실행하지 않습니다'):a.open_session('A','청솔')


def test_invalid_latest_backup_is_not_restored_and_previous_can_be_chosen(world,tmp_path):
    clock,a,b,drive=world
    session=a.open_session('A','청솔');add_work(session.store,tmp_path,'41');a.close_session(session.store,'청솔');session.store.close()
    clock.tick();bad=drive/'20261101_1831_청솔.omrbackup';bad.write_bytes(b'broken backup')
    meta=a.remote;meta._set_meta(bad.name,{'id':'broken','created':meta._stamp(),'sha256':__import__('core.filestore',fromlist=['x']).sha256_file(bad)})
    with pytest.raises(BackupInvalid) as caught:b.open_session('B','청솔')
    error=caught.value
    assert error.item['name']==bad.name and [c['name'] for c in error.candidates]==['20261101_1830_청솔.omrbackup']
    assert b.holding_lock()
    store=b.open_store();assert not store.students()
    b.restore_candidate(store,error.candidates[0]);assert len(store.students())==1
    b.close_session(store,'청솔');store.close()


def test_legacy_backup_on_drive_is_refused(world,tmp_path,legacy):
    import importlib
    clock,a,b,drive=world
    old=importlib.import_module('localomr.store').Store(tmp_path/'legacy'/'db.sqlite3')
    path=old.backup(drive/'20261101_1830_청솔.omrbackup');old.close()
    a.remote._set_meta(path.name,{'id':'legacy','created':a.remote._stamp(),'sha256':__import__('core.filestore',fromlist=['x']).sha256_file(path)})
    with pytest.raises(BackupInvalid,match='이관'):a.open_session('A','청솔')


def test_force_release_after_pc_failure(world,tmp_path):
    clock,a,b,drive=world
    session=a.open_session('A','청솔');add_work(session.store,tmp_path,'51');a.close_session(session.store,'청솔');session.store.close()
    clock.tick();crashed=a.open_session('A','청솔');add_work(crashed.store,tmp_path,'52');crashed.store.close()  # PC A breaks down
    with pytest.raises(SessionBlocked):b.open_session('B','청솔')
    released=b.force_release('원장','PC A 고장');assert len(released)==1
    clock.tick();session=b.open_session('B','청솔')
    assert len(session.store.students())==1  # A's unsent second student is not on Drive
    b.close_session(session.store,'청솔');session.store.close()
    clock.tick();back=a.open_session('A','청솔')
    assert any('관리자' in w for w in back.warnings) or any('교체' in w for w in back.warnings)
    assert len(back.store.students())==1 and list((a.data/'backups').glob('before_restore_*.omrbackup'))
    back.store.close()


def test_same_minute_names_and_unchanged_close(world,tmp_path):
    clock,a,b,drive=world
    session=a.open_session('A','청솔');add_work(session.store,tmp_path,'61');a.close_session(session.store,'청솔');session.store.close()
    session=a.open_session('A','청솔');add_work(session.store,tmp_path,'62')
    assert a.close_session(session.store,'청솔')=='20261101_1830_청솔_2.omrbackup';session.store.close()
    session=a.open_session('A','청솔');assert a.close_session(session.store,'청솔')=='';session.store.close()
    assert not list((drive/'locks').iterdir()) and len(list(drive.glob('*.omrbackup')))==2


def test_autosave_is_local_and_rotates(world,tmp_path):
    clock,a,b,drive=world
    session=a.open_session('A','청솔');add_work(session.store,tmp_path,'71')
    for _ in range(8):a.autosave(session.store)
    assert len(list((a.data/'backups'/'automatic').glob('autosave_*.omrbackup')))==6
    assert not list(drive.glob('autosave*'))
    a.close_session(session.store,'청솔');session.store.close()
