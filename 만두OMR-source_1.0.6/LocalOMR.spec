# Build on Windows x64 with requirements-build.txt.
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root=Path(SPECPATH)
datas=[];binaries=[];hiddenimports=[]
datas.append((str(root/'assets/수능수학_기본OMR.pdf'),'assets'))
datas.append((str(root/'assets/학생_일괄등록_서식.xlsx'),'assets'))
datas.append((str(root/'assets/exam_reference_v042.json'),'assets'))
datas.append((str(root/'assets/question_reference_v044.json'),'assets'))
for name in ('LocalOMR.ico','app_icon_heart.png','smart_mandu.png','celebrate_mandu.png','busy_mandu_alpha.png','home_mascot.png','busy_mandu.png','import_mandu.png','exit_mandu.png','grade_mandu.png','report_cheer.png','report_genius.png','report_cute.png','NanumDaeGwangYuRi.ttf','NanumDaeGwangYuRi-LICENSE.txt','NanumPenScript-Regular.ttf','NanumPenScript-OFL.txt'):
    datas.append((str(root/'assets'/name),'assets'))
for name in ('computer_mandu.png','thumb_mandu.png','frustrated_mandu.png','melted_mandu.png','please_mandu.png','crazy_mandu.png','dead_mandu.png','running_mandu.png','arrow_mandu.png','popup_assignments.json'):
    datas.append((str(root/'assets'/name),'assets'))
datas.append((str(root/'assets/google_client.json'),'assets'))
for package in ('pypdfium2','pypdfium2_raw'):
    d,b,h=collect_all(package);datas+=d;binaries+=b;hiddenimports+=h

a=Analysis([str(root/'main.py')],pathex=[str(root)],binaries=binaries,datas=datas,
           hiddenimports=hiddenimports,hookspath=[],hooksconfig={},runtime_hooks=[],
           excludes=[],noarchive=False,optimize=0)
# Qt 6.12 imports the Windows ICU shim's unversioned API. A Python runtime may
# carry ICU 78 with the same DLL name but versioned exports. Do not shadow the
# operating system's shim with that unrelated DLL (verified on Windows 10).
a.binaries=[entry for entry in a.binaries if Path(entry[0]).name.lower() not in ('icuuc.dll','icudt78.dll')]
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='만두OMR',debug=False,
        bootloader_ignore_signals=False,strip=False,upx=False,console=False,
        disable_windowed_traceback=False,icon=str(root/'assets/LocalOMR.ico'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='만두OMR')
