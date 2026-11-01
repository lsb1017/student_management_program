"""Partner-center recipe runner against a local mock page (real Edge via Playwright).

This proves the step runner, schedule branch, exact-one chat guard and dry run. The production
selectors in selectors.json still need calibration on the real 파트너센터 screen.
"""
import json
import pytest
from datetime import datetime
from academy.adapters.kakao.partner_center import PartnerCenterMessenger
from academy.adapters.kakao.base import AutomationFailed

MOCK='''<!doctype html><html><body>
<div id="compose">
 <button onclick="document.getElementById('form').hidden=false">기본 텍스트형</button>
 <div id="form" hidden>
  <textarea id="body"></textarea>
  <button onclick="document.getElementById('btn').hidden=false">버튼 추가</button>
  <div id="btn" hidden><input placeholder="버튼명" id="bname"><input placeholder="URL" id="blink"></div>
  <ul><li onclick="pick('청솔(토)',7)">청솔(토)</li><li onclick="pick('학림(수)',12)">학림(수)</li></ul>
  <div class="target"><span class="count" id="count">0명</span></div>
  <label><input type="radio" onclick="document.getElementById('when').hidden=false">예약 발송</label>
  <div id="when" hidden><input type="date" id="d"><input type="time" id="t"></div>
  <button onclick="send()">발송하기</button>
 </div>
</div>
<div id="chats"><input placeholder="검색" id="q"><ul class="chat-list">
 <li>김민수</li><li>김민수 학부모</li><li>이영희</li><li>이영희</li></ul>
 <textarea id="reply"></textarea><button onclick="reply()">전송</button><div id="log"></div></div>
<div id="done"></div>
<script>
 window.sent=[];var target='';
 function pick(name,n){target=name;document.getElementById('count').textContent='예상 '+n+'명';}
 function send(){window.sent.push({body:document.getElementById('body').value,button:document.getElementById('bname').value,
   link:document.getElementById('blink').value,target:target,date:document.getElementById('d').value,time:document.getElementById('t').value});
   document.getElementById('done').textContent='발송 완료';}
 function reply(){var v=document.getElementById('reply').value;window.sent.push({chat:v});document.getElementById('log').textContent=v;}
</script></body></html>'''


def recipe(url):
    return {'login_url_contains':['/login'],
            'channel_message':[{'action':'goto','url':url},{'action':'wait_login'},{'action':'click','selector':'text=기본 텍스트형'},
                {'action':'fill','selector':'#body','value':'{text}'},{'action':'click','selector':"button:has-text('버튼 추가')"},
                {'action':'fill','selector':"input[placeholder*='버튼명']",'value':'{button}'},{'action':'fill','selector':"input[placeholder*='URL']",'value':'{link}'},
                {'action':'click','selector':'li:has-text("{target}")'},
                {'action':'read_number','selector':'.target .count','store':'expected_count','minimum':1},
                {'action':'if_schedule','steps':[{'action':'click','selector':'text=예약 발송'},{'action':'fill','selector':'#d','value':'{date}'},{'action':'fill','selector':'#t','value':'{time}'}]},
                {'action':'click','selector':"button:has-text('발송하기')",'send':True},{'action':'wait_for','selector':'text=발송 완료','send':True}],
            'chat_reply':[{'action':'goto','url':url},{'action':'fill','selector':'#q','value':'{search}'},
                {'label':'채팅방 선택','action':'click','selector':'.chat-list li:text-is("{search}")','exact_one':True},
                {'action':'fill','selector':'#reply','value':'{text}'},{'action':'click','selector':"button:has-text('전송')",'send':True},
                {'action':'wait_for','selector':'#log:has-text("{text_head}")','send':True}]}


@pytest.fixture
def messenger(tmp_path):
    pytest.importorskip('playwright')
    page=tmp_path/'mock.html';page.write_text(MOCK,'utf-8')
    path=tmp_path/'recipe.json';path.write_text(json.dumps(recipe(page.as_uri()),ensure_ascii=False),'utf-8')
    m=PartnerCenterMessenger(tmp_path/'profile','_test',recipe=path,headless=True,step_timeout=4000)
    try:m.page()
    except AutomationFailed as exc:pytest.skip(str(exc))
    yield m
    m.close()


def test_channel_message_with_schedule(messenger):
    result=messenger.send_channel_message('[청솔] 안내','성적표 보기','https://viewer?s=abc','청솔(토)',datetime(2026,11,2,8,0))
    assert result=={'expected_count':7,'status':'scheduled'}
    sent=messenger.page().evaluate('window.sent')
    assert sent==[{'body':'[청솔] 안내','button':'성적표 보기','link':'https://viewer?s=abc','target':'청솔(토)','date':'2026-11-02','time':'08:00'}]


def test_chat_requires_exactly_one_room(messenger):
    assert messenger.send_chat('김민수','학번: 1234567')['status']=='sent'
    assert messenger.page().evaluate('window.sent')==[{'chat':'학번: 1234567'}]
    with pytest.raises(AutomationFailed,match='2개') as caught:messenger.send_chat('이영희','학번: 7654321')
    assert caught.value.payload['search']=='이영희'
    assert messenger.page().evaluate('window.sent')==[]   # the reloaded page received nothing


def test_dry_run_stops_before_send_and_missing_element_fails_with_payload(messenger):
    messenger.dry_run=True
    assert messenger.send_channel_message('본문','버튼','https://x','학림(수)')['status']=='dry_run'
    assert messenger.page().evaluate('window.sent')==[]
    messenger.dry_run=False
    with pytest.raises(AutomationFailed,match='단계') as caught:messenger.send_channel_message('본문','버튼','https://x','없는반')
    assert caught.value.payload['target']=='없는반' and caught.value.payload['link']=='https://x'
