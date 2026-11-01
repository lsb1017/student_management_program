"""M6 안내·발송: 성적표 Drive 게시, 분반 회차 안내, 신규생 학번 안내, 발송 결과 기록.

- 확정 성적만 게시함(검수 대기 답안은 성적표·발송 어디에도 들어가지 않음).
- 같은 분반 회차 안내는 1회만 보냄. 다시 보내려면 resend=True(화면에서 확인창)를 거침.
- 신규생 안내는 학생·학번·안내문 버전 조합당 1회. 학번이 바뀌면 조합이 달라져 무조건 재안내 대상이 됨.
- 20:55~08:00에는 다음 날(또는 당일) 08:00로 예약함. 열람 웹에서는 게시 즉시 볼 수 있음.
- manifest·index에는 학번·이름 대신 sha256(pepper+학번+':'+이름) 해시만 둠.
"""
from __future__ import annotations
from datetime import datetime,timedelta,time
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import secrets
import unicodedata

from core.store import now as utc_now,pack
from core.handoff import filename_part
from academy.config import program_setting
from academy.adapters.kakao.base import AutomationFailed

WEEKDAY_NAMES='월화수목금토일'
SESSION_TEXT=('[{학원명}] {날짜}({요일}) 수업 성적표 안내\n\n'
              '이번 수업의 주간지·미니테스트 결과와 과제 완성도가 담긴 성적표가 올라왔습니다.\n'
              '아래 버튼을 눌러 학번과 이름으로 로그인해 확인해 주세요.')
WELCOME_TEXT=('[{학원명}] {학생명} 학생 등록 안내\n\n'
              '{학원명} {분반}에 등록되었습니다.\n학번: {학번}\n'
              'OMR 답안지 학번 칸과 성적표 열람 로그인에 사용합니다.\n\n신규생 안내문 보기: {링크}')
PERSONAL_FIELDS=('{학생명}','{학번}')


class AlreadySent(ValueError):
    pass


def normalized_name(value):
    return ''.join(unicodedata.normalize('NFC',str(value)).split())


def pepper(store):
    value=store.setting('viewer_pepper')
    if not value:
        value=secrets.token_hex(16);store.set_setting('viewer_pepper',value,log=False)
    return value


def login_hash(secret,code,name):
    """Must equal viewer/Code.gs loginHash_(): hex(sha256(pepper + 학번 + ':' + NFC 이름(공백 제거)))."""
    return hashlib.sha256((secret+str(code)+':'+normalized_name(name)).encode('utf-8')).hexdigest()


def quiet_until(at,start='20:55',end='08:00'):
    """None when sending is allowed at `at`; otherwise the next allowed time (08:00)."""
    s=time.fromisoformat(start);e=time.fromisoformat(end);t=at.time()
    if e<=t<s:return None
    day=at.date()+(timedelta(days=1) if t>=s else timedelta())
    return datetime.combine(day,e)


def session_info(store,session_id):
    rows=store.rows('SELECT s.*,c.name classroom,c.weekday,c.academy_id,a.name academy FROM class_sessions s JOIN classes c ON c.id=s.class_id JOIN academies a ON a.id=c.academy_id WHERE s.id=?',(session_id,))
    if not rows:raise ValueError('분반 수업 회차를 찾을 수 없습니다.')
    return rows[0]


def session_results(store,info):
    """Confirmed results taken in this class on this date, grouped by student in exam order."""
    grouped={}
    for r in sorted(store.results(),key=lambda r:(r['exam_id'],r['id'])):
        if r['snapshot'].get('class_id')==info['class_id'] and r['day']==info['date']:grouped.setdefault(r['student_id'],[]).append(r)
    return grouped


def viewer_link(store,**params):
    base=program_setting(store,'viewer_url') or ''
    if not base:raise ValueError('설정에서 성적표 열람 웹 주소를 먼저 입력하세요.')
    return base+('&' if '?' in base else '?')+'&'.join(f'{k}={v}' for k,v in params.items())


