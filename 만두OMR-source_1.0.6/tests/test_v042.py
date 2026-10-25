import json
from copy import deepcopy
import pytest
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication,QPushButton
from localomr.ui import MainWindow
from localomr.history import results,save_cuts
from localomr.catalog import reference
from localomr.store import Store,pack
from localomr.reports import report_pdf
from test_math import store,exam,scan,KEY,CONFIG
from test_history import add_history


def test_scan_confirmation_without_checks_keeps_original_review_evidence(store):
    db,student=store;eid=exam(db);sid=scan(db,eid,student)
    db.save_review(sid,student,[None]+KEY[1:],[False]*30,True,elective='1',allow_reopen=True)
    db.confirm(sid)
    assert db.scan(sid)['status']=='confirmed' and db.scan(sid)['reviewed']==[False]*30
    assert db.results()[0]['score']==8700
    cfg=deepcopy(CONFIG);db.save_exam('수학시험','시리즈','수학','1','2026-10-18',KEY,[4]*30,eid,cfg)
    assert db.scan(sid)['status']=='confirmed'  # A points-only update must not demand review ticks again.
    key=KEY.copy();key[0]=2;db.save_exam('수학시험','시리즈','수학','1','2026-10-18',key,[4]*30,eid,cfg)
    assert db.scan(sid)['status']=='pending'


def test_rename_keeps_ids_and_historical_memberships_while_updating_labels(store):
    db,student=store;eid=exam(db);sid=scan(db,eid,student);add_history(db,student)
    before=db.scan(sid);cid=db.student(student)['class_id'];aid=db.student(student)['academy_id']
    other=db.classroom(db.academy('다른학원'),'A반');other_student=db.save_student('99999','동명이인',other)
    add_history(db,other_student,'다른 이전 시험')
    db.rename_organization('academy',aid,'새학원');db.rename_organization('class',cid,'새반')
    assert db.student(student)['class_id']==cid and db.student(student)['academy']=='새학원'
    assert db.scan(sid)['snapshot']['classroom']=='새반' and results(db,student)[0]['snapshot']['academy']=='새학원'
    assert results(db,other_student)[0]['snapshot']['academy']=='다른학원'
    for field in ('student_id','answers','score','reviewed','status','sat_on','raw'):assert db.scan(sid)[field]==before[field]
    assert db.averages(eid,academy_id=aid)[0]==90
    with pytest.raises(ValueError):db.rename_organization('academy',aid,'다른학원')
    assert db.student(student)['academy']=='새학원'


def test_latest_elective_fills_only_missing_records_and_preserves_source(store):
    db,student=store;eid=exam(db);scan(db,eid,student,choice='2')
    add_history(db,student,'과거 미확인');add_history(db,student,'과거 확통','2026-09-17')
    db.db.execute("UPDATE historical_results SET elective='1' WHERE exam_id=(SELECT id FROM historical_exams WHERE title='과거 확통')");db.db.commit()
    rows={r['title']:r for r in results(db,student)}
    assert rows['과거 미확인']['elective']=='2' and rows['과거 미확인']['elective_inferred']
    assert rows['과거 확통']['elective']=='1' and not rows['과거 확통']['elective_inferred']
    assert db.db.execute("SELECT elective FROM historical_results WHERE exam_id=(SELECT id FROM historical_exams WHERE title='과거 미확인')").fetchone()[0] is None
    other=db.save_student('88888','다른학생',db.student(student)['class_id']);add_history(db,other,'다른학생 미확인')
    assert results(db,other)[0]['elective'] is None


def test_supplied_cuts_migrate_once_and_manual_edits_survive_reopening(store,tmp_path):
    db,student=store;add_history(db,student,'2027 필요충분 모의고사 시즌4 - 1회')
    db.db.execute("UPDATE historical_results SET elective='2'");db.db.commit();db.migrate()
    r=results(db)[0];assert r['cuts']==[84,75,68,58,35] and r['grade']==1 and r['estimated_percentile']==96
    hid=-r['exam_id'];save_cuts(db,hid,{'2':[90,80,70,60,40]});db.migrate()
    assert results(db)[0]['cuts']==[90,80,70,60,40]
    with pytest.raises(ValueError):save_cuts(db,hid,{'2':[80,90,70,60,40]})
    backup=tmp_path/'v7.omrbackup';db.backup(backup);db.restore(backup)
    assert results(db)[0]['cuts']==[90,80,70,60,40]
    ref=reference('2027 수능 Fit × 양지용 6회차')
    assert ref['cuts']['2']==[87,82,65,53,41] and ref['cuts']['3']==ref['cuts']['1'] and '임시' in ref['note']
    assert reference('2026 필요충분 모의고사 시즌4 - 1회') is None


