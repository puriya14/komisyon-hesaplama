"""Gol pazarları: iki yarıda KG, 3.5 Üst, İY 1.5 Üst — tarama, maç analizi, kapsam, doğrulama, sanal takip."""

from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ...data.leagues import LEAGUES, league_name
from ...eligibility import display_label
from ...data.source_registry import SOURCES
from ...goals.coverage import coverage_matrix, coverage_summary, quarantine
from ...goals.decision import STATUS_TR, DecisionPolicy
from ...goals.markets import MARKETS, PRIMARY_YES, RULE_VERSION
from ...goals.model import FEATURE_VERSION, MODEL_VERSION
from ...goals.service import (
    SELECTIONS,
    decisions_for,
    gated_goal_match,
    ledger_csv,
    ledger_rows,
    record_decisions,
    settle_pending,
)
from ...goals.value import OddsQuote
from .. import theme
from ..charts import ChartCanvas
from ..widgets import Card, DataFrameModel, banner, fmt_num, fmt_pct, fmt_signed_pct, make_table, section
from .base import Page

NAMES = {"A": "İki yarıda da KG", "B": "Maç 3,5 Üst", "C": "İlk yarı 1,5 Üst"}
KEY_OF = {"A": "BTTS_BOTH_HALVES_YES", "B": "FT_OVER_3_5", "C": "FH_OVER_1_5"}
STATUS_SHORT = {
    "VALUE_CANDIDATE": "ADAY", "NO_VALUE": "YOK", "INSUFFICIENT_DATA": "VERİ", "ODDS_UNAVAILABLE": "ORAN YOK",
    "STALE_ODDS": "ESKİ ORAN", "MARKET_UNSUPPORTED": "EŞLEŞME", "MODEL_NOT_VALIDATED": "DOĞRULANMADI",
    "HIGH_UNCERTAINTY": "BELİRSİZ", "SETTLEMENT_AMBIGUOUS": "KURAL", "SUSPICIOUS_EDGE": "KARANTİNA",
    "DATA_NOT_ELIGIBLE": "VERİ UYGUN DEĞİL",
}


def _shown(verdict, now):
    """(sonuç, gösterim engeli): bu anda gösterilemeyen ilk pazar, yoksa bahsi engellenen, yoksa ilki. Gösterim
    denetimi gün, kimlik ve model durumu eşleşmesini de içerir (gün değişince eski sonuç kullanılmaz)."""
    items = [(e, verdict.display_codes(mk, now)) for mk, e in verdict.by_market.items()]
    for e, codes in items:
        if codes:
            return e, codes
    for e, codes in items:
        if not e.bet_ok:
            return e, codes
    return items[0] if items else (None, ["BAGLAM_YOK"])


def _data_label(verdict, now) -> str:
    return display_label(*_shown(verdict, now))[0]


def _data_text(verdict, now) -> str:
    return display_label(*_shown(verdict, now))[1]


