import json
import os
from copy import deepcopy
from datetime import date
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMessageBox
from localomr import storage,cheer
from localomr.store import Store,pack
from localomr.ui import MainWindow
from localomr.storageui import StorageDialog
from localomr.examui import ExamEditor
from localomr.historyui import HistoryCutsDialog
from localomr.history import save_cuts
from localomr.export_names import export_name,short_name
from localomr.preview_cache import preview_pdf,cache_files,clear_cache
from test_math import store,exam,scan,KEY,CONFIG
from test_history import add_history


@pytest.fixture
def app(monkeypatch):
    a=QApplication.instance() or QApplication([])
    monkeypatch.setattr(QMessageBox,'information',lambda *a:None)
    monkeypatch.setattr(QMessageBox,'warning',lambda *a:None)
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes)
    return a


def age(db,*ids):
    with db.transaction():
        db.db.executemany("UPDATE scans SET created_at='2020-01-01T00:00:00+00:00' WHERE id=?",[(sid,) for sid in ids])


def test_cleanup_releases_space_keeps_results_and_shared_source_until_last_reference(store,tmp_path):
    db,s=store;e=exam(db);a=scan(db,e,s,unique='a')
    e2=db.save_exam('두 번째','시리즈','수학','2','2026-10-10',KEY,[3]*30,config=CONFIG);b=scan(db,e2,s,unique='b')
    source=tmp_path/'original.pdf';data=os.urandom(2*1024*1024);source.write_bytes(data);source_id=db.source(source)
    with db.transaction():
        for sid in (a,b):db.db.execute('UPDATE scans SET source_id=?,raw=?,normalized=? WHERE id=?',(source_id,os.urandom(2*1024*1024),os.urandom(1024*1024),sid))
    age(db,a,b);db.db.execute('PRAGMA wal_checkpoint(TRUNCATE)');before=db.path.stat().st_size
    results=db.results();first=db.scan(a)
    proposed=storage.plan(db,[a]);assert proposed['shared_sources']==1 and proposed['source_ids']==[]
    result=storage.purge(db,[a]);assert result['freed_bytes']>2*1024*1024 and not result['warning']
    assert db.results()==results and db.scan(a)['raw']==b'' and db.scan(a)['images_purged_at']
    for field in ('score','answers','reviewed','student_id','snapshot','status'):assert db.scan(a)[field]==first[field]
    exported=tmp_path/'export.pdf';db.export_source(source_id,exported);assert exported.read_bytes()==data
    assert db.scan(b)['raw'] and db.path.stat().st_size<before
    assert storage.plan(db,[b])['source_ids']==[source_id]
    storage.purge(db,[b]);assert db.results()==results and db.db.execute('SELECT COUNT(*) FROM source_parts WHERE source_id=?',(source_id,)).fetchone()[0]==0
    protected=tmp_path/'protected.pdf';protected.write_bytes(b'keep')
    with pytest.raises(ValueError):db.export_source(source_id,protected)
    assert protected.read_bytes()==b'keep'
    # Reimporting an identical external file must restore the stored original.
    assert db.source(source)==source_id;db.export_source(source_id,exported);assert exported.read_bytes()==data
    backup=tmp_path/'cleaned.omrbackup';db.backup(backup);other=Store(tmp_path/'restored.sqlite3');other.restore(backup)
    assert other.results()==results and other.scan(a)['images_purged_at'];other.close()


def test_cleanup_excludes_recent_pending_failed_manual_and_revalidates(store):
    db,s=store;e=exam(db);ids=[]
    for i in range(5):
        st=s if i==0 else db.save_student(str(50000+i),'학생'+str(i),db.student(s)['class_id'])
        ids.append(scan(db,e,st,unique=str(i)))
    age(db,*ids[1:])
    with db.transaction():
        db.db.execute("UPDATE scans SET status='pending' WHERE id=?",(ids[1],))
        db.db.execute("UPDATE scans SET status='failed' WHERE id=?",(ids[2],))
        db.db.execute("UPDATE scans SET input_mode='manual' WHERE id=?",(ids[3],))
    assert [r['id'] for r in storage.candidates(db)]==[ids[4]]
    with pytest.raises(ValueError):storage.purge(db,ids)
    assert all(db.scan(sid)['raw'] for sid in ids)
    db.set_status(ids[4],'pending')
    with pytest.raises(ValueError):storage.purge(db,[ids[4]])


