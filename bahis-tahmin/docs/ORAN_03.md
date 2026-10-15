# ORAN-03: Sanal takipte kapanış oranı ve CLV

İstek: "1, 2 ve 3'ü sırayla yap" — üçüncü iş. İlk ikisi [`ORAN_01_02.md`](ORAN_01_02.md) belgesindedir.

## Neden

Kapanış oranı, maç başlamadan hemen önceki son orandır. Piyasanın en çok bilgiyi topladığı andır.

- Bir bahis kapanış oranından **yüksek** bir oranla alındıysa (pozitif CLV), piyasa sonradan o tarafa kaydı demektir.
- Uzun vadede düzenli pozitif CLV, kazandıran bir yöntemin en iyi erken işaretidir. Sonuçlar (kazandı/kaybetti) çok
  gürültülüdür; yüzlerce bahis gerekir. CLV, aynı soruya çok daha az bahisle yanıt verir.

ORAN-01, modelin 2,5 Üst/Alt'ta piyasaya bilgi eklemediğini gösterdi. Uygulamanın kendi pazarları (iki yarıda KG,
3,5 Üst, İY 1,5 Üst) için geçmiş oran yok; depoda kapanış oranı da yok. Bu pazarları sınamanın yolu ileriye dönük CLV
takibidir.

## Ne eklendi

**Kapanış oranı kaydı** (sanal takip veritabanında ayrı tablo, şema sürümü 2):

- **Değiştirilemez:** kayıt güncellenemez, silinemez. Her kayıt öncekinin özetini taşır; zincir doğrulaması
  ("Kayıt zincirini doğrula", `gol-sanal`) bu tabloyu da denetler.
- **Düzeltme:** aynı değerler tekrar girilirse kayıt eklenmez. Farklı bir oran, karşı oran ya da şirket önceki kaydı
  değiştirir; bu yalnızca **gerekçeyle**, yeni kayıt olarak eklenebilir. Eski kayıt silinmez.
- **Karar oranı değildir:** kapanış oranı karar motoruna girmez. Karar oranları ayrı tabloda kalır.
- **İki taraf:** bir pazarın kapanış oranıyla birlikte karşı tarafın (ör. 3,5 Üst ile 3,5 Alt) aynı andaki oranı da
  girilebilir. Karşı tarafa bahis yapılmışsa aynı kayıt yer değiştirerek kullanılır.
- **Eski dosyalar:** önceki sürümle oluşturulmuş sanal takip dosyası açılınca tablo boş olarak eklenir. Eski
  kayıtlar değişmez.

**CLV hesabı** (`bahis_tahmin/goals/clv.py`):

- **Ham CLV** = alınan oran / kapanış oranı − 1. Kapanış oranı şirket marjını içerdiği için iyimserdir.
- **Marjsız CLV** = alınan oran × marjsız kapanış olasılığı − 1. Yalnızca karşı taraf oranı da girildiyse hesaplanır.
  Kapanış piyasası doğruysa bu, bahsin beklenen getirisidir. **Asıl ölçüt budur.**
- **Zamanlama:** kapanış oranı karar anından **önce** gözlenmişse karşılaştırma yapılmaz (kapanış olamaz). Maç saati
  biliniyorsa satırda "maçtan 12 dk önce" gibi bir etiket görünür. Maçtan 1 saatten erken girilen oran "erken;
  kapanış olmayabilir" diye işaretlenir ve özette sayılır.
- **Özet:** yalnızca sanal bahisler (stake > 0, oranlı) sayılır:
  - kaç bahsin kapanış oranı var ve kaçı karşılaştırılabildi,
  - ortalama ham CLV ve kapanışı geçen bahis payı,
  - ortalama marjsız CLV ve yaklaşık %95 aralığı (az bahiste geniştir).
- **Satır bazında:** oranı olan her kayıtta (bahis olmasa da) karşılaştırma görünür.

## Kullanım

**Masaüstü:** Gol Pazarları → Sanal takip → "Kapanış oranı (CLV)" kutusu.

1. Listeden oranlı kaydı seçin (maç, pazar, alınan oran; girilmişse kapanış oranı da yazar).
2. Kapanış oranını ve varsa karşı tarafın oranını girin, şirket adını yazın.
3. "Kapanış oranını kaydet"e basın.

