# modern_theme.py — Shared modern UI palette adapter for every legacy Dunoon skin.
from skin_manager import SKINS


def _blend(hex_a: str, hex_b: str, amount: float) -> str:
    try:
        a = hex_a.lstrip('#'); b = hex_b.lstrip('#')
        av = [int(a[i:i+2], 16) for i in (0,2,4)]
        bv = [int(b[i:i+2], 16) for i in (0,2,4)]
        v = [round(x + (y-x)*amount) for x,y in zip(av,bv)]
        return '#' + ''.join(f'{x:02x}' for x in v)
    except Exception:
        return hex_a


def palette(name: str) -> dict:
    s = SKINS.get(name, SKINS['Dark'])
    bg = s.get('bg', '#0f1115')
    frame = s.get('frame_bg', bg)
    entry = s.get('entry_bg', _blend(bg, '#ffffff', .07))
    accent = s.get('accent', '#63d3ff')
    fg = s.get('fg', '#eceff4')
    button = s.get('button_bg', _blend(bg, fg, .12))
    muted = _blend(fg, bg, .48)
    border = _blend(fg, bg, .78)
    return {
        'bg': bg, 'panel': frame, 'panel2': entry, 'text': fg, 'muted': muted,
        'accent': accent, 'accent2': _blend(accent, fg, .42), 'button': button, 'button_fg': s.get('button_fg', fg),
        'entry_fg': s.get('entry_fg', fg), 'border': border,
    }

def contrast_text(hex_color: str) -> str:
    """Return black or white text with useful contrast against a solid hex background."""
    try:
        h = hex_color.lstrip('#')
        r, g, b = [int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
        def lin(c):
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
        return '#000000' if lum > 0.42 else '#ffffff'
    except Exception:
        return '#ffffff'


def apply_combobox_theme(root, skin_name: str):
    """Keep readonly comboboxes and their popup highlight legible on every Dunoon skin."""
    try:
        from tkinter import ttk
        p = palette(skin_name)
        selected_fg = contrast_text(p['accent'])
        style = ttk.Style(root)
        try:
            style.theme_use('clam')
        except Exception:
            pass
        style.configure(
            'TCombobox',
            fieldbackground=p['panel2'],
            background=p['button'],
            foreground=p['entry_fg'],
            arrowcolor=p['entry_fg'],
            selectbackground=p['accent'],
            selectforeground=selected_fg,
            bordercolor=p['border'],
            lightcolor=p['button'],
            darkcolor=p['button'],
        )
        style.map(
            'TCombobox',
            fieldbackground=[('readonly', p['panel2'])],
            foreground=[('readonly', p['entry_fg'])],
            selectbackground=[('readonly', p['accent'])],
            selectforeground=[('readonly', selected_fg)],
        )
        # The dropdown itself is a Tk Listbox, not a ttk widget. These options stop bright
        # selection bars from rendering bright text on bright backgrounds.
        root.option_add('*TCombobox*Listbox.background', p['panel2'])
        root.option_add('*TCombobox*Listbox.foreground', p['entry_fg'])
        root.option_add('*TCombobox*Listbox.selectBackground', p['accent'])
        root.option_add('*TCombobox*Listbox.selectForeground', selected_fg)
        root.option_add('*TCombobox*Listbox.activeStyle', 'none')
    except Exception:
        pass