def test_cleanup_ui_cancel_and_image_notice(store,app,monkeypatch):
    db,s=store;e=exam(db);sid=scan(db,e,s);age(db,sid)
    dlg=StorageDialog(db);dlg.check_all(Qt.CheckState.Checked);assert dlg.clean.isEnabled()
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.No);dlg.purge();assert db.scan(sid)['raw']
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes);dlg.purge();assert not db.scan(sid)['raw']
    w=MainWindow(db);w.score_exam.setCurrentIndex(1);assert '이미지' in w.review_pane.image_notice.text()
    assert all(not b.isEnabled() for b in w.review_pane.image_tools)
    assert w.review_pane.answer.isEnabled();w.hide();w.deleteLater();dlg.hide()


def test_bulk_click_confirms_remaining_with_explicit_identity_consent_and_updates_counts(store,app,monkeypatch):
    db,s=store;e=exam(db);a=scan(db,e,s,unique='a');cid=db.student(s)['class_id'];aid=db.student(s)['academy_id']
    t=db.save_student('55551','추가학생',cid);b=scan(db,e,t,unique='b')
    row=db.scan(b);db.save_review(b,t,row['answers'],[False]*30,False,elective='1',allow_reopen=True)
    # An unresolved row and duplicate pending students remain unconfirmed.
    u=db.save_student('55552','중복학생',cid);c=scan(db,e,u,unique='c');db.set_status(c,'pending');d=scan(db,e,u,unique='d');db.set_status(d,'pending')
    w=MainWindow(db);w.score_exam.setCurrentIndex(1);w.nav.setCurrentRow(3);w.show();app.processEvents()
    before=db.scan(a)
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.No);QTest.mouseClick(w.bulk_confirm,Qt.MouseButton.LeftButton)
    assert db.scan(b)['status']=='pending' and not db.scan(b)['identity_ok']
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.StandardButton.Yes);QTest.mouseClick(w.bulk_confirm,Qt.MouseButton.LeftButton);app.processEvents()
    assert db.scan(a)==before and db.scan(b)['status']=='confirmed' and db.scan(b)['identity_ok']
    assert db.scan(c)['status']==db.scan(d)['status']=='pending'
    assert '확정 2장' in w.scan_summary.text() and db.scan(b)['reviewed']==[False]*30
    assert db.rows("SELECT * FROM audit WHERE kind='identity_confirmed_on_confirmation'")
    w.hide();w.deleteLater()


def test_next_student_saves_without_confirming_and_defers_results_refresh(store,app,monkeypatch):
    db,s=store;e=exam(db);a=scan(db,e,s,unique='a');t=db.save_student('55551','다음학생',db.student(s)['class_id']);b=scan(db,e,t,unique='b')
    w=MainWindow(db);w.score_exam.setCurrentIndex(1);w.nav.setCurrentRow(3);w.show();app.processEvents();pane=w.review_pane
    calls=[];original=w.refresh_results;monkeypatch.setattr(w,'refresh_results',lambda *a:(calls.append(True),original()))
    pane.answer.setText('3');QTest.mouseClick(pane.next_student_button,Qt.MouseButton.LeftButton);app.processEvents()
    assert db.scan(a)['answers'][0]==3 and db.scan(a)['status']=='pending' and pane.sid==b
    assert not calls and '확정 1장' in w.scan_summary.text()
    assert app.focusWidget() is pane.answer
    QTest.mouseClick(pane.next_student_button,Qt.MouseButton.LeftButton);assert pane.sid==b
    w.nav.setCurrentRow(5);assert calls and w.result_table.rowCount()==1
    w.hide();w.deleteLater()


