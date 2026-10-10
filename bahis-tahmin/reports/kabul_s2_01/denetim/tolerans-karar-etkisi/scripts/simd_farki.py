"""numpy SIMD dağıtımı (AVX-512 açık/kapalı) ufunc sonuçlarını değiştiriyor mu? Kullanım: python simd_farki.py <kaydet.npy | karsilastir a.npy b.npy>"""
import sys
import numpy as np
if sys.argv[1] == "karsilastir":
    a, b = np.load(sys.argv[2]), np.load(sys.argv[3])
    names = ["exp", "log", "log1p", "expm1", "power", "sqrt"]
    print({n: int((a[i] != b[i]).sum()) for i, n in enumerate(names)}, "n=", a.shape[1])
else:
    rng = np.random.default_rng(0)
    x = rng.uniform(-8, 8, 2_000_000); y = rng.uniform(1e-3, 50, 2_000_000)
    np.save(sys.argv[1], np.stack([np.exp(x), np.log(y), np.log1p(y), np.expm1(x / 8), np.power(y, 1.7), np.sqrt(y)]))
