# eye_engine.py — Dunoon expressive Kylo/googly vector eyes.
# 🐉 Silver Wyrm: random wandering is primary; cursor-following is a brief curiosity glance.
from __future__ import annotations
import math, random, time, tkinter as tk

try:
    from eye_diagnostics import log_eye_state
except Exception:
    def log_eye_state(*_args, **_kwargs):
        return None

try:
    from PIL import Image, ImageDraw, ImageTk
    PIL_AA_AVAILABLE = True
except Exception:
    PIL_AA_AVAILABLE = False


def _blend(a,b,t):
    try:
        av=[int(a.lstrip('#')[i:i+2],16) for i in (0,2,4)]
        bv=[int(b.lstrip('#')[i:i+2],16) for i in (0,2,4)]
        v=[round(x+(y-x)*t) for x,y in zip(av,bv)]
        return '#'+''.join(f'{x:02x}' for x in v)
    except Exception:
        return a


class ExpressiveVectorEye(tk.Canvas):
    def __init__(self,master,size=50,bg=None,**kwargs):
        if bg is None:
            try: bg=master.cget('bg')
            except Exception: bg='#1a1a1a'
        super().__init__(master,width=size,height=size,bg=bg,highlightthickness=0,bd=0,**kwargs)
        self.size=size; self.cx=size/2; self.cy=size/2; self.radius=size/2-2; self.canvas_bg=bg
        self.idle_color='#fbfbf8'; self.current_color=self.idle_color; self.target_color=self.idle_color; self.sustain_frames=0
        self.pupil_scale=1.0; self.eyelid_open=1.0; self.is_blinking=False
        self.current_px=self.cx; self.current_py=self.cy; self.target_px=self.cx; self.target_py=self.cy
        self.is_expressive_light=True; self._animate()

    def set_background(self,c): self.canvas_bg=c; self.configure(bg=c)
    def set_target_gaze(self,x,y):
        m=self.radius*.31
        self.target_px=self.cx+max(-m,min(m,float(x)))
        self.target_py=self.cy+max(-m,min(m,float(y)))
    def set_signal(self,c,sustain_seconds=1.4,pupil_scale=1.0):
        self.target_color=str(c or self.idle_color); self.sustain_frames=max(1,int(sustain_seconds*30)); self.pupil_scale=max(.72,min(1.30,pupil_scale))
    def trigger_blink(self):
        if not self.is_blinking: self.is_blinking=True; self.eyelid_open=0.0
    def draw_eye(self):
        """Draw the vector eye. Pillow supersampling gives Tk smooth anti-aliased edges."""
        if not PIL_AA_AVAILABLE:
            self.delete('all'); lid=max(.9,self.radius*self.eyelid_open); off=max(1.0,self.size*.025)
            self.create_oval(self.cx-self.radius+off,self.cy-lid+off,self.cx+self.radius+off,self.cy+lid+off,fill='#202326' if self.eyelid_open>.08 else self.canvas_bg,outline='')
            sclera=self.current_color; edge=_blend(sclera,'#101214',.55)
            self.create_oval(self.cx-self.radius,self.cy-lid,self.cx+self.radius,self.cy+lid,fill=sclera,outline=edge,width=2)
            if self.eyelid_open>.12:
                pr=self.radius*.48*self.pupil_scale; mdx=self.radius-pr-2.5; mdy=self.radius*self.eyelid_open-pr-2.0
                px=self.cx+max(-mdx,min(mdx,self.current_px-self.cx)); py=self.cy+max(-max(0,mdy),min(max(0,mdy),self.current_py-self.cy))
                self.create_oval(px-pr,py-pr,px+pr,py+pr,fill='#08090a',outline='#000000',width=1)
                cr=max(1.7,pr*.21); hx=px-pr*.30; hy=py-pr*.34
                self.create_oval(hx-cr,hy-cr,hx+cr,hy+cr,fill='#ffffff',outline='')
                tr=max(1.0,pr*.075); tx=px-pr*.02; ty=py-pr*.04
                self.create_oval(tx-tr,ty-tr,tx+tr,ty+tr,fill='#ffffff',outline='')
            return

        scale = 4
        S = self.size * scale
        img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        sc = lambda v: int(round(v * scale))
        lid=max(.9,self.radius*self.eyelid_open); off=max(1.0,self.size*.025)

        shadow_fill = '#202326' if self.eyelid_open>.08 else self.canvas_bg
        d.ellipse([sc(self.cx-self.radius+off), sc(self.cy-lid+off), sc(self.cx+self.radius+off), sc(self.cy+lid+off)], fill=shadow_fill)

        sclera=self.current_color; edge=_blend(sclera,'#101214',.55)
        eye_box=[sc(self.cx-self.radius), sc(self.cy-lid), sc(self.cx+self.radius), sc(self.cy+lid)]
        d.ellipse(eye_box, fill=sclera, outline=edge, width=max(1, sc(1.55)))

        if self.eyelid_open>.12:
            pr=self.radius*.48*self.pupil_scale; mdx=self.radius-pr-2.5; mdy=self.radius*self.eyelid_open-pr-2.0
            px=self.cx+max(-mdx,min(mdx,self.current_px-self.cx)); py=self.cy+max(-max(0,mdy),min(max(0,mdy),self.current_py-self.cy))
            d.ellipse([sc(px-pr),sc(py-pr),sc(px+pr),sc(py+pr)],fill='#08090a',outline='#000000',width=max(1,sc(.75)))
            cr=max(1.7,pr*.21); hx=px-pr*.30; hy=py-pr*.34
            d.ellipse([sc(hx-cr),sc(hy-cr),sc(hx+cr),sc(hy+cr)],fill='#ffffff')
            tr=max(1.0,pr*.075); tx=px-pr*.02; ty=py-pr*.04
            d.ellipse([sc(tx-tr),sc(ty-tr),sc(tx+tr),sc(ty+tr)],fill='#ffffff')
            arc_col=_blend('#2e343b','#ffffff',.18)
            d.arc([sc(px-pr*.72),sc(py+pr*.18),sc(px+pr*.72),sc(py+pr*.78)],start=200,end=340,fill=arc_col,width=max(1,sc(self.size*.028)))

        resampling = getattr(Image, 'Resampling', Image).LANCZOS
        img = img.resize((self.size, self.size), resampling)
        self._aa_photo = ImageTk.PhotoImage(img)
        self.delete('all')
        self.create_image(0, 0, image=self._aa_photo, anchor='nw')
    def _animate(self):
        self.current_px+=(self.target_px-self.current_px)*.15; self.current_py+=(self.target_py-self.current_py)*.15
        if self.eyelid_open<1.0:
            self.eyelid_open=min(1.0,self.eyelid_open+.25)
            if self.eyelid_open>=1.0: self.is_blinking=False
        if self.sustain_frames>0:
            self.sustain_frames-=1; self.current_color=_blend(self.target_color,'#ffffff',.10)
        else:
            self.current_color=self.idle_color; self.pupil_scale=1.0
        self.draw_eye(); self.after(33,self._animate)


