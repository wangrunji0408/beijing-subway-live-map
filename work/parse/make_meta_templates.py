#!/usr/bin/env python3
"""Create/refresh work/parsed/<line>/meta.json templates (suffix -> info)."""
import os, glob, json, collections, sys
TT='timetables'; OUT='work/parsed'
LINES=['1','2','3','4','5','6','7','8','9','10','11','12','13','14','15','16','17','18',
       '19','S1','亦庄','八通','大兴机场','房山','昌平','燕房','首都机场']
for ln in LINES:
    fs=[os.path.basename(f) for f in glob.glob(f'{TT}/{ln}-*.jpg')+glob.glob(f'{TT}/{ln}-*.png')]
    sufs=collections.Counter(f.rsplit('.',1)[0].split('-')[-1] for f in fs)
    d=os.path.join(OUT,ln); os.makedirs(d,exist_ok=True)
    p=os.path.join(d,'meta.json')
    old=json.load(open(p)) if os.path.exists(p) else {}
    m={}
    for s in sorted(sufs):
        m[s]=old.get(s, {'direction':None,'service':None,'legend':None,'note':f'{sufs[s]} images'})
    json.dump(m, open(p,'w'), ensure_ascii=False, indent=1)
    print(ln, {s:m[s]['note'] for s in m})
