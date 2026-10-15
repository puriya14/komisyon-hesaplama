"""Önceden kaydedilen sanal bahis (paper trading) günlüğü ve oran deposu.

* Tahmin kayıtları DEĞİŞTİRİLEMEZ: SQLite tetikleyicileri UPDATE/DELETE işlemlerini reddeder.
* Sonuç ve düzeltmeler ayrı olay olarak eklenir; eski kayıt silinmez.
* Her kayıt bir önceki kaydın özetini (hash) içerir; zincir doğrulanarak sessiz değişiklik tespit edilir.
* Oran kayıtları benzersiz anahtarla saklanır; aynı dosya tekrar alındığında çoğalmaz.
* Kapanış oranları (ORAN-03) ayrı, değiştirilemez ve zincirli tabloda saklanır; karar oranı olarak kullanılmaz.
  Düzeltme yeni kayıt olarak, gerekçeyle eklenir.

Veritabanı dosyası yalnızca kullanıcı bu özelliği kullandığında, uygulama veri klasöründe oluşturulur.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import sqlite3
import uuid
from pathlib import Path

from .value import OddsQuote

SCHEMA_VERSION = 2  # 2: kapanış oranları tablosu (ORAN-03); eski dosyalarda tablo açılışta boş olarak eklenir

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
CREATE TABLE IF NOT EXISTS closing_odds (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL,
    market_key TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS closing_no_update BEFORE UPDATE ON closing_odds
BEGIN SELECT RAISE(ABORT, 'Kapanış oranı kaydı değiştirilemez; düzeltme yeni kayıt olarak eklenir'); END;
CREATE TRIGGER IF NOT EXISTS closing_no_delete BEFORE DELETE ON closing_odds
BEGIN SELECT RAISE(ABORT, 'Kapanış oranı kaydı silinemez'); END;
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
        row = self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if int(row[0]) < SCHEMA_VERSION:  # eski dosya: yeni tablolar yukarıda boş olarak eklendi
            self.conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))
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
        for table in ("predictions", "outcomes", "closing_odds"):
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

    # ------------------------------------------------------- kapanış oranları
    def record_closing(self, event: str, market_key: str, odds: float, observed_at: dt.datetime, bookmaker: str,
                       source: str, opposite_odds: float | None = None, note: str = "") -> bool:
        """Kapanış oranı (maç başlamadan önceki son oran) kaydı. ``opposite_odds``: aynı şirketin aynı andaki karşı
        taraf oranı (varsa marjsız kapanış olasılığı hesaplanır). Aynı değerler tekrar gelirse eklenmez; farklı bir
        değer yalnızca gerekçeyle (düzeltme) eklenir. Dönen: yeni kayıt eklendi mi."""
        from .markets import MARKETS

        m = MARKETS.get(market_key)
        if m is None or not m.complement:
            raise ValueError(f"Kapanış oranı yalnızca iki seçenekli pazarlarda kaydedilir: {market_key}")
        for v in (odds, opposite_odds):
            if v is not None and not (isinstance(v, (int, float)) and math.isfinite(v) and 1.0 < v <= 1000.0):
                raise ValueError("Oran 1'den büyük, sonlu bir sayı olmalı")
        prev = self.closing(event, market_key)
        if prev is not None:
            same = (abs(prev["odds"] - odds) < 1e-9 and prev["bookmaker"] == bookmaker
                    and (prev["opposite_odds"] is None) == (opposite_odds is None)
                    and (opposite_odds is None or abs(prev["opposite_odds"] - opposite_odds) < 1e-9))
            if same:
                return False
            if not note:
                raise ValueError("Önceki kapanış oranını değiştiren kayıt için düzeltme gerekçesi zorunlu")
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        payload = _canon({"event_id": event, "market_key": market_key, "odds": float(odds),
                          "opposite_odds": float(opposite_odds) if opposite_odds is not None else None,
                          "observed_at": _utc(observed_at), "recorded_at": now, "bookmaker": bookmaker,
                          "source": source, "note": note, "correction_of": prev["recorded_at"] if prev else None})
        h_prev = self._last_hash("closing_odds")
        with self.conn:
            self.conn.execute("INSERT INTO closing_odds (event_id, market_key, recorded_at, payload, prev_hash, hash) "
                              "VALUES (?,?,?,?,?,?)", (event, market_key, now, payload, h_prev, _hash(h_prev, payload)))
        return True

    def closing(self, event: str, market_key: str) -> dict | None:
        """Pazarın en son kapanış oranı kaydı, bu pazarın yönünde: karşı tarafın (tümleyen pazar) kaydı da kullanılır,
        oranlar yer değiştirir. Kayıt yoksa None."""
        from .markets import MARKETS

        m = MARKETS.get(market_key)
        keys = [market_key] + ([m.complement] if m is not None and m.complement else [])
        rows = self.conn.execute(
            f"SELECT payload FROM closing_odds WHERE event_id=? AND market_key IN ({','.join('?' * len(keys))}) "  # noqa: S608
            "ORDER BY seq DESC", (event, *keys)).fetchall()
        for (payload,) in rows:
            rec = json.loads(payload)
            if rec["market_key"] == market_key:
                return rec
            if rec["opposite_odds"] is not None:  # karşı tarafın kaydı: bu pazarın yönüne çevir
                return dict(rec, market_key=market_key, odds=rec["opposite_odds"], opposite_odds=rec["odds"])
        return None

    def closing_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM closing_odds").fetchone()[0]