class ExpressiveVectorEyePair(tk.Frame):
    def __init__(self,master,size=50,bg=None,**kwargs):
        if bg is None:
            try: bg=master.cget('bg')
            except Exception: bg='#1a1a1a'
        super().__init__(master,bg=bg,**kwargs); self._bg=bg
        self.left_eye=ExpressiveVectorEye(self,size=size,bg=bg); self.right_eye=ExpressiveVectorEye(self,size=size,bg=bg)
        self.left_eye.pack(side=tk.LEFT,padx=0); self.right_eye.pack(side=tk.LEFT,padx=0)
        self.is_expressive_light=True; self.thinking=False; self.breath_phase=0.0
        self._cursor_active_until=0.0; self._cursor_cooldown_until=0.0; self._last_pointer=None
        self.active_signal_key='idle'
        self._diagnostic_last_state=None
        self._diagnostic_pending_reason='initialise'
        self.signal_levels={k:0.0 for k in ('reset','deep','journal','intent','working','task','persona','factual','retrieval','continuation')}
        self.persona_palette={'idle':'#FFFFFF','thinking':'#00FF55','working':'#00EFFF','deep':'#FF0033','journal':'#FFF700','intent':'#AA00FF','task':'#FF8800','persona':'#FF66CC','factual':'#FFFFFF','continuation':'#FFFF00','reset':'#55595d','retrieval':'#0099FF'}
        self._scheduled_gaze_shift(); self._scheduled_blink(); self._track_pointer(); self._update_light_engine()

    def set_background(self,c): self._bg=c; self.configure(bg=c); self.left_eye.set_background(c); self.right_eye.set_background(c)
    def _trigger(self,key,reason=None):
        if key in self.signal_levels:
            self.signal_levels[key]=1.0; self.active_signal_key=key
            self._diagnostic_pending_reason=str(reason or f'trigger:{key}')
    def trigger_working(self): self._trigger('working')
    def trigger_deep(self): self._trigger('deep')
    def trigger_journal(self): self._trigger('journal')
    def trigger_intent(self): self._trigger('intent')
    def trigger_task(self): self._trigger('task')
    def trigger_persona(self): self._trigger('persona')
    def trigger_factual(self): self._trigger('factual')
    def trigger_continuation(self): self._trigger('continuation')
    def trigger_reset(self): self._trigger('reset')
    def trigger_retrieval(self): self._trigger('retrieval',reason='memory_retrieval')
    def trigger_vault(self,vault_name):
        key=str(vault_name or 'working').strip().lower().replace('_memory','')
        if key not in self.signal_levels: key='working'
        self._trigger(key,reason=f'memory_write:{key}')
    def start_breathing(self):
        self.thinking=True; self._diagnostic_pending_reason='model_generation'
    def stop_breathing(self):
        self.thinking=False; self.breath_phase=0.0; self._diagnostic_pending_reason='generation_complete'
    def set_signal(self,c,sustain_seconds=1.4,pupil_scale=1.0): self.left_eye.set_signal(c,sustain_seconds,pupil_scale); self.right_eye.set_signal(c,sustain_seconds,pupil_scale)

    def _update_light_engine(self):
        for k in self.signal_levels: self.signal_levels[k]=max(0.0,self.signal_levels[k]-.04)
        sigs=[(self.signal_levels['reset'],'reset',.82),(self.signal_levels['deep'],'deep',1.20),(self.signal_levels['journal'],'journal',1.10),(self.signal_levels['intent'],'intent',.92),(self.signal_levels['working'],'working',1.05),(self.signal_levels['task'],'task',.98),(self.signal_levels['persona'],'persona',1.14),(self.signal_levels['factual'],'factual',.90),(self.signal_levels['retrieval'],'retrieval',.88),(self.signal_levels['continuation'],'continuation',1.00)]
        level,key,dilation=max(sigs,key=lambda x:(x[0], 1 if x[1]==self.active_signal_key else 0))
        if level>.05:
            self.active_signal_key=key; self.set_signal(self.persona_palette.get(key,'#00FF55'),.12,dilation)
        elif self.thinking:
            self.active_signal_key='thinking'; self.breath_phase+=.08
            if math.sin(self.breath_phase)>0: self.set_signal(self.persona_palette['thinking'],.12,1.06)
        else:
            self.active_signal_key='idle'
        if self.active_signal_key != self._diagnostic_last_state:
            colour=self.persona_palette.get(self.active_signal_key,'#FFFFFF')
            log_eye_state(self.active_signal_key,colour,self._diagnostic_pending_reason)
            self._diagnostic_last_state=self.active_signal_key
            self._diagnostic_pending_reason='state_decay'
        self.after(50,self._update_light_engine)

    def _set_pair_gaze(self,dx,dy):
        self.left_eye.set_target_gaze(dx,dy); self.right_eye.set_target_gaze(dx,dy)

    def _track_pointer(self):
        """Cursor gets a brief curious glance, then random wandering retakes control."""
        try:
            x,y=self.winfo_pointerxy(); pointer=(x,y); now=time.monotonic()
            moved = self._last_pointer is None or abs(x-self._last_pointer[0])+abs(y-self._last_pointer[1])>=14
            if moved:
                self._last_pointer=pointer
                if now>=self._cursor_cooldown_until and self.winfo_ismapped():
                    self._cursor_active_until=now+.65
                    self._cursor_cooldown_until=now+3.4
            if now<self._cursor_active_until and self.winfo_ismapped():
                cx=self.winfo_rootx()+max(1,self.winfo_width())/2; cy=self.winfo_rooty()+max(1,self.winfo_height())/2
                dx=max(-7,min(7,(x-cx)/max(35,self.winfo_width())*10)); dy=max(-5.5,min(5.5,(y-cy)/max(28,self.winfo_height())*8))
                self._set_pair_gaze(dx,dy)
        except Exception:
            pass
        self.after(90,self._track_pointer)

    def _scheduled_gaze_shift(self):
        now=time.monotonic()
        if now>=self._cursor_active_until:
            # Full-range curious wandering. Thinking makes the eyes a little busier.
            r=random.random()
            if r<.18: dx,dy=random.uniform(4.5,7),random.uniform(-3.2,3.2)
            elif r<.36: dx,dy=random.uniform(-7,-4.5),random.uniform(-3.2,3.2)
            elif r<.52: dx,dy=random.uniform(-3.0,3.0),random.uniform(4.0,6.3)
            elif r<.68: dx,dy=random.uniform(-3.0,3.0),random.uniform(-6.3,-4.0)
            elif r<.88: dx,dy=random.uniform(-5.5,5.5),random.uniform(-4.5,4.5)
            else: dx,dy=random.uniform(-1,1),random.uniform(-1,1)
            self._set_pair_gaze(dx,dy)
        delay=random.randint(650,1700) if self.thinking else random.randint(1400,3600)
        self.after(delay,self._scheduled_gaze_shift)

    def _scheduled_blink(self):
        self.left_eye.trigger_blink(); self.right_eye.trigger_blink()
        if random.random()<.2:
            self.after(300,lambda:(self.left_eye.trigger_blink(),self.right_eye.trigger_blink()))
        self.after(random.randint(5000,11000),self._scheduled_blink)
