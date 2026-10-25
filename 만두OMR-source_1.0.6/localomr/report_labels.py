"""Compact report labels; original question metadata stays intact."""
import re


ALIASES={
    '지수함수와로그함수':'지수로그함수',
    '지수와로그함수':'지수로그함수',
    '함수의극한과연속':'함수극한연속',
    '함수의극한및연속':'함수극한연속',
    '미분법의활용':'미분법활용',
    '적분법의활용':'적분법활용',
    '경우의수와확률':'경우의수확률',
    '확률분포와통계적추정':'확률분포추정',
    '평면벡터의성분과내적':'평면벡터',
    '공간도형과공간좌표':'공간도형좌표',
}


def area_label(area,classification=''):
    """Use a short existing area name, otherwise its registered classification.

    Long learning objectives are not truncated or guessed from isolated words.
    Unmapped long classifications remain visibly unresolved rather than wrong.
    """
    for raw in (area,classification):
        original=str(raw or '').strip()
        if original and len(original)<=6:return original
        value=re.sub(r'[\s·ㆍ,/]+','',str(raw or ''))
        value=ALIASES.get(value,value)
        if value and len(value)<=6:return value
    return '분류 확인' if area or classification else '미입력'
