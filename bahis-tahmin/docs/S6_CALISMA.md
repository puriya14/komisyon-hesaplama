# S6-CALISMA-01 — Kayıtlı araştırmalar ve iki grup karşılaştırması

GitHub tarihsel arşivinin ([`S5_GITHUB.md`](S5_GITHUB.md)) üzerinde betimleyici bir çalışma alanıdır. Bir
araştırmaya ad ve filtre verip kaydedebilir, aynı arşiv üzerinde iki maç grubunu karşılaştırabilir, sonuçları
saklayabilir ve not ekleyebilirsiniz.

Bütün sonuçların statüsü `DESCRIPTIVE_RESEARCH`'tür. Olasılık, p-değeri, anlamlılık, strateji başarısı veya bahis
önerisi üretilmez; model eğitilmez.

## Çalışma alanı

- Ayrı bir klasördür: varsayılan olarak uygulama klasörünün yanındaki `BahisTahmin-Calisma`. Windows'ta
  `%LOCALAPPDATA%\BahisTahmin-Calisma`. `--calisma` veya `BAHIS_TAHMIN_CALISMA` ile değiştirilebilir.
- İçinde tek bir `calisma.sqlite` dosyası bulunur. Uygulama veri klasörü ve arşiv klasörüyle çakışan bir konum
  reddedilir. Kullanıcı veritabanı, defter, pilot ve model bu dosyaya dahil değildir; hiçbirinin şeması değişmez.
- **Yazan komutlar:** `calisma-olustur`, `calisma-revize`, `calisma-calistir`, `calisma-not`,
  `calisma-not-guncelle`. Yalnızca `calisma-olustur` çalışma alanı yoksa onu oluşturur; diğerleri var olan bir alan
  ister.
- **Salt okunur komutlar:** `calisma-liste`, `calisma-oku`, `calisma-calistirma-oku`, `calisma-dogrula`,
  `calisma-not-kart`, `calisma-karsilastir`. Çalışma alanını oluşturmaz, ağ isteği yapmaz, dosyaya yazmaz.
- Kayıtlar yalnızca eklenir. Değiştirme ve silme veritabanı tetikleyicileriyle reddedilir: tanım değişirse yeni
  revizyon, not değişirse yeni sürüm eklenir. Not "arşivlenebilir" ama fiziksel olarak silinmez.
- Her yazma tek bir işlemdir (`BEGIN IMMEDIATE`): yarım kalan bir çalıştırma kayıt bırakmaz. `--temel-revizyon`
  verilirse ve araştırma o arada başka biri tarafından değiştirildiyse değişiklik reddedilir (çıkış kodu 4); sessiz
  üzerine yazma olmaz.
- Bozuk, başka şemadaki veya kilitli bir dosya anlaşılır bir hata verir ve dosyaya dokunulmaz (üzerine yazılmaz).

## Araştırma tanımı (`calisma-tanim-v1`)

| Alan | Kural |
|---|---|
| `baslik` | zorunlu, en çok 200 karakter |
| `aciklama` | en çok 4000 karakter |
| `kaynak` | **zorunlu ve açık**: tek kaynak (`openfootball`, `datasets`, `xgabora`, `hudl`) veya `birlesik` |
| `grup_1` | filtreler (boş = görünümün bütün maçları) |
| `grup_2` | isteğe bağlı; aynı filtre alanları |
| `pazarlar` | `A`, `B`, `C`, `IYMS` alt kümesi (varsayılan hepsi) |
| `etiketler` | en çok 20 etiket, her biri en çok 50 karakter |

Gruplar Grup 1 ve Grup 2 olarak adlandırılır; uygulamadaki A/B/C pazarlarıyla karışmasın diye A/B denmez.

Filtre alanları açık bir izin listesiyle doğrulanır: `lig`, `sezonlar` (liste), `takim`, `yer` (`ev`/`deplasman`,
yalnızca takımla birlikte), `bas`, `son` (YYYY-AA-GG) ve `sonuc`. Bilinmeyen bir alan hata verir. SQL, Python ifadesi
veya `eval` yoktur; kullanıcı metni hiçbir yerde çalıştırılmaz.

`sonuc` geçmiş sonuca göre bir inceleme filtresidir. `A`/`B`/`C` için `tumu`, `gerceklesti`, `gerceklesmedi` veya
`bilinmiyor` değerlerini, `iy_ms` için merkezi kayıttaki İY/MS kodlarını alır; etiketler merkezi pazar kaydından
gelir. Böyle seçilen bir grup `GECMIS_SONUCA_GORE_SECILMIS_GRUP` olarak işaretlenir. Örneğin yalnızca 3,5 üst biten
maçları seçerseniz B oranının %100 çıkması seçimin doğal sonucudur; tahmin başarısı ya da maç öncesi strateji
değildir.

