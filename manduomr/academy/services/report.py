"""M3 성적표 2종(주간지·모의고사). render(kind, scan_ids) → PDF.

모의고사 = 1.0.6 수학 성적표(core.report_math) 그대로. 주간지 = report_weekly.
기타 유형은 시험 설정 report_kind(weekly|mock)로 사용자가 고름. 모의고사 양식은 수능수학 30문항만 가능.
"""
from pathlib import Path
from tempfile import TemporaryDirectory


def report_kind(exam):
    kind=exam['exam_kind']
    if kind=='other':kind=exam['config'].get('report_kind','weekly')
    if kind=='mock' and exam['config'].get('form')!='math30':kind='weekly'
    return kind


def render(store,scan_ids,path,kind=None):
    """Merge one report per confirmed scan, in the given order. Pending answers never enter."""
    import pypdfium2 as pdfium
    from core.report_math import report_math
    from core.history import results as historical_results
    from core.report_insights import cohort_error_rates
    from .report_weekly import weekly_report
    results={r['id']:r for r in store.results()}
    if not scan_ids or any(i not in results for i in scan_ids):raise ValueError('확정된 성적만 성적표로 출력할 수 있습니다.')
    rates=None
    with TemporaryDirectory(prefix='academy_report_') as folder:
        merged=pdfium.PdfDocument.new()
        try:
            for index,sid in enumerate(scan_ids):
                exam=store.exam(results[sid]['exam_id']);chosen=kind or report_kind(exam)
                if chosen=='mock' and exam['config'].get('form')!='math30':raise ValueError('모의고사 성적표는 수능수학 30문항 시험만 만들 수 있습니다.')
                part=Path(folder)/f'{index}.pdf'
                if chosen=='mock':
                    if rates is None:rates=cohort_error_rates(list(results.values())+historical_results(store,for_report=True))
                    report_math(part,store,sid,question_rates=rates)
                else:weekly_report(part,store,sid)
                doc=pdfium.PdfDocument(str(part))
                try:merged.import_pages(doc)
                finally:doc.close()
            merged.save(str(path))
        finally:merged.close()
    with store.transaction():store.log('report_exported',None,{'scan_ids':list(scan_ids),'kind':kind})
    return Path(path)
