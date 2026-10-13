# WEB-01 — Web sürümü (tarayıcıdan kullanım)

İstek: "gerçek web sürümünü yap". Uygulama artık masaüstü penceresinin yanında bir tarayıcı arayüzüyle de
kullanılabilir. Web arayüzü **kendi bilgisayarınızda** çalışır. İnternette barındırılan bir site değildir: veri
kaynaklarının kullanım koşulları verilerin yalnızca sizin bilgisayarınızda, kişisel amaçla kullanılmasına izin verir
(bkz. [`LISANS_DENETIMI.md`](LISANS_DENETIMI.md)).

Masaüstü uygulaması olduğu gibi kalır. İkisi aynı veri klasörünü, ayarları, modelleri ve sanal takip dosyasını kullanır.

## Açma

1. Uygulama klasöründe `web_baslat.bat` dosyasını çalıştırın. İlk seferde sanal ortam ve paketler kurulur. Eski bir
   kurulumda `flask` ve `waitress` eksikse bunlar da kurulur.
2. Tarayıcı kendiliğinden `http://127.0.0.1:8765` adresini açar. Açılmazsa adresi elle yazın.
3. Kapatmak için siyah pencereyi kapatın veya Ctrl+C'ye basın.

Komut satırından:

```bat
.venv\Scripts\python -m bahis_tahmin web                      & rem yalnızca bu bilgisayar
.venv\Scripts\python -m bahis_tahmin web --port 9000          & rem başka port
.venv\Scripts\python -m bahis_tahmin web --tarayici-acma      & rem tarayıcıyı açma
.venv\Scripts\python -m bahis_tahmin web --paylas             & rem aynı ağdaki cihazlar (parola sorulur)
```

İlk açılış masaüstüyle aynıdır. Önce **Veri → Kaynak koşulları ve onaylar** sayfasında kaynak onaylarını ve kişisel
kullanım beyanlarını işaretleyin. Ardından "Kaydet, Güncelle ve Eğit" düğmesine basın. Uzun işler (indirme, eğitim)
arka planda sürer. Üst çubukta ilerleme görünür; iş bitince sayfa kendiliğinden yenilenir.

## Telefondan (aynı ev ağı)

1. `web_paylas.bat` dosyasını çalıştırın.
2. Pencere bir giriş parolası sorar (en az 6 karakter). Parola komut satırında yazılmaz, böylece görev listesinde
   görünmez.
3. Pencerede `Aynı ağdaki cihazlardan: http://192.168.x.x:8765/` satırı çıkar. Telefonda bu adresi açıp parolayı girin.
4. Windows Güvenlik Duvarı izin isterse yalnızca **Özel ağlar** için izin verin.

Parola olmadan ağda paylaşım açılmaz (`--paylas` parolasız çalışmaz). Bağlantı HTTP'dir (şifrelenmez). Bu yüzden
yalnızca güvendiğiniz ev ağında kullanın, ortak Wi-Fi'da açmayın. Modem üzerinden internete port yönlendirmesi
yapmayın.

## Sayfalar

| Web | Masaüstündeki karşılığı |
|---|---|
| Genel Bakış | Genel Bakış (kartlar, isabet ve kalibrasyon grafikleri, sezon kalitesi) |
| Tahminler | Tahminler (lig/tarih/değer/takım süzgeci, renkli olasılıklar, veri durumu ve nedeni) |
| Maç ayrıntısı | Maç ayrıntı penceresi (olasılık çubuğu, marketler, skor ısı haritası, form ve aralarındaki maçlar) |
| En Olası Seçimler | En Olası Seçimler (geçmiş gerçekleşme kartları, kupon olasılığı) |
| Maç Analizi | Maç Analizi (elle maç, isteğe bağlı oranlar) |
| Gol Pazarları | Gol Pazarları: tarama, maç analizi ve oran girişi, kayıt, veri kapsamı, model doğrulama, sanal takip, CSV, zincir denetimi |
| Güç Sıralaması | Güç Sıralaması ve puan durumu |
| Geriye Dönük Test | Geriye Dönük Test |
| Veri | Veri (lig seçimi, profil, güncelleme, yüklü veriler) |
| Kaynak koşulları | Onay penceresi |
| Ayarlar, Hakkında | Ayarlar, Hakkında |

**Yalnızca masaüstünde kalanlar:** GitHub tarihsel arşivi, Dizi Araştırması ve Araştırma Çalışma Alanı. Bunlar
uzun süren, çok pencereli araştırma araçlarıdır. Web sayfalarında bu durum yazılıdır.

## Kurallar masaüstüyle aynı

Ortak kod `bahis_tahmin/core.py` dosyasındadır. Masaüstü (`ui/controller.py`) ve web (`web/state.py`) aynı işlevleri
çağırır:

- `update_work`: güncelleme ve (hak doğrulandıysa) eğitim.
- `retrain_work` ve `train_goal`: yeniden eğitim.
- `training_block_codes`: kişisel kullanım beyanı olmadan eğitim yapılmaz.
- `apply_consent`: beyan, onayı olmayan kaynak için kaydedilmez.
- `AppCore.refresh_predictions`: her tahmin ortak veri uygunluk kontrolünden geçer.
- `prediction_rows`: "Uyarılı" maçta oran ve beklenen değer gösterilmez.

Gol pazarlarında kayıt anında karar yeniden hesaplanır. Uygun olmayan maç kaydedilemez. Biçimlendirme (`fmt.py`),
renkler (`palette.py`), grafikler (`plots.py`), gol pazarı etiketleri (`goals/display.py`) ve Hakkında metni
(`about_text.py`) iki arayüzde ortaktır.

**İkisi aynı anda açıksa:** masaüstünde ayar, veri veya model değişirse web arayüzü bir sonraki sayfa açılışında
hepsini yeniden yükler. Web arayüzünün kendi kaydı yeniden yüklemeye yol açmaz. Aynı anda iki pencerede birden
güncelleme veya eğitim başlatmayın.

## Güvenlik

| Önlem | Neye karşı |
|---|---|
| Varsayılan adres 127.0.0.1 | Ağdaki başka cihazlar erişemez |
| Yerel modda `Host` başlığı denetimi | DNS yeniden bağlama (başka bir sitenin tarayıcınız üzerinden sunucuya ulaşması) |
| Her POST'ta oturuma bağlı CSRF anahtarı, `SameSite=Strict` çerez | Başka bir sitenin onay vermesi, güncelleme başlatması, ayar değiştirmesi |
| Paylaşımda zorunlu parola (sabit süreli karşılaştırma, hatalı denemede 1 sn bekleme) | Ağdaki başka kişiler |
| Girişten sonra yalnızca uygulama içi adrese yönlendirme | Açık yönlendirme |
| İçerik güvenlik politikası (`script-src 'self'`, satır içi betik yok), `X-Frame-Options: DENY`, `no-store` | Betik enjeksiyonu, çerçeveleme, önbellekte kalan sayfalar |
| Takım adları dahil tüm metinler kaçışlı | Veri kaynağından gelen HTML |
| Grafikler `<img>` içinde SVG veri adresi | SVG içindeki metin betik olarak çalışamaz |

Oturum anahtarı her çalıştırmada yeniden üretilir. Sunucu kapanınca bütün oturumlar geçersiz olur.

## Teknik

- **Sunucu:** Flask uygulaması, Waitress ile (8 iş parçacığı). Waitress yoksa Flask'ın kendi sunucusu kullanılır.
- **Uzun işler:** tek arka plan iş parçacığı (`web/jobs.py`). Aynı anda tek iş çalışır; ikinci istek "Başka bir işlem
  sürüyor" yanıtını alır. Tarayıcı `/api/is` adresinden ilerlemeyi okur.
- **Sanal takip:** SQLite bağlantısı her istekte açılıp kapanır (`AppCore.ledger`), iş parçacıkları arasında
  paylaşılmaz.
- **Paketler:** `flask>=3.0,<4` ve `waitress>=3.0,<4` (`requirements.txt`). Masaüstü bunlara ihtiyaç duymaz.
- **.exe:** `BahisTahmin.spec` web şablonlarını ve stil dosyalarını da pakete ekler (`BahisTahmin.exe web` için).
  .exe pencere uygulaması olarak derlendiği için adres satırları ve parola sorusu görünmez. Bu yüzden web için
  `web_baslat.bat` önerilir; .exe ile web modu Windows'ta ayrıca denenmedi.

## Testler

`tests/test_web.py` (17 test, SENTETİK veri, ağ isteği yok):

- ilk açılışta bütün sayfalar;
- yerel ad denetimi, CSRF ve güvenlik başlıkları;
- parolalı mod ve açık yönlendirme engeli;
- parolasız paylaşımın reddi;
- onay ve beyan kuralları;
- onay olmadan güncellemenin başlamaması;
- ayarların doğrulanması ve masaüstüyle aynı dosyaya yazılması;
- masaüstündeki değişikliklerin fark edilmesi (kendi kaydı yeniden yükleme başlatmaz);
- güncelleme işi ve iş yürütücüsü;
- doğrulanmamış veride olasılık yerine neden;
- uygun tahminler, maç ayrıntısı ve en olası seçimler;
- takım adlarının kaçışlanması;
- elle analiz;
- genel bakış, güç sıralaması ve geriye dönük test;
- gol pazarlarında tarama, oran, kayıt, CSV ve zincir;
- uygun olmayan maçın kaydının reddi.

Gerçek veriyle tarayıcı denetimi (Playwright, 1440 px ve 390 px telefon genişliği) şunları gösterdi:

- bütün sayfalar açılıyor;
- konsol hatası yok;
- telefonda yatay taşma yok;
- eğitim web arayüzünden başlatılıp tamamlanıyor.