Kaydetmek bir araştırma tanımı oluşturur. Bu kayıt, sonuçlar görülmeden kaydedildiğinin kanıtı (bilimsel ön-kayıt)
değildir. Her revizyonda `kayit_aninda_onceki_calistirma` alanı, o revizyon kaydedilirken araştırmanın kaç kez
çalıştırılmış olduğunu gösterir.

## Çalıştırma, karşılaştırma ve yeniden üretilebilirlik

- İki grup aynı arşiv yüklemesinden ve aynı `ArchiveView` görünümünden hesaplanır. Kaynak filtresi birleştirmeden
  önce uygulanır. Grup listesi, her sezon için `archive.explore_view` ile alınır; yani arşivin maç listesiyle aynı
  kümedir. Pazar sayıları merkezi `archive.summary` ve `goals.markets` hesaplarından gelir.
- Grup başına hesaplananlar: benzersiz maç, geçerli ve bilinmeyen hedef sayısı, A/B/C gerçekleşme sayısı ve her
  pazarın kendi paydası, gerçekleşme oranı, İY/MS dağılımı, mantıksal İY 0-0 sayısı, çelişki ve inceleme bilgisi,
  dosya düzeyi karantina, kullanılan sezonlar ve tarih aralığı.
- Karşılaştırma: `fark_yuzde_puan = 100 × (oran_grup_1 − oran_grup_2)`. Bu bir yüzde puan farkıdır, göreli yüzde
  değişim değildir. Payda sıfırsa oran ve fark `null` olur. Ortak maçlar olay kimliğiyle sayılır: `ortak`,
  `yalniz_grup_1`, `yalniz_grup_2`. Gruplar örtüşüyorsa `bagimsiz_ornek_degil: true` yazılır. İstatistiksel test
  yapılmaz.
