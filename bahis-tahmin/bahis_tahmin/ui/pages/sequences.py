"""Dizi araştırması: olay zaman çizgisi (geçmiş inceleme), benzer diziler (maç öncesi), örüntü doğrulama,
anomali incelemesi ve veri/yöntem.

Kurallar (docs/DIZI_ARASTIRMA_SOZLESMESI.md §13):
  * Geçmiş inceleme ekranı olay SONRASI bilgileri içerebilir; açıkça "olay seçimli, tahmin değil" etiketlidir.
  * Maç öncesi ekranı yalnızca karar anından önce bilinen bilgileri gösterir; POST_EVENT alanı yoktur.
  * Örüntü statüleri yalnızca dondurulmuş araştırma kaydından okunur; şike/kulüp/hakem statüsü değildir.
  * Anomali sayfası ayrıdır; karar motoruna, sanal takibe ve örüntü statüsüne bağlantısı yoktur.
"""

from __future__ import annotations

from html import escape

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



def _gap_text(flags: str) -> str:
    from ...sequences.timeline import GAP_FLAG_TEXT

    return "; ".join(GAP_FLAG_TEXT.get(f, f) for f in flags.split(",") if f) if flags else ""

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
                                 "gun_ara": "Önceki olaydan (gün)", "sezon_gecisi": "Sezon geçişi",
                                 "aralik": "Aralıkta veri boşluğu"}
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
                "aralik": _gap_text(r.get("aralik_durumu", "")),
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
            f"{tail.get('bitis_nedeni') or '-'}{' (' + _gap_text(tail['aralik_durumu']) + ')' if tail.get('aralik_durumu') else ''}. "
            "Açık aralık 'olmayacak' anlamına gelmez; 'uzun süredir olmadı, olmalı' kuralı kurulmaz. Aralıklar veride "
            "<i>gözlenen</i> lig maçı sayısıdır; veri boşluğu işaretli aralıklar gerçek sayıdan farklı olabilir.")
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
        row = QHBoxLayout()
        self.cb_fixture = QComboBox()
        self.cb_fixture.setMinimumWidth(360)
        self.btn_prematch = QPushButton("Yaklaşan maçları hazırla")
        self.btn_prematch.clicked.connect(self.ctl.ensure_prematch)
        row.addWidget(QLabel("Yaklaşan maç (takım):"))
        row.addWidget(self.cb_fixture)
        row.addWidget(self.btn_prematch)
        row.addStretch(1)
        lay.addLayout(row)
        self.sim_text = QLabel("")
        self.sim_text.setWordWrap(True)
        self.sim_text.setTextFormat(Qt.RichText)
        lay.addWidget(self.sim_text)
        self.sim_model = DataFrameModel()
        self.sim_model.headers = {"kosul": "Koşul (karar anından önce)", "hedef": "Hedef", "n_gecmis": "Geçmiş örnek",
                                  "isabet": "Gerçekleşti", "iska": "Gerçekleşmedi", "olay_orani": "Olay oranı",
                                  "s0_beklenen": "S0 beklenen", "statu": "Örüntü statüsü"}
        self.sim_model.formatters = {"olay_orani": fmt_pct, "s0_beklenen": lambda v: fmt_num(v, 1)}
        self.sim_model.hidden = {"_i"}
        self.sim_view, self.sim_proxy = make_table(self.sim_model)
        self.sim_view.setMinimumHeight(300)
        self.sim_view.clicked.connect(self._show_examples)
        lay.addWidget(self.sim_view)
        lay.addWidget(section("Geçmiş benzer örnekler (gerçekleşen ve gerçekleşmeyen birlikte)"))
        self.sim_ex_model = DataFrameModel()
        self.sim_ex_model.headers = {"sonuc": "Sonuç", "tarih": "Tarih", "lig": "Lig", "takim": "Takım", "rakip": "Rakip",
                                     "ev": "Ev?", "iy_ms": "İY/MS (ham)"}
        ev, _ = make_table(self.sim_ex_model, sortable=False)
        ev.setMinimumHeight(260)
        lay.addWidget(ev)
        self.cb_fixture.currentIndexChanged.connect(self.refresh_prematch)
        self._sim_view = None
        return w

    def _fill_fixtures(self) -> None:
        pf = self.ctl.prematch
        cur = self.cb_fixture.currentData()
        self.cb_fixture.blockSignals(True)
        self.cb_fixture.clear()
        if pf is not None:
            tm = pf["tm"]
            up = np.where(pf["upcoming"])[0]
            first = tm.iloc[up].groupby("team").head(1)
            for r, x in first.sort_values(["date", "league", "team"]).iterrows():
                self.cb_fixture.addItem(f"{_date(x['date'])} {x['league']} · {x['team']} – {x['opponent']} "
                                        f"({'ev' if x['is_home'] else 'deplasman'})", int(r))
            i = self.cb_fixture.findData(cur)
            self.cb_fixture.setCurrentIndex(max(i, 0))
        self.cb_fixture.blockSignals(False)

    def refresh_prematch(self) -> None:
        from ...sequences.prematch import prematch_view

        pf = self.ctl.prematch
        if pf is None:
            self.sim_text.setText(self.ctl.prematch_error or "Yaklaşan maç görünümü hazırlanmadı. "
                                  "'Yaklaşan maçları hazırla' düğmesine basın (fikstür verisi gerekir).")
            self.sim_model.set_frame(pd.DataFrame())
            self.sim_ex_model.set_frame(pd.DataFrame())
            return
        row = self.cb_fixture.currentData()
        if row is None:
            self.sim_text.setText("Fikstürde, son oynanmış maçtan sonra gelen yaklaşan maç yok.")
            self.sim_model.set_frame(pd.DataFrame())
            self.sim_ex_model.set_frame(pd.DataFrame())
            return
        v = prematch_view(pf, int(row), self.ctl.seq_results)
        self._sim_view = v
        true = [k for k, x in v["PRE_EVENT_KOSULLARI"].items() if x]
        undef = [k for k, x in v["PRE_EVENT_KOSULLARI"].items() if x is None]
        self.sim_text.setText(
            f"Karar anı: <b>{v['karar_ani']}</b> · doğru koşullar: <b>{', '.join(true) or '-'}</b> · tanımsız "
            f"(eksik pencere): {len(undef)}<br>{v['not']}"
            + ("" if pf["has_s0"] else "<br>Araştırma çalıştırılmadığı için S0 beklentisi ve beklenen puanlı atomlar "
                                       "tanımsız; statüler KAYIT_YOK."))
        df = pd.DataFrame([{k: s[k] for k in ("kosul", "hedef", "n_gecmis", "isabet", "iska", "olay_orani",
                                              "s0_beklenen", "statu")} for s in v["benzer_kosullar"]])
        if len(df):
            df["_i"] = np.arange(len(df))
        self.sim_model.set_frame(df)
        self.sim_ex_model.set_frame(pd.DataFrame())

    def _show_examples(self, idx) -> None:
        if self._sim_view is None:
            return
        src = self.sim_proxy.mapToSource(idx)
        i = int(self.sim_model.frame.iloc[src.row()]["_i"])
        s = self._sim_view["benzer_kosullar"][i]
        rows = ([{"sonuc": "gerçekleşti", **e} for e in s["ornekler_isabet"]]
                + [{"sonuc": "gerçekleşmedi", **e} for e in s["ornekler_iska"]])
        df = pd.DataFrame(rows)
        if len(df):
            df = df.drop(columns=["hedef_gerceklesti"]).sort_values("tarih", ascending=False, kind="mergesort")
        self.sim_ex_model.set_frame(df)

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
        self._fill_fixtures()
        self.refresh_prematch()
        if not res:
            for lbl, model in ((self.pat_text, self.pat_model), (self.an_text, self.an_model)):
                lbl.setText(empty)
                model.set_frame(pd.DataFrame())
            self.pat_card.setHtml("")
            return
        self._render_patterns(res)
        self._render_anomalies(res)

    def _render_patterns(self, res: dict) -> None:
        pats = pd.DataFrame(res.get("oruntuler", []))
        fam = res.get("aileler", {})
        self.pat_text.setText(
            f"Denenen ham hipotez: <b>{res.get('hipotez_ham', '-')}</b> · tekil: <b>{res.get('hipotez_tekil', '-')}</b> · "
            f"referans tekrarı R={res.get('R', '-')} · kalibrasyon kapısı: {res.get('kalibrasyon_kapisi', '-')} · "
            f"plasebo: {fam.get('F7', {}).get('ozet', '-')}")
        names = {"F1": "Sorgu 1 (maç öncesi koşul araması)", "F2": "Sorgu 2 (olay sonrası)", "F3": "S1/S2'nin S0'a katkısı",
                 "F4": "Olaylar arası süre (tehlike)", "F5": "A/B/C ek kontrolü", "F6": "Ekonomik değer (varsayımsal)",
                 "F7": "Plasebo negatif kontrol"}
        man = res.get("manifest", {})
        clean = man.get("temiz_test", {})
        fam_html = ("<h3>Deney aileleri (sonuç ne olursa olsun kayıtlı)</h3><ul>"
                    + "".join(f"<li><b>{k} {names.get(k, '')}</b>: {escape(str(v.get('ozet', '-')))}</li>"
                              for k, v in sorted(fam.items()))
                    + "</ul>"
                    + f"<p>Test dönemi temiz mi: <b>{'evet' if clean.get('temiz') else 'hayır'}</b>"
                    + (f" ({escape('; '.join(clean.get('nedenler', [])))})" if clean.get("nedenler") else "")
                    + ". F3, F5 ve F6 geliştirme sırasında gerçek veride görüldüğü için bu ailelerde statü en fazla "
                      "EXPLORATORY olabilir.</p>")
        if pats.empty:
            self.pat_model.set_frame(pd.DataFrame())
            self.pat_card.setHtml(fam_html + "<p>Keşif döneminde aile bazlı hata kontrolünden geçen örüntü yok. Bu da "
                                  "geçerli bir sonuçtur.</p>")
            return
        show = [c for c in ("hedef", "kosul", "statu", "lift", "lift_lo", "lift_hi", "p_adj", "n", "O", "E_adj") if c in pats]
        df = pats[show].copy()
        self.pat_model.headers = {"hedef": "Hedef", "kosul": "Koşul", "statu": "Statü", "lift": "O/E", "lift_lo": "Alt",
                                  "lift_hi": "Üst", "p_adj": "FWER düz. p", "n": "n", "O": "Gözlenen", "E_adj": "Beklenen (S0)"}
        self.pat_model.formatters = {"lift": fmt_num, "lift_lo": fmt_num, "lift_hi": fmt_num, "p_adj": lambda v: fmt_num(v, 3),
                                     "E_adj": lambda v: fmt_num(v, 1)}
        self.pat_model.set_frame(df)
        self.pat_card.setHtml(fam_html + res.get("oruntu_karti_html", ""))

    def _render_anomalies(self, res: dict) -> None:
        an = pd.DataFrame(res.get("anomaliler", []))
        summ = res.get("anomali_ozeti", {})
        self.an_text.setText(f"Özet (yalnızca tür/durum/dönem sayıları): {summ}" if summ else "Anomali kaydı yok.")
        self.an_model.set_frame(an)


_CARD_HEADERS = {"pencere": "Pencere", "date": "Tarih", "opponent": "Rakip", "is_home": "Ev?", "gf_ht": "İY attığı",
                 "ga_ht": "İY yediği", "gf_ft": "MS attığı", "ga_ft": "MS yediği", "ht_res": "İY", "ft_res": "MS",
                 "awarded": "Hükmen?", "lig_arasi_gun": "Lig arası gün", "has_odds": "Oran var"}
