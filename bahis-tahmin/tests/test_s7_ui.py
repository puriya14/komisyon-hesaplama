"""S7-UI-01: Araştırma Çalışma Alanı sayfası (kayıtlı araştırmalar, grup karşılaştırması, çoklu olay matrisi, notlar).

Bütün testler gerçek servislerle (``archive.load``/``view``, ``calisma``, ``olay_karsilastirma``) ve geçici klasörlerde
açıkça SENTETİK hazırlanmış bir arşivle (sahte HTTP oturumu; ağ yok) ve geçici çalışma alanlarıyla çalışır. Gerçek
veri, kullanıcı dosyası veya ağ gerekmez. Arka plan işini bekletmek gereken testler, gerçek servis fonksiyonunu
çağırmadan önce bir olayı bekleyen sarmalayıcı kullanır (servis yine gerçekten çalışır).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

if sys.platform != "win32" and not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QObject, Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QLabel, QMessageBox  # noqa: E402

from bahis_tahmin import archive as A  # noqa: E402
from bahis_tahmin import calisma as C  # noqa: E402
from bahis_tahmin import olay_karsilastirma as O  # noqa: E402
from bahis_tahmin.data import source_registry  # noqa: E402
from bahis_tahmin.data.github_kaynak import REPOS  # noqa: E402
from test_s5_github import C_OF, FakeSession, Resp, adv, raw, refs_url, transport  # noqa: E402

OF = "openfootball-sonuc"
OF_REPO = "openfootball/football.json"
TODAY = dt.date(2025, 6, 1)
ARS, CHE, EVE, LIV = "Arsenal FC", "Chelsea FC", "Everton FC", "Liverpool FC"
TEAMS = (ARS, CHE, EVE, LIV)
# 4 takımlı çift devre (6 hafta × 2 maç). Arsenal her haftanın ilk maçında (j=0).
ROUNDS = (((0, 1), (2, 3)), ((2, 0), (1, 3)), ((0, 3), (1, 2)), ((1, 0), (3, 2)), ((0, 2), (3, 1)), ((3, 0), (2, 1)))
# 2024/25: Arsenal'in üç ham İY/MS 2/1 maçı (iki ev: İY geride MS galip; bir deplasman: İY önde MS mağlup).
# Liverpool'un ev maçlarında İY skoru yok (A ve C bilinmiyor; MS 0-0 değil → mantıksal İY yok).
SPECIAL_2024 = {(2, 0): ((2, 1), (0, 1)), (4, 0): ((3, 2), (0, 1)), (3, 0): ((2, 1), (0, 1)),
                (3, 1): ((2, 1), None), (4, 1): ((1, 2), None), (5, 0): ((3, 1), None)}
SPECIAL_2023 = {(4, 0): ((2, 1), (0, 1))}


def season_json(year: int, special: dict, change: dict | None = None) -> bytes:
    """Sentetik openfootball lig-sezonu (varsayılan skorlarda Arsenal'in 2/1 maçı yoktur)."""
    special = {**special, **(change or {})}
    matches = []
    for i, rnd in enumerate(ROUNDS):
        day = (dt.date(year, 8, 10) + dt.timedelta(days=7 * i)).isoformat()
        for j, (h, a) in enumerate(rnd):
            if (i, j) in special:
                ft, ht = special[(i, j)]
            else:
                ft = ((year + i + j) % 3 + 1, (year + 2 * i + j) % 2)
                ht = (min(ft[0], (i + j) % 2), min(ft[1], j % 2))
            score = {"ft": list(ft)}
            if ht is not None:
                score["ht"] = list(ht)
            matches.append({"round": f"Matchday {i + 1}", "date": day, "team1": TEAMS[h], "team2": TEAMS[a],
                            "score": score})
    return json.dumps({"name": f"Premier League {year}/{(year + 1) % 100:02d}", "matches": matches}).encode()


def build_archive(base: Path, name: str = "arsiv", change_2024: dict | None = None) -> Path:
    """Geçici klasörde sentetik arşiv (yalnızca openfootball 2023/24 + 2024/25; sahte HTTP, ağ yok)."""
    r = {refs_url(OF_REPO): Resp(200, adv({f"refs/heads/{REPOS[OF_REPO].branch}": C_OF})),
         raw(OF_REPO, C_OF, "2023-24/en.1.json"): Resp(200, season_json(2023, SPECIAL_2023)),
         raw(OF_REPO, C_OF, "2024-25/en.1.json"): Resp(200, season_json(2024, SPECIAL_2024, change_2024))}
    home = base / name
    A.build(home, sources=(OF,), transport=transport(FakeSession(r)), today=TODAY, openfootball_from=2023)
    return home


def eid(day: str, home: str, away: str) -> str:
    return f"E0|{day}|{home}|{away}"


E1 = eid("2024-08-24", ARS, LIV)    # ev 2/1
E2 = eid("2024-08-31", CHE, ARS)    # deplasman: ham 2/1 (Arsenal İY önde, MS mağlup)
E3 = eid("2024-09-07", ARS, EVE)    # ev 2/1
EVENTS = [E1, E2, E3]


@pytest.fixture(scope="module")
def app():
    from bahis_tahmin.ui.theme import apply_theme

    a = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    apply_theme(a)
    return a


@pytest.fixture(autouse=True)
def no_callback_errors(monkeypatch):
    """Qt geri çağrısındaki yakalanmamış istisna yalnızca yazdırılır; burada test hatasına çevrilir."""
    seen = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: seen.append(exc))
    yield seen
    assert not seen, [f"{e[0].__name__}: {e[1]}" for e in seen]


@pytest.fixture(scope="module")
def archive_dir(tmp_path_factory):
    return build_archive(tmp_path_factory.mktemp("s7_arsiv"))


@pytest.fixture
def paths(tmp_path, tmp_home, monkeypatch):
    """Varsayılan arşiv/çalışma yolları da geçici klasörde (gerçek kullanıcı klasörüne dokunulmaz)."""
    monkeypatch.setenv("BAHIS_TAHMIN_ARSIV", str(tmp_path / "varsayilan-arsiv"))
    monkeypatch.setenv("BAHIS_TAHMIN_CALISMA", str(tmp_path / "varsayilan-calisma"))
    return tmp_path


def settle(app, ctl, timeout: float = 120.0) -> None:
    """Arka plan işleri (ve tamamlanınca başlatılan devam işleri) bitene kadar olay döngüsünü işletir."""
    deadline = time.monotonic() + timeout
    while True:
        ctl.wait()
        app.processEvents()
        app.processEvents()
        if not ctl.busy:
            return
        assert time.monotonic() < deadline, "arka plan işi bitmedi"


def make_window(app):
    from bahis_tahmin.ui.main_window import MainWindow
    from bahis_tahmin.ui.pages.research import ResearchPage

    win = MainWindow()
    page = win.page(ResearchPage)
    win.nav.setCurrentRow(win.pages.index(page))
    app.processEvents()
    return win, page


