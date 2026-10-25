"""Presentation-only policy for message boxes; no data or backup changes.

An application event filter covers Qt's static message APIs and custom boxes
without changing their return values, button roles, or existing signal handlers.
"""
import re
from functools import lru_cache
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QDialogButtonBox

ASSETS = {
    'polite':'grade_mandu.png', 'smart':'smart_mandu.png',
    'magnifier':'exit_mandu.png', 'important':'import_mandu.png',
    'thumb':'thumb_mandu.png', 'computer':'computer_mandu.png',
    'frustrated':'frustrated_mandu.png', 'melted':'melted_mandu.png',
    'please':'please_mandu.png', 'crazy':'crazy_mandu.png', 'dead':'dead_mandu.png',
}
TITLE_ROLES = {
    '작업 시작 · 백업 확인':'important', '가져올 백업 확인':'polite',
    '작업 마침 · 백업 확인':'magnifier', '채점 확인':'polite',
    '저장된 정답표 다운로드':'polite',
    '중복 학생 확인':'magnifier', '보강 학생 확인':'magnifier',
    '중복 성적':'magnifier', '중복 성적 검수':'magnifier', '기존 학생':'magnifier',
    '정답 변경 반영':'smart', '정답·배점 변경 확인':'smart', '성적 저장':'smart',
    '자동 입력 항목':'smart', '선택 답안 재인식':'smart', '검수 재개':'smart', '집계 제외':'smart',
    '수정 취소':'dead', 'OMR 이미지 정리':'dead', '저장하지 않은 검수':'dead', '수기 입력 변경':'dead',
    '선택 시험 삭제':'crazy', '선택 행 삭제':'crazy',
    '삭제 시험 복구':'melted', '다음 학생':'melted', '삭제 취소':'melted',
    '정답표 다운로드':'please', '채점 진행 중':'please',
    '저장 완료':'thumb', '엑셀 저장 완료':'thumb', '다운로드 완료':'thumb',
    '백업 파일 저장 완료':'thumb', '미리보기 정리':'thumb', '이미지 정리 완료':'thumb',
    '등록 완료':'thumb', '가져오기 완료':'thumb', '등록 · 연결 완료':'thumb',
}

def role_for(title, text, icon=QMessageBox.Icon.NoIcon, partial=None):
    if title=='저장하지 않은 수정 내용':return None
    if title == '저장하지 않은 수기 답안':
        return 'dead' if '버리고 종료' in text else 'please'
    if title == '답안 수정 되돌리기':
        return 'frustrated' if '되돌릴 수 없' in text else 'melted'
    if title == '전체 학생 성적 확정':
        return 'melted' if '추가로 확정할 답안이 없' in text else 'smart'
    if title in ('일괄 확정 결과', '파일 처리 결과'):
        if partial is None:
            # Fallback for catalog/standalone callers. Runtime passes a boolean.
            partial = bool(re.search(r'(?:남은 답안|미인식) [1-9]\d*장', text) or '중단되었습니다' in text)
        return 'frustrated' if partial else 'thumb'
    if title in TITLE_ROLES:
        return TITLE_ROLES[title]
    # Only existing required-selection errors; never invent new requirements.
    if text.startswith('다운로드할 학생을 체크') or re.search(
        r'(?:학원|반|시험|학생|선택과목|항목|행|체크박스).{0,20}(?:먼저 |등록하고 )?선택(?:하세요|해 주세요)', text
    ):
        return 'frustrated'
    if icon in (QMessageBox.Icon.Warning, QMessageBox.Icon.Critical):
        return 'computer'
    return None

@lru_cache(maxsize=32)
def mascot_pixmap(asset, size=86):
    from .reports import report_asset
    return QPixmap(str(report_asset(asset))).scaled(size,size,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)

@lru_cache(maxsize=16)
def popup_mascot_pixmap(asset):
    if asset not in ('grade_mandu.png','thumb_mandu.png','please_mandu.png','crazy_mandu.png'):
        return mascot_pixmap(asset)
    # Size the visible character, not the transparent canvas. Cache once.
    from .reports import report_asset
    pix=QPixmap(str(report_asset(asset)));im=pix.toImage()
    occupied=[y for y in range(im.height()) if any(im.pixelColor(x,y).alpha()>32 for x in range(im.width()))]
    if not occupied:return mascot_pixmap(asset,60)
    height=round(im.height()*48/(occupied[-1]-occupied[0]+1))
    return pix.scaledToHeight(height,Qt.TransformationMode.SmoothTransformation)

def error_title(title):
    specific={'확인해 주세요':'확인 필요','확인':'입력 확인 필요','답안 입력 확인':'답안 확인 필요','엑셀 저장 확인':'저장 확인 필요',
        '이미 실행 중':'실행 확인 필요','처리 오류':'작업 확인 필요','시작할 수 없습니다':'실행 확인 필요',
        '백업 안내 설정 저장 실패':'설정 저장 확인 필요','엑셀 가져오기':'엑셀 확인 필요','OMR 양식':'OMR 양식 확인 필요','보강생 연결':'학생 연결 확인 필요'}
    if title in specific:return specific[title]
    if title.endswith('확인 필요'):return title
    return title+' 필요' if title.endswith('확인') else title+' 확인 필요'

