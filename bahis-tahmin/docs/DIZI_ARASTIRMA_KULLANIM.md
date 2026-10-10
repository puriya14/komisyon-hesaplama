# Dizi araştırması — kullanım

Bu modül maç sonuçlarının çevresindeki dizileri (olay öncesi/sonrası) ve bunların yıllar içindeki tekrarlarını
**araştırma statüsünde** inceler. Ana tahmin modellerini değiştirmez. Yöntem ve kurallar:
[`DIZI_ARASTIRMA_SOZLESMESI.md`](DIZI_ARASTIRMA_SOZLESMESI.md) (ön-kayıtlı sözleşme).

> Bir ilişkinin bulunması neden-sonuç veya manipülasyon kanıtı değildir; bulunamaması da manipülasyon olmadığını
> kanıtlamaz. Uygulama hiçbir kulübe, oyuncuya veya hakeme etiket vermez ve "şike olasılığı" üretmez.

## Arayüz: "Dizi Araştırması" sayfası

| Sekme | Ne gösterir | Zaman kuralı |
|---|---|---|
| Olay zaman çizgisi (geçmiş) | Seçilen takımın İY/MS olayları (takım perspektifi veya ham kod), olaylar arası maç/gün, sezon geçişi, açık (sansürlü) son aralık; olay kartı: öncesi (5/10), olay, sonrası (1/3/5), rakibin öncesi; pencere durumu, kaynak, kapsam | **Geçmiş inceleme**: olay sonrası bilgi içerir, "olay seçimli, tahmin değil" |
| Benzer diziler (maç öncesi) | Yaklaşan bir maç için, karar anından önce bilinen koşullara benzeyen geçmiş örnekler (başarılı ve başarısız birlikte) | **Maç öncesi**: sonrası bilgisi yoktur |
| Örüntü doğrulama | Ön-kayıtlı aramanın sonuçları: tanım, dönemler, denenen alternatif sayısı, Mod B kartı, yanlışlama kontrolleri, statü | Yalnızca dondurulmuş araştırma kaydından |
| Anomali incelemesi | Temel modele göre sıra dışı tekil maçlar ve alternatif açıklama kontrol listesi | Tahminden ayrı; karar motoruna bağlı değil |
| Veri ve yöntem | Sözleşme sürümü, dönemler, incelenemeyen alanlar, takım kimliği eşlemesi, veri boşluklu lig-sezonlar | — |

"Tüm resmî maçlar" görünümü her zaman gösterilir ve `DATA_QUALITY_BLOCKED` yazar: veri setinde kupa/Avrupa maçı yoktur.

## Komut satırı

```bat
.venv\Scripts\python -m bahis_tahmin dizi-olay --takim "PSV Eindhoven" --iyms 2/1 --kart 0
.venv\Scripts\python -m bahis_tahmin dizi-olay --takim "PSV Eindhoven" --hedef IY_GERIDE_MS_GALIP
.venv\Scripts\python -m bahis_tahmin dizi-kapsam
.venv\Scripts\python -m bahis_tahmin dizi-arastir --isci 3
.venv\Scripts\python -m bahis_tahmin dizi-benzer --takim "PSV Eindhoven"
```

- `dizi-olay`: Mod A (tanımlayıcı, olay seçimli). `--iyms` ham kod (`2/1`, `X/1`, `0/2` …; `0` ve `X` beraberlik);
  `--hedef` takım perspektifi hedefi; `--kart N` N'inci olayın kartını yazdırır.
- `dizi-kapsam`: veri boşluklu lig-sezonlar, incelenemeyen alanlar, hükmen olabilir satırlar, ad eşlemeleri.
- `dizi-arastir`: ön-kayıtlı araştırmanın tamamı (F1–F7 + anomali). S0 soy kaydı ilk çalıştırmada kurulur
  (~20 dk) ve veri/eşleme değişmedikçe önbellekten okunur. Hesaplama bütçesi sabittir: referans süreç R = 1000,
  plasebo 20 tohum × 200 tekrar, bootstrap 1000; açık uçlu arama veya harici API çağrısı yoktur. `--isci` yalnızca
  hızı değiştirir (her tekrar kendi tohumunu kullanır; sonuç işçi sayısından bağımsızdır). Sözleşmenin altında
  tekrar sayısıyla çalıştırma "deneme" olarak uyarı verir.
- `dizi-benzer`: maç öncesi görünüm — takımın yaklaşan maçı için karar anından (maç günü 00:00) önce bilinen
  koşullar ve geçmiş benzer örnekler (gerçekleşen ve gerçekleşmeyen birlikte). Olay sonrası alan yoktur; statü
  yalnızca dondurulmuş araştırma kaydından okunur ve olasılık değiştirilmez.

## Statüler ve "temiz test"