def test_exam_draft_close_cancel_discard_save(store,app,monkeypatch):
    db,s=store;e=db.save_exam('자체시험','자체','수학','1','2026-10-19',[1,2],[5,5])
    dlg=ExamEditor(db,e);dlg.show();dlg.keys.item(0,6).setText('3')
    monkeypatch.setattr('localomr.draftui.unsaved_choice',lambda *a:'stay');dlg.close();assert dlg.isVisible() and dlg.keys.item(0,6).text()=='3'
    monkeypatch.setattr('localomr.draftui.unsaved_choice',lambda *a:'discard');dlg.reject();assert db.exam(e)['key'][0]==1
    dlg=ExamEditor(db,e);dlg.keys.item(0,6).setText('3')
    monkeypatch.setattr('localomr.draftui.unsaved_choice',lambda *a:'save');dlg.reject();assert db.exam(e)['key'][0]==3


def test_history_cuts_switch_retains_draft_on_cancel_and_saves_previous_exam(store,app,monkeypatch):
    db,s=store;add_history(db,s,'이전 A');add_history(db,s,'이전 B','2026-09-10')
    ids=[r['id'] for r in db.rows('SELECT id FROM historical_exams')]
    for eid in ids:save_cuts(db,eid,{'1':[83,74,65,56,40]})
    dlg=HistoryCutsDialog(db);first=dlg.active_exam;dlg.table.item(0,0).setText('88')
    monkeypatch.setattr('localomr.draftui.unsaved_choice',lambda *a:'stay');dlg.exam.setCurrentIndex(1)
    assert dlg.active_exam==first and dlg.exam.currentData()==first and dlg.table.item(0,0).text()=='88'
    monkeypatch.setattr('localomr.draftui.unsaved_choice',lambda *a:'save');dlg.exam.setCurrentIndex(1)
    assert dlg.active_exam!=first and float(json.loads(db.db.execute('SELECT cuts_json FROM historical_exams WHERE id=?',(first,)).fetchone()[0])['1'][0])==88
    dlg.reject()


def test_export_names_compact_actual_selected_membership_only():
    rows=[{'title':'2027 필요충분 모의고사 시즌4 - 3회','snapshot':{'academy':'학림','classroom':'확률과 통계'}}]
    assert export_name(rows,'rank',date(2026,10,19))=='필충모 시즌4-3회차_학림_2026-10-19.xlsx'
    assert export_name(rows,saved_on=date(2026,10,19))=='학림_확통_성적표_2026-10-19.pdf'
    rows.append({'title':rows[0]['title'],'snapshot':{'academy':'강북청솔','classroom':'미적분'}})
    name=export_name(rows,saved_on=date(2026,10,19));assert '외 1개학원' in name and '외 1개반' in name
    assert short_name('A/B:C*')=='A-B-C-' and rows[0]['snapshot']['classroom']=='확률과 통계'


def test_preview_reuse_invalidation_and_cleanup_does_not_touch_export(store,tmp_path):
    db,s=store;e=exam(db);sid=scan(db,e,s)
    a=preview_pdf(db,sid);assert preview_pdf(db,sid)==a and len(cache_files(db))==1
    exported=tmp_path/'my_report.pdf';exported.write_bytes(a.read_bytes())
    db.set_report_name('새 연구실');b=preview_pdf(db,sid);assert b!=a and len(cache_files(db))==1
    assert clear_cache(db)[0]>0 and not cache_files(db) and exported.exists()


@pytest.mark.parametrize('score,category',[(10000,'perfect'),(8400,'grade1'),(7600,'other'),(5400,'other'),(4000,'grade5plus'),(3900,'grade5plus'),(0,'grade5plus')])
def test_four_cheer_categories_and_legacy_settings_keep_custom_text(store,score,category):
    db,s=store;legacy={k:deepcopy(v) for k,v in cheer.DEFAULTS.items() if k!='grade5plus'};legacy['grade1']['text']='내 응원문구'
    with db.transaction():db.db.execute("INSERT INTO settings(name,value) VALUES('report_cheer',?)",(pack(legacy),))
    config=cheer.settings(db);assert config['grade1']['text']=='내 응원문구'
    result={'score':score,'maximum':10000,'cuts':[84,76,65,54,40]}
    kind,text,image=cheer.resolved(result,config);assert kind==category and image
    if category=='grade5plus':assert text=='귀여워,, 네 점수,,'


