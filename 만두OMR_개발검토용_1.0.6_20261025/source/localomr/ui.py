from __future__ import annotations
import csv
import json
import os
from pathlib import Path
from datetime import datetime
from functools import wraps
from PySide6.QtCore import Qt, QDate, QThread, Signal, QUrl, QTimer, QSize
from PySide6.QtGui import QPixmap, QColor, QPen, QDesktopServices, QFont, QFontDatabase, QImage, QPainter, QIntValidator, QIcon
from PySide6.QtWidgets import (
    QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,
    QPushButton,QLineEdit,QComboBox,QTableWidget,QTableWidgetItem,QHeaderView,
    QAbstractItemView,QDialog,QDialogButtonBox,QSpinBox,QDateEdit,QCheckBox,
    QFileDialog,QMessageBox,QStackedWidget,QListWidget,QListWidgetItem,QSplitter,QGraphicsView,
    QGraphicsScene,QProgressDialog,QTextEdit,QGroupBox,QScrollArea,QInputDialog,QStyle,QTabWidget,QFrame,
)
from .store import Store
from .examdata import effective,numeric,grade,ELECTIVES,percentile_label
from .mathomr import question_rect
from .examui import ExamEditor
from .omr import WIDTH, HEIGHT, answer_centers, id_centers
from .reports import sheet_pdf, report_pdf
from .importer import import_files,retry_failed,reread_selected,scan_in_scope
from .busy import BUSY_TEXT,run_store_task

STATE={'pending':'검수 대기','failed':'미인식','confirmed':'성적 확정','superseded':'교체된 답안','excluded':'집계 제외'}
FLAGS={'clear':'선명','blank':'무응답','multiple':'복수 마킹','faint':'흐림 / 흔적','failed':'미인식','incomplete':'숫자 자리 누락','manual':'수기 입력'}

from .design import STYLE



def guarded(fn):
    @wraps(fn)
    def wrapper(self,*args,**kwargs):
        try:
            return fn(self,*args,**kwargs)
        except Exception as exc:
            message=str(exc)
            if 'UNIQUE constraint failed' in message:
                message='같은 학생번호 또는 같은 시리즈·과목·회차가 이미 등록되어 있습니다.'
            QMessageBox.warning(self,'확인해 주세요',message)
    return wrapper


def button(text,callback,primary=False):
    b=QPushButton(text)
    if primary:b.setObjectName('Primary')
    b.clicked.connect(callback)
    return b


def label(text,kind=None):
    l=QLabel(text);l.setWordWrap(True)
    if kind:l.setObjectName(kind)
    return l


def table(headers):
    t=QTableWidget(0,len(headers));t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.verticalHeader().setVisible(False);t.setAlternatingRowColors(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.verticalHeader().setDefaultSectionSize(39)
    from .design import alignment
    for i,text in enumerate(headers):t.horizontalHeaderItem(i).setTextAlignment(alignment(text))
    return t


def populate(t,rows):
    t.setRowCount(len(rows))
    for i,(identity,values) in enumerate(rows):
        for j,value in enumerate(values):
            item=QTableWidgetItem(str(value));item.setData(Qt.ItemDataRole.UserRole,identity)
            from .design import alignment
            item.setTextAlignment(alignment(t.horizontalHeaderItem(j).text()));t.setItem(i,j,item)


def selected(t):
    row=t.currentRow()
    if row<0:raise ValueError('목록에서 항목을 선택하세요.')
    return t.item(row,0).data(Qt.ItemDataRole.UserRole)


def page(title,subtitle):
    w=QWidget();v=QVBoxLayout(w);v.setContentsMargins(28,23,28,24);v.setSpacing(16)
    v.addWidget(label(title,'Heading'));v.addWidget(label(subtitle,'Sub'))
    return w,v


class StudentDialog(QDialog):
    def __init__(self,store,student_id=None,parent=None):
        super().__init__(parent);self.store=store;self.student_id=student_id
        self.setWindowTitle('학생 등록 / 수정');self.resize(540,440)
        v=QVBoxLayout(self);f=QFormLayout();v.addLayout(f)
        self.name=QLineEdit();self.code=QLineEdit();self.code.setReadOnly(True);self.phone=QLineEdit();self.phone.setPlaceholderText('010-1234-5678 또는 5678');self.parent_phone=QLineEdit();self.school=QLineEdit();self.cls=QComboBox();self.cls.addItem('미배정 (선택)',None);self.active=QCheckBox('재원 학생');self.active.setChecked(True)
        for r in store.classes():self.cls.addItem(f"{r['academy']} / {r['name']}",r['id'])
        f.addRow('학생 성명 *',self.name);f.addRow('학생 연락처 *',self.phone);f.addRow('학교 (선택)',self.school);f.addRow('학부모 연락처 (선택)',self.parent_phone);f.addRow('학생번호 (자동)',self.code);f.addRow('기본 소속 반 (선택)',self.cls);f.addRow('',self.active)
        self.cls.hide();f.labelForField(self.cls).hide()
        self.code.setPlaceholderText('저장 시 연락처 뒤 4자리 + 1~9 자동 생성')
        v.addWidget(label('필수: 학생 성명, 학생 연락처(뒤 4자리 가능). 같은 뒤 4자리이면 구분번호를 1, 2, 3 순으로 배정합니다. 연락처 끝 4자리를 바꾸면 학생번호도 변경됩니다. 과거 성적 연결은 유지됩니다.','Sub'))
        if student_id:
            from .studentdata import display_code
            s=store.student(student_id);self.name.setText(s['name']);self.school.setText(s.get('school',''));self.code.setText(display_code(s['code']));self.phone.setText(s.get('phone') or (s['code'][1:5] if s['code'].startswith('0') else ''));self.parent_phone.setText(s.get('parent_phone',''));self.cls.setCurrentIndex(self.cls.findData(s['class_id']));self.active.setChecked(bool(s['active']))
        self.extra_classes=QListWidget();self.extra_classes.setMaximumHeight(150)
        selected={m['class_id'] for m in store.memberships(student_id)} if student_id else set()
        for row in store.classes():
            item=QListWidgetItem(f"{row['academy']} / {row['name']}");item.setData(Qt.ItemDataRole.UserRole,row['id']);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Checked if row['id'] in selected else Qt.CheckState.Unchecked);self.extra_classes.addItem(item)
        def choose_primary(index):
            for i in range(self.extra_classes.count()):
                if self.extra_classes.item(i).data(Qt.ItemDataRole.UserRole)==self.cls.currentData():self.extra_classes.item(i).setCheckState(Qt.CheckState.Checked)
        self.cls.currentIndexChanged.connect(choose_primary)
        v.addWidget(label('소속 반 · 여러 개 선택 가능 (미선택 시 미배정)','Sub'));v.addWidget(self.extra_classes)
        v.addWidget(button('학생 저장',self.save,True))

    @guarded
    def save(self):
        if not self.student_id:
            from .studentdata import phone_text
            phone=phone_text(self.phone.text())
            def same_contact(row):
                previous=''.join(c for c in row.get('phone','') if c.isdigit())
                return row['name'].strip()==self.name.text().strip() and previous[-4:]==phone[-4:] and (previous==phone or len(previous)==4 or len(phone)==4)
            matches=[r for r in self.store.students() if same_contact(r)]
            if matches:
                text='같은 이름과 연락처의 학생이 있습니다.\n'+'\n'.join(f"{r['name']} · {r['academy']} / {r['classroom']}" for r in matches)
                box=QMessageBox(self);box.setWindowTitle('중복 학생 확인');box.setTextFormat(Qt.TextFormat.PlainText);box.setText(text+'\n기존 학생에게 선택한 반을 추가할까요?')
                existing=box.addButton('기존 학생에게 반 추가',QMessageBox.ButtonRole.ActionRole);separate=box.addButton('별도 등록',QMessageBox.ButtonRole.AcceptRole);box.addButton('취소',QMessageBox.ButtonRole.RejectRole);box.exec()
                if box.clickedButton()==existing:
                    choices=[f"{r['name']} · {r['code'][-5:]} · {r['academy']} / {r['classroom']}" for r in matches]
                    choice,ok=(choices[0],True) if len(choices)==1 else QInputDialog.getItem(self,'기존 학생 확인','학생 선택',choices,0,False)
                    if ok:
                        found=matches[choices.index(choice)]
                        ids=[self.extra_classes.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.extra_classes.count()) if self.extra_classes.item(i).checkState()==Qt.CheckState.Checked]
                        if not ids:raise ValueError('추가할 소속 반을 선택해 주세요.')
                        current=[m['class_id'] for m in self.store.memberships(found['id'])]
                        self.store.set_student_classes(found['id'],[found['class_id']]+current+ids)
                        self.student_id=found['id'];self.accept()
                    return
                if box.clickedButton()!=separate:return
        ids=[self.extra_classes.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.extra_classes.count()) if self.extra_classes.item(i).checkState()==Qt.CheckState.Checked]
        primary=self.cls.currentData() if self.cls.currentData() in ids else (ids[0] if ids else None)
        self.student_id=self.store.save_student_contact(self.name.text(),self.phone.text(),self.school.text(),self.parent_phone.text(),primary,self.student_id,self.active.isChecked())
        if primary in ids:ids.remove(primary);ids.insert(0,primary)
        self.store.set_student_classes(self.student_id,ids or [self.store.student(self.student_id)['class_id']])
        self.accept()


ExamDialog = ExamEditor