@pytest.fixture
def ui(app, paths):
    win, page = make_window(app)
    yield win, page
    page.ask_unsaved = lambda action: "discard"  # test sonu: kirli taslak kapanışı bekletmesin
    settle(app, win.ctl)
    win.close()
    app.processEvents()


def open_archive(app, page, home) -> None:
    page.ed_archive.setText(str(home))
    page.btn_open_archive.click()
    settle(app, page.ctl)
    assert page.archive is not None, page.msg.text()


def create_ws(app, page, folder) -> None:
    page.ed_ws.setText(str(folder))
    page.btn_create_ws.click()
    settle(app, page.ctl)
    assert page.ws_path is not None, page.msg.text()


def set_source(page, key) -> None:
    page.cb_source.setCurrentIndex(page.cb_source.findData(key))


def set_group(gf, lig=None, sezonlar=(), takim=None, yer=None, bas=None, son=None, sonuc=None) -> None:
    gf.cb_league.setCurrentIndex(gf.cb_league.findData(lig) if lig else 0)
    for i in range(gf.lst_seasons.count()):
        it = gf.lst_seasons.item(i)
        it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in sezonlar else Qt.Unchecked)
    gf.cb_team.setCurrentText(takim or "")
    gf.cb_side.setCurrentIndex(gf.cb_side.findData(yer))
    gf.ed_from.setText(bas or "")
    gf.ed_to.setText(son or "")
    sonuc = sonuc or {}
    for k, cb in gf.cb_out.items():
        cb.setCurrentIndex(cb.findData(sonuc.get(k) or "tumu"))
    for c, chk in gf.chk_htft.items():
        chk.setChecked(c in (sonuc.get("iy_ms") or []))


def fill(page, title, g1, g2=None, kaynak=OF) -> None:
    set_source(page, kaynak)
    page.ed_title.setText(title)
    set_group(page.g1, **g1)
    page.chk_g2.setChecked(g2 is not None)
    if g2 is not None:
        set_group(page.g2, **g2)


G_2024 = {"lig": "E0", "sezonlar": ["2024/25"]}
G_2023 = {"lig": "E0", "sezonlar": ["2023/24"]}
G_ARS_21 = {"lig": "E0", "sezonlar": ["2024/25"], "takim": ARS, "sonuc": {"iy_ms": ["HTFT_2_1"]}}


def save_new(app, page, title="E0 2024/25 ile 2023/24", g1=G_2024, g2=G_2023, kaynak=OF) -> str:
    page.new_research()
    fill(page, title, g1, g2, kaynak)
    page.btn_save.click()
    settle(app, page.ctl)
    assert page.rid is not None and not page.dirty, page.msg.text()
    return page.rid


def db_rows(ws: Path, table: str) -> int:
    con = sqlite3.connect(f"file:{ws / C.DB_NAME}?mode=ro", uri=True)
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def tree(*dirs) -> dict:
    out = {}
    for d in dirs:
        d = Path(d)
        if d.exists():
            for p in sorted(d.rglob("*")):
                if p.is_file():
                    out[str(p)] = sha(p)
    return out


class Gate:
    """Gerçek servis çağrısını, test serbest bırakana kadar bekletir (servis yine çalışır)."""

    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()

    def wrap(self, fn):
        def inner(*a, **k):
            self.entered.set()
            assert self.release.wait(60), "kapı açılmadı"
            return fn(*a, **k)
        return inner


def wait_entered(app, gate, timeout=30.0) -> None:
    deadline = time.monotonic() + timeout
    while not gate.entered.is_set():
        app.processEvents()
        assert time.monotonic() < deadline
        time.sleep(0.01)


def explicit_pick(app, page, team, ids, season=None) -> None:
    page.rb_explicit.setChecked(True)
    page.cb_team_explicit.setCurrentText(team)
    page.cb_season_explicit.setCurrentIndex(page.cb_season_explicit.findData(season) if season else 0)
    page.btn_list.click()
    settle(app, page.ctl)
    m = page.pick_model
    col = m._cols.index("sec")
    for r in range(m.rowCount()):
        if m.mac_id(r) in ids:
            m.setData(m.index(r, col), Qt.Checked, Qt.CheckStateRole)
    assert m.picked == set(ids)


# ============================================================================ 1
def test_first_show_does_no_network_file_job_or_training(app, paths, monkeypatch):
    def no_net(*a, **k):
        raise AssertionError("ilk açılışta ağ isteği yapıldı")

    monkeypatch.setattr(socket.socket, "connect", no_net)
    from bahis_tahmin.ui.main_window import MainWindow
    from bahis_tahmin.ui.pages.research import ResearchPage

    win = MainWindow()
    for name in ("retrain", "update_and_train", "build_archive", "train_goal_engine", "open_archive"):
        monkeypatch.setattr(win.ctl, name, lambda *a, _n=name, **k: (_ for _ in ()).throw(AssertionError(_n)))
    started = []
    monkeypatch.setattr(win.ctl, "run_job", lambda *a, **k: started.append(a) or False)
    before = tree(paths)
    page = win.page(ResearchPage)
    win.nav.setCurrentRow(win.pages.index(page))
    for _ in range(3):
        app.processEvents()
    page.on_show()
    assert started == [] and not win.ctl.busy
    assert tree(paths) == before  # dosya oluşturulmadı/değişmedi
    assert not (paths / "varsayilan-calisma").exists() and not (paths / "varsayilan-arsiv").exists()
    assert page.archive is None and page.ws_path is None
    assert page.ed_ws.text() == str(paths / "varsayilan-calisma")  # öneri yalnızca metin
    # Boş durumlar ayrı ve açık
    assert "Arşiv açılmadı" in page.lbl_archive.text()
    assert "Çalışma alanı açılmadı" in page.list_state.text()
    assert "Henüz sonuç yok" in page.lbl_group_state.text()
    assert "Geçmiş veri incelemesi; tahmin değildir" in page.findChild(QLabel, "banner").text()
    win.close()


