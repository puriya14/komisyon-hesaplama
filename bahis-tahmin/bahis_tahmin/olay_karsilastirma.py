"""Kayıtlı araştırmadan çoklu olay öncesi/sonrası karşılaştırması (S6-OLAY-02).

Aynı takımın birden çok geçmiş olayını (ör. bir araştırma grubundaki İY/MS 2/1 maçları) mevcut olay kartının
önce/sonra pencereleriyle, aynı takım perspektifinden yan yana gösteren SALT OKUNUR hesap:

* İki açık giriş yolu: (A) saklı çalıştırma + grup: çalıştırmanın KENDİ tanımı, görünümü, veri özeti ve olay kümesi
  kullanılır (en son revizyon değil); güncel arşivin veri özeti farklıysa ``VERI_SURUMU_DEGISTI`` döner ve yeni veriyle
  hesap yapılmaz. (B) açık görünüm + olay kimliği listesi: elle seçilmiş yeni bir geçmiş incelemedir; ön-kayıt veya eski
  bir çalıştırmanın devamı değildir.
* İlk sürüm sınırları: tek takım, tek lig, tek görünüm, tek anlık görüntü. Takım görünümde birebir adıyla yoksa
  benzer ad eşlemesi yapılmaz. Birden çok lig varsa ``lig`` açıkça seçilmelidir.
* Arşiv bir kez yüklenir, görünüm bir kez kurulur, takım-maç tablosu bir kez hazırlanır; bütün kartlar aynı anlık
  görüntüden ``archive.event_card_in`` (= ``sequences.timeline.event_card``) ile üretilir. Yeni zaman çizelgesi, pazar
  etiketi veya İY/MS dönüşüm tablosu yoktur: A/B/C ve İY/MS merkezi pazar kaydından, takım perspektifi zaman
  çizelgesinden gelir.
* Pencereler seçim filtresiyle daraltılmaz ve önceki/sonraki sezona taşabilir. Eksik maç sıfır gol, mağlubiyet veya
  "gerçekleşmedi" sayılmaz; payda sıfırsa oran null'dur. Aynı maç birden çok pencerede olabilir: toplu özetlerde olay
  kimliğiyle bir kez sayılır ve örtüşme ayrıca raporlanır.
* Bütün sonuçlar ``DESCRIPTIVE_RESEARCH``: model, örüntü taraması, şike tespiti veya strateji doğrulaması değildir;
  istatistiksel test, benzerlik puanı veya öneri üretilmez. Hiçbir dosyaya veya veritabanına yazılmaz, ağ kullanılmaz.

Tek giriş noktası: ``olay_karsilastir(archive, takim, alan=..., calistirma_id=..., grup=...)`` veya
``olay_karsilastir(archive, takim, kaynak=..., olaylar=[...])``.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from . import archive as A
from .calisma import (
    LIMITS,
    OUTCOME_NOTE,
    SELECTED_BY_OUTCOME,
    STATUS,
    CalismaAlani,
    CalismaError,
    DogrulamaHatasi,
    _clean,
    _sha,
    code_info,
    snapshot,
)
from .data.source_registry import archive_allowed

OLAY_ANALIZ_SURUMU = "olay-karsilastirma-v1"
ANALIZ = "COKLU_OLAY_ONCESI_SONRASI"
PRE_OPTIONS = (5, 10)
POST_OPTIONS = (1, 3, 5)
DEFAULT_PRE, DEFAULT_POST = 5, 3
DEFAULT_LIMIT, MAX_LIMIT = 20, 50
MAX_INPUT_IDS = 1000
MODE_STORED = "KAYITLI_CALISTIRMA_GRUBU"
MODE_MANUAL = "ELLE_TARIHSEL_SECIM"
INTERVAL_KEY = "SECILI_OLAYLAR_ARASI_ARALIK"
ABC = ("A", "B", "C")
SORT_RULE = ("Olaylar tarihe göre artan, aynı tarihte olay kimliğine (mac_kimligi) göre artan sıralanır; sonuçlara "
             "göre seçim veya sıralama yapılmaz.")
STORED_NOTE = ("Saklı çalıştırmanın kendi tanımı, görünümü, veri özeti ve grup olay kümesi kullanıldı (en son revizyon "
               "değil). Seçilen olaylar takımın bütün maçlarını temsil ettiği iddia edilmez.")
MANUAL_NOTE = ("Elle verilen olay listesi: yeni, salt okunur bir geçmiş incelemedir; ön-kayıt veya eski bir "
               "çalıştırmanın devamı değildir. Seçilen olaylar takımın bütün maçlarını temsil ettiği iddia edilmez.")
ORDER_NOTE = "Arşivdeki önceki/sonraki kayıt; gerçek ardışıklık doğrulanamadı."
COMPLETE_ORDER_NOTE = ("Arşiv sırası; lig-sezon tamlık eşiği (%97) geçildi. Fikstür listesiyle bağımsız tamlık kanıtı "
                       "değildir.")
WINDOW_NOTE = (A.CARD_SCOPE_NOTE + " Olay seçim filtresi (ör. yalnızca İY/MS 2/1) pencereleri daraltmaz. Olayın "
               "kendisi (t0) önce/sonra özetlerine girmez.")
SUMMARY_NOTE = ("Sayılar yalnızca gözlenen kayıtlardandır: eksik konum sıfır gol, mağlubiyet veya 'gerçekleşmedi' "
                "sayılmaz; her pazarın paydası kendi geçerli kayıt sayısıdır; payda sıfırsa oran null'dur. Hükmen "
                "olabilecek maçın sonucu bilinmiyor sayılır ve gol toplamlarına girmez.")
OVERLAP_NOTE = ("Aynı maç birden çok olayın penceresinde olabilir; toplu özetlerde olay kimliğiyle bir kez sayılır. "
                "Pencereler bağımsız örnekler değildir; bağımsızlık testi yapılmadı.")
INTERVAL_NOTE = ("Arşivde gözlenen lig kaydı sayısıdır, doğrulanmış oynanan maç sayısı değildir: arşivde olmayan lig "
                 "maçları ve kupa/Avrupa maçları sayılmaz. İşaretsiz olması tamlık kanıtı değildir. 'Sırası geldi' "
                 "veya 'her N maçta tekrarlar' çıkarımı yapılmaz.")
LEAGUE_NOTE = ("Kaynaklar yalnızca lig maçlarını içerir: 'önceki 5' takımın bütün resmî maçları değildir; kupa ve "
               "Avrupa maçları arşivde yoktur. Skorlar normal süre sonudur (uzatma devreleri ve penaltı atışları "
               "hariç).")
SCOPE_NOTE = ("Betimleyici geçmiş incelemedir: model, örüntü taraması, şike tespiti veya strateji doğrulaması "
              "değildir; tahmin başarısı veya ekonomik avantaj göstermez. İstatistiksel test, benzerlik puanı veya "
              "öneri yoktur.")
TEAM_MISSING = ("Takım bu görünümde yok: '{takim}'. Benzer ad eşlemesi yapılmaz; görünümdeki tam adı kullanın (tek "
                "kaynak görünümünde takım adları kaynağın kendi adlarıdır).")
STATE_TEXT = {
    "COMPLETE": "Pencere dolu ve işaretsiz.",
    "DATA_START": "Takımın arşivdeki ilk kayıtlarına ulaşıldı (veri başlangıcı); daha önceki maçlar arşivde yok.",
    "COVERAGE_EXIT": "Takımın bu kapsamdaki kayıtları bitti (ör. lig değişikliği); sonraki maçlar arşivde yok.",
    "GAP_GT_400D": "400 günden uzun kapsam boşluğu; pencere boşluğun ötesine taşınmadı.",
    "RIGHT_CENSORED": "Arşiv sonu: sonraki maçlar arşivde yok.",
    "INCOMPLETE_SEASON": "Pencere tam olmayan bir lig-sezondan geçiyor; arada arşivde olmayan maç olabilir.",
    "SEASON_SKIP": "Pencere arşivde olmayan bir sezonun üzerinden geçiyor.",
    "HT_MISSING": "Penceredeki en az bir kaydın ilk yarı skoru yok.",
    "POSSIBLE_AWARDED": "Penceredeki en az bir maç hükmen olabilir; sonucu bilinmiyor sayılır.",
    "UST_TUR": "Olay normal sezon dışı (üst tur) maçı; pencere kurulmaz.",
}
NO_NEXT_TEXT = {
    "HENUZ_OYNANMAMIS_OLABILIR": "Kaynakta oynanmamış fikstür var: sonraki maç henüz oynanmamış olabilir.",
    "KAYNAK_GUNCEL_DEGIL_OLABILIR": "Kaynakta tarihi geçmiş ama sonucu olmayan maç var: kaynak güncel olmayabilir.",
    "KAPSAM_BITTI": ("Takımın bu lig kapsamındaki kayıtları bitti (ör. küme düşme); kaynak yalnızca lig maçlarını "
                     "içerir."),
    "UZUN_KAPSAM_BOSLUGU": "Takımın kayıtlarında 400 günden uzun boşluk var.",
    "UST_TUR": "Olay normal sezon dışı (üst tur) maçı; pencere kurulmaz.",
    "BILINMIYOR": "Neden kaynak bilgisinden belirlenemedi.",
}
INTERVAL_FLAG_TEXT = {
    "EKSIK_SEZON": "aralık tam olmayan lig-sezondan geçiyor (arşivde olmayan maç olabilir)",
    "DILIM_DEGISTI": "aralık uzun bir kapsam boşluğundan (>400 gün) geçiyor",
    "SEZON_ATLAMASI": "aralıkta arşivde olmayan sezon var",
    "LIG_DEGISTI": "aralıkta lig değişikliği var",
    "BILINMEYEN_SONUC": "aralıkta İY/MS sonucu bilinmeyen kayıt var",
    "UST_TUR": "olaylardan biri normal sezon dışı (üst tur) kaydı; sıra konumu yok",
}
INVALID_TEXT = {
    "GORUNUMDE_YOK": "Olay kimliği bu görünümde yok (başka görünüme geçilmez).",
    "TAKIM_BU_MACTA_YOK": "Seçilen takım bu maçta oynamıyor.",
    "SKOR_DOGRULANMADI": "Maçın skoru bu görünümde doğrulanmadı (çelişki veya tarih incelemesi); pencere kurulmaz.",
    "LIG_KAPSAMI_DISI": "Olay seçilen lig kapsamının dışında (ilk sürüm tek lig).",
    "BELIRSIZ_OLAY_KIMLIGI": "Olay kimliği görünümde birden çok satıra karşılık geliyor.",
    "KART_URETILEMEDI": "Mevcut olay kartı bu olay için üretilemedi.",
}


# ----------------------------------------------------------------------------
# Girdi doğrulama
# ----------------------------------------------------------------------------

def _int(name: str, v, default: int) -> int:
    if v is None:
        return default
    if isinstance(v, bool):
        raise DogrulamaHatasi(f"{name}: tam sayı olmalı")
    try:
        x = int(v)
    except (TypeError, ValueError) as e:
        raise DogrulamaHatasi(f"{name}: tam sayı olmalı") from e
    if isinstance(v, float) and v != x:
        raise DogrulamaHatasi(f"{name}: tam sayı olmalı")
    return x


def secenekler(once=None, sonra=None, limit=None, offset=None) -> dict:
    """Pencere ve sayfalama seçenekleri. Önceki pencere 5 veya 10, sonraki 1, 3 veya 5 (varsayılan 5 ve 3); en çok 50
    olay (varsayılan 20). Daha fazlası sessizce kesilmez: hata verir, ``offset`` ile sayfalanır."""
    o = _int("once", once, DEFAULT_PRE)
    s = _int("sonra", sonra, DEFAULT_POST)
    lim = _int("limit", limit, DEFAULT_LIMIT)
    off = _int("offset", offset, 0)
    if o not in PRE_OPTIONS:
        raise DogrulamaHatasi(f"once: {', '.join(map(str, PRE_OPTIONS))} değerlerinden biri olmalı")
    if s not in POST_OPTIONS:
        raise DogrulamaHatasi(f"sonra: {', '.join(map(str, POST_OPTIONS))} değerlerinden biri olmalı")
    if not 1 <= lim <= MAX_LIMIT:
        raise DogrulamaHatasi(f"limit: 1–{MAX_LIMIT} olmalı; daha fazla olay için offset ile sayfalayın (sessiz kesme "
                              "yapılmaz)")
    if off < 0:
        raise DogrulamaHatasi("offset: 0 veya pozitif olmalı")
    return {"once": o, "sonra": s, "limit": lim, "offset": off}


def _team(takim) -> str:
    if not isinstance(takim, str) or not takim.strip():
        raise DogrulamaHatasi("takim: görünümdeki tam takım adı verilmeli")
    t = takim.strip()
    if len(t) > LIMITS["takim"]:
        raise DogrulamaHatasi(f"takim: en çok {LIMITS['takim']} karakter")
    return t


def _ids(olaylar) -> list:
    if isinstance(olaylar, str) or not isinstance(olaylar, (list, tuple)):
        raise DogrulamaHatasi("olaylar: olay kimliği listesi olmalı")
    if not olaylar:
        raise DogrulamaHatasi("olaylar: en az bir olay kimliği verilmeli")
    if len(olaylar) > MAX_INPUT_IDS:
        raise DogrulamaHatasi(f"olaylar: en çok {MAX_INPUT_IDS} olay kimliği")
    out = []
    for x in olaylar:
        if not isinstance(x, str) or not x.strip() or len(x) > 300:
            raise DogrulamaHatasi(f"olaylar: geçersiz olay kimliği {x!r}")
        out.append(x.strip())
    return out


def _league(lig):
    from .data.leagues import LEAGUES

    if lig in (None, ""):
        return None
    if not isinstance(lig, str) or lig.strip() not in LEAGUES:
        raise DogrulamaHatasi(f"lig: bilinmeyen lig kodu {lig!r}")
    return lig.strip()


# ----------------------------------------------------------------------------
# Giriş noktaları
# ----------------------------------------------------------------------------

def olay_karsilastir(archive: A.Archive, takim: str, *, alan: CalismaAlani | None = None, calistirma_id=None,
                     grup=None, kaynak=None, olaylar=None, lig=None, once=None, sonra=None, limit=None,
                     offset=None) -> dict:
    """Arayüz ve CLI için TEK giriş noktası. Ya saklı çalıştırma yolu (``alan`` + ``calistirma_id`` + ``grup``) ya da
    açık liste yolu (``kaynak`` + ``olaylar``) verilir; ikisi birlikte veya hiçbiri verilirse ``DogrulamaHatasi``.
    Döner: JSON'a hazır sözlük (NaN yok). Salt okunur."""
    stored = calistirma_id not in (None, "")
    explicit = olaylar is not None
    if stored == explicit:
        raise DogrulamaHatasi("Ya saklı çalıştırma (calistirma + grup) ya da açık olay listesi (olaylar + kaynak) "
                              "verilmeli; ikisi birlikte kullanılamaz.")
    if stored:
        if kaynak not in (None, ""):
            raise DogrulamaHatasi("Saklı çalıştırma yolunda görünüm çalıştırmanın kendisinden gelir; kaynak verilemez.")
        if alan is None:
            raise CalismaError("Saklı çalıştırma için çalışma alanı gerekli.")
        return kayitli_calistirmadan(alan, archive, calistirma_id, grup, takim, lig=lig, once=once, sonra=sonra,
                                     limit=limit, offset=offset)
    if grup is not None:
        raise DogrulamaHatasi("grup yalnızca saklı çalıştırma yolunda kullanılır.")
    if kaynak in (None, ""):
        raise DogrulamaHatasi("Açık olay listesinde görünüm açıkça verilmeli (tek kaynak veya 'birlesik').")
    return acik_listeden(archive, kaynak, takim, olaylar, lig=lig, once=once, sonra=sonra, limit=limit,
                         offset=offset)


