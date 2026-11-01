"""Change revision and backup file names (ported from 1.0.6 handoff.py).

Lock and transfer state now lives in data/sync_state.json (academy.services.backup).
"""
import re
from datetime import datetime
from hashlib import sha256

BACKUP_NAME=re.compile(r'^(\d{8})_(\d{4})_(.+?)\.omrbackup$')


def filename_part(value):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',str(value).strip()).strip('. ')[:40]


def revision(store,legacy=False):
    # Exporting/previewing existing results does not change the data to hand off.
    where='' if legacy else " WHERE kind NOT IN ('report_exported','batch_report_exported','ranking_exported','import_failed','operator_started','autosaved')"
    row=store.db.execute('SELECT id,at,kind,detail FROM audit'+where+' ORDER BY id DESC LIMIT 1').fetchone()
    return sha256(repr(tuple(row) if row else ()).encode()).hexdigest()


def backup_filename(academy,taken=(),at=None):
    """날짜_저장시간_학원명.omrbackup; 같은 분이면 _2, _3을 붙이고 기존 이름은 쓰지 않음(1.0.6 규칙)."""
    stem=(at or datetime.now()).strftime('%Y%m%d_%H%M')+'_'+(filename_part(academy) or '전체')
    taken=set(taken);sequence=1
    while True:
        name=stem+(f'_{sequence}' if sequence>1 else '')+'.omrbackup'
        if name not in taken:return name
        sequence+=1


def backup_sort_key(item):
    """최신 백업은 파일명의 날짜·시간으로 고르고, 같으면 Drive 수정 시각으로 고름."""
    match=BACKUP_NAME.match(item['name'])
    stamp=match.group(1)+match.group(2) if match else ''
    return (stamp,item.get('modified',''),item['name'])
