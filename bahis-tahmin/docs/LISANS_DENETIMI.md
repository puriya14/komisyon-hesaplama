# Veri kaynakları lisans / kullanım koşulları denetimi

Denetim tarihi: 2026-10-10. Kod karşılığı: `bahis_tahmin/data/source_registry.py`.

**Önemli sınırlama:** Bu denetim, geliştirme ortamının ağ politikası nedeniyle football-data.co.uk ve
the-odds-api.com sitelerine **doğrudan erişilemeden** yapıldı (vekil sunucu 403). Aşağıdaki özetler,
erişilebilen depo lisans dosyalarına ve genel bilgilere dayanır; **hukuki görüş değildir**. Kullanım
hakkı belirsiz kaynaklar varsayılan olarak **kapalıdır**; kullanıcının açık onayı yalnızca indirmeyi (erişimi) açar.
S3-GATE-02'den itibaren "kişisel/yerel analiz" gerekçesiyle **otomatik** kullanım izni yoktur. Sonuç kullanımı, model
eğitimi ve model kullanımı belgeyle doğrulanmadıkça bu verilerle tahmin gösterilmez ve model eğitilmez. Tek istisna
VERI-01 ile geldi: kullanıcı ayrıca **açık bir kişisel (ticari olmayan) kullanım beyanı** verebilir. Bu beyan kendi
sorumluluğundadır ve hukuki bir değerlendirme değildir. Ayrıntılar aşağıda ve [`VERI_01.md`](VERI_01.md) belgesinde.

| Kaynak | Ne için | Lisans durumu | Otomatik indirme | Model eğitimi | Yeniden dağıtım | Uygulamadaki durum |
|---|---|---|---|---|---|---|
| football-data.co.uk | Geçmiş sonuçlar, İY skoru, şut, 1X2 ve 2,5 oranları; fikstür | Açık lisans metni bulunamadı; site "All Rights Reserved" altbilgisi taşıyor; İngiliz/İskoç ligleri için Football DataCo hak iddia eder | Doğrulanamadı → seyrek, önbellekli | Doğrulanamadı | Varsayılmaz (veri yalnızca kullanıcı bilgisayarında) | **Onay gerektirir**; onay yoksa indirilmez |
| GitHub: xgabora/Club-Football-Match-Data | football-data erişilemezse yedek geçmiş veri | Depo MIT; ancak içerik football-data/ClubElo kaynaklı, kaynak koşulları geçerli | GitHub tek dosya | Asıl kaynağa bağlı | Varsayılmaz | **Onay gerektirir** |
| openfootball/football.json | Yedek fikstür | CC0 1.0 | İzinli | İzinli | İzinli | Onay gerekmez |
| openfootball/football.json (sonuçlar, `openfootball-sonuc`) | Yalnızca S4 pilotu: E0 maç sonuçları | CC0 1.0 (derleyici hakları; doğruluk garantisi ve üçüncü kişi hakları kapsam dışı, madde 4) | Sabit commit, önbellekli | İzinli (köken doğrulanırsa) | İzinli; uygulama ham veriyi dağıtmaz | Onay gerekmez; köken doğrulaması zorunlu |
| openfootball/clubs (`europe/england/eng.clubs.txt`) | Yalnızca kulüp alternatif adı kanıtı (pilot kimlik eşlemesi) | CC0 1.0 | Tek dosya, bir kez okundu | — (veri değil, kimlik kanıtı) | — | Kodda 16 ad eşlemesi |
| The Odds API | (Planlanan) gerçek oran | Ücretli planlar; resmi koşullar doğrulanamadı | API anahtarı | Doğrulanamadı | Doğrulanamadı | **Entegre edilmedi** (ücretli, kullanıcı ücretsiz kaynak istedi) |

## Uygulanan kontroller

- İlk veri indirmeden önce **onay penceresi** (`ui/consent.py`) her kaynağın koşul özetini ve bağlantısını
  gösterir; kaynak başına ayrı onay kutusu vardır. Onaylar zaman damgasıyla ayarlarda saklanır ve Veri
  sayfasından geri alınabilir. Komut satırında: `update --accept-terms football-data`.
- Onay yoksa `DataStore.update(allowed=...)` ilgili kaynaktan **hiçbir istek yapmaz** ve raporda
  `blocked_sources` olarak gösterir (test: `tests/test_store.py`).
