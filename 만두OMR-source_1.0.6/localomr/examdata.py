"""Typed answers, elective keys, manually supplied grade thresholds."""
from copy import deepcopy
from decimal import Decimal

NUMERIC={16,17,18,19,20,21,22,29,30}
ELECTIVES={'1':'확률과 통계','2':'미적분','3':'기하'}


def numeric(exam,q):
    return exam.get('config',{}).get('form')=='math30' and q in NUMERIC


def valid_key(value,is_numeric):
    return type(value)==int and (0<=value<=999 if is_numeric else 1<=value<=5)


def effective(exam,elective=None):
    e=deepcopy(exam);cfg=e.get('config',{});n=len(e['key'])
    e['topics']=(cfg.get('topics',[])+['미분류']*n)[:n]
    e['skills']=(cfg.get('skills',[])+['']*n)[:n]
    e['kinds']=cfg.get('kinds',['숫자답안' if cfg.get('form')=='math30' and i+1 in NUMERIC else '선다형' for i in range(n)])
    for field,default in [('areas',''),('difficulties',''),('conditions','and')]:
        e[field]=(cfg.get(field,[])+[default]*n)[:n]
    e['configured']=True
    if cfg.get('form')=='math30':
        if str(elective)!=cfg.get('primary','1'):
            tail=cfg.get('variants',{}).get(str(elective))
            if tail:
                e['key']=e['key'][:22]+tail['key']
                e['points']=e['points'][:22]+[int(Decimal(str(p))*100) for p in tail['points']]
                e['topics']=e['topics'][:22]+tail['topics']
                e['skills']=e['skills'][:22]+tail['skills']
                e['kinds']=e['kinds'][:22]+tail.get('kinds',['선다형']*6+['숫자답안']*2)
                for field,default in [('areas',''),('difficulties',''),('conditions','and')]:
                    e[field]=e[field][:22]+tail.get(field,[default]*8)
            else:e['key']=e['key'][:22]+[None]*8;e['configured']=False
    e['cuts']=cfg.get('cuts',{}).get(str(elective) if cfg.get('form')=='math30' else '0',[])
    return e


def grade(score,cuts):
    if not cuts:return None
    for i,cut in enumerate(cuts):
        if score>=int(Decimal(str(cut))*100):return i+1
    return '6등급 이하' if len(cuts)==5 else 9


def estimated_percentile(score,maximum,cuts):
    """Reference conversion, NOT a measured/national percentile. Scores use cents.

    Grade 1..8 cut anchors use 96,89,77,60,40,23,11,4. Interpolate
    linearly between anchors; add zero and full-score endpoints when distinct.
    When a cut equals an endpoint, the cut anchor takes precedence.
    """
    if len(cuts) not in (5,8) or maximum<=0 or not 0<=score<=maximum:return None
    values=[Decimal(str(v))*100 for v in cuts]
    if values[0]>maximum or values[-1]<0 or any(a<=b for a,b in zip(values,values[1:])):return None
    if len(cuts)==5 and score<values[-1]:return None
    anchors=dict(zip(values,map(Decimal,(96,89,77,60,40,23,11,4))))
    anchors.setdefault(Decimal(0),Decimal(0))
    anchors.setdefault(Decimal(maximum),Decimal(100))
    ordered=sorted(anchors.items());value=Decimal(score)
    if value in anchors:return float(anchors[value])
    for (lo,p_lo),(hi,p_hi) in zip(ordered,ordered[1:]):
        if lo<value<hi:return float(p_lo+(value-lo)/(hi-lo)*(p_hi-p_lo))
    return None


def percentile_label(result):
    value=result['estimated_percentile']
    if value is not None:return f'{value:.1f}'
    if len(result['cuts'])==5 and result['grade']=='6등급 이하':return '40 미만'
    return '컷 미설정'


def validate_config(config,key,points,convert):
    c=deepcopy(config or {});form=c.setdefault('form','local60');n=len(key)
    if form not in ('local60','math30'):raise ValueError('지원하지 않는 OMR 양식입니다.')
    if form=='math30' and n!=30:raise ValueError('수능 수학 양식은 30문항입니다.')
    if any(not valid_key(k,form=='math30' and i+1 in NUMERIC) for i,k in enumerate(key)):
        raise ValueError('객관식 정답은 1~5, 숫자형 정답은 0~999로 입력하세요.')
    for field,default in [('topics','미분류'),('skills',''),('areas',''),('difficulties',''),('conditions','and')]:
        values=c.get(field,[default]*n)
        if len(values)!=n:raise ValueError('영역 정보의 문항 수가 다릅니다.')
        c[field]=[str(v).strip()[:80] or default for v in values]
    if form=='math30':
        c['id_digits']=5;c.setdefault('primary','1')
        if c['primary'] not in ELECTIVES:raise ValueError('선택과목을 지정하세요.')
    expected=['숫자답안' if form=='math30' and i+1 in NUMERIC else '선다형' for i in range(n)]
    c.setdefault('kinds',expected)
    if c['kinds']!=expected:raise ValueError('문제형태가 OMR 답란과 다릅니다. 수학 16~22·29~30번은 숫자답안이며 나머지는 선다형입니다.')
    if c.get('require_all_choices') and form=='math30' and set(c.get('variants',{}))!={k for k in ELECTIVES if k!=c['primary']}:
        raise ValueError('확률과 통계·미적분·기하를 모두 입력하세요.')
    for choice,v in c.get('variants',{}).items():
        if choice not in ELECTIVES or len(v.get('key',[]))!=8 or len(v.get('points',[]))!=8:raise ValueError('선택과목 정답·배점을 8문항 모두 입력하세요.')
        if any(not valid_key(k,i>=6) for i,k in enumerate(v['key'])):raise ValueError('선택과목 정답이 올바르지 않습니다.')
        [convert(p) for p in v['points']]
        v.setdefault('kinds',['선다형']*6+['숫자답안']*2)
        if v['kinds']!=['선다형']*6+['숫자답안']*2:raise ValueError(ELECTIVES[choice]+' 문제형태가 OMR 답란과 다릅니다. 23~28번 선다형, 29~30번 숫자답안입니다.')
        for field,default in [('topics','미분류'),('skills',''),('areas',''),('difficulties',''),('conditions','and')]:
            if len(v.get(field,[]))!=8:v[field]=[default]*8
        if sum(points[:22])+sum(convert(p) for p in v['points'])<=0:raise ValueError('만점은 0보다 커야 합니다.')
    if any(v.lower()!='and' for v in c.get('conditions',[])) or any(v.lower()!='and' for variant in c.get('variants',{}).values() for v in variant.get('conditions',[])):
        raise ValueError('현재는 단일 정답(and) 채점조건을 지원합니다.')
    for choice,cuts in c.get('cuts',{}).items():
        if not cuts:continue
        if choice not in ('0','1','2','3') or len(cuts) not in (5,8):raise ValueError('1~5등급 컷을 입력하세요. 6~8등급까지 사용할 때는 8개를 모두 입력하세요. 전체를 비우면 등급을 표시하지 않습니다.')
        values=[convert(v) for v in cuts]
        maximum=sum(points)
        if choice in c.get('variants',{}):maximum=sum(points[:22])+sum(convert(p) for p in c['variants'][choice]['points'])
        if values[0]>maximum or values[-1]<0 or any(a<=b for a,b in zip(values,values[1:])):
            raise ValueError('등급컷은 만점 이하에서 1등급부터 차례로 엄격히 낮아져야 합니다.')
    return c
