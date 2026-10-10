"""Banko (yüksek güven) seçimleri: geçmişte doğrulanmış isabet oranlarıyla."""

from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel

from ...data.leagues import LEAGUES, league_name
from ...models.engine import MARKET_GROUPS, verify_selection
from ...models.markets import MARKETS
from .. import theme
from ..match_view import MatchDialog
from ..widgets import Card, DataFrameModel, banner, fmt_num, fmt_pct, fmt_signed_pct, make_table, section
from .base import Page


def _dc_odds(odds: dict, key: str) -> float | None:
    """1X2 oranlarından yaklaşık Çifte Şans oranı."""
    pairs = {"1X": ("1", "X"), "12": ("1", "2"), "X2": ("X", "2")}
    if key not in pairs:
        return None
    a, b = (odds.get(k) for k in pairs[key])
    if not a or not b:
        return None
    return 1.0 / (1.0 / a + 1.0 / b)


class BankoPage(Page):
    title = "Banko – Yüksek Güvenli Seçimler"
    subtitle = ("Modelin çok yüksek olasılık verdiği seçimler. Üstteki kartlar, aynı ayarların geçmiş sezonlarda "
                "(model o maçları görmeden) ne kadar tuttuğunu gösterir.")

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Güven eşiği (en az):"))
        self.sp_thr = QDoubleSpinBox()
        self.sp_thr.setRange(0.60, 0.99)
        self.sp_thr.setSingleStep(0.01)
        self.sp_thr.setDecimals(2)
        self.sp_thr.setValue(0.90)
        ctrl.addWidget(self.sp_thr)
        self.groups: dict[str, QCheckBox] = {}
        for g in MARKET_GROUPS:
            cb = QCheckBox(g)
            cb.setChecked(True)
            self.groups[g] = cb
            ctrl.addWidget(cb)
        self.chk_one = QCheckBox("Maç başına tek seçim")
        self.chk_one.setChecked(True)
        ctrl.addWidget(self.chk_one)
        ctrl.addStretch(1)
        self.body.addLayout(ctrl)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.c_hit = Card("Geçmiş isabet oranı")
        self.c_cov = Card("Kapsam")
        self.c_odds = Card("Ortalama adil oran")
        self.c_roi = Card("Yaklaşık getiri (ROI)")
        for i, c in enumerate((self.c_hit, self.c_cov, self.c_odds, self.c_roi)):
            grid.addWidget(c, 0, i)
        self.body.addLayout(grid)
        self.body.addWidget(banner(
            "<b>Önemli:</b> Yüksek isabet, kâr demek değildir. %93 olasılıklı bir seçimin adil oranı ~1.07'dir; "
            "bahis şirketleri marj kestiği için teklif edilen oran genellikle bunun altındadır ve uzun vadede "
            "zarar ettirir. 'Yaklaşık getiri' kartı, oranı bilinen geçmiş seçimlerde (1X2, Çifte Şans ve 2.5 Alt/Üst; "
            "Çifte Şans oranları 1X2'den türetilmiştir) piyasa ortalaması oranla oynansaydı ne olacağını gösterir.",
            "warn",
        ))

        self.body.addWidget(section("Yaklaşan maçlardaki seçimler"))
        self.model = DataFrameModel()
        self.model.hidden = {"_i", "ev_raw"}
        self.model.checkable_col = "kupon"
        self.model.headers = {
            "kupon": "Kupon", "date": "Tarih", "time": "Saat", "league": "Lig", "match": "Maç",
            "selection": "Seçim", "prob": "Olasılık", "fair": "Adil oran", "odds": "Oran", "ev": "Beklenen değer",
        }
        self.model.formatters = {
            "kupon": lambda v: "",
            "date": lambda v: pd.Timestamp(v).strftime("%d.%m.%Y"),
            "league": lambda v: LEAGUES[v].name if v in LEAGUES else v,
            "prob": fmt_pct, "fair": fmt_num, "odds": fmt_num, "ev": fmt_signed_pct,
        }
        self.model.backgrounds = {
            "prob": lambda v, r: theme.prob_color(float(v)),
            "ev": lambda v, r: theme.ev_color(float(v)) if v == v else None,
        }
        self.model.tooltips = {"league": lambda v, r: league_name(v)}
        self.view, self.proxy = make_table(self.model)
        self.view.setMinimumHeight(420)
        self.view.doubleClicked.connect(self._open)
        self.body.addWidget(self.view)
        self.kupon = QLabel("Kupon için satırlardaki kutucukları işaretleyin.")
        self.kupon.setWordWrap(True)
        self.kupon.setTextFormat(Qt.RichText)
        self.body.addWidget(self.kupon)

        self.body.addWidget(section("Market bazında geçmiş başarı (güven ≥ %90)"))
        self.pm_model = DataFrameModel()
        self.pm_model.hidden = {"market", "roi_n"}
        self.pm_model.headers = {"label": "Market", "n": "Seçim sayısı", "isabet": "İsabet", "ort_olasilik": "Ort. olasılık",
                                 "roi": "Yaklaşık ROI"}
        self.pm_model.formatters = {"isabet": fmt_pct, "ort_olasilik": fmt_pct, "roi": fmt_signed_pct}
        pm_view, _ = make_table(self.pm_model)
        pm_view.setMinimumHeight(260)
        self.body.addWidget(pm_view)
        self.body.addStretch(1)

        self.sp_thr.valueChanged.connect(self.refresh)
        self.chk_one.toggled.connect(self.refresh)
        for cb in self.groups.values():
            cb.toggled.connect(self.refresh)
        self.model.dataChanged.connect(self._update_kupon)
        self.model.modelReset.connect(self._update_kupon)
        controller.predictionsChanged.connect(self.refresh)
        controller.modelChanged.connect(self.refresh)
        self.refresh()

    def _keys(self) -> list[str]:
        keys = []
        for g, cb in self.groups.items():
            if cb.isChecked():
                keys.extend(MARKET_GROUPS[g])
        return keys

    def refresh(self) -> None:
        thr = self.sp_thr.value()
        keys = self._keys()
        one = self.chk_one.isChecked()
        eng = self.ctl.engine
        if eng is not None and eng.oos is not None and not eng.oos.empty:
            v = verify_selection(eng.oos, keys, thr, one)
            if v["n"]:
                ok = v["isabet"] >= 0.9
                self.c_hit.set(fmt_pct(v["isabet"]), f"{v['n']:,} geçmiş seçimde (2018–bugün, örneklem dışı)".replace(",", "."),
                               color=theme.GOOD if ok else None)
                self.c_cov.set(fmt_pct(v["kapsam"]), f"maçların bu oranında en az bir seçim var ({v['n_mac']:,} maç)".replace(",", "."))
                self.c_odds.set(fmt_num(1.0 / v["ort_olasilik"]), f"ortalama olasılık {fmt_pct(v['ort_olasilik'])}")
                if v["roi_n"]:
                    self.c_roi.set(fmt_signed_pct(v["roi"]), f"oranı bilinen {v['roi_n']:,} seçimde, ort. oran {fmt_num(v['ort_oran'])}".replace(",", "."),
                                   color=theme.GOOD if v["roi"] > 0 else theme.CRITICAL)
                else:
                    self.c_roi.set("-", "Bu marketler için geçmiş oran verisi yok")
            else:
                for c in (self.c_hit, self.c_cov, self.c_odds, self.c_roi):
                    c.set("-", "Bu eşikte geçmiş seçim yok")
            conf = eng.report.confidence if eng.report else {}
            self.pm_model.set_frame(pd.DataFrame(conf.get("per_market_90", [])))
        else:
            for c in (self.c_hit, self.c_cov, self.c_odds, self.c_roi):
                c.set("-", "Model eğitilince hesaplanır")

        rows = []
        for i, p in enumerate(self.ctl.predictions):
            cands = [(k, float(p.markets[k])) for k in keys]
            if not cands:
                continue
            if one:
                cands = [max(cands, key=lambda kv: kv[1])]
            for k, prob in cands:
                if prob < thr:
                    continue
                o = p.odds.get(k) or _dc_odds(p.odds, k)
                rows.append({
                    "_i": i, "kupon": "", "date": p.date, "time": p.time, "league": p.league,
                    "match": f"{p.home} - {p.away}", "selection": MARKETS[k][0], "prob": prob,
                    "fair": 1.0 / prob, "odds": o if o else np.nan,
                    "ev": prob * o - 1.0 if o else np.nan,
                })
        self.model.set_frame(pd.DataFrame(rows))

    def _update_kupon(self, *args) -> None:
        df = self.model.frame
        sel = self.model.checked_rows()
        if df.empty or not sel:
            self.kupon.setText("Kupon için satırlardaki kutucukları işaretleyin.")
            return
        rows = df.iloc[sel]
        prob = float(np.prod(rows["prob"].to_numpy()))
        fair = 1.0 / prob if prob > 0 else float("inf")
        odds = rows["odds"].to_numpy(dtype=float)
        text = (f"<b>Kupon: {len(rows)} seçim</b> · birlikte tutma olasılığı <b>{fmt_pct(prob)}</b> · "
                f"adil kupon oranı <b>{fair:.2f}</b>")
        if np.all(np.isfinite(odds)):
            total = float(np.prod(odds))
            text += f" · teklif edilen oranlarla <b>{total:.2f}</b> (beklenen değer {fmt_signed_pct(prob * total - 1)})"
        text += ("<br><span style='color:%s'>Not: Seçimler birbirinden bağımsız varsayılır. Her eklenen maç, "
                 "kuponun tutma olasılığını düşürür.</span>" % theme.MUTED)
        self.kupon.setText(text)

    def _open(self, index) -> None:
        src = self.proxy.mapToSource(index)
        i = int(self.model.frame.iloc[src.row()]["_i"])
        MatchDialog(self.ctl, self.ctl.predictions[i], self).exec()
