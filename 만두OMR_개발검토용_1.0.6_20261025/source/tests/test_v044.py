from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QLineEdit,QLabel
from localomr.examui import ExamEditor
from localomr.ui import MainWindow
from localomr.history_analysis import enrich,catalog
from localomr.report_insights import clinic_priorities
from localomr.classification import course_for,normalize_config
from test_math import store,exam,scan,CONFIG,KEY
from test_v043 import app


def complete_config():
    cfg=deepcopy(CONFIG);cfg['variants']['3']=deepcopy(cfg['variants']['2'])
    return cfg


def test_copied_exam_save_prompts_cuts_cancel_and_accept(store,app,monkeypatch):
    db,_=store;eid=exam(db,complete_config());original=db.exam(eid)
    dlg=ExamEditor(db,eid);dlg.eid=None;dlg.title.setText('복사한 시험');dlg.round.setText('2');dlg.copy_cut_review_required=True
    seen=[]
    def cancel(popup):
        seen.append(popup.windowTitle());return 0
    monkeypatch.setattr(QDialog,'exec',cancel);dlg.save()
    assert len(db.exams())==1 and seen==['복사한 시험 · 등급컷 확인']
    def accept(popup):
        assert any('복사된 등급컷' in label.text() for label in popup.findChildren(QLabel))
        fields=popup.findChildren(QLineEdit);fields[0].setText('90');return 1
    monkeypatch.setattr(QDialog,'exec',accept);dlg.save()
    assert len(db.exams())==2 and float(db.exam(dlg.eid)['config']['cuts']['1'][0])==90
    assert db.exam(eid)==original


def test_normal_exam_save_does_not_prompt_cuts(store,app,monkeypatch):
    db,_=store;eid=exam(db,complete_config());dlg=ExamEditor(db,eid)
    monkeypatch.setattr(dlg,'edit_cuts',lambda:(_ for _ in ()).throw(AssertionError('unexpected popup')))
    dlg.save();assert dlg.eid==eid and len(db.exams())==1


def test_sort_keeps_student_edit_and_restoration_identity(store,app):
    db,s=store;e=exam(db);a=scan(db,e,s,unique='a');cid=db.student(s)['class_id']
    t=db.save_student('55551','가나다',cid);b=scan(db,e,t,unique='b')
    w=MainWindow(db);w.score_exam.setCurrentIndex(1);w.nav.setCurrentRow(3);w.show();app.processEvents()
    w.sort_scan_column(1);assert w.visible_scan_ids==[b,a]
    w.scan_table.setCurrentCell(0,5);app.processEvents();assert w.review_pane.sid==b
    w.review_pane.answer.setText('3');w.sort_scan_column(1)
    assert w.visible_scan_ids==[a,b] and db.scan(b)['answers'][0]==3 and db.scan(a)['answers'][0]==KEY[0]
    w.scan_table.setCurrentCell(0,5);w.next_scan_student();assert w.review_pane.sid==b
    db.delete_scans(e,[a]);w.refresh_scans();ids=db.restore_deleted_scans(e,return_ids=True)
    assert ids==[a];w.refresh_scans();w.select_restored_scans(ids)
    assert w.review_pane.sid==a and '예제학생' in w.statusBar().currentMessage()
    row=w.visible_scan_ids.index(a);assert w.scan_table.item(row,1).isSelected()
    assert w.scan_table.item(row,1).background().color().name()=='#d9eee2'
    w.clear_restored_highlight(ids);assert w.scan_table.item(row,1).background().color().name()!='#d9eee2'
    assert w.review_pane.identity_notice.isHidden() and w.review_pane.original.isHidden() and not w.review_pane.image_tools
    w.hide();w.deleteLater();app.processEvents()


def test_actual_reference_geometry_and_conflict_exclusion():
    entry=next(e for e in catalog().values() if '시즌4' in e['title'] and '6회' in e['title'])
    geom=[q for q in entry['questions'] if q['q']>22 and q['course']=='기하'];assert len(geom)==8
    selected={q['q']:q for q in entry['questions'] if q['q']<=22 or q['course']=='기하'}
    answers=[selected[q]['key'] for q in range(1,31)]
    row={'title':entry['title'],'historical':True,'exam_id':-1,'elective':'3','answers':answers,'ox':['O']*30,'earned':[selected[q]['points'] for q in range(1,31)],'score':10000}
    result=enrich(deepcopy(row));assert all(result['correctness']) and result['score']==10000
    row['answers'][0]=None;result=enrich(row)
    assert result['analysis_conflicts']==[1] and result['correctness'][0] is None and result['score']==10000
    assert clinic_priorities([result],'3')==[]


def test_legacy_swapped_columns_normalized_without_losing_detail():
    cfg={'topics':['미분']*30,'areas':['함수의 증감']*30,'skills':['수학 II']*30}
    assert course_for(cfg,0)=='수학Ⅱ'
    normalize_config(cfg);assert cfg['areas'][0]=='수학 II' and cfg['skills'][0]=='함수의 증감'
