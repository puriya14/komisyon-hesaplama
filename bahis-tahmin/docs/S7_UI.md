# S7-UI-01 — Araştırma Çalışma Alanı sayfası

Ana menüde **"Araştırma Çalışma Alanı"** sayfası ("Dizi Araştırması"nın altında). Kayıtlı araştırmaları, iki maç
grubunun karşılaştırmasını, çalıştırma geçmişini, notları ve bir takımın birden çok olayının önce/sonra matrisini
terminal veya JSON olmadan kullanmayı sağlar.

Sayfa yeni bir hesap motoru değildir; mevcut servisleri kullanır:

- `calisma.CalismaAlani`: oluşturma, revizyon, çalıştırma, saklı sonuç, doğrulama ve notlar;
- `calisma.compute`: önizleme;
- `olay_karsilastirma.olay_karsilastir`: olay matrisi;
- `archive.load`, `archive.view` ve `archive.explore_view`: salt okunur arşiv.

Bütün sonuçlar geçmiş veri incelemesidir (`DESCRIPTIVE_RESEARCH`). Tahmin, olasılık, strateji başarısı veya bahis
önerisi değildir.

## Açma ve oluşturma

Sayfa açılınca ağ isteği yapılmaz. Arşiv hazırlanmaz, çalışma alanı oluşturulmaz, kayıt veya eğitim yapılmaz.
Klasör alanlarında yalnızca önerilen yol yazılıdır. Arşiv ve çalışma alanı ayrı kavramlardır.

| Düğme | Ne yapar |
|---|---|
| Arşivi aç | Arşivi salt okunur açar. Arşiv yoksa nedenini ve yolunu yazar, "Veri sayfasına git" düğmesini gösterir. İndirme yapmaz. |
| Çalışma alanını aç | Yalnızca var olan alanı salt okunur açar; yoksa oluşturmaz. |
| Yeni çalışma alanı oluştur | Yazan işlemdir. Yalnızca boş veya henüz olmayan bir klasörde çalışır. |

"Yeni çalışma alanı oluştur" şu klasörleri reddeder:

- arşiv veya pilot klasörü ile bunların içindeki klasörler;
- uygulama veri klasörü;
- boş olmayan klasörler.

Bozuk veya uyumsuz dosyanın üzerine yazılmaz. Sayfa nedeni ve yolu gösterir.

## Sekmeler

**A · Araştırmalar ve tanım**
- Araştırma listesi ve tanım formu: başlık, açıklama, etiketler, pazarlar (A/B/C/İY/MS), Grup 1 ve isteğe bağlı Grup 2.
- Her grup için: lig, birden çok sezon, takım, ev/deplasman, tarih aralığı ve geçmiş sonuç filtresi.
- Kaynak görünümü üstteki seçimdir: tek kaynak veya birleştirilmiş görünüm.
- Takım alanına yazılan metin yalnızca listede arar; benzer ad eşlemesi yapılmaz.
- Kaynak değişince görünümde olmayan takım sessizce dönüştürülmez, uyarı yazılır.
- Kaydetme düğmeleri:
  - "Yeni araştırma" bellekte bir taslak açar; "Kaydet" onu kaydeder.
  - Açık araştırmada "Yeni revizyon kaydet" yeni revizyon ekler; eski revizyon değişmez.
- Araya başka bir revizyon girdiyse (`temel_revizyon` çakışması) kayıt yapılmaz ve taslak korunur.
- Kaydedilmemiş değişiklik açıkça yazılır. Başka araştırmaya geçerken, taslağı bırakırken veya pencereyi kapatırken
  "Kaydet / Değişiklikleri bırak / Vazgeç" sorulur.
- Sonuç düğmeleri:
  - "Önizle (kaydetmez)" formdaki tanımı hesaplar.
  - "Çalıştır ve sonucu sakla" yalnızca kayıtlı revizyonu çalıştırır. Taslak kirliyse çalışmaz. Ekrandaki revizyon
    artık en son revizyon değilse kayıt yapılmaz.

**B · Grup karşılaştırması**
- Her pazar için Grup 1 ve Grup 2 yan yana: gerçekleşen / geçerli, oran ve bilinmiyor sayısı.
- Fark yüzde puandır, göreli yüzde değişim değildir. Payda sıfırsa "Veri yok" veya "—" yazılır; %0 gösterilmez.
- Kesin değerler ipucunda görünür.
- İY/MS dağılımı 9 merkezi kodla gösterilir. Ham kod ev sahibi bakışıdır; 2/1 takımın geri dönüşü anlamına gelmez.
- Ortak / yalnız Grup 1 / yalnız Grup 2 sayıları gösterilir. Gruplar örtüşüyorsa "Gruplarda ortak maç var" notu
  eklenir.
