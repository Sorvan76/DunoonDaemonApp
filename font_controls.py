# font_controls.py — compact font chooser shared by chat and Arena.
from __future__ import annotations
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from ui_windowing import center_after_idle
from modern_tooltips import ensure_button_tooltips, register_tooltip

class FontControlDialog(tk.Toplevel):
    def __init__(self,owner,family,size,on_change,palette,title='Chat typography'):
        super().__init__(owner)
        self._on_change=on_change; self._p=palette; self._tooltips=[]
        self.title(title); self.geometry('390x205'); self.resizable(False,False); self.configure(bg=palette['panel'])
        self.transient(owner.winfo_toplevel())
        self.family_var=tk.StringVar(value=family); self.size_var=tk.IntVar(value=int(size))
        head=tk.Frame(self,bg=palette['panel']); head.pack(fill='x',padx=18,pady=(16,8))
        tk.Label(head,text='CHAT TYPOGRAPHY',bg=palette['panel'],fg=palette['muted'],font=('Segoe UI Semibold',8)).pack(side='left')
        tk.Label(head,text='live',bg=palette['panel'],fg=palette['accent'],font=('Segoe UI',8)).pack(side='right')
        body=tk.Frame(self,bg=palette['panel']); body.pack(fill='x',padx=18); body.columnconfigure(0,weight=1)
        families=sorted(set(tkfont.families(self))); preferred=['Segoe UI Emoji','Segoe UI','Arial','Calibri','Consolas','Georgia','Verdana']
        ordered=[x for x in preferred if x in families]+[x for x in families if x not in preferred]
        self.family=ttk.Combobox(body,values=ordered,textvariable=self.family_var,state='readonly'); self.family.grid(row=0,column=0,sticky='ew',padx=(0,8)); self.family.bind('<<ComboboxSelected>>',lambda _e:self._apply())
        smaller=self._button(body,'A−',lambda:self._bump(-1)); smaller.grid(row=0,column=1,padx=3); register_tooltip(self._tooltips,smaller,'Decrease text size by one point.')
        self.size_label=tk.Label(body,width=4,text=str(size),bg=palette['panel2'],fg=palette['text'],font=('Segoe UI Semibold',10),pady=7); self.size_label.grid(row=0,column=2,padx=3)
        larger=self._button(body,'A+',lambda:self._bump(1)); larger.grid(row=0,column=3,padx=(3,0)); register_tooltip(self._tooltips,larger,'Increase text size by one point.')
        self.preview=tk.Label(self,text='The quick brown fox meets Santa and the shark. 👀',bg=palette['bg'],fg=palette['text'],anchor='w',justify='left',padx=12,pady=13)
        self.preview.pack(fill='x',padx=18,pady=(14,8))
        tk.Label(self,text='Applies to single-agent chat and Arena transcript / composer.',bg=palette['panel'],fg=palette['muted'],font=('Segoe UI',8)).pack(anchor='w',padx=18)
        self._refresh()
        register_tooltip(self._tooltips,self.family,'Choose the interface font for chat text.')
        ensure_button_tooltips(self,self._tooltips)
        center_after_idle(self, owner)
    def _button(self,parent,text,command):
        p=self._p
        return tk.Button(parent,text=text,command=command,relief='flat',bd=0,bg=p['button'],fg=p['button_fg'],activebackground=p['accent'],activeforeground=p['bg'],font=('Segoe UI Semibold',9),padx=10,pady=6,cursor='hand2')
    def _bump(self,delta): self.size_var.set(max(8,min(28,int(self.size_var.get())+delta))); self._apply()
    def _refresh(self):
        family=self.family_var.get() or 'Segoe UI Emoji'; size=max(8,min(28,int(self.size_var.get())))
        self.size_label.configure(text=str(size)); self.preview.configure(font=(family,size))
    def _apply(self):
        self._refresh(); self._on_change(self.family_var.get(),int(self.size_var.get()))
