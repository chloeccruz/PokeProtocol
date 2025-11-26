# messages.py
# utilities to serialize and parse newline-separated "key: value" messages

from typing import Dict, Any

def serialize_message(d: Dict[str, Any]) -> bytes:
    """
    create newline-separated "key: value" pairs. Dict values that are dict/list are converted safely
    """
    lines = []
    for k, v in d.items():
        if isinstance(v, (dict, list)):
            #use repr to keep it compact | receiving side can eval() or use ast.literal_eval
            lines.append(f"{k}: {repr(v)}")
        else:
            lines.append(f"{k}: {v}")
    return ("\n".join(lines)).encode("utf-8")

def parse_message(raw: bytes) -> Dict[str, str]:
    """
    parse a bytes payload into a dict of strings
    """
    text = raw.decode("utf-8", errors="ignore")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out = {}
    for ln in lines:
        if ":" not in ln:
            continue
        k, v = ln.split(":", 1)
        out[k.strip()] = v.strip()
    return out

def make_ack(ack_number: int):
    return {"message_type": "ACK", "ack_number": ack_number}
