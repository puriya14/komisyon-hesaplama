"""Uygulama klasörleri ve kullanıcı ayarları."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import APP_NAME

DEFAULT_LEAGUES = [
    "T1", "E0", "E1", "SP1", "SP2", "I1", "I2", "D1", "D2",
    "F1", "F2", "N1", "P1", "B1", "SC0", "G1",
]


# Veri denetimi modları (eligibility.POLICY_MODES ile aynı)
VERI_DENETIMI = ("standart", "siki")


def app_home_path() -> Path:
    """Uygulama veri klasörünün yolu (klasör oluşturulmaz; ör. pilot dizininin bundan ayrı olduğunu denetlemek için)."""
    env = os.environ.get("BAHIS_TAHMIN_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return (Path(local) if local else Path.home() / "AppData" / "Local") / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / APP_NAME


def app_home() -> Path:
    """Verilerin ve modelin saklandığı klasör.

    Windows'ta %LOCALAPPDATA%\\BahisTahmin. Testler için BAHIS_TAHMIN_HOME
    ortam değişkeni ile değiştirilebilir.
    """
    base = app_home_path()
    base.mkdir(parents=True, exist_ok=True)
    return base


@dataclass
class Settings:
    leagues: list[str] = field(default_factory=lambda: list(DEFAULT_LEAGUES))
    years_back: int = 10
    # Değer (value) hesabında kullanılacak oran türü: avg, max, b365, pinnacle
    odds_type: str = "avg"
    # Marj temizleme yöntemi: power veya proportional
    margin_method: str = "power"
    min_ev: float = 0.05
    min_prob: float = 0.15
    min_odds: float = 1.30
    max_odds: float = 8.0
    kelly_fraction: float = 0.25
    max_stake_pct: float = 0.05
    bankroll: float = 1000.0
    currency: str = "TL"
    use_mirror_fallback: bool = True
    # Eğitim yalnızca kullanıcı isteğiyle yapılır; açılışta otomatik güncelleme varsayılan olarak kapalı
    auto_update_on_start: bool = False
    fixture_days: int = 10
    # Kaynak anahtarı -> kullanıcının kullanım koşullarını onayladığı zaman (ISO)
    source_consent: dict = field(default_factory=dict)
    # Gerçek para miktarı önerisi yalnızca kullanıcı risk sınırlarını kendisi belirleyip açarsa gösterilir
    stake_suggestions: bool = False
    # Veri profili (S5-GITHUB-01): "varsayilan" veya "github" (bütün güncelleme yolları yalnızca seçili GitHub depoları)
    data_profile: str = "varsayilan"
    # VERI-01: kaynak anahtarı -> kullanıcının kişisel (ticari olmayan) kullanım beyanı verdiği zaman (ISO). Beyan
    # yalnızca indirme onayı da olan kaynaklarda geçerlidir (source_registry.effective_declarations).
    kisisel_kullanim: dict = field(default_factory=dict)
    # Kullanıcının en son kaydettiği onay penceresi sürümü (source_registry.CONSENT_SCHEMA'dan küçükse sorulur)
    onay_surumu: int = 0
    # Veri denetimi: "standart" (doğrulanamayan güncellik tahmini engellemez; bilinen eksik/az geçmiş yalnızca bahis
    # adayını engeller) veya "siki" (S3-GATE-02 davranışı: güncelliği doğrulanmayan tahmin gösterilmez)
    veri_denetimi: str = "standart"

    @classmethod
    def path(cls) -> Path:
        return app_home() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        p = cls.path()
        s = cls()
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return s
            known = {f.name: f for f in fields(cls)}
            for k, v in raw.items():
                if k in known:
                    setattr(s, k, v)
        s.validate()
        return s

    def validate(self) -> None:
        from .data.leagues import LEAGUES

        self.leagues = [c for c in self.leagues if c in LEAGUES] or list(DEFAULT_LEAGUES)
        self.years_back = int(min(max(int(self.years_back), 3), 33))
        if not isinstance(self.source_consent, dict):
            self.source_consent = {}
        from .data.source_registry import DECLARABLE

        if not isinstance(self.kisisel_kullanim, dict):
            self.kisisel_kullanim = {}
        self.kisisel_kullanim = {k: v for k, v in self.kisisel_kullanim.items()
                                 if k in DECLARABLE and isinstance(v, str)}
        try:
            self.onay_surumu = max(int(self.onay_surumu), 0)
        except (TypeError, ValueError):
            self.onay_surumu = 0
        if self.veri_denetimi not in VERI_DENETIMI:
            self.veri_denetimi = "standart"
        if self.odds_type not in ("avg", "max", "b365", "pinnacle"):
            self.odds_type = "avg"
        if self.margin_method not in ("power", "proportional"):
            self.margin_method = "power"
        self.kelly_fraction = float(min(max(self.kelly_fraction, 0.0), 1.0))
        self.max_stake_pct = float(min(max(self.max_stake_pct, 0.0), 1.0))
        self.fixture_days = int(min(max(int(self.fixture_days), 1), 60))
        from .data.github_kaynak import PROFILE_DEFAULT, PROFILES

        if self.data_profile not in PROFILES:
            self.data_profile = PROFILE_DEFAULT

    def allowed_sources(self) -> set[str]:
        from .data.source_registry import allowed_sources

        return allowed_sources(self.source_consent)

    def declarations(self) -> dict[str, str]:
        """Geçerli kişisel kullanım beyanları (indirme onayı da olan, beyan verilebilen kaynaklar)."""
        from .data.source_registry import effective_declarations

        keys = effective_declarations(self.source_consent, self.kisisel_kullanim)
        return {k: v for k, v in self.kisisel_kullanim.items() if k in keys}

    def save(self) -> None:
        self.validate()
        tmp = self.path().with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path())