ACTION_LABELS = {
    '선택 시험 삭제':'삭제하기','선택 행 삭제':'삭제하기','OMR 이미지 정리':'정리하기',
    '성적 저장':'교체하기','중복 성적':'교체하기','중복 성적 검수':'교체하기',
    '정답·배점 변경 확인':'변경 저장','전체 학생 성적 확정':'확정하기',
    '선택 답안 재인식':'다시 읽기','검수 재개':'검수 재개','집계 제외':'제외하기',
    '수정 취소':'수정 버리기','저장하지 않은 검수':'버리고 닫기',
    '수기 입력 변경':'버리고 가져오기','저장하지 않은 수기 답안':'버리고 종료',
    '보강 학생 확인':'연결하기','저장된 정답표 다운로드':'다운로드',
}

ERROR_NEXT_STEPS = {
    '이미 실행 중':'열려 있는 만두OMR 창에서 작업해 주세요.',
    '처리 오류':'파일과 선택한 시험을 확인한 뒤 다시 불러와 주세요.',
    '시작할 수 없습니다':'사용 중인 프로그램을 닫고 데이터 폴더의 접근 권한을 확인해 주세요.',
    '출력 확인':'선택한 성적과 저장 위치를 확인한 뒤 다시 출력해 주세요.',
    '엑셀 저장 확인':'열려 있는 엑셀 파일을 닫거나 다른 이름으로 저장해 주세요.',
    '엑셀 가져오기':'일괄등록 서식과 파일 내용을 확인한 뒤 다시 선택해 주세요.',
    '다운로드 확인':'저장 위치와 파일 사용 여부를 확인한 뒤 다시 시도해 주세요.',
    '정리 확인':'사용 중인 파일을 닫은 뒤 다시 정리해 주세요.',
    '백업 안내 설정 저장 실패':'설정 파일의 저장 위치와 접근 권한을 확인해 주세요.',
}

def decorate(box):
    title=box.property('originalPopupTitle') or box.windowTitle();text=box.text()
    if box.property('originalPopupTitle') is None:
        box.setProperty('originalPopupTitle',title)
        choices=any(box.buttonRole(b) in (QMessageBox.ButtonRole.YesRole,QMessageBox.ButtonRole.NoRole,QMessageBox.ButtonRole.RejectRole,QMessageBox.ButtonRole.DestructiveRole) for b in box.buttons())
        box.setProperty('errorNotice',not choices and box.icon() in (QMessageBox.Icon.Warning,QMessageBox.Icon.Critical))
    error=box.property('errorNotice')
    role = role_for(title,text,QMessageBox.Icon.Warning if error else box.icon(),box.property('partialResult'))
    if title=='저장하지 않은 수정 내용':
        role=None;box.setIcon(QMessageBox.Icon.NoIcon);box.setProperty('mascotAsset',None)
    if role:
        asset=ASSETS[role];box.setIconPixmap(popup_mascot_pixmap(asset));box.setProperty('mascotAsset',asset)
    if error:box.setWindowTitle(error_title(title))
    if role=='computer' and not re.search(r'(?:하세요|주세요|이용|선택|입력)',text):
        step=ERROR_NEXT_STEPS.get(title,'위 내용을 확인한 뒤 다시 시도해 주세요.')
        box.setText(text+'\n\n'+step)
    box.setTextFormat(Qt.TextFormat.PlainText)
    # Retain explicitly named buttons; translate only Qt's stock labels.
    B=QMessageBox.StandardButton
    names={B.Ok:'확인',B.Cancel:'취소',B.Yes:ACTION_LABELS.get(title,'확인'),B.No:'취소',B.Close:'닫기',B.Save:'저장',B.Discard:'버리기',B.Retry:'다시 시도',B.Abort:'중단',B.Ignore:'건너뛰기'}
    stock={'ok','cancel','yes','no','close','save','discard','retry','abort','ignore'}
    for key,label in names.items():
        button=box.button(key)
        if button and button.text().replace('&','').lower() in stock:button.setText(label)
    # Non-destructive defaults for confirmations. Existing custom roles remain.
    if title!='작업 시작 · 백업 확인' and (box.standardButtons() & (B.Yes|B.Cancel) or title in ('중복 학생 확인','저장하지 않은 수기 답안')):
        cancel=box.button(B.Cancel) or box.button(B.No)
        if cancel is None:
            cancel=next((b for b in box.buttons() if box.buttonRole(b)==QMessageBox.ButtonRole.RejectRole),None)
        if cancel is not None:
            box.setDefaultButton(cancel);box.setEscapeButton(cancel)

class PopupStyle(QObject):
    def eventFilter(self, watched, event):
        if event.type()==QEvent.Type.Show:
            if isinstance(watched,QMessageBox):decorate(watched)
            elif isinstance(watched,QDialogButtonBox):
                if isinstance(watched.parentWidget(),QMessageBox):return False
                labels={'ok':'확인','cancel':'취소','save':'저장','close':'닫기','yes':'확인','no':'취소','apply':'적용','reset':'초기화','help':'도움말','discard':'버리기','retry':'다시 시도','abort':'중단','ignore':'건너뛰기'}
                for button in watched.buttons():
                    key=button.text().replace('&','').lower()
                    if key in labels:button.setText(labels[key])
        return False

def install():
    app=QApplication.instance()
    if app is not None and not hasattr(app,'_mandu_popup_style'):
        app._mandu_popup_style=PopupStyle(app);app.installEventFilter(app._mandu_popup_style)

def result_message(parent,title,text,partial):
    box=QMessageBox(parent);box.setWindowTitle(title);box.setText(text)
    box.setProperty('partialResult',bool(partial));box.setStandardButtons(QMessageBox.StandardButton.Ok)
    return box.exec()
