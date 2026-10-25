from pathlib import Path
import sys

MATH_FORM_NAME='우리 수능 수학 OMR · 공통 + 선택 3과목 (기본)'


def math_form_path():
    base=Path(sys._MEIPASS) if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
    path=base/'assets/수능수학_기본OMR.pdf'
    if not path.is_file():raise FileNotFoundError('기본 OMR 파일이 없습니다. 배포 ZIP 전체를 압축 해제하세요.')
    return path