| Statü | Anlamı |
|---|---|
| `EXPLORATORY` | Keşifte bulundu, örneklem dışında sınanmadı (veya test dönemi temiz değil) |
| `INSUFFICIENT_EVIDENCE` | Destek yetersiz, aile düzeltmesinden geçmedi ya da Monte Carlo aralığı 0,05'i içeriyor |
| `NO_ADDED_VALUE` | Örneklem dışında temel modele (S0) ek katkı doğrulanmadı veya piyasa kontrolünde kayboldu |
| `OUT_OF_SAMPLE_SUPPORTED` | Parametre ve test dönemlerinde ayrı ayrı doğrulandı; yanlışlama kontrolleri geçti |
| `PAPER_TRADING` | Örneklem dışı desteklenen örüntünün ileriye dönük sanal takibi |
| `DATA_QUALITY_BLOCKED` | Gerekli veri yok |

Test dönemi bir kez açıldıktan sonra sözleşme, parametre, uygulama kararları veya `sequences` kodu değişirse
sonraki çalıştırmalar "temiz test" sayılmaz: `OUT_OF_SAMPLE_SUPPORTED` otomatik olarak `EXPLORATORY`'ye iner ve
gerekçe kartta yazılır (`manifest.temiz_test`).

## Hedef adları

| Kod | Anlamı |
|---|---|
| `IY_GERIDE_MS_GALIP` | İlk yarıyı geride kapatıp maçı kazanma (maç içi geri dönüş değil: dakika verisi yok) |
| `IY_ONDE_MS_MAGLUP` | İlk yarıyı önde kapatıp maçı kaybetme |
| `HTFT_2_1` | Ham İY/MS: ilk yarıda deplasman önde, maç sonunda ev sahibi galip |
| `HTFT_1_2` | Ham İY/MS: ilk yarıda ev sahibi önde, maç sonunda deplasman galip |

Aynı ham kod ev sahibi ve deplasman için farklı takım davranışıdır: ev sahibinin `HTFT_2_1`'i "İY geride → MS
galip", deplasmanın aynı maçı ise "İY önde → MS mağlup"tur.

## Dosyalar

- Uygulama klasöründe (`%LOCALAPPDATA%\BahisTahmin\dizi_arastirma\`): `son_sonuclar.json` (arayüz özeti),
  `sonuclar_tam.json` (tüm aileler), `manifest.json`, `f1_hipotezler.csv` (başarısızlar dahil 800 hipotez),
  `anomaliler.json` (tekil maç anomali kayıtları — yalnızca yerelde), `deneyler.jsonl`, `s0_soy.pkl`,
  `s0_kalibre.pkl`. Ayrı bir araştırma defteri sınıfı (`dizi_arastirma.sqlite`) vardır ancak şu an hiçbir arayüz/CLI
  akışı bu dosyayı oluşturmaz (düzeltme D-35); A/B/C için ileriye dönük ölçüm gol pazarları defterinde
  `FORECAST_RECORD` olarak tutulur. Gerçek para kullanılmaz.
- Depoda: `reports/experiments.jsonl` (ön-kayıt ve tüm deneyler), `reports/dizi_sonuclar.json`,
  `reports/dizi_f1_hipotezler.csv`, `reports/dizi_sozlesme_kirmizi_takim.json` (sözleşme incelemesi). Depoya tekil
  maç anomali listesi yazılmaz; yalnızca tür/durum/dönem sayıları.

## Geri alma ve veri koruma

> Düzeltme (S2-KABUL-01, belge sürümü 1.1): Önceki sürüm "`dizi_arastirma` klasörünü silin" diyordu. Bu klasör
> önbellek dışında yeniden üretilemeyen araştırma geçmişi ve kayıt defteri içerir; silmek geri alma yöntemi değildir.
> Ayrıntı: [`DIZI_ARASTIRMA_DUZELTMELER.md`](DIZI_ARASTIRMA_DUZELTMELER.md).

`dizi_arastirma` klasöründeki dosyaların sınıfı:

| Dosya | Sınıf | Geri alırken |
|---|---|---|
| `s0_soy.pkl`, `s0_soy.json`, `s0_kalibre.pkl` | Önbellek (veriden yeniden üretilebilir; süre alır) | Silinmesi gerekmez; sorun varsa yedekleyip başka klasöre taşıyın |
| `manifest.json`, `sonuclar_tam.json`, `son_sonuclar.json`, `f1_hipotezler.csv`, `anomaliler.json` | Deney sonucu (o çalıştırmanın kaydı; yeniden çalıştırma "temiz test" değildir) | Silmeyin; arşivleyin |
| `deneyler.jsonl` | Deney geçmişi ve ön-kayıt (yalnızca eklenir) | Silmeyin, düzenlemeyin |
| `dizi_arastirma.sqlite` (varsa; şu an hiçbir akış oluşturmaz) | Değişmez kayıt defteri | Silmeyin, düzenlemeyin |

- Modülü devre dışı bırakmak veri silmeyi gerektirmez: arayüzde Dizi Araştırması sayfasını kullanmamak yeterlidir;
  maç öncesi görünüm `son_sonuclar.json` yoksa yalnızca tanımlayıcı bilgi gösterir.
- Kod: önce `git log` ile ilgili commit aralığını inceleyin, sonra yalnızca o commit'leri tek tek `git revert`
  ile geri alın; toplu revert yapmayın. Modül ana tahmin modellerini, karar motorunu veya mevcut kayıtları
  değiştirmez; üç ana pazarın tahminleri altın regresyon testiyle korunur.
