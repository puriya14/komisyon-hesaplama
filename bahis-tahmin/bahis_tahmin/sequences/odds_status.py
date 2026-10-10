"""Araştırmadaki oranların statü etiketi (S2-KABUL-01 oran denetimi).

Araştırmadaki 1X2 oranları (ayna veri seti; README'ye göre Bet365) maç başına yayımlanma/alınma zamanı taşımaz.
Piyasa kontrolleri (S0p, 7b/5, F6, MODEL_PIYASA_FARKI) yalnızca geçmişe dönük referanstır; karar anında erişilebilir
fiyat olduğu gösterilemez. Bu sabitler ``config`` dışında tutulur: ``config`` içindeki büyük harfli adlar ön-kayıtlı
parametre özetine girer ve bir etiket eklemek ön-kaydı değiştirmemelidir.
"""

ODDS_STATUS = "HISTORICAL_REFERENCE_ONLY"
ODDS_STATUS_NOTE = ("Oranlar HISTORICAL_REFERENCE_ONLY: maç başına zaman damgası yok; açılış/kapanış niteliği ve "
                    "bahisçi bilgisi yalnızca ayna README beyanına dayanıyor (doğrulanmadı).")
