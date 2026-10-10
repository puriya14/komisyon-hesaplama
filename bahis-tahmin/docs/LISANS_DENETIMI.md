# Veri kaynakları lisans / kullanım koşulları denetimi

Denetim tarihi: 2026-10-10. Kod karşılığı: `bahis_tahmin/data/source_registry.py`.

**Önemli sınırlama:** Bu denetim, geliştirme ortamının ağ politikası nedeniyle football-data.co.uk ve
the-odds-api.com sitelerine **doğrudan erişilemeden** yapıldı (vekil sunucu 403). Aşağıdaki özetler,
erişilebilen depo lisans dosyalarına ve genel bilgilere dayanır; **hukuki görüş değildir**. Kullanım
hakkı belirsiz kaynaklar varsayılan olarak **kapalıdır** ve yalnızca kullanıcının açık onayıyla,
kişisel ve ticari olmayan analiz için kullanılır.

| Kaynak | Ne için | Lisans durumu | Otomatik indirme | Model eğitimi | Yeniden dağıtım | Uygulamadaki durum |
|---|---|---|---|---|---|---|
| football-data.co.uk | Geçmiş sonuçlar, İY skoru, şut, 1X2 ve 2,5 oranları; fikstür | Açık lisans metni bulunamadı; site "All Rights Reserved" altbilgisi taşıyor; İngiliz/İskoç ligleri için Football DataCo hak iddia eder | Doğrulanamadı → seyrek, önbellekli | Doğrulanamadı | Varsayılmaz (veri yalnızca kullanıcı bilgisayarında) | **Onay gerektirir**; onay yoksa indirilmez |
| GitHub: xgabora/Club-Football-Match-Data | football-data erişilemezse yedek geçmiş veri | Depo MIT; ancak içerik football-data/ClubElo kaynaklı, kaynak koşulları geçerli | GitHub tek dosya | Asıl kaynağa bağlı | Varsayılmaz | **Onay gerektirir** |
| openfootball/football.json | Yedek fikstür | CC0 1.0 | İzinli | İzinli | İzinli | Onay gerekmez |
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

## Açık konular (kullanıcı kararı gerekir)

1. football-data.co.uk koşullarının site üzerinden okunması ve kişisel kullanımın uygun olduğunun teyidi.
2. Ticari kullanım/yeniden dağıtım planlanıyorsa yazılı izin veya lisanslı veri sağlayıcı.
3. Gerçek oranlı geçmiş getiri doğrulaması isteniyorsa A/B/C pazarlarını kapsayan, kullanım hakkı açık
   (büyük olasılıkla ücretli) bir oran kaynağı — bu, kullanıcının açık onayı olmadan başlatılmadı.
