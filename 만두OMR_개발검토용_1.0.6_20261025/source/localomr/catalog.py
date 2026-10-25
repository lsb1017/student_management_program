"""User-supplied exam cutoffs. Match exact normalized titles, never fuzzy names."""
import json
import re
import sys
from pathlib import Path


def entries():
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
    return json.loads((root/'assets/exam_reference_v042.json').read_text('utf-8'))['exams']


def title_key(title):
    value=re.sub(r'[^0-9a-z가-힣]','',title.casefold())
    value=re.sub(r'회차$','회',value)
    return value.replace('2027수능필요충분','2027필요충분').replace('이투스','')


def reference(title):
    key=title_key(title)
    return next((e for e in entries() if title_key(e['title'])==key),None)


def apply_catalog(store):
    """Caller holds a transaction. Apply once to each matched existing exam."""
    for table in ('exams','historical_exams'):
        for exam in store.rows(f'SELECT id,title FROM {table}'):
            entry=reference(exam['title'])
            if entry is None:continue
            marker=f"reference_v042_{table}_{exam['id']}"
            if store.db.execute('SELECT 1 FROM settings WHERE name=?',(marker,)).fetchone():continue
            if table=='exams':
                config=store.exam(exam['id'])['config'];config['cuts']=entry['cuts']
                config['cut_note']=entry.get('note','');config['cut_source']=entry['source']
                store.db.execute('UPDATE exams SET config=? WHERE id=?',(json.dumps(config,ensure_ascii=False),exam['id']))
            else:
                store.db.execute('UPDATE historical_exams SET cuts_json=?,cut_note=? WHERE id=?',
                    (json.dumps(entry['cuts'],ensure_ascii=False),entry.get('note',''),exam['id']))
            store.db.execute('INSERT INTO settings(name,value) VALUES(?,?)',(marker,entry['title']))
            store.log('reference_cuts_applied',exam['id'],{'table':table,'title':exam['title'],'cuts':entry['cuts'],'source':entry['source'],'note':entry.get('note','')})
