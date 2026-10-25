from urllib.parse import urlparse,parse_qs
from PySide6.QtWidgets import QFileDialog,QMessageBox,QInputDialog
from localomr.drive_backup import DriveClient
from localomr.drive_ui import DEFAULT_FOLDER
from localomr.backup_tools import inspect_backup
from test_v0411 import fixture

def test_one_click_backup_has_no_save_dialog(fixture,monkeypatch):
    app,db,w,*_=fixture
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(_ for _ in ()).throw(AssertionError('no chooser')))
    uploaded=[];monkeypatch.setattr(w.drive,'enqueue',lambda path:uploaded.append(path) or True)
    assert w.backup()
    assert len(uploaded)==1 and uploaded[0].parent.name=='automatic'
    assert inspect_backup(uploaded[0])['students']>0
    assert w.backup() and uploaded[0]!=uploaded[1]

def test_connect_default_folder_without_dialogs(fixture,monkeypatch):
    app,db,w,*_=fixture;d=w.drive;seen=[]
    def forbidden(*a,**k):raise AssertionError('unnecessary dialog')
    monkeypatch.setattr(QInputDialog,'getText',forbidden);monkeypatch.setattr(QMessageBox,'question',forbidden)
    monkeypatch.setattr(d,'run',lambda fn,done,*a,**k:done(fn()))
    monkeypatch.setattr(d.client,'connect',lambda *a:True)
    monkeypatch.setattr(d.client,'folder',lambda link:seen.append(link) or {'id':link,'name':'만두OMR 백업'})
    monkeypatch.setattr(d,'check_latest',lambda *a:None)
    d.setup();assert seen==[DEFAULT_FOLDER]
    d.state['folder']='existing_folder';d.setup();assert seen[-1]=='existing_folder'

def test_manual_backup_discovery_and_pagination(tmp_path,monkeypatch):
    c=DriveClient(tmp_path,tmp_path/'unused');queries=[]
    def request(url):
        q=parse_qs(urlparse(url).query);queries.append(q)
        if len(queries)==1:return {'files':[{'name':'wrong.omrbackup.txt'}],'nextPageToken':'next'}
        return {'files':[{'id':'manual','name':'기존백업.omrbackup'}]}
    monkeypatch.setattr(c,'request',request)
    assert c.latest('folder123')['id']=='manual'
    assert 'name contains' in queries[0]['q'][0] and queries[1]['pageToken']==['next']

def test_connection_colors(fixture):
    app,db,w,*_=fixture;d=w.drive
    d.render();assert '#FFE1BD' in w.drive_connection.styleSheet()
    d.state['folder']=DEFAULT_FOLDER;d.client.token_path.write_bytes(b'test');d.render()
    assert '#E5F3CE' in w.drive_connection.styleSheet()
    d.connection_error=True;d.render()
    assert '#FFE1BD' in w.drive_connection.styleSheet() and w.drive_connection.text()=='연결 오류'
