"""S2-KABUL-01: referans sürecin ulaşılabilir eşikleri ve sentetik pozitif/negatif kontrol (katı kural ile).

Yalnızca sentetik veri. Sentetik kontrol sonucu gerçek futbol avantajı değildir.
"""

import numpy as np
import pytest

from bahis_tahmin.sequences import config as C
from bahis_tahmin.sequences import null as NL
from bahis_tahmin.sequences import patterns as P
from bahis_tahmin.sequences.synthetic import synthetic_frame

SUPPORT = {"min_n": 300, "min_e": 10.0}
PLANTED = "IY_GERIDE_MS_GALIP|SON_MAC_IY_GERIDE_MS_GALIP"
R_STRICT = 104  # c = 0 iken MC %99 Clopper–Pearson üst sınırının 0,05'in altına indiği en küçük R


def _strict(c: int, R: int) -> tuple[float, float]:
    _, hi = NL.clopper_pearson(np.array([c]), R)
    return (c + 1) / (R + 1), float(hi[0])


def test_strict_rule_reachability():
    """Katı kural (p_adj < 0,05 VE MC üst sınır < 0,05): R = 20 ile hiçbir hipotez geçemez; c = 0 için R ≥ 104 gerekir."""
    assert C.MC_CI_LEVEL == 0.99
    p20, hi20 = _strict(0, 20)
    assert p20 == pytest.approx(1 / 21) and hi20 > 0.2  # p < 0,05 olsa da üst sınır geçmez
    assert _strict(0, R_STRICT - 1)[1] >= C.ALPHA and _strict(0, R_STRICT)[1] < C.ALPHA
    # Resmî R = 1000: en çok c = 32 aşımda geçer (p_adj = 33/1001 ≈ 0,033); R = 200 için c ≤ 2
    reach = {R: max([c for c in range(80) if (lambda p, h: p < C.ALPHA and h < C.ALPHA)(*_strict(c, R))], default=None)
             for R in (20, R_STRICT, 200, C.N_NULL)}
    assert C.N_NULL == 1000 and reach == {20: None, R_STRICT: 0, 200: 2, 1000: 32}


@pytest.fixture(scope="module")
def frames():
    pos, _, _ = synthetic_frame(5, comeback_boost=3.0, n_leagues=4)
    neg, _, _ = synthetic_frame(5, comeback_boost=1.0, n_leagues=4)
    return pos, neg


def _wy(fr, R):
    # Mevcut ekili etki testiyle aynı satırlar (üç dönem birlikte; makine testi, protokol dönemi değil)
    mask = fr.eligible & np.isin(fr.period.astype(str), ["kesif", "parametre", "test"])
    prep = P.prepare(fr, mask)
    obs = P.evaluate(fr, mask, prep=prep, **SUPPORT).set_index("hyp_id", drop=False)
    nul = NL.run_null(fr, mask, R, 3, prep=prep, **SUPPORT)
    p, lo, hi = NL.westfall_young_stepdown(obs["z"].to_numpy(), obs["supported"].to_numpy(), nul["z"], nul["supported"])
    obs["p_adj"], obs["ci_hi"] = p, hi
    return obs[obs["supported"] & (obs["p_adj"] < C.ALPHA) & (obs["ci_hi"] < C.ALPHA)]


def test_positive_and_negative_control_under_strict_rule(frames):
    """Aynı akış, aynı R: ekili güçlü etki katı kuralla yakalanır; etkisiz veride katı kuralı geçen hipotez yok."""
    pos, neg = frames
    hits = _wy(pos, 200)
    assert PLANTED in hits.index
    assert _wy(neg, 200).empty


def test_market_checks_are_labelled_historical_reference_only(frames):
    """Piyasa kontrolü (7b/5) çıktısı oranın zamanı doğrulanmamış tarihsel referans olduğunu taşır."""
    from bahis_tahmin.sequences.odds_status import ODDS_STATUS

    pos, _ = frames
    mask = pos.eligible & np.isin(pos.period.astype(str), ["kesif"])
    fa = P.falsification(pos, "IY_GERIDE_MS_GALIP", "SON_MAC_IY_GERIDE_MS_GALIP", mask,
                         p0_market=np.full(len(pos.tm), 0.3))
    assert ODDS_STATUS == "HISTORICAL_REFERENCE_ONLY" and fa["checks"]["5_piyasa"]["oran_statusu"] == ODDS_STATUS


def test_odds_label_does_not_change_preregistered_parameters():
    from bahis_tahmin.sequences.research import PREREGISTERED

    assert C.config_hash() == PREREGISTERED["parametre_ozeti"]


