"""Kurulum kontrolü: tüm bileşenleri yapay (rastgele üretilmiş) bir ligle uçtan uca çalıştırır.

Gerçek verilere dokunmaz; geçici bir klasör kullanır. Paketlenmiş .exe'nin
eksiksiz olduğunu doğrulamak için de kullanılır (çıkış kodu 0 = başarılı).
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd


def synthetic_matches(
    n_seasons: int = 5, n_teams: int = 14, league: str = "T1", seed: int = 0, start_year: int = 2020
) -> pd.DataFrame:
    """Bilinen takım güçleriyle Poisson skorlar ve %5 marjlı oranlar üretir (test amaçlı)."""
    from scipy.stats import poisson

    from .data.leagues import season_label
    from .data.parsers import MATCH_COLUMNS

    rng = np.random.default_rng(seed)
    g = np.arange(11)
    teams = [f"Takım {chr(65 + i)}" for i in range(n_teams)]
    att = rng.normal(0, 0.3, n_teams)
    dfn = rng.normal(0, 0.3, n_teams)
    rows = []
    for s in range(n_seasons):
        year = start_year + s
        date = pd.Timestamp(year, 8, 10)
        pairs = [(i, j) for i in range(n_teams) for j in range(n_teams) if i != j]
        rng.shuffle(pairs)
        per_round = n_teams // 2
        for k, (i, j) in enumerate(pairs):
            d = date + pd.Timedelta(days=7 * (k // per_round))
            lam = np.exp(0.25 + 0.2 + att[i] - dfn[j])
            nu = np.exp(0.25 + att[j] - dfn[i])
            hg, ag = int(rng.poisson(lam)), int(rng.poisson(nu))
            m = np.outer(poisson.pmf(g, lam), poisson.pmf(g, nu))
            p = np.array([np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()])
            odds = 1.0 / (p * 1.05)
            po = 1 - m[np.add.outer(g, g) <= 2].sum()
            o25 = 1.0 / (np.array([po, 1 - po]) * 1.05)
            rows.append({
                "league": league, "season": season_label(year), "date": d, "time": "19:00",
                "home": teams[i], "away": teams[j], "fthg": hg, "ftag": ag,
                "h_sot": max(hg, int(rng.poisson(lam * 3))), "a_sot": max(ag, int(rng.poisson(nu * 3))),
                "o_h": odds[0], "o_d": odds[1], "o_a": odds[2],
                "omax_h": odds[0] * 1.03, "omax_d": odds[1] * 1.03, "omax_a": odds[2] * 1.03,
                "o_o25": o25[0], "o_u25": o25[1], "omax_o25": o25[0] * 1.02, "omax_u25": o25[1] * 1.02,
                "source": "sentetik",
            })
    df = pd.DataFrame(rows)
    for c in MATCH_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    return df[MATCH_COLUMNS].sort_values("date", kind="mergesort").reset_index(drop=True)


def run_self_test(gui: bool = True) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bahis_selftest_"))
    os.environ["BAHIS_TAHMIN_HOME"] = str(tmp)
    log_lines: list[str] = []

    def log(msg: str) -> None:
        log_lines.append(msg)
        print(msg, flush=True)

    ok = True
    t0 = time.time()
    try:
        from .betting.backtest import BacktestConfig, run_backtest
        from .data.store import DataStore
        from .models.engine import PredictionEngine

        matches = synthetic_matches()
        log(f"Yapay veri: {len(matches)} maç")
        eng = PredictionEngine()
        rep = eng.train(matches)
        log(f"Eğitim tamam: {rep.metrics.get('n', 0)} örneklem dışı tahmin, isabet %{100 * rep.metrics.get('acc_model', 0):.1f}")
        p = eng.predict_match("T1", "Takım A", "Takım B", market_odds={"1": 2.1, "X": 3.3, "2": 3.6})
        assert abs(sum(p.p_final) - 1) < 1e-6, "olasılıklar toplamı 1 değil"
        assert abs(p.markets["1"] - p.p_final[0]) < 1e-6, "skor matrisi 1X2 ile tutarsız"
        log(f"Tahmin: {np.round(p.p_final, 3).tolist()}")
        bt = run_backtest(eng.oos, BacktestConfig(min_ev=0.0))
        log(f"Geriye dönük test: {bt.summary.get('bahis', 0)} bahis")
        eng.save(tmp / "engine.joblib")
        assert PredictionEngine.load(tmp / "engine.joblib") is not None, "model kaydedilip yüklenemedi"
        store = DataStore(tmp)
        store.matches = matches
        fx = matches.tail(4)[["league", "date", "time", "home", "away", "o_h", "o_d", "o_a", "source"]].copy()
        fx["date"] = pd.Timestamp.today().normalize()
        store.fixtures = fx.reindex(columns=store.fixtures.columns)
        store.meta["updated_at"] = pd.Timestamp.now().isoformat(timespec="seconds")
        store.save()
        if gui:
            if sys.platform != "win32" and not os.environ.get("DISPLAY"):
                os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            from PySide6.QtWidgets import QApplication

            from .ui.main_window import MainWindow
            from .ui.theme import apply_theme

            app = QApplication.instance() or QApplication([])
            apply_theme(app)
            win = MainWindow()
            win.ctl.settings.auto_update_on_start = False
            win.ctl.store = store
            win.ctl.engine = eng
            win.ctl.dataChanged.emit()
            win.ctl.modelChanged.emit()
            win.ctl.refresh_predictions()
            for row in range(win.nav.count()):
                win.nav.setCurrentRow(row)
                app.processEvents()
            log(f"Arayüz: {win.nav.count()} sayfa oluşturuldu, {len(win.ctl.predictions)} tahmin")
            win.close()
    except Exception:
        ok = False
        log("HATA:\n" + traceback.format_exc())
    log(f"Öz-test {'BAŞARILI' if ok else 'BAŞARISIZ'} ({time.time() - t0:.1f} sn)")
    try:
        out = Path(tempfile.gettempdir()) / "bahis_tahmin_selftest.log"
        out.write_text("\n".join(log_lines), encoding="utf-8")
    except OSError:
        pass
    return 0 if ok else 1
