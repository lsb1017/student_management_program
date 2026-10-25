from PySide6.QtWidgets import QMessageBox


def unsaved_choice(parent):
    dialog=QMessageBox(parent);dialog.setWindowTitle('저장하지 않은 수정 내용')
    dialog.setIcon(QMessageBox.Icon.Question);dialog.setText('수정한 내용을 저장할까요?')
    save=dialog.addButton('저장',QMessageBox.ButtonRole.AcceptRole)
    discard=dialog.addButton('버리기',QMessageBox.ButtonRole.DestructiveRole)
    stay=dialog.addButton('계속 편집',QMessageBox.ButtonRole.RejectRole)
    dialog.setDefaultButton(stay);dialog.setEscapeButton(stay);dialog.exec()
    return 'save' if dialog.clickedButton()==save else 'discard' if dialog.clickedButton()==discard else 'stay'
