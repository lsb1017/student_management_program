from collections import Counter
from .examdata import effective
from .importer import scan_in_scope


def candidates(store,ids,academy_id=None,class_id=None):
    rows=[store.scan(sid,images=False) for sid in dict.fromkeys(ids)]
    duplicate=Counter((r['exam_id'],r['student_id']) for r in rows if r['status']=='pending' and r['student_id'])
    ready=[];skipped=[];already=0
    for row in rows:
        if row['status']=='confirmed':already+=1;continue
        reason=''
        student=store.student(row['student_id']) if row['student_id'] else None
        scope={**(student or {}),**row}
        if not scan_in_scope(scope,academy_id,class_id):reason='선택한 학원·반 밖의 답안'
        elif row['status']!='pending':reason='확정 대상 아님'
        elif not student:reason='학생 미연결'
        elif row['error']:reason='인식 오류 확인 필요'
        elif row['input_mode']=='manual' and not all(row['reviewed']):reason='수기 답안 미입력'
        elif not effective(store.exam(row['exam_id']),row['elective'])['configured']:reason='선택과목·정답 확인 필요'
        elif store.official_id(row['exam_id'],row['student_id']):reason='기존 확정 성적 있음'
        elif duplicate[row['exam_id'],row['student_id']]>1:reason='같은 학생의 대기 답안 중복'
        elif not row['identity_ok']:
            context=row['import_context'];member=row['snapshot'] or store.student_for_class(student['id'],context.get('class_id'))
            makeup=context.get('makeup_link') and context.get('makeup_student_id')==row['student_id']
            if makeup:pass
            elif context.get('notice') or context.get('identity_reading',{}).get('notice'):reason='학생 연결 안내 확인 필요'
            elif ((context.get('class_id') is not None and context['class_id']!=member.get('class_id')) or
                  (context.get('academy_id') is not None and context['academy_id']!=member.get('academy_id'))):reason='학생 소속 확인 필요'
        if reason:skipped.append(reason)
        else:ready.append(row['id'])
    return ready,skipped,already
