from pathlib import Path
from copy import deepcopy
import pytest
import pypdfium2 as pdfium
from PySide6.QtWidgets import QFileDialog,QMessageBox
from localomr.reports import report_pdf
from localomr.ui import MainWindow
from test_math import store,exam,scan,CONFIG,KEY
from test_v043 import app


@pytest.mark.parametrize('wrong',[0,1,2,3,8])
def test_dynamic_review_count_and_page_order(store,tmp_path,wrong):
    db,s=store;cfg=deepcopy(CONFIG)
    cfg['topics']=['지수로그함수','삼각함수','수열','함수극한연속','미분','적분']*5
    cfg['areas']=['수학Ⅰ']*22+['확통']*8
    e=exam(db,cfg);answers=KEY.copy()
    for q in range(wrong):answers[q]=None
    sid=scan(db,e,s,answers=answers);path=tmp_path/'report.pdf';report_pdf(path,db,[sid])
    with pdfium.PdfDocument(str(path)) as doc:
        assert len(doc)==2;pages=[]
        for page in doc:
            tp=page.get_textpage();pages.append(tp.get_text_range());tp.close();page.close()
    title=f'이번 시험의 우선 복습 {min(wrong,3)}문항' if wrong else '이번 시험은 모든 문항을 맞혔어요!'
    first,second=pages
    assert title in first and title not in second
    assert first.index('단원별 성취도 분석')<first.index(title)<first.index('클리닉 우선순위 분석')
    assert '문항별 채점표' not in first
    assert second.index('회차별 성적')<second.index('성적 추이 분석')<second.index('문항별 채점표')<second.index('오답률 상위 분석')
    if wrong==0:assert '정답률이 높은데 내가 틀린 문항' not in first


def test_existing_backup_never_overwritten_and_remains_restorable(store,tmp_path):
    db,s=store;path=db.backup(tmp_path/'keep.omrbackup');before=path.read_bytes()
    db.set_report_name('새로운 자료')
    with pytest.raises(FileExistsError):db.backup(path)
    assert path.read_bytes()==before
    fresh=db.backup(tmp_path/'fresh.omrbackup');assert fresh.read_bytes()!=before
    db.restore(path);assert db.report_name()!='새로운 자료'
    assert not list(tmp_path.glob('*.tmp'))


def test_backup_publish_race_does_not_replace_existing_file(store,tmp_path,monkeypatch):
    import os
    if os.name!='nt':pytest.skip('Windows no-replace rename')
    db,_=store;target=tmp_path/'race.omrbackup';original=Path.rename
    def concurrent_file(path,destination):
        Path(destination).write_bytes(b'other backup')
        return original(path,destination)
    monkeypatch.setattr(Path,'rename',concurrent_file)
    with pytest.raises(FileExistsError):db.backup(target)
    assert target.read_bytes()==b'other backup' and not list(tmp_path.glob('*.tmp'))


def test_accidental_backup_ui_preserves_selected_restore_file(store,tmp_path,app,monkeypatch):
    db,_=store;path=db.backup(tmp_path/'previous.omrbackup');before=path.read_bytes();db.set_report_name('현재 PC')
    w=MainWindow(db);w.score_exam.setCurrentIndex(1);warnings=[];titles=[];defaults=[]
    def choose(*args,**kwargs):
        titles.append(args[1]);defaults.append(args[2]);return str(path),''
    monkeypatch.setattr(QFileDialog,'getSaveFileName',choose)
    monkeypatch.setattr(QMessageBox,'warning',lambda *a:warnings.append(a[-1]))
    w.backup(other_location=True);w.backup(other_location=True)
    assert path.read_bytes()==before and len(warnings)==2 and '덮어쓸 수 없습니다' in warnings[0]
    assert defaults[0]!=defaults[1] and all('현재 PC →' in t for t in titles)
    assert not w.backup_button.icon().isNull() and not w.restore_button.icon().isNull()
    assert w.backup_button.parent()==w.restore_button.parent()==w.home_notice
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a:(str(path),''))
    w.restore();assert db.report_name()!='현재 PC' and path.read_bytes()==before
    w.hide();w.deleteLater()
