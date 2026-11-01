"""Stage 3 simulation: Drive 게시, 열람 웹 로그인(Code.gs를 Edge에서 실행), 카카오 안내 기록·중복 방지."""
import base64
import json
from datetime import datetime
from pathlib import Path
import pytest
from core.store import Store
from core.omr import ReadResult
from academy.adapters.gdrive.publish import FakePublisher
from academy.adapters.kakao.base import FakeMessenger
from academy.services import entries,notify
from academy.services.notify import AlreadySent,quiet_until,login_hash

KEY=[1,2,3,4,5]


def confirmed(store,eid,student,answers,tag,day='2026-11-01',class_id=None,confirm=True):
    source=store.db.execute('INSERT INTO sources(hash,name) VALUES(?,?)',(tag,tag)).lastrowid;store.db.commit()
    result=ReadResult(None,[{'answer':a,'flag':'clear','levels':[]} for a in answers],None)
    sid,_=store.add_scan(eid,source,1,tag,b'',result,sat_on=day,class_id=class_id)
    store.save_review(sid,student,answers,[True]*5,True)
    if confirm:store.confirm(sid)
    return sid


@pytest.fixture
def world(tmp_path):
    store=Store(tmp_path/'data'/'academy.sqlite3')
    aid=store.academy('청솔');cid=store.classroom(aid,'청솔(토)','토')
    people=[('김민수','010-1111-5678','010-9999-0001'),('이영희','010-2222-1234',''),('박철수','4321','010-9999-0003')]
    ids=[store.save_student_contact(n,p,parent_phone=pp,class_id=cid) for n,p,pp in people]
    config={'topics':['다항식']*5,'areas':['대수']*5}
    eid=store.save_exam('주간지 1회','주간지','수학','1','2026-11-01',KEY,[20]*5,config=config,exam_kind='weekly')
    for i,(sid,answers) in enumerate(zip(ids,([1,2,3,4,5],[1,2,3,1,1],[2,2,3,4,5]))):confirmed(store,eid,sid,answers,f'p{i}',class_id=cid)
    store.set_setting('viewer_url','https://script.google.com/macros/s/TEST/exec')
    session=entries.save(store,cid,'2026-11-01',[{'student_id':ids[0],'mini_score':'9','homework':'A'}])
    publisher=FakePublisher(tmp_path/'drive_reports')
    yield store,cid,ids,eid,session,publisher,tmp_path
    store.close()


def manifest_of(publisher,store,session):
    folder=store.rows('SELECT drive_folder_id FROM class_sessions WHERE id=?',(session['id'],))[0]['drive_folder_id']
    return json.loads((publisher.path_of(folder)/'manifest.json').read_text('utf-8'))


def test_quiet_hours():
    assert quiet_until(datetime(2026,11,1,20,54)) is None
    assert quiet_until(datetime(2026,11,1,20,55))==datetime(2026,11,2,8,0)
    assert quiet_until(datetime(2026,11,2,7,59))==datetime(2026,11,2,8,0)
    assert quiet_until(datetime(2026,11,2,8,0)) is None


def test_publish_private_manifest_and_republish(world):
    store,cid,ids,eid,session,publisher,tmp=world
    other=store.save_student_contact('최대기','010-3333-7777',class_id=cid)
    confirmed(store,eid,other,KEY,'pending',class_id=cid,confirm=False)   # 검수 대기
    published=notify.publish(store,session['id'],publisher,today=datetime(2026,11,1,19,0))
    assert sorted(published)==['김민수','박철수','이영희']
    manifest=manifest_of(publisher,store,session);secret=notify.pepper(store)
    expected={login_hash(secret,store.student(i)['code'],store.student(i)['name']) for i in ids}
    assert set(manifest['entries'])==expected and manifest['session_key']==session['link_key']
    # Names and full phone numbers never appear; the 학번 itself (tail 4 + random 3) is in file names by design.
    every_text=''.join(p.read_text('utf-8',errors='ignore') for p in publisher.base.rglob('*.json') if p.name!='.ids.json')
    every_text+=''.join(p.name for p in publisher.base.rglob('*'))
    for i in ids+[other]:
        s=store.student(i);assert s['name'] not in every_text
        for phone in (s['phone'],s['parent_phone']):assert len(phone)<=4 or phone not in every_text
    names=sorted(p.name for p in publisher.base.rglob('*.pdf'))
    assert names==sorted(f"20261101_{store.student(i)['code']}.pdf" for i in ids)
    first_file=store.rows('SELECT drive_file_id FROM report_files WHERE student_id=?',(ids[0],))[0]['drive_file_id']
    notify.publish(store,session['id'],publisher,today=datetime(2026,11,2,9,0))
    manifest=manifest_of(publisher,store,session)
    assert len(manifest['entries'])==3 and first_file not in [e['file_id'] for e in manifest['entries'].values()]
    index=json.loads((publisher.base/'index.json').read_text('utf-8'))
    assert index['sessions'][session['link_key']]['date']=='2026-11-01' and len(index['latest'])==3