# ============================================================================ 2
def test_open_existing_workspace_is_separate_from_create(app, ui, paths, archive_dir):
    win, page = ui
    missing = paths / "yok"
    page.ed_ws.setText(str(missing))
    page.btn_open_ws.click()
    settle(app, win.ctl)
    assert page.ws_path is None and not missing.exists()  # açma oluşturmaz
    assert "Çalışma alanı yok" in page.lbl_ws.text() and str(missing) in page.lbl_ws.text()
    # Bozuk dosya: açılmaz, üzerine yazılmaz, "yeni alan açıldı" denmez
    bad = paths / "bozuk"
    bad.mkdir()
    (bad / C.DB_NAME).write_bytes(b"bu bir sqlite dosyasi degil" * 10)
    h = sha(bad / C.DB_NAME)
    page.ed_ws.setText(str(bad))
    page.btn_open_ws.click()
    settle(app, win.ctl)
    assert page.ws_path is None and sha(bad / C.DB_NAME) == h
    assert "bozuk" in page.lbl_ws.text().lower() and str(bad) in page.lbl_ws.text()
    page.btn_create_ws.click()
    settle(app, win.ctl)
    assert page.ws_path is None and sha(bad / C.DB_NAME) == h and "zaten" in page.lbl_ws.text()
    # Boş olmayan klasör ve arşiv klasörü içi reddedilir
    full = paths / "dolu"
    full.mkdir()
    (full / "baska.txt").write_text("x")
    page.ed_ws.setText(str(full))
    page.btn_create_ws.click()
    settle(app, win.ctl)
    assert page.ws_path is None and not (full / C.DB_NAME).exists() and "boş değil" in page.lbl_ws.text()
    page.ed_archive.setText(str(archive_dir))
    before_archive = tree(archive_dir)
    page.ed_ws.setText(str(archive_dir / "calisma"))
    page.btn_create_ws.click()
    settle(app, win.ctl)
    assert page.ws_path is None and tree(archive_dir) == before_archive and "arşiv" in page.lbl_ws.text()
    # Uygulama klasörü de reddedilir (servis konum denetimi)
    page.ed_ws.setText(os.environ["BAHIS_TAHMIN_HOME"] + "/calisma")
    page.btn_create_ws.click()
    settle(app, win.ctl)
    assert page.ws_path is None and "çakışıyor" in page.lbl_ws.text()
    # Açık yazma: yeni alan; sonra ayrı düğmeyle var olan alan açılır
    ws = paths / "yeni-alan"
    create_ws(app, page, ws)
    assert (ws / C.DB_NAME).is_file() and "Yeni çalışma alanı oluşturuldu" in page.msg.text()
    h2 = sha(ws / C.DB_NAME)
    page.btn_open_ws.click()
    settle(app, win.ctl)
    assert page.ws_path == str(ws.resolve()) and "Var olan çalışma alanı açıldı" in page.msg.text()
    assert sha(ws / C.DB_NAME) == h2  # salt okunur açma yazmaz
    assert "henüz araştırma yok" in page.list_state.text()


# ============================================================================ 3
def test_save_revision_and_reopen(app, ui, paths, archive_dir):
    win, page = ui
    ws = paths / "ws"
    open_archive(app, page, archive_dir)
    create_ws(app, page, ws)
    assert not page.btn_run.isEnabled()  # kaydedilmemiş taslak çalıştırılamaz
    rid = save_new(app, page, title="İlk <b>başlık</b>")
    assert page.rev == 1 and page.btn_save.text() == "Yeni revizyon kaydet"
    assert page.list_model.rowCount() == 1 and page.list_model.frame.iloc[0]["baslik"] == "İlk <b>başlık</b>"
    page.ed_title.setText("İkinci başlık")
    set_group(page.g2, lig="E0", sezonlar=["2023/24"], takim=ARS)
    assert page.dirty and "KAYDEDİLMEMİŞ" in page.lbl_draft.text()
    page.btn_save.click()
    settle(app, win.ctl)
    assert page.rid == rid and page.rev == 2 and not page.dirty
    with C.CalismaAlani.ac(ws) as w:
        r1, r2 = w.arastirma(rid, 1), w.arastirma(rid, 2)
    assert r1["tanim"]["baslik"] == "İlk <b>başlık</b>" and r1["tanim"]["grup_2"]["takim"] is None  # eski değişmedi
    assert r2["tanim"]["grup_2"]["takim"] == ARS
    assert page.rev_model.rowCount() == 2
    # Uygulamayı kapatıp yeniden aç: geçmiş korunur
    win2, page2 = make_window(app)
    try:
        page2.ed_ws.setText(str(ws))
        page2.btn_open_ws.click()
        settle(app, win2.ctl)
        assert page2.list_model.frame.iloc[0]["son_revizyon"] == 2
        page2.list_view.selectRow(0)
        page2.btn_open_research.click()
        settle(app, win2.ctl)
        assert page2.rid == rid and page2.rev == 2 and page2.ed_title.text() == "İkinci başlık"
        assert page2.g2.cb_team.currentText() == ARS and page2.g1.seasons() == ["2024/25"] and not page2.dirty
        assert page2.rev_model.rowCount() == 2
    finally:
        win2.close()


# ============================================================================ 4
def test_dirty_draft_is_not_silently_lost(app, ui, paths, archive_dir):
    win, page = ui
    ws = paths / "ws"
    open_archive(app, page, archive_dir)
    create_ws(app, page, ws)
    rid_a = save_new(app, page, title="A")
    rid_b = save_new(app, page, title="B")
    asked = []
    page.ed_title.setText("B değişti")
    page.ask_unsaved = lambda action: asked.append(action) or "cancel"
    page.btn_new.click()
    assert asked and page.ed_title.text() == "B değişti" and page.rid == rid_b and page.dirty  # vazgeç: taslak kalır
    page.ask_unsaved = lambda action: "discard"
    page.btn_new.click()
    assert page.rid is None and page.ed_title.text() == ""  # bırak: açıkça bırakıldı
    # Kaydet: önce kaydedilir, sonra istenen araştırma açılır
    page.open_research(rid_b)
    settle(app, win.ctl)
    page.ed_title.setText("B kaydedilerek")
    page.ask_unsaved = lambda action: "save"
    page.open_research(rid_a)
    settle(app, win.ctl)
    assert page.rid == rid_a and page.ed_title.text() == "A"
    with C.CalismaAlani.ac(ws) as w:
        assert w.arastirma(rid_b)["revizyon"] == 2 and w.arastirma(rid_b)["tanim"]["baslik"] == "B kaydedilerek"
    # Pencere kapanışı: vazgeç → açık kalır; kaydet → kaydedip kapanır
    win.show()
    page.ed_title.setText("A kapanışta")
    page.ask_unsaved = lambda action: "cancel"
    win.close()
    assert win.isVisible() and page.dirty
    page.ask_unsaved = lambda action: "save"
    win.close()
    settle(app, win.ctl)
    assert not win.isVisible()
    with C.CalismaAlani.ac(ws) as w:
        assert w.arastirma(rid_a)["tanim"]["baslik"] == "A kapanışta"


# ============================================================================ 5
def test_preview_writes_nothing_and_run_adds_one_record(app, ui, paths, archive_dir):
    win, page = ui
    ws = paths / "ws"
    open_archive(app, page, archive_dir)
    create_ws(app, page, ws)
    save_new(app, page)
    before = tree(ws, archive_dir)
    page.btn_preview.click()
    settle(app, win.ctl)
    assert page.group_shown["tur"] == "onizleme" and "ÖNİZLEME — kaydedilmedi" in page.lbl_group_head.text()
    assert tree(ws, archive_dir) == before and db_rows(ws, "calistirmalar") == 0
    page.btn_run.click()
    settle(app, win.ctl)
    assert db_rows(ws, "calistirmalar") == 1 and db_rows(ws, "calistirma_gruplari") == 2
    assert page.group_shown["tur"] == "sakli" and "SAKLI SONUÇ" in page.lbl_group_head.text()
    assert page.run_model.rowCount() == 1 and page.cb_run_b.count() == 1


