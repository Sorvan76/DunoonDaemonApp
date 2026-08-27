from __future__ import annotations
import colorsys, hashlib, json, os
from config import BASE_DIR
FILE=os.path.join(BASE_DIR,'custom_skins.json')

def _hex(rgb): return '#%02x%02x%02x'%tuple(max(0,min(255,int(x*255))) for x in rgb)
def _luma(h):
    h=h.lstrip('#'); r,g,b=[int(h[i:i+2],16)/255 for i in (0,2,4)]; return .2126*r+.7152*g+.0722*b

def generate_palette(seed_words):
    s=str(seed_words or '').strip().lower(); digest=hashlib.sha256(s.encode()).digest()
    hue=int.from_bytes(digest[:2],'big')/65535.0; sat=.22+(digest[2]/255)*.38
    dark=(digest[3]%2)==0
    bg_v=.09 if dark else .92; panel_v=.15 if dark else .84; accent_v=.88 if dark else .62
    bg=_hex(colorsys.hsv_to_rgb(hue,sat*.55,bg_v)); panel=_hex(colorsys.hsv_to_rgb(hue,sat*.6,panel_v))
    panel2=_hex(colorsys.hsv_to_rgb((hue+.03)%1,sat*.55,min(1,panel_v+(.08 if dark else -.08))))
    accent=_hex(colorsys.hsv_to_rgb((hue+.12)%1,min(.8,sat+.22),accent_v))
    text='#f2f2f2' if _luma(bg)<.45 else '#111111'; muted='#b8b8b8' if text=='#f2f2f2' else '#555555'
    return {'bg':bg,'fg':text,'accent':accent,'button_bg':panel2,'button_fg':text,'entry_bg':panel,'entry_fg':text,
            'frame_bg':bg,'tree_bg':panel,'tree_fg':text,'tree_header_bg':panel2,'tree_header_fg':text,
            'scroll_bg':panel2,'scroll_trough':bg}

def load_custom_skins():
    try:
        with open(FILE,'r',encoding='utf-8') as f: d=json.load(f)
        return d if isinstance(d,dict) else {}
    except Exception:return {}

def save_custom_skin(name,seeds):
    name=str(name or '').strip();
    if not name: raise ValueError('Skin name is empty.')
    d=load_custom_skins(); d[name]={'seed_words':str(seeds or ''),'palette':generate_palette(seeds)}
    tmp=FILE+'.tmp'
    with open(tmp,'w',encoding='utf-8') as f: json.dump(d,f,indent=2,ensure_ascii=False); f.flush(); os.fsync(f.fileno())
    os.replace(tmp,FILE); return d[name]['palette']

def delete_custom_skin(name):
    name = str(name or '').strip()
    if not name:
        return False
    d = load_custom_skins()
    if name not in d:
        return False
    del d[name]
    tmp = FILE + '.tmp'
    os.makedirs(os.path.dirname(FILE) or '.', exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, FILE)
    return True


def clear_custom_skins():
    d = load_custom_skins()
    names = sorted(d.keys())
    if not names:
        return []
    tmp = FILE + '.tmp'
    os.makedirs(os.path.dirname(FILE) or '.', exist_ok=True)
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({}, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, FILE)
    return names
