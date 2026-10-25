"""Inline scan review and keyboard-editable answer grid."""
import json
from copy import deepcopy
from collections import deque
from PySide6.QtCore import Qt,Signal,QDate,QEvent,QTimer
from PySide6.QtGui import QColor,QIntValidator,QFont,QFontInfo,QKeySequence
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,QCheckBox,QDateEdit,QLineEdit,QPushButton,QSplitter,QMessageBox,QTableWidget,QStyledItemDelegate,QAbstractItemDelegate,QAbstractItemView,QHeaderView,QCompleter,QStyleOptionViewItem,QStyle)
from .examdata import effective,numeric,ELECTIVES

ANSWER_START=5
ANSWER_ROLE=Qt.ItemDataRole.UserRole+1


class AnswerDelegate(QStyledItemDelegate):
    def paint(self,painter,option,index):
        if index.column()<ANSWER_START:return super().paint(painter,option,index)
        opt=QStyleOptionViewItem(option);self.initStyleOption(opt,index);text=str(index.data(Qt.ItemDataRole.DisplayRole) or '').splitlines()[0];opt.text=''
        background=index.data(Qt.ItemDataRole.BackgroundRole)
        color=QColor('#ECE3F8') if opt.state & QStyle.StateFlag.State_Selected else background.color() if background else QColor('#FBFAFD' if index.row()%2 else '#FFFFFF')
        painter.fillRect(option.rect,color)
        painter.save();painter.setPen(opt.palette.highlightedText().color() if opt.state & QStyle.StateFlag.State_Selected else index.data(Qt.ItemDataRole.ForegroundRole).color())
        rect=option.rect.adjusted(1,1,-1,-1);font=QFont(opt.font);painter.setFont(font)
        wrong=index.data(Qt.ItemDataRole.UserRole+3)=='X'
        if wrong:
            painter.drawText(rect.adjusted(0,0,0,-10),Qt.AlignmentFlag.AlignCenter,text)
            font.setPixelSize(max(8,round(QFontInfo(font).pixelSize()*.7)));painter.setFont(font)
            painter.drawText(rect.adjusted(0,rect.height()-15,0,0),Qt.AlignmentFlag.AlignCenter,'×')
        else:painter.drawText(rect,Qt.AlignmentFlag.AlignCenter,text)
        painter.restore()

    def createEditor(self,parent,option,index):
        if index.column()<ANSWER_START and index.column()!=2:return None
        editor=QLineEdit(parent);editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        is_numeric=bool(index.data(Qt.ItemDataRole.UserRole+2))
        editor.setValidator(QIntValidator(1 if index.column()==2 else 0 if is_numeric else 1,3 if index.column()==2 else 999 if is_numeric else 5,editor))
        if index.column()==2:editor.setMaxLength(1)
        editor.setProperty('grid_row',index.row());editor.setProperty('grid_col',index.column())
        return editor

    def setEditorData(self,editor,index):
        value=index.data(ANSWER_ROLE);editor.setText('' if value is None or value<0 else str(value));editor.selectAll()

    def setModelData(self,editor,model,index):
        if not editor.text().strip() or editor.hasAcceptableInput():model.setData(index,editor.text().strip(),Qt.ItemDataRole.EditRole)

    def eventFilter(self,editor,event):
        if event.type()==QEvent.Type.KeyPress:
            key=event.key();moves={Qt.Key.Key_Up:(-1,0),Qt.Key.Key_Down:(1,0),Qt.Key.Key_Left:(0,-1),Qt.Key.Key_Right:(0,1),Qt.Key.Key_Return:(1,0),Qt.Key.Key_Enter:(1,0),Qt.Key.Key_Tab:(0,1),Qt.Key.Key_Backtab:(0,-1)}
            if key in moves:
                if editor.text().strip() and not editor.hasAcceptableInput():return True
                row,col=editor.property('grid_row'),editor.property('grid_col');dr,dc=moves[key]
                self.commitData.emit(editor);self.closeEditor.emit(editor,QAbstractItemDelegate.EndEditHint.NoHint)
                grid=self.parent()
                QTimer.singleShot(0,lambda:grid.setCurrentCell(max(0,min(grid.rowCount()-1,row+dr)),max(0,min(grid.columnCount()-1,col+dc))))
                return True
        return super().eventFilter(editor,event)


