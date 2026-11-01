"""Screens. Each page reads through the store and changes data only through services/store methods."""
from __future__ import annotations
import json
import shutil
from datetime import date,datetime
from pathlib import Path
from PySide6.QtCore import Qt,QDate
from PySide6.QtGui import QPixmap,QKeySequence,QShortcut
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QComboBox,QDateEdit,QFileDialog,QDialog,
                               QFormLayout,QDialogButtonBox,QSpinBox,QCheckBox,QListWidget,QListWidgetItem,QPlainTextEdit,
                               QTableWidgetItem,QSplitter,QScrollArea,QInputDialog,QGroupBox)
from core.store import WEEKDAYS
from academy.config import program_setting,DEFAULTS
from academy.services import grading,entries,notify,questionbank,wrongnote,overlay,exams as exam_service
from academy.services.report import render,report_kind
from .common import Table,page,row,button,combo,run,error,info,ask,guarded,TextDialog


def date_edit(value=None):
    widget=QDateEdit();widget.setCalendarPopup(True);widget.setDisplayFormat('yyyy-MM-dd')
    widget.setDate(QDate.fromString(value,'yyyy-MM-dd') if value else QDate.currentDate());return widget


def iso(widget):return widget.date().toString('yyyy-MM-dd')


def class_items(store):
    return [(f"{c['academy']} · {c['name']}"+(f" ({c['weekday']})" if c['weekday'] and f"({c['weekday']})" not in c['name'] else ''),c['id']) for c in store.classes()]


def exam_items(store,kinds=None):
    return [(f"{e['day']} {e['title']} [{exam_service.KINDS[e['exam_kind']]}]",e['id']) for e in store.exams() if not kinds or e['exam_kind'] in kinds]


def save_path(parent,title,name,pattern):
    path,_=QFileDialog.getSaveFileName(parent,title,str(Path.home()/'Desktop'/name),pattern);return Path(path) if path else None


class BasePage(QWidget):
    def __init__(self,window):
        super().__init__();self.window=window;self.app=window.app
    @property
    def store(self):return self.window.store
    def refresh(self):pass


# ---- 홈·백업 상태 ------------------------------------------------------------------------
class HomePage(BasePage):
    def __init__(self,window):
        super().__init__(window)
        widget,layout=page('홈 · 백업 상태','시작할 때 최신 백업을 내려받았고, 종료할 때 자동으로 올리고 잠금을 풉니다. 작업 중에는 이 PC에만 자동 저장합니다.')
        QVBoxLayout(self).addWidget(widget)
        self.status=QLabel();self.status.setWordWrap(True);self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);layout.addWidget(self.status)
        layout.addLayout(row(button('지금 이 PC에 저장',guarded(self,self.autosave)),button('1.0.6 자료 가져오기(1회)',guarded(self,self.migrate)),'stretch'))
        layout.addStretch(1)

    def refresh(self):
        state=self.window.service.state;session=self.window.session
        lines=[f"작업자: {self.app.local.get('operator')} · 학원: {self.app.local.get('academy')} · PC: {self.app.local.pc_name}",
               f"모드: {'온라인' if session.mode=='online' else '오프라인(이 PC가 잠금 보유)'} · 잠금 보유: {'예' if state.get('holding_lock') else '아니오'}",
               f"마지막 내려받기: {(state.get('last_download') or {}).get('name','없음')} {(state.get('last_download') or {}).get('at','')}",
               f"마지막 올리기: {(state.get('last_upload') or {}).get('name','없음')} {(state.get('last_upload') or {}).get('at','')}",
               f"올리지 못한 백업: {state.get('pending_upload') or '없음'}",
               f"학생 {len(self.store.students())}명 · 시험 {len(self.store.exams())}개 · 확정 성적 {len(self.store.results())}건"]
        self.status.setText('\n'.join(lines))

    def autosave(self):
        path=self.window.service.autosave(self.store);info(self,f'이 PC에 저장했습니다.\n{path.name}')

    def migrate(self):
        from academy.migrations.from_v106 import migrate,inspect_v106
        path,_=QFileDialog.getOpenFileName(self,'1.0.6 백업 선택',str(Path.home()),'만두OMR 백업 (*.omrbackup)')
        if not path:return
        summary=inspect_v106(path)
        if not ask(self,f"학생 {summary['students']}명 · 시험 {summary['exams']}개 · 답안 {summary['scans']}건을 가져옵니다.\n모든 학생에게 7자리 학번을 새로 발급하며, 이후 학번 안내가 필요합니다.\n진행할까요?"):return
        result=run(self,'1.0.6 자료를 옮기고 있어요.',migrate,path,self.store)
        info(self,f"이관 완료: 학생 {result['students']}명, 확정 성적 {result['confirmed']}건. 성적표·안내 화면에서 학번 안내를 보내세요.");self.window.refresh_all()


# ---- 학생·분반 ---------------------------------------------------------------------------
class StudentDialog(QDialog):
    def __init__(self,store,student=None,parent=None):
        super().__init__(parent);self.store=store;self.student=student;self.setWindowTitle('학생 정보');self.resize(420,460)
        form=QFormLayout(self)
        self.name=QLineEdit(student['name'] if student else '');self.phone=QLineEdit(student['phone'] if student else '')
        self.parent_phone=QLineEdit(student['parent_phone'] if student else '');self.school=QLineEdit(student['school'] if student else '')
        self.phone.setPlaceholderText('010-1234-5678 또는 뒤 4자리');self.classes=QListWidget()
        members={m['class_id'] for m in store.memberships(student['id'])} if student else set()
        for label,cid in class_items(store):
            item=QListWidgetItem(label);item.setData(Qt.ItemDataRole.UserRole,cid)
            item.setCheckState(Qt.CheckState.Checked if cid in members else Qt.CheckState.Unchecked);self.classes.addItem(item)
        form.addRow('성명',self.name);form.addRow('학생 휴대전화',self.phone);form.addRow('학부모 휴대전화',self.parent_phone);form.addRow('학교',self.school);form.addRow('분반(첫 번째가 기본)',self.classes)
        note=QLabel('휴대전화 번호가 바뀌면 학번을 새로 발급하고 다시 안내합니다. 성적은 그대로 유지됩니다.');note.setWordWrap(True);note.setObjectName('hint');form.addRow(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(guarded(self,self.save));buttons.rejected.connect(self.reject);form.addRow(buttons)
        self.saved_id=None;self.code_changed=False

    def save(self):
        ids=[self.classes.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.classes.count()) if self.classes.item(i).checkState()==Qt.CheckState.Checked]
        if not ids:raise ValueError('분반을 하나 이상 선택하세요.')
        before=self.student['code'] if self.student else None
        sid=self.store.save_student_contact(self.name.text(),self.phone.text(),self.school.text(),self.parent_phone.text(),ids[0],self.student['id'] if self.student else None)
        self.store.set_student_classes(sid,ids)
        self.saved_id=sid;self.code_changed=before is not None and before!=self.store.student(sid)['code'];self.accept()


