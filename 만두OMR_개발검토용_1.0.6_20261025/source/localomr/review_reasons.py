"""Build visible row hints in one pass; never select image blobs."""
import json
from collections import Counter
from .examdata import effective
from .identity import name_advisory

def row_reasons(store,rows,base):
    if not base:return {}
    students={s['id']:s for s in store.students()}
    duplicate=Counter(r['student_id'] for r in rows if r['status']=='pending' and r['student_id'])
    officials={r['student_id'] for r in store.rows("SELECT student_id FROM scans WHERE exam_id=? AND status='confirmed'",(base['id'],))}
    configured={key:effective(base,key)['configured'] for key in (None,'0','1','2','3')}
    result={}
    for row in rows:
        sid=row['id'];reason=''
        if row['status']=='failed':reason='원본 재인식 필요'
        elif row['status']=='pending':
            student=students.get(row['student_id']);context=row['import_context'];snapshot=row['snapshot'];reviewed=row['reviewed']
            if isinstance(context,str):context=json.loads(context)
            if isinstance(snapshot,str):snapshot=json.loads(snapshot)
            if isinstance(reviewed,str):reviewed=json.loads(reviewed)
            if not student:reason='학생 미연결'
            elif row['error']:reason='인식 오류 확인'
            elif row['input_mode']=='manual' and not all(reviewed):reason='수기 답안 미입력'
            elif not configured.get(row['elective'],False):reason='선택과목 확인'
            elif row['student_id'] in officials:reason='기존 확정 있음'
            elif duplicate[row['student_id']]>1:reason='대기 답안 중복'
            elif not row['identity_ok']:
                member=snapshot or store.student_for_class(student['id'],context.get('class_id'))
                makeup=context.get('makeup_link') and context.get('makeup_student_id')==row['student_id']
                if not makeup:
                    if context.get('notice') or context.get('identity_reading',{}).get('notice'):reason='학생 연결 확인'
                    elif any(context.get(k) is not None and context[k]!=member.get(k) for k in ('class_id','academy_id')):reason='학생 소속 확인'
            if not reason and student:reason=name_advisory(context,student['name'])
        if reason:result[sid]=reason
    return result
