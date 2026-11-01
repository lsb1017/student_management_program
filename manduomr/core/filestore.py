"""Content-addressed file box outside the database. A written file never changes."""
from pathlib import Path
import hashlib
import os
import re
import uuid

DIGEST=re.compile(r'[0-9a-f]{64}')
EXTENSION=re.compile(r'[a-z0-9]{1,8}')


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def object_name(digest,ext):
    if not DIGEST.fullmatch(digest or '') or not EXTENSION.fullmatch(ext or ''):
        raise ValueError('파일함 식별자가 올바르지 않습니다.')
    return f'{digest}.{ext}'


def split_name(name):
    digest,_,ext=str(name).partition('.')
    object_name(digest,ext)
    return digest,ext


class FileStore:
    """data/files/<hash 앞 2자리>/<SHA-256>.<확장자>"""

    def __init__(self,root):
        self.root=Path(root)

    def path(self,digest,ext):
        return self.root/digest[:2]/object_name(digest,ext)

    def find(self,digest):
        if not DIGEST.fullmatch(digest or ''):return None
        folder=self.root/digest[:2]
        if not folder.is_dir():return None
        return next((p for p in folder.glob(digest+'.*') if not p.name.endswith('.tmp')),None)

    def exists(self,digest):
        return self.find(digest) is not None

    def _publish(self,temp,digest,ext):
        target=self.path(digest,ext);target.parent.mkdir(parents=True,exist_ok=True)
        try:
            if target.exists():return digest
            os.replace(temp,target)
        finally:
            Path(temp).unlink(missing_ok=True)
        return digest

    def put_bytes(self,data,ext):
        digest=sha256_bytes(data);ext=ext.lower().lstrip('.')
        if self.path(digest,ext).exists():return digest
        self.root.mkdir(parents=True,exist_ok=True)
        temp=self.root/(uuid.uuid4().hex+'.tmp');temp.write_bytes(data)
        return self._publish(temp,digest,ext)

    def put_file(self,source,ext=None):
        source=Path(source);ext=(ext or source.suffix or '.bin').lower().lstrip('.')
        self.root.mkdir(parents=True,exist_ok=True)
        temp=self.root/(uuid.uuid4().hex+'.tmp');h=hashlib.sha256()
        try:
            with source.open('rb') as src,temp.open('wb') as out:
                for chunk in iter(lambda:src.read(1024*1024),b''):h.update(chunk);out.write(chunk)
            return self._publish(temp,h.hexdigest(),ext)
        finally:
            temp.unlink(missing_ok=True)

    def read(self,digest):
        path=self.find(digest)
        if path is None:raise FileNotFoundError('파일함에 없는 파일입니다: '+str(digest)[:12])
        data=path.read_bytes()
        if sha256_bytes(data)!=digest:raise ValueError('파일함의 파일이 손상되었습니다: '+digest[:12])
        return data

    def copy_to(self,digest,target):
        Path(target).write_bytes(self.read(digest))
        return Path(target)
