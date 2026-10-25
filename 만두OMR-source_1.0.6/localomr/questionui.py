from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QTableWidget,QTableWidgetItem,QHeaderView,QPushButton,QMessageBox,QAbstractItemView,QTextEdit
from .question_import import combine_sheets
from .examui import HEADERS
from .examdata import ELECTIVES


class QuestionImportDialog(QDialog):
    def __init__(self,sheets,parent=None):
        super().__init__(parent);self.sheets=sheets;self.chosen=[];self.setWindowTitle('문항 엑셀 · 가져오기 전 확인');self.resize(1160,790)
        v=QVBoxLayout(self);v.addWidget(QLabel('같은 시험의 선택과목 시트를 체크하세요. 원본 엑셀은 변경하지 않습니다.\n초안에 반영한 뒤 시험명·시험일·정답·배점을 확인하고 시험 저장을 눌러야 적용됩니다.'))
        self.list=QTableWidget(len(sheets),6);self.list.setHorizontalHeaderLabels(['선택','시트명','선택과목','문항 수','만점','입력 검사']);self.list.verticalHeader().hide();self.list.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents);self.list.horizontalHeader().setStretchLastSection(True);self.list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.list.setMaximumHeight(255);v.addWidget(self.list)
        for i,s in enumerate(sheets):
            check=QTableWidgetItem();check.setFlags(Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsUserCheckable|Qt.ItemFlag.ItemIsSelectable);check.setCheckState(Qt.CheckState.Checked if i==0 else Qt.CheckState.Unchecked);self.list.setItem(i,0,check)
            for j,text in enumerate([s.name,ELECTIVES.get(s.elective,'미확인'),len(s.rows),f'{s.maximum:g}',f'오류 {len(s.errors)}개' if s.errors else '30문항 확인'],1):self.list.setItem(i,j,QTableWidgetItem(str(text)))
        self.details=QTableWidget(0,9);self.details.setHorizontalHeaderLabels(HEADERS);self.details.verticalHeader().hide();self.details.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.details.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents);v.addWidget(self.details,1)
        self.messages=QTextEdit();self.messages.setReadOnly(True);self.messages.setMaximumHeight(85);v.addWidget(self.messages)
        apply=QPushButton('선택한 시트를 시험 초안에 반영');apply.setObjectName('Primary');apply.clicked.connect(self.apply);v.addWidget(apply)
        self.list.currentCellChanged.connect(self.preview);self.list.selectRow(0);self.preview()

    def preview(self,*_):
        i=self.list.currentRow()
        if i<0:return
        sheet=self.sheets[i];self.details.setRowCount(len(sheet.rows))
        for r,row in enumerate(sheet.rows):
            from .classification import course_name
            display=dict(row)
            if course_name(row['skill']) and not course_name(row['area']):display['area'],display['skill']=row['skill'],row['area']
            for col,k in enumerate(['q','topic','area','skill','difficulty','points','key','kind','condition']):self.details.setItem(r,col,QTableWidgetItem(str(display[k])))
        self.messages.setPlainText('\n'.join(sheet.errors) if sheet.errors else '이 시트는 입력 형식 검사를 통과했습니다. 함께 선택한 시트의 시험·회차와 공통 문항 일치 여부는 반영 전에 다시 검사합니다.')

    def apply(self):
        try:
            chosen=[s for i,s in enumerate(self.sheets) if self.list.item(i,0).checkState()==Qt.CheckState.Checked]
            combine_sheets(chosen);self.chosen=chosen;self.accept()
        except ValueError as exc:QMessageBox.warning(self,'문항 정보 확인',str(exc))
