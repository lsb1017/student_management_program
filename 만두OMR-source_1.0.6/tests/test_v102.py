import pytest
from PySide6.QtWidgets import QApplication,QMessageBox,QPushButton
from localomr.popup_style import install,decorate,popup_mascot_pixmap,mascot_pixmap
from test_v0411 import fixture,add_scan

@pytest.mark.parametrize('title,expected',[('확인해 주세요','확인 필요'),('입력 확인','입력 확인 필요'),('답안 입력 확인','답안 확인 필요'),('엑셀 저장 확인','저장 확인 필요'),('출력 확인','출력 확인 필요')])
def test_error_titles_keep_body_and_image(title,expected):
    app=QApplication.instance() or QApplication([]);install()
    box=QMessageBox(QMessageBox.Icon.Warning,title,'파일을 확인해 주세요.',QMessageBox.StandardButton.Ok)
    decorate(box);decorate(box)
    assert box.windowTitle()==expected and box.text()=='파일을 확인해 주세요.'
    assert box.property('mascotAsset')=='computer_mandu.png'

def test_question_warning_and_unsaved_draft_keep_choices():
    app=QApplication.instance() or QApplication([]);install();B=QMessageBox.StandardButton
    question=QMessageBox(QMessageBox.Icon.Warning,'가져올 백업 확인','계속할까요?',B.Yes|B.Cancel)
    decorate(question);assert question.windowTitle()=='가져올 백업 확인'
    assert question.defaultButton()==question.button(B.Cancel)
    draft=QMessageBox();draft.setWindowTitle('저장하지 않은 수정 내용');draft.setText('수정한 내용을 저장할까요?')
    draft.setStandardButtons(B.Save|B.Discard|B.Cancel);draft.button(B.Cancel).setText('계속 편집')
    decorate(draft)
    assert draft.iconPixmap().isNull() and draft.property('mascotAsset') is None
    assert {b.text() for b in draft.buttons()}=={'저장','버리기','계속 편집'}

def test_only_four_mascots_shrink_to_runner_visible_size():
    app=QApplication.instance() or QApplication([])
    for asset in ('grade_mandu.png','thumb_mandu.png','please_mandu.png','crazy_mandu.png'):
        pix=popup_mascot_pixmap(asset);im=pix.toImage()
        ys=[y for y in range(im.height()) if any(im.pixelColor(x,y).alpha()>32 for x in range(im.width()))]
        assert 47<=max(ys)-min(ys)+1<=49
        assert pix.height()<mascot_pixmap(asset).height()
    for asset in ('smart_mandu.png','exit_mandu.png','computer_mandu.png','dead_mandu.png','melted_mandu.png','frustrated_mandu.png','import_mandu.png'):
        assert popup_mascot_pixmap(asset).cacheKey()==mascot_pixmap(asset).cacheKey()

def test_pending_arrow_scope_filter_and_zero(fixture,tmp_path):
    app,db,w,e,student,c,warnings=fixture
    sid=add_scan(db,e,student,tmp_path)
    other=db.save_exam('다른 시험','다른','수학','1','2026-10-21',[1,2,3],[2,3,4])
    add_scan(db,other,student,tmp_path)
    w.refresh();w.score_exam.setCurrentIndex(w.score_exam.findData(e));w.refresh_scans()
    assert not w.pending_mascot.isHidden() and '1장' in w.pending_mascot.toolTip()
    w.pending_mascot.click();assert w.scan_status_filter=='pending' and w.visible_scan_ids==[sid]
    db.confirm(sid);w.refresh_scans();assert w.pending_mascot.isHidden()
    w.score_exam.setCurrentIndex(w.score_exam.findData(other));w.refresh_scans()
    assert not w.pending_mascot.isHidden()
    absent=db.classroom(db.academy('없는학원'),'없는반')
    w.refresh();w.score_exam.setCurrentIndex(w.score_exam.findData(other))
    w.score_academy.setCurrentIndex(w.score_academy.findText('없는학원'));w.refresh_scans()
    assert w.pending_mascot.isHidden()

def test_exam_toolbar_and_duplicate_copy(fixture):
    from localomr.examui import ExamEditor
    app,db,w,e,student,c,warnings=fixture
    ed=ExamEditor(db,e)
    texts={b.text() for b in ed.findChildren(QPushButton)}
    assert '더보기' in texts and '현재 구역 정답 일괄 입력' not in texts and '엑셀 파일 불러오기' not in texts
    assert [a.text() for a in ed.more_menu.actions()]==['엑셀 파일 불러오기']
    ed.eid=None;ed.round.clear();ed.save()
    assert warnings[-1]=='동일한 시험명이 이미 있어요.\n기존 시험을 수정하거나, 시험명을 다르게 입력해 주세요.'
    ed.title.setText('이름만 다른 시험 7회');ed.save()
    assert ed.eid and ed.eid!=e and db.exam(ed.eid)['round']=='7'
    ed.title.setText('다른 시험 8회');ed.save();assert ed.eid and ed.eid!=e
    ed.hide();ed.deleteLater()

def test_restore_completion_hides_path_but_keeps_safety_backup(fixture,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    app,db,w,e,student,c,warnings=fixture
    path=db.backup(tmp_path/'incoming.omrbackup')
    db.save_student_contact('추가학생','9876',class_id=c)
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a:(str(path),''))
    monkeypatch.setattr(QMessageBox,'exec',lambda self:QMessageBox.StandardButton.Yes)
    notices=[];monkeypatch.setattr(QMessageBox,'information',lambda *a:notices.append((a[1],a[2])))
    assert w.restore() is True
    assert notices==[('가져오기 완료','백업을 가져왔습니다.')]
    assert len(db.students())==2 and list(tmp_path.rglob('before_restore_*.omrbackup'))
