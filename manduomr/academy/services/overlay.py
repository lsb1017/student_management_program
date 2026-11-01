"""M7 손풀이 삽입: [손풀이] 영역 탐지, 문제지 스캔의 학생 매칭, 스캔 정렬, 합성.

1. 원본 문제지 PDF에서 [손풀이] 문자열을 찾아 둘러싼 상자를 문항 번호와 묶어 저장(없으면 수동 지정).
2. 손풀이는 회차·문항별 PNG(투명 배경) 또는 PDF 쪽으로 미리 등록.
3. 인쇄용 문제지에는 기준점·쪽 표지와 첫 쪽 7자리 학번 버블을 넣고, 스캔 첫 쪽의 학번으로 학생을 찾음.
4. 스캔 쪽을 원본 쪽에 정렬해 영역 좌표를 스캔 좌표로 바꾸고 손풀이를 비율 유지로 배치함.
5. 원본 스캔은 고치지 않고 학생별 결과 PDF를 새로 만듦. 대상은 전체(기본) 또는 OMR 오답 문항.
"""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import cv2
import numpy as np
from PIL import Image
import pypdfium2 as pdfium
from core.store import now
from core.omr import load_pages
from academy.config import program_setting
from academy.forms.reader import read_group
from academy.pdf import compose as stamp_geometry
from academy.pdf.align import warp_markers
from academy.pdf.textsearch import find_text,render_page,question_regions
from academy.services.questionbank import source_pdf

LABEL='[손풀이]'


def _png(image):
    buf=BytesIO();image.save(buf,'PNG');return buf.getvalue()


def enclosing_box(pdf,page_index,label,dpi=100):
    """Smallest drawn rectangle containing the label; None when the box is not a drawn rectangle."""
    image,(width,height)=render_page(pdf,page_index,dpi);scale=dpi/72
    gray=np.array(image.convert('L'));_,mask=cv2.threshold(gray,180,255,cv2.THRESH_BINARY_INV)
    contours,_=cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    cx=(label[0]+label[2])/2*scale;cy=(label[1]+label[3])/2*scale;best=None
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if w<40*scale or h<30*scale or not (x<cx<x+w and y<cy<y+h):continue
        if w>gray.shape[1]*.95 and h>gray.shape[0]*.95:continue
        approx=cv2.approxPolyDP(contour,.02*cv2.arcLength(contour,True),True)
        if len(approx)!=4:continue
        if best is None or w*h<best[2]*best[3]:best=(x,y,w,h)
    if best is None:return None
    x,y,w,h=best
    return (x/scale,y/scale,(x+w)/scale,(y+h)/scale)


def detect_slots(store,exam_id):
    pdf=source_pdf(store,exam_id,'문제');count=len(store.exam(exam_id)['key'])
    regions={r['q_no']:r for r in store.rows('SELECT * FROM question_items WHERE exam_id=?',(exam_id,))} or question_regions(pdf,count)
    manual={r['q_no'] for r in store.rows("SELECT q_no FROM solution_slots WHERE exam_id=? AND method='manual'",(exam_id,))}
    found={};unassigned=[]
    for page,x0,top,x1,bottom in find_text(pdf,LABEL):
        cx,cy=(x0+x1)/2,(top+bottom)/2
        q=next((q for q,r in regions.items() if r['page']==page and r['x0']<=cx<=r['x1'] and r['y0']<=cy<=r['y1']),None)
        if q is None:unassigned.append((page,cx,cy));continue
        box=enclosing_box(pdf,page,(x0,top,x1,bottom))
        if box is None:
            region=regions[q];box=(x0,top,region['x1'],min(region['y1'],top+150))
        found[q]=(page,box)
    with store.transaction():
        for q,(page,(x0,y0,x1,y1)) in found.items():
            if q in manual:continue
            store.db.execute("INSERT INTO solution_slots(exam_id,q_no,page,x0,y0,x1,y1,method) VALUES(?,?,?,?,?,?,?,'auto') ON CONFLICT(exam_id,q_no) DO UPDATE SET page=excluded.page,x0=excluded.x0,y0=excluded.y0,x1=excluded.x1,y1=excluded.y1",
                             (exam_id,q,page,x0,y0,x1,y1))
        store.log('solution_slots_detected',exam_id,{'found':sorted(found),'unassigned':len(unassigned)})
    return {'found':sorted(found),'unassigned':unassigned,'no_text':not found and not unassigned}


