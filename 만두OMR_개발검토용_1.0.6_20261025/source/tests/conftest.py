import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import pytest

@pytest.fixture(autouse=True)
def dismiss_unrelated_editor_drafts(monkeypatch):
    # Legacy tests close draft editors solely for cleanup. Dedicated draft tests
    # override this choice to exercise save/stay/discard through the same UI.
    monkeypatch.setattr('localomr.draftui.unsaved_choice',lambda *args:'discard')

@pytest.fixture(autouse=True)
def dismiss_new_dialogs_in_legacy_tests(monkeypatch,request):
    # New workflow tests exercise these choices explicitly. Existing tests were
    # written before startup/backup preview dialogs and use windows as fixtures.
    if request.node.path.name in ('test_v0411.py','test_v10.py','test_v101.py','test_v102.py','test_v103.py'):return
    from localomr.backupui import BackupNameDialog
    monkeypatch.setattr(BackupNameDialog,'exec',lambda self:1)
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.StandardButton.Yes)
    def ask(parent,title,text,asset,buttons=None,default=None,labels=None):
        if title=='작업 시작 · 백업 확인':return QMessageBox.StandardButton.No
        return QMessageBox.question(parent,title,text,buttons,default)
    monkeypatch.setattr('localomr.popups.ask',ask)
    def execute(box):
        if box.windowTitle()=='작업 시작 · 백업 확인':return QMessageBox.StandardButton.No
        if box.windowTitle()=='작업 마침 · 백업 확인':return QMessageBox.StandardButton.No
        if box.windowTitle()=='가져올 백업 확인':return QMessageBox.StandardButton.Yes
        return QMessageBox.StandardButton.Ok
    monkeypatch.setattr(QMessageBox,'exec',execute)
