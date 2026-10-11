"""Veri sayfasındaki "GitHub Veri ve Arşiv" bölümü (S5-GITHUB-01).

A: kaynak kapsamı (lig/sezon, commit, son geçerli maç, İY/MS kapsamı, kullanım ve önbellek durumu); B: filtreli maç
listesi (A/B/C etiketleri, İY/MS, veri kalitesi); C: toplu tarihsel gerçekleşme özeti (merkezi pazar kaydı). Bölüm
açılınca hiçbir şey indirilmez veya yazılmaz; arşiv yalnızca düğmeyle okunur/hazırlanır. Buradaki oranlar geçmiş
gerçekleşmedir: olasılık, model güveni veya bahis avantajı değildir; tahmin ekranının uygunluk kurallarını atlatmaz.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ... import archive as A
from ...data.source_registry import SOURCE_LABELS
from ..widgets import DataFrameModel, banner, make_table

_ABC = {1.0: "evet", 0.0: "hayır"}
_SIDES = (("Ev + deplasman", None), ("Yalnızca ev", "ev"), ("Yalnızca deplasman", "deplasman"))


def _score(h, a) -> str:
    return "-" if pd.isna(h) or pd.isna(a) else f"{int(h)}-{int(a)}"


class ArchivePanel(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.ctl = controller
        self.archive: A.Archive | None = None
        self.merged = pd.DataFrame()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(banner(
            "Seçili GitHub depolarından (openfootball, datasets, xgabora, Hudl/StatsBomb) sabit commit'e bağlı geçmiş "
            "veri. Arşiv uygulama veri klasörünüzden <b>ayrı</b> bir klasördedir; kullanıcı verisi, model ve defter "
            "değişmez, eğitim yapılmaz. Bu bölüm açılınca hiçbir şey indirilmez. " + A.ARCHIVE_NOTE))
        row = QHBoxLayout()
        try:
            home_txt = str(A.archive_home_path())
        except Exception as e:  # klasör yolu çözülemedi: yalnızca bilgi
            home_txt = f"(çözülemedi: {e})"
        self.home_label = QLabel(f"Arşiv klasörü: {home_txt}")
        self.home_label.setObjectName("muted")
        self.home_label.setWordWrap(True)
        row.addWidget(self.home_label, 1)
        self.chk_access = QCheckBox("Bu çalıştırma için datasets ve xgabora erişim koşullarını okudum")
        self.chk_access.setToolTip("Yalnızca bu hazırlamada indirmeyi kapsar; kaydedilmez ve tarihsel analiz hakkı "
                                   "vermez (bu kaynakların analiz kapsamı doğrulanmadığı için yalnızca envanter "
                                   "gösterilir).")
        row.addWidget(self.chk_access)
        self.btn_open = QPushButton("Arşivi aç")
        self.btn_open.setToolTip("Arşiv klasörünü salt okunur açar (ağ isteği yok)")
        self.btn_open.clicked.connect(self.open)
        self.btn_build = QPushButton("Arşivi hazırla / güncelle")
        self.btn_build.setToolTip("Seçili GitHub depolarının ucunu bir kez çözer, dosyaları o commit'ten arşiv "
                                  "klasörüne alır")
        self.btn_build.clicked.connect(self.build)
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_build)
        lay.addLayout(row)
        self.status = QLabel("Arşiv açılmadı.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.RichText)
        lay.addWidget(self.status)

        lay.addWidget(QLabel("<b>A · Kaynak kapsamı</b>"))
        self.cov_model = DataFrameModel()
        self.cov_model.headers = {"kaynak": "Kaynak", "lig": "Lig", "sezon": "Sezon", "commit": "Commit",
                                  "durum": "Önbellek durumu", "son_gecerli_mac": "Son geçerli maç", "mac": "Maç",
                                  "ms_gecerli": "MS geçerli", "iy_gecerli": "İY geçerli",
                                  "iy_mantiksal": "İY mantıksal 0-0", "kapsam": "Kapsam",
                                  "kullanim": "Kullanım", "alan": "Olay / xG / gerçek oran"}
        self.cov_model.formatters = {"kaynak": lambda v: SOURCE_LABELS.get(v, v)}
        view, _ = make_table(self.cov_model)
        view.setMinimumHeight(220)
        lay.addWidget(view)

        lay.addWidget(QLabel("<b>B · Maç tarayıcı</b>"))
        frow = QHBoxLayout()
        self.cb_source = QComboBox()
        self.cb_league = QComboBox()
        self.cb_season = QComboBox()
        self.cb_team = QComboBox()
        self.cb_team.setMinimumWidth(200)
        self.cb_side = QComboBox()
        for text, val in _SIDES:
            self.cb_side.addItem(text, val)
        self.ed_from = QLineEdit()
        self.ed_from.setPlaceholderText("başlangıç YYYY-AA-GG")
        self.ed_to = QLineEdit()
        self.ed_to.setPlaceholderText("bitiş YYYY-AA-GG")
        self.btn_filter = QPushButton("Filtrele")
        self.btn_filter.clicked.connect(self.apply_filters)
        for w in (QLabel("Kaynak:"), self.cb_source, QLabel("Lig:"), self.cb_league, QLabel("Sezon:"), self.cb_season,
                  QLabel("Takım:"), self.cb_team, self.cb_side, self.ed_from, self.ed_to, self.btn_filter):
            frow.addWidget(w)
        frow.addStretch(1)
        lay.addLayout(frow)
        self.match_model = DataFrameModel()
        self.match_model.headers = {"mac_kimligi": "Maç kimliği", "iy": "İY", "ms": "MS", "A": "A", "B": "B", "C": "C",
                                    "iy_ms": "İY/MS", "kalite": "Veri kalitesi", "kaynaklar": "Kaynaklar",
                                    "xg": "xG (maç sonrası açıklama)"}
        self.match_view, self.match_proxy = make_table(self.match_model, sortable=False)
        self.match_view.setMinimumHeight(300)
        lay.addWidget(self.match_view)

        lay.addWidget(QLabel("<b>C · Toplu tarihsel özet</b>"))
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        lay.addWidget(self.summary)

        crow = QHBoxLayout()
        self.cb_card_side = QComboBox()
        self.cb_card_side.addItem("Ev sahibi takım", "home")
        self.cb_card_side.addItem("Deplasman takımı", "away")
        self.btn_card = QPushButton("Seçili maçın olay kartı (önce / sonra)")
        self.btn_card.clicked.connect(self.show_card)
        crow.addWidget(self.cb_card_side)
        crow.addWidget(self.btn_card)
        crow.addStretch(1)
        lay.addLayout(crow)
        self.card = QTextBrowser()
        self.card.setMinimumHeight(160)
        lay.addWidget(self.card)
        self.card_model = DataFrameModel()
        self.card_model.hidden = {"row_id", "event_id", "team", "season", "league", "source", "time", "has_stats",
                                  "red_for", "red_against", "onceki_mac", "sonraki_mac", "saat_dilimi", "s0_guc",
                                  "s0_guc_rakip", "htft"}
        cview, _ = make_table(self.card_model, sortable=False)
        cview.setMinimumHeight(220)
        lay.addWidget(cview)
        controller.busyChanged.connect(self._busy)
        self._set_filters_enabled(False)

    # ------------------------------------------------------------------ eylemler
    def _busy(self, busy: bool) -> None:
        self.btn_open.setEnabled(not busy)
        self.btn_build.setEnabled(not busy)

    def _set_filters_enabled(self, on: bool) -> None:
        for w in (self.cb_source, self.cb_league, self.cb_season, self.cb_team, self.cb_side, self.ed_from, self.ed_to,
                  self.btn_filter, self.btn_card, self.cb_card_side):
            w.setEnabled(on)

    def open(self) -> None:
        self.ctl.open_archive(self.show_archive)

    def build(self) -> None:
        consent = ("football-datasets", "github-mirror") if self.chk_access.isChecked() else ()
        self.ctl.build_archive(self.show_archive, consent=consent)

    def show_archive(self, archive: A.Archive) -> None:
        self.archive = archive
        self.merged, _, _ = A.unified(archive.rows)
        cov = archive.coverage_frame()
        if not cov.empty:
            cov["kullanim"] = ["tarihsel analiz" if x else "yalnızca envanter" for x in cov["tarihsel_analiz"]]
            cov["alan"] = [" / ".join("var" if v else "yok" for v in (o, x, g)) for o, x, g in
                           zip(cov["olay_verisi"], cov["xg"], cov["gercek_oran"])]
            cov = cov.drop(columns=["tarihsel_analiz", "olay_verisi", "xg", "gercek_oran", "yol", "alinma_utc"])
        self.cov_model.set_frame(cov)
        cat = archive.catalog
        parts = [f"Oluşturma {cat.get('olusturma_utc', '-')} · bilgi kesimi {cat.get('bilgi_kesimi', '-')}"]
        for key, st in cat.get("kaynaklar", {}).items():
            parts.append(f"<b>{SOURCE_LABELS.get(key, key)}</b>: {st.get('durum')} · commit "
                         f"{str(st.get('commit') or '-')[:12]} · {st.get('uc_notu') or st.get('hata') or ''}")
        for lg, g in (cat.get("guncel_veri") or {}).items():
            parts.append(f"Güncel veri {lg} {g['sezon']}: <b>{g['durum']}</b> — {g['not']}")
        if archive.rejected:
            parts.append(f"<b>Kökeni doğrulanamayan {len(archive.rejected)} blok kullanılmadı.</b>")
        self.status.setText("<br>".join(parts))
        self._fill_combos()
        self._set_filters_enabled(not self.merged.empty)
        self.apply_filters()

    def _fill_combos(self) -> None:
        m = self.merged
        self.cb_source.clear()
        self.cb_source.addItem("Tümü", None)
        for key in A.SOURCE_KEYS:
            self.cb_source.addItem(SOURCE_LABELS.get(key, key), key)
        self.cb_league.clear()
        self.cb_league.addItem("Tümü", None)
        for lg in sorted(set(m["league"])) if not m.empty else []:
            self.cb_league.addItem(lg, lg)
        self.cb_season.clear()
        self.cb_season.addItem("Tümü", None)
        for s in sorted(set(m["season"]), reverse=True) if not m.empty else []:
            self.cb_season.addItem(s, s)
        self.cb_team.clear()
        self.cb_team.addItem("Tümü", None)
        for t in sorted(set(m["home"]) | set(m["away"])) if not m.empty else []:
            self.cb_team.addItem(t, t)

    def filters(self) -> dict:
        return {"kaynak": self.cb_source.currentData(), "lig": self.cb_league.currentData(),
                "sezon": self.cb_season.currentData(), "takim": self.cb_team.currentData(),
                "yer": self.cb_side.currentData(), "bas": self.ed_from.text().strip() or None,
                "son": self.ed_to.text().strip() or None}

    def apply_filters(self) -> None:
        if self.archive is None:
            return
        try:
            lab, out = A.explore(self.archive, **self.filters())
        except (ValueError, A.ArchiveError) as e:  # ör. geçersiz tarih
            self.summary.setText(f"Filtre uygulanamadı: {e}")
            return
        rows = [{"mac_kimligi": r["mac_kimligi"], "iy": _score(r["hthg"], r["htag"]), "ms": _score(r["fthg"], r["ftag"]),
                 **{k: _ABC.get(r[k], "bilinmiyor") for k in ("A", "B", "C")},
                 "iy_ms": r["iy_ms"] or "bilinmiyor", "kalite": r["veri_kalitesi"], "kaynaklar": r["kaynaklar"],
                 "xg": "-" if pd.isna(r["xg_h"]) else f"{r['xg_h']:.2f}-{r['xg_a']:.2f}"}
                for _, r in lab.sort_values("date").iterrows()]
        self.match_model.set_frame(pd.DataFrame(rows))
        self.summary.setText(summary_html(out))

    def show_card(self) -> None:
        from .sequences import card_html, card_window

        if self.archive is None:
            return
        idx = self.match_view.selectionModel().currentIndex() if self.match_view.selectionModel() else None
        if idx is None or not idx.isValid():
            self.card.setHtml("Önce listeden bir maç seçin.")
            return
        row = self.match_model.frame.iloc[self.match_proxy.mapToSource(idx).row()]
        hit = self.merged[self.merged["mac_kimligi"] == row["mac_kimligi"]]
        if hit.empty:
            return
        team = hit.iloc[0][self.cb_card_side.currentData()]
        try:
            card = A.event_card_for(self.archive, row["mac_kimligi"], team)
        except (A.ArchiveError, ValueError) as e:
            self.card.setHtml(f"Olay kartı gösterilemiyor: {e}")
            self.card_model.set_frame(pd.DataFrame())
            return
        self.card.setHtml(card_html(card) + "<br><i>Geçmiş incelemedir; maç öncesi ekranına taşınmaz.</i>")
        frames = []
        for key in ("PRE_EVENT", "POST_EVENT", "RAKIP_PRE_EVENT"):
            _, df = card_window(card, key)
            if not df.empty:
                df.insert(0, "blok", key)
                frames.append(df)
        self.card_model.set_frame(pd.concat(frames, ignore_index=True) if frames else pd.DataFrame())


def summary_html(out: dict) -> str:
    """Toplu özetin metni: her oran geçerli örnek sayısıyla; bilinmiyor/çelişki/inceleme/karantina ayrı."""
    lines = [f"Maç <b>{out['mac']}</b> · birleşik geçerli {out['birlesik_gecerli']} · MS geçerli {out['ms_gecerli']} · "
             f"İY geçerli {out['iy_gecerli']} (mantıksal 0-0: {out['iy_mantiksal_0_0']}, işaretli) · çelişkili "
             f"{out['celiskili']} · tarih/kimlik incelemesi {out['incelemede'] + out['kimlik_veya_tarih_incelemesi']} · "
             f"kaynak karantinası {sum(out.get('kaynak_karantinasi', {}).values())} · doğrulanamayan blok "
             f"{out.get('dogrulanamayan_blok', 0)}"]
    for short, v in out["pazarlar"].items():
        rate = "-" if v["gerceklesme_orani"] is None else f"%{100 * v['gerceklesme_orani']:.1f}"
        lines.append(f"{short} · {v['ad']}: {v['evet']} / {v['gecerli']} geçerli ({rate}; bilinmiyor {v['bilinmiyor']})")
    if out.get("iy_ms_gecerli"):
        cells = " · ".join(f"{k.replace('HTFT_', '').replace('_', '/')}: {n}" for k, n in out["iy_ms"].items())
        lines.append(f"İY/MS (n={out['iy_ms_gecerli']}): {cells}")
    lines.append(f"<i>{out['aciklama']}</i>")
    return "<br>".join(lines)
