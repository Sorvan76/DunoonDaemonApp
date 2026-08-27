from __future__ import annotations

"""Structured persona import helpers for Dunoon Daemon."""

import ast
import io
import json
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List

try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except Exception:
    PYPDF_AVAILABLE = False

try:
    import docx
    DOCX_AVAILABLE = True
except Exception:
    DOCX_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VISION_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
TEXT_EXTS = {".txt", ".md", ".markdown", ".json", ".csv", ".log", ".py", ".js", ".cpp", ".rtf"}
DOC_EXTS = {".pdf", ".docx"}
SUPPORTED_EXTS = IMAGE_EXTS | TEXT_EXTS | DOC_EXTS
IMPORT_MODES = ("Character", "NPC", "Monster / creature")


class PersonaImportError(RuntimeError):
    pass


@dataclass
class PersonaImportResult:
    display_name: str = ""
    core_persona_directives: str = ""
    backstory: str = ""
    physiology: str = ""
    powers_skills: str = ""
    dream_guidance: str = ""
    ocean: Dict[str, int] | None = None
    confidence: Dict[str, int] = field(default_factory=dict)
    import_notes: str = ""
    source_text: str = ""
    source_name: str = ""
    used_image_path: str = ""
    image_origin: str = ""
    import_mode: str = "Character"


TRAITS = ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism")
FIELD_KEYS = (
    "display_name", "core_persona_directives", "backstory", "physiology",
    "powers_skills", "dream_guidance", "ocean",
)


def is_image_file(path: str) -> bool:
    return os.path.splitext(str(path or ""))[1].lower() in IMAGE_EXTS


def can_attach_to_vision(path: str) -> bool:
    return os.path.splitext(str(path or ""))[1].lower() in VISION_IMAGE_EXTS