def test_review_navigation_zoom_and_any_result_cell_preview(store,monkeypatch):
    app=QApplication.instance() or QApplication([]);db,student=store;eid=exam(db);sid=scan(db,eid,student)
    window=MainWindow(db);window.score_exam.setCurrentIndex(1);window.nav.setCurrentRow(3);window.show();app.processEvents();pane=window.review_pane
    db.save_review(sid,student,[None]+KEY[1:5]+[None]+KEY[6:],[False]*30,True,elective='1',allow_reopen=True)
    window.refresh_scans();pane.show_scan(sid,0);pane.next_question();assert pane.q==5
    pane.next_question(-1);assert pane.q==0 and app.focusWidget() is pane.answer
    names=[b.text() for b in pane.findChildren(QPushButton)]
    assert '이전 오답' in names and '다음 오답' in names and '다음 미검수' not in names and '전체 문항 원본 확인' not in names
    view=pane.view;view.fit();pos=view.viewport().rect().center();before=view.mapToScene(pos);scale=view.transform().m11()
    def wheel(mod,delta):
        event=QWheelEvent(QPointF(pos),QPointF(view.viewport().mapToGlobal(pos)),QPoint(0,0),QPoint(0,delta),Qt.MouseButton.NoButton,mod,Qt.ScrollPhase.NoScrollPhase,False)
        QApplication.sendEvent(view.viewport(),event);app.processEvents()
    wheel(Qt.KeyboardModifier.NoModifier,120);assert view.transform().m11()==scale
    wheel(Qt.KeyboardModifier.ControlModifier,120);assert view.transform().m11()>scale
    after=view.mapToScene(pos);assert (after-before).manhattanLength()<8
    wheel(Qt.KeyboardModifier.ControlModifier,-120);assert view.transform().m11()==pytest.approx(scale)
    pane.confirm();window.refresh_results();calls=[];monkeypatch.setattr(window,'preview_report',lambda row:calls.append(row))
    for col in (1,2,4,7,11):window.result_table.cellDoubleClicked.emit(0,col)
    window.result_table.cellDoubleClicked.emit(0,0);assert calls==[0]*5
    window.hide();window.deleteLater()


def test_long_area_uses_existing_short_classification_and_report_stays_two_pages(store,tmp_path):
    import pypdfium2 as pdfium
    from localomr.report_labels import area_label
    assert area_label('지수함수와 로그함수')=='지수로그함수'
    assert area_label('수학 I')=='수학 I'
    assert area_label('긴 학습목표를 설명하는 원본 문장','함수의 극한과 연속')=='함수극한연속'
    db,student=store;cfg=deepcopy(CONFIG)
    long='함수의 극한값과 연속성을 이용하여 조건을 만족하는 이차함수의 식과 계수의 값을 추론하기'
    cfg['areas']=[long]*30;cfg['topics']=['함수극한연속']*30;cfg['skills']=['수학Ⅱ']*30
    answers=KEY.copy()
    for q in (0,4,8,12,15,20,21,28):answers[q]=None
    for n in range(1,7):
        eid=db.save_exam(f'긴 영역 검증 {n}회','시리즈','수학',str(n),f'2026-10-{n:02}',KEY,[3]*30,config=cfg)
        sid=scan(db,eid,student,answers=answers,unique=f'layout{n}')
    path=tmp_path/'long_area.pdf';report_pdf(path,db,[sid])
    with pdfium.PdfDocument(str(path)) as doc:
        assert len(doc)==2;text=''
        for page in doc:
            tp=page.get_textpage();text+=tp.get_text_range();tp.close();page.close()
    assert '함수극한연속' in text and '학습내용' in text and '수학Ⅱ' in text
    assert db.exam(eid)['config']['areas']==[long]*30  # Display-only abbreviation.
    assert '순번' in text and '최근 6회' not in text and '(정답률이 높은데 내가 틀린 문항)' in text
    assert '수학은 양지용입니다.' in text and '이전 시험은 문항 분류 등록 필요' not in text
