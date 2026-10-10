"""Önceden kaydedilen sanal bahis (paper trading) günlüğü ve oran deposu.

* Tahmin kayıtları DEĞİŞTİRİLEMEZ: SQLite tetikleyicileri UPDATE/DELETE işlemlerini reddeder.
* Sonuç ve düzeltmeler ayrı olay olarak eklenir; eski kayıt silinmez.
* Her kayıt bir önceki kaydın özetini (hash) içerir; zincir doğrulanarak sessiz değişiklik tespit edilir.
* Oran kayıtları benzersiz anahtarla saklanır; aynı dosya tekrar alındığında çoğalmaz.

Veritabanı dosyası yalnızca kullanıcı bu özelliği kullandığında, uygulama veri klasöründe oluşturulur.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

from .value import OddsQuote

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS predictions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outcomes (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id TEXT NOT NULL REFERENCES predictions(id),
    recorded_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS odds (
    event_id TEXT NOT NULL, market_key TEXT NOT NULL, period TEXT NOT NULL, line REAL,
    selection TEXT NOT NULL, provider TEXT NOT NULL, bookmaker TEXT NOT NULL,
    decimal_odds REAL NOT NULL, quoted_at TEXT NOT NULL, fetched_at TEXT NOT NULL,
    status TEXT NOT NULL, settlement_rule_version TEXT NOT NULL,
    UNIQUE(event_id, market_key, provider, bookmaker, quoted_at)
);
CREATE TRIGGER IF NOT EXISTS predictions_no_update BEFORE UPDATE ON predictions
BEGIN SELECT RAISE(ABORT, 'Tahmin kaydı değiştirilemez'); END;
CREATE TRIGGER IF NOT EXISTS predictions_no_delete BEFORE DELETE ON predictions
BEGIN SELECT RAISE(ABORT, 'Tahmin kaydı silinemez'); END;
CREATE TRIGGER IF NOT EXISTS outcomes_no_update BEFORE UPDATE ON outcomes
BEGIN SELECT RAISE(ABORT, 'Sonuç kaydı değiştirilemez; düzeltme yeni kayıt olarak eklenir'); END;
CREATE TRIGGER IF NOT EXISTS outcomes_no_delete BEFORE DELETE ON outcomes
BEGIN SELECT RAISE(ABORT, 'Sonuç kaydı silinemez'); END;
CREATE TRIGGER IF NOT EXISTS odds_no_update BEFORE UPDATE ON odds
BEGIN SELECT RAISE(ABORT, 'Oran kaydı değiştirilemez'); END;
CREATE TRIGGER IF NOT EXISTS odds_no_delete BEFORE DELETE ON odds
BEGIN SELECT RAISE(ABORT, 'Oran kaydı silinemez'); END;
"""

GENESIS = "0" * 64


def _hash(prev: str, payload: str) -> str:
    return hashlib.sha256((prev + "|" + payload).encode("utf-8")).hexdigest()


