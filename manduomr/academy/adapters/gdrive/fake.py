"""Local-folder stand-in for the Drive backup folder, for simulation tests and dry runs.

Several FakeBackupFolder objects can share one root to simulate several PCs. Creation order
is a shared counter, like Drive's server-assigned createdTime. Each instance can go offline
or fail chosen operations independently.
"""
import hashlib
import json
import shutil
import uuid
from pathlib import Path
from .base import RemoteBackupFolder,RemoteError,RemoteUnavailable


def _sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


class FakeBackupFolder(RemoteBackupFolder):
    def __init__(self,root):
        self.root=Path(root);self.offline=False;self.fail=set();self.hooks={}
        for name in ('files','locks','meta'):(self.root/name).mkdir(parents=True,exist_ok=True)

    def _check(self,op):
        if self.offline:raise RemoteUnavailable('인터넷 연결을 확인해 주세요. (시뮬레이션)')
        if op in self.fail:raise RemoteError(f'구글드라이브 요청을 완료하지 못했습니다 ({op}, 시뮬레이션).')

    def _stamp(self):
        counter=self.root/'meta'/'counter';value=int(counter.read_text() if counter.exists() else 0)+1
        counter.write_text(str(value));return f'{value:012d}'

    def _meta(self,name):
        path=self.root/'meta'/(name+'.json')
        return json.loads(path.read_text('utf-8')) if path.exists() else {}

    def _set_meta(self,name,value):
        (self.root/'meta'/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False),'utf-8')

    def list_backups(self):
        self._check('list_backups')
        out=[]
        for p in sorted(self.root.glob('*.omrbackup')):
            meta=self._meta(p.name)
            out.append({'id':meta['id'],'name':p.name,'created':meta['created'],'modified':meta['created'],'size':p.stat().st_size,'sha256':meta['sha256'],'md5':''})
        return out

    def upload_backup(self,path):
        self._check('upload_backup')
        target=self.root/Path(path).name
        if target.exists():raise RemoteError('같은 이름의 백업이 이미 있습니다.')
        shutil.copyfile(path,target)
        meta={'id':uuid.uuid4().hex,'created':self._stamp(),'sha256':_sha(target)};self._set_meta(target.name,meta)
        if meta['sha256']!=_sha(path):raise RemoteError('업로드 검증 실패')
        return {'id':meta['id'],'name':target.name,'sha256':meta['sha256'],'created':meta['created']}

    def download_backup(self,item,dest):
        self._check('download_backup')
        source=self.root/item['name'];shutil.copyfile(source,dest)
        if item.get('sha256') and _sha(dest)!=item['sha256']:Path(dest).unlink();raise RemoteError('백업 다운로드 해시 검증에 실패했습니다.')
        return Path(dest)

    def list_locks(self):
        self._check('list_locks')
        out=[]
        for p in (self.root/'locks').glob('*.json'):
            data=json.loads(p.read_text('utf-8'))
            out.append({'id':data['_id'],'name':p.name,'created':data['_created'],'properties':{k:v for k,v in data.items() if not k.startswith('_')}})
        return out

    def create_lock(self,content):
        self._check('create_lock')
        item_id=uuid.uuid4().hex;created=self._stamp();name=f"lock_{content['pc_id'][:12]}_{content['nonce']}.json"
        (self.root/'locks'/name).write_text(json.dumps({**content,'_id':item_id,'_created':created},ensure_ascii=False),'utf-8')
        item={'id':item_id,'name':name,'created':created,'properties':dict(content)}
        hook=self.hooks.pop('after_create_lock',None)
        if hook:hook()
        return item

    def delete_lock(self,item):
        self._check('delete_lock')
        (self.root/'locks'/item['name']).unlink(missing_ok=True)

    def list_file_names(self):
        self._check('list_file_names')
        return {p.name for p in (self.root/'files').iterdir()}

    def upload_file(self,path,name):
        self._check('upload_file')
        shutil.copyfile(path,self.root/'files'/name)

    def download_file(self,name,dest):
        self._check('download_file')
        source=self.root/'files'/name
        if not source.exists():raise RemoteError('드라이브 파일함에 파일이 없습니다: '+name[:16])
        shutil.copyfile(source,dest);return Path(dest)
