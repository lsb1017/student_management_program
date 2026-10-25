"""Local handoff preferences; not part of the student database or backups."""
import json,re,uuid
from datetime import datetime
from hashlib import sha256


def filename_part(value):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',str(value).strip()).strip('. ')[:40]


def revision(store,legacy=False):
    # Exporting/previewing existing results does not change the data to hand off.
    where='' if legacy else " WHERE kind NOT IN ('report_exported','batch_report_exported','ranking_exported','import_failed')"
    row=store.db.execute('SELECT id,at,kind,detail FROM audit'+where+' ORDER BY id DESC LIMIT 1').fetchone()
    return sha256(repr(tuple(row) if row else ()).encode()).hexdigest()


class Handoff:
    def __init__(self,store):
        self.store=store;self.path=store.path.with_suffix('.handoff.json')
        try:self.state=json.loads(self.path.read_text('utf-8'))
        except (OSError,ValueError):self.state={}
        if not isinstance(self.state,dict):self.state={}
        if self.state.get('baseline')==revision(store,legacy=True):
            self.state['baseline']=revision(store)
        self.state.setdefault('baseline',revision(store))
        self.state.setdefault('remind',True)
        # Persist the opening baseline even if this session later ends abruptly.
        self.save()

    def save(self):
        temp=self.path.with_name(self.path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            temp.write_text(json.dumps(self.state,ensure_ascii=False,indent=2),'utf-8');temp.replace(self.path)
        finally:temp.unlink(missing_ok=True)

    def needs_backup(self):return self.state.get('baseline')!=revision(self.store)

    def filename(self,academy=None,classroom=None):
        tag=('_'.join(filename_part(v) for v in (academy or '전체 학원',classroom or '전체 반'))
             if academy is not None or classroom is not None else filename_part(self.state.get('location','')))
        stem=datetime.now().strftime('%Y%m%d_%H%M')+('_'+tag if tag else '')
        previous=self.state.get('suggested_backup_name',{})
        sequence=previous.get('sequence',0) if isinstance(previous,dict) and previous.get('stem')==stem else 0
        sequence=max(0,sequence) + 1 if isinstance(sequence,int) else 1
        # Keep names distinct within a minute, including after reopening the app.
        self.state['suggested_backup_name']={'stem':stem,'sequence':sequence};self.save()
        return stem+(f'_{sequence}' if sequence>1 else '')+'.omrbackup'

    def recorded(self,kind,path):
        self.state[kind]={'file':path.name,'at':datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        current=revision(self.store)
        self.state['baseline']=current
        if kind=='incoming':self.state['incoming_revision']=current
        self.save()

    def summary(self):
        incoming=self.state.get('incoming',{});outgoing=self.state.get('outgoing',{})
        lines=['마지막으로 가져온 백업: '+(incoming.get('file','기록 없음'))]
        if incoming:lines.append('가져온 시각: '+incoming.get('at',''))
        if outgoing:lines.append('마지막으로 저장한 백업: '+outgoing.get('file','')+'  ·  '+outgoing.get('at',''))
        imported=self.state.get('incoming_revision')
        lines.append('가져온 뒤 수정: '+('있음' if imported!=revision(self.store) else '없음') if imported else '가져온 뒤 수정: 이전 기록 확인 불가')
        lines.append('새 백업에 저장하지 않은 변경: '+('있음' if self.needs_backup() else '없음'))
        lines.append('이 PC의 저장 기록입니다. 드라이브 업로드 상태는 홈에서 확인하세요.')
        return '\n'.join(lines)