def test_code_change_moves_login_keys(world):
    store,cid,ids,eid,session,publisher,tmp=world
    notify.publish(store,session['id'],publisher)
    store.save_student_contact('김민수','010-1111-8888',parent_phone='010-9999-0001',student_id=ids[0],class_id=cid)
    assert notify.refresh_login(store,publisher,ids[0])==1
    s=store.student(ids[0]);key=login_hash(notify.pepper(store),s['code'],s['name'])
    assert s['code'].startswith('8888') and key in manifest_of(publisher,store,session)['entries']


def test_session_notice_quiet_hours_idempotency_and_friend_gap(world):
    store,cid,ids,eid,session,publisher,tmp=world
    messenger=FakeMessenger(friend_count=2)
    with pytest.raises(ValueError,match='게시'):notify.notify_session(store,session['id'],messenger)
    notify.publish(store,session['id'],publisher)
    result=notify.notify_session(store,session['id'],messenger,at=datetime(2026,11,1,21,30))
    assert result['status']=='scheduled' and result['scheduled_for']=='2026-11-02T08:00' and result['missing_friends']
    kind,text,button,link,target,schedule=messenger.calls[0]
    assert text.startswith('[청솔] 11월 1일(일) 수업 성적표 안내') and button=='성적표 보기'
    assert link.endswith('?s='+session['link_key']) and target=='청솔(토)' and schedule==datetime(2026,11,2,8,0)
    with pytest.raises(AlreadySent):notify.notify_session(store,session['id'],messenger,at=datetime(2026,11,2,9,0))
    again=notify.notify_session(store,session['id'],messenger,at=datetime(2026,11,2,9,0),resend=True)
    assert again['status']=='sent' and len(messenger.calls)==2


def test_automation_failure_switches_to_manual(world):
    store,cid,ids,eid,session,publisher,tmp=world
    notify.publish(store,session['id'],publisher)
    result=notify.notify_session(store,session['id'],FakeMessenger(fail=True),at=datetime(2026,11,1,15,0))
    assert result['status']=='failed' and result['manual']['link'].endswith(session['link_key'])
    assert {r['name'] for r in result['manual']['recipients']}=={'김민수','이영희','박철수'}
    notify.mark_manual_sent(store,result['id'])
    with pytest.raises(AlreadySent):notify.notify_session(store,session['id'],FakeMessenger(),at=datetime(2026,11,1,15,5))


def test_welcome_targets_versions_code_changes_and_queue(world):
    store,cid,ids,eid,session,publisher,tmp=world
    messenger=FakeMessenger()
    with pytest.raises(ValueError,match='안내문'):notify.send_welcome(store,ids[0],messenger,publisher)
    tid=notify.save_template(store,'신규생 안내','수업 준비물과 교재 안내입니다.',is_default=True)
    result=notify.send_welcome(store,ids[0],messenger,publisher,at=datetime(2026,11,1,10,0))
    assert result['status']=='sent' and [c[1] for c in messenger.calls]==['김민수','김민수 학부모']
    text=messenger.calls[0][2];code=store.student(ids[0])['code']
    assert f'학번: {code}' in text and '청솔(토)에 등록되었습니다' in text and '?n=' in text
    with pytest.raises(AlreadySent):notify.send_welcome(store,ids[0],messenger,publisher,at=datetime(2026,11,1,10,5))
    store.save_student_contact('김민수','010-1111-4444',parent_phone='010-9999-0001',student_id=ids[0],class_id=cid)
    assert notify.send_welcome(store,ids[0],messenger,publisher,at=datetime(2026,11,1,10,6))['status']=='sent'   # 학번 변경 → 재안내
    notify.save_template(store,'신규생 안내','개정된 안내입니다.',is_default=True,template_id=tid)
    assert notify.send_welcome(store,ids[0],messenger,publisher,at=datetime(2026,11,1,10,7))['status']=='sent'   # 안내문 버전 변경
    # 박철수: 학생 번호가 뒷 4자리뿐이므로 학부모에게만 보냄. 밤에는 예약 대기.
    queued=notify.send_welcome(store,ids[2],messenger,publisher,at=datetime(2026,11,1,22,0))
    assert queued['status']=='queued' and queued['scheduled_for']=='2026-11-02T08:00'
    assert notify.flush_due(store,messenger,publisher,at=datetime(2026,11,2,7,0))==[]
    sent=notify.flush_due(store,messenger,publisher,at=datetime(2026,11,2,8,1))
    assert [s['status'] for s in sent]==['sent'] and messenger.calls[-1][1]=='박철수 학부모'
    # 1:1 채팅방이 없으면 수동 발송 목록에 번호와 함께 남음
    lost=FakeMessenger(known_chats={'이영희'})
    notify.save_template(store,'신규생 안내','다시 안내합니다.',is_default=True,template_id=tid)
    result=notify.send_welcome(store,ids[1],lost,publisher,at=datetime(2026,11,2,10,0))
    assert result['status']=='sent' and len(lost.calls)==1


