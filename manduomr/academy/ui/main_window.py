"""Main window: navigation, autosave timer, close → backup upload → unlock."""
from __future__ import annotations
from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow,QWidget,QHBoxLayout,QListWidget,QStackedWidget,QMessageBox
from academy.config import asset,program_setting
from academy.services import notify
from academy.services.backup import UploadFailed
from .common import run,error,info,ask,TextDialog
from . import pages

NAV=[('홈·백업',pages.HomePage),('학생·분반',pages.StudentsPage),('시험·양식',pages.ExamsPage),('채점·검수',pages.GradingPage),
     ('미니테스트·과제',pages.EntriesPage),('성적표·안내',pages.ReportsPage),('문항은행·오답노트',pages.BankPage),('손풀이',pages.OverlayPage),('설정',pages.SettingsPage)]


class MainWindow(QMainWindow):
    def __init__(self,app,service,session):
        super().__init__();self.app=app;self.service=service;self.session=session;self.closing_done=False
        from academy import __version__
        self.setWindowTitle(f"학원 성적·학생 관리 {__version__} · {app.local.get('academy','')} · {app.local.get('operator','')}");self.resize(1320,860)
        icon=asset('app_icon_heart.png')
        if icon.exists():self.setWindowIcon(QIcon(str(icon)))
        central=QWidget();layout=QHBoxLayout(central);layout.setContentsMargins(0,0,0,0);self.setCentralWidget(central)
        self.nav=QListWidget();self.nav.setObjectName('nav');self.nav.setFixedWidth(190);self.stack=QStackedWidget()
        layout.addWidget(self.nav);layout.addWidget(self.stack,1);self.pages=[]
        for title,cls in NAV:
            self.nav.addItem(title);widget=cls(self);self.pages.append(widget);self.stack.addWidget(widget)
        self.nav.currentRowChanged.connect(self.show_page);self.nav.setCurrentRow(0)
        self.autosave=QTimer(self);self.autosave.timeout.connect(self.autosave_now)
        self.autosave.start(max(1,int(program_setting(self.store,'autosave_minutes')))*60*1000)

    @property
    def store(self):return self.session.store

    def show_page(self,index):
        self.stack.setCurrentIndex(index)
        try:self.pages[index].refresh()
        except Exception as exc:error(self,exc)

    def refresh_all(self):
        self.show_page(self.nav.currentRow())

    def autosave_now(self):
        try:self.service.autosave(self.store)
        except Exception:pass

    def offer_welcome(self,student_id,reason):
        s=self.store.student(student_id)
        if ask(self,f"{s['name']} 학생의 학번 {s['code']}을(를) {reason} 안내로 보낼까요?\n(학생·학부모 1:1 채팅방 또는 수동 발송)",'학번 안내',default_no=False):
            self.send_welcome([student_id])

    def send_welcome(self,ids):
        messenger=self.app.messenger(self.store);publisher=self.app.publisher(self.store);manual=[]
        try:
            for sid in ids:
                try:result=notify.send_welcome(self.store,sid,messenger,publisher)
                except notify.AlreadySent:
                    if not ask(self,f"{self.store.student(sid)['name']}: 이미 같은 학번·안내문으로 보냈습니다. 다시 보낼까요?"):continue
                    result=notify.send_welcome(self.store,sid,messenger,publisher,resend=True)
                if result['status']=='failed':manual.append(result['manual'])
        except Exception as exc:error(self,exc)
        finally:messenger.close()
        if manual:
            text='\n\n'.join(m['text']+'\n대상: '+', '.join(f"{t['search']} {t['phone']}" for t in m['targets']) for m in manual)
            TextDialog('수동 발송 필요(채팅방을 찾지 못함)',text,self).exec()

    def closeEvent(self,event):
        if self.closing_done:event.accept();return
        while True:
            try:
                name=run(self,'백업을 만들어 올리고 있어요.',self.service.close_session,self.store,self.app.local.get('academy'))
                break
            except Exception as exc:  # UploadFailed, or anything unexpected: never lose the choice
                text=str(exc) if isinstance(exc,UploadFailed) else f'종료 백업 중 문제가 생겼습니다. 잠금은 유지됩니다.\n{exc}'
                box=QMessageBox(self);box.setWindowTitle('업로드 실패');box.setText(text);box.setIcon(QMessageBox.Icon.Warning)
                retry=box.addButton('다시 시도',QMessageBox.ButtonRole.AcceptRole);leave=box.addButton('잠금 유지한 채 종료',QMessageBox.ButtonRole.DestructiveRole);box.addButton('취소',QMessageBox.ButtonRole.RejectRole)
                box.exec()
                if box.clickedButton()==retry:continue
                if box.clickedButton()==leave:name=None;break
                event.ignore();return
        self.autosave.stop();self.store.close();self.closing_done=True
        if name:info(self,f'백업을 올리고 잠금을 풀었습니다.\n{name}','종료')
        event.accept()
