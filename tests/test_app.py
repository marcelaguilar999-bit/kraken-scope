import json
import os
import tempfile
import unittest
from unittest import mock

import app


def velas_sinteticas(n=40):
    return [
        {"t": i, "open": 100.0, "high": 101.0, "low": 99.0,
         "close": 100.0, "volume": 10.0}
        for i in range(n)
    ]


class AnaliticaTests(unittest.TestCase):
    def test_excursion_separa_largo_y_corto_y_excluye_vela_de_entrada(self):
        velas = velas_sinteticas()
        # Un extremo enorme en la vela de entrada no debe contarse como excursión
        # posterior. En las siguientes barras el recorrido es simétrico y pequeño.
        # Se coloca en la primera entrada posible para que no sea, legítimamente,
        # una vela futura de ninguna entrada anterior dentro de la muestra.
        velas[1]["low"] = 50.0
        resultado = app.excursion_adversa(velas, k_barras=3)
        self.assertIn("largo", resultado)
        self.assertIn("corto", resultado)
        self.assertLess(resultado["largo"]["p95"], 2.0)
        self.assertLess(resultado["corto"]["p95"], 2.0)

    def test_perfil_cubre_al_menos_setenta_por_ciento(self):
        niveles, _, va_lo, va_hi = app.perfil_volumen(velas_sinteticas(), n_niveles=20)
        total = sum(n["vol"] for n in niveles)
        dentro = sum(n["vol"] for n in niveles if va_lo <= n["precio"] <= va_hi)
        self.assertGreaterEqual(dentro / total, 0.70)

    def test_cuadrantes(self):
        self.assertEqual(app.cuadrante(0.01, 0.01)[0], "dinero nuevo comprando")
        self.assertEqual(app.cuadrante(0.01, -0.01)[0], "cierre de cortos")
        self.assertEqual(app.cuadrante(-0.01, 0.01)[0], "dinero nuevo vendiendo")
        self.assertEqual(app.cuadrante(-0.01, -0.01)[0], "liquidación de largos")


class PersistenciaTests(unittest.TestCase):
    def test_registro_oi_preserva_otros_simbolos(self):
        with tempfile.TemporaryDirectory() as td:
            ruta = os.path.join(td, "oi.json")
            with open(ruta, "w") as f:
                json.dump({"PF_ETHUSD": [[1.0, 2.0, 3.0]]}, f)
            with mock.patch.object(app, "REGISTRO_OI", ruta), \
                 mock.patch.object(app.time, "time", return_value=10_000.0):
                app.registrar_oi("PF_XBTUSD", 10.0, 100.0)
            with open(ruta) as f:
                guardado = json.load(f)
            self.assertIn("PF_ETHUSD", guardado)
            self.assertIn("PF_XBTUSD", guardado)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()

    def test_salud(self):
        r = self.client.get("/api/salud")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"estado": "ok", "credenciales": False})

    def test_intervalo_invalido_no_llama_a_kraken(self):
        with mock.patch.object(app, "kraken") as llamada:
            r = self.client.get("/api/mercado?intervalo=7")
        self.assertEqual(r.status_code, 400)
        llamada.assert_not_called()

    def test_intervalo_no_numerico(self):
        r = self.client.get("/api/mercado?intervalo=cinco")
        self.assertEqual(r.status_code, 400)

    def test_par_desconocido(self):
        with mock.patch.object(app, "kraken", return_value={"XXBTZUSD": {"wsname": "XBT/USD"}}):
            r = self.client.get("/api/mercado?par=NO_EXISTE&intervalo=5")
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
