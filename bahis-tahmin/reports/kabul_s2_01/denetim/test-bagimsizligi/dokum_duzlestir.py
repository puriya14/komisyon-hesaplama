"""Alt ajan dökümlerini (JSONL) VERİ olarak okuyup düz olay tablosuna çevirir. Hiçbir kodu çalıştırmaz.

Çıktı: olaylar.jsonl — her satır: ts, ajan, etiket, satir_no, tur (tool_use/tool_result/text/user_text), arac, id, metin.
"""
import glob
import json
import os
import sys

D = sys.argv[1]
OUT = sys.argv[2]
labels = {}
for m in glob.glob(os.path.join(D, "agent-*.meta.json")):
    aid = os.path.basename(m)[len("agent-"):-len(".meta.json")]
    labels[aid] = json.load(open(m)).get("description")

n = 0
with open(OUT, "w", encoding="utf-8") as out:
    for f in sorted(glob.glob(os.path.join(D, "agent-*.jsonl"))):
        aid = os.path.basename(f)[len("agent-"):-len(".jsonl")]
        for i, line in enumerate(open(f, encoding="utf-8")):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            ts = d.get("timestamp")
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
                rec = {"ts": ts, "ajan": aid, "etiket": labels.get(aid), "satir_no": i + 1, "rol": role}
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
print(n, "olay yazıldı;", labels)
