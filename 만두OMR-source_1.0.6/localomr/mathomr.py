"""Geometry measured from the user's math sheet; no source product code/assets."""
import cv2
import numpy as np
from PIL import Image
from .omr import ReadResult, png_bytes
from .mark_reader import MarkReader

SIZE = (1682, 1190)
MARKERS = np.float32([[59,60],[1584,60],[1584,1112],[59,1112]])
NUMERIC = {16,17,18,19,20,21,22,29,30}
ELECTIVES = {'1':'확률과 통계','2':'미적분','3':'기하'}
# Printed name grid: three syllables, each with initial/vowel/final columns.
NAME_CONSONANTS='ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ'
NAME_VOWELS='ㅏㅑㅓㅕㅗㅛㅜㅠㅡㅣㅐㅒㅔㅖㅘㅚㅝㅟㅢ'
HANGUL_INITIALS='ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
HANGUL_VOWELS='ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ'
HANGUL_FINALS=' ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ'


def name_centers(syllable,part):
    labels=NAME_VOWELS if part==1 else NAME_CONSONANTS
    return [(365.5+28.7*(syllable*3+part),553+30.25*r) for r in range(len(labels))]


def read_name(rgb):
    groups=[[group(rgb,name_centers(s,p),list(NAME_VOWELS if p==1 else NAME_CONSONANTS)) for p in range(3)] for s in range(3)]
    if all(g['flag']=='blank' for syllable in groups for g in syllable):return {'name':None,'flag':'blank','groups':groups}
    chars=[];ended=False;flag='clear'
    for syllable in groups:
        first,vowel,last=syllable
        if all(g['flag']=='blank' for g in syllable):ended=True;continue
        if ended or first['flag']=='blank' or vowel['flag']=='blank':flag='incomplete';break
        if any(g['flag']=='multiple' for g in syllable):flag='multiple';break
        if any(g['flag']=='faint' for g in syllable):flag='faint';break
        initial=HANGUL_INITIALS.index(first['answer']);middle=HANGUL_VOWELS.index(vowel['answer']);final=HANGUL_FINALS.index(last['answer']) if last['answer'] else 0
        chars.append(chr(0xAC00+(initial*21+middle)*28+final))
    return {'name':''.join(chars) if flag=='clear' else None,'flag':flag,'groups':groups}


def centers(q):
    """One-based question number; numeric returns hundreds/tens/units groups."""
    if q <= 10:
        return [(697+26.7*i,155+43.3*(q-1)) for i in range(5)]
    if q <= 15:
        return [(898+26.5*i,155+43.3*(q-11)) for i in range(5)]
    if 23 <= q <= 28:
        return [(1369+26.4*i,328+43.4*(q-23)) for i in range(5)]
    x,y = {16:(1065,155),17:(1186,155),18:(665,702),19:(786,702),
           20:(907,702),21:(1027,702),22:(1149,702),29:(1335,702),30:(1456,702)}[q]
    return [[(x+30.4*p,y+43.3*d) for d in range(10)] for p in range(3)]


def question_rect(q):
    pts=centers(q)
    if q in NUMERIC:pts=[p for col in pts for p in col]
    xs,ys=zip(*pts)
    return (int(min(xs)-18),int(min(ys)-20),int(max(xs)-min(xs)+36),int(max(ys)-min(ys)+40))


def id_centers(pos):
    return [(191+28.8*pos,555+47.4*d) for d in range(10)]


def align(img,scale=1):
    rgb=np.array(img.convert('RGB'))
    for turns in range(4):
        arr=np.ascontiguousarray(np.rot90(rgb,turns));h,w=arr.shape[:2]
        # Scanner exposure can turn the printed black markers into mid-gray.
        # Broaden only marker detection; retain geometry and internal form checks.
        for threshold in (115,150,185):
            mask=(arr.max(axis=2)<threshold).astype(np.uint8)*255
            contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            candidates=[]
            for c in contours:
                x,y,cw,ch=cv2.boundingRect(c)
                if .003*w<cw<.018*w and .3<cw/ch<1.8 and cv2.contourArea(c)/(cw*ch)>.65:
                    candidates.append((x+cw/2,y+ch/2,cw,ch))
            pts=[]
            for right,bottom in [(False,False),(True,False),(True,True),(False,True)]:
                near=[p for p in candidates if (p[0]>.85*w if right else p[0]<.15*w)
                      and (p[1]>.85*h if bottom else p[1]<.15*h)
                      and (.5<p[3]/p[2]<1.5 if bottom else 1.5<p[3]/p[2]<3.5)]
                if not near:break
                tx,ty=(.942*w if right else .035*w),(.934*h if bottom else .05*h)
                pts.append(min(near,key=lambda p:(p[0]-tx)**2+(p[1]-ty)**2)[:2])
            if len(pts)!=4:continue
            source=np.float32(pts)
            if abs(cv2.contourArea(source))<.5*w*h:continue
            matrix=cv2.getPerspectiveTransform(source,MARKERS*scale)
            normal=cv2.warpPerspective(arr,matrix,tuple(round(v*scale) for v in SIZE),borderValue=(255,255,255))
            # Four corner marks alone cannot identify a form.
            gray=cv2.cvtColor(cv2.resize(normal,SIZE) if scale!=1 else normal,cv2.COLOR_RGB2GRAY)
            anchors=[(650,200),(650,450),(820,300),(850,200),(1020,300),
                     (1051,400),(1262,400),(1321,400),(1491,500),(650,850),
                     (740,1000),(771,900),(1012,950),(1224,900),(1533,950)]
            hits=sum(gray[y-5:y+6,x-5:x+6].min()<220 for x,y in anchors)
            if hits < 12:continue
            return Image.fromarray(normal),turns*90
    raise ValueError('수능 수학 양식의 4개 기준점 또는 내부 답란이 맞지 않습니다. 모서리 잘림·기울기·다른 양식을 확인하세요.')