- Geçmiş sonuca göre seçilmiş gruplar işaretlenir.
- Veri kalitesi aynı kapsamla gösterilir. Dosya düzeyi karantina takımın hata sayısı değildir.
- "Saklı sonucu aç" yeniden hesaplamaz. Saklı sonuç kendi revizyonu, çalıştırma zamanı, görünümü ve veri özetiyle
  gösterilir.
- "Mevcut arşivle doğrula" salt okunurdur. Durumlar ayrı yazılır: `DOGRULANDI`, `VERI_SURUMU_DEGISTI`, `SONUC_FARKLI`,
  `KULLANIM_KAPSAMI_KAPALI`. Veri sürümü değiştiyse saklı sonuç yerinde kalır; yeni veri için açıkça yeni
  çalıştırma gerekir.

**C · Olay karşılaştırması**
- İki yol vardır:
  - A: saklı çalıştırma → grup → takım;
  - B: mevcut görünümün maç tablosundan açık seçim. Kimlik elle yazılmaz.
- Seçim satır numarasıyla değil maç kimliğiyle tutulur; sıralama ve arama seçimi değiştirmez.
- Takım, kaynak veya veri sürümü değişince geçersizleşen seçim açıkça temizlenir. Pencere seçeneği (önce 5/10,
  sonra 1/3/5, sayfa boyutu) değişince seçim korunur ve sonuç temizlenir.
- Matris düzeni:
  - satırlar olaylardır; sütunlar t−k … t0 … t+k, t0 ayrı renkli ve kalın;
  - eksik konum "KAYIT YOK · neden" metniyle yazılır; ilk yarı skoru yoksa "İY yok" yazılır;
  - tam ayrıntı hücre seçilince alttaki panelde görünür.
- Sayfalama: varsayılan 20, en çok 50 olay. Özet başlığı "Bu sayfadaki olayların özeti (N olay; toplam aday M)"
  biçimindedir ve bütün adayların özeti değildir.
- Hesaplanmayan olaylar nedenleriyle listelenir.

**D · Notlar ve geçmiş**
- Revizyonlar, çalıştırmalar ve notlar listelenir.
- Not eylemleri:
  - araştırmaya not ekleme;
  - seçili maça bağlı not (C sekmesindeki seçimden, aynı görünüm);
  - yeni sürüm (önceki sürüm korunur);
  - arşivleme (fiziksel silme yok);
  - bağlı maçın olay kartı (notun görünümünde).
- Notlar skoru, modeli veya etiketleri değiştirmez.
- Bütün kullanıcı metinleri düz metin olarak gösterilir; HTML yorumlanmaz.

## İş parçacıkları ve kapanış

- Arşiv yükleme, hesap, çalıştırma, doğrulama ve disk işleri `AppController.run_job` ile arka planda çalışır. Bu, mevcut
  tek görev yöneticisidir.
- Form değerleri ana iş parçacığında kopyalanır. Çalışma alanı (SQLite) her işte o iş parçacığında açılıp kapanır.
- Her okuma isteği bağlamını taşır: arşiv yüklemesi, görünüm, araştırma ve revizyon, takım, pencere. Bağlam
  değiştiyse geç gelen sonuç gösterilmez. Tamamlanan yazma her zaman kayıtlara yansır.
- Aynı anda tek iş çalışır; iş sürerken iş başlatan düğmeler kapalıdır, bu yüzden çift tıklama çift kayıt üretmez.
- Pencere kapanırken okuma işi beklenir. Yazma işi sürüyorsa onay sorulur ve iş bitene kadar beklenir; yazma yarım
  kalmaz.

## Testler ve kabul

`tests/test_s7_ui.py` 22 zorunlu senaryoyu ve en küçük pencere boyutu denetimini kapsar. Boyut denetimi uzun ve boşluksuz klasör yollarını da içerir: uzun yol sayfayı yatay taşırmaz; kırpılırsa tam metin ipucunda görünür. Testler şunlarla çalışır:

- gerçek servisler;
- geçici klasörde sahte HTTP ile hazırlanmış sentetik arşiv;
- geçici çalışma alanları.

Qt geri çağrısındaki yakalanmamış her istisna test hatası sayılır. Ekran kontrolleri yalnızca sentetik veriyle
yapıldı: 1360×880 ve 1024×680, ölçek 1.0 / 1.25 / 1.5 (Linux offscreen). Bu kontroller Windows'ta elle kabulün
yerine geçmez.
