"""Personal review priorities from confirmed answers and entered question metadata."""
from decimal import Decimal
from .examdata import grade
from .classification import course_for,unit_name


def grade_target(result):
    score=result['score'];maximum=result['maximum'];cuts=result['cuts']
    if score==maximum:return '만점 달성'
    current=grade(score,cuts)
    if current is None:return ''
    if current==1:return f'만점까지 {(maximum-score)/100:g}점'
    target=len(cuts) if isinstance(current,str) else current-1
    threshold=int(Decimal(str(cuts[target-1]))*100)
    return f'{target}등급까지 {(threshold-score)/100:g}점'


def _type_key(result,q):
    return course_for(result,q),unit_name(result['topics'][q])


def question_correctness(result,q):
    if result.get('historical'):
        values=result.get('correctness',[])
        return values[q] if q<len(values) else None
    key=result['key'][q]
    return result['answers'][q]==key if key is not None else None


def question_rate_key(result,q):
    # Linked imports and local grades represent the same exam. Keep elective
    # questions and different answer keys separate, even at the same number.
    eid=result.get('linked_exam_id') or result['exam_id']
    return eid,q,str(result['elective']) if q>=22 else '',result['key'][q]


def cohort_error_rates(records):
    totals={};seen=set()
    # A confirmed local result takes precedence over an imported duplicate.
    for result in sorted(records,key=lambda r:bool(r.get('historical'))):
        identity=(result.get('linked_exam_id') or result['exam_id'],result.get('student_id'))
        if identity[1] is not None:
            if identity in seen:continue
            seen.add(identity)
        for q in range(len(result['answers'])):
            correct=question_correctness(result,q)
            if correct is None:continue
            counts=totals.setdefault(question_rate_key(result,q),[0,0])
            counts[0]+=not correct;counts[1]+=1
    return {key:wrong/total*100 for key,(wrong,total) in totals.items()}


def classified_questions(result,elective):
    for q,answer in enumerate(result['answers']):
        if q>=22 and str(result['elective'])!=str(elective):continue
        key=_type_key(result,q)
        if not all(key) or key[1] in ('미분류','미입력','분류확인','공통','선택','기하','미적분','확통','확률과통계'):continue
        correct=question_correctness(result,q)
        if correct is not None:yield q,key,correct


def analysis_coverage(history,elective,question_rates=None):
    usable=[r for r in history if any(question_rates is None or question_rate_key(r,q) in question_rates
        for q,_,_ in classified_questions(r,elective))]
    return len(usable),len(history)


def unit_history(history,elective,question_rates=None):
    groups={}
    for result in history[-6:]:
        for q,key,correct in classified_questions(result,elective):
            rate=question_rates.get(question_rate_key(result,q)) if question_rates is not None else None
            if question_rates is not None and rate is None:continue
            item=groups.setdefault(key,{'key':key,'course':key[0],'topic':key[1],
                'total':0,'wrong':0,'rounds':set(),'wrong_rounds':set(),'lost_points':0,'overall_wrong_sum':0})
            item['total']+=1;item['rounds'].add(result['exam_id'])
            if rate is not None:item['overall_wrong_sum']+=rate
            if not correct:
                item['wrong']+=1;item['wrong_rounds'].add(result['exam_id']);item['lost_points']+=result['points'][q]
    rows=[]
    for item in groups.values():
        if not item['wrong']:continue
        item['rounds']=len(item['rounds']);item['wrong_rounds']=len(item['wrong_rounds'])
        item['wrong_rate']=item['wrong']/item['total']*100
        if question_rates is not None:
            item['overall_wrong_rate']=item['overall_wrong_sum']/item['total']
            item['rate_gap']=item['wrong_rate']-item['overall_wrong_rate']
        rows.append(item)
    return rows


def clinic_priorities(history,elective,limit=5,question_rates=None):
    # Both rates use precisely the same questions, each with equal weight.
    rows=unit_history(history,elective,question_rates or {})
    rows.sort(key=lambda x:(-round(x['rate_gap'],10),-x['wrong_rounds'],-x['wrong'],x['key']))
    return rows if limit is None else rows[:limit]


def review_questions(result,all_results,history,limit=3):
    types={x['key']:x for x in unit_history(history,result['elective'])}
    candidates=[]
    for q,answer in enumerate(result['answers']):
        if answer==result['key'][q]:continue
        eligible=[x for x in all_results if q<22 or str(x['elective'])==str(result['elective'])]
        rate=sum(x['answers'][q]==x['key'][q] for x in eligible)/len(eligible)*100 if eligible else 0
        item=types.get(_type_key(result,q),{})
        candidates.append({'q':q,'correct_rate':rate,'repeat_rounds':item.get('wrong_rounds',0),
            'points':result['points'][q]})
    candidates.sort(key=lambda x:(-x['correct_rate'],-max(0,x['repeat_rounds']-1),-x['points'],x['q']))
    return candidates[:limit]
