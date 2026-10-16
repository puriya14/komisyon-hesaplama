# DISIPLIN-07: Bahis disiplini

İstek: "7'yi de yap ve rövanş etkisini uygula". Önerilen fikirlerden 7.si:

> **Bahis disiplini.** Sabit küçük pay ya da kesirli Kelly, aynı maçta birbirine bağlı bahislerden kaçınma ve gerçek
> parayla başlamadan önce yeterli sayıda sanal takip kaydı.

**Kısa sonuç:**

- **Portföy kuralları artık defter düzeyinde.** Aynı maça ikinci sanal bahis konmuyor. Maç günü ve lig-gün sınırları
  önceki kayıtlarla birlikte sayılıyor.
- **Stake yöntemi seçilebiliyor:** sabit küçük pay (varsayılan) veya kesirli Kelly.
- **Gerçek para hazırlık ölçütü önceden yazıldı** (`hazirlik-v1`). Masaüstü, web ve `gol-sanal` hangi koşulların
  sağlandığını gösteriyor. Ölçüt hiçbir defterde çalıştırılmadan yazıldı ve parmak iziyle sabitlendi.
- Kullanıcının sanal takip defteri bu çalışma ortamında yok. Kendi defterinizdeki sonucu Gol Pazarları → Sanal takip
  sekmesinde, Ayarlar'da ya da `python -m bahis_tahmin gol-sanal` ile görürsünüz.

Kod: `bahis_tahmin/goals/disiplin.py`, kayıt `goals/service.py::record_decisions`.

## Neden gerekliydi

- **Aynı maçtaki pazarlar birbirine bağlı.** "İki yarıda da karşılıklı gol" gerçekleşirse maçta en az 4 gol olur
  (3,5 Üst) ve ilk yarıda en az 2 gol olur (İY 1,5 Üst). Aynı maçta iki bahis çeşitlendirme değil, aynı olaya iki kez
  oynamaktır.
- **Önceki eksik.** Karar motoru (`apply_concentration`) aynı maçta tek aday, günde 10 ve lig-günde 3 sınırını
  yalnızca tek bir kayıt işlemi içinde uyguluyordu.
  - Aynı maç sonradan yeniden kaydedilince (ör. oran değişince) ikinci sanal bahis eklenebiliyordu.
  - Gün sınırı, o gün daha önce kaydedilmiş bahisleri saymıyordu.
- **Stake.** Sanal takip yalnızca sabit 1 birimle çalışıyordu. Kelly seçeneği, modelin olasılık hatasına karşı
  korumasız tam Kelly olmamalı: kesirli olmalı, güvenli olasılık kullanmalı ve tavanlı olmalı.
- **Ne zaman gerçek para?** Bunun için önceden yazılmış bir ölçüt yoktu. Sonuçlara bakarak karar vermek, şanslı bir
  serinin "kanıt" sayılmasına yol açar.

## Ne yapıldı

### 1. Portföy kuralları (kayıt anında, defterdeki önceki kayıtlarla)

Bir avantaj adayı ancak şu koşullarda sanal stake alır. Önceki koşullar aynen geçerli: veri uygunluğu ve kayıt anında
kararın hâlâ geçerli olması.

- Defterde **bu maçta** stake'i olan bir sanal bahis yok. Aynı işlemdeki ilk aday stake alır, sonrakiler almaz.
- **Bu maç gününde** en fazla 10 sanal bahis var.
- **Aynı lig ve maç gününde** en fazla 3 sanal bahis var.

Sınırlar karar politikasıyla (`DecisionPolicy`) aynı sayılar. Engellenen aday karar kaydı olarak yazılır:

- stake 0, tür `KARAR_KAYDI`;
- gerekçesi, ör. "Bu maçta zaten sanal bahis kayıtlı …";
- karar durumu (`VALUE_CANDIDATE`) değişmez.

Yeni kayıtlarda `mac_gunu` ve `disiplin_version` (`disiplin-v1`) alanları var. Eski kayıtların maç günü, başlama
zamanının tarih kısmından okunur.

### 2. Stake yöntemi (Ayarlar → Bahis disiplini)

| Yöntem | Stake | Strateji sürümü (kayıtta) |
|---|---|---|
| Sabit küçük pay (varsayılan) | 1 birim = 100 birimlik başlangıç sanal kasasının %1'i | `sanal-sabit-birim-v1` (önceki kayıtlarla aynı) |
| Kesirli Kelly | sanal kasa × min(kesir × f*, tavan); f* = (p_safe·oran − 1)/(oran − 1) | `sanal-kesirli-kelly-v1 (kesir …, tavan …)` |

