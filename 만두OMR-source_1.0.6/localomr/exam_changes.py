from .examdata import effective,ELECTIVES,validate_config
from .store import points_cents

def preview_change(store,eid,key,points,config):
    old=store.exam(eid);cents=[points_cents(p) for p in points]
    config=validate_config(config,key,cents,points_cents);new={'key':key,'points':cents,'config':config}
    changes={};lines=[]
    for choice in (ELECTIVES if config.get('form')=='math30' else ('0',)):
        before,after=effective(old,choice),effective(new,choice)
        changed=[i+1 for i,(a,b) in enumerate(zip(before['key'],after['key'])) if a!=b]
        weights=[i+1 for i,(a,b) in enumerate(zip(before['points'],after['points'])) if a!=b]
        if changed or weights:
            changes[choice]=changed
            if changed:lines.append(f"{ELECTIVES.get(choice,'공통')} 정답 {len(changed)}문항: "+', '.join(map(str,changed))+'번')
            if weights:lines.append(f"{ELECTIVES.get(choice,'공통')} 배점 {len(weights)}문항: "+', '.join(map(str,weights))+'번')
    affected=[r['id'] for r in store.rows("SELECT id,elective FROM scans WHERE exam_id=? AND status='confirmed'",(eid,)) if changes.get(r['elective'] if config.get('form')=='math30' else '0')]
    return lines,affected
