#!/usr/bin/env python3
"""Kraken Scope — ayuda visual para leer estructura de mercado.

QUÉ ES: un tablero que muestra dónde ha operado el volumen de verdad, cuánto se
mueve normalmente el par, quién está siendo agresivo ahora mismo y dónde está la
liquidez en el libro. Marcel opera; esto solo quita ruido.

QUÉ NO ES, a propósito: no da señales de compra/venta, no pronostica dirección y no
trae un montón de indicadores. Nueve meses de investigación (Odette e5/e6 y 212
configuraciones de order flow) establecieron que la predicción direccional de corto
plazo no sobrevive fuera de muestra. Meter aquí un RSI que diga "sobrevendido" sería
contradecir la propia evidencia de la casa.

SIN CREDENCIALES: usa solo endpoints públicos de Kraken. No pide ni guarda API keys.
Los saldos de la cuenta no hacen falta para leer estructura, así que no se tocan.

Uso:
    PYTHONPATH=~/Herramientas/pylibs python3 app.py
    y abrir http://127.0.0.1:8777
"""
import ipaddress
import json
import os
import tempfile
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager

import fcntl

import numpy as np
import requests
from flask import Flask, jsonify, request, send_from_directory

from technical import analizar_estructura

app = Flask(__name__, static_folder="static", static_url_path="")
KRAKEN = "https://api.kraken.com/0/public"
KRAKEN_FUT = "https://futures.kraken.com/derivatives/api"
AQUI = os.path.dirname(os.path.abspath(__file__))
REGISTRO_OI = os.path.join(AQUI, "oi_historico.json")
TIMEOUT = 15
INTERVALOS = {1, 5, 15, 30, 60, 240, 1440, 10080, 21600}
_cache = OrderedDict()
_cache_lock = threading.RLock()
CACHE_TTL = {"OHLC": 20, "Trades": 2, "Depth": 2, "AssetPairs": 3600, "Ticker": 2}
BASES_NO_CRIPTO = {
    "USD", "EUR", "GBP", "CAD", "AUD", "JPY", "CHF",
    "USDT", "USDC", "DAI", "PYUSD", "EURT", "RLUSD", "USDG", "USDS", "USDE",
}


def _ips_permitidas():
    """Lista opcional de clientes autorizados, configurada al arrancar."""
    crudas = os.environ.get("KRAKEN_SCOPE_ALLOWED_IPS", "")
    permitidas = {
        ipaddress.ip_address("127.0.0.1"),
        ipaddress.ip_address("::1"),
        ipaddress.ip_address("::ffff:127.0.0.1"),
    }
    for valor in crudas.split(","):
        valor = valor.strip()
        if valor:
            permitidas.add(ipaddress.ip_address(valor))
    return permitidas


@app.before_request
def limitar_clientes():
    """Cuando hay allowlist, no sirve ni la página ni la API a otros clientes."""
    if not os.environ.get("KRAKEN_SCOPE_ALLOWED_IPS", "").strip():
        return None
    try:
        cliente = ipaddress.ip_address(request.remote_addr)
    except (TypeError, ValueError):
        return jsonify({"error": "Dirección de cliente no válida"}), 403
    if cliente not in _ips_permitidas():
        return jsonify({"error": "Cliente no autorizado"}), 403
    return None


def _cache_consultar(clave, ttl):
    with _cache_lock:
        if clave not in _cache:
            return None, None
        t, datos = _cache[clave]
        edad = time.time() - t
        if edad >= ttl:
            del _cache[clave]
            return None, None
        _cache.move_to_end(clave)
        return datos, edad


def _cache_leer(clave, ttl):
    return _cache_consultar(clave, ttl)[0]


def _cache_guardar(clave, datos):
    with _cache_lock:
        _cache[clave] = (time.time(), datos)
        _cache.move_to_end(clave)
        while len(_cache) > 200:
            _cache.popitem(last=False)


