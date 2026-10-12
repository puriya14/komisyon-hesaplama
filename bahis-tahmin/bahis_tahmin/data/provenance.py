"""Sonuç verisinin kaynak kökeni (S4-PILOT-01).

openfootball sonuç satırları (etiket ``openfootball-sonuc``) yalnızca kökenleri doğrulanırsa hak kazanır: her
(lig, sezon) için veri deposunun ``meta["kaynak_kokeni"]`` kaydında kaynak deposu, dosya yolu, sabitlenmiş commit,
alınma anı, dosya içerik özeti ve ayrıştırıcı sürümü bulunmalı; önbellekteki dosya aynı özete sahip olmalı ve aynı
ayrıştırıcı bu dosyadan depodaki satırların BİREBİR aynısını üretmeli. Böylece başka kaynaktan gelen eski satırların
etiketi değiştirilerek (ör. football-data satırlarına ``openfootball-sonuc`` yazılarak) hak kazanılamaz.

Kaynak hakkı (lisans) ile adaptörün yeteneği ayrıdır: lisans ``source_registry`` kaydındadır; bu modül yalnızca
satırların gerçekten o kaynaktan geldiğini doğrular.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from .parsers import OPENFOOTBALL_RESULT_LABEL, OPENFOOTBALL_RESULT_PARSERS, parse_openfootball_results

OPENFOOTBALL_REPO = "openfootball/football.json"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class SourceFile:
    """Bir sezon dosyasının kökeni (deposu, yolu, sabit commit, alınma anı, içerik ve satır özetleri)."""
    repo: str
    path: str  # depodaki yol, ör. "2025-26/en.1.json"
    ref: str  # sabitlenmiş commit (40 onaltılık)
    url: str
    retrieved_at: str  # UTC ISO; dosyanın alındığı gerçek an (içindeki skorların güncelliği DEĞİL)
    sha256: str  # dosya baytlarının özeti
    league: str
    season: str  # depo etiketi, ör. "2025/26"
    parser: str
    rows: int
    rows_sha256: str
    cache_rel: str  # veri deposunun ham önbelleğine göre yol

    def to_dict(self) -> dict:
        return asdict(self)


def rows_sha256(df: pd.DataFrame) -> str:
    """Sonuç satırlarının içerik özeti (sıra bağımsız): lig, sezon, tarih, takımlar, MS ve İY skorları."""
    def cell(v) -> str:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return ""
        return "" if f != f else str(int(f))

    keys = sorted("|".join([str(lg), str(se), str(pd.Timestamp(d).date()), str(h), str(a), cell(fh), cell(fa),
                            cell(hh), cell(ha)])
                  for lg, se, d, h, a, fh, fa, hh, ha in zip(df["league"], df["season"], df["date"], df["home"],
                                                              df["away"], df["fthg"], df["ftag"], df["hthg"],
                                                              df["htag"]))
    return hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()


def _record(r) -> SourceFile | None:
    try:
        rec = r if isinstance(r, SourceFile) else SourceFile(**{k: r[k] for k in SourceFile.__dataclass_fields__})
    except (KeyError, TypeError):
        return None
    if not (_SHA40.match(str(rec.ref)) and _SHA256.match(str(rec.sha256)) and _SHA256.match(str(rec.rows_sha256))):
        return None
    return rec


def verify_results(matches: pd.DataFrame | None, records, raw_dir) -> tuple[bool, list[str]]:
    """``openfootball-sonuc`` etiketli bütün satırlar kayıtlı ve önbellekte doğrulanabilir kaynak dosyalarından mı?

    Döner: (doğrulandı mı, sorunlar). Etiketli satır yoksa doğrulanmış sayılmaz."""
    if matches is None or matches.empty or "source" not in matches:
        return False, ["sonuç satırı yok"]
    rows = matches[matches["source"] == OPENFOOTBALL_RESULT_LABEL]
    if rows.empty:
        return False, ["sonuç satırı yok"]
    problems: list[str] = []
    recs = {}
    for r in records or ():
        rec = _record(r)
        if rec is None:
            problems.append("geçersiz köken kaydı")
            continue
        if rec.repo != OPENFOOTBALL_REPO or rec.parser not in OPENFOOTBALL_RESULT_PARSERS:
            problems.append(f"{rec.season}: kaynak deposu veya ayrıştırıcı sürümü farklı")
            continue
        recs[(rec.league, rec.season)] = rec
    for (lg, season), g in rows.groupby([rows["league"], rows["season"].astype(str)]):
        rec = recs.get((lg, season))
        if rec is None:
            problems.append(f"{lg} {season}: köken kaydı yok")
            continue
        path = Path(raw_dir) / rec.cache_rel
        if not path.is_file():
            problems.append(f"{lg} {season}: kaynak dosyası önbellekte yok")
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != rec.sha256:
            problems.append(f"{lg} {season}: dosya özeti kayıtla uyuşmuyor")
            continue
        parsed = parse_openfootball_results(data, lg, season, rec.parser).matches  # kaydın kendi sürümüyle
        digest = rows_sha256(g)
        if digest != rows_sha256(parsed) or digest != rec.rows_sha256 or len(g) != rec.rows:
            problems.append(f"{lg} {season}: depodaki satırlar kaynak dosyasından üretilenlerle aynı değil")
    return (not problems), problems


def verified_labels(store) -> set[str]:
    """Veri deposundaki kökeni doğrulanmış sonuç etiketleri (kayıt yoksa boş küme; ağ isteği yapmaz)."""
    from .completion import COMPLETION_LABEL, verify_completion

    meta = getattr(store, "meta", None) or {}
    out: set[str] = set()
    matches, raw_dir = getattr(store, "matches", None), getattr(store, "raw_dir", ".")
    records = meta.get("kaynak_kokeni") or []
    if records and verify_results(matches, records, raw_dir)[0]:
        out.add(OPENFOOTBALL_RESULT_LABEL)
    completion = meta.get("tamamlama_kokeni") or []
    if completion and verify_completion(matches, completion, raw_dir)[0]:
        out.add(COMPLETION_LABEL)  # VERI-02: güncel sezon tamamlaması
    return out
