"""Web arayüzü (tarayıcıdan kullanım).

Masaüstü uygulamasıyla aynı veri klasörünü, ayarları, modeli ve kuralları kullanır (``bahis_tahmin.core``). Sunucu
varsayılan olarak yalnızca bu bilgisayardan erişilebilir (127.0.0.1). Aynı ağdaki başka bir cihazdan (ör. telefon)
erişim yalnızca parolayla açılır: ``python -m bahis_tahmin web --paylas --parola ...``.

Güvenlik:
* Her POST isteği oturuma bağlı CSRF anahtarı ister (başka bir web sitesi tarayıcınız üzerinden onay veremez,
  güncelleme başlatamaz).
* Yerel modda ``Host`` başlığı denetlenir (DNS yeniden bağlama saldırısına karşı).
* Parolalı modda her sayfa girişi ister; parola karşılaştırması sabit sürelidir.
* Satır içi betik yoktur; içerik güvenlik politikası yalnızca uygulamanın kendi dosyalarına izin verir.
"""

from __future__ import annotations

import hmac
import logging
import secrets
import time
from pathlib import Path

from flask import Flask, abort, redirect, request, session, url_for
from markupsafe import Markup

from .. import APP_TITLE, __version__
from .state import WebState

log = logging.getLogger(__name__)

DEFAULT_PORT = 8765
LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def create_app(home=None, password: str | None = None, port: int = DEFAULT_PORT, load: bool = True,
               state: WebState | None = None) -> Flask:
    """Web uygulamasını kurar. ``password``: verilirse her sayfa girişi ister (ağda paylaşım). ``load``: kayıtlı
    veri ve modeller arka planda yüklenir (testlerde durum elle kurulabilir)."""
    pkg = Path(__file__).resolve().parent
    app = Flask("bahis_tahmin.web", template_folder=str(pkg / "templates"), static_folder=str(pkg / "static"))
    app.secret_key = secrets.token_bytes(32)  # oturum ve CSRF anahtarı yalnızca bu çalıştırma için
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        MAX_CONTENT_LENGTH=1_000_000,
        TEMPLATES_AUTO_RELOAD=False,
        BT_PASSWORD=password or None,
        BT_PORT=int(port),
    )
    st = state or WebState(home)
    app.extensions["bahis_tahmin"] = st

    from . import filters, views

    filters.register(app)
    app.register_blueprint(views.bp)
    from . import gol

    app.register_blueprint(gol.bp)

    @app.before_request
    def _guard():
        if request.endpoint == "static":
            return None
        if not app.config["BT_PASSWORD"]:
            host = (request.host or "").rsplit(":", 1)[0] if not (request.host or "").startswith("[") else \
                (request.host or "").split("]")[0] + "]"
            if host not in LOCAL_HOSTS:
                abort(403, "Bu sunucu yalnızca bu bilgisayardan (127.0.0.1) kullanılabilir.")
        elif not session.get("giris") and request.endpoint not in ("views.giris",):
            return redirect(url_for("views.giris", sonra=request.full_path if request.method == "GET" else None))
        if request.method == "POST":
            sent = request.form.get("csrf") or request.headers.get("X-CSRF", "")
            if not sent or not hmac.compare_digest(sent, csrf_token()):
                abort(400, "Oturum anahtarı geçersiz; sayfayı yenileyip yeniden deneyin.")
        st.ensure_fresh()
        return None

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                "script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        if request.endpoint != "static":
            resp.headers.setdefault("Cache-Control", "no-store")
        if request.method == "POST" and st.core.loaded:
            st.remember_disk()  # bu istekte kaydedilen ayarlar masaüstündeki bir değişiklik sayılmaz
        return resp

    @app.context_processor
    def _ctx():
        return {"csrf": csrf_token(), "job": st.jobs.status(), "core": st.core, "app_title": APP_TITLE,
                "version": __version__, "parolali": bool(app.config["BT_PASSWORD"])}

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    def _err(e):
        from flask import render_template

        return render_template("hata.html", kod=e.code, mesaj=getattr(e, "description", str(e))), e.code

    if load:
        st.start_load()
    return app


def csrf_token() -> str:
    tok = session.get("csrf")
    if not tok:
        tok = session["csrf"] = secrets.token_urlsafe(32)
    return tok


def check_password(app: Flask, given: str) -> bool:
    expected = app.config.get("BT_PASSWORD") or ""
    ok = bool(expected) and hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))
    if not ok:
        time.sleep(1.0)  # deneme yanılmayı yavaşlatır
    return ok


def get_state() -> WebState:
    from flask import current_app

    return current_app.extensions["bahis_tahmin"]


def svg_img(canvas) -> Markup:
    """matplotlib SVG'si ``<img>`` olarak (veri URI'si; SVG içindeki metin betik olarak çalışamaz)."""
    import base64

    data = base64.b64encode(canvas.svg().encode("utf-8")).decode("ascii")
    return Markup(f'<img class="chart" alt="grafik" src="data:image/svg+xml;base64,{data}">')


def lan_addresses() -> list[str]:
    """Bu bilgisayarın yerel ağ adresleri (telefondan bağlanmak için gösterilir)."""
    import socket

    out = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # paket gönderilmez; yalnızca çıkış arayüzü seçilir
        out.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return [a for a in out if not a.startswith("127.")]


def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT, password: str | None = None,
          open_browser: bool = True) -> int:
    """Sunucuyu başlatır (Waitress; yoksa Flask'ın kendi sunucusu). Yerel olmayan adreste parola zorunludur."""
    local = host in ("127.0.0.1", "localhost", "::1")
    if not local and not password:
        print("Ağda paylaşım için parola gerekir: --parola ...")
        return 2
    app = create_app(password=password, port=port)
    url = f"http://127.0.0.1:{port}/"
    print(f"{APP_TITLE} web arayüzü: {url}")
    if not local:
        for a in lan_addresses():
            print(f"Aynı ağdaki cihazlardan: http://{a}:{port}/  (parola gerekir)")
    print("Kapatmak için bu pencereyi kapatın veya Ctrl+C'ye basın.")
    if open_browser:
        import threading
        import webbrowser

        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve as wserve

        wserve(app, host=host, port=port, threads=8, ident=APP_TITLE)
    except ImportError:
        app.run(host=host, port=port, threaded=True, use_reloader=False)
    return 0