def kraken(endpoint, _medicion=None, **params):
    """Llama a Kraken con caché corta, para no castigar la API al refrescar."""
    inicio = time.perf_counter()
    clave = (endpoint, tuple(sorted(params.items())))
    ttl = CACHE_TTL.get(endpoint, 10)
    datos, edad_cache = _cache_consultar(clave, ttl)
    if datos is not None:
        if _medicion is not None:
            _medicion.update({"cache": True,
                              "duracion_ms": (time.perf_counter() - inicio) * 1000,
                              "edad_cache_ms": edad_cache * 1000})
        return datos
    r = requests.get(f"{KRAKEN}/{endpoint}", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    j = r.json()
    if j.get("error"):
        raise RuntimeError("; ".join(j["error"]))
    datos = j["result"]
    _cache_guardar(clave, datos)
    if _medicion is not None:
        _medicion.update({"cache": False,
                          "duracion_ms": (time.perf_counter() - inicio) * 1000,
                          "edad_cache_ms": 0.0})
    return datos


def primera_clave(d):
    return next(k for k in d.keys() if k != "last")


def resumen_precio_real(trades, libro, ticker24=None, ahora=None):
    """Valores ejecutables y edad de la publicación más reciente disponible."""
    ahora = ahora or time.time()
    ultimo_trade = trades[-1] if trades else None
    bid = libro.get("bids", [None])[0] if libro.get("bids") else None
    ask = libro.get("asks", [None])[0] if libro.get("asks") else None
    bid_p = float(bid[0]) if bid else None
    ask_p = float(ask[0]) if ask else None
    trade_ts = float(ultimo_trade[2]) if ultimo_trade else None
    tiempos_libro = [float(x[2]) for x in (bid, ask) if x and len(x) > 2]
    libro_ts = max(tiempos_libro) if tiempos_libro else None
    ticker_last = None
    if ticker24:
        try:
            ticker_last = float(ticker24["c"][0])
        except (KeyError, TypeError, ValueError):
            pass
    return {
        "ultimo_trade": float(ultimo_trade[0]) if ultimo_trade else None,
        "ultimo_trade_ts": trade_ts,
        "bid": bid_p, "ask": ask_p,
        "medio": (bid_p + ask_p) / 2 if bid_p is not None and ask_p is not None else None,
        "ticker_last": ticker_last,
        "spread": ask_p - bid_p if bid_p is not None and ask_p is not None else None,
        "spread_pct": ((ask_p - bid_p) / ((ask_p + bid_p) / 2)
                       if bid_p is not None and ask_p is not None and ask_p + bid_p else None),
        "edad_trade_ms": max(0.0, (ahora - trade_ts) * 1000) if trade_ts else None,
        "edad_libro_ms": max(0.0, (ahora - libro_ts) * 1000) if libro_ts else None,
        "servidor_ts": ahora,
    }


def resumen_mapa_calor(pares, tickers, limite=30):
    """Activos USD líquidos y movers relevantes para la portada interactiva."""
    activos = []
    alias = {"XBT": "BTC", "XDG": "DOGE"}
    for par_id, datos_par in pares.items():
        nombre = datos_par.get("wsname", "")
        if (not nombre.endswith("/USD") or par_id.endswith(".d")
                or datos_par.get("status") not in (None, "online")):
            continue
        base = nombre.split("/", 1)[0]
        if base.upper() in BASES_NO_CRIPTO:
            continue
        ticker = tickers.get(par_id) or tickers.get(datos_par.get("altname"))
        if not ticker:
            continue
        try:
            ultimo = float(ticker["c"][0])
            apertura = float(ticker["o"])
            volumen_base = float(ticker["v"][1])
            vwap = float(ticker["p"][1])
            bajo = float(ticker["l"][1])
            alto = float(ticker["h"][1])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if apertura <= 0 or ultimo <= 0:
            continue
        volumen_usd = volumen_base * vwap
        activos.append({
            "id": par_id,
            "nombre": nombre,
            "simbolo": alias.get(base.upper(), base.upper()),
            "ultimo": ultimo,
            "cambio_dia_pct": (ultimo / apertura - 1) * 100,
            "rango_24h_pct": (alto - bajo) / apertura * 100,
            "volumen_usd": volumen_usd,
        })

    por_volumen = sorted(activos, key=lambda x: x["volumen_usd"], reverse=True)
    principales = por_volumen[:min(18, limite)]
    elegidos = {x["id"]: x for x in principales}
    candidatos_movimiento = [x for x in activos if x["volumen_usd"] >= 250_000]
    candidatos_movimiento.sort(
        key=lambda x: (abs(x["cambio_dia_pct"]), x["volumen_usd"]), reverse=True
    )
    for activo in candidatos_movimiento:
        if len(elegidos) >= limite:
            break
        if activo["id"] not in elegidos:
            activo["movimiento_destacado"] = True
            elegidos[activo["id"]] = activo
    return sorted(elegidos.values(), key=lambda x: x["volumen_usd"], reverse=True)


# ---------------------------------------------------------------- analítica
def atr(altos, bajos, cierres, n=14):
    tr = []
    for i in range(1, len(cierres)):
        tr.append(max(altos[i] - bajos[i],
                      abs(altos[i] - cierres[i - 1]),
                      abs(bajos[i] - cierres[i - 1])))
    if len(tr) < n:
        return float("nan"), []
    serie = [float(np.mean(tr[max(0, i - n + 1):i + 1])) for i in range(len(tr))]
    return serie[-1], serie


def perfil_volumen(velas, n_niveles=60):
    """Histograma de volumen por precio. Devuelve niveles, POC y área de valor (70%).

    Cada vela aporta su volumen repartido por su rango, no concentrado en el cierre:
    es una aproximación, pero refleja mejor dónde se negoció de verdad."""
    altos = [v["high"] for v in velas]
    bajos = [v["low"] for v in velas]
    pmin, pmax = min(bajos), max(altos)
    if pmax <= pmin:
        return [], None, None, None
    bordes = np.linspace(pmin, pmax, n_niveles + 1)
    centros = (bordes[:-1] + bordes[1:]) / 2
    vol = np.zeros(n_niveles)

    for v in velas:
        lo, hi, q = v["low"], v["high"], v["volume"]
        if q <= 0:
            continue
        i0 = max(0, np.searchsorted(bordes, lo, side="right") - 1)
        i1 = min(n_niveles - 1, np.searchsorted(bordes, hi, side="right") - 1)
        span = max(i1 - i0 + 1, 1)
        vol[i0:i1 + 1] += q / span

    poc_i = int(np.argmax(vol))
    poc = float(centros[poc_i])

    # área de valor: se expande desde el POC hasta cubrir el 70% del volumen
    objetivo = vol.sum() * 0.70
    lo_i = hi_i = poc_i
    acum = vol[poc_i]
    while acum < objetivo and (lo_i > 0 or hi_i < n_niveles - 1):
        izq = vol[lo_i - 1] if lo_i > 0 else -1
        der = vol[hi_i + 1] if hi_i < n_niveles - 1 else -1
        if der >= izq:
            hi_i += 1
            acum += vol[hi_i]
        else:
            lo_i -= 1
            acum += vol[lo_i]

    niveles = [{"precio": float(c), "vol": float(x)} for c, x in zip(centros, vol)]
    return niveles, poc, float(centros[lo_i]), float(centros[hi_i])


def excursion_adversa(velas, k_barras=12):
    """Excursión adversa posterior a una entrada al cierre, separada por dirección.

    La primera barra observada es la siguiente a la entrada. Así no contamos como
    adverso un máximo o mínimo de la propia vela que ocurrió antes de poder entrar.
    Devuelve percentiles en unidades del ATR conocido en el momento de la entrada.
    """
    altos = [v["high"] for v in velas]
    bajos = [v["low"] for v in velas]
    cierres = [v["close"] for v in velas]
    _, serie_atr = atr(altos, bajos, cierres)
    if not serie_atr:
        return {}
    exc_largo, exc_corto = [], []
    for entrada_i in range(1, len(cierres) - k_barras):
        a = serie_atr[entrada_i - 1]
        if not a or a <= 0:
            continue
        entrada = cierres[entrada_i]
        inicio = entrada_i + 1
        vent_lo = min(bajos[inicio:inicio + k_barras])
        vent_hi = max(altos[inicio:inicio + k_barras])
        exc_largo.append(max(0.0, entrada - vent_lo) / a)
        exc_corto.append(max(0.0, vent_hi - entrada) / a)
    if not exc_largo:
        return {}
    def percentiles(valores):
        arr = np.array(valores)
        return {f"p{p}": float(np.percentile(arr, p)) for p in (50, 70, 80, 90, 95)}
    return {"largo": percentiles(exc_largo), "corto": percentiles(exc_corto),
            "muestras": len(exc_largo), "horizonte_barras": k_barras}


def flujo(trades):
    """Delta y CVD reales: Kraken marca el lado agresor en cada operación."""
    compra = venta = 0.0
    cvd, acum = [], 0.0
    for t in trades:
        precio, vol, ts, lado = float(t[0]), float(t[1]), float(t[2]), t[3]
        if lado == "b":
            compra += vol
            acum += vol
        else:
            venta += vol
            acum -= vol
        cvd.append({"t": ts, "cvd": acum, "precio": precio})
    total = compra + venta
    paso = max(1, len(cvd) // 180)
    return {"compra": compra, "venta": venta, "delta": compra - venta,
            "ratio": (compra - venta) / total if total else 0.0,
            "n": len(trades), "cvd": cvd[::paso]}


def muros(libro, n=6):
    """Niveles del libro con volumen desproporcionado: ahí hay liquidez de verdad."""
    out = {}
    for lado in ("bids", "asks"):
        filas = [(float(p), float(v)) for p, v, *_ in libro.get(lado, [])]
        if not filas:
            out[lado] = []
            continue
        vols = np.array([v for _, v in filas])
        umbral = float(np.mean(vols) + 2 * np.std(vols)) if len(vols) > 3 else float("inf")
        picos = sorted([{"precio": p, "vol": v} for p, v in filas if v >= umbral],
                       key=lambda x: -x["vol"])[:n]
        out[lado] = picos
    bid_v = sum(float(v) for _, v, *_ in libro.get("bids", []))
    ask_v = sum(float(v) for _, v, *_ in libro.get("asks", []))
    tot = bid_v + ask_v
    out["desequilibrio"] = (bid_v - ask_v) / tot if tot else 0.0
    return out


# ------------------------------------------------- capa de futuros (Kraken Futures)
def futuros(url, ttl, **params):
    clave = (url, tuple(sorted(params.items())))
    d = _cache_leer(clave, ttl)
    if d is not None:
        return d
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    j = r.json()
    _cache_guardar(clave, j)
    return j


def perpetuo_de(base):
    """Busca el perpetuo de Kraken Futures de esa moneda.

    Prefiere PF_ (lineal, margen en USD) sobre PI_ (inverso, margen en la propia
    moneda): el funding del lineal es el que refleja el posicionamiento habitual."""
    j = futuros(f"{KRAKEN_FUT}/v3/tickers", 30)
    base = base.upper()
    candidatos = []
    for t in j.get("tickers", []):
        if t.get("tag") != "perpetual":
            continue
        par = (t.get("pair") or "").upper()
        if par.split(":")[0] == base and par.endswith(":USD"):
            candidatos.append(t)
    if not candidatos:
        return None
    candidatos.sort(key=lambda t: (0 if str(t.get("symbol", "")).startswith("PF_") else 1,
                                   -(t.get("openInterest") or 0)))
    return candidatos[0]


def funding_percentil(symbol, tasa_relativa):
    """Sitúa el funding de ahora dentro de su propio año de historia.

    Ojo: el endpoint de tickers da `fundingRate` en unidades de PRECIO, mientras el
    histórico da `relativeFundingRate` como tasa. Hay que convertir antes de comparar."""
    try:
        j = futuros(f"{KRAKEN_FUT}/v4/historicalfundingrates", 3600, symbol=symbol)
        serie = [float(x["relativeFundingRate"]) for x in j.get("rates", [])
                 if x.get("relativeFundingRate") is not None]
        if len(serie) < 50 or tasa_relativa is None:
            return None, len(serie)
        arr = np.array(serie)
        return float((arr < tasa_relativa).mean() * 100), len(serie)
    except Exception:
        return None, 0


@contextmanager
def _bloqueo_registro_oi():
    """Serializa lecturas/escrituras incluso si hubiera más de un proceso servidor."""
    ruta_lock = REGISTRO_OI + ".lock"
    with open(ruta_lock, "a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _guardar_json_atomico(ruta, datos):
    directorio = os.path.dirname(ruta)
    fd, temporal = tempfile.mkstemp(prefix=".oi_historico.", suffix=".tmp", dir=directorio)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(datos, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporal, ruta)
    finally:
        if os.path.exists(temporal):
            os.unlink(temporal)


def registrar_oi(symbol, oi, precio):
    """No hay histórico público de interés abierto, así que se acumula aquí.
    Devuelve el cambio desde el registro más antiguo dentro de 24 h."""
    ahora = time.time()
    with _bloqueo_registro_oi():
        try:
            with open(REGISTRO_OI) as f:
                reg = json.load(f)
            if not isinstance(reg, dict):
                reg = {}
        except (OSError, ValueError):
            reg = {}
        serie = [p for p in reg.get(symbol, []) if ahora - p[0] < 7 * 86400]
        previo = None
        for t, o, p in reversed(serie):  # el más reciente con al menos 1 h de diferencia
            if ahora - t >= 3600:
                previo = (t, o, p)
                break
        if not serie or ahora - serie[-1][0] > 120:
            serie.append([ahora, oi, precio])
        reg[symbol] = serie[-2000:]
        _guardar_json_atomico(REGISTRO_OI, reg)
    if previo and previo[1]:
        horas = (ahora - previo[0]) / 3600
        return {"cambio": (oi - previo[1]) / previo[1],
                "cambio_precio": (precio - previo[2]) / previo[2] if previo[2] else None,
                "horas": horas, "muestras": len(serie)}
    return {"cambio": None, "cambio_precio": None, "horas": None, "muestras": len(serie)}


def cuadrante(delta_precio, delta_oi):
    """La lectura clásica de posicionamiento: qué tipo de dinero mueve el precio."""
    if delta_precio is None or delta_oi is None:
        return None, None
    umbral = 0.001
    if abs(delta_precio) < umbral or abs(delta_oi) < 0.002:
        return "sin señal clara", "Ni el precio ni el interés abierto se movieron lo suficiente."
    if delta_precio > 0 and delta_oi > 0:
        return "dinero nuevo comprando", ("El precio sube y se abren contratos nuevos: entra "
                                          "posicionamiento largo fresco, no cierre de cortos.")
    if delta_precio > 0 and delta_oi < 0:
        return "cierre de cortos", ("El precio sube pero se cierran contratos: son cortos "
                                    "cubriéndose, no compradores nuevos. Suele agotarse antes.")
    if delta_precio < 0 and delta_oi > 0:
        return "dinero nuevo vendiendo", ("El precio baja y se abren contratos: entra "
                                          "posicionamiento corto fresco.")
    return "liquidación de largos", ("El precio baja y se cierran contratos: son largos "
                                     "saliendo o siendo liquidados, no vendedores nuevos.")


# ------------------------------------------------- análisis descriptivo
def analisis_tecnico(velas, perfil, atr_actual, ultimo, ticker24):
    """Describe el estado del precio. NO predice: cada línea es un hecho medible."""
    cierres = np.array([v["close"] for v in velas])
    vols = np.array([v["volume"] for v in velas])
    out = {}

    # posición respecto al valor negociado
    if perfil.get("poc") and atr_actual:
        d = (ultimo - perfil["poc"]) / atr_actual
        if perfil.get("va_lo") is not None and perfil["va_lo"] <= ultimo <= perfil["va_hi"]:
            zona = "dentro del área de valor"
            expl = "El precio está donde se negoció la mayor parte del volumen: zona de acuerdo."
        elif ultimo > (perfil.get("va_hi") or 0):
            zona = "por encima del área de valor"
            expl = ("El precio está fuera de la zona donde se negoció. Arriba hay poco volumen "
                    "previo, así que se mueve con menos resistencia — en ambos sentidos.")
        else:
            zona = "por debajo del área de valor"
            expl = ("El precio está fuera de la zona donde se negoció, por abajo. Poco volumen "
                    "previo debajo significa menos suelo estructural.")
        out["valor"] = {"zona": zona, "dist_poc_atr": float(d), "explicacion": expl}

    # alineación multi-horizonte (descripción de estado, no señal de entrada)
    medias = {}
    for n in (20, 60, 120):
        if len(cierres) > n:
            medias[n] = float(cierres[-n:].mean())
    arriba = sum(1 for m in medias.values() if ultimo > m)
    out["tendencia"] = {
        "medias": medias, "por_encima_de": arriba, "total": len(medias),
        "estado": ("alineada al alza" if arriba == len(medias) and medias else
                   "alineada a la baja" if arriba == 0 and medias else "mixta"),
    }

    # participación: ¿el movimiento trae volumen?
    # Dos decisiones que importan:
    #  - la función recibe solo velas cerradas; la última es por tanto comparable;
    #  - se compara contra la MEDIANA, no la media. El volumen está muy sesgado a la
    #    derecha (una vela de pico arrastra la media 2-3x por encima de lo típico) y
    #    con la media casi cualquier vela normal salía "por debajo de lo normal".
    if len(vols) > 30:
        ventana = vols[-97:-1] if len(vols) > 97 else vols[:-1]
        tipico = float(np.median(ventana))
        ultima_cerrada = float(vols[-1])
        ratio = float(ultima_cerrada / tipico) if tipico else None
        out["participacion"] = {
            "ratio": ratio, "tipico": tipico, "ultima": ultima_cerrada,
            "n_ventana": len(ventana),
            "lectura": ("volumen muy por encima de lo normal" if ratio and ratio > 2 else
                        "volumen por encima de lo normal" if ratio and ratio > 1.3 else
                        "volumen por debajo de lo normal" if ratio and ratio < 0.6 else
                        "volumen normal"),
        }

    # dónde está dentro del rango del día
    if ticker24:
        try:
            hi, lo = float(ticker24["h"][1]), float(ticker24["l"][1])
            if hi > lo:
                out["rango_dia"] = {"alto": hi, "bajo": lo,
                                    "posicion": float((ultimo - lo) / (hi - lo) * 100)}
        except Exception:
            pass
    return out


def beta_btc(velas, velas_btc):
    """¿Se mueve solo o sigue al mercado? Para una alt es media explicación del 'por qué'."""
    if not velas_btc or len(velas) < 30:
        return None
    a = {v["t"]: v["close"] for v in velas}
    b = {v["t"]: v["close"] for v in velas_btc}
    comunes = sorted(set(a) & set(b))
    if len(comunes) < 30:
        return None
    ra = np.diff(np.log([a[t] for t in comunes]))
    rb = np.diff(np.log([b[t] for t in comunes]))
    if rb.std() == 0:
        return None
    beta = float(np.cov(ra, rb)[0, 1] / rb.var())
    corr = float(np.corrcoef(ra, rb)[0, 1])
    return {"beta": beta, "correlacion": corr, "n": len(comunes)}


def narrativa(par, tec, fund, ticker24):
    """La frase de 'por qué': hechos encadenados, sin pronóstico."""
    trozos = []
    if ticker24:
        try:
            o = float(ticker24["o"])
            c = float(ticker24["c"][0])
            trozos.append(f"{par} {'sube' if c >= o else 'baja'} {abs(c/o-1)*100:.2f}% desde 00:00 UTC")
        except Exception:
            pass
    p = (tec or {}).get("participacion")
    if p and p.get("ratio"):
        trozos.append(f"con {p['lectura']} ({p['ratio']:.1f}× lo típico)")
    if fund and fund.get("cuadrante"):
        trozos.append(f"y el posicionamiento indica {fund['cuadrante']}")
    frase1 = ", ".join(trozos) + "." if trozos else ""

    extra = []
    if fund and fund.get("funding_pctl") is not None:
        q = fund["funding_pctl"]
        quien = "los largos pagan a los cortos" if (fund.get("funding_rel") or 0) > 0 else "los cortos pagan a los largos"
        nivel = "inusualmente alto" if q >= 90 else "alto" if q >= 70 else "inusualmente bajo" if q <= 10 else "bajo" if q <= 30 else "normal"
        extra.append(f"El funding está en el percentil {q:.0f} de su último año ({nivel}): {quien}")
    if fund and fund.get("basis_pct") is not None:
        b = fund["basis_pct"]
        extra.append(f"el perpetuo cotiza con {'prima' if b>=0 else 'descuento'} de {abs(b)*100:.3f}%")
    v = (tec or {}).get("valor")
    if v:
        extra.append(f"y el precio está {v['zona']}")
    frase2 = ", ".join(extra) + "." if extra else ""
    return " ".join(x for x in (frase1, frase2) if x)


# ---------------------------------------------------------------- rutas
@app.route("/")
def raiz():
    return send_from_directory("static", "index.html")


@app.route("/api/salud")
def salud():
    return jsonify({"estado": "ok", "credenciales": False})


@app.route("/api/pares")
def pares():
    d = kraken("AssetPairs")
    lista = [{"id": k, "nombre": v.get("wsname", k)} for k, v in d.items()
             if v.get("wsname", "").endswith(("/USD", "/USDT", "/EUR"))]
    lista.sort(key=lambda x: x["nombre"])
    return jsonify(lista)


@app.route("/api/mapa")
def mapa():
    """Mapa compacto: tamaño por volumen 24 h y color desde 00:00 UTC."""
    try:
        pares_disponibles = kraken("AssetPairs")
        tickers = kraken("Ticker")
        return jsonify({
            "activos": resumen_mapa_calor(pares_disponibles, tickers),
            "servidor_ts": time.time(),
            "criterio": {
                "tamano": "volumen aproximado negociado en USD durante 24 h",
                "color": "cambio desde las 00:00 UTC informado por Kraken",
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/precio")
def precio():
    """Snapshot ligero para refrescar precio/latencia sin recalcular la analítica."""
    inicio_backend = time.perf_counter()
    par = request.args.get("par", "XXBTZUSD").strip()
    try:
        pares_disponibles = kraken("AssetPairs")
        if par not in pares_disponibles:
            return jsonify({"error": "Par de mercado desconocido."}), 400
        mediciones = {"trades": {}, "libro": {}}
        d_tr = kraken("Trades", _medicion=mediciones["trades"], pair=par, count=1)
        trades = d_tr[primera_clave(d_tr)]
        d_bk = kraken("Depth", _medicion=mediciones["libro"], pair=par, count=1)
        libro = d_bk[primera_clave(d_bk)]
        ahora = time.time()
        real = resumen_precio_real(trades, libro, ahora=ahora)
        return jsonify({
            "par": par, "precio_real": real,
            "latencia": {
                "backend_ms": (time.perf_counter() - inicio_backend) * 1000,
                "endpoints": mediciones,
                "nota": ("RTT del navegador y tiempo backend son medidos; la edad del trade "
                         "depende del reloj local y no equivale a latencia de red unidireccional."),
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/mercado")
def mercado():
    inicio_backend = time.perf_counter()
    par = request.args.get("par", "XXBTZUSD").strip()
    try:
        intervalo = int(request.args.get("intervalo", 5))
    except (TypeError, ValueError):
        return jsonify({"error": "El intervalo debe ser un número entero."}), 400
    if intervalo not in INTERVALOS:
        return jsonify({"error": "Intervalo no admitido por Kraken."}), 400
    try:
        pares_disponibles = kraken("AssetPairs")
        if par not in pares_disponibles:
            return jsonify({"error": "Par de mercado desconocido."}), 400
        wsname = pares_disponibles[par].get("wsname", "")
        base = wsname.split("/", 1)[0] if "/" in wsname else ""

        mediciones = {"ohlc": {}, "trades": {}, "libro": {}, "ticker": {}}
        d_ohlc = kraken("OHLC", _medicion=mediciones["ohlc"], pair=par, interval=intervalo)
        clave = primera_clave(d_ohlc)
        crudas = d_ohlc[clave]
        velas = [{"t": int(c[0]), "open": float(c[1]), "high": float(c[2]),
                  "low": float(c[3]), "close": float(c[4]), "vwap": float(c[5]),
                  "volume": float(c[6]), "n": int(c[7])} for c in crudas]

        d_tr = kraken("Trades", _medicion=mediciones["trades"], pair=par, count=1000)
        trades = d_tr[primera_clave(d_tr)]
        d_bk = kraken("Depth", _medicion=mediciones["libro"], pair=par, count=100)
        libro = d_bk[primera_clave(d_bk)]

        if len(velas) < 30:
            raise RuntimeError("Kraken no devolvió suficientes velas para calcular la analítica.")
        # Kraken incluye al final una vela todavía abierta. Se muestra en el gráfico,
        # pero todos los estadísticos usan únicamente observaciones cerradas.
        velas_cerradas = velas[:-1]
        altos = [v["high"] for v in velas_cerradas]
        bajos = [v["low"] for v in velas_cerradas]
        cierres = [v["close"] for v in velas_cerradas]
        atr_actual, serie_atr = atr(altos, bajos, cierres)
        ultimo = float(trades[-1][0]) if trades else velas[-1]["close"]

        # régimen de volatilidad: el ATR de ahora contra su propia historia
        atr_pct = [a / c for a, c in zip(serie_atr, cierres[1:]) if c] if serie_atr else []
        pctl_vol = float((np.array(atr_pct) < (atr_actual / ultimo)).mean() * 100) if atr_pct else float("nan")

        niveles, poc, va_lo, va_hi = perfil_volumen(velas_cerradas)
        perfil = {"niveles": niveles, "poc": poc, "va_lo": va_lo, "va_hi": va_hi}
        mejor_bid = float(libro["bids"][0][0]) if libro.get("bids") else None
        mejor_ask = float(libro["asks"][0][0]) if libro.get("asks") else None

        # ----- ticker de 24 h -----
        try:
            d_tk = kraken("Ticker", _medicion=mediciones["ticker"], pair=par)
            ticker24 = d_tk[primera_clave(d_tk)]
        except Exception:
            ticker24 = None

        # ----- análisis técnico (descriptivo) -----
        tec = analisis_tecnico(velas_cerradas, perfil, atr_actual, ultimo, ticker24)
        estructura = analizar_estructura(velas_cerradas, perfil, ultimo, atr_actual)

        # ----- beta contra BTC -----
        if base.upper() not in ("XBT", "BTC"):
            try:
                d_btc = kraken("OHLC", pair="XBTUSD", interval=intervalo)
                vb = d_btc[primera_clave(d_btc)]
                tec["btc"] = beta_btc(velas, [{"t": int(c[0]), "close": float(c[4])} for c in vb])
            except Exception:
                tec["btc"] = None

        # ----- análisis fundamental (posicionamiento en derivados) -----
        fund = None
        if base:
            try:
                perp = perpetuo_de(base)
                if perp:
                    mark = float(perp.get("markPrice") or 0)
                    index = float(perp.get("indexPrice") or 0) or None
                    tasa_abs = perp.get("fundingRate")
                    tasa_rel = (float(tasa_abs) / mark) if (tasa_abs is not None and mark) else None
                    pctl, n_hist = funding_percentil(perp["symbol"], tasa_rel)
                    oi = float(perp.get("openInterest") or 0)
                    mov = registrar_oi(perp["symbol"], oi, mark or ultimo)
                    etq, expl = cuadrante(mov["cambio_precio"], mov["cambio"])
                    fund = {
                        "symbol": perp["symbol"],
                        "funding_rel": tasa_rel,
                        "funding_pctl": pctl,
                        "funding_muestras": n_hist,
                        "funding_prediccion": perp.get("fundingRatePrediction"),
                        "oi": oi,
                        "oi_cambio": mov["cambio"],
                        "oi_horas": mov["horas"],
                        "oi_muestras": mov["muestras"],
                        "precio_cambio": mov["cambio_precio"],
                        "cuadrante": etq,
                        "cuadrante_expl": expl,
                        "basis_pct": ((mark - index) / index) if (mark and index) else None,
                        "vol24h_perp": perp.get("volumeQuote"),
                        "change24h": perp.get("change24h"),
                    }
            except Exception as e:
                fund = {"error": str(e)}

        ahora_respuesta = time.time()
        precio_real = resumen_precio_real(trades, libro, ticker24, ahora_respuesta)
        if fund and "error" not in fund:
            precio_real["mark_perpetuo"] = mark
            precio_real["indice_perpetuo"] = index
        return jsonify({
            "tecnico": tec,
            "estructura": estructura,
            "fundamental": fund,
            "porque": narrativa(base or par, tec, fund if fund and "error" not in fund else None, ticker24),
            "par": par, "intervalo": intervalo, "velas": velas[-240:],
            "ultimo": ultimo,
            "precio_real": precio_real,
            "latencia": {
                "backend_ms": (time.perf_counter() - inicio_backend) * 1000,
                "endpoints": mediciones,
                "nota": ("RTT del navegador y tiempo backend son medidos; la edad del trade "
                         "depende del reloj local y no equivale a latencia de red unidireccional."),
            },
            "atr": atr_actual,
            "atr_pct_precio": atr_actual / ultimo if ultimo else None,
            "vol_percentil": pctl_vol,
            "perfil": perfil,
            "flujo": flujo(trades),
            "libro": muros(libro),
            "spread": (mejor_ask - mejor_bid) if (mejor_bid and mejor_ask) else None,
            "spread_pct": ((mejor_ask - mejor_bid) / ultimo) if (mejor_bid and mejor_ask and ultimo) else None,
            "excursion": excursion_adversa(velas_cerradas),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    host = os.environ.get("KRAKEN_SCOPE_HOST", "127.0.0.1")
    port = int(os.environ.get("KRAKEN_SCOPE_PORT", "8777"))
    print(f"Kraken Scope -> http://[{host}]:{port}   (sin credenciales, solo datos públicos)")
    app.run(host=host, port=port, debug=False)