- **p_safe:** belirsizlik aralığının güvenli ucu (kararda beklenen değer eşiği için zaten kullanılan olasılık). Model
  olasılığı değil: modelin hatasına karşı ilk tampon.
- **Kesir ve tavan:** Ayarlar'daki "Kelly kesri" (varsayılan 0,25 = çeyrek Kelly) ve "Tek bahiste kasanın en fazla"
  (varsayılan 0,05).
- **Sanal kasa:** 100 birim + sonuçlanmış sanal bahislerin neti. Bekleyen bahisler kasadan düşülmez. Kasa tükenirse
  stake konmaz.
- **Kayıtta ayrıca:** `stake_yontemi` ve kayıt anındaki `sanal_kasa`.
- Kayıp sonrası artırma (martingale vb.) yok.

### 3. Gerçek para hazırlık ölçütü (önceden yazılmış)

Ölçüt, kod yazılmadan ve hiçbir defterde çalıştırılmadan yazıldı. Parmak izi: 2026-10-16 01:38:38 UTC, sha256
`c007300ef3b7ded3ce9f32b072ad361933722bdf291577697947236057e42fd5`. Metin kodda `HAZIRLIK_KURALI` olarak durur; test, metnin
parmak iziyle aynı olduğunu ve bu belgede aynen yer aldığını denetler.

```
hazirlik-v1 — gerçek para hazırlık ölçütü (2026-10-16, kod yazılmadan ve hiçbir defterde çalıştırılmadan önce)

Sanal takip defterindeki sanal bahisler (stake > 0, oranlı kayıtlar) üzerinden. Altı koşulun HEPSİ sağlanırsa
"ölçüt karşılandı", aksi halde "ölçüt karşılanmadı" yazılır.

1. Kayıt zinciri sağlam (verify_chain).
2. En az 200 sonuçlanmış (WIN/LOSS) sanal bahis. VOID, PENDING, UNKNOWN sayılmaz.
3. En az 100 sanal bahiste marjsız CLV ölçülmüş (kapanış oranı ve karşı tarafın kapanış oranı girilmiş, zamanlama
   geçerli; ORAN-03 kuralları).
4. Ortalama marjsız CLV'nin %95 alt sınırı > 0 (normal yaklaşım: ortalama − 1,96·sd/√n).
5. Getirinin (yield = net / toplam stake, sonuçlanmış bahisler) %95 üst sınırı > 0. Aralık oran tahmincisiyle:
   yield ± 1,96·√(n/(n−1)·Σ(net_i − yield·stake_i)²)/Σstake_i. Sabit stake'te bahis başına getirinin ortalama aralığıyla
   aynıdır.
6. Sanal kasanın zirveden en büyük düşüşü < %30. Sanal kasa: 100 birim + sonuçlanmış bahislerin karar zamanı
   sırasıyla birikimli neti; düşüş = (zirve − kasa) / zirve, zirve başlangıç kasası dahil.

Ölçüt karşılansa bile kâr garantisi değildir; yalnızca önceden yazılmış asgari kanıttır. Ölçüt değiştirilirse sürüm
artırılır (hazirlik-v2) ve eski sürümün sonucu da gösterilir.
```

**Neden bu koşullar:**

- **Asıl kanıt CLV (koşul 3–4).** Kapanış oranını yenmek, sonuçtan çok daha az gürültülüdür. Bahis başına marjsız CLV'nin
  standart sapması örneğin %6 ise, 100 bahiste ortalamanın %95 aralığının yarı genişliği yaklaşık ±%1,2 olur.
- **Getiri yalnızca "açıkça zararda değil" denetimi (koşul 5).** Sonuçlanan bahislerden getirinin %95 aralığı çok
  geniştir. Alt sınırın sıfırın üstünde olmasını istemek, 200 bahiste %14 civarı getiri istemek demektir; bu gerçekçi
  değil. Bu yüzden yalnızca üst sınırın sıfırın üstünde olması isteniyor.
- **Düşüş (koşul 6):** sabit %1 payla %30'luk düşüş, stake'in ve beklentinin yanlış olabileceğinin işaretidir.
- **Kapanış oranı girilmezse** koşul 3 sağlanamaz. Kapanış oranı Sanal takip → "Kapanış oranı gir (CLV)" ya da
  `gol-kapanis-ekle` / `gol-oran-ice-aktar --kapanis` ile girilir (ORAN-03).

