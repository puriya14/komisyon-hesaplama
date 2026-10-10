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
    fx = st.fixtures
    if a.league:
        fx = fx[fx["league"] == a.league.upper()]
    preds = eng.predict_fixtures(fx, s.odds_type)
    if not preds:
        print("Yaklaşan maç bulunamadı.")
        return 0
    for p in preds[: a.top]:
        best = p.best_value(s)
        val = f"  DEĞER: {best['label']} @{best['odds']:.2f} ({100 * best['ev']:+.0f}%)" if best else ""
        print(f"{p.date:%d.%m} {p.time:5s} {p.league:4s} {p.home:>18s} - {p.away:<18s} "
              f"1:%{100 * p.p_final[0]:4.1f} X:%{100 * p.p_final[1]:4.1f} 2:%{100 * p.p_final[2]:4.1f} "
              f"Ü2.5:%{100 * p.markets['O2.5']:4.1f} KG:%{100 * p.markets['BTTS_Y']:4.1f}{val}")
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
    preds = eng.predict_fixtures(st.fixtures, Settings.load().odds_type)
    for p in preds:
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
    eng = _goal_engine()
    fx = _store().fixtures
    if a.league:
        fx = fx[fx["league"] == a.league.upper()]
    preds = eng.predict_fixtures(fx)
    if not preds:
        print("Yaklaşan maç bulunamadı.")
        return 0
    st = {k: ("doğrulandı" if v else "DOĞRULANMADI") for k, v in eng.validated.items()}
    print(f"Model durumu: A {st.get('BTTS_BOTH_HALVES_YES')} · B {st.get('FT_OVER_3_5')} · C {st.get('FH_OVER_1_5')}. "
          "Gerçek oran olmadan öneri üretilmez.")
    for p in preds:
        iv = {k: p.interval(k) for k in ("BTTS_BOTH_HALVES_YES", "FT_OVER_3_5", "FH_OVER_1_5")}
        txt = " ".join(
            f"{s}:%{100 * p.probs[s]:4.1f} [{100 * iv[k][0]:.0f}-{100 * iv[k][1]:.0f}]" if iv[k][0] is not None
            else f"{s}:%{100 * p.probs[s]:4.1f}"
            for s, k in (("A", "BTTS_BOTH_HALVES_YES"), ("B", "FT_OVER_3_5"), ("C", "FH_OVER_1_5")))
        note = "  (veri uyarısı)" if p.data_notes else ""
        print(f"{p.kickoff_text:>28s} {p.league:4s} {p.home:>18s} - {p.away:<18s} {txt}{note}")
    return 0


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
        print(f"  {r['date']:%d.%m.%Y} {r['season']} {'Ev ' if h else 'Dep'} {r['opponent']:<22s} İY {iy}  MS {ms}{gap}")
    tail = ev.attrs.get("censored_tail")
    if tail:
        print(f"Açık (sansürlü) aralık: {tail['acik_aralik_mac']} maç (son maç {tail['son_mac_tarihi']}, neden {tail['bitis_nedeni']}). "
              "'Olmayacak' anlamına gelmez.")
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


def cmd_self_test(a) -> int:
    from .selftest import run_self_test

    return run_self_test()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
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
    so = sub.add_parser("dizi-olay", help="Mod A: takımın İY/MS olayları, aralıklar ve olay kartı (geçmiş inceleme)")
    so.add_argument("--takim", required=True)
    so.add_argument("--hedef", default="IY_GERIDE_MS_GALIP", help="takım hedefi, ör. IY_GERIDE_MS_GALIP, IY_ONDE_MS_MAGLUP")
    so.add_argument("--iyms", help="ham İY/MS kodu, ör. 2/1 (verilirse --hedef yok sayılır)")
    so.add_argument("--kart", type=int, help="olay kartı gösterilecek olay sırası (0'dan)")
    so.set_defaults(fn=cmd_seq_events)
    sub.add_parser("dizi-kapsam", help="dizi araştırması veri kapsamı ve incelenemeyen alanlar").set_defaults(fn=cmd_seq_coverage)
    a = p.parse_args(argv)
    return a.fn(a)