# ============================================================================ 6
def test_double_click_does_not_create_double_records(app, ui, paths, archive_dir):
    win, page = ui
    ws = paths / "ws"
    open_archive(app, page, archive_dir)
    create_ws(app, page, ws)
    page.new_research()
    fill(page, "Çift tık", G_2024, G_2023)
    page.btn_save.click()
    page.btn_save.click()  # iş sürerken düğme kapalı
    page.save()  # programatik ikinci çağrı da tek görev yöneticisinde reddedilir
    settle(app, win.ctl)
    assert db_rows(ws, "arastirma_revizyonlari") == 1
    page.btn_run.click()
    page.btn_run.click()
    page.run_saved()
    settle(app, win.ctl)
    assert db_rows(ws, "calistirmalar") == 1
    page.ed_note.setPlainText("tek not")
    page.btn_note_add.click()
    page.btn_note_add.click()
    page.add_note(False)
    settle(app, win.ctl)
    assert db_rows(ws, "notlar") == 1


# ============================================================================ 7
def test_revision_conflict_is_not_bypassed(app, ui, paths, archive_dir):
    win, page = ui
    ws = paths / "ws"
    open_archive(app, page, archive_dir)
    create_ws(app, page, ws)
    rid = save_new(app, page)
    with C.CalismaAlani.yazmak_icin_ac(ws) as w:  # başka bir pencere/işlem araya revizyon ekler
        w.arastirma_revize(rid, {"aciklama": "başka yerden"}, temel_revizyon=1)
    page.ed_title.setText("Benim değişikliğim")
    page.btn_save.click()
    settle(app, win.ctl)
    assert "Revizyon çakışması" in page.msg.text() and page.dirty and page.rev == 1
    assert page.ed_title.text() == "Benim değişikliğim"  # taslak korunur
    assert db_rows(ws, "arastirma_revizyonlari") == 2
    page.btn_discard.click()
    assert not page.dirty
    page.btn_run.click()
    settle(app, win.ctl)
    assert "en son revizyonu r2" in page.msg.text() and db_rows(ws, "calistirmalar") == 0


# ============================================================================ 8
def test_stored_result_shows_old_definition_and_data_version(app, ui, paths, archive_dir):
    win, page = ui
    ws = paths / "ws"
    open_archive(app, page, archive_dir)
    create_ws(app, page, ws)
    save_new(app, page)
    page.btn_run.click()
    settle(app, win.ctl)
    run = page.group_shown["kayit"]
    stored_frame = page.market_model.frame.copy()
    set_group(page.g2, lig="E0", sezonlar=["2024/25"], takim=ARS)
    page.btn_save.click()
    settle(app, win.ctl)
    assert page.rev == 2
    page.cb_run_b.setCurrentIndex(page.cb_run_b.findData(run["calistirma_id"]))
    page.btn_open_run.click()
    settle(app, win.ctl)
    head = page.lbl_group_head.text()
    assert "r1" in head and "2023/24" in head and short(run["veri"]["veri_ozeti"]) in head
    assert "yeniden hesaplanmadı" in head
    assert page.market_model.frame.equals(stored_frame)
    g2 = run["sonuc"]["grup_2"]
    assert page.market_model.frame["_g2_gecerli"].tolist() == [g2["pazarlar"][k]["gecerli"] for k in "ABC"]


def short(h) -> str:
    return str(h)[:12]


# ============================================================================ 9
def test_changed_data_version_does_not_silently_recompute(app, ui, paths, archive_dir):
    win, page = ui
    ws = paths / "ws"
    other = build_archive(paths, "arsiv2", change_2024={(0, 1): ((4, 4), (2, 2))})
    open_archive(app, page, archive_dir)
    create_ws(app, page, ws)
    save_new(app, page, title="Arsenal 2/1", g1=G_ARS_21, g2=G_2023)
    page.btn_run.click()
    settle(app, win.ctl)
    shown = page.market_model.frame.copy()
    assert len(shown) == 3
    page.btn_verify.click()
    settle(app, win.ctl)
    assert page.lbl_verify.property("durum") == "DOGRULANDI" and page.market_model.frame.equals(shown)
    open_archive(app, page, other)  # yeni veri sürümü
    page.btn_verify.click()
    settle(app, win.ctl)
    assert page.lbl_verify.property("durum") == "VERI_SURUMU_DEGISTI"
    assert "yeniden hesaplanmadı" in page.lbl_verify.text()
    assert page.market_model.frame.equals(shown) and page.group_shown["tur"] == "sakli"
    assert db_rows(ws, "calistirmalar") == 1
    # Saklı grup yolunda da yeni veriyle hesap yapılmaz
    page.rb_stored.setChecked(True)
    page.btn_stored_teams.click()
    settle(app, win.ctl)
    page.cb_team_stored.setCurrentIndex(page.cb_team_stored.findData(ARS))
    page.btn_compare.click()
    settle(app, win.ctl)
    assert page.olay_shown["sonuc"]["durum"] == "VERI_SURUMU_DEGISTI" and page.matrix.rowCount() == 0
    assert "VERI_SURUMU_DEGISTI" in page.lbl_olay_state.text()


# ============================================================================ 10
def test_closed_source_cannot_bypass_service_guard(app, ui, paths, archive_dir, monkeypatch):
    win, page = ui
    ws = paths / "ws"
    open_archive(app, page, archive_dir)
    create_ws(app, page, ws)
    page.new_research()
    set_source(page, "football-datasets")
    assert "tarihsel analiz kapalı" in page.cb_source.currentText()
    page.ed_title.setText("Kapalı kaynak")
    page.btn_preview.click()
    settle(app, win.ctl)
    assert "KULLANIM KAPSAMI KAPALI" in page.lbl_group_state.text() and page.market_model.rowCount() == 0
    page.btn_save.click()
    settle(app, win.ctl)
    page.btn_run.click()
    settle(app, win.ctl)
    assert page.group_shown["kayit"]["sonuc"]["durum"] == "KULLANIM_KAPSAMI_KAPALI"
    assert page.market_model.rowCount() == 0
    page.rb_explicit.setChecked(True)
    page.btn_list.click()
    settle(app, win.ctl)
    assert "Kapalı kaynak" in page.lbl_explicit_state.text() and page.pick_model.rowCount() == 0
    # Saklı sonuç: kaynak sonradan kapanırsa sonuç ve olaylar gösterilmez
    save_new(app, page, title="Açık kaynak", g1=G_ARS_21, g2=None)
    page.btn_run.click()
    settle(app, win.ctl)
    cid = page.group_shown["kayit"]["calistirma_id"]
    page.rb_stored.setChecked(True)
    page.btn_stored_teams.click()
    settle(app, win.ctl)
    page.cb_team_stored.setCurrentIndex(page.cb_team_stored.findData(ARS))
    monkeypatch.setitem(source_registry.ARCHIVE_SCOPES[OF], "tarihsel_analiz", "DOGRULANAMADI")
    page.btn_open_run.click()
    settle(app, win.ctl)
    assert page.group_shown["kayit"]["calistirma_id"] == cid
    assert "KULLANIM KAPSAMI KAPALI" in page.lbl_group_state.text() and page.market_model.rowCount() == 0
    page.btn_compare.click()
    settle(app, win.ctl)
    assert page.olay_shown["sonuc"]["durum"] == "KULLANIM_KAPSAMI_KAPALI" and page.matrix.rowCount() == 0


