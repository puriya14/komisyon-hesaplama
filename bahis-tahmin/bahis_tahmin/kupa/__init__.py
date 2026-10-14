"""Kupa ve Avrupa maçları (KUPA-01): UEFA Şampiyonlar Ligi, Avrupa Ligi, Konferans Ligi (elemeleri dahil), süper
kupalar ve yurt içi kupalar.

Lig modeli (``models``) bir ligin takımlarını yalnızca kendi aralarında karşılaştırır; farklı liglerin takımlarının
oynadığı maçlarda bu güçler ortak bir ölçekte değildir. Bu paket, bütün lig ve kupa maçlarından ligler arası ortak bir
güç ölçeği kuran ayrı bir model (``kupa.model``), kupa verilerinin kaynak okuyucularını (``kupa.openfootball``,
ESPN), takım kimliği eşlemesini (``kupa.kimlik``), veri uygunluk kurallarını (``kupa.uygunluk``) ve motoru
(``kupa.motor``) içerir. Lig modeli ve lig maçlarının verisi değişmez.
"""
