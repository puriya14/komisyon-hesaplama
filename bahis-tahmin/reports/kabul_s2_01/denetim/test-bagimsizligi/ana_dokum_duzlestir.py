"""Ana oturum dökümünü (JSONL) VERİ olarak okuyup düz olay tablosuna çevirir; yalnızca verilen zaman aralığı.

Kullanım: python ana_dokum_duzlestir.py <dokum.jsonl> <cikti.jsonl> <bas_ts> <bit_ts>
"""
import json
import sys

src, out_path, t0, t1 = sys.argv[1:5]
n = 0
with open(out_path, "w", encoding="utf-8") as out:
    for i, line in enumerate(open(src, encoding="utf-8")):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        ts = d.get("timestamp")
        if not ts or ts < t0 or ts > t1:
            continue
        msg = d.get("message") or {}
        content = msg.get("content")
        role = msg.get("role")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            t = c.get("type")
            rec = {"ts": ts, "ajan": "ana", "etiket": "orkestrator", "satir_no": i + 1, "rol": role,
                   "yan_zincir": d.get("isSidechain")}
            if t == "tool_use":
                rec.update(tur="tool_use", arac=c.get("name"), id=c.get("id"),
                           metin=json.dumps(c.get("input"), ensure_ascii=False))
            elif t == "tool_result":
                cc = c.get("content")
                if isinstance(cc, list):
                    cc = "\n".join(x.get("text", "") for x in cc if isinstance(x, dict))
                rec.update(tur="tool_result", arac=None, id=c.get("tool_use_id"), metin=str(cc))
            elif t == "text":
                rec.update(tur="text" if role == "assistant" else "user_text", arac=None, id=None,
                           metin=c.get("text", ""))
            else:
                continue
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
print(n, "olay")
