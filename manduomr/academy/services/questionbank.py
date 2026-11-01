"""M4 문항은행: 회차별 문제·해설 한글 파일 등록·PDF 변환, 문항 영역·이미지, 유사문항·해설 연결."""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from core.store import now
from academy.pdf.textsearch import question_regions,render_region

KINDS=('문제','해설','유사')


def register_edition(store,exam_id,path,kind='문제',pdf=None,converter=None):
    """hwp를 올리면 한글 자동화로 PDF 변환, 한글이 없으면 pdf를 함께 받음. PDF만 올려도 됨."""
    if kind not in KINDS:raise ValueError('문제·해설·유사 중에서 고르세요.')
    path=Path(path);hwp_hash=''
    with TemporaryDirectory() as tmp:
        if path.suffix.lower() in ('.hwp','.hwpx'):
            with store.transaction():hwp_hash=store.put_file(path)
            if pdf is None:
                if converter is None or not converter.available():raise ValueError('이 PC에는 한컴오피스 한글이 없어 자동 변환할 수 없습니다. PDF를 함께 올려 주세요.')
                pdf=converter.convert(path,Path(tmp)/'converted.pdf')
        elif path.suffix.lower()=='.pdf':pdf=path
        else:raise ValueError('한글(.hwp) 또는 PDF 파일을 선택하세요.')
        with store.transaction():
            pdf_hash=store.put_file(pdf,'pdf')
            store.db.execute('INSERT INTO question_sources(exam_id,kind,hwp_hash,pdf_hash,created_at) VALUES(?,?,?,?,?) ON CONFLICT(exam_id,kind) DO UPDATE SET hwp_hash=excluded.hwp_hash,pdf_hash=excluded.pdf_hash,created_at=excluded.created_at',
                             (exam_id,kind,hwp_hash,pdf_hash,now()))
            store.log('question_source_registered',exam_id,{'kind':kind,'hwp':bool(hwp_hash),'pdf_hash':pdf_hash})
    return pdf_hash


def source_pdf(store,exam_id,kind='문제'):
    rows=store.rows('SELECT pdf_hash FROM question_sources WHERE exam_id=? AND kind=?',(exam_id,kind))
    if not rows:raise ValueError(f'{kind} 파일을 먼저 등록하세요.')
    return store.files.path(rows[0]['pdf_hash'],'pdf')


def _png(image):
    buf=BytesIO();image.save(buf,'PNG');return buf.getvalue()


def split_questions(store,exam_id,dpi=150):
    """문항 번호 위치로 문항 영역을 잘라 이미지로 저장. 수동 편집한 문항은 덮어쓰지 않음."""
    exam=store.exam(exam_id);count=len(exam['key']);pdf=source_pdf(store,exam_id,'문제')
    regions=question_regions(pdf,count)
    manual={r['q_no'] for r in store.rows("SELECT q_no FROM question_items WHERE exam_id=? AND method='manual'",(exam_id,))}
    with store.transaction():
        for q,box in regions.items():
            if q in manual:continue
            image=render_region(pdf,box['page'],(box['x0'],box['y0'],box['x1'],box['y1']),dpi)
            digest=store.put_bytes(_png(image),'png')
            store.db.execute("INSERT INTO question_items(exam_id,q_no,page,x0,y0,x1,y1,image_hash,method) VALUES(?,?,?,?,?,?,?,?,'auto') ON CONFLICT(exam_id,q_no) DO UPDATE SET page=excluded.page,x0=excluded.x0,y0=excluded.y0,x1=excluded.x1,y1=excluded.y1,image_hash=excluded.image_hash",
                             (exam_id,q,box['page'],box['x0'],box['y0'],box['x1'],box['y1'],digest))
        store.log('questions_split',exam_id,{'found':sorted(regions),'count':count})
    missing=[q for q in range(1,count+1) if q not in regions and q not in manual]
    if store.rows("SELECT 1 FROM question_sources WHERE exam_id=? AND kind='해설'",(exam_id,)):attach_solutions(store,exam_id,dpi)
    return {'found':sorted(regions),'missing':missing}


