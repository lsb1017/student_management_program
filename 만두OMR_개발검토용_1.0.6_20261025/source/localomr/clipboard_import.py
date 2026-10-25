"""Excel TSV clipboard parsing. No access to the system clipboard until requested."""
import csv,io,re
from .question_import import HEADERS,parse_rows,integer,header_name
from .examdata import ELECTIVES


def cells(text):
    if len(text)>1_000_000:raise ValueError('복사한 표가 너무 큽니다. 문항 표만 복사하세요.')
    rows=list(csv.reader(io.StringIO(text.lstrip('\ufeff')),delimiter='\t'))
    rows=[row for row in rows if any(v.strip() for v in row)]
    if not rows or len(rows)>100 or max(map(len,rows))>20:raise ValueError('1~100행, 20열 이하의 문항 표를 복사하세요.')
    return rows


def structured(rows):
    first=[header_name(v) for v in rows[0]]
    return all(h in first for h in HEADERS) or all(len(r)==9 for r in rows)


def parse_table(rows,active):
    first=[header_name(v) for v in rows[0]]
    values=rows if all(h in first for h in HEADERS) else [HEADERS]+rows
    headers=[header_name(v) for v in values[0]];qcol=headers.index('문항');acol=headers.index('영역')
    try:qs={integer(r[qcol]) for r in values[1:]}
    except Exception as exc:raise ValueError('문항 번호를 확인하세요. 제목 행을 포함하거나 9개 열을 순서대로 복사하세요.') from exc
    if qs==set(range(1,23)):target='common'
    elif qs in (set(range(23,31)),set(range(1,31))):
        names={re.sub(r'\s+','',r[acol]) for r in values[1:] if integer(r[qcol])>=23 and len(r)>acol}
        inferred=[k for k,v in ELECTIVES.items() if re.sub(r'\s+','',v) in names]
        if len(inferred)>1:raise ValueError('선택 문항에 여러 선택과목이 섞여 있습니다.')
        target=inferred[0] if inferred else active
        if target not in ELECTIVES:raise ValueError('붙여넣을 선택과목 탭을 먼저 선택하세요. 공통 22문항만 복사할 수도 있습니다.')
    else:raise ValueError('전체 표 붙여넣기는 공통 1~22번, 선택 23~30번 또는 전체 1~30번을 복사하세요. 일부 값은 해당 셀을 선택해 붙여넣으세요.')
    name='붙여넣기 '+ELECTIVES.get(target,'공통')
    sheet=parse_rows(name,values,qs,require_elective=target!='common')
    if sheet.errors:raise ValueError('\n'.join(sheet.errors[:8]))
    if target!='common' and sheet.elective!=target:raise ValueError('선택과목을 확인하세요.')
    return sheet,target
