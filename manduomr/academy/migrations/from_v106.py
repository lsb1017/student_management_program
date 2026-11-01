"""1.0.6 백업 → 새 프로그램 자료 1회 이관.

- 내부 학생 ID·시험 ID·답안 ID를 그대로 유지하므로 성적·답안 연결이 바뀌지 않음.
- 모든 학생에게 7자리 학번(휴대전화 뒷 4자리 + 무작위 3자리)을 새로 발급함. 기존 6자리 번호는
  student_codes.previous와 성적 스냅샷의 legacy_code에 남김. 성적 스냅샷의 code는 새 학번으로 바꿈.
- OMR 원본·스캔 이미지 BLOB은 파일함으로 옮기고 DB에는 해시만 둠.
- 이관 후 확정 성적을 다시 계산해 1.0.6 저장값과 같은지 검사하고, 다르면 전체를 취소함.
"""
from __future__ import annotations
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from core.store import Store,pack,now
from core.studentdata import next_code

WEEKDAY=re.compile(r'\(([월화수목금토일])\)\s*$')


def _cols(db,table):
    return [r[1] for r in db.execute(f'PRAGMA table_info({table})')]


def inspect_v106(path):
    path=Path(path)
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        version=db.execute('PRAGMA user_version').fetchone()[0]
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'settings' in tables and db.execute("SELECT 1 FROM settings WHERE name='app'").fetchone():
            raise ValueError('이미 새 프로그램 형식의 백업입니다. 이관할 필요가 없습니다.')
        if version!=10:raise ValueError('만두OMR 1.0.6(데이터 구조 10)에서 만든 최신 백업을 선택하세요.')
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('1.0.6 백업 무결성 검사에 실패했습니다.')
        if db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('1.0.6 백업의 데이터 연결이 손상되었습니다.')
        return {'students':db.execute('SELECT COUNT(*) FROM students').fetchone()[0],
                'exams':db.execute('SELECT COUNT(*) FROM exams').fetchone()[0],
                'scans':db.execute('SELECT COUNT(*) FROM scans').fetchone()[0],
                'confirmed':db.execute("SELECT COUNT(*) FROM scans WHERE status='confirmed'").fetchone()[0],
                'historical':db.execute('SELECT COUNT(*) FROM historical_results').fetchone()[0] if 'historical_results' in tables else 0}


