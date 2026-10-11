# S6-OLAY-02 — Çoklu olay öncesi/sonrası karşılaştırması

Bu araç aynı takımın birden çok geçmiş olayını yan yana gösterir. Örnek: bir araştırma grubundaki İY/MS 2/1 maçları.
Her olay için olayın kendisi (t0), önceki maçları (t−5 … t−1) ve sonraki maçları (t+1 … t+3) aynı takım
perspektifinden listelenir. Araç salt okunurdur ve sonuçlar `DESCRIPTIVE_RESEARCH` statüsündedir.

Bu araç şunlar değildir: model, örüntü taraması, şike tespiti veya strateji doğrulaması. Tahmin başarısı ya da
ekonomik avantaj göstermez. İstatistiksel test, p-değeri, benzerlik puanı veya öneri üretmez.

## İki giriş yolu

Saklı çalıştırma ve grup (`--calistirma`, `--grup`):

- Adaylar, çalıştırmanın saklı grup olay kümesinden gelir; takımın oynamadığı maçlar dışarıda kalır.
- Kullanılan tanım, görünüm ve olay kümesi çalıştırmanın kendisininkidir; araştırmanın en son revizyonu kullanılmaz.
- Güncel arşivin veri özeti, saklı özetten farklıysa sonuç `VERI_SURUMU_DEGISTI` olur ve yeni veriyle hesap yapılmaz.
- Kaynak şu anda tarihsel analize kapalıysa sonuç `KULLANIM_KAPSAMI_KAPALI` olur ve hiçbir olay gösterilmez.
- Grup geçmiş sonuca göre seçildiyse sonuç `GECMIS_SONUCA_GORE_SECILMIS_GRUP` olarak işaretlenir.

Açık olay listesi (`--kaynak`, `--olay` / `--olay-dosyasi`):

- Görünüm açıkça verilir: tek kaynak veya `birlesik`.
- Bu yol elle yapılmış yeni bir geçmiş incelemedir; ön-kayıt değildir ve eski bir çalıştırmanın devamı değildir.
- Aynı kimlik iki kez verilirse bir kez sayılır.
- Geçersiz kimlikler sessizce atlanmaz; `gecersiz_olaylar` altında nedenleriyle listelenir:
  - `GORUNUMDE_YOK`
  - `TAKIM_BU_MACTA_YOK`
  - `SKOR_DOGRULANMADI`
  - `LIG_KAPSAMI_DISI`

İki yol birlikte verilirse veya hiçbiri verilmezse doğrulama hatası (çıkış kodu 2) döner.

## İlk sürüm sınırları

- Tek takım, tek lig, tek görünüm ve tek anlık görüntü desteklenir.
- Takım adı görünümdeki tam adla verilmelidir. Bulunamazsa açık bir hata verilir; benzer ad eşlemesi yapılmaz.
- Olaylar birden çok ligdeyse `--lig` açıkça seçilmelidir.
- Olaylar tarihe göre, aynı tarihte olay kimliğine göre sıralanır.
- Sayfalama:
  - Varsayılan olarak ilk 20 olay hesaplanır; bir istekte en çok 50 olay işlenir.
  - Daha fazlası sessizce kesilmez: `--offset` ile sayfalanır.
  - Toplam aday, kalan olay ve sonraki offset `sayfalama` altında yazılır.
- Pencere seçenekleri:
  - Önceki pencere 5 veya 10 maçtır (varsayılan 5).
  - Sonraki pencere 1, 3 veya 5 maçtır (varsayılan 3).

## Pencereler ve sayma kuralları

Pencere kaynağı:

- Pencereler mevcut olay kartından (`sequences.timeline.event_card`) gelir.
- Arşiv bir kez yüklenir ve görünüm bir kez kurulur. Takım-maç tablosu da bir kez hazırlanır (`archive.team_matches`).
- Seçim filtresi (ör. yalnızca 2/1) pencereleri daraltmaz.
- Pencereler önceki veya sonraki sezona taşabilir. Taşan kayıtlar `pencere_kapsami` altında sayılır.

Takım perspektifi:

- Her konum için ham İY/MS kodu, ev/deplasman bilgisi, takımın İY ve MS sonucu, yarı golleri ve A/B/C etiketleri
  gösterilir.
- Ham 2/1 ev sahibi için "İY geride, MS galip", deplasman için "İY önde, MS mağlup" demektir. Bu ikisi tek bir
  etiket altında birleştirilmez.
- Skorlar normal süre sonudur; uzatma ve penaltı atışları dahil değildir.

Eksik veri:

