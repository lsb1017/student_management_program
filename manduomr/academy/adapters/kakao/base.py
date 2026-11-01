"""카카오비즈니스 채널 발송 계약. 파트너센터에는 발송 API가 없어 화면 자동화(partner_center)로 구현함.

ARCHITECTURE.md + 사용자 결정(2026-11-01):
- 분반 회차 안내: 파트너센터 채널 메시지(기본 텍스트형 + 성적표 보기 버튼), 20:55~08:00은 다음 날 08:00 예약.
- 신규생 학번 안내: 알림톡 API 대신 카카오비즈니스 채널 화면 자동화. 친구그룹 종료·타게팅 11명 이상 제한
  때문에 학생 1명만 고르는 채널 메시지는 보낼 수 없으므로, 학생·학부모가 채널에 먼저 말을 건 1:1 채팅방에서 보냄.
- 자동화가 멈추면 문구·링크·대상 목록을 띄워 담당자가 직접 보냄(수동 전환).
"""


class AutomationFailed(Exception):
    """The browser flow could not finish; payload carries what a person needs to send it by hand."""
    def __init__(self,reason,payload=None):
        self.reason=reason;self.payload=payload or {}
        super().__init__(reason)


class ChannelMessenger:
    def send_channel_message(self,text,button_label,link,target,schedule_at=None):
        """Return {'status':'sent'|'scheduled','expected_count':int|None}."""
        raise NotImplementedError

    def send_chat(self,search,text):
        """Reply in an existing 1:1 chat found by search text. Return {'status':'sent'}."""
        raise NotImplementedError

    def close(self):pass


class ManualMessenger(ChannelMessenger):
    """설정에서 '수동 발송'을 고른 경우: 항상 수동 발송창으로 넘김."""

    def send_channel_message(self,text,button_label,link,target,schedule_at=None):
        raise AutomationFailed('수동 발송으로 설정되어 있습니다.',{'text':text,'button':button_label,'link':link,'target':target,'schedule_at':schedule_at})

    def send_chat(self,search,text):
        raise AutomationFailed('수동 발송으로 설정되어 있습니다.',{'search':search,'text':text})


class FakeMessenger(ChannelMessenger):
    """Simulation: records calls; can report a smaller friend count or fail."""

    def __init__(self,friend_count=None,fail=False,known_chats=None):
        self.calls=[];self.friend_count=friend_count;self.fail=fail;self.known_chats=known_chats

    def send_channel_message(self,text,button_label,link,target,schedule_at=None):
        self.calls.append(('channel',text,button_label,link,target,schedule_at))
        if self.fail:raise AutomationFailed('화면 구조가 바뀌어 자동화를 멈췄습니다. (시뮬레이션)',{'text':text,'link':link,'target':target})
        return {'status':'scheduled' if schedule_at else 'sent','expected_count':self.friend_count}

    def send_chat(self,search,text):
        self.calls.append(('chat',search,text))
        if self.fail or (self.known_chats is not None and search not in self.known_chats):
            raise AutomationFailed('채팅방을 찾지 못했습니다. (시뮬레이션)',{'search':search,'text':text})
        return {'status':'sent'}
