from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QComboBox,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QPushButton,QDialogButtonBox,QMessageBox
from .history import results
from .examdata import ELECTIVES


class HistoryDialog(QDialog):
    def __init__(self,store,parent=None):
        super().__init__(parent);self.store=store;self.setWindowTitle('이전 성적 조회');self.resize(1200,750);self.rows=results(store)
        layout=QVBoxLayout(self);bar=QHBoxLayout();layout.addLayout(bar)
        self.search=QLineEdit();self.search.setPlaceholderText('학생명 · 학생번호 · 학원 · 반 검색');bar.addWidget(self.search,1)
        self.exam=QComboBox();self.exam.addItem('모든 이전 시험',None)
        for title in sorted({r['title'] for r in self.rows}):self.exam.addItem(title,title)
        bar.addWidget(self.exam,1);cuts=QPushButton('이전 시험 등급컷');cuts.clicked.connect(self.edit_cuts);bar.addWidget(cuts);self.count=QLabel();layout.addWidget(self.count)
        self.table=QTableWidget(0,10);self.table.setHorizontalHeaderLabels(['학원','반','학생명','학생번호','시험명','응시일자','선택과목','원점수','등급','시험 평균'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i,width in enumerate([105,155,85,75,300,95,95,65,45,75]):self.table.setColumnWidth(i,width)
        layout.addWidget(self.table,1)
        layout.addWidget(QLabel('행을 더블클릭하면 문항별 점수 · OX · 학생 답안을 확인합니다. 영역·유형 분류는 추가 등록 후 클리닉 분석에 연결할 수 있습니다.'))
        self.search.textChanged.connect(self.refresh);self.exam.currentIndexChanged.connect(self.refresh);self.table.cellDoubleClicked.connect(self.details);self.refresh()

    def refresh(self,*_):
        query=self.search.text().strip().lower();title=self.exam.currentData()
        rows=[r for r in self.rows if (not title or r['title']==title) and (not query or query in ' '.join(str(r['snapshot'].get(k,'')) for k in ('name','code','academy','classroom')).lower())]
        self.table.setSortingEnabled(False);self.table.setRowCount(len(rows))
        for i,r in enumerate(rows):
            s=r['snapshot'];values=[s['academy'],s['classroom'],s['name'],s['code'][-5:],r['title'],r['day'],ELECTIVES.get(r['elective'],'확인 필요'),r['score']/100,r['grade'] or '—',r['historical_mean']]
            for col,v in enumerate(values):
                item=QTableWidgetItem();item.setData(Qt.ItemDataRole.EditRole,v);item.setData(Qt.ItemDataRole.UserRole,r['id']);self.table.setItem(i,col,item)
        self.table.setSortingEnabled(True);self.count.setText(f'이전 성적 {len(rows):,}건 · 시험 {len({r["exam_id"] for r in rows})}개')

    def details(self,row,col):
        rid=self.table.item(row,0).data(Qt.ItemDataRole.UserRole);r=next(x for x in self.rows if x['id']==rid)
        dialog=QDialog(self);dialog.setWindowTitle(r['snapshot']['name']+' · '+r['title']);dialog.resize(540,720);layout=QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"응시 {r['day']} · 원점수 {r['score']/100:g} · 표준점수 {r['standard_score'] if r['standard_score'] is not None else '미입력'}"))
        table=QTableWidget(30,4);table.setHorizontalHeaderLabels(['문항','점수','OX','학생 답안']);table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for q in range(30):
            for col,val in enumerate([q+1,r['earned'][q]/100,r['ox'][q] or '무응답',r['answers'][q] if r['answers'][q] is not None else '—']):table.setItem(q,col,QTableWidgetItem(str(val)))
        layout.addWidget(table)
        if r['notes']:layout.addWidget(QLabel(r['notes']))
        if r.get('elective_inferred'):layout.addWidget(QLabel('선택과목은 이 학생의 최근 확인된 기록을 적용했습니다.'))
        dialog.exec()

    def edit_cuts(self):
        dialog=HistoryCutsDialog(self.store,self.exam.currentData(),self)
        dialog.exec();self.rows=results(self.store);self.refresh()


class HistoryCutsDialog(QDialog):
    def __init__(self,store,title=None,parent=None):
        super().__init__(parent);self.store=store;self.setWindowTitle('이전 시험 등급컷');self.resize(650,300)
        layout=QVBoxLayout(self);self.exam=QComboBox()
        for row in store.rows('SELECT id,title FROM historical_exams ORDER BY day DESC,id DESC'):self.exam.addItem(row['title'],row['id'])
        layout.addWidget(self.exam);self.table=QTableWidget(3,5);self.table.setVerticalHeaderLabels(list(ELECTIVES.values()));self.table.setHorizontalHeaderLabels([f'{i}등급' for i in range(1,6)])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);layout.addWidget(self.table)
        note=QLabel('선택과목별로 1~5등급컷을 모두 입력하거나 모두 비우세요.\n저장한 컷으로 해당 시험의 등급·추정 백분위를 계산합니다.');note.setWordWrap(True);layout.addWidget(note)
        self.source_note=QLabel();self.source_note.setWordWrap(True);layout.addWidget(self.source_note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.save);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        if title:self.exam.setCurrentIndex(max(0,self.exam.findText(title)))
        self.active_exam=None;self.initial_values=None
        self.exam.currentIndexChanged.connect(self.switch_exam);self.load()

    def values(self):
        values={}
        for i,choice in enumerate(ELECTIVES):
            cells=[self.table.item(i,j).text().strip() for j in range(5)]
            values[choice]=cells if any(cells) else []
        return values

    def save_current(self):
        from .history import save_cuts
        try:save_cuts(self.store,self.active_exam,self.values())
        except ValueError as exc:QMessageBox.warning(self,'등급컷 확인',str(exc));return False
        self.initial_values=self.values();return True

    def leave_current(self):
        if self.initial_values is None or self.values()==self.initial_values:return True
        from .draftui import unsaved_choice
        choice=unsaved_choice(self)
        return self.save_current() if choice=='save' else choice=='discard'

    def switch_exam(self,*_):
        if not self.leave_current():
            self.exam.blockSignals(True);self.exam.setCurrentIndex(self.exam.findData(self.active_exam));self.exam.blockSignals(False);return
        self.load()

    def reject(self):
        if self.leave_current():super().reject()

    def closeEvent(self,event):
        event.ignore();self.reject()

    def load(self,*_):
        import json
        self.active_exam=self.exam.currentData()
        row=self.store.db.execute('SELECT cuts_json,cut_note FROM historical_exams WHERE id=?',(self.exam.currentData(),)).fetchone()
        values=json.loads(row[0]) if row else {}
        self.source_note.setText(row[1] if row else '')
        for i,choice in enumerate(ELECTIVES):
            cuts=values.get(choice,[])
            for j in range(5):self.table.setItem(i,j,QTableWidgetItem(str(cuts[j]) if j<len(cuts) else ''))
        self.initial_values=self.values()

    def save(self):
        if self.save_current():self.accept()
