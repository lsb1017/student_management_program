from PySide6.QtCore import Qt,QTimer,QRectF
from PySide6.QtGui import QPainter,QColor,QPen,QFont
from PySide6.QtWidgets import QWidget,QFrame,QVBoxLayout,QHBoxLayout,QStackedWidget,QTextEdit,QLabel,QMessageBox,QTabBar
from . import cheer
from .cheerui import CheerDialog

class ReportBrandPreview(QWidget):
    """Static paper diagram: no extra bitmap or background timer."""
    def __init__(self,parent=None):
        super().__init__(parent);self.brand='연구실명';self.setMinimumSize(230,134);self.setMaximumWidth(340)

    def set_brand(self,text):self.brand=text.strip() or '연구실명';self.update()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w=self.width();h=self.height();paper=QRectF(10,29,w-20,h-31)
        p.setPen(QPen(QColor('#D9D3E2'),1));p.setBrush(QColor('white'));p.drawRect(paper)
        p.setFont(QFont('Malgun Gothic',9));p.setPen(QColor('#765A9C'));p.drawText(QRectF(w-137,0,124,24),Qt.AlignmentFlag.AlignCenter,'표시 위치 ↓')
        p.setFont(QFont('Malgun Gothic',12,QFont.Weight.Bold));p.setPen(QColor('#39334D'));p.drawText(QRectF(23,40,100,30),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,'성적표')
        target=QRectF(w-141,44,118,23);p.setPen(QPen(QColor('#AA91CF'),1,Qt.PenStyle.DashLine));p.setBrush(Qt.BrushStyle.NoBrush);p.drawRect(target)
        p.setFont(QFont('Malgun Gothic',8));p.setPen(QColor('#746E81'));text=p.fontMetrics().elidedText(self.brand,Qt.TextElideMode.ElideRight,108);p.drawText(target.adjusted(4,0,-4,0),Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,text)
        p.setPen(QPen(QColor('#E3DFE8'),1));p.setBrush(QColor('#F0EDF4'));p.drawRect(QRectF(23,82,w-46,16))
        for y in (98,114,130):p.drawLine(23,y,w-23,y)
        for i in range(6):
            x=23+(w-46)*i/5;p.drawLine(int(x),82,int(x),130)
        p.end()

class CategoryBar(QTabBar):
    def currentData(self):return self.tabData(self.currentIndex())

class CheerPanel(QFrame):
    sample=CheerDialog.sample
    preview=CheerDialog.preview
    upload=CheerDialog.upload
    remove=CheerDialog.remove
    reset=CheerDialog.reset

    def __init__(self,store,parent=None):
        super().__init__(parent)
        from .ui import button,label
        self.setObjectName('Surface');self.store=store;self.config=cheer.settings(store);self.editors={};self.previews={}
        v=QVBoxLayout(self);v.setContentsMargins(20,14,20,14);v.setSpacing(9)
        heading=label('응원 문구 · 이미지');heading.setStyleSheet('font-size:20px;font-weight:700;');v.addWidget(heading)
        v.addWidget(label('학생의 성적에 맞춰 성적표에 넣을 내용을 설정해요.','Sub'))
        self.category=CategoryBar();self.category.setExpanding(True);self.category.setDrawBase(False)
        self.category.setStyleSheet('QTabBar::tab {background:white;border:1px solid #DDD6E7;padding:9px 18px;} QTabBar::tab:selected {background:#E7DCFA;color:#4E3672;}')
        for key,title in zip(cheer.CATEGORIES,('만점','1등급','2~4등급','5등급 이하')):
            self.category.addTab(title);self.category.setTabData(self.category.count()-1,key)
        v.addWidget(self.category);self.stack=QStackedWidget();v.addWidget(self.stack)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(220);self.timer.timeout.connect(self.refresh_preview)
        for key in cheer.CATEGORIES:
            body=QWidget();row=QHBoxLayout(body);row.setContentsMargins(0,0,0,0);row.setSpacing(20)
            left=QVBoxLayout();left.setSpacing(7);left.addWidget(label('응원 문구'))
            editor=QTextEdit();editor.setAcceptRichText(False);editor.setFixedHeight(112);editor.setPlainText(self.config[key]['text']);self.editors[key]=editor;left.addWidget(editor)
            foot=QHBoxLayout();foot.addWidget(label('최대 120자 · 3줄','Sub'));foot.addStretch();help_button=button('자동 입력 항목 안내',self.field_help);help_button.setStyleSheet('border:0;padding:2px;color:#765A9C;font-size:12px;');foot.addWidget(help_button);left.addLayout(foot);left.addStretch();row.addLayout(left,1)
            divider=QFrame();divider.setFrameShape(QFrame.Shape.VLine);divider.setStyleSheet('color:#E4DEEB;');row.addWidget(divider)
            right=QVBoxLayout();right.setSpacing(7);right.addWidget(label('미리보기'))
            preview=QLabel();preview.setAlignment(Qt.AlignmentFlag.AlignCenter);preview.setMinimumWidth(330);preview.setFixedHeight(112);preview.setStyleSheet('background:white;border:1px solid #DDD6E7;border-radius:7px;');self.previews[key]=preview;right.addWidget(preview)
            actions=QHBoxLayout()
            for title,handler in [('이미지 선택',self.upload),('이미지 삭제',self.remove)]:actions.addWidget(button(title,lambda _,k=key,f=handler:f(k)))
            actions.addStretch();right.addLayout(actions);right.addStretch();row.addLayout(right,1);self.stack.addWidget(body)
            editor.textChanged.connect(lambda k=key:self.changed(k))
        rule=QFrame();rule.setFrameShape(QFrame.Shape.HLine);rule.setStyleSheet('color:#E4DEEB;');v.addWidget(rule)
        actions=QHBoxLayout();actions.addWidget(button('기본값으로 되돌리기',lambda:self.reset(self.category.currentData())));actions.addStretch();actions.addWidget(button('응원 설정 저장',self.save,True));v.addLayout(actions)
        self.category.currentChanged.connect(self.select_category);self.refresh_preview()

    def field_help(self):
        QMessageBox.information(self,'자동 입력 항목','{학생명}  {점수}  {등급}  {목표등급}  {필요점수}\n성적표를 만들 때 학생별 내용으로 바뀝니다.')

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
