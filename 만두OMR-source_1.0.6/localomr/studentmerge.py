"""Explicit, previewed student consolidation; no automatic identity matching."""
import hashlib,json,uuid
from datetime import datetime

def preview(store,keep_id,source_id):
    if keep_id==source_id:raise ValueError('서로 다른 두 학생을 선택하세요.')
    keep=store.student(keep_id);source=store.student(source_id)
    if not keep['active']:raise ValueError('유지할 학생은 재원 학생으로 선택하세요.')
    scans=store.rows('SELECT sc.id,sc.exam_id,sc.student_id,sc.status,sc.score,sc.input_mode,sc.answers,sc.reviewed,sc.snapshot,sc.import_context,sc.key_revision,sc.identity_ok,sc.sat_on,sc.pixel_hash,sc.elective,sc.reading,sc.error,e.title FROM scans sc JOIN exams e ON e.id=sc.exam_id WHERE student_id IN (?,?) ORDER BY sc.id',(keep_id,source_id))
    history=store.rows('SELECT r.*,e.title,e.linked_exam_id FROM historical_results r JOIN historical_exams e ON e.id=r.exam_id WHERE student_id IN (?,?) ORDER BY r.id',(keep_id,source_id))
    kept_exams={('exam',r['exam_id']) for r in scans if r['student_id']==keep_id and r['status']!='deleted'}
    kept_exams.update(('exam',r['linked_exam_id']) if r['linked_exam_id'] else ('history',r['exam_id']) for r in history if r['student_id']==keep_id)
    delete_scans=[];delete_history=[];removed=[];moved=[]
    for r in scans:
        if r['student_id']!=source_id:continue
        if r['status']=='deleted':continue
        reason='수기 성적' if r['input_mode']=='manual' else '겹치는 시험' if ('exam',r['exam_id']) in kept_exams else None
        if reason:
            delete_scans.append(r['id']);removed.append({'title':r['title'],'score':r['score']/100,'reason':reason})
        else:moved.append(r['id'])
    for r in history:
        if r['student_id']!=source_id:continue
        key=('exam',r['linked_exam_id']) if r['linked_exam_id'] else ('history',r['exam_id'])
        if key in kept_exams:
            delete_history.append(r['id']);removed.append({'title':r['title'],'score':r['score']/100,'reason':'겹치는 이전 성적'})
    members={str(s):store.memberships(s) for s in (keep_id,source_id)}
    fingerprint=hashlib.sha256(json.dumps([keep,source,scans,history,members],sort_keys=True,default=str).encode()).hexdigest()
    return dict(keep=keep,source=source,delete_scans=delete_scans,delete_history=delete_history,removed=removed,moved=moved,fingerprint=fingerprint)

def merge(store,keep_id,source_id,expected):
    plan=preview(store,keep_id,source_id)
    if plan['fingerprint']!=expected:raise ValueError('학생 기록이 변경되었습니다. 삭제 목록을 다시 확인하세요.')
    folder=store.path.parent/'backups'/'before_student_merge';folder.mkdir(parents=True,exist_ok=True)
    backup=store.backup(folder/(datetime.now().strftime('%Y%m%d_%H%M_학생합치기전_')+uuid.uuid4().hex[:8]+'.omrbackup'))
    with store.transaction():
        if preview(store,keep_id,source_id)['fingerprint']!=expected:raise ValueError('백업 중 학생 기록이 변경되어 합치기를 취소했습니다.')
        target=plan['keep'];snapshot=json.dumps(target,ensure_ascii=False)
        for row in store.rows('SELECT id,import_context,status FROM scans WHERE student_id=?',(source_id,)):
            context=json.loads(row['import_context']);context.update(student_merge=True,manual_link=True,makeup_link=True,makeup_student_id=keep_id)
            state=row['status']
            if row['id'] in plan['delete_scans']:
                state='deleted';context['merge_locked_deleted']=True
            # Previously deleted source records remain deleted but follow the surviving ID.
            store.db.execute('UPDATE scans SET student_id=?,snapshot=?,status=?,import_context=? WHERE id=?',(keep_id,snapshot,state,json.dumps(context,ensure_ascii=False),row['id']))
        # Existing deleted target records must also respect post-merge collision checks.
        for row in store.rows("SELECT id,import_context FROM scans WHERE student_id=? AND status='deleted'",(keep_id,)):
            context=json.loads(row['import_context']);context['student_merge']=True
            store.db.execute('UPDATE scans SET import_context=? WHERE id=?',(json.dumps(context,ensure_ascii=False),row['id']))
        for rid in plan['delete_history']:store.db.execute('DELETE FROM historical_results WHERE id=?',(rid,))
        store.db.execute('UPDATE historical_results SET student_id=?,snapshot=? WHERE student_id=?',(keep_id,snapshot,source_id))
        store.db.execute('INSERT OR IGNORE INTO student_classes SELECT ?,class_id FROM student_classes WHERE student_id=?',(keep_id,source_id))
        store.db.execute('DELETE FROM student_classes WHERE student_id=?',(source_id,))
        store.db.execute('DELETE FROM students WHERE id=?',(source_id,))
        store.log('students_merged',keep_id,{'source':plan['source'],'removed':plan['removed'],'moved':plan['moved'],'backup':str(backup)})
        if store.db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('학생 연결 검사에 실패했습니다. 변경을 취소합니다.')
    return backup