class StudentsPage(BasePage):
    def __init__(self,window):
        super().__init__(window)
        widget,layout=page('학생·분반','분반은 학원·요일별로 만듭니다(예: 청솔(토)). 학번은 학생 휴대전화 뒷 4자리 + 무작위 3자리입니다.')
        QVBoxLayout(self).addWidget(widget)
        self.class_table=Table(['분반','학원','요일','학생 수']);layout.addWidget(self.class_table,1)
        layout.addLayout(row(button('분반 추가',guarded(self,self.add_class)),button('분반 요일 변경',guarded(self,self.weekday)),'stretch'))
        self.search=QLineEdit();self.search.setPlaceholderText('이름·학번·분반 검색');self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.table=Table(['학번','이름','분반','학교','학생 연락처','학부모 연락처','재원']);layout.addWidget(self.table,3)
        layout.addLayout(row(button('학생 등록',guarded(self,self.add),True),button('정보 수정',guarded(self,self.edit)),button('엑셀 일괄 등록',guarded(self,self.import_xlsx)),
                             button('등록 서식 저장',guarded(self,self.template)),button('재원/퇴원 전환',guarded(self,self.toggle_active)),'stretch'))

    def refresh(self):
        classes=self.store.classes()
        self.class_table.fill([[c['name'],c['academy'],c['weekday'] or '—',len(self.store.class_students(c['id']))] for c in classes],[c['id'] for c in classes])
        students=self.store.students(self.search.text().strip())
        self.table.fill([[s['code'],s['name'],', '.join(m['classroom'] for m in self.store.memberships(s['id'])),s['school'],s['phone'],s['parent_phone'],'재원' if s['active'] else '퇴원'] for s in students],[s['id'] for s in students])

    def add_class(self):
        academy,ok=QInputDialog.getText(self,'분반 추가','학원명');academy=academy.strip()
        if not ok or not academy:return
        weekday,ok=QInputDialog.getItem(self,'분반 추가','요일',list(WEEKDAYS)+['(없음)'],5,False)
        if not ok:return
        weekday='' if weekday=='(없음)' else weekday
        name,ok=QInputDialog.getText(self,'분반 추가','분반 이름',text=f'{academy}({weekday})' if weekday else academy)
        if ok and name.strip():self.store.classroom(self.store.academy(academy),name.strip(),weekday);self.refresh()

    def weekday(self):
        cid=self.class_table.current_id()
        if not cid:raise ValueError('분반을 선택하세요.')
        c=next(c for c in self.store.classes() if c['id']==cid)
        weekday,ok=QInputDialog.getItem(self,'요일 변경',c['name'],list(WEEKDAYS)+['(없음)'],0,False)
        if ok:self.store.classroom(c['academy_id'],c['name'],'' if weekday=='(없음)' else weekday);self.refresh()

    def add(self):
        if not self.store.classes():raise ValueError('분반을 먼저 추가하세요.')
        dialog=StudentDialog(self.store,parent=self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.refresh();self.window.offer_welcome(dialog.saved_id,'신규 등록')

    def edit(self):
        sid=self.table.current_id()
        if not sid:raise ValueError('학생을 선택하세요.')
        dialog=StudentDialog(self.store,self.store.student(sid),self)
        if dialog.exec()==QDialog.DialogCode.Accepted:
            self.refresh()
            if dialog.code_changed:
                try:notify.refresh_login(self.store,self.app.publisher(self.store),sid)
                except Exception as exc:error(self,exc,'게시된 성적표 로그인 갱신 필요')
                self.window.offer_welcome(sid,'학번 변경')

    def toggle_active(self):
        sid=self.table.current_id()
        if not sid:raise ValueError('학생을 선택하세요.')
        s=self.store.student(sid)
        self.store.save_student(s['code'],s['name'],s['class_id'],sid,not s['active'],s['school']);self.refresh()

    def import_xlsx(self):
        from core.studentdata import read_students,plan_students
        path,_=QFileDialog.getOpenFileName(self,'학생 일괄 등록 서식',str(Path.home()),'엑셀 (*.xlsx)')
        if not path:return
        rows=read_students(path);plan=plan_students(self.store,rows)
        text='\n'.join(r['message'] for r in plan)
        if TextDialog('일괄 등록 미리보기',text,self,'등록').exec()!=QDialog.DialogCode.Accepted:return
        added,skipped=self.store.import_students(rows);self.refresh()
        info(self,f'{len(added)}명 등록(또는 반 추가), {skipped}명 건너뜀.\n성적표·안내 화면의 학번 안내 대기 목록에서 골라 일괄 발송하세요.')

    def template(self):
        from core.studentdata import template_path
        target=save_path(self,'서식 저장','학생_일괄등록_서식.xlsx','엑셀 (*.xlsx)')
        if target:shutil.copyfile(template_path(),target);info(self,'서식을 저장했습니다. G열 기존 학생번호에는 7자리 학번을 넣습니다.')


# ---- 시험·양식 ---------------------------------------------------------------------------
class FormDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent);self.setWindowTitle('OMR 양식 만들기');form=QFormLayout(self)
        self.name=QLineEdit();self.count=QSpinBox();self.count.setRange(1,60);self.count.setValue(20)
        self.choices=QSpinBox();self.choices.setRange(2,5);self.choices.setValue(5);self.numeric=QLineEdit();self.numeric.setPlaceholderText('예: 18, 19, 20 (없으면 비움)')
        form.addRow('양식 이름',self.name);form.addRow('문항 수',self.count);form.addRow('선택지 수',self.choices);form.addRow('숫자형 문항',self.numeric)
        form.addRow(QLabel('학번 칸은 7자리로 고정됩니다.'))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);form.addRow(buttons)


