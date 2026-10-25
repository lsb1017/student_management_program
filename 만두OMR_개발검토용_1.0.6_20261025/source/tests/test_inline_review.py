from PySide6.QtCore import Qt, QDate
from PySide6.QtWidgets import QApplication, QLineEdit
from PySide6.QtTest import QTest
import pytest
from localomr.ui import MainWindow
from localomr.importer import import_files
from localomr.mathomr import question_rect
from localomr.review_pane import ANSWER_ROLE
from test_math import drawing, KEY
from test_manual_students import setup


@pytest.fixture
def review(setup,tmp_path):
    db,student,eid,cid,warnings=setup
    path=tmp_path/'scan.png';drawing(code='0012').save(path)
    import_files(db.path,eid,[path],sat_on='2026-10-03')
    sid=db.scans(eid)[0]['id']
    db.save_review(sid,student,KEY,[True]*30,True,elective='1')
    window=MainWindow(db);window.score_exam.setCurrentIndex(1);window.resize(1300,840);window.nav.setCurrentRow(3);window.show();QApplication.processEvents()
    yield window,db,sid,student,eid,warnings
    window.hide();window.deleteLater();QApplication.processEvents()


def enter(grid,row,col,text,key=Qt.Key.Key_Right):
    grid.setCurrentCell(row,col);grid.setFocus();QTest.keyClicks(grid,text[0]);QApplication.processEvents()
    editor=QApplication.focusWidget();assert isinstance(editor,QLineEdit),(type(editor).__name__,grid.state(),grid.currentRow(),grid.currentColumn(),str(grid.item(row,col).flags()),grid.item(row,col).text())
    if len(text)>1:QTest.keyClicks(editor,text[1:])
    QTest.keyClick(editor,key);QApplication.processEvents();QApplication.processEvents()


def test_mouse_and_arrows_follow_exact_answer_rect_and_show_correct_key(review):
    window,db,sid,student,eid,warnings=review;grid=window.scan_table;pane=window.review_pane
    assert grid.columnCount()==35
    item=grid.item(0,11);QTest.mouseClick(grid.viewport(),Qt.MouseButton.LeftButton,pos=grid.visualItemRect(item).center());QApplication.processEvents()
    assert pane.q==6 and pane.view.highlight.rect().getRect()==question_rect(7)
    assert f'정답 {KEY[6]}' in pane.heading.text() and '│' in pane.answer_label.text() and '정답' in pane.answer_label.text()
    QTest.keyClick(grid,Qt.Key.Key_Right);QApplication.processEvents()
    assert pane.q==7 and pane.view.highlight.rect().getRect()==question_rect(8)
    grid.setCurrentCell(0,20);QApplication.processEvents()
    assert pane.view.highlight.rect().getRect()==question_rect(16)
    before=pane.view.transform().m11();pane.zoom_question();assert pane.view.transform().m11()>before
    pane.original.setChecked(True);assert pane.view.highlight is None
    pane.original.setChecked(False);assert pane.view.highlight.rect().getRect()==question_rect(16)
    assert not warnings


def test_keyboard_edit_multiple_digits_delete_and_save_without_changing_raw_or_date(review):
    window,db,sid,student,eid,warnings=review;grid=window.scan_table;before=db.scan(sid)
    enter(grid,0,5,'5')
    row=db.scan(sid);assert row['answers'][0]==5 and row['score']==8700 and not row['reviewed'][0]
    assert grid.currentColumn()==6 and grid.item(0,5).text()=='5\n×'
    enter(grid,0,20,'288',Qt.Key.Key_Left)
    assert db.scan(sid)['answers'][15]==288 and grid.currentColumn()==19
    grid.setCurrentCell(0,20);QTest.keyClick(grid,Qt.Key.Key_Delete);QApplication.processEvents()
    assert db.scan(sid)['answers'][15] is None and grid.item(0,20).data(ANSWER_ROLE) is None
    enter(grid,0,20,'0')
    assert db.scan(sid)['answers'][15]==0 and grid.item(0,20).text()=='0'
    for field in ('raw','source_id','page','sat_on'):assert db.scan(sid)[field]==before[field]
    assert not warnings


def test_vertical_navigation_commits_to_correct_student_and_escape_cancels(review,tmp_path):
    window,db,sid,student,eid,warnings=review
    second=db.save_student_contact('학생나','9988');path=tmp_path/'two.png';drawing(code='9988').save(path)
    import_files(db.path,eid,[path]);window.refresh_scans();grid=window.scan_table
    row=window.visible_scan_ids.index(sid);other=1-row
    enter(grid,row,5,'4',Qt.Key.Key_Down if row==0 else Qt.Key.Key_Up)
    assert db.scan(sid)['answers'][0]==4 and db.scan(window.visible_scan_ids[other])['answers'][0]==KEY[0]
    assert grid.currentRow()==other and window.review_pane.sid==window.visible_scan_ids[other]
    enter(grid,other,5,'3',Qt.Key.Key_Escape)
    assert db.scan(window.visible_scan_ids[other])['answers'][0]==KEY[0]
    assert not warnings


