"""Worksheet stamping (corner markers, page code, 7-digit 학번 bubbles) and overlay composition.

Geometry is in PDF points with a top-left origin. Stamps sit in the page margins: four 12pt
corner squares, a 22-bit strip (header 1,0,0,1 + exam id 12 bits + page index 6 bits) in the
top margin, and on page 1 a 7×10 학번 bubble block at a configurable relative position.
"""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import numpy as np
from PIL import Image
from pypdf import PdfReader,PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from core.reports import fonts

DPI=150
HEADER=(1,0,0,1)
EXAM_BITS,PAGE_BITS=12,6
MARK,INSET=12,14
BIT_X0,BIT_STEP,BIT_SIZE=40,11,8
ID_DX,ID_DY,ID_R=13,10,4


def marker_centers(width,height):
    c=INSET+MARK/2
    return [(c,c),(width-c,c),(width-c,height-c),(c,height-c)]


def bits_for(exam_id,page_index):
    if not 0<exam_id<2**EXAM_BITS or not 0<=page_index<2**PAGE_BITS:raise ValueError('문제지 표지 번호 범위를 벗어났습니다.')
    return list(HEADER)+[(exam_id>>(EXAM_BITS-1-i))&1 for i in range(EXAM_BITS)]+[(page_index>>(PAGE_BITS-1-i))&1 for i in range(PAGE_BITS)]


def bit_centers():
    return [(BIT_X0+i*BIT_STEP+BIT_SIZE/2,INSET+MARK/2) for i in range(len(HEADER)+EXAM_BITS+PAGE_BITS)]


def id_block_origin(width,height,position):
    return (position[0]*width,position[1]*height+14)


def id_centers(width,height,position):
    ox,oy=id_block_origin(width,height,position)
    return [[(ox+8+p*ID_DX,oy+8+d*ID_DY) for d in range(10)] for p in range(7)]


def stamp(source_pdf,target_pdf,exam_id,position,codes_on_first=None):
    """Return the print-ready worksheet: stamps merged onto every original page (content untouched)."""
    fonts()
    writer=PdfWriter(clone_from=str(source_pdf))
    for index,page in enumerate(writer.pages):
        width,height=float(page.mediabox.width),float(page.mediabox.height)
        buf=BytesIO();c=canvas.Canvas(buf,pagesize=(width,height))
        for x,y in marker_centers(width,height):c.rect(x-MARK/2,height-y-MARK/2,MARK,MARK,fill=1,stroke=0)
        for (x,y),bit in zip(bit_centers(),bits_for(exam_id,index)):
            if bit:c.rect(x-BIT_SIZE/2,height-y-BIT_SIZE/2,BIT_SIZE,BIT_SIZE,fill=1,stroke=0)
        if index==0:
            ox,oy=id_block_origin(width,height,position)
            c.setFont('Korean',6.5);c.drawString(ox,height-oy+3,'학번 7자리')
            for p,column in enumerate(id_centers(width,height,position)):
                for d,(x,y) in enumerate(column):
                    if p==0:c.drawRightString(x-6,height-y-2,str(d))
                    c.setLineWidth(.6);c.circle(x,height-y,ID_R,stroke=1,fill=0)
                    if codes_on_first and int(codes_on_first[p])==d:c.circle(x,height-y,ID_R-.6,fill=1,stroke=0)
        c.showPage();c.save()
        page.merge_page(PdfReader(BytesIO(buf.getvalue())).pages[0])
    with open(target_pdf,'wb') as f:writer.write(f)
    return Path(target_pdf)


def place_into(box,image_size):
    """Fit an image into box (x0,y0,x1,y1) keeping its ratio, aligned top-left."""
    x0,y0,x1,y1=box;iw,ih=image_size
    scale=min((x1-x0)/iw,(y1-y0)/ih)
    return x0,y0,iw*scale,ih*scale


def compose_pages(pages,out_path):
    """pages: [{'scan':PIL, 'size':(w_pt,h_pt), 'overlays':[(PIL rgba, (x,y,w,h) in scan px)]}]."""
    c=canvas.Canvas(str(out_path))
    for p in pages:
        width,height=p['size'];scan=p['scan'];sw,sh=scan.size
        c.setPageSize((width,height));kx,ky=width/sw,height/sh
        c.drawImage(ImageReader(scan),0,0,width,height)
        for image,(x,y,w,h) in p['overlays']:
            c.drawImage(ImageReader(image),x*kx,height-(y+h)*ky,w*kx,h*ky,mask='auto')
        c.showPage()
    c.save();return Path(out_path)


def transparent(image,threshold=245):
    """White background → transparent (손풀이 PDF 쪽·흰 배경 PNG용)."""
    rgba=np.array(image.convert('RGBA'))
    white=(rgba[:,:,:3]>=threshold).all(axis=2);rgba[white,3]=0
    return Image.fromarray(rgba)
