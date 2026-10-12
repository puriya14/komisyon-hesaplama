"""Arşiv görünümü ve çoklu olay karşılaştırması için tekrar çalıştırılabilir süre/bellek ölçümü (S6-PERF-03).

Salt okunurdur: arşivi ``archive.load`` ile okur, hiçbir dosyaya veya ağa yazmaz. Aynı aracı farklı bir paket köküyle
(``--paket-kok``) çalıştırarak eski ve yeni kodu aynı makinede, aynı arşiv ve aynı girdiyle karşılaştırabilirsiniz.

Aşamalar (her biri ayrı ölçülür):
  A yukle       archive.load (ham dosya özetleri ve satır özetleri doğrulanır)
  B tek_kaynak  archive.view(arsiv, kaynak)
  C birlesik    archive.view(arsiv, None)
  D zaman       archive.team_matches(tek_kaynak_gorunumu, lig)
  E coklu       çoklu olay hesabı (hazır görünüm ve veri özetiyle; takım-maç tablosu ve son özet denetimi dahil)
  F1 veri_ozeti calisma.snapshot (görünümün veri özeti)
  F2 json       calisma.to_json(sonuç)
  S servis      olay_karsilastir uçtan uca (süreç içinde)
  G cli         ``python -m bahis_tahmin calisma-olay-karsilastir`` yeni süreçte, duvar saati

"İlk çağrı" her geçişin yeni bir Python sürecinde yapıldığı ölçümdür. İşletim sistemi dosya önbelleği temizlenmez,
dolayısıyla soğuk disk ölçümü değildir. "Tekrar çağrı" aynı süreçte arka arkaya yapılan geçişlerdir. Bellek iki ayrı
yöntemle ölçülür: tracemalloc (yalnızca Python/numpy tahsislerinin aşama içi tepe değeri; ayrı süreçte, süre ölçümüne
karışmaz) ve süreç tepe RSS'i (``resource.getrusage``, Linux'ta KB). Süreler sonuç JSON'una veya özetine yazılmaz.

Örnek:
  python tools/perf_arsiv.py --ev <ARSIV> --takim "Arsenal FC" --kaynak openfootball --olay-dosyasi olaylar.txt \
      --tekrar 5 --cikti olcum.json [--paket-kok <ESKI_KOD_KOKU>]
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASES = ("A_yukle", "B_tek_kaynak", "C_birlesik", "D_zaman", "E_coklu", "F1_veri_ozeti", "F2_json", "S_servis")


def _import(root: Path):
    sys.path.insert(0, str(root))
    from bahis_tahmin import archive as A
    from bahis_tahmin import calisma as C
    from bahis_tahmin import olay_karsilastirma as O

    return A, C, O


def _ids(path: str) -> list:
    return [x.strip() for x in Path(path).read_text(encoding="utf-8").splitlines()
            if x.strip() and not x.strip().startswith("#")]


def one_pass(a, A, C, S, track=None) -> dict:
    """Bir ölçüm geçişi; her aşamanın süresi (sn). ``track``: aşama içi bellek tepe değeri ölçücüsü (isteğe bağlı)."""
    ids = _ids(a.olay_dosyasi)
    out, mem = {}, {}

    def step(name, fn):
        if track:
            track.reset_peak()
        t = time.perf_counter()
        res = fn()
        out[name] = time.perf_counter() - t
        if track:
            mem[name] = track.get_traced_memory()[1]
        return res

    ar = step("A_yukle", lambda: A.load(a.ev))
    v = step("B_tek_kaynak", lambda: A.view(ar, a.kaynak))
    step("C_birlesik", lambda: A.view(ar, None))
    lig = ids[0].split("|", 1)[0]
    step("D_zaman", lambda: A.team_matches(v, lig))
    snap = step("F1_veri_ozeti", lambda: C.snapshot(ar, v))
    opts = S.secenekler()
    sel = {"tur": S.MODE_MANUAL}
    res = step("E_coklu", lambda: S._compute(ar, v, snap, a.takim, sorted(set(ids)), sel, None, None, opts, [],
                                               explicit=True))
    step("F2_json", lambda: C.to_json(res))
    full = step("S_servis", lambda: S.olay_karsilastir(ar, a.takim, kaynak=a.kaynak, olaylar=ids))
    out["_kontrol"] = {"olay": len(full["olaylar"]), "veri_ozeti": full["veri"]["veri_ozeti"],
                       "tek_kaynak_mac": int(len(v.merged))}
    if track:
        out["_bellek"] = mem
    return out


def _child(a) -> None:
    A, C, S = _import(Path(a.paket_kok))
    if a.mod == "tek":
        res = one_pass(a, A, C, S)
        import resource

        res["_rss_kb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        res["_modul"] = A.__file__
        print(json.dumps(res))
    elif a.mod == "tekrar":
        print(json.dumps([one_pass(a, A, C, S) for _ in range(a.tekrar + 1)]))  # ilk geçiş ısınma; istatistiğe katılmaz
    elif a.mod == "bellek":
        import tracemalloc

        tracemalloc.start()
        print(json.dumps(one_pass(a, A, C, S, track=tracemalloc)))


def _run(a, mod: str, cwd: str):
    env = dict(os.environ, PYTHONPATH=str(a.paket_kok))
    cmd = [sys.executable, str(Path(__file__).resolve()), "--_cocuk", "--mod", mod, "--ev", a.ev, "--takim", a.takim,
           "--kaynak", a.kaynak, "--olay-dosyasi", a.olay_dosyasi, "--tekrar", str(a.tekrar), "--paket-kok",
           str(a.paket_kok)]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env, check=True)
    return json.loads(p.stdout.strip().splitlines()[-1])


def _stats(xs) -> dict:
    return {"medyan": statistics.median(xs), "min": min(xs), "maks": max(xs), "n": len(xs)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ev", required=True, help="arşiv klasörü (salt okunur)")
    p.add_argument("--takim", required=True)
    p.add_argument("--kaynak", default="openfootball")
    p.add_argument("--olay-dosyasi", required=True, help="her satırda bir olay kimliği")
    p.add_argument("--tekrar", type=int, default=5, help="eşdeğer tekrar sayısı (en az 5 önerilir)")
    p.add_argument("--paket-kok", default=str(ROOT), help="ölçülecek bahis_tahmin paketinin kök klasörü")
    p.add_argument("--cikti", help="sonuçların yazılacağı JSON dosyası")
    p.add_argument("--_cocuk", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--mod", choices=["tek", "tekrar", "bellek"], help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    a.paket_kok = str(Path(a.paket_kok).resolve())
    if a._cocuk:
        _child(a)
        return 0
    with tempfile.TemporaryDirectory() as cwd:  # cwd'deki başka bir paket yanlışlıkla içe aktarılmasın
        first = [_run(a, "tek", cwd) for _ in range(a.tekrar)]
        repeat = _run(a, "tekrar", cwd)[1:]
        mem = _run(a, "bellek", cwd)
        cli = []
        env = dict(os.environ, PYTHONPATH=a.paket_kok, BAHIS_TAHMIN_HOME=str(Path(cwd) / "home"))
        for _ in range(a.tekrar):
            t = time.perf_counter()
            r = subprocess.run([sys.executable, "-m", "bahis_tahmin", "calisma-olay-karsilastir", "--ev", a.ev,
                                "--kaynak", a.kaynak, "--takim", a.takim, "--olay-dosyasi", a.olay_dosyasi],
                               capture_output=True, text=True, cwd=cwd, env=env)
            cli.append(time.perf_counter() - t)
            if r.returncode != 0:
                raise SystemExit(f"CLI çıkış kodu {r.returncode}: {r.stderr[-500:]}")
    checks = {json.dumps(x["_kontrol"], sort_keys=True) for x in first + repeat}
    report = {
        "ortam": {"python": sys.version.split()[0], "platform": platform.platform(), "cpu": os.cpu_count(),
                  "paket_kok": a.paket_kok, "modul": first[0]["_modul"]},
        "girdi": {"ev": a.ev, "kaynak": a.kaynak, "takim": a.takim, "olay": len(_ids(a.olay_dosyasi))},
        "kontrol": [json.loads(c) for c in sorted(checks)],
        "ilk_cagri_sn": {k: _stats([x[k] for x in first]) for k in PHASES},
        "tekrar_cagri_sn": {k: _stats([x[k] for x in repeat]) for k in PHASES},
        "cli_uctan_uca_sn": _stats(cli),
        "bellek": {"yontem": "tracemalloc aşama içi tepe (yalnızca Python/numpy tahsisleri, bayt); süreç tepe RSS "
                             "(ru_maxrss, KB, tek geçişlik yeni süreç)",
                   "tracemalloc_tepe_bayt": mem["_bellek"],
                   "surec_tepe_rss_kb": _stats([x["_rss_kb"] for x in first])},
        "not": "İlk çağrı: yeni süreçte ilk geçiş; işletim sistemi dosya önbelleği temizlenmedi (soğuk disk değildir).",
    }
    txt = json.dumps(report, ensure_ascii=False, indent=1)
    if a.cikti:
        Path(a.cikti).write_text(txt, encoding="utf-8")
    print(txt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