def kayitli_calistirmadan(alan: CalismaAlani, archive: A.Archive, calistirma_id: str, grup, takim: str, lig=None,
                          once=None, sonra=None, limit=None, offset=None) -> dict:
    """Saklı çalıştırmanın Grup 1 veya 2 olaylarından seçilen takımın olayları. Çalıştırmanın kendi tanımı, görünümü ve
    olay kümesi kullanılır; güncel arşivin veri özeti saklı özetle aynı değilse hesap yapılmaz."""
    opts = secenekler(once, sonra, limit, offset)
    team = _team(takim)
    lg = _league(lig)
    if grup not in (1, 2, "1", "2"):
        raise DogrulamaHatasi("grup: 1 veya 2 olmalı")
    g = int(grup)
    rec = alan.calistirma(calistirma_id, olaylar=True)  # güncel kullanım kapsamı burada uygulanır
    tanim = rec["tanim"]
    flt = tanim.get(f"grup_{g}")
    sel = {"tur": MODE_STORED, "calistirma_id": rec["calistirma_id"], "arastirma_id": rec["arastirma_id"],
           "revizyon": rec["revizyon"], "tanim_ozeti": _sha(tanim), "grup": g, "grup_filtresi": flt,
           "sonuca_gore_secildi": bool((flt or {}).get("sonuc")), "aciklama": STORED_NOTE}
    key = tanim["gorunum"]["kaynak"]
    if rec["sonuc"].get("kapali_kaynaklar"):
        return _closed(sel, key, opts, rec["sonuc"]["kapali_kaynaklar"])
    kume = rec["olay_kumeleri"].get(str(g))
    if kume is None or flt is None:
        raise DogrulamaHatasi(f"Bu çalıştırmada grup {g} yok.")
    ids = kume.get("olaylar") or []
    if _sha(ids) != kume["olay_ozeti"] or len(ids) != kume["olay_sayisi"]:
        raise CalismaError("Saklı grup olay kümesi özetiyle uyuşmuyor; hesap yapılmadı.")
    sel.update({"grup_olay_sayisi": len(ids), "olay_kumesi_ozeti": kume["olay_ozeti"]})
    v = A.view(archive, key)
    if v.kapali:
        return _closed(sel, key, opts, [key])
    snap = snapshot(archive, v)
    if snap["veri_ozeti"] != rec["veri"]["veri_ozeti"]:
        out = _head(sel, v, opts)
        out.update({"durum": "VERI_SURUMU_DEGISTI", "sakli_veri_ozeti": rec["veri"]["veri_ozeti"],
                    "guncel_veri_ozeti": snap["veri_ozeti"], "olaylar": [],
                    "metin": "Saklı çalıştırmanın veri sürümü mevcut arşivde yok; olaylar yeni veriyle hesaplanmadı. "
                             "Yeni veriyle inceleme için açık olay listesi yolunu kullanın (yeni inceleme olarak)."})
        return _clean(out)
    warnings = []
    if sel["sonuca_gore_secildi"]:
        warnings.append({"kod": SELECTED_BY_OUTCOME, "metin": OUTCOME_NOTE})
    return _compute(archive, v, snap, team, ids, sel, flt, lg, opts, warnings, explicit=False)


