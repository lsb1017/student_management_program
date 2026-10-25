"""Explicit, auditable removal of retained scan images without removing grades."""
from datetime import datetime,timedelta,timezone
import shutil
from .store import now

ELIGIBLE=('confirmed','excluded','deleted','superseded')
MIN_RETENTION_DAYS=0


def candidates(store,days=7,exam_id=None):
    if type(days) is not int or days<MIN_RETENTION_DAYS:raise ValueError('정리 기간은 0일 이상으로 선택해 주세요.')
    cutoff=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat(timespec='seconds')
    query="""SELECT sc.id,sc.exam_id,e.title,sc.source_id,so.name filename,sc.page,
        sc.created_at,sc.sat_on,sc.status,s.name student,
        length(sc.raw)+COALESCE(length(sc.normalized),0) image_bytes
        FROM scans sc JOIN exams e ON sc.exam_id=e.id JOIN sources so ON so.id=sc.source_id
        LEFT JOIN students s ON s.id=sc.student_id
        WHERE sc.input_mode='scan' AND sc.images_purged_at='' AND sc.created_at<=?
        AND sc.status IN ('confirmed','excluded','deleted','superseded')
        AND (length(sc.raw)>0 OR COALESCE(length(sc.normalized),0)>0)"""
    params=[cutoff]
    if exam_id is not None:query+=' AND sc.exam_id=?';params.append(exam_id)
    return store.rows(query+' ORDER BY e.day,e.id,sc.id',params)


def plan(store,ids,days=7):
    wanted=set(ids);rows=[r for r in candidates(store,days) if r['id'] in wanted]
    selected={r['id'] for r in rows};sources=[];shared=0
    for source_id in sorted({r['source_id'] for r in rows}):
        # Protect every reference, including pending, archived and soft-deleted scans.
        refs=store.rows("SELECT id FROM scans WHERE source_id=? AND input_mode='scan' AND images_purged_at=''",(source_id,))
        if any(r['id'] not in selected for r in refs):shared+=1;continue
        size=store.db.execute('SELECT length(data)+(SELECT COALESCE(SUM(length(data)),0) FROM source_parts WHERE source_id=sources.id) FROM sources WHERE id=?',(source_id,)).fetchone()[0]
        if size:sources.append((source_id,size))
    return {'ids':sorted(selected),'rows':rows,'source_ids':[s[0] for s in sources],
            'bytes':sum(r['image_bytes'] for r in rows)+sum(s[1] for s in sources),'shared_sources':shared}


def database_bytes(store):
    return sum(p.stat().st_size for p in (store.path,store.path.with_name(store.path.name+'-wal')) if p.exists())


def compact(store):
    before=database_bytes(store)
    store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    pages=store.db.execute('PRAGMA page_count').fetchone()[0]-store.db.execute('PRAGMA freelist_count').fetchone()[0]
    required=pages*store.db.execute('PRAGMA page_size').fetchone()[0]*2+16*1024*1024
    if shutil.disk_usage(store.path.parent).free<required:
        raise ValueError('이미지 정리는 저장되었지만 빈 공간 정리에 필요한 디스크 여유 공간이 부족합니다. 여유 공간은 다음 이미지 정리 때 다시 회수합니다.')
    store.db.execute('VACUUM');store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    return max(0,before-database_bytes(store))


def purge(store,ids,days=7):
    before=database_bytes(store)
    with store.transaction():
        selected=plan(store,ids,days)
        if set(selected['ids'])!=set(ids):raise ValueError('대상 상태가 변경되었습니다. 목록을 다시 확인하세요.')
        if not selected['ids']:raise ValueError('정리할 이미지를 선택하세요.')
        stamp=now()
        store.db.executemany("UPDATE scans SET raw=X'',normalized=NULL,images_purged_at=? WHERE id=?",[(stamp,sid) for sid in selected['ids']])
        for source_id in selected['source_ids']:
            store.db.execute('DELETE FROM source_parts WHERE source_id=?',(source_id,))
            store.db.execute("UPDATE sources SET data=X'',purged_at=? WHERE id=?",(stamp,source_id))
        store.log('scan_images_purged',None,{'scan_ids':selected['ids'],'source_ids':selected['source_ids'],'image_bytes':selected['bytes'],'older_than_days':days})
    warning=''
    try:compact(store)
    except Exception as exc:warning=str(exc)
    return {**selected,'freed_bytes':max(0,before-database_bytes(store)),'warning':warning}
