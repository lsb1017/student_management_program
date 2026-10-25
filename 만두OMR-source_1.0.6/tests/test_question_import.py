from copy import deepcopy
import pytest
from localomr.question_import import HEADERS,parse_rows,combine_sheets
from localomr.examdata import NUMERIC,effective


def rows(choice='확률과 통계'):
    return [HEADERS]+[[q,'공통영역' if q<=22 else '선택영역','수학Ⅰ' if q<=22 else choice,'유형',None,2 if q<=10 else 4,0 if q in NUMERIC else 3,'숫자답안' if q in NUMERIC else '선다형','and'] for q in range(1,31)]


def test_headers_whitespace_and_numeric_zero():
    data=rows();data[0]=[' '+h+'\n' for h in HEADERS];data.insert(0,[None]*9);data.append([None]*9)
    s=parse_rows('시즌1 확통 ',data)
    assert not s.errors and s.rows[15]['key']==0 and s.elective=='1' and s.maximum==100


@pytest.mark.parametrize('q,column,value',[(1,6,None),(1,6,0),(16,6,1000),(1,5,-1),(1,7,'숫자답안'),(1,8,'or'),(1,6,'=1+2'),(1,6,'1,2'),(16,6,1.5)])
def test_invalid_values_are_visible(q,column,value):
    data=rows();data[q][column]=value
    assert parse_rows('시즌1 확통',data).errors


def test_duplicates_gaps_and_foreign_exam():
    data=rows();data[-1][0]=29;assert parse_rows('시즌1 확통',data).errors
    first=parse_rows('시즌1 확통',rows());second=parse_rows('시즌2 미적분',rows('미적분'))
    with pytest.raises(ValueError,match='다른 시험'):combine_sheets([first,second])


def test_conflicting_common_keys_and_matching_sheets():
    first=parse_rows('시즌1 확통',rows());second=parse_rows('시즌1 미적분',rows('미적분'))
    assert set(combine_sheets([first,second]))=={'1','2'}
    second.rows[0]['key']=4
    with pytest.raises(ValueError,match='공통 문항'):combine_sheets([first,second])
    with pytest.raises(ValueError,match='같은 선택과목'):combine_sheets([first,first])


def test_editor_import_preserves_all_columns(tmp_path,monkeypatch):
    import os
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtWidgets import QApplication,QMessageBox
    from localomr.examui import ExamEditor
    from localomr.store import Store
    app=QApplication.instance() or QApplication([])
    def fail(*args):raise AssertionError(str(args[-1]))
    monkeypatch.setattr(QMessageBox,'warning',fail)
    db=Store(tmp_path/'import.sqlite3');editor=ExamEditor(db)
    sheets=[parse_rows('시즌1 확통',rows()),parse_rows('시즌1 미적분',rows('미적분')),parse_rows('시즌1 기하',rows('기하'))]
    editor.apply_import(sheets,'synthetic.xlsx');editor.series.setText('시즌1');editor.round.setText('1');editor.save()
    e=db.exam(editor.eid);assert e['key'][15]==0 and e['config']['areas'][0]=='수학Ⅰ'
    assert e['config']['conditions']==['and']*30 and e['config']['difficulties']==['']*30
    assert effective(e,'2')['areas'][22]=='미적분'
    assert e['config']['import_sources'][0]['file']=='synthetic.xlsx'
    # Sequential imports must not bypass the common-key conflict protection.
    conflicting=rows('기하');conflicting[1][6]=4
    with pytest.raises(ValueError,match='공통 문항'):editor.apply_import([parse_rows('시즌1 기하',conflicting)])
    editor.close();db.close()


def test_default_points_are_100_for_every_elective():
    import os
    os.environ['QT_QPA_PLATFORM']='offscreen'
    from PySide6.QtWidgets import QApplication
    from localomr.examui import ExamEditor
    app=QApplication.instance() or QApplication([])
    editor=ExamEditor(None)
    for k in ('1','2','3'):
        editor.select_section(k)
        assert sum(float(r[1]) for r in editor.bank[k])==100
    editor.close()