def _read_text_file(path: str) -> str:
    for encoding in ("utf-8", "latin-1", "cp1252"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise PersonaImportError("Could not decode plain text file.")


def _extract_pdf(path: str) -> str:
    if not PYPDF_AVAILABLE:
        raise PersonaImportError("PDF import needs pypdf installed.")
    try:
        reader = PdfReader(path)
        pages_text = []
        for idx, page in enumerate(reader.pages):
            txt = page.extract_text() or ""
            if txt.strip():
                pages_text.append(f"--- Page {idx + 1} ---\n{txt.strip()}")
        return "\n\n".join(pages_text).strip()
    except Exception as exc:
        raise PersonaImportError(f"Error reading PDF file: {exc}") from exc


def _extract_docx(path: str) -> str:
    if not DOCX_AVAILABLE:
        raise PersonaImportError("DOCX import needs python-docx installed.")
    try:
        doc = docx.Document(path)
        full_text = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
        return "\n".join(full_text).strip()
    except Exception as exc:
        raise PersonaImportError(f"Error reading Word document: {exc}") from exc


def extract_source_text(path: str) -> str:
    if not path:
        return ""
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return ""
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    if ext in TEXT_EXTS:
        return _read_text_file(path).strip()
    raise PersonaImportError(f"Unsupported import format: {ext or '[no extension]'}")


def _write_temp_image(data: bytes, suffix: str) -> str:
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    fd, path = tempfile.mkstemp(prefix="dunoon_persona_import_", suffix=suffix)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path


def extract_embedded_images(path: str, *, max_images: int = 8) -> List[str]:
    """Extract plausible embedded images to temp files. Caller owns cleanup."""
    ext = os.path.splitext(str(path or ""))[1].lower()
    out: List[str] = []
    if ext == ".docx":
        try:
            with zipfile.ZipFile(path, "r") as zf:
                names = [n for n in zf.namelist() if n.lower().startswith("word/media/")]
                for name in names[:max_images]:
                    suffix = os.path.splitext(name)[1].lower()
                    if suffix not in IMAGE_EXTS:
                        continue
                    data = zf.read(name)
                    if len(data) < 256:
                        continue
                    out.append(_write_temp_image(data, suffix))
        except Exception:
            return []
        return out

    if ext == ".pdf" and PYPDF_AVAILABLE:
        try:
            reader = PdfReader(path)
            for page in reader.pages:
                images = getattr(page, "images", None)
                if images is None:
                    continue
                for image in list(images):
                    if len(out) >= max_images:
                        return out
                    data = getattr(image, "data", b"") or b""
                    name = str(getattr(image, "name", "embedded.png") or "embedded.png")
                    suffix = os.path.splitext(name)[1].lower()
                    if suffix not in IMAGE_EXTS:
                        suffix = ".png"
                    if len(data) < 256:
                        continue
                    # Some PDF image payloads need Pillow normalization before llama-server.
                    if PIL_AVAILABLE:
                        try:
                            im = Image.open(io.BytesIO(data))
                            buf = io.BytesIO()
                            im.convert("RGB").save(buf, format="PNG")
                            data = buf.getvalue()
                            suffix = ".png"
                        except Exception:
                            pass
                    out.append(_write_temp_image(data, suffix))
        except Exception:
            return []
    return out


def choose_best_embedded_image(paths: List[str]) -> str:
    """Favor portrait-like, substantial images without semantic guessing."""
    if not paths:
        return ""
    if not PIL_AVAILABLE:
        return paths[0]
    scored = []
    for path in paths:
        try:
            with Image.open(path) as im:
                w, h = im.size
            if w < 80 or h < 80:
                continue
            area = w * h
            portrait_bonus = 1.25 if h >= w else 1.0
            scored.append((area * portrait_bonus, path))
        except Exception:
            continue
    if not scored:
        return paths[0]
    scored.sort(reverse=True)
    return scored[0][1]


def _extract_json(raw: str) -> Dict[str, Any] | None:
    text = re.sub(r"```(?:json)?", "", str(raw or ""), flags=re.I).strip()

    def _try(candidate: str):
        candidate = str(candidate or "").strip()
        if not candidate:
            return None
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else None
        except Exception:
            pass
        cleaned = re.sub(r",\s*([}\]])", r"\1", candidate)
        if cleaned != candidate:
            try:
                obj = json.loads(cleaned)
                return obj if isinstance(obj, dict) else None
            except Exception:
                pass
        keyed = re.sub(r'([,{]\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)', r'\1"\2"\3', cleaned)
        if keyed != cleaned:
            try:
                obj = json.loads(keyed)
                return obj if isinstance(obj, dict) else None
            except Exception:
                pass
        try:
            obj = ast.literal_eval(keyed)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

    direct = _try(text)
    if direct is not None:
        return direct
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text[i:])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None