def _fin(v) -> float | None:
    """Sonlu sayıysa float, değilse (None/NaN/metin) None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _iv(pred, key) -> str:
    lo, hi = pred.intervals.get(key, (None, None)) if pred.intervals else (None, None)
    return f"%{100 * lo:.0f}–%{100 * hi:.0f}" if lo is not None else "-"


class GoalsPage(Page):
    title = "Gol Pazarları"
    subtitle = ("İki yarıda da karşılıklı gol · Maç 3,5 Üst · İlk yarı 1,5 Üst. Olasılıklar tek bir ortak gol dağılımından "
                "türetilir; öneri yalnızca gerçek oran ve doğrulanmış model ile oluşabilir.")

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.status_banner = banner("", "warn")
        self.body.addWidget(self.status_banner)
        bar = QHBoxLayout()
        self.btn_train = QPushButton("Gol modelini eğit")
        self.btn_train.clicked.connect(self.ctl.train_goal_engine)
        bar.addWidget(self.btn_train)
        bar.addStretch(1)
        self.body.addLayout(bar)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_scan(), "Tarama")
        self.tabs.addTab(self._build_match(), "Maç analizi")
        self.tabs.addTab(self._build_coverage(), "Veri kapsamı")
        self.tabs.addTab(self._build_validation(), "Model doğrulama")
        self.tabs.addTab(self._build_ledger(), "Sanal takip")
        self.tabs.setMinimumHeight(980)
        self.body.addWidget(self.tabs)
        self.body.addWidget(QLabel("18+ · Bahis bağımlılık yapabilir. Bu ekran analiz amaçlıdır; kazanç garantisi vermez. "
                                   "Destek: YEDAM 115."))
        controller.goalModelChanged.connect(self._reset_panel)
        controller.goalModelChanged.connect(self.refresh_all)
        controller.goalPredictionsChanged.connect(self.refresh_scan)
        controller.dataChanged.connect(self._reset_panel)
        controller.dataChanged.connect(self.refresh_coverage)
        controller.settingsChanged.connect(self._settings_changed)
        controller.busyChanged.connect(lambda b: self.btn_train.setEnabled(not b and self.ctl.store.has_data))
        self.refresh_all()

    # ================================================================ Tarama
    def _build_scan(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.cb_mode = QComboBox()
        self.cb_mode.addItem("En olası (olasılığa göre sıralı)", "likely")
        self.cb_mode.addItem("Avantaj adayları (gerçek oranına göre)", "value")
        self.cb_market = QComboBox()
        for s, name in NAMES.items():
            self.cb_market.addItem(f"{s}: {name}", s)
        row.addWidget(QLabel("Görünüm:"))
        row.addWidget(self.cb_mode)
        row.addWidget(QLabel("Sıralama pazarı:"))
        row.addWidget(self.cb_market)
        row.addStretch(1)
        lay.addLayout(row)
        self.scan_model = DataFrameModel()
        self.scan_model.hidden = {"_i", "_sort"}
        self.scan_model.headers = {
            "when": "Tarih (İstanbul)", "league": "Lig", "match": "Maç",
            "A": "A: İki yarı KG", "A_iv": "A aralık", "B": "B: 3,5 Üst", "B_iv": "B aralık",
            "C": "C: İY 1,5 Üst", "C_iv": "C aralık", "data": "Veri durumu", "decision": "Karar (A/B/C)",
            "neden": "Veri ayrıntısı (neden · veri kesimi · gereken)",
        }
        self.scan_model.tooltips = {"neden": lambda v, r: v, "data": lambda v, r: r["neden"]}
        self.scan_model.formatters = {"A": fmt_pct, "B": fmt_pct, "C": fmt_pct,
                                      "league": lambda v: LEAGUES[v].name if v in LEAGUES else v}
        for c in ("A", "B", "C"):
            self.scan_model.backgrounds[c] = lambda v, r: theme.prob_color(_fin(v)) if _fin(v) is not None else None
        self.scan_view, self.scan_proxy = make_table(self.scan_model)
        self.scan_view.setMinimumHeight(560)
        self.scan_view.doubleClicked.connect(self._open_from_scan)
        lay.addWidget(self.scan_view)
        self.scan_note = QLabel("")
        self.scan_note.setWordWrap(True)
        self.scan_note.setObjectName("muted")
        lay.addWidget(self.scan_note)
        self.cb_mode.currentIndexChanged.connect(self.refresh_scan)
        self.cb_market.currentIndexChanged.connect(self.refresh_scan)
        return w

    def refresh_scan(self) -> None:
        if getattr(self, "_in_scan", False):  # sinyal üzerinden yeniden giriş koruması
            return
        self._in_scan = True
        try:
            self._refresh_scan()
        finally:
            self._in_scan = False

    def _refresh_scan(self) -> None:
        if self.ctl.goal_day_stale():  # gün değişti: uygunluk yeniden değerlendirilir (bu arada eski sonuç gösterilmez)
            self.ctl.refresh_goal_predictions()
        eng = self.ctl.goal_engine
        verdicts = self.ctl.goal_verdicts
        self._decisions = {}
        if eng is None or not verdicts:
            self.scan_model.set_frame(pd.DataFrame())
            self.scan_note.setText(
                "Gol modeli henüz eğitilmedi." if eng is None else
                "Yaklaşan maç bulunamadı (fikstür verisi yok). Maç analizi sekmesinden elle maç seçebilirsiniz.")
            self._fill_match_combo()
            return
        mode = self.cb_mode.currentData()
        msel = self.cb_market.currentData()
        now = self.ctl.now()
        rows = []
        n_blocked = 0
        for i, v in enumerate(verdicts):
            p = v.prediction
            # Kararlar aynı uygunluk sonucuyla üretilir; uygunluk yoksa karar motoru DATA_NOT_ELIGIBLE döndürür.
            decs = decisions_for(p, eng, self.ctl.ledger_if_exists(), now, eligibility=v) if p is not None else []
            self._decisions[v.candidate_id] = decs
            by = {d.market_key: d for d in decs}
            if mode == "value" and not any(d.status == "VALUE_CANDIDATE" for d in decs):
                continue
            probs, ivs = {}, {}
            for s, key in KEY_OF.items():
                ok = v.usable(key, now)
                probs[s] = p.probs.get(s, np.nan) if ok else np.nan  # uygun değilse olasılık gösterilmez (0 değil)
                ivs[s] = _iv(p, key) if ok else "-"
            usable = any(np.isfinite(x) for x in probs.values())
            n_blocked += not usable
            sel = probs.get(msel, np.nan)
            rows.append({
                # Uygun olmayan maçlar olasılık sırasında en sona düşer ("en iyi" gibi üste taşınmaz)
                "_i": i, "_sort": -sel if np.isfinite(sel) else np.inf,
                "when": p.kickoff_text if p is not None else f"{v.date:%d.%m.%Y}", "league": v.league,
                "match": f"{v.home} - {v.away}" + ("" if v.canonical_id else " (takım eşleşmedi)"),
                "A": probs["A"], "A_iv": ivs["A"], "B": probs["B"], "B_iv": ivs["B"], "C": probs["C"],
                "C_iv": ivs["C"], "data": _data_label(v, now),
                "decision": (" / ".join(STATUS_SHORT.get(by[k].status, by[k].status) for k in PRIMARY_YES)
                             if decs else "TAHMİN YOK"),
                "neden": _data_text(v, now),
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("_sort", kind="mergesort").reset_index(drop=True)
        self.scan_model.set_frame(df)
        n_val = sum(1 for decs in self._decisions.values() for d in decs if d.status == "VALUE_CANDIDATE")
        self.scan_note.setText(
            ("Uygun aday yok: hiçbir maçta önceden tanımlı kontrollerin tamamı geçilmedi. Bu geçerli bir sonuçtur. "
             if mode == "value" and df.empty else "")
            + f"{len(verdicts)} maç · tahmini gösterilemeyen {n_blocked} maçta olasılık yok (nedeni veri sütununda) · "
            f"{n_val} avantaj adayı · karar politikası: {DecisionPolicy().version}. "
            "'En olası' görünümü avantaj göstermez; yüksek olasılık düşük oranla birlikte gelir. "
            "Bu pazarlar için veri setinde gerçek oran yoktur: oranları Maç analizi sekmesinde siz girersiniz.")
        self._fill_match_combo()

    def _open_from_scan(self, index) -> None:
        src = self.scan_proxy.mapToSource(index)
        i = int(self.scan_model.frame.iloc[src.row()]["_i"])
        self.cb_fixture.setCurrentIndex(i + 1)
        self.tabs.setCurrentIndex(1)

    # ============================================================ Maç analizi
    def _build_match(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        pick = QGroupBox("Maç seçimi")
        pl = QGridLayout(pick)
        self.cb_fixture = QComboBox()
        self.cb_fixture.setMinimumWidth(420)
        self.cb_league = QComboBox()
        self.cb_home = QComboBox()
        self.cb_away = QComboBox()
        btn_manual = QPushButton("Elle seçilen maçı analiz et")
        btn_manual.clicked.connect(self._analyze_manual)
        pl.addWidget(QLabel("Yaklaşan maç:"), 0, 0)
        pl.addWidget(self.cb_fixture, 0, 1, 1, 3)
        pl.addWidget(QLabel("veya lig / ev / deplasman:"), 1, 0)
        pl.addWidget(self.cb_league, 1, 1)
        pl.addWidget(self.cb_home, 1, 2)
        pl.addWidget(self.cb_away, 1, 3)
        pl.addWidget(btn_manual, 2, 3)
        lay.addWidget(pick)
        cards = QHBoxLayout()
        self.cards = {s: Card(f"{s}: {NAMES[s]}") for s in ("A", "B", "C")}
        for c in self.cards.values():
            cards.addWidget(c)
        lay.addLayout(cards)
        self.rel = QLabel("")
        self.rel.setWordWrap(True)
        self.rel.setTextFormat(Qt.RichText)
        lay.addWidget(self.rel)
        lay.addWidget(section("İki yarıda KG için dört koşul (ortak modelden, bağımsız çarpılmadan)"))
        self.cond_model = DataFrameModel()
        self.cond_model.headers = {"kosul": "Koşul", "p": "Gerçekleşme olasılığı", "not": "Not"}
        self.cond_model.formatters = {"p": fmt_pct}
        cv, _ = make_table(self.cond_model, sortable=False)
        cv.setMinimumHeight(160)
        lay.addWidget(cv)

        odds = QGroupBox("Gerçek oranlar (karar anında bahis şirketinizde görünen; boş = 0)")
        ol = QGridLayout(odds)
        self.odds_spin = {}
        for i, key in enumerate(SELECTIONS):
            sp = QDoubleSpinBox()
            sp.setRange(0.0, 1000.0)
            sp.setDecimals(2)
            sp.setSpecialValueText("–")
            self.odds_spin[key] = sp
            ol.addWidget(QLabel(MARKETS[key].name_tr), i // 2, (i % 2) * 2)
            ol.addWidget(sp, i // 2, (i % 2) * 2 + 1)
        self.ed_book = QLineEdit()
        self.ed_book.setPlaceholderText("Bahis şirketi adı")
        ol.addWidget(QLabel("Bahis şirketi:"), 3, 0)
        ol.addWidget(self.ed_book, 3, 1)
        btn_odds = QPushButton("Oranları şimdi geçerli olarak kaydet")
        btn_odds.clicked.connect(self._save_odds)
        ol.addWidget(btn_odds, 3, 3)
        lay.addWidget(odds)
        lay.addWidget(section("Karar tablosu"))
        self.dec_model = DataFrameModel()
        self.dec_model.headers = {
            "secim": "Seçim", "p": "Olasılık", "aralik": "Belirsizlik (%80)", "adil": "Adil oran", "oran": "Gerçek oran",
            "basabas": "Başabaş", "ev": "Beklenen değer", "ev_safe": "Belirsizlik dahil EV", "min_oran": "Gereken min. oran",
            "durum": "Durum", "gerekce": "Gerekçe",
        }
        self.dec_model.formatters = {"p": fmt_pct, "adil": fmt_num, "oran": fmt_num, "basabas": fmt_pct,
                                     "ev": fmt_signed_pct, "ev_safe": fmt_signed_pct, "min_oran": fmt_num}
        self.dec_model.backgrounds = {"ev": lambda v, r: theme.ev_color(_fin(v)) if _fin(v) is not None else None}
        self.dec_model.tooltips = {"gerekce": lambda v, r: v}
        dv, _ = make_table(self.dec_model, sortable=False)
        dv.setMinimumHeight(240)
        lay.addWidget(dv)
        rec = QHBoxLayout()
        self.btn_record = QPushButton("Bu kararları sanal takibe kaydet (değiştirilemez)")
        self.btn_record.clicked.connect(self._record)
        rec.addWidget(self.btn_record)
        rec.addStretch(1)
        lay.addLayout(rec)
        self.used = QTextBrowser()
        self.used.setMinimumHeight(170)
        lay.addWidget(section("Kullanılan veri ve model"))
        lay.addWidget(self.used)
        lay.addWidget(section("İkinci aşama (araştırma) pazarları — öneri motoruna kapalı"))
        self.sec_model = DataFrameModel()
        self.sec_model.headers = {"pazar": "Pazar", "p": "Yapısal model olasılığı", "not": "Durum"}
        self.sec_model.formatters = {"p": fmt_pct}
        sv, _ = make_table(self.sec_model, sortable=False)
        sv.setMinimumHeight(190)
        lay.addWidget(sv)
        self.cb_fixture.currentIndexChanged.connect(self._analyze_fixture)
        self.cb_league.currentIndexChanged.connect(self._fill_teams)
        self._current = None
        self._current_verdict = None
        self._current_decisions = []
        return w

    def _fill_match_combo(self) -> None:
        self.cb_fixture.blockSignals(True)
        cur = self.cb_fixture.currentIndex()
        self.cb_fixture.clear()
        self.cb_fixture.addItem("— seçin —", None)
        now = self.ctl.now()
        for v in self.ctl.goal_verdicts:
            when = v.prediction.kickoff_text if v.prediction is not None else f"{v.date:%d.%m.%Y}"
            tag = "" if v.any_usable(now) else f" · {_data_label(v, now)}"
            self.cb_fixture.addItem(f"{when} · {league_name(v.league)} · {v.home} - {v.away}{tag}", v.candidate_id)
        self.cb_fixture.setCurrentIndex(cur if 0 <= cur < self.cb_fixture.count() else 0)
        self.cb_fixture.blockSignals(False)
        eng = self.ctl.goal_engine
        self.cb_league.blockSignals(True)
        self.cb_league.clear()
        if eng is not None:
            for code in [c for c in LEAGUES if c in eng.states]:
                self.cb_league.addItem(league_name(code), code)
        self.cb_league.blockSignals(False)
        self._fill_teams()

    def _fill_teams(self) -> None:
        eng = self.ctl.goal_engine
        lg = self.cb_league.currentData()
        teams = sorted(eng.states[lg].elo.cur_teams or eng.states[lg].elo.prev_teams) if (eng and lg in (eng.states or {})) else []
        for cb in (self.cb_home, self.cb_away):
            cb.clear()
            cb.addItems(teams)
        if len(teams) > 1:
            self.cb_away.setCurrentIndex(1)

    def _analyze_fixture(self) -> None:
        i = self.cb_fixture.currentIndex() - 1
        if 0 <= i < len(self.ctl.goal_verdicts):
            self._show(self.ctl.goal_verdicts[i])

    def _analyze_manual(self) -> None:
        eng = self.ctl.goal_engine
        lg, h, a = self.cb_league.currentData(), self.cb_home.currentText(), self.cb_away.currentText()
        if eng is None or not lg or not h or not a or h == a:
            return
        # Elle seçim de aynı uygunluk kontrolünden geçer (bağlam kurulamazsa sonuç uygun değildir)
        ctx = self.ctl.eligibility_context(eng)
        self._show(gated_goal_match(eng, ctx, lg, h, a, pd.Timestamp.today().normalize(), self.ctl.now()))

    def _reset_panel(self) -> None:
        """Model veya veri değişti: maç analizi paneli eski tahmin/uygunlukla kalmaz (kayıt kapalı)."""
        self._current = None
        self._current_verdict = None
        self._verdict_key = None
        self._current_decisions = []
        self.btn_record.setEnabled(False)
        for s in ("A", "B", "C"):
            self.cards[s].set("—", "Maç seçin (model veya veri değişti).")
        self.rel.setText("")
        self.cond_model.set_frame(pd.DataFrame())
        self.dec_model.set_frame(pd.DataFrame())
        self.sec_model.set_frame(pd.DataFrame())

    def _policy_key(self) -> tuple:
        """Uygunluğu değiştiren ayarlar: veri denetimi modu, onaylar ve kişisel kullanım beyanları (VERI-01)."""
        s = self.ctl.settings
        return s.veri_denetimi, tuple(sorted(s.source_consent)), tuple(sorted(s.declarations()))

    def _settings_changed(self) -> None:
        self._refresh_sources()
        if getattr(self, "_verdict_key", None) is not None and self._verdict_key != self._policy_key():
            self._reset_panel()  # paneldeki uygunluk eski mod/haklarla üretildi: gösterilmez, kaydedilmez

    def _panel_valid(self) -> bool:
        """Paneldeki tahmin hâlâ GÜNCEL motorun aynı lig durumundan ve güncel mod/haklarla mı üretildi?"""
        from ...eligibility import league_state_digest

        eng, p = self.ctl.goal_engine, getattr(self, "_current", None)
        if eng is None or not eng.trained or p is None or getattr(self, "_current_verdict", None) is None:
            return False
        if getattr(self, "_verdict_key", None) != self._policy_key():
            return False
        return bool(p.state_digest) and p.state_digest == league_state_digest(eng.states.get(p.league))

    def _show_blocked(self, v) -> None:
        """Tahmin üretilemeyen/gösterilemeyen maç: olasılık yerine somut neden, veri kesimi ve gereken düzeltme."""
        now = self.ctl.now()
        for s in ("A", "B", "C"):
            e = v.get(KEY_OF[s])
            label, text = display_label(e, v.display_codes(KEY_OF[s], now))
            self.cards[s].set("—", f"Tahmin yok · {label} · {text}")
        label, text = display_label(*_shown(v, now))
        self.rel.setText(
            f"<b>Veri durumu: {label}</b> — {text}"
            + ("" if v.canonical_id else f"<br>Takım adı eşleşmedi; aday kimlik {v.candidate_id} (kanonik maç "
                                          "kimliği değildir). Sahte takım veya olasılık atanmadı."))
        self.cond_model.set_frame(pd.DataFrame())
        self.sec_model.set_frame(pd.DataFrame())
        self._blocked_decision_table(v)
        self.used.setHtml(self._eligibility_html(v))

    def _blocked_decision_table(self, v) -> None:
        """Karar tablosu: olasılıktan türetilen hiçbir değer (aralık, gereken oran) gösterilmez; kayıt kapalı."""
        now = self.ctl.now()
        self._current_decisions = []
        self.dec_model.set_frame(pd.DataFrame([{
            "secim": MARKETS[k].name_tr, "durum": STATUS_TR["DATA_NOT_ELIGIBLE"],
            "gerekce": display_label(v.get(k), v.display_codes(k, now))[1]} for k in PRIMARY_YES]))
        self.btn_record.setEnabled(False)

    @staticmethod
    def _eligibility_html(v) -> str:
        e = v.first()
        if e is None:
            return "<b>Veri uygunluğu:</b> değerlendirilmedi (uygun değil)."
        st = e.state_scope or {}
        ev = (e.data_scope or {}).get("kapsam_kanitlari") or []
        def _araliklar(x) -> str:
            ar = x.get("gecmis_aralik_kaniti")
            if ar is None:
                return ""
            return "; geçmiş aralık kanıtı " + (", ".join(f"{a}–{b}" for a, b in ar) or "yok")

        kan = ", ".join(f"{x['kaynak']} {x['sezon']} ({'tam sezon takvimi' if x['tam'] else 'tam sezon doğrulanmadı'}"
                        f"{_araliklar(x)}, alınma {x['alinma'][:16]})" for x in ev) or "yok"
        rows = "".join(f"<br>· {k}: {x.status_label} — {', '.join(x.reasons) or 'neden yok'}"
                       for k, x in v.by_market.items())
        return (f"<b>Veri uygunluğu</b> (politika {e.policy_version}; değerlendirme {e.evaluated_at[:16]} UTC; "
                f"bilgi kesimi {e.info_cutoff} öncesi; veri kesimi {e.data_cutoff or '-'}):{rows}<br>"
                f"<b>Kullanılan model durumu:</b> lig durumu son maç {st.get('lig_durum_son_mac', '-')}, takımlar "
                f"{st.get('takim_durum_son_mac', '-')}, model eğitim kesimi {st.get('model_egitim_kesimi', '-')}<br>"
                f"<b>Kaynak kapsam kanıtı:</b> {kan}<br><b>Takım eşleme:</b> {e.team_mapping} · "
                f"<b>Gerekli alanlar:</b> {e.required_fields} · <b>Kimlik:</b> {e.candidate_id}"
                + ("" if e.canonical_id else " (aday kimlik, kanonik değil)"))

    def _show(self, v) -> None:
        self._current_verdict = v
        self._verdict_key = self._policy_key()
        p = v.prediction
        self._current = p
        eng = self.ctl.goal_engine
        now = self.ctl.now()
        self.btn_record.setEnabled(True)
        if p is None or eng is None or not v.any_usable(now):
            self._show_blocked(v)
            return
        for s in ("A", "B", "C"):
            key = KEY_OF[s]
            e = v.get(key)
            if not v.usable(key, now):
                label, text = display_label(e, v.display_codes(key, now))
                self.cards[s].set("—", f"Tahmin yok · {label} · {text}")
                continue
            prob = p.probs.get(s, np.nan)
            status = eng.status_text(key)
            self.cards[s].set(
                fmt_pct(prob),
                f"Belirsizlik (%80): {_iv(p, key)} · adil oran {fmt_num(1 / prob) if prob == prob and prob > 0 else '-'} · "
                f"lig taban oranı {fmt_pct(p.base_rates.get(s))} · model: "
                + ("sanal takip için doğrulandı" if status == "VALIDATED_FOR_PAPER_TRADING" else "DOĞRULANMADI")
                + f" · veri: {e.status_label}" + ("" if e.bet_ok else f" (bahis adayı değil: {e.lead_code})"),
            )
        if not v.all_usable(now):  # pazarlardan biri engelli: ortak olasılık ilişkileri gösterilmez
            self.rel.setText(f"<b>Veri durumu:</b> {_data_label(v, now)} — {_data_text(v, now)}")
            self.cond_model.set_frame(pd.DataFrame())
            self.sec_model.set_frame(pd.DataFrame())
            self._refresh_decisions()
            self.used.setHtml(self._eligibility_html(v))
            return
        a, bc = p.probs.get("A", np.nan), p.probs.get("BC", np.nan)
        cond = (a / bc) if bc and bc == bc and bc > 0 else np.nan
        self.rel.setText(
            f"<b>Pazarlar arası bağlantı:</b> A gerçekleşirse B ve C de gerçekleşir (A ⊆ B ∩ C). "
            f"P(B ve C birlikte) = <b>{fmt_pct(bc)}</b>; bunun içinde A'nın payı P(A | B∩C) = <b>{fmt_pct(cond)}</b>. "
            f"B ve C birlikte gerçekleşip A gerçekleşmeme olasılığı = <b>{fmt_pct(bc - a if bc == bc else np.nan)}</b>. "
            "Aynı maçtaki bu üç seçim bağımsız değildir; kupon/çeşitlendirme gibi değerlendirilmemelidir."
            + ("<br><span style='color:%s'>Veri notları: %s</span>" % (theme.WARNING, " · ".join(p.data_notes)) if p.data_notes else ""))
        conds = [("Ev sahibi ilk yarıda gol atar", p.probs.get("h1_home")), ("Deplasman ilk yarıda gol atar", p.probs.get("h1_away")),
                 ("Ev sahibi ikinci yarıda gol atar", p.probs.get("h2_home")), ("Deplasman ikinci yarıda gol atar", p.probs.get("h2_away"))]
        vals = [c[1] if c[1] is not None else np.nan for c in conds]
        weakest = int(np.nanargmin(vals)) if np.isfinite(vals).any() else -1
        self.cond_model.set_frame(pd.DataFrame([
            {"kosul": k, "p": v, "not": "en zayıf koşul" if i == weakest else ""} for i, (k, v) in enumerate(conds)]))
        self._refresh_decisions()
        man = eng.manifest
        val = ", ".join(f"{y}/{(y + 1) % 100:02d}" for y in eng.validation_years)
        self.used.setHtml(
            f"<b>Model:</b> {MODEL_VERSION} / {eng.variant} · özellik sürümü {FEATURE_VERSION} · sonuçlandırma kuralı {RULE_VERSION}<br>"
            f"<b>Eğitim:</b> {eng.trained_at} · veri kesimi {eng.data_cutoff} · {man.get('n_matches', 0):,} maç "
            f"({man.get('first_date')} – {man.get('last_date')}) · kaynak: {', '.join(man.get('sources', []))}<br>"
            f"<b>Zaman sıralı iç doğrulama sezonları:</b> {val}<br>"
            f"<b>Girdiler:</b> ilk yarı / ikinci yarı / maç sonu Poisson takım güçleri (yalnızca maçtan önceki günlerin sonuçları), "
            "lig ilk yarı gol payı, yakın dönem yarı bazlı gol sıklıkları, lig taban oranları. Bahis oranları, kadro, "
            "sakatlık, xG ve hava durumu verisi KULLANILMIYOR. (Kapalı testte 3,5 Üst için piyasa oranlarını kullanan "
            "maç sonucu motoru bu modelden daha iyiydi; ayrıntı: docs/GOL_PAZARLARI_MODEL_KARTI.md.)<br>"
            f"<b>Belirsizlik yöntemi:</b> {p.intervals.get('meta', {}).get('method', '-')}; "
            f"{p.intervals.get('meta', {}).get('draws', '-')} çekiliş, tohum {p.intervals.get('meta', {}).get('seed', '-')}. "
            "Bu aralık gerçek olasılığın kesin sınırı değildir.<br>"
            "<b>Zaman doğrulaması:</b> geçmiş özellikler yeniden oluşturulmuştur (yalnızca maç tarihi bilinir; o anda "
            "yayımlanmış olduğu doğrulanamaz).<br>" + self._eligibility_html(v))
        sec = [("Maç sonu KG Var", "FT_BTTS"), ("İlk yarı KG Var", "FH_BTTS"), ("İkinci yarı 1,5 Üst", "SH_O15"),
               ("Maç sonu 2,5 Üst", "FT_O25"), ("Maç sonu 4,5 Üst", "FT_O45")]
        self.sec_model.set_frame(pd.DataFrame([
            {"pazar": n, "p": p.probs.get(k, np.nan), "not": "Araştırma: doğrulama ve oran eşlemesi tamamlanmadı, öneri yok"}
            for n, k in sec]))

    def _refresh_decisions(self) -> None:
        p = self._current
        eng = self.ctl.goal_engine
        v = getattr(self, "_current_verdict", None)
        if p is None or eng is None:
            return
        now = self.ctl.now()
        if not self._panel_valid():  # model değişmiş: eski tahmin gösterilmez
            self._reset_panel()
            return
        if v is None or not v.any_usable(now):  # gün değişmiş veya veri uygun değil: türetilmiş değer gösterilmez
            if v is not None:
                self._blocked_decision_table(v)
            else:
                self.dec_model.set_frame(pd.DataFrame())
            return
        decs = decisions_for(p, eng, self.ctl.ledger_if_exists(), now, eligibility=v)
        self._current_decisions = decs
        self.btn_record.setEnabled(True)
        rows = []
        for d in decs:
            lo, hi = p.interval(d.market_key) if np.isfinite(d.p) else (None, None)
            rows.append({
                "secim": MARKETS[d.market_key].name_tr, "p": d.p,
                "aralik": f"%{100 * lo:.0f}–%{100 * hi:.0f}" if lo is not None else "-",
                "adil": d.fair_odds, "oran": d.odds, "basabas": d.breakeven, "ev": d.ev, "ev_safe": d.ev_safe,
                "min_oran": d.min_odds, "durum": STATUS_TR.get(d.status, d.status), "gerekce": " ".join(d.reasons),
            })
        self.dec_model.set_frame(pd.DataFrame(rows))

    def _save_odds(self) -> None:
        p = self._current
        if p is None:
            return
        now = self.ctl.now()
        quotes = []
        for key, sp in self.odds_spin.items():
            if sp.value() > 1.0:
                m = MARKETS[key]
                quotes.append(OddsQuote(p.event_id, key, m.period, m.line, m.selection, "manuel",
                                        self.ed_book.text().strip() or "belirtilmedi", float(sp.value()), now, now))
        if quotes:
            self.ctl.ledger.add_odds(quotes)
        self._refresh_decisions()
        self.refresh_ledger()

    def _record(self) -> None:
        p = self._current
        if p is None or not getattr(self, "_current_decisions", None):
            return
        if not self._panel_valid():  # model/veri değişti veya model yok: eski tahminle kayıt yapılmaz
            self._reset_panel()
            return
        # Kararlar kayıt anında aynı uygunluk sonucuyla YENİDEN üretilir (önceden hesaplanmış karar doğrudan yazılmaz)
        now = self.ctl.now()
        decs = decisions_for(p, self.ctl.goal_engine, self.ctl.ledger, now,
                             eligibility=getattr(self, "_current_verdict", None))
        record_decisions(self.ctl.ledger, p, decs, self.ctl.goal_engine, record_time=now)
        self.refresh_ledger()
        self.tabs.setCurrentIndex(4)

    # ============================================================ Veri kapsamı
    def _build_coverage(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(banner(
            "Üç katman ayrı gösterilir: <b>sonuç</b> (maç sonu ve ilk yarı skorları), <b>zenginleştirilmiş</b> (şut verisi) "
            "ve <b>oran</b> (ilgili pazarın gerçek oran kaydı). Sonuç geçmişi uzun olsa bile, üç pazarın hiçbiri için "
            "veri setinde gerçek oran yoktur; bu yüzden geçmiş getiri (ROI/CLV) hesaplanamaz. 'Beklenen' maç sayısı "
            "çift devreli lig varsayımıyla tahminidir."))
        row = QHBoxLayout()
        self.cb_cov_league = QComboBox()
        row.addWidget(QLabel("Lig:"))
        row.addWidget(self.cb_cov_league)
        row.addStretch(1)
        self.q_label = QLabel("")
        row.addWidget(self.q_label)
        lay.addLayout(row)
        self.cov_sum_model = DataFrameModel()
        self.cov_sum_model.formatters = {"league": league_name}
        self.cov_sum_model.headers = {
            "league": "Lig", "sezon_sonuc": "Sezon: sonuç", "sezon_ilk_yari": "Sezon: İY skoru (≥%90)",
            "sezon_A_orani": "Sezon: A gerçek oran", "sezon_B_orani": "Sezon: B gerçek oran",
            "sezon_C_orani": "Sezon: C gerçek oran", "ilk_sezon": "İlk sezon", "son_sezon": "Son sezon",
            "maç": "Maç", "A_pozitif": "A gerçekleşen",
        }
        v1, _ = make_table(self.cov_sum_model)
        v1.setMinimumHeight(240)
        lay.addWidget(section("Lig özeti"))
        lay.addWidget(v1)
        self.cov_model = DataFrameModel()
        self.cov_model.hidden = {"zaman_dogrulama"}
        self.cov_model.formatters = {"league": league_name}
        self.cov_model.headers = {
            "league": "Lig", "season": "Sezon", "takim": "Takım", "beklenen_tahmini": "Beklenen (tahmini)",
            "bulunan": "Bulunan", "ms_gecerli": "MS skoru", "iy_gecerli": "İY skoru geçerli", "iy_eksik": "İY eksik",
            "celiskili": "Çelişkili", "sut_verisi": "Şut verisi", "oran_2_5_gercek": "2,5 gerçek oran",
            "kaynak": "Kaynak", "lisans": "Lisans durumu",
            **{f"{s}_{k}": f"{s} {t}" for s in "ABC" for k, t in
               (("bilinen", "etiket bilinen"), ("pozitif", "gerçekleşen"), ("oran_gercek", "gerçek oran"))},
        }
        v2, self.cov_proxy = make_table(self.cov_model)
        v2.setMinimumHeight(320)
        lay.addWidget(section("Lig–sezon kapsam matrisi"))
        lay.addWidget(v2)
        lay.addWidget(section("Kaynaklar ve kullanım koşulları"))
        self.src_model = DataFrameModel()
        v3, _ = make_table(self.src_model, sortable=False)
        v3.setMinimumHeight(200)
        lay.addWidget(v3)
        self.cb_cov_league.currentIndexChanged.connect(self._filter_cov)
        return w

    def refresh_coverage(self) -> None:
        st = self.ctl.store
        self._refresh_sources()
        if not st.has_data:
            self.cov_model.set_frame(pd.DataFrame())
            self.cov_sum_model.set_frame(pd.DataFrame())
            return
        self._refresh_coverage_tables(st)

    def _refresh_sources(self) -> None:
        self.src_model.set_frame(pd.DataFrame([{
            "Kaynak": s.name, "Lisans özeti": s.license_summary, "Ticari kullanım": s.commercial_use,
            "Model eğitimi": s.model_training, "Maliyet": s.cost,
            "Durum": ("Entegre edilmedi" if k == "the-odds-api" else
                      # S4: yalnızca ayrı pilot klasöründe; ana uygulama bu kaynaktan sonuç okumaz
                      "Yalnızca S4 pilotu (köken doğrulaması zorunlu)" if k == "openfootball-sonuc" else
                      # S5: yalnızca ayrı GitHub arşivinde; ana uygulama bu kaynaklardan sonuç okumaz veya eğitmez
                      "Yalnızca GitHub arşivi (envanter; analiz ve eğitim kapalı)" if k == "football-datasets" else
                      "Yalnızca GitHub arşivi (araştırma amaçlı tarihsel inceleme; eğitim ve tahmin kapalı)"
                      if k == "statsbomb-acik" else
                      "Onay gerekmez" if not s.requires_consent else
                      ("ONAY YOK" if k not in self.ctl.settings.source_consent else
                       "Kullanıcı onayladı + kişisel kullanım beyanı" if k in self.ctl.settings.declarations() else
                       "Kullanıcı onayladı (beyan yok)")),
        } for k, s in SOURCES.items()]))

    def _refresh_coverage_tables(self, st) -> None:
        odds_counts = {}
        cov = coverage_matrix(st.matches, self.ctl.settings.source_consent, odds_counts)
        self._cov = cov
        self.cov_sum_model.set_frame(coverage_summary(cov))
        self.q_label.setText(f"Karantinadaki kayıt: {len(quarantine(st.matches))}")
        cur = self.cb_cov_league.currentData()
        self.cb_cov_league.blockSignals(True)
        self.cb_cov_league.clear()
        self.cb_cov_league.addItem("Tümü", None)
        for code in [c for c in LEAGUES if c in set(cov["league"])]:
            self.cb_cov_league.addItem(league_name(code), code)
        i = self.cb_cov_league.findData(cur)
        self.cb_cov_league.setCurrentIndex(max(i, 0))
        self.cb_cov_league.blockSignals(False)
        self._filter_cov()

    def _filter_cov(self) -> None:
        cov = getattr(self, "_cov", pd.DataFrame())
        lg = self.cb_cov_league.currentData()
        self.cov_model.set_frame(cov[cov["league"] == lg] if (lg and not cov.empty) else cov)

    # ========================================================= Model doğrulama
    def _build_validation(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.val_text = QLabel("")
        self.val_text.setWordWrap(True)
        self.val_text.setTextFormat(Qt.RichText)
        lay.addWidget(self.val_text)
        self.val_model = DataFrameModel()
        self.val_model.formatters = {k: (lambda v: fmt_num(v, 4)) for k in ("LL model", "LL taban", "Δ LL", "Δ alt", "Δ üst")}
        self.val_model.formatters.update({"Taban oran": fmt_pct, "Brier becerisi": fmt_signed_pct, "AP model": fmt_num,
                                          "AP taban": fmt_num, "Kal. eğim": fmt_num, "ECE": lambda v: fmt_num(v, 4)})
        vv, _ = make_table(self.val_model, sortable=False)
        vv.setMinimumHeight(170)
        lay.addWidget(vv)
        row = QHBoxLayout()
        self.cb_cal = QComboBox()
        for s, name in NAMES.items():
            self.cb_cal.addItem(f"{s}: {name}", s)
        self.lbl_cal = QLabel("Kalibrasyon eğrisi:")
        row.addWidget(self.lbl_cal)
        row.addWidget(self.cb_cal)
        row.addStretch(1)
        lay.addLayout(row)
        self.cal_chart = ChartCanvas(7, 4)
        self.cal_chart.setMinimumHeight(380)
        lay.addWidget(self.cal_chart)
        self.cb_cal.currentIndexChanged.connect(self._plot_cal)
        return w

    def refresh_validation(self) -> None:
        eng = self.ctl.goal_engine
        has = bool(eng is not None and eng.validation)
        for w in (self.cal_chart, self.cb_cal, self.lbl_cal):
            w.setVisible(has)
        if eng is None:
            self.val_text.setText("Gol modeli eğitilmedi; doğrulama sonuçları eğitimden sonra burada görünür.")
            self.val_model.set_frame(pd.DataFrame())
            return
        if not eng.validation:
            self.val_text.setText(
                "<b>Zaman sıralı doğrulama yapılamadı:</b> eldeki veride, test edilecek sezondan önce yeterli eğitim "
                "maçı yok (sezon başına en az 2.000 ilk yarı skorlu eğitim maçı gerekir). Bu yüzden üç pazarın "
                "tamamı <b>DOĞRULANMADI</b> durumundadır ve öneri motoru avantaj adayı üretmez. Daha fazla lig/sezon "
                "ekleyip modeli yeniden eğitin.")
            self.val_model.set_frame(pd.DataFrame())
            return
        yrs = ", ".join(f"{y}/{(y + 1) % 100:02d}" for y in eng.validation_years)
        self.val_text.setText(
            f"<b>Zaman sıralı iç doğrulama</b> ({yrs}): her sezon yalnızca önceki sezonlarla eğitilen modelle tahmin edildi. "
            f"Referans: ligin geçmiş taban oranı. Kural: {eng.validation.get('rule', '') or ''}"
            "Doğrulama yalnızca olasılık kalitesini ölçer; gerçek oranlı getiri doğrulaması yapılamaz (oran verisi yok). "
            "Ayrıntılı geliştirme/test raporu: reports/ klasörü.")
        rows = []
        for key in PRIMARY_YES:
            r = eng.validation.get(key, {})
            m = r.get("modeller", {}).get(eng.variant, {})
            b = r.get("modeller", {}).get("M0_taban", {})
            if not m:
                continue
            base_ll = m["log_loss"] - m["ll_fark_ref"]
            rows.append({
                "Pazar": MARKETS[key].name_tr, "Maç": r["n"], "Pozitif": r["pozitif"], "Taban oran": r["taban_oran"],
                "LL model": m["log_loss"], "LL taban": base_ll, "Δ LL": m["ll_fark_ref"], "Δ alt": m["ll_fark_alt"],
                "Δ üst": m["ll_fark_ust"], "Brier becerisi": m["brier_skill"], "AP model": m["ap"], "AP taban": b.get("ap", np.nan),
                "Kal. eğim": m["kal_egim"], "ECE": m["ece"], "Statü": eng.status_text(key),
            })
        self.val_model.set_frame(pd.DataFrame(rows))
        self._plot_cal()

    def _plot_cal(self) -> None:
        eng = self.ctl.goal_engine
        c = self.cal_chart
        c.reset("Kalibrasyon: tahmin edilen ve gerçekleşen (eşit örnekli bölmeler, %95 Wilson aralığı)")
        if eng is None or not eng.validation:
            c.finish()
            return
        key = KEY_OF[self.cb_cal.currentData()]
        bins = eng.validation.get(key, {}).get("modeller", {}).get(eng.variant, {}).get("kalibrasyon", [])
        if not bins:
            c.finish()
            return
        x = np.array([b["tahmin"] for b in bins])
        y = np.array([b["gercek"] for b in bins])
        lo = np.array([b["alt"] for b in bins])
        hi = np.array([b["ust"] for b in bins])
        top = max(x.max(), hi.max()) * 1.1
        c.ax.plot([0, top], [0, top], color=theme.MUTED, linewidth=1, label="Kusursuz kalibrasyon")
        c.ax.vlines(x, lo, hi, color=theme.SERIES_1, linewidth=1)
        c.ax.plot(x, y, color=theme.SERIES_1, linewidth=2, label="Model")
        c.ax.plot(x, y, "o", color=theme.SERIES_1, markersize=8, markeredgecolor=theme.SURFACE, markeredgewidth=2)
        c.ax.set_xlim(0, top)
        c.ax.set_ylim(0, top)
        c.ax.legend(frameon=False, labelcolor=theme.TEXT, fontsize=8, loc="upper left")
        c.set_hover(x, [("Gerçekleşen", y)], lambda v: f"Tahmin: %{100 * v:.1f}", lambda v: f"%{100 * v:.1f}")
        c.finish()

    # ============================================================== Sanal takip
    def _build_ledger(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(banner(
            "Sanal takip gerçek bahis değildir. Her kayıt karar anında değiştirilemez biçimde saklanır; sonuç sonradan ayrı "
            "olay olarak eklenir. İleriye dönük sanal performans, geçmiş testlerden ayrı gösterilir. Başarılı bir sanal "
            "dönem gerçek parayla kazanç garantisi değildir."))
        self.led_sum = QLabel("")
        self.led_sum.setWordWrap(True)
        lay.addWidget(self.led_sum)
        row = QHBoxLayout()
        b1 = QPushButton("Sonuçları veriden güncelle")
        b1.clicked.connect(self._settle)
        b2 = QPushButton("Kayıt zincirini doğrula")
        b2.clicked.connect(self._verify)
        b3 = QPushButton("CSV dışa aktar")
        b3.clicked.connect(self._export)
        for b in (b1, b2, b3):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.led_model = DataFrameModel()
        lv, _ = make_table(self.led_model)
        lv.setMinimumHeight(520)
        lay.addWidget(lv)
        return w

    def _ledger_frame(self) -> pd.DataFrame:
        return pd.DataFrame(ledger_rows(self.ctl.ledger_if_exists()))

    def refresh_ledger(self) -> None:
        df = self._ledger_frame()
        self.led_model.set_frame(df)
        if df.empty:
            self.led_sum.setText("Henüz sanal kayıt yok. Maç analizi sekmesinden kararları kaydedebilirsiniz.")
            return
        s = self.ctl.ledger.summary()
        y = f"{100 * s['yield']:+.1f}%" if s["yield"] is not None else "hesaplanamıyor"
        self.led_sum.setText(
            f"{s['kayit']} kayıt · {s['sanal_bahis']} sanal bahis (yalnızca avantaj adayları) · {s['sonuclanan']} sonuçlandı · "
            f"{s['bekleyen_veya_iade']} bekleyen/iade (paydaya girmez) · net {s['net']:+.2f} birim · yield {y}")

    def _settle(self) -> None:
        led = self.ctl.ledger_if_exists()
        if led is None:
            self.led_sum.setText("Henüz sanal kayıt yok.")
            return
        res = settle_pending(led, self.ctl.store.matches)
        self.refresh_ledger()
        self.led_sum.setText(self.led_sum.text() + f"  ·  güncelleme: {res['sonuclanan']} sonuçlandı, {res['bekleyen']} bekliyor")

    def _verify(self) -> None:
        led = self.ctl.ledger_if_exists()
        if led is None:
            self.led_sum.setText("Henüz sanal kayıt yok.")
            return
        ok, msg = led.verify_chain()
        self.led_sum.setText(("✔ " if ok else "✘ ") + msg)

    def _export(self) -> None:
        rows = ledger_rows(self.ctl.ledger_if_exists())
        if not rows:
            return
        path, _ = QFileDialog.getSaveFileName(self, "CSV kaydet", "sanal_takip.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write(ledger_csv(rows))

    # ================================================================== genel
    def refresh_all(self) -> None:
        eng = self.ctl.goal_engine
        if eng is None:
            err = self.ctl.goal_load_error
            self.status_banner.setText(
                "Gol pazarları modeli eğitilmedi." + (f" ({err})" if err and "yok" not in err else "")
                + " Veriler indirildikten sonra 'Gol modelini eğit' butonunu kullanın.")
        else:
            st = " · ".join(f"{s}: {'doğrulandı (sanal takip)' if eng.validated.get(KEY_OF[s]) else 'DOĞRULANMADI'}"
                            for s in ("A", "B", "C"))
            self.status_banner.setText(
                f"Model durumu — {st}. Bu pazarlar için geçmiş gerçek oran verisi olmadığından kârlılık doğrulanamaz; "
                "'avantaj adayı' yalnızca girdiğiniz güncel gerçek oranla ve tüm kontroller geçilirse oluşur.")
        self.btn_train.setEnabled(self.ctl.store.has_data and not self.ctl.busy)
        self.refresh_scan()
        self.refresh_coverage()
        self.refresh_validation()
        self.refresh_ledger()