class ExamDialog(QDialog):
    def __init__(self,store,exam=None,parent=None):
        super().__init__(parent);self.store=store;self.exam=exam;self.variants={};self.setWindowTitle('시험 등록');self.resize(640,560)
        form=QFormLayout(self);cfg=exam['config'] if exam else {}
        self.title=QLineEdit(exam['title'] if exam else '');self.series=QLineEdit(exam['series'] if exam else '');self.subject=QLineEdit(exam['subject'] if exam else '수학')
        self.round=QLineEdit(exam['round'] if exam else '');self.day=date_edit(exam['day'] if exam else None)
        self.kind=combo([(v,k) for k,v in exam_service.KINDS.items()],exam['exam_kind'] if exam else 'weekly')
        self.report=combo([('주간지 성적표','weekly'),('모의고사 성적표','mock')],cfg.get('report_kind','weekly'))
        forms=[('수능수학 30문항(모의고사)','math30'),('1.0.6 LocalOMR 60','local60')]+[(f"{f['name']} ({f['question_count']}문항)",f['id']) for f in store.forms()]
        self.form=combo(forms,exam['form_id'] if exam and exam['form_id'] else cfg.get('form','math30') if exam else None)
        self.key=QLineEdit(','.join(map(str,exam['key'])) if exam else '');self.points=QLineEdit(','.join(f'{p/100:g}' for p in exam['points']) if exam else '')
        self.topics=QLineEdit(','.join(cfg.get('topics',[])));self.areas=QLineEdit(','.join(cfg.get('areas',[])));self.skills=QLineEdit(','.join(cfg.get('skills',[])))
        self.variants=cfg.get('variants',{});self.primary=cfg.get('primary','1')
        for label,widget in [('시험명',self.title),('시리즈',self.series),('과목',self.subject),('회차',self.round),('시행일',self.day),('시험 유형',self.kind),('기타 유형 성적표',self.report),('OMR 양식',self.form),
                             ('정답(쉼표)',self.key),('배점(쉼표)',self.points),('단원(쉼표)',self.topics),('과목/영역(쉼표, 주간지 단원별 점수)',self.areas),('학습내용(쉼표)',self.skills)]:form.addRow(label,widget)
        form.addRow(button('문항 정보 엑셀 가져오기',guarded(self,self.load_workbook)))
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(guarded(self,self.save));buttons.rejected.connect(self.reject);form.addRow(buttons)

    def load_workbook(self):
        path,_=QFileDialog.getOpenFileName(self,'문항 정보 엑셀',str(Path.home()),'엑셀 (*.xlsx)')
        if not path:return
        form=self.form.currentData()
        if form=='math30':
            from core.question_import import read_question_book
            groups=sorted({s.group for s in read_question_book(path) if not s.errors})
            group,ok=QInputDialog.getItem(self,'시험 선택','시트 묶음',groups,0,False) if len(groups)>1 else (groups[0] if groups else None,True)
            if not ok or group is None:return
            key,points,config=exam_service.from_workbook_math(path,group);self.variants=config['variants'];self.primary=config['primary']
        else:
            count=len(exam_service.numbers(self.key.text())) or 60
            if isinstance(form,int):
                f=self.store.form(form);key,points,config=exam_service.from_workbook_custom(path,f['question_count'],f['numeric_questions'],f['choice_count'])
            else:key,points,config=exam_service.from_workbook_custom(path,count)
        self.key.setText(','.join(map(str,key)));self.points.setText(','.join(f'{p:g}' for p in points))
        self.topics.setText(','.join(config['topics']));self.areas.setText(','.join(config['areas']));self.skills.setText(','.join(config['skills']))

    def save(self):
        key=exam_service.numbers(self.key.text());points=[p for p in self.points.text().replace(' ','').split(',') if p]
        n=len(key);meta={'topics':exam_service.labels(self.topics.text(),n,'미분류'),'areas':exam_service.labels(self.areas.text(),n),'skills':exam_service.labels(self.skills.text(),n)}
        extra={'variants':self.variants,'primary':self.primary} if self.form.currentData()=='math30' else {}
        if self.exam:extra={**{k:v for k,v in self.exam['config'].items() if k in ('cuts','cut_note','cut_source','difficulties')},**extra}
        self.saved=exam_service.save(self.store,self.title.text(),self.series.text(),self.subject.text(),self.round.text(),iso(self.day),self.kind.currentData(),self.form.currentData(),key,points,meta,
                                     self.exam['id'] if self.exam else None,self.report.currentData(),extra)
        self.accept()


