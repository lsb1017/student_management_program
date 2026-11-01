"""Read-only enrichment of imported scores; never rewrites saved grades."""
from functools import lru_cache
from pathlib import Path
import json,sys
from .catalog import title_key
from .classification import course_name
from .examdata import ELECTIVES

@lru_cache(maxsize=1)
def catalog():
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
    return {title_key(e['title']):e for e in json.loads((root/'assets/question_reference_v044.json').read_text('utf-8'))['exams']}

def enrich(result):
    entry=catalog().get(title_key(result['title']))
    result.update(topics=['']*30,areas=['']*30,skills=['']*30,points=[0]*30,
                  correctness=[None]*30,key=[None]*30,analysis_conflicts=[],analysis_source='')
    if entry is None:return result
    result['analysis_source']=entry['source']
    choice=course_name(ELECTIVES.get(str(result.get('elective')),''))
    for item in entry['questions']:
        q=item['q']-1
        if q>=22 and course_name(item['course'])!=choice:continue
        result['topics'][q]=item['unit'];result['areas'][q]=item['course']
        result['skills'][q]=item['detail'];result['points'][q]=item['points'];result['key'][q]=item['key']
        ox=result['ox'][q] if q<len(result['ox']) else ''
        original=True if ox=='O' else False if ox=='X' else None
        earned=result['earned'][q] if q<len(result['earned']) else None
        if original is not None and earned is not None and (earned>0)!=original:
            result['analysis_conflicts'].append(q+1);continue
        if item['key'] is not None:
            answer=result['answers'][q] if q<len(result['answers']) else None
            try:answer=int(answer) if answer is not None else None
            except (TypeError,ValueError):answer=None
            calculated=answer==item['key']
            if original is not None and calculated!=original:
                result['analysis_conflicts'].append(q+1);continue
            result['correctness'][q]=calculated
        else:
            result['correctness'][q]=original
    return result
