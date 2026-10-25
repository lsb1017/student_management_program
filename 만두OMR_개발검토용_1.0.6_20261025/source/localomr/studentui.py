from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QMessageBox,QHeaderView
from .ui import label,button,table,populate,guarded
from .studentdata import plan_students,display_code

class StudentImportDialog(QDialog):
    def __init__(self,store,rows,parent=None):
        super().__init__(parent);self.store=store;self.rows=rows;self.setWindowTitle('학생 엑셀 일괄 등록 미리보기');self.resize(1150,650)
        v=QVBoxLayout(self);v.addWidget(label('반은 세미콜론(;)으로 여러 개 입력할 수 있습니다. 기존 학생에 반을 추가하려면 기존 학생번호를 입력하세요.','Sub'))
        plan=plan_students(store,rows);self.plan=plan
        v.addWidget(label(f"신규 {sum(r['action'] in ('add','link') for r in plan)}명 · 건너뜀 {sum(r['action']=='skip' for r in plan)}명 · 오류 {sum(r['action']=='error' for r in plan)}행"))
        grid=table(['성명','학생 연락처','학교','학부모 연락처','학원','반','학생번호','처리']);grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents);grid.horizontalHeader().setStretchLastSection(True);v.addWidget(grid,1)
        populate(grid,[(i,[r.get('name',''),r.get('phone',''),r.get('school',''),r.get('parent_phone',''),r.get('academy',''),r.get('classroom',''),display_code(r['code']),r['message']]) for i,r in enumerate(plan)])
        v.addWidget(label('기존 학생번호를 지정하면 반만 추가합니다. 번호 없이 같은 성명·연락처가 있으면 건너뜁니다. 오류가 있으면 엑셀을 고친 뒤 다시 불러오세요. 모든 행을 확인한 후 한 번에 등록합니다.','Sub'))
        h=QHBoxLayout();v.addLayout(h);h.addStretch();h.addWidget(button('취소',self.reject));self.commit=button('일괄 등록',self.save,True);self.commit.setEnabled(any(r['action'] in ('add','link') for r in plan) and not any(r['action']=='error' for r in plan));h.addWidget(self.commit)

    @guarded
    def save(self):
        added,skipped=self.store.import_students(self.rows);QMessageBox.information(self,'등록 완료',f'{len(added)}명 등록 · {skipped}명 건너뜀');self.accept()
