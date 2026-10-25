"""Report encouragement templates and image bytes stored in the database backup."""
import base64
import io
import json
from copy import deepcopy
from decimal import Decimal
from string import Formatter
from PIL import Image
from .examdata import grade

CATEGORIES={'perfect':'만점 학생','grade1':'1등급 학생','other':'2~4등급 학생','grade5plus':'5등급 이하 학생'}
DEFAULTS={
    'perfect':{'text':'만점 달성!\n완벽하게 해냈어요!','image':'default'},
    'grade1':{'text':'1등급 달성!\n정말 잘했어요!','image':'default'},
    'grade5plus':{'text':'귀여워,, 네 점수,,','image':'default'},
    'other':{'text':'{목표등급}등급까지 {필요점수}점 남았어요!\n화이팅!','image':'default'},
}
FIELDS={'학생명','점수','등급','목표등급','필요점수'}

def settings(store):
    row=store.db.execute("SELECT value FROM settings WHERE name='report_cheer'").fetchone()
    config=deepcopy(DEFAULTS)
    if row:config.update(json.loads(row[0]))
    return config

def encode_image(data):
    if len(data)>8*1024*1024:raise ValueError('이미지는 8MB 이하의 PNG/JPG를 선택하세요.')
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ('PNG','JPEG') or im.width*im.height>25_000_000:raise ValueError()
            im.load()
    except Exception:raise ValueError('읽을 수 있는 PNG/JPG 이미지(2,500만 화소 이하)를 선택하세요.')
    return base64.b64encode(data).decode('ascii')

def image_bytes(category,entry):
    value=entry.get('image')
    if not value:return None
    if value=='default':
        from .reports import report_asset
        return report_asset('report_genius.png' if category in ('perfect','grade1') else 'report_cute.png' if category=='grade5plus' else 'report_cheer.png').read_bytes()
    return base64.b64decode(value,validate=True)

def validate(config):
    if set(config)!=set(DEFAULTS):raise ValueError('네 유형의 응원 문구 설정을 확인하세요.')
    for category,entry in config.items():
        text=entry['text']
        if not isinstance(text,str) or len(text)>120:raise ValueError('응원 문구는 유형별로 120자 이내로 입력하세요.')
        if text.count('\n')>2:raise ValueError('응원 문구는 직접 줄바꿈을 2번까지, 최대 3줄로 입력하세요.')
        try:
            for _,field,format_spec,conversion in Formatter().parse(text):
                if field is not None and (field not in FIELDS or format_spec or conversion):raise ValueError()
        except ValueError:raise ValueError('자동 문구는 {학생명}, {점수}, {등급}, {목표등급}, {필요점수}만 사용할 수 있습니다.')
        if entry.get('image') not in (None,'default'):encode_image(image_bytes(category,entry))

def save(store,config):
    validate(config)
    with store.transaction():
        store.db.execute("INSERT INTO settings(name,value) VALUES('report_cheer',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(json.dumps(config,ensure_ascii=False),))
        store.log('report_cheer_saved',None,{'categories':list(config)})

def resolved(result,config):
    current=grade(result['score'],result['cuts'])
    low=(isinstance(current,int) and current>=5) or (isinstance(current,str) and current.startswith(('5','6','7','8','9')))
    category='perfect' if result['score']==result['maximum'] else 'grade1' if current==1 else 'grade5plus' if low else 'other'
    target=None;points=None
    if result['cuts'] and category in ('other','grade5plus'):
        target=len(result['cuts']) if isinstance(current,str) else current-1
        points=(int(Decimal(str(result['cuts'][target-1]))*100)-result['score'])/100
    values={'학생명':result.get('snapshot',{}).get('name','학생'),'점수':f"{result['score']/100:g}",'등급':str(current or '미설정'),'목표등급':str(target or ''),'필요점수':f'{points:g}' if points is not None else ''}
    entry=config.get(category,DEFAULTS[category]);text=entry['text']
    if target is None and ('{목표등급}' in text or '{필요점수}' in text):text='다음 시험도 힘내요!\n화이팅!'
    return category,text.format(**values),image_bytes(category,entry)

def draw_cheer(canvas,result,store,x=307,y=753,width=258,height=64,config=None):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.lib.utils import ImageReader
    from .reports import fonts
    fonts();category,text,data=resolved(result,config or settings(store))
    image_width=0
    if data:
        im=ImageReader(io.BytesIO(data));iw,ih=im.getSize();scale=min(62/iw,height/ih)*1.10
        image_width=iw*scale;image_height=ih*scale
        canvas.drawImage(im,x+width-image_width,y+(height-image_height)/2,image_width,image_height,mask='auto')
    right=x+width-image_width-(6 if data else 0);available=right-x
    def lines_at(size):
        lines=[]
        for paragraph in text.split('\n'):
            line=''
            for char in paragraph:
                if line and pdfmetrics.stringWidth(line+char,'KoreanHand',size)>available:lines.append(line.rstrip());line=''
                line+=char
            lines.append(line.rstrip())
        return lines
    size=22*.85;lines=lines_at(size)
    while size>6 and len(lines)*size*1.12>height:size-=.5;lines=lines_at(size)
    canvas.saveState();canvas.setFillColor('#203752' if category in ('perfect','grade1') else '#AF4031');canvas.setFont('KoreanHand',size)
    baseline=y+height/2+(len(lines)-1)*size*.56-size*.30
    for i,line in enumerate(lines):
        if data:canvas.drawRightString(right,baseline-i*size*1.12,line)
        else:canvas.drawCentredString(x+width/2,baseline-i*size*1.12,line)
    canvas.restoreState()
