"""Ortak veri uygunluk kontrolü (politika ``veri-uygunluk-v2``; v1: S3-GATE-01, v2: S3-GATE-02).

Kullanıcıya dönük bütün tahmin ve karar yolları (gol pazarları taraması, maç analizi, elle maç seçimi, 1X2 tahmin
listeleri, CLI, ileriye dönük ölçüm kaydı, sanal takip kaydı) bu modülün sonucunu kullanır. İki soru ayrıdır:

* ``forecast_ok`` — Bu maç/pazar için veri ve zaman açısından tahmin üretilebilir mi?
* ``bet_ok`` — Veri ve kaynak hakları açısından bahis adayına engel kalmadı mı? Model doğrulaması, gerçek oran,
  belirsizlik, sonuçlandırma ve diğer karar kontrolleri karar motorunda AYRICA uygulanır; ``bet_ok`` yalnızca veri
  koşulunun geçildiğini gösterir.

Güncellik (``freshness``):

* ``VERIFIED_CURRENT`` — İlgili kapsamın güncelliği kanıtla doğrulandı.
* ``KNOWN_STALE`` — Tamamlanmış ve erişilebilir olması beklenen maçların eksik olduğu biliniyor.
* ``UNKNOWN`` — Doğrulamaya yeterli kanıt yok. Sıkı modda (``siki``, v2) UNKNOWN hiçbir zaman uygun sayılmaz; kontrol
  çağrılmadıysa veya bağlam verilmediyse sonuç uygun değildir (``BAGLAM_YOK``).

Veri denetimi modu (VERI-01, ``POLICY_MODES``): ``siki`` v2 kurallarının aynısıdır (kütüphane varsayılanı; ileriye
dönük ölçüm kaydı ve pilot bu modu kullanır). ``standart`` (uygulama ve CLI varsayılanı) neden kodlarını ve güncellik
sonucunu değiştirmez, yalnızca kodların engel düzeyini ``STANDART_LEVELS`` ile belirler: yapısal engeller (model/
takım/kimlik/zaman/hak) tahmini engeller; bilinen eksik veri, çelişki, az geçmiş ve eski model durumu yalnızca bahis
adayını engeller (tahmin "Uyarılı" gösterilir); yalnızca kanıt eksikliği (bağımsız takvimle güncellik
doğrulanamadı) engel değildir ve açıklamada yazılır.

Kanıt zinciri (kontrol edilen veri, tahminde KULLANILAN veriye bağlanır):

1. **Model durumu ↔ veri deposu.** Tahminler modelin bellekteki lig/takım durumundan (state) üretilir ve bu durum
   eğitim anında donar. Depoda, durumun içermediği ve bilgi kesiminden önce tamamlanmış (modelin işleyeceği) maç
   varsa ``DURUM_DEPODAN_GERIDE`` (KNOWN_STALE). Model parametrelerinin eğitim kesimi tek başına engel değildir;
   karşılaştırma tahminde kullanılan lig/takım durumunun kapsamı üzerinden yapılır.
2. **Veri deposu ↔ fikstür/sonuç kaynağı.** Kaynağın sezon takvimi (ör. openfootball, CC0) ile takımın geçmiş
   maçları karşılaştırılır. Kaynakta tamamlanmış görünen ama depoda olmayan maç ``DEPODA_EKSIK_MAC`` (KNOWN_STALE;
   kısmi takvim de bilinen eksiği gösterebilir, ama "eksik yok" kanıtı olamaz). Kontrol depodaki son tarihle sınırlı
   değildir: ligin yeni maçları depoda olsa bile takımın daha eski bir maçı eksikse yakalanır. Ertelenen/iptal
   edilen maçlar eksik sayılmaz; geçmiş tarihli, sonucu kaynakta da depoda da olmayan maç ``KAYNAK_DURUMU_BELIRSIZ``
   (UNKNOWN) olur. Doğrulanmış aralıkta depoda olup kaynakta olmayan maç kaynakların çeliştiğini gösterir
   (``KAYNAK_DEPO_CELISKISI``, UNKNOWN).
3. **Kapsam (v2).** Kaynak dosyasının kendi takım sayısı kendi tamlığının kanıtı DEĞİLDİR. Takvim kanıtı iki ayrı
   sorudur: (A) bütün sezon takviminin tamlığı ve (B) gerekli geçmiş aralığın tamlığı. B, bağımsız katılımcı listesi
   (aynı sezonun başka sağlayıcıdan gelen veri deposundaki takımları; kaynak adları kesin kimlikle eşleşmeli) üzerinde,
   1. turdan başlayıp ardışık her turu bu katılımcıların tam eşleşmesi olan (her takım turda bir kez) numaralı
   turlardan kurulur; yinelenen kayıtlar tekilleştirilir, çakışan kayıt turu doğrulanmamış yapar, numaralı olmayan
   aşamalar (play-off/split) ve eksik turdan sonrası aralığa girmez. A için ayrıca lig formatının beklenen tur sayısı
   ve eşleşme yapısı (her ikili beklenen sayıda) gerekir. Gelecek fikstürlerin yayımlanmamış olması tek başına B'yi
   reddetmez. Gerekli pencere (bilgi kesiminden önceki 365 gün; depodaki ilk maç pencereyi kısaltamaz) B
   aralıklarıyla kapsanmalıdır. Ardışık iki sezon arasındaki ara yalnızca önceki sezonun listelenen takvimi sonuna
   kadar doğrulanmışsa (split/play-off'lu liglerde hiçbir zaman) ve arada (bilgi kesiminden önce) ne depoda ne
   kaynakta maç yoksa kapsanmış sayılır; yeni sezon
   takvimi bilgi kesiminden önce maç göstermiyorsa (sezon başlamadı) ara bilgi kesimine kadar kapsanır. Veri
   deposunun yalnızca kendi iç tutarlılığı (takım sayısı depodan çıkarılarak) artık kapsam kanıtı sayılmaz. Kaynak
   yoksa, boşsa, kısmîyse veya bağımsız katılımcı listesi yoksa "eksik maç yok" sonucu çıkmaz: UNKNOWN.
4. **Takım kimliği (v2).** Fikstür adları ``data.teams`` sözleşmesiyle (``takim-eslesme-v2``) yalnızca kesin kimlikle
   eşlenir; başka kaynaktan eşlenmiş fikstür (openfootball) uygunluk anında aynı kaynak dosyasında güncel eşleyiciyle
   yeniden kurulamıyorsa ``TAKIM_ESLESMESI_DOGRULANAMADI`` (eski kayıtlar yeni eşleyiciden geçmiş sayılmaz).

Zaman kuralı (muhafazakâr, maç bitiş/yayın saati bilinmediği için): değerlendirme anının İstanbul takvim günü ``D``
ise yalnızca tarihi ``D``'den ÖNCE olan maç sonuçları erişilebilir sayılır; aynı günün sonuçları beklenmez. Kaynak
takviminde bir maçın "tamamlandı" görünmesi yalnızca değerlendirme anından ÖNCE alınmış kaynak dosyası için kanıttır
(``KAYNAK_KARAR_ANINDAN_SONRA``); geçmiş bir an, bugünkü tam sezon dosyasıyla "o gün veri tamdı" diye doğrulanamaz.
Aynı kural tamlığın dayandığı bağımsız katılımcı referansı için de geçerlidir (``ParticipantSet.available_since``,
S4-KAYNAK-03): referans değerlendirme anında henüz erişilebilir değilse takvim o an için kısmi sayılır.
Model durumu ``D`` veya sonrasına tarihli maç içeriyorsa ve durumun değerlendirme anından önce var olduğu
bilinmiyorsa ``DURUM_KARAR_ANINDAN_SONRA``. Depoya sonradan eklenen sonuçlar geçmiş bir değerlendirmenin sonucunu
değiştirmez (bütün karşılaştırmalar bilgi kesimiyle sınırlıdır).

Kaynak hakları (``data.source_registry.USE_RIGHTS``, işlem kapsamları ``OPERATION_SCOPES``): kullanıcı indirme
onayı, kaynak erişim koşulları, sonuç verisinin analizde kullanımı, model eğitimi, mevcut modelin kullanımı, ticari
kullanım ve yeniden dağıtım ayrı alanlardır. v2'de "yerel analiz" istisnası yoktur: kullanıcıya gösterilen tahmin/
olasılık ve tahmin kaydı için de (bahis adayıyla aynı) sonuç kullanımı, model eğitimi ve mevcut modelin kullanımı
belgeyle doğrulanmış ve modelin eğitim verisi kökeni kayıtlı olmalıdır; aksi halde tahmin üretilmez (nedenli,
olasılıksız kayıt ve kaynak kapsamı açıklaması gösterilir). Gerçek veriyle model eğitimi ``training_rights_codes``
ile aynı kayıttan denetlenir. Yeniden dağıtım ve ticari kullanım bu işlemler için gerekmez ve engel değildir.
Kullanıcı onayı yalnızca erişimi kapsar; arayüz onayı, komut satırı bayrağı veya kaynak etiketi bu alanları
doğrulanmış yapamaz (etiket, kaynağın gerçekten sağladığı veri türüyle de denetlenir). VERI-01: kullanıcı, indirme
onayı verdiği ve kaydında ``kisisel_beyan`` alanları bulunan kaynak için ayrıca açık bir kişisel (ticari olmayan)
kullanım beyanı verebilir; beyan bu alanları belge yerine kullanıcının sorumluluğunda "KULLANICI_BEYANI" yapar
(``rights_from_registry``). Belge durumu, ticari kullanım ve yeniden dağıtım değişmez.

Bu modül olasılık hesaplamaz ve modelin matematiğini değiştirmez.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field, replace

import numpy as np
import pandas as pd

from .data.teams import MATCHING_VERSION
from .timeutil import ISTANBUL

POLICY_VERSION = "veri-uygunluk-v2"  # v1 (S3-GATE-01) sonuçları karar denetiminde bu sürümle eşleşmez
# VERI-01: veri denetimi modu. "siki" = v2 kuralları aynen (kütüphane varsayılanı; ileriye dönük ölçüm protokolü v3 ve
# pilot buna bağlıdır). "standart" = uygulama/CLI varsayılanı (bkz. STANDART_LEVELS).
POLICY_MODES = ("standart", "siki")
POLICY_VERSIONS = {"siki": POLICY_VERSION, "standart": "veri-uygunluk-v3-standart"}

VERIFIED_CURRENT = "VERIFIED_CURRENT"
KNOWN_STALE = "KNOWN_STALE"
UNKNOWN = "UNKNOWN"

EPOCH = pd.Timestamp("2000-01-01")  # goals.features / models.features ile aynı gün numarası
LOOKBACK_DAYS = 365  # takım özelliklerinin (form, n365, zamanla azalan güçler) bağlı olduğu pencere
MIN_TEAM_MATCHES = 10  # karar politikasıyla aynı: son 365 günde bu ligde en az maç
LEAGUE_MISSING_SHARE = 0.05  # lig düzeyinde eksik/belirsiz maç payı bunu aşarsa paylaşılan lig durumu güvenilmez
PAIR_DAY_TOLERANCE = 3  # kaynak ile depo arasında aynı eşleşme için tarih farkı toleransı (yerel tarih farkları)
# VERI-02 (yalnızca standart mod): bilgi kesiminden önceki son bu kadar gün içinde oynanması beklenen ama sonucu henüz
# kaynakta da depoda da olmayan maçlar olağan yayın gecikmesidir (SON_SONUC_BEKLENIYOR); daha eskileri belirsizdir.
PENDING_GRACE_DAYS = 4
NOT_PLAYED_STATUSES = frozenset({"POSTPONED", "CANCELLED", "ABANDONED", "SUSPENDED"})
FINISHED = "FINISHED"
SCHEDULED_OR_UNKNOWN = "SCHEDULED_OR_UNKNOWN"
# Takım adları veri deposundan farklı olan ve ``data.teams`` ile eşlenen fikstür kaynakları (fikstür etiketi)
MAPPED_FIXTURE_SOURCES = frozenset({"openfootball"})
# Kapsam kaynağıyla AYNI veri zincirinden gelen depo etiketleri: bu satırlar kaynağın bağımsız denetimi olamaz
# (bağımsız katılımcı listesine girmez; depo↔kaynak karşılaştırması tek kaynak zinciri olarak işaretlenir)
COVERAGE_CHAIN_LABELS = {"openfootball": frozenset({"openfootball", "openfootball-sonuc", "openfootball-tamamlama"})}

# ----------------------------------------------------------------------------
# Neden kodları
# ----------------------------------------------------------------------------
# blocks: "tahmin" = tahmini ve bahis adayını engeller; "bahis" = yalnızca bahis adayını engeller; "yok" = bilgi.
# freshness: bu nedenin güncellik sonucuna etkisi (None = güncellikle ilgisiz).


@dataclass(frozen=True)
class Reason:
    text: str
    blocks: str
    freshness: str | None
    fix: str


_BEYAN_FIX = ("Veri sayfasındaki 'Kaynak koşulları ve onaylar...' penceresinde bu kaynak için kişisel (ticari "
              "olmayan) kullanım beyanı verin (komut satırı: update --kisisel-kullanim KAYNAK); ya da kaynağın lisans "
              "belgesini kaynak kaydına ekleyin. İndirme onayı tek başına yeterli değildir. İleriye dönük ölçüm kaydı "
              "(protokol v3) ve pilot beyanı kabul etmez; yalnızca belgeli kaynakla çalışır.")

REASONS: dict[str, Reason] = {
    "BAGLAM_YOK": Reason("Veri uygunluk kontrolü yapılmadı veya gerekli bağlam verilmedi.", "tahmin", UNKNOWN,
                         "Tahmini uygulamanın veya CLI'nin uygunluk kontrollü yolundan üretin."),
    "BAGLAM_UYUSMUYOR": Reason("Uygunluk sonucu bu maç, pazar, karar günü veya model durumu için değil.", "tahmin",
                               UNKNOWN, "Uygunluğu bu karar anı ve bu model için yeniden değerlendirin."),
    "MAC_GECMISTE": Reason("Maç günü değerlendirme gününden önce; maç öncesi tahmin değildir.", "tahmin", None,
                           "Yalnızca oynanmamış maçlar için tahmin üretilir."),
    "MODEL_YOK": Reason("Eğitilmiş model yok.", "tahmin", None, "Modeli eğitin."),
    "LIG_MODEL_KAPSAMI_DISI": Reason("Lig modelin durumunda yok.", "tahmin", None,
                                     "Bu ligin verisini indirip modeli yeniden eğitin."),
    "TAKIM_ESLESMEDI": Reason(
        "Fikstürdeki takım adı veri deposundaki bir takımla kesin olarak eşleştirilemedi (bulunamadı, belirsiz veya "
        "yalnızca benzer ad).", "tahmin", None,
        "Doğrulanmış takma ad (data/teams.py) gerekir; benzer ad önerisi kimlik kanıtı değildir."),
    "TAKIM_ESLESMESI_DOGRULANAMADI": Reason(
        "Başka kaynaktan eşlenmiş fikstürün takım kimliği güncel eşleyiciyle kaynak takviminde yeniden kurulamadı "
        "(eski kayıt veya kaynak dosyası yok).", "tahmin", UNKNOWN,
        "Verileri güncelleyin (fikstür güncel eşleyiciyle yeniden eşlenir)."),
    "TAKIM_DURUMDA_YOK": Reason("Takım modelin lig durumunda yok (geçmişi olmayan veya eğitimden sonra gelen takım).",
                                "tahmin", None, "Takımın bu ligdeki geçmiş verisi ve güncel model gerekir."),
    "DURUM_KARAR_ANINDAN_SONRA": Reason(
        "Model durumu değerlendirme gününde veya sonrasında oynanan maçları içeriyor (bilgi kesimi aşılmış olabilir).",
        "tahmin", None, "Bu an için, o andan önce oluşturulmuş bir model durumu gerekir."),
    "DURUM_DEPODAN_GERIDE": Reason(
        "Modelin kullandığı takım/lig durumu, depodaki tamamlanmış maçları içermiyor (model durumu veriden eski).",
        "tahmin", KNOWN_STALE, "Modeli güncel veriyle yeniden eğitin."),
    "DEPODA_EKSIK_MAC": Reason("Kaynakta tamamlanmış görünen maç(lar) veri deposunda yok.", "tahmin", KNOWN_STALE,
                               "Verileri güncelleyin."),
    "DEPODA_GECERSIZ_SKOR": Reason(
        "Kaynakta tamamlanmış görünen maçın depodaki kaydı geçersiz skorlu (karantinada); model bu maçı kullanmıyor.",
        "tahmin", KNOWN_STALE, "Maçın skorunu kaynakta düzeltip verileri güncelleyin."),
    "DURUM_KOKENI_YOK": Reason(
        "Model dosyasında lig durumunun hangi maçlardan kurulduğu bilgisi yok (eski model); kullanılan durum veriyle "
        "doğrulanamıyor.", "tahmin", UNKNOWN, "Modeli yeniden eğitin (eski model dosyası değiştirilmez)."),
    "DURUM_VERIYLE_UYUSMUYOR": Reason(
        "Modelin lig durumu, depodaki aynı dönemin maçlarıyla birebir uyuşmuyor (farklı veriyle kurulmuş).", "tahmin",
        UNKNOWN, "Modeli güncel veriyle yeniden eğitin."),
    "LIG_DURUMU_EKSIK": Reason(
        f"Ligde tamamlanmış maçların %{100 * LEAGUE_MISSING_SHARE:.0f}'inden fazlası depoda yok "
        "(paylaşılan lig durumu güvenilmez).", "tahmin", KNOWN_STALE, "Verileri güncelleyin."),
    "LIG_DURUMU_KISMEN_EKSIK": Reason("Ligde başka takımlara ait az sayıda tamamlanmış maç depoda yok.", "yok", None,
                                      "Verileri güncelleyin."),
    "LIG_DURUMU_BELIRSIZ": Reason(
        f"Ligde geçmiş tarihli maçların %{100 * LEAGUE_MISSING_SHARE:.0f}'inden fazlasının sonucu doğrulanamıyor.",
        "tahmin", UNKNOWN, "Kaynak dosyası ve veriler güncellendikten sonra yeniden deneyin."),
    "KAYNAK_KAPSAMI_YOK": Reason("Bu lig için güncelliği doğrulayacak fikstür/sonuç kaynağı (tam sezon takvimi) yok.",
                                 "tahmin", UNKNOWN,
                                 "Ligin openfootball sezon dosyası (veya başka tam takvim kaynağı) gerekir."),
    "KAYNAK_KAPSAMI_KISMI": Reason(
        "Kaynak takvimi boş, okunamadı, eksik veya bağımsız katılımcı listesiyle doğrulanamıyor (tamlık kanıtı yok).",
        "tahmin", UNKNOWN,
        "Bağımsız katılımcı listesiyle (aynı sezonun veri deposu) doğrulanabilen tur bilgili sezon takvimi gerekir."),
    "KAYNAK_KARAR_ANINDAN_SONRA": Reason("Kaynak dosyası değerlendirme anından sonra alınmış; o anın kanıtı olamaz.",
                                         "tahmin", UNKNOWN, "Geçmiş an için o anda alınmış kaynak gerekir."),
    "KAYNAK_ARALIK_DISI": Reason("Takımın gerekli geçmiş pencere aralığı kaynak veya tam sezon kanıtıyla kapsanmıyor.",
                                 "tahmin", UNKNOWN, "Önceki sezonun tam verisi veya sezon takvimi gerekir."),
    "KAYNAK_DURUMU_BELIRSIZ": Reason(
        "Takımın geçmiş tarihli bir maçının sonucu ne kaynakta ne depoda var (oynandı mı bilinmiyor).",
        "tahmin", UNKNOWN, "Kaynak ve veriler güncellendikten sonra yeniden deneyin."),
    "SON_SONUC_BEKLENIYOR": Reason(
        f"Takımın son {PENDING_GRACE_DAYS} gün içindeki maçının sonucu henüz yayımlanmadı (kaynakta da veride de yok; "
        "sonuçlar genellikle birkaç gün içinde gelir). Tahmin bu maçı içermiyor.", "tahmin", UNKNOWN,
        "Birkaç gün sonra verileri yeniden güncelleyin."),
    "KAYNAK_ESLESME_BELIRSIZ": Reason("Takımın maçları kaynak takviminde güvenilir biçimde eşleştirilemedi.", "tahmin",
                                      UNKNOWN, "Takım adı eşlemesini düzeltin."),
    "KAYNAK_DEPO_CELISKISI": Reason(
        "Doğrulanmış takvim aralığında depoda olan maç kaynak takviminde yok (kaynaklar çelişiyor).", "tahmin",
        UNKNOWN, "Kaynak dosyası ve veriler güncellendikten sonra yeniden deneyin."),
    "KAYNAK_ESLESMEMIS_ADLAR": Reason("Kaynak takviminde eşleşmeyen takım adları var (lig düzeyi bilgi).", "yok", None,
                                      "Takım adı eşlemesini düzeltin."),
    "GEREKLI_ALAN_EKSIK": Reason("Modelin bu pazar için gerektirdiği girdiler (yarı bazlı takım güçleri) yok.",
                                 "tahmin", None, "İlk yarı skorlu yeterli geçmiş veri gerekir."),
    "TAKIM_GECMISI_YETERSIZ": Reason(f"Takımın son 365 günde bu ligde {MIN_TEAM_MATCHES} maçtan az geçmişi var.",
                                     "tahmin", None, "Daha fazla maç verisi gerekir."),
    "LIG_IY_ORANI_DUSUK": Reason("Bu ligde geçerli ilk yarı skoru oranı düşük.", "bahis", None,
                                 "İlk yarı skoru kapsamı yüksek veri gerekir."),
    "KAYNAK_ERISIM_IZNI_YOK": Reason("Kullanılan verinin kaynağı için kullanıcı erişim onayı yok.", "tahmin", None,
                                     "Kaynak kullanım koşullarını uygulamada onaylayın."),
    "KAYNAK_HAKKI_BILINMIYOR": Reason("Kullanılan verinin kaynağı kayıtlı değil; kullanım hakkı bilinmiyor.", "tahmin",
                                      None, "Kaynağı belgeleriyle kaynak kaydına (source_registry) ekleyin."),
    # v2: "yerel analiz" istisnası kaldırıldı — doğrulanmamış hak tahmini de (yalnızca bahsi değil) engeller
    "KAYNAK_ETIKETI_UYUMSUZ": Reason(
        "Verinin kaynak etiketi, bu kaynağın uygulamada sağladığı veri türüyle uyuşmuyor (etiketle hak aşılamaz).",
        "tahmin", None, "Veriyi kaynağın kendi adaptörüyle yeniden indirin."),
    "KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI": Reason(
        "Sonuç verisinin kaynağında analizde kullanım hakkı belgeyle doğrulanmadı (bu işlemde geçerli bir kişisel "
        "kullanım beyanı da yok); tahmin ve bahis adayı üretilmez.", "tahmin", None, _BEYAN_FIX),
    "KAYNAK_EGITIM_HAKKI_DOGRULANAMADI": Reason(
        "Modelin eğitildiği verinin kaynağında model eğitimi hakkı belgeyle doğrulanmadı (bu işlemde geçerli bir "
        "kişisel kullanım beyanı da yok); tahmin ve bahis adayı üretilmez.", "tahmin", None, _BEYAN_FIX),
    "KAYNAK_MODEL_KULLANIMI_DOGRULANAMADI": Reason(
        "Bu veriyle eğitilmiş modelin kullanım hakkı belgeyle doğrulanmadı (bu işlemde geçerli bir kişisel kullanım "
        "beyanı da yok); tahmin ve bahis adayı üretilmez.", "tahmin", None, _BEYAN_FIX),
    "KAYNAK_KOKENI_DOGRULANAMADI": Reason(
        "Sonuç satırlarının gerçekten kayıtlı kaynak dosyasından geldiği doğrulanamadı (köken kaydı, dosya özeti veya "
        "yeniden ayrıştırma uyuşmuyor); etiket tek başına hak vermez.", "tahmin", None,
        "Verileri kaynağın kendi sonuç adaptörüyle sabit commit üzerinden yeniden hazırlayın."),
    "MODEL_EGITIM_KOKENI_YOK": Reason(
        "Model dosyasında eğitim verisinin kaynak kökeni yok; modelin izinli kullanımı doğrulanamıyor (eski model).",
        "tahmin", None, "Hakları belgeli veriyle modeli yeniden eğitin (eski model dosyasına köken uydurulmaz)."),
    "OLASILIK_GECERSIZ": Reason("Model olasılığı geçersiz (NaN, sonsuz veya [0,1] dışı).", "tahmin", None,
                                "Model ve girdi verisi denetlenmeli."),
}

# Kullanıcıya gösterilecek birincil nedenin sırası: önce bağlam ve yapısal engeller (tahmin hiç kurulamaz), sonra
# bilinen eksik veri, sonra doğrulanamayan kapsam, sonra gerekli alanlar ve haklar; en son yalnızca bahsi engelleyenler.
LEAD_ORDER = (
    "BAGLAM_YOK", "BAGLAM_UYUSMUYOR", "TAKIM_ESLESMEDI", "TAKIM_ESLESMESI_DOGRULANAMADI", "MAC_GECMISTE", "MODEL_YOK",
    "LIG_MODEL_KAPSAMI_DISI", "TAKIM_DURUMDA_YOK", "DURUM_KARAR_ANINDAN_SONRA", "DEPODA_EKSIK_MAC",
    "DEPODA_GECERSIZ_SKOR", "DURUM_DEPODAN_GERIDE", "LIG_DURUMU_EKSIK", "DURUM_KOKENI_YOK", "DURUM_VERIYLE_UYUSMUYOR",
    "KAYNAK_KAPSAMI_YOK", "KAYNAK_KAPSAMI_KISMI", "KAYNAK_KARAR_ANINDAN_SONRA", "KAYNAK_ESLESME_BELIRSIZ",
    "KAYNAK_DEPO_CELISKISI", "KAYNAK_DURUMU_BELIRSIZ", "SON_SONUC_BEKLENIYOR", "KAYNAK_ARALIK_DISI",
    "LIG_DURUMU_BELIRSIZ",
    "OLASILIK_GECERSIZ", "GEREKLI_ALAN_EKSIK", "TAKIM_GECMISI_YETERSIZ", "KAYNAK_ERISIM_IZNI_YOK",
    "KAYNAK_HAKKI_BILINMIYOR", "KAYNAK_ETIKETI_UYUMSUZ", "KAYNAK_KOKENI_DOGRULANAMADI", "MODEL_EGITIM_KOKENI_YOK",
    "KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI", "KAYNAK_EGITIM_HAKKI_DOGRULANAMADI", "KAYNAK_MODEL_KULLANIMI_DOGRULANAMADI",
    "LIG_IY_ORANI_DUSUK",
)


# VERI-01 "standart" modunda her kodun engel düzeyi (siki modda REASONS[c].blocks aynen kullanılır).
#   tahmin: yapısal engel — tahmin kurulamaz veya yanlış maça/takıma/ana ait olur ya da hak yoktur;
#   bahis : bilinen eksik/çelişkili veri, az geçmiş, eski model durumu — tahmin uyarıyla gösterilir, bahis adayı olmaz;
#   yok   : yalnızca kanıt eksikliği (bağımsız takvimle güncellik doğrulanamadı) — bilinen bir sorun yok; tahmin ve
#           değer hesabı engellenmez, güncellik açıklamada yazılır.
# Güncellik sonucu (freshness) ve neden kodları her iki modda aynıdır (gerçeği yazar); yalnızca engel düzeyi değişir.
STANDART_LEVELS = {
    "BAGLAM_YOK": "tahmin", "BAGLAM_UYUSMUYOR": "tahmin", "MAC_GECMISTE": "tahmin", "MODEL_YOK": "tahmin",
    "LIG_MODEL_KAPSAMI_DISI": "tahmin", "TAKIM_ESLESMEDI": "tahmin", "TAKIM_ESLESMESI_DOGRULANAMADI": "tahmin",
    "TAKIM_DURUMDA_YOK": "tahmin", "DURUM_KARAR_ANINDAN_SONRA": "tahmin",
    "DURUM_DEPODAN_GERIDE": "bahis", "DEPODA_EKSIK_MAC": "bahis", "DEPODA_GECERSIZ_SKOR": "bahis",
    "DURUM_KOKENI_YOK": "bahis", "DURUM_VERIYLE_UYUSMUYOR": "bahis", "LIG_DURUMU_EKSIK": "bahis",
    "LIG_DURUMU_KISMEN_EKSIK": "yok", "LIG_DURUMU_BELIRSIZ": "bahis",
    "KAYNAK_KAPSAMI_YOK": "yok", "KAYNAK_KAPSAMI_KISMI": "yok", "KAYNAK_KARAR_ANINDAN_SONRA": "yok",
    "KAYNAK_ARALIK_DISI": "yok", "KAYNAK_DURUMU_BELIRSIZ": "bahis", "SON_SONUC_BEKLENIYOR": "yok",
    "KAYNAK_ESLESME_BELIRSIZ": "bahis",
    "KAYNAK_DEPO_CELISKISI": "bahis", "KAYNAK_ESLESMEMIS_ADLAR": "yok",
    "GEREKLI_ALAN_EKSIK": "tahmin", "TAKIM_GECMISI_YETERSIZ": "bahis", "LIG_IY_ORANI_DUSUK": "bahis",
    "KAYNAK_ERISIM_IZNI_YOK": "tahmin", "KAYNAK_HAKKI_BILINMIYOR": "tahmin", "KAYNAK_ETIKETI_UYUMSUZ": "tahmin",
    "KAYNAK_KOKENI_DOGRULANAMADI": "tahmin", "KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI": "tahmin",
    "KAYNAK_EGITIM_HAKKI_DOGRULANAMADI": "tahmin", "KAYNAK_MODEL_KULLANIMI_DOGRULANAMADI": "tahmin",
    "MODEL_EGITIM_KOKENI_YOK": "tahmin", "OLASILIK_GECERSIZ": "tahmin",
}
LEVELS = {"siki": {c: r.blocks for c, r in REASONS.items()}, "standart": STANDART_LEVELS}
assert all(set(v) == set(REASONS) for v in LEVELS.values())
_RANK = {"yok": 0, "bahis": 1, "tahmin": 2}
assert all(_RANK[STANDART_LEVELS[c]] <= _RANK[r.blocks] for c, r in REASONS.items())  # standart siki'den katı olamaz


def code_level(code: str, mode: str = "siki") -> str:
    """Kodun ``mode`` modundaki engel düzeyi: "tahmin" / "bahis" / "yok"."""
    return LEVELS.get(mode, LEVELS["siki"])[code]


def _lead_key(code: str):
    return (LEAD_ORDER.index(code) if code in LEAD_ORDER else len(LEAD_ORDER), code)


def lead_reason(codes, mode: str = "siki") -> str | None:
    """Engelleyen kodlardan kullanıcıya gösterilecek birincil neden (bilgi kodları hariç). Tahmini engelleyen kod,
    yalnızca bahsi engelleyenden önce gelir (siki modda LEAD_ORDER ile aynı sonuç)."""
    blocking = [c for c in codes if code_level(c, mode) != "yok"]
    if not blocking:
        return None
    return min(blocking, key=lambda c: (code_level(c, mode) != "tahmin",) + _lead_key(c))


STATUS_TEXT = {"UYGUN": "Kullanılabilir", KNOWN_STALE: "Eksik veri", UNKNOWN: "Doğrulanamıyor",
               "ENGELLI": "Uygun değil", "UYARILI": "Uyarılı"}

# Pazarın gerçek model bağımlılığı (skor etiketlenebilirliğinden AYRI): gol modeli (M10) üç pazarı da yarı bazlı
# takım güçlerinden (goals.model.REQUIRED) üretir; 3,5 Üst'ün sonuçlandırması yalnızca maç sonu skoru gerektirse de
# tahmini ilk yarı verisine bağlıdır. 1X2 motoru yalnızca maç sonu skorlarını kullanır.
MODEL_INPUTS = {
    "gol": {"BTTS_BOTH_HALVES_YES": ("ilk_yari", "mac_sonu"), "FT_OVER_3_5": ("ilk_yari", "mac_sonu"),
            "FH_OVER_1_5": ("ilk_yari", "mac_sonu")},
    "mac": {"1X2": ("mac_sonu",)},
}
GOAL_MARKETS = ("BTTS_BOTH_HALVES_YES", "FT_OVER_3_5", "FH_OVER_1_5")
MATCH_MARKETS = ("1X2",)
# Motorun yapılandırılmış tahmin kodları -> (neden kodu, gerektirdiği girdi; None = her pazar)
PREDICTION_CODE_MAP = {"TAKIM_GUCU_YOK": ("GEREKLI_ALAN_EKSIK", "ilk_yari"),
                       "TAKIM_N365_AZ": ("TAKIM_GECMISI_YETERSIZ", None),
                       "LIG_IY_ORANI_DUSUK": ("LIG_IY_ORANI_DUSUK", "ilk_yari"),
                       "OLASILIK_GECERSIZ": ("OLASILIK_GECERSIZ", None)}


def day_number(d) -> int:
    return int((pd.Timestamp(d).normalize() - EPOCH).days)


def day_to_date(day: int) -> dt.date:
    return (EPOCH + pd.Timedelta(days=int(day))).date()


def info_cutoff(as_of: dt.datetime) -> dt.date:
    """Bilgi kesimi: değerlendirme anının İstanbul tarihi. Bu günden ÖNCEKİ sonuçlar erişilebilir sayılır."""
    if as_of.tzinfo is None:
        raise ValueError("Değerlendirme anı zaman dilimi bilgisi içermeli")
    return as_of.astimezone(ISTANBUL).date()


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# Durum özetine giren alanlar: motorun o satırdan gerçekten TÜKETTİĞİ değerler (skor düzeltmesi de fark yaratır)
DIGEST_COLUMNS = {"gol": ("fthg", "ftag", "hthg", "htag"),
                  "mac": ("fthg", "ftag", "h_sot", "a_sot", "o_h", "o_d", "o_a", "o_o25", "o_u25")}


def _cell(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    return f"{f:.6f}" if math.isfinite(f) else ""


def rows_digest(df: pd.DataFrame, kind: str) -> tuple[int, str]:
    """Bir lig durumunun kurulduğu maç kümesinin kimliği: (sayı, SHA-256). Gün, takımlar ve motorun tükettiği değerler
    (``DIGEST_COLUMNS``) girer. Motorlar eğitimde işledikleri satırlar için hesaplayıp durum nesnesine yazar
    (``row_digest``); uygunluk kontrolü depodaki aynı dönemle birebir karşılaştırır."""
    days = ((pd.to_datetime(df["date"]).dt.normalize() - EPOCH).dt.days).to_numpy()
    cols = [df[c].to_numpy() if c in df else np.full(len(df), np.nan) for c in DIGEST_COLUMNS[kind]]
    keys = sorted("|".join([str(int(d)), str(h), str(a)] + [_cell(c[i]) for c in cols])
                  for i, (d, h, a) in enumerate(zip(days, df["home"], df["away"])))
    return len(keys), hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------------
# Kaynak kapsamı (tam sezon takvimi)
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class ScheduledMatch:
    date: dt.date
    raw_home: str
    raw_away: str
    home: str | None  # yalnızca KESİN kimlikle eşlenmiş ad; aksi halde None
    away: str | None
    status: str  # FINISHED / POSTPONED / CANCELLED / ABANDONED / SUSPENDED / SCHEDULED_OR_UNKNOWN
    round: str | None = None  # kaynağın tur/aşama etiketi (ör. "Matchday 7")


@dataclass(frozen=True)
class SourceCoverage:
    """Bir lig-sezon için kaynağın takvim kanıtı.

    ``complete`` (A): listelenen sezon takvimi bağımsız katılımcı listesine ve lig formatına göre baştan sona tam.
    ``windows`` (B): kanıtla tam olduğu bilinen tarih aralıkları (gün numarası). ``None`` yalnızca doğrudan kurulan
    (sentetik test) kapsam içindir: o zaman ``complete`` ise bütün takvim aralığı, değilse hiçbir aralık sayılır.
    ``reaches_end``: B aralığı listelenen takvimin sonuna kadar doğrulandı (sezonlar arası köprü için)."""
    league: str
    source: str
    season: str
    retrieved_at: dt.datetime
    matches: tuple[ScheduledMatch, ...]
    complete: bool
    detail: str
    sha256: str
    unmapped_names: tuple[str, ...] = ()
    windows: tuple[tuple[int, int], ...] | None = None
    reaches_end: bool | None = None
    matching_version: str = ""
    participants: int | None = None
    # A/B kanıtının dayandığı bağımsız katılımcı referansının erişilebilir olduğu en erken an (None: depo kaynaklı
    # liste veya liste yok). Değerlendirme anı bundan önceyse aynı takvim kısmi sayılır (``coverages_at``).
    participants_since: dt.datetime | None = None

    @property
    def window(self) -> tuple[int, int] | None:
        if not self.matches:
            return None
        days = [day_number(m.date) for m in self.matches]
        return min(days), max(days)

    @property
    def verified_windows(self) -> tuple[tuple[int, int], ...]:
        if self.windows is not None:
            return tuple(self.windows)
        return (self.window,) if (self.complete and self.window is not None) else ()

    @property
    def season_end_verified(self) -> bool:
        return bool(self.complete if self.reaches_end is None else self.reaches_end)


class ParticipantSet(frozenset):
    """Bağımsız katılımcı referansından gelen küme ve referansın bu sistemde erişilebilir olduğu en erken an
    (``available_since``, zaman dilimli). Kümenin hangi sezona ait olduğu ile dosyanın ne zaman erişilebilir olduğu ayrı
    bilgilerdir; zaman bilgisi olmayan referans kümesi kapsam kanıtı olarak kullanılmaz."""

    def __new__(cls, teams=(), available_since: dt.datetime | None = None):
        obj = super().__new__(cls, teams)
        obj.available_since = available_since
        return obj


def expected_per_team(league: str, n_teams: int) -> int:
    """Takım başına normal sezon maç sayısı (dizi araştırmasıyla aynı tek kaynak)."""
    from .sequences.timeline import REGULAR_LEN_OVERRIDE

    return int(REGULAR_LEN_OVERRIDE.get(league, 2 * (n_teams - 1)))


# Normal sezondan sonra şampiyonluk/küme aşaması (split veya play-off) olan ligler (bugünkü format). Bu liglerde
# listelenen takvim sezonun sonunu kanıtlamaz (aşamanın toplam tur sayısı doğrulanmış bir kaynaktan bilinmiyor):
# tam sezon (A) kurulmaz ve sezonlar arası köprü yoktur. Liste yalnızca daha sıkı sonuç verir; geçmiş sezonlara
# "tamlık" yüklemez.
POST_STAGE_LEAGUES = frozenset({"SC0", "B1", "G1", "AUT", "DNK", "SWZ"})

# Numaralı normal sezon turu etiketleri ("Matchday 7", "7. Spieltag"); başka etiketler ayrı aşama sayılır
_ROUND_PATTERNS = (
    re.compile(r"^(?:matchday|match day|round|spieltag|jornada|giornata|journee|speeldag|rodada|fecha|runde|hafta|"
               r"week|gameweek|matchweek)\s*(\d+)$"),
    re.compile(r"^(\d+)\s*\.?\s*(?:spieltag|hafta|journee|giornata|jornada|matchday|round|speeldag|runde)$"),
)


def round_number(label) -> int | None:
    """Kaynağın tur etiketinden normal sezon tur numarası; numaralı tur değilse None."""
    if label is None:
        return None
    s = unicodedata.normalize("NFKD", str(label)).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"\s+", " ", s).strip()
    for p in _ROUND_PATTERNS:
        m = p.match(s)
        if m:
            return int(m.group(1))
    return None


def _verify_calendar(league: str, matches: list[ScheduledMatch], conflicted: set[int],
                     participants) -> tuple[tuple, bool, str, int]:
    """(B aralıkları, A tamlığı, açıklama, doğrulanan tur sayısı). Kaynağın kendi takım sayısı kullanılmaz."""

    part = frozenset(participants or ())
    n = len(part)
    if n < 4:
        return (), False, "bağımsız katılımcı listesi yok", 0
    named = {t for m in matches for t in (m.home, m.away)}
    if None in named or named != part:
        return (), False, "kaynak takımları bağımsız katılımcı listesiyle uyuşmuyor", 0
    regular: dict[int, list[int]] = {}
    for i, m in enumerate(matches):
        r = round_number(m.round)
        if r is not None:
            regular.setdefault(r, []).append(i)

    def structural(idx):
        """Turun yapısal kaydı: aynı eşleşmenin oynanmamış (ertelenen/iptal) kaydı, yenisi varsa sayılmaz."""
        if any(i in conflicted for i in idx):
            return None
        pairs: dict[tuple, list[ScheduledMatch]] = {}
        for i in idx:
            pairs.setdefault((matches[i].home, matches[i].away), []).append(matches[i])
        use = []
        for lst in pairs.values():
            played = [m for m in lst if m.status not in NOT_PLAYED_STATUSES]
            use += played or lst[:1]
        teams = [t for m in use for t in (m.home, m.away)]
        return use if (len(teams) == len(set(teams)) and len(use) == n // 2) else None

    k, rounds = 0, {}
    while (k + 1) in regular:
        use = structural(regular[k + 1])
        if use is None:
            break
        k += 1
        rounds[k] = use
    if not k:
        return (), False, "1. turdan başlayan, katılımcıların tamamını içeren tur yok", 0
    ver = {i for r in range(1, k + 1) for i in regular[r]}
    days = [day_number(matches[i].date) for i in ver]
    start, end = min(days), max(days)
    unver = [i for i in range(len(matches)) if i not in ver]
    block = [day_number(matches[i].date) for i in unver if day_number(matches[i].date) >= start]
    if block:
        end = min(end, min(block) - 1)
    windows = ((start, end),) if end >= start else ()
    per = expected_per_team(league, n)
    rounds_exp = per if n % 2 == 0 else (per * n // (n - 1) if (per * n) % (n - 1) == 0 else None)
    why = ""
    if rounds_exp is None or per % (n - 1):
        why = "lig formatı bağımsız katılımcı sayısıyla tutarsız"
    elif unver:
        why = "doğrulanmamış tur veya aşama maçı var"
    elif k < rounds_exp:
        why = f"yalnızca {k}/{rounds_exp} tur listelenmiş"
    elif league in POST_STAGE_LEAGUES:
        why = "normal sezon sonrası aşaması (split/play-off) olan lig: sezon sonu takvimden doğrulanamaz"
    else:
        kk = per // (n - 1)
        reg = [m for r in range(1, rounds_exp + 1) for m in rounds[r]]
        upair = Counter(frozenset((m.home, m.away)) for m in reg)
        opair = Counter((m.home, m.away) for m in reg)
        ok = len(upair) == n * (n - 1) // 2 and all(v == kk for v in upair.values())
        if ok and kk % 2 == 0:
            ok = len(opair) == n * (n - 1) and all(v == kk // 2 for v in opair.values())
        if not ok:
            why = "rakip/iç-dış saha dağılımı lig formatıyla uyuşmuyor"
    reaches = not why
    return windows, reaches, why, k


def _status_of(m: dict) -> str:
    st = str(m.get("status") or "").strip().upper()
    if st in ("POSTPONED", "CANCELLED", "CANCELED", "ABANDONED", "SUSPENDED"):
        return "CANCELLED" if st == "CANCELED" else st
    score = m.get("score")
    if isinstance(score, dict):
        score = score.get("ft")
    if isinstance(score, (list, tuple)) and len(score) >= 2 and all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in score[:2]):
        return FINISHED
    if isinstance(m.get("score1"), int) and isinstance(m.get("score2"), int):
        return FINISHED
    return SCHEDULED_OR_UNKNOWN


def _score_of(m: dict):
    score = m.get("score")
    if isinstance(score, dict):
        score = score.get("ft")
    if isinstance(score, (list, tuple)):
        return tuple(score[:2])
    return (m.get("score1"), m.get("score2"))


def coverage_from_openfootball(data: bytes, league: str, season: str, retrieved_at: dt.datetime,
                               known_teams, participants=None) -> SourceCoverage:
    """openfootball/football.json sezon dosyasından kapsam kanıtı (ağ isteği yapmaz).

    ``known_teams``: ad eşlemesinin bağlamı (ligin son iki sezonundaki depo takımları). ``participants``: bu sezonun
    BAĞIMSIZ katılımcı listesi (aynı sezonun başka sağlayıcıdan gelen veri deposundaki takımları); verilmezse tamlık
    (A/B) kanıtı kurulmaz. Tekilleştirme: kaynak maç kimliği varsa onunla, yoksa (tur, tarih, ev, deplasman) anahtarıyla;
    aynı anahtarlı farklı içerik çakışmadır (birleştirilmez, turu doğrulanmamış yapar)."""
    from .data.teams import resolve_teams

    raw_bytes = data if isinstance(data, bytes) else str(data).encode("utf-8")
    sha = hashlib.sha256(raw_bytes).hexdigest()
    since = getattr(participants, "available_since", None)
    if isinstance(participants, ParticipantSet) and since is None:
        participants = None  # erişilebilirlik anı bilinmeyen referans kanıt değildir
    base = dict(league=league, source="openfootball", season=season, retrieved_at=retrieved_at, sha256=sha,
                matching_version=MATCHING_VERSION, windows=(), reaches_end=False,
                participants=len(set(participants)) if participants else None,
                participants_since=since if participants else None)
    try:
        obj = json.loads(raw_bytes.decode("utf-8-sig"))
        raw = obj.get("matches", []) if isinstance(obj, dict) else []
        if not isinstance(raw, list):
            raw = []
    except (ValueError, UnicodeDecodeError):
        return SourceCoverage(matches=(), complete=False, detail="dosya okunamadı", **base)
    rows, seen, conflicts, dup = [], {}, set(), 0
    for m in raw:
        if not isinstance(m, dict):
            continue
        t1, t2 = m.get("team1"), m.get("team2")
        t1 = t1.get("name") if isinstance(t1, dict) else t1
        t2 = t2.get("name") if isinstance(t2, dict) else t2
        raw_date = m.get("date")
        try:
            d = pd.to_datetime(raw_date, errors="coerce") if isinstance(raw_date, str) else pd.NaT
        except (TypeError, ValueError, OverflowError):
            d = pd.NaT
        if not t1 or not t2 or pd.isna(d) or not str(t1).strip() or not str(t2).strip():
            continue
        t1, t2, rnd = str(t1).strip(), str(t2).strip(), (None if m.get("round") is None else str(m.get("round")))
        pid = m.get("id")
        key = (("id", str(pid)) if isinstance(pid, (str, int)) and not isinstance(pid, bool)
               else ("olay", rnd, d.date(), t1, t2))
        content = (rnd, d.date(), t1, t2, _status_of(m), _score_of(m))
        if key in seen:
            if seen[key] == content:
                dup += 1  # birebir yinelenen kayıt: sayımı artırmaz
                continue
            conflicts.add(key)
        else:
            seen[key] = content
        rows.append((key, d.date(), t1, t2, _status_of(m), rnd))
    known = sorted(set(known_teams or ()))
    res = resolve_teams([r[2] for r in rows] + [r[3] for r in rows], known, league, "openfootball")
    out, bad = [], set()
    for _, day, t1, t2, status, rnd in rows:
        h = res[t1].team if res[t1].exact else None
        a = res[t2].team if res[t2].exact else None
        if h is not None and h == a:  # ev sahibi ve deplasman aynı takıma düşüyor: ikisi de güvenilmez
            bad |= {t1, t2}
            h = a = None
        out.append(ScheduledMatch(day, t1, t2, h, a, status, rnd))
    unmapped = tuple(sorted({n for n, v in res.items() if not v.exact} | bad))
    if not out:
        return SourceCoverage(matches=(), complete=False, detail="dosyada maç yok", unmapped_names=unmapped, **base)
    conflicted = {i for i, r in enumerate(rows) if r[0] in conflicts}
    windows, complete, why, k = _verify_calendar(league, out, conflicted, participants)
    rng = (f"{day_to_date(windows[0][0])}–{day_to_date(windows[0][1])}" if windows else "yok")
    detail = (f"{len(out)} maç ({dup} yinelenen kayıt elendi, {len(conflicts)} çakışan anahtar); bağımsız katılımcı: "
              f"{base['participants'] or 'yok'}; doğrulanan ardışık tur: {k}; geçmiş aralık kanıtı: {rng}; tam sezon "
              f"takvimi: {'evet' if complete else 'hayır (' + why + ')'}")
    return SourceCoverage(matches=tuple(out), complete=complete, detail=detail, unmapped_names=unmapped,
                          **{**base, "windows": windows, "reaches_end": complete})


# ----------------------------------------------------------------------------
# Model durumu görünümü (tahminde KULLANILAN durumun kapsamı)
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class LeagueStateView:
    last_day: int | None
    team_last: dict
    team_days: dict  # takım -> durumun bildiği maç günleri
    team_days_from: dict  # takım -> bu günden itibaren team_days tam (None = baştan beri tam)
    digest: str
    rows: tuple | None = None  # (sayı, sha) — durumun kurulduğu maçlar; eski model dosyalarında yok (None)


def league_state_digest(st) -> str:
    """Bir lig durumunun özeti (tahmin ile uygunluk sonucunun AYNI durumdan geldiğini bağlamak için)."""
    if st is None:
        return ""
    rows = getattr(st, "row_digest", None)
    if hasattr(st, "dates"):  # gol durumu
        body = ["gol", st.last_match_day, sorted((t, int(d)) for t, d in st.last_day.items()), st.season,
                st.season_n, rows]
    else:  # 1X2 durumu
        body = ["mac", st.last_day, sorted((t, f.last_day) for t, f in st.forms.items()), st.season, rows]
    return _digest(body)


@dataclass(frozen=True)
class StateView:
    kind: str  # "gol" | "mac"
    feature_version: str
    model_cutoff: str  # model parametrelerinin eğitim verisi kesimi (dinamik durumdan ayrı)
    leagues: dict
    available_since: dt.datetime | None  # durumun (ve içindeki bilginin) en geç bu anda var olduğu biliniyor
    train_sources: tuple[str, ...] | None  # modelin eğitildiği verinin kaynak etiketleri (biliniyorsa)
    fingerprint: str

    def scope(self, league: str, teams: tuple[str, ...]) -> dict:
        lv = self.leagues.get(league)
        out = {"tur": self.kind, "ozellik_surumu": self.feature_version, "model_egitim_kesimi": self.model_cutoff,
               "egitim_kaynaklari": list(self.train_sources) if self.train_sources is not None else None}
        if lv is None:
            return out
        out.update({
            "lig_durum_son_mac": str(day_to_date(lv.last_day)) if lv.last_day is not None else None,
            "takim_durum_son_mac": {t: (str(day_to_date(lv.team_last[t])) if t in lv.team_last else None)
                                    for t in teams},
            "durum_ozeti": lv.digest,
        })
        return out


def state_view(engine) -> StateView | None:
    """Gol motoru (GoalEngine) veya 1X2 motoru (PredictionEngine) durumunun kapsam görünümü."""
    if engine is None or not getattr(engine, "trained", False):
        return None
    kind = "gol" if hasattr(engine, "validated") else "mac"
    leagues = {}
    for lg, st in (getattr(engine, "states", None) or {}).items():
        team_last, team_days, team_from = {}, {}, {}
        if hasattr(st, "dates"):  # gol durumu: takım başına son 60 maç günü
            for t, dq in st.dates.items():
                days = [int(d) for d in dq]
                team_days[t] = frozenset(days)
                team_from[t] = days[0] if dq.maxlen is not None and len(days) >= dq.maxlen else None
            team_last = {t: int(d) for t, d in st.last_day.items()}
            last = st.last_match_day
        else:  # 1X2 durumu: takım başına son 6 maç
            for t, f in st.forms.items():
                days = [int(r[0]) for r in f.all]
                team_days[t] = frozenset(days)
                team_from[t] = min(days) if (days and f.all.maxlen is not None and len(days) >= f.all.maxlen) else None
                if f.last_day is not None:
                    team_last[t] = int(f.last_day)
            last = st.last_day
        rows = getattr(st, "row_digest", None)
        leagues[lg] = LeagueStateView(None if last is None else int(last), team_last, team_days, team_from,
                                      league_state_digest(st), tuple(rows) if rows is not None else None)
    if kind == "gol":
        from .goals.model import FEATURE_VERSION as fv

        cutoff = str(getattr(engine, "data_cutoff", "") or "")
        srcs = (getattr(engine, "manifest", None) or {}).get("sources")
    else:
        from .models.features import FEATURES

        fv = "mac-ozellik:" + hashlib.sha256(",".join(FEATURES).encode()).hexdigest()[:8]
        lmd = getattr(engine, "last_match_date", None)
        cutoff = str(pd.Timestamp(lmd).date()) if lmd is not None else ""
        srcs = getattr(engine, "train_sources", None)
    avail = getattr(engine, "state_available_since", None)
    if not (isinstance(avail, dt.datetime) and avail.tzinfo is not None):
        avail = None  # köken bilgisi yoksa uydurulmaz
    fp = _digest([kind, fv, cutoff, sorted((lg, v.digest) for lg, v in leagues.items())])
    return StateView(kind, fv, cutoff, leagues, avail, tuple(sorted(srcs)) if srcs is not None else None, fp)


# ----------------------------------------------------------------------------
# Kaynak hakları
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceUse:
    """Bir kaynak etiketinin kullanım kapsamı. Alanlar ayrıdır; belgelenmemiş alan izinli sayılmaz (varsayılanlar
    kapalıdır: doğrudan kurulan nesne eksik alanla hak kazanmaz)."""
    label: str
    key: str | None
    erisim: str  # kullanıcı indirme onayı: IZINLI (onay gerekmez) / ONAY_VAR / ONAY_YOK / BILINMIYOR
    sonuc_kullanimi: str  # sonuç verisinin analizde kullanımı: IZINLI_BELGELI / DOGRULANAMADI / BILINMIYOR
    model_egitimi: str
    yeniden_dagitim: str
    model_kullanimi: str = "BILINMIYOR"  # bu veriyle eğitilmiş mevcut modelin kullanımı
    erisim_kosullari: str = "BILINMIYOR"  # kaynağın erişim/indirme koşulları (indirme onayından ayrı)
    ticari_kullanim: str = "BILINMIYOR"
    saglar: tuple[str, ...] = ()  # kaynağın uygulamada sağladığı veri türleri ("sonuc", "fikstur", "takvim")
    koken: str = "GEREKMEZ"  # GEREKMEZ / DOGRULANDI / DOGRULANAMADI (satırların gerçekten bu kaynaktan geldiği)
    beyan: str = "YOK"  # VERI-01 kişisel kullanım beyanı: VAR / YOK (VAR iken açılan alanlar "KULLANICI_BEYANI")


# İşlem -> gerekli kapsam. "veri": işlemde kullanılan sonuç verisinin etiketleri; "model": modelin eğitim verisinin
# etiketleri. Yeniden dağıtım ve ticari kullanım bu işlemlerin hiçbiri için gerekmez (uygulama veri dağıtmaz,
# ticari hizmet vermez); gerekmeyen hak işlemi engellemez.
OPERATION_SCOPES: dict[str, dict[str, tuple[str, ...]]] = {
    "tahmin": {"veri": ("sonuc_kullanimi",), "model": ("model_egitimi", "model_kullanimi")},
    "bahis": {"veri": ("sonuc_kullanimi",), "model": ("model_egitimi", "model_kullanimi")},
    "egitim": {"veri": ("sonuc_kullanimi", "model_egitimi"), "model": ()},
}
# Kabul edilen kapsam değerleri: belgeli izin veya (VERI-01) kullanıcının kişisel kullanım beyanı. "KULLANICI_BEYANI"
# yalnızca ``rights_from_registry`` tarafından, kayıtta DOGRULANAMADI olan ve beyan verilebilen alanlara yazılır.
ACCEPTED_RIGHTS = frozenset({"IZINLI_BELGELI", "KULLANICI_BEYANI"})
_SCOPE_CODES = {"sonuc_kullanimi": "KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI",
                "model_egitimi": "KAYNAK_EGITIM_HAKKI_DOGRULANAMADI",
                "model_kullanimi": "KAYNAK_MODEL_KULLANIMI_DOGRULANAMADI"}


@dataclass(frozen=True)
class RightsStatus:
    by_label: dict  # etiket -> SourceUse

    def codes(self, data_labels, train_labels, operation: str = "tahmin") -> list[str]:
        """``operation`` için engel kodları. Etiketin hakkı, yalnızca kaynağın uygulamada gerçekten sağladığı sonuç
        verisi için geçerlidir (ör. yalnızca fikstür sağlayan kaynağın etiketiyle sonuç satırı hak kazanamaz)."""
        scope = OPERATION_SCOPES[operation]
        data_labels, train_labels = set(data_labels), set(train_labels)
        out = []
        for lb in data_labels | train_labels:
            u = self.by_label.get(lb)
            if u is None or u.key is None:
                out.append("KAYNAK_HAKKI_BILINMIYOR")
                continue
            if "sonuc" not in u.saglar:
                out.append("KAYNAK_ETIKETI_UYUMSUZ")
            if u.koken == "DOGRULANAMADI":
                out.append("KAYNAK_KOKENI_DOGRULANAMADI")
            if u.erisim not in ("IZINLI", "ONAY_VAR"):
                out.append("KAYNAK_ERISIM_IZNI_YOK")
            need = (scope["veri"] if lb in data_labels else ()) + (scope["model"] if lb in train_labels else ())
            for f in dict.fromkeys(need):
                if getattr(u, f) not in ACCEPTED_RIGHTS:
                    out.append(_SCOPE_CODES[f])
        return sorted(set(out))

    def summary(self, labels) -> dict:
        return {lb: (asdict(self.by_label[lb]) if lb in self.by_label else None) for lb in sorted(set(labels))}


def rights_from_registry(labels, consent: dict | None, verified_labels=None,
                         declarations: dict | None = None) -> RightsStatus:
    """Kaynak kaydındaki BELGELİ kullanım kapsamı + kullanıcı onayı (onay yalnızca erişimi etkiler).

    ``verified_labels``: kökeni doğrulanmış etiketler (``data.provenance.verified_labels``). Kaydında
    ``koken_dogrulamasi`` olan kaynak, etiketi doğrulanmadıkça hak kazanmaz.

    ``declarations`` (VERI-01): kullanıcının kişisel kullanım beyanları (kaynak anahtarı -> zaman). Beyan yalnızca
    indirme onayı da olan ve kaydında ``kisisel_beyan`` alanları bulunan kaynakta, değeri tam olarak DOGRULANAMADI olan
    bu alanları "KULLANICI_BEYANI" yapar. Ticari kullanım, yeniden dağıtım ve erişim koşulları değişmez."""
    from .data.source_registry import SOURCE_LABELS, SOURCES, USE_RIGHTS

    consent = consent or {}
    declarations = declarations or {}
    out = {}
    for lb in set(labels):
        key = SOURCE_LABELS.get(lb)
        if key is None or key not in USE_RIGHTS or key not in SOURCES:
            out[lb] = SourceUse(lb, None, "BILINMIYOR", "BILINMIYOR", "BILINMIYOR", "BILINMIYOR")
            continue
        r = USE_RIGHTS[key]
        erisim = "IZINLI" if not SOURCES[key].requires_consent else ("ONAY_VAR" if key in consent else "ONAY_YOK")
        koken = ("GEREKMEZ" if not r.get("koken_dogrulamasi") else
                 "DOGRULANDI" if lb in set(verified_labels or ()) else "DOGRULANAMADI")
        scope = {f: r.get(f, "BILINMIYOR") for f in ("sonuc_kullanimi", "model_egitimi", "model_kullanimi")}
        beyan = "YOK"
        if key in declarations and erisim == "ONAY_VAR" and r.get("kisisel_beyan"):
            beyan = "VAR"
            for f in r["kisisel_beyan"]:
                if scope.get(f) == "DOGRULANAMADI":
                    scope[f] = "KULLANICI_BEYANI"
        out[lb] = SourceUse(lb, key, erisim, scope["sonuc_kullanimi"], scope["model_egitimi"], r["yeniden_dagitim"],
                            scope["model_kullanimi"], r.get("erisim_kosullari", "BILINMIYOR"),
                            r.get("ticari_kullanim", "BILINMIYOR"), tuple(r.get("saglar", ())), koken, beyan)
    return RightsStatus(out)


def training_rights_codes(matches: pd.DataFrame | None, consent: dict | None, verified_labels=None,
                          declarations: dict | None = None) -> list[str]:
    """Gerçek veriyle model eğitimi için engel kodları (boş = eğitime hak açısından engel yok).

    Eğitim verisinin her satırının kaynağı kayıtlı olmalı ve kaynak kaydında sonuç kullanımı ile model eğitimi hakkı
    belgeli olmalı ya da (VERI-01) kullanıcı o kaynak için kişisel kullanım beyanı vermiş olmalıdır. İndirme onayı tek
    başına erişimi kapsar; onay kutusu veya bayrak bu kontrolü aşamaz."""
    if matches is None or len(matches) == 0:
        return []
    if "source" not in matches:
        return ["KAYNAK_HAKKI_BILINMIYOR"]
    src = matches["source"]
    out = ["KAYNAK_HAKKI_BILINMIYOR"] if src.isna().any() else []
    labels = set(src.dropna().astype(str))
    rights = rights_from_registry(labels, consent, verified_labels, declarations)
    return sorted(set(out) | set(rights.codes(labels, (), "egitim")))


# ----------------------------------------------------------------------------
# Sonuç
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Eligibility:
    candidate_id: str  # kanonik maç kimliği veya (eşleşmeyen fikstür için) aday kimliği
    canonical_id: bool  # False: yalnızca kayıt takibi için aday kimliği; kanonik maç kimliği DEĞİLDİR
    league: str
    home: str
    away: str
    match_date: str
    market: str
    evaluated_at: str  # gerçek değerlendirme anı (UTC, ISO)
    info_cutoff: str  # bu günden ÖNCEKİ sonuçlar erişilebilir sayıldı (İstanbul tarihi)
    data_cutoff: str | None  # depoda bilgi kesiminden önceki son lig maçı
    data_scope: dict
    state_scope: dict
    freshness: str
    continuity: str  # TAM / EKSIK / BILINMIYOR
    team_mapping: str  # ESLESTI / ESLESMEDI / KONTROL_EDILMEDI
    required_fields: str  # YETERLI / EKSIK / KONTROL_EDILMEDI
    source_use: dict
    reasons: tuple[str, ...]
    forecast_ok: bool
    bet_ok: bool
    primary_text: str
    fix_text: str
    policy_version: str = POLICY_VERSION
    fingerprint: str = ""
    policy_mode: str = "siki"  # VERI-01 veri denetimi modu ("siki" = v2 kuralları; "standart")

    @property
    def status_key(self) -> str:
        if self.policy_mode == "standart":
            # Tahmin gösteriliyorsa ama bahis adayı değilse "Uyarılı"; engellenmişse birincil nedenin kendi türü
            # (ör. MODEL_YOK "Uygun değil"dir; başka bir koddan gelen "Eksik veri" etiketi taşımaz)
            if self.forecast_ok:
                return "UYGUN" if self.bet_ok else "UYARILI"
            lead = self.lead_code
            f = REASONS[lead].freshness if lead else None
            return f if f in (KNOWN_STALE, UNKNOWN) else "ENGELLI"
        if self.forecast_ok:
            return "UYGUN"
        if self.freshness in (KNOWN_STALE, UNKNOWN):
            return self.freshness
        return "ENGELLI"

    @property
    def status_label(self) -> str:
        """Renkten bağımsız okunabilir durum: Kullanılabilir / Uyarılı / Eksik veri / Doğrulanamıyor / Uygun değil."""
        return STATUS_TEXT[self.status_key]

    @property
    def as_of_day(self) -> dt.date:
        return dt.date.fromisoformat(self.info_cutoff)

    @property
    def state_digest(self) -> str:
        return str(self.state_scope.get("durum_ozeti", "") or "")

    @property
    def lead_code(self) -> str | None:
        return lead_reason(self.reasons, self.policy_mode)

    def short_text(self) -> str:
        """Tek satır: durum, somut neden, veri kesimi ve gereken düzeltme."""
        cut = self.data_cutoff or "-"
        if self.forecast_ok and self.bet_ok:
            if self.freshness != VERIFIED_CURRENT:  # yalnızca standart modda: güncellik kanıtı yok (bilinen sorun yok)
                return f"{self.status_label} (veri kesimi {cut}); not: {self.primary_text}"
            return f"{self.status_label} (veri kesimi {cut})"
        if self.forecast_ok:
            return (f"{self.status_label}; bahis adayı değil: {self.primary_text} [{self.lead_code}] — "
                    f"veri kesimi {cut}; gereken: {self.fix_text}")
        return (f"{self.status_label}: {self.primary_text} [{self.lead_code}] — veri kesimi {cut}; "
                f"gereken: {self.fix_text}")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["reasons"] = list(self.reasons)
        d["status_label"] = self.status_label
        return d

    def compact(self) -> dict:
        """Kayıtlara geriye uyumlu ek alan olarak yazılan özet."""
        return {"politika": self.policy_version, "politika_modu": self.policy_mode, "guncellik": self.freshness,
                "tahmin_uygun": self.forecast_ok,
                "bahis_veri_uygun": self.bet_ok, "nedenler": list(self.reasons), "bilgi_kesimi": self.info_cutoff,
                "veri_kesimi": self.data_cutoff, "degerlendirme_ani": self.evaluated_at,
                "aday_kimlik": self.candidate_id, "kanonik_kimlik": self.canonical_id,
                "durum_ozeti": self.state_digest[:16], "ozet": self.fingerprint[:16]}


def candidate_id(source: str, league: str, date, raw_home: str, raw_away: str) -> str:
    """Eşleşmeyen fikstür için kararlı aday kimliği (kanonik maç kimliği DEĞİLDİR)."""
    key = "|".join([str(source or ""), str(league), str(pd.Timestamp(date).date()), str(raw_home), str(raw_away)])
    return "aday:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _finalize(base: dict, codes, markets, per_market: dict, evidence_checked: bool,
              required_checked: bool, mode: str = "siki") -> dict:
    """Kodlardan pazar başına sonuç. ``mode`` (VERI-01): "siki" = v2 kuralı (güncellik VERIFIED_CURRENT değilse tahmin
    yok); "standart" = yalnızca "tahmin" düzeyindeki kodlar tahmini, "bahis" düzeyindekiler bahis adayını engeller."""
    if mode not in LEVELS:
        raise ValueError(f"Bilinmeyen veri denetimi modu: {mode}")
    out = {}
    for mk in markets:
        cs = tuple(sorted(set(codes) | set(per_market.get(mk, ()))))
        stale = any(REASONS[c].freshness == KNOWN_STALE for c in cs)
        unknown = any(REASONS[c].freshness == UNKNOWN for c in cs) or not evidence_checked
        freshness = KNOWN_STALE if stale else (UNKNOWN if unknown else VERIFIED_CURRENT)
        lv = {c: code_level(c, mode) for c in cs}
        hard = any(v == "tahmin" for v in lv.values())
        if mode == "siki":
            forecast_ok = freshness == VERIFIED_CURRENT and required_checked and not hard
        else:
            forecast_ok = required_checked and not hard
        bet_ok = forecast_ok and not any(v == "bahis" for v in lv.values())
        blocking = [c for c in cs if lv[c] != "yok"]
        if not forecast_ok and (not blocking if mode == "siki" else not hard):
            blocking = blocking + ["BAGLAM_YOK"]
            cs = tuple(sorted(set(cs) | {"BAGLAM_YOK"}))
        lead = lead_reason(blocking, mode)
        if lead:
            primary, fix = REASONS[lead].text, REASONS[lead].fix
        elif freshness != VERIFIED_CURRENT:  # yalnızca standart modda: tahmin uygun, güncellik kanıtlanamadı
            note = min((c for c in cs if REASONS[c].freshness in (UNKNOWN, KNOWN_STALE)), key=_lead_key, default=None)
            if note is not None:
                primary = f"Güncellik bağımsız bir takvimle doğrulanamadı — {REASONS[note].text} [{note}]"
                fix = REASONS[note].fix
            else:
                primary, fix = "Güncellik bağımsız bir takvimle doğrulanamadı.", "-"
        else:
            primary, fix = "Veri uygunluğu doğrulandı.", "-"
        continuity = "EKSIK" if stale else ("BILINMIYOR" if unknown else "TAM")
        if any(c in ("GEREKLI_ALAN_EKSIK", "TAKIM_GECMISI_YETERSIZ") for c in cs):
            req = "EKSIK"
        else:
            req = "YETERLI" if required_checked else "KONTROL_EDILMEDI"
        e = dict(base, market=mk, freshness=freshness, continuity=continuity, required_fields=req, reasons=cs,
                 forecast_ok=forecast_ok, bet_ok=bet_ok, primary_text=primary, fix_text=fix,
                 policy_version=POLICY_VERSIONS[mode], policy_mode=mode)
        fp = _digest({k: v for k, v in e.items() if k != "evaluated_at"})
        out[mk] = Eligibility(**e, fingerprint=fp)
    return out


# ----------------------------------------------------------------------------
# Bağlam
# ----------------------------------------------------------------------------

class EligibilityContext:
    """Veri deposu + kullanılan model durumu + kaynak kapsamı + haklar.

    Bağlamın parmak izi bunlardan herhangi biri değişince değişir; önbellek parmak izine bağlıdır (eski "uygun"
    sonucu yeni veri/durum/kapsamla kullanılmaz)."""

    def __init__(self, matches: pd.DataFrame | None, state: StateView | None,
                 coverages: dict | None = None, rights: RightsStatus | None = None,
                 consent: dict | None = None, verified_labels=None, *, declarations: dict | None = None,
                 mode: str = "siki"):
        """``mode``: veri denetimi modu (VERI-01; kütüphane varsayılanı "siki" = v2 kuralları). ``declarations``:
        kullanıcının kişisel kullanım beyanları (``rights_from_registry``)."""
        if mode not in POLICY_MODES:
            raise ValueError(f"Bilinmeyen veri denetimi modu: {mode}")
        self.mode = mode
        self.policy_version = POLICY_VERSIONS[mode]
        self.state = state
        self.coverages = {lg: tuple(v) for lg, v in (coverages or {}).items()}
        need = ("league", "date", "home", "away", "fthg", "ftag")
        m = matches
        if m is None or m.empty or not all(c in m for c in need):
            m = pd.DataFrame({c: pd.Series(dtype=object) for c in need + ("season", "hthg", "htag", "source")})
        m = m[pd.to_numeric(m["fthg"], errors="coerce").notna() & pd.to_numeric(m["ftag"], errors="coerce").notna()]
        # Modelin bu satırı işleyip işlemediği: gol durumu karantinadaki (geçersiz skorlu) kayıtları atlar.
        if state is not None and state.kind == "gol" and len(m) and "hthg" in m and "htag" in m:
            from .goals.markets import frame_issues

            ingest = (frame_issues(m) == "").to_numpy()
        else:
            ingest = np.ones(len(m), dtype=bool)
        keep = DIGEST_COLUMNS.get(state.kind, ()) if state is not None else ()
        cols = [c for c in ("league", "season", "date", "home", "away", "source") + tuple(keep) if c in m]
        m = m[cols].copy()
        m["date"] = pd.to_datetime(m["date"]).dt.normalize()
        m["day"] = ((m["date"] - EPOCH).dt.days).astype(int)
        m["ingest"] = ingest
        for c in ("source", "season"):
            if c not in m:
                m[c] = None
        self.matches = m
        self._by_league = {lg: g.sort_values("day", kind="mergesort") for lg, g in m.groupby("league", sort=False)}
        labels = set(m["source"].dropna().astype(str))
        train = set(state.train_sources) if (state is not None and state.train_sources is not None) else labels
        self.rights = (rights if rights is not None
                       else rights_from_registry(labels | train, consent, verified_labels, declarations))
        h = hashlib.sha256()
        h.update(pd.util.hash_pandas_object(m[["league", "day", "home", "away", "source", "ingest"]].astype(str),
                                            index=False).values.tobytes() if len(m) else b"bos")
        h.update((state.fingerprint if state else "durum-yok").encode())
        if state is not None:
            h.update(str(state.available_since).encode())
        for lg in sorted(self.coverages):
            for c in self.coverages[lg]:
                h.update(f"{lg}|{c.season}|{c.sha256}|{c.retrieved_at.isoformat()}|{c.matching_version}|"
                         f"{c.verified_windows}|{c.season_end_verified}|{c.participants}".encode())
                if c.participants_since is not None:
                    h.update(f"|katilimci:{c.participants_since.isoformat()}".encode())
        h.update(_digest({k: asdict(v) for k, v in self.rights.by_label.items()}).encode())
        h.update(f"{self.policy_version}|{MATCHING_VERSION}".encode())
        self.fingerprint = h.hexdigest()
        self._cache: dict = {}
        self._rows_cache: dict = {}

    def league_matches(self, league: str) -> pd.DataFrame:
        return self._by_league.get(league, self.matches.iloc[0:0])

    def coverages_at(self, league: str, as_of: dt.datetime) -> list[SourceCoverage]:
        """``as_of`` anında kanıt olarak kullanılabilen kapsamlar. Kaynak dosyası o andan önce (veya o anda) alınmış
        olmalı; takvim aralıkları bağımsız katılımcı referansına dayanıyorsa referans da o anda erişilebilir olmalı —
        değilse aynı takvim yalnızca kısmi takvim sayılır (A/B tamlık kanıtı yok; bilinen eksik yine görünür)."""
        out = []
        for c in self.coverages.get(league, ()):
            if c.retrieved_at > as_of:
                continue
            if c.participants_since is not None and c.participants_since > as_of:
                c = replace(c, windows=(), complete=False, reaches_end=False, participants=None,
                            detail=c.detail + "; bağımsız katılımcı referansı bu andan sonra erişilebilir: tamlık "
                                              "kanıtı yok")
            out.append(c)
        return out

    def _rows(self, league: str, last_day: int) -> tuple[int, str]:
        """Depoda modelin işleyeceği, ``last_day``e kadarki lig satırlarının kimliği (önbellekli)."""
        key = (league, int(last_day))
        hit = self._rows_cache.get(key)
        if hit is None:
            g = self.league_matches(league)
            g = g[g["ingest"] & (g["day"] <= last_day)]
            hit = rows_digest(g, self.state.kind)
            self._rows_cache[key] = hit
        return hit

    def recent_teams(self, league: str, seasons: int = 2) -> list[str]:
        g = self.league_matches(league)
        if g.empty:
            return []
        recent = sorted(g["season"].dropna().astype(str).unique())[-seasons:]
        g = g[g["season"].astype(str).isin(recent)] if recent else g
        return sorted(set(g["home"]) | set(g["away"]))

    # ------------------------------------------------------------------ değerlendirme
    def evaluate(self, *, league: str, date, home: str, away: str, as_of: dt.datetime, markets,
                 source: str = "", mapped: bool = True, raw_home: str | None = None, raw_away: str | None = None,
                 prediction_codes=None, event_id: str | None = None) -> dict:
        """Bir fikstür için pazar başına uygunluk (önbellekli; bağlam parmak izi değişince yeniden hesaplanır).

        ``prediction_codes``: motorun yapılandırılmış veri kodları (``GoalPrediction.data_codes``); None ise gerekli
        alan yeterliliği "KONTROL_EDILMEDI" olur ve tahmin uygun sayılmaz."""
        markets = tuple(markets)
        cut = info_cutoff(as_of)
        pcodes = None if prediction_codes is None else tuple(sorted(prediction_codes))
        live = self._live(as_of)
        # O anda kullanılabilen kapsamlar ve katılımcı referansının erişilebilirliği anahtara girer: daha sonraki bir
        # anın "doğrulandı" sonucu daha önceki bir an için önbellekten kullanılmaz
        usable = tuple(sorted((c.sha256, bool(c.verified_windows)) for c in self.coverages_at(league, as_of)))
        key = (self.fingerprint, MATCHING_VERSION, league, str(pd.Timestamp(date).date()), home, away, bool(mapped),
               raw_home, raw_away, source, pcodes, markets, cut, live, usable, event_id)
        hit = self._cache.get(key)
        if hit is None:
            hit = self._evaluate(league, date, home, away, as_of, cut, live, markets, source, mapped, raw_home,
                                 raw_away, pcodes, event_id)
            self._cache[key] = hit
        stamp = as_of.astimezone(dt.timezone.utc).isoformat()
        return {mk: _restamp(e, stamp) for mk, e in hit.items()}

    def _live(self, as_of: dt.datetime) -> bool:
        """Durumun değerlendirme anından önce var olduğu biliniyor mu (o zaman içindeki bilgi o anda vardı)."""
        av = self.state.available_since if self.state is not None else None
        return av is not None and as_of >= av

    def _evaluate(self, league, date, home, away, as_of, cut, live, markets, source, mapped, raw_home, raw_away,
                  pcodes, eid):
        from .goals.ledger import event_id as make_event_id

        cut_day = day_number(cut)
        fx_day = day_number(date)
        kind = self.state.kind if self.state else None
        codes: list[str] = []
        detail: dict = {}
        if eid is None:
            eid = (make_event_id(league, pd.Timestamp(date).date(), home, away) if mapped
                   else candidate_id(source, league, date, raw_home or home, raw_away or away))
        g_all = self.league_matches(league)
        g = g_all[g_all["day"] < cut_day]  # bilgi kesiminden ÖNCE erişilebilir sonuçlar
        labels = sorted(set(g["source"].dropna().astype(str)))
        unlabeled = bool(g["source"].isna().any())  # kaynağı kayıtsız satır: hakkı bilinemez
        # Model eğitim verisinin kaynakları: model dosyasında kayıtlıysa o; değilse (eski model dosyası) depodaki bütün
        # kaynaklar ihtiyatla denetlenir ve ayrıca MODEL_EGITIM_KOKENI_YOK engeli konur (köken bilgisi uydurulmaz)
        provenance = self.state is not None and bool(self.state.train_sources)  # boş küme = köken bilinmiyor
        train = (sorted(self.state.train_sources) if provenance
                 else sorted(set(self.matches["source"].dropna().astype(str))))
        base = dict(candidate_id=eid, canonical_id=bool(mapped), league=league, home=home, away=away,
                    match_date=str(pd.Timestamp(date).date()), evaluated_at="", info_cutoff=str(cut),
                    team_mapping="ESLESTI" if mapped else "ESLESMEDI",
                    data_cutoff=str(day_to_date(int(g["day"].max()))) if len(g) else None,
                    data_scope={"lig_mac_sayisi": int(len(g)), "kaynaklar": labels, "kapsam_kanitlari": [],
                                "depo_ozeti": _digest(g[["day", "home", "away"]].astype(str).values.tolist())[:16]},
                    state_scope=self.state.scope(league, (home, away)) if self.state else {"tur": None},
                    source_use=self.rights.summary(set(labels) | set(train)))
        if fx_day < cut_day:
            codes.append("MAC_GECMISTE")
        if not mapped:
            codes.append("TAKIM_ESLESMEDI")
            return _finalize(base, codes, markets, {}, evidence_checked=False, required_checked=False,
                             mode=self.mode)
        codes += self.rights.codes(labels, train, "tahmin")
        if unlabeled or (not provenance and self.matches["source"].isna().any()):
            codes.append("KAYNAK_HAKKI_BILINMIYOR")
        if self.state is not None and not provenance:
            codes.append("MODEL_EGITIM_KOKENI_YOK")
        # 0) Başka kaynaktan eşlenmiş fikstürün kimliği: aynı kaynak dosyasında güncel eşleyiciyle yeniden kurulmalı
        if home == away:
            codes.append("TAKIM_ESLESMESI_DOGRULANAMADI")
        elif source in MAPPED_FIXTURE_SOURCES:
            fx_date = pd.Timestamp(date).date()
            ok = any(m.date == fx_date and m.home == home and m.away == away
                     for c in self.coverages.get(league, ()) if c.retrieved_at <= as_of and c.source == source
                     for m in c.matches)
            base["team_mapping"] = "ESLESTI" if ok else "DOGRULANAMADI"
            base["data_scope"]["eslesme"] = {"surum": MATCHING_VERSION, "kaynak": source,
                                             "kaynak_takviminde_yeniden_kuruldu": ok}
            if not ok:
                codes.append("TAKIM_ESLESMESI_DOGRULANAMADI")
        # 1) Model durumu ↔ depo (yalnızca modelin işlediği satırlar)
        gi = g[g["ingest"]]
        if self.state is None:
            codes.append("MODEL_YOK")
        else:
            lv = self.state.leagues.get(league)
            if lv is None:
                codes.append("LIG_MODEL_KAPSAMI_DISI")
            else:
                if any(t not in lv.team_last for t in (home, away)):
                    codes.append("TAKIM_DURUMDA_YOK")
                if lv.last_day is not None and lv.last_day >= cut_day and not live:
                    codes.append("DURUM_KARAR_ANINDAN_SONRA")
                behind = int((gi["day"] > (lv.last_day if lv.last_day is not None else -10 ** 9)).sum())
                team_gaps = {}
                for t in (home, away):
                    tg = gi[(gi["home"] == t) | (gi["away"] == t)]
                    known = lv.team_days.get(t, frozenset())
                    since = lv.team_days_from.get(t)
                    days = [int(d) for d in tg["day"] if since is None or int(d) >= since]
                    miss = sorted(d for d in days if d not in known)
                    if miss:
                        team_gaps[t] = [str(day_to_date(d)) for d in miss[-5:]]
                # Durumun kurulduğu maç kümesi ↔ depodaki aynı dönem (modelin işlediği satırlar), birebir
                stale_rows = mismatch = False
                if lv.rows is None:
                    codes.append("DURUM_KOKENI_YOK")
                elif lv.last_day is not None:
                    n_store, sha_store = self._rows(league, lv.last_day)
                    if (n_store, sha_store) != tuple(lv.rows):
                        stale_rows = n_store > lv.rows[0]
                        mismatch = not stale_rows
                        detail["durum_satirlari"] = {"durum": int(lv.rows[0]), "depo": int(n_store)}
                if behind or team_gaps or stale_rows:
                    codes.append("DURUM_DEPODAN_GERIDE")
                    detail["durum_depodan_geride"] = {"lig_mac": behind, "takim": team_gaps}
                if mismatch:
                    codes.append("DURUM_VERIYLE_UYUSMUYOR")
        # Takımın pencere içinde karantinada (modelin kullanmadığı) kaydı: kaynak takviminden bağımsız bilinen eksik
        qg = g[~g["ingest"] & (g["day"] >= cut_day - LOOKBACK_DAYS)]
        bad = {t: [str(day_to_date(int(d))) for d in qg[(qg["home"] == t) | (qg["away"] == t)]["day"]]
               for t in (home, away)}
        bad = {t: v for t, v in bad.items() if v}
        if bad:
            codes.append("DEPODA_GECERSIZ_SKOR")
            detail["gecersiz_skorlu_depo"] = bad
        # Takım geçmişi (depodan; modelden bağımsız yapısal ölçü)
        for t in (home, away):
            n = int((((g["home"] == t) | (g["away"] == t)) & (g["day"] >= cut_day - LOOKBACK_DAYS)).sum())
            if n < MIN_TEAM_MATCHES:
                codes.append("TAKIM_GECMISI_YETERSIZ")
                detail.setdefault("takim_mac_365", {})[t] = n
        # 2) Depo ↔ kaynak takvimi ve kapsam
        covs = self.coverages.get(league, ())
        usable = self.coverages_at(league, as_of)
        evidence = [c for c in usable if c.verified_windows]  # (B) kanıtla tam olduğu bilinen aralığı olan takvimler
        evidence_checked = bool(evidence)
        if not covs:
            codes.append("KAYNAK_KAPSAMI_YOK")
        elif not usable:
            codes.append("KAYNAK_KARAR_ANINDAN_SONRA")
        elif not evidence:
            codes.append("KAYNAK_KAPSAMI_KISMI")
        for c in usable:
            base["data_scope"]["kapsam_kanitlari"].append({
                "kaynak": c.source, "sezon": c.season, "alinma": c.retrieved_at.isoformat(),
                "tam": c.complete,  # (A) tam sezon takvimi; geriye uyumlu anahtar
                "gecmis_aralik_kaniti": [[str(day_to_date(s)), str(day_to_date(e))] for s, e in c.verified_windows],
                "bagimsiz_katilimci": c.participants, "eslesme_surumu": c.matching_version or None,
                "katilimci_erisilebilir": c.participants_since.isoformat() if c.participants_since else None,
                "depo_ayni_kaynak_zinciri": bool(set(labels) & COVERAGE_CHAIN_LABELS.get(c.source, frozenset())),
                "aciklama": c.detail, "ozet": c.sha256[:16]})
        near = g_all[g_all["day"] < cut_day + PAIR_DAY_TOLERANCE]  # aynı maçın yerel tarih farkı (sınırda da)
        partial = [c for c in usable if not c.verified_windows]
        if partial:  # kısmi takvim "eksik yok" kanıtı olamaz ama bilinen eksiği gösterebilir
            self._missing_in_partial(home, away, near[near["ingest"]], near, partial, cut_day, codes, detail)
        if evidence:
            self._check_against_source(home, away, near[near["ingest"]], near, evidence, cut_day, codes, detail, base,
                                       PENDING_GRACE_DAYS if self.mode == "standart" else 0)
            self._store_vs_source(home, away, g, evidence, cut_day, codes, detail)
            for t in (home, away):
                if not any(t in (m.home, m.away) for c in evidence for m in c.matches):
                    codes.append("KAYNAK_ESLESME_BELIRSIZ")
                elif not self._window_covered(t, g, usable, evidence, cut_day):
                    codes.append("KAYNAK_ARALIK_DISI")
        # 3) Modelin gerçek girdi bağımlılığı (motorun yapılandırılmış kodlarından; metin aranmaz)
        per_market: dict[str, tuple] = {}
        for mk in markets:
            inputs = MODEL_INPUTS.get(kind or "", {}).get(mk, ("mac_sonu",))
            req = []
            for pc in pcodes or ():
                code, _, only = pc.partition(":")  # "KOD:PAZAR" yalnızca o pazara uygulanır
                if only and only != mk:
                    continue
                hit = PREDICTION_CODE_MAP.get(code)
                if hit and (hit[1] is None or hit[1] in inputs):
                    req.append(hit[0])
            per_market[mk] = tuple(req)
        base["data_scope"]["ayrinti"] = detail
        return _finalize(base, codes, markets, per_market, evidence_checked, required_checked=pcodes is not None,
                         mode=self.mode)

    @staticmethod
    def _check_against_source(home, away, g_pair, g_any, complete, cut_day, codes, detail, base,
                              pending_days: int = 0) -> None:
        """Kaynakta beklenen maçlar ↔ depodaki maçlar (takım düzeyi ve paylaşılan lig durumu).

        ``pending_days`` (yalnızca standart mod): bilgi kesiminden önceki son bu kadar günde sonucu henüz hiçbir yerde
        olmayan maçlar belirsiz sayılmaz, ``SON_SONUC_BEKLENIYOR`` olur (olağan yayın gecikmesi). 0 = v2 davranışı.

        ``g_pair``: modelin işlediği depo satırları (eşleştirme; bilgi kesimi + tarih toleransı); ``g_any``: aynı aralıkta
        karantinadakiler dahil bütün satırlar (geçersiz skorlu kaydı "yok" yerine ayrıca adlandırmak için)."""
        def pairs(df):
            out: dict[tuple, list[int]] = {}
            for h, a, d in zip(df["home"], df["away"], df["day"]):
                out.setdefault((h, a), []).append(int(d))
            return out

        ok_days, any_days = pairs(g_pair), pairs(g_any)

        def found(idx, m: ScheduledMatch) -> bool:
            md = day_number(m.date)
            return any(abs(d - md) <= PAIR_DAY_TOLERANCE for d in idx.get((m.home, m.away), ()))

        team_missing: dict[str, list[str]] = {}
        team_invalid: dict[str, list[str]] = {}
        team_unknown: dict[str, list[str]] = {}
        team_pending: dict[str, list[str]] = {}
        team_unmapped: dict[str, list[str]] = {}
        league: dict[str, dict[str, int]] = {}  # sezon -> pencere içindeki diğer-takım sayımları
        unmapped: set[str] = set()
        checked = {"takimlar": [home, away], "donem_sonu": str(day_to_date(cut_day - 1)), "kaynak_sezonlari": []}
        for c in complete:
            unmapped |= set(c.unmapped_names)
            checked["kaynak_sezonlari"].append(c.season)
            cnt = league.setdefault(c.season, {"gecmis": 0, "eksik": 0, "belirsiz": 0})
            for m in c.matches:
                md = day_number(m.date)
                if md >= cut_day or m.status in NOT_PLAYED_STATUSES:
                    continue  # aynı gün / gelecek veya ertelenen-iptal edilen: eksik tamamlanmış maç sayılmaz
                ours = [t for t in (home, away) if t in (m.home, m.away)]
                in_window = md >= cut_day - LOOKBACK_DAYS  # paylaşılan lig durumu için ilgili dönem
                if not ours and in_window:
                    cnt["gecmis"] += 1
                if m.home is None or m.away is None:
                    # Kaynaktaki takım adı eşleşmedi: depoda olup olmadığı güvenilir biçimde bilinemez (UNKNOWN;
                    # yanlışlıkla "eksik" sayılmaz)
                    for t in ours:
                        team_unmapped.setdefault(t, []).append(str(m.date))
                    if not ours and in_window:
                        cnt["belirsiz"] += 1
                    continue
                if found(ok_days, m):
                    continue
                if m.status == FINISHED:
                    bucket = team_invalid if found(any_days, m) else team_missing
                    for t in ours:
                        bucket.setdefault(t, []).append(str(m.date))
                    if not ours and in_window:
                        cnt["eksik"] += 1
                elif pending_days and md >= cut_day - pending_days:
                    for t in ours:
                        team_pending.setdefault(t, []).append(str(m.date))
                else:
                    for t in ours:
                        team_unknown.setdefault(t, []).append(str(m.date))
                    if not ours and in_window:
                        cnt["belirsiz"] += 1
        checked.update({"eksik_tamamlanmis": {t: len(v) for t, v in team_missing.items()},
                        "gecersiz_skorlu": {t: len(v) for t, v in team_invalid.items()},
                        "sonucu_belirsiz": {t: len(v) for t, v in team_unknown.items()}})
        base["data_scope"]["kontrol"] = checked
        if team_missing:
            codes.append("DEPODA_EKSIK_MAC")
            detail["depoda_eksik"] = {t: v[-5:] for t, v in team_missing.items()}
        if team_invalid:
            codes.append("DEPODA_GECERSIZ_SKOR")
            detail["gecersiz_skorlu"] = {t: v[-5:] for t, v in team_invalid.items()}
        if team_unknown:
            codes.append("KAYNAK_DURUMU_BELIRSIZ")
            detail["sonucu_belirsiz"] = {t: v[-5:] for t, v in team_unknown.items()}
        if team_pending:
            codes.append("SON_SONUC_BEKLENIYOR")
            detail["sonucu_bekleniyor"] = {t: v[-5:] for t, v in team_pending.items()}
        if team_unmapped:
            codes.append("KAYNAK_ESLESME_BELIRSIZ")
            detail["rakip_adi_eslesmeyen"] = {t: v[-5:] for t, v in team_unmapped.items()}
        # Lig düzeyi: oran her kaynak sezonu için AYRI ve yalnızca son 365 gün içinde hesaplanır; ek sezon kanıtı
        # yalnızca engel ekleyebilir, mevcut engeli seyreltemez.
        # Küçük paydada (sezon başı, pencere kuyruğu) tek maç bütün ligi engellemesin: sınır en az 1 maç.
        partial = False
        for cnt in league.values():
            if not cnt["gecmis"]:
                continue
            limit = max(1.0, LEAGUE_MISSING_SHARE * cnt["gecmis"])
            if cnt["eksik"] > limit:
                codes.append("LIG_DURUMU_EKSIK")
            elif cnt["eksik"]:
                partial = True
            if cnt["belirsiz"] > limit:
                codes.append("LIG_DURUMU_BELIRSIZ")
        if partial and "LIG_DURUMU_EKSIK" not in codes:
            codes.append("LIG_DURUMU_KISMEN_EKSIK")
        detail["lig_duzeyi"] = league
        if unmapped:
            codes.append("KAYNAK_ESLESMEMIS_ADLAR")
            detail["eslesmeyen_kaynak_adi_sayisi"] = len(unmapped)

    @staticmethod
    def _missing_in_partial(home, away, g_pair, g_any, partial, cut_day, codes, detail) -> None:
        """Tamlığı kanıtlanmamış (kısmi) takvimden yalnızca BİLİNEN eksik: kaynakta tamamlanmış, kesin kimlikle eşlenmiş
        ve depoda olmayan maç. "Eksik yok" iddiası ve sayım özeti üretilmez."""
        def idx(df):
            out: dict[tuple, list[int]] = {}
            for h, a, d in zip(df["home"], df["away"], df["day"]):
                out.setdefault((h, a), []).append(int(d))
            return out

        ok_days, any_days = idx(g_pair), idx(g_any)
        missing: dict[str, list[str]] = {}
        invalid: dict[str, list[str]] = {}
        for c in partial:
            for m in c.matches:
                md = day_number(m.date)
                if md >= cut_day or m.status != FINISHED or m.home is None or m.away is None:
                    continue
                ours = [t for t in (home, away) if t in (m.home, m.away)]
                if not ours or any(abs(d - md) <= PAIR_DAY_TOLERANCE for d in ok_days.get((m.home, m.away), ())):
                    continue
                bucket = invalid if any(abs(d - md) <= PAIR_DAY_TOLERANCE
                                        for d in any_days.get((m.home, m.away), ())) else missing
                for t in ours:
                    bucket.setdefault(t, []).append(str(m.date))
        if missing:
            codes.append("DEPODA_EKSIK_MAC")
            detail["kismi_takvimde_depoda_eksik"] = {t: v[-5:] for t, v in missing.items()}
        if invalid:
            codes.append("DEPODA_GECERSIZ_SKOR")
            detail["kismi_takvimde_gecersiz_skorlu"] = {t: v[-5:] for t, v in invalid.items()}

    @staticmethod
    def _store_vs_source(home, away, g, evidence, cut_day, codes, detail) -> None:
        """Ters yön: doğrulanmış takvim aralığında depoda olan maç kaynakta da olmalı (bağımsız iki sağlayıcı)."""
        idx: dict[tuple, list[int]] = {}
        for c in evidence:
            for m in c.matches:
                if m.home is not None and m.away is not None:
                    idx.setdefault((m.home, m.away), []).append(day_number(m.date))
        wins = [(s, min(e, cut_day - 1)) for c in evidence for s, e in c.verified_windows]
        extra: dict[str, list[str]] = {}
        for t in (home, away):
            tg = g[(g["home"] == t) | (g["away"] == t)]
            for h, a, d in zip(tg["home"], tg["away"], tg["day"]):
                d = int(d)
                if not any(s <= d <= e for s, e in wins):
                    continue
                if not any(abs(x - d) <= PAIR_DAY_TOLERANCE for x in idx.get((h, a), ())):
                    extra.setdefault(t, []).append(str(day_to_date(d)))
        if extra:
            codes.append("KAYNAK_DEPO_CELISKISI")
            detail["kaynakta_olmayan_depo_maci"] = {t: v[-5:] for t, v in extra.items()}

    @staticmethod
    def _window_covered(team: str, g: pd.DataFrame, usable: list, evidence: list, cut_day: int) -> bool:
        """Takımın gerekli pencere aralığı (B) kanıtla kapsanıyor mu?

        Yalnızca kaynak takviminin bağımsız katılımcılarla doğrulanmış aralıkları sayılır (veri deposunun kendi iç
        tutarlılığı kapsam kanıtı değildir: takım sayısı depodan çıkarılırsa eksik takım/alt küme görünmez). Ardışık
        sezonlar arasındaki ara, önceki sezonun listelenen takvimi sonuna kadar doğrulandıysa ve arada (bilgi
        kesiminden önce) ne depoda ne kaynakta maç yoksa kapsanır; yeni sezonun takvimi bilgi kesiminden önce maç
        göstermiyorsa (sezon başlamadı) ara bilgi kesimine kadar kapsanır."""
        # Pencerenin başı depodaki ilk maçtan alınmaz (eksik önceki sezonlar pencereyi kısaltamaz): her zaman 365 gün.
        # Ligde yeni olan takımın önceki dönemi, takımın yer almadığı doğrulanmış lig takvimiyle kapsanır.
        w0 = cut_day - LOOKBACK_DAYS
        w1 = cut_day - 1
        iv = sorted(((s, e, c) for c in evidence for s, e in c.verified_windows), key=lambda x: (x[0], x[1]))
        if not iv:
            return False
        store_days = g["day"].astype(int).to_numpy()
        source_days = [day_number(m.date) for c in usable for m in c.matches]

        def gap_empty(a: int, b: int) -> bool:
            b = min(b, cut_day - 1)  # bilgi kesiminden sonrası bilinemez ve pencereye girmez
            if a > b:
                return True
            return not ((store_days >= a) & (store_days <= b)).any() and not any(a <= d <= b for d in source_days)

        def final(c, e) -> bool:
            return c.season_end_verified and e == max(we for _, we in c.verified_windows)

        def not_started(c) -> bool:
            days = [day_number(m.date) for m in c.matches]
            return (bool(days) and min(days) >= cut_day and any(round_number(m.round) == 1 for m in c.matches)
                    and any(team in (m.home, m.away) for m in c.matches))

        merged: list[list] = []
        for s, e, c in iv:
            if merged:
                ps, pe, pc = merged[-1]
                if s <= pe + 1 or (_next_season(pc.season) == c.season and final(pc, pe) and gap_empty(pe + 1, s - 1)):
                    merged[-1] = [ps, max(pe, e), c if e >= pe else pc]
                    continue
            merged.append([s, e, c])
        for item in merged:  # sezon henüz başlamadı: önceki sezon sonundan bilgi kesimine kadar
            ps, pe, pc = item
            if pe < w1 and final(pc, pe) and gap_empty(pe + 1, w1) and any(
                    c.season == _next_season(pc.season) and not_started(c) for c in usable):
                item[1] = w1
        return any(s <= w0 and e >= w1 for s, e, _ in merged)

def _next_season(season: str) -> str:
    s = str(season)
    try:
        if "/" in s:
            y = int(s.split("/")[0]) + 1
            return f"{y}/{(y + 1) % 100:02d}"
        if "-" in s:
            y = int(s.split("-")[0]) + 1
            return f"{y}/{(y + 1) % 100:02d}"
        if s.isdigit():
            return str(int(s) + 1)
    except ValueError:
        return ""
    return ""


def _restamp(e: Eligibility, stamp: str) -> Eligibility:
    """Önbellekten gelen sonuca gerçek değerlendirme anını yazar (aynı gün, aynı parmak izi)."""
    d = asdict(e)
    d["evaluated_at"] = stamp
    d["reasons"] = tuple(d["reasons"])
    return Eligibility(**d)


def not_evaluated(event_id: str, market: str, as_of: dt.datetime | None = None,
                  canonical: bool | None = None) -> Eligibility:
    """Bağlam verilmediğinde kullanılan sonuç: uygun değil (``BAGLAM_YOK``)."""
    now = as_of or dt.datetime.now(dt.timezone.utc)
    canonical = (not str(event_id).startswith("aday:")) if canonical is None else bool(canonical)
    base = dict(candidate_id=event_id, canonical_id=canonical, league="", home="", away="", match_date="",
                evaluated_at=now.astimezone(dt.timezone.utc).isoformat(), info_cutoff=str(info_cutoff(now)),
                data_cutoff=None, data_scope={}, state_scope={}, source_use={}, team_mapping="KONTROL_EDILMEDI")
    return _finalize(base, ["BAGLAM_YOK"], (market,), {}, evidence_checked=False, required_checked=False)[market]


def _context_mismatch(e, event_id: str, market: str, at: dt.datetime, state_digest: str | None) -> list[str]:
    """Sonuç bu maç, pazar, gün, politika ve model durumu için mi (ve ``at`` anından önce mi) üretildi?"""
    if not isinstance(e, Eligibility) or "BAGLAM_YOK" in e.reasons:
        return ["BAGLAM_YOK"]
    if (e.candidate_id != event_id or e.market != market
            or e.policy_version != POLICY_VERSIONS.get(getattr(e, "policy_mode", "siki"))
            or e.as_of_day != info_cutoff(at)):
        return ["BAGLAM_UYUSMUYOR"]
    try:  # o andan SONRA değerlendirilmiş sonuç o anın kanıtı olamaz
        if dt.datetime.fromisoformat(e.evaluated_at) > at + dt.timedelta(seconds=1):
            return ["BAGLAM_UYUSMUYOR"]
    except (TypeError, ValueError):
        return ["BAGLAM_UYUSMUYOR"]
    if state_digest is not None and e.state_digest != state_digest:
        return ["BAGLAM_UYUSMUYOR"]
    return []


def check_for_decision(e, event_id: str, market: str, decision_time: dt.datetime,
                       state_digest: str | None = None) -> list[str]:
    """Karar motorunun denetimi. Boş liste = veri açısından bahis adayına engel yok. Bağlam yoksa, başka maça/
    pazara/güne/model durumuna aitse ya da veri bahis için uygun değilse engel kodları döner."""
    mismatch = _context_mismatch(e, event_id, market, decision_time, state_digest)
    if mismatch:
        return mismatch
    if not e.bet_ok:
        return [c for c in e.reasons if code_level(c, e.policy_mode) != "yok"] or ["BAGLAM_YOK"]
    return []


def check_for_display(e, event_id: str, market: str, now: dt.datetime, state_digest: str | None = None) -> list[str]:
    """Gösterim denetimi: olasılık ancak sonuç BUGÜN (bilgi kesimi günü), bu maç/pazar ve bu model durumu için
    üretilmiş ve tahmine izin veriyorsa gösterilir. Boş liste = gösterilebilir. Gün değişince eski sonuç kullanılmaz."""
    mismatch = _context_mismatch(e, event_id, market, now, state_digest)
    if mismatch:
        return mismatch
    if not e.forecast_ok:
        return forecast_block_codes(e)
    return []


def forecast_block_codes(e) -> list[str]:
    """Tahmini engelleyen kodlar (sonucun kendi veri denetimi moduna göre); hiçbiri yoksa ``BAGLAM_YOK``."""
    mode = getattr(e, "policy_mode", "siki")
    return [c for c in e.reasons if code_level(c, mode) == "tahmin"] or ["BAGLAM_YOK"]


# Etiketlerde kodun yanında gösterilen kısa Türkçe açıklama (ayrıntı metni ve gereken düzeltme ``REASONS``'ta)
SHORT_TEXT = {
    "BAGLAM_YOK": "uygunluk değerlendirilmedi", "BAGLAM_UYUSMUYOR": "sonuç başka güne veya modele ait",
    "MAC_GECMISTE": "maç tarihi geçti", "MODEL_YOK": "model eğitilmedi", "LIG_MODEL_KAPSAMI_DISI": "lig modelde yok",
    "TAKIM_ESLESMEDI": "takım adı eşleşmedi", "TAKIM_ESLESMESI_DOGRULANAMADI": "takım kimliği doğrulanamadı",
    "TAKIM_DURUMDA_YOK": "takım modelde yok", "DURUM_KARAR_ANINDAN_SONRA": "model sonraki maçları içeriyor",
    "DURUM_DEPODAN_GERIDE": "model veriden eski", "DEPODA_EKSIK_MAC": "veride eksik maç var",
    "DEPODA_GECERSIZ_SKOR": "geçersiz skorlu maç", "DURUM_KOKENI_YOK": "eski model dosyası",
    "DURUM_VERIYLE_UYUSMUYOR": "model farklı veriyle eğitilmiş", "LIG_DURUMU_EKSIK": "ligde çok maç eksik",
    "LIG_DURUMU_KISMEN_EKSIK": "ligde az sayıda maç eksik", "LIG_DURUMU_BELIRSIZ": "ligde sonucu bilinmeyen maçlar",
    "KAYNAK_KAPSAMI_YOK": "güncellik takvimi yok", "KAYNAK_KAPSAMI_KISMI": "güncellik takvimi eksik",
    "KAYNAK_KARAR_ANINDAN_SONRA": "takvim sonradan alınmış", "KAYNAK_ARALIK_DISI": "geçmiş dönem doğrulanamadı",
    "KAYNAK_DURUMU_BELIRSIZ": "son maç sonucu bilinmiyor", "SON_SONUC_BEKLENIYOR": "son maç sonucu bekleniyor",
    "KAYNAK_ESLESME_BELIRSIZ": "takvimde eşleşme belirsiz", "KAYNAK_DEPO_CELISKISI": "kaynaklar çelişiyor",
    "KAYNAK_ESLESMEMIS_ADLAR": "takvimde eşleşmeyen adlar", "GEREKLI_ALAN_EKSIK": "gerekli veri yok",
    "TAKIM_GECMISI_YETERSIZ": "takımın bu ligde az maçı var", "LIG_IY_ORANI_DUSUK": "ligde ilk yarı verisi az",
    "KAYNAK_ERISIM_IZNI_YOK": "kaynak onayı yok", "KAYNAK_HAKKI_BILINMIYOR": "kaynak kayıtlı değil",
    "KAYNAK_ETIKETI_UYUMSUZ": "kaynak etiketi uyumsuz", "KAYNAK_KOKENI_DOGRULANAMADI": "veri kökeni doğrulanamadı",
    "KAYNAK_SONUC_KULLANIMI_DOGRULANAMADI": "kullanım beyanı yok", "KAYNAK_EGITIM_HAKKI_DOGRULANAMADI": "kullanım beyanı yok",
    "KAYNAK_MODEL_KULLANIMI_DOGRULANAMADI": "kullanım beyanı yok", "MODEL_EGITIM_KOKENI_YOK": "modelin veri kökeni yok",
    "OLASILIK_GECERSIZ": "geçersiz olasılık",
}
assert set(SHORT_TEXT) == set(REASONS)


def _short(code) -> str:
    return f"{SHORT_TEXT.get(code, code)} ({code})" if code else ""


def display_label(e, codes) -> tuple[str, str]:
    """(kısa durum, ayrıntı metni). Renkten bağımsız: Kullanılabilir / Uyarılı / Doğrulanamıyor / Eksik veri / Uygun
    değil; ardından kısa Türkçe neden ve kodu."""
    if e is None or (codes and codes[0] in ("BAGLAM_YOK", "BAGLAM_UYUSMUYOR")):
        code = codes[0] if codes else "BAGLAM_YOK"
        return f"Doğrulanamıyor · {_short(code)}", f"{REASONS[code].text} [{code}] Gereken: {REASONS[code].fix}"
    if codes:
        return f"{e.status_label} · {_short(e.lead_code)}", e.short_text()
    if not e.bet_ok:
        return f"{e.status_label} · bahis adayı değil: {_short(e.lead_code)}", e.short_text()
    return e.status_label, e.short_text()


def valid_probability(p) -> bool:
    if p is None or isinstance(p, bool):
        return False
    try:
        f = float(p)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and 0.0 <= f <= 1.0


def finite_or_none(v):
    """Kamuya açık JSON/CSV için: NaN/sonsuz değerler None olur (sıfır olarak doldurulmaz)."""
    if v is None or isinstance(v, bool):
        return v
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def reason_texts(codes) -> str:
    return "; ".join(f"{c}: {REASONS[c].text}" for c in codes if c in REASONS)


# ----------------------------------------------------------------------------
# Uygulama ve CLI için: önbellekteki kaynak dosyalarından kapsam (ağ isteği yok)
# ----------------------------------------------------------------------------

def cached_coverages(raw_dir, leagues, today: dt.date, known_teams_by_league: dict,
                     participants_by_season: dict | None = None) -> dict:
    """Veri güncellemesinin önbelleğe aldığı openfootball sezon dosyaları (içinde bulunulan ve önceki iki sezon).

    Alınma anı dosyanın değiştirilme zamanıdır (güncellemenin dosyayı yazdığı an). ``participants_by_season``:
    (lig, sezon) -> o sezonun bağımsız katılımcıları (veri deposu); yoksa takvim tamlığı kanıtlanmaz."""
    from pathlib import Path

    from .data.leagues import LEAGUES, openfootball_season

    out: dict[str, list[SourceCoverage]] = {}
    for code in leagues:
        lg = LEAGUES.get(code)
        if lg is None or not lg.openfootball:
            continue
        # 365 günlük pencere sezon arasında üç sezona dokunabilir (yalnızca önbellekteki dosyalar; indirme yok)
        for season in sorted({openfootball_season(today - dt.timedelta(days=d), lg.calendar_year)
                              for d in (0, 365, 730)}):
            path = Path(raw_dir) / "openfootball" / season / f"{lg.openfootball}.json"
            if not path.is_file():
                continue
            at = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
            label = _norm_season(season, lg.calendar_year)
            out.setdefault(code, []).append(coverage_from_openfootball(
                path.read_bytes(), code, label, at, known_teams_by_league.get(code, ()),
                (participants_by_season or {}).get((code, label))))
    return out


def _norm_season(season: str, calendar_year: bool) -> str:
    """openfootball "2026-27" -> depo etiketi "2026/27" (takvim yılı ligleri aynen)."""
    if calendar_year or "-" not in season:
        return season
    y = int(season.split("-")[0])
    return f"{y}/{(y + 1) % 100:02d}"


def season_participants(matches: pd.DataFrame | None) -> dict:
    """(lig, sezon) -> veri deposunda o sezonda maçı olan takımlar: kaynak takviminin BAĞIMSIZ katılımcı listesi
    (başka sağlayıcı). Bir takımın açılış maçı henüz depoda yoksa liste eksik kalır ve takvim tamlığı kanıtlanmaz."""
    if matches is None or matches.empty or "season" not in matches:
        return {}
    m = matches.dropna(subset=["season"])
    out: dict = {}
    for (lg, season), g in m.groupby([m["league"], m["season"].astype(str)]):
        out[(lg, season)] = frozenset(g["home"]) | frozenset(g["away"])
    return out


def build_context(store, engine, consent: dict | None, today: dt.date | None = None,
                  participants: dict | None = None, *, declarations: dict | None = None,
                  mode: str = "siki") -> EligibilityContext:
    """Uygulama/CLI için bağlam: veri deposu + motorun durumu + önbellekteki kaynak takvimleri + kayıtlı haklar.

    ``participants``: (lig, sezon) -> bağımsız katılımcılar (depo adlarıyla). Verilmezse depodan türetilir; kapsam
    kaynağıyla aynı veri zincirinden gelen satırlar (``COVERAGE_CHAIN_LABELS``) bağımsız sayılmaz ve dışarıda kalır.
    Sonuç satırlarının kökeni ``data.provenance`` ile doğrulanır (ağ isteği yok)."""
    from .data.provenance import verified_labels

    today = today or dt.datetime.now(ISTANBUL).date()
    matches = getattr(store, "matches", None)
    sv = state_view(engine)
    leagues = sorted(set(matches["league"].unique())) if matches is not None and not matches.empty else []
    tmp = EligibilityContext(matches, None, rights=RightsStatus({}))
    known = {lg: tmp.recent_teams(lg) for lg in leagues}
    if participants is None and matches is not None and not matches.empty and "source" in matches:
        chain = COVERAGE_CHAIN_LABELS["openfootball"]
        participants = season_participants(matches[~matches["source"].astype(str).isin(chain)])
    covs = cached_coverages(getattr(store, "raw_dir", "."), leagues, today, known, participants)
    return EligibilityContext(matches, sv, covs, consent=consent, verified_labels=verified_labels(store),
                              declarations=declarations, mode=mode)


@dataclass
class FixtureVerdict:
    """Bir fikstürün pazar başına uygunluğu ve (varsa) tahmini — kullanıcı yollarında ortak kullanım."""
    league: str
    date: pd.Timestamp
    time: str
    home: str
    away: str
    candidate_id: str
    canonical_id: bool
    by_market: dict = field(default_factory=dict)
    prediction: object | None = None

    def get(self, market: str) -> Eligibility | None:
        return self.by_market.get(market)

    @property
    def forecast_ok(self) -> bool:
        return bool(self.by_market) and all(e.forecast_ok for e in self.by_market.values())

    @property
    def any_forecast_ok(self) -> bool:
        return any(e.forecast_ok for e in self.by_market.values())

    def display_codes(self, market: str, now: dt.datetime) -> list[str]:
        """Gösterim engeli (boş = bu anda gösterilebilir): gün, kimlik ve model durumu eşleşmesi dahil."""
        if self.prediction is None:
            e = self.by_market.get(market)
            return forecast_block_codes(e) if e else ["BAGLAM_YOK"]
        digest = getattr(self.prediction, "state_digest", None) or None
        return check_for_display(self.by_market.get(market), self.candidate_id, market, now, digest)

    def usable(self, market: str, now: dt.datetime) -> bool:
        return self.prediction is not None and not self.display_codes(market, now)

    def any_usable(self, now: dt.datetime) -> bool:
        return any(self.usable(mk, now) for mk in self.by_market)

    def all_usable(self, now: dt.datetime) -> bool:
        return bool(self.by_market) and all(self.usable(mk, now) for mk in self.by_market)

    def first(self) -> Eligibility | None:
        return next(iter(self.by_market.values()), None)


# ----------------------------------------------------------------------------
# 1X2 (maç sonucu) motoru için ince bağlayıcı: aynı merkezi değerlendirme
# ----------------------------------------------------------------------------

def gate_match_prediction(ctx: EligibilityContext | None, pred, as_of: dt.datetime) -> Eligibility:
    """1X2 tahminine uygunluk sonucunu bağlar (``pred.eligibility``) ve döndürür."""
    eid = pred.event_id
    if ctx is None:
        e = not_evaluated(eid, "1X2", as_of, canonical=True)
    else:
        ok = bool(np.all(np.isfinite(np.asarray(pred.p_final, dtype=float))))
        codes = () if ok else ("OLASILIK_GECERSIZ:1X2",)
        e = ctx.evaluate(league=pred.league, date=pred.date, home=pred.home, away=pred.away, as_of=as_of,
                         markets=MATCH_MARKETS, source=pred.source or "", prediction_codes=codes, event_id=eid)["1X2"]
    pred.eligibility = e
    return e


def gated_match_predictions(engine, ctx: EligibilityContext | None, fixtures: pd.DataFrame | None,
                            as_of: dt.datetime, odds_type: str = "avg", unmatched: pd.DataFrame | None = None):
    """Toplu 1X2 tahmini: (uygunluğu bağlanmış tahminler, tahmini olmayan fikstürlerin nedenli sonuçları)."""
    from .goals.ledger import event_id

    fx = fixtures if fixtures is not None else pd.DataFrame()
    preds = engine.predict_fixtures(fx, odds_type) if (engine is not None and engine.trained and not fx.empty) else []
    for p in preds:
        gate_match_prediction(ctx, p, as_of)
    have = {p.event_id for p in preds}
    missing: list[FixtureVerdict] = []
    rows = [(r, True) for r in fx.itertuples(index=False)]
    rows += [(r, False) for r in (unmatched if unmatched is not None else pd.DataFrame()).itertuples(index=False)]
    for r, mapped in rows:
        home = r.home if mapped else r.raw_home
        away = r.away if mapped else r.raw_away
        src = getattr(r, "source", "") or ""
        eid = event_id(r.league, r.date, home, away) if mapped else candidate_id(src, r.league, r.date, home, away)
        if mapped and eid in have:
            continue
        if ctx is None:
            by = {"1X2": not_evaluated(eid, "1X2", as_of, canonical=mapped)}
        else:
            by = ctx.evaluate(league=r.league, date=r.date, home=home, away=away, as_of=as_of, markets=MATCH_MARKETS,
                              source=src, mapped=mapped, raw_home=None if mapped else home,
                              raw_away=None if mapped else away, prediction_codes=None, event_id=eid)
        missing.append(FixtureVerdict(league=r.league, date=pd.Timestamp(r.date), time=getattr(r, "time", "") or "",
                                      home=home, away=away, candidate_id=eid, canonical_id=mapped, by_market=by))
    return preds, missing