def _canon(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def _utc(t: dt.datetime) -> str:
    """Sıralanabilir ve karşılaştırılabilir olması için UTC ISO metni (zaman dilimi zorunlu)."""
    if t.tzinfo is None:
        raise ValueError("Zaman dilimi bilgisi olmayan zaman kaydedilemez")
    return t.astimezone(dt.timezone.utc).isoformat()


def event_id(league: str, date, home: str, away: str) -> str:
    d = str(date)[:10]
    return f"{league}|{d}|{home}|{away}"


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)
        self.conn.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------ tahminler
    def _last_hash(self, table: str) -> str:
        row = self.conn.execute(f"SELECT hash FROM {table} ORDER BY seq DESC LIMIT 1").fetchone()  # noqa: S608
        return row[0] if row else GENESIS

    def record_prediction(self, record: dict) -> str:
        """Değişmez tahmin kaydı. Zorunlu alanlar: event_id, market_key, decision_time, model_version,
        feature_version, data_cutoff, p, decision_status, reasons, stake_units, strategy_version."""
        required = ("event_id", "market_key", "decision_time", "model_version", "feature_version",
                    "data_cutoff", "p", "decision_status", "reasons", "stake_units", "strategy_version")
        missing = [k for k in required if k not in record]
        if missing:
            raise ValueError(f"Eksik alanlar: {missing}")
        pid = str(uuid.uuid4())
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        payload = _canon({"id": pid, "created_at": now, **record})
        prev = self._last_hash("predictions")
        with self.conn:
            self.conn.execute("INSERT INTO predictions (id, created_at, payload, prev_hash, hash) VALUES (?,?,?,?,?)",
                              (pid, now, payload, prev, _hash(prev, payload)))
        return pid

    def record_outcome(self, prediction_id: str, settlement: str, label: str, source: str, note: str = "") -> None:
        """Sonuç olayını ekler. Aynı tahmine yeni sonuç yalnızca gerekçeli düzeltme olarak eklenebilir."""
        exists = self.conn.execute("SELECT 1 FROM predictions WHERE id=?", (prediction_id,)).fetchone()
        if not exists:
            raise KeyError(prediction_id)
        prev_outcome = self.latest_outcome(prediction_id)
        if prev_outcome is not None:
            if prev_outcome["settlement"] == settlement and prev_outcome["label"] == label:
                return  # aynı sonuç tekrar gelirse çoğaltma (idempotent)
            if not note:
                raise ValueError("Önceki sonucu değiştiren kayıt için düzeltme gerekçesi zorunlu")
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        payload = _canon({"prediction_id": prediction_id, "recorded_at": now, "settlement": settlement,
                          "label": label, "source": source, "note": note,
                          "correction_of": prev_outcome["recorded_at"] if prev_outcome else None})
        prev = self._last_hash("outcomes")
        with self.conn:
            self.conn.execute("INSERT INTO outcomes (prediction_id, recorded_at, payload, prev_hash, hash) VALUES (?,?,?,?,?)",
                              (prediction_id, now, payload, prev, _hash(prev, payload)))

    def latest_outcome(self, prediction_id: str) -> dict | None:
        row = self.conn.execute("SELECT payload FROM outcomes WHERE prediction_id=? ORDER BY seq DESC LIMIT 1",
                                (prediction_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def predictions(self) -> list[dict]:
        out = []
        for (payload,) in self.conn.execute("SELECT payload FROM predictions ORDER BY seq"):
            rec = json.loads(payload)
            rec["outcome"] = self.latest_outcome(rec["id"])
            out.append(rec)
        return out

    def verify_chain(self) -> tuple[bool, str]:
        for table in ("predictions", "outcomes"):
            prev = GENESIS
            for seq, payload, p, h in self.conn.execute(f"SELECT seq, payload, prev_hash, hash FROM {table} ORDER BY seq"):  # noqa: S608
                if p != prev or _hash(prev, payload) != h:
                    return False, f"{table} kaydı #{seq} zinciri bozuk"
                prev = h
        return True, "Zincir doğrulandı"

    def summary(self) -> dict:
        """İleriye dönük sanal performans (geçmiş backtest'ten ayrı). VOID/PENDING/UNKNOWN paydaya girmez."""
        recs = self.predictions()
        bets = [r for r in recs if r.get("stake_units", 0) > 0 and r.get("odds")]
        settled = [r for r in bets if r["outcome"] and r["outcome"]["settlement"] in ("WIN", "LOSS")]
        staked = sum(r["stake_units"] for r in settled)
        net = sum(r["stake_units"] * (r["odds"] - 1) if r["outcome"]["settlement"] == "WIN" else -r["stake_units"]
                  for r in settled)
        return {
            "kayit": len(recs),
            "sanal_bahis": len(bets),
            "sonuclanan": len(settled),
            "bekleyen_veya_iade": len(bets) - len(settled),
            "kazanan": sum(1 for r in settled if r["outcome"]["settlement"] == "WIN"),
            "toplam_stake": staked,
            "net": net,
            "yield": net / staked if staked else None,
        }

    # ---------------------------------------------------------------- oranlar
    def add_odds(self, quotes: list[OddsQuote]) -> int:
        """Oranları ekler; aynı (olay, pazar, sağlayıcı, bahis şirketi, zaman) tekrar eklenmez."""
        before = self.conn.total_changes
        with self.conn:
            self.conn.executemany(
                "INSERT OR IGNORE INTO odds VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [(q.event_id, q.market_key, q.period, q.line, q.selection, q.provider, q.bookmaker, q.decimal_odds,
                  _utc(q.quoted_at), _utc(q.fetched_at), q.status, q.settlement_rule_version) for q in quotes],
            )
        return self.conn.total_changes - before

    def latest_quote(self, event: str, market_key: str, before: dt.datetime) -> OddsQuote | None:
        """Karar anından önceki en güncel oran (karar anından sonraki oranlar asla dönmez)."""
        rows = self.conn.execute(
            "SELECT * FROM odds WHERE event_id=? AND market_key=? ORDER BY quoted_at DESC", (event, market_key)
        ).fetchall()
        for r in rows:
            q = OddsQuote(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7],
                          dt.datetime.fromisoformat(r[8]), dt.datetime.fromisoformat(r[9]), r[10], r[11])
            if q.quoted_at <= before:
                return q
        return None

    def odds_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM odds").fetchone()[0]
