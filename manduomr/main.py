"""학원 성적·학생 관리 통합 프로그램 진입점.

  python main.py [--data-dir DIR] [--simulate-drive FOLDER]
  python main.py --smoke-test result.json     # 가상 자료로 전체 흐름 점검(창 없이)
"""
from pathlib import Path
import argparse
import os
import sys
import traceback


def smoke_test(out):
    """Packaged-runtime check with synthetic data: two PCs, forms, grading, reports, publishing."""
    import json,tempfile
    from datetime import datetime
    from academy.app import App
    from academy.forms.generator import save_generated,render_pdf
    from academy.services import grading,entries,notify
    from academy.services.report import render
    from academy.adapters.kakao.base import FakeMessenger
    result={'ok':False}
    with tempfile.TemporaryDirectory(prefix='academy_smoke_') as tmp:
        tmp=Path(tmp);drive=tmp/'drive'
        a=App(tmp/'pc_a',drive);session=a.backup_service().open_session('점검','청솔')
        store=session.store;store.set_operator('점검',a.local.pc_id)
        cid=store.classroom(store.academy('청솔'),'청솔(토)','토');sid=store.save_student('5678123','점검학생',cid)
        fid=save_generated(store,'점검 양식',5,5,[5])
        eid=store.save_exam('점검 주간지 1회','점검','수학','1','2026-11-01',[1,2,3,4,123],[20]*5,config={'areas':['대수']*5},exam_kind='weekly',form_id=fid)
        sheet=render_pdf(store.form(fid)['layout'],tmp/'sheet.pdf','점검','5678123',[1,2,3,4,123])
        summary=grading.import_pdf(store,eid,[sheet],store.classes()[0]['academy_id'],cid,'2026-11-01')
        done,_=grading.confirm_clear(store,eid,[s['id'] for s in store.scans(eid)])
        entries.save(store,cid,'2026-11-01',[{'student_id':sid,'mini_score':'10','homework':'A'}])
        render(store,done,tmp/'report.pdf')
        session_row=entries.session(store,cid,'2026-11-01');store.set_setting('viewer_url','https://example.invalid/exec')
        published=notify.publish(store,session_row['id'],a.publisher(store))
        sent=notify.notify_session(store,session_row['id'],FakeMessenger(friend_count=1),at=datetime(2026,11,1,15,0))
        a.backup_service().close_session(store,'청솔');store.close()
        b=App(tmp/'pc_b',drive);other=b.backup_service().open_session('점검B','청솔')
        result.update(imported=summary['added'],confirmed=len(done),score=other.store.results(eid)[0]['score']/100,published=len(published),notice=sent['status'],
                      handoff=other.restored,pages_ok=(tmp/'report.pdf').stat().st_size>0)
        b.backup_service().close_session(other.store,'청솔');other.store.close()
        os.environ['QT_QPA_PLATFORM']='offscreen'
        from PySide6.QtWidgets import QApplication,QMessageBox
        QMessageBox.information=lambda *a,**k:None   # no modal boxes in an unattended check
        from academy.ui.common import STYLE,install_fonts
        from academy.ui.main_window import MainWindow
        qt=QApplication.instance() or QApplication([]);install_fonts(qt);qt.setStyleSheet(STYLE)
        c=App(tmp/'pc_c',drive);service=c.backup_service();s=service.open_session('화면점검','청솔')
        window=MainWindow(c,service,s);window.show()
        for i in range(window.nav.count()):window.nav.setCurrentRow(i);qt.processEvents()
        window.grab().save(str(Path(out).with_suffix('.png')))
        window.close();result['ui_pages']=window.nav.count()
    result['ok']=result['score']==100 and result['confirmed']==1 and result['published']==1 and result['handoff'].endswith('.omrbackup')
    Path(out).write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    return 0 if result['ok'] else 1


def main():
    parser=argparse.ArgumentParser(description='학원 성적·학생 관리 통합 프로그램')
    parser.add_argument('--data-dir',type=Path)
    parser.add_argument('--simulate-drive',type=Path,help='Google Drive 대신 쓸 폴더(시험 운영)')
    parser.add_argument('--smoke-test',type=Path)
    args=parser.parse_args()
    if args.smoke_test:return smoke_test(args.smoke_test)
    from PySide6.QtWidgets import QApplication,QMessageBox,QDialog
    from academy.config import default_data_dir
    from academy.app import App
    from academy.ui.common import STYLE,install_fonts
    from academy.ui.start import StartDialog
    from academy.ui.main_window import MainWindow
    qt=QApplication(sys.argv);qt.setApplicationName('학원 성적·학생 관리');qt.setStyle('Fusion');install_fonts(qt);qt.setStyleSheet(STYLE)
    data_dir=(args.data_dir or default_data_dir()).resolve()
    try:
        from PySide6.QtCore import QLockFile
        data_dir.mkdir(parents=True,exist_ok=True)
        lock=QLockFile(str(data_dir/'session.lock'));lock.setStaleLockTime(0)
        if not lock.tryLock(100):
            QMessageBox.warning(None,'이미 실행 중','이 데이터 폴더를 쓰는 프로그램이 이미 실행 중입니다.');return 1
        app=App(data_dir,args.simulate_drive)
        start=StartDialog(app)
        if start.exec()!=QDialog.DialogCode.Accepted or not start.session:return 0
        window=MainWindow(app,start.service,start.session);window.show()
        def report_error(kind,value,tb):
            (data_dir/'last_error.log').write_text(''.join(traceback.format_exception(kind,value,tb)),encoding='utf-8')
            QMessageBox.warning(window,'처리 오류',str(value))
        sys.excepthook=report_error
        return qt.exec()
    except Exception as exc:
        QMessageBox.critical(None,'시작할 수 없습니다',f'{exc}\n쓰기 가능한 폴더에서 실행하세요.');return 1


if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    sys.exit(main())
