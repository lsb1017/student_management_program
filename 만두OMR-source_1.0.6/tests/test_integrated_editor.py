import csv,io,os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
import pytest
from PySide6.QtWidgets import QApplication,QMessageBox
from PySide6.QtCore import Qt
from localomr.store import Store
from localomr.examui import ExamEditor
from localomr.examdata import ELECTIVES,effective,grade,estimated_percentile,percentile_label
from localomr.clipboard_import import cells,parse_table
from localomr.forms import math_form_path
from test_question_import import rows
from test_math import scan


def tsv(data):
    out=io.StringIO();csv.writer(out,delimiter='\t',lineterminator='\r\n').writerows(data);return out.getvalue()


@pytest.fixture
def editor(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);db=Store(tmp_path/'editor.sqlite3');dialog=ExamEditor(db);warnings=[]
    monkeypatch.setattr(QMessageBox,'warning',lambda *args:warnings.append(str(args[-1])))
    yield dialog,db,warnings
    dialog.close();db.close()


def fill_all(dialog):
    for name in ELECTIVES.values():dialog.apply_clipboard(tsv(rows(name)))


def test_name_and_date_only_one_exam_three_electives_missing_popup(editor):
    d,db,warnings=editor
    assert d.form.currentData()=='math30' and math_form_path().is_file()
    assert d.tabs.count()==4 and d.keys.rowCount()==22
    d.title.setText('모의고사 7회차')
    for name in ('확률과 통계','미적분'):d.apply_clipboard(tsv(rows(name)))
    d.save();assert d.eid is None and not db.exams()
    assert '기하' in warnings[-1] and '23' in warnings[-1] and d.active=='3'
    d.apply_clipboard(tsv(rows('기하')));d.save()
    assert d.eid and len(db.exams())==1
    exam=db.exam(d.eid);assert exam['round']=='7' and exam['subject']=='수학' and exam['config']['require_all_choices']
    for k in ELECTIVES:assert effective(exam,k)['configured'] and len(effective(exam,k)['key'])==30
    assert set(exam['config']['variants'])|{exam['config']['primary']}==set(ELECTIVES)


def test_paste_headerless_common_elective_and_partial_cells(editor):
    d,db,warnings=editor;data=rows()
    d.apply_clipboard(tsv(data[1:23]));assert d.active=='common' and d.bank['1'][15][0]=='0'
    assert all(d.bank[k][15][0]=='0' for k in ELECTIVES)
    d.select_section('1');d.apply_clipboard(tsv(data[23:]));assert d.bank['1'][22][0]=='3'
    d.select_section('common');d.keys.setCurrentCell(0,1);d.apply_clipboard('지수로그함수\t수학 I\n미분\t수학 II')
    assert d.bank['1'][0][2]=='지수로그함수' and d.bank['2'][1][4]=='수학 II'
    assert not d.keys.item(0,0).flags() & Qt.ItemFlag.ItemIsEditable
    d.keys.setCurrentCell(21,8);before=d.draft()
    with pytest.raises(ValueError,match='공간'):d.apply_clipboard('and\nand')
    assert d.draft()==before


def test_wrong_form_kind_rejected_without_saving(editor):
    d,db,warnings=editor;fill_all(d);d.title.setText('형식 검증');d.select_section('common')
    d.keys.cellWidget(0,7).setCurrentText('숫자답안');d.save()
    assert not d.eid and '문제형태' in warnings[-1]
    d.keys.cellWidget(0,7).setCurrentText('선다형');d.save();assert d.eid


def test_common_conflict_in_full_subject_paste_is_not_silently_overwritten(editor):
    d,db,warnings=editor;d.apply_clipboard(tsv(rows('확률과 통계')))
    other=rows('미적분');other[1][6]=4
    with pytest.raises(ValueError,match='공통 문항'):d.apply_clipboard(tsv(other))
    assert d.bank['1'][0][0]=='3'


def test_clipboard_errors_are_visible():
    for data in (rows()[:-1],rows()+[rows()[1]]):
        with pytest.raises(ValueError):parse_table(cells(tsv(data)),'1')
    data=rows();data[1][6]='=1+2'
    with pytest.raises(ValueError,match='수식'):parse_table(cells(tsv(data)),'1')
    data=rows();data[2][2]='수학 I';data[2][3]='여러 줄\n유형 설명'
    parsed,_=parse_table(cells(tsv(data)),'1');assert '\n' in parsed.rows[1]['skill']


def test_five_grade_cuts_apply_per_elective_with_same_exam(editor):
    d,db,warnings=editor;fill_all(d);d.title.setText('통합 모의고사 1회차')
    d.cuts={'1':[90,80,70,60,50],'2':[88,78,68,58,48],'3':[85,75,65,55,45]};d.save();assert d.eid
    academy=db.academy('학원');cls=db.classroom(academy,'혼합반')
    for k in ELECTIVES:
        student=db.save_student(k,'선택'+k,cls);answers=effective(db.exam(d.eid),k)['key'];answers=deepcopy(answers)
        # 6 wrong 2-point common questions => 88 points for all three electives.
        answers[:6]=[None]*6;scan(db,d.eid,student,k,'choice'+k,answers)
    results=db.results(d.eid);assert len(results)==3 and {r['exam_id'] for r in results}=={d.eid}
    by_choice={r['elective']:r for r in results}
    assert [by_choice[k]['grade'] for k in ELECTIVES]==[2,1,1]
    assert by_choice['2']['estimated_percentile']==96
    assert grade(4999,d.cuts['1'])=='6등급 이하'
    assert estimated_percentile(4999,10000,d.cuts['1']) is None
    assert percentile_label({'estimated_percentile':None,'grade':'6등급 이하','cuts':d.cuts['1']})=='40 미만'
    assert grade(5000,d.cuts['1'])==5 and estimated_percentile(5000,10000,d.cuts['1'])==40
    assert len(db.exams())==1


def test_complete_three_subject_requirement_enforced_in_storage(editor):
    d,db,warnings=editor;fill_all(d);d.title.setText('저장 검사');d.save()
    e=db.exam(d.eid);cfg=deepcopy(e['config']);cfg['variants'].pop(next(iter(cfg['variants'])))
    with pytest.raises(ValueError,match='모두'):db.save_exam(e['title'],e['series'],e['subject'],e['round'],e['day'],e['key'],[p/100 for p in e['points']],e['id'],cfg)


def test_five_cut_report_and_xlsx_below_cut_are_not_fabricated(editor,tmp_path):
    import pypdfium2 as pdfium
    import openpyxl
    from localomr.reports import report_pdf
    from localomr.ranking import ranking_xlsx
    d,db,_=editor;fill_all(d);d.title.setText('하위 등급 표시');d.cuts={k:[90,80,70,60,50] for k in ELECTIVES};d.save()
    aid=db.academy('학원');cid=db.classroom(aid,'반');student=db.save_student('12341','예제',cid)
    sid=scan(db,d.eid,student,'1','low',[None]*30)
    pdf=tmp_path/'low.pdf';report_pdf(pdf,db,[sid])
    with pdfium.PdfDocument(str(pdf)) as doc:
        page=doc[0];t=page.get_textpage();text=t.get_text_range();assert '6등급 이하' in text and '40 미만' in text;t.close();page.close()
    xlsx=tmp_path/'low.xlsx';ranking_xlsx(xlsx,db,d.eid,[cid]);book=openpyxl.load_workbook(xlsx)
    assert book.active['M9'].value=='6등급 이하' and book.active['N9'].value=='40 미만';book.close()