# ---- publishing --------------------------------------------------------------------
def publish(store,session_id,publisher,today=None,progress=lambda text:None):
    from academy.services.report import render
    info=session_info(store,session_id);grouped=session_results(store,info)
    if not grouped:raise ValueError('이 분반·날짜에 확정된 성적이 없습니다. 검수·확정 후 게시하세요.')
    secret=pepper(store);today=today or datetime.now()
    folder=publisher.session_folder(filename_part(info['classroom']),info['date'])
    manifest,_=publisher.read_json(folder,'manifest.json',{'version':1,'session_key':info['link_key'],'date':info['date'],'entries':{}})
    previous={r['student_id']:r for r in store.rows('SELECT * FROM report_files WHERE session_id=?',(session_id,))}
    published=[];latest={}
    with TemporaryDirectory(prefix='academy_publish_') as tmp:
        for i,(student_id,rows) in enumerate(grouped.items(),1):
            student=store.student(student_id);progress(f"성적표 게시 중 · {i}/{len(grouped)} {student['name']}")
            pdf=render(store,[r['id'] for r in rows],Path(tmp)/f'{student_id}.pdf')
            name=f"{today:%Y%m%d}_{student['code']}.pdf"
            file_id=publisher.upload_pdf(folder,name,pdf)
            old=previous.get(student_id)
            if old:manifest['entries']={h:e for h,e in manifest['entries'].items() if e.get('file_id')!=old['drive_file_id']}
            key=login_hash(secret,student['code'],student['name'])
            manifest['entries'][key]={'file_id':file_id,'file_name':name,'created_at':utc_now()}
            with store.transaction():
                store.db.execute('INSERT INTO report_files(session_id,student_id,scan_id,kind,drive_file_id,file_name,uploaded_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(session_id,student_id,kind) DO UPDATE SET scan_id=excluded.scan_id,drive_file_id=excluded.drive_file_id,file_name=excluded.file_name,uploaded_at=excluded.uploaded_at',
                                 (session_id,student_id,rows[0]['id'],'session',file_id,name,utc_now()))
            latest[key]={'file_id':file_id,'date':info['date'],'session_key':info['link_key']}
            published.append(student['name'])
    manifest_id=publisher.write_json(folder,'manifest.json',manifest)
    root=publisher.root();index,_=publisher.read_json(root,'index.json',{'version':1,'sessions':{},'latest':{},'notices':{}})
    index['sessions'][info['link_key']]={'manifest_id':manifest_id,'date':info['date']}
    for key,value in latest.items():
        if value['date']>=index['latest'].get(key,{}).get('date',''):index['latest'][key]=value
    publisher.write_json(root,'index.json',index)
    with store.transaction():
        store.db.execute('UPDATE class_sessions SET drive_folder_id=? WHERE id=?',(folder,session_id))
        store.log('reports_published',session_id,{'students':len(published),'date':info['date'],'class_id':info['class_id']})
    return published


def refresh_login(store,publisher,student_id):
    """학번이 바뀐 학생의 기존 게시 성적표 로그인 키를 새 학번으로 옮김(이름·파일은 그대로)."""
    if not store.rows('SELECT 1 FROM report_files WHERE student_id=? LIMIT 1',(student_id,)):return 0
    student=store.student(student_id);secret=pepper(store);new=login_hash(secret,student['code'],student['name'])
    root=publisher.root();index,_=publisher.read_json(root,'index.json',{'version':1,'sessions':{},'latest':{},'notices':{}})
    files={r['drive_file_id'] for r in store.rows('SELECT drive_file_id FROM report_files WHERE student_id=?',(student_id,))}
    moved=0
    for row in store.rows('SELECT r.drive_file_id,s.drive_folder_id FROM report_files r JOIN class_sessions s ON s.id=r.session_id WHERE r.student_id=?',(student_id,)):
        manifest,_=publisher.read_json(row['drive_folder_id'],'manifest.json',None)
        if not manifest:continue
        for key,entry in list(manifest['entries'].items()):
            if entry.get('file_id')==row['drive_file_id'] and key!=new:
                manifest['entries'][new]=manifest['entries'].pop(key);moved+=1
        publisher.write_json(row['drive_folder_id'],'manifest.json',manifest)
    for key,entry in list(index['latest'].items()):
        if entry.get('file_id') in files and key!=new:index['latest'][new]=index['latest'].pop(key)
    publisher.write_json(root,'index.json',index)
    return moved