def acik_listeden(archive: A.Archive, kaynak, takim: str, olaylar, lig=None, once=None, sonra=None, limit=None,
                  offset=None) -> dict:
    """Açık görünüm ve olay kimliği listesiyle elle seçilmiş geçmiş inceleme. Aynı kimlik iki kez verilirse bir kez
    sayılır; geçersiz kimlikler nedeniyle listelenir (sessizce atlanmaz)."""
    opts = secenekler(once, sonra, limit, offset)
    team = _team(takim)
    lg = _league(lig)
    raw = _ids(olaylar)
    try:
        key = A.resolve_source(kaynak)
    except A.ArchiveError as e:
        raise DogrulamaHatasi(f"kaynak: {e}") from e
    uniq = sorted(set(raw))
    sel = {"tur": MODE_MANUAL, "girdi_olay_sayisi": len(raw), "tekil_olay_sayisi": len(uniq),
           "tekrar_eden_girdi": len(raw) - len(uniq), "olay_kumesi_ozeti": _sha(uniq), "aciklama": MANUAL_NOTE}
    v = A.view(archive, key)
    if v.kapali:
        return _closed(sel, key, opts, [key])
    snap = snapshot(archive, v)
    warnings = [{"kod": MODE_MANUAL, "metin": MANUAL_NOTE}]
    return _compute(archive, v, snap, team, uniq, sel, None, lg, opts, warnings, explicit=True)


