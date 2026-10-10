"""Veri sürümü: yeniden kurulan maç tablosunun iki özetini hesaplar (sonuç analizi yok, yalnızca özet).

1) sequences.research.data_sha256 (dizi araştırması manifesti: 6ca929a2…)
2) goals.validation.data_manifest()['sha256'] (önceki görev, experiments.jsonl 0–9. satırlar: 281e3ea2…)
"""
import json
import sys
from pathlib import Path

import pandas as pd

KOD, CSV = Path(sys.argv[1]), sys.argv[2]
sys.path.insert(0, str(KOD))
from bahis_tahmin.goals.validation import data_manifest  # noqa: E402
from bahis_tahmin.sequences.research import data_sha256  # noqa: E402

m = pd.read_csv(CSV, parse_dates=["date"])
dm = data_manifest(m)
print(json.dumps({"satir": len(m), "data_sha256": data_sha256(m), "data_manifest_sha256": dm["sha256"],
                  "ilk": dm["first_date"], "son": dm["last_date"], "kaynak": dm["sources"]}, ensure_ascii=False))
