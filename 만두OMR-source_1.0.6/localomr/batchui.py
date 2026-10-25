from pathlib import Path
from PySide6.QtCore import Qt,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QCheckBox,QTableWidget,QTableWidgetItem,QHeaderView,QPushButton,QFileDialog,QMessageBox,QAbstractItemView
from .ranking import ranked_results,sorted_results,ranking_xlsx
from .examdata import ELECTIVES
from .reports import report_pdf
from .export_names import export_name
from .busy import run_store_task


class BatchOutputDialog(QDialog):
    def __init__(self,store,eid=None,parent=None,academy_id=None,class_id=None):
        super().__init__(parent);self.store=store;self.loading=True;self.class_ids=[];self.rows=[];self.initial_academy=academy_id;self.initial_class=class_id
        self.setWindowTitle('시험 · 반별 성적표 / 석차 엑셀');self.resize(1160,850)
        v=QVBoxLayout(self);top=QHBoxLayout();v.addLayout(top);top.addWidget(QLabel('시험'));self.exam=QComboBox();top.addWidget(self.exam,1)
        for e in store.exams():self.exam.addItem(e['title'],e['id'])
        self.exam.setCurrentIndex(max(0,self.exam.findData(eid)))
        v.addWidget(QLabel('출력할 반을 체크하세요. 응시 당시 소속을 기준으로 확정 성적만 표시합니다.'))
        from .tableui import CheckTable
        self.classes=CheckTable(['선택','학원','반','확정 인원','반 평균'],[80,250,250,100,100]);self.classes.setHorizontalHeaderLabels(['선택','학원','반','확정 인원','반 평균']);self.classes.verticalHeader().hide();self.classes.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.classes.setMaximumHeight(220);self.classes.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);v.addWidget(self.classes)
        line=QHBoxLayout();v.addLayout(line);line.addWidget(QLabel('출력 순서'));self.field=QComboBox();self.field.addItem('학생명','name');self.field.addItem('점수','score');line.addWidget(self.field)
        self.direction=QComboBox();self.direction.addItem('오름차순',False);self.direction.addItem('내림차순',True);line.addWidget(self.direction);self.group=QCheckBox('반별로 묶기');self.group.setChecked(True);line.addWidget(self.group);line.addStretch()
        self.summary=QLabel();v.addWidget(self.summary)
        self.preview=QTableWidget(0,8);self.preview.setHorizontalHeaderLabels(['출력 순서','학생명','반','선택과목','점수 / 만점','등급','시험 전체 석차','반 석차']);self.preview.verticalHeader().hide();self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);v.addWidget(self.preview,1)
        note=QLabel('아래 미리보기 순서로 출력합니다. 동점 석차는 1, 1, 3 방식이며 출력 정렬을 바꿔도 석차는 바뀌지 않습니다.\n엑셀에는 전체·선택 반·반·선택과목 석차와 추정 백분위를 저장합니다. 집계 인원은 내보내지 않습니다.');note.setWordWrap(True);v.addWidget(note)
        line=QHBoxLayout();v.addLayout(line);self.pdf_button=QPushButton('체크한 반 성적표 PDF');self.pdf_button.setObjectName('Primary');self.excel_button=QPushButton('체크한 반 석차 엑셀');line.addWidget(self.pdf_button);line.addWidget(self.excel_button)
        self.exam.currentIndexChanged.connect(self.load_classes);self.classes.itemChanged.connect(self.refresh_preview);self.classes.checksChanged.connect(self.refresh_preview);self.field.currentIndexChanged.connect(self.refresh_preview);self.direction.currentIndexChanged.connect(self.refresh_preview);self.group.toggled.connect(self.refresh_preview);self.pdf_button.clicked.connect(self.save_pdf);self.excel_button.clicked.connect(self.save_excel)
        self.loading=False;self.load_classes()

    def check_all(self,checked):
        self.loading=True
        for i in range(self.classes.rowCount()):self.classes.item(i,0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.loading=False;self.refresh_preview()

    def load_classes(self,*_):
        self.loading=True;eid=self.exam.currentData();rows=self.store.results(eid) if eid else [];groups={}
        for r in rows:groups.setdefault(r['snapshot']['class_id'],[]).append(r)
        self.class_ids=sorted(groups,key=lambda cid:(groups[cid][0]['snapshot']['academy'],groups[cid][0]['snapshot']['classroom'],cid));self.classes.setRowCount(len(groups))
        for i,cid in enumerate(self.class_ids):
            group=groups[cid];s=group[0]['snapshot'];item=QTableWidgetItem();item.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable|Qt.ItemFlag.ItemIsUserCheckable);item.setData(Qt.ItemDataRole.UserRole,cid);item.setCheckState(Qt.CheckState.Checked if (self.initial_class is None or cid==self.initial_class) and (self.initial_academy is None or s.get('academy_id')==self.initial_academy) else Qt.CheckState.Unchecked);self.classes.setItem(i,0,item)
            for j,value in enumerate([s['academy'],s['classroom'],len(group),f"{sum(r['score'] for r in group)/len(group)/100:.2f}"],1):self.classes.setItem(i,j,QTableWidgetItem(str(value)))
        self.loading=False;self.refresh_preview()

    def selected_classes(self):return [cid for i,cid in enumerate(self.class_ids) if self.classes.item(i,0).checkState()==Qt.CheckState.Checked]

    def refresh_preview(self,*_):
        if self.loading:return
        selected=self.selected_classes();eid=self.exam.currentData()
        self.rows=sorted_results(ranked_results(self.store,eid,selected),self.field.currentData(),self.direction.currentData(),self.group.isChecked()) if eid and selected else []
        self.preview.setRowCount(len(self.rows))
        for i,r in enumerate(self.rows):
            values=[i+1,r['snapshot']['name'],r['snapshot']['classroom'],ELECTIVES.get(r['elective'],r['subject']),f"{r['score']/100:g} / {r['maximum']/100:g}",r['grade'] or '미설정',f"{r['overall_rank']} / {r['overall_n']}",f"{r['class_rank']} / {r['class_n']}"]
            for j,value in enumerate(values):self.preview.setItem(i,j,QTableWidgetItem(str(value)))
        pages=sum(2 if r['config'].get('form')=='math30' else 1 for r in self.rows);self.summary.setText(f'선택 {len(selected)}개 반 · {len(self.rows)}명 · 성적표 {pages}쪽')
        self.pdf_button.setEnabled(bool(self.rows));self.excel_button.setEnabled(bool(self.rows))

    def save_pdf(self):
        if not self.rows:return
        path,_=QFileDialog.getSaveFileName(self,'반별 성적표 저장',export_name(self.rows),'PDF (*.pdf)')
        if not path:return
        try:
            ids=[r['id'] for r in self.rows];run_store_task(self,self.store,lambda db:report_pdf(path,db,ids),readonly=True)
            with self.store.transaction():self.store.log('batch_report_exported',self.exam.currentData(),{'scan_ids':ids,'class_ids':self.selected_classes(),'sort':self.field.currentData(),'descending':self.direction.currentData(),'group_classes':self.group.isChecked(),'file':Path(path).name})
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as exc:QMessageBox.warning(self,'출력 확인',str(exc))

    def save_excel(self):
        if not self.rows:return
        path,_=QFileDialog.getSaveFileName(self,'석차 엑셀 저장',export_name(self.rows,'rank'),'Excel (*.xlsx)')
        if not path:return
        try:
            args=(self.exam.currentData(),self.selected_classes(),self.field.currentData(),self.direction.currentData(),self.group.isChecked())
            count=run_store_task(self,self.store,lambda db:ranking_xlsx(path,db,*args),readonly=True)
            with self.store.transaction():self.store.log('ranking_exported',self.exam.currentData(),{'class_ids':self.selected_classes(),'count':count,'file':Path(path).name})
            QMessageBox.information(self,'엑셀 저장 완료',f'{count}명의 석차를 저장했습니다.\n{path}')
        except Exception as exc:QMessageBox.warning(self,'엑셀 저장 확인',str(exc))