class AnswerTable(QTableWidget):
    def __init__(self):
        super().__init__();self.setItemDelegate(AnswerDelegate(self))
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems);self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked|QAbstractItemView.EditTrigger.AnyKeyPressed|QAbstractItemView.EditTrigger.EditKeyPressed)
        self.verticalHeader().setVisible(False);self.verticalHeader().setDefaultSectionSize(40)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive);self.setAlternatingRowColors(True)

    def keyPressEvent(self,event):
        if event.matches(QKeySequence.StandardKey.Undo):
            pane=getattr(self.window(),'review_pane',None)
            if pane:pane.undo_answer()
            return
        item=self.currentItem()
        if event.key() in (Qt.Key.Key_Delete,Qt.Key.Key_Backspace) and item and (self.currentColumn()==2 or self.currentColumn()>=ANSWER_START) and item.flags()&Qt.ItemFlag.ItemIsEditable:
            item.setText('');return
        super().keyPressEvent(event)


class ReviewPane(QWidget):
    saved=Signal(int)
    question_selected=Signal(int)
    next_student_requested=Signal()

    def __init__(self,store,parent=None):
        super().__init__(parent)
        from .ui import ImageView,button,label
        self.store=store;self.sid=None;self.q=0;self.loading=False;self.data=None;self.undo_history=deque(maxlen=50)
        outer=QVBoxLayout(self);outer.setContentsMargins(0,0,0,0);outer.setSpacing(5)
        top=QHBoxLayout();outer.addLayout(top)
        self.student=QComboBox();self.student.setEditable(True);self.student.setInsertPolicy(QComboBox.InsertPolicy.NoInsert);self.student.setMinimumWidth(230);top.addWidget(self.student,1)
        self.makeup_button=button('보강생 연결',self.link_makeup);top.addWidget(self.makeup_button)
        self.day=QDateEdit();self.day.setCalendarPopup(True);self.day.setDisplayFormat('yyyy-MM-dd');top.addWidget(self.day)
        actions=QVBoxLayout();top.addLayout(actions)
        self.confirm_button=button('성적 확정',self.confirm,True);actions.addWidget(self.confirm_button)
        self.next_student_button=button('다음 학생',lambda:self.next_student_requested.emit());actions.addWidget(self.next_student_button)
        self.identity_notice=label('','Sub');self.identity_notice.hide()
        split=QSplitter();outer.addWidget(split,1)
        left=QWidget();lv=QVBoxLayout(left);lv.setContentsMargins(0,0,5,0);lv.setSpacing(3)
        self.original=QCheckBox(self);self.original.hide()
        self.view=ImageView();self.image_tools=[]
        self.image_notice=label('','Sub');lv.addWidget(self.image_notice)
        lv.addWidget(self.view,1);split.addWidget(left)
        right=QWidget();right.setMinimumWidth(280);right.setMaximumWidth(350);rv=QVBoxLayout(right);rv.setContentsMargins(8,0,0,0);rv.setSpacing(5)
        self.heading=label('위 표에서 학생과 문항을 선택하세요');self.heading.setStyleSheet('font-size:16px;font-weight:bold;');rv.addWidget(self.heading)
        self.verdict=label('');self.verdict.hide()
        self.answer_label=label('학생 답안');rv.addWidget(self.answer_label)
        answer_row=QHBoxLayout();rv.addLayout(answer_row);self.answer=QLineEdit();self.answer.setMaximumWidth(110);self.answer.setPlaceholderText('빈칸: 무응답');answer_row.addWidget(self.answer)
        self.reading=label('','Sub');answer_row.addWidget(self.reading,1)
        rv.addWidget(label('방향키 이동 / 숫자 입력 / Delete: 답안 비우기','Sub'))
        nav=QHBoxLayout();rv.addLayout(nav);nav.addWidget(button('이전 오답',lambda:self.next_question(-1)));nav.addWidget(button('다음 오답',lambda:self.next_question()))
        self.undo_button=button('답안 수정 되돌리기',self.undo_answer);self.undo_button.setToolTip('최근 수정 50회 · Ctrl+Z · 되돌린 뒤 성적을 다시 확정해 주세요.');rv.addWidget(self.undo_button);self.status=label('','Sub');rv.addWidget(self.status);rv.addStretch()
        split.addWidget(right);split.setSizes([760,310])
        self.student.activated.connect(self.metadata_changed);self.day.dateChanged.connect(self.metadata_changed)
        self.answer.editingFinished.connect(self.answer_edited);self.original.toggled.connect(self.load_image)
        self.setEnabled(False)

    def show_scan(self,sid,q=0):
        same=self.sid==sid;old_normal=self.data['normalized'] if self.data and same else None
        self.loading=True;self.sid=sid;self.data=self.store.scan(sid);self.base=self.store.exam(self.data['exam_id']);self.exam=effective(self.base,self.data['elective'])
        self.q=max(0,min(q,len(self.exam['key'])-1));self.readonly=self.data['status']=='deleted' or self.data['input_mode']=='manual'
        self.student.clear();self.student.addItem('',None)
        self.student.lineEdit().setPlaceholderText('학생을 검색해 연결하세요')
        self.student.completer().setFilterMode(Qt.MatchFlag.MatchContains)
        self.student.completer().setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.student.completer().setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        context=self.data['import_context'];cid=context.get('class_id');aid=context.get('academy_id')
        if cid is None and hasattr(self.window(),'score_class'):
            cid=self.window().score_class.currentData();aid=self.window().score_academy.currentData()
        roster=[s for s in self.store.students() if (s['active'] and cid is not None and self.store.in_class(s['id'],cid,aid)) or s['id']==self.data['student_id']]
        for s in roster:self.student.addItem(f"{s['name']} · {s['code'][-5:]} · {s['academy']} / {s['classroom']}",s['id'])
        self.student.setCurrentIndex(max(0,self.student.findData(self.data['student_id'])))
        self.day.setDate(QDate.fromString(self.data['sat_on'],'yyyy-MM-dd'))
        self.setEnabled(True)
        for widget in (self.student,self.day,self.answer,self.confirm_button,self.makeup_button):widget.setEnabled(not self.readonly)
        self.loading=False
        if not same or old_normal!=self.data['normalized']:self.load_image();QTimer.singleShot(0,self.view.fit)
        self.show_question(self.q)

    def clear(self):
        self.sid=None;self.data=None;self.setEnabled(False);self.heading.setText('위 표에서 학생과 문항을 선택하세요');self.verdict.clear();self.reading.clear();self.identity_notice.clear();self.status.clear();self.answer.clear();self.view.scene_.clear();self.view.highlight=None

    def show_question(self,q):
        if not self.sid:return
        self.q=q;self.loading=True;self.choice_mode=False;self.answer.setMaxLength(3)
        a=self.data['answers'][q];k=self.exam['key'][q];known=not(self.base['config'].get('form')=='math30' and q>=22 and not self.data['elective']) and k is not None
        self.heading.setText(f"{q+1}번 <span style='color:#C6C1CC'>│</span> 정답 {k if known else '확인 필요'}")
        answer='무응답' if a is None else '무효' if a<0 else str(a)
        self.verdict.setText(f"정답 {k}" if known else '정답 확인 필요')
        self.answer_label.setText('학생 답안 <span style="color:#C6C1CC">│</span> '+('정답 '+str(k) if a==k else '오답') if known else '학생 답안')
        self.answer.setStyleSheet('background:#FDECE8;border:1px solid #C95348;color:#A43530;' if known and a!=k else '')
        self.answer.setValidator(QIntValidator(0 if numeric(self.base,q+1) else 1,999 if numeric(self.base,q+1) else 5,self.answer));self.answer.setText('' if a is None else str(a))
        from .ui import FLAGS
        identity=self.data['import_context'].get('identity_reading',{})
        method={'phone_name':'뒷번호 + 이름으로 연결','unique_phone':'반 내 뒷번호 일치','explicit_code':'학생번호로 연결','unique_name':'반 내 이름 일치'}.get(identity.get('method'),'학생 확인 필요')
        if self.data['import_context'].get('manual_link'):method='직접 연결됨'
        parts=[f"인식 번호 {identity.get('phone_tail') or '미확인'} · 이름 {identity.get('name',{}).get('name') or '미확인'} · {method}"] if identity else []
        notice=self.data['import_context'].get('notice') or identity.get('notice')
        if notice and not self.data['student_id']:parts.append(notice)
        if self.data['import_context'].get('makeup_student_id')==self.data['student_id'] and self.data['student_id']:
            s=self.data['snapshot'];parts.append(f"보강 연결 · 성적 소속: {s.get('academy','')} / {s.get('classroom','')} (원래 소속)")
        from .identity import name_advisory
        advisory=name_advisory(self.data['import_context'],self.store.student(self.data['student_id'])['name']) if self.data['student_id'] else ''
        if advisory:parts.append(advisory+' · 원본 이름을 확인해 주세요. 성적 확정은 가능합니다.')
        self.student.setToolTip('\n'.join(parts));self.identity_notice.hide()
        flag=self.data['reading'][q]['flag'];self.reading.setText('인식: '+FLAGS.get(flag,'확인 필요'));self.reading.setStyleSheet('color:#9D533E;font-weight:600;' if flag not in ('clear','manual') else 'color:#746E81;')
        instruction='수기 채점 탭에서 수정하세요.' if self.data['input_mode']=='manual' else '수정하면 검수 대기로 바뀝니다. 수정 후 성적을 확정하세요.' if self.data['status'] in ('confirmed','superseded','excluded') else '수정 내용은 자동 저장됩니다.'
        if self.data['error']:instruction='미인식 원본 다시 읽기를 먼저 실행하세요.\n'+self.data['error']
        self.status.setText((f"{'확정' if self.data['status']=='confirmed' else '가채점'} {self.data['score']/100:g}점" if self.exam['configured'] else '선택과목과 정답을 확인하세요.')+'\n'+instruction)
        self.loading=False
        if self.data['normalized'] and not self.original.isChecked():self.view.mark(q,self.base['config'].get('form')=='math30')

    def show_choice(self):
        if not self.sid or self.base['config'].get('form')!='math30':return
        self.show_question(self.q);self.choice_mode=True;self.loading=True
        self.heading.setText('선택과목 · '+ELECTIVES.get(self.data['elective'],'미확인'))
        self.answer_label.setText('선택과목');self.answer.setStyleSheet('');self.answer.setValidator(QIntValidator(1,3,self.answer));self.answer.setMaxLength(1)
        self.answer.setText(self.data['elective'] or '')
        self.reading.setText('1 확통 / 2 미적분 / 3 기하 · 숫자 직접 입력')
        self.loading=False
        if self.view.highlight:self.view.scene_.removeItem(self.view.highlight);self.view.highlight=None

    def persist(self,answers=None,reviewed=None,student_id='current',elective='current',identity_ok=None,sat_on=None,note='답안표에서 검수'):
        if not self.sid or self.readonly:return
        row=self.store.scan(self.sid,images=False)
        self.store.save_review(self.sid,row['student_id'] if student_id=='current' else student_id,answers if answers is not None else row['answers'],reviewed if reviewed is not None else row['reviewed'],row['identity_ok'] if identity_ok is None else identity_ok,note,row['elective'] if elective=='current' else elective,sat_on=sat_on or row['sat_on'],allow_reopen=True)
        self.data={**self.data,**self.store.scan(self.sid,images=False)};self.exam=effective(self.base,self.data['elective']);self.show_question(self.q);self.saved.emit(self.sid)

    def update_answer(self,q,value):
        if self.readonly:raise ValueError('수기 입력은 수기 채점 화면에서 수정하세요.')
        if value is not None and not (0<=value<=999 if numeric(self.base,q+1) else 1<=value<=5):raise ValueError('선다형은 1~5, 숫자답안은 0~999로 입력하세요.')
        row=self.store.scan(self.sid,images=False)
        if row['answers'][q]==value:return
        before=deepcopy(row);answers=row['answers'];checks=row['reviewed'];answers[q]=value;checks[q]=False
        self.persist(answers=answers,reviewed=checks,note=f'답안표 {q+1}번 수정')
        fields=('id','exam_id','student_id','answers','reviewed','status','elective','sat_on','key_revision','identity_ok','import_context')
        after=self.store.scan(self.sid,images=False)
        self.undo_history.append((self.sid,q,{k:before[k] for k in fields},{k:after[k] for k in fields}))

    def undo_answer(self):
        if not self.sid:return
        entries=[entry for entry in self.undo_history if entry[0]==self.sid]
        if not entries:QMessageBox.information(self,'답안 수정 되돌리기','이 답안에서 되돌릴 최근 수정이 없어요.');return
        entry=entries[-1];sid,q,before,after=entry
        current=self.store.scan(sid,images=False)
        if any(current[k]!=v for k,v in after.items()) or self.store.exam(current['exam_id'])['revision']!=after['key_revision']:
            QMessageBox.information(self,'답안 수정 되돌리기','이후 학생 연결·정답·확정 상태가 변경되어 이 수정은 되돌릴 수 없어요.');return
        self.undo_history.remove(entry)
        self.persist(answers=before['answers'],reviewed=before['reviewed'],note=f'답안표 {q+1}번 수정 되돌리기')
        self.show_question(q);self.question_selected.emit(q)
        self.status.setText(self.status.text()+'\n수정을 되돌렸어요. 확인 후 성적을 확정해 주세요.')

    def answer_edited(self):
        if self.loading or not self.sid or self.readonly:return True
        try:
            text=self.answer.text().strip()
            if getattr(self,'choice_mode',False):self.choice_changed(text or None);self.show_choice()
            else:self.update_answer(self.q,int(text) if text else None)
            return True
        except (ValueError,TypeError) as exc:
            QMessageBox.warning(self,'답안 입력 확인',str(exc));self.answer.setFocus();return False

    def link_makeup(self):
        if not self.sid or self.readonly or self.answer_edited() is False:return
        from .makeupui import MakeupStudentDialog
        dialog=MakeupStudentDialog(self.store,self)
        if dialog.exec():
            try:
                self.store.link_makeup_student(self.sid,dialog.student_id)
                self.show_scan(self.sid,self.q);self.saved.emit(self.sid)
            except ValueError as exc:QMessageBox.warning(self,'보강생 연결',str(exc))

    def metadata_changed(self,*_):
        if self.loading or not self.sid or self.readonly:return
        try:
            index=self.student.currentIndex()
            if index<0 or self.student.currentText()!=self.student.itemText(index):raise ValueError('검색 결과에서 정확한 학생을 선택해 주세요.')
            student=self.student.currentData();changed=student!=self.data['student_id']
            self.persist(student_id=student,identity_ok=False if changed else self.data['identity_ok'],sat_on=self.day.date().toString('yyyy-MM-dd'),note='학생 연결·응시일·확인 변경')
        except ValueError as exc:QMessageBox.warning(self,'검수 확인',str(exc))

    def choice_changed(self,elective):
        if self.loading or not self.sid or self.readonly:return
        try:
            if elective not in (None,'1','2','3'):raise ValueError('선택과목은 1 확통 / 2 미적분 / 3 기하로 입력하세요.')
            if elective==self.data['elective']:return
            checks=self.data['reviewed'].copy()
            for q in range(22,len(checks)):checks[q]=False
            self.persist(elective=elective,reviewed=checks,identity_ok=False,note='선택과목 확인')
        except ValueError as exc:QMessageBox.warning(self,'선택과목 확인',str(exc))

    def next_question(self,direction=1):
        if not self.sid:return
        if self.answer_edited() is False:return
        for step in range(1,len(self.exam['key'])+1):
            q=(self.q+step*direction)%len(self.exam['key'])
            if self.data['answers'][q]!=self.exam['key'][q]:
                self.show_question(q);self.question_selected.emit(q)
                self.answer.setFocus();self.answer.selectAll();return

    def confirm(self):
        if not self.sid or self.readonly:return
        if self.answer_edited() is False:return
        if self.data['status']=='confirmed':return
        try:
            try:self.store.confirm(self.sid,verify_identity=True)
            except ValueError as exc:
                if not str(exc).startswith('DUPLICATE:'):raise
                if QMessageBox.question(self,'중복 성적','기존 확정 성적을 보관하고 이 답안으로 교체할까요?')!=QMessageBox.StandardButton.Yes:return
                self.store.confirm(self.sid,replace=True,verify_identity=True)
            self.show_scan(self.sid,self.q);self.saved.emit(self.sid)
        except ValueError as exc:QMessageBox.warning(self,'성적 확정 확인',str(exc))

    def load_image(self,*_):
        if not self.sid:return
        present=bool(self.data['raw'] or self.data['normalized'])
        for widget in self.image_tools:widget.setEnabled(present)
        self.image_notice.setText('OMR 이미지가 정리되었습니다. 답안·점수는 보존되어 있습니다.' if self.data.get('images_purged_at') else '' if present else '표시할 스캔 이미지가 없습니다.')
        self.image_notice.setVisible(bool(self.image_notice.text()))
        self.view.load(self.data['raw'] if self.original.isChecked() or not self.data['normalized'] else self.data['normalized']);self.show_question(self.q)

    def zoom_question(self):
        if self.view.highlight and not self.original.isChecked():self.view.fitInView(self.view.highlight.rect().adjusted(-25,-25,25,25),Qt.AspectRatioMode.KeepAspectRatio)

