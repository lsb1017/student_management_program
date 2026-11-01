"""Resolve an OMR identity. 7-digit 학번 matches first; phone tail and name are auxiliary.

1.0.6 codes were 0+tail+suffix; the new 학번 is tail(4)+random(3), so the tail is code[:4].
The 수능수학 sheet has only five ID columns (tail 4 + a suffix column printed with 1),
which cannot carry a 7-digit 학번. Its suffix column is therefore ignored, and the sheet
links by tail and name inside the selected class (ARCHITECTURE.md 기본안).
"""
import unicodedata


def normalized_name(value):
    return ''.join(unicodedata.normalize('NFC',value).split())


def name_advisory(context,student_name):
    """Non-blocking display hint, deliberately separate from blocking notices."""
    if context.get('manual_link'):return ''
    reading=context.get('identity_reading',{});name=reading.get('name',{})
    if (reading.get('method') in ('explicit_code','unique_phone') and name.get('flag')=='clear'
            and name.get('name') and student_name and normalized_name(name['name'])!=normalized_name(student_name)):
        return '이름 확인 필요'
    return ''


def resolve_student(db,result,academy_id=None,class_id=None):
    reading=getattr(result,'identity_reading',None)
    query='SELECT s.id,s.code,s.name,c.id class_id,c.academy_id FROM students s JOIN student_classes m ON m.student_id=s.id JOIN classes c ON c.id=m.class_id WHERE s.active=1'
    params=[]
    if academy_id is not None:query+=' AND c.academy_id=?';params.append(academy_id)
    if class_id is not None:query+=' AND c.id=?';params.append(class_id)
    if reading is None:
        return (db.execute(query+' AND s.code=?',(*params,result.code)).fetchone() if result.code else None),{}
    detail=dict(reading);detail.update(recognized_code=result.code,method='unresolved',notice='')
    if class_id is None:
        detail['notice']='자동 연결할 학원과 반을 선택하세요.';return None,detail
    roster=db.execute(query,params).fetchall()
    code=result.code if result.code and len(result.code)==7 and reading.get('code_digits')==7 else None
    if code:
        exact=[s for s in roster if s['code']==code]
        if len(exact)==1:detail['method']='explicit_code';return exact[0],detail
    tail=reading.get('phone_tail');name=reading.get('name') or {}
    phones=[s for s in roster if tail and s['code'][:4]==tail]
    names=[s for s in roster if name.get('flag')=='clear' and name.get('name') and normalized_name(s['name'])==normalized_name(name['name'])]
    if phones and names:
        common=[s for s in phones if any(s['id']==n['id'] for n in names)]
        if len(common)==1:detail['method']='phone_name';return common[0],detail
        detail['notice']='번호와 이름이 서로 다르거나 중복됩니다. 학생을 확인해 연결하세요.';return None,detail
    if len(phones)==1:
        detail['method']='unique_phone';return phones[0],detail
    if len(names)==1:
        detail['method']='unique_name';return names[0],detail
    detail['notice']='선택한 학원·반에 유일하게 일치하는 학생이 없습니다. 학생을 검색하거나 등록하세요.';return None,detail