# ----------------------------------------------------------------------------
# Hesap
# ----------------------------------------------------------------------------

def _versions() -> dict:
    p = Path(__file__)
    digest = hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() if p.is_file() else None
    return {**code_info(), "olay_analiz_surumu": OLAY_ANALIZ_SURUMU, "olay_kod_ozeti": digest}


def _head(sel: dict, v: A.ArchiveView | None, opts: dict) -> dict:
    gor = ({"tur": v.tur, "kaynak": v.kaynak, "aciklama": v.aciklama(), "kullanim": A.USE_NOTE} if v is not None
           else None)
    return {"statu": STATUS, "analiz": ANALIZ, "durum": None, "secim": sel, "gorunum": gor,
            "secenekler": {**{k: opts[k] for k in ("once", "sonra")}, "izinli_once": list(PRE_OPTIONS),
                           "izinli_sonra": list(POST_OPTIONS)},
            "aciklamalar": [{"kod": "BETIMLEYICI", "metin": SCOPE_NOTE}], "surumler": _versions()}


def _closed(sel: dict, key, opts: dict, closed: list) -> dict:
    out = _head(sel, None, opts)
    out.update({"durum": "KULLANIM_KAPSAMI_KAPALI", "kapali_kaynaklar": sorted(str(x) for x in closed if x),
                "gorunum": {"kaynak": key, "aciklama": A.CLOSED_NOTE.format(kaynak=key)}, "olaylar": [],
                "metin": "Kullanılan kaynak(lar) şu anda tarihsel analize kapalı; olay, pencere veya sayı "
                         "gösterilmez."})
    for k in ("olay_kumesi_ozeti", "grup_olay_sayisi"):
        out["secim"].pop(k, None)
    return _clean(out)


def _score(a, b):
    return f"{int(a)}-{int(b)}" if np.isfinite(a) and np.isfinite(b) else None


def _num(x):
    return int(x) if np.isfinite(x) else None


def _label(x):
    return None if not np.isfinite(x) else int(x)


def _perspective(r) -> dict:
    """Takım perspektifi: ham İY/MS (ev sahibi-deplasman kodu), takımın İY ve MS sonucu, yarı golleri ve A/B/C.
    Aynı ham kod ev sahibi ve deplasman için farklı takım davranışıdır (ör. 2/1: ev sahibi İY geride MS galip,
    deplasman İY önde MS mağlup); ikisi tek etiket altında birleştirilmez."""
    from .goals.markets import TEAM_TARGETS

    cells = {v: k for k, v in TEAM_TARGETS.items()}
    home = bool(r["is_home"])
    awarded = bool(r["awarded"])
    gf_ht, ga_ht, gf_ft, ga_ft = (float(r[c]) for c in ("gf_ht", "ga_ht", "gf_ft", "ga_ft"))
    ht_ok = np.isfinite(gf_ht) and np.isfinite(ga_ht) and not awarded
    ft_ok = bool(r["ft_known"])
    ht, ft = r["ht_res"], r["ft_res"]
    return {"ev_sahibi": home, "yer": "ev" if home else "deplasman", "rakip": r["opponent"],
            "rakip_kaynak_adi": r["opponent_raw"], "iy_ms_ham": r["htft"] if isinstance(r["htft"], str) else None,
            "takim_iy": ht, "takim_ms": ft, "takim_iy_ms": cells.get((ht, ft)) if ht and ft else None,
            "iy_skor_takim": _score(gf_ht, ga_ht), "ms_skor_takim": _score(gf_ft, ga_ft),
            "ilk_yari_atilan": _num(gf_ht) if ht_ok else None, "ilk_yari_yenilen": _num(ga_ht) if ht_ok else None,
            "ikinci_yari_atilan": _num(gf_ft - gf_ht) if ht_ok and ft_ok else None,
            "ikinci_yari_yenilen": _num(ga_ft - ga_ht) if ht_ok and ft_ok else None,
            "A": _label(float(r["A"])), "B": _label(float(r["B"])), "C": _label(float(r["C"])),
            "hukmen_olabilir": awarded, "ilk_yari_skoru_yok": not (np.isfinite(gf_ht) and np.isfinite(ga_ht)),
            "ust_tur": bool(r["ust_tur"])}


