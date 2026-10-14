"""Hakkında metni (Qt'den bağımsız): masaüstü ve web arayüzü aynı metni gösterir."""

ABOUT_HTML = """
<h2>Bahis Tahmin {version}</h2>
<p>Tamamen ücretsiz ve açık verilerle çalışan, veriye dayalı futbol maç tahmin uygulaması.</p>

<h3>Yöntem</h3>
<ol>
<li><b>Elo güç puanları</b> – her maçtan sonra güncellenen, gol farkı ve ev sahibi avantajını hesaba katan reyting.</li>
<li><b>Dixon-Coles gol modeli</b> – takımların hücum/savunma güçleri, eski maçların etkisi zamanla azalacak
şekilde (yarı ömür ≈ 1 yıl) tahmin edilir; düşük skorlar için Dixon-Coles düzeltmesi uygulanır.</li>
<li><b>İsabetli şut modeli</b> – gollerden daha az şansa bağlı olan isabetli şut sayılarıyla (xG benzeri) güç ölçümü.</li>
<li><b>Piyasa reytingi</b> – geçmiş maçların bahis oranlarından takımların piyasa gözündeki gücü.</li>
<li><b>Makine öğrenmesi</b> – yukarıdakiler ve form, dinlenme süresi, lig ortalamaları gibi {n_features} özellikle eğitilen
lojistik regresyon + gradient boosting topluluğu (1X2, 2.5 Alt/Üst, Karşılıklı Gol). Veri azsa model, zaman sırasına
uygun doğrulamayla daha sade bir yapıyı kendisi seçer.</li>
<li><b>Piyasa harmanlama</b> – maçın güncel oranları varsa, model ve piyasa olasılıkları geçmiş performansa göre
ağırlıklandırılarak birleştirilir.</li>
<li><b>Tutarlı skor matrisi</b> – tüm marketler (doğru skor, 1.5/3.5 Alt-Üst, Çifte Şans) nihai olasılıklarla
uyumlu tek bir skor dağılımından hesaplanır.</li>
</ol>
<h3>Gol pazarları (ayrı model)</h3>
<p>İki yarıda da karşılıklı gol, maç sonu 3,5 Üst ve ilk yarı 1,5 Üst; ilk yarı ve ikinci yarı için ayrı takım
güçlerinden kurulan <b>tek bir ortak yarı-gol dağılımından</b> hesaplanır (ikinci yarı, ilk yarı skoruna koşulludur).
Marjinaller zaman sıralı kalibre edilir; pazarlar arası mantıksal ilişkiler (iki yarıda KG ⊆ 3,5 Üst ∩ İY 1,5 Üst)
yapısal olarak korunur. Bu pazarların gerçek oranları ücretsiz veride bulunmadığından geçmiş getiri hesaplanamaz;
öneri yalnızca doğrulanmış model ve sizin girdiğiniz güncel gerçek oranla oluşabilir.</p>
<h3>Kupa ve Avrupa maçları (ligler arası ortak model)</h3>
<p>Şampiyonlar Ligi, Avrupa Ligi, Konferans Ligi (eleme turları ve UEFA Süper Kupa dahil), ulusal kupalar ve süper
kupalar, diğer kıtaların kulüp turnuvaları. Lig modelleri her ligi kendi içinde ölçer; farklı liglerin takımları aynı
ölçekte olmadığından kupa maçları <b>ayrı bir ortak modelden</b> tahmin edilir: bütün lig ve kupa maçlarından, zamanla
azalan ağırlıkla kurulan bir Poisson gol modeli (takım güçleri ligin gücüne göre ayarlanır; ligler kupa maçlarıyla
birbirine bağlanır; tarafsız sahada iç saha avantajı uygulanmaz). Skorlar 90 dakikadır (uzatma ve penaltılar sayılmaz).
Model her doğrulama grubu (UEFA turnuvaları, yurt içi kupalar, diğer kıtalar) için ayrı ölçülür: haftalık
ileriye dönük (model o maçları görmeden) tahminler önceki sezonların kupa maçı oranlarından anlamlı biçimde daha
iyiyse <b>"doğrulandı"</b> sayılır; doğrulanmayan grupların tahminleri gösterilir ama bahis adayı olmaz. Kupa maçları için
ücretsiz veride piyasa oranı yoktur; Maç Analizi'nde kendi oranlarınızı girerek değer hesaplayabilirsiniz. Gol Pazarları
sayfası kupa maçlarını da kapsar: ortak modelin gol beklentileri, önceki kupa maçlarındaki ilk yarı gol payıyla yarılara
bölünür. Her pazar her doğrulama grubunda ayrı ölçülür; doğrulanmayan pazarlar bahis adayı olmaz.</p>
<p>Tüm başarı ölçümleri <b>sızıntısızdır</b>: her sezon, yalnızca o sezondan önceki verilerle eğitilen bir modelle
tahmin edilmiştir (walk-forward). Uygulamadaki yüzdeler bu gerçekçi testlerden gelir.</p>

<h3>Gerçekçi beklentiler</h3>
<p>Futbolda maç sonucu tahmininde en iyi bahis şirketlerinin bile isabeti ~%50-53'tür; %90 genel isabet mümkün değildir.
Model bir seçime yüksek olasılık verdiğinde bu seçimlerin geçmişte ne sıklıkla gerçekleştiği ölçülür ve gösterilir
(bkz. En Olası Seçimler), fakat bu seçimlerin oranları düşüktür; yüksek olasılık tek başına kâr anlamına gelmez.
Uygulamada "kesin", "garanti" veya "banko" gibi kanıtsız ifadeler kullanılmaz.</p>
<p><b>Yapay zekâ (LLM) kullanımı:</b> Uygulamadaki hiçbir olasılık bir dil modeli tarafından üretilmez. Tüm yüzdeler
yukarıda açıklanan istatistiksel modellerden gelir ve uygulama internetsiz/LLM'siz çalışır.</p>

<h3>Veri kaynakları ve kullanım koşulları</h3>
<ul>
<li><a href="https://www.football-data.co.uk/">football-data.co.uk</a> – maç sonuçları, ilk yarı skorları, istatistikler,
1X2 ve 2.5 Alt/Üst oranları, fikstürler. Ücretsiz indirme sunulur; yeniden kullanım/model eğitimi için açık lisans
metni bulunamadı. <b>Kullanıcı onayı olmadan indirilmez.</b> Model eğitimi ve tahmin için ayrıca kullanıcının
kişisel (ticari olmayan) kullanım beyanı gerekir; beyan ticari kullanım veya yeniden dağıtım hakkı vermez.</li>
<li><a href="https://github.com/xgabora/Club-Football-Match-Data-2000-2025">Club Football Match Data (GitHub)</a> – depo MIT
lisanslı; içerik football-data.co.uk ve ClubElo kaynaklıdır (asıl kaynağın koşulları geçerli). Kullanıcı onayı gerekir.</li>
<li><a href="https://github.com/openfootball/football.json">openfootball/football.json</a> – CC0 (serbest); yedek fikstür kaynağı.
football.json'da güncel sezon dosyası olmayan liglerde (ör. Süper Lig) openfootball'un aynı lisanslı ulusal metin
depoları (<a href="https://github.com/openfootball/europe">europe</a> ve diğerleri) okunur.</li>
<li><a href="https://www.espn.com/soccer/">ESPN skor tablosu</a> – resmi olmayan, belgelenmemiş uç nokta; açık lisans
metni yok. Verileri football-data.co.uk'tan alınamayan ligler için fikstür, sonuç ve sezon takvimi (bu liglerde
openfootball yerine; ESPN'den veri gelmezse openfootball yedeği kullanılır).
<b>Kullanıcı onayı olmadan istek gönderilmez</b>; model eğitimi ve tahmin için ayrıca kişisel kullanım beyanı
gerekir. Takım adları yalnızca maç kanıtıyla eşlenir. Kupa ve Avrupa turnuvalarının içinde bulunulan sezonu da
buradan gelir.</li>
<li><a href="https://github.com/openfootball/champions-league">openfootball/champions-league</a> – CC0 (serbest);
Şampiyonlar Ligi, Avrupa Ligi ve Konferans Ligi'nin (eleme turlarıyla) geçmiş sezon sonuçları. Takımlar ülke kodu ve
uygulamanın doğrulanmış takım adlarıyla eşlenir; eşlenemeyen takım hiçbir lig takımıyla birleştirilmez, ayrı takım
olarak tutulur (maçları bahis adayı olmaz).</li>
</ul>
<p>Veriler yalnızca bilgisayarınızda saklanır ve uygulama ile dağıtılmaz: <code>{home}</code></p>

<h3>Sorumlu bahis</h3>
<p>Bu uygulama bilgi ve analiz amaçlıdır; kazanç garantisi vermez. Bahis bağımlılık yapabilir.
Kaybetmeyi göze alamayacağınız parayla oynamayın, kayıplarınızı kovalamayın. Türkiye'de yalnızca yasal ve lisanslı
kanalları kullanın; 18 yaşından küçükler bahis oynayamaz. Destek için Yeşilay Danışmanlık Merkezi (YEDAM): <b>115</b>.</p>
"""
