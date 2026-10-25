from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QComboBox,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QPushButton,QMessageBox


class MakeupStudentDialog(QDialog):
    def __init__(self,store,parent=None):
        super().__init__(parent);self.store=store;self.student_id=None
        self.setWindowTitle('보강생 연결');self.resize(760,480)
        v=QVBoxLayout(self);v.addWidget(QLabel('보강 학생을 직접 찾아 연결합니다. 성적은 학생의 원래 학원·반 평균과 개인 누적에 포함됩니다.'))
        h=QHBoxLayout();v.addLayout(h);self.academy=QComboBox();self.academy.addItem('모든 학원',None)
        for row in store.rows('SELECT id,name FROM academies ORDER BY name'):self.academy.addItem(row['name'],row['id'])
        h.addWidget(self.academy);self.search=QLineEdit();self.search.setPlaceholderText('이름 · 학생번호 · 전화번호 뒤 4자리');h.addWidget(self.search,1)
        self.table=QTableWidget(0,5);self.table.setHorizontalHeaderLabels(['학생명','학생번호','원래 학원','원래 반','학교']);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);v.addWidget(self.table,1)
        self.note=QLabel('연결할 학생을 선택하세요. 학생 등록 소속은 변경하지 않습니다.');self.note.setWordWrap(True);v.addWidget(self.note)
        h=QHBoxLayout();v.addLayout(h);h.addStretch();cancel=QPushButton('취소');cancel.clicked.connect(self.reject);h.addWidget(cancel)
        self.connect_button=QPushButton('이 학생 연결');self.connect_button.setObjectName('Primary');self.connect_button.setEnabled(False);self.connect_button.clicked.connect(self.select_student);h.addWidget(self.connect_button)
        self.search.textChanged.connect(self.refresh);self.academy.currentIndexChanged.connect(self.refresh);self.table.itemSelectionChanged.connect(self.selection_changed);self.table.cellDoubleClicked.connect(self.select_student);self.refresh();self.search.setFocus()

    def refresh(self,*_):
        query=self.search.text().strip().lower();aid=self.academy.currentData()
        self.rows=[r for r in self.store.students() if r['active'] and (aid is None or r['academy_id']==aid) and (not query or query in r['name'].lower() or query in r['code'] or query in r.get('phone',''))]
        self.table.blockSignals(True);self.table.setRowCount(len(self.rows));self.table.clearSelection();self.table.setCurrentCell(-1,-1)
        for i,r in enumerate(self.rows):
            for j,value in enumerate([r['name'],r['code'][-5:],r['academy'],r['classroom'],r['school']]):
                item=QTableWidgetItem(value);item.setData(Qt.ItemDataRole.UserRole,r['id']);self.table.setItem(i,j,item)
        self.table.blockSignals(False);self.connect_button.setEnabled(False);self.note.setText(f'검색 결과 {len(self.rows)}명 · 이름과 원래 학원·반을 확인하고 선택하세요.')

    def selection_changed(self):
        row=self.table.currentRow();selected=bool(self.table.selectedItems()) and 0<=row<len(self.rows)
        self.connect_button.setEnabled(selected)
        if selected:
            r=self.rows[row];self.note.setText(f"{r['name']} ({r['code'][-5:]}) → {r['academy']} / {r['classroom']} 소속으로 성적 기록\n기존 개인 성적에 누적되며 학생을 새로 등록하지 않습니다.")

    def select_student(self,*_):
        row=self.table.currentRow()
        if row<0 or not self.table.selectedItems():return
        r=self.rows[row]
        if QMessageBox.question(self,'보강 학생 확인',f"{r['name']} ({r['code'][-5:]}) 학생을 이 답안에 연결할까요?\n성적은 {r['academy']} / {r['classroom']}에 기록합니다.\n이미 확정한 답안이라면 검수 대기로 바뀝니다.")!=QMessageBox.StandardButton.Yes:return
        self.student_id=r['id'];self.accept()
