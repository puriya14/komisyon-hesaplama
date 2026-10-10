"""research.clean_test_status davranışını (01b7e9f) YAPAY manifestlerle sınar. Gerçek maç verisi/sonucu kullanılmaz.

Senaryolar:
  A  resmi çalıştırmayla aynı kod/karar/parametre (398b60b manifesti) + depo experiments.jsonl → temiz?
  B  A + farklı veri özeti (veri_sha256 değişik) → temiz?  (veri karşılaştırılıyor mu?)
  C  A + kod özeti 01b7e9f (HEAD) → temiz?
  D  manifestte kod/karar/parametre alanları yok (None) + experiments boş → temiz?
  E  A + farklı S0 model özetleri (s0_model_ozetleri) → temiz?  (S0 karşılaştırılıyor mu?)
  F  A + experiments boş (ör. reports/ yok) → temiz?
Ayrıca HEAD'de code_sha256() değeri.
"""
import json
import sys
from pathlib import Path

KOD = Path(sys.argv[1])
sys.path.insert(0, str(KOD))
from bahis_tahmin.sequences import research as RS  # noqa: E402

exps = RS._read_experiments(KOD / "reports" / "experiments.jsonl")
base = {
    "on_kayitla_uyum": {"sozlesme": True, "parametre": True, "esleme": True},
    "parametre_ozeti": RS.TEST_OPENED["parametre_ozeti"],
    "uygulama_kararlari_sha256": RS.TEST_OPENED["uygulama_kararlari_sha256"],
    "kod_sha256": RS.TEST_OPENED["kod_sha256"],
    "veri_sha256": "6ca929a2c62fb0aa304bb672339d290347db416e1c8bbfea758f6a46b53b4bc2",
    "s0_model_ozetleri": ["x"],
}
out = {"HEAD_code_sha256": RS.code_sha256(), "TEST_OPENED": RS.TEST_OPENED,
       "experiments_F1_kayitlari": [r.get("zaman_utc") for r in exps
                                    if str(r.get("asama", "")).startswith("dizi-arastirma F1")]}
sc = {
    "A_ayni_kod_ayni_veri": (dict(base), exps),
    "B_farkli_veri": ({**base, "veri_sha256": "0" * 64}, exps),
    "C_HEAD_kodu": ({**base, "kod_sha256": RS.code_sha256()}, exps),
    "D_alanlar_yok_deneyler_bos": ({"on_kayitla_uyum": base["on_kayitla_uyum"]}, []),
    "E_farkli_S0": ({**base, "s0_model_ozetleri": ["baska"]}, exps),
    "F_deneyler_bos": (dict(base), []),
}
for k, (m, e) in sc.items():
    out[k] = RS.clean_test_status(m, e)
print(json.dumps(out, ensure_ascii=False, indent=1))
