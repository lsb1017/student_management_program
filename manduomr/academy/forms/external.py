"""M1 외부 양식 등록: 이미 인쇄해 쓰는 양식을 빈 양식 스캔 위에서 답란·학번 영역을 지정해 등록함.

Blocks are given in the blank image's pixel coordinates:
  {'kind':'choice','first':1,'count':20,'choices':5,'origin':[x,y],'dx':43,'dy':48}
  {'kind':'numeric','q':16,'origin':[x,y],'dx':40,'dy':27,'places':3}
  {'kind':'id','digits':7,'origin':[x,y],'dx':48,'dy':28}
Scans are aligned to the blank by feature matching, then read at these centers.
"""
import io
import json
from PIL import Image
from core.store import pack,now


def expand(blocks,radius=8):
    questions={};identity=None;choice_count=None
    for b in blocks:
        ox,oy=map(float,b['origin']);dx,dy=float(b['dx']),float(b['dy'])
        if b['kind']=='choice':
            choices=int(b.get('choices',5))
            if choice_count not in (None,choices):raise ValueError('한 양식의 선택지 수는 같아야 합니다.')
            choice_count=choices
            for i in range(int(b['count'])):
                q=int(b['first'])+i
                if q in questions:raise ValueError(f'{q}번 답란이 겹칩니다.')
                questions[q]={'q':q,'kind':'choice','centers':[(ox+k*dx,oy+i*dy) for k in range(choices)]}
        elif b['kind']=='numeric':
            q=int(b['q'])
            if q in questions:raise ValueError(f'{q}번 답란이 겹칩니다.')
            questions[q]={'q':q,'kind':'numeric','places':[[(ox+p*dx,oy+d*dy) for d in range(10)] for p in range(int(b.get('places',3)))]}
        elif b['kind']=='id':
            if int(b.get('digits',7))!=7:raise ValueError('학번 칸은 7자리로 지정하세요.')
            identity={'digits':7,'centers':[[(ox+p*dx,oy+d*dy) for d in range(10)] for p in range(7)]}
        else:raise ValueError('알 수 없는 영역 종류입니다.')
    if not questions:raise ValueError('답란을 하나 이상 지정하세요.')
    numbers=sorted(questions)
    if numbers!=list(range(1,len(numbers)+1)):raise ValueError('문항 번호가 1번부터 빠짐없이 이어져야 합니다.')
    if identity is None:raise ValueError('학번 7자리 영역을 지정하세요.')
    return {'version':1,'reader':'features','choice_count':choice_count or 5,'radius':radius,'question_count':len(numbers),
            'numeric':[q for q in numbers if questions[q]['kind']=='numeric'],'id':identity,'questions':[questions[q] for q in numbers],'blocks':blocks}


def register_external(store,name,blank_image_path,blocks,radius=8):
    name=str(name).strip()
    if not name or len(name)>60:raise ValueError('양식 이름을 1~60자로 입력하세요.')
    layout=expand(blocks,radius)
    with Image.open(blank_image_path) as im:
        rgb=im.convert('RGB');layout['size']=list(rgb.size);buf=io.BytesIO();rgb.save(buf,'PNG')
    with store.transaction():
        blank=store.put_bytes(buf.getvalue(),'png')
        fid=store.db.execute("INSERT INTO omr_forms(name,question_count,choice_count,numeric_questions,id_digits,layout_json,source,blank_hash,created_at) VALUES(?,?,?,?,7,?,'external',?,?)",
                             (name,layout['question_count'],layout['choice_count'],pack(layout['numeric']),json.dumps(layout),blank,now())).lastrowid
        store.log('omr_form_registered',fid,{'name':name,'question_count':layout['question_count'],'blocks':blocks})
    return fid
