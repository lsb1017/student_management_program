"""M2 채점·검수: PDF 불러오기, 학생 연결, 검수, 확정. Ported store rules are unchanged."""
from __future__ import annotations
from core.importer import import_files,retry_failed,reread_selected,default_recognizer
from core.identity import name_advisory


def recognizer(store,exam):
    """Pick the reader for an exam: 1.0.6 forms or a user-defined/external form."""
    if exam['config'].get('form')!='custom':return default_recognizer(store,exam)
    from academy.forms.reader import recognize,reference_gray
    form=store.form(exam['form_id']);layout=form['layout']
    reference=reference_gray(store,form) if form['source']=='external' else None
    return lambda img:recognize(img,layout,reference)


def import_pdf(store,exam_id,files,academy_id,class_id,sat_on=None,progress=lambda text:None,cancelled=lambda:False):
    if academy_id is None or class_id is None:raise ValueError('불러올 학원과 분반을 선택하세요.')
    store.db.commit()
    return import_files(store.path,exam_id,files,progress,cancelled,academy_id,class_id,sat_on,recognizer=recognizer,operator_id=store.operator_id)


def retry(store,exam_id,scan_ids,academy_id=None,class_id=None):
    return retry_failed(store.path,exam_id,scan_ids,academy_id=academy_id,class_id=class_id,recognizer=recognizer)


def reread(store,exam_id,scan_ids,academy_id=None,class_id=None):
    return reread_selected(store.path,exam_id,scan_ids,academy_id=academy_id,class_id=class_id,recognizer=recognizer)


ATTENTION=('blank','multiple','faint','incomplete','failed')


def review_reasons(store,row):
    """Why a page needs a person before confirmation (shown in the review list)."""
    reasons=[]
    if row['status']=='failed':reasons.append('인식 실패')
    if not row['student_id']:reasons.append('학생 미연결')
    flagged=[i+1 for i,r in enumerate(row['reading']) if r.get('flag') in ATTENTION]
    if flagged:reasons.append('확인 문항 '+', '.join(map(str,flagged[:8]))+(' 외' if len(flagged)>8 else ''))
    context=row['import_context'] if isinstance(row['import_context'],dict) else {}
    if context.get('notice'):reasons.append(context['notice'])
    if row['student_id']:
        advisory=name_advisory(context,row.get('name') or '')
        if advisory:reasons.append(advisory)
    return reasons


def confirm_clear(store,exam_id,scan_ids):
    """일괄 확정: 학생이 연결되고 확인할 문항이 없는 검수 대기 답안만 확정함(학생·시험 일치 확인 포함)."""
    done=[];skipped=[]
    rows={r['id']:r for r in store.scans(exam_id)}
    import json
    for sid in scan_ids:
        row=rows.get(sid)
        if not row or row['status']!='pending':skipped.append((sid,'검수 대기 상태가 아님'));continue
        row=dict(row);row['reading']=json.loads(row['reading']);row['import_context']=json.loads(row['import_context'])
        reasons=review_reasons(store,row)
        if reasons:skipped.append((sid,', '.join(reasons)));continue
        try:store.confirm(sid,verify_identity=True);done.append(sid)
        except ValueError as exc:skipped.append((sid,str(exc)))
    return done,skipped