def _coerce_text(value: Any) -> str:
    """Normalize structured model fields into clean editor prose."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        items = [str(item or "").strip() for item in value]
        items = [item for item in items if item]
        return "\n".join(f"• {item}" for item in items)
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            text = str(item or "").strip()
            if text:
                parts.append(f"{str(key).replace('_', ' ').strip().title()}: {text}")
        return "\n".join(parts)
    return str(value or "").strip()


def _coerce_ocean(ocean: Any) -> Dict[str, int]:
    result: Dict[str, int] = {}
    if not isinstance(ocean, dict):
        return result
    for trait in TRAITS:
        raw = ocean.get(trait)
        if raw is None:
            raw = ocean.get(trait.title())
        try:
            val = int(round(float(raw)))
        except Exception:
            continue
        result[trait] = max(0, min(100, val))
    return result




def _ocean_is_coarse(ocean: Dict[str, int]) -> bool:
    """True when a complete profile looks mechanically rounded to broad tens."""
    if len(ocean) < 5:
        return False
    values = [int(ocean[t]) for t in TRAITS if t in ocean]
    return len(values) == 5 and sum(1 for value in values if value % 10 == 0) >= 4


def _refine_coarse_ocean(handler, source_name: str, source_text: str, mode: str, ocean: Dict[str, int]) -> Dict[str, int]:
    """One bounded calibration pass; preserve interpretation, refine only coarse precision."""
    if not _ocean_is_coarse(ocean):
        return ocean
    system = (
        "You are calibrating an already-decided OCEAN profile for Dunoon Daemon. "
        "Preserve the psychological interpretation and rank ordering. Do not materially change the personality. "
        "Use the full 0-100 scale and choose evidence-supported integer values rather than mechanically rounding to tens. "
        "Return exactly one JSON object with keys openness, conscientiousness, extraversion, agreeableness, neuroticism."
    )
    user = (
        f"SOURCE: {source_name}\nIMPORT MODE: {mode}\n"
        f"COARSE PROFILE: {json.dumps(ocean, ensure_ascii=False)}\n\n"
        f"SOURCE EVIDENCE:\n{source_text[:12000]}\n\n"
        "Refine precision only. A few-point adjustment is normal; a major personality shift is not."
    )
    packet = {
        "system": system, "history": [], "user": user, "temperature": 0.08,
        "repeat_penalty": 1.0, "presence_penalty": 0.0, "max_tokens": 300,
        "response_format": {"type": "json_object"}, "disable_reasoning": True,
    }
    try:
        raw = handler.send(packet)
        parsed = _extract_json(raw)
        refined = _coerce_ocean(parsed or {})
        if len(refined) != 5:
            return ocean
        # Calibration is precision, not reinterpretation. Reject any wild movement.
        if any(abs(int(refined[t]) - int(ocean[t])) > 8 for t in TRAITS):
            return ocean
        return refined
    except Exception:
        return ocean


def _coerce_confidence(value: Any) -> Dict[str, int]:
    out = {}
    if not isinstance(value, dict):
        return out
    for key in FIELD_KEYS:
        try:
            out[key] = max(0, min(100, int(round(float(value.get(key))))))
        except Exception:
            continue
    return out


def import_persona_from_source(handler, source_path: str, *, allow_known_character_enrichment: bool = False,
                               image_path: str = "", import_mode: str = "Character",
                               auto_extract_embedded_image: bool = True) -> PersonaImportResult:
    if not source_path:
        raise PersonaImportError("Choose a source file to import.")
    if not os.path.exists(source_path):
        raise PersonaImportError("The selected source file no longer exists.")
    ext = os.path.splitext(source_path)[1].lower()
    if ext not in SUPPORTED_EXTS:
        raise PersonaImportError(f"Unsupported import format: {ext or '[no extension]'}")
    if not (handler and getattr(handler, "is_active", lambda: False)()):
        raise PersonaImportError("Load a local GGUF model before importing a persona.")

    mode = import_mode if import_mode in IMPORT_MODES else "Character"
    source_text = extract_source_text(source_path)
    chosen_image = ""
    image_origin = ""
    if image_path and os.path.exists(image_path):
        chosen_image = image_path
        image_origin = "user-selected"
    elif is_image_file(source_path):
        chosen_image = source_path
        image_origin = "source-image"
    elif auto_extract_embedded_image and ext in DOC_EXTS:
        embedded = extract_embedded_images(source_path)
        chosen_image = choose_best_embedded_image(embedded)
        image_origin = "embedded-document" if chosen_image else ""
        # Keep only the chosen candidate. Clean up the rest immediately.
        for candidate in embedded:
            if candidate != chosen_image:
                try:
                    os.remove(candidate)
                except Exception:
                    pass

    if is_image_file(source_path) and not getattr(handler, "is_vision_model", False):
        raise PersonaImportError("Image-only persona import needs a vision-capable local model.")
    if not source_text and not chosen_image:
        raise PersonaImportError("No readable text or supported image content was found.")

    image_clause = "No image is attached."
    packet_image_path = ""
    if chosen_image and getattr(handler, "is_vision_model", False) and can_attach_to_vision(chosen_image):
        packet_image_path = chosen_image
        image_clause = (
            "One character/creature image is attached. Use it only for visible appearance, body form, equipment and obvious visual facts. "
            "Explicit source text outranks the image."
        )
    elif chosen_image:
        image_clause = "An avatar image is available for the editor but is not being sent to this non-vision inference."

    mode_clause = {
        "Character": (
            "IMPORT MODE: CHARACTER. Build a playable/interactable individual. Preserve biography, voice, relationships, goals and personal contradictions when supported."
        ),
        "NPC": (
            "IMPORT MODE: NPC. Build a concise interactable non-player character. Prioritize role, motives, loyalties, knowledge boundaries, speech style and useful capabilities."
        ),
        "Monster / creature": (
            "IMPORT MODE: MONSTER / CREATURE. Stat blocks and bestiary entries are enough. Translate mechanics into behaviour, instincts, sensory priorities, physiology, powers, limitations and likely communication style. "
            "Do not invent a human-like childhood, profession, moral philosophy or elaborate biography unless the source explicitly provides one. Nonverbal or low-intelligence creatures may communicate through action, sound and instinct."
        ),
    }[mode]

    source_name = os.path.basename(source_path)
    system = (
        "You are Dunoon Daemon's persona-import tool. Convert source material into a conservative, editable persona draft. "
        "Use ONLY supplied source material unless KNOWN CHARACTER ENRICHMENT is explicitly allowed. Original/homebrew source always wins. "
        "If information is missing, leave the field blank rather than inventing lore. "
        f"{mode_clause} "
        "Return exactly one compact JSON object with keys: display_name, core_persona_directives, backstory, physiology, powers_skills, dream_guidance, ocean, confidence, import_notes. "
        "ocean contains integer 0-100 values for openness, conscientiousness, extraversion, agreeableness and neuroticism. Use the full scale: avoid mechanically rounding every score to 0/10/20/etc. when the evidence supports a more precise estimate. "
        "confidence contains integer 0-100 values for display_name, core_persona_directives, backstory, physiology, powers_skills, dream_guidance and ocean. "
        "Confidence measures how strongly the supplied material supports the proposed field, not how eloquent the prose is. "
        "Core persona directives must be directly usable behaviour/voice instructions. Dream guidance preserves identity anchors, vulnerabilities, motives or defining traits."
    )
    user = (
        f"SOURCE NAME: {source_name}\nSOURCE EXTENSION: {ext}\nIMPORT MODE: {mode}\n"
        f"KNOWN CHARACTER ENRICHMENT ALLOWED: {'YES' if allow_known_character_enrichment else 'NO'}\n"
        f"{image_clause}\n\nSOURCE TEXT:\n"
        f"{source_text if source_text else '[no extracted text; rely on attached image if present]'}\n\n"
        "Blank is better than invention."
    )
    packet = {
        "system": system, "history": [], "user": user, "temperature": 0.10,
        "repeat_penalty": 1.0, "presence_penalty": 0.0, "max_tokens": 1900,
        "response_format": {"type": "json_object"}, "disable_reasoning": True,
    }
    if packet_image_path:
        packet["image_path"] = packet_image_path

    raw = handler.send(packet)
    data = _extract_json(raw)
    if not data:
        raise PersonaImportError("The model did not return a valid persona import JSON object.")

    ocean = _coerce_ocean(data.get("ocean"))
    ocean = _refine_coarse_ocean(handler, source_name, source_text, mode, ocean)

    return PersonaImportResult(
        display_name=_coerce_text(data.get("display_name") or data.get("name")),
        core_persona_directives=_coerce_text(data.get("core_persona_directives") or data.get("system_prompt")),
        backstory=_coerce_text(data.get("backstory")), physiology=_coerce_text(data.get("physiology")),
        powers_skills=_coerce_text(data.get("powers_skills") or data.get("powers") or data.get("skills")),
        dream_guidance=_coerce_text(data.get("dream_guidance")), ocean=ocean,
        confidence=_coerce_confidence(data.get("confidence")), import_notes=_coerce_text(data.get("import_notes")),
        source_text=source_text, source_name=source_name, used_image_path=chosen_image,
        image_origin=image_origin, import_mode=mode,
    )
