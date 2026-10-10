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
<p>Tüm başarı ölçümleri <b>sızıntısızdır</b>: her sezon, yalnızca o sezondan önceki verilerle eğitilen bir modelle
tahmin edilmiştir (walk-forward). Uygulamadaki yüzdeler bu gerçekçi testlerden gelir.</p>

<h3>Gerçekçi beklentiler</h3>
<p>Futbolda maç sonucu tahmininde en iyi bahis şirketlerinin bile isabeti ~%50-53'tür; %90 genel isabet mümkün değildir.
Model, bir seçime %90 olasılık verdiğinde bu seçimler geçmişte gerçekten ~%90+ tutmuştur (bkz. Banko sayfası),
fakat bu seçimlerin oranları düşüktür ve yüksek isabet tek başına kâr anlamına gelmez.</p>

<h3>Veri kaynakları (ücretsiz)</h3>
<ul>
<li><a href="https://www.football-data.co.uk/">football-data.co.uk</a> – maç sonuçları, istatistikler, bahis oranları ve fikstürler.</li>
<li><a href="https://github.com/xgabora/Club-Football-Match-Data-2000-2025">Club Football Match Data (GitHub)</a> – football-data.co.uk ve ClubElo kaynaklı yedek veri seti.</li>
<li><a href="https://github.com/openfootball/football.json">openfootball/football.json</a> – yedek fikstür kaynağı.</li>
</ul>
<p>Veriler bilgisayarınızda saklanır: <code>{home}</code></p>

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
