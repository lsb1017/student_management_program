# Build on Windows x64 with requirements-dev.txt:  .\build.ps1
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root=Path(SPECPATH)
datas=[(str(p),'assets') for p in (root/'assets').iterdir() if p.is_file()]
datas+=[(str(root/'viewer'/name),'viewer') for name in ('Code.gs','index.html','appsscript.json')]
datas.append((str(root/'academy'/'adapters'/'kakao'/'selectors.json'),'academy/adapters/kakao'))
binaries=[];hiddenimports=['win32com.client','pythoncom']
for package in ('pypdfium2','pypdfium2_raw','playwright'):
    d,b,h=collect_all(package);datas+=d;binaries+=b;hiddenimports+=h

a=Analysis([str(root/'main.py')],pathex=[str(root)],binaries=binaries,datas=datas,hiddenimports=hiddenimports,
           hookspath=[],hooksconfig={},runtime_hooks=[],excludes=['pytest'],noarchive=False,optimize=0)
# Same ICU exclusion as 만두OMR 1.0.6: keep the Windows ICU shim Qt 6.12 expects.
a.binaries=[entry for entry in a.binaries if Path(entry[0]).name.lower() not in ('icuuc.dll','icudt78.dll')]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='학원성적관리',debug=False,bootloader_ignore_signals=False,strip=False,upx=False,
        console=False,disable_windowed_traceback=False,icon=str(root/'assets'/'LocalOMR.ico'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='학원성적관리')
