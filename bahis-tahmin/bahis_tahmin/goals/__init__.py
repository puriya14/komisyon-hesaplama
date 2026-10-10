"""Gol pazarları analiz motoru.

Öncelikli pazarlar:
  A = BTTS_BOTH_HALVES_YES  (her iki takım da her iki yarıda gol atar)
  B = FT_OVER_3_5           (maç sonu toplam gol 3,5 üst)
  C = FH_OVER_1_5           (ilk yarı toplam gol 1,5 üst)

A gerçekleşirse B ve C de gerçekleşir; bu ilişki etiketlerde ve olasılıklarda korunur.
"""
