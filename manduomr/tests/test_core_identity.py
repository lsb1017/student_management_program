"""Ported from 1.0.6 tests/test_name_identity.py, adapted to the 7-digit 학번.

Intentional change: the 수능수학 sheet's suffix column no longer selects among students
with the same phone tail, because 7-digit 학번 have no 1-digit suffix. The name decides.
"""
from types import SimpleNamespace
import pytest
from PIL import ImageDraw
from core.mathomr import (recognize_math,name_centers,NAME_CONSONANTS,NAME_VOWELS,HANGUL_INITIALS,HANGUL_VOWELS,HANGUL_FINALS)
from core.identity import resolve_student
from core.importer import import_files,retry_failed
from core.store import Store
from test_core_math import drawing,KEY,CONFIG


def named_sheet(name,code='0012',suffix=None):
    image=drawing(code=code,suffix=suffix);draw=ImageDraw.Draw(image)
    for s,char in enumerate(name):
        value=ord(char)-0xAC00
        parts=[HANGUL_INITIALS[value//588],HANGUL_VOWELS[value//28%21],HANGUL_FINALS[value%28]]
        for p,char in enumerate(parts):
            if char==' ':continue
            labels=NAME_VOWELS if p==1 else NAME_CONSONANTS
            x,y=name_centers(s,p)[labels.index(char)];draw.ellipse((x-5,y-11,x+5,y+11),fill='black')
    return image


@pytest.fixture
def setup(tmp_path):
    db=Store(tmp_path/'db.sqlite3');cid=db.classroom(db.academy('학원'),'A반');student=db.save_student_contact('학생가','0012',class_id=cid)
    eid=db.save_exam('시험','시리즈','수학','1','2026-10-18',KEY,[3]*30,config=CONFIG)
    yield db,student,eid,cid
    db.close()


@pytest.mark.parametrize('name,angle',[('김민수',0),('양지용',90),('고은',180),('이예준',270),('최의찬',0)])
def test_name_grid_decodes_hangul_and_blank_final_consonants(name,angle):
    result=recognize_math(named_sheet(name).rotate(angle,expand=True))
    assert not result.error and result.identity_reading['name']['name']==name
    assert result.identity_reading['phone_tail']=='0012' and result.identity_reading['suffix_defaulted']
    assert [a['answer'] for a in result.answers]==KEY


def test_phone_and_name_match_only_inside_selected_class(setup,tmp_path):
    db,first,eid,cid=setup
    second=db.save_student_contact('김민수','0012',class_id=cid)
    other_class=db.classroom(db.academy('다른학원'),'B반');outside=db.save_student_contact('김민수','0012',class_id=other_class)
    aid=db.rows('SELECT academy_id FROM classes WHERE id=?',(cid,))[0]['academy_id']
    result=recognize_math(named_sheet('김민수'))
    assert resolve_student(db.db,result)[0] is None
    assert resolve_student(db.db,result,aid,cid)[0]['id']==second
    assert resolve_student(db.db,result,None,other_class)[0]['id']==outside
    path=tmp_path/'name.png';named_sheet('김민수').save(path)
    import_files(db.path,eid,[path],academy_id=aid,class_id=cid)
    scan=db.scan(db.scans(eid)[0]['id']);assert scan['student_id']==second and not scan['identity_ok']
    assert scan['import_context']['identity_reading']['method']=='phone_name' and scan['import_context']['class_id']==cid
    assert resolve_student(db.db,result,999,cid)[0] is None


def test_blank_or_unclear_name_with_shared_tail_requires_review(setup):
    db,first,eid,cid=setup;second=db.save_student_contact('김민수','0012',class_id=cid)
    assert resolve_student(db.db,recognize_math(drawing(code='0012')),None,cid)[0] is None
    # The printed suffix column is ignored: the clear name decides, whatever the suffix.
    for suffix in (1,2):
        assert resolve_student(db.db,recognize_math(named_sheet('김민수',suffix=suffix)),None,cid)[0]['id']==second
    image=named_sheet('김민수');draw=ImageDraw.Draw(image);x,y=name_centers(0,0)[1];draw.ellipse((x-5,y-11,x+5,y+11),fill='black')
    result=recognize_math(image);assert result.identity_reading['name']['flag']=='multiple' and resolve_student(db.db,result,None,cid)[0] is None


def test_unique_phone_falls_back_when_name_not_in_class_and_never_links_outside(setup):
    db,first,eid,cid=setup
    result=recognize_math(named_sheet('김민수'));assert resolve_student(db.db,result,None,cid)[0]['id']==first
    other_class=db.classroom(db.academy('다른학원'),'B반');second=db.save_student_contact('김민수','0012',class_id=other_class)
    assert resolve_student(db.db,result,None,cid)[0]['id']==first
    result=recognize_math(drawing(code='0012'));assert resolve_student(db.db,result,None,cid)[0]['id']==first
    assert resolve_student(db.db,result,None,other_class)[0]['id']==second


def test_retry_failed_uses_saved_class_and_name_metadata(setup,tmp_path):
    db,first,eid,cid=setup;second=db.save_student_contact('김민수','0012',class_id=cid)
    path=tmp_path/'retry.png';named_sheet('김민수').save(path)
    import_files(db.path,eid,[path],class_id=cid);sid=db.scans(eid)[0]['id']
    db.db.execute("UPDATE scans SET status='failed',student_id=NULL WHERE id=?",(sid,));db.db.commit()
    assert retry_failed(db.path,eid,[sid],class_id=999)['recovered']==1
    assert db.scan(sid)['student_id']==second and db.scan(sid)['import_context']['class_id']==cid


def test_seven_digit_code_matches_exactly_then_falls_back_to_tail(setup):
    db,first,eid,cid=setup;code=db.student(first)['code']
    other=db.save_student_contact('학생다','0012',class_id=cid)
    reading=lambda c:SimpleNamespace(code=c,identity_reading={'phone_tail':c[:4],'name':{'flag':'blank'},'code_digits':7})
    assert resolve_student(db.db,reading(code),None,cid)[0]['id']==first
    assert resolve_student(db.db,reading('0012999' if code!='0012999' else '0012998'),None,cid)[0] is None
    db.db.execute('UPDATE students SET active=0 WHERE id=?',(other,));db.db.commit()
    assert resolve_student(db.db,reading('0012999' if code!='0012999' else '0012998'),None,cid)[0]['id']==first


def test_phone_change_reissues_code_and_keeps_results(setup,seq_random):
    db,first,eid,cid=setup;before=db.student(first)['code']
    db.save_student_contact('학생가','010-5555-0012',student_id=first,class_id=cid)
    assert db.student(first)['code']==before  # tail-only number completed with the same tail
    db.save_student_contact('학생가','010-5555-7777',student_id=first,class_id=cid,rng=seq_random(42))
    assert db.student(first)['code']=='7777042'
    db.save_student_contact('학생가','010-6666-7777',student_id=first,class_id=cid,rng=seq_random(43))
    assert db.student(first)['code']=='7777043'
    history=db.code_history(first)
    assert [h['reason'] for h in history]==['registered','phone_changed','phone_changed'] and history[-1]['previous']=='7777042'
