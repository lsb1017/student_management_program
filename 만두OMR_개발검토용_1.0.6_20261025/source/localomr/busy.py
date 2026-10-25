"""Small, on-demand activity indicator for operations that can take time."""
from PySide6.QtCore import Qt, QThread, QTimer,QRectF,QSize
from PySide6.QtGui import QPainter,QPixmap,QColor,QPainterPath
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar
from .store import Store

BUSY_TEXT = '작업 중이에요.\n잠시만 기다려 주세요.'

class ManduProgressBar(QProgressBar):
    """A cached sprite; the 12 fps timer runs only while indeterminate and visible."""
    def __init__(self,parent=None):
        super().__init__(parent)
        from .reports import report_asset
        from .popup_style import mascot_pixmap
        self.sprite=mascot_pixmap('running_mandu.png',60)
        image=self.sprite.toImage()
        self.sprite_foot=max(y for y in range(image.height()) for x in range(image.width()) if image.pixelColor(x,y).alpha()>32)
        self.phase=0;self.timer=QTimer(self);self.timer.setInterval(80);self.timer.timeout.connect(self.tick)
        self.setFixedHeight(86);self.setTextVisible(False);self.setRange(0,0)

    def sizeHint(self):return QSize(super().sizeHint().width(),86)

    def minimumSizeHint(self):return QSize(120,86)

    def setRange(self, minimum, maximum):
        super().setRange(minimum,maximum)
        if hasattr(self,'timer'):
            if minimum==maximum and self.isVisible():self.timer.start()
            else:self.timer.stop()

    def tick(self):
        if self.minimum()!=self.maximum():self.timer.stop();return
        self.phase=(self.phase+1)%72;self.update()

    def showEvent(self,event):
        super().showEvent(event)
        if self.minimum()==self.maximum():self.timer.start()

    def hideEvent(self,event):self.timer.stop();super().hideEvent(event)

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left=2;length=max(1,self.width()-4);y=64;height=20
        track=QRectF(left,y,length,height);clip=QPainterPath();clip.addRoundedRect(track,7,7);p.setClipPath(clip)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#EBE5F2'));p.drawRoundedRect(track,7,7)
        busy=self.minimum()==self.maximum()
        ratio=self.phase/71 if busy else max(0,min(1,(self.value()-self.minimum())/max(1,self.maximum()-self.minimum())))
        x=left+ratio*length;p.setBrush(QColor('#B6A0DC'))
        start=max(left,x-70) if busy else left
        p.drawRoundedRect(QRectF(start,y,max(0,x-start),height),7,7)
        sprite_x=max(left+1,min(left+length-self.sprite.width()-1,x-self.sprite.width()))
        p.setClipping(False)
        p.drawPixmap(round(sprite_x),round(y-1-self.sprite_foot),self.sprite);p.end()


class BusyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('작업 중')
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)
        self.message = QLabel(BUSY_TEXT)
        layout.addWidget(self.message)
        bar = ManduProgressBar()
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        layout.addWidget(bar)
        self.setFixedSize(420, 205)

    def reject(self):
        # Escape must not release the main window while its data is changing.
        pass

    def closeEvent(self, event):
        event.ignore()


class StoreTask(QThread):
    def __init__(self, path, task, readonly, parent):
        super().__init__(parent)
        self.path, self.task, self.readonly = path, task, readonly
        self.value = None
        self.error = None

    def run(self):
        store = None
        try:
            # SQLite connections belong to the thread that created them.
            store = Store.open_existing(self.path, readonly=self.readonly)
            self.value = self.task(store)
        except Exception as exc:
            self.error = exc
        finally:
            if store is not None:
                try:
                    store.close()
                except Exception as exc:
                    if self.error is None:self.error = exc


def run_store_task(parent, store, task, *, readonly=False):
    """Keep Qt responsive; task receives its own connection and must not use UI."""
    owner = parent
    while owner.parentWidget() is not None:owner = owner.parentWidget()
    if getattr(owner, '_busy_operation', False) or getattr(owner, 'worker', None):
        raise ValueError('현재 작업이 끝난 뒤 다시 시도해 주세요.')
    if store.db.in_transaction:
        raise ValueError('편집 중인 자료를 먼저 저장해 주세요.')
    dialog = BusyDialog(parent)
    worker = StoreTask(store.path, task, readonly, dialog)
    worker.finished.connect(dialog.accept)
    owner._busy_operation = True
    try:
        QTimer.singleShot(0, worker.start)
        dialog.exec()
        worker.wait()
        if worker.error is not None:raise worker.error
        return worker.value
    finally:
        owner._busy_operation = False
        dialog.deleteLater()
