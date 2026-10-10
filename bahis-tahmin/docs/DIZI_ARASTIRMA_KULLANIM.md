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
```

- `dizi-olay`: Mod A (tanımlayıcı, olay seçimli). `--iyms` ham kod (`2/1`, `X/1`, `0/2` …; `0` ve `X` beraberlik);
  `--hedef` takım perspektifi hedefi; `--kart N` N'inci olayın kartını yazdırır.
- `dizi-kapsam`: veri boşluklu lig-sezonlar, incelenemeyen alanlar, hükmen olabilir satırlar, ad eşlemeleri.

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

- Uygulama klasöründe (`%LOCALAPPDATA%\BahisTahmin\dizi_arastirma\`): araştırma sonuçları ve manifesti.
  İleriye dönük sanal takip için ayrı bir defter (`dizi_arastirma.sqlite`) kullanılır; gerçek para kullanılmaz.
- Depoda: `reports/experiments.jsonl` (ön-kayıt ve tüm deneyler), `reports/dizi_*.json` (sonuçlar),
  `reports/dizi_sozlesme_kirmizi_takim.json` (sözleşme incelemesi).
