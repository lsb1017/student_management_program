from copy import deepcopy
import re
from PySide6.QtCore import QDate,Qt,QUrl,Signal
from PySide6.QtGui import QDesktopServices,QKeySequence
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QComboBox,QSpinBox,QDateEdit,QTableWidget,QTableWidgetItem,QHeaderView,QInputDialog,QMessageBox,QLabel,QPushButton,QFileDialog,QCheckBox,QTabBar,QApplication,QGridLayout,QMenu
from .examdata import ELECTIVES,NUMERIC,effective
from .classification import normalize_config
from .forms import MATH_FORM_NAME,math_form_path

MATH_POINTS=[2,2]+[3]*6+[4]*7+[3]*4+[4]*3+[2]+[3]*4+[4]*3
HEADERS=['문항','단원','과목','학습내용','난이도','배점','정답','문제형태','채점조건']


def kind_for(q,math=True):return '숫자답안' if math and q in NUMERIC else '선다형'


def blank_math_rows(choice='1'):
    return [['',str(p),'','',ELECTIVES[choice] if i>=22 else '','','and',kind_for(i+1)] for i,p in enumerate(MATH_POINTS)]


class QuestionTable(QTableWidget):
    paste_requested=Signal()
    def keyPressEvent(self,event):
        if event.matches(QKeySequence.StandardKey.Paste):self.paste_requested.emit();event.accept()
        else:super().keyPressEvent(event)


