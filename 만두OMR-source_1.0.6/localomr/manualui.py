from PySide6.QtWidgets import QCheckBox
from copy import deepcopy
from PySide6.QtCore import Qt,Signal,QDate
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QComboBox,QLineEdit,QTableWidget,QTableWidgetItem,QHeaderView,QSplitter,QScrollArea,QCheckBox,QMessageBox,QAbstractItemView,QDateEdit
from .examdata import ELECTIVES,effective,numeric,grade
from .ui import button,label,table,populate,guarded
from .studentdata import display_code


class ManualPage(QWidget):
    saved=Signal()

    def __init__(self,store,parent=None):
        super().__init__(parent);self.store=store;self.current=None;self.cache={};self.dirty=False;self.loading=False;self.state=None
        v=QVBoxLayout(self);v.setContentsMargins(22,20,22,20);v.addWidget(label('수기 채점','Heading'))
        v.addWidget(label('미응시 학생은 빈칸으로 시작합니다. O/X를 누르거나 학생 답안을 입력하세요. 모든 문항을 채우고 저장하면 성적에 반영됩니다.','Sub'))
        h=QHBoxLayout();v.addLayout(h);self.exam=QComboBox();self.cls=QComboBox();self.search=QLineEdit();self.search.setPlaceholderText('학생명 · 학생번호 검색')
        h.addWidget(self.exam,2);h.addWidget(self.cls,1);h.addWidget(self.search,1)
        split=QSplitter();v.addWidget(split,1);left=QWidget();lv=QVBoxLayout(left);lv.setContentsMargins(0,0,8,0);lv.addWidget(label('대상 학생'))
        self.roster=table(['성명','학생번호','점수','상태']);self.roster.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents);self.roster.horizontalHeader().setStretchLastSection(False);self.roster.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch);self.roster.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.Fixed);self.roster.setColumnWidth(3,82);lv.addWidget(self.roster);left.setMinimumWidth(290);split.addWidget(left)
        right=QWidget();rv=QVBoxLayout(right);rv.setContentsMargins(8,0,0,0);self.student_label=label('학생을 선택하세요');rv.addWidget(self.student_label)
        h=QHBoxLayout();rv.addLayout(h);h.addWidget(label('선택과목'));self.choice=QComboBox();self.choice.addItem('선택과목을 선택하세요',None)
        for k,name in ELECTIVES.items():self.choice.addItem(name,k)
        h.addWidget(self.choice);h.addWidget(label('응시일자'));self.sat_on=QDateEdit(QDate.currentDate());self.sat_on.setCalendarPopup(True);self.sat_on.setDisplayFormat('yyyy-MM-dd');h.addWidget(self.sat_on);self.sat_on.dateChanged.connect(self.change_date);h.addStretch();h.addWidget(button('미입력으로',self.clear_answers));h.addWidget(button('만점으로',self.full_marks));self.save_button=button('저장',self.save,True);h.addWidget(self.save_button)
        self.summary=label('');rv.addWidget(self.summary)
        scroll=QScrollArea();scroll.setWidgetResizable(True);body=QWidget();self.grids_layout=QVBoxLayout(body);self.grids_layout.setContentsMargins(0,0,0,0);self.grids_layout.setAlignment(Qt.AlignmentFlag.AlignTop);scroll.setWidget(body);rv.addWidget(scroll,1)
        self.note=label('','Sub');rv.addWidget(self.note);rv.addWidget(button('수정 취소 · 저장된 답안 다시 불러오기',self.reload));split.addWidget(right);split.setSizes([300,900])
        self.include_inactive=QCheckBox('퇴원생 포함');lv.addWidget(self.include_inactive);self.include_inactive.toggled.connect(self.filters_changed)
        self.exam.currentIndexChanged.connect(self.filters_changed);self.cls.currentIndexChanged.connect(self.filters_changed);self.search.textChanged.connect(self.filters_changed);self.roster.currentCellChanged.connect(self.selected);self.choice.currentIndexChanged.connect(self.change_choice)
        self.grids=[];self.ox=[];self.inputs=[];self.earned=[];self.key_cells=[];self.points_cells=[]

    def stash(self):
        if self.current and self.state and self.dirty:self.cache[self.current]=deepcopy(self.state)

    def has_unsaved(self):return self.dirty or bool(self.cache)

    def discard_all(self):
        self.cache.clear();self.current=None;self.state=None;self.dirty=False

    def refresh(self):
        self.stash();eid=self.exam.currentData();cid=self.cls.currentData();self.loading=True
        self.exam.clear()
        for e in self.store.exams():self.exam.addItem(e['title'],e['id'])
        self.exam.setCurrentIndex(max(0,self.exam.findData(eid)));self.cls.clear();self.cls.addItem('모든 학원 · 반',None)
        for c in self.store.classes():self.cls.addItem(f"{c['academy']} / {c['name']}",c['id'])
        self.cls.setCurrentIndex(max(0,self.cls.findData(cid)));self.loading=False;self.filters_changed()

    def filters_changed(self,*_):
        if self.loading:return
        self.stash();eid=self.exam.currentData();old_student=self.current[1] if self.current and self.current[0]==eid else None
        results={r['student_id']:r for r in self.store.results(eid)} if eid else {}
        students=[s for s in self.store.students(self.search.text()) if (s['active'] or self.include_inactive.isChecked()) and (self.cls.currentData() is None or self.store.in_class(s['id'],self.cls.currentData()))]
        self.loading=True;display=[]
        pending={r['student_id'] for r in self.store.scans(eid) if r['input_mode']=='manual' and r['status']=='pending'} if eid else set()
        for s in students:
            r=results.get(s['id']);status='확정' if r else '미응시'
            if s['id'] in pending:status='입력 대기'
            if (eid,s['id']) in self.cache:status='수정 중'
            display.append((s['id'],[s['name'],display_code(s['code']),f"{r['score']/100:g}" if r else '',status]))
        populate(self.roster,display)
        index=next((i for i,s in enumerate(students) if s['id']==old_student),0)
        self.loading=False
        if students and eid:self.roster.selectRow(index);self.load(eid,students[index]['id'])
        else:self.current=None;self.state=None;self.dirty=False;self.render()

    def selected(self,row,*_):
        if self.loading or row<0:return
        self.load(self.exam.currentData(),self.roster.item(row,0).data(Qt.ItemDataRole.UserRole))

    def open_student(self,eid,student_id):
        self.include_inactive.setChecked(not bool(self.store.student(student_id)['active']))
        self.stash();self.loading=True;self.exam.setCurrentIndex(self.exam.findData(eid));self.cls.setCurrentIndex(0);self.search.clear();self.loading=False
        self.current=(eid,student_id);self.dirty=False;self.state=None;self.filters_changed()

    def load(self,eid,student_id):
        self.stash();self.current=(eid,student_id);self.base=self.store.exam(eid);self.dirty=self.current in self.cache
        if self.dirty:self.state=deepcopy(self.cache[self.current])
        else:
            row=self.store.student_attempt(eid,student_id);n=len(self.base['key'])
            self.state={'answers':row['answers'][:] if row else [None]*n,'entered':([bool(v) for v in row['reviewed']] if row else [False]*n),'choice':row['elective'] if row else None,'sid':row['id'] if row else None,'revision':self.base['revision'],'official':(row['origin_scan_id'] if row and row['input_mode']=='manual' and row['status']=='pending' else self.store.official_id(eid,student_id)),'status':row['status'] if row else 'new','mode':row['input_mode'] if row else 'manual'}
            if row and row['input_mode']=='scan':self.state['entered']=[bool(r) or a is not None or row['status']=='confirmed' for r,a in zip(row['reviewed'],row['answers'])]
            self.state['sat_on']=row['sat_on'] if row else QDate.currentDate().toString('yyyy-MM-dd')
        self.render()

    def render(self):
        self.loading=True
        for g in self.grids:self.grids_layout.removeWidget(g);g.hide();g.deleteLater()
        self.grids=[];self.ox=[];self.inputs=[];self.earned=[];self.key_cells=[];self.points_cells=[]
        self.choice.setEnabled(bool(self.state));self.save_button.setEnabled(bool(self.state))
        self.sat_on.setEnabled(bool(self.state))
        if not self.state:
            self.student_label.setText('시험과 학생을 선택하세요.');self.summary.clear();self.note.clear();self.loading=False;return
        student=self.store.student(self.current[1]);self.student_label.setText(f"{student['name']}  ·  {display_code(student['code'])}  ·  {student['academy']} / {student['classroom']}")
        self.sat_on.setDate(QDate.fromString(self.state['sat_on'],'yyyy-MM-dd'))
        self.choice.setVisible(self.base['config']['form']=='math30');self.choice.setCurrentIndex(max(0,self.choice.findData(self.state['choice'])));self.effective=effective(self.base,self.state['choice'])
        n=len(self.effective['key'])
        for start in range(0,n,20):
            count=min(20,n-start);grid=QTableWidget(5,count);grid.setHorizontalHeaderLabels([str(q+1) for q in range(start,start+count)]);grid.setVerticalHeaderLabels(['배점','득점','O/X','정답','학생 답안']);grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            grid.setStyleSheet('QTableWidget {font-size:12px;} QHeaderView::section {padding:4px;font-size:12px;} QLineEdit {padding:1px;border:1px solid #CBD6DD;border-radius:2px;min-height:20px;font-size:12px;} QPushButton {padding:1px;border-radius:2px;min-height:21px;font-size:12px;}')
            grid.horizontalHeader().setDefaultSectionSize(39);grid.verticalHeader().setDefaultSectionSize(32);grid.setFixedHeight(210);grid.setMinimumWidth(200)
            for col,q in enumerate(range(start,start+count)):
                for row,arr in ((0,self.points_cells),(1,self.earned),(3,self.key_cells)):
                    item=QTableWidgetItem();item.setTextAlignment(Qt.AlignmentFlag.AlignCenter);grid.setItem(row,col,item);arr.append(item)
                ox=button('',lambda _,i=q:self.toggle(i));grid.setCellWidget(2,col,ox);self.ox.append(ox)
                answer=QLineEdit();answer.setAlignment(Qt.AlignmentFlag.AlignCenter);answer.setValidator(QIntValidator(-1,999 if numeric(self.base,q+1) else 5,answer));answer.setText('' if self.state['answers'][q] is None else str(self.state['answers'][q]));answer.textEdited.connect(lambda text,i=q:self.type_answer(i,text));grid.setCellWidget(4,col,answer);self.inputs.append(answer)
            self.grids_layout.addWidget(grid);self.grids.append(grid)
        self.loading=False;self.update_cells()

    def update_cells(self):
        if not self.state:return
        self.effective=effective(self.base,self.state['choice']);key=self.effective['key'];points=self.effective['points'];answers=self.state['answers'];entered=self.state['entered']
        for i,k in enumerate(key):
            enabled=k is not None;self.ox[i].setEnabled(enabled);self.inputs[i].setEnabled(enabled);self.key_cells[i].setText(str(k) if enabled else '—');self.points_cells[i].setText(f'{points[i]/100:g}')
            correct=answers[i]==k and enabled;self.ox[i].setText(('O' if correct else 'X') if entered[i] else '');self.ox[i].setStyleSheet('color:#B53030;font-weight:bold;' if entered[i] and not correct else 'font-weight:bold;')
            self.earned[i].setText(f'{points[i]/100:g}' if entered[i] and correct else ('0' if entered[i] else ''))
        count=sum(entered)
        if count:
            score=self.store.score(answers,key,points);common=self.store.score(answers[:22],key[:22],points[:22]);g=grade(score,self.effective['cuts']);gtext=f'{g}등급' if type(g)==int else g or '컷 미설정'
            self.summary.setText(f"입력 {count}/{len(key)}문항   ·   {'합계' if all(entered) else '가채점'} {score/100:g}점   ·   공통 {common/100:g}점   ·   선택 {(score-common)/100:g}점   ·   {gtext if all(entered) else '입력 중'}")
        else:self.summary.setText('미입력  ·  점수는 저장된 응시 기록이 있을 때만 집계됩니다.')
        status='수정 중 · 저장 버튼을 눌러 반영하세요.' if self.dirty else ('기존 답안을 불러왔습니다.' if self.state['sid'] else '미응시 학생입니다.')
        self.note.setText(status+' 빈칸이 남으면 임시 저장되며 평균에서 제외됩니다. 기존 확정 성적은 새 답안이 완성될 때까지 유지됩니다.')
        if self.dirty:
            for row in range(self.roster.rowCount()):
                if self.roster.item(row,0).data(Qt.ItemDataRole.UserRole)==self.current[1]:self.roster.item(row,3).setText('수정 중')

    def changed(self):self.dirty=True;self.update_cells()

    def change_date(self,value):
        if self.loading or not self.state:return
        self.state['sat_on']=value.toString('yyyy-MM-dd');self.changed()

    def toggle(self,q):
        if not self.state:return
        key=self.effective['key'][q]
        if key is None:return
        is_o=self.state['entered'][q] and self.state['answers'][q]==key
        self.state['answers'][q]=None if is_o else key;self.state['entered'][q]=True;self.inputs[q].setText('' if is_o else str(key));self.changed()

    def type_answer(self,q,text):
        if self.loading:return
        if text.strip() in ('','-'):self.state['answers'][q]=None;self.state['entered'][q]=False
        else:self.state['answers'][q]=int(text);self.state['entered'][q]=True
        self.changed()

    def change_choice(self,*_):
        if self.loading or not self.state:return
        self.state['choice']=self.choice.currentData();self.state['answers'][22:]=[None]*max(0,len(self.state['answers'])-22);self.state['entered'][22:]=[False]*max(0,len(self.state['entered'])-22);self.dirty=True;self.render()

    def clear_answers(self):
        if not self.state:return
        self.state['answers']=[None]*len(self.state['answers']);self.state['entered']=[False]*len(self.state['entered']);self.dirty=True;self.render()

    @guarded
    def full_marks(self):
        if not self.state:return
        if not self.effective['configured']:raise ValueError('선택과목을 먼저 선택하세요.')
        self.state['answers']=self.effective['key'][:];self.state['entered']=[True]*len(self.state['answers']);self.dirty=True;self.render()

    @guarded
    def save(self):
        if not self.state:return
        st=self.state
        if not self.dirty:return
        complete=all(st['entered']);replace=bool(complete and st['official'])
        if replace and QMessageBox.question(self,'성적 저장','기존 확정 성적을 현재 수기 답안으로 바꿀까요? 이전 답안과 원본은 보관됩니다.')!=QMessageBox.StandardButton.Yes:return
        sid=self.store.save_manual(*self.current,st['choice'],st['answers'],st['entered'],st['revision'],st['sid'],st['official'],replace,sat_on=st['sat_on'],class_id=self.cls.currentData())
        current=self.current;self.cache.pop(current,None);self.dirty=False;self.load(*current);self.saved.emit()
        QMessageBox.information(self,'저장 완료','성적을 확정하고 평균·누적 성적에 반영했습니다.' if complete else '임시 저장했습니다. 빈 문항을 모두 입력해야 성적으로 확정됩니다.')
        return sid

    def reload(self):
        if not self.current:return
        if self.dirty and QMessageBox.question(self,'수정 취소','아직 저장하지 않은 수정을 취소할까요?')!=QMessageBox.StandardButton.Yes:return
        current=self.current;self.cache.pop(current,None);self.dirty=False;self.load(*current)