# ============================================================================ 11
def test_group_values_and_denominators_equal_service(app, ui, paths, archive_dir):
    win, page = ui
    ws = paths / "ws"
    open_archive(app, page, archive_dir)
    create_ws(app, page, ws)
    g1 = {"lig": "E0", "sezonlar": ["2024/25"]}
    g2 = {"lig": "E0", "sezonlar": ["2023/24", "2024/25"], "takim": ARS}
    save_new(app, page, g1=g1, g2=g2)
    page.btn_preview.click()
    settle(app, win.ctl)
    direct = C.compute(A.load(archive_dir), page.form_input())["sonuc"]
    f = page.market_model.frame
    for i, k in enumerate("ABC"):
        a, b = direct["grup_1"]["pazarlar"][k], direct["grup_2"]["pazarlar"][k]
        row = f.iloc[i]
        assert (row["_g1_evet"], row["_g1_gecerli"], row["_g1_oran"]) == (a["evet"], a["gecerli"], a["gerceklesme_orani"])
        assert (row["_g2_evet"], row["_g2_gecerli"], row["_g2_oran"]) == (b["evet"], b["gecerli"], b["gerceklesme_orani"])
        assert row["_fark"] == direct["karsilastirma"]["pazarlar"][k]["fark_yuzde_puan"]
        assert row["g1_sayi"] == f"{a['evet']} / {a['gecerli']}" and row["g1_bilinmiyor"] == a["bilinmiyor"]
        assert row["fark"].endswith("yp")  # yüzde puan; göreli % değil
    h = page.htft_model.frame
    assert len(h) == 9 and h["g1_sayi"].tolist() == [direct["grup_1"]["iy_ms"]["dagilim"][c] for c in h["_kod"]]
    assert "2/1" in h["kod"].tolist()
    o = direct["karsilastirma"]["ortusme"]
    assert o["ortak"] > 0 and f"Ortak maç: {o['ortak']}" in page.lbl_overlap.text()
    assert "Gruplarda ortak maç var" in page.lbl_overlap.text()
    q = page.quality_model.frame
    assert q.iloc[0]["g1"] == str(direct["grup_1"]["mac"]) and "karantina" in q.iloc[-1]["olcu"]
    # Sonuca göre seçilmiş grup: işaretlenir, başarı rozeti yok
    page.new_research()
    fill(page, "Seçim", {"lig": "E0", "sonuc": {"B": "gerceklesti"}}, None)
    page.btn_preview.click()
    settle(app, win.ctl)
    f = page.market_model.frame
    assert f.iloc[1]["_g1_oran"] == 1.0 and "seçildi" in f.iloc[1]["not"]
    assert "geçmiş sonuca göre seçildi" in page.lbl_group_notes.text()


# ============================================================================ 12
def test_empty_denominator_never_shows_zero_percent(app, ui, paths, archive_dir):
    win, page = ui
    open_archive(app, page, archive_dir)
    page.new_research()
    fill(page, "Boş payda", {"lig": "E0", "sezonlar": ["2024/25"], "takim": LIV, "yer": "ev"},
         {"lig": "E0", "bas": "2030-01-01"})
    page.btn_preview.click()
    settle(app, win.ctl)
    f = page.market_model.frame
    by = {r["_k"]: r for _, r in f.iterrows()}
    assert by["A"]["_g1_gecerli"] == 0 and by["A"]["g1_oran"] == "Veri yok"  # İY yok → A bilinmiyor
    assert by["C"]["_g1_gecerli"] == 0 and by["C"]["g1_oran"] == "Veri yok"
    assert by["B"]["_g1_gecerli"] == 3 and by["B"]["g1_oran"].startswith("%")
    for k in "ABC":
        assert by[k]["g2_oran"] == "Veri yok" and by[k]["fark"] == "—"  # boş grup
    shown = [page.market_model.data(page.market_model.index(r, c))
             for r in range(page.market_model.rowCount()) for c in range(page.market_model.columnCount())]
    assert "%0.0" not in shown
    h = page.htft_model.frame
    assert set(h["g2_pay"]) == {"Veri yok"} and set(h["fark"]) == {"—"}
    assert "Grupta maç yok" in page.lbl_group_notes.text()


# ============================================================================ 13
def test_sorting_and_filter_do_not_change_selected_event_ids(app, ui, paths, archive_dir):
    win, page = ui
    open_archive(app, page, archive_dir)
    set_source(page, OF)
    explicit_pick(app, page, ARS, EVENTS)
    m, proxy, view = page.pick_model, page.pick_proxy, page.pick_view
    assert m.rowCount() == 12
    view.sortByColumn(m._cols.index("tarih"), Qt.DescendingOrder)
    app.processEvents()
    page.ed_search.setText("Chelsea")
    app.processEvents()
    assert proxy.rowCount() < m.rowCount() and m.picked == set(EVENTS)
    page.ed_search.setText("")
    view.sortByColumn(m._cols.index("deplasman"), Qt.AscendingOrder)
    col = m._cols.index("sec")
    checked_ids = {m.mac_id(proxy.mapToSource(proxy.index(r, 0)).row()) for r in range(proxy.rowCount())
                   if proxy.data(proxy.index(r, col), Qt.CheckStateRole) == Qt.Checked}
    assert checked_ids == set(EVENTS)
    assert page._olay_params(0)["olaylar"] == tuple(sorted(EVENTS))
    # Pencere seçeneği seçimi silmez; takım değişikliği açıkça temizler
    page.cb_once.setCurrentIndex(page.cb_once.findData(10))
    assert m.picked == set(EVENTS)
    page.cb_team_explicit.setCurrentText(CHE)
    assert m.picked == set() and "temizlendi" in page.msg.text()


