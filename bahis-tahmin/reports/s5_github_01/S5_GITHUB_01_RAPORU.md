# S5-GITHUB-01 — GitHub veri profili ve tarihsel arşiv: sonuç raporu

Tarih: 2026-10-11 · Başlangıç: `e023aac` (claude/bahis-tahmin) · Kullanım: [`docs/S5_GITHUB.md`](../../docs/S5_GITHUB.md)

Bu rapor yalnızca toplu sayılar içerir. Maç satırı, ham veri, tahmin veya oran listesi yoktur. Gerçek çalıştırma
geçici bir bulut kapsayıcısında, ayrı bir arşiv klasöründe yapıldı. Bu klasör depoya eklenmedi ve kalıcı değildir;
kullanıcının bilgisayarında yeniden üretmek için belgedeki komutlar kullanılır.

## Durumlar

| Durum | Değer |
|---|---|
| GITHUB_TRANSPORT | **WORKING** — github.com (`info/refs`) ve raw.githubusercontent.com; 4 depo sabit commit'ten okundu |
| HISTORICAL_EXPLORER | **WORKING_WITH_REAL_DATA** — openfootball E0 2010/11–2025/26 (16 tamamlanmış sezon) + Hudl 12 maçlık olay örneği |
| CURRENT_E0_DATA | **STALE** — openfootball'da son sonuç 2026-09-20; 2026-10-10 tarihli 6 maçın sonucu yok (uç 2026-10-11'de çözüldü, değişmemiş) |
| MODEL | **BELOW_BASELINE** — bu görevde değiştirilmedi (eğitim yok, eşik/kalibrasyon/özellik değişikliği yok) |

## Kaynaklar (sabit commit'ler, 2026-10-11)

| Kaynak | Commit | Durum |
|---|---|---|
| openfootball/football.json | `e6744429ee39` (pilotla aynı uç) | katalog okundu · şema doğrulandı · sentetik testler geçti · gerçek veri okundu · **tarihsel analiz etkin** |
| datasets/football-datasets | `436a51f15258` | katalog (`datapackage.json`) okundu · şema doğrulandı · sentetik testler geçti · gerçek veri okundu · **tarihsel analiz hak kapsamı nedeniyle kapalı** (yalnızca envanter) |
| xgabora/Club-Football-Match-Data-2000-2025 | `25882a58a736` | mevcut okuyucu · gerçek veri okundu · türetilmiş alanlar ayrıldı · **tarihsel analiz hak kapsamı nedeniyle kapalı** (yalnızca envanter) |
| hudl/open-data | `4b73468fc5b0` | competitions + maç listeleri okundu · olay okuyucusu sentetik testlerden geçti · 12 maçlık gerçek örnek okundu · **araştırma amaçlı tarihsel analiz etkin**; ticari kullanım ve dağıtım yasak; eğitim ve tahmin kapalı |

xgabora kimliği: verilen ad ile README'nin atıf yaptığı `xgabora/Club-Football-Match-Data` adı, git ve raw üzerinde
aynı commit'i veriyor. Hangisinin kanonik ad olduğu doğrulanamadı, çünkü bu oturumda GitHub API'si bu depoya kapalı.
Benzer adlı başka bir depo kullanılmadı.

## Arşiv sayıları

### openfootball E0 (analiz etkin)

- 17 blok: 16 tamamlanmış sezon (2010/11–2025/26) ve içinde bulunulan 2026/27. Toplam 6.064 geçerli maç;
  bunların 6.014'ü tamamlanmış sezonlarda.
- 15 sezon tam (380/380). 2019/20 kısmi: 314 maç. Kaynak dosyada sezonun devamındaki 66 maç 2019-07 olarak
  yanlış yılla yazılmış; okuyucu yılı tahmin edip düzeltmiyor, bu kayıtları karantinaya alıyor (`TARIH_SEZON_DISI`).
- İY: 5.653 gerçek İY skoru ve 411 mantıksal İY 0-0. Mantıksal 0-0 yalnızca MS 0-0 maçlarda kaydedilir ve
  işaretlenir (`openfootball-sonuc-v2` kuralı). Eksik İY 0-0 yapılmadı.
- Dosyaların 11'i pilotun doğrulanmış önbelleğinden, özetleri doğrulanarak kopyalandı (2016/17–2026/27); 6'sı
  GitHub'dan alındı (2010/11–2015/16). Pilot klasöründeki 19 dosyanın SHA-256 özeti çalıştırmadan önce ve
  sonra aynı.

**2024/25 örneği** (CLI `arsiv-ozet --kaynak openfootball --sezon 2024/25`):

| | Evet | Geçerli n | Bilinmiyor |
|---|---|---|---|
| A · İki yarıda da KG | 17 | 380 | 0 |
| B · MS 3,5 Üst | 130 | 380 | 0 |
| C · İY 1,5 Üst | 139 | 380 | 0 |

- İY/MS (n=380): 1/1 97, 1/X 30, 1/2 15, X/1 44, X/X 45, X/2 46, 2/1 14, 2/X 18, 2/2 71.
- Mantıksal İY 0-0: 16 (işaretli). Çelişki 0, inceleme 0, karantina 0.

**16 tamamlanmış sezon ve 2026/27'nin 50 maçı birlikte** (n=6.064):

- A 332, B 1.893, C 2.185.
- Kaynak karantinası: 66 (2019/20 tarih hatası). Çelişki 0, kimlik incelemesi 0.

Bu sayılar tarihsel gerçekleşmedir. Olasılık, model güveni veya bahis avantajı değildir.