def stats(tm: pd.DataFrame, idx) -> dict:
    """Verilen takım-maç satırlarının (tekil) betimleyici özeti: yalnızca gözlenen kayıtlar; payda sıfırsa null."""
    t = tm.loc[sorted(set(int(i) for i in idx))] if len(idx) else tm.iloc[0:0]
    n = int(len(t))
    awarded = t["awarded"].to_numpy(dtype=bool)
    gf_ht, ga_ht = t["gf_ht"].to_numpy(dtype=float), t["ga_ht"].to_numpy(dtype=float)
    gf_ft, ga_ft = t["gf_ft"].to_numpy(dtype=float), t["ga_ft"].to_numpy(dtype=float)
    ft_ok = t["ft_known"].to_numpy(dtype=bool)
    ht_ok = np.isfinite(gf_ht) & np.isfinite(ga_ht) & ~awarded
    both = ht_ok & ft_ok
    res = t["ft_res"].to_numpy(dtype=object)

    def goals(ok, gf, ga) -> dict:  # geçerli skor yoksa toplam null (sıfır gol uydurulmaz)
        n_ok = int(ok.sum())
        return {"gecerli_mac": n_ok, "atilan": int(gf[ok].sum()) if n_ok else None,
                "yenilen": int(ga[ok].sum()) if n_ok else None}

    out = {"gozlenen_kayit": n, "kullanilabilir_mac": int(ft_ok.sum()), "sonucu_bilinmeyen_kayit": n - int(ft_ok.sum()),
           "pazarlar": {}, "takim_ms": {"G": int((res[ft_ok] == "G").sum()), "B": int((res[ft_ok] == "B").sum()),
                                        "M": int((res[ft_ok] == "M").sum()), "gecerli": int(ft_ok.sum())},
           "gol": goals(ft_ok, gf_ft, ga_ft), "ilk_yari_gol": goals(ht_ok, gf_ht, ga_ht),
           "ikinci_yari_gol": goals(both, gf_ft - gf_ht, ga_ft - ga_ht)}
    for k in ABC:
        col = t[k].to_numpy(dtype=float)
        valid = int(np.isfinite(col).sum())
        yes = int((col == 1.0).sum())
        out["pazarlar"][k] = {"evet": yes, "gecerli": valid, "bilinmiyor": n - valid,
                              "oran": (yes / valid) if valid else None}
    return out


def _coverage(archive: A.Archive, v: A.ArchiveView, lg: str) -> tuple[dict, dict]:
    """Görünümün bu ligdeki doğrulanmış blokları (sezon → bloklar) ve doğrulanamayan bloklar (sezon → kayıtlar)."""
    in_view = ((lambda k: k == v.kaynak) if v.kaynak is not None
               else (lambda k: archive_allowed(str(k), "tarihsel_analiz")))
    rej_keys = {(r.get("kaynak"), r.get("yol"), r.get("blok")) for r in archive.rejected}
    by_season: dict = {}
    for b in archive.blocks():
        if ("satir_ozeti" in b and b.get("lig") == lg and in_view(b.get("kaynak"))
                and (b.get("kaynak"), b.get("yol"), b.get("blok")) not in rej_keys):
            by_season.setdefault(str(b.get("sezon")), []).append(b)
    rejected: dict = {}
    for r in archive.rejected:
        if in_view(r.get("kaynak")) and r.get("lig") == lg:
            rejected.setdefault(str(r.get("sezon")), []).append(r)
    return by_season, rejected


def _season_info(cov: tuple, season: str) -> dict:
    by_season, rejected = cov
    bs = by_season.get(season, [])
    info = {"sezon": season, "kaynak_kapsamlari": sorted({str(b.get("kapsam")) for b in bs}),
            "tam_kaynak_var": any(str(b.get("kapsam")).startswith("TAM") for b in bs),
            "oynanmamis": int(sum(int(b.get("oynanmamis") or 0) for b in bs)),
            "tarihi_gecmis_sonucsuz": int(sum(int(b.get("tarihi_gecmis_sonucsuz") or 0) for b in bs)),
            "dogrulanamayan_blok": len(rejected.get(season, []))}
    if not bs:
        info["kaynak_kapsamlari"] = ["BLOK_BILGISI_YOK"]
    return info


def _window(tm, card_w: dict, k: int, forward: bool, ev_row, cov: tuple) -> dict:
    """Bir önce/sonra penceresinin özeti: durum, gözlenen/eksik konum, betimleyici sayılar, ardışıklık ve bilinen
    kaynak boşlukları. Olayın kendisi girmez."""
    st = card_w["durum"]
    idx = [int(x["row_id"]) for x in card_w["maclar"]]
    seasons = sorted({str(tm.loc[ev_row, "season"])} | {str(tm.loc[i, "season"]) for i in idx})
    infos = [_season_info(cov, s) for s in seasons]
    known_gaps = [x for x in infos if x["kaynak_kapsamlari"] != ["BLOK_BILGISI_YOK"]
                  and (not x["tam_kaynak_var"] or x["dogrulanamayan_blok"] or x["tarihi_gecmis_sonucsuz"])]
    out = {"pencere": f"{'sonraki' if forward else 'onceki'}_{k}", "istenen_konum": k, "gozlenen_kayit": len(idx),
           "eksik_konum": k - len(idx), "durum": st, "durum_aciklama": STATE_TEXT.get(st, st),
           "tam_pencere": st == "COMPLETE" and len(idx) == k,
           "ardisiklik": COMPLETE_ORDER_NOTE if st == "COMPLETE" else ORDER_NOTE,
           **stats(tm, idx),
           "sezonlar": seasons, "bilinen_kaynak_bosluklari": known_gaps,
           "kaynak_kapsami_bilinmeyen_sezonlar": [x["sezon"] for x in infos
                                                  if x["kaynak_kapsamlari"] == ["BLOK_BILGISI_YOK"]],
           "celiski": None, "not": SUMMARY_NOTE}
    if st == "COMPLETE" and known_gaps:
        out["celiski"] = {"kod": "PENCERE_TAM_AMA_KAYNAKTA_BILINEN_BOSLUK",
                          "metin": "Pencere tamlık eşiğini geçiyor, ama kaynak bu lig-sezonu kısmi veya doğrulanamamış "
                                   "olarak işaretliyor; arşivde olmayan maç olabilir."}
    if forward and len(idx) < k:
        out["sonraki_kayit_yok"] = _no_next(st, cov, str(tm.loc[ev_row, "season"]))
    return out