Düzeltmede gerekçe alanını doldurun. Özet satırı kutunun altında, CLV sütunları tabloda ve CSV'de görünür.

**Web:** Gol Pazarları → Sanal takip → "Kapanış oranı gir (CLV)". Alanlar ve kurallar masaüstüyle aynı.

**CLI:**

```
python -m bahis_tahmin gol-kapanis-ekle                       # kapanış oranı girilebilecek kayıtlar
python -m bahis_tahmin gol-kapanis-ekle --olay "E0|2026-10-18|Arsenal|Chelsea" --pazar FT_OVER_3_5 \
    --oran 2.90 --karsi 1.40 --sirket "Şirket"                # düzeltmede: --not "gerekçe"
python -m bahis_tahmin gol-oran-ice-aktar --csv kapanis.csv --kapanis --uygula   # CSV'den kapanış oranları
python -m bahis_tahmin gol-sanal                              # özet + CLV satırı + zincir doğrulaması
```

- **CSV ile içe aktarma:** oran CSV'siyle aynı biçim kullanılır. `quoted_at`, kapanış oranının gözlendiği an
  sayılır.
- **Eşleme:** aynı olay, sağlayıcı ve şirketten en fazla 10 dk arayla tümleyen pazarın oranı da varsa karşı taraf
  olarak eşlenir.
- **Kuru çalıştırma:** `--uygula` olmadan hiçbir şey yazılmaz.

**Pratik öneri:**

- Kaydettiğiniz her oranlı karar için maç başlamadan 5–10 dakika önce aynı şirketin iki taraf oranını girin. Sonuç
  beklemeden yöntemin piyasayı yenip yenmediği görülür.
- Kapanış oranını mümkünse keskin bir şirketten alın; keskin şirketin kapanışı daha iyi bir ölçüttür.
- ORAN-02'ye göre bahis oranı olarak alınabilecek en iyi oran girilmeli.

## Sınırlar

- **Elle giriş:** kapanış oranları elle ya da CSV'yle girilir; uygulama oran toplamaz. Girilen anın gerçekten kapanış
  olup olmadığı yalnızca zamanlama etiketiyle gösterilir.
- **Maçtan sonra giriş:** bir sitedeki kapanış oranı maçtan sonra girilirse gözlem anı giriş anıdır; etiket "maç
  başladıktan sonra girildi" olur. Değer kullanıcının beyanıdır.
- **Az bahis:** aralık genişse sonuç yorumlanmamalıdır.
- **CLV kazanç garantisi değildir:** pozitif CLV piyasanın sonradan size hak verdiğini gösterir. Tek başına kazanç
  garantisi değildir.

## Testler

`tests/test_oran_03.py` (12 test), ayrıca `test_ui.py` ve `test_web.py` içindeki Gol Pazarları akış testleri.
Sınananlar:

- **Hesap:** ham ve marjsız CLV, zamanlama etiketleri (karar öncesi, erken, 60 dk sınırı, maç sonrası, saat
  bilinmiyor, zaman dilimi yok).
- **Kayıt:**
  - değiştirilemezlik ve zincir (sessiz eklenen satır tespit edilir),
  - aynı değerin tekrar eklenmemesi; oran, karşı oran ya da şirket değişince gerekçe zorunluluğu,
  - geçersiz oran ve zaman,
  - karşı taraf yönüne çevirme ve en yeni kullanılabilir kayıt,
  - eski dosyanın kayıtlar değişmeden yeni şemaya geçmesi.
- **Özet:** yalnızca bahisler sayılır; karar anından önceki kapanış dışarıda kalır; erken sayısı; %95 aralığı.
- **Tablo, CSV ve aday listesi.**
- **CSV'den kapanış:** tümleyen eşleme, 10 dk sınırı, tekrar içe aktarma, karar oranı tablosuna yazmama.
- **CLI, masaüstü ve web:** giriş, gerekçesiz düzeltmenin reddi, özet satırı; web'de CSRF zorunluluğu.

**Mutasyon denetimi:** kodu kasıtlı bozan 30 değişiklik denendi. İlk turda üçü yakalanmadı:

- maç başladıktan hemen sonraki girişi "maçtan önce" saymak,
- yalnızca karşı oranın değişmesini düzeltme saymamak,
- şirketin değişmesini düzeltme saymamak.

Üçü için test eklendi; son durumda 30'unun hepsi en az bir testi kırıyor.