def level(rgb,xy):
    x,y=map(lambda v:int(round(v)),xy)
    patch=rgb[y-9:y+10,x-4:x+5].max(axis=2)
    yy,xx=np.ogrid[-9:10,-4:5]
    inside=(xx/4)**2+(yy/9)**2<=1
    # Ratio of genuinely dark ink, not the green outlines/numbers.
    return round(float((patch[inside]<120).mean()),4)


def group(rgb,pts,labels):
    if isinstance(rgb,MarkReader):return rgb.group(pts,labels)
    levels=[level(rgb,p) for p in pts];idx=sorted(range(len(levels)),key=lambda i:levels[i],reverse=True)
    top,second=levels[idx[0]],levels[idx[1]]
    if top<.22:answer,flag=None,'blank'
    elif second>=.50:answer,flag=None,'multiple'
    elif top<.78 or second>.28 or top-second<.50:answer,flag=labels[idx[0]],'faint'
    else:answer,flag=labels[idx[0]],'clear'
    return {'answer':answer,'flag':flag,'levels':levels}


def recognize_math(img,id_digits=5):
    scale=2 if max(img.size)>2400 else 1
    try:normal,rotation=align(img,scale)
    except ValueError as exc:
        return ReadResult(None,[{'answer':None,'flag':'failed','levels':[]} for _ in range(30)],None,error=str(exc))
    rgb=MarkReader(np.array(normal));answers=[]
    for q in range(1,31):
        pts=centers(q)
        if q not in NUMERIC:
            answers.append(group(rgb,pts,list(range(1,6))));continue
        # Hundreds zero is not printed. Leading blank places are allowed; interior gaps are not.
        digits=[group(rgb,p[1:] if i==0 else p,list(range(1,10)) if i==0 else list(range(10))) for i,p in enumerate(pts)]
        marked=[i for i,d in enumerate(digits) if d['flag']!='blank']
        value=None
        if not marked:flag='blank'
        elif any(d['flag']=='multiple' for d in digits):flag='multiple'
        elif any(d['flag']=='blank' for d in digits[min(marked):]):flag='incomplete'
        else:
            value=sum((d['answer'] or 0)*10**(2-i) for i,d in enumerate(digits))
            flag='faint' if any(d['flag']=='faint' for d in digits) else 'clear'
        answers.append({'answer':value,'flag':flag,'levels':[d['levels'] for d in digits],'digits':digits})
    digits=[group(rgb,id_centers(p),list(range(10))) for p in range(id_digits)]
    # The supplied blank has a green prefilled 1 in the final ID column.
    # If no black suffix is written, keep that default; explicit black 2..9 overrides it.
    if digits[-1]['flag']=='blank':digits[-1]={'answer':1,'flag':'clear','levels':digits[-1]['levels'],'default':True}
    code=''.join(str(d['answer']) for d in digits).zfill(6) if all(d['flag']=='clear' for d in digits) else None
    choice=group(rgb,[(1337,115),(1337,156),(1337,199)],['1','2','3'])
    result=ReadResult(png_bytes(normal.resize(SIZE,Image.Resampling.LANCZOS) if scale!=1 else normal),answers,code,rotation)
    result.elective=choice['answer'] if choice['flag']=='clear' else None
    result.choice_reading=choice
    result.identity_reading={'phone_tail':''.join(str(d['answer']) for d in digits[:4]) if all(d['flag']=='clear' for d in digits[:4]) else None,
                             'suffix_defaulted':bool(digits[-1].get('default')),'digits':digits,'name':read_name(rgb)}
    return result
