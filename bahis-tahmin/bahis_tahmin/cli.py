"""Komut satırı arayüzü (arayüzsüz kullanım ve otomatik testler için).

Örnekler:
    python -m bahis_tahmin                      # masaüstü uygulaması
    python -m bahis_tahmin update --leagues T1,E0 --years 5
    python -m bahis_tahmin train
    python -m bahis_tahmin predict --league T1
    python -m bahis_tahmin en-olasi --threshold 0.9
    python -m bahis_tahmin backtest --odds max --min-ev 0.05
    python -m bahis_tahmin self-test
    python -m bahis_tahmin gol-egit                 # gol pazarları modeli (A/B/C) eğitimi + iç doğrulama
    python -m bahis_tahmin gol-tahmin --league E0   # yaklaşan maçlar için A/B/C olasılıkları
    python -m bahis_tahmin gol-kapsam --csv kapsam.csv
    python -m bahis_tahmin gol-sanal                # sanal takip özeti ve kayıt zinciri doğrulaması
    python -m bahis_tahmin gol-oran-ice-aktar --csv oranlar.csv            # yalnızca doğrulama
    python -m bahis_tahmin gol-oran-ice-aktar --csv oranlar.csv --uygula   # doğrulananları ekle
    python -m bahis_tahmin dizi-olay --takim "PSV Eindhoven" --iyms 2/1    # geçmiş inceleme (olay seçimli)
    python -m bahis_tahmin dizi-arastir --isci 3                           # ön-kayıtlı dizi araştırması
    python -m bahis_tahmin dizi-benzer --takim "PSV Eindhoven"             # maç öncesi benzer diziler
"""

from __future__ import annotations

import argparse
import sys
import time

from .config import Settings, app_home
from .data.leagues import LEAGUES, league_name

ENGINE_FILE = "engine.joblib"
GOAL_ENGINE_FILE = "goal_engine.joblib"
LEDGER_FILE = "gol_pazarlari.sqlite"


def _store():
    from .data.store import DataStore

    st = DataStore(app_home())
    st.load()
    return st


def _engine():
    from .models.engine import PredictionEngine

    eng = PredictionEngine.load(app_home() / ENGINE_FILE)
    if eng is None:
        print("Model bulunamadı. Önce 'update' ve 'train' komutlarını çalıştırın.", file=sys.stderr)
        sys.exit(2)
    return eng


def _progress(p: int, msg: str) -> None:
    print(f"[{p:3d}%] {msg}", flush=True)


def _eligibility_ctx(st, eng):
    """Ortak veri uygunluk bağlamı (veri deposu + motor durumu + önbellekteki kaynak takvimleri + kayıtlı haklar).

    Kullanıcı onayı yalnızca kaynak ERİŞİMİNİ kapsar; komut satırında uygunluğu atlatan bir bayrak yoktur."""
    from .eligibility import build_context
    from .timeutil import ISTANBUL

    return build_context(st, eng, Settings.load().source_consent, today=_now_utc().astimezone(ISTANBUL).date())


def _now_utc():
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc)


def _training_blocked(st) -> bool:
    """Gerçek veriyle model eğitimi hak kapsamı (S3-GATE-02): eğitim verisinin kaynaklarında sonuç kullanımı ve model
    eğitimi hakkı belgeli değilse eğitim yapılmaz. Onay veya bayrak bu kontrolü aşamaz."""
    from .data.provenance import verified_labels
    from .eligibility import reason_texts, training_rights_codes

    codes = training_rights_codes(st.matches, Settings.load().source_consent, verified_labels(st))
    if codes:
        print("Model eğitimi yapılmadı (veri kaynağının kullanım kapsamı doğrulanmadı): " + reason_texts(codes),
              file=sys.stderr)
    return bool(codes)


def _blocked_line(e) -> str:
    return f"TAHMİN YOK — {e.short_text()}" if e is not None else "TAHMİN YOK — uygunluk değerlendirilmedi"


def cmd_update(a) -> int:
    from .data.store import DataStore

    s = Settings.load()
    if a.leagues:
        s.leagues = [c.strip().upper() for c in a.leagues.split(",") if c.strip().upper() in LEAGUES]
    if a.years:
        s.years_back = a.years
    if a.accept_terms:
        import datetime as dt

        from .data.source_registry import SOURCES

        for key in a.accept_terms.split(","):
            key = key.strip()
            if key not in SOURCES:
                print(f"Bilinmeyen kaynak: {key}", file=sys.stderr)
                return 2
            print(f"{SOURCES[key].name} kullanım koşulları onaylandı ({SOURCES[key].terms_url}).")
            s.source_consent[key] = dt.datetime.now().isoformat(timespec="seconds")
    s.save()
    if not ({"football-data", "github-mirror"} & s.allowed_sources()):
        print("Geçmiş veri kaynaklarının kullanım koşulları onaylanmadı. Koşulları okuyup onaylamak için:\n"
              "  python -m bahis_tahmin update --accept-terms football-data[,github-mirror]", file=sys.stderr)
        return 3
    st = DataStore(app_home())
    st.load()
    rep = st.update(s.leagues, s.years_back, progress=_progress, force=a.force,
                    use_mirror_fallback=not a.no_mirror, fixture_days=s.fixture_days,
                    allowed=s.allowed_sources())
    print(rep.summary())
    print(st.summary().to_string(index=False))
    return 0 if st.has_data else 1


