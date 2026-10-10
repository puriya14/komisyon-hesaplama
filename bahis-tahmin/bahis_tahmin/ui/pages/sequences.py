"""Dizi araştırması: olay zaman çizgisi (geçmiş inceleme), benzer diziler (maç öncesi), örüntü doğrulama,
anomali incelemesi ve veri/yöntem.

Kurallar (docs/DIZI_ARASTIRMA_SOZLESMESI.md §13):
  * Geçmiş inceleme ekranı olay SONRASI bilgileri içerebilir; açıkça "olay seçimli, tahmin değil" etiketlidir.
  * Maç öncesi ekranı yalnızca karar anından önce bilinen bilgileri gösterir; POST_EVENT alanı yoktur.
  * Örüntü statüleri yalnızca dondurulmuş araştırma kaydından okunur; şike/kulüp/hakem statüsü değildir.
  * Anomali sayfası ayrıdır; karar motoruna, sanal takibe ve örüntü statüsüne bağlantısı yoktur.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ...goals.markets import HTFT_KEYS, TEAM_TARGETS
from ...sequences import config as C
from ...sequences.aliases import MANUAL_ALIASES, REJECTED
from ..widgets import DataFrameModel, banner, fmt_num, fmt_pct, make_table, section
from .base import Page

TARGET_LABELS = {
    "IY_GERIDE_MS_GALIP": "İlk yarıyı geride kapatıp kazanma",
    "IY_ONDE_MS_MAGLUP": "İlk yarıyı önde kapatıp kaybetme",
    "IY_BERABERE_MS_GALIP": "İlk yarı berabere → kazanma",
    "IY_ONDE_MS_BERABERE": "İlk yarıyı önde kapatıp berabere",
    "IY_GERIDE_MS_BERABERE": "İlk yarıyı geride kapatıp berabere",
    "IY_BERABERE_MS_MAGLUP": "İlk yarı berabere → kaybetme",
    "IY_ONDE_MS_GALIP": "İlk yarıyı önde kapatıp kazanma",
    "IY_BERABERE_MS_BERABERE": "İlk yarı berabere → berabere",
    "IY_GERIDE_MS_MAGLUP": "İlk yarıyı geride kapatıp kaybetme",
}
RES_TR = {"G": "G", "B": "B", "M": "M"}
HISTORICAL_NOTE = ("GEÇMİŞ İNCELEME — olay seçimli, tahmin değil. Bu ekran olayların SONRASINI da gösterir; bu bilgiler "
                   "maç öncesi tahmin ekranına taşınmaz. Bir olayın tekrar etmesi neden-sonuç veya manipülasyon kanıtı değildir.")
PREMATCH_NOTE = ("MAÇ ÖNCESİ — yalnızca karar anından (maç günü 00:00) önce bilinen bilgiler. Benzerlik yüzdesi bir "
                 "olasılık değildir; başarılı ve başarısız benzer örnekler birlikte gösterilir.")


def _score(a, b) -> str:
    return f"{int(a)}-{int(b)}" if np.isfinite(a) and np.isfinite(b) else "?"


def _date(v) -> str:
    return pd.Timestamp(v).strftime("%d.%m.%Y")


class SequencesPage(Page):
    title = "Dizi Araştırması"
    subtitle = ("Maç sonuçlarının çevresindeki diziler, olay öncesi/sonrası ve tekrarlar. Araştırma statüsündedir: "
                "ana tahmin modellerini değiştirmez; yalnızca kullanılmamış dönemde doğrulanan ek katkı raporlanır.")

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        self.status = banner("", "warn")
        self.body.addWidget(self.status)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_timeline(), "Olay zaman çizgisi (geçmiş)")
        self.tabs.addTab(self._build_similar(), "Benzer diziler (maç öncesi)")
        self.tabs.addTab(self._build_patterns(), "Örüntü doğrulama")
        self.tabs.addTab(self._build_anomaly(), "Anomali incelemesi")
        self.tabs.addTab(self._build_method(), "Veri ve yöntem")
        self.tabs.setMinimumHeight(1000)
        self.body.addWidget(self.tabs)
        self.body.addWidget(QLabel("18+ · Bu ekran araştırma amaçlıdır; bahis önerisi veya kazanç garantisi değildir."))
        controller.sequenceChanged.connect(self.refresh_all)
        controller.dataChanged.connect(self._data_changed)
        self.refresh_all()

    def on_show(self) -> None:
        self.ctl.ensure_sequence_table()

    def _data_changed(self) -> None:
        self.refresh_all()
        if self.isVisible():
            self.ctl.ensure_sequence_table()

    # ======================================================= A: zaman çizgisi
    def _build_timeline(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(banner(HISTORICAL_NOTE, "warn"))
        row = QHBoxLayout()
        self.cb_league = QComboBox()
        self.cb_team = QComboBox()
        self.cb_team.setMinimumWidth(220)
        self.cb_target = QComboBox()
        for k in TEAM_TARGETS:
            self.cb_target.addItem(f"Takım: {TARGET_LABELS[k]}", ("target", k))
        for k in HTFT_KEYS:
            self.cb_target.addItem(f"Ham İY/MS {k[5]}/{k[7]}", ("htft", k))
        row.addWidget(QLabel("Lig:"))
        row.addWidget(self.cb_league)
        row.addWidget(QLabel("Takım:"))
        row.addWidget(self.cb_team)
        row.addWidget(QLabel("Olay:"))
        row.addWidget(self.cb_target)
        row.addStretch(1)
        lay.addLayout(row)
        vrow = QHBoxLayout()
        self.rb_league = QRadioButton("Lig maçları")
        self.rb_league.setChecked(True)
        self.rb_all = QRadioButton("Tüm resmî maçlar")
        self.rb_all.setEnabled(False)
        self.rb_all.setToolTip("DATA_QUALITY_BLOCKED: " + C.DATA_QUALITY_BLOCKED_ITEMS["TUM_RESMI_MACLAR"])
        vrow.addWidget(QLabel("Görünüm:"))
        vrow.addWidget(self.rb_league)
        vrow.addWidget(self.rb_all)
        vrow.addWidget(QLabel("(tüm resmî maçlar: DATA_QUALITY_BLOCKED — kupa/Avrupa maçı verisi yok)"))
        vrow.addStretch(1)
        lay.addLayout(vrow)
        self.ev_summary = QLabel("")
        self.ev_summary.setWordWrap(True)
        self.ev_summary.setTextFormat(Qt.RichText)
        lay.addWidget(self.ev_summary)
        self.ev_model = DataFrameModel()
        self.ev_model.hidden = {"_row"}
        self.ev_model.headers = {"tarih": "Tarih", "sezon": "Sezon", "rakip": "Rakip", "yer": "Yer", "iy": "İY (ev-dep)",
                                 "ms": "MS (ev-dep)", "takim": "Takım İY→MS", "mac_ara": "Önceki olaydan (maç)",
                                 "gun_ara": "Önceki olaydan (gün)", "sezon_gecisi": "Sezon geçişi"}
        self.ev_model.formatters = {"mac_ara": lambda v: "-" if v != v else str(int(v)),
                                    "gun_ara": lambda v: "-" if v != v else str(int(v))}
        self.ev_view, self.ev_proxy = make_table(self.ev_model, sortable=False)
        self.ev_view.setMinimumHeight(260)
        self.ev_view.clicked.connect(self._show_card)
        lay.addWidget(self.ev_view)
        lay.addWidget(section("Olay kartı"))
        self.card_tabs = QTabWidget()
        self.card_models = {}
        for key, title in (("PRE_EVENT", "Öncesi (son 5 / 10)"), ("EVENT_OUTCOME", "Olay"), ("POST_EVENT", "Sonrası (1 / 3 / 5)"),
                           ("RAKIP_PRE_EVENT", "Rakibin öncesi")):
            if key == "EVENT_OUTCOME":
                self.card_event = QTextBrowser()
                self.card_tabs.addTab(self.card_event, title)
                continue
            box = QWidget()
            bl = QVBoxLayout(box)
            state = QLabel("")
            state.setWordWrap(True)
            model = DataFrameModel()
            model.headers = _CARD_HEADERS
            model.hidden = {"row_id", "event_id", "team", "season", "league", "source", "time", "has_stats", "red_for",
                            "red_against", "onceki_mac", "sonraki_mac", "saat_dilimi", "s0_guc", "s0_guc_rakip", "htft"}
            view, _ = make_table(model, sortable=False)
            view.setMinimumHeight(260)
            bl.addWidget(state)
            bl.addWidget(view)
            self.card_models[key] = (state, model)
            self.card_tabs.addTab(box, title)
        self.card_tabs.setMinimumHeight(330)
        lay.addWidget(self.card_tabs)
        self.cb_league.currentIndexChanged.connect(self._fill_teams)
        self.cb_team.currentIndexChanged.connect(self.refresh_events)
        self.cb_target.currentIndexChanged.connect(self.refresh_events)
        return w

    def _fill_leagues(self) -> None:
        tm = self.ctl.seq_table
        cur = self.cb_league.currentData()
        self.cb_league.blockSignals(True)
        self.cb_league.clear()
        if tm is not None:
            from ...data.leagues import LEAGUES, league_name

            for code in [c for c in LEAGUES if c in set(tm["league"])]:
                self.cb_league.addItem(league_name(code), code)
        i = self.cb_league.findData(cur)
        self.cb_league.setCurrentIndex(max(i, 0))
        self.cb_league.blockSignals(False)
        self._fill_teams()

    def _fill_teams(self) -> None:
        tm = self.ctl.seq_table
        lg = self.cb_league.currentData()
        cur = self.cb_team.currentText()
        self.cb_team.blockSignals(True)
        self.cb_team.clear()
        if tm is not None and lg:
            teams = tm.loc[tm["league"] == lg].groupby("team")["date"].max().sort_values(ascending=False)
            self.cb_team.addItems(sorted(teams.index))
            i = self.cb_team.findText(cur)
            self.cb_team.setCurrentIndex(max(i, 0))
        self.cb_team.blockSignals(False)
        self.refresh_events()

    def refresh_events(self) -> None:
        from ...sequences.timeline import team_events

        tm = self.ctl.seq_table
        team = self.cb_team.currentText()
        if tm is None or not team:
            self.ev_model.set_frame(pd.DataFrame())
            self.ev_summary.setText("Takım seçin." if tm is not None else "")
            return
        kind, key = self.cb_target.currentData()
        ev = team_events(tm, team, target=key if kind == "target" else None, htft_key=key if kind == "htft" else None)
        allm = tm[(tm["team"] == team) & tm["in_seq"]]
        rows = []
        for i, r in ev.iterrows():
            home = bool(r["is_home"])
            rows.append({
                "_row": int(i), "tarih": _date(r["date"]), "sezon": r["season"], "rakip": r["opponent"],
                "yer": "Ev" if home else "Dep",
                "iy": _score(*((r["gf_ht"], r["ga_ht"]) if home else (r["ga_ht"], r["gf_ht"]))),
                "ms": _score(*((r["gf_ft"], r["ga_ft"]) if home else (r["ga_ft"], r["gf_ft"]))),
                "takim": f"{r['ht_res'] or '?'}→{r['ft_res'] or '?'}", "mac_ara": r["onceki_olaydan_mac"],
                "gun_ara": r["onceki_olaydan_gun"], "sezon_gecisi": "evet" if r["sezon_gecisi"] else "",
            })
        self.ev_model.set_frame(pd.DataFrame(rows))
        tail = ev.attrs.get("censored_tail", {})
        known = allm["cell"] >= 0 if kind == "target" else allm["htft"].notna()
        rate = len(ev) / max(int(known.sum()), 1)
        label = TARGET_LABELS.get(key, key)
        self.ev_summary.setText(
            f"<b>{team}</b> · {label}: <b>{len(ev)}</b> olay / {int(known.sum())} sonucu bilinen lig maçı "
            f"(%{100 * rate:.1f}; tanımlayıcı, olay seçimli). Son olay: {tail.get('son_olay_tarihi') or '-'} · "
            f"açık (sansürlü) aralık: <b>{tail.get('acik_aralik_mac', '-')}</b> maç, gözlem sonu nedeni: "
            f"{tail.get('bitis_nedeni') or '-'}. Açık aralık 'olmayacak' anlamına gelmez; 'uzun süredir olmadı, olmalı' "
            "kuralı kurulmaz.")
        for state, model in self.card_models.values():
            state.setText("")
            model.set_frame(pd.DataFrame())
        self.card_event.setHtml("")

    def _show_card(self, index) -> None:
        from ...sequences.timeline import event_card

        tm = self.ctl.seq_table
        src = self.ev_proxy.mapToSource(index)
        row = int(self.ev_model.frame.iloc[src.row()]["_row"])
        card = event_card(tm, row, data_meta=self.ctl.store.meta)
        k, e = card["kimlik"], card["EVENT_OUTCOME"]
        src_ = card["kaynak"]
        self.card_event.setHtml(
            f"<b>{k['takim']}</b> ({'ev' if k['ev_sahibi'] else 'deplasman'}) – {k['rakip']} · {k['tarih']} · {k['lig']} "
            f"{k['sezon']}<br>İY (ev-dep) {e['iy_ev_dep']} · MS (ev-dep) {e['ms_ev_dep']} · ham İY/MS {e['iy_ms_ham'] or 'bilinmiyor'} · "
            f"takım perspektifi {e['takim_iy'] or '?'}→{e['takim_ms'] or '?'}"
            + (" · <b>hükmen olabilir (sonuç karar anında bilinmiyordu)</b>" if e["hukmen_olabilir"] else "")
            + f"<br><br><b>Kaynak:</b> {src_['kaynak']} · veri güncelleme {src_['veri_guncelleme'] or '-'} · yayımlanma zamanı: "
            f"{src_['yayimlanma_zamani']} · kimlik eşlemesi: {src_['esleme']}"
            f"<br><b>Kapsam:</b> {card['kapsam']['alanlar']}. Yok: {card['kapsam']['yok']}. Tüm resmî maçlar görünümü: "
            f"{card['kapsam']['gorunum_tum_resmi']}. Event kimliği: {k['event_id']}")
        for key, (state, model) in self.card_models.items():
            parts, frames = [], []
            for name, blk in card[key].items():
                parts.append(f"{name.replace('_', ' ')}: {blk['durum']}")
                df = pd.DataFrame(blk["maclar"])
                if not df.empty:
                    df.insert(0, "pencere", name.replace("_", " "))
                    frames.append(df)
            state.setText(" · ".join(parts))
            model.set_frame(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())

    # ======================================================= B: benzer diziler
    def _build_similar(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(banner(PREMATCH_NOTE, "banner"))
        self.sim_text = QLabel("")
        self.sim_text.setWordWrap(True)
        self.sim_text.setTextFormat(Qt.RichText)
        lay.addWidget(self.sim_text)
        self.sim_model = DataFrameModel()
        sv, _ = make_table(self.sim_model)
        sv.setMinimumHeight(420)
        lay.addWidget(sv)
        lay.addStretch(1)
        return w

    # ======================================================= C: örüntü doğrulama
    def _build_patterns(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(banner("Statüler örüntü statüsüdür (" + ", ".join(C.STATUSES) + "); şike, kulüp, oyuncu veya hakem "
                             "statüsü değildir. p-değeri örüntünün doğru olma olasılığı değildir.", "banner"))
        self.pat_text = QLabel("")
        self.pat_text.setWordWrap(True)
        self.pat_text.setTextFormat(Qt.RichText)
        lay.addWidget(self.pat_text)
        self.pat_model = DataFrameModel()
        pv, _ = make_table(self.pat_model)
        pv.setMinimumHeight(360)
        lay.addWidget(pv)
        self.pat_card = QTextBrowser()
        self.pat_card.setMinimumHeight(320)
        lay.addWidget(self.pat_card)
        return w

    # ======================================================= D: anomali
    def _build_anomaly(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(banner(
            "Anomali incelemesi tahminden AYRIDIR. Anomali puanı (bit cinsinden sürpriz) suç veya şike olasılığı değildir; "
            "kulüp, oyuncu veya hakem etiketlenmez; takım/lig bazında sıralama yapılmaz. Kaydın olmaması 'temiz' anlamına "
            "gelmez. Bu sayfanın karar motoruna, sanal takibe veya örüntü statülerine bağlantısı yoktur.", "warn"))
        self.an_text = QLabel("")
        self.an_text.setWordWrap(True)
        lay.addWidget(self.an_text)
        self.an_model = DataFrameModel()
        av, _ = make_table(self.an_model)
        av.setMinimumHeight(420)
        lay.addWidget(av)
        return w

    # ======================================================= E: veri ve yöntem
    def _build_method(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.meth_text = QTextBrowser()
        self.meth_text.setMinimumHeight(300)
        lay.addWidget(self.meth_text)
        lay.addWidget(section("Eksik (veri boşluklu) lig-sezonlar — bu sezonlara dokunan pencereler tanımsızdır"))
        self.cov_model = DataFrameModel()
        cv, _ = make_table(self.cov_model)
        cv.setMinimumHeight(300)
        lay.addWidget(cv)
        return w

    def refresh_method(self) -> None:
        tm = self.ctl.seq_table
        blocked = "".join(f"<li><b>{k}</b>: {v}</li>" for k, v in C.DATA_QUALITY_BLOCKED_ITEMS.items())
        splits = (tm.attrs.get("intra_season_splits", {}) if tm is not None else {})
        manual = "".join(f"<li>{c}: {a} → {b[0]} ({b[1]})</li>" for (c, a), b in MANUAL_ALIASES.items())
        auto = "".join(f"<li>{k.replace('|', ': ')} → {v} (sezon ortası ayrılma, otomatik kural)</li>" for k, v in splits.items())
        self.meth_text.setHtml(
            f"<b>Sözleşme:</b> {C.CONTRACT_VERSION} ({C.CONTRACT_DATE}) · parametre özeti {C.config_hash()[:16]}… · "
            "ayrıntı: docs/DIZI_ARASTIRMA_SOZLESMESI.md<br>"
            f"<b>Dönemler:</b> {', '.join(f'{k} {a}/{(a + 1) % 100:02d}–{b}/{(b + 1) % 100:02d}' for k, (a, b) in C.PERIODS.items())}; "
            f"ileriye dönük: {C.FORWARD_FROM} sonrası<br>"
            f"<b>İncelenemeyenler (DATA_QUALITY_BLOCKED):</b><ul>{blocked}</ul>"
            f"<b>Takım kimliği eşlemesi</b> (yalnızca bu modül):<ul>{auto}{manual}</ul>"
            f"Bilerek eşlenmeyen (ardıl/yeniden kurulmuş kulüpler): {', '.join(REJECTED)}<br>"
            + (f"<b>Hükmen olabilir satırlar:</b> {tm.attrs.get('n_awarded', 0)} maç (sonuç karar anında bilinmiyor sayılır) · "
               f"veri sonu: {tm.attrs.get('data_end')}" if tm is not None else ""))
        if tm is None:
            self.cov_model.set_frame(pd.DataFrame())
            return
        from ...sequences.timeline import coverage_report

        cov = coverage_report(tm)
        self.cov_model.set_frame(cov[~cov["tam"]].reset_index(drop=True))

    # ================================================================ genel
    def refresh_all(self) -> None:
        tm = self.ctl.seq_table
        if not self.ctl.store.has_data:
            self.status.setText("Veri yok. Önce Veri sayfasından verileri indirin.")
        elif tm is None and self.ctl.seq_error:
            self.status.setText(f"Takım-maç tablosu kurulamadı: {self.ctl.seq_error}")
        elif tm is None:
            self.status.setText("Takım-maç tablosu hazırlanıyor (sayfa açıldığında arka planda kurulur)...")
        else:
            res = self.ctl.seq_results
            self.status.setText(
                f"{len(tm):,} takım-maç satırı · {tm['team'].nunique()} takım · veri sonu {tm.attrs.get('data_end')} · "
                + ("araştırma sonuçları: " + res.get("manifest", {}).get("zaman_utc", "?") if res else
                   "araştırma sonuçları yok (python -m bahis_tahmin dizi-arastir)"))
        self._fill_leagues()
        self.refresh_method()
        self.refresh_research()

    def refresh_research(self) -> None:
        """Benzer diziler, örüntü kartları ve anomaliler: yalnızca dondurulmuş araştırma sonuçlarından."""
        res = self.ctl.seq_results
        empty = ("Araştırma henüz çalıştırılmadı. Ön-kayıtlı araştırma komut satırından çalıştırılır: "
                 "<code>python -m bahis_tahmin dizi-arastir</code>. Sonuçlar burada gösterilir; gerçek veri yoksa örnek "
                 "sonuç gösterilmez.")
        if not res:
            for lbl, model in ((self.sim_text, self.sim_model), (self.pat_text, self.pat_model), (self.an_text, self.an_model)):
                lbl.setText(empty)
                model.set_frame(pd.DataFrame())
            self.pat_card.setHtml("")
            return
        self._render_patterns(res)
        self._render_anomalies(res)
        self.sim_text.setText(res.get("benzer_diziler_notu", "Maç öncesi benzer diziler için yaklaşan maç seçimi gerekir."))

    def _render_patterns(self, res: dict) -> None:
        pats = pd.DataFrame(res.get("oruntuler", []))
        fam = res.get("aileler", {})
        self.pat_text.setText(
            f"Denenen ham hipotez: <b>{res.get('hipotez_ham', '-')}</b> · tekil: <b>{res.get('hipotez_tekil', '-')}</b> · "
            f"referans tekrarı R={res.get('R', '-')} · kalibrasyon kapısı: {res.get('kalibrasyon_kapisi', '-')} · "
            f"plasebo: {fam.get('F7', {}).get('ozet', '-')}")
        if pats.empty:
            self.pat_model.set_frame(pd.DataFrame())
            self.pat_card.setHtml("Keşif döneminde aile bazlı hata kontrolünden geçen örüntü yok. Bu da geçerli bir sonuçtur.")
            return
        show = [c for c in ("hedef", "kosul", "statu", "lift", "lift_lo", "lift_hi", "p_adj", "n", "O", "E_adj") if c in pats]
        df = pats[show].copy()
        self.pat_model.headers = {"hedef": "Hedef", "kosul": "Koşul", "statu": "Statü", "lift": "O/E", "lift_lo": "Alt",
                                  "lift_hi": "Üst", "p_adj": "FWER düz. p", "n": "n", "O": "Gözlenen", "E_adj": "Beklenen (S0)"}
        self.pat_model.formatters = {"lift": fmt_num, "lift_lo": fmt_num, "lift_hi": fmt_num, "p_adj": lambda v: fmt_num(v, 3),
                                     "E_adj": lambda v: fmt_num(v, 1)}
        self.pat_model.set_frame(df)
        self.pat_card.setHtml(res.get("oruntu_karti_html", ""))

    def _render_anomalies(self, res: dict) -> None:
        an = pd.DataFrame(res.get("anomaliler", []))
        summ = res.get("anomali_ozeti", {})
        self.an_text.setText(f"Özet (yalnızca tür/durum/dönem sayıları): {summ}" if summ else "Anomali kaydı yok.")
        self.an_model.set_frame(an)


_CARD_HEADERS = {"pencere": "Pencere", "date": "Tarih", "opponent": "Rakip", "is_home": "Ev?", "gf_ht": "İY attığı",
                 "ga_ht": "İY yediği", "gf_ft": "MS attığı", "ga_ft": "MS yediği", "ht_res": "İY", "ft_res": "MS",
                 "awarded": "Hükmen?", "lig_arasi_gun": "Lig arası gün", "has_odds": "Oran var"}
