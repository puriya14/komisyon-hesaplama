"""Fikstür kontrolü (salt okuma): indirilen openfootball 2026-27 dosyalarını TEMEL (01b7e9f) proje ayrıştırıcısıyla
okur, _update_fixtures'ın süzme kuralını taklit eder, takım adı eşlemesini (data/teams.match_team) gerçek veri
adlarına karşı sınar ve veri kesiminden (son maç) sonra oynanmış ama veride olmayan maç SAYISINI çıkarır.

Skor DEĞERLERİ kullanılmaz; yalnızca "skor alanı dolu mu" (oynanmış mı) bilgisi sayılır. Örüntü/hipotez testi yok.

Kullanım: python -I fikstur_kontrol.py <kod_kok> <maclar.csv.gz> <cikti_klasoru> <lig_kodu=dosya.json> [...]
"""

import json
import sys
from pathlib import Path

kod, csv_path, out_dir = sys.argv[1], sys.argv[2], Path(sys.argv[3])
pairs = [a.split("=", 1) for a in sys.argv[4:]]
sys.path.insert(0, kod)

import pandas as pd  # noqa: E402

from bahis_tahmin.data.parsers import parse_openfootball  # noqa: E402
from bahis_tahmin.data.store import DataStore  # noqa: E402
from bahis_tahmin.data.teams import ALIASES, match_team, norm_key  # noqa: E402

TODAY = pd.Timestamp("2026-10-10")
out_dir.mkdir(parents=True, exist_ok=True)
m = pd.read_csv(csv_path, parse_dates=["date"], low_memory=False)
rapor = {"bugun": str(TODAY.date()), "mac_sayisi": int(len(m)), "veri_son_tarih": str(m["date"].max().date()),
         "ligler": {}}
eslesme_rows = []


def how(name, known):
    """match_team'in hangi adımla eşlediğini (yaklaşık) etiketler."""
    if name in known:
        return "birebir"
    key = norm_key(name)
    by_key = {norm_key(c): c for c in known}
    if key in by_key:
        return "normalize"
    alias = ALIASES.get(key)
    if alias and alias in known:
        return "takma_ad_tablosu"
    return "jeton/benzerlik" if match_team(name, known) else "ESLESMEDI"


for code, path in pairs:
    raw = Path(path).read_bytes()
    obj = json.loads(raw.decode("utf-8"))
    allm = obj.get("matches", [])
    of = parse_openfootball(raw, code)  # proje ayrıştırıcısı: yalnızca oynanmamış maçlar
    lg = m[m["league"] == code]
    known = DataStore._recent_teams(m, code)  # _update_fixtures ile aynı: son 2 sezon
    last_data = lg["date"].max()
    # _update_fixtures süzmesi (football-data fikstürü yokmuş gibi: last_fd = NaT)
    win = {}
    for days in (10, 60):
        lo, hi = TODAY, TODAY + pd.Timedelta(days=days)
        f = of[(of["date"] >= lo) & (of["date"] <= hi)].copy()
        f["home_m"] = [match_team(t, known) for t in f["home"]]
        f["away_m"] = [match_team(t, known) for t in f["away"]]
        unm = f["home_m"].isna() | f["away_m"].isna()
        win[f"{days}_gun"] = {"fikstur": int(len(f)), "eslesmeyen": int(unm.sum()),
                              "saatsiz": int((f["time"].astype(str) == "").sum()),
                              "ilk_tarih": str(f["date"].min().date()) if len(f) else None,
                              "son_tarih": str(f["date"].max().date()) if len(f) else None}
    teams = sorted({(t if isinstance(t, str) else t.get("name")) for mm in allm for t in (mm["team1"], mm["team2"])})
    for t in teams:
        tgt = match_team(t, known)
        eslesme_rows.append({"lig": code, "openfootball_adi": t, "eslesen_veri_adi": tgt, "yontem": how(t, known),
                             "veride_son_2_sezonda": tgt in known if tgt else False})
    # Veri kesiminden sonra (last_data, TODAY] openfootball'da skor alanı DOLU maçlar = veride olmayan oynanmış maçlar
    def played(mm):
        sc = mm.get("score")
        if isinstance(sc, dict):
            return bool(sc.get("ft"))
        if isinstance(sc, list):
            return len(sc) >= 2 and sc[0] is not None and sc[1] is not None
        return mm.get("score1") is not None and mm.get("score2") is not None

    gap_rows = []
    for mm in allm:
        d = pd.Timestamp(mm["date"])
        if last_data < d <= TODAY:
            gap_rows.append({"date": d, "home": mm["team1"], "away": mm["team2"], "played": played(mm)})
    gap = pd.DataFrame(gap_rows)
    per_team = {}
    if len(gap):
        for side in ("home", "away"):
            for t, g in gap.groupby(side):
                k = match_team(t, known) or t
                per_team.setdefault(k, {"oynanmis": 0, "skorsuz": 0})
                per_team[k]["oynanmis"] += int(g["played"].sum())
                per_team[k]["skorsuz"] += int((~g["played"]).sum())
    sc_types = pd.Series([type(mm.get("score")).__name__ for mm in allm]).value_counts().to_dict()
    list_scores = [mm for mm in allm if isinstance(mm.get("score"), list)]
    rapor["ligler"][code] = {
        "dosya": str(path), "dosya_adi_alani": obj.get("name"), "toplam_mac": len(allm),
        "skor_alani_turleri": sc_types, "liste_skor_ornekleri": list_scores[:3],
        "proje_ayristirici_oynanmamis": int(len(of)),
        "proje_ayristirici_tarih_araligi": [str(of["date"].min().date()), str(of["date"].max().date())] if len(of) else None,
        "bugunden_sonra_oynanmamis": int((of["date"] > TODAY).sum()),
        "veri_son_mac_bu_lig": str(last_data.date()),
        "veri_son_2_sezon_takimlari": known,
        "pencere_10_ve_60_gun": win,
        "kesimden_sonra_bugune_kadar_mac": int(len(gap)),
        "kesimden_sonra_skoru_dolu_mac": int(gap["played"].sum()) if len(gap) else 0,
        "kesimden_sonra_skorsuz_mac": int((~gap["played"]).sum()) if len(gap) else 0,
        "takim_basina_kayitsiz_oynanmis_mac": dict(sorted(per_team.items())),
    }

pd.DataFrame(eslesme_rows).to_csv(out_dir / "openfootball_takim_eslesme.csv", index=False, encoding="utf-8")
(out_dir / "fikstur_kontrol.json").write_text(json.dumps(rapor, ensure_ascii=False, indent=1, default=str),
                                              encoding="utf-8")
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk not in ("veri_son_2_sezon_takimlari", "liste_skor_ornekleri",
                                                                    "takim_basina_kayitsiz_oynanmis_mac")}
                  for k, v in rapor["ligler"].items()}, ensure_ascii=False, indent=1, default=str))
print(pd.DataFrame(eslesme_rows).to_string(index=False))