def cmd_train(a) -> int:
    from .models.engine import PredictionEngine

    st = _store()
    if not st.has_data:
        print("Veri yok. Önce 'update' çalıştırın.", file=sys.stderr)
        return 2
    if _training_blocked(st):
        return 3
    s = Settings.load()
    eng = PredictionEngine()
    t = time.time()
    rep = eng.train(st.matches, progress=_progress, margin_method=s.margin_method)
    eng.save(app_home() / ENGINE_FILE)
    m = rep.metrics
    print(f"Eğitim {time.time() - t:.0f} sn sürdü. {rep.n_matches} maç, {m.get('n', 0)} örneklem dışı tahmin.")
    print(f"1X2 isabeti: model %{100 * m.get('acc_model', 0):.1f} · piyasa %{100 * m.get('acc_market', 0):.1f} · "
          f"nihai %{100 * m.get('acc_final', 0):.1f}")
    print(f"Log-kayıp: model {m.get('ll_model', 0):.4f} · piyasa {m.get('ll_market', 0):.4f} · "
          f"nihai {m.get('ll_final', 0):.4f} · sabit tahmin {m.get('ll_baseline', 0):.4f}")
    for r in rep.confidence.get("best", []):
        if r["n"]:
            print(f"  olasılık ≥ %{100 * r['esik']:.0f}: gerçekleşme %{100 * r['isabet']:.1f}, kapsam %{100 * r['kapsam']:.1f} ({r['n']} seçim)")
    return 0


def cmd_predict(a) -> int:
    st = _store()
    eng = _engine()
    s = Settings.load()
    from .eligibility import gated_match_predictions

    fx = st.fixtures
    un = st.unmatched_fixtures
    if a.league:
        fx = fx[fx["league"] == a.league.upper()]
        un = un[un["league"] == a.league.upper()]
    preds, missing = gated_match_predictions(eng, _eligibility_ctx(st, eng), fx, _now_utc(), s.odds_type, un)
    if not preds and not missing:
        print("Yaklaşan maç bulunamadı.")
        return 0
    now = _now_utc()
    for p in preds[: a.top]:
        head = f"{p.date:%d.%m} {p.time:5s} {p.league:4s} {p.home:>18s} - {p.away:<18s} "
        if not p.forecast_ok_at(now):
            print(head + _blocked_line(p.eligibility))
            continue
        best = p.best_value(s, now=now)
        block = p.data_block(now)
        val = f"  DEĞER: {best['label']} @{best['odds']:.2f} ({100 * best['ev']:+.0f}%)" if best else ""
        gate = "" if (best or not block) else f"  (bahis/değer önerisi yok: {', '.join(block)})"
        print(head + f"1:%{100 * p.p_final[0]:4.1f} X:%{100 * p.p_final[1]:4.1f} 2:%{100 * p.p_final[2]:4.1f} "
              f"Ü2.5:%{100 * p.markets['O2.5']:4.1f} KG:%{100 * p.markets['BTTS_Y']:4.1f}{val}{gate}")
    for v in missing:
        tag = "" if v.canonical_id else f" [aday kimlik {v.candidate_id}, kanonik değil]"
        print(f"{v.date:%d.%m} {v.time:5s} {v.league:4s} {v.home:>18s} - {v.away:<18s} {_blocked_line(v.first())}{tag}")
    return 0


def cmd_likely(a) -> int:
    from .models.engine import MARKET_GROUPS, verify_selection
    from .models.markets import MARKETS

    st = _store()
    eng = _engine()
    keys = [k for g in MARKET_GROUPS.values() for k in g]
    v = verify_selection(eng.oos, keys, a.threshold, True)
    if v["n"]:
        print(f"Geçmiş doğrulama (olasılık ≥ %{100 * a.threshold:.0f}): gerçekleşme %{100 * v['isabet']:.1f}, "
              f"{v['n']} seçim, maçların %{100 * v['kapsam']:.1f}'i")
    from .eligibility import gated_match_predictions

    preds, missing = gated_match_predictions(eng, _eligibility_ctx(st, eng), st.fixtures, _now_utc(),
                                             Settings.load().odds_type, st.unmatched_fixtures)
    now = _now_utc()
    blocked = [p for p in preds if not p.forecast_ok_at(now)]
    if blocked or missing:
        print(f"Veri uygunluğu doğrulanmadığı için listelenmeyen maç: {len(blocked) + len(missing)} "
              "(ayrıntı: predict komutu).")
    for p in preds:
        if not p.forecast_ok_at(now):
            continue
        k, prob = max(((k, p.markets[k]) for k in keys), key=lambda kv: kv[1])
        if prob >= a.threshold:
            print(f"{p.date:%d.%m} {league_name(p.league):28s} {p.home} - {p.away}: {MARKETS[k][0]} "
                  f"(%{100 * prob:.1f}, adil oran {1 / prob:.2f})")
    return 0


