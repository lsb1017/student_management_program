"""Resolve an OMR identity without assuming a missing collision suffix is 1."""
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
    tail=reading.get('phone_tail');name=reading.get('name',{});digits=reading.get('digits',[])
    roster=db.execute(query,params).fetchall()
    phones=[s for s in roster if tail and s['code'][1:5]==tail]
    names=[s for s in roster if name.get('flag')=='clear' and name.get('name') and normalized_name(s['name'])==normalized_name(name['name'])]
    explicit=bool(tail and digits and digits[-1]['flag']=='clear' and not reading.get('suffix_defaulted'))
    codes=[s for s in phones if explicit and s['code']==result.code]
    # A clear suffix can distinguish a collision, but must not override a conflicting name.
    number=codes if explicit and codes else phones
    if number and names:
        common=[s for s in number if any(s['id']==n['id'] for n in names)]
        if len(common)==1:detail['method']='phone_name';return common[0],detail
        detail['notice']='번호와 이름이 서로 다르거나 중복됩니다. 학생을 확인해 연결하세요.';return None,detail
    if len(number)==1:
        detail['method']='explicit_code' if codes else 'unique_phone';return number[0],detail
    if len(names)==1:
        detail['method']='unique_name';return names[0],detail
    detail['notice']='선택한 학원·반에 유일하게 일치하는 학생이 없습니다. 학생을 검색하거나 등록하세요.';return None,detail