class ExamsPage(BasePage):
    def __init__(self,window):
        super().__init__(window)
        widget,layout=page('시험·OMR 양식','시험 유형마다 문항 수·배점·문제 형식을 정합니다. 주간지 OMR은 양식을 만들거나 이미 쓰는 양식을 등록합니다.')
        QVBoxLayout(self).addWidget(widget)
        self.forms=Table(['양식','문항','선택지','숫자형','종류']);layout.addWidget(self.forms,1)
        layout.addLayout(row(button('양식 만들기',guarded(self,self.make_form)),button('양식 PDF 저장',guarded(self,self.save_form_pdf)),button('외부 양식 등록',guarded(self,self.external)),'stretch'))
        self.exams=Table(['시험','유형','양식','문항','시행일','성적표']);layout.addWidget(self.exams,2)
        layout.addLayout(row(button('시험 등록',guarded(self,self.add),True),button('시험 수정',guarded(self,self.edit)),button('시험 보관(삭제)',guarded(self,self.archive)),'stretch'))

    def refresh(self):
        forms=self.store.forms()
        self.forms.fill([[f['name'],f['question_count'],f['choice_count'],', '.join(map(str,json.loads(f['numeric_questions']))) or '—','생성' if f['source']=='generated' else '외부'] for f in forms],[f['id'] for f in forms])
        exams=self.store.exams();names={f['id']:f['name'] for f in forms}
        self.exams.fill([[e['title'],exam_service.KINDS[e['exam_kind']],names.get(e['form_id'],{'math30':'수능수학','local60':'LocalOMR 60'}.get(json.loads(e['config']).get('form'),'—')),len(json.loads(e['key_json'])),e['day'],
                          {'weekly':'주간지','mock':'모의고사'}[report_kind(self.store.exam(e['id']))]] for e in exams],[e['id'] for e in exams])

    def make_form(self):
        from academy.forms.generator import save_generated
        dialog=FormDialog(self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        save_generated(self.store,dialog.name.text(),dialog.count.value(),dialog.choices.value(),exam_service.numbers(dialog.numeric.text()));self.refresh()

    def save_form_pdf(self):
        fid=self.forms.current_id()
        if not fid:raise ValueError('양식을 선택하세요.')
        form=self.store.form(fid)
        if form['source']!='generated':raise ValueError('외부 양식은 이미 인쇄해 쓰는 양식입니다.')
        target=save_path(self,'양식 PDF',f"{form['name']}.pdf",'PDF (*.pdf)')
        if target:self.store.files.copy_to(form['pdf_hash'],target);info(self,'저장했습니다. 실제 크기(100%)로 인쇄하세요.')

    def external(self):
        from academy.forms.external import register_external
        image,_=QFileDialog.getOpenFileName(self,'빈 양식 스캔 이미지',str(Path.home()),'이미지 (*.png *.jpg *.jpeg)')
        if not image:return
        sample=json.dumps([{'kind':'choice','first':1,'count':20,'choices':5,'origin':[200,560],'dx':43,'dy':48},{'kind':'id','digits':7,'origin':[800,185],'dx':48,'dy':28}],ensure_ascii=False,indent=1)
        dialog=TextDialog('답란·학번 영역(빈 양식 이미지 픽셀 좌표)',sample,self,'등록');dialog.box.setReadOnly(False)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        name,ok=QInputDialog.getText(self,'외부 양식','양식 이름')
        if ok:register_external(self.store,name,image,json.loads(dialog.box.toPlainText()));self.refresh()

    def add(self):
        if ExamDialog(self.store,parent=self).exec()==QDialog.DialogCode.Accepted:self.refresh()

    def edit(self):
        eid=self.exams.current_id()
        if not eid:raise ValueError('시험을 선택하세요.')
        if ExamDialog(self.store,self.store.exam(eid),self).exec()==QDialog.DialogCode.Accepted:self.refresh()

    def archive(self):
        ids=self.exams.selected_ids()
        if ids and ask(self,f'{len(ids)}개 시험을 보관(목록에서 숨김)할까요? 성적은 지우지 않습니다.'):self.store.archive_exams(ids);self.refresh()


# ---- 채점·검수 ---------------------------------------------------------------------------
class GradingPage(BasePage):
    def __init__(self,window):
        super().__init__(window)
        widget,layout=page('채점·검수','OMR 스캔 PDF를 불러오면 인식·채점 후 검수 대기가 됩니다. 학생·시험 일치를 확인하고 확정한 성적만 성적표·오답노트·발송에 쓰입니다.')
        QVBoxLayout(self).addWidget(widget)
        self.exam=QComboBox();self.klass=QComboBox();self.day=date_edit()
        self.exam.currentIndexChanged.connect(self.load_scans)
        layout.addLayout(row(QLabel('시험'),self.exam,QLabel('분반'),self.klass,QLabel('응시일'),self.day,button('PDF 불러오기',guarded(self,self.import_pdf),True),'stretch'))
        split=QSplitter();layout.addWidget(split,1)
        self.table=Table(['ID','상태','학생','학번','점수','확인할 점']);self.table.itemSelectionChanged.connect(self.show_scan);split.addWidget(self.table)
        right=QWidget();rl=QVBoxLayout(right);split.addWidget(right);split.setSizes([600,600])
        self.image=QLabel('답안을 선택하세요.');self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll=QScrollArea();scroll.setWidget(self.image);scroll.setWidgetResizable(True);rl.addWidget(scroll,1)
        self.student=QComboBox();self.answers=QLineEdit();self.answers.setPlaceholderText('문항 순서대로, 빈 답은 -');self.identity=QCheckBox('학생·시험 일치 확인')
        rl.addLayout(row(QLabel('학생'),self.student));rl.addWidget(QLabel('답안'));rl.addWidget(self.answers);rl.addWidget(self.identity)
        rl.addLayout(row(button('검수 저장',guarded(self,self.save_review)),button('확정',guarded(self,self.confirm),True),button('제외',guarded(self,self.exclude)),'stretch'))
        layout.addLayout(row(button('선택 일괄 확정(확인할 점 없는 답안)',guarded(self,self.bulk)),button('미인식 다시 읽기',guarded(self,self.retry)),button('새로고침',self.load_scans),'stretch'))

    def refresh(self):
        current=self.exam.currentData();self.exam.blockSignals(True);self.exam.clear()
        for label,data in exam_items(self.store):self.exam.addItem(label,data)
        index=self.exam.findData(current);self.exam.setCurrentIndex(max(0,index));self.exam.blockSignals(False)
        cls=self.klass.currentData();self.klass.clear()
        for label,data in class_items(self.store):self.klass.addItem(label,data)
        i=self.klass.findData(cls);self.klass.setCurrentIndex(max(0,i))
        self.load_scans()

    def context(self):
        cid=self.klass.currentData()
        if cid is None:raise ValueError('분반을 선택하세요.')
        return next(c['academy_id'] for c in self.store.classes() if c['id']==cid),cid

    def import_pdf(self):
        eid=self.exam.currentData()
        if not eid:raise ValueError('시험을 먼저 등록하세요.')
        files,_=QFileDialog.getOpenFileNames(self,'OMR 스캔 PDF',str(Path.home()),'PDF·이미지 (*.pdf *.png *.jpg *.jpeg *.tif *.tiff)')
        if not files:return
        aid,cid=self.context()
        summary=run(self,'OMR을 인식하고 있어요.',grading.import_pdf,self.store,eid,files,aid,cid,iso(self.day))
        info(self,f"추가 {summary['added']} · 중복 {summary['duplicate']} · 인식 실패 {summary['failed']} · 다른 반 {summary['outside_class']}"+('\n'+'\n'.join(summary['errors']) if summary['errors'] else ''))
        self.load_scans()

    def load_scans(self):
        eid=self.exam.currentData()
        if not eid:self.table.fill([]);return
        rows=[]
        for s in self.store.scans(eid):
            s=dict(s);s['reading']=json.loads(s['reading']);s['import_context']=json.loads(s['import_context'])
            rows.append((s,grading.review_reasons(self.store,s)))
        status={'pending':'검수 대기','confirmed':'확정','failed':'인식 실패','excluded':'제외','superseded':'교체됨'}
        self.table.fill([[s['id'],status.get(s['status'],s['status']),s['name'] or '미연결',s['code'] or '',f"{s['score']/100:g}",', '.join(r)] for s,r in rows],[s['id'] for s,_ in rows])

    def show_scan(self):
        sid=self.table.current_id()
        if not sid:return
        scan=self.store.scan(sid);data=scan['normalized'] or scan['raw']
        pix=QPixmap();pix.loadFromData(data)
        self.image.setPixmap(pix.scaledToWidth(560,Qt.TransformationMode.SmoothTransformation) if not pix.isNull() else QPixmap())
        self.student.clear();self.student.addItem('(미연결)',None)
        cid=scan['import_context'].get('class_id')
        candidates=self.store.class_students(cid) if cid else self.store.students()
        for s in candidates:self.student.addItem(f"{s['name']} {s['code']}",s['id'])
        if scan['student_id'] and self.student.findData(scan['student_id'])<0:
            s=self.store.student(scan['student_id']);self.student.addItem(f"{s['name']} {s['code']}",s['id'])
        self.student.setCurrentIndex(max(0,self.student.findData(scan['student_id'])))
        self.answers.setText(','.join('-' if a is None else str(a) for a in scan['answers']));self.identity.setChecked(bool(scan['identity_ok']))

    def parsed_answers(self):
        values=[v.strip() for v in self.answers.text().split(',')]
        return [None if v in ('','-') else int(v) for v in values]

    def _write_review(self):
        """Save the open answer; returns its id. The id is taken before any table reload."""
        sid=self.table.current_id()
        if not sid:raise ValueError('답안을 선택하세요.')
        answers=self.parsed_answers()
        self.store.save_review(sid,self.student.currentData(),answers,[True]*len(answers),self.identity.isChecked(),allow_reopen=True)
        return sid

    def select(self,sid):
        for r in range(self.table.rowCount()):
            if self.table.item(r,0).data(Qt.ItemDataRole.UserRole)==sid:self.table.selectRow(r);return

    def save_review(self):
        sid=self._write_review();self.load_scans();self.select(sid)

    def confirm(self):
        sid=self._write_review()
        try:
            try:self.store.confirm(sid)
            except ValueError as exc:
                if not str(exc).startswith('DUPLICATE') or not ask(self,'같은 학생·시험의 확정 성적이 있습니다. 기존 성적을 이 답안으로 교체할까요?'):raise
                self.store.confirm(sid,replace=True)
        finally:
            self.load_scans();self.select(sid)

    def exclude(self):
        sid=self.table.current_id()
        if sid:self.store.set_status(sid,'excluded');self.load_scans()

    def bulk(self):
        ids=self.table.selected_ids() or [self.table.item(r,0).data(Qt.ItemDataRole.UserRole) for r in range(self.table.rowCount())]
        done,skipped=grading.confirm_clear(self.store,self.exam.currentData(),ids)
        info(self,f'{len(done)}건 확정, {len(skipped)}건은 확인이 필요해 남겼습니다.'+('\n'+'\n'.join(f'{a}: {b}' for a,b in skipped[:15]) if skipped else ''));self.load_scans()

    def retry(self):
        ids=[r['id'] for r in self.store.scans(self.exam.currentData()) if r['status']=='failed']
        if ids:
            aid,cid=self.context();summary=run(self,'다시 읽고 있어요.',grading.retry,self.store,self.exam.currentData(),ids,aid,cid)
            info(self,f"복구 {summary['recovered']} · 여전히 실패 {summary['failed']}");self.load_scans()


# ---- 미니테스트·과제 수기 입력 ------------------------------------------------------------
class EntriesPage(BasePage):
    def __init__(self,window):
        super().__init__(window)
        widget,layout=page('미니테스트·과제 입력','분반·수업 날짜를 고르면 분반 학생이 행으로 열립니다. 방향키 이동, 엑셀 범위 붙여넣기(Ctrl+V)를 지원하며 빈 칸은 미제출로 저장합니다.')
        QVBoxLayout(self).addWidget(widget)
        self.klass=QComboBox();self.day=date_edit()
        layout.addLayout(row(QLabel('분반'),self.klass,QLabel('수업 날짜'),self.day,button('불러오기',guarded(self,self.load)),'stretch'))
        self.table=Table(['학번','이름','미니테스트','과제(A/B/C)'],editable=True);layout.addWidget(self.table,1)
        QShortcut(QKeySequence.StandardKey.Paste,self.table,activated=guarded(self,self.paste))
        layout.addLayout(row(button('저장',guarded(self,self.save),True),button('엑셀 내보내기',guarded(self,self.export)),button('엑셀 가져오기',guarded(self,self.import_xlsx)),'stretch'))

    def refresh(self):
        cid=self.klass.currentData();self.klass.clear()
        for label,data in class_items(self.store):self.klass.addItem(label,data)
        self.klass.setCurrentIndex(max(0,self.klass.findData(cid)))

    def load(self):
        cid=self.klass.currentData()
        if cid is None:raise ValueError('분반을 선택하세요.')
        rows=entries.grid(self.store,cid,iso(self.day))
        self.table.fill([[r['code'],r['name'],'' if r['mini_score'] is None else f"{r['mini_score']:g}",r['homework'] if r['saved'] else ''] for r in rows],[r['student_id'] for r in rows])
        for r in range(self.table.rowCount()):
            for c in (0,1):self.table.item(r,c).setFlags(self.table.item(r,c).flags()&~Qt.ItemFlag.ItemIsEditable)

    def paste(self):
        from PySide6.QtWidgets import QApplication
        cells=entries.parse_paste(QApplication.clipboard().text());start_r=max(0,self.table.currentRow());start_c=max(2,self.table.currentColumn())
        for i,values in enumerate(cells):
            for j,value in enumerate(values):
                r,c=start_r+i,start_c+j
                if r<self.table.rowCount() and c in (2,3):self.table.setItem(r,c,QTableWidgetItem(value.strip()))

    def values(self):
        return [{'student_id':self.table.item(r,0).data(Qt.ItemDataRole.UserRole),'mini_score':(self.table.item(r,2).text() if self.table.item(r,2) else ''),
                 'homework':(self.table.item(r,3).text() if self.table.item(r,3) else '')} for r in range(self.table.rowCount())]

    def save(self):
        entries.save(self.store,self.klass.currentData(),iso(self.day),self.values());self.load();info(self,'저장했습니다. 빈 칸은 미제출로 기록했습니다.')

    def export(self):
        target=save_path(self,'엑셀 내보내기',f'미니테스트_{iso(self.day)}.xlsx','엑셀 (*.xlsx)')
        if target:entries.export_xlsx(self.store,self.klass.currentData(),iso(self.day),target)

    def import_xlsx(self):
        path,_=QFileDialog.getOpenFileName(self,'엑셀 가져오기',str(Path.home()),'엑셀 (*.xlsx)')
        if not path:return
        values,unmatched=entries.import_xlsx(self.store,self.klass.currentData(),iso(self.day),path)
        entries.save(self.store,self.klass.currentData(),iso(self.day),values);self.load()
        info(self,f'{len(values)}명 저장'+(f"\n찾지 못한 행: {', '.join(unmatched)}" if unmatched else ''))


# ---- 성적표·게시·안내 ---------------------------------------------------------------------
class ReportsPage(BasePage):
    def __init__(self,window):
        super().__init__(window)
        widget,layout=page('성적표·게시·안내','확정 성적만 성적표로 만듭니다. 게시하면 열람 웹에서 바로 볼 수 있고, 안내는 20:55~08:00에는 다음 날 08:00 예약으로 보냅니다.')
        QVBoxLayout(self).addWidget(widget)
        box=QGroupBox('성적표 출력');bl=QVBoxLayout(box);layout.addWidget(box,2)
        self.exam=QComboBox();self.exam.currentIndexChanged.connect(self.load_results)
        bl.addLayout(row(QLabel('시험'),self.exam,button('성적표 PDF 저장',guarded(self,self.export),True),button('석차 엑셀',guarded(self,self.ranking)),'stretch'))
        self.results=Table(['ID','학생','학번','분반','점수','응시일']);bl.addWidget(self.results)
        box=QGroupBox('분반 회차 게시·안내');bl=QVBoxLayout(box);layout.addWidget(box,2)
        self.sessions=Table(['ID','분반','날짜','확정 성적','게시','안내']);bl.addWidget(self.sessions)
        bl.addLayout(row(button('게시',guarded(self,self.publish),True),button('안내 보내기',guarded(self,self.send)),button('재발송',guarded(self,lambda:self.send(True))),button('수동 발송 완료 처리',guarded(self,self.manual_done)),'stretch'))
        box=QGroupBox('신규생·학번 변경 안내');bl=QVBoxLayout(box);layout.addWidget(box,1)
        self.pending=Table(['ID','이름','학번']);bl.addWidget(self.pending)
        bl.addLayout(row(button('선택 학생 안내',guarded(self,self.welcome)),button('예약 대기 발송',guarded(self,self.flush)),'stretch'))

    def refresh(self):
        current=self.exam.currentData();self.exam.blockSignals(True);self.exam.clear()
        for label,data in exam_items(self.store):self.exam.addItem(label,data)
        self.exam.setCurrentIndex(max(0,self.exam.findData(current)));self.exam.blockSignals(False);self.load_results()
        # sessions: every class/date with confirmed results gets a 회차 (link key) on demand
        pairs={(r['snapshot'].get('class_id'),r['day']) for r in self.store.results() if r['snapshot'].get('class_id')}
        for cid,day in sorted(pairs):entries.session(self.store,cid,day)
        rows=self.store.rows('SELECT s.id,c.name,s.date,(SELECT COUNT(*) FROM report_files r WHERE r.session_id=s.id) files,(SELECT status FROM notifications n WHERE n.session_id=s.id ORDER BY n.id DESC LIMIT 1) notice FROM class_sessions s JOIN classes c ON c.id=s.class_id ORDER BY s.date DESC,c.name')
        counts={(cid,day):0 for cid,day in pairs}
        for r in self.store.results():counts[(r['snapshot'].get('class_id'),r['day'])]=counts.get((r['snapshot'].get('class_id'),r['day']),0)+1
        cmap={s['id']:s['class_id'] for s in self.store.rows('SELECT id,class_id FROM class_sessions')}
        label={'sent':'발송','scheduled':'예약','failed':'실패(수동 필요)','manual':'수동 발송','queued':'예약 대기'}
        self.sessions.fill([[r['id'],r['name'],r['date'],counts.get((cmap[r['id']],r['date']),0),f"{r['files']}명" if r['files'] else '—',label.get(r['notice'],'—')] for r in rows],[r['id'] for r in rows])
        from academy.migrations.from_v106 import students_needing_notice
        pending=students_needing_notice(self.store)
        self.pending.fill([[p['id'],p['name'],p['code']] for p in pending],[p['id'] for p in pending])

    def load_results(self):
        eid=self.exam.currentData()
        rows=self.store.results(eid) if eid else []
        self.results.fill([[r['id'],r['snapshot']['name'],r['snapshot']['code'],r['snapshot'].get('classroom',''),f"{r['score']/100:g}",r['day']] for r in rows],[r['id'] for r in rows])

    def export(self):
        ids=self.results.selected_ids() or [self.results.item(r,0).data(Qt.ItemDataRole.UserRole) for r in range(self.results.rowCount())]
        if not ids:raise ValueError('확정 성적이 없습니다.')
        from core.export_names import export_name
        rows=[r for r in self.store.results() if r['id'] in ids]
        target=save_path(self,'성적표 저장',export_name(rows),'PDF (*.pdf)')
        if target:run(self,'성적표를 만들고 있어요.',render,self.store,ids,target);info(self,'저장했습니다.')

    def ranking(self):
        from core.ranking import ranking_xlsx
        eid=self.exam.currentData();classes=sorted({r['snapshot'].get('class_id') for r in self.store.results(eid)})
        target=save_path(self,'석차 엑셀','석차.xlsx','엑셀 (*.xlsx)')
        if target:ranking_xlsx(target,self.store,eid,classes);info(self,'저장했습니다.')

    def publish(self):
        sid=self.sessions.current_id()
        if not sid:raise ValueError('분반 회차를 선택하세요.')
        names=run(self,'성적표를 게시하고 있어요.',notify.publish,self.store,sid,self.app.publisher(self.store))
        info(self,f'{len(names)}명 게시했습니다. 열람 웹에서 바로 볼 수 있습니다.');self.refresh()

    def send(self,resend=False):
        sid=self.sessions.current_id()
        if not sid:raise ValueError('분반 회차를 선택하세요.')
        if resend and not ask(self,'이미 보낸 안내를 다시 보냅니다. 계속할까요?'):return
        messenger=self.app.messenger(self.store)
        try:result=run(self,'카카오 채널 메시지를 보내고 있어요.',notify.notify_session,self.store,sid,messenger,None,resend)
        finally:messenger.close()
        self.show_result(result);self.refresh()

    def show_result(self,result):
        if result['status']=='failed':
            manual=result['manual'];people='\n'.join(f"{p.get('name','')} {p.get('phone','')} {p.get('parent_phone','')}".strip() for p in manual.get('recipients',manual.get('targets',[])))
            TextDialog('수동 발송 필요',f"자동 발송을 멈췄습니다: {result.get('reason','')}\n\n[문구]\n{manual['text']}\n\n[링크] {manual.get('link','')}\n[대상] {manual.get('target','')}\n예약: {manual.get('schedule_at') or '즉시'}\n\n[명단]\n{people}",self).exec()
        elif result['status']=='scheduled':info(self,f"{result['scheduled_for']} 예약 발송으로 등록했습니다."+('\n채널 미추가자가 있습니다.' if result.get('missing_friends') else ''))
        else:info(self,'보냈습니다.'+(f"\n예상 대상 {result['friend_count']}명 · 명단 {result['roster']}명: 채널 미추가자가 있습니다." if result.get('missing_friends') else ''))

    def manual_done(self):
        sid=self.sessions.current_id()
        rows=self.store.rows("SELECT id FROM notifications WHERE session_id=? AND status='failed' ORDER BY id DESC LIMIT 1",(sid,))
        if not rows:raise ValueError('수동 발송이 필요한 안내가 없습니다.')
        notify.mark_manual_sent(self.store,rows[0]['id']);self.refresh()

    def welcome(self):
        ids=self.pending.selected_ids()
        if not ids:raise ValueError('안내할 학생을 선택하세요.')
        self.window.send_welcome(ids);self.refresh()

    def flush(self):
        messenger=self.app.messenger(self.store)
        try:done=notify.flush_due(self.store,messenger,self.app.publisher(self.store))
        finally:messenger.close()
        info(self,f'{len(done)}건 처리했습니다.');self.refresh()


# ---- 문항은행·오답노트 --------------------------------------------------------------------
class BankPage(BasePage):
    def __init__(self,window):
        super().__init__(window)
        widget,layout=page('문항은행·4주 오답노트','주간지 회차마다 문제 한글 파일(또는 PDF)을 등록하면 문항 번호 위치로 문항을 자르고, 해설도 같은 번호로 연결합니다.')
        QVBoxLayout(self).addWidget(widget)
        self.exam=QComboBox();self.exam.currentIndexChanged.connect(self.load)
        layout.addLayout(row(QLabel('주간지'),self.exam,button('문제 등록',guarded(self,lambda:self.register('문제')),True),button('해설 등록',guarded(self,lambda:self.register('해설'))),button('문항 자동 분할',guarded(self,self.split)),'stretch'))
        self.items=Table(['ID','문항','쪽','영역(pt)','방식','해설']);layout.addWidget(self.items,1)
        self.missing=QLabel();self.missing.setWordWrap(True);layout.addWidget(self.missing)
        layout.addLayout(row(button('영역 수정',guarded(self,self.edit_region)),button('유사문항 후보·연결',guarded(self,self.similar)),'stretch'))
        self.student=QComboBox()
        layout.addLayout(row(QLabel('학생'),self.student,button('4주 오답노트 만들기(선택 회차까지)',guarded(self,self.note),True),'stretch'))

    def refresh(self):
        current=self.exam.currentData();self.exam.blockSignals(True);self.exam.clear()
        for label,data in exam_items(self.store,('weekly',)):self.exam.addItem(label,data)
        self.exam.setCurrentIndex(max(0,self.exam.findData(current)));self.exam.blockSignals(False)
        self.student.clear()
        for s in self.store.students():self.student.addItem(f"{s['name']} {s['code']}",s['id'])
        self.load()

    def load(self):
        eid=self.exam.currentData()
        if not eid:self.items.fill([]);self.missing.setText('');return
        rows=questionbank.items(self.store,eid)
        self.items.fill([[i['id'],i['q_no'],i['page']+1,f"{i['x0']:.0f},{i['y0']:.0f}~{i['x1']:.0f},{i['y1']:.0f}",'자동' if i['method']=='auto' else '수동','있음' if i['solution_hash'] else '—'] for i in rows],[i['id'] for i in rows])
        missing=questionbank.unregistered(self.store,eid)
        self.missing.setText('미등록 문항: '+(', '.join(map(str,missing)) if missing else '없음'))

    def register(self,kind):
        eid=self.exam.currentData()
        if not eid:raise ValueError('주간지 시험을 선택하세요.')
        path,_=QFileDialog.getOpenFileName(self,f'{kind} 파일',str(Path.home()),'한글·PDF (*.hwp *.hwpx *.pdf)')
        if not path:return
        pdf=None;converter=self.app.hwp()
        if path.lower().endswith(('.hwp','.hwpx')) and not converter.available():
            pdf,_=QFileDialog.getOpenFileName(self,'이 PC에는 한글이 없습니다. 같은 내용의 PDF를 선택하세요.',str(Path(path).parent),'PDF (*.pdf)')
            if not pdf:return
        run(self,'파일을 등록하고 있어요.',questionbank.register_edition,self.store,eid,path,kind,pdf,converter);self.load()

    def split(self):
        result=run(self,'문항을 나누고 있어요.',questionbank.split_questions,self.store,self.exam.currentData())
        info(self,f"{len(result['found'])}문항을 찾았습니다."+(f"\n찾지 못한 문항: {', '.join(map(str,result['missing']))} → 영역 수정으로 지정하세요." if result['missing'] else ''));self.load()

    def edit_region(self):
        text,ok=QInputDialog.getText(self,'영역 수정','문항, 쪽, x0, y0, x1, y1 (pt, 왼쪽 위 기준)')
        if not ok:return
        q,p,x0,y0,x1,y1=[float(v) for v in text.split(',')]
        questionbank.set_region(self.store,self.exam.currentData(),int(q),int(p)-1,(x0,y0,x1,y1));self.load()

    def similar(self):
        qid=self.items.current_id()
        if not qid:raise ValueError('문항을 선택하세요.')
        candidates=questionbank.similar_candidates(self.store,qid)
        if not candidates:info(self,'같은 단원·난이도의 후보가 없습니다.');return
        labels=[f"{self.store.exam(c['exam_id'])['title']} {c['q_no']}번 ({c['unit']}·{c['difficulty'] or '난이도 미입력'})" for c in candidates]
        chosen,ok=QInputDialog.getItem(self,'유사문항 연결','후보',labels,0,False)
        if ok:questionbank.link_similar(self.store,qid,[candidates[labels.index(chosen)]['id']]);info(self,'연결했습니다.')

    def note(self):
        sid=self.student.currentData();eid=self.exam.currentData()
        if not sid or not eid:raise ValueError('학생과 기준 회차를 선택하세요.')
        target=save_path(self,'오답노트 저장',f"오답노트_{self.store.student(sid)['name']}.pdf",'PDF (*.pdf)')
        if not target:return
        result=run(self,'오답노트를 만들고 있어요.',wrongnote.build,self.store,sid,eid,target)
        info(self,f"{len(result['exams'])}회차 오답 {result['wrong']}문항."+(f"\n문항 이미지 미등록 {len(result['missing'])}문항은 자리만 표시했습니다." if result['missing'] else ''))


# ---- 손풀이 ------------------------------------------------------------------------------
class OverlayPage(BasePage):
    def __init__(self,window):
        super().__init__(window)
        widget,layout=page('손풀이 삽입','원본 문제지의 [손풀이] 상자에 문항별 손풀이를 넣어 학생별 PDF를 만듭니다. 원본 스캔은 수정하지 않습니다.')
        QVBoxLayout(self).addWidget(widget)
        self.exam=QComboBox();self.exam.currentIndexChanged.connect(self.load)
        layout.addLayout(row(QLabel('주간지'),self.exam,button('[손풀이] 영역 찾기',guarded(self,self.detect)),button('손풀이 등록',guarded(self,self.register)),button('인쇄용 문제지 저장',guarded(self,self.print_pdf),True),'stretch'))
        self.slots=Table(['문항','쪽','영역(pt)','방식','손풀이']);layout.addWidget(self.slots,1)
        layout.addLayout(row(button('영역 직접 지정',guarded(self,self.set_slot)),button('문제지 스캔 불러오기',guarded(self,self.import_scans),True),'stretch'))
        self.sheets=Table(['ID','학생','상태','쪽수','안내']);layout.addWidget(self.sheets,1)
        self.target=combo([('전체 문항','all'),('OMR 오답 문항만','wrong')])
        layout.addLayout(row(button('학생 연결',guarded(self,self.link)),QLabel('대상'),self.target,button('손풀이 PDF 만들기',guarded(self,self.compose),True),'stretch'))

    def refresh(self):
        current=self.exam.currentData();self.exam.blockSignals(True);self.exam.clear()
        for label,data in exam_items(self.store,('weekly',)):self.exam.addItem(label,data)
        self.exam.setCurrentIndex(max(0,self.exam.findData(current)));self.exam.blockSignals(False)
        self.target.setCurrentIndex(max(0,self.target.findData(program_setting(self.store,'overlay_target'))));self.load()

    def load(self):
        eid=self.exam.currentData()
        if not eid:self.slots.fill([]);self.sheets.fill([]);return
        solutions={r['q_no'] for r in self.store.rows('SELECT q_no FROM hand_solutions WHERE exam_id=?',(eid,))}
        slots=self.store.rows('SELECT * FROM solution_slots WHERE exam_id=? ORDER BY q_no',(eid,))
        self.slots.fill([[s['q_no'],s['page']+1,f"{s['x0']:.0f},{s['y0']:.0f}~{s['x1']:.0f},{s['y1']:.0f}",'자동' if s['method']=='auto' else '수동','있음' if s['q_no'] in solutions else '—'] for s in slots],[s['q_no'] for s in slots])
        sheets=self.store.rows('SELECT w.*,s.name FROM worksheets w LEFT JOIN students s ON s.id=w.student_id WHERE w.exam_id=? ORDER BY w.id',(eid,))
        self.sheets.fill([[w['id'],w['name'] or '미연결',{'pending':'학생 확인 필요','matched':'연결됨','composed':'완성'}[w['status']],w['pages'],json.loads(w['detail']).get('notice','')] for w in sheets],[w['id'] for w in sheets])

    def detect(self):
        result=run(self,'[손풀이] 영역을 찾고 있어요.',overlay.detect_slots,self.store,self.exam.currentData())
        info(self,f"{len(result['found'])}개 문항의 영역을 찾았습니다."+('\n문자가 없는 이미지 PDF입니다. 영역을 직접 지정하세요.' if result['no_text'] else ''));self.load()

    def set_slot(self):
        text,ok=QInputDialog.getText(self,'손풀이 영역','문항, 쪽, x0, y0, x1, y1 (pt, 왼쪽 위 기준)')
        if ok:
            q,p,x0,y0,x1,y1=[float(v) for v in text.split(',')];overlay.set_slot(self.store,self.exam.currentData(),int(q),int(p)-1,(x0,y0,x1,y1));self.load()

    def register(self):
        q,ok=QInputDialog.getInt(self,'손풀이 등록','문항 번호',1,1,60)
        if not ok:return
        path,_=QFileDialog.getOpenFileName(self,'손풀이 파일',str(Path.home()),'PNG·PDF (*.png *.pdf)')
        if path:overlay.register_hand_solution(self.store,self.exam.currentData(),q,path,self.app.local.get('operator',''));self.load()

    def print_pdf(self):
        target=save_path(self,'인쇄용 문제지','문제지_인쇄용.pdf','PDF (*.pdf)')
        if target:overlay.worksheet_pdf(self.store,self.exam.currentData(),target);info(self,'저장했습니다. 첫 쪽의 학번 칸에 학생이 7자리를 마킹합니다.')

    def import_scans(self):
        path,_=QFileDialog.getOpenFileName(self,'문제지 스캔 PDF',str(Path.home()),'PDF (*.pdf)')
        if not path:return
        result=run(self,'문제지 스캔을 확인하고 있어요.',overlay.import_worksheets,self.store,self.exam.currentData(),path)
        info(self,f"{len(result['worksheets'])}명분을 나눴습니다."+(f"\n읽지 못한 쪽: {result['unreadable_pages']}" if result['unreadable_pages'] else ''));self.load()

    def link(self):
        wid=self.sheets.current_id()
        if not wid:raise ValueError('문제지를 선택하세요.')
        students=self.store.students();labels=[f"{s['name']} {s['code']}" for s in students]
        chosen,ok=QInputDialog.getItem(self,'학생 연결','학생',labels,0,False)
        if ok:overlay.link_worksheet(self.store,wid,students[labels.index(chosen)]['id']);self.load()

    def compose(self):
        ids=self.sheets.selected_ids()
        if not ids:raise ValueError('문제지를 선택하세요.')
        folder=QFileDialog.getExistingDirectory(self,'저장할 폴더')
        if not folder:return
        made=[]
        for wid in ids:
            ws=self.store.rows('SELECT w.*,s.name,s.code FROM worksheets w LEFT JOIN students s ON s.id=w.student_id WHERE w.id=?',(wid,))[0]
            result=overlay.compose(self.store,wid,Path(folder)/f"손풀이_{ws['name']}_{ws['code']}.pdf",self.target.currentData());made.append(result)
        info(self,f'{len(made)}명분 손풀이 PDF를 만들었습니다.');self.load()


# ---- 설정 --------------------------------------------------------------------------------
class SettingsPage(BasePage):
    FIELDS=[('viewer_url','성적표 열람 웹 주소'),('reports_folder','성적표 게시 폴더(Drive 링크)'),('kakao_channel_id','카카오 채널 식별자(_xxxx)'),
            ('quiet_start','발송 제한 시작'),('quiet_end','발송 제한 끝'),('wrongnote_rounds','오답노트 회차 수'),('autosave_minutes','자동 저장(분)'),
            ('worksheet_id_position','문제지 학번 위치[x,y 비율]'),('login_fail_limit','로그인 실패 허용'),('login_lock_minutes','로그인 잠금(분)')]

    def __init__(self,window):
        super().__init__(window)
        widget,layout=page('설정','여기 값은 모든 PC가 백업으로 함께 씁니다. Google 토큰·카카오 로그인 세션은 PC별로 두고 백업하지 않습니다.')
        QVBoxLayout(self).addWidget(widget)
        form=QFormLayout();layout.addLayout(form);self.edits={}
        for name,label in self.FIELDS:
            self.edits[name]=QLineEdit();form.addRow(label,self.edits[name])
        self.report_name=QLineEdit();form.addRow('성적표 연구실명',self.report_name)
        self.kakao=combo([('수동 발송(문구·명단 표시)','manual'),('파트너센터 자동화','automation')]);form.addRow('카카오 발송 방식',self.kakao)
        self.dry=QCheckBox('자동화 시험 실행(발송 직전에서 멈춤)');form.addRow(self.dry)
        layout.addLayout(row(button('설정 저장',guarded(self,self.save),True),button('열람 웹 배포 파일 저장',guarded(self,self.export_viewer)),'stretch'))
        box=QGroupBox('신규생 안내문');bl=QVBoxLayout(box);layout.addWidget(box,1)
        self.templates=Table(['ID','제목','적용','버전','기본']);bl.addWidget(self.templates)
        bl.addLayout(row(button('안내문 추가',guarded(self,lambda:self.edit_template(None))),button('안내문 수정',guarded(self,lambda:self.edit_template(self.templates.current_id()))),'stretch'))

    def refresh(self):
        for name,_ in self.FIELDS:
            value=program_setting(self.store,name);self.edits[name].setText(json.dumps(value) if isinstance(value,list) else str(value))
        self.report_name.setText(self.store.report_name())
        self.kakao.setCurrentIndex(max(0,self.kakao.findData(self.store.setting('kakao_mode','manual'))));self.dry.setChecked(bool(self.store.setting('kakao_dry_run',False)))
        rows=self.store.rows('SELECT t.*,a.name academy,c.name classroom FROM notice_templates t LEFT JOIN academies a ON a.id=t.academy_id LEFT JOIN classes c ON c.id=t.class_id ORDER BY t.id')
        self.templates.fill([[t['id'],t['title'],t['classroom'] or t['academy'] or '전체',t['version'],'예' if t['is_default'] else ''] for t in rows],[t['id'] for t in rows])

    def save(self):
        for name,_ in self.FIELDS:
            text=self.edits[name].text().strip();default=DEFAULTS[name]
            if isinstance(default,int):value=int(text)
            elif isinstance(default,list):value=json.loads(text)
            else:value=text
            if name=='reports_folder' and value:
                from academy.adapters.gdrive.client import DriveClient
                value=DriveClient.folder_id(value)
            if value!=program_setting(self.store,name):self.store.set_setting(name,value)
        if self.report_name.text().strip()!=self.store.report_name():self.store.set_report_name(self.report_name.text())
        self.store.set_setting('kakao_mode',self.kakao.currentData());self.store.set_setting('kakao_dry_run',self.dry.isChecked())
        info(self,'저장했습니다.');self.refresh()

    def export_viewer(self):
        folder=QFileDialog.getExistingDirectory(self,'열람 웹 배포 파일을 저장할 폴더')
        if not folder:return
        from academy.config import app_root
        source=app_root()/'viewer'
        for name in ('Code.gs','index.html','appsscript.json'):shutil.copyfile(source/name,Path(folder)/name)
        values=f"ROOT_FOLDER_ID={program_setting(self.store,'reports_folder')}\nPEPPER={notify.pepper(self.store)}\nFAIL_LIMIT={program_setting(self.store,'login_fail_limit')}\nLOCK_MINUTES={program_setting(self.store,'login_lock_minutes')}\n"
        (Path(folder)/'스크립트_속성.txt').write_text(values,'utf-8')
        info(self,'Code.gs·index.html·appsscript.json과 스크립트 속성 값을 저장했습니다.\nREADME의 열람 웹 배포 순서를 따르세요. PEPPER는 외부에 공유하지 마세요.')

    def edit_template(self,template_id):
        old=self.store.rows('SELECT * FROM notice_templates WHERE id=?',(template_id,))[0] if template_id else None
        dialog=QDialog(self);dialog.setWindowTitle('신규생 안내문');dialog.resize(520,480);form=QFormLayout(dialog)
        title=QLineEdit(old['title'] if old else '신규생 안내');body=QPlainTextEdit(old['body'] if old else '');scope=combo([('전체',None)]+[(f"학원 {a['name']}",('a',a['id'])) for a in self.store.academies()]+[(f'분반 {l}',('c',cid)) for l,cid in class_items(self.store)])
        default=QCheckBox('기본 안내문으로 사용');default.setChecked(bool(old['is_default']) if old else True);attach=[None]
        pick=button('첨부(이미지·PDF)',lambda:attach.__setitem__(0,QFileDialog.getOpenFileName(dialog,'첨부',str(Path.home()),'이미지·PDF (*.png *.jpg *.pdf)')[0] or None))
        form.addRow('제목',title);form.addRow('본문({학생명}, {학번} 사용 시 학생별 링크)',body);form.addRow('적용 범위',scope);form.addRow(default);form.addRow(pick)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);form.addRow(buttons)
        if dialog.exec()!=QDialog.DialogCode.Accepted:return
        target=scope.currentData()
        notify.save_template(self.store,title.text(),body.toPlainText(),attach[0],target[1] if target and target[0]=='a' else None,target[1] if target and target[0]=='c' else None,default.isChecked(),template_id)
        self.refresh()
