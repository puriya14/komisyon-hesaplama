"""En olası seçimler: model olasılığı yüksek seçimler ve aynı eşiğin geçmiş (örneklem dışı) isabeti.

Bu görünüm "en olası" sonuçları listeler; oranına göre avantaj adayı DEĞİLDİR.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel

from ...data.leagues import league_name, short_name
from ...models.engine import MARKET_GROUPS, verify_selection
from ...models.markets import MARKETS
from .. import theme
from ..match_view import MatchDialog
from ..widgets import Card, DataFrameModel, banner, fmt_num, fmt_pct, fmt_signed_pct, make_table, section
from .base import Page


class LikelyPage(Page):
    title = "En Olası Seçimler"
    subtitle = ("Model olasılığı yüksek seçimler. Bu liste 'oranına göre avantaj' listesi değildir. Üstteki kartlar, "
                "aynı eşiğin geçmiş sezonlarda (model o maçları görmeden) ne sıklıkla gerçekleştiğini gösterir.")

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Model olasılığı en az:"))
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
        self.c_hit = Card("Geçmişte gerçekleşme oranı")
        self.c_cov = Card("Kapsam")
        self.c_odds = Card("Ortalama adil oran")
        self.c_roi = Card("Gerçek oranla geçmiş getiri")
        for i, c in enumerate((self.c_hit, self.c_cov, self.c_odds, self.c_roi)):
            grid.addWidget(c, 0, i)
        self.body.addLayout(grid)
        self.body.addWidget(banner(
            "<b>Önemli:</b> Yüksek olasılık, kâr demek değildir. %93 olasılıklı bir seçimin adil oranı ~1.07'dir; "
            "teklif edilen oran marj nedeniyle genellikle bunun altındadır. 'Gerçek oranla geçmiş getiri' kartı "
            "YALNIZCA verisetinde gerçek oranı olan marketleri (1X2 ve 2.5 Alt/Üst, piyasa ortalaması) kapsar; "
            "Çifte Şans, 1.5/3.5 Alt/Üst ve KG için oran türetilmez, getiri hesaplanamaz.",
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
            "league": short_name,
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
        self.gate_note = QLabel("")
        self.gate_note.setWordWrap(True)
        self.gate_note.setObjectName("muted")
        self.body.addWidget(self.gate_note)
        self.cup_note = QLabel("")  # KUPA-01: kupa modelinin aynı eşikteki geçmişi (kartlar lig modelinindir)
        self.cup_note.setWordWrap(True)
        self.cup_note.setObjectName("muted")
        self.body.addWidget(self.cup_note)
        self.kupon = QLabel("Kupon için satırlardaki kutucukları işaretleyin.")
        self.kupon.setWordWrap(True)
        self.kupon.setTextFormat(Qt.RichText)
        self.body.addWidget(self.kupon)

        self.body.addWidget(section("Market bazında geçmiş gerçekleşme (model olasılığı ≥ %90)"))
        self.pm_model = DataFrameModel()
        self.pm_model.hidden = {"market", "roi_n"}
        self.pm_model.headers = {"label": "Market", "n": "Seçim sayısı", "isabet": "Gerçekleşme", "ort_olasilik": "Ort. olasılık",
                                 "roi": "Gerçek oranla ROI"}
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
        if self.ctl.check_day():  # gün değişti: yeniden değerlendirme sinyali bu sayfayı yeniden çizer
            return
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
                    self.c_roi.set("Hesaplanamıyor", "Seçilen marketler için geçmiş gerçek oran yok")
            else:
                for c in (self.c_hit, self.c_cov, self.c_odds, self.c_roi):
                    c.set("-", "Bu eşikte geçmiş seçim yok")
            conf = eng.report.confidence if eng.report else {}
            self.pm_model.set_frame(pd.DataFrame(conf.get("per_market_90", [])))
        else:
            for c in (self.c_hit, self.c_cov, self.c_odds, self.c_roi):
                c.set("-", "Model eğitilince hesaplanır")

        rows = []
        skipped = len(self.ctl.match_unpredicted)
        warned = 0
        now = self.ctl.now()
        for i, p in enumerate(self.ctl.predictions):
            if not p.forecast_ok_at(now):  # veri uygunluğu doğrulanmadı: "en olası" listesine girmez
                skipped += 1
                continue
            # VERI-01 "Uyarılı" tahmin (bilinen eksik veri / az geçmiş): olasılık gösterilir ama bahis adayı değildir;
            # oran ve beklenen değer gösterilmez
            bet_ok = not p.data_block(now)
            warned += not bet_ok
            cands = [(k, float(p.markets[k])) for k in keys]
            if not cands:
                continue
            if one:
                cands = [max(cands, key=lambda kv: kv[1])]
            for k, prob in cands:
                if prob < thr:
                    continue
                o = p.odds.get(k) if bet_ok else None  # yalnızca gerçek oran; türetilmiş oran kullanılmaz
                rows.append({
                    "_i": i, "kupon": "", "date": p.date, "time": p.time, "league": p.league,
                    "match": f"{p.home} - {p.away}", "selection": MARKETS[k][0], "prob": prob,
                    "fair": 1.0 / prob, "odds": o if o else np.nan,
                    "ev": prob * o - 1.0 if o else np.nan,
                })
        self.model.set_frame(pd.DataFrame(rows))
        notes = []
        if skipped:
            notes.append(f"Tahmini gösterilemediği için listelenmeyen maç: {skipped}.")
        if warned:
            notes.append(f"Uyarılı (bahis adayı olmayan) {warned} maçta oran ve beklenen değer gösterilmez.")
        self.gate_note.setText(" ".join(notes) + (" Neden ve gereken veri için Tahminler sayfasındaki 'Veri durumu' "
                                                  "sütununa bakın." if notes else ""))
        from ...kupa.gorunum import likely_history_line

        line = likely_history_line(getattr(self.ctl, "cup_engine", None), keys, thr, one)
        self.cup_note.setText(line)
        self.cup_note.setVisible(bool(line))

    def _update_kupon(self, *args) -> None:
        df = self.model.frame
        sel = self.model.checked_rows()
        if df.empty or not sel:
            self.kupon.setText("Birden çok maçın birlikte gerçekleşme olasılığını görmek için kutucukları işaretleyin.")
            return
        rows = df.iloc[sel]
        dup = rows["match"].duplicated(keep=False)
        if dup.any():
            self.kupon.setText(
                "<b>Aynı maçtan birden fazla seçim işaretlendi.</b> Aynı maçtaki seçimler birbirine bağımlıdır "
                "(ör. iki yarıda KG gerçekleşirse 3.5 Üst ve İY 1.5 Üst de gerçekleşir); ortak olasılık bu ekranda "
                "hesaplanmaz. Her maçtan tek seçim bırakın.")
            return
        prob = float(np.prod(rows["prob"].to_numpy()))
        self.kupon.setText(
            f"<b>{len(rows)} farklı maç</b> · birlikte gerçekleşme olasılığı <b>yaklaşık {fmt_pct(prob)}</b> "
            f"<span style='color:{theme.MUTED}'>(maçların birbirinden bağımsız olduğu varsayımıyla; kombine oran ve "
            "beklenen kazanç, sağlayıcının gerçek kombine oranı olmadan hesaplanmaz. Her eklenen maç olasılığı düşürür.)</span>")

    def _open(self, index) -> None:
        src = self.proxy.mapToSource(index)
        i = int(self.model.frame.iloc[src.row()]["_i"])
        MatchDialog(self.ctl, self.ctl.predictions[i], self).exec()