def test_v7_upgrade_preserves_answers_and_adds_cleanup_state(store,tmp_path):
    db,s=store;e=exam(db);sid=scan(db,e,s);before=db.results();db.db.execute('PRAGMA user_version=7')
    path=tmp_path/'v7.omrbackup';db.backup(path);restored=Store(tmp_path/'upgrade.sqlite3');restored.restore(path)
    assert restored.results()==before and restored.scan(sid)['images_purged_at']==''
    assert restored.db.execute('PRAGMA user_version').fetchone()[0]==__import__('localomr.store',fromlist=['SCHEMA_VERSION']).SCHEMA_VERSION;restored.close()


def test_makeup_popup_explicit_search_keeps_original_academy_average_and_history(store,app,monkeypatch):
    from localomr.makeupui import MakeupStudentDialog
    from localomr.bulk_confirm import candidates
    from localomr.importer import scan_in_scope
    db,s=store;e=exam(db);sid=scan(db,e,s);original=db.student(s)
    attending=db.classroom(db.academy('학림'),'보강반');attending_aid=next(c['academy_id'] for c in db.classes() if c['id']==attending)
    with db.transaction():db.db.execute('UPDATE scans SET student_id=NULL,status=\'pending\',identity_ok=0,snapshot=\'{}\',import_context=? WHERE id=?',(pack({'academy_id':attending_aid,'class_id':attending}),sid))
    dlg=MakeupStudentDialog(db);dlg.search.setText('4241');assert len(dlg.rows)==1
    dlg.table.setCurrentCell(0,0);dlg.table.selectRow(0);dlg.select_student();assert dlg.student_id==s
    count=len(db.students());db.link_makeup_student(sid,s)
    ready,skipped,_=candidates(db,[sid],attending_aid,attending);assert ready==[sid] and not skipped
    db.confirm(sid,verify_identity=True);assert len(db.students())==count and db.student(s)==original
    assert db.scan(sid)['snapshot']['class_id']==original['class_id']
    assert scan_in_scope(db.scans(e)[0],attending_aid,attending)
    assert db.averages(e,academy_id=original['academy_id'])[1]==1 and db.averages(e,academy_id=attending_aid)[1]==0
    assert len(db.results(student_id=s))==1


def test_bulk_confirms_23_unchecked_students_and_ignores_deleted_row(store,app):
    db,s=store;e=exam(db);cid=db.student(s)['class_id'];ids=[]
    for i in range(24):
        st=s if i==0 else db.save_student(str(60000+i),'학생'+str(i),cid)
        sid=scan(db,e,st,unique='whole'+str(i));r=db.scan(sid)
        db.save_review(sid,st,r['answers'],[False]*30,False,elective='1',allow_reopen=True);ids.append(sid)
    db.delete_scans(e,[ids[-1]])
    w=MainWindow(db);w.score_exam.setCurrentIndex(1);w.confirm_visible_scans()
    assert len(db.results(e))==23 and db.scan(ids[-1])['status']=='deleted'
    assert '확정 23장' in w.scan_summary.text();w.hide();w.deleteLater()


def test_single_confirm_needs_no_identity_checkbox_but_still_requires_student(store,app):
    from PySide6.QtWidgets import QCheckBox
    db,s=store;e=exam(db);sid=scan(db,e,s);r=db.scan(sid)
    db.save_review(sid,None,r['answers'],[False]*30,False,elective='1',allow_reopen=True)
    w=MainWindow(db);w.score_exam.setCurrentIndex(1);pane=w.review_pane
    assert not any('학생' in box.text() or '시험' in box.text() for box in pane.findChildren(QCheckBox))
    pane.confirm();assert db.scan(sid)['status']=='pending'
    db.save_review(sid,s,r['answers'],[False]*30,False,elective='1');pane.show_scan(sid)
    QTest.mouseClick(pane.confirm_button,Qt.MouseButton.LeftButton)
    assert db.scan(sid)['status']=='confirmed' and db.scan(sid)['identity_ok']
    assert '확정 1장' in w.scan_summary.text();w.hide();w.deleteLater()
