from __future__ import annotations
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import hashlib
import json
import os
import re
import sqlite3
import uuid

from .examdata import effective, grade, numeric, validate_config, estimated_percentile

SCHEMA_VERSION = 10


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def pack(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def validate_sat_on(value):
    try:
        parsed=date.fromisoformat(value)
        if parsed.isoformat()!=value:raise ValueError()
        return value
    except (TypeError,ValueError):raise ValueError('응시일자를 YYYY-MM-DD 형식의 실제 날짜로 입력하세요.')


def points_cents(value):
    try:
        val = Decimal(str(value))
        if not val.is_finite() or not 0 <= val <= 10000 or val * 100 != (val * 100).to_integral_value():
            raise ValueError()
        return int(val * 100)
    except (ValueError, InvalidOperation):
        raise ValueError('배점은 0~10,000 사이의 수이며 소수 둘째 자리까지 입력하세요.')


class Store:
    @classmethod
    def open_existing(cls, path, *, readonly=False):
        """Worker connection to an initialized database; never create or migrate."""
        store = cls.__new__(cls)
        store.path = Path(path).resolve()
        mode = 'ro' if readonly else 'rw'
        store.db = sqlite3.connect(store.path.as_uri()+'?mode='+mode, uri=True, timeout=30)
        store.db.row_factory = sqlite3.Row
        store.db.execute('PRAGMA foreign_keys=ON')
        return store

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA busy_timeout=30000')
        self.db.execute('PRAGMA journal_mode=WAL')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in range(SCHEMA_VERSION+1):
            raise ValueError('이 데이터는 다른 버전의 프로그램에서 저장되었습니다.')
        if 0<version<SCHEMA_VERSION:
            self.backup(self.path.parent/'backups'/f'before_upgrade_v{version}_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}.omrbackup')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS academies(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE);
        CREATE TABLE IF NOT EXISTS classes(id INTEGER PRIMARY KEY,academy_id INTEGER NOT NULL REFERENCES academies(id),name TEXT NOT NULL,UNIQUE(academy_id,name));
        CREATE TABLE IF NOT EXISTS students(id INTEGER PRIMARY KEY,code TEXT NOT NULL UNIQUE,name TEXT NOT NULL,class_id INTEGER NOT NULL REFERENCES classes(id),active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS exams(id INTEGER PRIMARY KEY,title TEXT NOT NULL,series TEXT NOT NULL,subject TEXT NOT NULL,round TEXT NOT NULL,day TEXT NOT NULL,key_json TEXT NOT NULL,points_json TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,UNIQUE(series,subject,round));
        CREATE TABLE IF NOT EXISTS sources(id INTEGER PRIMARY KEY,hash TEXT NOT NULL UNIQUE,name TEXT NOT NULL,data BLOB NOT NULL);
        CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY,exam_id INTEGER NOT NULL REFERENCES exams(id),source_id INTEGER NOT NULL REFERENCES sources(id),page INTEGER NOT NULL,pixel_hash TEXT NOT NULL,raw BLOB NOT NULL,normalized BLOB,reading TEXT NOT NULL,answers TEXT NOT NULL,reviewed TEXT NOT NULL,student_id INTEGER REFERENCES students(id),identity_ok INTEGER NOT NULL DEFAULT 0,snapshot TEXT NOT NULL DEFAULT '{}',status TEXT NOT NULL DEFAULT 'pending',error TEXT NOT NULL DEFAULT '',score INTEGER NOT NULL DEFAULT 0,key_revision INTEGER NOT NULL,created_at TEXT NOT NULL,UNIQUE(exam_id,pixel_hash));
        CREATE UNIQUE INDEX IF NOT EXISTS official_result ON scans(exam_id,student_id) WHERE status='confirmed';
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at TEXT NOT NULL,kind TEXT NOT NULL,entity_id INTEGER,detail TEXT NOT NULL);

        ''')

        self.migrate()

    def migrate(self):
        with self.migration_transaction():
            for table,column,definition in [('exams','config',"TEXT NOT NULL DEFAULT '{}'"),('scans','elective','TEXT'),('scans','choice_reading',"TEXT NOT NULL DEFAULT '{}'"),('students','school',"TEXT NOT NULL DEFAULT ''"),('scans','input_mode',"TEXT NOT NULL DEFAULT 'scan'"),('scans','origin_scan_id','INTEGER REFERENCES scans(id)')]:
                cols=[r[1] for r in self.db.execute(f'PRAGMA table_info({table})')]
                if column not in cols:self.db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
            for column in ('phone','parent_phone'):
                cols=[r[1] for r in self.db.execute('PRAGMA table_info(students)')]
                if column not in cols:self.db.execute(f"ALTER TABLE students ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            if 'import_context' not in [r[1] for r in self.db.execute('PRAGMA table_info(scans)')]:self.db.execute("ALTER TABLE scans ADD COLUMN import_context TEXT NOT NULL DEFAULT '{}'")
            self.db.execute('CREATE TABLE IF NOT EXISTS source_parts(source_id INTEGER NOT NULL REFERENCES sources(id),part INTEGER NOT NULL,data BLOB NOT NULL,PRIMARY KEY(source_id,part))')
            self.db.execute('CREATE TABLE IF NOT EXISTS settings(name TEXT PRIMARY KEY,value TEXT NOT NULL)')
            if 'sat_on' not in [r[1] for r in self.db.execute('PRAGMA table_info(scans)')]:
                self.db.execute("ALTER TABLE scans ADD COLUMN sat_on TEXT NOT NULL DEFAULT ''")
            self.db.execute("UPDATE scans SET sat_on=(SELECT day FROM exams WHERE id=scans.exam_id) WHERE sat_on=''")
            for column,definition in [('updated_at',"TEXT NOT NULL DEFAULT ''"),('archived','INTEGER NOT NULL DEFAULT 0')]:
                if column not in [r[1] for r in self.db.execute('PRAGMA table_info(exams)')]:self.db.execute(f'ALTER TABLE exams ADD COLUMN {column} {definition}')
            self.db.execute("UPDATE exams SET updated_at=COALESCE((SELECT MAX(at) FROM audit WHERE entity_id=exams.id AND kind IN ('exam_created','exam_saved','key_changed','report_settings_changed')),'') WHERE updated_at=''")
            from .history import create_tables
            create_tables(self.db)
            from .catalog import apply_catalog
            apply_catalog(self)
            for table,column in [('scans','images_purged_at'),('sources','purged_at')]:
                if column not in [r[1] for r in self.db.execute(f'PRAGMA table_info({table})')]:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
            self.db.execute('CREATE TABLE IF NOT EXISTS student_classes(student_id INTEGER NOT NULL REFERENCES students(id),class_id INTEGER NOT NULL REFERENCES classes(id),PRIMARY KEY(student_id,class_id))')
            self.db.execute('INSERT OR IGNORE INTO student_classes SELECT id,class_id FROM students')
            self.remove_round_uniqueness()
            self.db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')

    @contextmanager
    def migration_transaction(self):
        # SQLite's documented table-rebuild procedure: disable FK enforcement
        # before the transaction, retain IDs, then check all references before commit.
        upgrading=self.db.execute('PRAGMA user_version').fetchone()[0]<SCHEMA_VERSION
        self.db.execute('PRAGMA foreign_keys=OFF')
        try:
            with self.transaction():
                yield
                if upgrading and self.db.execute('PRAGMA foreign_key_check').fetchone():
                    raise ValueError('자료 연결을 확인할 수 없어 업데이트를 취소했습니다.')
        finally:self.db.execute('PRAGMA foreign_keys=ON')

    def remove_round_uniqueness(self):
        sql=self.db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='exams'").fetchone()[0]
        updated=re.sub(r',\s*UNIQUE\s*\(\s*series\s*,\s*subject\s*,\s*round\s*\)', '',sql,flags=re.I)
        if updated==sql:return
        extras=[r[0] for r in self.db.execute("SELECT sql FROM sqlite_master WHERE tbl_name='exams' AND type IN ('index','trigger') AND sql IS NOT NULL")]
        create=re.sub(r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?["`\[]?exams["`\]]?', 'CREATE TABLE exams_v9_new',updated,count=1,flags=re.I)
        columns=','.join('"'+r[1].replace('"','""')+'"' for r in self.db.execute('PRAGMA table_info(exams)'))
        self.db.execute(create)
        self.db.execute(f'INSERT INTO exams_v9_new({columns}) SELECT {columns} FROM exams')
        self.db.execute('DROP TABLE exams')
        self.db.execute('ALTER TABLE exams_v9_new RENAME TO exams')
        for statement in extras:self.db.execute(statement)

    def close(self):
        self.db.close()

    def report_name(self):
        """Instructor research office brand, separate from students' academies."""
        row=self.db.execute("SELECT value FROM settings WHERE name='report_name'").fetchone()
        return row[0] if row else '양지용 수학연구실'

    def set_report_name(self,name):
        name=name.strip()
        if not name or len(name)>60:raise ValueError('강사 연구실명을 1~60자로 입력하세요.')
        with self.transaction():
            self.db.execute("INSERT INTO settings(name,value) VALUES('report_name',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(name,))
            self.log('report_name_changed',None,{'name':name})

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def log(self, kind, entity_id, detail):
        self.db.execute('INSERT INTO audit(at,kind,entity_id,detail) VALUES(?,?,?,?)', (now(),kind,entity_id,pack(detail)))

    def rows(self, sql, params=()):
        return [dict(r) for r in self.db.execute(sql, params)]

    def academy(self, name):
        name = name.strip()
        if not name:
            raise ValueError('학원명을 입력하세요.')
        with self.transaction():
            created=self.db.execute('INSERT OR IGNORE INTO academies(name) VALUES(?)',(name,))
            if created.rowcount:self.log('academy_created',created.lastrowid,{'name':name})
        return self.db.execute('SELECT id FROM academies WHERE name=?',(name,)).fetchone()[0]

    def classroom(self, academy_id, name):
        name = name.strip()
        if not name:
            raise ValueError('반 이름을 입력하세요.')
        with self.transaction():
            created=self.db.execute('INSERT OR IGNORE INTO classes(academy_id,name) VALUES(?,?)',(academy_id,name))
            if created.rowcount:self.log('class_created',created.lastrowid,{'academy_id':academy_id,'name':name})
        return self.db.execute('SELECT id FROM classes WHERE academy_id=? AND name=?',(academy_id,name)).fetchone()[0]

    def classes(self):
        return self.rows('SELECT c.*,a.name academy FROM classes c JOIN academies a ON a.id=c.academy_id ORDER BY a.name,c.name')

    def rename_organization(self,kind,entity_id,name):
        """Rename an existing organization, preserving IDs and historical membership."""
        name=name.strip()
        if kind not in ('academy','class') or not name or len(name)>80:
            raise ValueError('이름을 1~80자로 입력하세요.')
        with self.transaction():
            table='academies' if kind=='academy' else 'classes'
            row=self.db.execute(f'SELECT * FROM {table} WHERE id=?',(entity_id,)).fetchone()
            if not row:raise ValueError('변경할 학원 또는 반을 선택하세요.')
            old=dict(row)
            if name==old['name']:return
            if kind=='academy':
                duplicate=self.db.execute('SELECT id FROM academies WHERE name=? AND id<>?',(name,entity_id)).fetchone()
                class_ids={r[0] for r in self.db.execute('SELECT id FROM classes WHERE academy_id=?',(entity_id,))}
            else:
                duplicate=self.db.execute('SELECT id FROM classes WHERE academy_id=? AND name=? AND id<>?',(old['academy_id'],name,entity_id)).fetchone()
                academy=self.db.execute('SELECT name FROM academies WHERE id=?',(old['academy_id'],)).fetchone()[0]
            if duplicate:raise ValueError('같은 이름이 이미 있습니다. 기존 항목과 합치지는 않습니다.')
            changed=0
            for source in ('scans','historical_results'):
                for record in self.rows(f'SELECT id,snapshot FROM {source}'):
                    snapshot=json.loads(record['snapshot'])
                    if kind=='academy':
                        matches=(snapshot.get('academy_id')==entity_id or
                                 snapshot.get('class_id') in class_ids or
                                 (not snapshot.get('academy_id') and snapshot.get('academy')==old['name']))
                        field='academy'
                    else:
                        matches=(snapshot.get('class_id')==entity_id or
                                 (not snapshot.get('class_id') and snapshot.get('academy')==academy and snapshot.get('classroom')==old['name']))
                        field='classroom'
                    if matches:
                        snapshot[field]=name
                        self.db.execute(f'UPDATE {source} SET snapshot=? WHERE id=?',(pack(snapshot),record['id']))
                        changed+=1
            self.db.execute(f'UPDATE {table} SET name=? WHERE id=?',(name,entity_id))
            self.log('organization_renamed',entity_id,{'kind':kind,'before':old['name'],'after':name,'updated_snapshots':changed})

    def save_student(self, code, name, class_id, student_id=None, active=True, school=''):
        code, name = code.strip(), name.strip()
        if not re.fullmatch(r'[0-9]{1,6}',code) or not name or len(name)>60:
            raise ValueError('학생번호는 숫자 1~6자리, 이름은 1~60자로 입력하세요. 번호는 6자리로 맞춰 저장합니다.')
        code = code.zfill(6)
        with self.transaction():
            if student_id:
                self.db.execute('UPDATE students SET code=?,name=?,class_id=?,active=? WHERE id=?',(code,name,class_id,int(active),student_id))
            else:
                student_id = self.db.execute('INSERT INTO students(code,name,class_id,active) VALUES(?,?,?,?)',(code,name,class_id,int(active))).lastrowid
            self.db.execute('UPDATE students SET school=? WHERE id=?',(school.strip()[:80],student_id))
            self._sync_primary(student_id,class_id)
            self.log('student_saved',student_id,{'code':code,'name':name,'class_id':class_id,'active':active})
        return student_id

    def students(self, query=''):
        escaped = query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
        return self.rows("SELECT s.*,c.name classroom,a.name academy,a.id academy_id FROM students s JOIN classes c ON c.id=s.class_id JOIN academies a ON a.id=c.academy_id WHERE s.name LIKE ? ESCAPE '\\' OR s.code LIKE ? ESCAPE '\\' OR c.name LIKE ? ESCAPE '\\' OR a.name LIKE ? ESCAPE '\\' ORDER BY s.name,s.code",tuple(['%'+escaped+'%']*4))

    def student(self, sid):
        return self.rows('SELECT s.*,c.name classroom,a.name academy,a.id academy_id FROM students s JOIN classes c ON c.id=s.class_id JOIN academies a ON a.id=c.academy_id WHERE s.id=?',(sid,))[0]

    def _sync_primary(self,sid,cid):
        if self.db.execute('SELECT COUNT(*) FROM student_classes WHERE student_id=?',(sid,)).fetchone()[0]<=1:self.db.execute('DELETE FROM student_classes WHERE student_id=?',(sid,))
        self.db.execute('INSERT OR IGNORE INTO student_classes VALUES(?,?)',(sid,cid))

    def memberships(self,sid):
        return self.rows('SELECT c.id class_id,c.name classroom,a.id academy_id,a.name academy FROM student_classes m JOIN classes c ON c.id=m.class_id JOIN academies a ON a.id=c.academy_id WHERE m.student_id=? ORDER BY a.name,c.name',(sid,))

    def in_class(self,sid,class_id=None,academy_id=None):
        return any((class_id is None or m['class_id']==class_id) and (academy_id is None or m['academy_id']==academy_id) for m in self.memberships(sid))

    def student_for_class(self,sid,class_id=None):
        s=self.student(sid)
        if class_id is not None:
            member=next((m for m in self.memberships(sid) if m['class_id']==class_id),None)
            if member:s.update(member)
        return s

    def set_student_classes(self,sid,ids):
        ids=list(dict.fromkeys(ids))
        if not ids:raise ValueError('소속 반을 하나 이상 선택하세요.')
        with self.transaction():
            for cid in ids:
                if not self.db.execute('SELECT 1 FROM classes WHERE id=?',(cid,)).fetchone():raise ValueError('반을 다시 선택하세요.')
            self.db.execute('DELETE FROM student_classes WHERE student_id=?',(sid,))
            self.db.executemany('INSERT INTO student_classes VALUES(?,?)',[(sid,cid) for cid in ids])
            self.db.execute('UPDATE students SET class_id=? WHERE id=?',(ids[0],sid))
            self.log('student_classes_saved',sid,{'class_ids':ids})

    def allocate_student_code(self,phone):
        if not re.fullmatch(r'[0-9]{4}',phone):raise ValueError('전화번호 뒤 4자리를 입력하세요.')
        used={r['code'] for r in self.students()}
        for suffix in range(1,10):
            code=(phone+str(suffix)).zfill(6)
            if code not in used:return code
        raise ValueError('같은 뒤 4자리의 구분번호 1~9가 모두 사용 중입니다. 별도 번호를 지정하세요.')

    def save_student_contact(self,name,phone,school='',parent_phone='',class_id=None,student_id=None,active=True):
        from .studentdata import validate_student, next_code
        data=validate_student(dict(name=name,phone=phone,school=school,parent_phone=parent_phone))
        with self.transaction():
            return self._save_contact(data,class_id,student_id,active)

    def _save_contact(self,data,class_id=None,student_id=None,active=True):
        from .studentdata import next_code
        old=self.student(student_id) if student_id else None
        used={r[0] for r in self.db.execute('SELECT code FROM students')}
        tail=data['phone'][-4:]
        code=old['code'] if old and len(old['code'])==6 and old['code'][0]=='0' and old['code'][1:5]==tail and old['code'][-1] in '123456789' else next_code(tail,used)
        if class_id is None:
            self.db.execute("INSERT OR IGNORE INTO academies(name) VALUES('미지정')")
            aid=self.db.execute("SELECT id FROM academies WHERE name='미지정'").fetchone()[0]
            self.db.execute("INSERT OR IGNORE INTO classes(academy_id,name) VALUES(?,'미배정')",(aid,))
            class_id=self.db.execute("SELECT id FROM classes WHERE academy_id=? AND name='미배정'",(aid,)).fetchone()[0]
        args=(code,data['name'],class_id,int(active),data['school'],data['phone'],data['parent_phone'])
        if old:self.db.execute('UPDATE students SET code=?,name=?,class_id=?,active=?,school=?,phone=?,parent_phone=? WHERE id=?',args+(student_id,))
        else:student_id=self.db.execute('INSERT INTO students(code,name,class_id,active,school,phone,parent_phone) VALUES(?,?,?,?,?,?,?)',args).lastrowid
        self._sync_primary(student_id,class_id)
        self.log('student_saved',student_id,{'code':code,'name':data['name'],'class_id':class_id,'active':active})
        return student_id

    def import_students(self,rows):
        from .studentdata import plan_students
        with self.transaction():
            plan=plan_students(self,rows)
            errors=[r['message'] for r in plan if r['action']=='error']
            if errors:raise ValueError('\n'.join(errors))
            added=[]
            for r in plan:
                if r['action'] not in ('add','link'):continue
                ids=[]
                for classroom in r.get('classrooms') or ['미배정']:
                    academy=r.get('academy') or '미지정'
                    self.db.execute('INSERT OR IGNORE INTO academies(name) VALUES(?)',(academy,))
                    aid=self.db.execute('SELECT id FROM academies WHERE name=?',(academy,)).fetchone()[0]
                    self.db.execute('INSERT OR IGNORE INTO classes(academy_id,name) VALUES(?,?)',(aid,classroom))
                    ids.append(self.db.execute('SELECT id FROM classes WHERE academy_id=? AND name=?',(aid,classroom)).fetchone()[0])
                sid=r['student_id'] if r['action']=='link' else self._save_contact(r,ids[0])
                self.db.executemany('INSERT OR IGNORE INTO student_classes VALUES(?,?)',[(sid,cid) for cid in ids])
                added.append(sid)
            self.log('students_imported',None,{'added':len(added),'skipped':len(plan)-len(added)})
        return added,len(plan)-len(added)

    def save_exam(self, title, series, subject, round_no, day, key, points, exam_id=None, config=None):
        if not all(str(v).strip() for v in [title,series,subject,round_no]):raise ValueError('시험명·시리즈·과목·회차를 입력하세요.')
        datetime.strptime(day,'%Y-%m-%d')
        if not 1<=len(key)<=60 or len(key)!=len(points):raise ValueError('문항 수와 정답·배점 수를 확인하세요.')
        old=self.exam(exam_id) if exam_id else None
        cents=[points_cents(p) for p in points]
        if sum(cents)<=0:raise ValueError('총 배점은 0보다 커야 합니다.')
        config=config if config is not None else (old['config'] if old else {})
        if not old:
            from .catalog import reference
            entry=reference(title)
            if entry and config.get('form')=='math30':
                from copy import deepcopy
                config=deepcopy(config)
                for choice,values in entry['cuts'].items():
                    if not config.setdefault('cuts',{}).get(choice):config['cuts'][choice]=values
                config['cut_note']=entry.get('note','');config['cut_source']=entry['source']
        config=validate_config(config,key,cents,points_cents)
        new={'key':key,'points':cents,'config':config}
        with self.transaction():
            duplicate=self.db.execute('SELECT id,archived FROM exams WHERE title=? AND archived=0 AND id<>?',(title.strip(),exam_id or -1)).fetchone()
            if duplicate and (not old or old['title']!=title.strip()):
                raise ValueError('동일한 시험명이 이미 있어요.\n기존 시험을 수정하거나, 시험명을 다르게 입력해 주세요.')
            if old:
                scans=self.rows('SELECT id,answers,reviewed,status,elective FROM scans WHERE exam_id=?',(exam_id,))
                if scans and (len(old['key'])!=len(key) or old['config'].get('form','local60')!=config['form']):raise ValueError('답안이 있는 시험의 양식·문항 수는 바꿀 수 없습니다.')
                changed=any(effective(old,c)[f]!=effective(new,c)[f] for c in ('0','1','2','3') for f in ('key','points'))
                revision=old['revision']+int(changed)
                self.db.execute('UPDATE exams SET title=?,series=?,subject=?,round=?,day=?,key_json=?,points_json=?,revision=?,config=? WHERE id=?',(title.strip(),series.strip(),subject.strip(),str(round_no).strip(),day,pack(key),pack(cents),revision,pack(config),exam_id))
                if changed:
                    for row in scans:
                        previous,current=effective(old,row['elective']),effective(new,row['elective'])
                        answers,reviewed=json.loads(row['answers']),json.loads(row['reviewed'])
                        for i in range(len(key)):
                            if current['key'][i]!=previous['key'][i]:reviewed[i]=False
                        key_changed=previous['key']!=current['key']
                        status='pending' if row['status']=='confirmed' and (key_changed or not current['configured']) else row['status']
                        self.db.execute('UPDATE scans SET score=?,reviewed=?,status=?,key_revision=? WHERE id=?',(self.score(answers,current['key'],current['points']),pack(reviewed),status,revision,row['id']))
                    self.log('key_changed',exam_id,{'before_key':old['key'],'key':key,'points':cents,'before_config':old['config'],'config':config,'revision':revision})
                elif old['config']!=config:self.log('report_settings_changed',exam_id,{'before':old['config'],'after':config})
            else:
                exam_id=self.db.execute('INSERT INTO exams(title,series,subject,round,day,key_json,points_json,config) VALUES(?,?,?,?,?,?,?,?)',(title.strip(),series.strip(),subject.strip(),str(round_no).strip(),day,pack(key),pack(cents),pack(config))).lastrowid
                self.log('exam_created',exam_id,{'key':key,'points':cents,'config':config})
            self.db.execute('UPDATE exams SET updated_at=? WHERE id=?',(now(),exam_id))
            self.log('exam_saved',exam_id,{'title':title})
            if not old:
                self.db.execute('INSERT OR IGNORE INTO settings(name,value) VALUES(?,?)',(f'reference_v042_exams_{exam_id}','created with current settings'))
        return exam_id

    def exam(self,eid):
        row = dict(self.db.execute('SELECT * FROM exams WHERE id=?',(eid,)).fetchone())
        row['key'],row['points'] = json.loads(row['key_json']),json.loads(row['points_json'])
        row['config']=json.loads(row['config'])
        return row

    def exams(self):
        return self.rows('SELECT * FROM exams WHERE archived=0 ORDER BY day DESC,id DESC')

    def archive_exams(self,ids):
        ids=list(dict.fromkeys(ids))
        with self.transaction():
            for eid in ids:
                if not self.db.execute('SELECT id FROM exams WHERE id=? AND archived=0',(eid,)).fetchone():raise ValueError('삭제할 시험을 다시 선택하세요.')
            for eid in ids:self.db.execute('UPDATE exams SET archived=1 WHERE id=?',(eid,))
            self.log('exams_archived',None,{'ids':ids})

    def restore_exams(self,ids):
        with self.transaction():
            for eid in ids:self.db.execute('UPDATE exams SET archived=0 WHERE id=?',(eid,))
            self.log('exams_restored',None,{'ids':list(ids)})

    def relink_unresolved(self,eid,academy_id,class_id):
        """Re-evaluate stored identity readings, never override a manual or existing link."""
        from types import SimpleNamespace
        from .identity import resolve_student
        if academy_id is None or class_id is None:return 0
        linked=0
        with self.transaction():
            for r in self.rows("SELECT id,import_context FROM scans WHERE exam_id=? AND student_id IS NULL AND status='pending'",(eid,)):
                context=json.loads(r['import_context']);reading=context.get('identity_reading')
                if context.get('manual_link') or not reading:continue
                # Old pages without a known import class require an explicit manual choice.
                if context.get('class_id')!=class_id or context.get('academy_id') not in (None,academy_id):continue
                student,detail=resolve_student(self.db,SimpleNamespace(code=reading.get('recognized_code'),identity_reading=reading),academy_id,class_id)
                context['identity_reading']=detail
                if student:
                    context.pop('notice',None)
                    self.db.execute('UPDATE scans SET student_id=?,identity_ok=0,import_context=? WHERE id=?',(student['id'],pack(context),r['id']))
                    self.log('student_auto_linked',r['id'],{'student_id':student['id'],'method':detail['method']});linked+=1
                elif context!=json.loads(r['import_context']):
                    self.db.execute('UPDATE scans SET import_context=? WHERE id=?',(pack(context),r['id']))
                    self.log('import_context_changed',r['id'],{'context':context})
        return linked

    @staticmethod
    def score(answers,key,points):
        return sum(p for a,k,p in zip(answers,key,points) if k is not None and a==k)

    def source(self,path,cancelled=lambda:False):
        path=Path(path)
        digest=hashlib.sha256()
        with path.open('rb') as f:
            while chunk:=f.read(1024*1024):
                if cancelled():raise InterruptedError('파일 처리를 중단했습니다.')
                digest.update(chunk)
        digest=digest.hexdigest()
        with self.transaction():
            old=self.db.execute('SELECT id,purged_at FROM sources WHERE hash=?',(digest,)).fetchone()
            if old and not old['purged_at']:return old[0]
            if old:
                sid=old[0];self.db.execute('DELETE FROM source_parts WHERE source_id=?',(sid,))
                self.db.execute("UPDATE sources SET purged_at='',data=X'' WHERE id=?",(sid,))
            else:sid=self.db.execute('INSERT INTO sources(hash,name,data) VALUES(?,?,?)',(digest,path.name,b'')).lastrowid
            check=hashlib.sha256()
            with path.open('rb') as f:
                part=0
                while chunk:=f.read(1024*1024):
                    if cancelled():raise InterruptedError('파일 처리를 중단했습니다.')
                    self.db.execute('INSERT INTO source_parts(source_id,part,data) VALUES(?,?,?)',(sid,part,chunk));part+=1;check.update(chunk)
            if check.hexdigest()!=digest:raise ValueError('불러오는 중 파일이 변경되었습니다. 다시 시도하세요.')
            self.log('source_restored' if old else 'source_imported',sid,{'filename':path.name})
        return sid

    def export_source(self,source_id,path):
        row=self.db.execute('SELECT purged_at FROM sources WHERE id=?',(source_id,)).fetchone()
        if not row or row[0]:raise ValueError('이미지 정리로 원본 파일이 제거되었습니다.')
        with Path(path).open('wb') as f:
            rows=self.db.execute('SELECT data FROM source_parts WHERE source_id=? ORDER BY part',(source_id,));first=rows.fetchone()
            if first:
                f.write(first[0])
                for row in rows:f.write(row[0])
            else:f.write(self.db.execute('SELECT data FROM sources WHERE id=?',(source_id,)).fetchone()[0])

    def set_import_context(self,sid,academy_id=None,class_id=None):
        row=self.scan(sid);context=row['import_context'].copy();context.update(academy_id=academy_id,class_id=class_id);outside=False
        if row['student_id']:
            s=self.student(row['student_id']);actual=self.db.execute('SELECT academy_id FROM classes WHERE id=?',(s['class_id'],)).fetchone()[0]
            outside=not self.in_class(s['id'],class_id,academy_id)
            if outside:context['notice']=f"인식 학생 {s['name']} ({s['code']})은 선택한 학원·반 소속이 아닙니다. 원본을 보고 학생을 다시 연결하세요."
        with self.transaction():
            if context!=row['import_context'] or outside:
                self.db.execute('UPDATE scans SET import_context=? WHERE id=?',(pack(context),sid))
                if outside:self.db.execute('UPDATE scans SET student_id=NULL,identity_ok=0 WHERE id=?',(sid,))
                self.log('import_context_changed',sid,{'context':context,'unlinked':outside})
        return outside

    def add_scan(self,eid,source_id,page,pixel_hash,raw,result,sat_on=None,academy_id=None,class_id=None,deduplicate_source_page=False):
        sat_on=validate_sat_on(sat_on if sat_on is not None else date.today().isoformat())
        existing = self.db.execute("SELECT id FROM scans WHERE exam_id=? AND status!='deleted' AND (pixel_hash=? OR (? AND source_id=? AND page=?))",(eid,pixel_hash,int(deduplicate_source_page),source_id,page)).fetchone()
        if existing:
            retained=self.db.execute('SELECT images_purged_at FROM scans WHERE id=?',(existing[0],)).fetchone()
            if retained and retained[0]:
                with self.transaction():
                    self.db.execute("UPDATE scans SET raw=?,normalized=?,images_purged_at='' WHERE id=?",(raw,result.normalized,existing[0]))
                    self.log('scan_images_restored',existing[0],{'source_id':source_id,'page':page})
            return existing[0], False
        exam=effective(self.exam(eid),getattr(result,'elective',None))
        answers=[r['answer'] for r in result.answers]
        # Every question requires review in the pilot; clear answers can be bulk acknowledged after viewing.
        reviewed=[False]*len(answers)
        from .identity import resolve_student
        student,identity=resolve_student(self.db,result,academy_id,class_id)
        with self.transaction():
            sid=self.db.execute('INSERT INTO scans(exam_id,source_id,page,pixel_hash,raw,normalized,reading,answers,reviewed,student_id,status,error,score,key_revision,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(eid,source_id,page,pixel_hash,raw,result.normalized,pack(result.answers),pack(answers),pack(reviewed),student[0] if student else None,'failed' if result.error else 'pending',result.error,self.score(answers,exam['key'],exam['points']),exam['revision'],now())).lastrowid
            self.db.execute('UPDATE scans SET elective=?,choice_reading=?,sat_on=? WHERE id=?',(getattr(result,'elective',None),pack(getattr(result,'choice_reading',{})),sat_on,sid))
            self.db.execute('UPDATE scans SET import_context=? WHERE id=?',(pack({'identity_reading':identity,'academy_id':academy_id,'class_id':class_id}),sid))
            self.log('scan_imported',sid,{'source_id':source_id,'page':page,'rotation':result.rotation,'recognized_code':result.code,'error':result.error,'sat_on':sat_on})
        return sid,True

    def scan(self,sid,images=True):
        columns='*' if images else ','.join(r[1] for r in self.db.execute('PRAGMA table_info(scans)') if r[1] not in ('raw','normalized'))
        row = dict(self.db.execute(f'SELECT {columns} FROM scans WHERE id=?',(sid,)).fetchone())
        for key in ('reading','answers','reviewed','snapshot','choice_reading','import_context'):
            row[key]=json.loads(row[key])
        return row

    def retry_failed_scan(self,sid,result,academy_id=None,class_id=None):
        """Replace only untouched failed recognition; retain source, date and audit."""
        with self.transaction():
            row=self.scan(sid)
            if row['status']!='failed' or row['input_mode']!='scan' or any(row['reviewed']) or row['identity_ok']:
                return False
            exam=effective(self.exam(row['exam_id']),getattr(result,'elective',None))
            answers=[r['answer'] for r in result.answers]
            if len(answers)!=len(exam['key']):raise ValueError('재인식 문항 수가 시험과 다릅니다.')
            from .identity import resolve_student
            context=row['import_context'].copy()
            if context.get('academy_id') is None and context.get('class_id') is None:
                context.update(academy_id=academy_id,class_id=class_id)
            student,identity=resolve_student(self.db,result,context.get('academy_id'),context.get('class_id'))
            if identity:context['identity_reading']=identity
            outside=student and not self.in_class(student['id'],context.get('class_id'),context.get('academy_id'))
            if outside:context['notice']='인식 학생은 선택한 학원·반 소속이 아닙니다. 원본을 보고 학생을 다시 연결하세요.'
            self.db.execute('UPDATE scans SET normalized=?,reading=?,answers=?,reviewed=?,student_id=?,identity_ok=0,status=?,error=?,score=?,key_revision=?,elective=?,choice_reading=?,import_context=? WHERE id=?',
                (result.normalized,pack(result.answers),pack(answers),pack([False]*len(answers)),student['id'] if student and not outside else None,'failed' if result.error else 'pending',result.error,self.score(answers,exam['key'],exam['points']),exam['revision'],getattr(result,'elective',None),pack(getattr(result,'choice_reading',{})),pack(context),sid))
            self.log('scan_retried',sid,{'before_error':row['error'],'before_reading':row['reading'],'before_answers':row['answers'],'before_student':row['student_id'],'before_elective':row['elective'],'error':result.error,'recognized_code':result.code,'rotation':result.rotation,'sat_on':row['sat_on']})
        return True

    def reread_scan(self,sid,result,academy_id=None,class_id=None):
        """Refresh pending recognition while keeping reviewed and manually edited values."""
        with self.transaction():
            row=self.scan(sid)
            if row['status'] not in ('pending','failed') or row['input_mode']!='scan':return False
            if result.error and row['status']=='pending':raise ValueError('다시 읽기에 실패해 기존 답안을 유지했습니다: '+result.error)
            context=row['import_context'].copy()
            if context.get('class_id') is None:context.update(academy_id=academy_id,class_id=class_id)
            if class_id is not None and context.get('class_id')!=class_id:return False
            if academy_id is not None and context.get('academy_id') not in (None,academy_id):return False
            from .identity import resolve_student
            candidate,identity=resolve_student(self.db,result,context.get('academy_id'),context.get('class_id'))
            if identity:context['identity_reading']=identity
            student=row['student_id'] or (candidate['id'] if candidate and not context.get('manual_link') else None)
            if row['student_id'] and candidate and row['student_id']!=candidate['id']:
                context['notice']='새 인식 결과가 연결된 학생과 다릅니다. 기존 연결을 유지했으니 학생을 확인하세요.'
            choice=row['elective'] if context.get('manual_elective') or row['identity_ok'] else getattr(result,'elective',None)
            exam=effective(self.exam(row['exam_id']),choice)
            if len(result.answers)!=len(row['answers']):raise ValueError('재인식 문항 수가 시험과 다릅니다.')
            answers=[];reading=[];kept=[]
            for q,new in enumerate(result.answers):
                preserve=row['reviewed'][q] or row['answers'][q]!=row['reading'][q]['answer']
                answers.append(row['answers'][q] if preserve else new['answer'])
                reading.append(row['reading'][q] if preserve else new)
                if preserve:kept.append(q+1)
            checks=row['reviewed'].copy()
            if choice!=row['elective']:
                for q in range(22,len(checks)):checks[q]=False
            context['recognizer_version']='0.4.1'
            self.db.execute('UPDATE scans SET normalized=?,reading=?,answers=?,reviewed=?,student_id=?,identity_ok=0,status=?,error=?,score=?,key_revision=?,elective=?,choice_reading=?,import_context=? WHERE id=?',
                (result.normalized,pack(reading),pack(answers),pack(checks),student,'failed' if result.error else 'pending',result.error,self.score(answers,exam['key'],exam['points']),exam['revision'],choice,pack(getattr(result,'choice_reading',{})),pack(context),sid))
            self.log('scan_reread',sid,{'before_answers':row['answers'],'before_reading':row['reading'],'before_student':row['student_id'],'before_elective':row['elective'],'preserved_questions':kept,'recognized_code':result.code})
        return True

    def scans(self,eid):
        return self.rows("SELECT sc.id,sc.student_id,sc.status,sc.score,sc.error,sc.page,sc.reviewed,sc.reading,sc.answers,sc.identity_ok,sc.elective,sc.input_mode,sc.import_context,sc.snapshot,sc.sat_on,sc.images_purged_at,s.name,s.code,s.class_id,c.academy_id,so.name filename FROM scans sc LEFT JOIN students s ON s.id=sc.student_id LEFT JOIN classes c ON c.id=s.class_id JOIN sources so ON so.id=sc.source_id WHERE sc.exam_id=? AND sc.status!='deleted' ORDER BY sc.id",(eid,))

    def delete_scans(self,eid,ids):
        entries=[];batch=uuid.uuid4().hex
        with self.transaction():
            for sid in dict.fromkeys(ids):
                row=self.scan(sid)
                if row['exam_id']!=eid:raise ValueError('선택한 시험의 답안만 삭제할 수 있습니다.')
                if row['status']=='deleted':continue
                entries.append({'id':sid,'status':row['status'],'pixel_hash':row['pixel_hash'],'revision':row['key_revision']})
                # Retain original pages for undo, but permit a clean re-import.
                self.db.execute("UPDATE scans SET status='deleted',pixel_hash=? WHERE id=?",('deleted:'+batch+':'+row['pixel_hash'],sid))
            if entries:self.log('scans_deleted',eid,{'batch':batch,'entries':entries})
        return len(entries)

    def restore_deleted_scans(self,eid,return_ids=False):
        with self.transaction():
            for event in self.rows("SELECT detail FROM audit WHERE kind='scans_deleted' AND entity_id=? ORDER BY id DESC",(eid,)):
                detail=json.loads(event['detail']);entries=[]
                for entry in detail['entries']:
                    row=self.scan(entry['id'])
                    if row['status']=='deleted' and row['pixel_hash']=='deleted:'+detail['batch']+':'+entry['pixel_hash']:entries.append((entry,row))
                if not entries:continue
                for entry,row in entries:
                    if row['import_context'].get('student_merge') and sum(1 for _,candidate in entries if candidate['student_id']==row['student_id'])>1:raise ValueError('합친 학생의 같은 시험 기록 여러 개를 동시에 복구할 수 없습니다.')
                    if row['import_context'].get('merge_locked_deleted'):raise ValueError('학생 합치기에서 정리한 기록은 삭제 취소할 수 없습니다. 합치기 전 안전 백업을 확인해 주세요.')
                    if row['import_context'].get('student_merge') and (self.db.execute("SELECT 1 FROM scans WHERE student_id=? AND exam_id=? AND status!='deleted' AND id<>?",(row['student_id'],eid,row['id'])).fetchone() or self.db.execute('SELECT 1 FROM historical_results r JOIN historical_exams e ON e.id=r.exam_id WHERE r.student_id=? AND e.linked_exam_id=?',(row['student_id'],eid)).fetchone()):raise ValueError('합친 학생에게 같은 시험 기록이 있어 중복 복구할 수 없습니다.')
                    duplicate=self.db.execute('SELECT id FROM scans WHERE exam_id=? AND pixel_hash=?',(eid,entry['pixel_hash'])).fetchone()
                    if duplicate:raise ValueError('같은 원본을 이미 다시 불러왔습니다. 새 답안이 있으므로 중복 복구하지 않습니다.')
                for entry,row in entries:
                    state=entry['status']
                    if state=='confirmed' and (self.official_id(eid,row['student_id']) or row['key_revision']!=entry['revision']):state='pending'
                    self.db.execute('UPDATE scans SET status=?,pixel_hash=? WHERE id=?',(state,entry['pixel_hash'],entry['id']))
                self.log('scan_deletion_undone',eid,{'batch':detail['batch'],'ids':[entry['id'] for entry,row in entries]})
                return [entry['id'] for entry,row in entries] if return_ids else len(entries)
        return [] if return_ids else 0

    def student_attempt(self,eid,student_id):
        row=self.db.execute("SELECT id FROM scans WHERE exam_id=? AND student_id=? AND status IN ('pending','confirmed','failed') ORDER BY CASE WHEN input_mode='manual' AND status='pending' THEN 0 WHEN status='confirmed' THEN 1 ELSE 2 END,id DESC LIMIT 1",(eid,student_id)).fetchone()
        return self.scan(row[0]) if row else None

    def official_id(self,eid,student_id):
        row=self.db.execute("SELECT id FROM scans WHERE exam_id=? AND student_id=? AND status='confirmed'",(eid,student_id)).fetchone()
        return row[0] if row else None

    def save_manual(self,eid,student_id,elective,answers,entered,expected_revision,existing_id=None,expected_official_id=None,replace=False,sat_on=None,class_id=None):
        """Save manual work atomically. Incomplete drafts never enter averages.

        None+entered=True is an explicit X/unanswered response. None+False is
        unentered work. Prior confirmed scan/manual records are preserved.
        """
        base=self.exam(eid);exam=effective(base,elective);student=self.student_for_class(student_id,class_id)
        if base['revision']!=expected_revision:raise ValueError('시험 정답이 바뀌었습니다. 시험을 다시 선택해 정답을 확인하세요.')
        if not exam['configured']:raise ValueError('선택과목과 해당 과목의 정답을 확인하세요.')
        if len(answers)!=len(exam['key']) or len(entered)!=len(answers):raise ValueError('문항 수가 다릅니다.')
        for i,a in enumerate(answers):
            if a is not None and (type(a)!=int or not (-1<=a<=999 if numeric(base,i+1) else a==-1 or 1<=a<=5)):
                raise ValueError(f'{i+1}번 학생 답안을 확인하세요. 선다형은 1~5, 숫자답안은 0~999입니다.')
            if a is not None and not entered[i]:raise ValueError('답안 입력 상태를 확인하세요.')
        complete=all(entered);existing=self.scan(existing_id) if existing_id else None
        sat_on=validate_sat_on(sat_on if sat_on is not None else existing['sat_on'] if existing else date.today().isoformat())
        if existing and (existing['exam_id']!=eid or existing['student_id']!=student_id):raise ValueError('선택한 학생·시험과 기존 답안이 다릅니다.')
        with self.transaction():
            official=self.official_id(eid,student_id)
            if official!=expected_official_id:raise ValueError('기존 성적이 변경되었습니다. 학생을 다시 선택한 뒤 저장하세요.')
            if complete and official and not replace:raise ValueError('DUPLICATE: 기존 확정 성적이 있습니다. 교체 여부를 확인하세요.')
            reuse=existing and existing['input_mode']=='manual' and existing['status']=='pending'
            snapshot=existing['snapshot'] if existing and existing['snapshot'] else student
            if reuse:sid=existing['id']
            else:
                uid='manual:'+uuid.uuid4().hex;payload=pack({'mode':'manual','student_id':student_id,'exam_id':eid,'answers':answers,'entered':entered}).encode('utf-8')
                source=self.db.execute('INSERT INTO sources(hash,name,data) VALUES(?,?,?)',(uid,'수기 입력 · '+student['name'],payload)).lastrowid
                reading=[{'answer':a,'flag':'manual','levels':[]} for a in answers]
                sid=self.db.execute("INSERT INTO scans(exam_id,source_id,page,pixel_hash,raw,reading,answers,reviewed,student_id,identity_ok,snapshot,key_revision,created_at,elective,input_mode,origin_scan_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(eid,source,1,uid,b'',pack(reading),pack(answers),pack(entered),student_id,1,pack(snapshot),base['revision'],now(),elective,'manual',official)).lastrowid
            score=self.score(answers,exam['key'],exam['points'])
            if complete and official:self.db.execute("UPDATE scans SET status='superseded' WHERE id=?",(official,))
            self.db.execute('UPDATE scans SET answers=?,reviewed=?,elective=?,score=?,status=?,key_revision=?,identity_ok=1 WHERE id=?',(pack(answers),pack([bool(v) for v in entered]),elective,score,'confirmed' if complete else 'pending',base['revision'],sid))
            self.db.execute('UPDATE scans SET origin_scan_id=?,sat_on=? WHERE id=?',(None if complete else official,sat_on,sid))
            self.log('manual_saved',sid,{'before':existing['answers'] if existing else None,'answers':answers,'entered':entered,'elective':elective,'confirmed':complete,'replaced':official if complete else None,'origin':existing_id,'score':score,'sat_on':sat_on})
        return sid

    def save_review(self,sid,student_id,answers,reviewed,identity_ok,note='',elective='current',sat_on=None,allow_reopen=False):
        row=self.scan(sid,images=False)
        sat_on=validate_sat_on(sat_on if sat_on is not None else row['sat_on'])
        if row['status']=='deleted' or (row['status'] in ('confirmed','superseded','excluded') and not allow_reopen):
            raise ValueError('확정/보관 답안은 먼저 검수를 다시 열어 주세요.')
        base=self.exam(row['exam_id'])
        elective=row['elective'] if elective=='current' else str(elective) if elective is not None else None
        exam=effective(base,elective)
        if len(answers)!=len(exam['key']) or len(reviewed)!=len(answers) or any(a is not None and (type(a)!=int or not (-1<=a<=999 if numeric(base,i+1) else -1<=a<=5)) for i,a in enumerate(answers)):
            raise ValueError('답안의 길이 또는 값이 올바르지 않습니다.')
        snapshot=self.student_for_class(student_id,row['import_context'].get('class_id')) if student_id else {}
        if student_id==row['student_id'] and row['snapshot']:
            snapshot=row['snapshot']
        with self.transaction():
            self.db.execute('UPDATE scans SET student_id=?,identity_ok=?,snapshot=?,answers=?,reviewed=?,score=?,status=?,key_revision=? WHERE id=?',(student_id,int(identity_ok),pack(snapshot),pack(answers),pack([bool(v) for v in reviewed]),self.score(answers,exam['key'],exam['points']),'pending',exam['revision'],sid))
            self.db.execute('UPDATE scans SET elective=?,sat_on=? WHERE id=?',(elective,sat_on,sid))
            context=row['import_context'].copy()
            if student_id!=row['student_id']:context['manual_link']=bool(student_id)
            if elective!=row['elective']:context['manual_elective']=True
            self.db.execute('UPDATE scans SET import_context=? WHERE id=?',(pack(context),sid))
            self.log('review_saved',sid,{'before':row['answers'],'after':answers,'before_student':row['student_id'],'student':student_id,'reviewed':reviewed,'identity_ok':identity_ok,'note':note,'before_elective':row['elective'],'elective':elective,'before_sat_on':row['sat_on'],'sat_on':sat_on,'before_status':row['status']})

    def confirm(self,sid,replace=False,verify_identity=False):
        with self.transaction():
            row=self.scan(sid,images=False)
            if row['status']!='pending' or not row['student_id'] or not (row['identity_ok'] or verify_identity):
                raise ValueError('학생을 연결하고 학생·시험 일치를 확인한 뒤 확정하세요.')
            if row['input_mode']=='manual' and not all(row['reviewed']):
                raise ValueError('수기 채점에서 아직 입력하지 않은 문항을 확인하세요.')
            if row['key_revision'] != self.exam(row['exam_id'])['revision']:
                raise ValueError('정답이 바뀌었습니다. 검수 화면을 다시 열어 주세요.')
            current=effective(self.exam(row['exam_id']),row['elective'])
            if not current['configured']:raise ValueError('선택과목을 확인하고 해당 과목의 정답·배점을 등록하세요.')
            other=self.db.execute("SELECT id FROM scans WHERE exam_id=? AND student_id=? AND status='confirmed' AND id<>?",(row['exam_id'],row['student_id'],sid)).fetchone()
            if other and not replace:
                raise ValueError('DUPLICATE: 같은 학생·시험의 확정 성적이 있습니다. 기존 성적 교체 여부를 선택하세요.')
            if verify_identity:
                snapshot=row['snapshot'] or self.student_for_class(row['student_id'],row['import_context'].get('class_id'))
                self.db.execute('UPDATE scans SET identity_ok=1,snapshot=? WHERE id=?',(pack(snapshot),sid))
                self.log('identity_confirmed_on_confirmation',sid,{'student_id':row['student_id'],'exam_id':row['exam_id']})
            if other:
                self.db.execute("UPDATE scans SET status='superseded' WHERE id=?",(other[0],))
            self.db.execute("UPDATE scans SET status='confirmed' WHERE id=?",(sid,))
            self.log('confirmed',sid,{'replaced':other[0] if other else None,'score':row['score'],'revision':row['key_revision']})

    def link_makeup_student(self,sid,student_id):
        row=self.scan(sid,images=False);student=self.student(student_id)
        if row['input_mode']!='scan' or row['status']=='deleted':raise ValueError('스캔 답안에서 보강 학생을 연결하세요.')
        if not student['active']:raise ValueError('재원 학생을 선택하세요.')
        with self.transaction():
            context=row['import_context'].copy()
            context.update(manual_link=True,makeup_link=True,makeup_student_id=student_id)
            self.db.execute("UPDATE scans SET student_id=?,snapshot=?,identity_ok=0,status='pending',import_context=? WHERE id=?",(student_id,pack(student),pack(context),sid))
            self.log('makeup_student_linked',sid,{'before_student':row['student_id'],'student_id':student_id,'score_class_id':student['class_id'],'attended_class_id':context.get('class_id'),'before_status':row['status']})

    def set_status(self,sid,status):
        if status not in ('pending','excluded'):
            raise ValueError('올바르지 않은 상태입니다.')
        with self.transaction():
            before=self.scan(sid)['status']
            self.db.execute('UPDATE scans SET status=? WHERE id=?',(status,sid))
            self.log('status_changed',sid,{'before':before,'after':status})

    def results(self,eid=None,student_id=None):
        query="SELECT sc.id,sc.exam_id,sc.student_id,sc.score,sc.snapshot,sc.answers,sc.key_revision,sc.elective,sc.input_mode,e.title,e.series,e.subject,e.round,sc.sat_on AS day,e.day AS exam_day,e.points_json,e.key_json,e.config FROM scans sc JOIN exams e ON e.id=sc.exam_id WHERE sc.status='confirmed' AND e.archived=0"
        params=[]
        if eid:query+=' AND sc.exam_id=?';params.append(eid)
        if student_id:query+=' AND sc.student_id=?';params.append(student_id)
        rows=self.rows(query+' ORDER BY sc.sat_on DESC,e.id DESC',params)
        for r in rows:
            for name in ('snapshot','answers','config'):r[name]=json.loads(r[name])
            r['key'],r['points']=json.loads(r['key_json']),json.loads(r['points_json'])
            data=effective(r,r['elective'])
            for name in ('key','points','topics','skills','areas','cuts'):r[name]=data[name]
            r['maximum']=sum(r['points']);r['grade']=grade(r['score'],r['cuts'])
            r['estimated_percentile']=estimated_percentile(r['score'],r['maximum'],r['cuts'])
            r['wrong']=[i+1 for i,(a,k) in enumerate(zip(r['answers'],r['key'])) if a!=k]
        return rows

    def averages(self,eid,class_id=None,academy_id=None):
        rows=self.results(eid)
        if class_id is not None:
            rows=[r for r in rows if r['snapshot'].get('class_id')==class_id]
        if academy_id is not None:
            names={r['name'] for r in self.rows('SELECT name FROM academies WHERE id=?',(academy_id,))}
            rows=[r for r in rows if r['snapshot'].get('academy') in names]
        return (sum(r['score'] for r in rows)/len(rows)/100 if rows else None),len(rows)

    def backup(self,target):
        target=Path(target).resolve()
        if target==self.path:
            raise ValueError('원본 데이터 파일 위에 백업할 수 없습니다.')
        if target.exists():
            raise FileExistsError('기존 파일에는 백업을 덮어쓸 수 없습니다. 새 파일명으로 저장하세요. 저장한 자료를 가져오려면 백업 가져오기를 선택하세요.')
        target.parent.mkdir(parents=True,exist_ok=True)
        staging=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            dest=sqlite3.connect(staging)
            try:
                self.db.backup(dest)
                dest.execute('CREATE TABLE IF NOT EXISTS backup_metadata(name TEXT PRIMARY KEY,value TEXT NOT NULL)')
                dest.execute("INSERT OR REPLACE INTO backup_metadata VALUES('saved_at',?)",(now(),))
                dest.commit()
                if dest.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                    raise ValueError('백업 무결성 검사에 실패했습니다.')
            finally:
                dest.close()
            # Publish a complete backup without replacing any existing file,
            # even if one appeared after the initial existence check.
            if os.name=='nt':staging.rename(target)
            else:os.link(staging,target)
        finally:
            staging.unlink(missing_ok=True)
        return target

    def restore(self,source):
        source=Path(source).resolve()
        if source==self.path or not source.is_file():
            raise ValueError('다른 백업 파일을 선택하세요.')
        incoming=sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
        try:
            if incoming.execute('PRAGMA user_version').fetchone()[0] not in range(1,SCHEMA_VERSION+1) or incoming.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise ValueError('유효한 OMR 백업이 아닙니다.')
            if incoming.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('백업의 데이터 연결이 손상되었습니다.')
            for table,cols in {'academies':'id,name','classes':'id,academy_id,name','students':'id,code,name,class_id,active','exams':'id,key_json,points_json,revision','sources':'id,hash,name,data','scans':'id,raw,normalized,reading,answers,reviewed,student_id,identity_ok,snapshot,status,error,score,key_revision,created_at','audit':'id,at,kind,entity_id,detail'}.items():
                incoming.execute(f'SELECT {cols} FROM {table} LIMIT 1').fetchall()
            safety=self.path.parent/'backups'/('before_restore_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]+'.omrbackup')
            self.backup(safety)
            incoming.backup(self.db)
        finally:
            incoming.close()
        self.db.execute('PRAGMA foreign_keys=ON')
        self.migrate()
        with self.transaction():
            self.log('restored',None,{'backup':source.name,'safety_backup':str(safety)})
        return safety