def cmd_backtest(a) -> int:
    from .betting.backtest import BacktestConfig, run_backtest

    eng = _engine()
    cfg = BacktestConfig(odds_type=a.odds, min_ev=a.min_ev, prob_source=a.source)
    r = run_backtest(eng.oos, cfg)
    for k, v in r.summary.items():
        print(f"{k:14s}: {v:.4f}" if isinstance(v, float) else f"{k:14s}: {v}")
    if not r.by_season.empty:
        print(r.by_season.to_string(index=False))
    return 0


def cmd_goal_train(a) -> int:
    from .goals.engine import GoalDataError, GoalEngine
    from .goals.markets import MARKETS, PRIMARY_YES

    st = _store()
    if not st.has_data:
        print("Veri yok. Önce 'update' çalıştırın.", file=sys.stderr)
        return 2
    if _training_blocked(st):
        return 3
    eng = GoalEngine()
    t = time.time()
    try:
        val = eng.train(st.matches, progress=_progress)
    except GoalDataError as e:
        print(str(e), file=sys.stderr)
        return 2
    eng.save(app_home() / GOAL_ENGINE_FILE)
    print(f"Eğitim {time.time() - t:.0f} sn. Model {eng.variant}; veri kesimi {eng.data_cutoff}; "
          f"iç doğrulama sezonları: {', '.join(str(y) for y in eng.validation_years) or '-'}")
    for key in PRIMARY_YES:
        r = val.get(key, {})
        mm = r.get("modeller", {}).get(eng.variant)
        if not mm:
            print(f"  {MARKETS[key].name_tr}: doğrulama yapılamadı → {eng.status_text(key)}")
            continue
        print(f"  {MARKETS[key].name_tr}: n={r['n']} taban=%{100 * r['taban_oran']:.1f} "
              f"ΔLL={mm['ll_fark_ref']:+.5f} [{mm['ll_fark_alt']:+.5f}, {mm['ll_fark_ust']:+.5f}] "
              f"eğim={mm['kal_egim']:.2f} ECE={mm['ece']:.4f} → {eng.status_text(key)}")
    return 0


def _goal_engine():
    from .goals.engine import GoalEngine

    eng, err = GoalEngine.load(app_home() / GOAL_ENGINE_FILE)
    if eng is None:
        print(f"Gol modeli yüklenemedi ({err}). Önce 'gol-egit' çalıştırın.", file=sys.stderr)
        sys.exit(2)
    return eng


def cmd_goal_predict(a) -> int:
    from .goals.service import gated_goal_predictions

    eng = _goal_engine()
    store = _store()
    fx, un = store.fixtures, store.unmatched_fixtures
    if a.league:
        fx = fx[fx["league"] == a.league.upper()]
        un = un[un["league"] == a.league.upper()]
    now = _now_utc()
    verdicts = gated_goal_predictions(eng, _eligibility_ctx(store, eng), fx, now, unmatched=un)
    if not verdicts:
        print("Yaklaşan maç bulunamadı.")
        return 0
    st = {k: ("doğrulandı" if v else "DOĞRULANMADI") for k, v in eng.validated.items()}
    print(f"Model durumu: A {st.get('BTTS_BOTH_HALVES_YES')} · B {st.get('FT_OVER_3_5')} · C {st.get('FH_OVER_1_5')}. "
          "Gerçek oran olmadan öneri üretilmez. Olasılık yalnızca veri uygunluğu doğrulanan pazarlarda gösterilir.")
    for v in verdicts:
        p = v.prediction
        when = p.kickoff_text if p is not None else f"{v.date:%d.%m.%Y}"
        head = f"{when:>28s} {v.league:4s} {v.home:>18s} - {v.away:<18s} "
        if p is None or not v.any_usable(now):
            tag = "" if v.canonical_id else f" [aday kimlik {v.candidate_id}, kanonik değil]"
            print(head + _blocked_line(v.first()) + tag)
            continue
        parts = []
        for s_, k in (("A", "BTTS_BOTH_HALVES_YES"), ("B", "FT_OVER_3_5"), ("C", "FH_OVER_1_5")):
            if not v.usable(k, now):
                parts.append(f"{s_}:yok({v.display_codes(k, now)[0]})")
                continue
            lo, hi = p.interval(k)
            parts.append(f"{s_}:%{100 * p.probs[s_]:4.1f} [{100 * lo:.0f}-{100 * hi:.0f}]" if lo is not None
                         else f"{s_}:%{100 * p.probs[s_]:4.1f}")
        e0 = v.first()
        note = "" if (e0 is not None and e0.bet_ok) else f"  (bahis adayı değil: {e0.lead_code if e0 else 'BAGLAM_YOK'})"
        print(head + " ".join(parts) + note)
    return 0


def _forecast_inputs():
    """Ölçüm kaydı girdileri: veri deposu, gol motoru (yüklenebiliyorsa), fikstür kaynaklarının hak durumu metni.

    Veri uygunluğu (v2) ortak kontrolden gelir; önbellekteki openfootball dosyaları bağlam kurulurken okunur
    (ağ isteği yapılmaz)."""
    from .data.source_registry import allowed_sources
    from .goals.engine import GoalEngine

    st = _store()
    eng, err = GoalEngine.load(app_home() / GOAL_ENGINE_FILE)
    allowed = allowed_sources(Settings.load().source_consent)
    rights = {"openfootball": "CC0 (belgeli: openfootball/football.json LICENSE.md)",
              "football-data.co.uk": ("kullanıcı onayı ile; yeniden kullanım/model eğitimi hakkı belgelenmedi"
                                      if "football-data" in allowed else "onay yok"),
              "manuel": "kullanıcı girdisi"}
    return st, eng, err, rights


