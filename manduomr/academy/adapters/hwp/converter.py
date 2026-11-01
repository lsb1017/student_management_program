"""한글(hwp) → PDF 변환. 한컴오피스 한글이 설치된 PC에서만 자동화(pywin32)로 동작함.

미설치 PC에서는 available()이 False이며, 화면에서 PDF를 함께 올리도록 안내함(기본안).
"""
from pathlib import Path


class HwpUnavailable(Exception):
    pass


class HwpConverter:
    PROG_ID='HWPFrame.HwpObject'

    def available(self):
        try:
            import win32com.client  # noqa: F401
            import pythoncom
            pythoncom.CoInitialize()
            from win32com.client import GetObject  # noqa: F401
            import winreg
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,self.PROG_ID))
            return True
        except Exception:
            return False

    def convert(self,hwp_path,pdf_path):
        hwp_path=Path(hwp_path).resolve();pdf_path=Path(pdf_path).resolve()
        if not self.available():raise HwpUnavailable('이 PC에는 한컴오피스 한글이 없어 자동 변환할 수 없습니다. PDF를 함께 올려 주세요.')
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        hwp=win32com.client.Dispatch(self.PROG_ID)
        try:
            # Security module registration avoids a file-access prompt when it is installed.
            try:hwp.RegisterModule('FilePathCheckDLL','FilePathCheckerModule')
            except Exception:pass
            hwp.SetMessageBoxMode(0x00000001)
            if not hwp.Open(str(hwp_path),'HWP','forceopen:true'):raise HwpUnavailable('한글 파일을 열지 못했습니다.')
            if not hwp.SaveAs(str(pdf_path),'PDF',''):raise HwpUnavailable('PDF로 저장하지 못했습니다.')
        finally:
            try:hwp.Clear(1);hwp.Quit()
            except Exception:pass
        if not pdf_path.is_file() or pdf_path.stat().st_size==0:raise HwpUnavailable('변환된 PDF가 비어 있습니다.')
        return pdf_path


class FakeHwpConverter:
    """Simulation: 'converts' by copying a prepared PDF."""
    def __init__(self,pdf=None):self.pdf=pdf
    def available(self):return self.pdf is not None
    def convert(self,hwp_path,pdf_path):
        if not self.pdf:raise HwpUnavailable('이 PC에는 한컴오피스 한글이 없어 자동 변환할 수 없습니다. PDF를 함께 올려 주세요.')
        Path(pdf_path).write_bytes(Path(self.pdf).read_bytes());return Path(pdf_path)
