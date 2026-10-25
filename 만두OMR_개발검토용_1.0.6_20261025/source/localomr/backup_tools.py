"""Read backup metadata without loading scan image blobs."""
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime

def counts(connection):
    students=connection.execute('SELECT COUNT(*) FROM students').fetchone()[0]
    results=connection.execute("SELECT COUNT(*) FROM scans WHERE status='confirmed'").fetchone()[0]
    tables={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'historical_results' in tables:
        results+=connection.execute('SELECT COUNT(*) FROM historical_results').fetchone()[0]
    return {'students':students,'results':results}

def inspect_backup(path):
    from .store import SCHEMA_VERSION
    path=Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
        if db.execute('PRAGMA user_version').fetchone()[0] not in range(1,SCHEMA_VERSION+1):
            raise ValueError('지원하는 OMR 백업 파일을 선택하세요.')
        data=counts(db);data.update(file=path.name,saved_at=None)
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='backup_metadata'").fetchone():
            row=db.execute("SELECT value FROM backup_metadata WHERE name='saved_at'").fetchone()
            if row:
                try:data['saved_at']=datetime.fromisoformat(row[0]).astimezone().strftime('%Y-%m-%d %H:%M')
                except (ValueError,TypeError):pass
    return data

def comparison(current,incoming):
    lines=[f"파일: {incoming['file']}",f"백업 저장 시각: {incoming['saved_at'] or '확인 불가 (이전 버전 백업)'}",'']
    for key,title,unit in [('students','학생','명'),('results','성적','건')]:
        delta=incoming[key]-current[key]
        lines.append(f"{title}  현재 {current[key]:,}{unit} → {delta:+,}{unit} · 총 {incoming[key]:,}{unit}")
    return '\n'.join(lines)