def _no_next(state: str, cov: tuple, season: str) -> list:
    codes = []
    if state == "RIGHT_CENSORED":
        later = [s for s in cov[0] if s >= season]
        infos = [_season_info(cov, s) for s in sorted(later)]
        if any(x["oynanmamis"] for x in infos):
            codes.append("HENUZ_OYNANMAMIS_OLABILIR")
        if any(x["tarihi_gecmis_sonucsuz"] for x in infos):
            codes.append("KAYNAK_GUNCEL_DEGIL_OLABILIR")
    elif state == "COVERAGE_EXIT":
        codes.append("KAPSAM_BITTI")
    elif state == "GAP_GT_400D":
        codes.append("UZUN_KAPSAM_BOSLUGU")
    elif state == "UST_TUR":
        codes.append("UST_TUR")
    return [{"kod": c, "metin": NO_NEXT_TEXT[c]} for c in (codes or ["BILINMIYOR"])]


def _in_group_filter(eid: str, season: str, flt: dict) -> bool:
    lg, day, home, away = str(eid).split("|", 3)
    base = {k: flt.get(k) for k in ("lig", "takim", "yer", "bas", "son")}
    return any(A._in_filter(lg, season, day, home, away, {**base, "sezon": s}) for s in (flt.get("sezonlar") or [None]))


def _intervals(tm: pd.DataFrame, canon: str, cands: list, start: int, stop: int) -> list:
    """Her sayfa olayı için sıralı aday listesindeki bir önceki seçili olaydan bu yana aralık (sayfalamadan
    bağımsız): takvim günü, arşivde gözlenen kayıt ve süreklilik işaretleri (``sequences.timeline`` kuralları)."""
    from .sequences.timeline import _gap_flags

    t = tm[(tm["team"] == canon) & tm["in_seq"]].reset_index(drop=True)
    pos = {e: i for i, e in enumerate(t["event_id"])}
    known = (t["htft"].notna() & ~t["awarded"].astype(bool)).reset_index(drop=True)
    team_dates = pd.to_datetime(tm.loc[tm["team"] == canon, "date"])
    out = []
    for k in range(start, stop):
        eid, day = cands[k]["eid"], cands[k]["date"]
        if k == 0:
            out.append({"olay_kimligi": eid, "onceki_secili_olay": None, "takvim_gunu": None,
                        "arsivde_gozlenen_kayit": None, "dogrulanmis_oynanan_mac": None,
                        "sureklilik_durumu": None, "isaretler": [],
                        "metin": "Seçimdeki ilk olay; önceki seçili olay yok."})
            continue
        prev, pday = cands[k - 1]["eid"], cands[k - 1]["date"]
        a, b = pos.get(prev), pos.get(eid)
        flags = ["UST_TUR"] if a is None or b is None else [f for f in _gap_flags(t, known, a, b, True).split(",") if f]
        between = int(((team_dates > pday) & (team_dates < day)).sum())
        out.append({"olay_kimligi": eid, "onceki_secili_olay": prev, "takvim_gunu": int((day - pday).days),
                    "arsivde_gozlenen_kayit": between, "dogrulanmis_oynanan_mac": None,
                    "sureklilik_durumu": "BOSLUK_ISARETLI" if flags else "ISARETSIZ",
                    "isaretler": [{"kod": f, "metin": INTERVAL_FLAG_TEXT.get(f, f)} for f in flags],
                    "metin": INTERVAL_NOTE})
    return out


