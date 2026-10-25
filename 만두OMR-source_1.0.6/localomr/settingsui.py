from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QComboBox,QStackedWidget,QTextEdit,QLabel,QMessageBox
from . import cheer
from .cheerui import CheerDialog

class CheerPanel(QWidget):
    sample=CheerDialog.sample
    preview=CheerDialog.preview
    upload=CheerDialog.upload
    remove=CheerDialog.remove
    reset=CheerDialog.reset

    def __init__(self,store,parent=None):
        super().__init__(parent)
        from .ui import button,label
        self.store=store;self.config=cheer.settings(store);self.editors={};self.previews={}
        v=QVBoxLayout(self);v.setContentsMargins(0,0,0,0);v.setSpacing(12)
        v.addWidget(label('응원 문구와 이미지'));v.addWidget(label('성적에 따라 자동으로 표시됩니다. 이미지 사용 시 저작권에 주의해 주세요.','Sub'))
        self.category=QComboBox();self.category.setMaximumWidth(240)
        for key,title in cheer.CATEGORIES.items():self.category.addItem(title,key)
        v.addWidget(self.category);self.stack=QStackedWidget();v.addWidget(self.stack)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(220);self.timer.timeout.connect(self.refresh_preview)
        for key in cheer.CATEGORIES:
            body=QWidget();layout=QVBoxLayout(body);layout.setContentsMargins(0,0,0,0)
            editor=QTextEdit();editor.setAcceptRichText(False);editor.setFixedHeight(100);editor.setPlainText(self.config[key]['text']);self.editors[key]=editor;layout.addWidget(editor)
            preview=QLabel();preview.setAlignment(Qt.AlignmentFlag.AlignCenter);preview.setFixedHeight(120);preview.setStyleSheet('background:white;border:1px solid #E4DEEB;border-radius:8px;');self.previews[key]=preview;layout.addWidget(preview)
            row=QHBoxLayout();layout.addLayout(row)
            for title,handler in [('이미지 선택',self.upload),('이미지 삭제',self.remove),('기본값 복원',self.reset)]:row.addWidget(button(title,lambda _,k=key,f=handler:f(k)))
            row.addStretch();self.stack.addWidget(body);editor.textChanged.connect(lambda k=key:self.changed(k))
        v.addWidget(label('120자 · 최대 3줄  │  {학생명} {점수} {등급} {목표등급} {필요점수}','Sub'))
        row=QHBoxLayout();row.addStretch();row.addWidget(button('응원 설정 저장',self.save,True));v.addLayout(row)
        self.category.currentIndexChanged.connect(self.select_category);self.refresh_preview()

    def changed(self,key):
        self.config[key]['text']=self.editors[key].toPlainText();self.timer.start()

    def select_category(self,index):self.stack.setCurrentIndex(index);self.refresh_preview()

    def refresh_preview(self):self.preview(self.category.currentData())

    def save(self):
        try:
            for key,editor in self.editors.items():self.config[key]['text']=editor.toPlainText()
            cheer.save(self.store,self.config);QMessageBox.information(self,'저장 완료','응원 문구와 이미지를 저장했습니다.')
        except ValueError as exc:QMessageBox.warning(self,'문구 확인',str(exc))

    def reload(self):
        self.config=cheer.settings(self.store)
        for key,editor in self.editors.items():editor.blockSignals(True);editor.setPlainText(self.config[key]['text']);editor.blockSignals(False)
        self.refresh_preview()
