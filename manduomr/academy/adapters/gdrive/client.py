"""Google Drive API v3 client, ported from 1.0.6 drive_backup.py and extended.

Kept from 1.0.6: system-browser PKCE login, DPAPI-encrypted token, resumable upload with a
pre-generated id (idempotent retry), MD5 verification. Added: generic list/create/delete,
small JSON files (locks, manifests) and plain downloads.
"""
from datetime import datetime,timezone
import base64,ctypes,hashlib,json,os,re,secrets,time,uuid,webbrowser
from pathlib import Path
from urllib.parse import urlencode,urlparse,parse_qs,quote
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from http.server import HTTPServer,BaseHTTPRequestHandler
from .base import RemoteError,RemoteUnavailable

API='https://www.googleapis.com/drive/v3/files'
UPLOAD='https://www.googleapis.com/upload/drive/v3/files'
TOKEN='https://oauth2.googleapis.com/token'
SCOPE='https://www.googleapis.com/auth/drive'
FOLDER='application/vnd.google-apps.folder'


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:temp.write_text(json.dumps(value,ensure_ascii=False,indent=1),'utf-8');temp.replace(path)
    finally:temp.unlink(missing_ok=True)


def digest(path,algorithm='sha256'):
    h=hashlib.new(algorithm)
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def protect(data,decrypt=False):
    if os.name!='nt':raise ValueError('연결 인증정보는 Windows에서만 저장합니다.')
    class Blob(ctypes.Structure):_fields_=[('size',ctypes.c_ulong),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buf=ctypes.create_string_buffer(data);source=Blob(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte)));out=Blob()
    fn=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(out)):raise ValueError('Windows 인증정보 저장소에 접근할 수 없습니다. 다시 연결해 주세요.')
    try:return ctypes.string_at(out.data,out.size)
    finally:ctypes.windll.kernel32.LocalFree(out.data)


def quoted(value):
    return "'"+str(value).replace('\\','\\\\').replace("'","\\'")+"'"


