#!/bin/bash
# OpenBLAS çekirdek türü × iş parçacığı × numpy SIMD (AVX-512 açık/kapalı) matrisi; her koşu ayrı süreç, sıralı.
O=$1
PY=/home/user/venv-bahis/bin/python
for npy in all nov4; do
 for ct in auto Haswell SkylakeX Sandybridge Nehalem Zen Prescott; do
  for th in 1 4; do
   tag="ct-${ct}_th-${th}_npy-${npy}"
   env -u OPENBLAS_CORETYPE -u NPY_DISABLE_CPU_FEATURES PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=$th OMP_NUM_THREADS=$th \
     $( [ "$ct" != auto ] && echo OPENBLAS_CORETYPE=$ct ) \
     $( [ "$npy" = nov4 ] && echo "NPY_DISABLE_CPU_FEATURES=X86_V4" ) \
     $PY $O/scripts/hesap_current.py $O/kod/bahis-tahmin $O/cikti/run_$tag.json $tag
  done
 done
done
