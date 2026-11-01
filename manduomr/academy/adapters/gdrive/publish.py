"""성적표 게시 폴더(비공개). 열람 웹(Apps Script)만 이 폴더를 읽음.

성적표/
  index.json                      sessions: 회차 키 → manifest, latest: 로그인 해시 → 최근 성적표, notices
  <분반>/<YYYY-MM-DD>/<생성날짜>_<학번>.pdf
  <분반>/<YYYY-MM-DD>/manifest.json   로그인 해시(학번+이름) → 파일 (이름·전화번호 없음)
  notices/<안내문 키>.json
"""
import json
import uuid
from pathlib import Path
from .base import RemoteError


class ReportPublisher:
    def session_folder(self,class_label,day):raise NotImplementedError
    def upload_pdf(self,folder,name,path):raise NotImplementedError
    def read_json(self,folder,name,default):raise NotImplementedError
    def write_json(self,folder,name,value):raise NotImplementedError
    def notices_folder(self):raise NotImplementedError
    def root(self):raise NotImplementedError


class DrivePublisher(ReportPublisher):
    def __init__(self,client,root_folder):
        self.client=client;self.root_id=client.folder_id(root_folder)

    def root(self):return self.root_id

    def session_folder(self,class_label,day):
        return self.client.ensure_folder(self.client.ensure_folder(self.root_id,class_label),day)

    def notices_folder(self):return self.client.ensure_folder(self.root_id,'notices')

    def upload_pdf(self,folder,name,path):
        # Drive allows equal names; a re-made report is a new file and the manifest moves to it.
        return self.client.create_bytes(folder,name,Path(path).read_bytes(),'application/pdf')['id']

    def _find(self,folder,name):
        found=self.client.children(folder,name,folders=False)
        return sorted(found,key=lambda f:(f.get('createdTime',''),f['id']))[0] if found else None

    def read_json(self,folder,name,default):
        item=self._find(folder,name)
        return (json.loads(self.client.read_bytes(item['id']).decode('utf-8')),item['id']) if item else (default,None)

    def write_json(self,folder,name,value):
        data=json.dumps(value,ensure_ascii=False,indent=1).encode('utf-8');item=self._find(folder,name)
        if item:self.client.update_bytes(item['id'],data);return item['id']
        return self.client.create_bytes(folder,name,data)['id']


class FakePublisher(ReportPublisher):
    """Local folder with Drive-like ids, for simulation and dry runs."""

    def __init__(self,root):
        self.base=Path(root);self.base.mkdir(parents=True,exist_ok=True);self.offline=False
        self.ids=self.base/'.ids.json'
        if not self.ids.exists():self.ids.write_text('{}','utf-8')

    def _check(self):
        if self.offline:raise RemoteError('게시 폴더에 연결할 수 없습니다. (시뮬레이션)')

    def _register(self,path):
        table=json.loads(self.ids.read_text('utf-8'));key=str(path.relative_to(self.base))
        for fid,rel in table.items():
            if rel==key:return fid
        fid=uuid.uuid4().hex;table[fid]=key;self.ids.write_text(json.dumps(table,ensure_ascii=False),'utf-8');return fid

    def path_of(self,file_id):
        return self.base/json.loads(self.ids.read_text('utf-8'))[file_id]

    def root(self):return self._register(self.base)

    def session_folder(self,class_label,day):
        self._check();folder=self.base/class_label/day;folder.mkdir(parents=True,exist_ok=True);return self._register(folder)

    def notices_folder(self):
        folder=self.base/'notices';folder.mkdir(exist_ok=True);return self._register(folder)

    def upload_pdf(self,folder,name,path):
        self._check();target=self.path_of(folder)/name
        if target.exists():target=target.with_name(target.stem+'_'+uuid.uuid4().hex[:6]+target.suffix)
        target.write_bytes(Path(path).read_bytes());return self._register(target)

    def read_json(self,folder,name,default):
        self._check();target=self.path_of(folder)/name
        return (json.loads(target.read_text('utf-8')),self._register(target)) if target.exists() else (default,None)

    def write_json(self,folder,name,value):
        self._check();target=self.path_of(folder)/name
        target.write_text(json.dumps(value,ensure_ascii=False,indent=1),'utf-8');return self._register(target)