def set_slot(store,exam_id,q_no,page,box):
    x0,y0,x1,y1=box
    if x1-x0<20 or y1-y0<20:raise ValueError('손풀이 영역이 너무 작습니다.')
    with store.transaction():
        store.db.execute("INSERT INTO solution_slots(exam_id,q_no,page,x0,y0,x1,y1,method) VALUES(?,?,?,?,?,?,?,'manual') ON CONFLICT(exam_id,q_no) DO UPDATE SET page=excluded.page,x0=excluded.x0,y0=excluded.y0,x1=excluded.x1,y1=excluded.y1,method='manual'",
                         (exam_id,q_no,page,x0,y0,x1,y1))
        store.log('solution_slot_edited',exam_id,{'q_no':q_no,'page':page,'box':list(box)})


def register_hand_solution(store,exam_id,q_no,path,author=''):
    """PNG(투명 배경 권장) 또는 태블릿 PDF의 첫 쪽. 흰 배경은 투명하게 바꿔 원래 글씨가 가려지지 않게 함."""
    path=Path(path)
    if path.suffix.lower()=='.pdf':
        doc=pdfium.PdfDocument(str(path))
        try:image=doc[0].render(scale=200/72).to_pil()
        finally:doc.close()
    elif path.suffix.lower()=='.png':image=Image.open(path)
    else:raise ValueError('손풀이는 PNG 또는 PDF로 등록하세요.')
    image=stamp_geometry.transparent(image)
    with store.transaction():
        digest=store.put_bytes(_png(image),'png')
        store.db.execute('INSERT INTO hand_solutions(exam_id,q_no,image_hash,author,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(exam_id,q_no) DO UPDATE SET image_hash=excluded.image_hash,author=excluded.author,updated_at=excluded.updated_at',
                         (exam_id,q_no,digest,author,now()))
        store.log('hand_solution_registered',exam_id,{'q_no':q_no,'author':author})
    return digest


def worksheet_pdf(store,exam_id,out_path):
    """인쇄용 문제지(원본 + 기준점·쪽 표지 + 첫 쪽 학번 버블)."""
    position=program_setting(store,'worksheet_id_position')
    return stamp_geometry.stamp(source_pdf(store,exam_id,'문제'),out_path,exam_id,position)


def _page_sizes(store,exam_id):
    doc=pdfium.PdfDocument(str(source_pdf(store,exam_id,'문제')))
    try:return [doc[i].get_size() for i in range(len(doc))]
    finally:doc.close()


def read_page(img,exam_id,sizes,position):
    """Align a scanned worksheet page; return (page_index, code, normalized->scan matrix, rotated scan)."""
    scale=stamp_geometry.DPI/72;expected_head=list(stamp_geometry.HEADER)
    for index,(width,height) in enumerate(sizes):
        targets=[(x*scale,y*scale) for x,y in stamp_geometry.marker_centers(width,height)]
        size=(round(width*scale),round(height*scale))
        def check(normal):
            gray=cv2.cvtColor(normal,cv2.COLOR_RGB2GRAY)
            bits=[int(gray[int(y*scale)-3:int(y*scale)+4,int(x*scale)-3:int(x*scale)+4].mean()<130) for x,y in stamp_geometry.bit_centers()]
            return bits[:4]==expected_head and bits==stamp_geometry.bits_for(exam_id,index)
        try:normal,rotation,matrix=warp_markers(img,targets,size,check)
        except ValueError:continue
        rotated=img.rotate(rotation,expand=True) if rotation else img
        code=None
        if index==0:
            gray=np.array(normal.convert('L'))
            digits=[read_group(gray,[(x*scale,y*scale) for x,y in column],list(range(10)),radius=6) for column in stamp_geometry.id_centers(width,height,position)]
            code=''.join(str(d['answer']) for d in digits) if all(d['flag']=='clear' for d in digits) else None
        return index,code,np.linalg.inv(matrix),rotated.convert('RGB')
    return None


