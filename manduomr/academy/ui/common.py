"""Shared widgets: progress runner, messages, simple tables. Screens call services only."""
from __future__ import annotations
import traceback
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication,QMessageBox,QProgressDialog,QTableWidget,QTableWidgetItem,QHeaderView,
                               QAbstractItemView,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QDialog,
                               QDialogButtonBox,QPlainTextEdit)

STYLE='''
QMainWindow,QWidget{font-family:"Malgun Gothic";font-size:13px;color:#203752}
QListWidget#nav{background:#203752;color:#FFFFFF;border:0;font-size:14px;padding:8px}
QListWidget#nav::item{padding:10px 8px;border-radius:6px}
QListWidget#nav::item:selected{background:#DF654F}
QPushButton{padding:6px 12px;border:1px solid #B8C4CF;border-radius:6px;background:#FFFFFF}
QPushButton#primary{background:#203752;color:#FFFFFF;border:0}
QLabel#title{font-size:18px;font-weight:bold}
QLabel#hint{color:#606A74}
'''


def install_fonts(app):
    """Register 맑은 고딕 explicitly so every Qt platform (including offscreen checks) renders Korean."""
    from pathlib import Path
    from PySide6.QtGui import QFontDatabase,QFont
    for name in ('malgun.ttf','malgunbd.ttf'):
        path=Path('C:/Windows/Fonts')/name
        if path.exists():QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont('Malgun Gothic',10))


def run(parent,title,fn,*args,**kwargs):
    """Run fn in the UI thread with a progress dialog. fn may accept progress=callable."""
    dialog=QProgressDialog(title,None,0,0,parent);dialog.setWindowTitle('작업 중');dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setMinimumDuration(300);dialog.show();QApplication.processEvents()
    def progress(text):
        dialog.setLabelText(str(text));QApplication.processEvents()
    import inspect
    try:accepts='progress' in inspect.signature(fn).parameters
    except (TypeError,ValueError):accepts=False
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        return fn(*args,progress=progress,**kwargs) if accepts else fn(*args,**kwargs)
    finally:
        QApplication.restoreOverrideCursor();dialog.close()


def error(parent,exc,title='확인 필요'):
    text=str(exc) if isinstance(exc,(ValueError,FileExistsError,PermissionError)) or exc.__class__.__name__ in ('SessionBlocked','DriveUnavailable','BackupInvalid','UploadFailed','AlreadySent','AutomationFailed','HwpUnavailable') else f'처리하지 못했습니다.\n{exc}'
    QMessageBox.warning(parent,title,text)


def info(parent,text,title='완료'):
    QMessageBox.information(parent,title,text)


def ask(parent,text,title='확인',default_no=True):
    box=QMessageBox(parent);box.setWindowTitle(title);box.setText(text);box.setIcon(QMessageBox.Icon.Question)
    box.setStandardButtons(QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No if default_no else QMessageBox.StandardButton.Yes)
    return box.exec()==QMessageBox.StandardButton.Yes


def guarded(parent,fn):
    """Wrap a button handler so service errors become messages, not crashes."""
    def handler(*_):
        try:return fn()
        except Exception as exc:
            if not isinstance(exc,ValueError):traceback.print_exc()
            error(parent,exc)
    return handler


class Table(QTableWidget):
    def __init__(self,headers,parent=None,editable=False):
        super().__init__(0,len(headers),parent);self.setHorizontalHeaderLabels(headers)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive);self.horizontalHeader().setStretchLastSection(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.verticalHeader().setVisible(False)
        if not editable:self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    def fill(self,rows,ids=None):
        self.setRowCount(0)
        for r,row in enumerate(rows):
            self.insertRow(r)
            for c,value in enumerate(row):
                item=QTableWidgetItem('' if value is None else str(value))
                if ids is not None and c==0:item.setData(Qt.ItemDataRole.UserRole,ids[r])
                self.setItem(r,c,item)
        self.resizeColumnsToContents()

    def selected_ids(self):
        rows=sorted({i.row() for i in self.selectedIndexes()})
        return [self.item(r,0).data(Qt.ItemDataRole.UserRole) for r in rows if self.item(r,0)]

    def current_id(self):
        ids=self.selected_ids();return ids[0] if ids else None


def page(title,hint=''):
    widget=QWidget();layout=QVBoxLayout(widget)
    label=QLabel(title);label.setObjectName('title');layout.addWidget(label)
    if hint:
        h=QLabel(hint);h.setObjectName('hint');h.setWordWrap(True);layout.addWidget(h)
    return widget,layout


def row(*widgets):
    box=QHBoxLayout()
    for w in widgets:
        if w=='stretch':box.addStretch(1)
        else:box.addWidget(w)
    return box


def button(text,handler,primary=False):
    b=QPushButton(text)
    if primary:b.setObjectName('primary')
    b.clicked.connect(handler);return b


def combo(items,current=None):
    """items: [(label, data)]"""
    c=QComboBox()
    for label,data in items:c.addItem(label,data)
    if current is not None:
        index=c.findData(current)
        if index>=0:c.setCurrentIndex(index)
    return c


class TextDialog(QDialog):
    """Read-only text for manual sending (문구·링크·대상 목록) with a copy button."""
    def __init__(self,title,text,parent=None,confirm_label=None):
        super().__init__(parent);self.setWindowTitle(title);self.resize(560,460)
        layout=QVBoxLayout(self);self.box=QPlainTextEdit(text);self.box.setReadOnly(True);layout.addWidget(self.box)
        buttons=QDialogButtonBox();copy=buttons.addButton('복사',QDialogButtonBox.ButtonRole.ActionRole)
        copy.clicked.connect(lambda:QApplication.clipboard().setText(text))
        if confirm_label:buttons.addButton(confirm_label,QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton('닫기',QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
