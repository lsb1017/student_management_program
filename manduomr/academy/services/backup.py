"""M8 백업·실행 잠금: start → lock → latest backup → restore; close → backup → upload → unlock.

The live SQLite file never syncs in place; only complete backup copies travel (1.0.6 rule).
Lock and transfer state is kept in data/sync_state.json, outside the database, so that a
restore never overwrites it (same idea as 1.0.6 handoff.json).
"""
from __future__ import annotations
from dataclasses import dataclass,field
from datetime import datetime
from pathlib import Path
import json
import secrets
import shutil
import uuid

from core.store import Store,LegacyDataError
from core.backup_tools import inspect_backup
from core.handoff import revision,backup_filename,backup_sort_key
from core.filestore import sha256_file,split_name
from academy.adapters.gdrive.base import RemoteError,RemoteUnavailable,lock_order
from academy.config import DB_NAME


class SessionBlocked(Exception):
    def __init__(self,holder):
        self.holder=holder;props=holder.get('properties',{})
        started=props.get('started_at','')
        try:shown=datetime.fromisoformat(started).strftime('%H:%M')
        except ValueError:shown=started or '알 수 없는 시각'
        super().__init__(f"{props.get('operator','다른 작업자')}님이 {shown}부터 작업 중입니다. ({props.get('pc_name','다른 PC')})\n그 PC에서 프로그램을 종료하면 실행할 수 있습니다.")


class DriveUnavailable(Exception):
    pass


class BackupInvalid(Exception):
    def __init__(self,item,reason,candidates):
        self.item=item;self.reason=reason;self.candidates=candidates
        super().__init__(f"최신 백업 {item['name']}을(를) 쓸 수 없습니다: {reason}\n교체하지 않았습니다. 직전 백업을 선택해 주세요.")


class UploadFailed(Exception):
    pass


@dataclass
class Session:
    store:Store
    mode:str                     # online | offline
    restored:str=''              # backup name restored at start
    uploaded_first:str=''        # pending local work uploaded before starting
    warnings:list=field(default_factory=list)


