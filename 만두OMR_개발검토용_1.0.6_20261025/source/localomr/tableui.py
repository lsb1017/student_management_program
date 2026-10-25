"""Checkable result/exam tables, with stable identifiers and typed sorting."""
from PySide6.QtCore import Qt,Signal,QRect,QEvent
from PySide6.QtGui import QKeySequence,QColor
from PySide6.QtWidgets import QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QStyleOptionButton,QStyle,QStyleOptionHeader,QStyledItemDelegate
from .design import alignment

SORT_ROLE=Qt.ItemDataRole.UserRole+20

class SortItem(QTableWidgetItem):
    def __lt__(self,other):
        a=self.data(SORT_ROLE);b=other.data(SORT_ROLE)
        if a is not None and b is not None:return a<b
        return super().__lt__(other)

class CheckHeader(QHeaderView):
    def paintSection(self,painter,rect,index):
        if index!=0:return super().paintSection(painter,rect,index)
        table=self.parent();option=QStyleOptionHeader();self.initStyleOption(option)
        option.rect=rect;option.text='';painter.save()
        self.style().drawControl(QStyle.ControlElement.CE_Header,option,painter,self)
        count=len(table.checked_ids());total=table.rowCount();check=QStyleOptionButton()
        check.rect=QRect(rect.left()+8,rect.center().y()-7,15,15)
        check.state=QStyle.StateFlag.State_Enabled | (QStyle.StateFlag.State_On if total and count==total else QStyle.StateFlag.State_NoChange if count else QStyle.StateFlag.State_Off)
        self.style().drawControl(QStyle.ControlElement.CE_CheckBox,check,painter,self)
        painter.drawText(rect.adjusted(27,0,0,0),Qt.AlignmentFlag.AlignVCenter|Qt.AlignmentFlag.AlignLeft,'선택');painter.restore()

class CenterCheckDelegate(QStyledItemDelegate):
    def paint(self,painter,option,index):
        color=QColor('#ECE3F8') if option.state & QStyle.StateFlag.State_Selected else QColor('#FBFAFD' if index.row()%2 else '#FFFFFF')
        painter.fillRect(option.rect,color);check=QStyleOptionButton();size=16
        check.rect=QRect(option.rect.center().x()-size//2,option.rect.center().y()-size//2,size,size)
        check.state=QStyle.StateFlag.State_Enabled | (QStyle.StateFlag.State_On if index.data(Qt.ItemDataRole.CheckStateRole) in (Qt.CheckState.Checked,Qt.CheckState.Checked.value) else QStyle.StateFlag.State_Off)
        option.widget.style().drawControl(QStyle.ControlElement.CE_CheckBox,check,painter,option.widget)

    def editorEvent(self,event,model,option,index):
        toggle=(event.type()==QEvent.Type.MouseButtonRelease and event.button()==Qt.MouseButton.LeftButton) or (event.type()==QEvent.Type.KeyPress and event.key()==Qt.Key.Key_Space)
        if toggle:
            checked=index.data(Qt.ItemDataRole.CheckStateRole) in (Qt.CheckState.Checked,Qt.CheckState.Checked.value)
            return model.setData(index,(Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked).value,Qt.ItemDataRole.CheckStateRole)
        return False

class CheckTable(QTableWidget):
    checksChanged=Signal()
    def __init__(self,headers,widths):
        super().__init__(0,len(headers));self.setHorizontalHeader(CheckHeader(Qt.Orientation.Horizontal,self));self.setHorizontalHeaderLabels(headers);self._filling=False
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True);self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(39)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i,width in enumerate(widths):
            self.setColumnWidth(i,max(66,width) if i==0 else width)
            self.horizontalHeaderItem(i).setTextAlignment(alignment(headers[i]))
        self.horizontalHeader().sectionClicked.connect(self.header_clicked)
        self.setItemDelegateForColumn(0,CenterCheckDelegate(self))
        self.itemChanged.connect(self.check_changed)

    def check_changed(self,item):
        if item.column()==0 and not self._filling:self.horizontalHeader().viewport().update();self.checksChanged.emit()

    def checked_ids(self):
        return [self.item(r,0).data(Qt.ItemDataRole.UserRole) for r in range(self.rowCount()) if self.item(r,0) and self.item(r,0).checkState()==Qt.CheckState.Checked]

    def set_checks(self,checked):
        self._filling=True
        for r in range(self.rowCount()):self.item(r,0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._filling=False;self.horizontalHeader().viewport().update();self.checksChanged.emit()

    def keyPressEvent(self,event):
        if event.matches(QKeySequence.StandardKey.SelectAll):
            self.selectAll();self.set_checks(True);return
        super().keyPressEvent(event)

    def header_clicked(self,col):
        if col==0:self.set_checks(len(self.checked_ids())!=self.rowCount())

    def fill(self,rows):
        self._filling=True
        checked=set(self.checked_ids());current=self.item(self.currentRow(),0)
        current_id=current.data(Qt.ItemDataRole.UserRole) if current else None
        sorting=self.isSortingEnabled();self.setSortingEnabled(False);self.setRowCount(len(rows))
        for row,(identity,values,keys) in enumerate(rows):
            for col,value in enumerate(['']+values):
                item=SortItem(str(value));item.setData(Qt.ItemDataRole.UserRole,identity)
                item.setTextAlignment(alignment(self.horizontalHeaderItem(col).text()))
                item.setData(SORT_ROLE,identity if col==0 else keys[col-1])
                if col==0:
                    item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if identity in checked else Qt.CheckState.Unchecked)
                self.setItem(row,col,item)
        self.setSortingEnabled(sorting)
        self._filling=False;self.horizontalHeader().viewport().update();self.checksChanged.emit()
        if current_id is not None:
            for row in range(self.rowCount()):
                if self.item(row,0).data(Qt.ItemDataRole.UserRole)==current_id:self.setCurrentCell(row,1);break