def set_region(store,exam_id,q_no,page,box,dpi=150):
    """영역 편집 화면에서 고친 문항 영역(점 단위, 왼쪽 위 기준)."""
    pdf=source_pdf(store,exam_id,'문제');x0,y0,x1,y1=box
    if x1-x0<10 or y1-y0<10:raise ValueError('문항 영역이 너무 작습니다.')
    image=render_region(pdf,page,box,dpi)
    with store.transaction():
        digest=store.put_bytes(_png(image),'png')
        store.db.execute("INSERT INTO question_items(exam_id,q_no,page,x0,y0,x1,y1,image_hash,method) VALUES(?,?,?,?,?,?,?,?,'manual') ON CONFLICT(exam_id,q_no) DO UPDATE SET page=excluded.page,x0=excluded.x0,y0=excluded.y0,x1=excluded.x1,y1=excluded.y1,image_hash=excluded.image_hash,method='manual'",
                         (exam_id,q_no,page,x0,y0,x1,y1,digest))
        store.log('question_region_edited',exam_id,{'q_no':q_no,'page':page,'box':list(box)})


def attach_solutions(store,exam_id,dpi=150):
    """해설 파일도 문항 번호로 나눠 같은 번호 문항에 연결."""
    pdf=source_pdf(store,exam_id,'해설');count=len(store.exam(exam_id)['key'])
    regions=question_regions(pdf,count);linked=[]
    with store.transaction():
        for q,box in regions.items():
            item=store.rows('SELECT id FROM question_items WHERE exam_id=? AND q_no=?',(exam_id,q))
            if not item:continue
            digest=store.put_bytes(_png(render_region(pdf,box['page'],(box['x0'],box['y0'],box['x1'],box['y1']),dpi)),'png')
            store.db.execute('UPDATE question_items SET solution_hash=? WHERE id=?',(digest,item[0]['id']));linked.append(q)
        store.log('solutions_attached',exam_id,{'linked':linked})
    return linked


def items(store,exam_id):
    return store.rows('SELECT * FROM question_items WHERE exam_id=? ORDER BY q_no',(exam_id,))


def unregistered(store,exam_id):
    count=len(store.exam(exam_id)['key'])
    have={r['q_no'] for r in store.rows("SELECT q_no FROM question_items WHERE exam_id=? AND image_hash<>''",(exam_id,))}
    return [q for q in range(1,count+1) if q not in have]


def _meta(store,item):
    from core.examdata import effective
    exam=effective(store.exam(item['exam_id']));q=item['q_no']-1
    return {'unit':exam['topics'][q],'difficulty':exam['difficulties'][q]}


def similar_candidates(store,question_id,limit=10):
    """같은 단원·난이도의 다른 회차 문항을 후보로 제시함(확정은 담당자)."""
    base=store.rows('SELECT * FROM question_items WHERE id=?',(question_id,))
    if not base:raise ValueError('문항을 선택하세요.')
    target=_meta(store,base[0]);out=[]
    for item in store.rows("SELECT * FROM question_items WHERE exam_id<>? AND image_hash<>'' ORDER BY exam_id DESC,q_no",(base[0]['exam_id'],)):
        meta=_meta(store,item)
        if meta['unit']==target['unit'] and meta['unit'] not in ('','미분류') and meta['difficulty']==target['difficulty']:
            out.append({**item,**meta})
        if len(out)>=limit:break
    return out


def link_similar(store,question_id,similar_ids):
    ids=list(dict.fromkeys(similar_ids))
    if question_id in ids:raise ValueError('같은 문항은 유사문항으로 연결할 수 없습니다.')
    with store.transaction():
        store.db.execute('DELETE FROM similar_links WHERE question_id=?',(question_id,))
        store.db.executemany('INSERT INTO similar_links(question_id,similar_id,rank) VALUES(?,?,?)',[(question_id,sid,i+1) for i,sid in enumerate(ids)])
        store.log('similar_linked',question_id,{'similar_ids':ids})