- Veriler uygulama ile **dağıtılmaz**; derlenen .exe veri içermez.
- Gol pazarları için **gerçek oran kaynağı yoktur**: football-data dosyaları 3,5 Üst, İY 1,5 Üst ve iki yarıda
  KG oranı içermez. Bu oranlar başka pazarlardan türetilmez; kullanıcı kendi gördüğü oranı girer veya
  şemaya uygun CSV ile içe aktarır.

- Kullanım kapsamı yapılandırılmış olarak `source_registry.USE_RIGHTS`'ta tutulur (erişim koşulları, sonuç kullanımı,
  model eğitimi, model kullanımı, ticari kullanım, yeniden dağıtım ve kaynağın sağladığı veri türleri ayrı) ve ortak
  veri uygunluk kontrolü işlem kapsamına göre (`eligibility.OPERATION_SCOPES`) okur: belgelenmemiş sonuç kullanımı/
  model eğitimi/model kullanımı hakkıyla **tahmin gösterilmez, bahis adayı üretilmez ve gerçek veriyle model
  eğitilmez**; yeniden dağıtım ve ticari kullanım bu yerel işlemler için gerekmez. Kullanıcı onayı yalnızca erişimi
  kapsar; onay kutusu, bayrak veya kaynak etiketi bu kontrolü aşamaz (S3-GATE-02, [`VERI_UYGUNLUK.md`](VERI_UYGUNLUK.md)).
- 2026-10-10 (S3-GATE-02): football-data.co.uk `data.php` ve `contact.php` sayfaları bu ortamdan yeniden denendi;
  alan adı çözümlenemedi (ENOTFOUND), belge okunamadı. Veri indirilmedi, kaynak sahibine mesaj gönderilmedi, ücretli
  üyelik başlatılmadı. Belge okunamadığı için hiçbir alan "izinli" sayılmadı. GitHub yedeğinin depo lisansı (MIT) asıl
  kaynağın haklarını kanıtlamaz.
- 2026-10-10 (S4-PILOT-01): openfootball/football.json `LICENSE.md` (commit e6744429ee39, git nesnesi
  670154e3538863b2) ve openfootball/clubs `LICENSE.md` (commit ae3800227c44, aynı git nesnesi) kısmi git klonuyla
  okundu: CC0 1.0 Universal. CC0, derleyicinin telif ve veritabanı haklarından feragatidir; verinin doğruluğunu
  garanti etmez ve üçüncü kişilerin olası haklarını (ör. lig fikstür listeleri üzerindeki talepler) temizlemez
  (madde 4). Sonuç satırları yalnızca köken doğrulamasıyla hak kazanır (`openfootball-sonuc`, `data/provenance.py`);
  football-data/GitHub yedeği satırları bu etiketle hak kazanamaz. Ham veri depoya veya dağıtıma konmadı.

- VERI-01 (kişisel kullanım beyanı): Onay penceresinde ve `update --kisisel-kullanim` seçeneğinde, indirme onayından
  ayrı ikinci bir kutu vardır. Kullanıcı bu kutuyla verileri yalnızca kişisel ve ticari olmayan amaçla
  kullanacağını, paylaşmayacağını ve yeniden dağıtmayacağını beyan eder. Kişisel amaç kendi analizi, bu
  bilgisayarda model eğitimi ve tahmindir.
  - Beyan yalnızca football-data ve GitHub yedeği için ve yalnızca indirme onayıyla geçerlidir.
  - Kayıtta `DOGRULANAMADI` olan sonuç kullanımı, model eğitimi ve model kullanımı alanlarını açar; değerleri
    `KULLANICI_BEYANI` olur.
  - Kaynak kaydındaki belge durumu değişmez. Ticari kullanım ve yeniden dağıtım beyanla açılmaz.
  - Beyan geri alınabilir. Geri alınınca daha önce eğitilmiş model de kullanılmaz.
  - İleriye dönük ölçüm kaydı (protokol v3) ve S4 pilotu beyanı kullanmaz.

## Açık konular (kullanıcı kararı gerekir)

1. football-data.co.uk koşullarının site üzerinden okunması; sonuç kullanımı, model eğitimi ve model kullanımı
   kapsamının belgeyle teyidi (belge kayda eklenmeden bu verilerle tahmin gösterilmez).
2. Ticari kullanım/yeniden dağıtım planlanıyorsa yazılı izin veya lisanslı veri sağlayıcı.
3. Gerçek oranlı geçmiş getiri doğrulaması isteniyorsa A/B/C pazarlarını kapsayan, kullanım hakkı açık
   (büyük olasılıkla ücretli) bir oran kaynağı — bu, kullanıcının açık onayı olmadan başlatılmadı.
