"""Stage 0: 1.0.6 백업 1회 이관. The 1.0.6 data is produced by the original 1.0.6 code."""
import importlib
import sqlite3
import pytest
from PIL import Image
from core.store import Store
from academy.migrations.from_v106 import migrate,inspect_v106,students_needing_notice
from test_core_math import drawing,KEY,CONFIG


@pytest.fixture
def v106_backup(tmp_path,legacy):
    store_mod=importlib.import_module('localomr.store');importer=importlib.import_module('localomr.importer')
    old=store_mod.Store(tmp_path/'v106'/'localomr.sqlite3')
    aid=old.academy('청솔');sat=old.classroom(aid,'청솔(토)');sun=old.classroom(aid,'청솔(일)')
    first=old.save_student_contact('김민수','010-1234-4241',school='예제고',parent_phone='010-9999-0000',class_id=sat)
    second=old.save_student_contact('이영희','5678',class_id=sun)
    old.set_student_classes(second,[sun,sat])
    eid=old.save_exam('2027 필요충분 모의고사 시즌 9 - 1회','필요충분','수학','1','2026-10-18',KEY,[3]*30,config=CONFIG)
    sheet=tmp_path/'math.png';drawing().save(sheet)
    importer.import_files(old.path,eid,[sheet],academy_id=aid,class_id=sat,sat_on='2026-10-18')
    scan=old.scans(eid)[0]['id'];row=old.scan(scan)
    old.save_review(scan,first,row['answers'],[True]*30,True,elective='1');old.confirm(scan)
    local=old.save_exam('주간 평가','주간','수학','1','2026-10-19',[1,2,3],[2,3,5])
    manual=old.save_manual(local,second,None,[1,2,4],[True]*3,1,class_id=sun,sat_on='2026-10-19')
    with old.transaction():
        he=old.db.execute("INSERT INTO historical_exams(title,day,mean,maximum,source_name,source_hash) VALUES('이전 시험 1회','2026-09-01',70,10000,'x.xlsx','h')").lastrowid
        old.db.execute('INSERT INTO historical_results(exam_id,student_id,sat_on,score,grade,elective,snapshot,earned,ox,answers,source_row) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(he,first,'2026-09-01',8400,'2','1',store_mod.pack(old.student(first)),store_mod.pack([200]*30),store_mod.pack(['O']*30),store_mod.pack(KEY),5))
    old.set_report_name('양지용 수학연구실')
    expected={'raw':row['raw'],'normalized':row['normalized'],'scores':{r['id']:r['score'] for r in old.results()},'codes':{s['id']:s['code'] for s in old.students()},'first':first,'second':second,'scan':scan,'manual':manual,'eid':eid}
    backup=old.backup(tmp_path/'20261024_1237_청솔.omrbackup');old.close()
    return backup,expected


def test_migration_preserves_results_images_and_issues_codes(tmp_path,v106_backup,seq_random):
    backup,expected=v106_backup
    assert inspect_v106(backup)['confirmed']==2
    store=Store(tmp_path/'new'/'academy.sqlite3')
    store.set_operator('조교A','pc-a')   # the program records the operator before the migration button
    summary=migrate(backup,store,rng=seq_random(11,22))
    assert store.rows("SELECT COUNT(*) n FROM audit WHERE kind='scan_imported'")[0]['n']==1
    first=store.student(expected['first']);second=store.student(expected['second'])
    assert first['code']=='4241011' and second['code']=='5678022'
    assert summary['codes'][expected['first']]['legacy_code']==expected['codes'][expected['first']]
    assert {r['id']:r['score'] for r in store.results()}==expected['scores']
    scan=store.scan(expected['scan'])
    assert scan['raw']==expected['raw'] and scan['normalized']==expected['normalized'] and scan['raw_hash']
    assert scan['snapshot']['code']=='4241011' and scan['snapshot']['legacy_code']==expected['codes'][expected['first']]
    assert [c['class_id'] for c in store.memberships(expected['second'])]==[c['class_id'] for c in store.memberships(expected['second'])]
    assert {c['name']:c['weekday'] for c in store.classes()}=={'청솔(토)':'토','청솔(일)':'일'}
    assert store.exam(expected['eid'])['exam_kind']=='mock'
    assert store.report_name()=='양지용 수학연구실'
    assert store.code_history(expected['first'])[0]['previous']==expected['codes'][expected['first']]
    assert {s['id'] for s in students_needing_notice(store)}=={expected['first'],expected['second']}
    from core.history import results as historical
    assert historical(store,expected['first'])[0]['snapshot']['code']=='4241011'
    from core.reports import report_pdf
    report_pdf(tmp_path/'r.pdf',store,[expected['scan']])
    assert store.db.execute('PRAGMA foreign_key_check').fetchone() is None
    store.close()


def test_migration_requires_empty_target_and_rolls_back_on_mismatch(tmp_path,v106_backup):
    backup,expected=v106_backup
    store=Store(tmp_path/'new'/'academy.sqlite3')
    store.classroom(store.academy('기존'),'반');store.save_student('1111111','기존학생',store.classes()[0]['id'])
    with pytest.raises(ValueError,match='빈 자료'):migrate(backup,store)
    store.close()
    tampered=tmp_path/'tampered.omrbackup';tampered.write_bytes(backup.read_bytes())
    db=sqlite3.connect(tampered);db.execute("UPDATE scans SET score=score+100 WHERE status='confirmed'");db.commit();db.close()
    fresh=Store(tmp_path/'fresh'/'academy.sqlite3')
    with pytest.raises(ValueError,match='1.0.6 저장값과 달라'):migrate(tampered,fresh)
    assert not fresh.students() and not fresh.exams()
    fresh.close()
