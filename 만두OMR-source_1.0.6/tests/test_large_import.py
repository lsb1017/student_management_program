from pathlib import Path
import threading,time,sqlite3
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
import pytest
from localomr.omr import load_pages,MAX_PAGES,MAX_FILE_BYTES
from localomr.store import Store,SCHEMA_VERSION
from localomr.importer import import_files
from localomr.ui import MainWindow,StudentDialog,ReviewDialog
from test_manual_students import setup
from test_math import scan

def large_pdf(path,size):
    offsets=[0]
    with path.open('wb') as f:
        f.write(b'%PDF-1.4\n')
        values=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << >> >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << >> >>']
        for i,value in enumerate(values,1):offsets.append(f.tell());f.write(f'{i} 0 obj\n'.encode()+value+b'\nendobj\n')
        offsets.append(f.tell());f.write(f'5 0 obj\n<< /Length {size} >>\nstream\n'.encode())
        for _ in range(size//(1024*1024)):f.write(b'0'*(1024*1024))
        f.write(b'\nendstream\nendobj\n');xref=f.tell();f.write(b'xref\n0 6\n0000000000 65535 f \n')
        for offset in offsets[1:]:f.write(f'{offset:010d} 00000 n \n'.encode())
        f.write(f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())

def test_over_150mb_pdf_two_pages_streamed_and_backup_restored(setup,tmp_path):
    db,s,e,c,w=setup;p=tmp_path/'large.pdf';large_pdf(p,151*1024*1024)
    assert p.stat().st_size>150*1024*1024 and MAX_FILE_BYTES==1024**3 and MAX_PAGES==2000
    result=import_files(db.path,e,[p],academy_id=db.classes()[0]['academy_id'],class_id=c)
    assert result['added']==2 and result['failed']==2 and not result['errors']
    sid=db.scans(e)[0]['id'];assert db.scan(sid)['import_context']['class_id']==c
    source=db.scan(sid)['source_id'];out=tmp_path/'restored.pdf';db.export_source(source,out)
    import hashlib
    def digest(path):
        h=hashlib.sha256()
        with path.open('rb') as f:
            while chunk:=f.read(1024*1024):h.update(chunk)
        return h.hexdigest()
    assert digest(p)==digest(out)

def test_page_limit_and_cancelled_source_transaction(setup,tmp_path):
    import pypdfium2 as pdfium
    p=tmp_path/'pages.pdf'
    with pdfium.PdfDocument.new() as doc:
        for _ in range(2001):doc.new_page(10,10).close()
        doc.save(str(p))
    with pytest.raises(ValueError,match='2,000'):next(load_pages(p))
    db,*_=setup;p=tmp_path/'cancel.bin';p.write_bytes(b'x'*(3*1024*1024));calls=0
    def cancel():
        nonlocal calls;calls+=1;return calls>=5
    before=db.db.execute('SELECT COUNT(*) FROM sources').fetchone()[0]
    with pytest.raises(InterruptedError):db.source(p,cancel)
    assert db.db.execute('SELECT COUNT(*) FROM sources').fetchone()[0]==before and db.db.execute('SELECT COUNT(*) FROM source_parts').fetchone()[0]==0

def test_students_can_register_during_background_import(setup,monkeypatch):
    db,s,e,c,w=setup;gate=threading.Event();observed=[]
    def fake_import(path,*args):
        gate.wait(5);other=Store(path);observed.append(any(s['name']=='진행중등록' for s in other.students()));other.close()
        return dict(added=0,duplicate=0,failed=0,errors=[],cancelled=False)
    monkeypatch.setattr('localomr.ui.import_files',fake_import)
    window=MainWindow(db);window.score_exam.setCurrentIndex(1);window.score_academy.setCurrentIndex(window.score_academy.findData(db.classes()[0]['academy_id']));window.score_class.setCurrentIndex(window.score_class.findData(c));window.start_import(e,[])
    assert window.centralWidget().isEnabled() and window.pages.widget(1).isEnabled() and window.progress.windowModality()==Qt.WindowModality.NonModal
    window.nav.setCurrentRow(1);dlg=StudentDialog(db);dlg.name.setText('진행중등록');dlg.phone.setText('1122');dlg.save();gate.set()
    deadline=time.time()+8
    while window.worker and time.time()<deadline:QApplication.processEvents();time.sleep(.01)
    assert observed==[True] and window.import_button.isEnabled();window.hide();window.deleteLater();QApplication.processEvents()

def test_review_registers_new_student_and_connects_without_auto_confirm(setup,monkeypatch):
    db,s,e,c,w=setup;scan(db,e,s);sid=db.official_id(e,s);db.set_status(sid,'pending');db.db.execute('UPDATE scans SET student_id=NULL WHERE id=?',(sid,));db.db.commit();db.set_import_context(sid,None,c)
    def register(dlg):
        assert dlg.cls.currentData()==c
        dlg.name.setText('새학생');dlg.phone.setText('7788');dlg.save();return 1
    monkeypatch.setattr(StudentDialog,'exec',register)
    d=ReviewDialog(db,sid);d.new_student();student=db.student(d.student.currentData());assert student['name']=='새학생' and student['class_id']==c and not d.identity_confirmed
    d.dirty=False;d.close()

def test_v2_migration_preserves_existing_students(setup,tmp_path):
    db,s,e,c,w=setup;backup=tmp_path/'old.omrbackup';db.backup(backup)
    old=sqlite3.connect(backup)
    for table,col in [('students','phone'),('students','parent_phone'),('scans','input_mode'),('scans','origin_scan_id'),('scans','import_context')]:old.execute(f'ALTER TABLE {table} DROP COLUMN {col}')
    old.execute('DROP TABLE source_parts');old.execute('PRAGMA user_version=2');old.commit();old.close();db.restore(backup)
    assert db.student(s)['name']=='학생가' and db.student(s)['phone']=='' and db.db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION
