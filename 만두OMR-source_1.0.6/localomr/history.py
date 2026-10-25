"""Imported historical scores retain the exported result, without invented keys."""
import json
from .examdata import estimated_percentile,grade


def create_tables(db):
    db.execute('''CREATE TABLE IF NOT EXISTS historical_exams(
        id INTEGER PRIMARY KEY,title TEXT NOT NULL UNIQUE,day TEXT NOT NULL,
        mean REAL NOT NULL,standard_mean REAL,maximum INTEGER NOT NULL,
        source_name TEXT NOT NULL,source_hash TEXT NOT NULL,
        linked_exam_id INTEGER REFERENCES exams(id))''')
    db.execute('''CREATE TABLE IF NOT EXISTS historical_results(
        id INTEGER PRIMARY KEY,exam_id INTEGER NOT NULL REFERENCES historical_exams(id),
        student_id INTEGER NOT NULL REFERENCES students(id),sat_on TEXT NOT NULL,
        score INTEGER NOT NULL,standard_score REAL,grade TEXT,elective TEXT,
        snapshot TEXT NOT NULL,earned TEXT NOT NULL,ox TEXT NOT NULL,answers TEXT NOT NULL,
        source_row INTEGER NOT NULL,notes TEXT NOT NULL DEFAULT '',
        UNIQUE(exam_id,student_id))''')
    if 'cuts_json' not in [r[1] for r in db.execute('PRAGMA table_info(historical_exams)')]:
        db.execute("ALTER TABLE historical_exams ADD COLUMN cuts_json TEXT NOT NULL DEFAULT '{}'")
    if 'cut_note' not in [r[1] for r in db.execute('PRAGMA table_info(historical_exams)')]:
        db.execute("ALTER TABLE historical_exams ADD COLUMN cut_note TEXT NOT NULL DEFAULT ''")


def latest_electives(store):
    rows=store.rows("""SELECT student_id,elective,sat_on,0 priority,id FROM historical_results WHERE elective IN ('1','2','3')
        UNION ALL SELECT s.student_id,s.elective,s.sat_on,1 priority,s.id FROM scans s JOIN exams e ON e.id=s.exam_id
        WHERE s.status='confirmed' AND e.archived=0 AND s.elective IN ('1','2','3')
        ORDER BY sat_on DESC,priority DESC,id DESC""")
    latest={}
    for r in rows:latest.setdefault(r['student_id'],r['elective'])
    return latest


def save_cuts(store,exam_id,cuts):
    from .store import points_cents,pack
    exam=store.db.execute('SELECT maximum FROM historical_exams WHERE id=?',(exam_id,)).fetchone()
    if not exam:raise ValueError('이전 시험을 선택하세요.')
    for choice,values in cuts.items():
        if choice not in ('1','2','3') or len(values) not in (0,5):raise ValueError('선택과목별 1~5등급컷을 모두 입력하거나 모두 비우세요.')
        if not values:continue
        numbers=[points_cents(v) for v in values]
        if numbers[0]>exam['maximum'] or any(a<=b for a,b in zip(numbers,numbers[1:])):
            raise ValueError('등급컷은 만점 이하에서 1등급부터 차례로 낮아져야 합니다.')
    with store.transaction():
        store.db.execute('UPDATE historical_exams SET cuts_json=? WHERE id=?',(pack(cuts),exam_id))
        store.db.execute('INSERT OR IGNORE INTO settings(name,value) VALUES(?,?)',(f'reference_v042_historical_exams_{exam_id}','user edited'))
        store.log('historical_cuts_saved',exam_id,{'cuts':cuts})


def results(store,student_id=None,for_report=False):
    sql='''SELECT r.*,e.title,e.day exam_day,e.mean historical_mean,e.standard_mean,
        e.maximum,e.linked_exam_id,e.cuts_json FROM historical_results r
        JOIN historical_exams e ON e.id=r.exam_id'''
    args=[]
    if student_id is not None:sql+=' WHERE r.student_id=?';args.append(student_id)
    rows=store.rows(sql+' ORDER BY r.sat_on DESC,r.exam_id DESC',args)
    official={(r['exam_id'],r['student_id']) for r in store.results(student_id=student_id)} if for_report else set()
    latest=latest_electives(store);out=[]
    for r in rows:
        if for_report and (r['linked_exam_id'],r['student_id']) in official:continue
        for field in ('snapshot','earned','ox','answers'):r[field]=json.loads(r[field])
        r['elective_inferred']=r['elective'] not in ('1','2','3') and r['student_id'] in latest
        if r['elective_inferred']:r['elective']=latest[r['student_id']]
        cuts=json.loads(r['cuts_json']).get(str(r['elective']),[])
        # A linked registered exam may already have the appropriate cutoffs.
        if not cuts and r['linked_exam_id']:
            cuts=store.exam(r['linked_exam_id'])['config'].get('cuts',{}).get(str(r['elective']),[])
        if cuts:r['grade']=grade(r['score'],cuts)
        r.update(id=-r['id'],exam_id=-r['exam_id'],day=r['sat_on'],subject='수학',series='이전 수학 시험',
            round='',historical=True,estimated_percentile=estimated_percentile(r['score'],r['maximum'],cuts),cuts=cuts,topics=['']*30,skills=['']*30)
        import re
        match=re.search(r'(\d+)회(?:차)?\s*$',r['title'])
        if match:r['round']=match.group(1)
        from .history_analysis import enrich
        enrich(r)
        out.append(r)
    return out


def mean_for_history(store,result):
    if result.get('historical'):return result['historical_mean']
    return store.averages(result['exam_id'])[0]