def import_worksheets(store,exam_id,scan_path,progress=lambda text:None):
    """스캔 PDF(여러 학생 연속) → 학생별 문제지. 학번을 못 읽으면 검수 대기(pending)."""
    sizes=_page_sizes(store,exam_id);position=program_setting(store,'worksheet_id_position')
    with store.transaction():source=store.put_file(scan_path)
    groups=[];orphans=[]
    for number,img in load_pages(scan_path):
        progress(f'문제지 스캔 {number}쪽 확인 중')
        read=read_page(img,exam_id,sizes,position)
        if read is None:orphans.append(number);continue
        index,code,inverse,rotated=read
        if index==0 or not groups:groups.append({'code':code,'pages':[]})
        with store.transaction():digest=store.put_bytes(_png(rotated),'png')
        groups[-1]['pages'].append({'hash':digest,'page_index':index,'inverse':inverse.tolist(),'scan_page':number})
    created=[]
    with store.transaction():
        for group in groups:
            student=store.rows('SELECT id FROM students WHERE code=? AND active=1',(group['code'],)) if group['code'] else []
            status='matched' if student else 'pending'
            detail={'pages':group['pages'],'code':group['code'],'notice':'' if student else '학번을 읽지 못했거나 등록되지 않은 학번입니다. 학생을 직접 연결하세요.'}
            wid=store.db.execute('INSERT INTO worksheets(exam_id,student_id,source_hash,page_hashes,pages,status,detail,created_at) VALUES(?,?,?,?,?,?,?,?)',
                                 (exam_id,student[0]['id'] if student else None,source,json.dumps([p['hash'] for p in group['pages']]),len(group['pages']),status,json.dumps(detail),now())).lastrowid
            created.append(wid)
        store.log('worksheets_imported',exam_id,{'worksheets':created,'unreadable_pages':orphans})
    return {'worksheets':created,'unreadable_pages':orphans}


def link_worksheet(store,worksheet_id,student_id):
    with store.transaction():
        store.db.execute("UPDATE worksheets SET student_id=?,status='matched' WHERE id=?",(student_id,worksheet_id))
        store.log('worksheet_linked',worksheet_id,{'student_id':student_id})


def compose(store,worksheet_id,out_path,target=None):
    ws=store.rows('SELECT * FROM worksheets WHERE id=?',(worksheet_id,))[0]
    if not ws['student_id']:raise ValueError('학생을 먼저 연결하세요.')
    target=target or program_setting(store,'overlay_target');exam_id=ws['exam_id']
    slots={r['q_no']:r for r in store.rows('SELECT * FROM solution_slots WHERE exam_id=?',(exam_id,))}
    solutions={r['q_no']:r for r in store.rows('SELECT * FROM hand_solutions WHERE exam_id=?',(exam_id,))}
    wanted=set(slots)
    if target=='wrong':
        result=store.results(exam_id,ws['student_id'])
        if not result:raise ValueError('확정 성적이 없어 오답 문항을 알 수 없습니다. 전체 문항으로 만들거나 먼저 확정하세요.')
        wanted&=set(result[0]['wrong'])
    sizes=_page_sizes(store,exam_id);scale=stamp_geometry.DPI/72;detail=json.loads(ws['detail']);pages=[];placed=[]
    for page in detail['pages']:
        scan=Image.open(BytesIO(store.file_bytes(page['hash']))).convert('RGB');inverse=np.array(page['inverse'])
        overlays=[]
        for q in sorted(wanted):
            slot=slots[q]
            if slot['page']!=page['page_index'] or q not in solutions:continue
            corners=np.float32([[[slot['x0']*scale,slot['y0']*scale]],[[slot['x1']*scale,slot['y0']*scale]],[[slot['x1']*scale,slot['y1']*scale]],[[slot['x0']*scale,slot['y1']*scale]]])
            mapped=cv2.perspectiveTransform(corners,inverse).reshape(-1,2)
            # Anchor at the mapped top-left corner; the slot's real edge lengths give the size.
            tl,tr,br,bl=mapped
            box=(tl[0],tl[1],tl[0]+float(np.linalg.norm(tr-tl)),tl[1]+float(np.linalg.norm(bl-tl)))
            image=Image.open(BytesIO(store.file_bytes(solutions[q]['image_hash'])))
            overlays.append((image,stamp_geometry.place_into(box,image.size)));placed.append(q)
        pages.append({'scan':scan,'size':sizes[page['page_index']],'overlays':overlays})
    stamp_geometry.compose_pages(pages,out_path)
    with store.transaction():
        digest=store.put_file(out_path,'pdf')
        store.db.execute("UPDATE worksheets SET result_hash=?,status='composed' WHERE id=?",(digest,worksheet_id))
        store.log('overlay_composed',worksheet_id,{'questions':placed,'target':target})
    return {'path':Path(out_path),'questions':placed}