class DriveClient:
    def __init__(self,root,client_path):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.client_path=Path(client_path)
        self.token_path=self.root/'google_token.bin';self.access=None;self.expires=0

    def client(self):
        try:c=json.loads(self.client_path.read_text('utf-8'))['installed']
        except (OSError,ValueError,KeyError):raise ValueError('데스크톱 앱용 Google 연결 설정 JSON을 선택해 주세요.')
        if not c.get('client_id') or not c.get('client_secret'):raise ValueError('Google 연결 설정을 확인해 주세요.')
        return c

    def connected(self):
        return self.token_path.exists()

    def save_token(self,t):
        payload=protect(json.dumps(t).encode());temp=self.token_path.with_suffix('.tmp');temp.write_bytes(payload);temp.replace(self.token_path)
        self.access=t['access_token'];self.expires=time.time()+int(t.get('expires_in',3600))-90

    def token_request(self,values):
        try:
            with urlopen(Request(TOKEN,data=urlencode(values).encode()),timeout=30) as r:return json.load(r)
        except HTTPError:raise RemoteError('Google 연결 인증이 만료되었거나 거절되었습니다. 연결 설정에서 다시 로그인해 주세요.') from None
        except (URLError,TimeoutError,OSError):raise RemoteUnavailable('인터넷 연결을 확인해 주세요.') from None

    def connect(self,cancelled=lambda:False):
        c=self.client();state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(64);result={}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                q=parse_qs(urlparse(self.path).query)
                if urlparse(self.path).path!='/callback' or not secrets.compare_digest(q.get('state',[''])[0],state):self.send_error(400);return
                result.update(code=q.get('code',[''])[0],error=q.get('error',[''])[0]);self.send_response(200);self.send_header('Content-Type','text/plain; charset=utf-8');self.end_headers();self.wfile.write('프로그램으로 돌아가 주세요. 이 창은 닫아도 됩니다.'.encode())
        with HTTPServer(('127.0.0.1',0),Handler) as server:
            server.timeout=1;redirect=f'http://127.0.0.1:{server.server_port}/callback'
            params=dict(client_id=c['client_id'],redirect_uri=redirect,response_type='code',scope=SCOPE,access_type='offline',prompt='consent select_account',state=state,code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='),code_challenge_method='S256')
            webbrowser.open('https://accounts.google.com/o/oauth2/v2/auth?'+urlencode(params))
            deadline=time.time()+180
            while not result and time.time()<deadline and not cancelled():server.handle_request()
        if not result.get('code'):raise ValueError('Google 연결을 완료하지 않았습니다. 다시 연결할 수 있어요.')
        self.save_token(self.token_request(dict(client_id=c['client_id'],client_secret=c['client_secret'],code=result['code'],redirect_uri=redirect,grant_type='authorization_code',code_verifier=verifier)))
        return True

    def access_token(self):
        if self.access and time.time()<self.expires:return self.access
        try:t=json.loads(protect(self.token_path.read_bytes(),True))
        except (OSError,ValueError):raise RemoteError('구글드라이브에 먼저 연결해 주세요.') from None
        c=self.client();fresh=self.token_request(dict(client_id=c['client_id'],client_secret=c['client_secret'],refresh_token=t.get('refresh_token',''),grant_type='refresh_token'))
        fresh['refresh_token']=fresh.get('refresh_token') or t.get('refresh_token');self.save_token(fresh);return self.access

    def request(self,url,method='GET',body=None,headers=None,raw=False):
        if urlparse(url).scheme!='https' or urlparse(url).hostname!='www.googleapis.com':raise ValueError('잘못된 Google API 주소입니다.')
        hdr={'Authorization':'Bearer '+self.access_token(),**(headers or {})}
        if isinstance(body,dict):body=json.dumps(body).encode();hdr['Content-Type']='application/json; charset=UTF-8'
        try:
            with urlopen(Request(url,data=body,headers=hdr,method=method),timeout=45) as response:
                data=response.read();return (data,dict(response.headers)) if raw else json.loads(data or b'{}')
        except HTTPError as exc:
            if exc.code==308:return {'resume':True}
            if exc.code==401:self.access=None;self.expires=0
            raise RemoteError(f'구글드라이브 요청을 완료하지 못했습니다 ({exc.code}). 연결·권한·저장 용량을 확인해 주세요.') from None
        except (URLError,TimeoutError,OSError):raise RemoteUnavailable('인터넷 연결을 확인해 주세요. PC 백업은 보존됩니다.') from None

    @staticmethod
    def folder_id(value):
        value=value.strip();match=re.search(r'/folders/([A-Za-z0-9_-]+)',value)
        fid=match[1] if match else value
        if not re.fullmatch(r'[A-Za-z0-9_-]{5,200}',fid):raise ValueError('구글드라이브 폴더의 링크를 입력해 주세요.')
        return fid

    def folder(self,value):
        fid=self.folder_id(value);r=self.request(API+'/'+fid+'?fields=id,name,mimeType,trashed,capabilities(canAddChildren)&supportsAllDrives=true')
        if r.get('trashed') or r.get('mimeType')!=FOLDER or not r.get('capabilities',{}).get('canAddChildren'):raise ValueError('파일을 저장할 수 있는 폴더를 선택해 주세요.')
        return r

    # ---- generic helpers ----------------------------------------------------------
    def list(self,query,fields='id,name,createdTime,modifiedTime,md5Checksum,size,appProperties,mimeType',order='createdTime'):
        out=[];page=None
        while True:
            params=dict(q=query+' and trashed=false',fields='nextPageToken,files('+fields+')',orderBy=order,pageSize=1000,supportsAllDrives='true',includeItemsFromAllDrives='true')
            if page:params['pageToken']=page
            data=self.request(API+'?'+urlencode(params))
            out.extend(data.get('files',[]))
            page=data.get('nextPageToken')
            if not page:return out

    def children(self,parent,name=None,folders=None):
        query=f'{quoted(self.folder_id(parent))} in parents'
        if name is not None:query+=f' and name={quoted(name)}'
        if folders is True:query+=f" and mimeType='{FOLDER}'"
        if folders is False:query+=f" and mimeType!='{FOLDER}'"
        return self.list(query)

    def ensure_folder(self,parent,name):
        existing=self.children(parent,name,folders=True)
        if existing:return sorted(existing,key=lambda f:(f.get('createdTime',''),f['id']))[0]['id']
        return self.request(API+'?supportsAllDrives=true&fields=id',method='POST',body={'name':name,'mimeType':FOLDER,'parents':[self.folder_id(parent)]})['id']

    def create_bytes(self,parent,name,data,mime='application/json',app_properties=None):
        """Small multipart upload (locks, manifests). createdTime is assigned by Drive."""
        boundary='mandu'+uuid.uuid4().hex
        meta={'name':name,'parents':[self.folder_id(parent)],'appProperties':app_properties or {}}
        body=(f'--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(meta)}\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n').encode()+data+f'\r\n--{boundary}--'.encode()
        return self.request(UPLOAD+'?uploadType=multipart&supportsAllDrives=true&fields=id,name,createdTime,modifiedTime,md5Checksum,appProperties',method='POST',body=body,headers={'Content-Type':'multipart/related; boundary='+boundary})

    def update_bytes(self,file_id,data,mime='application/json'):
        return self.request(UPLOAD+'/'+quote(file_id,safe='')+'?uploadType=media&supportsAllDrives=true&fields=id,name,md5Checksum,modifiedTime',method='PATCH',body=data,headers={'Content-Type':mime})

    def delete(self,file_id):
        try:self.request(API+'/'+quote(file_id,safe='')+'?supportsAllDrives=true',method='DELETE')
        except RemoteError as exc:
            if '(404)' not in str(exc):raise

    def read_bytes(self,file_id):
        data,_=self.request(API+'/'+quote(file_id,safe='')+'?alt=media&supportsAllDrives=true',raw=True)
        return data

    def upload(self,path,folder,revision='',remote_id=None,app_properties=None):
        path=Path(path);size=path.stat().st_size;sha=digest(path);md5=digest(path,'md5')
        if not remote_id:remote_id=self.request(API+'/generateIds?count=1&space=drive')['ids'][0]
        else:
            try:
                existing=self.request(API+'/'+quote(remote_id,safe='')+'?fields=id,md5Checksum,name')
                if existing.get('md5Checksum')==md5:return existing
                raise RemoteError('업로드 대상 식별자가 다른 파일과 충돌했습니다.')
            except RemoteError as exc:
                if '(404)' not in str(exc):raise
        properties={'mandu_backup':'1','sha256':sha,'revision':revision,**(app_properties or {})}
        meta={'createdTime':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),'id':remote_id,'name':path.name,'parents':[self.folder_id(folder)],'appProperties':properties}
        data,headers=self.request(UPLOAD+'?uploadType=resumable&supportsAllDrives=true&fields=id,name,md5Checksum',method='POST',body=meta,headers={'X-Upload-Content-Type':'application/octet-stream','X-Upload-Content-Length':str(size)},raw=True)
        location=next((v for k,v in headers.items() if k.lower()=='location'),None)
        if not location:raise RemoteError('업로드를 시작하지 못했습니다.')
        result={}
        with path.open('rb') as f:
            offset=0
            while offset<size:
                chunk=f.read(8*1024*1024);end=offset+len(chunk)-1
                result=self.request(location,'PUT',chunk,{'Content-Type':'application/octet-stream','Content-Range':f'bytes {offset}-{end}/{size}'})
                offset=end+1
        if size==0:result=self.request(location,'PUT',b'',{'Content-Type':'application/octet-stream','Content-Range':'bytes */0'})
        if result.get('md5Checksum')!=md5:raise RemoteError('업로드 파일 검증에 실패했습니다. PC 백업은 보존됩니다.')
        return result

    def download(self,item,dest):
        fid=item['id']
        if not re.fullmatch(r'[A-Za-z0-9_-]+',fid):raise ValueError('파일 식별자를 확인해 주세요.')
        dest=Path(dest);tmp=dest.with_name(dest.name+'.part')
        try:
            request=Request(API+'/'+fid+'?alt=media&supportsAllDrives=true',headers={'Authorization':'Bearer '+self.access_token()})
            with urlopen(request,timeout=45) as response,tmp.open('wb') as out:
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk:break
                    out.write(chunk)
            if item.get('md5Checksum') and digest(tmp,'md5')!=item['md5Checksum']:raise RemoteError('다운로드 검증에 실패했습니다.')
            tmp.replace(dest);return dest
        except (URLError,OSError):raise RemoteUnavailable('파일을 내려받지 못했습니다. 인터넷 연결을 확인해 주세요.') from None
        finally:tmp.unlink(missing_ok=True)