def cmd_goal_forecast_log(a) -> int:
    """İleriye dönük ölçüm: yaklaşan maçlar için A/B/C tahmin kayıtları (varsayılan kuru çalıştırma)."""
    from .goals.forecast_log import ACTIVE_PROTOCOL, build_forecast_records, record_forecasts
    from .goals.ledger import Ledger

    st, eng, err, rights = _forecast_inputs()
    if st.fixtures.empty and st.unmatched_fixtures.empty:
        print("Yaklaşan maç (fikstür) yok. Önce 'update' çalıştırın; gerçek fikstür olmadan kayıt üretilmez.")
        return 0
    if eng is None:
        print(f"Gol modeli yüklenemedi ({err}); tüm adaylar MODEL_YOK nedeniyle olasılıksız kaydedilir.")
    led_path = app_home() / LEDGER_FILE
    led = Ledger(led_path) if (a.uygula or led_path.exists()) else None
    recs = build_forecast_records(eng, st.fixtures, st.matches, ledger=led, ctx=_eligibility_ctx(st, eng),
                                  unmatched=st.unmatched_fixtures, source_rights=rights)
    ok = [r for r in recs if r["decision_status"] == "TAHMIN"]
    print(f"Protokol {ACTIVE_PROTOCOL}: {len(recs)} aday kayıt ({len(ok)} tahmin, {len(recs) - len(ok)} tahmin yok).")
    seen = set()
    for r in recs:
        key = r["event_id"]
        if key in seen:
            continue
        seen.add(key)
        neden = "uygun" if r["decision_status"] == "TAHMIN" else ", ".join(r["reasons"][:2])
        print(f"  {r['mac_tarihi']} {r['league']:4s} {r['home']:>18s} - {r['away']:<18s} {neden}")
    if not a.uygula:
        print("Kuru çalıştırma: hiçbir kayıt yazılmadı. Yazmak için --uygula ekleyin (değişmez kayıt).")
        if led is not None:
            led.close()
        return 0
    res = record_forecasts(led, recs)
    led.close()
    print(f"Yazılan: {res['yazilan']} · mükerrer atlanan: {res['atlanan_mukerrer']} · yazma anında geç kalan: {res['gec_kalan']}")
    return 0


