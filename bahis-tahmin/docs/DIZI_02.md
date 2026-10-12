# DIZI-02 — "Takım-maç tablosu kurulamadı: aynı takımın aynı gün birden fazla maçı var"

## Belirti

Dizi Araştırması sayfası tablo kurulamadığı için boş kalıyordu. Ekranda şu mesaj görünüyordu: "Takım-maç tablosu
kurulamadı: Aynı takımın aynı gün birden fazla maçı var (564); sıra belirsiz". Bu yüzden olay zaman çizgisi, benzer
diziler ve yöntem sekmeleri boştu.

## Neden

Ham veride aynı gün çakışması yok. Bu, yedek veri setindeki 38 ligin 2000'den beri bütün maçlarında denetlendi.

Çakışmayı dizi modülünün takım kimliği kuralı üretiyordu: katman 1, sezon ortası ad ayrılması
(`sequences/aliases.py`). Kural bir lig-sezonda erken ayrılan bir ad ile geç katılan bir adı aynı kulüp sayıyordu.
Ek liglerde (POL, ROU, IRL, DNK, FIN, SWZ, AUT, RUS, CHN) sezon etiketi bazen iki gerçek sezonu kapsıyor. Bu
durumda düşen ve çıkan farklı kulüpler "ad değişikliği" sanıldı (ör. Gornik Zabrze → Wisla, Bray → Derry City).
Eşleme bütün sezonlara uygulandığı için iki kulübün maçları tek takıma yazıldı ve aynı gün iki maç oluştu. Tüm
liglerde onlarca aday bulunuyordu; yalnızca 3'ü gerçekti.

## Düzeltme

Katman 1 adayı iki ek koşulla doğrulanır. İkisi de yalnızca ad, lig ve tarih kullanır; sonuç verisine bakmaz.

1. **Sezon sınırı.** Lig-sezonda erken ayrılan ve geç katılan takım tek olmalı. Birden çok takım birlikte ayrılıp
   katılıyorsa bu bir sezon sınırıdır (düşen ve çıkan kulüpler); aday reddedilir.
2. **Ülke genelinde çelişki.** İki ad ülkenin hiçbir maçında aynı gün oynamamış ve birbirleriyle karşılaşmamış
   olmalıdır. Eşleme zincirleri grup olarak denetlenir.

Ek önlemler:

- Farklı ülkelerde aynı adı taşıyan kulüpler "Ad (Ülke)" olarak ayrı tutulur.
- Hata yine oluşursa (gerçek veri hatası) mesajda örnek takım, lig ve tarih yazılır.
- Reddedilen eşlemeler ve ülkeyle ayrılan adlar sayfanın "Veri ve yöntem" sekmesinde listelenir.

## Sonuç (yedek veri seti, gerçek veri)

| Veri | Önce | Sonra |
|---|---|---|
| 38 lig, 2000+ (238.854 maç) | kurulamadı (1.208 çakışma) | kuruldu; 3 eşleme kabul, 61 aday reddedildi |
| 38 lig, son 11 sezon | kurulamadı | kuruldu; 3 kabul, 50 red |
| Varsayılan 16 lig | kuruluyordu | aynı (3 eşleme, ön-kayıtlı eşleme özeti aynı) |

Ön-kayıtlı araştırma sözleşmesi (`DIZI_ARASTIRMA_SOZLESMESI.md`) ve özeti değişmedi. Varsayılan liglerde kabul edilen
eşlemeler ve eşleme SHA-256'sı aynıdır. Testler `tests/test_dizi_02.py` dosyasında.