def migrate(source,store:Store,rng=None,progress=lambda text:None):
    """Copy a 1.0.6 backup into an empty store. Returns a summary; raises and rolls back on mismatch."""
    summary=inspect_v106(source)
    if any(store.rows(f'SELECT 1 FROM {table} LIMIT 1') for table in ('students','exams','academies','classes','sources','historical_exams')):
        raise ValueError('이관은 빈 자료에서 1회만 합니다. 새 데이터 폴더에서 실행하세요.')
    old=sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True);old.row_factory=sqlite3.Row
    db=store.db;codes={}
    try:
        db.execute('PRAGMA foreign_keys=OFF')
        with store.transaction():
            progress('학원·반·학생을 옮기고 있어요.')
            for r in old.execute('SELECT id,name FROM academies'):db.execute('INSERT INTO academies(id,name) VALUES(?,?)',(r['id'],r['name']))
            for r in old.execute('SELECT id,academy_id,name FROM classes'):
                match=WEEKDAY.search(r['name'])
                db.execute('INSERT INTO classes(id,academy_id,name,weekday) VALUES(?,?,?,?)',(r['id'],r['academy_id'],r['name'],match.group(1) if match else ''))
            used=set()
            for r in old.execute('SELECT * FROM students ORDER BY id'):
                r=dict(r);phone=r.get('phone') or ''
                tail=(phone[-4:] if len(phone)>=4 else '') or (r['code'][1:5] if len(r['code'])==6 and r['code'].startswith('0') else r['code'][-4:].zfill(4))
                code=next_code(tail,used,rng);used.add(code);codes[r['id']]=(code,r['code'])
                db.execute('INSERT INTO students(id,code,name,class_id,active,school,phone,parent_phone,code_issued_at) VALUES(?,?,?,?,?,?,?,?,?)',
                           (r['id'],code,r['name'],r['class_id'],r['active'],r.get('school',''),phone,r.get('parent_phone',''),now()))
                db.execute('INSERT INTO student_codes(student_id,code,issued_at,reason,previous) VALUES(?,?,?,?,?)',(r['id'],code,now(),'migrated_from_v106',r['code']))
            db.executemany('INSERT OR IGNORE INTO student_classes(student_id,class_id) VALUES(?,?)',[(r[0],r[1]) for r in old.execute('SELECT student_id,class_id FROM student_classes')])
            progress('시험을 옮기고 있어요.')
            for r in old.execute('SELECT * FROM exams ORDER BY id'):
                r=dict(r);config=json.loads(r['config'])
                kind='mock' if config.get('form')=='math30' else 'other'
                db.execute('INSERT INTO exams(id,title,series,subject,round,day,key_json,points_json,revision,config,updated_at,archived,exam_kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (r['id'],r['title'],r['series'],r['subject'],r['round'],r['day'],r['key_json'],r['points_json'],r['revision'],r['config'],r['updated_at'],r['archived'],kind))
            progress('원본 파일을 파일함으로 옮기고 있어요.')
            for r in old.execute('SELECT id,hash,name,purged_at FROM sources ORDER BY id'):
                r=dict(r);file_hash='';payload=''
                if r['hash'].startswith('manual:'):
                    payload=bytes(old.execute('SELECT data FROM sources WHERE id=?',(r['id'],)).fetchone()[0]).decode('utf-8')
                elif not r['purged_at']:
                    parts=[bytes(p[0]) for p in old.execute('SELECT data FROM source_parts WHERE source_id=? ORDER BY part',(r['id'],))]
                    data=b''.join(parts) if parts else bytes(old.execute('SELECT data FROM sources WHERE id=?',(r['id'],)).fetchone()[0])
                    if data:file_hash=store.put_bytes(data,(Path(r['name']).suffix.lstrip('.') or 'bin').lower()[:8])
                db.execute('INSERT INTO sources(id,hash,name,file_hash,payload,purged_at) VALUES(?,?,?,?,?,?)',(r['id'],r['hash'],r['name'],file_hash,payload,r['purged_at']))
            progress('답안과 스캔 이미지를 옮기고 있어요.')
            scan_cols=[c for c in _cols(old,'scans') if c not in ('raw','normalized')]
            for r in old.execute(f"SELECT {','.join(scan_cols)},raw,normalized FROM scans ORDER BY id"):
                r=dict(r);raw=bytes(r.pop('raw') or b'');normalized=r.pop('normalized')
                r['raw_hash']=store.put_bytes(raw,'png') if raw else ''
                r['normalized_hash']=store.put_bytes(bytes(normalized),'png') if normalized else None
                snapshot=json.loads(r['snapshot'])
                if snapshot and r['student_id'] in codes:
                    snapshot['legacy_code']=snapshot.get('code','');snapshot['code']=codes[r['student_id']][0];r['snapshot']=pack(snapshot)
                names=list(r)
                db.execute(f"INSERT INTO scans({','.join(names)}) VALUES({','.join('?'*len(names))})",[r[n] for n in names])
            progress('이전 성적·설정·기록을 옮기고 있어요.')
            for table in ('historical_exams','historical_results'):
                cols=_cols(old,table);rows=[dict(r) for r in old.execute(f'SELECT * FROM {table}')]
                for r in rows:
                    if table=='historical_results':
                        snapshot=json.loads(r['snapshot'])
                        if r['student_id'] in codes:snapshot['legacy_code']=snapshot.get('code','');snapshot['code']=codes[r['student_id']][0]
                        r['snapshot']=pack(snapshot)
                    db.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?'*len(cols))})",[r[c] for c in cols])
            for r in old.execute('SELECT name,value FROM settings'):
                if r['name']!='app':db.execute('INSERT OR REPLACE INTO settings(name,value) VALUES(?,?)',(r['name'],r['value']))
            # 1.0.6 audit rows keep their order and content; ids are reassigned because this
            # session's operator rows already exist. entity_id values still point to kept ids.
            for r in old.execute('SELECT at,kind,entity_id,detail FROM audit ORDER BY id'):
                db.execute('INSERT INTO audit(at,kind,entity_id,detail) VALUES(?,?,?,?)',tuple(r))
            if db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('이관한 자료의 연결 검사에 실패해 이관을 취소했습니다.')
            progress('점수를 다시 계산해 1.0.6 값과 비교하고 있어요.')
            # Re-grade every confirmed answer with the ported scoring rules (effective key/points per elective).
            stored={r['id']:r['score'] for r in store.rows("SELECT id,score FROM scans WHERE status='confirmed'")}
            recalculated={r['id']:Store.score(r['answers'],r['key'],r['points']) for r in store.results()}
            archived={r['id'] for r in store.rows("SELECT sc.id FROM scans sc JOIN exams e ON e.id=sc.exam_id WHERE e.archived=1 AND sc.status='confirmed'")}
            if any(stored[i]!=recalculated[i] for i in recalculated) or set(stored)-archived!=set(recalculated):
                raise ValueError('이관 후 다시 계산한 점수가 1.0.6 저장값과 달라 이관을 취소했습니다.')
            for table,count in (('students',summary['students']),('exams',summary['exams']),('scans',summary['scans'])):
                if db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]!=count:raise ValueError(f'{table} 수가 달라 이관을 취소했습니다.')
            store.log('migrated_from_v106',None,{'source':Path(source).name,**summary})
    finally:
        db.execute('PRAGMA foreign_keys=ON');old.close()
    summary['codes']={sid:{'code':c,'legacy_code':legacy} for sid,(c,legacy) in codes.items()}
    return summary


def students_needing_notice(store):
    """이관 등으로 학번이 바뀌어 아직 안내하지 않은 학생 목록(학번이 바뀌면 무조건 재안내)."""
    return store.rows("""SELECT s.id,s.name,s.code FROM students s WHERE s.active=1 AND NOT EXISTS(
        SELECT 1 FROM notifications n WHERE n.kind='welcome' AND n.student_id=s.id AND n.status IN ('sent','manual')
        AND n.idem_key LIKE 'welcome:'||s.id||':'||s.code||':%') ORDER BY s.name""")