- Pencere durumları korunur: `DATA_START`, `RIGHT_CENSORED`, `COVERAGE_EXIT`, `GAP_GT_400D`,
  `INCOMPLETE_SEASON`, `SEASON_SKIP`, `HT_MISSING`, `POSSIBLE_AWARDED`, `UST_TUR`.
- Eksik konum `KAYIT_YOK` olarak gösterilir. Sıfır gol, mağlubiyet veya "gerçekleşmedi" sayılmaz.
- Her pazarın paydası kendi geçerli kayıt sayısıdır. Payda sıfırsa oran ve gol toplamı `null` olur.
- Tam olmayan pencerelerde "Arşivdeki önceki kayıt; gerçek ardışıklık doğrulanamadı" yazılır.
- `COMPLETE` bağımsız bir tamlık kanıtı değildir. Kaynak sezonu kısmi işaretliyorsa `celiski` alanı doldurulur.
- Sonraki maç yoksa olası neden yazılır:
  - henüz oynanmamış,
  - kaynak güncel değil,
  - kapsam bitti,
  - bilinmiyor.
- Kaynaklar yalnızca lig maçlarını içerir. "Önceki 5", takımın bütün resmî maçları değildir.

Ortak maçlar:

- Aynı maç birden çok pencerede olabilir. Toplu özetlerde (`toplu`) olay kimliğiyle bir kez sayılır.
- `ortusme` altında şu sayılar ayrı ayrı yazılır:
  - toplam pencere konumu,
  - benzersiz maç,
  - önceki ve sonraki pencerelerin ortak maçları,
  - başka bir olayın penceresine düşen seçili olaylar.

`SECILI_OLAYLAR_ARASI_ARALIK`:

- Her olay için sıralı listedeki bir önceki seçili olaydan bu yana takvim günü verilir.
- Arşivde gözlenen kayıt sayısı ve süreklilik işaretleri de verilir.
- Bu sayı doğrulanmış oynanan maç sayısı değildir; `dogrulanmis_oynanan_mac` her zaman `null`'dur.
- "Sırası geldi" çıkarımı yapılmaz.

## Komutlar

Linux:

```
python -m bahis_tahmin calisma-olay-karsilastir --calisma <ALAN> --ev <ARSIV> --calistirma <CALISTIRMA_ID> --grup 1 \
    --takim "Arsenal FC" [--once 10] [--sonra 5] [--limit 20] [--offset 0] [--lig E0]
python -m bahis_tahmin calisma-olay-karsilastir --ev <ARSIV> --kaynak openfootball --takim "Arsenal FC" \
    --olay "E0|2024-08-17|Arsenal FC|Wolverhampton Wanderers FC" --olay "<OLAY_KIMLIGI_2>"
python -m bahis_tahmin calisma-olay-karsilastir --ev <ARSIV> --kaynak openfootball --takim "Arsenal FC" \
    --olay-dosyasi olaylar.txt
```

Windows'ta aynı komutlar `.venv\Scripts\python -m bahis_tahmin ...` ile çalışır.

`--olay-dosyasi` UTF-8 bir dosyadır: her satırda bir olay kimliği bulunur; `#` ile başlayan satırlar atlanır.

Komut çalışma alanını oluşturmaz, değiştirmez ve not eklemez. Arşive, pilota veya deftere yazmaz; ağ kullanmaz. Çıkış
kodları `calisma-*` komutlarıyla aynıdır: 0 tamam, 2 doğrulama, 3 çalışma alanı/arşiv, 4 çakışma.

## Arayüz için servis sözleşmesi

`bahis_tahmin.olay_karsilastirma` PySide6'dan bağımsızdır. Tek giriş noktası:

```python
olay_karsilastir(arsiv, takim, *, alan=None, calistirma_id=None, grup=None,   # saklı çalıştırma yolu
                 kaynak=None, olaylar=None,                                   # açık liste yolu
                 lig=None, once=5, sonra=3, limit=20, offset=0) -> dict
```

- `arsiv` = `archive.load(klasor)`.
- `alan` = `CalismaAlani.ac(klasor)` (salt okunur).
- Dönen sözlük JSON'a hazırdır (NaN yok) ve `calisma.to_json` ile yazılır.
- Hatalar `CalismaError` ailesindendir: `DogrulamaHatasi` girdi hatalarını bildirir.
- Aynı veri ve seçeneklerle aynı `sonuc_ozeti` üretilir. Arşiv satırlarının ve olay kimliklerinin sırası sonucu
  değiştirmez.
- Çıktıda kod sürümleri `surumler` altında, veri kimliği `veri` altında yer alır.
