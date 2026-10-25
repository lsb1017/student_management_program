from copy import deepcopy
import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox
from localomr.store import Store
from localomr.handoff import Handoff
from localomr.ui import MainWindow
from localomr.report_insights import clinic_priorities,cohort_error_rates,question_rate_key,analysis_coverage
from test_math import store,exam,scan
from test_report_insights import record
from test_v043 import app

REAL_QUESTION=QMessageBox.question


def rates_for(records,value):
    return {question_rate_key(r,q):value for r in records for q in range(len(r['answers']))}


def test_clinic_difficulty_adjustment_uses_matching_questions_not_exam_average():
    # Integration has more errors, but sequence problems show the larger gap.
    mine=record(1,range(11));mine['topics']=['적분법']*18+['']*12
    other=record(2,range(6));other['topics']=['수열']*21+['']*9
    rates={**rates_for([mine],55),**rates_for([other],10)}
    rows=clinic_priorities([mine,other],'1',question_rates=rates)
    assert [r['topic'] for r in rows]==['수열','적분법']
    assert rows[0]['total']==21 and rows[0]['wrong']==6
    assert rows[0]['rate_gap']==pytest.approx(600/21-10)
    assert rows[1]['rate_gap']==pytest.approx(1100/18-55)
    # Unequal numbers per exam: all three questions carry equal weight.
    a=record(1,[0]);b=record(2,[0,1]);a['topics']=['수열']+['']*29;b['topics']=['수열']*2+['']*28
    rows=clinic_priorities([a,b],'1',question_rates={**rates_for([a],0),**rates_for([b],90)})
    assert rows[0]['overall_wrong_rate']==60 and rows[0]['rate_gap']==40


def test_clinic_tie_repeat_exams_then_error_count_and_recent_six_only():
    records=[record(i,[0,1]) for i in range(1,8)]
    for r in records:
        r['topics']=['수열','적분법']+['']*28
        if r['exam_id']<6:r['answers'][1]=r['key'][1]
    rates=rates_for(records,0)
    # Sequence: six errors in six exams at 100%; integration: two/6 at 33.33%.
    for r in records:rates[question_rate_key(r,0)]=200/3
    ranked=clinic_priorities(records,'1',question_rates=rates)
    assert ranked[0]['topic']=='수열' and ranked[0]['wrong_rounds']==6 and ranked[0]['total']==6


def test_clinic_missing_comparison_excluded_from_both_denominators():
    mine=record(1,[0,1]);mine['topics']=['수열']*3+['']*27
    rates={question_rate_key(mine,0):20,question_rate_key(mine,2):0}
    row=clinic_priorities([mine],'1',question_rates=rates)[0]
    assert (row['wrong'],row['total'],row['wrong_rate'],row['overall_wrong_rate'],row['rate_gap'])==(1,2,50,10,40)
    assert clinic_priorities([mine],'1',question_rates={})==[]
    assert analysis_coverage([mine],'1',{})==(0,1)


def test_cohort_common_elective_historical_conflicts_and_linked_duplicates():
    local=record(1,[0,22]);local['student_id']=10
    imported=record(-2,[],choice='1');imported.update(student_id=10,historical=True,linked_exam_id=1,correctness=[True]*30)
    historical=deepcopy(imported);historical.update(student_id=20,correctness=[None]+[True]*29)
    different=record(1,[0],choice='2');different['student_id']=30
    rates=cohort_error_rates([imported,historical,different,local])
    assert rates[question_rate_key(local,0)]==100  # Conflict omitted; duplicate not counted.
    assert rates[question_rate_key(local,22)]==50
    assert rates[question_rate_key(different,22)]==0
    # A different answer key must not mix into the reference rate.
    historical['key'][22]=999
    rates=cohort_error_rates([historical,local])
    assert rates[question_rate_key(local,22)]==100


def test_all_better_than_cohort_still_provides_optional_review():
    mine=record(1,[0]);mine['topics']=['수열']*10+['']*20
    rows=clinic_priorities([mine],'1',question_rates=rates_for([mine],30))
    assert rows[0]['rate_gap']==-20


def test_academy_class_source_changes_are_detected_and_persist_on_reopen(store,tmp_path):
    db,_=store;h=Handoff(db)
    db.academy('새 학원');assert h.needs_backup()
    assert Handoff(db).needs_backup()  # Opening baseline was already persisted.
    h.recorded('outgoing',db.backup(tmp_path/'one.omrbackup'))
    aid=db.academy('새 학원');assert not h.needs_backup()
    db.classroom(aid,'새 반');assert h.needs_backup()
    h.recorded('outgoing',db.backup(tmp_path/'two.omrbackup'))
    db.classroom(aid,'새 반');assert not h.needs_backup()
    source=tmp_path/'original.bin';source.write_bytes(b'new source')
    db.source(source);assert h.needs_backup()
    h.recorded('outgoing',db.backup(tmp_path/'three.omrbackup'))
    db.source(source);assert not h.needs_backup()


def test_export_audit_is_not_a_data_change_and_does_not_hide_existing_change(store,tmp_path):
    db,_=store;h=Handoff(db)
    for kind in ('report_exported','batch_report_exported','ranking_exported','import_failed'):
        with db.transaction():db.log(kind,None,{'file':'example.pdf'})
    assert not h.needs_backup()
    db.academy('학원 변경')
    with db.transaction():db.log('report_exported',None,{})
    assert h.needs_backup() and Handoff(db).needs_backup()


def test_organization_change_prompts_exit_but_backup_clears_it(store,tmp_path,app,monkeypatch):
    db,_=store;w=MainWindow(db);w.score_exam.setCurrentIndex(1);db.academy('추가 학원');prompts=[]
    def cancel(*args):prompts.append(args[2]);return QMessageBox.StandardButton.Cancel
    monkeypatch.setattr(QMessageBox,'question',cancel)
    event=QCloseEvent();w.closeEvent(event)
    assert not event.isAccepted() and len(prompts)==1
    w.handoff.recorded('outgoing',db.backup(tmp_path/'done.omrbackup'))
    event=QCloseEvent();w.closeEvent(event)
    assert event.isAccepted() and len(prompts)==1
    w.hide();w.deleteLater()


def test_disabled_exit_reminder_stays_disabled(store,app,monkeypatch):
    db,_=store;w=MainWindow(db);w.score_exam.setCurrentIndex(1);w.handoff_reminder.setChecked(False);db.academy('변경')
    monkeypatch.setattr(QMessageBox,'question',lambda *a:(_ for _ in ()).throw(AssertionError('disabled')))
    event=QCloseEvent();w.closeEvent(event);assert event.isAccepted()
    w.hide();w.deleteLater()


def test_actual_exit_popup_cancel_button(store,app,monkeypatch):
    db,_=store;w=MainWindow(db);w.score_exam.setCurrentIndex(1);db.academy('실제 팝업 테스트');seen=[]
    monkeypatch.setattr(QMessageBox,'question',REAL_QUESTION)
    def click_cancel():
        popup=app.activeModalWidget();seen.append(popup.text())
        popup.button(QMessageBox.StandardButton.Cancel).click()
    QTimer.singleShot(10,click_cancel)
    event=QCloseEvent();w.closeEvent(event)
    assert not event.isAccepted() and len(seen)==1 and '백업' in seen[0]
    w.hide();w.deleteLater()
