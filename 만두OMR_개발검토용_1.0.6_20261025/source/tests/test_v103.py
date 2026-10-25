import json,sqlite3,hashlib
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QMessageBox
from localomr.store import Store,SCHEMA_VERSION
from localomr.identity import resolve_student,name_advisory
from localomr.bulk_confirm import candidates
from localomr.review_reasons import row_reasons
from test_v0411 import fixture,add_scan


def test_distinct_titles_same_round_and_history(fixture):
    from localomr.report_math import report_history
    app,db,w,e,s,c,warnings=fixture
    one=db.save_exam('핏 6회차','수학 모의고사','수학','6','2026-10-23',[1,2,3],[2,3,4])
    two=db.save_exam('필충모 6회차','수학 모의고사','수학','6','2026-10-23',[1,2,3],[2,3,4])
    db.save_manual(one,s,None,[1,2,3],[True]*3,1,sat_on='2026-10-23')
    db.save_manual(two,s,None,[1,2,3],[True]*3,1,sat_on='2026-10-23')
    assert [r['title'] for r in report_history(db,db.results(two)[0])]==['핏 6회차','필충모 6회차']
    with pytest.raises(ValueError,match='동일한 시험명'):db.save_exam('핏 6회차','별도분류','수학','7','2026-10-23',[1],[1])
    db.archive_exams([one])
    new=db.save_exam('새 시험 6회','수학 모의고사','수학','6','2026-10-23',[1],[1])
    assert new not in (one,two) and db.exam(one)['archived']==1
    assert db.db.execute('PRAGMA foreign_key_check').fetchone() is None


def make_v8(db):
    # Reconstruct the exact old constraint without depending on another checkout.
    db.db.execute('PRAGMA foreign_keys=OFF')
    sql=db.db.execute("SELECT sql FROM sqlite_master WHERE name='exams'").fetchone()[0]
    sql=sql[:sql.rfind(')')]+',UNIQUE(series,subject,round))'
    with db.transaction():
        db.db.execute(sql.replace('"exams"','exams_legacy',1).replace('CREATE TABLE exams(','CREATE TABLE exams_legacy(',1))
        db.db.execute('INSERT INTO exams_legacy SELECT * FROM exams')
        db.db.execute('DROP TABLE exams');db.db.execute('ALTER TABLE exams_legacy RENAME TO exams')
        db.db.execute('PRAGMA user_version=8')
    db.db.execute('PRAGMA foreign_keys=ON')


def test_old_data_upgrade_and_old_backup_restore(tmp_path):
    path=tmp_path/'old.sqlite3';db=Store(path)
    c=db.classroom(db.academy('기존학원'),'기존반');s=db.save_student_contact('기존학생','1111',class_id=c)
    e=db.save_exam('기존 6회','수학 모의고사','수학','6','2026-10-20',[1,2],[2,3])
    sid=db.save_manual(e,s,None,[1,2],[True,True],1,sat_on='2026-10-20')
    expected=(db.students(),db.results());make_v8(db);backup=db.backup(tmp_path/'old.omrbackup');db.close()
    before=hashlib.sha256(backup.read_bytes()).hexdigest()
    upgraded=Store(path)
    assert (upgraded.students(),upgraded.results())==expected
    assert upgraded.scan(sid)['exam_id']==e
    assert list((tmp_path/'backups').glob('before_upgrade_v8_*.omrbackup'))
    assert upgraded.db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION
    assert upgraded.db.execute('PRAGMA foreign_keys').fetchone()[0]==1
    upgraded.save_exam('다른 6회','수학 모의고사','수학','6','2026-10-23',[1,2],[2,3])
    safety=upgraded.restore(backup);assert safety.exists()
    assert (upgraded.students(),upgraded.results())==expected
    assert hashlib.sha256(backup.read_bytes()).hexdigest()==before
    upgraded.save_exam('복원 후 다른 6회','수학 모의고사','수학','6','2026-10-23',[1,2],[2,3])
    assert upgraded.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert upgraded.db.execute('PRAGMA foreign_key_check').fetchone() is None
    fresh=upgraded.backup(tmp_path/'new.omrbackup');other=Store(tmp_path/'other.sqlite3');other.restore(fresh)
    assert other.results()==upgraded.results();other.close();upgraded.close()


