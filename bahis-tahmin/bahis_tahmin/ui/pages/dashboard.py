"""Genel bakış sayfası."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPushButton, QWidget

from ...data.leagues import league_name
from .. import theme
from ..charts import ChartCanvas, plot_confidence, plot_season_quality
from ..widgets import Card, banner, fmt_pct, section
from .base import Page


class DashboardPage(Page):
    title = "Genel Bakış"
    subtitle = "Ücretsiz verilerle eğitilmiş tahmin modelinin özeti"

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.first_run = banner(
            "<b>Hoş geldiniz!</b> Başlamak için son yılların maç verilerini indirip modeli eğitmeniz gerekiyor. "
            "Verilerin kullanım koşullarını 'Veri' sayfasında okuyup onaylamanız istenecek (onay olmadan veri "
            "indirilmez). İlk kurulum birkaç dakika sürer; sonraki güncellemelerde yalnızca yeni maçlar indirilir."
        )
        self.body.addWidget(self.first_run)

        actions = QHBoxLayout()
        self.btn_update = QPushButton("Verileri Güncelle ve Modeli Eğit")
        self.btn_update.setObjectName("primary")
        self.btn_update.clicked.connect(lambda: self.ctl.update_and_train())
        self.btn_retrain = QPushButton("Modeli Yeniden Eğit")
        self.btn_retrain.clicked.connect(self.ctl.retrain)
        actions.addWidget(self.btn_update)
        actions.addWidget(self.btn_retrain)
        actions.addStretch(1)
        self.body.addLayout(actions)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.c_data = Card("Maç verisi")
        self.c_acc = Card("1X2 isabeti (örneklem dışı)")
        self.c_likely = Card("Olasılığı ≥ %90 seçimler: geçmişte gerçekleşme")
        self.c_fix = Card("Yaklaşan maçlar")
        for i, c in enumerate((self.c_data, self.c_acc, self.c_likely, self.c_fix)):
            grid.addWidget(c, 0, i)
        self.body.addLayout(grid)

        self.body.addWidget(section("Model güvenilirliği"))
        charts = QHBoxLayout()
        self.ch_conf = ChartCanvas(5.5, 3.2)
        self.ch_season = ChartCanvas(5.5, 3.2)
        self.ch_conf.setMinimumHeight(300)
        self.ch_season.setMinimumHeight(300)
        charts.addWidget(self.ch_conf)
        charts.addWidget(self.ch_season)
        holder = QWidget()
        holder.setLayout(charts)
        self.body.addWidget(holder)

        self.body.addWidget(banner(
            "<b>Dürüst not:</b> Futbolda maç sonucu (1-X-2) tahmininde en iyi bahis şirketlerinin bile isabeti "
            "yaklaşık %50-53'tür; hiçbir model tüm maçlarda %90 isabet sağlayamaz. Bu uygulama olasılıkları "
            "doğru (kalibre) tahmin etmeye odaklanır: model bir seçime %90 dediğinde, geçmiş testlerde bu seçimler "
            "yaklaşık o sıklıkta gerçekleşmiştir. Yüksek olasılık kâr anlamına gelmez; bu seçimlerin oranları düşüktür. "
            "Ayrıntılar: 'En Olası Seçimler', 'Gol Pazarları' ve 'Geriye Dönük Test'. 18+ · Bahis bağımlılık yapabilir.",
            "warn",
        ))
        self.body.addStretch(1)

        controller.dataChanged.connect(self.refresh)
        controller.modelChanged.connect(self.refresh)
        controller.predictionsChanged.connect(self.refresh)
        controller.busyChanged.connect(self._busy)
        self.refresh()

    def _busy(self, busy: bool) -> None:
        self.btn_update.setEnabled(not busy)
        self.btn_retrain.setEnabled(not busy and self.ctl.store.has_data)

    def refresh(self) -> None:
        st = self.ctl.store
        eng = self.ctl.engine
        self.first_run.setVisible(not st.has_data)
        self.btn_retrain.setEnabled(st.has_data and not self.ctl.busy)
        if st.has_data:
            n_lg = st.matches["league"].nunique()
            upd = st.meta.get("updated_at", "-").replace("T", " ")
            last = st.matches["date"].max().strftime("%d.%m.%Y")
            self.c_data.set(f"{len(st.matches):,}".replace(",", "."), f"{n_lg} lig · son maç {last} · güncelleme {upd}")
        else:
            self.c_data.set("-", "Henüz veri yok")
        if eng is not None and eng.report is not None:
            m = eng.report.metrics
            self.c_acc.set(
                fmt_pct(m.get("acc_final", m.get("acc_model"))),
                f"Model tek başına {fmt_pct(m.get('acc_model'))} · bahis piyasası {fmt_pct(m.get('acc_market'))} "
                f"· {m.get('n', 0):,} maç".replace(",", "."),
            )
            conf = eng.report.confidence or {}
            r90 = next((r for r in conf.get("best", []) if abs(r["esik"] - 0.9) < 1e-9), None)
            if r90 and r90["n"]:
                self.c_likely.set(
                    fmt_pct(r90["isabet"]),
                    f"{r90['n']:,} seçim · maçların {fmt_pct(r90['kapsam'])}'i".replace(",", "."),
                    color=theme.GOOD if r90["isabet"] >= 0.9 else None,
                )
            else:
                self.c_likely.set("-", "Model eğitilince hesaplanır")
            plot_confidence(self.ch_conf, conf.get("best", []), "En olası seçim: olasılık eşiğine göre gerçekleşme ve kapsam")
            plot_season_quality(self.ch_season, eng.report.per_season)
        else:
            self.c_acc.set("-", "Model henüz eğitilmedi")
            self.c_likely.set("-", "")
        preds = self.ctl.predictions
        if preds:
            n_val = sum(1 for p in preds if p.best_value(self.ctl.settings))
            leagues = sorted({p.league for p in preds})
            self.c_fix.set(str(len(preds)), f"{n_val} değerli bahis fırsatı · {len(leagues)} lig")
            self.c_fix.setToolTip("\n".join(league_name(lg) for lg in leagues))
        else:
            self.c_fix.set("0", "Fikstür verisi yok (güncellemeyi deneyin)")
