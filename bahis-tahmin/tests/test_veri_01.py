"""VERI-01: "birçok maç için veri bulunamadı" düzeltmesi.

Üç katman ayrı ayrı sınanır:

1. Kişisel kullanım beyanı: lisans belgesi doğrulanamayan kaynakta (football-data, GitHub yedeği) model eğitimi ve
   tahmin yalnızca indirme onayı + açık kişisel (ticari olmayan) kullanım beyanıyla açılır; kayıt gerçeği değişmez.
2. Takım adları: maç düzeyinde kanıtlı takma adlar ve yalnızca yazımı farklı adların birleştirilmesi.
3. Veri denetimi modu: "standart" (uygulama varsayılanı) yalnızca kanıt eksikliğini engel saymaz; bilinen eksik veri
   ve az geçmiş yalnızca bahis adayını engeller; yapısal engeller her iki modda tahmini engeller. "siki" v2 aynen.

Bütün veriler AÇIKÇA SENTETİKTİR (geçici klasörler); ağ isteği yapılmaz.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json

import pandas as pd
import pytest
from uygunluk_yardim import AS_OF, FIXTURE_DAY, full_context, recent_synthetic, synthetic_rights

from bahis_tahmin import eligibility as E
from bahis_tahmin.data import source_registry as R
from bahis_tahmin.goals.engine import GoalEngine
from bahis_tahmin.goals.service import gated_goal_predictions

FD = "football-data.co.uk"
MIRROR = "github-yedek"


@pytest.fixture(scope="module")
def m():
    return recent_synthetic()


@pytest.fixture(scope="module")
def eng(m):
    e = GoalEngine()
    e.train(m)
    return e


@pytest.fixture(scope="module")
def teams(m):
    return sorted(set(m["home"]))


def one(ctx, teams, *, as_of=AS_OF, day=FIXTURE_DAY, pcodes=(), market="FT_OVER_3_5", **kw):
    return ctx.evaluate(league="T1", date=day, home=teams[0], away=teams[1], as_of=as_of, markets=(market,),
                        prediction_codes=pcodes, **kw)[market]


# ====================================================================== 3) veri denetimi modu
def test_levels_cover_every_code_and_standart_is_never_stricter():
    for mode in E.POLICY_MODES:
        assert set(E.LEVELS[mode]) == set(E.REASONS)
    rank = {"yok": 0, "bahis": 1, "tahmin": 2}
    for c in E.REASONS:
        assert rank[E.code_level(c, "standart")] <= rank[E.code_level(c, "siki")], c
        assert E.code_level(c, "siki") == E.REASONS[c].blocks  # sıkı mod v2 ile aynı
    structural = ("BAGLAM_YOK", "BAGLAM_UYUSMUYOR", "MAC_GECMISTE", "MODEL_YOK", "LIG_MODEL_KAPSAMI_DISI",
                  "TAKIM_ESLESMEDI", "TAKIM_ESLESMESI_DOGRULANAMADI", "TAKIM_DURUMDA_YOK", "DURUM_KARAR_ANINDAN_SONRA",
                  "GEREKLI_ALAN_EKSIK", "KAYNAK_ERISIM_IZNI_YOK", "KAYNAK_HAKKI_BILINMIYOR", "KAYNAK_ETIKETI_UYUMSUZ",
                  "KAYNAK_KOKENI_DOGRULANAMADI", "KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI",
                  "KAYNAK_EGITIM_HAKKI_DOGRULANAMADI", "KAYNAK_MODEL_KULLANIMI_DOGRULANAMADI",
                  "MODEL_EGITIM_KOKENI_YOK", "OLASILIK_GECERSIZ")
    assert all(E.code_level(c, "standart") == "tahmin" for c in structural)
    with pytest.raises(ValueError):
        E.EligibilityContext(None, None, mode="gevsek")


def test_unverifiable_freshness_blocks_only_in_strict_mode(m, eng, teams):
    near = dt.datetime(2026, 3, 5, 12, tzinfo=dt.timezone.utc)  # son lig maçından 4 gün sonra; takvim kaynağı yok
    day = dt.date(2026, 3, 8)
    strict = E.EligibilityContext(m, E.state_view(eng), rights=synthetic_rights())
    std = E.EligibilityContext(m, E.state_view(eng), rights=synthetic_rights(), mode="standart")
    assert strict.fingerprint != std.fingerprint
    s = one(strict, teams, as_of=near, day=day)
    e = one(std, teams, as_of=near, day=day)
    assert not s.forecast_ok and s.status_label == "Doğrulanamıyor" and s.policy_version == E.POLICY_VERSION
    # Aynı kanıt, standart mod: güncellik gerçeği değişmez (UNKNOWN) ama bilinen bir sorun olmadığı için tahmin ve
    # değer hesabı engellenmez; açıklama güncelliğin doğrulanamadığını yazar
    assert e.reasons == s.reasons and e.freshness == E.UNKNOWN and "KAYNAK_KAPSAMI_YOK" in e.reasons
    assert e.forecast_ok and e.bet_ok and e.status_label == "Kullanılabilir" and e.lead_code is None
    assert e.policy_mode == "standart" and e.policy_version == E.POLICY_VERSIONS["standart"]
    assert "doğrulanamadı" in e.short_text() and "KAYNAK_KAPSAMI_YOK" in e.short_text()
    assert E.check_for_display(e, e.candidate_id, e.market, near) == []
    assert E.check_for_decision(e, e.candidate_id, e.market, near) == []
    assert e.compact()["politika_modu"] == "standart"
    # Politika sürümü ve mod birbirini tutmalı (sahte sonuç gösterilmez)
    forged = dataclasses.replace(e, policy_version=E.POLICY_VERSION)
    assert E.check_for_display(forged, e.candidate_id, e.market, near) == ["BAGLAM_UYUSMUYOR"]


def test_known_missing_match_shows_warned_forecast_but_never_a_bet(m, teams):
    team = teams[0]
    idx = m[(m["home"] == team) | (m["away"] == team)].index[-3]
    stale_store = m.drop(index=idx)
    stale_eng = GoalEngine()
    stale_eng.train(stale_store)
    fx = pd.DataFrame([{"league": "T1", "date": pd.Timestamp(FIXTURE_DAY), "time": "", "home": teams[0],
                        "away": teams[1], "source": "SENTETIK-FIKSTUR"}])
    strict = full_context(stale_store, stale_eng, AS_OF, FIXTURE_DAY, schedule=m)
    std = full_context(stale_store, stale_eng, AS_OF, FIXTURE_DAY, schedule=m, mode="standart")
    vs = gated_goal_predictions(stale_eng, strict, fx, AS_OF)[0]
    vd = gated_goal_predictions(stale_eng, std, fx, AS_OF)[0]
    for e in vs.by_market.values():  # sıkı: v2 aynen (T01)
        assert e.freshness == E.KNOWN_STALE and not e.forecast_ok and e.status_label == "Eksik veri"
    for mk, e in vd.by_market.items():
        assert e.freshness == E.KNOWN_STALE and "DEPODA_EKSIK_MAC" in e.reasons
        assert e.forecast_ok and not e.bet_ok and e.status_label == "Uyarılı" and e.lead_code == "DEPODA_EKSIK_MAC"
        label, text = E.display_label(e, E.check_for_display(e, e.candidate_id, mk, AS_OF,
                                                             vd.prediction.state_digest))
        assert label == "Uyarılı · bahis adayı değil: veride eksik maç var (DEPODA_EKSIK_MAC)"
        assert "bahis adayı değil" in text
        assert E.check_for_decision(e, e.candidate_id, mk, AS_OF, vd.prediction.state_digest)[0] == "DEPODA_EKSIK_MAC"
    assert vd.any_usable(AS_OF) and not vs.any_usable(AS_OF)
    from bahis_tahmin.goals.ledger import Ledger
    from bahis_tahmin.goals.service import decisions_for

    decs = decisions_for(vd.prediction, stale_eng, Ledger(":memory:"), AS_OF, eligibility=vd)
    assert decs and all(d.status != "VALUE_CANDIDATE" for d in decs)


def test_short_history_is_bet_only_in_standart(m, eng, teams):
    late = dt.datetime(2027, 3, 15, 12, tzinfo=dt.timezone.utc)  # son lig maçından bir yıldan fazla sonra
    for mode, forecast in (("siki", False), ("standart", True)):
        ctx = full_context(m, eng, AS_OF, FIXTURE_DAY, mode=mode)
        e = one(ctx, teams, as_of=late, day=dt.date(2027, 3, 20))
        assert "TAKIM_GECMISI_YETERSIZ" in e.reasons and e.forecast_ok is forecast and not e.bet_ok


def test_structural_blocks_hold_in_standart_and_label_names_the_real_reason(m, eng, teams):
    no_model = E.EligibilityContext(m, None, rights=synthetic_rights(), mode="standart")
    e = one(no_model, teams)
    # Eskiden başka bir kodun güncelliğinden "Eksik veri · MODEL_YOK" yazılıyordu; standart modda birincil neden
    assert not e.forecast_ok and e.lead_code == "MODEL_YOK" and e.status_label == "Uygun değil"
    ctx = full_context(m, eng, AS_OF, FIXTURE_DAY, mode="standart")
    assert not one(ctx, teams, day=AS_OF.date() - dt.timedelta(days=2)).forecast_ok  # MAC_GECMISTE
    un = ctx.evaluate(league="T1", date=FIXTURE_DAY, home="Foo FC", away="Bar FC", as_of=AS_OF,
                      markets=("FT_OVER_3_5",), mapped=False, raw_home="Foo FC", raw_away="Bar FC",
                      source="openfootball")["FT_OVER_3_5"]
    assert not un.forecast_ok and un.lead_code == "TAKIM_ESLESMEDI"
    lost = one(ctx, teams, pcodes=("TAKIM_GUCU_YOK",))  # gerekli alan yok
    assert not lost.forecast_ok and "GEREKLI_ALAN_EKSIK" in lost.reasons
    same = ctx.evaluate(league="T1", date=FIXTURE_DAY, home=teams[0], away=teams[0], as_of=AS_OF,
                        markets=("FT_OVER_3_5",), prediction_codes=())["FT_OVER_3_5"]
    assert not same.forecast_ok
    # Gerçek kaynak etiketi + yalnızca indirme onayı: hak yok → tahmin yok (her iki modda)
    real = m.assign(source=FD)
    for mode in E.POLICY_MODES:
        c = E.EligibilityContext(real, E.state_view(eng), consent={"football-data": "t"}, mode=mode)
        r = one(c, teams)
        assert not r.forecast_ok and "KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI" in r.reasons


# ====================================================================== 1) kişisel kullanım beyanı
def test_declaration_opens_only_the_declarable_scope_and_registry_stays_truthful():
    consent = {"football-data": "t", "github-mirror": "t"}
    plain = E.rights_from_registry({FD, MIRROR}, consent)
    decl = E.rights_from_registry({FD, MIRROR}, consent, declarations={"football-data": "t"})
    assert plain.codes({FD}, {FD}) and plain.by_label[FD].beyan == "YOK"
    u = decl.by_label[FD]
    assert u.beyan == "VAR" and (u.sonuc_kullanimi, u.model_egitimi, u.model_kullanimi) == ("KULLANICI_BEYANI",) * 3
    assert u.ticari_kullanim == "DOGRULANAMADI" and u.yeniden_dagitim == "IZIN_VARSAYILMAZ"
    assert u.erisim_kosullari == "DOGRULANAMADI"
    assert decl.codes({FD}, {FD}, "tahmin") == [] and decl.codes({FD}, (), "egitim") == []
    # Beyan kaynak başınadır: yedek veri setinin beyanı yoksa onun satırları yine engellenir
    assert "KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI" in decl.codes({FD, MIRROR}, {FD})
    # Onaysız beyan geçmez (erişim yok; alanlar açılmaz)
    no_access = E.rights_from_registry({FD}, {}, declarations={"football-data": "t"}).by_label[FD]
    assert no_access.beyan == "YOK" and no_access.sonuc_kullanimi == "DOGRULANAMADI"
    # Beyan verilemeyen / bilinmeyen / kökeni doğrulanmayan kaynaklar beyanla hak kazanmaz
    other = E.rights_from_registry({"football-datasets", "statsbomb-acik", "uydurma", "openfootball-sonuc"},
                                   {k: "t" for k in R.SOURCES},
                                   declarations={k: "t" for k in R.SOURCES})
    assert other.codes({"football-datasets"}, ()) and other.codes({"uydurma"}, ()) == ["KAYNAK_HAKKI_BILINMIYOR"]
    assert other.by_label["statsbomb-acik"].model_egitimi == "DOGRULANAMADI"
    assert "KAYNAK_KOKENI_DOGRULANAMADI" in other.codes({"openfootball-sonuc"}, ())
    # Kaynak kaydı (belge durumu) değişmez; beyan verilebilen kaynaklar yalnızca bu ikisi
    assert R.DECLARABLE == ("football-data", "github-mirror")
    for k in R.DECLARABLE:
        assert R.USE_RIGHTS[k]["belge"] == "" and "IZINLI_BELGELI" not in R.USE_RIGHTS[k].values()
    assert R.effective_declarations({"football-data": "t"}, {"football-data": "t", "github-mirror": "t"}) == {
        "football-data"}


def test_training_rights_need_a_declaration_for_every_result_source(m):
    mixed = pd.concat([m.assign(source=FD), m.head(5).assign(source=MIRROR)])
    consent = {"football-data": "t", "github-mirror": "t"}
    assert E.training_rights_codes(mixed, consent) == ["KAYNAK_EGITIM_HAKKI_DOGRULANAMADI",
                                                      "KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI"]
    assert E.training_rights_codes(mixed, consent, declarations={"football-data": "t"})
    assert E.training_rights_codes(mixed, consent, declarations={"football-data": "t", "github-mirror": "t"}) == []
    assert E.training_rights_codes(mixed, {}, declarations={"football-data": "t", "github-mirror": "t"})


def test_declaration_revocation_blocks_a_previously_trained_model(m, eng, teams):
    real = m.assign(source=FD)
    sv = dataclasses.replace(E.state_view(eng), train_sources=(FD,))
    consent = {"football-data": "t"}
    ok = E.EligibilityContext(real, sv, consent=consent, declarations={"football-data": "t"}, mode="standart")
    gone = E.EligibilityContext(real, sv, consent=consent, mode="standart")
    assert ok.fingerprint != gone.fingerprint
    e_ok, e_gone = one(ok, teams), one(gone, teams)
    assert e_ok.forecast_ok and e_ok.source_use[FD]["beyan"] == "VAR"
    assert not e_gone.forecast_ok and "KAYNAK_MODEL_KULLANIMI_DOGRULANAMADI" in e_gone.reasons


def test_settings_are_backward_compatible_and_validated(tmp_home):
    from bahis_tahmin.config import Settings

    (tmp_home / "settings.json").write_text(json.dumps({"source_consent": {"football-data": "2026-01-01T00:00:00"}}),
                                            encoding="utf-8")
    s = Settings.load()
    assert s.kisisel_kullanim == {} and s.onay_surumu == 0 and s.veri_denetimi == "standart"
    assert s.declarations() == {}
    (tmp_home / "settings.json").write_text(json.dumps({
        "source_consent": {"football-data": "t"}, "kisisel_kullanim": {"football-data": "t", "github-mirror": "t",
                                                                       "statsbomb-acik": "t", "x": 1},
        "onay_surumu": "bozuk", "veri_denetimi": "gevsek"}), encoding="utf-8")
    s = Settings.load()
    assert s.kisisel_kullanim == {"football-data": "t", "github-mirror": "t"}  # beyan verilemeyenler atılır
    assert s.declarations() == {"football-data": "t"}  # onayı olmayan kaynağın beyanı geçmez
    assert s.onay_surumu == 0 and s.veri_denetimi == "standart"
    s.veri_denetimi = "siki"
    s.save()
    assert Settings.load().veri_denetimi == "siki"


# ---------------------------------------------------------------------- arayüz ve CLI yolları
@pytest.fixture(scope="module")
def qapp():
    QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_consent_dialog_declaration_requires_download_consent(qapp):
    from bahis_tahmin.ui.consent import ConsentDialog

    dlg = ConsentDialog({}, None, {"football-data": "t"})
    box, decl = dlg.boxes["football-data"], dlg.decl_boxes["football-data"]
    assert set(dlg.decl_boxes) == set(R.DECLARABLE)
    assert not box.isChecked() and not decl.isEnabled() and not decl.isChecked()  # onaysız eski beyan işaretli gelmez
    box.setChecked(True)
    assert decl.isEnabled() and not decl.isChecked()
    decl.setChecked(True)
    assert dlg.declared() == ["football-data"]
    box.setChecked(False)
    assert not decl.isChecked() and not decl.isEnabled() and dlg.declared() == []
    dlg.close()


def test_old_consent_asks_once_and_declaration_is_recorded(qapp, tmp_home):
    from bahis_tahmin.ui.consent import apply_consent
    from bahis_tahmin.ui.controller import AppController

    ctl = AppController()
    ctl.settings.source_consent = {"football-data": "2026-01-01T00:00:00"}  # VERI-01 öncesi onay
    assert ctl.needs_consent()  # pencere bir kez yeniden gösterilir (beyan yeni)
    keys = ["football-data", "github-mirror"]
    assert apply_consent(ctl, ["football-data"], [], keys) is False  # beyansız kaydetmek de yeterli: bir daha sorulmaz
    assert not ctl.needs_consent() and ctl.settings.declarations() == {}
    assert apply_consent(ctl, ["football-data", "github-mirror"], keys, keys) is True
    assert set(ctl.settings.declarations()) == set(keys)
    ctl.revoke_consent("github-mirror")  # onay geri alınınca beyan da kalkar
    assert set(ctl.settings.declarations()) == {"football-data"}
    ctl.revoke_declaration("football-data")
    assert ctl.settings.declarations() == {}


def test_controller_context_follows_declaration_and_mode(qapp, m, eng, tmp_home):
    from bahis_tahmin.data.store import DataStore
    from bahis_tahmin.ui.controller import AppController

    ctl = AppController()
    st = DataStore(tmp_home)
    st.matches = m.assign(source=FD)
    ctl.store = st
    ctl.settings.source_consent = {"football-data": "t"}
    c1 = ctl.eligibility_context(eng)
    assert c1.mode == "standart" and c1.rights.by_label[FD].beyan == "YOK"
    ctl.record_declaration(["football-data"])
    c2 = ctl.eligibility_context(eng)
    assert c2 is not c1 and c2.rights.by_label[FD].beyan == "VAR"
    ctl.settings.veri_denetimi = "siki"
    c3 = ctl.eligibility_context(eng)
    assert c3 is not c2 and c3.mode == "siki" and c3.policy_version == E.POLICY_VERSION


def test_update_flow_trains_and_shows_predictions_after_declaration(qapp, tmp_home, monkeypatch):
    """Kullanıcının akışı (ağsız): onay + beyan → 'Verileri Güncelle' → model eğitilir → yaklaşan maçlarda olasılık.
    Aynı akış beyansız: eğitim yapılmaz, nedeni ve beyan yolu yazılır."""
    from bahis_tahmin.data.store import DataStore, UpdateReport
    from bahis_tahmin.ui.consent import apply_consent
    from bahis_tahmin.ui.controller import AppController

    data = recent_synthetic(n_seasons=4).assign(source=MIRROR)
    names = sorted(set(data["home"]))
    fx = pd.DataFrame([{"league": "T1", "date": pd.Timestamp(FIXTURE_DAY), "time": "19:00", "home": names[2 * i],
                        "away": names[2 * i + 1], "source": "SENTETIK-FIKSTUR"} for i in range(3)])

    def fake_update(self, leagues, years_back, **kw):
        self.matches, self.fixtures = data.copy(), fx.reindex(columns=self.fixtures.columns)
        self.meta["updated_at"] = "2026-11-01T12:00:00"
        self.save()
        return UpdateReport(n_matches=len(data), n_fixtures=len(fx))

    monkeypatch.setattr(DataStore, "update", fake_update)
    keys = ["football-data", "github-mirror"]

    def run(declared):
        ctl = AppController()
        ctl.clock = lambda: AS_OF
        msgs = []
        ctl.message.connect(lambda k, t: msgs.append((k, t)))
        apply_consent(ctl, keys, declared, keys)
        assert not ctl.needs_consent() and ctl.update_and_train()
        while ctl.busy or ctl._queue:
            qapp.processEvents()
            ctl.wait()
        qapp.processEvents()
        return ctl, msgs

    ctl, msgs = run([])
    assert ctl.engine is None and ctl.goal_engine is None
    popup = next(t for k, t in msgs if k == "popup")
    assert "Model eğitimi yapılmadı" in popup and "kişisel" in popup.lower()
    df = ctl.prediction_frame()
    assert len(df) == 3 and df["p1"].isna().all() and df["veri"].str.contains("MODEL_YOK").all()

    ctl, msgs = run(keys)
    assert ctl.engine is not None and ctl.engine.trained
    df = ctl.prediction_frame()
    assert len(df) == 3 and df["p1"].notna().all(), df[["home", "away", "veri", "veri_neden"]].to_string()
    assert not df["veri"].str.contains("MODEL_YOK|DOGRULANAMADI").any()
    assert (df[["p1", "px", "p2"]].sum(axis=1) - 1).abs().max() < 1e-6


def test_cli_declaration_flags(tmp_home, monkeypatch, capsys):
    from bahis_tahmin import cli
    from bahis_tahmin.config import Settings
    from bahis_tahmin.data.store import DataStore, UpdateReport

    monkeypatch.setattr(DataStore, "update", lambda self, *a, **k: UpdateReport())
    assert cli.main(["update", "--kisisel-kullanim", "football-data"]) == 2  # indirme onayı yok
    assert "--accept-terms" in capsys.readouterr().err
    assert cli.main(["update", "--accept-terms", "football-data", "--kisisel-kullanim", "statsbomb-acik"]) == 2
    cli.main(["update", "--accept-terms", "football-data", "--kisisel-kullanim", "football-data",
              "--veri-denetimi", "siki"])
    s = Settings.load()
    assert s.declarations().keys() == {"football-data"} and s.veri_denetimi == "siki"
    assert s.onay_surumu == R.CONSENT_SCHEMA and "ticari olmayan" in capsys.readouterr().out
    cli.main(["update", "--kisisel-kullanim-geri-al", "football-data"])
    assert Settings.load().declarations() == {}
    # İleriye dönük ölçüm kaydı v2 protokolüne bağlıdır: ayarlar ne olursa olsun sıkı mod ve beyansız haklar
    s = Settings.load()
    s.kisisel_kullanim = {"football-data": "t"}
    s.veri_denetimi = "standart"
    s.save()
    st = DataStore(tmp_home)
    st.matches = recent_synthetic(n_seasons=2).assign(source=FD)
    strict = cli._eligibility_ctx(st, None, strict=True)
    normal = cli._eligibility_ctx(st, None)
    assert strict.mode == "siki" and strict.rights.by_label[FD].beyan == "YOK"
    assert normal.mode == "standart" and normal.rights.by_label[FD].beyan == "VAR"


# ====================================================================== 2) takım adları
@pytest.mark.parametrize("league,raw,fd,known", [
    ("E0", "Coventry City FC", "Coventry", ["Arsenal", "Coventry", "Hull"]),
    ("E1", "Preston North End FC", "Preston", ["Preston", "Stoke", "Derby"]),
    ("SP1", "Real Betis Balompié", "Betis", ["Betis", "Barcelona", "Sevilla"]),
    ("SP1", "Real Racing Club de Santander", "Santander", ["Santander", "Osasuna"]),
    ("I1", "Atalanta BC", "Atalanta", ["Atalanta", "Milan"]),
    ("D1", "SV 07 Elversberg", "Elversberg", ["Elversberg", "Augsburg"]),
    ("F1", "ES Troyes AC", "Troyes", ["Troyes", "Lens"]),
    ("N1", "FC Twente '65", "Twente", ["Twente", "Utrecht"]),
    ("N1", "AZ", "AZ Alkmaar", ["AZ Alkmaar", "PSV Eindhoven"]),
    ("P1", "Sporting Clube de Braga", "Sp Braga", ["Sp Braga", "Sp Lisbon"]),
])
def test_verified_aliases_resolve_unmatched_fixture_names(league, raw, fd, known):
    from bahis_tahmin.data.teams import KESIN, resolve_team

    r = resolve_team(raw, known, league, "openfootball")
    assert r.status == KESIN and r.team == fd and r.basis == "takma_ad"


def test_alias_scope_and_spelling_only_target():
    from bahis_tahmin.data.teams import match_team, resolve_teams, spelling_key

    assert match_team("Coventry City FC", ["Coventry"], "SC0", "openfootball") is None  # başka ülke
    assert match_team("Coventry City FC", ["Coventry"], "E1", "football-data") is None  # başka kaynak
    # Hedef adın yalnızca yazımı farklı tek karşılığı kabul edilir; yazım anahtarı ad parçası atmaz
    assert match_team("Nottingham Forest FC", ["Nottm Forest", "Arsenal"], "E0", "openfootball") == "Nottm Forest"
    assert spelling_key("Preußen Münster") == spelling_key("Preussen Munster") != spelling_key("Preussen")
    # Ters çakışma kuralı korunur: aynı dosyada iki farklı ad aynı takıma takma adla düşebilir (aynı kulüp)
    res = resolve_teams(["GD Estoril", "GD Estoril Praia"], ["Estoril", "Porto"], "P1", "openfootball")
    assert {r.team for r in res.values()} == {"Estoril"}


def test_spelling_variants_are_unified_per_country_and_fixtures_follow(tmp_home):
    from bahis_tahmin.data.store import _spelling_index, unify_spellings

    rows = [("E0", "2022-01-01", "Nottm Forest", "Arsenal", MIRROR), ("E0", "2025-01-01", "Nott'm Forest", "Arsenal",
                                                                      MIRROR),
            ("E1", "2024-01-01", "Arsenal", "Nottm Forest", FD), ("SC0", "2024-01-01", "Nottm Forest", "Celtic", MIRROR),
            ("E0", "2024-02-01", "Nottm Forest", "Leeds", "openfootball-sonuc")]
    m = pd.DataFrame(rows, columns=["league", "date", "home", "away", "source"])
    m["date"] = pd.to_datetime(m["date"])
    out, ren = unify_spellings(m)
    assert ren == {("İngiltere", "Nottm Forest"): "Nott'm Forest"}
    assert out.loc[0, "home"] == out.loc[2, "away"] == "Nott'm Forest"
    assert out.loc[3, "home"] == "Nottm Forest"  # başka ülke (tek yazım) dokunulmaz
    assert out.loc[4, "home"] == "Nottm Forest"  # kökeni dosyayla doğrulanan satır değişmez
    idx = _spelling_index(out)
    assert idx[("İngiltere", "nottmforest")] == "Nott'm Forest"
    same, none = unify_spellings(m[m["league"] == "SC0"])
    assert none == {} and same is not None


# ====================================================================== bağımsız inceleme bulguları (regresyon)
def test_alias_prefers_exact_target_when_both_spellings_exist():
    from bahis_tahmin.data.teams import match_team

    both = ["Nott'm Forest", "Nottm Forest", "Arsenal"]  # birleştirilmemiş eski bağlam (ör. arşiv)
    assert match_team("Nottingham Forest FC", both, "E0", "openfootball") == "Nott'm Forest"


def test_store_load_unifies_old_spellings_and_signature_sees_names(tmp_home):
    from bahis_tahmin.data.store import DataStore
    from bahis_tahmin.models.engine import PredictionEngine

    m = recent_synthetic(n_seasons=2).assign(source=MIRROR)
    t = sorted(set(m["home"]))[0]
    old = m.copy()
    first = old.index[(old["home"] == t) | (old["away"] == t)][:5]
    for col in ("home", "away"):  # eski yazım (ör. "Nottm Forest") yalnızca ilk maçlarda
        old.loc[first, col] = old.loc[first, col].where(old.loc[first, col] != t, t.upper())
    st = DataStore(tmp_home)
    st.matches = old
    st.fixtures = pd.DataFrame([{"league": "T1", "date": pd.Timestamp(FIXTURE_DAY), "time": "", "home": t.upper(),
                                 "away": "X", "source": "x"}]).reindex(columns=st.fixtures.columns)
    st.save()
    st2 = DataStore(tmp_home)
    assert st2.load()
    assert t.upper() not in set(st2.matches["home"]) | set(st2.matches["away"])
    assert st2.fixtures.loc[0, "home"] == t
    assert PredictionEngine.signature(st2.matches) != PredictionEngine.signature(old)  # yeniden eğitim gerekir


def test_sequence_research_alias_hash_survives_unification():
    from bahis_tahmin.sequences.aliases import EXPECTED_SPLITS, AliasMap

    rows = [("D1", "2024/25", "2024-08-20", "M'gladbach", "Bayern Munich"),
            ("E0", "2024/25", "2024-08-20", "Nott'm Forest", "Arsenal"),
            ("D2", "2024/25", "2024-08-20", "Preußen Münster", "Hamburg")]
    m = pd.DataFrame(rows, columns=["league", "season", "date", "home", "away"])
    m["date"] = pd.to_datetime(m["date"])
    assert AliasMap.from_matches(m).splits == {k: v for k, v in EXPECTED_SPLITS.items()}


def test_cli_declaration_is_all_or_nothing_and_hint_names_missing_sources(tmp_home, monkeypatch, capsys):
    from bahis_tahmin import cli
    from bahis_tahmin.config import Settings
    from bahis_tahmin.data.store import DataStore, UpdateReport

    monkeypatch.setattr(DataStore, "update", lambda self, *a, **k: UpdateReport())
    assert cli.main(["update", "--accept-terms", "football-data", "--kisisel-kullanim",
                     "football-data,github-mirror"]) == 2  # ikinci anahtarın onayı yok
    assert "kaydedildi" not in capsys.readouterr().out
    assert Settings.load().kisisel_kullanim == {}
    st = DataStore(tmp_home)
    st.matches = recent_synthetic(n_seasons=2).assign(source=MIRROR)
    assert cli._training_blocked(st)
    err = capsys.readouterr().err
    assert "--accept-terms github-mirror --kisisel-kullanim github-mirror" in err and "football-data" not in err


def test_goals_panel_is_reset_when_mode_or_declaration_changes(qapp, tmp_home):
    from bahis_tahmin.ui.controller import AppController
    from bahis_tahmin.ui.pages.goals import GoalsPage

    ctl = AppController()
    page = GoalsPage(ctl)
    page._current_verdict, page._verdict_key = object(), page._policy_key()
    page._current = object()
    ctl.settings.veri_denetimi = "siki"
    ctl.settingsChanged.emit()
    assert page._current is None and page._current_verdict is None and not page._panel_valid()
    page._current_verdict, page._verdict_key, page._current = object(), page._policy_key(), object()
    ctl.settings.source_consent["football-data"] = "t"
    ctl.record_declaration(["football-data"])  # settingsChanged yayar
    assert page._current is None
    status = dict(zip(page.src_model.frame["Kaynak"], page.src_model.frame["Durum"]))
    assert status["football-data.co.uk"] == "Kullanıcı onayladı + kişisel kullanım beyanı"
    page.close()


def test_declaration_change_queues_a_single_conditional_retrain(qapp, tmp_home, monkeypatch):
    from bahis_tahmin.ui.controller import AppController

    ctl = AppController()
    ctl.store.matches = recent_synthetic(n_seasons=2).assign(source=MIRROR)
    calls = []
    monkeypatch.setattr(ctl, "retrain", lambda: calls.append(1) or True)
    ctl.engine = None
    ctl.declarations_changed(added=True)
    assert calls == [1]
    # Süren bir iş varken: koşul iş bittikten sonra yeniden denetlenir (iş modeli zaten eğittiyse ikinci eğitim yok)
    calls.clear()
    ctl._task = object()
    ctl.declarations_changed(added=True)
    assert calls == [] and ctl._queue
    ctl._task = None
    monkeypatch.setattr(ctl, "needs_training", lambda: False)
    ctl.engine = object()
    while ctl._queue:
        ctl._queue.pop(0)()
    assert calls == []
