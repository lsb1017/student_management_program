"""Rename existing academies and classes without creating new memberships."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QListWidget,QListWidgetItem,QLineEdit,QPushButton,QMessageBox


class OrganizationDialog(QDialog):
    def __init__(self,store,parent=None):
        super().__init__(parent);self.store=store;self.setWindowTitle('학원 · 반 이름 변경');self.resize(650,480)
        layout=QVBoxLayout(self)
        note=QLabel('학원 또는 반을 선택하고 이름을 수정하세요.\n학생 소속과 성적 연결은 유지되며, 기존 성적의 학원·반 표기도 함께 바뀝니다.');note.setWordWrap(True);layout.addWidget(note)
        columns=QHBoxLayout();layout.addLayout(columns,1)
        self.academies=QListWidget();self.classes=QListWidget();columns.addWidget(self.academies);columns.addWidget(self.classes)
        self.academy_name=QLineEdit();self.class_name=QLineEdit()
        for title,edit,kind in [('학원명',self.academy_name,'academy'),('반명',self.class_name,'class')]:
            bar=QHBoxLayout();bar.addWidget(QLabel(title));bar.addWidget(edit,1);button=QPushButton(title+' 저장');button.clicked.connect(lambda _,k=kind:self.save(k));bar.addWidget(button);layout.addLayout(bar)
        close=QPushButton('닫기');close.clicked.connect(self.accept);layout.addWidget(close)
        self.academies.currentItemChanged.connect(self.select_academy);self.classes.currentItemChanged.connect(self.select_class)
        self.refresh()

    def refresh(self,aid=None,cid=None):
        self.academies.clear()
        for row in self.store.rows('SELECT * FROM academies ORDER BY name'):
            item=QListWidgetItem(row['name']);item.setData(Qt.ItemDataRole.UserRole,row['id']);self.academies.addItem(item)
        index=next((i for i in range(self.academies.count()) if self.academies.item(i).data(Qt.ItemDataRole.UserRole)==aid),0)
        self.academies.setCurrentRow(index)
        if cid is not None:
            for i in range(self.classes.count()):
                if self.classes.item(i).data(Qt.ItemDataRole.UserRole)==cid:self.classes.setCurrentRow(i);break

    def select_academy(self,current,*_):
        self.classes.clear();self.academy_name.setText(current.text() if current else '');self.class_name.clear()
        if current:
            aid=current.data(Qt.ItemDataRole.UserRole)
            for row in self.store.classes():
                if row['academy_id']==aid:
                    item=QListWidgetItem(row['name']);item.setData(Qt.ItemDataRole.UserRole,row['id']);self.classes.addItem(item)
            self.classes.setCurrentRow(0)

    def select_class(self,current,*_):self.class_name.setText(current.text() if current else '')

    def save(self,kind):
        item=(self.academies if kind=='academy' else self.classes).currentItem()
        if not item:return
        aid=self.academies.currentItem().data(Qt.ItemDataRole.UserRole)
        cid=self.classes.currentItem().data(Qt.ItemDataRole.UserRole) if self.classes.currentItem() else None
        try:self.store.rename_organization(kind,item.data(Qt.ItemDataRole.UserRole),(self.academy_name if kind=='academy' else self.class_name).text())
        except ValueError as exc:QMessageBox.warning(self,'이름 변경 확인',str(exc));return
        self.refresh(aid,cid)