def test_anomaly_outputs_have_no_prematch_consumer():
    """Ters yön koruması: anomali modülünü yalnızca araştırma yürütücüsü içe aktarır; maç öncesi/tahmin yolları
    anomali çıktısını okumaz (eşikler geriye dönük, tüm sezonu kullanır)."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "bahis_tahmin"
    # Göreli yol işletim sisteminden bağımsız gösterilir (Windows'ta str() ters eğik çizgi üretir; S3-WIN-01)
    importers = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.py")
                       if re.search(r"from \.+(sequences\.)?anomaly import|from \.+sequences import anomaly|"
                                    r"from \. import anomaly|sequences\.anomaly", p.read_text(encoding="utf-8"))
                       and p.name != "anomaly.py")
    assert importers == ["sequences/research.py"]
    for rel in ("sequences/prematch.py", "sequences/patterns.py", "sequences/models.py", "goals/engine.py",
                "goals/decision.py", "goals/forecast_log.py"):
        path = root / rel
        if path.exists():
            assert not re.search(r"anomal|UNEXPLAINED|surprise_bits", path.read_text(encoding="utf-8")), rel


def test_relative_path_display_is_platform_independent():
    """Yukarıdaki tüketici listesi karşılaştırması için: aynı göreli yol Windows ve POSIX biçiminde aynı ``as_posix()``
    gösterimini verir; ``str()`` gösterimi ise farklıdır (Windows hatasının nedeni). Gerçek Windows testinin yerine
    geçmez."""
    from pathlib import PurePosixPath, PureWindowsPath

    win = PureWindowsPath(r"C:\depo\bahis_tahmin\sequences\research.py").relative_to(r"C:\depo\bahis_tahmin")
    posix = PurePosixPath("/depo/bahis_tahmin/sequences/research.py").relative_to("/depo/bahis_tahmin")
    assert win.as_posix() == posix.as_posix() == "sequences/research.py"
    assert str(win) == "sequences\\research.py" != str(posix)


def test_anomaly_display_labels_are_neutral():
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from bahis_tahmin.ui.pages import sequences as S

    text = S._anomaly_summary_text({"toplam": 3, "tur": {"UNEXPLAINED_ANOMALY": 2, "MODEL_PIYASA_FARKI": 1},
                                    "durum": {"açıklanabilir": 1, "UNEXPLAINED_ANOMALY": 2}, "donem": {"test": 3}})
    assert "UNEXPLAINED_ANOMALY" not in text and "yaygınlık tahmini değildir" in text
    assert "alternatif açıklamayla uyumlu" in text
    assert all("şike" not in v and "suç" not in v for v in S._ANOMALY_VALUES.values())


def test_openfootball_2026_names_map_to_store_names():
    from bahis_tahmin.data.teams import match_team

    known = ["Nijmegen", "PSV Eindhoven", "Rennes", "Benfica", "Sp Lisbon", "Porto", "Lens"]
    assert match_team("NEC", known) == "Nijmegen"
    assert match_team("Stade Rennais FC 1901", known) == "Rennes"
    assert match_team("Sport Lisboa e Benfica", known) == "Benfica"
    assert match_team("Sporting Clube de Portugal", known) == "Sp Lisbon"
    assert match_team("PSV", known) == "PSV Eindhoven"


def _temp_contract_sha256(RS, root, data: bytes) -> str | None:
    """Geçici sözleşme kopyasını (yalnızca ``root`` altında, bayt olarak) yazıp ürün fonksiyonuyla özetler."""
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "DIZI_ARASTIRMA_SOZLESMESI.md").write_bytes(data)
    return RS.contract_sha256()


@pytest.mark.parametrize("ending", ["LF", "CRLF"])
def test_contract_hash_ignores_line_endings(tmp_path, monkeypatch, ending):
    """Sözleşme özeti satır sonundan bağımsızdır; test girdisi kaynak checkout'u LF veya CRLF olsa da aynıdır
    (S3-WIN-01: CRLF checkout'a ikinci kez CRLF uygulamak ``\\r\\r\\n`` üretiyordu). Gerçek içerik değişikliği ve
    fazladan CR yine fark edilir; ürün fonksiyonu ve ön-kayıtlı özet değişmez."""
    from bahis_tahmin.sequences import research as RS

    expected = RS.PREREGISTERED["sozlesme_sha256"]
    assert RS.contract_sha256() == expected  # asıl sözleşme (bu checkout LF veya CRLF olabilir)
    src = (RS._repo_root() / "docs" / "DIZI_ARASTIRMA_SOZLESMESI.md").read_bytes()
    canonical_lf = src.replace(b"\r\n", b"\n")  # ortak başlangıç: yalnızca CRLF -> LF
    assert b"\r" not in canonical_lf and canonical_lf.count(b"\n") > 0
    sample = canonical_lf if ending == "LF" else canonical_lf.replace(b"\n", b"\r\n")
    if ending == "CRLF":
        assert b"\r\r\n" not in sample and sample.count(b"\r\n") == canonical_lf.count(b"\n")
    else:
        assert b"\r\n" not in sample
    monkeypatch.setattr(RS, "_repo_root", lambda: tmp_path)
    assert _temp_contract_sha256(RS, tmp_path, sample) == expected
    # Satır sonu dışındaki gerçek içerik değişikliği (yalnızca geçici kopyada) özeti değiştirir
    nl = b"\n" if ending == "LF" else b"\r\n"
    changed = sample + b"<!-- TEST AMACLI ICERIK DEGISIKLIGI -->" + nl
    assert _temp_contract_sha256(RS, tmp_path, changed) != expected
    # Normalizasyon dar kalır: fazladan CR (``\r\r\n``) satır sonu değil, içerik farkıdır
    assert _temp_contract_sha256(RS, tmp_path, canonical_lf.replace(b"\n", b"\r\r\n")) != expected
    assert _temp_contract_sha256(RS, tmp_path, sample) == expected  # aynı kopya geri yazılınca yine eşit


def test_redirected_cli_output_survives_ansi_code_page(monkeypatch):
    import io
    import sys

    from bahis_tahmin import cli

    buf = io.BytesIO()
    out = io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", out)
    assert cli.main(["gol-olcum-degerlendir", "--protokol"]) == 0
    out.flush()
    assert "maç günü 00:00" in buf.getvalue().decode("utf-8")