def test_viewer_code_gs_runs_with_published_files(world):
    pytest.importorskip('playwright')
    from playwright.sync_api import sync_playwright
    store,cid,ids,eid,session,publisher,tmp=world
    notify.publish(store,session['id'],publisher)
    tid=notify.save_template(store,'신규생 안내','교재를 준비해 주세요.',is_default=True)
    notice_key=notify.publish_notice(store,publisher,store.rows('SELECT * FROM notice_templates WHERE id=?',(tid,))[0])
    table=json.loads(publisher.ids.read_text('utf-8'));files={};folders={}
    for fid,rel in table.items():
        path=publisher.base/rel
        if path.is_dir():folders[fid]={p.name:next((k for k,v in table.items() if v==str(p.relative_to(publisher.base))),None) for p in path.iterdir()}
        elif path.suffix=='.json':files[fid]={'text':path.read_text('utf-8')}
        else:files[fid]={'base64':base64.b64encode(path.read_bytes()).decode(),'mime':'application/pdf'}
    root=publisher.root();student=store.student(ids[1])
    code_gs=(Path(__file__).resolve().parents[1]/'viewer'/'Code.gs').read_text('utf-8')
    harness=(Path(__file__).with_name('viewer_harness.js')).read_text('utf-8')
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page();page.set_content('<html><body></body></html>')
            page.evaluate('([files,folders])=>{window.__files=files;window.__folders=folders;}',[files,folders])
            page.add_script_tag(content=harness);page.add_script_tag(content=code_gs)
            page.evaluate('([root,pepper])=>{__props.ROOT_FOLDER_ID=root;__props.PEPPER=pepper;}',[root,notify.pepper(store)])
            ok=page.evaluate('([c,n,s])=>login(c,n,s)',[student['code'],' 이 영희 ',session['link_key']])
            assert ok['ok'] and ok['date']=='2026-11-01'
            pdf=base64.b64decode(ok['pdf']);assert pdf.startswith(b'%PDF')
            stored=store.rows('SELECT file_name FROM report_files WHERE student_id=?',(ids[1],))[0]['file_name']
            assert pdf==next(publisher.base.rglob(stored)).read_bytes()
            assert page.evaluate('([c,n])=>login(c,n,"")',[student['code'],'이영희'])['ok']   # 회차 키 없이 → 최근 성적표
            assert not page.evaluate('([c,n,s])=>login(c,n,s)',[student['code'],'이영희','wrongkey'])['ok']
            for _ in range(5):assert not page.evaluate('([c,s])=>login(c,"김민수",s)',[student['code'],session['link_key']])['ok']
            locked=page.evaluate('([c,n,s])=>login(c,n,s)',[student['code'],'이영희',session['link_key']])
            assert locked.get('locked') and '10분' in locked['message']
            page.evaluate('()=>{window.__now+=11*60000;}')
            assert page.evaluate('([c,n,s])=>login(c,n,s)',[student['code'],'이영희',session['link_key']])['ok']
            note=page.evaluate('(k)=>notice(k)',notice_key);assert note['ok'] and note['body']=='교재를 준비해 주세요.'
            browser.close()
    except Exception as exc:
        if 'Executable doesn' in str(exc) or 'msedge' in str(exc).lower() and 'not found' in str(exc).lower():pytest.skip('Edge를 찾지 못함')
        raise
