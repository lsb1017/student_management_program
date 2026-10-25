"""Static, shared styling. No background effects or animation engine."""
STYLE = '''
QWidget { font-family:"Malgun Gothic"; font-size:13px; color:#39334D; }
QMainWindow,QDialog { background:#FAF9F6; }
QLabel#Heading {font-size:24px;font-weight:700;color:#39334D;padding:3px 0;}
QLabel#Sub {color:#746E81;font-size:12px;}
QLabel#HomeStat,QWidget#HomeNotice,QFrame#Surface {background:white;border:1px solid #E8E3EF;border-radius:12px;}
QLabel#HomeStat {padding:8px 12px;}
QLabel#HomeNoticeTitle {font-size:16px;font-weight:600;color:#49405D;}
QLabel#HomeRoutine {background:#F2EFF7;border-radius:9px;padding:8px;font-size:12px;color:#696174;}
QWidget#Sidebar {background:#F0EBF6;}
QListWidget#Nav {background:#F0EBF6;color:#5D516E;border:0;padding:0;font-size:14px;outline:0;}
QListWidget#Nav::item {min-height:26px;}
QListWidget#Nav::item {padding:15px 12px;margin:3px 0;border-radius:8px;}
QListWidget#Nav::item:selected {background:#E0D4F0;color:#49346A;font-weight:700;}
QPushButton {background:white;border:1px solid #DDD6E7;border-radius:7px;padding:8px 12px;}
QPushButton:hover {background:#F4EFFB;border-color:#BAA7D7;}
QPushButton:disabled {color:#A29AA9;background:#F1EFF2;border-color:#E4DFE9;}
QPushButton#Primary {background:#E7DCFA;color:#4E3672;border:1px solid #D9C7F5;font-weight:700;}
QPushButton#Primary:hover {background:#DBC9F6;}
QPushButton#Primary:disabled {color:#A29AA9;background:#F1EFF2;border-color:#E4DFE9;}
QPushButton#Import {background:#FFF0E4;color:#77523D;border-color:#F1D6C1;font-weight:700;}
QPushButton#Import:hover {background:#FCE4D2;}
QLineEdit,QComboBox,QDateEdit,QSpinBox,QTextEdit {background:white;border:1px solid #DDD6E7;border-radius:5px;padding:5px;min-height:22px;selection-background-color:#E4D8F4;selection-color:#39334D;}
QSpinBox::up-button,QSpinBox::down-button {width:22px;}
QTableWidget {background:white;border:1px solid #E4DEEB;gridline-color:#F0ECF4;selection-background-color:#ECE3F8;selection-color:#39334D;alternate-background-color:#FBFAFD;}
QHeaderView::section {background:#F2EEF7;border:0;padding:8px;font-weight:600;}
QGroupBox {border:1px solid #E4DEEB;border-radius:9px;margin-top:14px;padding:14px;}
QGroupBox::title {subcontrol-origin:margin;left:13px;font-weight:600;}
QCheckBox {spacing:7px;} QCheckBox::indicator {width:16px;height:16px;}
QGraphicsView {background:#F0EDF3;border:1px solid #E0D9E8;}
QTabWidget::pane {border:1px solid #E4DEEB;background:#FAF9F6;border-radius:8px;}
QTabBar::tab {background:#F1EDF5;padding:10px 19px;border:1px solid #E4DEEB;}
QTabBar::tab:selected {background:white;color:#563E79;font-weight:600;}
QToolTip {background:white;color:#39334D;border:1px solid #D8CEE5;}
'''

def alignment(header):
    from PySide6.QtCore import Qt
    left = any(word in header for word in ('학생명','성명','시험명','학원','원본 파일','학습내용','단원','유형','영역')) or header in ('학생','반','학교','제목')
    return (Qt.AlignmentFlag.AlignLeft if left else Qt.AlignmentFlag.AlignHCenter) | Qt.AlignmentFlag.AlignVCenter