- Çalıştırma kaydında şunlar bulunur: araştırma kimliği ve revizyonu, gerçek çalıştırma zamanı, tam tanım, görünüm,
  kaynak commit'leri, `veri_ozeti` (kullanılan doğrulanmış blokların depo/commit/yol/dosya özeti/satır
  özeti/ayrıştırıcısı ile görünüm satırlarının içerik özeti; dosya yolu veya değiştirilme zamanı kimlik sayılmaz),
  sürümler (paket, git commit'i, kod özeti, tanım/analiz/arşiv/eşleme/pazar kuralı sürümleri), grup olay kümesi
  özeti ve sayısı, toplu sonuçlar, uyarılar ve `sonuc_ozeti`.
- Aynı veri ve tanımla yapılan yeni bir çalıştırmanın kimliği ve zamanı farklıdır, ama `sonuc_ozeti` aynıdır. Veri
  değişmişse yeni çalıştırma `onceki_calistirmaya_gore_veri: DEGISTI` yazar; önceki sonuç değişmez.
- `calisma-dogrula` saklı bir çalıştırmayı mevcut arşivle yeniden hesaplar ve hiçbir şey yazmaz. Sonuç şu
  durumlardan biridir:
  - `DOGRULANDI`: aynı veri sürümü, aynı sonuç.
  - `VERI_SURUMU_DEGISTI`: saklı veri sürümü artık arşivde yok. Saklı sonuç okunabilir ama yeniden hesaplanarak
    doğrulanamaz; yeni veri eski verinin yerine kullanılmaz.
  - `SONUC_FARKLI`: veri aynı ama sonuç farklı; kod veya analiz sürümü değişmiş olabilir.
  - `KULLANIM_KAPSAMI_KAPALI`
- Saklı bir çalıştırma okunurken **güncel** kullanım kapsamı uygulanır. Kullandığı kaynak artık tarihsel analize
  kapalıysa toplu sonuç ve olay listeleri gösterilmez. Analizi kapalı bir kaynakla (datasets, xgabora) yapılan
  çalıştırma `KULLANIM_KAPSAMI_KAPALI` sonucunu verir.
- Özetler (SHA-256) içerik eşleşmesini denetlemek içindir. Bağımsız zaman damgası, saldırıya dayanıklı değişmezlik
  veya yedek değildir.

## Notlar

Notlar serbest metindir (en çok 4000 karakter; Türkçe ve Unicode metin olduğu gibi korunur). İsteğe bağlı olarak
arşivdeki bir maça bağlanabilir. Bağlantı olay kimliğini, görünümü ve bağlantı anındaki veri özetini taşır. Maç o
görünümde yoksa not eklenmez; başka bir kaynağın maçına sessizce bağlanmaz.

Bir not skoru, kaynak kimliğini, resmî maç statüsünü veya model sonucunu değiştirmez ve hiçbir karar kuralını
çalıştırmaz. "Şüpheli buldum" gibi bir not sistemin tespiti (örneğin şike tespiti) sayılmaz.

`calisma-not-kart`, notun bağlı olduğu maçın kartını mevcut `archive.event_card_for` ile aynı görünümde açar.

## Komutlar

Linux:

```
python -m bahis_tahmin calisma-olustur --calisma <ALAN> --baslik "E0 2024/25 ile 2023/24" --kaynak openfootball \
    --g1-lig E0 --g1-sezon 2024/25 --g2-lig E0 --g2-sezon 2023/24 --etiket sezon
python -m bahis_tahmin calisma-olustur --calisma <ALAN> --baslik "Arsenal evde, 3,5 üst bitenler" --kaynak openfootball \
    --g1-takim "Arsenal FC" --g1-yer ev --g1-sonuc B=gerceklesti --g2-takim "Arsenal FC" --g2-yer ev
python -m bahis_tahmin calisma-liste      --calisma <ALAN>
python -m bahis_tahmin calisma-oku        --calisma <ALAN> --arastirma <ID>
python -m bahis_tahmin calisma-revize     --calisma <ALAN> --arastirma <ID> --temel-revizyon 1 --g2-sezon 2022/23 --g2-lig E0
python -m bahis_tahmin calisma-calistir   --calisma <ALAN> --ev <ARSIV> --arastirma <ID>
python -m bahis_tahmin calisma-calistirma-oku --calisma <ALAN> --calistirma <CALISTIRMA_ID> [--olaylar]
python -m bahis_tahmin calisma-dogrula    --calisma <ALAN> --ev <ARSIV> --calistirma <CALISTIRMA_ID>
python -m bahis_tahmin calisma-karsilastir --ev <ARSIV> --kaynak openfootball --g1-sezon 2024/25 --g2-sezon 2023/24
python -m bahis_tahmin calisma-not        --calisma <ALAN> --arastirma <ID> --metin "Not" [--mac "E0|2024-08-17|Arsenal FC|Wolverhampton Wanderers FC" --ev <ARSIV>]
python -m bahis_tahmin calisma-not-guncelle --calisma <ALAN> --not <NOT_ID> [--metin "..."] [--arsivle]
python -m bahis_tahmin calisma-not-kart   --calisma <ALAN> --ev <ARSIV> --not <NOT_ID> --takim "Arsenal FC"
```

Windows'ta aynı komutlar `.venv\Scripts\python -m bahis_tahmin ...` ile çalışır. Örnek:
`--calisma "%LOCALAPPDATA%\BahisTahmin-Calisma" --ev "%LOCALAPPDATA%\BahisTahmin-Arsiv"`.

Bazı ayrıntılar:

- `--g1-sezon` ve `--g2-sezon` tekrarlanabilir veya virgülle verilebilir.
- `--g2-tum` Grup 2 olarak görünümün bütün maçlarını seçer.
- `calisma-revize` içinde bir `--g1-*` / `--g2-*` bayrağı verilirse o grup verilen bayraklarla tamamen yeniden
  tanımlanır; `--grup2-kaldir` Grup 2'yi kaldırır.
- Tam tanım `--tanim dosya.json` ile de verilebilir.

Bütün çıktılar JSON'dur: sonlu sayılar ve `null` kullanılır, NaN/Infinity yazılmaz. Çıkış kodları:

| Kod | Anlamı |
|---|---|
| 0 | tamam |
| 2 | doğrulama hatası (ve argparse hataları) |
| 3 | çalışma alanı veya arşiv hatası (eksik, bozuk, kilitli, kayıt yok) |
| 4 | eşzamanlı değişiklik çakışması |

## Arayüz için servis sözleşmesi (tek bağlantı noktası)

`bahis_tahmin.calisma` PySide6'dan bağımsızdır. Arayüz yalnızca şunları kullanır:

- `CalismaAlani.ac(klasor)`: salt okunur.
- `CalismaAlani.olustur_veya_ac(klasor)` / `yazmak_icin_ac(klasor)`: yazma.
- Okuma: `arastirmalar()`, `arastirma(id, revizyon=None)`, `calistirma(id, olaylar=False)`, `notlar(id)`,
  `dogrula(arsiv, calistirma_id)`, `not_karti(arsiv, not_id, takim)`.
- Yazma: `arastirma_olustur(tanim)`, `arastirma_revize(id, degisiklik, temel_revizyon)`, `calistir(arsiv, id)`,
  `not_ekle(id, metin, mac_kimligi, arsiv, kaynak)`, `not_guncelle(not_id, metin, durum)`.
- Kaydetmeden önizleme: modül işlevi `compute(arsiv, tanim)`.

Arşiv nesnesi `archive.load(klasor)` ile alınır. Hatalar `CalismaError` (alt sınıfları `DogrulamaHatasi`,
`CakismaHatasi`) olarak gelir. Dönen değerler JSON'a hazır sözlüklerdir ve `to_json` ile yazılır.
