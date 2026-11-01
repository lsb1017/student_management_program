"""시험 등록: 유형(주간지·모의고사·기타)별 양식·문항 수·배점·문제 형식, 문항 정보 엑셀(1.0.6 서식) 반영."""
from __future__ import annotations
from core.question_import import read_question_book,combine_sheets,parse_rows
from core.examdata import ELECTIVES

KINDS={'weekly':'주간지','mock':'모의고사','other':'기타'}


def numbers(text):
    """'1,2,3' / '1 2 3' → [1,2,3]; '-' or empty cell → None (정답 미정은 허용하지 않음)."""
    parts=[p for p in str(text).replace(',',' ').split() if p]
    try:return [int(p) for p in parts]
    except ValueError:raise ValueError('숫자를 쉼표 또는 공백으로 구분해 입력하세요.')


def labels(text,count,default=''):
    parts=[p.strip() for p in str(text).split(',')] if str(text).strip() else []
    if parts and len(parts)!=count:raise ValueError(f'문항 정보는 {count}개를 쉼표로 구분해 입력하세요. (현재 {len(parts)}개)')
    return parts or [default]*count


def config_from_rows(rows):
    return {'topics':[r['topic'] for r in rows],'areas':[r['area'] for r in rows],'skills':[r['skill'] for r in rows],'difficulties':[r['difficulty'] for r in rows]}


def from_workbook_math(path,group=None,primary=None):
    """수능수학(math30): 같은 시험의 선택과목 시트들을 합쳐 공통+선택 정답·배점·단원 구성."""
    sheets=[s for s in read_question_book(path) if not s.errors]
    groups=sorted({s.group for s in sheets})
    if group is None:
        if len(groups)!=1:raise ValueError('시험(시트 묶음)을 고르세요: '+', '.join(groups))
        group=groups[0]
    chosen=[s for s in sheets if s.group==group]
    by_choice=combine_sheets(chosen)
    primary=primary or ('1' if '1' in by_choice else sorted(by_choice)[0])
    rows=by_choice[primary]
    config={'form':'math30','primary':primary,**config_from_rows(rows),'variants':{}}
    for choice,variant in by_choice.items():
        if choice==primary:continue
        tail=variant[22:]
        config['variants'][choice]={'key':[r['key'] for r in tail],'points':[r['points'] for r in tail],**config_from_rows(tail)}
    return [r['key'] for r in rows],[r['points'] for r in rows],config


def from_workbook_custom(path,question_count,numeric=(),choices=5,sheet=None):
    """사용자 정의 양식: 문항 수·숫자형 문항에 맞춰 한 시트를 읽음."""
    import openpyxl
    book=openpyxl.load_workbook(path,read_only=True,data_only=False)
    try:
        names=book.sheetnames;name=sheet or names[0]
        values=[list(r) for r in book[name].iter_rows(values_only=True)]
    finally:book.close()
    parsed=parse_rows(name,values,require_elective=False,numeric=numeric,max_question=question_count,choices=choices)
    if parsed.errors:raise ValueError('\n'.join(parsed.errors))
    rows=parsed.rows
    return [r['key'] for r in rows],[r['points'] for r in rows],config_from_rows(rows)


def save(store,title,series,subject,round_no,day,kind,form,key,points,meta=None,exam_id=None,report_kind=None,variants_config=None):
    """form: 'math30' | 'local60' | form id (int, 사용자 정의 양식)."""
    config=dict(variants_config or {})
    if meta:config.update(meta)
    form_id=None
    if isinstance(form,int):config['form']='custom';form_id=form
    else:config['form']=form
    if kind=='other' and report_kind:config['report_kind']=report_kind
    return store.save_exam(title,series,subject,round_no,day,key,points,exam_id=exam_id,config=config,exam_kind=kind,form_id=form_id)


def electives_label(choice):
    return ELECTIVES.get(str(choice),'')
