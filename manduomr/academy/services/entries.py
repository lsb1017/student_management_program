"""미니테스트·과제 수기 입력: 분반·수업 날짜별 표. 저장할 때 빈 칸은 미제출로 채움."""
from __future__ import annotations
from datetime import date
from decimal import Decimal,InvalidOperation
from pathlib import Path
import secrets
from core.store import now,validate_sat_on

HOMEWORK=('A','B','C','미제출')


def session(store,class_id,day,create=True):
    day=validate_sat_on(day)
    row=store.rows('SELECT * FROM class_sessions WHERE class_id=? AND date=?',(class_id,day))
    if row or not create:return row[0] if row else None
    with store.transaction():
        store.db.execute('INSERT INTO class_sessions(class_id,date,link_key,created_at) VALUES(?,?,?,?)',(class_id,day,secrets.token_urlsafe(9),now()))
        sid=store.db.execute('SELECT id FROM class_sessions WHERE class_id=? AND date=?',(class_id,day)).fetchone()[0]
        store.log('class_session_created',sid,{'class_id':class_id,'date':day})
    return store.rows('SELECT * FROM class_sessions WHERE id=?',(sid,))[0]


def mini_score(value):
    """Blank → None (미제출). 0~1,000, up to two decimals."""
    if value is None or str(value).strip() in ('','-','미제출'):return None
    try:
        number=Decimal(str(value).strip())
        if not number.is_finite() or not 0<=number<=1000 or number*100!=(number*100).to_integral_value():raise ValueError()
        return float(number)
    except (InvalidOperation,ValueError):raise ValueError('미니테스트 점수는 0~1,000 사이의 수(소수 둘째 자리까지)로 입력하세요.')


def homework(value):
    text=str(value or '').strip().upper()
    if text in ('','-','미제출','X'):return '미제출'
    if text in ('A','B','C'):return text
    raise ValueError('과제 완성도는 A, B, C 중 하나로 입력하세요. 빈 칸은 미제출입니다.')


def grid(store,class_id,day):
    """Rows for the table: class students (active), with saved values if any."""
    found=session(store,class_id,day,create=False)
    saved={r['student_id']:r for r in store.rows('SELECT * FROM session_entries WHERE session_id=?',(found['id'],))} if found else {}
    rows=[]
    for s in store.class_students(class_id):
        entry=saved.get(s['id'])
        rows.append({'student_id':s['id'],'code':s['code'],'name':s['name'],
                     'mini_score':entry['mini_score'] if entry else None,'homework':entry['homework'] if entry else '',
                     'saved':bool(entry)})
    return rows


def save(store,class_id,day,values):
    """values: [{'student_id','mini_score','homework'}] for the class. Validates all rows first."""
    members={s['id'] for s in store.class_students(class_id,active_only=False)}
    cleaned=[];errors=[]
    for i,v in enumerate(values,1):
        try:
            if v['student_id'] not in members:raise ValueError('분반 학생이 아닙니다.')
            cleaned.append((v['student_id'],mini_score(v.get('mini_score')),homework(v.get('homework'))))
        except ValueError as exc:errors.append(f'{i}행: {exc}')
    if errors:raise ValueError('\n'.join(errors))
    found=session(store,class_id,day)
    with store.transaction():
        for sid,score,work in cleaned:
            store.db.execute('INSERT INTO session_entries(session_id,student_id,mini_score,homework,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(session_id,student_id) DO UPDATE SET mini_score=excluded.mini_score,homework=excluded.homework,updated_at=excluded.updated_at',
                             (found['id'],sid,score,work,now()))
        store.log('session_entries_saved',found['id'],{'class_id':class_id,'date':found['date'],'rows':len(cleaned)})
    return found


def entry_for(store,class_id,day,student_id):
    rows=store.rows('SELECT e.* FROM session_entries e JOIN class_sessions s ON s.id=e.session_id WHERE s.class_id=? AND s.date=? AND e.student_id=?',(class_id,day,student_id))
    return rows[0] if rows else None


def parse_paste(text):
    """Excel clipboard (tab-separated) → list of cell lists. Trailing empty line ignored."""
    lines=text.replace('\r\n','\n').replace('\r','\n').split('\n')
    if lines and lines[-1]=='':lines.pop()
    return [line.split('\t') for line in lines]


EXPORT_HEADERS=['학번','이름','미니테스트','과제(A/B/C)']


def export_xlsx(store,class_id,day,path):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    book=Workbook();sheet=book.active;sheet.title='미니테스트·과제'
    sheet.append(EXPORT_HEADERS)
    for cell in sheet[1]:cell.font=Font(bold=True)
    for r in grid(store,class_id,day):
        sheet.append([r['code'],r['name'],r['mini_score'],r['homework'] or None])
        sheet.cell(sheet.max_row,1).number_format='@'
    for col,width in zip('ABCD',(12,14,12,14)):sheet.column_dimensions[col].width=width
    book.save(path);book.close();return Path(path)


def import_xlsx(store,class_id,day,path):
    """Match rows by 학번, then by unique name in the class. Returns (values, unmatched)."""
    from openpyxl import load_workbook
    book=load_workbook(path,read_only=True,data_only=True)
    try:
        rows=[list(r) for r in book.worksheets[0].iter_rows(values_only=True)]
    finally:book.close()
    if not rows or [str(v or '').strip() for v in rows[0][:2]]!=EXPORT_HEADERS[:2]:raise ValueError('학번 / 이름 / 미니테스트 / 과제 순서의 서식을 사용하세요.')
    students=store.class_students(class_id);by_code={s['code']:s for s in students}
    values=[];unmatched=[]
    for r in rows[1:]:
        if not any(v not in (None,'') for v in r):continue
        code=str(r[0]).strip() if r[0] is not None else ''
        if code.isdigit():code=code.zfill(7)
        student=by_code.get(code)
        if not student:
            named=[s for s in students if s['name']==str(r[1] or '').strip()]
            student=named[0] if len(named)==1 else None
        if not student:unmatched.append(f'{r[0]} {r[1]}');continue
        values.append({'student_id':student['id'],'mini_score':r[2] if len(r)>2 else None,'homework':r[3] if len(r)>3 else None})
    return values,unmatched