# ============================================================================ 14
def test_stored_and_explicit_paths_use_same_service_rules(app, ui, paths, archive_dir):
    win, page = ui
    ws = paths / "ws"
    open_archive(app, page, archive_dir)
    create_ws(app, page, ws)
    save_new(app, page, title="2/1 tüm takımlar", g1={"lig": "E0", "sezonlar": ["2024/25"],
                                                     "sonuc": {"iy_ms": ["HTFT_2_1"]}}, g2=None)
    page.btn_run.click()
    settle(app, win.ctl)
    page.rb_stored.setChecked(True)
    page.btn_stored_teams.click()
    settle(app, win.ctl)
    assert ARS in [page.cb_team_stored.itemData(i) for i in range(page.cb_team_stored.count())]
    page.cb_team_stored.setCurrentIndex(page.cb_team_stored.findData(ARS))
    page.btn_compare.click()
    settle(app, win.ctl)
    stored = page.olay_shown["sonuc"]
    assert stored["durum"] == "TAMAMLANDI" and [e["olay_kimligi"] for e in stored["olaylar"]] == EVENTS
    assert page.matrix.rowCount() == 3 and page.matrix.columnCount() == 1 + 5 + 1 + 3
    with C.CalismaAlani.ac(ws) as w:
        direct = O.olay_karsilastir(A.load(archive_dir), ARS, alan=w, calistirma_id=stored["secim"]["calistirma_id"],
                                    grup=1)
    assert direct["sonuc_ozeti"] == stored["sonuc_ozeti"]  # arayüz = doğrudan servis
    # Açık yol: aynı olaylar aynı kurallarla (pencereler aynı; grup filtresi bilgisi yalnızca saklı yolda)
    set_source(page, OF)
    explicit_pick(app, page, ARS, EVENTS)
    page.btn_compare.click()
    settle(app, win.ctl)
    explicit = page.olay_shown["sonuc"]
    direct2 = O.olay_karsilastir(A.load(archive_dir), ARS, kaynak="openfootball", olaylar=EVENTS)
    assert direct2["sonuc_ozeti"] == explicit["sonuc_ozeti"]

    def strip(res):
        return [[{k: v for k, v in p.items() if k != "secim_filtresinde"} for p in e["konumlar"]]
                for e in res["olaylar"]]

    assert strip(stored) == strip(explicit)
    assert stored["toplu"] == explicit["toplu"]
    # Eksik konum metinle; t0 ayrı başlık
    texts = [page.matrix.data(page.matrix.index(r, c)) for r in range(3) for c in range(page.matrix.columnCount())]
    assert any(str(t).startswith("KAYIT YOK") for t in texts)
    assert page.matrix.headerData(6, Qt.Horizontal) == "t0 (olay)"
    assert "İY yok" in " ".join(map(str, texts))  # HT_MISSING kaydı metinle işaretli
    # Hücre ayrıntısı
    page.matrix_view.setCurrentIndex(page.matrix.index(0, 7))
    assert "Ham İY/MS" in page.matrix_detail.toPlainText() and "Kaynak:" in page.matrix_detail.toPlainText()


# ============================================================================ 15
def test_paged_summary_is_labelled_as_page_only(app, ui, paths, archive_dir):
    win, page = ui
    open_archive(app, page, archive_dir)
    set_source(page, OF)
    explicit_pick(app, page, ARS, EVENTS)
    page.sp_limit.setValue(2)
    page.btn_compare.click()
    settle(app, win.ctl)
    r = page.olay_shown["sonuc"]
    assert r["sayfalama"]["toplam_aday"] == 3 and r["toplu"]["olay_sayisi"] == 2 and page.matrix.rowCount() == 2
    assert "Bu sayfadaki olayların özeti (2 olay; toplam aday 3)" in page.lbl_summary.text()
    assert "bütün adayların özeti değildir" in page.lbl_summary.text()
    assert "Olay 1–2 / toplam aday 3" in page.lbl_page.text()
    assert page.btn_next.isEnabled() and not page.btn_prev.isEnabled()
    page.btn_next.click()
    settle(app, win.ctl)
    assert page.matrix.rowCount() == 1 and "Olay 3–3 / toplam aday 3" in page.lbl_page.text()
    assert "(1 olay; toplam aday 3)" in page.lbl_summary.text()
    page.btn_prev.click()
    settle(app, win.ctl)
    assert page.matrix.rowCount() == 2


# ============================================================================ 16
def test_late_results_after_context_change_are_not_shown(app, ui, paths, archive_dir, monkeypatch):
    win, page = ui
    orig_olay, orig_compute = O.olay_karsilastir, C.compute
    open_archive(app, page, archive_dir)
    set_source(page, OF)
    explicit_pick(app, page, ARS, EVENTS)
    gate = Gate()
    monkeypatch.setattr(O, "olay_karsilastir", gate.wrap(orig_olay))
    page.btn_compare.click()
    wait_entered(app, gate)
    page.cb_sonra.setCurrentIndex(page.cb_sonra.findData(5))  # pencere değişti
    gate.release.set()
    settle(app, win.ctl)
    assert page.olay_shown is None and page.matrix.rowCount() == 0 and "gösterilmedi" in page.msg.text()
    assert page.pick_model.picked == set(EVENTS)  # seçim korunur
    # Önizleme: istek sırasında kaynak değişirse sonuç gösterilmez
    gate2 = Gate()
    monkeypatch.setattr(C, "compute", gate2.wrap(orig_compute))
    page.new_research()
    fill(page, "Geç sonuç", G_2024, G_2023)
    page.btn_preview.click()
    wait_entered(app, gate2)
    set_source(page, A.MERGED_VIEW)
    gate2.release.set()
    settle(app, win.ctl)
    assert page.group_shown is None and page.market_model.rowCount() == 0 and "gösterilmedi" in page.msg.text()
    # Arşiv yeniden açılırken başlatılan olay isteği yeni arşiv üzerinde gösterilmez
    gate3 = Gate()
    monkeypatch.setattr(O, "olay_karsilastir", gate3.wrap(orig_olay))
    set_source(page, OF)
    explicit_pick(app, page, ARS, EVENTS)
    page.btn_compare.click()
    wait_entered(app, gate3)
    page.archive_gen += 1  # (aynı anda yeni arşiv yüklemesi tamamlanmış gibi)
    gate3.release.set()
    settle(app, win.ctl)
    assert page.olay_shown is None and page.matrix.rowCount() == 0