def _compute(archive: A.Archive, v: A.ArchiveView, snap: dict, team: str, ids: list, sel: dict, flt: dict | None,
             lig, opts: dict, warnings: list, explicit: bool) -> dict:
    if team not in v.teams():
        raise DogrulamaHatasi(TEAM_MISSING.format(takim=team))
    merged = v.merged
    pos_of: dict = {}
    for i, mid in enumerate(merged["mac_kimligi"]):
        pos_of.setdefault(mid, []).append(i)
    sel_set = set(ids)
    invalid, not_team, cands = [], 0, []
    for eid in sorted(sel_set):
        hits = pos_of.get(eid, [])
        reason = None
        if not hits:
            reason = "GORUNUMDE_YOK"
        elif len(hits) > 1:
            reason = "BELIRSIZ_OLAY_KIMLIGI"
        else:
            r = merged.iloc[hits[0]]
            if team not in (r["home"], r["away"]):
                if not explicit:
                    not_team += 1  # grup başka takımların maçlarını da içerebilir: sayılır, tek tek listelenmez
                    continue
                reason = "TAKIM_BU_MACTA_YOK"
            elif r["durum"] != "TAMAM":
                reason = "SKOR_DOGRULANMADI"
        if reason:
            invalid.append({"olay_kimligi": eid, "neden": reason, "metin": INVALID_TEXT[reason],
                            **({"durum": merged.iloc[hits[0]]["durum"]} if reason == "SKOR_DOGRULANMADI" else {})})
            continue
        cands.append({"eid": eid, "date": pd.Timestamp(r["date"]).normalize(), "league": r["league"],
                      "season": str(r["season"])})
    leagues = Counter(c["league"] for c in cands)
    if lig is None and len(leagues) > 1:
        raise DogrulamaHatasi("Olaylar birden çok ligde (" + ", ".join(f"{k}: {n}" for k, n in sorted(leagues.items()))
                              + "); ilk sürüm tek lig kapsamındadır, lig açıkça seçilmeli.")
    if lig is not None:
        for c in [c for c in cands if c["league"] != lig]:
            invalid.append({"olay_kimligi": c["eid"], "neden": "LIG_KAPSAMI_DISI",
                            "metin": INVALID_TEXT["LIG_KAPSAMI_DISI"], "lig": c["league"]})
        cands = [c for c in cands if c["league"] == lig]
    lg = lig if lig is not None else (next(iter(leagues)) if leagues else None)
    cands.sort(key=lambda c: (c["date"], c["eid"]))
    invalid.sort(key=lambda x: (x["neden"], x["olay_kimligi"]))
    off, lim = opts["offset"], opts["limit"]
    start, stop = min(off, len(cands)), min(off + lim, len(cands))
    page = cands[start:stop]
    out = _head(sel, v, opts)
    out.update({"durum": "TAMAMLANDI", "veri": snap})
    out["sayfalama"] = {"toplam_aday": len(cands), "offset": off, "limit": lim, "bu_sayfada": len(page),
                        "kalan": len(cands) - stop, "sonraki_offset": stop if stop < len(cands) else None,
                        "azami_limit": MAX_LIMIT, "varsayilan_limit": DEFAULT_LIMIT, "siralama": SORT_RULE}
    out["gecersiz_olaylar"] = invalid
    out["gecersiz_ozeti"] = {**dict(sorted(Counter(x["neden"] for x in invalid).items())),
                             **({"TAKIM_BU_MACTA_YOK_GRUPTA": not_team} if not explicit else {})}
    tm = None
    if cands:
        try:
            tm = A.team_matches(v, lg)
        except ValueError as e:  # mevcut zaman çizelgesinin belirsiz sıra kuralı
            raise CalismaError(f"Takım-maç tablosu kurulamadı: {e}") from e
    cand_ids = {c["eid"] for c in cands}
    canon, raw_names = None, []
    events, occ = [], {}
    pre_rows, post_rows, ev_rows = [], [], []
    cov = _coverage(archive, v, lg) if lg else ({}, {})
    origin = _Origin(merged, pos_of) if v.kaynak is None else {}  # birleştirilmiş görünümde alan kökeni
    kapsam = None
    for k, c in enumerate(page):
        eid = c["eid"]
        try:
            card = A.event_card_in(archive, v, tm, eid, team, pre=(opts["once"],), post=(opts["sonra"],))
        except A.ArchiveError as e:
            raise CalismaError(f"Olay kartı üretilemedi ({eid}): {e}") from e
        row = int(tm.index[(tm["event_id"] == eid) & (tm["team_raw"] == team)][0])
        r = tm.loc[row]
        if canon is None:
            canon = r["team"]
        elif r["team"] != canon:
            raise DogrulamaHatasi("Takım kimliği olaylar arasında belirsiz; farklı takım satırları karıştırılmaz.")
        kapsam = kapsam or card["kapsam"]
        pw, qw = card["PRE_EVENT"][f"onceki_{opts['once']}"], card["POST_EVENT"][f"sonraki_{opts['sonra']}"]
        pre_idx = [int(x["row_id"]) for x in pw["maclar"]]
        post_idx = [int(x["row_id"]) for x in qw["maclar"]]
        positions = []
        for j in range(opts["once"] - len(pre_idx)):
            positions.append(_missing(-(opts["once"] - j), pw["durum"]))
        for j, i in enumerate(pre_idx):
            positions.append(_position(tm, i, -(len(pre_idx) - j), cand_ids, sel_set, flt, origin))
        positions.append(_position(tm, row, 0, cand_ids, sel_set, flt, origin))
        for j, i in enumerate(post_idx):
            positions.append(_position(tm, i, j + 1, cand_ids, sel_set, flt, origin))
        for j in range(len(post_idx), opts["sonra"]):
            positions.append(_missing(j + 1, qw["durum"]))
        for p in positions:
            if p["durum"] == "GOZLENDI" and p["konum"] != "t0":
                occ.setdefault(p["olay_kimligi"], []).append(
                    {"olay": eid, "taraf": "onceki" if p["konum"].startswith("t-") else "sonraki", "konum": p["konum"]})
        pre_rows += pre_idx
        post_rows += post_idx
        ev_rows.append(row)
        events.append({"sira": start + k + 1, "olay_kimligi": eid, "tarih": str(c["date"].date()), "lig": r["league"],
                       "sezon": str(r["season"]), "takim_perspektifi": _perspective(r), "konumlar": positions,
                       "onceki": _window(tm, pw, opts["once"], False, row, cov),
                       "sonraki": _window(tm, qw, opts["sonra"], True, row, cov),
                       "kaynak": card["kaynak"], "alan_kokeni": origin.get(eid, "")})
    page_ids = [c["eid"] for c in page]
    for e in events:
        e["baska_olayin_penceresinde"] = occ.get(e["olay_kimligi"], [])
        e["penceresindeki_secili_olaylar"] = [p["olay_kimligi"] for p in e["konumlar"]
                                             if p["durum"] == "GOZLENDI" and p["konum"] != "t0" and p["secili_olay"]]
    out["olaylar"] = events
    if tm is not None and canon is not None:
        raw_names = sorted(set(tm.loc[tm["team"] == canon, "team_raw"]))
    kim, unknown = A._identity_review(v.review, lig=lg, takim=team)
    team_rows = (merged[(merged["league"] == lg) & ((merged["home"] == team) | (merged["away"] == team))] if lg
                 else merged.iloc[0:0])
    out["takim"] = {"ad": team, "kanonik_ad": canon, "kaynak_adlari": raw_names, "lig": lg,
                    "lig_dagilimi": dict(sorted(leagues.items())),
                    "not": ("Birden çok kaynak adı mevcut kimlik eşlemesiyle aynı takıma bağlandı."
                            if len(raw_names) > 1 else None)}
    out["kimlik_incelemesi"] = {
        "takim_kaynak_satiri": int(len(kim)), "takima_indirgenemeyen": unknown,
        "pencereye_girmeyen_takim_kaydi": dict(sorted(Counter(team_rows.loc[team_rows["durum"] != "TAMAM",
                                                                             "durum"]).items())),
        "not": "Takım kimliği kesinleşmeyen, çelişkili veya tarih incelemesindeki kayıtlar pencerelere girmez; benzer "
               "ad eşlemesi yapılmaz."}
    win_ids = set(occ)
    win_days = sorted(pd.Timestamp(str(e).split("|", 3)[1]) for e in win_ids)
    win_seasons = sorted({str(tm.loc[i, "season"]) for i in pre_rows + post_rows}) if tm is not None else []
    cand_days = [c["date"] for c in cands]
    lo, hi = (min(cand_days), max(cand_days)) if cand_days else (None, None)
    out["pencere_kapsami"] = {
        "pencere_sezonlari": win_seasons,
        "pencere_tarih_araligi": [str(win_days[0].date()), str(win_days[-1].date())] if win_days else None,
        "secim_sezonlari": sorted({c["season"] for c in cands}),
        "secim_tarih_araligi": [str(lo.date()), str(hi.date())] if cand_days else None,
        "secim_kumesi_disi_pencere_maci": len([e for e in win_ids if e not in sel_set]),
        "secim_filtresi_disi_pencere_maci": (None if flt is None else
                                             len([e for e in win_ids if not _in_group_filter(
                                                 e, str(tm.loc[_row_of(tm, e, canon), "season"]), flt)])),
        "secim_tarih_araligi_disi_pencere_maci": (len([d for d in win_days if d < lo or d > hi]) if cand_days
                                                  else 0),
        "not": WINDOW_NOTE}
    pre_set, post_set = set(), set()
    for e in events:
        for p in e["konumlar"]:
            if p["durum"] == "GOZLENDI" and p["konum"] != "t0":
                (pre_set if p["konum"].startswith("t-") else post_set).add(p["olay_kimligi"])
    multi = [{"olay_kimligi": e, "pencere_sayisi": len(occ[e]), "yerler": occ[e]} for e in sorted(occ)
             if len(occ[e]) > 1]
    sel_in = [{"olay_kimligi": e, "bu_sayfada": e in set(page_ids), "yerler": occ[e]} for e in sorted(occ)
              if e in cand_ids]
    out["ortusme"] = {"toplam_pencere_konumu": len(pre_rows) + len(post_rows), "onceki_pencere_konumu": len(pre_rows),
                      "sonraki_pencere_konumu": len(post_rows), "benzersiz_mac": len(win_ids),
                      "onceki_benzersiz": len(pre_set), "sonraki_benzersiz": len(post_set),
                      "onceki_ve_sonraki_ortak": len(pre_set & post_set), "birden_fazla_pencerede_mac": len(multi),
                      "birden_fazla_pencerede": multi, "pencerede_secili_olay": sel_in,
                      "bagimsiz_ornek_degil": bool(multi or sel_in or (pre_set & post_set)),
                      "istatistiksel_test": "YAPILMADI", "not": OVERLAP_NOTE}
    tstat = (lambda rows: stats(tm, rows)) if tm is not None else (lambda rows: None)
    states = {"onceki": dict(sorted(Counter(e["onceki"]["durum"] for e in events).items())),
              "sonraki": dict(sorted(Counter(e["sonraki"]["durum"] for e in events).items()))}
    out["toplu"] = {"kapsam": "Bu sayfadaki olaylar; pencere kayıtları olay kimliğiyle bir kez sayılır.",
                    "olay_sayisi": len(events), "onceki": tstat(pre_rows), "olaylar": tstat(ev_rows),
                    "sonraki": tstat(post_rows), "pencere_durumlari": states,  # stats tekilleştirir
                    "tam_onceki_pencere": sum(1 for e in events if e["onceki"]["tam_pencere"]),
                    "tam_sonraki_pencere": sum(1 for e in events if e["sonraki"]["tam_pencere"]),
                    "not": SUMMARY_NOTE}
    out[INTERVAL_KEY] = _intervals(tm, canon, cands, start, stop) if tm is not None and canon is not None else []
    out["kapsam"] = {**(kapsam or {}), "lig_disi_maclar": LEAGUE_NOTE}
    if v.kaynak is None:
        warnings.append({"kod": "BIRLESTIRILMIS_GORUNUM", "metin": A.MERGED_NOTE})
    if snap["dogrulanamayan_blok"]:
        warnings.append({"kod": "DOGRULANAMAYAN_BLOK",
                         "metin": f"{snap['dogrulanamayan_blok']} blok köken doğrulamasından geçmedi; kullanılmadı."})
    if invalid:
        warnings.append({"kod": "GECERSIZ_OLAY", "metin": f"{len(invalid)} olay hesaplanmadı; nedenleri "
                                                          "'gecersiz_olaylar' altında."})
    if out["sayfalama"]["kalan"]:
        warnings.append({"kod": "SAYFALAMA", "metin": f"Toplam {len(cands)} adaydan bu sayfada {len(page)} olay "
                                                      f"hesaplandı; kalan {out['sayfalama']['kalan']} olay için "
                                                      f"offset={stop} kullanın."})
    if out["ortusme"]["bagimsiz_ornek_degil"]:
        warnings.append({"kod": "ORTUSEN_PENCERELER", "metin": OVERLAP_NOTE})
    out["uyarilar"] = warnings
    if snapshot(archive, v)["veri_ozeti"] != snap["veri_ozeti"]:
        raise CalismaError("Görünümün verisi hesap sırasında değişti; karışık sonuç döndürülmedi.")
    out = _clean(out)
    out["sonuc_ozeti"] = _sha(out)
    return out


