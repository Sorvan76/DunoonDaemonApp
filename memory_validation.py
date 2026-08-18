# memory_validation.py — Content-Agnostic Structural Validation

def validate_memory(m: str) -> bool:
    if not isinstance(m,str): return False
    text=m.strip()
    if not text or len(text)<2 or len(text)>4000: return False
    if "\x00" in text: return False
    controls=sum(1 for ch in text if ord(ch)<32 and ch not in "\n\r\t")
    if controls>max(2,int(len(text)*0.02)): return False
    return True
