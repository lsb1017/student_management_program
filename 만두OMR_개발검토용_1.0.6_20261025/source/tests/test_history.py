import json
import pypdfium2 as pdfium
from PySide6.QtWidgets import QApplication
from localomr.history import results,mean_for_history
from localomr.historyui import HistoryDialog
from localomr.report_math import report_history
from localomr.report_insights import clinic_priorities
from localomr.reports import report_pdf
from localomr.store import pack,SCHEMA_VERSION
from test_math import store,exam,scan


def add_history(db,student,title='이전 수학시험 2회',day='2026-09-18',linked=None):
    with db.transaction():
        eid=db.db.execute('INSERT INTO historical_exams(title,day,mean,maximum,source_name,source_hash,linked_exam_id) VALUES(?,?,72.94,10000,?,?,?)',(title,day,'source.xlsx',title,linked)).lastrowid
        db.db.execute('INSERT INTO historical_results(exam_id,student_id,sat_on,score,standard_score,grade,elective,snapshot,earned,ox,answers,source_row) VALUES(?,?,?,8400,120,?,NULL,?,?,?,?,5)',(eid,student,day,'1',pack(db.student(student)),pack([200]*22+[500]*8),pack(['O']*22+['X']*8),pack([2]*29+['1|4'])))


def test_imported_scores_in_report_keep_mean_and_do_not_invent_classification(store,tmp_path):
    db,student=store;eid=exam(db);sid=scan(db,eid,student);add_history(db,student)
    current=db.results()[0];history=report_history(db,current)
    assert len(history)==2 and history[0]['score']==8400 and mean_for_history(db,history[0])==72.94
    assert history[0]['answers'][-1]=='1|4' and history[0]['elective']=='1' and history[0]['elective_inferred']
    assert clinic_priorities(history,current['elective'])==[]
    p=tmp_path/'history.pdf';report_pdf(p,db,[sid])
    with pdfium.PdfDocument(str(p)) as doc:
        assert len(doc)==2
        page=doc[1];textpage=page.get_textpage();text=textpage.get_text_range();textpage.close();page.close()
    assert '이전 수학시험 2회' in text and '72.9' in text and '84 / 100' in text
    assert '이전 시험은 문항 분류 등록 필요' not in text


def test_history_limit_future_exclusion_and_current_override(store):
    db,student=store;eid=exam(db);sid=scan(db,eid,student)
    for i in range(1,8):add_history(db,student,f'이전 시험 {i}회',f'2026-09-{i:02}')
    add_history(db,student,'미래 시험','2026-12-01');add_history(db,student,'동일 현재 시험','2026-10-18',eid)
    history=report_history(db,db.results()[0]);assert len(history)==6
    assert history[0]['title']=='이전 시험 3회' and history[-1]['id']==sid
    assert all(x['title'] not in ('미래 시험','동일 현재 시험') for x in history)
    assert len(results(db))==9


def test_history_backup_restore_and_search(store,tmp_path):
    db,student=store;add_history(db,student)
    p=tmp_path/'history.omrbackup';db.backup(p)
    db.db.execute('DELETE FROM historical_results');db.db.commit();assert not results(db)
    db.restore(p);assert len(results(db))==1 and db.db.execute('PRAGMA user_version').fetchone()[0]==SCHEMA_VERSION
    app=QApplication.instance() or QApplication([]);dialog=HistoryDialog(db)
    assert dialog.table.rowCount()==1
    dialog.search.setText('4241');assert dialog.table.rowCount()==1
    dialog.search.setText('없는학생');assert dialog.table.rowCount()==0
    dialog.close()
