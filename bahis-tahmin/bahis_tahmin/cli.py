"""Komut satırı arayüzü (arayüzsüz kullanım ve otomatik testler için).

Örnekler:
    python -m bahis_tahmin                      # masaüstü uygulaması
    python -m bahis_tahmin update --leagues T1,E0 --years 5
    python -m bahis_tahmin train
    python -m bahis_tahmin predict --league T1
    python -m bahis_tahmin banko --threshold 0.9
    python -m bahis_tahmin backtest --odds max --min-ev 0.05
    python -m bahis_tahmin self-test
"""

from __future__ import annotations

import argparse
import sys
import time

from .config import Settings, app_home
from .data.leagues import LEAGUES, league_name

ENGINE_FILE = "engine.joblib"


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
    s.save()
    st = DataStore(app_home())
    st.load()
    rep = st.update(s.leagues, s.years_back, progress=_progress, force=a.force,
                    use_mirror_fallback=not a.no_mirror, fixture_days=s.fixture_days)
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
            print(f"  güven ≥ %{100 * r['esik']:.0f}: isabet %{100 * r['isabet']:.1f}, kapsam %{100 * r['kapsam']:.1f} ({r['n']} seçim)")
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


def cmd_banko(a) -> int:
    from .models.engine import MARKET_GROUPS, verify_selection
    from .models.markets import MARKETS

    st = _store()
    eng = _engine()
    keys = [k for g in MARKET_GROUPS.values() for k in g]
    v = verify_selection(eng.oos, keys, a.threshold, True)
    if v["n"]:
        print(f"Geçmiş doğrulama (güven ≥ %{100 * a.threshold:.0f}): isabet %{100 * v['isabet']:.1f}, "
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
    u.set_defaults(fn=cmd_update)
    sub.add_parser("train", help="modeli eğit").set_defaults(fn=cmd_train)
    pr = sub.add_parser("predict", help="yaklaşan maç tahminleri")
    pr.add_argument("--league")
    pr.add_argument("--top", type=int, default=200)
    pr.set_defaults(fn=cmd_predict)
    b = sub.add_parser("banko", help="yüksek güvenli seçimler")
    b.add_argument("--threshold", type=float, default=0.9)
    b.set_defaults(fn=cmd_banko)
    bt = sub.add_parser("backtest", help="geriye dönük test")
    bt.add_argument("--odds", default="avg", choices=["avg", "max", "b365", "pinnacle"])
    bt.add_argument("--min-ev", type=float, default=0.05)
    bt.add_argument("--source", default="final", choices=["final", "model"])
    bt.set_defaults(fn=cmd_backtest)
    sub.add_parser("self-test", help="kurulum kontrolü").set_defaults(fn=cmd_self_test)
    a = p.parse_args(argv)
    return a.fn(a)
