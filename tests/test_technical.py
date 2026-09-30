import unittest

from technical import (analizar_estructura, canal_donchian, detectar_hch,
                       detectar_pivotes, estructura_dow, mapa_volumen,
                       pullback_medias)


def velas_desde_precios(precios):
    return [{"t": i, "open": p, "high": p + 0.2, "low": p - 0.2,
             "close": p, "volume": 10 + i} for i, p in enumerate(precios)]


class EstructuraTests(unittest.TestCase):
    def test_dow_alcista(self):
        pivotes = [
            {"tipo": "bajo", "i": 1, "t": 1, "precio": 90.0, "volumen": 1},
            {"tipo": "alto", "i": 2, "t": 2, "precio": 100.0, "volumen": 1},
            {"tipo": "bajo", "i": 3, "t": 3, "precio": 95.0, "volumen": 1},
            {"tipo": "alto", "i": 4, "t": 4, "precio": 110.0, "volumen": 1},
        ]
        d = estructura_dow(pivotes, ultimo=108, atr=2)
        self.assertEqual(d["estado"], "alcista")
        self.assertEqual(d["confirmacion"], 110.0)
        self.assertEqual(d["invalidacion"], 95.0)

    def test_detecta_hch_superior(self):
        pivotes = [
            {"tipo": "alto", "i": 2, "t": 2, "precio": 110.0, "volumen": 12},
            {"tipo": "bajo", "i": 4, "t": 4, "precio": 100.0, "volumen": 10},
            {"tipo": "alto", "i": 7, "t": 7, "precio": 122.0, "volumen": 15},
            {"tipo": "bajo", "i": 10, "t": 10, "precio": 101.0, "volumen": 10},
            {"tipo": "alto", "i": 12, "t": 12, "precio": 111.0, "volumen": 11},
        ]
        p = detectar_hch(pivotes, ultimo=99.0, atr=2.0, ultimo_indice=14)
        self.assertEqual(p["nombre"], "Hombro-cabeza-hombro")
        self.assertEqual(p["estado"], "confirmado")
        self.assertEqual(p["sesgo"], "corto")
        self.assertLess(p["objetivo"], p["confirmacion"])

    def test_detecta_hch_invertido_formandose(self):
        pivotes = [
            {"tipo": "bajo", "i": 2, "t": 2, "precio": 90.0, "volumen": 12},
            {"tipo": "alto", "i": 4, "t": 4, "precio": 100.0, "volumen": 10},
            {"tipo": "bajo", "i": 7, "t": 7, "precio": 78.0, "volumen": 15},
            {"tipo": "alto", "i": 10, "t": 10, "precio": 99.0, "volumen": 10},
            {"tipo": "bajo", "i": 12, "t": 12, "precio": 89.0, "volumen": 11},
        ]
        p = detectar_hch(pivotes, ultimo=96.0, atr=2.0, ultimo_indice=14)
        self.assertEqual(p["nombre"], "Hombro-cabeza-hombro invertido")
        self.assertEqual(p["estado"], "formándose")
        self.assertGreater(p["objetivo"], p["confirmacion"])

    def test_mapa_volumen_compara_zona_actual(self):
        perfil = {"niveles": [
            {"precio": 98.0, "vol": 10.0}, {"precio": 99.0, "vol": 20.0},
            {"precio": 100.0, "vol": 50.0}, {"precio": 101.0, "vol": 15.0},
            {"precio": 102.0, "vol": 40.0}], "poc": 100.0}
        m = mapa_volumen(perfil, 100.1)
        self.assertGreater(m["volumen_relativo_actual"], 2.0)
        self.assertEqual(m["poc"], 100.0)

    def test_analisis_no_inventa_patron_en_serie_plana(self):
        velas = velas_desde_precios([100.0] * 50)
        perfil = {"niveles": [{"precio": 100.0, "vol": 10.0}],
                  "poc": 100.0, "va_lo": 99.0, "va_hi": 101.0}
        a = analizar_estructura(velas, perfil, 100.0, 1.0)
        self.assertIsNone(a["patron"])
        self.assertGreaterEqual(len(a["metodos"]), 8)

    def test_donchian_expone_ambos_limites(self):
        velas = velas_desde_precios(list(range(100, 130)))
        d = canal_donchian(velas, ultimo=129.1, atr=1.0)
        self.assertEqual(d["n"], 20)
        self.assertGreater(d["alto"], d["bajo"])
        self.assertTrue(d["cerca_alto"])

    def test_pullback_reconoce_medias_alineadas(self):
        velas = velas_desde_precios([100 + i * 0.5 for i in range(140)])
        m20 = sum(v["close"] for v in velas[-20:]) / 20
        p = pullback_medias(velas, ultimo=m20, atr=2.0)
        self.assertEqual(p["alineacion"], "alcista")
        self.assertEqual(p["sesgo"], "largo")
        self.assertTrue(p["cerca"])


if __name__ == "__main__":
    unittest.main()