# ---- class session notice ------------------------------------------------------------
def session_message(store,info):
    day=datetime.fromisoformat(info['date'])
    return SESSION_TEXT.format(**{'학원명':info['academy'],'날짜':f'{day.month}월 {day.day}일','요일':WEEKDAY_NAMES[day.weekday()]})


def _record(store,**values):
    values.setdefault('created_at',utc_now())
    names=list(values)
    with store.transaction():
        nid=store.db.execute(f"INSERT INTO notifications({','.join(names)}) VALUES({','.join('?'*len(names))})",[values[n] for n in names]).lastrowid
        store.log('notification_recorded',nid,{'kind':values['kind'],'status':values['status'],'idem_key':values['idem_key']})
    return nid


def _idem(store,base,resend,blocking=('sent','scheduled','manual','queued')):
    rows=store.rows('SELECT * FROM notifications WHERE idem_key=? OR idem_key LIKE ?',(base,base+':resend:%'))
    done=[r for r in rows if r['status'] in blocking]
    if done and not resend:raise AlreadySent('이미 보낸 안내입니다. 다시 보내려면 재발송을 확인하세요.')
    if not rows:return base
    # failed attempts are kept as history; every new attempt needs its own key
    return f'{base}:resend:{len(rows)}'


def notify_session(store,session_id,messenger,at=None,resend=False):
    info=session_info(store,session_id);at=at or datetime.now()
    if not store.rows('SELECT 1 FROM report_files WHERE session_id=? LIMIT 1',(session_id,)):raise ValueError('성적표를 먼저 게시한 뒤 안내를 보내세요.')
    key=_idem(store,f'session:{session_id}',resend)
    text=session_message(store,info);link=viewer_link(store,s=info['link_key'])
    schedule=quiet_until(at,program_setting(store,'quiet_start'),program_setting(store,'quiet_end'))
    roster=store.class_students(info['class_id'])
    phones=[p for s in roster for p in (s['phone'],s['parent_phone']) if p and len(p)>4]
    target=info['classroom'];base=dict(kind='session',class_id=info['class_id'],session_id=session_id,phones=pack(phones),content=text,idem_key=key,
                                      scheduled_for=schedule.isoformat(timespec='minutes') if schedule else '')
    try:
        result=messenger.send_channel_message(text,'성적표 보기',link,target,schedule)
    except AutomationFailed as exc:
        nid=_record(store,channel='partner_center',status='failed',error=exc.reason,**base)
        return {'id':nid,'status':'failed','reason':exc.reason,'manual':{'text':text,'button':'성적표 보기','link':link,'target':target,'schedule_at':base['scheduled_for'],
                'recipients':[{'name':s['name'],'phone':s['phone'],'parent_phone':s['parent_phone']} for s in roster]}}
    status=result['status'];count=result.get('expected_count')
    nid=_record(store,channel='partner_center',status=status,friend_count=count,sent_at=utc_now() if status=='sent' else '',**base)
    return {'id':nid,'status':status,'friend_count':count,'roster':len(roster),'missing_friends':count is not None and count<len(roster),'scheduled_for':base['scheduled_for']}


def mark_manual_sent(store,notification_id):
    """담당자가 수동 발송창의 내용을 직접 보낸 뒤 누르는 완료 처리."""
    row=store.rows('SELECT * FROM notifications WHERE id=?',(notification_id,))
    if not row or row[0]['status'] not in ('failed',):raise ValueError('수동 발송을 기록할 안내를 다시 선택하세요.')
    with store.transaction():
        store.db.execute("UPDATE notifications SET status='manual',channel='manual',sent_at=? WHERE id=?",(utc_now(),notification_id))
        store.log('notification_sent_manually',notification_id,{})


