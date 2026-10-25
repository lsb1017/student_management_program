"""An isolated copy of an old backup, migrated there and reopened read-only."""
import sqlite3,tempfile
from pathlib import Path
from PySide6.QtCore import Qt,QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QTabWidget,QWidget,QLineEdit,QComboBox,QFileDialog,QMessageBox
from .store import Store
from .busy import run_store_task
from .tableui import CheckTable

def prepare_archive(source,target):
    from .backup_tools import inspect_backup
    inspect_backup(source)
    src=sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True)
    dst=sqlite3.connect(target)
    try:
        if src.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('백업 파일이 손상되었습니다.')
        src.backup(dst)
    finally:src.close();dst.close()
    migrated=Store(target);migrated.close()

class ArchiveDialog(QDialog):
    def __init__(self,store,source,parent=None):
        super().__init__(parent)
        from .ui import label,button,table,populate
        self.store=store;self.setWindowTitle('이전 백업 조회 · 읽기 전용');self.resize(1050,700)
        v=QVBoxLayout(self);heading=label('읽기 전용 · '+Path(source).name);heading.setTextFormat(Qt.TextFormat.PlainText);v.addWidget(heading)
        v.addWidget(label('현재 PC 자료와 원래 백업 파일은 변경되지 않습니다.','Sub'))
        tabs=QTabWidget();v.addWidget(tabs)
        page=QWidget();layout=QVBoxLayout(page);tabs.addTab(page,'성적표')
        row=QHBoxLayout();layout.addLayout(row);self.search=QLineEdit();self.search.setPlaceholderText('학생명 · 학생번호 검색');row.addWidget(self.search)
        self.exam=QComboBox();self.exam.addItem('모든 시험',None)
        for e in store.exams():self.exam.addItem(e['title'],e['id'])
        row.addWidget(self.exam,1)
        self.grid=CheckTable(['선택','학생명','학원','반','시험명','응시일','점수'],[66,100,120,120,280,105,80]);layout.addWidget(self.grid)
        row=QHBoxLayout();layout.addLayout(row);self.count=label('선택 0건','Sub');row.addWidget(self.count);row.addStretch();row.addWidget(button('성적표 다운로드',self.export,True))
        self.grid.checksChanged.connect(lambda:self.count.setText(f'선택 {len(self.grid.checked_ids())}건'))
        self.search.textChanged.connect(self.refresh);self.exam.currentIndexChanged.connect(self.refresh);self.grid.cellDoubleClicked.connect(self.preview)
        students=table(['성명','학생번호','학원','반','상태']);populate(students,[(r['id'],[r['name'],r['code'][-5:],r['academy'],r['classroom'],'재원' if r['active'] else '퇴원']) for r in store.students()]);tabs.addTab(students,'학생')
        exams=table(['시험명','등록일']);populate(exams,[(r['id'],[r['title'],r['day']]) for r in store.exams()]);tabs.addTab(exams,'시험')
        historical=table(['성명','시험명','응시일','점수','등급'])
        rows=store.rows('SELECT r.*,e.title,s.name FROM historical_results r JOIN historical_exams e ON e.id=r.exam_id LEFT JOIN students s ON s.id=r.student_id ORDER BY r.sat_on DESC')
        populate(historical,[(r['id'],[r['name'] or '미연결',r['title'],r['sat_on'],r['score']/100,r['grade'] or '-']) for r in rows]);tabs.addTab(historical,'이관 성적')
        self.refresh()

    def refresh(self,*_):
        query=self.search.text().strip().lower();rows=[r for r in self.store.results(self.exam.currentData()) if not query or query in r['snapshot'].get('name','').lower() or query in r['snapshot'].get('code','')]
        data=[]
        for r in rows:
            s=r['snapshot'];values=[s['name'],s['academy'],s['classroom'],r['title'],r['day'],f"{r['score']/100:g}"];data.append((r['id'],values,values))
        self.grid.fill(data)

    def preview(self,row,col):
        if col==0:return
        from .preview_cache import preview_pdf
        try:
            sid=self.grid.item(row,0).data(Qt.ItemDataRole.UserRole)
            path=run_store_task(self,self.store,lambda db:preview_pdf(db,sid),readonly=True);QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as exc:QMessageBox.warning(self,'성적표 확인',str(exc))

    def export(self):
        from .reports import report_pdf
        ids=self.grid.checked_ids()
        if not ids:QMessageBox.information(self,'성적표','다운로드할 학생을 체크하세요.');return
        path,_=QFileDialog.getSaveFileName(self,'이전 백업 성적표 저장','이전성적표.pdf','PDF (*.pdf)')
        if not path:return
        try:run_store_task(self,self.store,lambda db:report_pdf(path,db,ids),readonly=True);QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as exc:QMessageBox.warning(self,'성적표 확인',str(exc))

def open_archive(parent,source):
    with tempfile.TemporaryDirectory(prefix='mandu_archive_',ignore_cleanup_errors=True) as folder:
        path=Path(folder)/'archive.sqlite3'
        run_store_task(parent,parent.store,lambda _:prepare_archive(source,path),readonly=True)
        db=Store.open_existing(path,readonly=True)
        try:ArchiveDialog(db,source,parent).exec()
        finally:db.close()
