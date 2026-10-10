"""Hakkında: yöntem, veri kaynakları ve sorumlu bahis."""

from __future__ import annotations

from PySide6.QtWidgets import QTextBrowser

from ... import __version__
from ...config import app_home
from ...models.features import FEATURES
from .base import Page

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
metni bulunamadı. <b>Kullanıcı onayı olmadan indirilmez.</b></li>
<li><a href="https://github.com/xgabora/Club-Football-Match-Data-2000-2025">Club Football Match Data (GitHub)</a> – depo MIT
lisanslı; içerik football-data.co.uk ve ClubElo kaynaklıdır (asıl kaynağın koşulları geçerli). Kullanıcı onayı gerekir.</li>
<li><a href="https://github.com/openfootball/football.json">openfootball/football.json</a> – CC0 (serbest); yedek fikstür kaynağı.</li>
</ul>
<p>Veriler yalnızca bilgisayarınızda saklanır ve uygulama ile dağıtılmaz: <code>{home}</code></p>

<h3>Sorumlu bahis</h3>
<p>Bu uygulama bilgi ve analiz amaçlıdır; kazanç garantisi vermez. Bahis bağımlılık yapabilir.
Kaybetmeyi göze alamayacağınız parayla oynamayın, kayıplarınızı kovalamayın. Türkiye'de yalnızca yasal ve lisanslı
kanalları kullanın; 18 yaşından küçükler bahis oynayamaz. Destek için Yeşilay Danışmanlık Merkezi (YEDAM): <b>115</b>.</p>
"""


class AboutPage(Page):
    title = "Hakkında"
    subtitle = ""

    def __init__(self, controller, parent=None):
        super().__init__(controller, parent)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setHtml(ABOUT_HTML.format(version=__version__, home=app_home(), n_features=len(FEATURES)))
        tb.setMinimumHeight(820)
        self.body.addWidget(tb)
