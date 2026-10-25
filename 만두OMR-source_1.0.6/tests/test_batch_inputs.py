from pathlib import Path
import pypdfium2 as pdfium
from localomr.store import Store
from localomr.reports import sheet_pdf
from localomr.omr import load_pages
from localomr.importer import import_files


def test_multipage_pdf_and_tiff(tmp_path):
    one=tmp_path/'one.pdf';two=tmp_path/'two.pdf';batch=tmp_path/'batch.pdf'
    sheet_pdf(one,3,'first','000001',[1,2,3]);sheet_pdf(two,3,'second','000002',[3,2,1])
    merged=pdfium.PdfDocument.new()
    for p in [one,two]:
        with pdfium.PdfDocument(p) as doc:merged.import_pages(doc)
    merged.save(batch);merged.close()
    pages=list(load_pages(batch));assert len(pages)==2
    tif=tmp_path/'batch.tiff';pages[0][1].save(tif,save_all=True,append_images=[pages[1][1]])
    assert len(list(load_pages(tif)))==2
    s=Store(tmp_path/'test.sqlite3');a=s.academy('학원');c=s.classroom(a,'반');s.save_student('1','학생1',c);s.save_student('2','학생2',c)
    eid=s.save_exam('시험','시리즈','과목','1','2026-10-18',[1,2,3],[1,1,1])
    result=import_files(s.path,eid,[batch]);assert result['added']==2 and result['failed']==0
    again=import_files(s.path,eid,[tif]);assert again['duplicate']==2 and len(s.scans(eid))==2
    s.close()


def test_corrupt_file_is_logged_and_next_file_continues(tmp_path):
    bad=tmp_path/'bad.pdf';bad.write_bytes(b'bad')
    good=tmp_path/'good.pdf';sheet_pdf(good,3)
    s=Store(tmp_path/'test.sqlite3');eid=s.save_exam('시험','시리즈','과목','1','2026-10-18',[1,2,3],[1,1,1])
    result=import_files(s.path,eid,[bad,good]);assert len(result['errors'])==1 and result['added']==1
    assert s.rows("SELECT * FROM audit WHERE kind='import_failed'")
    s.close()