class SyncState:
    def __init__(self,path):
        self.path=Path(path)
        try:self.values=json.loads(self.path.read_text('utf-8'))
        except (OSError,ValueError):self.values={}

    def get(self,name,default=None):return self.values.get(name,default)

    def update(self,**values):
        self.values.update(values);self.save()

    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_name(self.path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:temp.write_text(json.dumps(self.values,ensure_ascii=False,indent=1),'utf-8');temp.replace(self.path)
        finally:temp.unlink(missing_ok=True)


class BackupService:
    def __init__(self,data_dir,remote,pc_id,pc_name='',clock=datetime.now):
        self.data=Path(data_dir);self.remote=remote;self.pc_id=pc_id;self.pc_name=pc_name or pc_id[:8];self.clock=clock
        self.db_path=self.data/DB_NAME;self.state=SyncState(self.data/'sync_state.json')
        for name in ('backups/outgoing','backups/incoming','backups/automatic'):(self.data/name).mkdir(parents=True,exist_ok=True)

    # ---- helpers ----------------------------------------------------------------
    def open_store(self):
        return Store(self.db_path)

    def has_local_changes(self,store):
        base=self.state.get('base_revision')
        return base is None and bool(store.rows('SELECT 1 FROM students LIMIT 1') or store.rows('SELECT 1 FROM exams LIMIT 1')) or (base is not None and revision(store)!=base)

    def holding_lock(self):
        return bool(self.state.get('holding_lock'))

    def log(self,text):
        with (self.data/'sync.log').open('a',encoding='utf-8') as f:f.write(f'{self.clock():%Y-%m-%d %H:%M:%S} {text}\n')

    # ---- start ------------------------------------------------------------------
    def open_session(self,operator,academy,progress=lambda text:None):
        progress('구글드라이브 실행 잠금을 확인하고 있어요.')
        try:locks=self.remote.list_locks()
        except RemoteUnavailable:
            if self.holding_lock():
                self.log('offline start with lock held')
                return Session(self.open_store(),'offline',warnings=['구글드라이브에 연결할 수 없어 이 PC의 자료로 작업합니다. 종료할 때 다시 업로드를 시도합니다.'])
            raise DriveUnavailable('구글드라이브에 연결할 수 없어 실행하지 않습니다.\n인터넷 연결을 확인한 뒤 다시 실행해 주세요.') from None
        except RemoteError as exc:
            raise DriveUnavailable(f'구글드라이브 잠금을 확인하지 못해 실행하지 않습니다.\n{exc}') from None
        held=self.state.get('lock') or {}
        mine=[l for l in locks if l['id']==held.get('id')]
        warnings=[]
        if self.holding_lock() and mine:
            store=self.open_store()
            uploaded=''
            if self.state.get('pending_upload') or self.has_local_changes(store):
                progress('이 PC에 올리지 못한 변경을 먼저 업로드하고 있어요.')
                try:uploaded=self._upload(store,academy)
                except (RemoteError,OSError) as exc:
                    warnings.append(f'올리지 못한 변경을 다시 업로드하지 못했습니다. 종료할 때 다시 시도합니다.\n{exc}')
            self.log(f'resumed own lock {held.get("name")}')
            return Session(store,'online',uploaded_first=uploaded,warnings=warnings)
        if self.holding_lock() and not mine:
            # An administrator force-released this PC's lock; its unsent changes are not on Drive.
            store=self.open_store()
            if self.has_local_changes(store) or self.state.get('pending_upload'):
                warnings.append('이 PC의 잠금이 관리자에 의해 해제되어, 올리지 못한 변경은 반영되지 않습니다. 현재 자료는 안전 백업으로 보관합니다.')
            store.close()
            self.state.update(holding_lock=False,lock=None,pending_upload=None)
        others=sorted(locks,key=lock_order)
        if others:raise SessionBlocked(others[0])
        progress('실행 잠금을 얻고 있어요.')
        content={'operator':operator,'pc_id':self.pc_id,'pc_name':self.pc_name,'started_at':self.clock().isoformat(timespec='minutes'),'nonce':secrets.token_hex(4)}
        try:
            lock=self.remote.create_lock(content)
            locks=self.remote.list_locks()
        except RemoteError as exc:
            raise DriveUnavailable(f'실행 잠금을 만들지 못해 실행하지 않습니다.\n{exc}') from None
        winner=min(locks,key=lock_order)
        if winner['id']!=lock['id']:
            try:self.remote.delete_lock(lock)
            except RemoteError:pass
            raise SessionBlocked(winner)
        self.state.update(holding_lock=True,lock={'id':lock['id'],'name':lock['name'],'created':lock['created']},operator=operator,academy=academy)
        self.log(f'lock acquired {lock["name"]}')
        try:
            store,restored=self._bring_latest(progress,warnings)
        except BackupInvalid:
            raise  # the lock is kept while the user chooses an earlier backup
        except Exception:
            try:self.release_lock()
            except UploadFailed:pass
            raise
        return Session(store,'online',restored=restored,warnings=warnings)

    def _bring_latest(self,progress,warnings):
        backups=sorted(self.remote.list_backups(),key=backup_sort_key,reverse=True)
        store=self.open_store()
        if not backups:
            if self.state.get('base_revision') is None:self.state.update(base_revision=revision(store))
            return store,''
        latest=backups[0]
        known={(self.state.get('last_download') or {}).get('sha256'),(self.state.get('last_upload') or {}).get('sha256')}
        changed=self.has_local_changes(store)
        if latest.get('sha256') in known and not changed:
            return store,''
        try:
            self._restore_item(store,latest,progress)
        except BackupInvalid as exc:
            exc.candidates=backups[1:];store.close();raise
        except Exception:
            store.close();raise
        if changed:warnings.append('이 PC에만 있던 변경은 최신 백업으로 교체되었습니다. 교체 전 자료는 data/backups의 before_restore 안전 백업에 있습니다.')
        return store,latest['name']

    def _restore_item(self,store,item,progress):
        progress(f"최신 백업 {item['name']}을(를) 내려받고 있어요.")
        target=self.data/'backups'/'incoming'/item['name']
        if target.exists():target=target.with_name(target.stem+'_'+uuid.uuid4().hex[:6]+target.suffix)
        try:
            self.remote.download_backup(item,target)
            info=inspect_backup(target)
        except LegacyDataError as exc:
            raise BackupInvalid(item,str(exc),[]) from None
        except RemoteUnavailable:
            raise
        except (RemoteError,ValueError,OSError) as exc:
            target.unlink(missing_ok=True)
            raise BackupInvalid(item,str(exc),[]) from None
        except Exception as exc:  # sqlite3.DatabaseError: not a database at all
            target.unlink(missing_ok=True)
            raise BackupInvalid(item,f'무결성 검사 실패 ({exc})',[]) from None
        missing=[name for name in info['files'] if not store.files.exists(split_name(name)[0])]
        for i,name in enumerate(missing,1):
            progress(f'파일함을 내려받고 있어요 · {i}/{len(missing)}')
            digest,ext=split_name(name);temp=self.data/'backups'/'incoming'/(name+'.part')
            self.remote.download_file(name,temp)
            if sha256_file(temp)!=digest:temp.unlink(missing_ok=True);raise BackupInvalid(item,'파일함 해시 검증 실패',[])
            store.files.put_file(temp,ext);temp.unlink(missing_ok=True)
        progress('현재 자료를 안전 백업한 뒤 교체하고 있어요.')
        store.restore(target)
        self.state.update(last_download={'id':item['id'],'name':item['name'],'sha256':item.get('sha256') or sha256_file(target),'at':self.clock().isoformat(timespec='seconds')},base_revision=revision(store))
        self.log(f'restored {item["name"]}')

    def restore_candidate(self,store,item,progress=lambda text:None):
        """사용자가 고른 직전 백업으로 교체. 잠금을 보유한 상태에서만 허용."""
        if not self.holding_lock():raise ValueError('실행 잠금을 보유한 뒤 백업을 선택하세요.')
        self._restore_item(store,item,progress)
        return item['name']

    def candidates(self):
        return sorted(self.remote.list_backups(),key=backup_sort_key,reverse=True)

    # ---- close ------------------------------------------------------------------
    def _upload(self,store,academy):
        taken={p.name for p in (self.data/'backups'/'outgoing').glob('*.omrbackup')}
        try:taken|={b['name'] for b in self.remote.list_backups()}
        except RemoteError:pass
        name=backup_filename(academy or self.state.get('academy') or '전체',taken,self.clock())
        path=store.backup(self.data/'backups'/'outgoing'/name)
        self.state.update(pending_upload=str(path))
        remote_names=self.remote.list_file_names()
        for file_name in store.file_names():
            if file_name in remote_names:continue
            digest,ext=split_name(file_name)
            self.remote.upload_file(store.files.path(digest,ext),file_name)
        item=self.remote.upload_backup(path)
        sha=sha256_file(path)
        if item.get('sha256') and item['sha256']!=sha:raise RemoteError('업로드한 백업의 해시가 다릅니다.')
        self.state.update(pending_upload=None,last_upload={'id':item['id'],'name':item['name'],'sha256':sha,'at':self.clock().isoformat(timespec='seconds')},base_revision=revision(store))
        self.log(f'uploaded {name}')
        return name

    def close_session(self,store,academy=None,progress=lambda text:None):
        """Returns the uploaded backup name ('' when nothing changed). Raises UploadFailed and keeps the lock."""
        if not self.holding_lock():return ''
        uploaded=''
        if self.has_local_changes(store) or self.state.get('pending_upload'):
            progress('백업을 만들어 구글드라이브에 올리고 있어요.')
            try:uploaded=self._upload(store,academy)
            except (RemoteError,OSError) as exc:
                self.log(f'upload failed: {exc}')
                raise UploadFailed(f'구글드라이브 업로드에 실패해 잠금을 유지했습니다.\n다시 시도하거나, 그대로 종료하면 다음 실행 때 이 PC가 먼저 업로드합니다.\n{exc}') from None
        progress('실행 잠금을 해제하고 있어요.')
        self.release_lock()
        return uploaded

    def release_lock(self):
        lock=self.state.get('lock')
        if lock:
            try:self.remote.delete_lock(lock)
            except RemoteError as exc:
                self.log(f'unlock failed: {exc}')
                raise UploadFailed(f'백업은 올렸지만 잠금을 해제하지 못했습니다. 다시 시도해 주세요.\n{exc}') from None
        self.state.update(holding_lock=False,lock=None)
        self.log('lock released')

    def force_release(self,operator,reason=''):
        """관리자 강제 해제: 잠금 보유 PC의 미업로드 변경은 반영되지 않음(호출 전 경고·확인 필수)."""
        locks=self.remote.list_locks()
        for lock in locks:self.remote.delete_lock(lock)
        self.log(f'force released {len(locks)} lock(s) by {operator}: {reason}')
        self.state.update(forced_release={'by':operator,'at':self.clock().isoformat(timespec='seconds'),'locks':[l.get('properties',{}) for l in locks],'reason':reason})
        return locks

    # ---- autosave ---------------------------------------------------------------
    def autosave(self,store,keep=6):
        """비정상 종료 대비 로컬 자동 저장. Drive에는 올리지 않음."""
        folder=self.data/'backups'/'automatic'
        path=store.backup(folder/f'autosave_{self.clock():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:4]}.omrbackup')
        for old in sorted(folder.glob('autosave_*.omrbackup'))[:-keep]:old.unlink(missing_ok=True)
        return path
