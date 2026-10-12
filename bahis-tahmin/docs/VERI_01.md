# VERI-01 — "Birçok maç için veri bulunamadı" düzeltmesi

## Sorun

"Verileri Güncelle" sonrasında uygulama yaklaşan maçların neredeyse hepsinde olasılık göstermiyordu. Sorun aynı
akışla yeniden üretildi:

- yeni uygulama klasörü;
- football-data.co.uk ve GitHub yedeği için onay;
- varsayılan 16 lig, 10 yıl.

Sonuç: 88 fikstürün **88'i** engelliydi. Ekranda "Eksik veri · MODEL_YOK" ya da "Doğrulanamıyor · TAKIM_ESLESMEDI"
yazıyordu.

Üç ayrı neden üst üste biniyordu.

1. **Model hiç eğitilmiyordu.** football-data.co.uk ve GitHub yedeği için sonuç kullanımı ve model eğitimi hakkı
   kaynak kaydında `DOGRULANAMADI` duruyor. S3-GATE-02'den beri indirme onayı bu hakları kapsamıyordu. Bu yüzden
   "Verileri Güncelle" veriyi indiriyor ama modeli eğitmiyordu, ve bütün maçlar `MODEL_YOK` oluyordu. "Eksik veri"
   etiketi de yanıltıcıydı: etiket başka bir kodun güncelliğinden alınıyor, birincil neden ise MODEL_YOK'tu.
2. **Takım adları eşleşmiyordu.** openfootball fikstür adları (ör. "Coventry City FC", "Real Betis Balompié", "AZ")
   football-data adlarına ("Coventry", "Betis", "AZ Alkmaar") yalnızca küçük bir takma ad tablosuyla eşleniyordu.
   2026-27 dosyalarındaki adların bir bölümü eşleşmedi ve bu maçlar `TAKIM_ESLESMEDI` oldu. Ayrıca eşleşmeyen adlar
   bütün lig takviminin doğrulanmasını da bozuyordu (`KAYNAK_KAPSAMI_KISMI`).
3. **Güncellik denetimi çok katıydı.** Model eğitilse bile bir maçın tahmini ancak güncelliği bağımsız bir sezon
   takvimiyle *kanıtlanırsa* gösteriliyordu. Uygulama yalnızca içinde bulunulan sezonun openfootball dosyasını indirir.
   Birçok ligin (T1, D2, I2, SP2, F2, B1, SC0, G1) 2026-27 dosyası da yok. Sonuç olarak her fikstüre
   `KAYNAK_ARALIK_DISI` / `KAYNAK_KAPSAMI_YOK` düşüyordu. Yeni çıkan takımlar da sezonun ilk aylarında
   `TAKIM_GECMISI_YETERSIZ` ile tamamen engelleniyordu.

## Düzeltmeler

### 1. Kişisel kullanım beyanı

Onay penceresi (Veri › "Kaynak koşulları ve onaylar...") her kaynak için iki ayrı kutu gösterir.

- **1. İndirme onayı** (eskisi gibi).
- **2. Kişisel kullanım beyanı.** Kullanıcı verileri yalnızca kişisel ve ticari olmayan amaçla kullanacağını beyan
  eder: kendi analizi, bu bilgisayarda model eğitimi ve tahmin. Paylaşmaz ve yeniden dağıtmaz. Kaynağın koşulları
  geçerlidir; sorumluluk kullanıcıdadır.

Beyanın kuralları:

- Yalnızca indirme onayı verilmiş kaynakta geçerlidir. Onay geri alınınca beyan da kalkar.
- Yalnızca beyan verilebilen kaynaklarda kullanılabilir (`source_registry.DECLARABLE`: football-data, github-mirror).
- Yalnızca kayıtta `DOGRULANAMADI` olan şu üç alanı açar: `sonuc_kullanimi`, `model_egitimi`, `model_kullanimi`.
  Değerleri `KULLANICI_BEYANI` olur.
- Kaynak kaydı (belge durumu) değişmez. Ticari kullanım, yeniden dağıtım ve erişim koşulları açılmaz.
- `IZIN_VARSAYILMAZ` ve yasak alanlar hiçbir zaman açılmaz.
- Beyan kaynak başınadır. Hem football-data hem yedek veri seti satırları varsa ikisinin de beyanı gerekir.
- Beyan geri alınırsa daha önce eğitilmiş model de hemen kullanılamaz olur (`KAYNAK_MODEL_KULLANIMI_DOGRULANAMADI`).