class _Origin:
    """Birleştirilmiş görünüm satırının alan kökeni (``archive.field_origin``), olay kimliğiyle ve gerektikçe."""

    def __init__(self, merged: pd.DataFrame, pos_of: dict):
        self.merged, self.pos_of, self.cache = merged, pos_of, {}

    def get(self, eid: str, default: str = "") -> str:
        if eid not in self.cache:
            hits = self.pos_of.get(eid, [])
            self.cache[eid] = A.field_origin(self.merged.iloc[hits[0]]) if len(hits) == 1 else default
        return self.cache[eid]


def _row_of(tm: pd.DataFrame, eid: str, canon: str) -> int:
    return int(tm.index[(tm["event_id"] == eid) & (tm["team"] == canon)][0])


def _missing(konum: int, state: str) -> dict:
    return {"konum": f"t{konum:+d}", "durum": "KAYIT_YOK", "neden": state, "metin": STATE_TEXT.get(state, state)}


def _position(tm: pd.DataFrame, i: int, konum: int, cand_ids: set, sel_set: set, flt: dict | None,
              origin: dict) -> dict:
    r = tm.loc[i]
    eid = r["event_id"]
    return {"konum": "t0" if konum == 0 else f"t{konum:+d}", "durum": "GOZLENDI", "olay_kimligi": eid,
            "tarih": str(pd.Timestamp(r["date"]).date()), "sezon": str(r["season"]), **_perspective(r),
            "lig_arasi_gun": _num(float(r["lig_arasi_gun"])) if r["lig_arasi_gun"] is not None else None,
            "sezon_tam": bool(r["season_complete"]), "sezon_atlamasi": bool(r["season_skip"]),
            "kaynak": r["source"], "alan_kokeni": origin.get(eid, ""), "secili_olay": eid in cand_ids,
            "secim_kumesinde": eid in sel_set,
            "secim_filtresinde": None if flt is None else _in_group_filter(eid, str(r["season"]), flt),
            "sira_turu": "ARSIV_SIRASI"}
