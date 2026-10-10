"""Tek maç tahmininin ayrıntılı görünümü (tahmin sayfası penceresi ve maç analizi için)."""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..analysis import head_to_head, team_matches
from ..data.leagues import league_name
from ..models.engine import MatchPrediction
from ..models.markets import top_scores
from . import theme
from .widgets import (
    DataFrameModel,
    ProbBar,
    ScoreHeatmap,
    banner,
    fmt_num,
    fmt_pct,
    fmt_signed_pct,
    make_table,
    section,
)


class MatchDetail(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.ctl = controller
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.title = QLabel("")
        self.title.setObjectName("pageTitle")
        self.title.setWordWrap(True)
        self.sub = QLabel("")
        self.sub.setObjectName("muted")
        self.sub.setWordWrap(True)
        lay.addWidget(self.title)
        lay.addWidget(self.sub)
        self.bar = ProbBar()
        lay.addWidget(self.bar)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        lay.addWidget(self.summary)
        self.note = banner("", "warn")
        lay.addWidget(self.note)

        mid = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(section("Marketler, adil oranlar ve değer"))
        self.mk_model = DataFrameModel()
        self.mk_model.headers = {
            "label": "Market", "prob": "Olasılık", "fair": "Adil oran", "need": "Değer için min. oran",
            "odds": "Oran", "ev": "Beklenen değer", "stake": "Önerilen bahis",
        }
        self.mk_model.hidden = {"market", "group", "kelly", "value"}
        self.mk_model.formatters = {
            "prob": fmt_pct, "fair": fmt_num, "need": fmt_num, "odds": fmt_num, "ev": fmt_signed_pct,
            "stake": lambda v: "-" if not v else f"{v:,.0f} {self.ctl.settings.currency}",
        }
        self.mk_model.backgrounds = {
            "prob": lambda v, r: theme.prob_color(float(v) * 0.8),
            "ev": lambda v, r: theme.ev_color(float(v)) if v == v else None,
        }
        self.mk_view, _ = make_table(self.mk_model, sortable=False)
        self.mk_view.setMinimumHeight(484)
        left.addWidget(self.mk_view)
        mid.addLayout(left, 3)
        right = QVBoxLayout()
        right.addWidget(section("Skor olasılıkları (%)"))
        hint = QLabel("Satır: ev sahibi golü · Sütun: deplasman golü")
        hint.setObjectName("muted")
        right.addWidget(hint)
        self.heat = ScoreHeatmap(6)
        self.heat.setMinimumSize(320, 320)
        right.addWidget(self.heat)
        self.scores = QLabel("")
        self.scores.setWordWrap(True)
        right.addWidget(self.scores)
        right.addStretch(1)
        mid.addLayout(right, 2)
        lay.addLayout(mid)

        lay.addWidget(section("Takım karşılaştırması"))
        self.compare = QGridLayout()
        self.compare.setHorizontalSpacing(24)
        lay.addLayout(self.compare)

        tables = QHBoxLayout()
        self.form_home = DataFrameModel()
        self.form_away = DataFrameModel()
        self.h2h = DataFrameModel()
        res_bg = {
            "Sonuç": lambda v, r: QColor("#12401a") if v == "G" else QColor("#3a1d1d") if v == "M" else None
        }
        self.form_home.backgrounds = res_bg
        self.form_away.backgrounds = res_bg
        self._form_titles = []
        for model in (self.form_home, self.form_away, self.h2h):
            col = QVBoxLayout()
            t = section("")
            self._form_titles.append(t)
            col.addWidget(t)
            view, _ = make_table(model, sortable=False)
            view.setMinimumHeight(300)
            col.addWidget(view)
            tables.addLayout(col)
        lay.addLayout(tables)
        self.pred: MatchPrediction | None = None

    def show_prediction(self, p: MatchPrediction, odds: dict | None = None) -> None:
        self.pred = p
        s = self.ctl.settings
        when = p.date.strftime("%d.%m.%Y") + (f" {p.time}" if p.time else "")
        self.title.setText(f"{p.home}  –  {p.away}")
        self.sub.setText(f"{league_name(p.league)} · {when}")
        self.bar.set_probs(p.p_final, (f"1 {p.home}", "X", f"2 {p.away}") if len(p.home) < 14 else ("1", "X", "2"))
        xg = p.exp_goals
        parts = [
            f"Beklenen gol: <b>{xg[0]:.2f} – {xg[1]:.2f}</b>",
            f"1: <b>{fmt_pct(p.p_final[0])}</b> · X: <b>{fmt_pct(p.p_final[1])}</b> · 2: <b>{fmt_pct(p.p_final[2])}</b>",
            f"2.5 Üst: <b>{fmt_pct(p.markets['O2.5'])}</b> · KG Var: <b>{fmt_pct(p.markets['BTTS_Y'])}</b>",
        ]
        if p.p_market is not None:
            parts.append(
                f"<span style='color:{theme.MUTED}'>Model tek başına: {fmt_pct(p.p_model[0])} / {fmt_pct(p.p_model[1])} / "
                f"{fmt_pct(p.p_model[2])} · Piyasa (marjsız): {fmt_pct(p.p_market[0])} / {fmt_pct(p.p_market[1])} / "
                f"{fmt_pct(p.p_market[2])}</span>"
            )
        self.summary.setText("<br>".join(parts))
        if p.p_market is None:
            self.note.setText(
                "Bu maç için piyasa oranı yok; olasılıklar yalnızca modelden gelir (model tek başına piyasadan "
                "biraz daha az isabetlidir). Maç Analizi sayfasında oranları girerseniz sonuç iyileşir."
            )
            self.note.show()
        else:
            self.note.hide()

        rows = p.value_rows(s, odds)
        df = pd.DataFrame(rows)
        df["need"] = df["fair"] * (1 + s.min_ev)
        df = df[["market", "group", "label", "prob", "fair", "need", "odds", "ev", "stake", "kelly", "value"]]
        if not getattr(s, "stake_suggestions", False):
            df = df.drop(columns=["stake"])
        self.mk_model.set_frame(df)

        self.heat.set_matrix(p.matrix)
        ts = top_scores(p.matrix, 6)
        self.scores.setText("En olası skorlar: " + ", ".join(f"{i}-{j} (%{100 * v:.1f})" for i, j, v in ts))

        while self.compare.count():
            w = self.compare.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        info = p.info
        rows = [
            ("", p.home, p.away),
            ("Elo puanı", fmt_num(info.get("elo_h"), 0), fmt_num(info.get("elo_a"), 0)),
            ("Son 6 maç puan ort.", fmt_num(info.get("h_ppg6")), fmt_num(info.get("a_ppg6"))),
            ("Son 6 maç attığı / yediği", f"{fmt_num(info.get('h_gf6'), 1)} / {fmt_num(info.get('h_ga6'), 1)}",
             f"{fmt_num(info.get('a_gf6'), 1)} / {fmt_num(info.get('a_ga6'), 1)}"),
            ("İç / dış saha puan ort. (son 5)", fmt_num(info.get("h_home_ppg5")), fmt_num(info.get("a_away_ppg5"))),
            ("İsabetli şut ort. (son 6)", fmt_num(info.get("h_sotf6"), 1), fmt_num(info.get("a_sotf6"), 1)),
            ("Dinlenme (gün)", fmt_num(info.get("h_rest"), 0), fmt_num(info.get("a_rest"), 0)),
            ("Lige yeni (yükselen)", "Evet" if info.get("h_new") else "Hayır", "Evet" if info.get("a_new") else "Hayır"),
        ]
        for r, (label, a, b) in enumerate(rows):
            for c, text in enumerate((label, a, b)):
                lbl = QLabel(text)
                if r == 0 or c == 0:
                    lbl.setObjectName("muted")
                self.compare.addWidget(lbl, r, c)

        matches = self.ctl.store.matches
        self._form_titles[0].setText(f"{p.home} – son maçlar")
        self._form_titles[1].setText(f"{p.away} – son maçlar")
        self._form_titles[2].setText("Aralarındaki son maçlar")
        self.form_home.set_frame(team_matches(matches, p.home, 8, p.league))
        self.form_away.set_frame(team_matches(matches, p.away, 8, p.league))
        self.h2h.set_frame(head_to_head(matches, p.home, p.away, 8))


class MatchDialog(QDialog):
    def __init__(self, controller, prediction: MatchPrediction, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{prediction.home} - {prediction.away}")
        self.resize(1180, 860)
        lay = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        inner.setObjectName("page")
        il = QVBoxLayout(inner)
        il.setContentsMargins(20, 16, 20, 16)
        self.detail = MatchDetail(controller)
        il.addWidget(self.detail)
        scroll.setWidget(inner)
        lay.addWidget(scroll)
        self.detail.show_prediction(prediction)
