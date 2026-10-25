import json
from pathlib import Path
import pytest
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QApplication,QMessageBox,QProgressDialog
from PySide6.QtTest import QTest
from localomr.popup_style import ASSETS,role_for,install,decorate,mascot_pixmap
from localomr.busy import ManduProgressBar,BusyDialog

@pytest.fixture
def app():
    app=QApplication.instance() or QApplication([]);install();return app

def test_all_numbered_alert_assignments(app):
    records=json.loads((Path(__file__).parents[1]/'assets/popup_assignments.json').read_text('utf-8'))
    special={16:'다운로드할 학생을 체크하세요.',39:'되돌릴 최근 수정이 없어요.',40:'이후 상태가 변경되어 되돌릴 수 없어요.',65:'추가로 확정할 답안이 없습니다.',76:'저장하지 않은 수기 답안을 버리고 종료할까요?'}
    assert {r['number'] for r in records} >= set(range(1,80))
    for r in records:
        if r['number'] in (4,9,93,95,102):continue # custom dialogs below
        role=role_for(r['title'],special.get(r['number'],'샘플 안내'),QMessageBox.Icon.Warning,True if r['number'] in (56,57) else None)
        assert ASSETS.get(role)==r['asset'],r

@pytest.mark.parametrize('title',['일괄 확정 결과','파일 처리 결과'])
def test_partial_result_only_changes_image(app,title):
    assert role_for(title,'중복 3장 · 기존 확정 5장 유지',partial=False)=='thumb'
    assert role_for(title,'처리할 답안이 남음',partial=True)=='frustrated'
    for partial,asset in ((False,'thumb_mandu.png'),(True,'frustrated_mandu.png')):
        box=QMessageBox();box.setWindowTitle(title);box.setText('결과 수치 보존');box.setProperty('partialResult',partial)
        box.setStandardButtons(QMessageBox.StandardButton.Ok);box.show();app.processEvents()
        assert box.property('mascotAsset')==asset and box.text()=='결과 수치 보존'
        box.close()

@pytest.mark.parametrize('title',['선택 시험 삭제','선택 행 삭제','OMR 이미지 정리','성적 저장','중복 성적','중복 성적 검수','수기 입력 변경','저장하지 않은 검수','저장하지 않은 수기 답안'])
@pytest.mark.parametrize('action',['enter','escape','close'])
def test_confirmations_keyboard_and_close_never_commit(app,title,action):
    B=QMessageBox.StandardButton
    box=QMessageBox();box.setWindowTitle(title);box.setText('변경을 버리고 종료할까요?');box.setStandardButtons(B.Yes|B.No)
    box.show();app.processEvents()
    assert box.defaultButton()==box.button(B.No)
    assert box.button(B.No).text()=='취소'
    if action=='close':box.close()
    else:QTest.keyClick(box,Qt.Key.Key_Return if action=='enter' else Qt.Key.Key_Escape)
    app.processEvents();assert box.result()==B.No

def test_native_static_question_uses_localization_and_safe_default(app):
    B=QMessageBox.StandardButton;seen=[]
    def inspect():
        box=app.activeModalWidget();seen.append((box.button(B.Yes).text(),box.property('mascotAsset')))
        QTest.keyClick(box,Qt.Key.Key_Return)
    QTimer.singleShot(20,inspect)
    assert QMessageBox.question(None,'선택 시험 삭제','삭제할까요?')==B.No
    assert seen==[('삭제하기','crazy_mandu.png')]

def test_backup_restore_custom_buttons_and_escape(app):
    B=QMessageBox.StandardButton
    box=QMessageBox();box.setWindowTitle('가져올 백업 확인');box.setText('학생 현재 1명 → +2명 · 총 3명');box.setStandardButtons(B.Yes|B.Cancel)
    box.button(B.Yes).setText('백업 가져오기');box.show();app.processEvents()
    assert box.defaultButton()==box.button(B.Cancel) and box.button(B.Yes).text()=='백업 가져오기'
    QTest.keyClick(box,Qt.Key.Key_Escape);assert box.result()==B.Cancel

def test_required_selection_error_precedence(app):
    assert role_for('확인해 주세요','학원과 반을 먼저 선택해 주세요.',QMessageBox.Icon.Warning)=='frustrated'
    assert role_for('확인해 주세요','파일을 열 수 없습니다.',QMessageBox.Icon.Warning)=='computer'

def test_alpha_assets_and_loading_layout_lifecycle(app):
    from PIL import Image
    folder=Path(__file__).parents[1]/'assets'
    for asset in set(ASSETS.values())|{'celebrate_mandu.png','running_mandu.png'}:
        with Image.open(folder/asset) as im:
            assert im.mode=='RGBA' and im.getextrema()[3][0]==0,asset
            assert im.width<=256 and im.height<=256,asset
        assert not mascot_pixmap(asset).isNull()
    bar=ManduProgressBar();bar.resize(360,74);bar.show();app.processEvents()
    assert bar.sprite.height()==60 and bar.timer.isActive()
    bar.phase=20;bar.tick();assert bar.phase==21
    bar.setRange(0,100);bar.setValue(50);assert not bar.timer.isActive()
    bar.setRange(0,0);assert bar.timer.isActive()
    bar.hide();assert not bar.timer.isActive()
    dialog=QProgressDialog('작업 중이에요.','중단',0,0);dialog.setBar(ManduProgressBar(dialog));dialog.setMinimumSize(420,205);dialog.show();app.processEvents()
    track=dialog.findChild(ManduProgressBar)
    assert track.height()==86 and track.geometry().bottom()<dialog.height()
    dialog.close();app.processEvents();assert not track.timer.isActive()

def test_backup_copy_removes_only_requested_lines():
    from localomr.backup_tools import comparison
    text=comparison({'students':1,'results':2},{'students':3,'results':5,'file':'old.omrbackup','saved_at':None})
    assert '+2명' in text and '+3건' in text and '확인 불가' in text
    assert '증감은' not in text and '안전 백업됩니다' not in text

def test_input_and_editor_buttons_korean_without_new_mascots(app):
    from PySide6.QtWidgets import QInputDialog,QDialogButtonBox,QDialog,QVBoxLayout
    inp=QInputDialog();inp.show();app.processEvents()
    assert {b.text() for b in inp.findChild(QDialogButtonBox).buttons()}=={'확인','취소'}
    assert inp.property('mascotAsset') is None;inp.close()
    dlg=QDialog();layout=QVBoxLayout(dlg);buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);layout.addWidget(buttons)
    dlg.show();app.processEvents();assert {b.text() for b in buttons.buttons()}=={'저장','취소'};dlg.close()
