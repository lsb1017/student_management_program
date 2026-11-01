"""Side-by-side regression against the original 1.0.6 code in this repository.

ARCHITECTURE.md 정합성: 같은 답안·정답이면 1.0.6과 같은 점수·성적표가 나와야 함.
Only the student code differs by design (6-digit 0+tail+suffix → 7-digit 학번).
"""
import importlib
import json
import re
from copy import deepcopy
import pytest
from core.store import Store
from core.omr import ReadResult
from test_core_math import KEY,CONFIG,drawing

MATH_POINTS=[2,2]+[3]*6+[4]*7+[3]*4+[4]*3+[2]+[3]*4+[4]*3
PEOPLE=[('가학생','1',[10,14,21,29]),('나학생','2',[10,14,21,29]),('다학생','1',[]),('라학생','1',[8,10,14,21,29]),('마학생','1',[0,3,15])]


def build(module_store,path,codes):
    db=module_store.Store(path);academy=db.academy('학원');a=db.classroom(academy,'A반');b=db.classroom(academy,'B반')
    cfg={'form':'math30','primary':'1','cuts':{'1':[83,74,66,56,36,25,15,5],'2':[90,80,70,60,50,40,30,20]},
         'topics':['지수로그함수']*8+['미분']*8+['적분']*6+['확률']*8,'areas':['수학Ⅰ']*8+['수학Ⅱ']*14+['확률과 통계']*8,
         'skills':[f'유형{i}' for i in range(30)],
         'variants':{'2':{'key':[1]*8,'points':MATH_POINTS[22:],'topics':['미분법']*8,'skills':['']*8,'areas':['미적분']*8}}}
    ids=[]
    for round_no in (1,2):
        eid=db.save_exam(f'2027 필요충분 모의고사 시즌 9 - {round_no}회','시리즈','수학',str(round_no),f'2026-10-0{round_no}',[1]*30,MATH_POINTS,config=cfg)
        for i,(name,choice,wrong) in enumerate(PEOPLE):
            cid=a if i<2 else b
            student=db.save_student(codes[i],name,cid) if round_no==1 else next(s['id'] for s in db.students(name))
            wrong=[q for q in wrong if round_no==1 or q!=10]
            answers=[None if q in wrong else 1 for q in range(30)]
            data=dict(hash=f'{round_no}-{i}',name=name)
            if 'payload' in [r[1] for r in db.db.execute('PRAGMA table_info(sources)')]:source=db.db.execute('INSERT INTO sources(hash,name) VALUES(?,?)',(data['hash'],name)).lastrowid
            else:source=db.db.execute('INSERT INTO sources(hash,name,data) VALUES(?,?,?)',(data['hash'],name,b'x')).lastrowid
            db.db.commit()
            result=ReadResult(None,[{'answer':v,'flag':'clear','levels':[]} for v in answers],None);result.elective=choice
            sid,_=db.add_scan(eid,source,1,data['hash'],b'',result,sat_on=f'2026-10-0{round_no}')
            db.save_review(sid,student,answers,[True]*30,True,elective=choice);db.confirm(sid)
        ids.append(eid)
    return db,ids,(a,b)


@pytest.fixture
def pair(tmp_path,legacy):
    old_store=importlib.import_module('localomr.store')
    old,old_ids,old_classes=build(old_store,tmp_path/'old'/'db.sqlite3',[f'{i+1:06d}' for i in range(5)])
    import core.store
    new,new_ids,new_classes=build(core.store,tmp_path/'new'/'db.sqlite3',[f'{i+1:07d}' for i in range(5)])
    yield (old,old_ids,old_classes),(new,new_ids,new_classes)
    old.close();new.close()


def comparable(rows):
    keep=('score','grade','estimated_percentile','wrong','maximum','elective','key','points','topics','answers')
    return sorted(([r['snapshot']['name']]+[json.dumps(r[k],ensure_ascii=False) for k in keep] for r in rows))


def test_scores_grades_percentiles_identical(pair):
    (old,old_ids,_),(new,new_ids,_)=pair
    assert comparable(old.results())==comparable(new.results())
    for o,n in zip(old_ids,new_ids):assert old.averages(o)==new.averages(n)


def test_rankings_identical(pair,legacy):
    (old,old_ids,old_classes),(new,new_ids,new_classes)=pair
    old_rank=importlib.import_module('localomr.ranking');from core import ranking
    fields=('overall_rank','selected_rank','class_rank','elective_rank','overall_n','class_n','elective_n')
    o=sorted((r['snapshot']['name'],)+tuple(r[f] for f in fields) for r in old_rank.ranked_results(old,old_ids[0],list(old_classes)))
    n=sorted((r['snapshot']['name'],)+tuple(r[f] for f in fields) for r in ranking.ranked_results(new,new_ids[0],list(new_classes)))
    assert o==n


def test_cohort_rates_and_clinic_identical(pair,legacy):
    (old,old_ids,_),(new,new_ids,_)=pair
    old_insights=importlib.import_module('localomr.report_insights');from core import report_insights
    def normalize(rates,ids):return sorted((ids.index(k[0]),)+k[1:]+(round(v,9),) for k,v in rates.items())
    assert normalize(old_insights.cohort_error_rates(old.results()),old_ids)==normalize(report_insights.cohort_error_rates(new.results()),new_ids)


def page_texts(path):
    import pypdfium2 as pdfium
    out=[]
    with pdfium.PdfDocument(str(path)) as doc:
        for page in doc:
            tp=page.get_textpage();out.append(tp.get_text_range());tp.close();page.close()
    return out


def test_mock_report_text_identical_except_student_code(pair,tmp_path,legacy):
    (old,old_ids,_),(new,new_ids,_)=pair
    old_reports=importlib.import_module('localomr.reports');from core import reports
    for name in ('가학생','라학생','다학생'):
        o=next(r for r in old.results(old_ids[1]) if r['snapshot']['name']==name)
        n=next(r for r in new.results(new_ids[1]) if r['snapshot']['name']==name)
        old_reports.report_pdf(tmp_path/'o.pdf',old,[o['id']]);reports.report_pdf(tmp_path/'n.pdf',new,[n['id']])
        old_text,new_text=page_texts(tmp_path/'o.pdf'),page_texts(tmp_path/'n.pdf')
        assert len(old_text)==len(new_text)==2
        # Only the header label and the code value change (학생번호 code[-5:] → 학번 7자리).
        strip=lambda t,code,label:t.replace(label,'<LABEL>').replace(code,'<CODE>')
        assert strip(old_text[0],o['snapshot']['code'][-5:],'학생번호')==strip(new_text[0],n['snapshot']['code'],'학번')
        assert old_text[1]==new_text[1]


def test_recognition_identical(legacy,tmp_path):
    old_math=importlib.import_module('localomr.mathomr');old_omr=importlib.import_module('localomr.omr');old_reports=importlib.import_module('localomr.reports')
    from core import mathomr,omr
    image=drawing()
    a,b=old_math.recognize_math(image),mathomr.recognize_math(image)
    assert a.answers==b.answers and a.code==b.code and a.elective==b.elective and a.identity_reading==b.identity_reading
    path=tmp_path/'local.pdf';old_reports.sheet_pdf(path,60,'비교','000123',[i%5+1 for i in range(60)])
    page=next(omr.load_pages(path))[1]
    assert old_omr.recognize(page,60).answers==omr.recognize(page,60).answers
