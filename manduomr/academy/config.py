"""Data folder layout and per-PC settings that must survive a backup restore."""
import json
import socket
import sys
import uuid
from pathlib import Path

DB_NAME='academy.sqlite3'

# Program-wide defaults stored in the database (shared by every PC through backups).
# ARCHITECTURE.md 기본안을 설정값으로 둔 것임.
DEFAULTS={
    'autosave_minutes':10,           # 작업 중 로컬 자동 저장 주기
    'wrongnote_rounds':4,            # 4주 오답노트 = 같은 시리즈 주간지 4회차
    'overlay_target':'all',          # 손풀이 대상: all(전체 문항) | wrong(OMR 오답만)
    'worksheet_id_position':[0.70,0.015],  # 문제지 첫 쪽 학번 버블 위치(쪽 너비·높이 비율)
    'quiet_start':'20:55','quiet_end':'08:00',  # 카카오 정보성 메시지 발송 제한 시간
    'viewer_url':'',                 # 성적표 열람 웹(Apps Script) 주소
    'kakao_channel_id':'',           # 카카오비즈니스 파트너센터 채널 식별자(_xxxx)
    'reports_folder':'',             # Drive 성적표 게시 폴더(비공개)
    'login_fail_limit':5,'login_lock_minutes':10,
}


def app_root():
    """Folder holding assets: the PyInstaller bundle, or the manduomr source folder."""
    return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))


def asset(name):
    return app_root()/'assets'/name


def default_data_dir():
    if getattr(sys,'frozen',False):return Path(sys.executable).parent/'data'
    return Path(__file__).resolve().parents[2]/'data'


class LocalSettings:
    """data/local.json: this PC's id, Drive folder and preferences. Never inside backups."""

    def __init__(self,data_dir):
        self.path=Path(data_dir)/'local.json'
        try:self.values=json.loads(self.path.read_text('utf-8'))
        except (OSError,ValueError):self.values={}
        if not self.values.get('pc_id'):
            self.values['pc_id']=uuid.uuid4().hex;self.save()
        self.values.setdefault('pc_name',socket.gethostname()[:40])

    def get(self,name,default=None):return self.values.get(name,default)

    def set(self,name,value):
        self.values[name]=value;self.save()

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_name(self.path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:temp.write_text(json.dumps(self.values,ensure_ascii=False,indent=1),'utf-8');temp.replace(self.path)
        finally:temp.unlink(missing_ok=True)

    @property
    def pc_id(self):return self.values['pc_id']

    @property
    def pc_name(self):return self.values['pc_name']


def program_setting(store,name):
    return store.setting(name,DEFAULTS.get(name))