# ============================================================================ 17
def test_note_versions_keep_old_and_text_is_not_html(app, ui, paths, archive_dir):
    win, page = ui
    ws = paths / "ws"
    open_archive(app, page, archive_dir)
    create_ws(app, page, ws)
    title = "<b>başlık</b> & <i>eğik</i> <img src='http://example.invalid/t.png'>"
    save_new(app, page, title=title, g1=G_ARS_21, g2=None)
    evil = "<b>kalın</b> <img src='http://example.invalid/x.png'> & <a href='http://example.invalid'>bağlantı</a>"
    page.ed_note.setPlainText(evil)
    page.btn_note_add.click()
    settle(app, win.ctl)
    assert page.note_model.rowCount() == 1 and page.note_model.frame.iloc[0]["metin"] == evil[:80]
    page.note_view.selectRow(0)
    assert evil in page.note_detail.toPlainText()
    page.btn_note_load.click()
    page.ed_note.setPlainText(evil + " (düzeltildi)")
    page.btn_note_version.click()
    settle(app, win.ctl)
    page.note_view.selectRow(0)
    detail = page.note_detail.toPlainText()
    assert "sürüm 2" in detail and "Önceki sürüm 1" in detail and evil in detail
    page.btn_note_archive.click()
    settle(app, win.ctl)
    with C.CalismaAlani.ac(ws) as w:
        n = w.notlar(page.rid)[0]
    assert n["surum"] == 3 and n["durum"] == "arsivlendi" and len(n["onceki_surumler"]) == 2
    assert n["onceki_surumler"][0]["metin"] == evil
    page.chk_archived.setChecked(False)
    assert page.note_model.rowCount() == 0
    page.chk_archived.setChecked(True)
    # Hata: taslak kaybolmaz (çok uzun not)
    long = "x" * (C.LIMITS["not"] + 1)
    page.ed_note.setPlainText(long)
    page.btn_note_add.click()
    settle(app, win.ctl)
    assert "en çok" in page.msg.text() and page.ed_note.toPlainText() == long
    page.ed_note.setPlainText("   ")
    page.btn_note_add.click()
    settle(app, win.ctl)
    assert "boş olamaz" in page.msg.text()
    # Maça bağlı not ve kart (aynı görünüm)
    page.btn_run.click()
    settle(app, win.ctl)
    page.rb_stored.setChecked(True)
    page.btn_stored_teams.click()
    settle(app, win.ctl)
    page.cb_team_stored.setCurrentIndex(page.cb_team_stored.findData(ARS))
    page.btn_compare.click()
    settle(app, win.ctl)
    page.matrix_view.setCurrentIndex(page.matrix.index(0, 6))  # t0
    assert page.link_match == (E1, OF) and E1 in page.lbl_link.text()
    page.ed_note.setPlainText("bağlı <i>not</i>")
    page.btn_note_match.click()
    settle(app, win.ctl)
    # Not eklemek (geçmiş yenilenir) gösterilen olay matrisini ve takım seçimini silmez
    assert page.matrix.rowCount() == 3 and page.cb_team_stored.currentData() == ARS and page.olay_shown is not None
    with C.CalismaAlani.ac(ws) as w:
        linked = [x for x in w.notlar(page.rid) if x["mac_kimligi"]][0]
    assert linked["mac_kimligi"] == E1 and linked["gorunum_kaynak"] == OF
    row = page.note_model.frame.index[page.note_model.frame["mac_kimligi"] == E1][0]
    page.note_view.selectRow(page.note_proxy.mapFromSource(page.note_model.index(int(row), 0)).row())
    page.btn_note_card.click()
    settle(app, win.ctl)
    assert ARS in page.card_text.toPlainText() and page.card_model.rowCount() > 0
    # Hiçbir dinamik metin HTML olarak yorumlanmaz: başlık ve not metni ham hâliyle, düz metin etiketlerde
    page.matrix_view.setCurrentIndex(page.matrix.index(0, 6))
    page.btn_open_run.click()
    settle(app, win.ctl)
    shown = [lbl for lbl in page.findChildren(QLabel) if "<b>başlık</b>" in lbl.text()]
    assert len(shown) >= 3  # taslak durumu, geçmiş ve saklı sonuç başlığı
    for lbl in page.findChildren(QLabel):
        if any(x in lbl.text() for x in ("<b>kalın", "<i>not", "<b>başlık")):
            assert lbl.textFormat() == Qt.PlainText, lbl.text()
    assert page.list_model.frame.iloc[0]["baslik"] == title


# ============================================================================ 18
def test_event_loop_keeps_running_while_worker_runs(app, ui, paths, archive_dir, monkeypatch):
    win, page = ui
    open_archive(app, page, archive_dir)
    gate = Gate()
    monkeypatch.setattr(C, "compute", gate.wrap(C.compute))
    page.new_research()
    fill(page, "Döngü", G_2024, G_2023)
    page.btn_preview.click()
    wait_entered(app, gate)
    ticks = []
    QTimer.singleShot(0, lambda: ticks.append(win.ctl.busy))
    for _ in range(20):
        app.processEvents()
        time.sleep(0.005)
    assert ticks == [True]  # iş sürerken olay döngüsü çalışıyor
    page.ed_title.setText("İş sürerken yazıldı")  # form kullanılabilir
    assert not page.btn_preview.isEnabled() and not page.btn_save.isEnabled()  # iş başlatan düğmeler kapalı
    gate.release.set()
    settle(app, win.ctl)
    assert page.btn_preview.isEnabled()


# ============================================================================ 19
def test_closing_during_compute_and_during_write_is_safe(app, paths, archive_dir, monkeypatch):
    # (a) okuma (önizleme) sürerken kapanış: sormadan beklenir, sonra pencere güvenle silinir
    win, page = make_window(app)
    win.show()
    open_archive(app, page, archive_dir)
    page.new_research()
    fill(page, "Kapanış", G_2024, G_2023)
    page.ask_unsaved = lambda action: "discard"
    gate = Gate()
    monkeypatch.setattr(C, "compute", gate.wrap(C.compute))
    page.btn_preview.click()
    wait_entered(app, gate)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a) or QMessageBox.Yes)
    threading.Timer(0.3, gate.release.set).start()
    win.close()
    # salt okuma: soru yok; pencere gizlendi ve iş parçacığı bitti (geri çağrı henüz işlenmedi)
    assert not win.isVisible() and win.ctl._task.isFinished() and asked == []
    from PySide6.QtCore import QCoreApplication, QEvent

    win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    for _ in range(5):
        app.processEvents()  # bekleyen geri çağrı silinen sayfaya dokunmaz
    # (b) yazma sürerken kapanış: onay sorulur; "Hayır" → pencere açık, iş sürer; "Evet" → yazma tamamlanır
    win, page = make_window(app)
    win.show()
    ws = paths / "ws"
    open_archive(app, page, archive_dir)
    create_ws(app, page, ws)
    page.new_research()
    fill(page, "Yazma sırasında kapanış", G_2024, G_2023)
    gate = Gate()
    monkeypatch.setattr(C.CalismaAlani, "arastirma_olustur", gate.wrap(C.CalismaAlani.arastirma_olustur))
    page.btn_save.click()
    wait_entered(app, gate)
    assert win.ctl.busy_critical
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    win.close()
    assert win.isVisible() and win.ctl.busy
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    threading.Timer(0.3, gate.release.set).start()
    win.close()
    assert not win.isVisible() and win.ctl._task.isFinished()
    assert db_rows(ws, "arastirma_revizyonlari") == 1  # yazma yarım kalmadı
    settle(app, win.ctl)
    assert page.rid is not None  # tamamlanan yazma "iptal" diye gizlenmedi
    win.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


