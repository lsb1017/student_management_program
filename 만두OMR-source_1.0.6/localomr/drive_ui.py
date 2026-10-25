"""Single background worker, persistent outbox, explicit restore consent."""
import json,shutil,uuid
from pathlib import Path
from datetime import datetime
from PySide6.QtCore import QObject,QThread,Signal,QTimer
from PySide6.QtWidgets import QMessageBox,QInputDialog,QFileDialog
from .drive_backup import DriveClient,atomic_json,digest,API
from .handoff import revision
DEFAULT_FOLDER = "1k-MGOEQfrsNVxzah5iEPfgrAnEQhafHe"

class DriveJob(QThread):
    done=Signal(object);failed=Signal(str)
    def __init__(self,fn,parent):super().__init__(parent);self.fn=fn
    def run(self):
        try:self.done.emit(self.fn())
        except Exception as exc:self.failed.emit(str(exc) if isinstance(exc,ValueError) else '드라이브 작업을 완료하지 못했습니다. 연결과 인터넷 상태를 확인해 주세요.')

class DriveController(QObject):
    def __init__(self,window):
        super().__init__(window);self.w=window;self.job=None;self.busy=False;self.status='구글드라이브 연결 필요';self.after=None;self.connection_error=False
        self.root=window.store.path.parent/'drive';self.root.mkdir(exist_ok=True);self.path=self.root/'settings.json'
        try:self.state=json.loads(self.path.read_text('utf-8'))
        except (OSError,ValueError):self.state={}
        from .reports import report_asset
        self.client=DriveClient(self.root,report_asset('google_client.json'))
        self.retry=QTimer(self);self.retry.setSingleShot(True);self.retry.setInterval(60000);self.retry.timeout.connect(self.upload_next)
        self.render()
        if self.connected():QTimer.singleShot(1200,self.startup)

    def save(self):atomic_json(self.path,self.state)
    def connected(self):return bool(self.state.get('folder') and self.client.token_path.exists())
    def render(self):
        if not hasattr(self.w,'drive_status'):return
        healthy=self.connected() and not self.connection_error
        self.w.drive_connection.setText('연결 오류' if self.connection_error else '연구실 드라이브 연결됨' if healthy else '구글드라이브 연결 필요')
        self.w.drive_connection.setStyleSheet('padding:6px 10px;border-radius:8px;background:'+('#E5F3CE;color:#3F6212;' if healthy else '#FFE1BD;color:#9A4508;'))
        self.w.drive_status.setText(self.status)
        self.w.drive_location.setText('저장 위치: '+self.state.get('folder_name','만두OMR 백업'))

    def run(self,fn,done,status,failed=None):
        if self.busy:return False
        self.busy=True;self.status=status;self.render();job=DriveJob(fn,self);self.job=job
        outcome={}
        job.done.connect(lambda value:outcome.update(value=value));job.failed.connect(lambda text:outcome.update(error=text))
        def finish():
            self.busy=False;self.job=None;job.deleteLater()
            if 'error' in outcome:
                self.connection_error=True;self.status=outcome['error'];self.render()
                if failed:failed(outcome['error'])
            else:
                self.connection_error=False;done(outcome.get('value'));self.render()
        job.finished.connect(finish);job.start();return True

    def setup(self):
        if self.busy:QMessageBox.information(self.w,'작업 중','드라이브 작업이 끝난 뒤 다시 눌러 주세요.');return
        def authenticated(_):
            if self.state.get('outbox'):self.upload_next();return
            link=self.state.get('folder') or DEFAULT_FOLDER
            def selected(folder):
                self.state.update(folder=folder['id'],folder_name=folder['name']);self.save();self.status='구글드라이브 연결 완료';self.render();self.check_latest(True)
            self.run(lambda:self.client.folder(link),selected,'백업 폴더 확인 중')
        self.run(lambda:self.client.connect(lambda:self.job.isInterruptionRequested() if self.job else False),authenticated,'브라우저에서 연구실 계정으로 로그인해 주세요.')

    def enqueue(self,path):
        if not self.connected():return False
        # Outbox is an immutable copy, independent of the user's chosen local path.
        folder=self.root/'outbox'/uuid.uuid4().hex;folder.mkdir(parents=True)
        copy=folder/Path(path).name;shutil.copy2(path,copy)
        self.state.setdefault('outbox',[]).append({'path':str(copy),'revision':revision(self.w.store),'folder':self.state['folder'],'remote_id':None})
        self.save();self.upload_next();return True

    def upload_next(self):
        if self.busy:self.retry.start();return
        queue=self.state.get('outbox',[])
        if not queue or not self.connected():return
        entry=queue[0]
        def send():
            if not entry.get('remote_id'):
                entry['remote_id']=self.client.request(API+'/generateIds?count=1&space=drive')['ids'][0]
                # Persist identifier before sending bytes; retries cannot create duplicates.
                self.save()
            return self.client.upload(entry['path'],entry['folder'],entry['revision'],entry['remote_id'])
        def done(result):
            self.state['outbox'].remove(entry);self.state['last_id']=result['id'];self.state['last_revision']=entry['revision'];self.state['last_at']=datetime.now().strftime('%Y-%m-%d %H:%M');self.save()
            Path(entry['path']).unlink(missing_ok=True)
            self.status='✓ 드라이브 백업 완료 · '+self.state['last_at'];self.render()
            if self.state['outbox']:self.upload_next()
        def fail(message):
            self.status='PC 백업 보존 · 업로드 재시도 대기\n'+message;self.render();self.retry.start()
        self.run(send,done,'PC에 백업했어요. 구글드라이브에 업로드 중이에요.',fail)

    def startup(self):
        if self.state.get('outbox'):self.upload_next()
        else:self.check_latest(False)

    def check_latest(self,manual=False):
        if not self.connected():
            if manual:self.setup()
            return
        if self.busy:
            if manual:QMessageBox.information(self.w,'작업 중','드라이브 작업이 끝난 뒤 다시 눌러 주세요.')
            return
        def found(item):
            self.w.startup_backup_ready=True
            if not item:self.status='드라이브에 저장된 만두OMR 백업이 아직 없어요.';self.render();return
            same=item['id']==self.state.get('last_id') or item.get('appProperties',{}).get('revision')==revision(self.w.store)
            self.status='최근 드라이브 백업: '+item['name'];self.render()
            if same and not manual:return
            if self.w.worker or getattr(self.w,'_busy_operation',False):return
            if not self.w.isVisible():return
            local=self.w.handoff.needs_backup() or self.w.manual.has_unsaved() or bool(self.state.get('outbox'))
            if local:
                QMessageBox.information(self.w,'현재 자료 확인 필요','이 PC에 아직 저장·업로드하지 않은 변경사항이 있어요.\n현재 자료를 백업한 뒤 드라이브 백업을 가져와 주세요.');return
            box=QMessageBox(self.w);box.setWindowTitle('새 백업 확인');box.setText('드라이브 백업을 가져올까요?\n'+item['name']);yes=box.addButton('가져오기',QMessageBox.ButtonRole.AcceptRole);box.addButton('이번에는 건너뛰기',QMessageBox.ButtonRole.RejectRole);box.exec()
            if box.clickedButton()!=yes:return
            def received(path):
                try:
                    # Recheck after download: user may have edited while it ran.
                    if self.w.handoff.needs_backup() or self.w.manual.has_unsaved():raise ValueError('다운로드 중 자료가 변경되었습니다. 현재 자료를 먼저 백업해 주세요.')
                    if self.w.restore(path):self.state.update(last_id=item['id']);self.save();self.status='드라이브 백업을 가져왔습니다.'
                except ValueError as exc:QMessageBox.warning(self.w,'백업 확인 필요',str(exc))
                finally:Path(path).unlink(missing_ok=True);self.render()
            self.run(lambda:self.client.download(item),received,'드라이브 백업 다운로드 중')
        self.run(lambda:self.client.latest(self.state['folder']),found,'최신 드라이브 백업 확인 중')
