"""Araştırma verisinin kökenini pickle açmadan doğrular.

Ham yedek dosyadan (xgabora Matches.csv önbelleği) projenin kendi ayrıştırıcısıyla, AĞA ÇIKMADAN (çevrimdışı önbellek)
maç tablosunu yeniden kurar ve içerik özetini (sequences.research.data_sha256, bellek içi tablo üzerinde) beklenen
değerle karşılaştırır. Not: tabloyu CSV'ye yazıp geri okumak tür (dtype) dönüşümleri nedeniyle özeti değiştirir;
karşılaştırma bellek içi tablo üzerinde yapılmalıdır.

Kullanım: python -I veri_kokeni_dogrula.py <ham_Matches.csv> <yeni_bos_klasor> [<beklenen_sha256>]
"""
import datetime as dt
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bahis_tahmin.data.sources import Downloader  # noqa: E402
from bahis_tahmin.data.store import DataStore  # noqa: E402
from bahis_tahmin.sequences.research import data_sha256  # noqa: E402

LEAGUES = ["T1", "E0", "E1", "E2", "E3", "EC", "SC0", "SC1", "SC2", "SC3", "D1", "D2", "I1", "I2", "SP1", "SP2",
           "F1", "F2", "N1", "B1", "P1", "G1"]


def main() -> int:
    raw, out = Path(sys.argv[1]), Path(sys.argv[2])
    expected = sys.argv[3] if len(sys.argv) > 3 else None
    if out.exists() and any(out.iterdir()):
        print("Çıktı klasörü boş olmalı (mevcut veriye dokunulmaz).", file=sys.stderr)
        return 2
    (out / "raw" / "mirror").mkdir(parents=True)
    shutil.copy2(raw, out / "raw" / "mirror" / "Matches.csv")
    print("ham dosya sha256:", hashlib.sha256(raw.read_bytes()).hexdigest())
    st = DataStore(out)
    dl = Downloader(out / "raw", offline=True)
    st.update(LEAGUES, 26, today=dt.date(2026, 10, 10), downloader=dl, allowed={"github-mirror"})
    m = st.matches
    sha = data_sha256(m)
    print(f"maç {len(m)}, lig {m['league'].nunique()}, {m['date'].min().date()} – {m['date'].max().date()}, "
          f"ağ isteği {dl.stats['network']}")
    print("içerik sha256 (bellek içi):", sha)
    if expected:
        print("beklenenle aynı:", sha == expected)
        return 0 if sha == expected else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
