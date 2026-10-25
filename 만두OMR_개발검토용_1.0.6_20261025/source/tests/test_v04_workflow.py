from copy import deepcopy
from types import SimpleNamespace
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication,QMessageBox
from PySide6.QtTest import QTest
from localomr.ui import MainWindow
from localomr.identity import resolve_student
from localomr import cheer
from localomr.cheerui import CheerDialog
from localomr.examdata import effective
from localomr.mathomr import recognize_math
from localomr.omr import png_bytes
from localomr.store import Store
from test_manual_students import setup
from test_math import KEY,drawing,scan
import pytest


def reading(tail=None,name=None,suffix=False,code=None):
    return SimpleNamespace(code=code,identity_reading={'phone_tail':tail,'name':{'flag':'clear' if name else 'faint','name':name},'suffix_defaulted':not suffix,'digits':[{'flag':'clear'}]*4+[{'flag':'clear' if suffix else 'blank'}]})

def test_unique_phone_or_name_conflicts_collisions_and_scope(setup):
    db,s,e,c,w=setup;a=db.student(s)['academy_id']
    t=db.save_student_contact('학생나','3456',class_id=c)
    assert resolve_student(db.db,reading('0012'),a,c)[0]['id']==s
    assert resolve_student(db.db,reading(name='학생나'),a,c)[0]['id']==t
    assert resolve_student(db.db,reading('0012','학생나'),a,c)[0] is None
    assert resolve_student(db.db,reading('0012'),a,None)[0] is None
    twin=db.save_student_contact('학생다','0012',class_id=c)
    assert resolve_student(db.db,reading('0012'),a,c)[0] is None
    assert resolve_student(db.db,reading('0012','학생다'),a,c)[0]['id']==twin
    other=db.classroom(db.academy('외부학원'),'외부반')
    assert resolve_student(db.db,reading(name='학생가'),None,other)[0] is None
    assert resolve_student(db.db,reading(name='학생가'),999,c)[0] is None

def test_relink_old_unlinked_record_preserves_answers_and_manual_decision(setup,tmp_path):
    db,s,e,c,w=setup;a=db.student(s)['academy_id'];im=drawing(code='0012');path=tmp_path/'scan.png';im.save(path)
    result=recognize_math(im);result.identity_reading=reading('0012').identity_reading
    sid,_=db.add_scan(e,db.source(path),1,'relink',png_bytes(im),result,academy_id=a,class_id=c)
    db.db.execute('UPDATE scans SET student_id=NULL WHERE id=?',(sid,));db.db.commit();before=db.scan(sid)
    assert db.relink_unresolved(e,a,c)==1
    after=db.scan(sid);assert after['student_id']==s and after['answers']==before['answers'] and not after['identity_ok']
    assert after['raw']==before['raw'] and after['sat_on']==before['sat_on']
    assert db.relink_unresolved(e,a,c)==0

def test_results_check_filtered_ctrl_a_sort_numeric_and_preview(setup,monkeypatch):
    db,s,e,c,w=setup;sid=scan(db,e,s,unique='r1');other=db.save_student_contact('가나다','2222',class_id=c)
    low=scan(db,e,other,unique='r2',answers=[None]*30)
    third=db.save_student_contact('미적분학생','3333',class_id=c)
    key=effective(db.exam(e),'2')['key'];mid=db.save_manual(e,third,'2',key,[True]*30,db.exam(e)['revision'])
    window=MainWindow(db);window.score_exam.setCurrentIndex(1);window.nav.setCurrentRow(5);window.show();QApplication.processEvents()
    grid=window.result_table
    grid.sortItems(7,Qt.SortOrder.DescendingOrder)
    assert grid.item(0,0).data(Qt.ItemDataRole.UserRole) in (sid,mid)
    assert grid.item(grid.rowCount()-1,0).data(Qt.ItemDataRole.UserRole)==low
    grid.sortItems(1,Qt.SortOrder.AscendingOrder);assert grid.item(0,1).text()=='가나다'
    window.result_choice.setCurrentIndex(window.result_choice.findData('2'));grid.setFocus();QTest.keyClick(grid,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier)
    assert grid.checked_ids()==[mid]
    called=[];monkeypatch.setattr(window,'save_report',lambda ids:called.append(ids));window.checked_reports();assert called==[[mid]]
    monkeypatch.setattr(window,'preview_report',lambda row:called.append(row));grid.cellDoubleClicked.emit(0,1);assert called[-1]==0
    window.result_choice.setCurrentIndex(0);assert grid.checked_ids()==[mid]
    window.hide();window.deleteLater();assert not w

def test_student_filters_column_order_and_four_digit_search(setup):
    db,s,e,c,w=setup;other_class=db.classroom(db.academy('다른학원'),'B반')
    other=db.save_student_contact('퇴원생','9876',class_id=other_class,active=False)
    window=MainWindow(db)
    assert window.nav.item(1).text()=='학생 조회 · 추가'
    assert [window.student_table.horizontalHeaderItem(i).text() for i in range(8)]==['학원','반','성명','학교','학생번호','학부모연락처','학생연락처','상태']
    window.student_academy.setCurrentIndex(window.student_academy.findData(db.student(other)['academy_id']))
    assert window.student_table.rowCount()==1 and window.student_class.findData(c)==-1
    window.student_status.setCurrentIndex(window.student_status.findData(1));assert window.student_table.rowCount()==0
    window.student_academy.setCurrentIndex(0);window.search.setText('0012');assert window.student_table.rowCount()==1
    window.hide();window.deleteLater()

