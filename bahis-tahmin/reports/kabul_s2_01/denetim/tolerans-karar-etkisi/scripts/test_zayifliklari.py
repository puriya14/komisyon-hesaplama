"""tests/test_primary_regression.py (01b7e9f) iddia mantığının iki zayıflığını altın değerlerle gösterir (kopyalanmış mantık):
(1) aralık karşılaştırmasında NaN maskesi denetlenmiyor; (2) 'tail' anahtarında mutlak TOL, büyüklüğün kendisinden büyük."""
import json, sys
import numpy as np
gold = json.load(open(sys.argv[1]))
TOL = 5e-5
_arr = lambda v: np.array([np.nan if x is None else x for x in np.ravel(v)], dtype=float)  # noqa: E731  (testteki gibi)
out = {}
# (1) aralık: testteki iki satırın birebir kopyası, bir satırın aralığı NaN yapılırsa
want = _arr(gold["interval"]["BTTS_BOTH_HALVES_YES"])
got = want.copy(); got[0:2] = np.nan  # ilk maçın [alt, üst] ucu kayboldu
out["aralik_NaN_kaybi_test_gecer"] = bool(np.nanmax(np.abs(got - want)) <= TOL)
got2 = want.copy(); got2[:-2] = np.nan  # 20 maçın 19'unda aralık kayboldu
out["aralik_19/20_NaN_test_gecer"] = bool(np.nanmax(np.abs(got2 - want)) <= TOL)
# predict tarafında maske denetimi VAR: aynı kayıp orada yakalanır
wp = _arr(gold["predict"]["A"]); gp = wp.copy(); gp[0] = np.nan
out["predict_NaN_kaybi_maske_yakalar"] = not bool(np.array_equal(np.isnan(gp), np.isnan(wp)))
# (2) tail: altın büyüklüğü ve sıfır tahmini
tail = _arr(gold["predict"]["tail"])
out["tail_altin_max"] = float(np.nanmax(tail)); out["tail_altin_medyan"] = float(np.nanmedian(tail))
out["tail_hepsi_sifir_test_gecer"] = bool(np.nanmax(np.abs(np.zeros_like(tail) - tail)) <= TOL)
out["tail_10kat_test_gecer"] = bool(np.nanmax(np.abs(10 * tail - tail)) <= TOL)
# (3) ilk başarısız anahtarda durma: predict 17 anahtar, aralık 3 anahtar
out["predict_anahtar_sayisi"] = len(gold["predict"]); out["predict_anahtar_sirasi"] = list(gold["predict"])
out["interval_anahtar_sirasi"] = list(gold["interval"])
print(json.dumps(out, ensure_ascii=False, indent=1))
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
