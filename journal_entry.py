# journal_entry.py
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import List
import hashlib

@dataclass
class JournalEntry:
    id: str
    text: str
    summary: str
    timestamp: str
    tags: List[str]
    significance: float

    def to_dict(self):
        return asdict(self)

def make_journal_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()