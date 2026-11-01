"""Remote backup folder contract shared by the Google Drive adapter and the simulator.

Folder layout (Google Drive 백업 폴더):
  <root>/YYYYMMDD_HHMM_학원.omrbackup   전체 자료 백업
  <root>/files/<sha256>.<ext>           파일함 (같은 해시는 한 번만 올림)
  <root>/locks/lock_<pc>_<nonce>.json   실행 잠금 (Drive가 매긴 생성 시각 순)
"""


class RemoteError(Exception):
    """Drive refused or failed a request."""


class RemoteUnavailable(RemoteError):
    """Network or Drive cannot be reached."""


def lock_order(item):
    # Drive has no atomic lock: the earliest server-assigned createdTime wins, id breaks ties.
    return (item['created'],item['id'])


class RemoteBackupFolder:
    """Interface. Every method raises RemoteUnavailable when offline."""

    def list_backups(self):raise NotImplementedError
    def upload_backup(self,path):raise NotImplementedError
    def download_backup(self,item,dest):raise NotImplementedError
    def list_locks(self):raise NotImplementedError
    def create_lock(self,content):raise NotImplementedError
    def delete_lock(self,item):raise NotImplementedError
    def list_file_names(self):raise NotImplementedError
    def upload_file(self,path,name):raise NotImplementedError
    def download_file(self,name,dest):raise NotImplementedError