def test_exam_archive_restoration_timestamp_and_backup(setup,tmp_path):
    db,s,e,c,w=setup;sid=scan(db,e,s,unique='archive');before=db.scan(sid)
    assert db.exam(e)['updated_at']
    db.archive_exams([e]);assert not db.exams() and not db.results()
    db.backup(tmp_path/'archive.omrbackup');db.restore(tmp_path/'archive.omrbackup');db.restore_exams([e])
    assert db.results()[0]['id']==sid and db.scan(sid)['answers']==before['answers'] and db.scan(sid)['raw']==before['raw']
    window=MainWindow(db);window.score_exam.setCurrentIndex(1);assert window.exam_table.columnWidth(2)>=400 and window.exam_table.columnWidth(4)<80
    window.hide();window.deleteLater()

def test_cheer_categories_custom_upload_remove_and_backup(setup,tmp_path):
    db,s,e,c,w=setup;config=cheer.settings(db)
    def result(score,cuts=[84,76,65,54,40]):return {'score':score,'maximum':10000,'cuts':cuts,'snapshot':{'name':'학생가'}}
    assert cheer.resolved(result(10000),config)[0]=='perfect'
    cat,text,image=cheer.resolved(result(8400),config);assert cat=='grade1' and '만점까지' not in text and image
    assert '3등급까지 5점' in cheer.resolved(result(6000),config)[1]
    assert '다음 시험도' in cheer.resolved(result(6000,[]),config)[1]
    data=cheer.image_bytes('perfect',config['perfect']);config['other']={'text':'{학생명}, {목표등급}등급까지 {필요점수}점!','image':cheer.encode_image(data)}
    cheer.save(db,config);db.backup(tmp_path/'cheer.omrbackup');cheer.save(db,deepcopy(cheer.DEFAULTS));db.restore(tmp_path/'cheer.omrbackup')
    assert cheer.settings(db)==config and cheer.image_bytes('other',config['other'])==data
    config['other']['image']=None;cheer.save(db,config);assert cheer.resolved(result(6000),cheer.settings(db))[2] is None
    config['other']['text']='{학생명.__class__}'
    with pytest.raises(ValueError):cheer.save(db,config)
    with pytest.raises(ValueError):cheer.encode_image(b'not an image')

def test_cheer_dialog_previews_all_categories_and_cancel_does_not_save(setup):
    db,s,e,c,w=setup;before=cheer.settings(db);dlg=CheerDialog(db)
    for label in dlg.previews.values():assert label.pixmap() and not label.pixmap().isNull(),label.text()
    dlg.editors['grade1'].setPlainText('꺅!! 1등급\n소리질러~~');dlg.reject();assert cheer.settings(db)==before
    dlg=CheerDialog(db);dlg.remove('perfect');dlg.editors['perfect'].setPlainText('만점 축하!');dlg.save();assert cheer.settings(db)['perfect']=={'text':'만점 축하!','image':None}

def test_bulk_confirm_visible_class_without_review_check_requirement(setup,tmp_path,monkeypatch):
    db,s,e,c,w=setup;a=db.student(s)['academy_id'];source=tmp_path/'sheet.png';im=drawing(code='0012');im.save(source);read=recognize_math(im)
    ready=[]
    for i in range(3):
        student=s if i==0 else db.save_student_contact('학생'+str(i),str(4440+i),class_id=c)
        sid,_=db.add_scan(e,db.source(source),i+1,'bulk'+str(i),png_bytes(im),read,academy_id=a,class_id=c)
        db.save_review(sid,student,KEY,[i<2]*30,True,elective='1');ready.append(sid)
    elsewhere=db.classroom(db.academy('다른학원'),'다른반');student=db.save_student_contact('외부학생','9999',class_id=elsewhere)
    outside,_=db.add_scan(e,db.source(source),4,'outside',png_bytes(im),read,class_id=elsewhere)
    db.save_review(outside,student,KEY,[True]*30,True,elective='1')
    window=MainWindow(db);window.score_exam.setCurrentIndex(1);window.score_academy.setCurrentIndex(window.score_academy.findData(a));window.score_class.setCurrentIndex(window.score_class.findData(c))
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.No);window.confirm_visible_scans();assert not db.results()
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.Yes);window.confirm_visible_scans()
    assert {r['id'] for r in db.results()}==set(ready);assert db.scan(outside)['status']=='pending'
    assert not w;window.hide();window.deleteLater()

def test_statistics_update_across_academies_and_remove_pending(setup):
    db,s,e,c,w=setup;sid=scan(db,e,s,unique='stats1');a=db.student(s)['academy_id']
    other=db.classroom(db.academy('다른학원'),'B반');t=db.save_student_contact('다른학생','7777',class_id=other)
    two=scan(db,e,t,unique='stats2',answers=[None]*30)
    assert db.averages(e)[0]==45 and db.averages(e,academy_id=a)[0]==90
    db.save_review(two,t,KEY,[True]*30,True,elective='1',allow_reopen=True);assert db.averages(e)[1]==1
    db.confirm(two);assert db.averages(e)[0]==90
    db.delete_scans(e,[two]);assert db.averages(e)[1]==1
