from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QSpinBox,QPushButton,QMessageBox,QApplication
from .tableui import CheckTable
from . import storage
from .preview_cache import cache_files,clear_cache
from .busy import run_store_task


def mb(value):return f'{value/1024/1024:,.1f} MB'


class StorageDialog(QDialog):
    def __init__(self,store,parent=None):
        super().__init__(parent);self.store=store;self.loading=False
        self.setWindowTitle('저장 용량 줄이기');self.resize(1000,700)
        v=QVBoxLayout(self);intro=QLabel('답안·점수·성적표·누적 분석은 유지하고, 선택한 답안의 스캔 이미지와 원본 파일만 정리합니다.\n정리한 이미지로는 원본 검수·재인식을 할 수 없습니다.');intro.setWordWrap(True);v.addWidget(intro)
        h=QHBoxLayout();v.addLayout(h);self.exam=QComboBox();self.exam.addItem('모든 시험',None)
        for row in store.rows('SELECT id,title FROM exams ORDER BY day DESC,id DESC'):self.exam.addItem(row['title'],row['id'])
        h.addWidget(self.exam,1);h.addWidget(QLabel('불러온 지'));self.days=QSpinBox();self.days.setRange(storage.MIN_RETENTION_DAYS,3650);self.days.setValue(7);self.days.setSuffix('일 이상');self.days.setMinimumWidth(132);self.days.setButtonSymbols(QSpinBox.ButtonSymbols.UpDownArrows);self.days.setKeyboardTracking(False);h.addWidget(self.days)
        self.empty=QLabel();self.empty.setWordWrap(True);v.addWidget(self.empty)
        self.show_all=QPushButton('모든 시험 · 2일 이상 보기');self.show_all.clicked.connect(self.broaden);v.addWidget(self.show_all)
        self.table=CheckTable(['선택','시험명','학생','응시일','원본 파일','쪽','상태','이미지 용량'],[48,230,80,95,180,45,85,100]);v.addWidget(self.table,1)
        h=QHBoxLayout();v.addLayout(h)
        for text,state in [('대상 전체 선택',Qt.CheckState.Checked),('선택 해제',Qt.CheckState.Unchecked)]:
            b=QPushButton(text);b.clicked.connect(lambda _,s=state:self.check_all(s));h.addWidget(b)
        h.addStretch();self.summary=QLabel();v.addWidget(self.summary)
        note=QLabel('검수 대기·미인식·수기 답안은 대상에서 제외됩니다. 다른 답안이 사용하는 원본 PDF는 보존합니다.\n컴퓨터에 따로 보관한 스캔 파일과 기존 백업 파일은 삭제하지 않습니다. 백업에도 이미지가 남아 있을 수 있습니다.');note.setWordWrap(True);v.addWidget(note)
        self.clean=QPushButton('선택한 OMR 이미지 정리');self.clean.setStyleSheet('color:#A43530;border:1px solid #C95348;');self.clean.clicked.connect(self.purge);v.addWidget(self.clean)
        h=QHBoxLayout();v.addLayout(h);self.cache_label=QLabel();h.addWidget(self.cache_label,1)
        self.preview_clean=QPushButton('성적표 미리보기 파일 정리');self.preview_clean.clicked.connect(self.clear_previews);h.addWidget(self.preview_clean)
        self.exam.currentIndexChanged.connect(self.refresh);self.days.valueChanged.connect(self.refresh);self.table.itemChanged.connect(self.update_summary);self.refresh()

    def broaden(self):
        self.exam.blockSignals(True);self.exam.setCurrentIndex(0);self.exam.blockSignals(False);self.days.blockSignals(True);self.days.setValue(2);self.days.blockSignals(False);self.refresh()

    def check_all(self,state):
        self.loading=True
        for i in range(self.table.rowCount()):self.table.item(i,0).setCheckState(state)
        self.loading=False;self.update_summary()

    def refresh(self,*_):
        self.loading=True
        labels={'confirmed':'성적 확정','excluded':'집계 제외','deleted':'삭제된 행','superseded':'교체된 답안'}
        rows=storage.candidates(self.store,self.days.value(),self.exam.currentData())
        display=[]
        for r in rows:
            values=[r['title'],r['student'] or '미연결',r['sat_on'],r['filename'],r['page'],labels[r['status']],mb(r['image_bytes'])]
            display.append((r['id'],values,values))
        self.table.fill(display)
        self.empty.setVisible(not rows);self.show_all.setVisible(not rows and (self.days.value()>2 or self.exam.currentData() is not None))
        self.empty.setText('현재 시험·기간 조건에 해당하는 정리 대상이 없어요. 기간을 줄이거나 다른 시험을 선택해 주세요.' if self.days.value()>0 or self.exam.currentData() is not None else '정리할 이미지가 없어요. 검수 대기·미인식·수기 답안과 이미 정리한 이미지는 표시하지 않습니다.')
        self.loading=False;self.update_summary()

    def update_summary(self,*_):
        if self.loading:return
        data=storage.plan(self.store,self.table.checked_ids(),self.days.value())
        self.summary.setText(f"선택 {len(data['ids'])}장 · 제거할 이미지·원본 {mb(data['bytes'])} · 공유 중인 원본 {data['shared_sources']}개 보존")
        self.clean.setEnabled(bool(data['ids']))
        files=cache_files(self.store);self.cache_label.setText(f'성적표 미리보기 파일 {len(files)}개 · {mb(sum(p.stat().st_size for p in files))}');self.preview_clean.setEnabled(bool(files))

    def purge(self):
        ids=self.table.checked_ids();data=storage.plan(self.store,ids,self.days.value())
        if not ids:return
        if QMessageBox.question(self,'OMR 이미지 정리',f"선택한 {len(ids)}장 · {mb(data['bytes'])}의 이미지·원본을 정리할까요?\n답안과 성적은 유지됩니다. 이미지 복구에는 정리 전 백업이 필요합니다.\n기존 백업과 별도로 저장한 파일은 유지합니다.",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        days=self.days.value()
        try:
            result=run_store_task(self,self.store,lambda db:storage.purge(db,ids,days))
            QMessageBox.information(self,'이미지 정리 완료',f"{len(result['ids'])}장 정리 · 실제 확보 {mb(result['freed_bytes'])}\n"+(result['warning'] or '답안과 성적은 그대로 유지됩니다.'))
        except Exception as exc:QMessageBox.warning(self,'정리 확인',str(exc))
        finally:self.refresh()

    def clear_previews(self):
        removed,busy=clear_cache(self.store);self.update_summary()
        QMessageBox.information(self,'미리보기 정리',f'{mb(removed)} 확보'+(f' · 열려 있는 파일 {busy}개는 닫은 뒤 다시 정리하세요.' if busy else ''))

    def compact(self):
        try:QMessageBox.information(self,'데이터 파일 압축',f'{mb(run_store_task(self,self.store,storage.compact))} 확보')
        except Exception as exc:QMessageBox.warning(self,'압축 확인',str(exc))