# ---- notice templates and welcome ------------------------------------------------------
def save_template(store,title,body,attachment=None,academy_id=None,class_id=None,is_default=False,template_id=None):
    title=str(title).strip();body=str(body).strip()
    if not title or len(title)>80 or not body or len(body)>4000:raise ValueError('안내문 제목(80자 이내)과 본문(4,000자 이내)을 입력하세요.')
    with store.transaction():
        digest=store.put_file(attachment) if attachment else ''
        if template_id:
            old=store.rows('SELECT * FROM notice_templates WHERE id=?',(template_id,))[0]
            digest=digest or old['attachment_hash']
            # Every edit raises the version and gets a new public key, so links of old versions stay as they were.
            store.db.execute('UPDATE notice_templates SET title=?,body=?,attachment_hash=?,academy_id=?,class_id=?,is_default=?,version=version+1,notice_key=?,updated_at=? WHERE id=?',
                             (title,body,digest,academy_id,class_id,int(is_default),secrets.token_urlsafe(9),utc_now(),template_id))
        else:
            template_id=store.db.execute('INSERT INTO notice_templates(title,body,attachment_hash,academy_id,class_id,is_default,notice_key,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                                         (title,body,digest,academy_id,class_id,int(is_default),secrets.token_urlsafe(9),utc_now())).lastrowid
        store.log('notice_template_saved',template_id,{'title':title,'academy_id':academy_id,'class_id':class_id,'default':bool(is_default)})
    return template_id


def template_for(store,student):
    """분반 지정 > 학원 지정 > 전체 기본 안내문."""
    member=store.memberships(student['id'])
    class_ids=[m['class_id'] for m in member];academy_ids=sorted({m['academy_id'] for m in member})
    for column,ids in (('class_id',class_ids),('academy_id',academy_ids)):
        if not ids:continue
        extra='' if column=='class_id' else ' AND class_id IS NULL'
        rows=store.rows(f"SELECT * FROM notice_templates WHERE is_default=1 AND {column} IN ({','.join('?'*len(ids))}){extra} ORDER BY updated_at DESC,id DESC",ids)
        if rows:return rows[0]
    rows=store.rows('SELECT * FROM notice_templates WHERE is_default=1 AND academy_id IS NULL AND class_id IS NULL ORDER BY updated_at DESC,id DESC')
    return rows[0] if rows else None


def publish_notice(store,publisher,template,student=None):
    """안내문을 열람 웹이 읽는 notices/에 올림. 학생명·학번이 들어가면 학생별 키를 씀."""
    personal=any(field in template['body'] or field in template['title'] for field in PERSONAL_FIELDS)
    values={'학생명':student['name'] if student else '','학번':student['code'] if student else ''}
    body=template['body'];title=template['title']
    for field,value in values.items():body=body.replace('{'+field+'}',value);title=title.replace('{'+field+'}',value)
    key=template['notice_key']+('-'+login_hash(pepper(store),student['code'],student['name'])[:12] if personal and student else '')
    folder=publisher.notices_folder()
    attachment=None
    if template['attachment_hash']:
        ext=store.rows('SELECT ext FROM file_objects WHERE hash=?',(template['attachment_hash'],))[0]['ext']
        attachment=publisher.upload_pdf(folder,f'{key}.{ext}',store.files.path(template['attachment_hash'],ext))
    file_id=publisher.write_json(folder,f'{key}.json',{'title':title,'body':body,'attachment_id':attachment,'version':template['version']})
    root=publisher.root();index,_=publisher.read_json(root,'index.json',{'version':1,'sessions':{},'latest':{},'notices':{}})
    index['notices'][key]=file_id;publisher.write_json(root,'index.json',index)
    return key


def welcome_targets(store,student):
    """학생 본인(전체 번호가 있을 때)과 학부모. 1:1 채팅방 검색어는 설정 kakao_chat_search 형식."""
    formats=store.setting('kakao_chat_search',{'student':'{학생명}','parent':'{학생명} 학부모'})
    targets=[]
    if len(student['phone'])>4:targets.append(('student',formats['student'].replace('{학생명}',student['name']),student['phone']))
    if student['parent_phone']:targets.append(('parent',formats['parent'].replace('{학생명}',student['name']),student['parent_phone']))
    return targets


def send_welcome(store,student_id,messenger,publisher,at=None,resend=False):
    student=store.student(student_id);template=template_for(store,student);at=at or datetime.now()
    if not template:raise ValueError('설정 > 안내문에서 기본 신규생 안내문을 먼저 등록하세요.')
    targets=welcome_targets(store,student)
    if not targets:raise ValueError('학생 전체 번호 또는 학부모 번호가 없어 안내를 보낼 수 없습니다. 연락처를 보완하세요.')
    key=_idem(store,f"welcome:{student_id}:{student['code']}:{template['version']}",resend)
    notice=publish_notice(store,publisher,template,student)
    classroom=', '.join(m['classroom'] for m in store.memberships(student_id))
    text=WELCOME_TEXT.format(**{'학원명':student['academy'],'학생명':student['name'],'분반':classroom,'학번':student['code'],'링크':viewer_link(store,n=notice)})
    schedule=quiet_until(at,program_setting(store,'quiet_start'),program_setting(store,'quiet_end'))
    base=dict(kind='welcome',student_id=student_id,phones=pack([t[2] for t in targets]),content=text,idem_key=key,channel='chat')
    if schedule:
        nid=_record(store,status='queued',scheduled_for=schedule.isoformat(timespec='minutes'),**base)
        return {'id':nid,'status':'queued','scheduled_for':schedule.isoformat(timespec='minutes')}
    return _deliver_welcome(store,None,messenger,targets,text,base)


def _deliver_welcome(store,nid,messenger,targets,text,base):
    failed=[]
    for role,search,phone in targets:
        try:messenger.send_chat(search,text)
        except AutomationFailed as exc:failed.append({'role':role,'search':search,'phone':phone,'reason':exc.reason})
    status='failed' if failed else 'sent';error='; '.join(f"{f['search']}: {f['reason']}" for f in failed)
    if nid is None:nid=_record(store,status=status,error=error,sent_at='' if failed else utc_now(),**base)
    else:
        with store.transaction():
            store.db.execute('UPDATE notifications SET status=?,error=?,sent_at=? WHERE id=?',(status,error,'' if failed else utc_now(),nid))
            store.log('notification_recorded',nid,{'kind':'welcome','status':status})
    out={'id':nid,'status':status}
    if failed:out['manual']={'text':text,'targets':failed}
    return out


def flush_due(store,messenger,publisher,at=None):
    """예약 대기(queued) 신규생 안내 중 발송 시각이 지난 것을 보냄. 프로그램 실행 중 주기적으로 호출."""
    at=at or datetime.now();done=[]
    for row in store.rows("SELECT * FROM notifications WHERE kind='welcome' AND status='queued' AND scheduled_for<=? ORDER BY id",(at.isoformat(timespec='minutes'),)):
        if quiet_until(at,program_setting(store,'quiet_start'),program_setting(store,'quiet_end')):break
        student=store.student(row['student_id'])
        if not row['idem_key'].startswith(f"welcome:{student['id']}:{student['code']}:"):
            with store.transaction():
                store.db.execute("UPDATE notifications SET status='failed',error='학번이 바뀌어 이전 안내를 보내지 않았습니다.' WHERE id=?",(row['id'],))
            continue
        done.append(_deliver_welcome(store,row['id'],messenger,welcome_targets(store,student),row['content'],{}))
    return done