def test_migration_failure_rolls_back_table_and_version(tmp_path,monkeypatch):
    db=Store(tmp_path/'rollback.sqlite3');db.save_exam('보존','수학','수학','1','2026-10-23',[1],[1]);make_v8(db)
    original=db.remove_round_uniqueness
    def fail():original();raise RuntimeError('injected migration failure')
    monkeypatch.setattr(db,'remove_round_uniqueness',fail)
    with pytest.raises(RuntimeError):db.migrate()
    assert db.exam(1)['title']=='보존' and db.db.execute('PRAGMA user_version').fetchone()[0]==8
    assert 'UNIQUE' in db.db.execute("SELECT sql FROM sqlite_master WHERE name='exams'").fetchone()[0]
    assert db.db.execute('PRAGMA foreign_keys').fetchone()[0]==1;db.close()


def test_scoped_navigation_and_button(fixture,tmp_path,monkeypatch):
    app,db,w,e,s,c,warnings=fixture
    other_c=db.classroom(db.academy('다른학원'),'다른반');other_s=db.save_student_contact('다른학생','3333',class_id=other_c)
    add_scan(db,e,other_s,tmp_path)
    w.refresh();w.startup_backup_ready=True;w.score_exam.setCurrentIndex(w.score_exam.findData(e))
    w.score_academy.setCurrentIndex(w.score_academy.findData(db.student(s)['academy_id']))
    w.score_class.setCurrentIndex(w.score_class.findData(c));w.nav.setCurrentRow(3)
    calls=[];monkeypatch.setattr('localomr.popups.ask',lambda *args:calls.append(args) or QMessageBox.StandardButton.Cancel)
    w.nav.setCurrentRow(5);assert not calls and w.pages.currentIndex()==5
    w.nav.setCurrentRow(3);pending=add_scan(db,e,s,tmp_path)
    w.refresh_scans();assert not w.pending_mascot.isHidden() and '검수 대기 1장' in w.pending_mascot.text()
    assert '검수 대기 1장' not in w.scan_summary.text()
    w.filter_scan_status('failed');w.nav.setCurrentRow(5)
    assert len(calls)==1 and 'OMR이 1장' in calls[0][2]
    assert '성적을 확정해야 성적표를 출력할 수 있어요.' in calls[0][2]
    assert w.pages.currentIndex()==3
    w.pending_mascot.click();assert w.visible_scan_ids==[pending]
    db.confirm(pending);w.refresh_scans();assert w.pending_mascot.isHidden() and '검수 대기 0장' in w.scan_summary.text()


@pytest.mark.parametrize('name,flag,number,expected,hint',[
    ('가상학생','clear','A','A',False),('','blank','A','A',False),
    ('오인식이름','faint','A','A',False),('가상학생','clear','none','A',False),
    ('B학생','clear','A',None,False),('명단에없는이름','clear','A','A',True)])
def test_identity_rules(fixture,name,flag,number,expected,hint):
    app,db,w,e,s,c,warnings=fixture
    b=db.save_student_contact('B학생','2222',class_id=c);student=db.student(s)
    read=SimpleNamespace(code=student['code'] if number=='A' else None,
        identity_reading={'phone_tail':student['code'][1:5] if number=='A' else None,
        'name':{'name':name,'flag':flag},'digits':[{'flag':'clear'}],'suffix_defaulted':False})
    linked,detail=resolve_student(db.db,read,student['academy_id'],c)
    assert (linked['id'] if linked else None)==(s if expected=='A' else None)
    assert bool(name_advisory({'identity_reading':detail},student['name']))==hint


def test_name_advisory_does_not_block_bulk_confirmation(fixture,tmp_path):
    app,db,w,e,s,c,warnings=fixture
    sid=add_scan(db,e,s,tmp_path);row=db.scan(sid);context=row['import_context']
    context.pop('manual_link',None)
    context.update(identity_reading={'method':'explicit_code','name':{'flag':'clear','name':'다른이름'}})
    with db.transaction():db.db.execute('UPDATE scans SET import_context=?,identity_ok=0 WHERE id=?',(json.dumps(context),sid))
    assert row_reasons(db,db.scans(e),db.exam(e))[sid]=='이름 확인 필요'
    ready,skipped,_=candidates(db,[sid],db.student(s)['academy_id'],c)
    assert ready==[sid] and not skipped
    db.confirm(sid,verify_identity=True);assert db.scan(sid)['status']=='confirmed'