VERI-01'den önce verilmiş indirme onayı beyan sayılmaz. Bu yüzden onay penceresi bir kez yeniden gösterilir
(`onay_surumu < CONSENT_SCHEMA`). Pencere beyansız kaydedilirse bir daha sorulmaz. Beyan Veri sayfasından verilirse
ve veri olduğu halde model yoksa model hemen eğitilir.

Komut satırı:

```bat
python -m bahis_tahmin update --accept-terms football-data,github-mirror --kisisel-kullanim football-data,github-mirror
python -m bahis_tahmin update --kisisel-kullanim-geri-al github-mirror
```

İleriye dönük ölçüm kaydı (`gol-olcum-kaydet`, protokol v3) ve S4 pilotu beyanı kullanmaz. Bu yollar değişmedi.

### 2. Doğrulanmış takım takma adları

`data/teams.py` dosyasına 135 takma ad eklendi (`_DERIVED_ALIASES`; ülke kapsamlı). Hepsi maç düzeyindeki kanıttan
türetildi:

- openfootball sezon dosyalarındaki (2022-23 … 2026-27) oynanmış maçlar, football-data adlı sonuçlarla eşlendi;
- eşleme koşulu: aynı lig, tarih ±1 gün, aynı MS skoru, ikisinde de varsa aynı İY skoru;
- bir maç yalnızca tek aday kaldığında oy verdi.

Kabul ölçütleri:

- en az 3 tekil maç;
- oyların en az %90'ı tek takımda;
- ev ve deplasman oyları aynı takımda.

Girdilerin çoğu 30-150 maçla %100 uyumludur. Yalnızca mevcut eşleyicinin bulamadığı adlar eklendi ve mevcut
girdilerle çakışma yok.

Yeniden üretimde 2026-27 fikstürlerinin hepsi eşlendi: önce 44/88, sonra 88/88.

Kimlik sözleşmesi (`takim-eslesme-v2`) değişmedi:

- benzerlik veya önek hâlâ yalnızca öneridir;
- takma ad yalnızca kendi ülkesinde ve openfootball kaynağında uygulanır.

Yanlış eşleme riski aynı kalır. Takma ad hedefinin yalnızca yazımı farklı tek karşılığı da kabul edilir (ör. "Nott'm
Forest" / "Nottm Forest").

**Yazım birleştirme** (`data/store.py:unify_spellings`). Yedek veri seti aynı takımı farklı yazımlarla tutuyordu:
"Nottm Forest" / "Nott'm Forest", "MGladbach" / "M'gladbach", "Preussen Munster" / "Preußen Münster". Bu durumda
takımın geçmişi ikiye bölünüyordu.

- Aynı ülkedeki bu yazımlar, en son kullanılan yazıma indirilir.
- Yalnızca büyük/küçük harf, aksan ve noktalama farkı birleştirilir (`teams.spelling_key`; ad parçası atılmaz).
- Kökeni dosyayla doğrulanan satırlara (`openfootball-sonuc`) dokunulmaz.
- football-data fikstür adları da aynı yazıma çevrilir.

### 3. Veri denetimi modu: Standart / Sıkı

Ayarlar › Uygulama › **Veri denetimi**. Varsayılan Standart'tır. Neden kodları ve güncellik sonucu iki modda da
aynıdır; yalnızca kodların engel düzeyi değişir (`eligibility.STANDART_LEVELS`).

| Kod türü | Sıkı (v2, eski davranış) | Standart |
|---|---|---|
| Yapısal: model yok, lig/takım modelde yok, takım eşleşmedi veya kimliği kurulamadı, maç geçmişte, model durumu karar anından sonra, gerekli alan yok, geçersiz olasılık, kullanım hakkı yok (beyan yok), etiket/köken uyumsuz | tahmin yok | tahmin yok |
| Bilinen eksik veya çelişki: depoda eksik maç, geçersiz skor, lig durumu eksik veya belirsiz, sonucu bilinmeyen geçmiş maç, kaynak-depo çelişkisi, eski model durumu; ayrıca az geçmiş (`TAKIM_GECMISI_YETERSIZ`) | tahmin yok | tahmin **"Uyarılı"** gösterilir, bahis adayı / değer önerisi yok |
| Yalnızca kanıt eksikliği: kaynak takvimi yok veya kısmi, geçmiş aralık kanıtlanamadı, kaynak dosyası karar anından sonra alındı | tahmin yok | engel değil; açıklamaya "güncellik bağımsız bir takvimle doğrulanamadı" yazılır |

Standart moddaki etiketler:

- **Kullanılabilir.** Bilinen bir sorun yok. Güncellik kanıtlanamadıysa açıklamada yazar.
- **Uyarılı · bahis adayı değil (KOD).** Tahmin gösterilir; bahis adayı ve değer önerisi yoktur.
- **Uygun değil / Eksik veri / Doğrulanamıyor · KOD.** Tahmin yoktur. Etiket artık birincil nedenin kendi türünü yazar
  (ör. "Uygun değil · MODEL_YOK").

**Neden az geçmiş yalnızca bahsi engelliyor?** Model, lige yeni gelen takımları önbilgiyle küçültür: Elo'da yükselen
takım başlangıcı, Dixon-Coles'ta ridge önbilgisi. Gerçek veride (yedek veri seti, 44.062 maç, zaman sıralı ve örneklem
dışı) ölçüm şöyle:

- **Son 365 günde 10'dan az lig maçı olan takımlar:** model, sabit sıklık tahminini yaklaşık 0,067 nat geçti.
- **Diğer takımlar:** fark yaklaşık 0,079 nat.

Piyasa da bu maçlarda benzer ölçüde zorlanıyor. Tahmin anlamlı, ama belirsizliği daha yüksek. Bu yüzden bahis adayı
olmaz.

Politika sürümleri: sıkı `veri-uygunluk-v2` (değişmedi), standart `veri-uygunluk-v3-standart`. Sonucun modu ile sürümü
birbirini tutmazsa sonuç gösterilmez (`BAGLAM_UYUSMUYOR`). Kütüphane varsayılanı sıkıdır. Uygulama ve CLI ayardaki
modu kullanır. İleriye dönük ölçüm kaydı ve pilot her zaman sıkı moddadır.

## Doğrulama

Yeniden üretim, bu bulut ortamında yapıldı. Ortamın koşulları:

- football-data.co.uk ağ politikası nedeniyle erişilemedi;
- GitHub yedek veri seti ve openfootball kullanıldı;
- 55.290 maç alındı ve 88 yaklaşan maç vardı.

| | Önce | Sonra |
|---|---|---|
| Model eğitimi | yapılmadı (hak engeli) | yapıldı (beyanla) |
| Olasılığı gösterilen maç (1X2) | 0 / 88 | 88 / 88 |
| Gol pazarlarında kullanılabilir maç | 0 / 88 | 88 / 88 |
| Etiket | Eksik veri · MODEL_YOK, Doğrulanamıyor · TAKIM_ESLESMEDI | Uyarılı · bahis adayı değil (DEPODA_EKSIK_MAC) |

Bu ortamda yedek veri seti 3 Eylül 2026'da bitiyor ve openfootball sonraki maçları gösteriyor. Bu yüzden "Uyarılı"
etiketi doğrudur: depo gerçekten eksik.

football-data erişilebilir olduğunda veri birkaç gün içinde güncel olur. Fikstürler de football-data'nın kendi
dosyasından ve aynı adlarla gelir. Bu yüzden maçların çoğu "Kullanılabilir" görünmelidir. Bu durum burada ölçülemedi,
çünkü site bu ortamdan erişilemiyor.

Eğitim süresi (55 bin maç, 4 çekirdek): 1X2 motoru yaklaşık 145 sn, gol motoru yaklaşık 132 sn.

Testler `tests/test_veri_01.py` dosyasında. Eski (sıkı) davranışın testleri değişmeden geçer.

## Bilinen sınırlar

- football-data.co.uk erişilemezse fikstürler yalnızca openfootball'dan gelir. 2026-27'de T1, D2, I2, SP2, F2, B1,
  SC0, G1, E2, E3 ve ek liglerin çoğu için dosya yok; bu liglerde yaklaşan maç listelenmez. Erişim sorunu çözülünce
  (ör. ağ veya güvenlik duvarı ayarı) bu ligler de gelir.
- Takvim dosyası olmayan liglerde güncellik bağımsız olarak denetlenemez. Standart modda bu tahmini engellemez; veri
  güncelliği Veri sayfasındaki son tarihlerden izlenmelidir.
- Beyan bir hukuki değerlendirme değildir. Kaynağın koşullarını okumak ve uymak kullanıcının sorumluluğundadır.
