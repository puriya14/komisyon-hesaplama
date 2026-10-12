# S6-PERF-03 — Arşiv görünümünü sonuçları değiştirmeden hızlandırma

## Ne değişti

Tek kaynak ve birleştirilmiş arşiv görünümü (`archive.view`) maçları `archive.unified` ile birleştirir. Darboğaz,
maç başına küçük pandas seçimleriydi. Gerçek arşivde yaklaşık 6.000 maç için şunlar tekrar tekrar yapılıyordu:

- `g[...]`, `g.loc[...]` seçimleri;
- `astype` dönüşümleri;
- `iterrows` döngüleri.

Grup kuralları aynen korunarak döngü sütun listeleri üzerinde düz Python'a çevrildi:

- Grup numarası pandas'ın `groupby(..., sort=True).ngroup()` işlevinden gelir; numaralandırma yineleme sırasıyla
  aynıdır.
- Grup içindeki satır sırası (kaynak önceliği) korunur.
- Anahtarı eksik satır (ör. tarihsiz kayıt) önceden olduğu gibi gruba girmez.

Değişmeyenler:

- Kaynak filtresi birleştirmeden önce uygulanır; tek kaynakta başka kaynaktan alan taşınmaz.
- Takım kimliği eşleme ve kaynak önceliği.
- Tekilleştirme; çelişki ve tarih uyuşmazlığı.
- Alan kökeni, mantıksal İY ve maç kimlikleri.
- Veri özeti ve hak/köken denetimleri.

Yeni önbellek, kalıcı dosya, iş parçacığı veya bağımlılık eklenmedi.

## Eşdeğerlik kanıtı

`tests/test_s6_perf.py`, önceki `unified` gövdesini referans olarak içerir. Yeni çıktı onunla katı biçimde
karşılaştırılır: hücre değeri ve tipi, sütun tipi, satır sırası ve indeks.

Karşılaştırılan girdiler:

- Kenar durumları:
  - tekil ve yinelenen kayıt;
  - çok kaynak;
  - MS ve İY çelişkisi;
  - bir kaynakta eksik İY;
  - gerçek ve mantıksal 0-0;
  - tarih uyuşmazlığı;
  - belirsiz kimlik;
  - aynı gün maçlar;
  - tarihsiz kayıt;
  - boş ve kapalı görünüm.
- 40 sabit tohumlu karışık girdi; karıştırılmış satır sırasıyla da ayrıca karşılaştırılır.

Aşağı akış çıktıları da `A.unified` önceki gövdeyle değiştirilerek aynı girdide karşılaştırılır: görünüm, filtreli
özet, olay kartı ve çoklu olay karşılaştırması.

Not: İnceleme (`review`) satırlarında yedi sıralama anahtarı aynı olan kayıtlar girdi sırasında kalır. Bu önceki
uygulamanın da davranışıdır ve değiştirilmedi.

## Ölçüm aracı

```
python tools/perf_arsiv.py --ev <ARSIV> --takim "Arsenal FC" --kaynak openfootball --olay-dosyasi olaylar.txt \
    --tekrar 5 --cikti olcum.json [--paket-kok <KARSILASTIRILACAK_KOD_KOKU>]
```

Aşamalar ayrı ayrı ölçülür:

| Kod | Aşama |
|---|---|
| A | yükleme ve köken doğrulama |
| B | tek kaynak görünümü |
| C | birleşik görünüm |
| D | takım-maç tablosu |
| E | çoklu olay hesabı |
| F | veri özeti ve JSON |
| S | servis uçtan uca |
| G | CLI uçtan uca |

Çağrı türleri:

- "İlk çağrı": her geçiş yeni bir Python sürecinde yapılır. İşletim sistemi dosya önbelleği temizlenmez; bu soğuk
  disk ölçümü değildir.
- "Tekrar çağrı": geçişler aynı süreçte arka arkaya yapılır; ilk geçiş ısınma sayılır ve istatistiğe katılmaz.

Bellek iki ayrı yöntemle ölçülür:

- tracemalloc: yalnızca Python/numpy tahsislerinin aşama içi tepe değeri. Ayrı bir süreçte çalışır.
- Süreç tepe RSS'i (`ru_maxrss`).

Araç salt okunurdur. Ölçülen süreler hiçbir sonuç JSON'una veya sonuç özetine yazılmaz.
