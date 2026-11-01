"""Student workbook input and shared contact/code validation.

학번은 학생 휴대전화 뒷 4자리 + 무작위 3자리 = 7자리임(1.0.6의 0+뒷4자리+구분1자리를 대체).
"""
import re
import secrets
import sys
from pathlib import Path
from openpyxl import load_workbook

HEADERS=['성명','학생 연락처','학교','학부모 연락처','학원','반']
FIELDS=['name','phone','school','parent_phone','academy','classroom']
CODE=re.compile(r'[0-9]{7}')


def phone_text(value,required=True):
    if value is None:value=''
    if isinstance(value,bool):raise ValueError('연락처를 숫자로 입력하세요.')
    if isinstance(value,(int,float)):
        if value!=int(value):raise ValueError('연락처에 소수를 사용할 수 없습니다.')
        value=str(int(value))
        if required and len(value)<=4:value=value.zfill(4)
    value=str(value).strip()
    if not value and not required:return ''
    if not re.fullmatch(r'[0-9() +\-]+',value):raise ValueError('연락처는 숫자와 하이픈으로 입력하세요.')
    digits=re.sub(r'[^0-9]','',value)
    if required and len(digits)==4:return digits
    if 9<=len(digits)<=11 and digits.startswith('0'):return digits
    raise ValueError('학생 연락처는 뒤 4자리 또는 전체 번호를 입력하세요. 전체 번호의 첫 0을 확인하세요.' if required else '학부모 연락처는 첫 0을 포함한 전체 번호로 입력하세요.')


def validate_student(row):
    r=dict(row);r['name']=str(r.get('name') or '').strip()
    if not r['name'] or len(r['name'])>60:raise ValueError('성명은 필수이며 60자 이내로 입력하세요.')
    r['phone']=phone_text(r.get('phone'));r['parent_phone']=phone_text(r.get('parent_phone'),False)
    for field in ('school','academy','classroom'):
        r[field]=str(r.get(field) or '').strip()
        if len(r[field])>(800 if field=='classroom' else 80):raise ValueError('학교·학원·반은 80자 이내로 입력하세요.')
    r['classrooms']=[x.strip() for x in r['classroom'].split(';') if x.strip()]
    if any(len(x)>80 for x in r['classrooms']):raise ValueError('반 이름은 80자 이내로 입력하세요.')
    return r


def next_code(tail,used,rng=None):
    """휴대전화 뒷 4자리 + 무작위 3자리. 겹치면 다시 뽑고, 1,000개가 모두 쓰이면 중단함."""
    if not re.fullmatch(r'[0-9]{4}',tail or ''):raise ValueError('학생 휴대전화 뒷 4자리를 확인하세요.')
    free=[n for n in range(1000) if f'{tail}{n:03d}' not in used]
    if not free:raise ValueError(f'{tail}: 뒷 4자리가 같은 학번 1,000개가 모두 사용 중입니다.')
    draw=(rng or secrets.SystemRandom())
    while True:
        code=f'{tail}{draw.randrange(1000):03d}'
        if code not in used:return code


def phone_changed(before,after):
    """학번 재발급 기준: 뒷 4자리가 바뀌거나, 전체 번호끼리 서로 다르면 번호 변경으로 봄.

    뒷 4자리만 입력했던 학생에게 같은 뒷 4자리의 전체 번호를 보충하는 것은 변경이 아님.
    """
    before=re.sub(r'[^0-9]','',before or '');after=re.sub(r'[^0-9]','',after or '')
    if before[-4:]!=after[-4:]:return True
    return len(before)>4 and len(after)>4 and before!=after


def display_code(code):
    return code


def plan_students(store,rows,rng=None):
    existing=store.students();used={s['code'] for s in existing};plan=[]
    for i,row in enumerate(rows,1):
        r=dict(row);line=r.get('row',i)
        try:
            r=validate_student(r)
            def same(s):
                phone=s.get('phone') or s.get('code','')[:4]
                return s['name']==r['name'] and phone[-4:]==r['phone'][-4:] and (phone==r['phone'] or len(phone)==4 or len(r['phone'])==4)
            matches=[s for s in existing if same(s)]
            target=r.get('student_code')
            # Excel stores 0123456 as a number; restore the leading zero.
            target=f'{int(target):07d}' if isinstance(target,(int,float)) and not isinstance(target,bool) and target==int(target) else str(target or '').strip()
            if target:
                if not CODE.fullmatch(target):raise ValueError('기존 학번은 숫자 7자리로 입력하세요.')
                targets=[x for x in existing if x.get('code')==target]
                if len(targets)!=1 or targets[0]['name']!=r['name']:raise ValueError('기존 학번과 성명이 일치하지 않습니다.')
                r.update(action='link',code=target,student_id=targets[0]['id'],message=f'{line}행: 기존 학생에 반 추가 (성적·기존 정보 유지)')
            elif matches:
                r.update(action='skip',code=matches[0]['code'],message=f'{line}행: 같은 성명·연락처가 있어 건너뜀 (기존 정보 유지)')
            else:
                r.update(action='add',code=next_code(r['phone'][-4:],used,rng),message=f'{line}행: 신규 등록')
                used.add(r['code']);existing.append(r)
        except ValueError as exc:r.update(action='error',code='',message=f'{line}행: {exc}')
        plan.append(r)
    return plan


def read_students(path):
    path=Path(path)
    if path.suffix.lower()!='.xlsx':raise ValueError('학생 등록 서식(.xlsx)을 선택하세요.')
    if path.stat().st_size>20*1024*1024:raise ValueError('20MB 이하의 엑셀을 선택하세요.')
    book=load_workbook(path,read_only=True,data_only=False)
    try:
        sheet=book['학생등록'] if '학생등록' in book.sheetnames else book.worksheets[0]
        if sheet.max_row>10020:raise ValueError('한 번에 10,000명까지 등록할 수 있습니다.')
        header=None;rows=[]
        for index,cells in enumerate(sheet.iter_rows(max_col=7),1):
            vals=[c.value for c in cells]
            if header is None:
                names=[str(v or '').replace(' ','').replace('*','').replace('(필수)','') for v in vals]
                if names[:6]==[h.replace(' ','') for h in HEADERS]:header=index
                elif index>=20:raise ValueError('성명 / 학생 연락처 / 학교 / 학부모 연락처 / 학원 / 반 순서의 서식을 사용하세요.')
                continue
            if not any(v is not None and str(v).strip() for v in vals):continue
            if any(c.data_type=='f' for c in cells):raise ValueError(f'{index}행: 수식 대신 값을 붙여넣어 주세요.')
            rows.append(dict(zip(FIELDS+['student_code'],vals),row=index))
        if not header or not rows:raise ValueError('등록할 학생이 없습니다. 서식의 입력란을 채워 주세요.')
        return rows
    finally:book.close()


def template_path():
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))
    return root/'assets'/'학생_일괄등록_서식.xlsx'
