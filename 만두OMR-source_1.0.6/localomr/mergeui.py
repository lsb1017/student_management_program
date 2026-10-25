from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QComboBox,QLabel,QPushButton,QMessageBox,QTableWidget,QTableWidgetItem,QHeaderView
from .studentmerge import preview,merge
from .busy import run_store_task

class MergeStudentsDialog(QDialog):
    def __init__(self,store,parent=None):
        super().__init__(parent);self.store=store;self.setWindowTitle('학생 합치기');self.resize(720,520)
        layout=QVBoxLayout(self);form=QFormLayout();layout.addLayout(form)
        self.keep=QComboBox();self.source=QComboBox()
        for combo in (self.keep,self.source):
            combo.addItem('학생 선택',None)
            for s in store.students():combo.addItem(f"{s['name']} · {s['code'][-5:]} · {s['academy']} / {s['classroom']}",s['id'])
        form.addRow('유지할 학생',self.keep);form.addRow('옮길 학생',self.source)
        note=QLabel('유지할 학생의 번호와 성적은 보존합니다. 옮길 학생의 수기 성적과 중복 시험 기록만 삭제합니다.\n나머지 OMR은 확정 상태 그대로 옮기고 소속 반을 함께 연결합니다. 성적 소속은 유지할 학생의 기본 반으로 바뀝니다.');note.setWordWrap(True);layout.addWidget(note)
        self.rows=QTableWidget(0,3);self.rows.setHorizontalHeaderLabels(['삭제될 시험명','점수','사유']);self.rows.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);layout.addWidget(self.rows)
        self.status=QLabel('두 학생을 선택해 삭제 목록을 확인하세요.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.go=QPushButton('삭제 목록 확인 후 합치기');self.go.setEnabled(False);self.go.clicked.connect(self.apply);layout.addWidget(self.go)
        cancel=QPushButton('취소');cancel.clicked.connect(self.reject);layout.addWidget(cancel)
        self.keep.currentIndexChanged.connect(self.refresh);self.source.currentIndexChanged.connect(self.refresh);self.plan=None

    def refresh(self):
        self.plan=None;self.go.setEnabled(False);self.rows.setRowCount(0)
        if self.keep.currentData() is None or self.source.currentData() is None:return
        try:self.plan=preview(self.store,self.keep.currentData(),self.source.currentData())
        except (ValueError,IndexError) as exc:self.status.setText(str(exc));return
        self.rows.setRowCount(len(self.plan['removed']))
        for i,r in enumerate(self.plan['removed']):
            for j,v in enumerate([r['title'],f"{r['score']:g}",r['reason']]):
                item=QTableWidgetItem(v);item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable);self.rows.setItem(i,j,item)
        self.status.setText(f"이동할 OMR {len(self.plan['moved'])}건 · 삭제할 기록 {len(self.plan['removed'])}건\n처리 전 전체 안전 백업을 저장합니다. 옮길 학생 등록은 합친 뒤 제거됩니다.")
        self.go.setEnabled(True)

    def apply(self):
        if not self.plan:return
        box=QMessageBox(self);box.setWindowTitle('학생 합치기 확인');box.setTextFormat(Qt.TextFormat.PlainText)
        p=self.plan;lines=[f"유지: {p['keep']['name']} ({p['keep']['code'][-5:]})",f"옮김: {p['source']['name']} ({p['source']['code'][-5:]})",'삭제할 기록:']
        lines.extend(f"{r['title']} · {r['score']:g}점 · {r['reason']}" for r in p['removed']);lines.append('없음' if not p['removed'] else '위 기록은 삭제됩니다.')
        lines.append('안전 백업 후 진행합니다. 합치기 취소는 전체 백업 복원이 필요합니다.');box.setText('\n'.join(lines))
        yes=box.addButton('삭제 후 합치기' if p['removed'] else '학생 합치기',QMessageBox.ButtonRole.AcceptRole);cancel=box.addButton('취소',QMessageBox.ButtonRole.RejectRole);box.setDefaultButton(cancel);box.exec()
        if box.clickedButton()!=yes:return
        try:
            run_store_task(self,self.store,lambda db:merge(db,p['keep']['id'],p['source']['id'],p['fingerprint']),readonly=False)
        except Exception as exc:QMessageBox.warning(self,'학생 합치기 실패',str(exc));self.refresh();return
        QMessageBox.information(self,'학생 합치기 완료','학생을 합쳤어요. 성적을 확인하고 새 백업을 저장해 주세요.');self.accept()
