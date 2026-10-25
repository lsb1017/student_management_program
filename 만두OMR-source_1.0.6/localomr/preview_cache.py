"""Only manages previews created here; never touches user export directories."""
from hashlib import sha256
from pathlib import Path
import re
from . import __version__
from .reports import report_pdf


def cache_files(store):
    folder=store.path.parent/'preview_cache'
    if not folder.exists() or folder.is_symlink():return []
    return [p for p in folder.iterdir() if p.is_file() and not p.is_symlink() and re.fullmatch(r'preview_\d+_[a-f0-9]{24}\.pdf',p.name)]


def clear_cache(store):
    removed=0;busy=0
    for path in cache_files(store):
        try:size=path.stat().st_size;path.unlink();removed+=size
        except OSError:busy+=1
    return removed,busy


def preview_pdf(store,sid):
    # Any data edit (including peers' answers, historic data, cuts and branding)
    # invalidates the result. total_changes is specific to this DB connection.
    token=(__version__,store.db.execute('SELECT MAX(id) FROM audit').fetchone()[0],
           store.db.total_changes,store.db.execute('PRAGMA data_version').fetchone()[0])
    digest=sha256(repr(token).encode()).hexdigest()[:24]
    folder=store.path.parent/'preview_cache';folder.mkdir(exist_ok=True)
    path=folder/f'preview_{int(sid)}_{digest}.pdf'
    if not path.exists():
        staging=folder/f'preview_{int(sid)}_{digest}.tmp'
        try:report_pdf(staging,store,[sid]);staging.replace(path)
        finally:staging.unlink(missing_ok=True)
    for old in cache_files(store):
        if old!=path and old.name.startswith(f'preview_{int(sid)}_'):
            try:old.unlink()
            except OSError:pass # A PDF viewer can hold an old preview open on Windows.
    return path