def cmd_goal_forecast_eval(a) -> int:
    import json as _json

    from .goals.forecast_log import ACTIVE_PROTOCOL, PROTOCOL_VERSION, evaluate_forecasts, protocol_document
    from .goals.ledger import Ledger

    if a.protokol:
        print(_json.dumps({"etkin_protokol": protocol_document(ACTIVE_PROTOCOL),
                           "dondurulmus_onceki_protokol": protocol_document(PROTOCOL_VERSION)},
                          ensure_ascii=False, indent=1))
        return 0
    path = app_home() / LEDGER_FILE
    if not path.exists():
        print("Henüz kayıt defteri yok; ileriye dönük ölçüm başlamadı.")
        return 0
    led = Ledger(path)
    res = evaluate_forecasts(led)
    ok, msg = led.verify_chain()
    led.close()
    print(f"Zincir: {msg}")
    print(_json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 0 if ok else 3


def cmd_goal_coverage(a) -> int:
    from .goals.coverage import coverage_matrix, coverage_summary

    st = _store()
    if not st.has_data:
        print("Veri yok. Önce 'update' çalıştırın.", file=sys.stderr)
        return 2
    cov = coverage_matrix(st.matches, Settings.load().source_consent, {})
    summ = coverage_summary(cov)
    print(summ.to_string(index=False))
    if a.csv:
        from .goals.value import safe_csv_cell

        cov.map(safe_csv_cell).to_csv(a.csv, index=False, encoding="utf-8-sig")
        print(f"Kapsam matrisi yazıldı: {a.csv}")
    return 0


def cmd_goal_ledger(a) -> int:
    from .goals.ledger import Ledger

    path = app_home() / LEDGER_FILE
    if not path.exists():
        print("Henüz sanal takip kaydı yok.")
        return 0
    led = Ledger(path)
    ok, msg = led.verify_chain()
    s = led.summary()
    led.close()
    y = f"{100 * s['yield']:+.1f}%" if s["yield"] is not None else "hesaplanamıyor"
    print(f"{msg}. {s['kayit']} kayıt · {s['sanal_bahis']} sanal bahis · {s['sonuclanan']} sonuçlandı · "
          f"net {s['net']:+.2f} birim · yield {y}")
    return 0 if ok else 1


def cmd_goal_odds_import(a) -> int:
    """Gerçek oran CSV'si içe aktarma. Varsayılan: yalnızca doğrulama (kuru çalıştırma), hiçbir şey yazılmaz."""
    from pathlib import Path

    from .goals.ledger import Ledger
    from .goals.value import ODDS_CSV_FIELDS, OddsError, parse_odds_csv

    try:
        quotes, bad = parse_odds_csv(Path(a.csv).read_bytes())
    except (OSError, OddsError, UnicodeDecodeError) as e:
        print(f"Dosya okunamadı: {e}", file=sys.stderr)
        print(f"Beklenen sütunlar: {', '.join(ODDS_CSV_FIELDS)}", file=sys.stderr)
        return 2
    print(f"Geçerli oran kaydı: {len(quotes)} · karantina: {len(bad)}")
    for line in bad[:20]:
        print(f"  {line}")
    if not a.uygula:
        print("Kuru çalıştırma: hiçbir kayıt yazılmadı. Yazmak için --uygula ekleyin.")
        return 0
    led = Ledger(app_home() / LEDGER_FILE)
    n = led.add_odds(quotes)
    led.close()
    print(f"{n} yeni oran kaydı eklendi (aynı kayıtlar tekrar eklenmez).")
    return 0


def _seq_table():
    from .sequences.timeline import build_team_matches

    st = _store()
    if not st.has_data:
        print("Veri yok. Önce 'update' çalıştırın.", file=sys.stderr)
        sys.exit(2)
    return build_team_matches(st.matches), st


def cmd_seq_events(a) -> int:
    """Mod A (tanımlayıcı, olay seçimli): bir takımın olayları ve isteğe bağlı olay kartı."""
    from .goals.markets import parse_htft
    from .sequences.timeline import event_card, team_events

    tm, st = _seq_table()
    teams = sorted(tm["team"].unique())
    if a.takim not in teams:
        near = [t for t in teams if a.takim.lower() in t.lower()]
        print(f"Takım bulunamadı: {a.takim}. Benzer: {', '.join(near[:10]) or '-'}", file=sys.stderr)
        return 2
    key = parse_htft(a.iyms) if a.iyms else None
    if a.iyms and key is None:
        print(f"İY/MS kodu anlaşılamadı: {a.iyms} (ör. 2/1, X/1, 0/2)", file=sys.stderr)
        return 2
    ev = team_events(tm, a.takim, target=None if key else a.hedef, htft_key=key)
    print("GEÇMİŞ İNCELEME — olay seçimli, tahmin değil (olay sonrası bilgi içerir).")
    print(f"{a.takim} · {key or a.hedef}: {len(ev)} olay")
    for _, r in ev.iterrows():
        h = bool(r["is_home"])
        iy = f"{int(r['gf_ht'] if h else r['ga_ht'])}-{int(r['ga_ht'] if h else r['gf_ht'])}" if r["htft"] else "?"
        ms = f"{int(r['gf_ft'] if h else r['ga_ft'])}-{int(r['ga_ft'] if h else r['gf_ft'])}"
        gap = "" if r["onceki_olaydan_mac"] != r["onceki_olaydan_mac"] else f"  (önceki olaydan {int(r['onceki_olaydan_mac'])} maç / {int(r['onceki_olaydan_gun'])} gün)"
        if r.get("aralik_durumu"):
            gap += f"  [veri boşluğu: {r['aralik_durumu']}]"
        print(f"  {r['date']:%d.%m.%Y} {r['season']} {'Ev ' if h else 'Dep'} {r['opponent']:<22s} İY {iy}  MS {ms}{gap}")
    tail = ev.attrs.get("censored_tail")
    if tail:
        print(f"Açık (sansürlü) aralık: {tail['acik_aralik_mac']} maç (son maç {tail['son_mac_tarihi']}, neden {tail['bitis_nedeni']}"
              f"{', veri boşluğu: ' + tail['aralik_durumu'] if tail.get('aralik_durumu') else ''}). 'Olmayacak' anlamına gelmez.")
    print("Aralıklar veride gözlenen lig maçı sayısıdır; veri boşluğu işaretli aralıklar gerçek sayıdan farklı olabilir.")
    if a.kart is not None and 0 <= a.kart < len(ev):
        card = event_card(tm, int(ev.index[a.kart]), data_meta=st.meta)
        print(f"\nOlay kartı #{a.kart}: {card['kimlik']}")
        print(f"  EVENT_OUTCOME: {card['EVENT_OUTCOME']}")
        for blk in ("PRE_EVENT", "POST_EVENT", "RAKIP_PRE_EVENT"):
            for name, w in card[blk].items():
                res = " ".join(f"{(m['ht_res'] or '?')}{(m['ft_res'] or '?')}" for m in w["maclar"])
                print(f"  {blk} {name}: {w['durum']}  {res}")
    return 0


def cmd_seq_coverage(a) -> int:
    from .sequences import config as SC
    from .sequences.timeline import coverage_report

    tm, _ = _seq_table()
    cov = coverage_report(tm)
    inc = cov[~cov["tam"]]
    print(f"{len(cov)} lig-sezon; {len(inc)} tanesinde veri boşluğu var (bu sezonlara dokunan pencereler tanımsızdır):")
    print(inc.to_string(index=False))
    print("\nİncelenemeyenler (DATA_QUALITY_BLOCKED):")
    for k, v in SC.DATA_QUALITY_BLOCKED_ITEMS.items():
        print(f"  {k}: {v}")
    print(f"Hükmen olabilir satır: {tm.attrs.get('n_awarded')} · sezon ortası ad ayrılmaları: {tm.attrs.get('intra_season_splits')}")
    return 0


def cmd_seq_research(a) -> int:
    """Ön-kayıtlı dizi araştırması (sözleşme dizi-sozlesme-v2): F1–F7 + anomali; sonuçlar uygulama klasörüne."""
    import pandas as pd

    from .sequences import config as SC
    from .sequences.research import load_or_build_s0, run_research

    st = _store()
    if not st.has_data:
        print("Veri yok. Önce 'update' çalıştırın.", file=sys.stderr)
        return 2
    out = app_home() / "dizi_arastirma"
    fams = [f.strip().upper() for f in a.aileler.split(",") if f.strip()]
    bad = [f for f in fams if f not in ("F1", "F2", "F3", "F4", "F5", "F6", "F7")]
    if bad:
        print(f"Bilinmeyen aile: {bad}", file=sys.stderr)
        return 2
    if a.R < SC.N_NULL or a.plasebo_R < SC.N_NULL_PLACEBO or a.plasebo_tohum < SC.N_PLACEBO_SEEDS:
        print(f"UYARI: sözleşmenin altında tekrar sayısı (R={a.R}, plasebo {a.plasebo_tohum}×{a.plasebo_R}); sonuçlar "
              "statü için geçerli sayılmaz, yalnızca deneme çalıştırmasıdır.")
    t = time.time()
    log = lambda s: print(f"[{time.time() - t:7.0f} sn] {s}", flush=True)  # noqa: E731
    if _training_blocked(st):  # S0 modeli ve araştırma gerçek sonuç verisiyle eğitilir/çalışır (S3-GATE-02)
        return 3
    s0 = pd.read_pickle(a.s0) if a.s0 else load_or_build_s0(st.matches, out, progress=log)
    res = run_research(st.matches, out, s0=s0, R=a.R, placebo_seeds=a.plasebo_tohum, R_placebo=a.plasebo_R,
                       workers=a.isci, families=fams, progress=log, record=True,
                       experiments_path=out / "deneyler.jsonl", data_label="uygulama verisi")
    print("\nÖzet (her aile, sonuç ne olursa olsun kaydedildi):")
    for k, v in res["aileler"].items():
        print(f"  {k}: {v.get('ozet')}")
    print(f"Anomali özeti (yalnızca tür/durum/dönem sayıları): {res.get('anomali_ozeti', {}).get('durum')}")
    print(f"Sonuçlar: {out}")
    return 0


def cmd_seq_prematch(a) -> int:
    """Maç öncesi benzer diziler: yaklaşan maç için karar anından önce bilinen koşullar ve geçmiş örnekler."""
    import json

    import pandas as pd

    from .sequences.prematch import prematch_frame, prematch_view

    st = _store()
    if not st.has_data:
        print("Veri yok. Önce 'update' çalıştırın.", file=sys.stderr)
        return 2
    out = app_home() / "dizi_arastirma"
    cal = pd.read_pickle(out / "s0_kalibre.pkl") if (out / "s0_kalibre.pkl").exists() else None
    res = json.loads((out / "son_sonuclar.json").read_text(encoding="utf-8")) if (out / "son_sonuclar.json").exists() else None
    pf = prematch_frame(st.matches, st.fixtures, cal)
    tm = pf["tm"]
    rows = [int(i) for i in tm.index[pf["upcoming"] & (tm["team"] == a.takim).to_numpy()]]
    if not rows:
        print(f"{a.takim} için yaklaşan maç bulunamadı (fikstür verisi gerekir).", file=sys.stderr)
        return 2
    v = prematch_view(pf, rows[0], res)
    print("MAÇ ÖNCESİ GÖRÜNÜM — yalnızca karar anından önce bilinen bilgi; olay sonrası alan yok.")
    print(f"{v['kimlik']['date']} {v['kimlik']['team']} - {v['kimlik']['opponent']} (karar anı {v['karar_ani']})")
    print("Doğru koşullar:", ", ".join(k for k, x in v["PRE_EVENT_KOSULLARI"].items() if x) or "-")
    for s in v["benzer_kosullar"]:
        rate = "-" if s["olay_orani"] is None else f"{s['olay_orani']:.3f}"
        exp = "-" if s["s0_beklenen"] is None else f"{s['s0_beklenen']:.1f}"
        print(f"  {s['kosul']:<45s} {s['hedef']:<20s} n={s['n_gecmis']:<6d} isabet={s['isabet']:<5d} "
              f"ıska={s['iska']:<5d} oran={rate} S0 beklenen={exp} statü={s['statu']}")
    print(v["not"])
    if cal is None:
        print("Not: araştırma çalıştırılmadığı için beklenen puanlı atomlar ve S0 beklentisi tanımsız.")
    return 0


def _pilot_run(fn) -> int:
    """Pilot komutlarının ortak çıktısı: JSON özet (yalnızca sayılar/kimlikler; maç satırı yok)."""
    import json as _json

    from .pilot import PilotError

    try:
        out = fn()
    except PilotError as e:
        print(f"Pilot: {e}", file=sys.stderr)
        return 3
    print(_json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


def cmd_pilot_coverage(a) -> int:
    """S4 pilotu: kaynak kapsamı, köken, katılımcı referansı, model ve defter durumu (salt okunur)."""
    from .pilot import summary

    return _pilot_run(lambda: summary(a.ev))


def cmd_pilot_prepare(a) -> int:
    """S4 pilotu: openfootball sonuçlarını sabit commit'ten pilot klasörüne hazırlar (yalnızca o klasöre yazar)."""
    from .pilot import prepare

    return _pilot_run(lambda: prepare(a.ev, ref=a.ref, completed=a.sezon, fixture_days=a.gun,
                                      participants_file=a.katilimci))


def cmd_pilot_train(a) -> int:
    """S4 pilotu: mevcut gol motorunun ayrı pilot örneğini yalnızca pilot verisiyle eğitir."""
    from .pilot import train

    return _pilot_run(lambda: train(a.ev, progress=_progress))


def cmd_pilot_forecast(a) -> int:
    """S4 pilotu: yaklaşan maçlar için A/B/C kayıtları (varsayılan kuru çalıştırma; --uygula pilot defterine yazar)."""
    from .pilot import forecast

    return _pilot_run(lambda: forecast(a.ev, apply=a.uygula))


def cmd_pilot_diagnose(a) -> int:
    """S4 pilotu: M10 aşama tanılaması (iç doğrulamanın tek yeniden üretimi; ayrı çıktı klasörü, pilot değişmez)."""
    from .pilot import diagnose

    return _pilot_run(lambda: diagnose(a.ev, a.cikti, progress=_progress))


def cmd_self_test(a) -> int:
    from .selftest import run_self_test

    return run_self_test()


def _utf8_redirected_output() -> None:
    """Dosyaya/boruya yönlendirilen çıktı Windows ANSI kod sayfasında Türkçe karakterlerle düşmesin."""
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            continue


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _utf8_redirected_output()
    if not argv:
        from .ui.app import run

        return run()
    p = argparse.ArgumentParser(prog="bahis_tahmin", description="Bahis Tahmin komut satırı")
    sub = p.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("update", help="verileri indir/güncelle")
    u.add_argument("--leagues", help="virgülle ayrılmış lig kodları, ör. T1,E0,SP1")
    u.add_argument("--years", type=int)
    u.add_argument("--force", action="store_true")
    u.add_argument("--no-mirror", action="store_true", help="GitHub yedek veri setini kullanma")
    u.add_argument("--accept-terms", help="kullanım koşullarını okuyup onayladığınız kaynaklar, ör. football-data")
    u.set_defaults(fn=cmd_update)
    sub.add_parser("train", help="modeli eğit").set_defaults(fn=cmd_train)
    pr = sub.add_parser("predict", help="yaklaşan maç tahminleri")
    pr.add_argument("--league")
    pr.add_argument("--top", type=int, default=200)
    pr.set_defaults(fn=cmd_predict)
    b = sub.add_parser("en-olasi", help="model olasılığı yüksek seçimler (avantaj listesi değildir)")
    b.add_argument("--threshold", type=float, default=0.9)
    b.set_defaults(fn=cmd_likely)
    bt = sub.add_parser("backtest", help="geriye dönük test")
    bt.add_argument("--odds", default="avg", choices=["avg", "max", "b365", "pinnacle"])
    bt.add_argument("--min-ev", type=float, default=0.05)
    bt.add_argument("--source", default="final", choices=["final", "model"])
    bt.set_defaults(fn=cmd_backtest)
    sub.add_parser("self-test", help="kurulum kontrolü").set_defaults(fn=cmd_self_test)
    sub.add_parser("gol-egit", help="gol pazarları modelini eğit ve iç doğrulama yap").set_defaults(fn=cmd_goal_train)
    gp = sub.add_parser("gol-tahmin", help="yaklaşan maçlar için iki yarıda KG / 3.5 Üst / İY 1.5 Üst olasılıkları")
    gp.add_argument("--league")
    gp.set_defaults(fn=cmd_goal_predict)
    gk = sub.add_parser("gol-kapsam", help="lig-sezon veri kapsam özeti")
    gk.add_argument("--csv", help="kapsam matrisini bu CSV dosyasına yaz")
    gk.set_defaults(fn=cmd_goal_coverage)
    sub.add_parser("gol-sanal", help="sanal takip özeti ve kayıt zinciri doğrulaması").set_defaults(fn=cmd_goal_ledger)
    go = sub.add_parser("gol-oran-ice-aktar", help="gerçek oran CSV'sini doğrula (varsayılan) veya --uygula ile ekle")
    go.add_argument("--csv", required=True)
    go.add_argument("--uygula", action="store_true", help="doğrulanan kayıtları sanal takip veritabanına yaz")
    go.set_defaults(fn=cmd_goal_odds_import)
    gf = sub.add_parser("gol-olcum-kaydet", help="ileriye dönük ölçüm: yaklaşan maçların A/B/C tahmin kayıtları "
                                                 "(varsayılan kuru çalıştırma)")
    gf.add_argument("--uygula", action="store_true", help="kayıtları değişmez deftere yaz")
    gf.set_defaults(fn=cmd_goal_forecast_log)
    ge = sub.add_parser("gol-olcum-degerlendir", help="ileriye dönük ölçüm kayıtlarının değerlendirmesi (yazma yapmaz)")
    ge.add_argument("--protokol", action="store_true", help="dondurulmuş protokolü yazdır")
    ge.set_defaults(fn=cmd_goal_forecast_eval)
    so = sub.add_parser("dizi-olay", help="Mod A: takımın İY/MS olayları, aralıklar ve olay kartı (geçmiş inceleme)")
    so.add_argument("--takim", required=True)
    so.add_argument("--hedef", default="IY_GERIDE_MS_GALIP", help="takım hedefi, ör. IY_GERIDE_MS_GALIP, IY_ONDE_MS_MAGLUP")
    so.add_argument("--iyms", help="ham İY/MS kodu, ör. 2/1 (verilirse --hedef yok sayılır)")
    so.add_argument("--kart", type=int, help="olay kartı gösterilecek olay sırası (0'dan)")
    so.set_defaults(fn=cmd_seq_events)
    sub.add_parser("dizi-kapsam", help="dizi araştırması veri kapsamı ve incelenemeyen alanlar").set_defaults(fn=cmd_seq_coverage)
    sa = sub.add_parser("dizi-arastir", help="ön-kayıtlı dizi araştırması (F1–F7 + anomali); uzun sürer")
    sa.add_argument("--R", type=int, default=1000, help="referans süreç tekrar sayısı (sözleşme: 1000)")
    sa.add_argument("--plasebo-tohum", type=int, default=20, help="plasebo tohum sayısı (sözleşme: 20)")
    sa.add_argument("--plasebo-R", type=int, default=200, help="plasebo başına referans tekrarı (sözleşme: 200)")
    sa.add_argument("--isci", type=int, default=1, help="paralel işlem sayısı (sonuç işçi sayısından bağımsızdır)")
    sa.add_argument("--aileler", default="F1,F2,F3,F4,F5,F6,F7", help="çalıştırılacak aileler")
    sa.add_argument("--s0", help="hazır S0 soy kaydı (pickle); verilmezse uygulama klasöründe kurulur/önbellekten okunur")
    sa.set_defaults(fn=cmd_seq_research)
    sb = sub.add_parser("dizi-benzer", help="maç öncesi benzer diziler (yaklaşan maç; olay sonrası bilgi yok)")
    sb.add_argument("--takim", required=True)
    sb.set_defaults(fn=cmd_seq_prematch)
    # S4 pilotu: openfootball sonuçlarıyla tek lig (E0); bütün yazmalar yalnızca --ev klasörüne
    pk = sub.add_parser("pilot-kapsam", help="S4 pilotu: kaynak kapsamı, köken, model ve defter durumu (salt okunur)")
    pk.add_argument("--ev", required=True, help="pilot klasörü (uygulama veri klasöründen ayrı olmalı)")
    pk.set_defaults(fn=cmd_pilot_coverage)
    ph = sub.add_parser("pilot-hazirla", help="S4 pilotu: openfootball E0 sonuçlarını sabit commit'ten pilot "
                                               "klasörüne indir ve hazırla (yalnızca o klasöre yazar)")
    ph.add_argument("--ev", required=True, help="pilot klasörü (uygulama veri klasöründen ayrı olmalı)")
    ph.add_argument("--ref", help="openfootball/football.json commit'i (40 karakter); verilmezse GitHub'dan çözülür")
    ph.add_argument("--sezon", type=int, default=10, help="tamamlanmış sezon sayısı (varsayılan 10; en çok 16)")
    ph.add_argument("--gun", type=int, default=10, help="fikstür penceresi (gün)")
    ph.add_argument("--katilimci", help="bağımsız katılımcı referansı JSON (resmî kaynaktan; bkz. docs/S4_PILOT.md)")
    ph.set_defaults(fn=cmd_pilot_prepare)
    pe = sub.add_parser("pilot-egit", help="S4 pilotu: mevcut gol motorunu yalnızca pilot verisiyle eğit")
    pe.add_argument("--ev", required=True, help="pilot klasörü")
    pe.set_defaults(fn=cmd_pilot_train)
    pt = sub.add_parser("pilot-tahmin", help="S4 pilotu: yaklaşan maçlar için A/B/C kayıtları (varsayılan kuru "
                                              "çalıştırma)")
    pt.add_argument("--ev", required=True, help="pilot klasörü")
    pt.add_argument("--uygula", action="store_true", help="kayıtları pilot defterine yaz (değişmez)")
    pt.set_defaults(fn=cmd_pilot_forecast)
    pd_ = sub.add_parser("pilot-tani", help="S4 pilotu: M10 aşama tanılaması (iç doğrulamayı aynı veri ve bölmeyle "
                                            "bir kez yeniden üretir; pilot dosyaları değişmez)")
    pd_.add_argument("--ev", required=True, help="pilot klasörü (eğitilmiş pilot modeli olmalı)")
    pd_.add_argument("--cikti", required=True, help="tanılama çıktı klasörü (pilot ve uygulama veri klasöründen ayrı; "
                                                    "maç satırları yalnızca burada kalır)")
    pd_.set_defaults(fn=cmd_pilot_diagnose)
    a = p.parse_args(argv)
    return a.fn(a)
