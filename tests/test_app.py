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

    def test_precio_real_incluye_bid_ask_y_edad(self):
        trades = [["101.5", "0.2", 999.5, "b"]]
        libro = {"bids": [["101.0", "2", 999.7]],
                 "asks": [["102.0", "3", 999.8]]}
        p = app.resumen_precio_real(trades, libro, ahora=1000.0)
        self.assertEqual(p["ultimo_trade"], 101.5)
        self.assertEqual(p["medio"], 101.5)
        self.assertAlmostEqual(p["edad_trade_ms"], 500.0)
        self.assertAlmostEqual(p["edad_libro_ms"], 200.0)

    def test_mapa_calor_excluye_estables_y_conserva_mover_con_volumen(self):
        pares = {
            "XXBTZUSD": {"wsname": "XBT/USD", "altname": "XBTUSD", "status": "online"},
            "XETHZUSD": {"wsname": "ETH/USD", "altname": "ETHUSD", "status": "online"},
            "QNTUSD": {"wsname": "QNT/USD", "altname": "QNTUSD", "status": "online"},
            "USDTZUSD": {"wsname": "USDT/USD", "altname": "USDTUSD", "status": "online"},
        }

        def ticker(ultimo, apertura, volumen, vwap, bajo, alto):
            return {"c": [str(ultimo)], "o": str(apertura),
                    "v": ["0", str(volumen)], "p": ["0", str(vwap)],
                    "l": ["0", str(bajo)], "h": ["0", str(alto)]}

        tickers = {
            "XXBTZUSD": ticker(105, 100, 100_000, 102, 95, 108),
            "XETHZUSD": ticker(202, 200, 20_000, 201, 190, 210),
            "QNTUSD": ticker(130, 100, 3_000, 110, 95, 135),
            "USDTZUSD": ticker(1, 1, 500_000_000, 1, .99, 1.01),
        }
        resultado = app.resumen_mapa_calor(pares, tickers, limite=3)
        self.assertEqual({x["simbolo"] for x in resultado}, {"BTC", "ETH", "QNT"})
        qnt = next(x for x in resultado if x["simbolo"] == "QNT")
        self.assertAlmostEqual(qnt["cambio_dia_pct"], 30.0)
        self.assertNotIn("USDTZUSD", {x["id"] for x in resultado})


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
        self._allowed_ips = os.environ.pop("KRAKEN_SCOPE_ALLOWED_IPS", None)
        self.client = app.app.test_client()

    def tearDown(self):
        if self._allowed_ips is not None:
            os.environ["KRAKEN_SCOPE_ALLOWED_IPS"] = self._allowed_ips
        else:
            os.environ.pop("KRAKEN_SCOPE_ALLOWED_IPS", None)

    def test_allowlist_ipv6_rechaza_otro_cliente(self):
        os.environ["KRAKEN_SCOPE_ALLOWED_IPS"] = "2001:db8::1234"
        respuesta = self.client.get(
            "/api/salud", environ_base={"REMOTE_ADDR": "2001:db8::7"}
        )
        self.assertEqual(respuesta.status_code, 403)

    def test_allowlist_ipv6_permite_cliente_configurado(self):
        cliente = "2001:db8::1234"
        os.environ["KRAKEN_SCOPE_ALLOWED_IPS"] = cliente
        respuesta = self.client.get(
            "/api/salud", environ_base={"REMOTE_ADDR": cliente}
        )
        self.assertEqual(respuesta.status_code, 200)

    def test_salud(self):
        r = self.client.get("/api/salud")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"estado": "ok", "credenciales": False})

    def test_api_mapa_devuelve_activos(self):
        pares = {"XXBTZUSD": {"wsname": "XBT/USD", "altname": "XBTUSD", "status": "online"}}
        tickers = {"XXBTZUSD": {"c": ["105"], "o": "100", "v": ["0", "1000"],
                                  "p": ["0", "102"], "l": ["0", "95"], "h": ["0", "108"]}}
        with mock.patch.object(app, "kraken", side_effect=[pares, tickers]):
            r = self.client.get("/api/mapa")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["activos"][0]["simbolo"], "BTC")

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

    def test_precio_rechaza_par_desconocido(self):
        with mock.patch.object(app, "kraken", return_value={"XXBTZUSD": {"wsname": "XBT/USD"}}):
            r = self.client.get("/api/precio?par=NO_EXISTE")
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