class ExamEditor(QDialog):
    def __init__(self,store,eid=None,parent=None):
        super().__init__(parent);self.store=store;self.eid=eid;self.loading=True;self.bank={k:blank_math_rows(k) for k in ELECTIVES};self.cuts={};self.active='common';self.metadata={};self.import_sources=[];self.primary='1'
        self.setWindowTitle('통합 시험 등록 · 공통 + 선택과목');self.resize(1200,860)
        v=QVBoxLayout(self)
        self.title=QLineEdit();self.title.setPlaceholderText('예: 모의고사 1회차')
        self.day=QDateEdit(QDate.currentDate());self.day.setDisplayFormat('yyyy-MM-dd');self.day.setCalendarPopup(True)
        line=QHBoxLayout();line.addWidget(QLabel('시험명'));line.addWidget(self.title,1);line.addWidget(QLabel('시험일 / 등록일'));line.addWidget(self.day);v.addLayout(line)
        # Retain old grouping values for existing records; new exams get sensible defaults.
        self.series=QLineEdit('수학 모의고사');self.subject=QLineEdit('수학');self.round=QLineEdit();self.exam_code=QLineEdit();self.enabled=QCheckBox();self.enabled.setChecked(True)
        self.form=QComboBox();self.form.addItem(MATH_FORM_NAME,'math30');self.form.addItem('만두OMR 자체 OMR · 선다형 1~60문항','local60')
        self.count=QSpinBox();self.count.setRange(1,60);self.count.setValue(30)
        line=QHBoxLayout();line.addWidget(QLabel('OMR 양식'));line.addWidget(self.form,1);line.addWidget(QLabel('학생당 문항'));line.addWidget(self.count)
        self.form_button=QPushButton('기본 OMR 열기');self.form_button.clicked.connect(self.open_form);line.addWidget(self.form_button);v.addLayout(line)
        line=QHBoxLayout()
        for name,callback in [('엑셀 표 붙여넣기 (Ctrl+V)',self.paste_table),('선택과목별 등급컷',self.edit_cuts)]:
            b=QPushButton(name);b.clicked.connect(callback);line.addWidget(b)
        self.more_button=QPushButton('더보기');self.more_menu=QMenu(self.more_button)
        self.import_excel_action=self.more_menu.addAction('엑셀 파일 불러오기');self.import_excel_action.triggered.connect(self.import_excel)
        self.more_button.setMenu(self.more_menu);line.addWidget(self.more_button)
        v.addLayout(line)
        self.tabs=QTabBar();self.tabs.setExpanding(True)
        for name,k in [('공통 · 수학 I / II (1~22)','common'),('확률과 통계 (23~30)','1'),('미적분 (23~30)','2'),('기하 (23~30)','3')]:
            index=self.tabs.addTab(name);self.tabs.setTabData(index,k)
        v.addWidget(self.tabs)
        self.hint=QLabel('한 시험에 공통 22문항과 선택 3과목을 함께 저장합니다. 채점 시 OMR의 선택과목을 읽어 정답을 적용합니다.');self.hint.setWordWrap(True);v.addWidget(self.hint)
        self.keys=QuestionTable(0,9);self.keys.setHorizontalHeaderLabels(HEADERS);self.keys.verticalHeader().hide();self.keys.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive);self.keys.setWordWrap(False)
        for col,width in enumerate([50,140,115,265,65,60,65,110,75]):self.keys.setColumnWidth(col,width)
        self.keys.paste_requested.connect(self.paste_table);self.keys.itemChanged.connect(self.update_status);v.addWidget(self.keys,1)
        self.status=QLabel();self.status.setWordWrap(True);v.addWidget(self.status)
        self.cut_label=QLabel();self.cut_label.setWordWrap(True);v.addWidget(self.cut_label)
        note=QLabel('셀을 더블클릭하거나 선택 후 입력해 수정합니다. 선다형/숫자답안은 기본 OMR의 실제 답란과 맞아야 합니다.\n공통 오답률은 선택과목 전체를 합산하고, 선택 문항은 해당 선택과목 안에서 분석합니다. 붙여넣기는 시험 저장 전까지 초안입니다.');note.setWordWrap(True);v.addWidget(note)
        actions=QHBoxLayout();v.addLayout(actions);self.export_button=QPushButton('정답표 엑셀 다운로드');self.export_button.clicked.connect(self.export_excel);self.export_button.setEnabled(bool(eid));actions.addWidget(self.export_button);actions.addStretch();b=QPushButton('시험 저장 · 공통과 선택과목 함께 저장');b.setObjectName('Primary');b.clicked.connect(self.save);actions.addWidget(b)
        if eid:
            e=store.exam(eid);cfg=normalize_config(e['config']);self.form.setCurrentIndex(self.form.findData(cfg.get('form','local60')));self.count.setValue(len(e['key']));self.primary=cfg.get('primary','1');self.cuts=deepcopy(cfg.get('cuts',{}));self.metadata=deepcopy(cfg.get('metadata',{}));self.import_sources=deepcopy(cfg.get('import_sources',[]))
            self.exam_code.setText(self.metadata.get('code',''));self.enabled.setChecked(self.metadata.get('active',True))
            for widget,k in [(self.title,'title'),(self.series,'series'),(self.subject,'subject'),(self.round,'round')]:widget.setText(e[k])
            self.day.setDate(QDate.fromString(e['day'],'yyyy-MM-dd'))
            for choice in (ELECTIVES if self.math() else ('0',)):
                d=effective(e,choice)
                self.bank[choice]=[[str(d['key'][i]) if d['key'][i] is not None else '',f"{d['points'][i]/100:g}",d['topics'][i],d['skills'][i],d['areas'][i],d['difficulties'][i],d['conditions'][i],d['kinds'][i]] for i in range(len(d['key']))]
        self.active='common' if self.math() else '0';self.loading=False;self.fill()
        self.tabs.currentChanged.connect(self.switch_section);self.form.currentIndexChanged.connect(self.form_changed);self.count.valueChanged.connect(self.count_changed)
        if eid and store.scans(eid):self.form.setEnabled(False);self.count.setEnabled(False)
        self.initial_draft=self.draft_state()

    def draft_state(self):
        self.cache()
        return deepcopy((self.bank,self.cuts,self.metadata,self.import_sources,self.primary,
            self.title.text(),self.series.text(),self.subject.text(),self.round.text(),
            self.exam_code.text(),self.enabled.isChecked(),self.day.date().toString('yyyy-MM-dd'),
            self.form.currentData(),self.count.value()))

    def reject(self):
        if self.draft_state()!=self.initial_draft:
            from .draftui import unsaved_choice
            choice=unsaved_choice(self)
            if choice=='stay':return
            if choice=='save':self.save();return
        super().reject()

    def closeEvent(self,event):
        event.ignore();self.reject()

    def math(self):return self.form.currentData()=='math30'

    def open_form(self):
        try:QDesktopServices.openUrl(QUrl.fromLocalFile(str(math_form_path())))
        except Exception as exc:QMessageBox.warning(self,'OMR 양식',str(exc))

    def questions(self):
        return list(range(1,23)) if self.math() and self.active=='common' else list(range(23,31)) if self.math() else list(range(1,self.count.value()+1))

    def draft(self):
        rows=[]
        for i in range(self.keys.rowCount()):
            row=[self.keys.item(i,j).text() if self.keys.item(i,j) else '' for j in (6,5,1,3,2,4,8)]
            row.append(self.keys.cellWidget(i,7).currentText());rows.append(row)
        return rows

    def cache(self):
        if self.loading:return
        data=self.draft()
        if not self.math():self.bank['0']=data
        elif self.active=='common':
            for k in ELECTIVES:self.bank[k]=deepcopy(data)+self.bank.get(k,blank_math_rows(k))[22:]
        else:self.bank[self.active]=self.bank.get(self.active,blank_math_rows(self.active))[:22]+data

    def fill(self):
        self.loading=True
        if self.math():self.count.setValue(30)
        self.count.setEnabled(not self.math() and not (self.eid and self.store.scans(self.eid)));self.tabs.setVisible(self.math());self.form_button.setEnabled(self.math())
        data=self.bank.get(self.primary if self.active=='common' else self.active,[]);qs=self.questions()
        for i in range(self.keys.rowCount()):
            previous=self.keys.cellWidget(i,7)
            if previous:previous.hide();self.keys.removeCellWidget(i,7)
        self.keys.setRowCount(len(qs))
        for i,q in enumerate(qs):
            row=data[q-1] if q<=len(data) else ['',str(5),'','','','','and','선다형']
            values=[str(q),row[2],row[4],row[3],row[5],row[1],row[0],row[7],row[6]]
            for j,value in enumerate(values):
                if j==7:
                    kind=QComboBox();kind.addItems(['선다형','숫자답안']);kind.setCurrentText(value);kind.setToolTip(f'{q}번 기본 OMR 답란: {kind_for(q,self.math())}');self.keys.setCellWidget(i,j,kind);continue
                item=QTableWidgetItem(value);item.setToolTip(value)
                if j==0:item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                from .design import alignment
                item.setTextAlignment(alignment(HEADERS[j]));self.keys.setItem(i,j,item)
        self.hint.setText('한 시험에 공통 22문항 + 선택 3과목을 함께 등록합니다. 각 학생은 공통과 본인 선택과목 총 30문항으로 채점합니다.' if self.math() else '자체 OMR은 선다형만 지원합니다. 수능 수학은 위 OMR 양식에서 기본 양식을 선택하세요.')
        self.cut_label.setText('등급컷: '+' / '.join(f"{ELECTIVES.get(k,'자체시험')} " + (' · '.join(f'{i+1}등급 {c}점' for i,c in enumerate(cuts)) if cuts else '미설정') for k,cuts in ((k,self.cuts.get(k,[])) for k in (ELECTIVES if self.math() else ('0',)))))
        from .catalog import reference
        entry=reference(self.title.text())
        if entry and entry.get('note'):self.cut_label.setText(self.cut_label.text()+'\n'+entry['note'])
        self.loading=False;self.update_status()

    def update_status(self,*_):
        if self.loading:return
        self.cache()
        if self.math():
            common=sum(bool(r[0].strip()) for r in self.bank[self.primary][:22]);parts=[f'공통 {common}/22']+[f'{name} {sum(bool(r[0].strip()) for r in self.bank[k][22:])}/8' for k,name in ELECTIVES.items()]
            self.status.setText('정답 입력 현황 · '+' / '.join(parts)+' · 선택과목 전체가 하나의 시험입니다.')
        else:self.status.setText(f'{len(self.draft())}문항 · 저장 전 정답과 배점을 확인하세요.')

    def switch_section(self,index):
        if self.loading:return
        self.cache();self.active=self.tabs.tabData(index);self.fill()

    def select_section(self,key):
        self.cache();self.active=key;self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(next(i for i in range(self.tabs.count()) if self.tabs.tabData(i)==key));self.tabs.blockSignals(False);self.fill()

    def form_changed(self):
        if self.loading:return
        self.bank={k:blank_math_rows(k) for k in ELECTIVES};self.cuts={};self.active='common' if self.math() else '0'
        if self.math():self.tabs.blockSignals(True);self.tabs.setCurrentIndex(0);self.tabs.blockSignals(False)
        self.fill()

    def count_changed(self):
        if self.loading:return
        self.cache();self.fill()

    @staticmethod
    def import_row(r):
        from .classification import course_name
        area,skill=r['area'],r['skill']
        if course_name(skill) and not course_name(area):area,skill=skill,area
        return [str(r['key']),f"{r['points']:g}",r['topic'],skill,area,r['difficulty'],r['condition'],kind_for(r['q'])]

    def apply_import(self,sheets,source_name=''):
        from .question_import import combine_sheets
        from decimal import Decimal
        selected=combine_sheets(sheets)
        if self.eid and self.store.scans(self.eid) and not self.math():raise ValueError('답안이 있는 자체 양식 시험을 수학 양식으로 바꿀 수 없습니다.')
        self.cache();incoming=next(iter(selected.values()))
        if self.math():
            for choice,old in self.bank.items():
                if choice in selected or choice not in ELECTIVES or not all(row[0].strip() for row in old[22:]):continue
                conflicts=[i+1 for i in range(22) if old[i][0].strip() and (old[i][0].strip()!=str(incoming[i]['key']) or Decimal(old[i][1])!=Decimal(str(incoming[i]['points'])))]
                if conflicts:raise ValueError('기존 다른 선택과목과 공통 문항 정답·배점이 다릅니다: '+', '.join(map(str,conflicts))+'. 같은 시험 시트를 함께 가져오거나 공통 탭에서 확인하세요.')
        if not self.math():self.bank={k:blank_math_rows(k) for k in ELECTIVES};self.cuts={}
        self.loading=True;self.form.setCurrentIndex(self.form.findData('math30'));self.loading=False
        for choice,rows in selected.items():self.bank[choice]=[self.import_row(r) for r in rows]
        common=[self.import_row(r) for r in incoming[:22]]
        for choice in ELECTIVES:self.bank[choice]=deepcopy(common)+self.bank.get(choice,blank_math_rows(choice))[22:]
        self.primary=next(iter(selected));self.active='common'
        self.tabs.blockSignals(True);self.tabs.setCurrentIndex(0);self.tabs.blockSignals(False)
        if not self.title.text().strip() and source_name!='엑셀 복사/붙여넣기':self.title.setText(sheets[0].group)
        self.import_sources.append({'file':source_name,'sheets':[s.name for s in sheets]});self.fill()

    def import_excel(self):
        from .question_import import read_question_book
        from .questionui import QuestionImportDialog
        from pathlib import Path
        path,_=QFileDialog.getOpenFileName(self,'문항정보 엑셀 선택','','Excel (*.xlsx)')
        if not path:return
        try:
            sheets=read_question_book(path);dialog=QuestionImportDialog(sheets,self)
            if dialog.exec():self.apply_import(dialog.chosen,Path(path).name)
        except Exception as exc:QMessageBox.warning(self,'엑셀 가져오기',str(exc))

    def apply_clipboard(self,text):
        from .clipboard_import import cells,structured,parse_table
        rows=cells(text)
        if structured(rows) and self.math():
            sheet,target=parse_table(rows,self.active)
            if len(sheet.rows)==30:self.apply_import([sheet],'엑셀 복사/붙여넣기');return
            self.cache();data=[self.import_row(r) for r in sheet.rows]
            if target=='common':
                for k in ELECTIVES:self.bank[k]=deepcopy(data)+self.bank[k][22:]
            else:self.bank[target]=self.bank[target][:22]+data
            # Select without caching the now stale visible grid.
            self.active=target;self.tabs.blockSignals(True);self.tabs.setCurrentIndex(0 if target=='common' else int(target));self.tabs.blockSignals(False);self.fill();return
        # Partial columns paste into the selected cell, all-or-nothing on bounds/type.
        row,col=max(0,self.keys.currentRow()),max(1,self.keys.currentColumn())
        if row+len(rows)>self.keys.rowCount() or col+max(map(len,rows))>9:raise ValueError('선택한 셀부터 붙여넣을 공간이 부족합니다. 시작 셀과 복사 범위를 확인하세요.')
        for values in rows:
            for j,value in enumerate(values,col):
                if value.lstrip().startswith('='):raise ValueError('수식 대신 계산된 값을 복사하세요.')
                if j==7 and value not in ('선다형','숫자답안'):raise ValueError('문제형태는 선다형 또는 숫자답안입니다.')
        self.loading=True
        for i,values in enumerate(rows,row):
            for j,value in enumerate(values,col):
                if j==7:self.keys.cellWidget(i,j).setCurrentText(value)
                else:self.keys.item(i,j).setText(value)
        self.loading=False;self.update_status()

    def paste_table(self):
        try:self.apply_clipboard(QApplication.clipboard().text())
        except Exception as exc:QMessageBox.warning(self,'붙여넣기 확인',str(exc))

    def paste_keys(self):
        text,ok=QInputDialog.getMultiLineText(self,'현재 구역 정답 입력',f'현재 구역 {self.keys.rowCount()}문항의 정답을 쉼표·공백·줄바꿈으로 구분해 입력하세요.')
        if not ok:return
        parts=text.replace(',',' ').split()
        if len(parts)!=self.keys.rowCount():QMessageBox.warning(self,'확인','현재 구역 문항 수만큼 입력하세요.');return
        for i,p in enumerate(parts):self.keys.item(i,6).setText(p)

    def edit_cuts(self):
        self.cache();dlg=QDialog(self);dlg.setWindowTitle('선택과목별 등급컷');dlg.setStyleSheet('QDialog {background:white;}');v=QVBoxLayout(dlg)
        if getattr(self,'copy_cut_review_required',False):
            dlg.setWindowTitle('복사한 시험 · 등급컷 확인')
            from PySide6.QtGui import QPixmap
            from .reports import report_asset
            row=QHBoxLayout();image=QLabel();image.setPixmap(QPixmap(str(report_asset('import_mandu.png'))).scaled(66,66,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation));row.addWidget(image)
            note=QLabel('이전 시험에서 복사된 등급컷입니다.\n새 시험에 맞는 값인지 확인한 뒤 반영해주세요!');note.setWordWrap(True);row.addWidget(note,1);v.addLayout(row)
        dlg.setMinimumWidth(630)
        more=QCheckBox('6~8등급 컷도 입력');more.setChecked(any(len(c)==8 for c in self.cuts.values()));v.addWidget(more)
        grid=QGridLayout();v.addLayout(grid);fields={};extra=[]
        for col,k in enumerate(ELECTIVES if self.math() else ('0',)):
            grid.addWidget(QLabel(ELECTIVES.get(k,'자체 시험')),0,col*2,1,2);fields[k]=[]
            for i in range(8):
                values=self.cuts.get(k,[]);field=QLineEdit(str(values[i]) if i<len(values) else '');fields[k].append(field);label=QLabel(f'{i+1}등급');grid.addWidget(label,i+1,col*2);grid.addWidget(field,i+1,col*2+1)
                if i>=5:extra.extend([label,field]);label.setVisible(more.isChecked());field.setVisible(more.isChecked())
        more.toggled.connect(lambda checked:[w.setVisible(checked) for w in extra])
        b=QPushButton('등급컷 반영');b.clicked.connect(dlg.accept);v.addWidget(b)
        if dlg.exec():
            for k,entries in fields.items():values=[e.text().strip() for e in entries[:8 if more.isChecked() else 5]];self.cuts[k]=values if any(values) else []
            self.fill()
            return True
        return False

    def export_excel(self):
        if not self.eid:QMessageBox.information(self,'정답표 다운로드','시험을 먼저 저장해 주세요.');return
        if self.draft_state()!=self.initial_draft:
            if QMessageBox.question(self,'저장된 정답표 다운로드','현재 수정 중인 내용은 포함되지 않아요. 마지막으로 저장한 정답표를 내려받을까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        exam=self.store.exam(self.eid);name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',exam['title'])+'_정답표.xlsx'
        path,_=QFileDialog.getSaveFileName(self,'정답표 엑셀 다운로드',name,'Excel (*.xlsx)')
        if not path:return
        try:
            from .question_export import export_question_book
            from .busy import run_store_task
            run_store_task(self,self.store,lambda db:export_question_book(path,db.exam(self.eid)),readonly=True)
            QMessageBox.information(self,'다운로드 완료','일괄등록과 같은 서식으로 저장했어요. 선택과목별 시트에 공통 문항도 함께 들어 있습니다.')
        except Exception as exc:QMessageBox.warning(self,'다운로드 확인',str(exc))

    def save(self):
        try:
            self.cache();config={'form':self.form.currentData(),'cuts':deepcopy(self.cuts)};primary='0';rows=self.bank.get('0',[]);variants={}
            if self.math():
                missing=[];first=None
                common_missing=[str(i+1) for i,r in enumerate(self.bank[self.primary][:22]) if not r[0].strip()]
                if common_missing:missing.append('공통: '+', '.join(common_missing)+'번');first='common'
                for k,name in ELECTIVES.items():
                    gaps=[str(i+23) for i,r in enumerate(self.bank[k][22:]) if not r[0].strip()]
                    if gaps:missing.append(name+': '+', '.join(gaps)+'번');first=first or k
                if missing:
                    self.select_section(first)
                    raise ValueError('모든 과목의 정답을 입력한 뒤 저장할 수 있습니다.\n'+'\n'.join(missing)+'\n누락된 과목과 문항을 채워 주세요.')
                complete=list(ELECTIVES)
                primary=self.primary if self.primary in complete else complete[0];rows=self.bank[primary]
                for k in ELECTIVES:
                    r=self.bank[k]
                    if k==primary:continue
                    if any(row[0].strip() for row in r[22:]):
                        if k not in complete:raise ValueError(ELECTIVES[k]+' 정답을 모두 채우거나 23~30번을 비워 주세요.')
                        variants[k]={'key':[int(x[0]) for x in r[22:]],'points':[x[1] for x in r[22:]]}
                        for name,index in [('topics',2),('skills',3),('areas',4),('difficulties',5),('conditions',6),('kinds',7)]:variants[k][name]=[x[index] or ('미분류' if name=='topics' else 'and' if name=='conditions' else '') for x in r[22:]]
                config.update(primary=primary,variants=variants,id_digits=5,require_all_choices=True)
            for name,index in [('topics',2),('skills',3),('areas',4),('difficulties',5),('conditions',6),('kinds',7)]:config[name]=[r[index] or ('미분류' if name=='topics' else 'and' if name=='conditions' else '') for r in rows]
            config['metadata']={**self.metadata,'year':self.day.date().year(),'type':'모의수능수학' if self.math() else '자체 시험','code':self.exam_code.text().strip(),'active':self.enabled.isChecked()};config['import_sources']=deepcopy(self.import_sources)
            title=self.title.text().strip()
            if not title:raise ValueError('시험명을 입력하세요.')
            round_no=self.round.text().strip()
            if not round_no:
                match=re.search(r'(\d+)\s*회',title)
                round_no=match.group(1) if match else str(1+max([int(e['round']) for e in self.store.exams() if e['series']==self.series.text() and str(e['round']).isdigit()]+[0]))
            if getattr(self,'copy_cut_review_required',False):
                if not self.edit_cuts():return
                config['cuts']=deepcopy(self.cuts)
            self.affected_ids=[]
            if self.eid:
                from .exam_changes import preview_change
                lines,affected=preview_change(self.store,self.eid,[int(r[0]) for r in rows],[r[1] for r in rows],config)
                if lines:
                    text='변경 내용을 저장할까요?\n'+'\n'.join(lines)+f'\n\n검수 대기로 돌아갈 확정 성적: {len(affected)}건\n배점만 바뀐 성적은 확정을 유지하고 점수만 갱신합니다.'
                    if QMessageBox.question(self,'정답·배점 변경 확인',text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
                    self.affected_ids=affected
            self.eid=self.store.save_exam(title,self.series.text() or '수학 모의고사',self.subject.text() or '수학',round_no,self.day.date().toString('yyyy-MM-dd'),[int(r[0]) for r in rows],[r[1] for r in rows],self.eid,config);self.accept()
        except Exception as exc:
            message=str(exc)
            QMessageBox.warning(self,'입력 확인',message)