class ImageView(QGraphicsView):
    def __init__(self):
        super().__init__();self.scene_=QGraphicsScene(self);self.setScene(self.scene_);self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag);self.highlight=None;self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    def load(self,blob):
        self.scene_.clear();self.highlight=None
        self.pixmap=QPixmap();self.pixmap.loadFromData(blob);self.scene_.addPixmap(self.pixmap);self.scene_.setSceneRect(self.pixmap.rect());self.fit()

    def fit(self):
        self.fitInView(self.scene_.sceneRect(),Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self,event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self.scene_.items():
                delta=event.angleDelta().y() or event.pixelDelta().y()
                factor=1.2**(delta/120)
                current=self.transform().m11()
                factor=max(.05,min(30,current*factor))/current
                point=event.position().toPoint();before=self.mapToScene(point)
                anchor=self.transformationAnchor();self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
                self.scale(factor,factor)
                after=self.mapToScene(point);offset=after-before;self.translate(offset.x(),offset.y())
                self.setTransformationAnchor(anchor)
            event.accept();return
        super().wheelEvent(event)

    def mark(self,q,math=False):
        if self.highlight:self.scene_.removeItem(self.highlight)
        x,y=answer_centers(q)[0]
        rect=question_rect(q+1) if math else (x-30,y-22,235,44)
        pen=QPen(QColor('#E53935'),2);pen.setCosmetic(True)
        self.highlight=self.scene_.addRect(*rect,pen);self.highlight.setZValue(2);self.ensureVisible(self.highlight,20,20)


class ReviewDialog(QDialog):
    def __init__(self,store,sid,parent=None):
        super().__init__(parent);self.store=store;self.sid=sid;self.data=store.scan(sid);self.base_exam=store.exam(self.data['exam_id']);self.exam=effective(self.base_exam,self.data['elective']);self.dirty=False;self.loading=True
        self.setWindowTitle(f"원본 검수 · 답안 {sid} · {self.exam['title']}");self.resize(1380,900)
        v=QVBoxLayout(self);top=QHBoxLayout();v.addLayout(top)
        self.student=QComboBox();self.student.setMinimumWidth(270);self.student.setEditable(True);self.student.setInsertPolicy(QComboBox.InsertPolicy.NoInsert);self.student.addItem('',None);self.student.lineEdit().setPlaceholderText('학생을 검색해 연결하세요');self.student.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        for s in store.students():self.student.addItem(f"{s['name']} · {s['code']} · {s['academy']} / {s['classroom']}",s['id'])
        self.student.setCurrentIndex(max(0,self.student.findData(self.data['student_id'])))
        self.identity_confirmed=bool(self.data['identity_ok'])
        top.addWidget(self.student);top.addStretch()
        self.register_student=button('신규생 등록 · 연결',self.new_student);top.addWidget(self.register_student)
        self.elective=QLineEdit(self.data['elective'] or '');self.elective.setMaxLength(1);self.elective.setMaximumWidth(65);self.elective.setValidator(QIntValidator(1,3,self.elective));self.elective.setPlaceholderText('1/2/3')
        self.elective.setToolTip('1 확통 / 2 미적분 / 3 기하');top.addWidget(self.elective);self.elective.setVisible(self.base_exam['config'].get('form')=='math30')
        top.addWidget(label('응시일자'));self.sat_on=QDateEdit(QDate.fromString(self.data['sat_on'],'yyyy-MM-dd'));self.sat_on.setCalendarPopup(True);self.sat_on.setDisplayFormat('yyyy-MM-dd');top.addWidget(self.sat_on)
        self.sat_on.dateChanged.connect(self.changed)
        self.status=label('');v.addWidget(self.status)
        if self.data['import_context'].get('notice'):v.addWidget(label(self.data['import_context']['notice']))
        split=QSplitter();v.addWidget(split,1)
        left=QWidget();lv=QVBoxLayout(left);lv.setContentsMargins(0,0,8,0)
        tools=QHBoxLayout();lv.addLayout(tools)
        self.original=QCheckBox('보정 전 원본');tools.addWidget(self.original)
        self.view=ImageView();tools.addWidget(button('맞춤',self.view.fit));tools.addWidget(button('+',lambda:self.view.scale(1.3,1.3)));tools.addWidget(button('-',lambda:self.view.scale(1/1.3,1/1.3)))
        lv.addWidget(self.view,1);lv.addWidget(label('문항을 선택하면 해당 마킹이 아래에 확대됩니다.','Sub'))
        self.crop=QLabel();self.crop.setAlignment(Qt.AlignmentFlag.AlignCenter);self.crop.setMinimumHeight(105);lv.addWidget(self.crop)
        split.addWidget(left)
        right=QWidget();rv=QVBoxLayout(right);rv.setContentsMargins(8,0,0,0)
        row=QHBoxLayout();rv.addLayout(row)
        self.filter=QComboBox();self.filter.addItems(['전체 문항','오답만','인식 확인 필요']);row.addWidget(self.filter);row.addWidget(button('이전 오답',lambda:self.next_wrong(-1)));row.addWidget(button('다음 오답',self.next_wrong))
        self.grid=QTableWidget(len(self.exam['key']),6);self.grid.setHorizontalHeaderLabels(['번호 / 판정','최초 인식','최종 답','정답','배점','인식 상태'])
        self.grid.verticalHeader().setVisible(False);self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents);self.grid.horizontalHeader().setStretchLastSection(True);self.grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.grid.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection);self.grid.verticalHeader().setDefaultSectionSize(39)
        rv.addWidget(self.grid,1);self.answer_widgets=[];self.reviewed=self.data['reviewed'].copy()
        for i,key in enumerate(self.exam['key']):
            read=self.data['reading'][i]
            for col,value in [(0,i+1),(1,read['answer'] if read['answer'] is not None else '—'),(3,key),(4,self.exam['points'][i]/100),(5,FLAGS[read['flag']])]:self.grid.setItem(i,col,QTableWidgetItem(str(value)))
            combo=QComboBox();combo.addItem('무응답',None);combo.addItem('복수/무효',-1)
            for num in (range(1000) if numeric(self.base_exam,i+1) else range(1,6)):combo.addItem(str(num),num)
            if numeric(self.base_exam,i+1):combo.setEditable(True);combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            combo.setCurrentIndex(combo.findData(self.data['answers'][i]));self.grid.setCellWidget(i,2,combo);self.answer_widgets.append(combo)
            combo.currentIndexChanged.connect(lambda _,q=i:self.answer_changed(q))
        self.note=QLineEdit();self.note.setPlaceholderText('수정 사유 / 검수 메모 (이력에 저장)');rv.addWidget(self.note)
        split.addWidget(right);split.setSizes([620,700])
        bottom=QHBoxLayout();v.addLayout(bottom)
        bottom.addWidget(button('수정 이력',self.audit));source_button=button('원본 파일 내보내기',self.export_source);source_button.setEnabled(not self.data['images_purged_at']);bottom.addWidget(source_button);bottom.addStretch()
        if self.data['images_purged_at']:
            self.original.setEnabled(False);self.view.setEnabled(False);self.crop.setText('이미지 정리됨 · 답안과 성적은 보존되어 있습니다.')
        self.save_button=button('검수 저장',self.save);self.confirm_button=button('성적 확정',self.confirm,True);bottom.addWidget(self.save_button);bottom.addWidget(self.confirm_button);bottom.addWidget(button('닫기',self.reject))
        self.original.toggled.connect(self.load_image);self.filter.currentIndexChanged.connect(self.refresh_status);self.grid.currentCellChanged.connect(lambda *_:self.show_crop());self.student.currentIndexChanged.connect(self.identity_changed);self.note.textChanged.connect(self.changed);self.elective.textChanged.connect(self.elective_changed)
        self.loading=False;self.load_image();self.refresh_status();self.grid.selectRow(0)
        if self.data['status'] in ('confirmed','superseded','excluded'):
            self.sat_on.setEnabled(False)
            self.register_student.setEnabled(False)
            self.save_button.setEnabled(False);self.confirm_button.setEnabled(False);self.student.setEnabled(False);self.elective.setEnabled(False);self.note.setReadOnly(True)
            for widget in self.answer_widgets:widget.setEnabled(False)
        screen=QApplication.primaryScreen()
        if screen:
            available=screen.availableGeometry();self.resize(min(1380,available.width()-40),min(900,available.height()-70))
        QTimer.singleShot(100,self.view.fit)

    @guarded
    def new_student(self):
        dlg=StudentDialog(self.store,parent=self)
        context=self.data.get('import_context',{});cid=context.get('class_id')
        if cid is not None:dlg.cls.setCurrentIndex(dlg.cls.findData(cid))
        imports=self.store.rows("SELECT detail FROM audit WHERE kind='scan_imported' AND entity_id=? ORDER BY id DESC LIMIT 1",(self.sid,))
        code=json.loads(imports[0]['detail']).get('recognized_code') if imports else None
        if code and len(code)==6 and code.startswith('0'):dlg.phone.setText(code[1:5])
        if dlg.exec():
            s=self.store.student(dlg.student_id);self.student.addItem(f"{s['name']} · {s['code']} · {s['academy']} / {s['classroom']}",s['id']);self.student.setCurrentIndex(self.student.count()-1);self.identity_confirmed=False
            QMessageBox.information(self,'등록 · 연결 완료',f"{s['name']} 학생을 연결했습니다. 원본의 성명·번호와 시험을 확인한 후 성적을 확정하세요.")

    def changed(self,*_):
        if not self.loading:self.dirty=True;self.refresh_status()

    def elective_changed(self,*_):
        self.exam=effective(self.base_exam,self.elective.text().strip() or None)
        for i in range(len(self.exam['key'])):
            self.grid.item(i,3).setText(str(self.exam['key'][i]) if self.exam['key'][i] is not None else '미등록')
            self.grid.item(i,4).setText(f"{self.exam['points'][i]/100:g}")
            if i>=22:self.reviewed[i]=False
        self.identity_confirmed=False;self.changed()

    def identity_changed(self,*_):
        self.identity_confirmed=False;self.changed()

    def answer_changed(self,q):
        self.reviewed[q]=False;self.changed()

    def load_image(self,*_):
        use_raw=self.original.isChecked() or not self.data['normalized']
        self.view.load(self.data['raw'] if use_raw else self.data['normalized']);self.show_crop()

    def show_crop(self):
        q=self.grid.currentRow()
        if q<0:return
        if self.data['normalized']:
            image=QPixmap();image.loadFromData(self.data['normalized']);x,y=answer_centers(q)[0]
            math=self.base_exam['config'].get('form')=='math30';rect=question_rect(q+1) if math else (x-75,y-23,285,46)
            self.crop.setPixmap(image.copy(*rect).scaled(560,170 if numeric(self.base_exam,q+1) else 92,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            if not self.original.isChecked():self.view.mark(q,math)
        else:self.crop.setText('이미지 정리됨 · 답안과 성적은 보존되어 있습니다.' if self.data['images_purged_at'] else '양식 미인식: 왼쪽 원본을 확대해 직접 입력하세요.')

    def refresh_status(self,*_):
        if self.loading:return
        answers=[c.currentData() for c in self.answer_widgets]
        score=self.store.score(answers,self.exam['key'],self.exam['points'])/100;wrong=0;alerts=0
        for i,key in enumerate(self.exam['key']):
            is_wrong=answers[i]!=key;alert=self.data['reading'][i]['flag']!='clear';wrong+=is_wrong;alerts+=alert
            self.grid.item(i,0).setText(f'{i+1} 오답' if is_wrong else str(i+1))
            self.answer_widgets[i].setStyleSheet('QComboBox { color: '+('#C43F48' if is_wrong else '#263549')+'; }')
            for col in [0,1,3,4]:self.grid.item(i,col).setForeground(QColor('#C43F48' if is_wrong else '#263549'))
            self.grid.item(i,5).setBackground(QColor('#FFF0D1' if alert else '#E9F5F0'))
            mode=self.filter.currentIndex();hide=(mode==1 and not is_wrong) or (mode==2 and not alert);self.grid.setRowHidden(i,hide)
        detail=f"가채점 {score:g} / {sum(self.exam['points'])/100:g}점   ·   오답 {wrong}   ·   인식 확인 {alerts}   ·   {STATE[self.data['status']]}"
        g=grade(int(round(score*100)),self.exam.get('cuts',[]))
        detail+='   ·   '+(f'{g}등급' if isinstance(g,int) else g or '등급컷 미설정')
        if not self.exam['configured']:detail+='\n선택과목 미확인 또는 정답 미등록: 성적을 확정할 수 없습니다.'
        if self.data['error']:detail+='\n'+self.data['error']
        self.status.setText(detail)

    def next_wrong(self,direction=1):
        start=self.grid.currentRow()
        for offset in range(1,len(self.answer_widgets)+1):
            q=(start+offset*direction)%len(self.answer_widgets)
            if self.answer_widgets[q].currentData()!=self.exam['key'][q]:
                self.filter.setCurrentIndex(0);self.grid.selectRow(q);self.grid.scrollToItem(self.grid.item(q,0));self.answer_widgets[q].setFocus()
                if self.answer_widgets[q].isEditable():self.answer_widgets[q].lineEdit().selectAll()
                return

    def persist(self):
        index=self.student.currentIndex()
        if index<0 or self.student.currentText()!=self.student.itemText(index):raise ValueError('검색 결과에서 정확한 학생을 선택하세요.')
        for combo in self.answer_widgets:
            if combo.isEditable() and combo.currentText()!=combo.itemText(combo.currentIndex()):raise ValueError('숫자 답안을 입력한 뒤 목록에서 해당 값을 선택하세요.')
        self.store.save_review(self.sid,self.student.currentData(),[c.currentData() for c in self.answer_widgets],self.reviewed,self.identity_confirmed,self.note.text(),self.elective.text().strip() or None,sat_on=self.sat_on.date().toString('yyyy-MM-dd'));self.dirty=False;self.data=self.store.scan(self.sid)

    @guarded
    def save(self):
        self.persist();self.refresh_status();QMessageBox.information(self,'저장 완료','검수 내용을 저장했습니다. 아직 평균에는 포함되지 않습니다.')

    @guarded
    def confirm(self):
        self.persist()
        try:self.store.confirm(self.sid,verify_identity=True)
        except ValueError as exc:
            if not str(exc).startswith('DUPLICATE:'):raise
            if QMessageBox.question(self,'중복 성적 검수','이 답안을 공식 성적으로 교체할까요?\n동일 학생·시험의 기존 확정 성적은 보관됩니다.')!=QMessageBox.StandardButton.Yes:return
            self.store.confirm(self.sid,replace=True,verify_identity=True)
        self.accept()

    @guarded
    def export_source(self):
        r=self.store.rows('SELECT name FROM sources WHERE id=?',(self.data['source_id'],))[0]
        path,_=QFileDialog.getSaveFileName(self,'최초 파일 내보내기',r['name'])
        if path:self.store.export_source(self.data['source_id'],path)

    def audit(self):
        dlg=QDialog(self);dlg.setWindowTitle('답안 수정 이력');dlg.resize(760,500);v=QVBoxLayout(dlg);text=QTextEdit();text.setReadOnly(True)
        rows=self.store.rows('SELECT at,kind,detail FROM audit WHERE entity_id=? AND kind IN (\'review_saved\',\'scan_imported\',\'scan_retried\',\'confirmed\',\'status_changed\') ORDER BY id',(self.sid,))
        text.setPlainText('\n\n'.join(f"{r['at']}  {r['kind']}\n{json.dumps(json.loads(r['detail']),ensure_ascii=False,indent=2)}" for r in rows));v.addWidget(text);dlg.exec()

    def reject(self):
        if self.dirty and QMessageBox.question(self,'저장하지 않은 검수','저장하지 않은 변경을 버리고 닫을까요?')!=QMessageBox.StandardButton.Yes:return
        super().reject()


class ImportWorker(QThread):
    progress=Signal(str);result=Signal(dict)
    def __init__(self,db_path,eid,paths,academy_id=None,class_id=None,sat_on=None,retry_ids=None,reread=False):
        super().__init__();self.db_path=db_path;self.eid=eid;self.paths=paths;self.academy_id=academy_id;self.class_id=class_id;self.sat_on=sat_on;self.retry_ids=retry_ids;self.reread=reread
    def run(self):
        try:
            if self.retry_ids is not None:summary=(reread_selected if self.reread else retry_failed)(self.db_path,self.eid,self.retry_ids,self.progress.emit,self.isInterruptionRequested,self.academy_id,self.class_id)
            else:summary=import_files(self.db_path,self.eid,self.paths,self.progress.emit,self.isInterruptionRequested,self.academy_id,self.class_id,self.sat_on)
        except Exception as exc:summary={'added':0,'duplicate':0,'failed':0,'errors':[str(exc)],'cancelled':False}
        self.result.emit(summary)


class MainWindow(QMainWindow):
    def __init__(self,store):
        super().__init__();self.store=store;self.worker=None
        from .handoff import Handoff
        self.handoff=Handoff(store);self.startup_backup_ready=False;self.scan_status_filter=None
        for filename in ('malgun.ttf','malgunbd.ttf'):
            font_path=Path('C:/Windows/Fonts')/filename
            if font_path.exists():QFontDatabase.addApplicationFont(str(font_path))
        emoji_font=Path('C:/Windows/Fonts/seguiemj.ttf')
        if emoji_font.exists():
            QFontDatabase.addApplicationFont(str(emoji_font))
            QFontDatabase.setApplicationEmojiFontFamilies(['Segoe UI Emoji'])
        QApplication.instance().setFont(QFont('Malgun Gothic',10))
        from .popup_style import install
        install()
        from . import __version__
        self.setWindowTitle('만두OMR '+__version__);self.resize(1300,840);self.setMinimumSize(1050,680)
        from .reports import report_asset
        self.setWindowIcon(QIcon(str(report_asset('LocalOMR.ico'))))
        QApplication.instance().setWindowIcon(self.windowIcon())
        root=QWidget();self.setCentralWidget(root);h=QHBoxLayout(root);h.setContentsMargins(0,0,0,0);h.setSpacing(0)
        from .icons import icon
        sidebar=QWidget();sidebar.setObjectName('Sidebar');sidebar.setFixedWidth(210);sv=QVBoxLayout(sidebar);sv.setContentsMargins(10,18,10,0);sv.setSpacing(8)
        brand=QHBoxLayout();brand.setContentsMargins(6,0,6,10)
        mascot=QLabel();mascot.setPixmap(QPixmap(str(report_asset('app_icon_heart.png'))).scaled(47,47,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation));brand.addWidget(mascot)
        name=QLabel('만두OMR');name.setStyleSheet('font-size:23px;font-weight:700;');brand.addWidget(name);brand.addStretch();sv.addLayout(brand)
        self.nav=QListWidget();self.nav.setObjectName('Nav');self.nav.setIconSize(QSize(25,25))
        for key,title in [('home','홈'),('students','학생 조회 · 추가'),('exam','시험 · 정답 관리'),('scan','OMR 채점 · 검수'),('pen','수기 채점'),('results','성적표 · 석차 조회'),('settings','설정')]:self.nav.addItem(QListWidgetItem(icon(key),title))
        sv.addWidget(self.nav,1);h.addWidget(sidebar)
        self.pages=QStackedWidget();h.addWidget(self.pages,1)
        self.make_home();self.make_students();self.make_exams();self.make_scoring()
        from .manualui import ManualPage
        self.manual=ManualPage(store,self);self.pages.addWidget(self.manual);self.manual.saved.connect(self.refresh)
        self.make_results();self.make_settings()
        self.nav.currentRowChanged.connect(self.page_changed);self.nav.setCurrentRow(0);self.refresh()
        from .drive_ui import DriveController
        self.drive=DriveController(self)
        self.statusBar().showMessage('만두OMR · 이 PC에 자동 저장됩니다.')

    def page_changed(self,index):
        previous=self.pages.currentIndex()
        if previous==3 and index!=3:
            if self.review_pane.answer_edited() is False:
                self.nav.blockSignals(True);self.nav.setCurrentRow(previous);self.nav.blockSignals(False);return
            eid=self.score_exam.currentData()
            aid=self.score_academy.currentData();cid=self.score_class.currentData()
            count=sum(r['status']=='pending' and scan_in_scope(r,aid,cid) for r in self.store.scans(eid)) if eid else 0
            if count:
                from .popups import ask
                choice=ask(self,'검수 대기 안내',f'검수 대기 OMR이 {count}장 있어요.\n성적을 확정해야 성적표를 출력할 수 있어요.\n다른 탭으로 이동할까요?','smart_mandu.png',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel,{QMessageBox.StandardButton.Cancel:'계속 검수하기',QMessageBox.StandardButton.Yes:'다른 탭 이동'})
                if choice!=QMessageBox.StandardButton.Yes:
                    self.nav.blockSignals(True);self.nav.setCurrentRow(previous);self.nav.blockSignals(False);return
        if index!=0 and not self.startup_backup_ready and self.pages.currentIndex()==0:
            from .popups import ask
            choice=ask(self,'작업 시작 · 백업 확인','작업 전 최신 백업을 확인해 주세요.','import_mandu.png',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.Yes,{QMessageBox.StandardButton.Yes:'백업 가져오기',QMessageBox.StandardButton.No:'이번에는 건너뛰기'})
            if choice==QMessageBox.StandardButton.No:self.startup_backup_ready=True
            elif choice==QMessageBox.StandardButton.Yes:self.restore()
            if not self.startup_backup_ready:
                self.nav.blockSignals(True);self.nav.setCurrentRow(0);self.nav.blockSignals(False);return
        self.pages.setCurrentIndex(index)
        if index==5 and getattr(self,'results_dirty',False):self.refresh_results()
        if index==0:self.refresh_home_counts();self.refresh_handoff()

    def refresh_home_counts(self):
        counts=[self.store.db.execute('SELECT COUNT(*) FROM students').fetchone()[0],len(self.store.exams()),self.store.db.execute("SELECT COUNT(*) FROM scans WHERE status IN ('pending','failed') AND exam_id IN (SELECT id FROM exams WHERE archived=0)").fetchone()[0]]
        self.set_home_counts(counts)

    def set_home_counts(self,counts):
        for item,title,value in zip(self.home_cards,['등록 학생','등록 시험','검수 대기'],counts):
            item.setText(f'<span style="font-size:12px;color:#607587">{title}</span><br><span style="font-size:23px;font-weight:600;color:#203752">{value}</span>')

    def make_home(self):
        from .reports import report_asset
        from .icons import icon
        w=QWidget();v=QVBoxLayout(w);v.setContentsMargins(28,23,28,24);v.setSpacing(16);self.pages.addWidget(w)
        cards=QHBoxLayout();cards.setSpacing(14);v.addLayout(cards);self.home_cards=[]
        for key in ('students','exam','clock'):
            card=QFrame();card.setObjectName('Surface');card.setFixedHeight(94);row=QHBoxLayout(card);row.setContentsMargins(12,8,12,8);row.addStretch()
            glyph=QLabel();glyph.setPixmap(icon(key).pixmap(30,30));row.addWidget(glyph);row.addSpacing(10)
            item=label('');item.setAlignment(Qt.AlignmentFlag.AlignCenter);item.setTextFormat(Qt.TextFormat.RichText);row.addWidget(item);row.addStretch();cards.addWidget(card,1);self.home_cards.append(item)
        self.home_notice=QWidget();self.home_notice.setObjectName('HomeNotice');notice=QHBoxLayout(self.home_notice);notice.setContentsMargins(22,18,22,18);notice.setSpacing(22)
        self.home_mascot=QLabel();self.home_mascot.setFixedSize(100,114);self.home_mascot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.home_mascot.setPixmap(QPixmap(str(report_asset('home_mascot.png'))).scaled(96,106,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation));notice.addWidget(self.home_mascot)
        content=QVBoxLayout();content.setSpacing(10);notice.addLayout(content,1)
        notice_title=QHBoxLayout();notice_title.addWidget(label('작업을 마치면 지금 백업을 눌러 주세요💙','HomeNoticeTitle'),1);self.drive_connection=label('구글드라이브 연결 필요','Sub');self.drive_connection.setWordWrap(False);self.drive_connection.setStyleSheet('padding:6px 10px;background:#F0ECF7;border-radius:8px;');notice_title.addWidget(self.drive_connection);content.addLayout(notice_title);content.addWidget(label('PC 백업을 연구실 구글드라이브에도 자동 업로드해요.','Sub'))
        actions=QHBoxLayout();actions.setSpacing(14);content.addLayout(actions)
        self.restore_button=button('드라이브 백업 가져오기',lambda:self.drive.check_latest(True));self.restore_button.setObjectName('Import');self.restore_button.setIcon(icon('folder'));self.restore_button.setIconSize(QSize(22,22))
        self.backup_button=button('지금 백업',self.backup,True);self.backup_button.setIcon(icon('save'));self.backup_button.setIconSize(QSize(22,22))
        for action in (self.restore_button,self.backup_button):action.setMinimumHeight(40);actions.addWidget(action,1)
        v.addWidget(self.home_notice)
        self.drive_status=label('구글드라이브 연결 필요','Sub');self.drive_location=label('','Sub')
        drive_line=QHBoxLayout();drive_line.addWidget(self.drive_status,1);drive_line.addWidget(button('연결 설정',lambda:self.drive.setup()));drive_line.addWidget(button('PC 백업 가져오기',self.restore));drive_line.addWidget(button('다른 위치에 백업 저장',lambda:self.backup(other_location=True)));v.addLayout(drive_line);v.addWidget(self.drive_location)
        self.home_handoff=label('PC에 저장한 자료와 드라이브 백업 상태를 확인해 주세요.','Sub');self.home_handoff.setTextFormat(Qt.TextFormat.PlainText);v.addWidget(self.home_handoff)
        self.home_routine=QFrame();self.home_routine.setObjectName('Surface');routine=QHBoxLayout(self.home_routine);routine.setContentsMargins(14,10,14,10);routine.setSpacing(10)
        for i,title in enumerate(('학생 · 반 등록','시험 · 정답 설정','파일 채점','검수 · 출력'),1):
            if i>1:routine.addWidget(label('→','Sub'));routine.addStretch()
            badge=QLabel(f'{i:02}');badge.setAlignment(Qt.AlignmentFlag.AlignCenter);badge.setFixedSize(34,34);badge.setStyleSheet('background:#F0E9F8;border-radius:17px;color:#5D516E;');routine.addWidget(badge);routine.addWidget(label(title));routine.addStretch()
        v.addWidget(self.home_routine);v.addStretch()
        bottom=QHBoxLayout();bottom.addStretch();self.home_storage_button=button('저장 용량 줄이기',self.clean_storage);self.home_storage_button.setIcon(icon('broom'));self.home_storage_button.setIconSize(QSize(18,18));self.home_storage_button.setStyleSheet('font-size:12px;padding:6px 10px;');bottom.addWidget(self.home_storage_button);v.addLayout(bottom)

    def make_students(self):
        w,v=page('학생조회·추가','학생번호로 성적을 연결합니다. 반을 옮겨도 과거 성적의 소속은 유지됩니다.');self.pages.addWidget(w)
        h=QHBoxLayout();v.addLayout(h);self.search=QLineEdit();self.search.setPlaceholderText('학생명, 학생번호, 학원 또는 반 검색');h.addWidget(self.search,1)
        h.addWidget(button('학원 · 반 등록',self.add_class));h.addWidget(button('학원 · 반 이름 변경',self.manage_organizations));h.addWidget(button('학생 추가',self.add_student,True));h.addWidget(button('선택 학생 수정',self.edit_student));h.addWidget(button('학생 합치기',self.merge_students));self.search.textChanged.connect(self.refresh_students)
        h=QHBoxLayout();v.addLayout(h);h.addWidget(button('엑셀 일괄 등록',self.import_students,True));h.addWidget(button('일괄 등록 서식 다운로드',self.student_template));h.addStretch()
        filters=QHBoxLayout();v.addLayout(filters)
        self.student_academy=QComboBox();self.student_class=QComboBox();self.student_status=QComboBox()
        self.student_status.addItem('모든 상태',None);self.student_status.addItem('재원',1);self.student_status.addItem('퇴원',0)
        for caption,combo in [('학원',self.student_academy),('반',self.student_class),('상태',self.student_status)]:filters.addWidget(label(caption));filters.addWidget(combo,1)
        self.student_academy.currentIndexChanged.connect(self.refresh_student_classes);self.student_class.currentIndexChanged.connect(self.refresh_students);self.student_status.currentIndexChanged.connect(self.refresh_students)
        self.student_table=table(['학원','반','성명','학교','학생번호','학부모연락처','학생연락처','상태']);v.addWidget(self.student_table,1);self.student_table.cellDoubleClicked.connect(lambda *_:self.edit_student())

    @guarded
    def student_template(self):
        from .studentdata import template_path
        import shutil
        path,_=QFileDialog.getSaveFileName(self,'일괄 등록 서식 다운로드','학생_일괄등록_서식.xlsx','Excel (*.xlsx)')
        if path:shutil.copy2(template_path(),path);QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @guarded
    def import_students(self):
        from .studentdata import read_students
        from .studentui import StudentImportDialog
        path,_=QFileDialog.getOpenFileName(self,'학생 엑셀 선택','','Excel (*.xlsx)')
        if path and StudentImportDialog(self.store,read_students(path),self).exec():self.refresh()

    @guarded
    def manage_organizations(self):
        from .organizationui import OrganizationDialog
        OrganizationDialog(self.store,self).exec();self.refresh()

    @guarded
    def add_class(self):
        dlg=QDialog(self);dlg.setWindowTitle('학원 · 반 등록');v=QVBoxLayout(dlg);f=QFormLayout();v.addLayout(f);academy=QComboBox();academy.setEditable(True)
        for a in self.store.rows('SELECT name FROM academies ORDER BY name'):academy.addItem(a['name'])
        name=QLineEdit();f.addRow('학원',academy);f.addRow('반',name);buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel);v.addWidget(buttons);buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject)
        if dlg.exec():
            if not academy.currentText().strip() or not name.text().strip():raise ValueError('학원명과 반 이름을 입력하세요.')
            aid=self.store.academy(academy.currentText());self.store.classroom(aid,name.text());self.refresh()

    @guarded
    def add_student(self):
        if StudentDialog(self.store,parent=self).exec():self.refresh()

    @guarded
    def merge_students(self):
        if self.worker or getattr(self,'_busy_operation',False) or self.drive.busy:raise ValueError('진행 중인 작업이 끝난 뒤 학생을 합쳐 주세요.')
        if not self.check_manual_before_backup():return
        if self.review_pane.answer_edited() is False:return
        from .mergeui import MergeStudentsDialog
        dialog=MergeStudentsDialog(self.store,self)
        if dialog.exec():self.refresh()

    @guarded
    def edit_student(self):
        if StudentDialog(self.store,selected(self.student_table),self).exec():self.refresh()

    def refresh_students(self,*_):
        from .studentdata import display_code
        rows=self.store.students(self.search.text());aid=self.student_academy.currentData();cid=self.student_class.currentData();active=self.student_status.currentData()
        rows=[s for s in rows if self.store.in_class(s['id'],cid,aid) and (active is None or s['active']==active)]
        for student in rows:
            members=self.store.memberships(student['id'])
            student['academy']=' / '.join(dict.fromkeys(m['academy'] for m in members))
            student['classroom']=' / '.join(m['classroom'] for m in members)
        rows.sort(key=lambda s:(s['academy'],s['classroom'],s['name'],s['code']))
        populate(self.student_table,[(s['id'],[s['academy'],s['classroom'],s['name'],s.get('school',''),display_code(s['code']),s.get('parent_phone',''),s.get('phone',''),'재원' if s['active'] else '퇴원']) for s in rows])

    def refresh_student_classes(self,*_):
        self.fill_classes(self.student_class,self.student_academy.currentData());self.refresh_students()

    def fill_classes(self,combo,aid):
        old=combo.currentData();combo.blockSignals(True);combo.clear();combo.addItem('모든 반',None)
        for c in self.store.classes():
            if aid is None or c['academy_id']==aid:combo.addItem(f"{c['academy']} / {c['name']}",c['id'])
        combo.setCurrentIndex(max(0,combo.findData(old)));combo.blockSignals(False)

    def fill_academies(self,combo):
        old=combo.currentData();combo.blockSignals(True);combo.clear();combo.addItem('모든 학원',None)
        for a in self.store.rows('SELECT * FROM academies ORDER BY name'):combo.addItem(a['name'],a['id'])
        combo.setCurrentIndex(max(0,combo.findData(old)));combo.blockSignals(False)

    def make_exams(self):
        w,v=page('시험 · 정답 관리','한 시험에 공통과 확률과 통계·미적분·기하를 함께 등록합니다. 엑셀 붙여넣기 후 셀을 직접 수정할 수 있습니다.');self.pages.addWidget(w)
        h=QHBoxLayout();v.addLayout(h);h.addWidget(button('시험 등록',self.add_exam,True));h.addWidget(button('선택 시험 복사',self.copy_exam));h.addWidget(button('정답 · 배점 수정',self.edit_exam));h.addWidget(button('선택 시험 OMR 저장',self.exam_form));h.addStretch()
        h.addWidget(button('선택 시험 삭제',self.delete_exams));h.addWidget(button('삭제 시험 복구',self.restore_exams))
        from .tableui import CheckTable
        self.exam_table=CheckTable(['선택','순번','시험명','등록일','문항','만점','정답 버전','최종 수정일시'],[48,48,440,104,55,55,76,160]);v.addWidget(self.exam_table,1);self.exam_table.cellDoubleClicked.connect(lambda *_:self.edit_exam())

    @guarded
    def delete_exams(self):
        if self.worker:raise ValueError('파일 처리가 끝난 뒤 시험을 삭제하세요.')
        ids=self.exam_table.checked_ids()
        if not ids:raise ValueError('삭제할 시험의 체크박스를 선택하세요.')
        if self.manual.has_unsaved():raise ValueError('수기 채점 중인 답안을 먼저 저장하거나 비워 주세요.')
        if QMessageBox.question(self,'선택 시험 삭제',f'{len(ids)}개 시험을 삭제할까요?\n관련 답안과 성적도 조회·집계에서 제외됩니다. 삭제 시험 복구로 되돌릴 수 있습니다.')!=QMessageBox.StandardButton.Yes:return
        self.store.archive_exams(ids);self.manual.discard_all();self.refresh()

    @guarded
    def restore_exams(self):
        rows=self.store.rows('SELECT id,title,day FROM exams WHERE archived=1 ORDER BY day DESC,id DESC')
        if not rows:QMessageBox.information(self,'삭제 시험 복구','복구할 시험이 없습니다.');return
        from .tableui import CheckTable
        dlg=QDialog(self);dlg.setWindowTitle('삭제 시험 복구');dlg.resize(680,420);v=QVBoxLayout(dlg)
        grid=CheckTable(['선택','시험명','등록일'],[48,470,110]);grid.fill([(r['id'],[r['title'],r['day']],[r['title'],r['day']]) for r in rows]);v.addWidget(grid)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.button(QDialogButtonBox.StandardButton.Ok).setText('선택 시험 복구');buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);v.addWidget(buttons)
        if dlg.exec() and grid.checked_ids():self.store.restore_exams(grid.checked_ids());self.refresh()

    @guarded
    def add_exam(self):
        if ExamDialog(self.store,parent=self).exec():self.refresh()

    @guarded
    def copy_exam(self):
        dlg=ExamDialog(self.store,selected(self.exam_table),self)
        dlg.eid=None;dlg.round.clear();dlg.day.setDate(QDate.currentDate());dlg.form.setEnabled(True);dlg.exam_code.clear();dlg.enabled.setChecked(True)
        dlg.copy_cut_review_required=True
        if dlg.exec():self.refresh()

    @guarded
    def edit_exam(self):
        dialog=ExamDialog(self.store,selected(self.exam_table),self)
        if dialog.exec():
            self.refresh()
            if getattr(dialog,'affected_ids',[]):
                box=QMessageBox(self);box.setWindowTitle('정답 변경 반영');box.setText(f'{len(dialog.affected_ids)}건의 성적이 검수 대기로 변경됐어요.');go=box.addButton('확인할 답안 보기',QMessageBox.ButtonRole.ActionRole);box.addButton('닫기',QMessageBox.ButtonRole.AcceptRole);box.exec()
                if box.clickedButton()==go:
                    self.nav.setCurrentRow(3)
                    if self.pages.currentIndex()!=3:return
                    self.score_academy.setCurrentIndex(0);self.score_class.setCurrentIndex(0);self.scan_status_filter='pending';self.score_exam.setCurrentIndex(self.score_exam.findData(dialog.eid));self.refresh_scans()
                    if dialog.affected_ids[0] in self.visible_scan_ids:self.scan_table.setCurrentCell(self.visible_scan_ids.index(dialog.affected_ids[0]),5)

    @guarded
    def blank_form(self):
        from .forms import math_form_path
        import shutil
        path,_=QFileDialog.getSaveFileName(self,'우리 수능 수학 OMR 저장','수능수학_기본OMR.pdf','PDF (*.pdf)')
        if path:shutil.copy2(math_form_path(),path);QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @guarded
    def exam_form(self):
        exam=self.store.exam(selected(self.exam_table))
        if exam['config'].get('form')=='math30':self.blank_form();return
        path,_=QFileDialog.getSaveFileName(self,'시험 OMR 양식','OMR_시험.pdf','PDF (*.pdf)')
        if path:sheet_pdf(path,len(exam['key']),exam['title']);QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def make_scoring(self):
        w,v=page('OMR 채점 · 원본 검수','이전·다음 오답으로 답안을 확인하고 성적을 확정하세요. 이미지에서 Ctrl+휠로 확대·축소할 수 있습니다.');self.pages.addWidget(w)
        v.setContentsMargins(18,10,18,10);v.setSpacing(6)
        h=QHBoxLayout();v.addLayout(h);self.score_exam=QComboBox();h.addWidget(self.score_exam,1);self.import_button=button('PDF · 이미지 불러오기',self.import_dialog,True);h.addWidget(self.import_button);self.score_exam.currentIndexChanged.connect(self.refresh_scans)
        h=QHBoxLayout();v.addLayout(h);h.addWidget(label('학원'));self.score_academy=QComboBox();h.addWidget(self.score_academy,1);h.addWidget(label('반'));self.score_class=QComboBox();h.addWidget(self.score_class,1);self.score_academy.currentIndexChanged.connect(self.refresh_score_classes);self.score_class.currentIndexChanged.connect(self.refresh_scans)
        h.addWidget(button('신규생 등록',self.scoring_student))
        h=QHBoxLayout();v.addLayout(h);h.addWidget(label('응시일자'));self.score_sat_on=QDateEdit(QDate.currentDate());self.score_sat_on.setCalendarPopup(True);self.score_sat_on.setDisplayFormat('yyyy-MM-dd');h.addWidget(self.score_sat_on);h.addWidget(button('오늘',lambda:self.score_sat_on.setDate(QDate.currentDate())));h.addStretch()
        self.scan_summary=label('','Sub');self.scan_summary.setWordWrap(False);self.scan_summary.setTextFormat(Qt.TextFormat.RichText);self.scan_summary.linkActivated.connect(self.filter_scan_status)
        summary_row=QHBoxLayout();summary_row.addWidget(self.scan_summary)
        from .reports import report_asset
        self.pending_mascot=QPushButton();self.pending_mascot.setIcon(QIcon(str(report_asset('arrow_mandu.png'))))
        self.pending_mascot.setIconSize(QSize(44,44));self.pending_mascot.setFixedHeight(56)
        self.pending_mascot.setStyleSheet('QPushButton { background:#FFF0E4; border:1px solid #E8C5AB; border-radius:10px; color:#8A4C30; font-weight:600; padding:5px 14px; } QPushButton:hover { background:#FFE6D3; }')
        self.pending_mascot.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pending_mascot.setAccessibleName('검수 대기 OMR만 보기')
        self.pending_mascot.clicked.connect(lambda:self.filter_scan_status('pending'))
        self.pending_mascot.hide();summary_row.addWidget(self.pending_mascot)
        shortcut_hint=label('│  Ctrl+A 전체 선택','Sub');shortcut_hint.setWordWrap(False)
        summary_row.addWidget(shortcut_hint);summary_row.addStretch();v.addLayout(summary_row)
        from .review_pane import AnswerTable,ReviewPane
        self.scan_table=AnswerTable();self.scan_table.setMinimumHeight(120)
        self.scan_sort_column=None;self.scan_sort_descending=False
        self.scan_table.horizontalHeader().setSectionsClickable(True)
        self.scan_table.horizontalHeader().sectionClicked.connect(self.sort_scan_column)
        self.review_pane=ReviewPane(self.store,self);self.review_pane.setMinimumHeight(275)
        self.scan_split=QSplitter(Qt.Orientation.Vertical);self.scan_split.addWidget(self.scan_table);self.scan_split.addWidget(self.review_pane);self.scan_split.setSizes([190,340]);v.addWidget(self.scan_split,1)
        self.scan_table.currentCellChanged.connect(self.scan_cell_selected);self.scan_table.itemChanged.connect(self.scan_answer_edited)
        self.review_pane.next_student_requested.connect(self.next_scan_student)
        self.review_pane.saved.connect(self.inline_review_saved);self.review_pane.question_selected.connect(lambda q:self.scan_table.setCurrentCell(self.scan_table.currentRow(),5+q))
        h=QHBoxLayout();v.addLayout(h);h.addWidget(button('선택 행 삭제',self.delete_selected_scans));h.addWidget(button('삭제 취소',self.undo_scan_deletion));h.addWidget(button('상세 검수',self.open_review));h.addWidget(button('성적 집계에서 제외',self.exclude));h.addStretch()
        self.retry_button=button('선택 OMR 다시 인식',self.retry_unrecognized);h.addWidget(self.retry_button)
        h.addSpacing(24);self.bulk_confirm=button('전체 학생 성적 확정',self.confirm_visible_scans);self.bulk_confirm.setObjectName('Primary');h.addWidget(self.bulk_confirm)

    def refresh_scans(self,*_):
        previous=self.review_pane.sid;question=self.review_pane.q
        eid=self.score_exam.currentData()
        if eid and not self.worker:self.store.relink_unresolved(eid,self.score_academy.currentData(),self.score_class.currentData())
        rows=self.store.scans(eid) if eid else []
        total=len(rows)
        if hasattr(self,'score_academy'):
            aid=self.score_academy.currentData();cid=self.score_class.currentData()
            rows=[r for r in rows if scan_in_scope(r,aid,cid)]
        self.scoped_scan_rows=rows.copy()
        if self.scan_status_filter:rows=[r for r in rows if r['status']==self.scan_status_filter]
        if self.scan_sort_column is not None:
            col=self.scan_sort_column
            def sort_value(row):
                if col==0:return int(row['code']) if row['code'] and str(row['code']).isdigit() else -1
                if col==1:return row['name'] or ''
                if col==2:return row['elective'] or ''
                if col==3:return row['score']
                return STATE[row['status']]
            rows.sort(key=lambda row:(sort_value(row),row['id']),reverse=self.scan_sort_descending)
        self.visible_scan_ids=[r['id'] for r in rows]
        base=self.store.exam(eid) if eid else None;count=len(base['key']) if base else 30
        from .review_reasons import row_reasons
        self.scan_reasons=row_reasons(self.store,self.scoped_scan_rows,base)
        self.scan_table.blockSignals(True);self.scan_table.setColumnCount(5+count);self.scan_table.setHorizontalHeaderLabels(['학생번호','학생','선택과목','점수','처리 상태']+[str(i+1) for i in range(count)]);self.scan_table.setRowCount(len(rows))
        from .design import alignment
        for col,width in enumerate([66,94,70,50,106]+[38]*count):
            self.scan_table.setColumnWidth(col,width);self.scan_table.horizontalHeaderItem(col).setTextAlignment(alignment(self.scan_table.horizontalHeaderItem(col).text()))
        for i,row in enumerate(rows):self.fill_scan_row(i,row,base)
        self.scan_table.blockSignals(False)
        self.update_scan_summary(rows,total)
        if rows:
            index=self.visible_scan_ids.index(previous) if previous in self.visible_scan_ids else 0
            self.scan_table.blockSignals(True);self.scan_table.setCurrentCell(index,5+min(question,count-1));self.scan_table.blockSignals(False)
            self.review_pane.show_scan(rows[index]['id'],min(question,count-1))
        else:self.review_pane.clear()

    def sort_scan_column(self,col):
        if col>=5:return
        if self.review_pane.answer_edited() is False:return
        self.scan_sort_descending=not self.scan_sort_descending if self.scan_sort_column==col else False
        self.scan_sort_column=col
        header=self.scan_table.horizontalHeader();header.setSortIndicatorShown(True)
        header.setSortIndicator(col,Qt.SortOrder.DescendingOrder if self.scan_sort_descending else Qt.SortOrder.AscendingOrder)
        self.refresh_scans()

    def select_restored_scans(self,ids):
        visible=[sid for sid in ids if sid in self.visible_scan_ids]
        self.scan_table.clearSelection()
        if visible:
            row=self.visible_scan_ids.index(visible[0]);self.scan_table.setCurrentCell(row,1)
            self.scan_table.scrollToItem(self.scan_table.item(row,1))
            self.scan_table.blockSignals(True)
            for sid in visible:
                row=self.visible_scan_ids.index(sid)
                for col in range(self.scan_table.columnCount()):
                    item=self.scan_table.item(row,col)
                    if item:
                        item.setData(Qt.ItemDataRole.UserRole+9,item.data(Qt.ItemDataRole.BackgroundRole))
                        item.setSelected(True);item.setBackground(QColor('#D9EEE2'))
            self.scan_table.blockSignals(False)
            QTimer.singleShot(6000,lambda:self.clear_restored_highlight(visible))
        names=[self.store.scan(sid,images=False)['student_id'] for sid in ids]
        roster={s['id']:s['name'] for s in self.store.students()}
        label=roster.get(names[0],'학생 미연결') if names else ''
        message=f"{label}"+(f' 외 {len(ids)-1}명' if len(ids)>1 else '')+' 복구됨'
        if len(visible)<len(ids):message+=' · 현재 학원·반 필터 밖의 답안도 복구되었습니다.'
        self.statusBar().showMessage(message,12000)

    def clear_restored_highlight(self,ids):
        self.scan_table.blockSignals(True)
        for row in range(self.scan_table.rowCount()):
            first=self.scan_table.item(row,0)
            if first and first.data(Qt.ItemDataRole.UserRole) in ids:
                for col in range(self.scan_table.columnCount()):
                    item=self.scan_table.item(row,col)
                    if item and item.background().color()==QColor('#D9EEE2'):
                        item.setData(Qt.ItemDataRole.BackgroundRole,item.data(Qt.ItemDataRole.UserRole+9))
        self.scan_table.blockSignals(False)

    def update_scan_summary(self,rows,total):
        scoped=getattr(self,'scoped_scan_rows',rows)
        counts={state:sum(r['status']==state for r in scoped) for state in ('confirmed','pending','failed')}
        self.pending_mascot.setVisible(counts['pending']>0)
        self.pending_mascot.setText(f"검수 대기 {counts['pending']}장  ›")
        self.pending_mascot.setAccessibleName(f"검수 대기 {counts['pending']}장만 보기")
        self.pending_mascot.setToolTip(f"검수 대기 {counts['pending']}장 · 클릭하면 검수 대기 OMR만 표시합니다.")
        parts=[f"시험 전체 {total}장",f"현재 표시 {len(rows)}장",f"확정 {counts['confirmed']}장"]
        if self.scan_status_filter:parts.append('<a href="all" style="color:#684692">전체 보기</a>')
        for key,title in [('failed','미인식'),('pending','검수 대기')]:
            if key=='pending' and counts[key]:continue
            color='#A04F40' if counts[key] else '#746E81'
            parts.append(f'<a href="{key}" style="color:{color};text-decoration:none;">{title} {counts[key]}장</a>')
        self.scan_summary.setText(' · '.join(parts))
        self.scan_summary.setToolTip('검수 대기·미인식을 클릭하면 해당 답안만 표시합니다. 행의 처리 상태에 마우스를 올리면 확인할 내용을 볼 수 있습니다.')
        if hasattr(self,'retry_button'):self.retry_button.setEnabled(not self.worker and any(r['status'] in ('failed','pending') and r['input_mode']=='scan' and not r['images_purged_at'] for r in rows))

    def filter_scan_status(self,key):
        if self.review_pane.answer_edited() is False:return
        self.scan_status_filter=None if key=='all' else key;self.refresh_scans()

    def next_scan_student(self):
        if self.review_pane.answer_edited() is False:return
        sid=self.review_pane.sid
        if sid not in self.visible_scan_ids:return
        index=self.visible_scan_ids.index(sid)+1
        if index>=len(self.visible_scan_ids):
            QMessageBox.information(self,'다음 학생','현재 목록의 마지막 학생입니다.');return
        self.scan_table.setCurrentCell(index,5)
        self.scan_table.scrollToItem(self.scan_table.item(index,5))
        self.review_pane.answer.setFocus();self.review_pane.answer.selectAll()

    def fill_scan_row(self,index,row,base):
        from .review_pane import ANSWER_ROLE
        exam=effective(base,row['elective']);answers=json.loads(row['answers']) if isinstance(row['answers'],str) else row['answers'];reading=json.loads(row['reading']) if isinstance(row['reading'],str) else row['reading']
        values=[(row['code'] or '—')[-5:],row['name'] or '학생 미연결',(row['elective'] or '—') if base['config'].get('form')=='math30' else '공통',f"{row['score']/100:g}" if exam['configured'] else '—',STATE[row['status']]]
        detail=('이미지 정리됨 · ' if row.get('images_purged_at') else '')+f"{row['filename']} · {row['page']}쪽 · 응시 {row['sat_on']}"+ ('\n'+row['error'] if row['error'] else '')
        for col,value in enumerate(values):
            item=self.scan_table.item(index,col)
            if item is None:item=QTableWidgetItem();self.scan_table.setItem(index,col,item)
            item.setText(value);item.setData(Qt.ItemDataRole.UserRole,row['id']);item.setToolTip(detail);item.setTextAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter if col==1 else Qt.AlignmentFlag.AlignCenter)
            if col==4 and row['status'] in ('pending','failed'):
                reason=getattr(self,'scan_reasons',{}).get(row['id'],'')
                if reason:item.setText(value+'\n'+reason)
                item.setToolTip(detail+'\n'+(reason or '원본과 학생 연결을 확인한 뒤 성적을 확정하세요.'));item.setForeground(QColor('#A04F40'))
            else:item.setData(Qt.ItemDataRole.ForegroundRole,None)
            editable=col==2 and base['config'].get('form')=='math30' and row['input_mode']!='manual'
            item.setFlags(item.flags()|Qt.ItemFlag.ItemIsEditable if editable else item.flags()&~Qt.ItemFlag.ItemIsEditable)
        if self.scan_table.cellWidget(index,2):self.scan_table.removeCellWidget(index,2)
        if base['config'].get('form')=='math30':
            item=self.scan_table.item(index,2);item.setData(ANSWER_ROLE,int(row['elective']) if row['elective'] else None)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter);item.setToolTip('1 확통 / 2 미적분 / 3 기하 · 숫자 직접 입력')
            if not row['elective']:item.setBackground(QColor('#FFF1D6'))
            else:item.setData(Qt.ItemDataRole.BackgroundRole,None)
        for q,a in enumerate(answers):
            key=exam['key'][q];known=key is not None and not(base['config'].get('form')=='math30' and q>=22 and not row['elective'])
            verdict='O' if known and a==key else 'X' if known else '?'
            value='-' if a is None else '무효' if a<0 else str(a)
            item=QTableWidgetItem(value+('\n×' if verdict=='X' else '\n?' if verdict=='?' else ''));item.setData(Qt.ItemDataRole.UserRole+3,verdict);item.setTextAlignment(Qt.AlignmentFlag.AlignCenter);item.setData(Qt.ItemDataRole.UserRole,row['id']);item.setData(ANSWER_ROLE,a);item.setData(Qt.ItemDataRole.UserRole+2,numeric(base,q+1))
            if row['input_mode']=='manual':item.setFlags(item.flags()&~Qt.ItemFlag.ItemIsEditable)
            item.setForeground(QColor('#B23330' if verdict=='X' else '#126254' if verdict=='O' else '#607080'))
            if reading[q]['flag']!='clear':item.setBackground(QColor('#FFF1D6'))
            elif verdict=='X':item.setBackground(QColor('#FCEBE7'))
            item.setToolTip(f"{q+1}번 · 정답 {key if known else '선택과목 확인 필요'} · 학생 답안 {value} · {verdict}\n인식: {FLAGS[reading[q]['flag']]}\n방향키 이동 · 숫자 입력 · Delete: 답안 비우기")
            self.scan_table.setItem(index,5+q,item)

    @guarded
    def scan_choice_changed(self,sid,elective):
        if self.review_pane.sid!=sid:self.review_pane.show_scan(sid,22)
        self.review_pane.choice_changed(elective)

    @guarded
    def scan_cell_selected(self,row,col,*_):
        if row<0 or not self.scan_table.item(row,0):return
        sid=self.scan_table.item(row,0).data(Qt.ItemDataRole.UserRole);q=max(0,col-5)
        if sid==self.review_pane.sid:self.review_pane.show_question(q)
        else:self.review_pane.show_scan(sid,q)
        if col==2:self.review_pane.show_choice()

    def inline_review_saved(self,sid):
        # Replacing cells while the delegate commits can detach its active editor.
        if self.scan_table.state()==QAbstractItemView.State.EditingState:
            QTimer.singleShot(0,lambda:self.refresh_inline_review(sid));return
        self.refresh_inline_review(sid)

    def refresh_inline_review(self,sid):
        if self.score_exam.currentData() is None:return
        rows=self.store.scans(self.score_exam.currentData());record=next((r for r in rows if r['id']==sid),None)
        from .review_reasons import row_reasons
        self.scan_reasons=row_reasons(self.store,rows,self.store.exam(self.score_exam.currentData()))
        if record and sid in self.visible_scan_ids:
            self.scan_table.blockSignals(True);self.fill_scan_row(self.visible_scan_ids.index(sid),record,self.store.exam(self.score_exam.currentData()));self.scan_table.blockSignals(False)
        self.scoped_scan_rows=[r for r in rows if scan_in_scope(r,self.score_academy.currentData(),self.score_class.currentData())]
        if self.scan_status_filter and record and record['status']!=self.scan_status_filter:self.refresh_scans()
        self.update_scan_summary([r for r in rows if r['id'] in self.visible_scan_ids],len(rows))
        self.results_dirty=True
        if self.nav.currentRow()==5:self.refresh_results()

    @guarded
    def confirm_visible_scans(self):
        if self.worker:raise ValueError('파일 처리가 끝난 뒤 확정하세요.')
        if self.review_pane.answer_edited() is False:return
        from collections import Counter
        from .bulk_confirm import candidates
        aid,cid=self.score_academy.currentData(),self.score_class.currentData()
        ready,skipped,already=candidates(self.store,self.visible_scan_ids,aid,cid)
        details='\n'.join(f'{key}: {value}장' for key,value in Counter(skipped).items())
        message=f"{self.score_exam.currentText()}\n{self.score_academy.currentText()} / {self.score_class.currentText()}\n현재 표시 {len(self.visible_scan_ids)}장 · 추가 확정 {len(ready)}장 · 이미 확정 {already}장\n"+details
        if not ready:QMessageBox.information(self,'전체 학생 성적 확정',message+'\n추가로 확정할 답안이 없습니다.');return
        if QMessageBox.question(self,'전체 학생 성적 확정','추가 대상의 성적을 확정할까요?\n현재 연결된 학생·선택과목·답안으로 확정하며, 기존 확정 성적은 유지합니다.\n\n'+message,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:return
        failures=[];done=0
        for sid in ready:
            try:
                still_ready,reasons,_=candidates(self.store,[sid],aid,cid)
                if not still_ready:failures.extend(reasons);continue
                self.store.confirm(sid,verify_identity=True);done+=1
            except ValueError as exc:failures.append(str(exc).replace('DUPLICATE:',''))
        self.refresh_scans();self.refresh_results();self.refresh_home_counts()
        from .popup_style import result_message
        result_message(self,'일괄 확정 결과',f'추가 확정 {done}장 · 기존 확정 {already}장 유지 · 남은 답안 {len(skipped)+len(failures)}장'+('\n'+details if details else '')+('\n'+'\n'.join(failures[:3]) if failures else ''),partial=bool(skipped or failures))

    @guarded
    def delete_selected_scans(self):
        if self.worker:raise ValueError('불러오기가 끝난 후 삭제해 주세요.')
        rows=sorted({index.row() for index in self.scan_table.selectedIndexes()})
        if not rows:raise ValueError('삭제할 행을 선택하세요. Ctrl+A로 현재 목록 전체를 선택할 수 있습니다.')
        ids=[self.scan_table.item(row,0).data(Qt.ItemDataRole.UserRole) for row in rows]
        if QMessageBox.question(self,'선택 행 삭제',f'선택한 {len(ids)}개 행을 삭제할까요?\n확정 성적은 평균·성적표에서 제외됩니다. 잘못 삭제한 경우 삭제 취소로 복구할 수 있습니다.')!=QMessageBox.StandardButton.Yes:return
        self.store.delete_scans(self.score_exam.currentData(),ids);self.refresh_scans();self.refresh_results()

    @guarded
    def undo_scan_deletion(self):
        if self.worker:raise ValueError('불러오기가 끝난 후 복구해 주세요.')
        ids=self.store.restore_deleted_scans(self.score_exam.currentData(),return_ids=True);self.refresh_scans();self.refresh_results()
        if not ids:QMessageBox.information(self,'삭제 취소','이 시험에서 복구할 삭제 내역이 없습니다.')
        else:self.select_restored_scans(ids)

    @guarded
    def scan_answer_edited(self,item):
        if item.column()<5 and item.column()!=2:return
        sid=item.data(Qt.ItemDataRole.UserRole)
        if item.column()==2:
            text=item.text().strip()
            if text not in ('','1','2','3'):
                self.inline_review_saved(sid);raise ValueError('선택과목은 1, 2, 3으로 입력하세요.')
            self.scan_choice_changed(sid,text or None);self.inline_review_saved(sid);self.review_pane.show_choice();return
        q=item.column()-5
        try:
            text=item.text().strip();value=int(text) if text else None
            if self.review_pane.sid!=sid:self.review_pane.show_scan(sid,q)
            self.review_pane.update_answer(q,value)
        except (ValueError,TypeError):
            self.inline_review_saved(sid);raise ValueError('선다형은 1~5, 숫자답안은 0~999로 입력하세요. 빈칸은 무응답입니다.')
        self.inline_review_saved(sid)

    def refresh_score_classes(self,*_):
        old=self.score_class.currentData();aid=self.score_academy.currentData();self.score_class.blockSignals(True);self.score_class.clear();self.score_class.addItem('모든 반 (조회용)',None)
        for c in self.store.classes():
            if aid is None or c['academy_id']==aid:self.score_class.addItem(f"{c['academy']} / {c['name']}",c['id'])
        self.score_class.setCurrentIndex(max(0,self.score_class.findData(old)));self.score_class.blockSignals(False);self.refresh_scans()

    @guarded
    def scoring_student(self):
        dlg=StudentDialog(self.store,parent=self);cid=self.score_class.currentData()
        if cid is not None:dlg.cls.setCurrentIndex(dlg.cls.findData(cid))
        if dlg.exec():self.refresh()

    @guarded
    def import_dialog(self):
        eid=self.score_exam.currentData()
        if not eid:raise ValueError('시험을 먼저 등록하고 선택하세요.')
        self.selected_scoring_context()
        paths,_=QFileDialog.getOpenFileNames(self,'채점할 파일 선택','','OMR 파일 (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)')
        if not paths:return
        from .popups import ask
        if ask(self,'채점 확인','채점을 시작할까요?','grade_mandu.png')!=QMessageBox.StandardButton.Ok:return
        self.start_import(eid,paths)

    def selected_scoring_context(self):
        aid=self.score_academy.currentData();cid=self.score_class.currentData()
        if aid is None and cid is None:raise ValueError('학원과 반을 먼저 선택해 주세요. 모든 학원·모든 반은 기존 답안 조회용입니다.')
        if aid is None:raise ValueError('학원을 먼저 선택해 주세요. 모든 학원은 기존 답안 조회용입니다.')
        if cid is None:raise ValueError('반을 먼저 선택해 주세요. 모든 반은 기존 답안 조회용입니다.')
        if not any(c['id']==cid and c['academy_id']==aid for c in self.store.classes()):raise ValueError('선택한 학원에 속한 반을 다시 선택해 주세요.')
        return aid,cid

    @guarded
    def retry_unrecognized(self):
        self.selected_scoring_context()
        eid=self.score_exam.currentData()
        selected_ids={self.scan_table.item(i.row(),0).data(Qt.ItemDataRole.UserRole) for i in self.scan_table.selectedIndexes()}
        ids=[r['id'] for r in self.store.scans(eid) if r['id'] in selected_ids and r['status'] in ('failed','pending') and r['input_mode']=='scan' and not r['images_purged_at']] if eid else []
        if not ids:raise ValueError('다시 읽을 검수 대기·미인식 행을 선택하세요. Ctrl+A로 전체 선택할 수 있습니다.')
        if QMessageBox.question(self,'선택 답안 재인식',f'선택한 검수 대기·미인식 {len(ids)}장을 다시 읽을까요?\n직접 수정하거나 검수한 문항, 원본과 응시일자는 유지합니다. 확정 성적은 변경하지 않습니다.\n재인식 후 학생·시험을 다시 확인해 주세요.')==QMessageBox.StandardButton.Yes:
            self.start_import(eid,[],retry_ids=ids,reread=True)

    def start_import(self,eid,paths,retry_ids=None,reread=False):
        if self.worker:raise ValueError('현재 파일 처리가 끝난 뒤 다시 시도하세요.')
        aid,cid=self.selected_scoring_context()
        self.import_button.setEnabled(False);self.retry_button.setEnabled(False);self.pages.widget(2).setEnabled(False);self.pages.widget(6).setEnabled(False)
        self.progress=QProgressDialog(BUSY_TEXT,'중단',0,0,self);from .busy import ManduProgressBar;self.progress.setBar(ManduProgressBar(self.progress));self.progress.setWindowTitle('작업 중');self.progress.setWindowModality(Qt.WindowModality.NonModal);self.progress.setMinimumDuration(0);self.progress.setAutoClose(False);self.progress.setMinimumSize(420,205);self.progress.show()
        self.worker=ImportWorker(self.store.path,eid,paths,aid,cid,self.score_sat_on.date().toString('yyyy-MM-dd'),retry_ids,reread);self.progress.canceled.connect(self.worker.requestInterruption);self.worker.result.connect(self.import_done);self.worker.finished.connect(self.worker_finished);self.worker.start()

    def worker_finished(self):
        if self.worker:self.worker.deleteLater();self.worker=None
        self.refresh_scans()

    def import_done(self,result):
        self.progress.close();self.import_button.setEnabled(True);self.pages.widget(2).setEnabled(True);self.pages.widget(6).setEnabled(True);self.refresh()
        text=f"새 답안 {result['added']}장 · 중복 건너뜀 {result['duplicate']}장 · 미인식 {result['failed']}장"
        if result.get('retried'):text+=f"\n기존 답안 {result['retried']}장 재시도 · 인식 성공 {result.get('recovered',0)}장 (원본 검수 필요)"
        if result['duplicate']:text+='\n중복은 이번에 새로 저장하지 않았다는 뜻입니다. 시험·학원·반을 확인해 기존 목록을 보세요.'
        if result['failed']:text+='\n미인식 원본은 보관되어 있습니다. 목록에서 원본 검수 또는 미인식 원본 다시 읽기를 이용하세요.'
        if result['cancelled']:text+='\n중단되었습니다. 이미 처리한 답안은 저장되어 있습니다.'
        if result.get('outside_class'):text+=f"\n선택한 학원·반 외 학생 {result['outside_class']}명: 원본 검수에서 학생을 연결해 주세요."
        if result['errors']:text+='\n\n'+'\n'.join(result['errors'])
        from .popup_style import result_message
        result_message(self,'파일 처리 결과',text,partial=bool(result['failed'] or result['cancelled'] or result['errors'] or result.get('outside_class')))

    @guarded
    def open_review(self):
        self.review_answer(selected(self.scan_table))

    def review_answer(self,sid):
        row=self.store.scan(sid)
        if row['input_mode']=='manual':self.manual.open_student(row['exam_id'],row['student_id']);self.nav.setCurrentRow(4)
        else:ReviewDialog(self.store,sid,self).exec();self.refresh()

    @guarded
    def reopen(self):
        sid=selected(self.scan_table)
        if self.store.scan(sid)['input_mode']=='manual':self.review_answer(sid);return
        if QMessageBox.question(self,'검수 재개','다시 검수할까요?\n확정 성적은 검수를 마칠 때까지 평균·성적표에서 제외됩니다.')==QMessageBox.StandardButton.Yes:
            self.store.set_status(sid,'pending');self.refresh_scans();self.refresh_results()

    @guarded
    def exclude(self):
        sid=selected(self.scan_table)
        if QMessageBox.question(self,'집계 제외','이 답안을 평균에서 제외하고 보관할까요? 원본은 유지되며 검수를 다시 열 수 있습니다.')==QMessageBox.StandardButton.Yes:self.store.set_status(sid,'excluded');self.refresh()

    def make_results(self):
        w,v=page('성적표 · 석차 조회','행을 두 번 클릭하면 성적표가 열립니다. Ctrl+A로 현재 조회 결과 전체를 체크할 수 있습니다.');self.pages.addWidget(w)
        h=QHBoxLayout();v.addLayout(h);self.result_search=QLineEdit();self.result_search.setPlaceholderText('학생명 · 학생번호 뒤 4자리 검색');self.result_exam=QComboBox();self.result_choice=QComboBox();self.result_choice.addItem('모든 선택과목',None)
        for key,name in ELECTIVES.items():self.result_choice.addItem(name,key)
        h.addWidget(self.result_search,1);h.addWidget(self.result_exam,2);self.result_choice.setParent(w);self.result_choice.hide()
        h=QHBoxLayout();v.addLayout(h);self.result_academy=QComboBox();self.result_class=QComboBox();h.addWidget(label('학원'));h.addWidget(self.result_academy,1);h.addWidget(label('반'));h.addWidget(self.result_class,1);h.addWidget(button('이전 성적 조회',self.show_history))
        self.result_search.textChanged.connect(self.refresh_results);self.result_exam.currentIndexChanged.connect(self.refresh_results);self.result_class.currentIndexChanged.connect(self.refresh_results);self.result_choice.currentIndexChanged.connect(self.refresh_results);self.result_academy.currentIndexChanged.connect(self.refresh_result_classes)
        self.result_summary=label('','Sub');v.addWidget(self.result_summary)
        from .tableui import CheckTable
        self.result_table=CheckTable(['선택','학생명','학원','반','시험명','선택과목','응시일자','점수 / 만점','등급','추정 백분위','반 평균','시험 평균'],[62,100,110,120,240,110,105,95,65,90,85,85]);self.result_table.setSortingEnabled(True);self.result_table.sortItems(1,Qt.SortOrder.AscendingOrder)
        self.result_table.horizontalHeaderItem(5).setText('선택과목 ▾')
        self.result_table.horizontalHeader().sectionClicked.connect(self.choose_result_elective)
        self.result_table.checksChanged.connect(self.update_selected_count);self.selection_count=label('선택 0건','Sub');v.addWidget(self.result_table,1);self.result_table.cellDoubleClicked.connect(lambda row,col:self.preview_report(row) if col!=0 else None)
        h=QHBoxLayout();v.addLayout(h);h.addWidget(button('성적표 다운로드',self.checked_reports,True));h.addWidget(self.selection_count);h.addWidget(button('석차 엑셀',self.batch_report));h.addWidget(button('CSV 내보내기',self.export_csv));h.addStretch()

    def choose_result_elective(self,col):
        if col!=5:return
        from PySide6.QtWidgets import QMenu
        menu=QMenu(self)
        for i in range(self.result_choice.count()):
            action=menu.addAction(self.result_choice.itemText(i));action.setCheckable(True);action.setChecked(i==self.result_choice.currentIndex())
            action.triggered.connect(lambda checked=False,index=i:self.result_choice.setCurrentIndex(index))
        header=self.result_table.horizontalHeader()
        menu.exec(header.mapToGlobal(header.rect().bottomLeft())+__import__('PySide6.QtCore',fromlist=['QPoint']).QPoint(header.sectionViewportPosition(5),0))
        value=self.result_choice.currentText() if self.result_choice.currentData() else '선택과목'
        self.result_table.horizontalHeaderItem(5).setText(value+' ▾')

    def update_selected_count(self):
        self.selection_count.setText(f'선택 {len(self.result_table.checked_ids())}건')

    def show_history(self):
        from .historyui import HistoryDialog
        HistoryDialog(self.store,self).exec()

    def refresh_result_classes(self,*_):
        self.fill_classes(self.result_class,self.result_academy.currentData());self.refresh_results()

    def filtered_results(self):
        query=self.result_search.text().strip().lower();eid=self.result_exam.currentData();cid=self.result_class.currentData();aid=self.result_academy.currentData();choice=self.result_choice.currentData()
        academy=self.result_academy.currentText() if aid is not None else None
        return [r for r in self.store.results(eid) if (not query or query in r['snapshot'].get('name','').lower() or query in r['snapshot'].get('code','')) and (cid is None or r['snapshot'].get('class_id')==cid) and (academy is None or r['snapshot'].get('academy')==academy) and (choice is None or r['elective']==choice)]

    def refresh_results(self,*_):
        self.results_dirty=False
        rows=self.filtered_results();display=[];cache={}
        for r in rows:
            s=r['snapshot'];eid=r['exam_id'];cid=s['class_id']
            for key in [(eid,None),(eid,cid)]:
                if key not in cache:cache[key]=self.store.averages(*key)[0]
            avg=cache[eid,None];ca=cache[eid,cid]
            values=[s['name'],s['academy'],s['classroom'],r['title'],ELECTIVES.get(r['elective'],r['subject']),r['day'],f"{r['score']/100:g} / {r['maximum']/100:g}",r['grade'] or '미설정',percentile_label(r),f'{ca:.2f}',f'{avg:.2f}']
            keys=values.copy();keys[4]=int(r['elective'] or 0);keys[6]=r['score'];keys[7]=r['grade'] if isinstance(r['grade'],int) else 9;keys[8]=r['estimated_percentile'] if r['estimated_percentile'] is not None else -1;keys[9]=ca;keys[10]=avg
            display.append((r['id'],values,keys))
        self.result_table.fill(display)
        self.update_selected_count()
        note=f'조회 결과 {len(rows)}건 · 제목을 클릭하면 오름차순/내림차순 정렬'
        eid=self.result_exam.currentData();aid=self.result_academy.currentData()
        if eid:
            avg,_=self.store.averages(eid)
            if avg is not None:note+=f' · 전체 학원 시험 평균 {avg:.2f}점'
            if aid is not None:
                avg,_=self.store.averages(eid,academy_id=aid)
                if avg is not None:note+=f' · 선택 학원 평균 {avg:.2f}점'
        self.result_summary.setText(note)

    @guarded
    def preview_report(self,row):
        from .preview_cache import preview_pdf
        sid=self.result_table.item(row,0).data(Qt.ItemDataRole.UserRole)
        path=run_store_task(self,self.store,lambda db:preview_pdf(db,sid),readonly=True);QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    @guarded
    def checked_reports(self):
        ids=self.result_table.checked_ids()
        if not ids:raise ValueError('다운로드할 학생을 체크하세요. Ctrl+A로 현재 목록 전체를 체크할 수 있습니다.')
        self.save_report(ids)

    @guarded
    def result_review(self):
        self.preview_report(self.result_table.currentRow())

    def save_report(self,ids):
        if not ids:raise ValueError('출력할 확정 성적이 없습니다.')
        from .export_names import export_name
        rows=[r for r in self.store.results() if r['id'] in ids]
        path,_=QFileDialog.getSaveFileName(self,'A4 성적표 PDF 저장',export_name(rows),'PDF (*.pdf)')
        if path:
            run_store_task(self,self.store,lambda db:report_pdf(path,db,ids),readonly=True)
            with self.store.transaction():self.store.log('report_exported',None,{'scan_ids':ids,'file':Path(path).name})
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @guarded
    def one_report(self):self.save_report([selected(self.result_table)])
    @guarded
    def batch_report(self):
        from .batchui import BatchOutputDialog
        BatchOutputDialog(self.store,self.result_exam.currentData(),self,academy_id=self.result_academy.currentData(),class_id=self.result_class.currentData()).exec()

    @guarded
    def export_csv(self):
        rows=self.filtered_results()
        if not rows:raise ValueError('내보낼 성적이 없습니다.')
        path,_=QFileDialog.getSaveFileName(self,'성적 CSV','성적.csv','CSV (*.csv)')
        if not path:return
        def safe(value):
            s=str(value)
            return "'"+s if s[:1] in ('=','+','-','@','\t','\r') else s
        def write_csv(db):
            with open(path,'w',encoding='utf-8-sig',newline='') as f:
                writer=csv.writer(f);writer.writerow(['학생번호','학생명','학원','반','시험명','시리즈','과목','회차','응시일자','점수','만점','시험평균','반평균','오답','정답버전','선택과목','등급','추정백분위(등급컷환산)'])
                for r in rows:
                    s=r['snapshot'];avg,_=db.averages(r['exam_id']);ca,_=db.averages(r['exam_id'],s['class_id']);writer.writerow([safe(v) for v in [s['code'],s['name'],s['academy'],s['classroom'],r['title'],r['series'],r['subject'],r['round'],r['day'],r['score']/100,r['maximum']/100,round(avg,2),round(ca,2),' '.join(map(str,r['wrong'])),r['key_revision'],ELECTIVES.get(r['elective'],''),r['grade'] or '',r['estimated_percentile'] if r['estimated_percentile'] is not None else ('40 미만' if len(r['cuts'])==5 else '')]])
        run_store_task(self,self.store,write_csv,readonly=True)
        QMessageBox.information(self,'저장 완료','조회 결과를 CSV로 저장했습니다.')

    def make_settings(self):
        w,v=page('설정','성적표와 자료 관리 옵션을 한곳에서 설정하세요.');self.pages.addWidget(w)
        self.settings_tabs=QTabWidget();v.addWidget(self.settings_tabs,1)
        report=QWidget();rv=QVBoxLayout(report);rv.setContentsMargins(16,16,16,16);rv.setSpacing(14)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame);scroll.setWidget(report);self.settings_tabs.addTab(scroll,'성적표 설정')
        base=QFrame();base.setObjectName('Surface');base.setFixedHeight(190);base_row=QHBoxLayout(base);base_row.setContentsMargins(20,16,20,16);base_row.setSpacing(24)
        fields=QVBoxLayout();fields.setSpacing(8);heading=label('성적표 기본 정보');heading.setStyleSheet('font-size:20px;font-weight:700;');fields.addWidget(heading);fields.addWidget(label('강사 · 연구실명'))
        row=QHBoxLayout();self.report_brand=QLineEdit(self.store.report_name());self.report_brand.setPlaceholderText('연구실명을 입력하세요');self.report_brand.setMaxLength(60);self.report_brand.setMaximumWidth(380);row.addWidget(self.report_brand,1);save_brand=button('저장',self.save_report_name,True);save_brand.setFixedSize(110,34);row.addWidget(save_brand);fields.addLayout(row);fields.addWidget(label('성적표 오른쪽 위에 표시됩니다.','Sub'));base_row.addLayout(fields,3)
        from .settings_cards import CheerPanel,ReportBrandPreview
        self.report_brand_preview=ReportBrandPreview();self.report_brand_preview.set_brand(self.report_brand.text());self.report_brand.textChanged.connect(self.report_brand_preview.set_brand);base_row.addWidget(self.report_brand_preview,2);rv.addWidget(base)
        self.cheer_panel=CheerPanel(self.store,self);rv.addWidget(self.cheer_panel)
        rv.addWidget(label('이미지는 사용 권한과 저작권을 확인해 주세요.\n변경한 설정은 새로 만드는 성적표에 반영됩니다.','Sub'));rv.addStretch()
        data=QWidget();dv=QVBoxLayout(data);dv.setContentsMargins(18,16,18,16);dv.setSpacing(16);self.settings_tabs.addTab(data,'자료 관리')
        for title,description,action in [('이전 백업 조회','현재 자료를 바꾸지 않고 이전 학생과 성적을 읽기 전용으로 확인해요.',self.view_old_backup),('저장 용량 줄이기','불필요한 OMR 이미지와 미리보기 파일을 정리해요. 답안과 성적은 유지됩니다.',self.clean_storage),('OMR 양식 다운로드','인쇄할 기본 OMR 양식을 저장해요.',self.blank_form)]:
            group=QGroupBox(title);row=QHBoxLayout(group);row.addWidget(label(description,'Sub'),1);row.addWidget(button(title,action));dv.addWidget(group)
        options=QGroupBox('백업 옵션');ov=QVBoxLayout(options)
        self.handoff_reminder=QCheckBox('수정 후 종료할 때 백업 안내');self.handoff_reminder.setChecked(self.handoff.state['remind']);ov.addWidget(self.handoff_reminder);self.handoff_reminder.toggled.connect(self.save_handoff_preferences);dv.addWidget(options);dv.addStretch()
        self.handoff_label=QLabel(self);self.handoff_label.hide()
        help_text=QTextEdit();help_text.setReadOnly(True);help_text.setPlainText('기존 맥가이와 비슷한 흐름으로 사용할 수 있어요.\n\n1. 작업 시작: 홈에서 백업을 가져오세요. 직전 수업까지 반영된 파일인지 저장 시각을 확인해 주세요.\n2. 시험과 학원·반을 선택하고 PDF 또는 이미지를 불러오세요.\n3. 신규생은 채점 화면의 신규생 등록에서 추가할 수 있어요.\n4. OMR은 Ctrl + 마우스 휠로 확대·축소해요.\n5. 오답과 학생 연결을 확인하고 성적을 확정하면 성적표 · 석차 조회에서 출력할 수 있어요.\n6. 작업 마침: 홈에서 새 백업을 저장하세요. 연결된 구글드라이브에 자동 업로드됩니다. 완료 상태를 확인한 뒤 종료하세요.\n\n이미지 정리 시 답안과 성적은 유지되지만, 정리한 원본을 다시 확인하거나 재인식하려면 정리 전 백업이 필요해요.\n\n기능은 업데이트될 수 있어요. 불편한 점이 있으면 알려 주세요.');self.settings_tabs.addTab(help_text,'사용 안내')

    @guarded
    def view_old_backup(self):
        from .archiveui import open_archive
        path,_=QFileDialog.getOpenFileName(self,'이전 백업 조회 · 읽기 전용','','OMR 백업 (*.omrbackup)')
        if path:open_archive(self,path)

    @guarded
    def clean_storage(self):
        if self.worker:raise ValueError('파일 처리가 끝난 뒤 이미지를 정리하세요.')
        from .storageui import StorageDialog
        StorageDialog(self.store,self).exec()
        self.review_pane.sid=None;self.refresh_scans()

    def edit_cheer(self):
        from .cheerui import CheerDialog
        CheerDialog(self.store,self).exec()

    @guarded
    def save_report_name(self):
        self.store.set_report_name(self.report_brand.text());QMessageBox.information(self,'저장 완료','새 성적표의 오른쪽 상단에 반영됩니다. 학생 소속 학원은 바뀌지 않습니다. 이미 만든 PDF는 다시 출력하세요.')

    @guarded
    def backup(self,skip_manual=False,other_location=False):
        if self.worker:raise ValueError('현재 작업이 끝난 뒤 백업해 주세요.')
        if not skip_manual and not self.check_manual_before_backup():return False
        if self.review_pane.answer_edited() is False:return False
        from .backupui import BackupNameDialog
        names=BackupNameDialog(self.store,self.handoff.state,self)
        if names.exec()!=QDialog.DialogCode.Accepted:return False
        academy,classroom=names.names()
        self.handoff.state.update(backup_academy=academy,backup_classroom=classroom)
        self.save_handoff_preferences()
        filename=self.handoff.filename(academy,classroom)
        if other_location:
            path,_=QFileDialog.getSaveFileName(self,'현재 PC → 새 백업 파일 저장',filename,'OMR 백업 (*.omrbackup)',options=QFileDialog.Option.DontConfirmOverwrite)
            if not path:return False
        else:
            directory=self.store.path.parent/'backups'/'automatic';directory.mkdir(parents=True,exist_ok=True)
            candidate=directory/filename;number=2
            while candidate.exists():
                candidate=directory/(Path(filename).stem+'_'+str(number)+'.omrbackup');number+=1
            path=str(candidate)
        saved=run_store_task(self,self.store,lambda db:db.backup(path),readonly=True);self.handoff.recorded('outgoing',saved);self.refresh_handoff()
        if not other_location:
            if not self.drive.enqueue(saved):
                self.drive.status='PC 백업 완료 · 드라이브 업로드를 위해 연결 설정을 눌러 주세요.';self.drive.render()
            return True
        box=QMessageBox(self);box.setWindowTitle('백업 파일 저장 완료');box.setTextFormat(Qt.TextFormat.PlainText);box.setText('PC에 백업했어요.\n구글드라이브에 업로드 중이에요.' if self.drive.enqueue(saved) else 'PC에 백업했어요.\n구글드라이브 연결 후 자동 업로드를 사용할 수 있어요.')
        open_button=box.addButton('저장한 파일 위치 열기',QMessageBox.ButtonRole.ActionRole);box.addButton('확인',QMessageBox.ButtonRole.AcceptRole);box.exec()
        if box.clickedButton()==open_button:
            import subprocess
            if os.name=='nt':subprocess.Popen(['explorer.exe','/select,',str(saved)])
            else:QDesktopServices.openUrl(QUrl.fromLocalFile(str(saved.parent)))
        return True

    def check_manual_before_backup(self):
        if not self.manual.has_unsaved():return True
        self.manual.stash();count=len(self.manual.cache);students=len({key[1] for key in self.manual.cache})
        box=QMessageBox(self);box.setWindowTitle('저장하지 않은 수기 답안');box.setText(f'저장하지 않은 수기 답안이 {students}명 · {count}건 있어요.\n수기 채점에서 저장한 뒤 백업해 주세요.')
        move=box.addButton('수기 채점으로 이동',QMessageBox.ButtonRole.AcceptRole);box.addButton('취소',QMessageBox.ButtonRole.RejectRole);box.exec()
        if box.clickedButton()==move:
            self.pages.setCurrentIndex(4);self.nav.blockSignals(True);self.nav.setCurrentRow(4);self.nav.blockSignals(False)
        return False

    @guarded
    def save_handoff_preferences(self,*args):
        self.handoff.state.update(remind=self.handoff_reminder.isChecked());self.handoff.save()

    def refresh_handoff(self):
        self.handoff_label.setText(self.handoff.summary())
        self.home_handoff.setText('아직 백업하지 않은 변경사항이 있어요.' if self.handoff.needs_backup() else '현재 PC 자료는 백업에 저장되어 있어요.' if self.handoff.state.get('outgoing') or self.handoff.state.get('incoming') else '아직 백업 저장 기록이 없어요.')

    @guarded
    def restore(self,path=None):
        if self.worker:raise ValueError('현재 작업이 끝난 뒤 백업을 가져와 주세요.')
        from_drive=isinstance(path,(str,Path))
        if not from_drive:path,_=QFileDialog.getOpenFileName(self,'가져올 백업 선택','','OMR 백업 (*.omrbackup)')
        if not path:return False
        from .backup_tools import inspect_backup,counts,comparison
        incoming=run_store_task(self,self.store,lambda db:inspect_backup(path),readonly=True)
        box=QMessageBox(self);box.setWindowTitle('가져올 백업 확인');box.setTextFormat(Qt.TextFormat.PlainText);box.setText(comparison(counts(self.store.db),incoming))
        box.setStandardButtons(QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel);box.button(QMessageBox.StandardButton.Yes).setText('백업 가져오기');box.button(QMessageBox.StandardButton.Cancel).setText('취소');box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec()!=QMessageBox.StandardButton.Yes:return False
        if self.manual.has_unsaved() and QMessageBox.question(self,'수기 입력 변경','저장하지 않은 수기 답안을 버리고 백업을 가져올까요?')!=QMessageBox.StandardButton.Yes:return False
        if self.review_pane.answer_edited() is False:return False
        if from_drive and self.handoff.needs_backup():raise ValueError('현재 변경사항을 먼저 백업해 주세요.')
        safety=run_store_task(self,self.store,lambda db:db.restore(path))
        self.handoff.recorded('incoming',Path(path));self.startup_backup_ready=True;self.refresh_handoff();self.manual.discard_all();self.report_brand.setText(self.store.report_name());self.cheer_panel.reload()
        self.score_exam.blockSignals(True);self.score_exam.setCurrentIndex(0);self.score_exam.blockSignals(False);self.scan_status_filter=None;self.review_pane.undo_history.clear();self.review_pane.clear();self.refresh()
        QMessageBox.information(self,'가져오기 완료','백업을 가져왔습니다.');return True

    def refresh(self):
        self.fill_academies(self.student_academy);self.refresh_student_classes()
        exams=self.store.exams();display=[]
        for i,e in enumerate(exams,1):
            modified=datetime.fromisoformat(e['updated_at']).astimezone().strftime('%Y-%m-%d %H:%M') if e['updated_at'] else '기록 없음'
            values=[i,e['title'],e['day'],len(json.loads(e['key_json'])),f"{sum(json.loads(e['points_json']))/100:g}",e['revision'],modified]
            display.append((e['id'],values,[i,e['title'],e['day'],values[3],sum(json.loads(e['points_json'])),e['revision'],modified]))
        self.exam_table.fill(display)
        for combo,all_title in [(self.score_exam,None),(self.result_exam,'모든 시험')]:
            old=combo.currentData();combo.blockSignals(True);combo.clear()
            combo.addItem(all_title or '시험을 선택해 주세요',None)
            for e in exams:
                if combo is self.score_exam and not json.loads(e['config']).get('metadata',{}).get('active',True):continue
                combo.addItem(e['title'],e['id'])
            combo.setCurrentIndex(max(0,combo.findData(old)));combo.blockSignals(False)
        self.fill_academies(self.result_academy);self.fill_classes(self.result_class,self.result_academy.currentData())
        old=self.score_academy.currentData();self.score_academy.blockSignals(True);self.score_academy.clear();self.score_academy.addItem('모든 학원 (조회용)',None)
        for a in self.store.rows('SELECT * FROM academies ORDER BY name'):self.score_academy.addItem(a['name'],a['id'])
        self.score_academy.setCurrentIndex(max(0,self.score_academy.findData(old)));self.score_academy.blockSignals(False);self.refresh_score_classes()
        self.refresh_scans();self.refresh_results()
        self.manual.refresh()
        counts=[len(self.store.students()),len(exams),self.store.db.execute("SELECT COUNT(*) FROM scans WHERE status IN ('pending','failed') AND exam_id IN (SELECT id FROM exams WHERE archived=0)").fetchone()[0]]
        self.set_home_counts(counts)

    def closeEvent(self,event):
        if hasattr(self,'drive') and self.drive.busy:
            QMessageBox.information(self,'드라이브 작업 중','드라이브 작업이 끝난 뒤 종료해 주세요. PC 백업은 저장되어 있습니다.');event.ignore();return
        if getattr(self,'_busy_operation',False):event.ignore();return
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self,'채점 진행 중','파일 처리를 중단하거나 완료한 뒤 종료하세요.');event.ignore();return
        discard_manual=self.manual.has_unsaved()
        if discard_manual and QMessageBox.question(self,'저장하지 않은 수기 답안','저장하지 않은 수기 답안을 버리고 종료할까요?')!=QMessageBox.StandardButton.Yes:event.ignore();return
        if self.review_pane.answer_edited() is False:event.ignore();return
        if self.handoff.state.get('remind',True) and self.handoff.needs_backup():
            from .popups import ask
            choice=ask(self,'작업 마침 · 백업 확인','아직 백업하지 않은 변경사항이 있어요.\n백업을 저장하고 종료할까요?','exit_mandu.png',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Yes,{QMessageBox.StandardButton.Yes:'백업 저장 후 종료',QMessageBox.StandardButton.No:'백업 없이 종료',QMessageBox.StandardButton.Cancel:'취소'})
            if choice!=QMessageBox.StandardButton.No and (choice!=QMessageBox.StandardButton.Yes or not self.backup(skip_manual=discard_manual)):event.ignore();return

        if hasattr(self,'drive') and self.drive.busy:event.ignore();return
        try:self.handoff.save()
        except OSError as exc:QMessageBox.warning(self,'백업 안내 설정 저장 실패',str(exc));event.ignore();return
        self.store.close();event.accept()