# ============================================================================ 20
def test_widget_and_sqlite_thread_boundaries(app, ui, paths, archive_dir, monkeypatch):
    win, page = ui
    main = threading.get_ident()
    opened, closed, callbacks, jobs = [], [], [], []
    orig_init, orig_close = C.CalismaAlani.__init__, C.CalismaAlani.close

    def rec_init(self, folder, conn, writable):
        opened.append(threading.get_ident())
        orig_init(self, folder, conn, writable)

    def rec_close(self):
        closed.append(threading.get_ident())
        orig_close(self)

    monkeypatch.setattr(C.CalismaAlani, "__init__", rec_init)
    monkeypatch.setattr(C.CalismaAlani, "close", rec_close)
    orig_run = win.ctl.run_job

    def rec_run(fn, on_done, label, critical=True):
        jobs.append(fn.job)
        return orig_run(fn, lambda res: (callbacks.append(threading.get_ident()), on_done(res)), label, critical)

    monkeypatch.setattr(win.ctl, "run_job", rec_run)
    ws = paths / "ws"
    open_archive(app, page, archive_dir)
    create_ws(app, page, ws)
    save_new(app, page, g1=G_ARS_21, g2=G_2023)
    page.btn_preview.click()
    settle(app, win.ctl)
    page.btn_run.click()
    settle(app, win.ctl)
    page.btn_verify.click()
    settle(app, win.ctl)
    page.ed_note.setPlainText("iş parçacığı")
    page.btn_note_add.click()
    settle(app, win.ctl)
    page.rb_stored.setChecked(True)
    page.btn_stored_teams.click()
    settle(app, win.ctl)
    page.cb_team_stored.setCurrentIndex(page.cb_team_stored.findData(ARS))
    page.btn_compare.click()
    settle(app, win.ctl)
    assert len(jobs) >= 8 and opened and len(opened) == len(closed)
    assert main not in opened and main not in closed  # SQLite yalnızca işte açılıp kapandı
    assert set(callbacks) == {main}  # sonuçlar ana iş parçacığında işlendi

    def no_qt(o, depth=0):
        assert not isinstance(o, QObject), o
        if depth < 4:
            if isinstance(o, dict):
                for v in o.values():
                    no_qt(v, depth + 1)
            elif isinstance(o, (list, tuple, set)):
                for v in o:
                    no_qt(v, depth + 1)

    for j in jobs:
        assert j.func.__module__.endswith("ui.pages.research") and j.func.__name__.startswith("job_")
        no_qt(list(j.args))
        no_qt(dict(j.keywords))
    for v in vars(page).values():  # sayfa bağlantı veya çalışma alanı nesnesi tutmaz
        assert not isinstance(v, (C.CalismaAlani, sqlite3.Connection))


# ============================================================================ 21
def test_existing_pages_and_archive_panel_remain(app, ui):
    from bahis_tahmin.ui.main_window import NAV
    from bahis_tahmin.ui.pages.archive_panel import ArchivePanel
    from bahis_tahmin.ui.pages.data import DataPage
    from bahis_tahmin.ui.pages.goals import GoalsPage
    from bahis_tahmin.ui.pages.sequences import SequencesPage

    names = [n for n, _ in NAV]
    assert names.count("Araştırma Çalışma Alanı") == 1
    assert names.index("Araştırma Çalışma Alanı") == names.index("Dizi Araştırması") + 1
    for cls in (DataPage, GoalsPage, SequencesPage):
        assert any(c is cls for _, c in NAV)
    win, page = ui
    assert win.page(DataPage).findChild(ArchivePanel) is not None and win.nav.count() == len(NAV)


def test_min_size_has_no_horizontal_page_overflow(app, ui, paths, archive_dir):
    """En küçük pencerede sayfa yatay taşmaz; uzun ve boşluksuz yollar (ör. Windows geçici klasörü) ve uzun hata
    metinleri de taşırmaz (matris kendi içinde kaydırılabilir)."""
    import shutil

    from PySide6.QtWidgets import QScrollArea

    win, page = ui
    win.resize(1024, 680)
    win.show()
    deep = paths / ("cok_uzun_klasor_adi_" * 4) / ("ikinci_uzun_klasor_adi_" * 3)
    shutil.copytree(archive_dir, deep / "arsiv")
    open_archive(app, page, deep / "arsiv")
    create_ws(app, page, deep / "calisma_alani_uzun_adli_klasor")
    page.ed_ws.setText(str(deep / "olmayan_calisma_alani_klasoru_bu_da_uzun"))
    page.btn_open_ws.click()  # uzun yol içeren hata metni
    settle(app, win.ctl)
    assert "Çalışma alanı yok" in page.lbl_ws.text()
    scroll = page.findChild(QScrollArea)
    for i in range(page.tabs.count()):
        page.tabs.setCurrentIndex(i)
        for _ in range(3):
            app.processEvents()
        assert scroll.horizontalScrollBar().maximum() == 0, page.tabs.tabText(i)
        assert page.width() <= win.width()


# ============================================================================ 22
def test_process_exits_zero_after_page_use(tmp_path, archive_dir):
    """Ayrı süreçte sayfa kullanılır ve uygulama kapatılır: çıkış kodu 0, Qt kapanış uyarısı yok."""
    script = tmp_path / "kapanis.py"
    script.write_text(
        "import sys, time\n"
        "from PySide6.QtWidgets import QApplication\n"
        "from bahis_tahmin.ui.theme import apply_theme\n"
        "from bahis_tahmin.ui.main_window import MainWindow\n"
        "from bahis_tahmin.ui.pages.research import ResearchPage\n"
        "app = QApplication([])\napply_theme(app)\nwin = MainWindow()\nwin.show()\n"
        "page = win.page(ResearchPage)\nwin.nav.setCurrentRow(win.pages.index(page))\n"
        "page.ask_unsaved = lambda action: 'discard'\n"
        f"page.ed_archive.setText({str(archive_dir)!r})\npage.btn_open_archive.click()\n"
        "def later():\n"
        "    if win.ctl.busy:\n        return\n"
        "    timer.stop()\n    page.ed_title.setText('Kapanış')\n    page.btn_preview.click()\n"
        "    win.close()\n    app.quit()\n"
        "from PySide6.QtCore import QTimer\ntimer = QTimer()\ntimer.timeout.connect(later)\ntimer.start(50)\n"
        "sys.exit(app.exec())\n", encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", BAHIS_TAHMIN_HOME=str(tmp_path / "home"),
               BAHIS_TAHMIN_CALISMA=str(tmp_path / "calisma"), BAHIS_TAHMIN_ARSIV=str(tmp_path / "arsiv-yok"))
    root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(root)
    p = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=300, env=env, cwd=tmp_path)
    assert p.returncode == 0, p.stderr[-2000:]
    assert "QObject" not in p.stderr and "Traceback" not in p.stderr, p.stderr[-2000:]
    assert not (tmp_path / "calisma").exists()
