"""Wiring: local settings → Drive backup folder, report publisher, Kakao messenger, HWP converter.

'시뮬레이션 Drive'는 Google 계정 없이 이 PC의 폴더를 Drive 대신 쓰는 시험 운영 모드임
(여러 PC를 흉내 내려면 같은 공유 폴더를 지정). 실제 운영은 Google Drive 모드로 함.
"""
from __future__ import annotations
from pathlib import Path
from academy.config import LocalSettings,asset,program_setting
from academy.services.backup import BackupService


class App:
    def __init__(self,data_dir,simulate_drive=None):
        self.data=Path(data_dir);self.data.mkdir(parents=True,exist_ok=True)
        self.local=LocalSettings(self.data)
        if simulate_drive:self.local.set('remote',{'kind':'simulation','path':str(Path(simulate_drive).resolve())})
        self._client=None

    # ---- Google Drive -------------------------------------------------------------
    def drive_client(self):
        if self._client is None:
            from academy.adapters.gdrive.client import DriveClient
            self._client=DriveClient(self.data/'drive',asset('google_client.json'))
        return self._client

    def remote_kind(self):
        return (self.local.get('remote') or {}).get('kind')

    def configured(self):
        remote=self.local.get('remote') or {}
        if remote.get('kind')=='simulation':return True
        return remote.get('kind')=='drive' and bool(remote.get('folder')) and self.drive_client().connected()

    def remote(self):
        remote=self.local.get('remote') or {}
        if remote.get('kind')=='simulation':
            from academy.adapters.gdrive.fake import FakeBackupFolder
            return FakeBackupFolder(remote['path'])
        if remote.get('kind')=='drive':
            from academy.adapters.gdrive.remote import DriveBackupFolder
            return DriveBackupFolder(self.drive_client(),remote['folder'])
        raise ValueError('백업 폴더를 먼저 설정하세요.')

    def use_drive(self,folder_link):
        client=self.drive_client();folder=client.folder(folder_link)
        self.local.set('remote',{'kind':'drive','folder':folder['id'],'folder_name':folder.get('name','')})
        return folder

    def use_simulation(self,path):
        self.local.set('remote',{'kind':'simulation','path':str(Path(path).resolve())})

    def backup_service(self):
        return BackupService(self.data,self.remote(),self.local.pc_id,self.local.pc_name)

    # ---- publishing and messaging ---------------------------------------------------
    def publisher(self,store):
        if self.remote_kind()=='simulation':
            from academy.adapters.gdrive.publish import FakePublisher
            return FakePublisher(Path((self.local.get('remote') or {})['path']).parent/'성적표_시뮬레이션')
        folder=program_setting(store,'reports_folder')
        if not folder:raise ValueError('설정에서 성적표 게시 폴더(비공개 Drive 폴더)를 먼저 입력하세요.')
        from academy.adapters.gdrive.publish import DrivePublisher
        return DrivePublisher(self.drive_client(),folder)

    def messenger(self,store):
        mode=store.setting('kakao_mode','manual')
        if mode=='automation':
            from academy.adapters.kakao.partner_center import PartnerCenterMessenger
            channel=program_setting(store,'kakao_channel_id')
            if not channel:raise ValueError('설정에서 카카오 채널 식별자(_로 시작)를 먼저 입력하세요.')
            return PartnerCenterMessenger(self.data/'kakao_profile',channel,dry_run=bool(store.setting('kakao_dry_run',False)))
        from academy.adapters.kakao.base import ManualMessenger
        return ManualMessenger()

    def hwp(self):
        from academy.adapters.hwp.converter import HwpConverter
        return HwpConverter()
