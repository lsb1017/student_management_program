from pathlib import Path
from datetime import date
import io
import json
from PIL import Image
from .store import Store,validate_sat_on
from .mathomr import recognize_math
from .omr import load_pages, recognize, pixel_hash, png_bytes, MAX_FILE_BYTES


def scan_in_scope(row,academy_id=None,class_id=None):
    context=row['import_context']
    if isinstance(context,str):context=json.loads(context)
    aid=context.get('academy_id') or row.get('academy_id')
    cid=context.get('class_id') or row.get('class_id')
    unresolved=row['student_id'] is None and row['status'] in ('failed','pending')
    return (academy_id is None or aid==academy_id or (unresolved and aid is None)) and (class_id is None or cid==class_id or (unresolved and cid is None))


def retry_failed(db_path,eid,scan_ids,progress=lambda message:None,cancelled=lambda:False,academy_id=None,class_id=None):
    store=Store(db_path);summary={'added':0,'duplicate':0,'failed':0,'errors':[],'cancelled':False,'retried':0,'recovered':0,'outside_class':0}
    try:
        for i,sid in enumerate(dict.fromkeys(scan_ids)):
            if cancelled():summary['cancelled']=True;break
            try:
                row=store.scan(sid)
                if row['exam_id']!=eid or row['status']!='failed' or row['input_mode']!='scan':
                    summary['duplicate']+=1;continue
                progress(f'미인식 원본 다시 읽는 중 · {i+1}/{len(scan_ids)}장')
                exam=store.exam(eid)
                with Image.open(io.BytesIO(row['raw'])) as img:
                    result=recognize_math(img) if exam['config'].get('form')=='math30' else recognize(img,len(exam['key']))
                if store.retry_failed_scan(sid,result,academy_id,class_id):
                    summary['retried']+=1;summary['failed' if result.error else 'recovered']+=1
                else:summary['duplicate']+=1
            except Exception as exc:summary['errors'].append(f'답안 {sid}: {exc}')
    finally:store.close()
    return summary


def reread_selected(db_path,eid,scan_ids,progress=lambda message:None,cancelled=lambda:False,academy_id=None,class_id=None):
    store=Store(db_path);summary={'added':0,'duplicate':0,'failed':0,'errors':[],'cancelled':False,'retried':0,'recovered':0,'outside_class':0}
    try:
        for i,sid in enumerate(dict.fromkeys(scan_ids)):
            if cancelled():summary['cancelled']=True;break
            try:
                row=store.scan(sid)
                if row['exam_id']!=eid or row['status'] not in ('failed','pending') or row['input_mode']!='scan':
                    summary['duplicate']+=1;continue
                if row['images_purged_at']:raise ValueError('이미지 정리로 원본이 제거되어 다시 읽을 수 없습니다.')
                progress(f'선택 답안 다시 읽는 중 · {i+1}/{len(scan_ids)}장')
                exam=store.exam(eid)
                with Image.open(io.BytesIO(row['raw'])) as img:
                    result=recognize_math(img) if exam['config'].get('form')=='math30' else recognize(img,len(exam['key']))
                if store.reread_scan(sid,result,academy_id,class_id):
                    summary['retried']+=1;summary['failed' if result.error else 'recovered']+=1
                else:summary['duplicate']+=1
            except Exception as exc:summary['errors'].append(f'답안 {sid}: {exc}')
    finally:store.close()
    return summary


def import_files(db_path,eid,paths,progress=lambda message:None,cancelled=lambda:False,academy_id=None,class_id=None,sat_on=None):
    sat_on=validate_sat_on(sat_on if sat_on is not None else date.today().isoformat())
    store=Store(db_path)
    summary={'added':0,'duplicate':0,'failed':0,'errors':[],'cancelled':False,'outside_class':0,'retried':0,'recovered':0}
    try:
        exam=store.exam(eid);count=len(exam['key'])
        for name in paths:
            if cancelled():
                summary['cancelled']=True;break
            try:
                path=Path(name)
                if path.stat().st_size>MAX_FILE_BYTES:
                    raise ValueError('파일당 1GB 제한을 초과했습니다.')
                progress(f'{path.name} · 원본을 보관하고 있습니다.')
                source_id=store.source(path,cancelled)
                for page,img in load_pages(path):
                    if cancelled():
                        summary['cancelled']=True;break
                    progress(f'{path.name} · {page}쪽 인식 중')
                    result=recognize_math(img) if exam['config'].get('form')=='math30' else recognize(img,count)
                    sid,added=store.add_scan(eid,source_id,page,pixel_hash(img),png_bytes(img),result,sat_on=sat_on,academy_id=academy_id,class_id=class_id,deduplicate_source_page=path.suffix.lower()=='.pdf')
                    if added:
                        summary['outside_class']+=int(store.set_import_context(sid,academy_id,class_id))
                        summary['added']+=1
                    elif store.retry_failed_scan(sid,result,academy_id,class_id):
                        summary['retried']+=1;summary['failed' if result.error else 'recovered']+=1
                    else:summary['duplicate']+=1
                    if added and result.error:
                        summary['failed']+=1
            except InterruptedError:
                summary['cancelled']=True;break
            except Exception as exc:
                summary['errors'].append(f'{Path(name).name}: {exc}')
                with store.transaction():
                    store.log('import_failed',eid,{'filename':Path(name).name,'error':str(exc)})
    finally:
        store.close()
    return summary