def test_invalid_edits_and_confirmed_edit_automatically_returns_to_pending(review):
    window,db,sid,student,eid,warnings=review;pane=window.review_pane
    with pytest.raises(ValueError):pane.update_answer(0,6)
    with pytest.raises(ValueError):pane.update_answer(15,1000)
    assert db.scan(sid)['answers']==KEY
    pane.confirm();assert db.scan(sid)['status']=='confirmed'
    assert window.scan_table.item(0,5).flags()&Qt.ItemFlag.ItemIsEditable
    pane.update_answer(0,2);assert db.scan(sid)['answers'][0]==2
    assert db.scan(sid)['status']=='pending' and not db.results(eid) and not db.scan(sid)['reviewed'][0]
    assert not warnings


def test_ctrl_a_delete_only_visible_rows_and_undo_preserves_pages(review,tmp_path):
    window,db,sid,student,eid,warnings=review;before=db.scan(sid)
    other=db.classroom(db.academy('다른학원'),'B반');path=tmp_path/'other.png';drawing(code='9988').save(path)
    import_files(db.path,eid,[path],class_id=other);other_id=db.scans(eid)[-1]['id']
    cid=db.student(student)['class_id'];aid=db.rows('SELECT academy_id FROM classes WHERE id=?',(cid,))[0]['academy_id']
    db.set_import_context(sid,aid,cid)
    window.score_academy.setCurrentIndex(window.score_academy.findData(aid));window.score_class.setCurrentIndex(window.score_class.findData(cid));window.refresh_scans()
    grid=window.scan_table;grid.setFocus();QTest.keyClick(grid,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier)
    assert len(grid.selectedIndexes())==35
    window.delete_selected_scans();assert grid.rowCount()==0 and db.scan(sid)['status']=='deleted' and db.scan(other_id)['status']=='pending'
    assert db.scan(sid)['raw']==before['raw']
    window.undo_scan_deletion();assert grid.rowCount()==1 and db.scan(sid)['pixel_hash']==before['pixel_hash'] and db.scan(sid)['answers']==before['answers']
    assert not warnings


def test_deleted_pages_can_reimport_and_undo_does_not_create_duplicate(review,tmp_path):
    window,db,sid,student,eid,warnings=review
    db.delete_scans(eid,[sid]);path=tmp_path/'same.png';drawing(code='0012').save(path)
    assert import_files(db.path,eid,[path])['added']==1
    with pytest.raises(ValueError,match='다시 불러'):db.restore_deleted_scans(eid)
    assert len(db.scans(eid))==1


def test_delete_restore_after_changed_key_requires_review_and_survives_backup(review,tmp_path):
    window,db,sid,student,eid,warnings=review;db.confirm(sid);db.delete_scans(eid,[sid])
    exam=db.exam(eid);key=KEY.copy();key[0]=4
    db.save_exam(exam['title'],exam['series'],exam['subject'],exam['round'],exam['day'],key,[3]*30,eid,exam['config'])
    path=tmp_path/'deleted.omrbackup';db.backup(path);db.restore(path)
    assert db.restore_deleted_scans(eid)==1 and db.scan(sid)['status']=='pending' and not db.scan(sid)['reviewed'][0]


def test_elective_change_and_attendance_save_then_follow_wrong_question(review):
    window,db,sid,student,eid,warnings=review;pane=window.review_pane
    assert window.scan_table.cellWidget(0,2) is None
    enter(window.scan_table,0,2,'2')
    row=db.scan(sid);assert all(row['reviewed'][:22]) and not any(row['reviewed'][22:]) and not row['identity_ok']
    window.scan_table.setCurrentCell(0,27);assert '정답 2' in pane.heading.text()
    pane.day.setDate(QDate(2026,10,5));assert db.scan(sid)['sat_on']=='2026-10-05'
    pane.next_question();assert window.scan_table.currentColumn()==5+pane.q
    assert QApplication.focusWidget() is pane.answer and pane.answer.selectedText()==pane.answer.text()
    assert pane.data['answers'][pane.q]!=pane.exam['key'][pane.q]
    assert not warnings


def test_student_search_placeholder_phone_tail_and_top_confirm_location(review):
    window,db,sid,student,eid,warnings=review;pane=window.review_pane
    cid=db.student(student)['class_id'];aid=db.student(student)['academy_id'];db.set_import_context(sid,aid,cid)
    db.save_review(sid,None,KEY,[False]*30,False,elective='1');pane.show_scan(sid)
    assert pane.student.currentText()=='' and pane.student.lineEdit().placeholderText()=='학생을 검색해 연결하세요'
    pane.student.setEditText('0012');pane.student.completer().setCompletionPrefix('0012')
    assert pane.student.completer().completionCount()==1
    pane.student.setCurrentIndex(pane.student.findData(student));pane.student.activated.emit(pane.student.currentIndex())
    assert db.scan(sid)['student_id']==student and not db.scan(sid)['identity_ok']
    assert pane.confirm_button.geometry().top()<pane.next_student_button.geometry().top()
    assert pane.confirm_button.geometry().left()==pane.next_student_button.geometry().left()
    assert not hasattr(pane,'choice') and not hasattr(pane,'register') and not warnings
