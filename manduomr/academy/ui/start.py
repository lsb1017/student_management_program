"""시작 화면: 백업 폴더 연결 → 작업자·학원 선택 → 잠금 확인·최신 백업 내려받기."""
from __future__ import annotations
from PySide6.QtWidgets import (QDialog,QVBoxLayout,QFormLayout,QLineEdit,QComboBox,QLabel,QDialogButtonBox,QPushButton,
                               QFileDialog,QInputDialog,QListWidget,QListWidgetItem,QMessageBox)
from PySide6.QtCore import Qt
from academy.services.backup import SessionBlocked,DriveUnavailable,BackupInvalid
from .common import run,error,ask,info


class CandidateDialog(QDialog):
    def __init__(self,error_obj,parent=None):
        super().__init__(parent);self.setWindowTitle('최신 백업 확인 필요');self.resize(520,360)
        layout=QVBoxLayout(self);label=QLabel(str(error_obj));label.setWordWrap(True);layout.addWidget(label)
        self.list=QListWidget()
        for item in error_obj.candidates:
            row=QListWidgetItem(item['name']);row.setData(Qt.ItemDataRole.UserRole,item);self.list.addItem(row)
        if self.list.count():self.list.setCurrentRow(0)
        layout.addWidget(self.list)
        buttons=QDialogButtonBox();buttons.addButton('선택한 백업으로 시작',QDialogButtonBox.ButtonRole.AcceptRole);buttons.addButton('취소(잠금 해제)',QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def chosen(self):
        item=self.list.currentItem();return item.data(Qt.ItemDataRole.UserRole) if item else None


class StartDialog(QDialog):
    def __init__(self,app,parent=None):
        super().__init__(parent);self.app=app;self.session=None;self.service=None
        self.setWindowTitle('학원 성적·학생 관리 · 작업 시작');self.resize(520,320)
        layout=QVBoxLayout(self)
        self.remote_label=QLabel();self.remote_label.setWordWrap(True);layout.addWidget(self.remote_label)
        setup=QPushButton('백업 폴더 설정');setup.clicked.connect(self.setup);layout.addWidget(setup)
        form=QFormLayout();layout.addLayout(form)
        self.operator=QLineEdit(app.local.get('operator',''));self.operator.setPlaceholderText('작업자 이름')
        self.academy=QComboBox();self.academy.setEditable(True)
        for name in app.local.get('academies',[]):self.academy.addItem(name)
        self.academy.setCurrentText(app.local.get('academy',''))
        form.addRow('작업자',self.operator);form.addRow('작업 학원(백업 파일명)',self.academy)
        hint=QLabel('시작하면 Drive 잠금을 확인하고 최신 백업을 자동으로 내려받습니다. 종료하면 자동으로 올리고 잠금을 풉니다.');hint.setWordWrap(True);hint.setObjectName('hint')
        layout.addWidget(hint)
        buttons=QDialogButtonBox();self.start_button=buttons.addButton('작업 시작',QDialogButtonBox.ButtonRole.AcceptRole);buttons.addButton('닫기',QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.start);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.render()

    def render(self):
        remote=self.app.local.get('remote') or {}
        if remote.get('kind')=='simulation':text=f"백업 폴더: 시뮬레이션 폴더 {remote['path']}\n(Google Drive 대신 이 폴더를 사용합니다. 시험 운영용)"
        elif remote.get('kind')=='drive':text=f"백업 폴더: Google Drive · {remote.get('folder_name') or remote.get('folder')}"+('' if self.app.drive_client().connected() else '\nGoogle 로그인이 필요합니다.')
        else:text='백업 폴더가 설정되지 않았습니다. 먼저 백업 폴더를 설정하세요.'
        self.remote_label.setText(text);self.start_button.setEnabled(self.app.configured())

    def setup(self):
        choice,ok=QInputDialog.getItem(self,'백업 폴더','사용할 백업 폴더',['Google Drive 폴더 연결','시뮬레이션 폴더(이 PC/공유 폴더)'],0,False)
        if not ok:return
        try:
            if choice.startswith('Google'):
                client=self.app.drive_client()
                if not client.connected() and ask(self,'브라우저에서 학원 Google 계정으로 로그인합니다. 계속할까요?',default_no=False):
                    run(self,'브라우저에서 로그인해 주세요.',client.connect)
                link,ok=QInputDialog.getText(self,'백업 폴더','Google Drive 백업 폴더 링크')
                if ok and link:run(self,'폴더를 확인하고 있어요.',self.app.use_drive,link)
            else:
                path=QFileDialog.getExistingDirectory(self,'시뮬레이션 백업 폴더')
                if path:self.app.use_simulation(path)
        except Exception as exc:error(self,exc)
        self.render()

    def start(self):
        operator=self.operator.text().strip();academy=self.academy.currentText().strip()
        if not operator or not academy:error(self,ValueError('작업자와 작업 학원을 입력하세요.'));return
        self.app.local.set('operator',operator);self.app.local.set('academy',academy)
        names=list(dict.fromkeys([academy]+self.app.local.get('academies',[])))[:20];self.app.local.set('academies',names)
        try:self.service=self.app.backup_service()
        except Exception as exc:error(self,exc);return
        while True:
            try:
                self.session=run(self,'구글드라이브를 확인하고 있어요.',self.service.open_session,operator,academy);break
            except SessionBlocked as exc:
                box=QMessageBox(self);box.setWindowTitle('다른 PC에서 작업 중');box.setText(str(exc));box.setIcon(QMessageBox.Icon.Information)
                force=box.addButton('관리자 강제 해제',QMessageBox.ButtonRole.DestructiveRole);box.addButton('닫기',QMessageBox.ButtonRole.RejectRole);box.exec()
                if box.clickedButton()!=force:return
                if not ask(self,'강제 해제하면 잠금을 가진 PC에서 아직 올리지 못한 변경은 반영되지 않습니다.\n그 PC가 고장 났거나 업로드 없이 꺼진 경우에만 진행하세요.\n\n정말 강제 해제할까요?','강제 해제 경고'):return
                reason,_=QInputDialog.getText(self,'강제 해제 사유','사유(기록용)')
                try:run(self,'잠금을 해제하고 있어요.',self.service.force_release,operator,reason)
                except Exception as error_obj:error(self,error_obj);return
            except BackupInvalid as exc:
                chooser=CandidateDialog(exc,self)
                if chooser.exec()!=QDialog.DialogCode.Accepted or not chooser.chosen():
                    self.service.release_lock();return
                store=self.service.open_store()
                try:run(self,'선택한 백업으로 교체하고 있어요.',self.service.restore_candidate,store,chooser.chosen())
                except Exception as error_obj:
                    store.close();error(self,error_obj);continue
                from academy.services.backup import Session
                self.session=Session(store,'online',restored=chooser.chosen()['name']);break
            except DriveUnavailable as exc:
                error(self,exc,'실행할 수 없습니다');return
            except Exception as exc:
                error(self,exc);return
        self.session.store.set_operator(operator,self.app.local.pc_id)
        messages=[]
        if self.session.restored:messages.append(f'최신 백업을 가져왔습니다: {self.session.restored}')
        if self.session.uploaded_first:messages.append(f'이 PC에 남은 변경을 먼저 올렸습니다: {self.session.uploaded_first}')
        messages.extend(self.session.warnings)
        if messages:info(self,'\n\n'.join(messages),'작업 시작')
        self.accept()