### datasets/football-datasets (yalnızca envanter)

- 33 Premier League sezon dosyası: 1993/94–2025/26. Hepsi tam (1993/94 ve 1994/95'te 22 takım, 462 maç).
- Toplam MS 12.704. İY 11.780 (31 sezon; İY 1995/96'dan itibaren var).
- Karantina 0, birebir tekrar 0. Depo oran sütunlarını attığı için gerçek oran yok.
- `datapackage.json` lisansı ODC-PDDL-1.0. Ancak asıl kaynağın (football-data.co.uk) koşulları doğrulanamadığı
  için tarihsel analiz, eğitim ve tahmin kapalı.

### xgabora (yalnızca envanter)

- Toplam 238.858 satır. E0 için 27 sezon bloğu (2000/01–2026/27).
- Kısmi sezonlar: 2003/04 ve 2004/05'te 335'er maç (45'er maç eksik). 2024/25'te 380 maç var, ancak aynı kulüp
  iki farklı adla yazılmış (`Nott'm Forest` / `Nottm Forest`), bu yüzden 21 farklı takım adı görünüyor.
  2026/27'de son maç 2026-08-31 (20 maç).
- Türetilmiş alanlar (Elo, Form3/5, küme olasılıkları) ve piyasa alanları (oranlar) ayrı listelendi; model
  girdisi yapılmaz. README'ye göre Elo kökeni 2025-06-15'ten sonra değişmiştir.

### Hudl / StatsBomb

- `competitions.json`'da 80 kayıt var. Bu uygulamanın liglerine eşlenen yalnızca 2'si:
  - Premier League 2015/16: tam sezon, 380 maç.
  - Premier League 2003/04: yalnızca Arsenal'in 38 maçı (seçili maçlar; tam sezon olarak sunulmadı).
- Olay örneği önceden tanımlı kurala göre seçildi: 2015/16'nın tarih, sonra maç kimliği sırasına göre ilk 12
  maçı. 12/12 maç meta veriyle uzlaştı (2 kendi kalesine gol, uzatma yok). Bu 12 maç openfootball kayıtlarıyla
  aynı İY/MS'yi verdi; birleşik görünümde her biri bir kez sayıldı (bağımsız köken: 2).
- 360 verisi indirilmedi. Bu bir örneklemdir, sezon analizi değildir.

### 30 sezon hedefi

Analiz hakkı olan kaynakla 16 tamamlanmış sezona ulaşıldı (openfootball 2010/11–2025/26; 15'i tam, 2019/20 kısmi).
Hedef karşılanmadı.

Envanterde 33 tamamlanmış sezon var (datasets: MS 33 sezon, İY 31 sezon). Ancak bu kaynağın analiz hakkı
doğrulanmadığı için bu sezonlar kullanılmadı.

## Kapalı işlemler

- datasets ve xgabora: tarihsel analiz, model eğitimi, tahmin gösterimi, ticari kullanım (doğrulanamadı);
  yeniden dağıtım (izin varsayılmaz). Eksik kapsam: asıl kaynağın (football-data.co.uk) bu işlemler için
  koşulları.
- Hudl/StatsBomb: model eğitimi ve tahmin gösterimi (doğrulanamadı); ticari kullanım ve yeniden dağıtım (lisans
  gereği yasak).
- Bütün kaynaklarda: kullanıcı veri deposuna yazma, model eğitimi, eşik/kalibrasyon değişikliği, bahis veya stake
  önerisi, depoların `process.py` betikleri, 360 verisi, football-data.co.uk/.org istekleri (GitHub profilinde).

## Kod ve testler

- Yeni modüller:
  - `bahis_tahmin/data/github_kaynak.py` (taşıma, sürümlü önbellek)
  - `bahis_tahmin/data/statsbomb.py` (olay okuyucusu)
  - `bahis_tahmin/archive.py` (arşiv, birleşik görünüm, özet)
  - `bahis_tahmin/ui/pages/archive_panel.py` (Veri sayfası bölümü)
- Değişenler:
  - `data/parsers.py` (datasets okuyucusu)
  - `data/source_registry.py` (iki kaynak kaydı ve işlem bazında arşiv kapsamı)
  - `data/sources.py` (izinli adres listesi, elle yönlendirme denetimi, eski kopya sayımı)
  - `data/store.py` (`profile="github"`)
  - `config.py` (`data_profile`)
  - `ui/controller.py`, `ui/pages/data.py`, `ui/pages/sequences.py` (olay kartı biçimlendirmesinin ortak
    kullanımı)
  - `ui/pages/goals.py` (iki yeni kaynağın kaynak tablosundaki durumu: "Yalnızca GitHub arşivi")
  - `cli.py` (`update --profil`, `arsiv-*`)
- `tests/test_s5_github.py`: 32 sentetik test. Gerçek ham veri veya ağ gerektirmez.
- `tests/test_ui.py::test_goals_page`: kaynak tablosundaki beklenen satır sayısı 5'ten 7'ye güncellendi. İki yeni
  kaynağın durum metni için ayrıca doğrulama eklendi. Bu, S4'teki 4 → 5 değişikliğiyle aynı türde bir
  güncellemedir; hiçbir doğrulama kaldırılmadı.
- İlk tam koşuda 1 test başarısız oldu (bu satır sayısı). Düzeltmeden sonra temiz kopyada tam paket yeniden
  çalıştırıldı: **483 geçti, 1 atlandı** (atlanan test önceden vardı; ağ testi).
- Hiçbir test atlanmadı, işaretlenmedi veya silinmedi; hiçbir tolerans gevşetilmedi.