**Getirinin %95 aralığının yarı genişliği** (kâr/zararın stake'e oranı; yalnızca şans, gerçek avantaj 0 iken):

| Sonuçlanan bahis | Oran 1,8 | Oran 2,0 | Oran 2,5 |
|---:|---:|---:|---:|
| 100 | ±%17,5 | ±%19,6 | ±%24,0 |
| 200 | ±%12,4 | ±%13,9 | ±%17,0 |
| 500 | ±%7,8 | ±%8,8 | ±%10,7 |
| 1000 | ±%5,5 | ±%6,2 | ±%7,6 |
| 2000 | ±%3,9 | ±%4,4 | ±%5,4 |

Gerçekçi bir avantaj (%2–5) getiriden ancak binlerce bahiste ayırt edilebilir. 200 bahisten sonra +%10 getiri, şans
olabilir.

### Görünürlük

- **Gol Pazarları → Sanal takip** (masaüstü ve web): özet satırının altında hazırlık ölçütü ve uygulanan disiplin satırı.
  Örnek: "Gerçek para hazırlık ölçütü (hazirlik-v1): karşılanmadı (2/6); gerçek parayla başlamadan önce sanal takibe
  devam edin. kayıt zinciri sağlam (tamam) · sonuçlanan sanal bahis 37/200 (eksik) · …".
- **Ayarlar** (masaüstü ve web): "Bahis disiplini (sanal takip)" bölümü: stake yöntemi ve aynı hazırlık satırı.
- **CLI:** `gol-sanal` hazırlık ve disiplin satırlarını da yazar.

## Bilinen sınırlar

- **Ölçüt asgari kanıttır, kâr garantisi değildir.** Karşılansa bile gerçek parayla sabit küçük payla ve önceden
  belirlenmiş bir kayıp sınırıyla başlamak gerekir. Metin bunu söyler.
- **Yalnızca gol pazarlarının sanal takibi.** Tahminler sayfasındaki (1X2) gerçek para miktarı önerisi ayrı bir
  ayardır ("Gerçek para miktarı önerilerini göster") ve bu ölçüte bağlanmadı. Ölçütün durumu aynı Ayarlar sayfasında
  gösterilir.
- **Kelly'nin p_safe'i modelin kendi belirsizlik aralığından gelir.** Model sistematik olarak yanılıyorsa aralık da
  yanılır. Tavan ve kesir bu yüzden var.
- **Farklı maçlar arasındaki bağımlılık** (aynı gün aynı ligde ortak hava, hakem eğilimi vb.) yalnızca lig-gün
  sınırıyla kabaca sınırlanır.

## Testler

`tests/test_disiplin_07.py` (17 test), `tests/test_web.py` ve `tests/test_ui.py`'de birer test:

- **Ön kayıt:** kural metninin parmak izi, metnin bu belgede aynen bulunması.
- **Portföy:** aynı işlemde ve sonraki işlemde aynı maça ikinci bahis yok, karar durumu değişmez. Avantaj adayı
  olmayan kayıtlar sınırı doldurmaz. Gün ve lig-gün sınırları önceki kayıtlarla sayılır; başka maç günü ayrı. Eski
  kayıtların maç günü başlama zamanından okunur.
- **Stake:** sabit varsayılan, sürüm ve alanlar. Kelly: p_safe ile pay, tavan, kasa küçülünce stake'in küçülmesi; kasa
  tükenince veya olasılık geçersizken 0. Ayardan yöntem seçimi; geçersiz değer sabit'e döner.
- **Hazırlık:** boş defter. Altı koşulun hepsi sağlanınca "KARŞILANDI"; VOID ve bekleyen paydaya girmez. Her koşulun
  tek başına bozulması (199 bahis, 99 CLV, negatif CLV, zarar, tam %30 düşüş). %29 düşüş geçer. Değişken stake'te oran
  tahmincisi ve düşüş hesabı. Bozuk kayıt zinciri.
- **Arayüz:** web ve masaüstü ayarlarda yöntem seçimi ve hazırlık satırı; Sanal takip sekmesinde hazırlık ve disiplin
  satırları.

Mutasyon denetimi: `disiplin.py` ve kayıt fonksiyonunda 31 değişikliğin hepsi yakalandı.
