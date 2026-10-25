from copy import deepcopy
import pytest
from localomr.report_insights import grade_target,clinic_priorities,review_questions,unit_history
from localomr.reports import report_pdf
from test_math import store,scan,exam,KEY,CONFIG


@pytest.mark.parametrize('score,cuts,expected',[
    (5700,[83,74,66,56,36],'3등급까지 9점'),
    (5600,[83,74,66,56,36],'3등급까지 10점'),
    (5500,[83,74,66,56,36],'4등급까지 1점'),
    (3500,[83,74,66,56,36],'5등급까지 1점'),
    (8300,[83,74,66,56,36],'만점까지 17점'),
    (10000,[83,74,66,56,36],'만점 달성'),
    (1900,[90,80,70,60,50,40,30,20],'8등급까지 1점'),
    (6500,[88,78,68,58,38],'3등급까지 3점'),
    (8275,[83,74,66,56,36],'1등급까지 0.25점'),
    (6500,[],''),
])
def test_grade_target_boundaries_and_missing_cuts(score,cuts,expected):
    assert grade_target({'score':score,'maximum':10000,'cuts':cuts})==expected


def record(eid,wrong=(),choice='1'):
    answers=KEY.copy()
    for q in wrong:answers[q]=None
    return {'exam_id':eid,'elective':choice,'key':KEY.copy(),'answers':answers,
        'points':[300]*30,'topics':[f'단원{i}' for i in range(30)],'areas':['수학Ⅰ']*22+[{'1':'확통','2':'미적분'}[choice]]*8,'skills':[f'유형{i}' for i in range(30)]}


def test_clinic_counts_distinct_exams_and_excludes_other_elective():
    first=record(1,[0,22],choice='2');second=record(2,[0,1]);third=record(3,[0,1,2])
    second['topics'][1]=second['topics'][0];third['topics'][1]=third['topics'][0]
    rows=unit_history([record(0,[29]),first,second,third],'1')
    target=next(x for x in rows if x['topic']=='단원0')
    assert target['wrong_rounds']==3 and target['rounds']==4
    assert target['wrong']==5 and target['total']==6
    assert not any(x['course']=='미적분' for x in rows)
    assert clinic_priorities([record(4)],'1')==[]


def test_review_only_own_errors_correct_rate_then_repeat_then_points():
    old=record(1,[0]);mine=record(2,[0,1,22,23]);mine['points'][23]=400
    same=record(2,[0,22]);other=record(2,[0],choice='2')
    choices=review_questions(mine,[mine,same,other],[old,mine])
    assert [x['q'] for x in choices]==[1,23,0]
    assert choices[2]['repeat_rounds']==2 and choices[0]['correct_rate']==pytest.approx(200/3)
    assert choices[1]['correct_rate']==50  # Other electives do not affect the choice questions.
    assert len(review_questions(record(2,[1]),[same],[record(2,[1])]))==1
    assert review_questions(record(2),[same],[record(2)])==[]


def test_insights_pdf_keeps_all_three_sections_and_two_pages(store,tmp_path):
    import pypdfium2 as pdfium
    s,student=store;cfg=deepcopy(CONFIG)
    cfg['skills']=['반복유형']+['나머지유형']*29;cfg['areas']=['수학 I']*22+['확률과 통계']*8
    cfg['topics']=['지수로그함수']*22+['확률']*8
    answers=KEY.copy();answers[0]=None;answers[15]=None
    titles=[]
    for i in range(1,7):
        title=f'2027 필요충분 모의고사 시즌 4 - {i}회 · 수학 영역';titles.append(title)
        eid=s.save_exam(title,'시리즈','수학',str(i),f'2026-10-{i:02}',KEY,[3]*30,config=cfg)
        sid=scan(s,eid,student,unique=f'insight{i}',answers=answers)
    path=tmp_path/'insights.pdf';report_pdf(path,s,[sid])
    with pdfium.PdfDocument(str(path)) as doc:
        assert len(doc)==2;text='';pages=[]
        for page in doc:
            tp=page.get_textpage();pages.append(tp.get_text_range());text+=pages[-1];tp.close();page.close()
    for label in ('클리닉 우선순위 분석','누적 오답/문항','차이','내 오답률과 전체 학생 오답률의 차이가 큰 단원 순','이번 시험의 우선 복습 2문항','오답률 상위 분석','문항번호','단원','수학Ⅰ','전체 오답률','1등급 달성!'):
        assert label in text,label
    for removed in ('복습 우선 영역','이번 시험의 오답률 상위 문항'):assert removed not in text
    assert '1등급 달성!' in pages[0] and '정말 잘했어요!' in pages[0] and '만점까지' not in pages[0]
    assert '응시 2026-10-06' not in pages[0]
    assert '시험명' in pages[1]
    for title in titles:assert ''.join(title.split()) in ''.join(pages[1].split())
    assert b'NanumDaeGwangYuRi' in path.read_bytes()
