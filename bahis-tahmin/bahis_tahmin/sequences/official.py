"""Resmî kararlar kaydı (sözleşme §4, §11) — anomali ve örüntü hesaplarından AYRI, yalnızca ekleme.

* Kaynak, karar tarihi, kapsam (maç/olay kimlikleri), tür, itiraz/kesinleşme durumu ve not saklanır.
* Kayıt silinmez veya değiştirilmez; düzeltme ``supersedes`` alanıyla YENİ kayıttır. Dosya bir özet zinciri
  (SHA-256) taşır; sessiz değişiklik eklemeden önce tespit edilir.
* Bir karar, karar tarihinden ÖNCE hiçbir hesaba giremez: ``decisions_known_at(t)`` yalnızca
  ``decision_date < t`` (İstanbul yerel tarihi) kararları döndürür.
* Kaydın olmaması "temiz" anlamına gelmez: durum ``KAYIT_YOK`` olarak döner (asla "TEMIZ").
* Şu an hiçbir resmî karar veri kaynağı entegre değildir; kayıt varsayılan olarak boştur.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from ..timeutil import ISTANBUL

FINALITY = ("itiraz_edildi", "kesinlesmedi", "kesin")
NO_RECORD = "KAYIT_YOK"
SCHEMA_VERSION = 1
SOURCE_NOTE = ("Resmî karar veri kaynağı entegre değil; kayıt yalnızca elle eklenen kararları içerir. "
               "Kaydın olmaması 'temiz' anlamına gelmez (durum: KAYIT_YOK).")
GENESIS = "0" * 64


def _nonempty(name: str, v) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{name} boş olmayan metin olmalı")
    return v


@dataclass(frozen=True)
class OfficialDecision:
    decision_id: str
    source: str
    decision_date: dt.date
    scope_event_ids: list
    kind: str
    finality: str
    note: str = ""
    supersedes: str | None = None

    def __post_init__(self) -> None:
        _nonempty("decision_id", self.decision_id)
        _nonempty("source", self.source)
        _nonempty("kind", self.kind)
        if isinstance(self.decision_date, dt.datetime) or not isinstance(self.decision_date, dt.date):
            raise ValueError("decision_date saat içermeyen bir tarih (datetime.date) olmalı")
        scope = self.scope_event_ids
        if isinstance(scope, (str, bytes)) or not isinstance(scope, (list, tuple)):
            raise ValueError("scope_event_ids olay kimliklerinin listesi olmalı")
        scope = [_nonempty("scope_event_ids öğesi", e) for e in scope]
        if not scope:
            raise ValueError("scope_event_ids en az bir maç/olay kimliği içermeli")
        if len(set(scope)) != len(scope):
            raise ValueError("scope_event_ids tekrar eden kimlik içeremez")
        object.__setattr__(self, "scope_event_ids", list(scope))
        if self.finality not in FINALITY:
            raise ValueError(f"finality şunlardan biri olmalı: {FINALITY}")
        if not isinstance(self.note, str):
            raise ValueError("note metin olmalı")
        if self.supersedes is not None:
            _nonempty("supersedes", self.supersedes)
            if self.supersedes == self.decision_id:
                raise ValueError("Bir karar kendisinin yerine geçemez")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["decision_date"] = self.decision_date.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "OfficialDecision":
        return cls(decision_id=d["decision_id"], source=d["source"],
                   decision_date=dt.date.fromisoformat(d["decision_date"]), scope_event_ids=list(d["scope_event_ids"]),
                   kind=d["kind"], finality=d["finality"], note=d.get("note", ""), supersedes=d.get("supersedes"))


def _local_date(t) -> dt.date:
    """Karşılaştırma tarihi: zaman dilimli an → İstanbul yerel tarihi; saf tarih olduğu gibi."""
    if isinstance(t, dt.datetime):
        if t.tzinfo is None or t.utcoffset() is None:
            raise ValueError("Zaman dilimi bilgisi olmayan zamanla resmî karar sorgulanamaz")
        return t.astimezone(ISTANBUL).date()
    if isinstance(t, dt.date):
        return t
    raise ValueError("t bir datetime (zaman dilimli) veya date olmalı")


def _hash(prev: str, payload: str) -> str:
    return hashlib.sha256((prev + "|" + payload).encode("utf-8")).hexdigest()


def _canon(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


class OfficialRegistry:
    """JSON dosyasında yalnızca eklemeli resmî karar kaydı. Silme veya güncelleme işlevi yoktur."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._entries: list[dict] = []
        self._load()

    # ------------------------------------------------------------- depolama
    def _read(self) -> list[dict]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Bilinmeyen resmî karar kaydı sürümü: {data.get('schema_version')}")
        entries = list(data.get("records", []))
        prev = GENESIS
        for k, e in enumerate(entries):
            if e.get("prev_hash") != prev or _hash(prev, _canon(e["payload"])) != e.get("hash"):
                raise ValueError(f"Resmî karar kaydı #{k + 1} zinciri bozuk (dosya değiştirilmiş)")
            OfficialDecision.from_dict(e["payload"]["decision"])  # alan doğrulaması
            prev = e["hash"]
        return entries

    def _load(self) -> None:
        self._entries = self._read()

    def _write(self, entries: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"schema_version": SCHEMA_VERSION, "kind": "resmi_kararlar", "note": SOURCE_NOTE, "records": entries}
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)

    # ---------------------------------------------------------------- ekleme
    def append(self, decision: OfficialDecision) -> None:
        """Yeni karar ekler. Kimlik tekrarlanamaz; düzeltme ``supersedes`` ile önceki kararı işaret eder."""
        if not isinstance(decision, OfficialDecision):
            raise TypeError("OfficialDecision bekleniyor")
        entries = self._read()  # diskteki sürüm doğrulanır (dışarıdan değişiklik varsa ekleme yapılmaz)
        known = {e["payload"]["decision"]["decision_id"]: e for e in entries}
        if decision.decision_id in known:
            raise ValueError(f"Karar kimliği zaten kayıtlı: {decision.decision_id} (düzeltme yeni kimlikle eklenir)")
        if decision.supersedes is not None:
            if decision.supersedes not in known:
                raise ValueError(f"Yerine geçilen karar kayıtlı değil: {decision.supersedes}")
            old = OfficialDecision.from_dict(known[decision.supersedes]["payload"]["decision"])
            if decision.decision_date < old.decision_date:
                raise ValueError("Düzeltme kararı, yerine geçtiği karardan önceki bir tarihte olamaz")
        payload = {"decision": decision.to_dict(),
                   "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
        prev = entries[-1]["hash"] if entries else GENESIS
        entries.append({"seq": len(entries) + 1, "payload": payload, "prev_hash": prev,
                        "hash": _hash(prev, _canon(payload))})
        self._write(entries)
        self._entries = entries

    # -------------------------------------------------------------- sorgular
    def decisions(self) -> list[OfficialDecision]:
        """Tüm kararlar (ekleme sırasıyla; düzeltilenler dahil)."""
        return [OfficialDecision.from_dict(e["payload"]["decision"]) for e in self._entries]

    def decisions_known_at(self, t) -> list[OfficialDecision]:
        """``t`` anında bilinen kararlar: karar tarihi ``t``'nin (İstanbul) tarihinden önce olanlar (aynı gün hariç)."""
        day = _local_date(t)
        return [d for d in self.decisions() if d.decision_date < day]

    def status_for_event(self, event_id: str, at) -> "OfficialDecision | str":
        """``at`` anında olay için en güncel bilinen karar; yoksa ``KAYIT_YOK`` (asla "temiz" değildir).

        Düzeltme zinciri izlenir: bilinen bir düzeltmeyle yerine geçilmiş karar, zincirin en son bilinen kaydıyla
        temsil edilir. Birden çok aday varsa karar tarihi ve ekleme sırasına göre en sonuncusu döner. Düzeltme olayı
        kapsamdan çıkarmışsa da zincirin son kararı döner (olayın önceki kararı geri alınmıştır); çağıran
        ``scope_event_ids`` alanını kontrol etmelidir.
        """
        _nonempty("event_id", event_id)
        known = self.decisions_known_at(at)
        order = {d.decision_id: k for k, d in enumerate(known)}
        successors: dict[str, list[OfficialDecision]] = {}
        for d in known:
            if d.supersedes is not None and d.supersedes in order:
                successors.setdefault(d.supersedes, []).append(d)
        key = lambda d: (d.decision_date, order[d.decision_id])  # noqa: E731

        def latest_in_chain(d: OfficialDecision) -> OfficialDecision:
            seen = {d.decision_id}
            while d.decision_id in successors:
                d = max(successors[d.decision_id], key=key)
                if d.decision_id in seen:  # döngü olamaz (ekleme sırası), yine de güvenli dur
                    break
                seen.add(d.decision_id)
            return d

        covering = [d for d in known if event_id in d.scope_event_ids]
        if not covering:
            return NO_RECORD
        return max((latest_in_chain(d) for d in covering), key=key)

    def summary(self) -> dict:
        return {"kayit": len(self._entries), "durum_yoksa": NO_RECORD, "not": SOURCE_NOTE}

    @property
    def note(self) -> str:
        return SOURCE_NOTE

    def __len__(self) -> int:
        return len(self._entries)
