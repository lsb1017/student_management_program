"""Small static illustrations shared by confirmation dialogs."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QMessageBox,QDialog,QLabel,QVBoxLayout,QHBoxLayout,QPushButton
from .reports import report_asset

class IllustratedMessage(QMessageBox):
    def reject(self):self.done(QMessageBox.StandardButton.Cancel)
    def closeEvent(self,event):self.reject();event.accept()
    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:self.reject();return
        super().keyPressEvent(event)

class PendingReviewDialog(QDialog):
    def __init__(self,parent,text):
        super().__init__(parent);self.setWindowTitle('검수 대기 안내');self.setStyleSheet('QDialog {background:white;}');self.setMinimumWidth(510)
        v=QVBoxLayout(self);v.setContentsMargins(22,20,22,18);v.setSpacing(18);row=QHBoxLayout();row.setSpacing(20)
        image=QLabel();image.setPixmap(QPixmap(str(report_asset('smart_mandu.png'))).scaled(82,82,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.FastTransformation));row.addWidget(image)
        copy=QVBoxLayout()
        for i,line in enumerate(text.splitlines()):
            label=QLabel(line)
            if i==0:label.setStyleSheet('font-size:17px;font-weight:700;')
            copy.addWidget(label)
        row.addLayout(copy,1);v.addLayout(row)
        actions=QHBoxLayout();actions.addStretch();stay=QPushButton('계속 검수하기');stay.setObjectName('Primary');stay.setDefault(True);stay.clicked.connect(self.reject);actions.addWidget(stay)
        move=QPushButton('다른 탭 이동');move.clicked.connect(lambda:self.done(int(QMessageBox.StandardButton.Yes)));actions.addWidget(move);v.addLayout(actions);stay.setFocus()

def ask(parent,title,text,asset,buttons=None,default=None,labels=None):
    if title=='검수 대기 안내' and asset=='smart_mandu.png':return PendingReviewDialog(parent,text).exec()
    buttons=buttons or (QMessageBox.StandardButton.Ok|QMessageBox.StandardButton.Cancel)
    dialog=IllustratedMessage(parent);dialog.setWindowTitle(title)
    dialog.setTextFormat(Qt.TextFormat.PlainText);dialog.setText(text)
    dialog.setIconPixmap(QPixmap(str(report_asset(asset))).scaled(86,86,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
    dialog.setStandardButtons(buttons)
    if default:dialog.setDefaultButton(default)
    for key,label in (labels or {QMessageBox.StandardButton.Ok:'확인',QMessageBox.StandardButton.Cancel:'취소'}).items():
        if dialog.button(key):dialog.button(key).setText(label)
    return dialog.exec()
