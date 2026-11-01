"""RemoteBackupFolder on Google Drive (backups, file box, run locks)."""
import json
from pathlib import Path
from .base import RemoteBackupFolder,RemoteError
from .client import DriveClient,digest,quoted


class DriveBackupFolder(RemoteBackupFolder):
    def __init__(self,client:DriveClient,folder_id):
        self.client=client;self.folder=client.folder_id(folder_id);self._sub={}

    def sub(self,name):
        if name not in self._sub:self._sub[name]=self.client.ensure_folder(self.folder,name)
        return self._sub[name]

    @staticmethod
    def _item(f):
        props=f.get('appProperties') or {}
        return {'id':f['id'],'name':f['name'],'created':f.get('createdTime',''),'modified':f.get('modifiedTime',''),
                'size':int(f.get('size') or 0),'md5':f.get('md5Checksum',''),'sha256':props.get('sha256',''),'properties':props}

    def list_backups(self):
        files=self.client.list(f"{quoted(self.folder)} in parents and name contains '.omrbackup'")
        return [self._item(f) for f in files if f['name'].lower().endswith('.omrbackup')]

    def upload_backup(self,path):
        result=self.client.upload(path,self.folder)
        return {'id':result['id'],'name':result['name'],'md5':result.get('md5Checksum',''),'sha256':digest(path)}

    def download_backup(self,item,dest):
        path=self.client.download({'id':item['id'],'md5Checksum':item.get('md5')},dest)
        if item.get('sha256') and digest(path)!=item['sha256']:
            Path(path).unlink(missing_ok=True);raise RemoteError('백업 다운로드 해시 검증에 실패했습니다.')
        return path

    def list_locks(self):
        return [self._item(f) for f in self.client.children(self.sub('locks'),folders=False)]

    def create_lock(self,content):
        props={k:str(v)[:60] for k,v in content.items()}
        name=f"lock_{content['pc_id'][:12]}_{content['nonce']}.json"
        return self._item(self.client.create_bytes(self.sub('locks'),name,json.dumps(content,ensure_ascii=False).encode(),app_properties=props))

    def delete_lock(self,item):
        self.client.delete(item['id'])

    def list_file_names(self):
        return {f['name'] for f in self.client.children(self.sub('files'),folders=False)}

    def upload_file(self,path,name):
        # File-box objects are already stored as <sha256>.<ext>, the Drive name.
        if Path(path).name!=name:raise ValueError('파일함 파일명과 업로드 이름이 다릅니다.')
        self.client.upload(Path(path),self.sub('files'),app_properties={'mandu_backup':'0'})

    def download_file(self,name,dest):
        found=self.client.children(self.sub('files'),name,folders=False)
        if not found:raise RemoteError('드라이브 파일함에 파일이 없습니다: '+name[:16])
        return self.client.download({'id':found[0]['id'],'md5Checksum':found[0].get('md5Checksum')},dest)
