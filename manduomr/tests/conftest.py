import os
import sys
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(Path(__file__).resolve().parent))

import pytest

# Original 1.0.6 source in this repository; used only by regression comparisons.
LEGACY=ROOT.parent/'만두OMR-source_1.0.6'


@pytest.fixture
def legacy():
    if not (LEGACY/'localomr').is_dir():pytest.skip('만두OMR 1.0.6 원본 소스가 없어 비교 검사를 건너뜀')
    if str(LEGACY) not in sys.path:sys.path.append(str(LEGACY))
    import localomr
    return localomr


class SequenceRandom:
    """Deterministic stand-in for secrets.SystemRandom in 학번 tests."""
    def __init__(self,*values):self.values=list(values)
    def randrange(self,stop):
        value=self.values.pop(0) if self.values else 0
        return value%stop


@pytest.fixture
def seq_random():
    return SequenceRandom
