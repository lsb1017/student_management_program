"""Backup labels are local naming preferences, never a data export filter."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QDialogButtonBox
from .reports import report_asset

class BackupNameDialog(QDialog):
    def __init__(self,store,state,parent=None):
        super().__init__(parent);self.store=store
        self.setWindowTitle('새 백업 저장');self.setStyleSheet('QDialog {background:white;}');self.setMinimumWidth(490)
        v=QVBoxLayout(self);v.setContentsMargins(22,20,22,20);v.setSpacing(16)
        row=QHBoxLayout();mascot=QLabel();mascot.setPixmap(QPixmap(str(report_asset('celebrate_mandu.png'))).scaled(82,82,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.FastTransformation));row.addWidget(mascot)
        copy=QVBoxLayout();title=QLabel('오늘도 수고 많으셨어요!');title.setStyleSheet('font-size:18px;font-weight:700;');copy.addWidget(title);copy.addWidget(QLabel('파일명에 표시할 학원과 반을 선택해 주세요.'));row.addLayout(copy,1);v.addLayout(row)
        row=QHBoxLayout();row.addWidget(QLabel('학원명:'));self.academy=QComboBox();self.academy.setMinimumWidth(160);row.addWidget(self.academy,1);row.addWidget(QLabel('반명:'));self.classroom=QComboBox();self.classroom.setMinimumWidth(160);row.addWidget(self.classroom,1);v.addLayout(row)
        self.academy.addItem('전체 학원',None)
        for a in store.rows('SELECT id,name FROM academies ORDER BY name'):self.academy.addItem(a['name'],a['id'])
        self.academy.currentIndexChanged.connect(self.refresh_classes)
        self.academy.setCurrentIndex(max(0,self.academy.findText(state.get('backup_academy',''))));self.refresh_classes()
        self.classroom.setCurrentIndex(max(0,self.classroom.findText(state.get('backup_classroom',''))))
        self.filename_preview=QLabel();self.filename_preview.setObjectName('Sub');self.filename_preview.setWordWrap(True);v.addWidget(self.filename_preview)
        note=QLabel('학원·반은 파일명에만 표시되며, 전체 자료가 백업됩니다.');note.setObjectName('Sub');v.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Ok).setText('확인');buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName('Primary');buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소');buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);v.addWidget(buttons)
        self.academy.currentIndexChanged.connect(self.update_preview);self.classroom.currentIndexChanged.connect(self.update_preview);self.update_preview()

    def refresh_classes(self,*_):
        self.classroom.clear();self.classroom.addItem('전체 반',None)
        aid=self.academy.currentData()
        if aid is not None:
            for c in self.store.classes():
                if c['academy_id']==aid:self.classroom.addItem(c['name'],c['id'])

    def names(self):return self.academy.currentText(),self.classroom.currentText()

    def update_preview(self,*_):
        from datetime import datetime
        from .handoff import filename_part
        academy,classroom=self.names()
        self.filename_preview.setText(datetime.now().strftime('%Y%m%d_%H%M')+'_'+filename_part(academy)+'_'+filename_part(classroom)+'.omrbackup')
