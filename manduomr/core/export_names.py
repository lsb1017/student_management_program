"""Compact names for exported files; stored organization/exam names stay intact."""
from datetime import date
import re


def short_name(value):
    value=re.sub(r'확률\s*과\s*통계','확통',str(value or '').strip())
    if '필요충분' in value:
        season=re.search(r'시즌\s*(\d+)',value);round_no=re.search(r'(\d+)\s*회',value)
        if season and round_no:return f'필충모 시즌{season[1]}-{round_no[1]}회차'
        value=re.sub(r'^(?:20\d\d\s*)?(?:수능\s*)?필요충분\s*모의고사','필충모',value)
    value=re.sub(r'[<>:"/\\|?*\x00-\x1f]','-',value)
    value=re.sub(r'\s+',' ',value).strip(' .')
    return value[:70].rstrip(' .') or '미지정'


def group_name(values,unit):
    # Count distinct full labels, even if two abbreviations happen to coincide.
    names=sorted(set(str(v or '미지정') for v in values))
    if not names:return '미지정'
    return short_name(names[0])+(f' 외 {len(names)-1}개{unit}' if len(names)>1 else '')


def export_name(rows,kind='report',saved_on=None):
    day=(saved_on or date.today()).isoformat()
    academy=group_name([r['snapshot'].get('academy') for r in rows],'학원')
    if kind=='rank':
        title=group_name([r['title'] for r in rows],'시험')
        return f'{title}_{academy}_{day}.xlsx'
    classroom=group_name([r['snapshot'].get('classroom') for r in rows],'반')
    return f'{academy}_{classroom}_성적표_{day}.pdf'
