"""카카오비즈니스 파트너센터 화면 자동화(Playwright + Windows 기본 Edge).

- 최초 1회 담당자가 열린 창에서 직접 로그인·2단계 인증. 이후 data/kakao_profile 세션 재사용, 비밀번호 저장 안 함.
- 화면 조작 순서와 선택자는 recipe JSON(selectors.json)에 있음. 화면이 바뀌면 코드 수정 없이 JSON만 고침.
- 1:1 채팅 대상은 검색 결과가 정확히 1개일 때만 보냄(다른 사람에게 잘못 보내지 않도록).
- dry_run이면 'send' 표시 단계 직전까지만 진행하고 멈춤(선택자 확인용).
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from .base import ChannelMessenger,AutomationFailed

RECIPE=Path(__file__).with_name('selectors.json')


def fill_values(text,values):
    return re.sub(r'\{(\w+)\}',lambda m:str(values[m.group(1)]) if m.group(1) in values else m.group(0),str(text))


class PartnerCenterMessenger(ChannelMessenger):
    def __init__(self,profile_dir,channel_id,recipe=None,headless=False,dry_run=False,login_timeout=300,browser_channel='msedge',step_timeout=15000):
        self.profile=Path(profile_dir);self.channel=channel_id;self.headless=headless;self.dry_run=dry_run
        self.login_timeout=login_timeout;self.browser_channel=browser_channel;self.step_timeout=step_timeout
        self.recipe=json.loads(Path(recipe or RECIPE).read_text('utf-8'))
        self._pw=None;self._context=None;self._page=None

    def page(self):
        if self._page:return self._page
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:raise AutomationFailed('브라우저 자동화 구성요소(Playwright)가 설치되지 않았습니다.') from None
        self.profile.mkdir(parents=True,exist_ok=True)
        try:
            self._pw=sync_playwright().start()
            self._context=self._pw.chromium.launch_persistent_context(str(self.profile),channel=self.browser_channel,headless=self.headless)
            self._page=self._context.pages[0] if self._context.pages else self._context.new_page()
            self._page.set_default_timeout(self.step_timeout)
        except Exception as exc:
            self.close();raise AutomationFailed(f'Edge 브라우저를 열지 못했습니다: {exc}') from None
        return self._page

    def close(self):
        for closer in (lambda:self._context and self._context.close(),lambda:self._pw and self._pw.stop()):
            try:closer()
            except Exception:pass
        self._pw=self._context=self._page=None

    def _logged_out(self,page):
        return any(marker in page.url for marker in self.recipe.get('login_url_contains',[]))

    def _step(self,page,step,values,out):
        action=step['action'];selector=fill_values(step.get('selector',''),values)
        if action=='goto':page.goto(fill_values(step['url'],values))
        elif action=='wait_login':
            if self._logged_out(page):
                if self.headless:raise AutomationFailed('카카오 로그인이 필요합니다. 화면을 띄운 상태로 다시 실행해 로그인해 주세요.')
                page.wait_for_url(lambda url:not any(m in url for m in self.recipe.get('login_url_contains',[])),timeout=self.login_timeout*1000)
                if step.get('then_goto'):page.goto(fill_values(step['then_goto'],values))
        elif action=='click':
            target=page.locator(selector)
            if step.get('exact_one'):
                target.first.wait_for(state='visible')
                count=target.count()
                if count!=1:raise AutomationFailed(f"대상이 {count}개 검색되어 보내지 않았습니다. ({fill_values(step.get('label',''),values)})")
            target.first.click()
        elif action=='fill':page.locator(selector).first.fill(fill_values(step['value'],values))
        elif action=='press':page.locator(selector).first.press(step['key'])
        elif action=='select':page.locator(selector).first.select_option(fill_values(step['value'],values))
        elif action=='wait_for':page.locator(selector).first.wait_for(state='visible')
        elif action=='read_number':
            text=page.locator(selector).first.inner_text();digits=re.sub(r'[^0-9]','',text)
            out[step['store']]=int(digits) if digits else None
            minimum=step.get('minimum')
            if minimum is not None and (out[step['store']] or 0)<minimum:
                raise AutomationFailed(f"예상 대상이 {out[step['store']]}명이라 발송할 수 없습니다(최소 {minimum}명).")
        elif action=='if_schedule':
            if values.get('schedule'):
                for inner in step['steps']:self._step(page,inner,values,out)
        else:raise AutomationFailed(f'알 수 없는 자동화 단계: {action}')

    def run(self,name,values,payload):
        steps=self.recipe[name];page=self.page();out={}
        for index,step in enumerate(steps,1):
            if step.get('send') and self.dry_run:
                out['status']='dry_run';return out
            try:self._step(page,step,values,out)
            except AutomationFailed as exc:
                exc.payload={**payload,**exc.payload};raise
            except Exception as exc:
                raise AutomationFailed(f"자동화 {index}단계({step.get('label') or step['action']})에서 멈췄습니다: {str(exc).splitlines()[0][:160]}",payload) from None
        out.setdefault('status','scheduled' if values.get('schedule') else 'sent')
        return out

    def send_channel_message(self,text,button_label,link,target,schedule_at=None):
        values={'channel':self.channel,'text':text,'button':button_label,'link':link,'target':target,'schedule':bool(schedule_at),
                'date':schedule_at.strftime('%Y-%m-%d') if schedule_at else '','time':schedule_at.strftime('%H:%M') if schedule_at else ''}
        payload={'text':text,'button':button_label,'link':link,'target':target,'schedule_at':schedule_at.isoformat(timespec='minutes') if schedule_at else ''}
        return self.run('channel_message',values,payload)

    def send_chat(self,search,text):
        values={'channel':self.channel,'search':search,'text':text,'text_head':text.splitlines()[0][:20]}
        return self.run('chat_reply',values,{'search':search,'text':text})
