"""M1 판독: recognize(page, form) → ReadResult, for generated and externally registered forms."""
from __future__ import annotations
import io
import numpy as np
from PIL import Image
from core.omr import ReadResult,png_bytes,darkness
from academy.pdf.align import warp_markers,align_features
from .generator import signature_centers


def read_group(gray,centers,labels,radius=8):
    """1.0.6 read_group thresholds with a configurable bubble radius."""
    levels=[round(darkness(gray,(int(round(x)),int(round(y))),radius),4) for x,y in centers]
    ordered=sorted(range(len(levels)),key=lambda i:levels[i],reverse=True)
    top,second=levels[ordered[0]],levels[ordered[1]]
    if top<.10:answer,flag=None,'blank'
    elif second>=.28:answer,flag=None,'multiple'
    elif top<.55 or second>.12 or top-second<.4:answer,flag=labels[ordered[0]],'faint'
    else:answer,flag=labels[ordered[0]],'clear'
    return {'answer':answer,'flag':flag,'levels':levels}


def read_numeric(gray,places,radius):
    digits=[read_group(gray,column,list(range(10)),radius) for column in places]
    marked=[i for i,d in enumerate(digits) if d['flag']!='blank']
    value=None
    if not marked:flag='blank'
    elif any(d['flag']=='multiple' for d in digits):flag='multiple'
    elif any(d['flag']=='blank' for d in digits[min(marked):]):flag='incomplete'
    else:
        value=sum((d['answer'] or 0)*10**(len(digits)-1-i) for i,d in enumerate(digits))
        flag='faint' if any(d['flag']=='faint' for d in digits) else 'clear'
    return {'answer':value,'flag':flag,'levels':[d['levels'] for d in digits],'digits':digits}


def failed(count,message):
    return ReadResult(None,[{'answer':None,'flag':'failed','levels':[]} for _ in range(count)],None,error=message)


def _read(normal,layout,rotation):
    gray=np.array(normal.convert('L'));radius=layout.get('radius',8)
    labels=list(range(1,layout['choice_count']+1));answers=[]
    for item in layout['questions']:
        if item['kind']=='choice':answers.append(read_group(gray,item['centers'],labels,radius))
        else:answers.append(read_numeric(gray,item['places'],radius))
    digits=[read_group(gray,column,list(range(10)),radius) for column in layout['id']['centers']]
    code=''.join(str(d['answer']) for d in digits) if all(d['flag']=='clear' for d in digits) else None
    result=ReadResult(png_bytes(normal),answers,code,rotation)
    tail=''.join(str(d['answer']) for d in digits[:4]) if all(d['flag']=='clear' for d in digits[:4]) else None
    # Auxiliary identity: exact 7-digit 학번 first, then the phone tail (core.identity).
    result.identity_reading={'phone_tail':tail,'code_digits':len(digits),'digits':digits,'name':{'flag':'blank','name':None}}
    return result


def recognize(img,layout,reference=None):
    count=len(layout['questions'])
    if layout.get('reader','markers')=='markers':
        expected=layout['signature']
        def check(normal):
            gray=np.array(Image.fromarray(normal).convert('L'))
            observed=[int(gray[y-4:y+5,x-4:x+5].mean()<130) for x,y in signature_centers()]
            return observed==expected
        try:normal,rotation,_=warp_markers(img,layout['markers'],layout['size'],check)
        except ValueError:return failed(count,'사용자 정의 양식의 기준점/양식 번호를 찾지 못했습니다. 이 시험의 양식으로 인쇄했는지 확인하세요.')
        return _read(normal,layout,rotation)
    if reference is None:raise ValueError('외부 양식의 빈 양식 이미지가 필요합니다.')
    try:normal,_,_=align_features(img,reference)
    except ValueError as exc:return failed(count,str(exc))
    return _read(normal,layout,0)


def reference_gray(store,form):
    """Blank external form image (file box) as the alignment reference."""
    data=store.file_bytes(form['blank_hash'])
    with Image.open(io.BytesIO(data)) as im:
        return np.array(im.convert('L'))
