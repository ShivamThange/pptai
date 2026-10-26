import hashlib
import json
import re
from pathlib import Path


def read_json(path):
    with open(path, encoding="utf-8") as f: return json.load(f)


def write_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f: json.dump(value, f, indent=2, ensure_ascii=False)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
    return h.hexdigest()


def clean(text): return re.sub(r"\s+", " ", text or "").strip()


def sentences(text):
    return [clean(s) for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(clean(s).split()) >= 3]
