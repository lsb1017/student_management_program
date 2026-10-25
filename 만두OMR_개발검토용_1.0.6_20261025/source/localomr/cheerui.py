from copy import deepcopy
from io import BytesIO
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QTextEdit,QGroupBox,QScrollArea,QWidget,QFileDialog,QMessageBox
from . import cheer

class CheerDialog(QDialog):
    def __init__(self,store,parent=None):
        super().__init__(parent)
        from .ui import button,label
        self.store=store;self.config=cheer.settings(store);self.editors={};self.previews={}
        self.setWindowTitle('응원 문구 · 이미지 설정');self.resize(810,760)
        outer=QVBoxLayout(self);outer.addWidget(label('성적에 따라 문구와 이미지를 자동으로 선택합니다. 만점 학생을 먼저 구분합니다.'))
        outer.addWidget(label('자동 입력: {학생명}  {점수}  {등급}  {목표등급}  {필요점수}\n120자·최대 3줄 / 대광유리체 · PNG/JPG · 문구와 이미지는 전체 데이터 백업에 포함됩니다.','Sub'))
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();v=QVBoxLayout(body);scroll.setWidget(body);outer.addWidget(scroll,1)
        for category,title in cheer.CATEGORIES.items():
            box=QGroupBox(title);bv=QVBoxLayout(box);row=QHBoxLayout();bv.addLayout(row)
            editor=QTextEdit();editor.setAcceptRichText(False);editor.setFixedHeight(92);editor.setPlainText(self.config[category]['text']);self.editors[category]=editor;row.addWidget(editor,1)
            preview=QLabel();preview.setFixedSize(330,100);preview.setAlignment(Qt.AlignmentFlag.AlignCenter);preview.setStyleSheet('background:white;border:1px solid #DCE4EA;border-radius:6px;');self.previews[category]=preview;row.addWidget(preview)
            actions=QHBoxLayout();bv.addLayout(actions)
            actions.addWidget(button('이미지 업로드',lambda _,k=category:self.upload(k)));actions.addWidget(button('이미지 삭제',lambda _,k=category:self.remove(k)));actions.addWidget(button('기본값 복원',lambda _,k=category:self.reset(k)));actions.addStretch();v.addWidget(box)
            editor.textChanged.connect(lambda k=category:self.preview(k))
            self.preview(category)
        buttons=QHBoxLayout();outer.addLayout(buttons);buttons.addStretch();buttons.addWidget(button('취소',self.reject));buttons.addWidget(button('모든 유형 저장',self.save,True))

    def sample(self,category):
        return {'score':10000 if category=='perfect' else 8400 if category=='grade1' else 3800 if category=='grade5plus' else 7800,'maximum':10000,'cuts':[84,76,65,54,40],'snapshot':{'name':'예시학생'}}

    def preview(self,category):
        from reportlab.pdfgen import canvas
        import pypdfium2 as pdfium
        self.config[category]['text']=self.editors[category].toPlainText()
        try:
            cheer.validate(self.config)
            output=BytesIO();c=canvas.Canvas(output,pagesize=(330,100));c.setFillColor('white');c.rect(0,0,330,100,fill=1,stroke=0)
            cheer.draw_cheer(c,self.sample(category),self.store,12,14,306,72,self.config);c.showPage();c.save()
            doc=pdfium.PdfDocument(output.getvalue());page=doc[0];bitmap=page.render(scale=1.5)
            try:
                buffer=BytesIO();bitmap.to_pil().save(buffer,format='PNG');pix=QPixmap();pix.loadFromData(buffer.getvalue());self.previews[category].setPixmap(pix.scaled(326,96,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            finally:bitmap.close();page.close();doc.close()
        except Exception as exc:self.previews[category].setText(str(exc))

    def upload(self,category):
        from pathlib import Path
        path,_=QFileDialog.getOpenFileName(self,'응원 이미지 선택','','이미지 (*.png *.jpg *.jpeg)')
        if not path:return
        try:
            if Path(path).stat().st_size>8*1024*1024:raise ValueError('8MB 이하 이미지를 선택하세요.')
            self.config[category]['image']=cheer.encode_image(Path(path).read_bytes());self.preview(category)
        except ValueError as exc:QMessageBox.warning(self,'이미지 확인',str(exc))

    def remove(self,category):self.config[category]['image']=None;self.preview(category)

    def reset(self,category):
        self.config[category]=deepcopy(cheer.DEFAULTS[category]);self.editors[category].setPlainText(self.config[category]['text']);self.preview(category)

    def save(self):
        try:cheer.save(self.store,self.config);self.accept()
        except ValueError as exc:QMessageBox.warning(self,'문구 확인',str(exc))
