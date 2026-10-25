"""Canonical course/unit labels, including legacy spreadsheet column layouts."""
import re
from .examdata import ELECTIVES
from .report_labels import ALIASES

COURSES={'수학I':'수학Ⅰ','수학1':'수학Ⅰ','수학Ⅰ':'수학Ⅰ',
         '수학II':'수학Ⅱ','수학2':'수학Ⅱ','수학Ⅱ':'수학Ⅱ',
         '확률과통계':'확통','확통':'확통','미적분':'미적분','기하':'기하'}

def course_name(value):
    return COURSES.get(re.sub(r'\s+','',str(value or '')),'')

def unit_name(value):
    value=re.sub(r'\s+','',str(value or ''))
    value=re.sub(r'\((수학Ⅱ|수학II|미적분)\)$','',value)
    return ALIASES.get(value,value)

def course_for(result,q):
    for field in ('areas','skills'):
        values=result.get(field,[])
        if q<len(values) and course_name(values[q]):return course_name(values[q])
    if q>=22:return course_name(ELECTIVES.get(str(result.get('elective')),''))
    topic=unit_name(result.get('topics',['']*30)[q])
    if topic in ('지수로그함수','삼각함수','수열'):return '수학Ⅰ'
    if topic in ('함수극한연속','미분','적분'):return '수학Ⅱ'
    return ''

def detail_for(result,q):
    # Some old exports put the course in 'skills' and the objective in 'areas'.
    area=result.get('areas',['']*len(result['topics']))[q]
    skill=result.get('skills',['']*len(result['topics']))[q]
    return area if course_name(skill) and not course_name(area) else skill

def normalize_config(config):
    for part in [config,*config.get('variants',{}).values()]:
        areas=part.get('areas',[]);skills=part.get('skills',[])
        for q in range(min(len(areas),len(skills))):
            if course_name(skills[q]) and not course_name(areas[q]):
                areas[q],skills[q]=skills[q],areas[q]
    return config
