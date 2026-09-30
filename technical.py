"""Lecturas técnicas geométricas para Kraken Scope.

No intenta aprender ni predecir retornos. Convierte pivotes, perfil de volumen y
niveles de precio en escenarios condicionales con confirmación e invalidación.
"""

import math

import numpy as np


def detectar_pivotes(velas, orden=3):
    """Detecta máximos/mínimos locales y comprime pivotes consecutivos del mismo tipo."""
    if len(velas) < orden * 2 + 1:
        return []
    candidatos = []
    for i in range(orden, len(velas) - orden):
        ventana = velas[i - orden:i + orden + 1]
        alto = velas[i]["high"]
        bajo = velas[i]["low"]
        es_alto = alto == max(v["high"] for v in ventana)
        es_bajo = bajo == min(v["low"] for v in ventana)
        if es_alto and es_bajo:
            continue
        if es_alto:
            candidatos.append({"tipo": "alto", "i": i, "t": velas[i]["t"],
                               "precio": float(alto), "volumen": float(velas[i]["volume"])})
        elif es_bajo:
            candidatos.append({"tipo": "bajo", "i": i, "t": velas[i]["t"],
                               "precio": float(bajo), "volumen": float(velas[i]["volume"])})

    pivotes = []
    for p in candidatos:
        if pivotes and pivotes[-1]["tipo"] == p["tipo"]:
            extremo = (p["precio"] > pivotes[-1]["precio"] if p["tipo"] == "alto"
                       else p["precio"] < pivotes[-1]["precio"])
            if extremo:
                pivotes[-1] = p
        else:
            pivotes.append(p)
    return pivotes


def estructura_dow(pivotes, ultimo, atr):
    """Clasificación simplificada por máximos y mínimos crecientes/decrecientes."""
    altos = [p for p in pivotes if p["tipo"] == "alto"][-2:]
    bajos = [p for p in pivotes if p["tipo"] == "bajo"][-2:]
    if len(altos) < 2 or len(bajos) < 2:
        return {"estado": "insuficiente", "lectura": "Faltan pivotes confirmados."}

    hh = altos[-1]["precio"] > altos[-2]["precio"]
    hl = bajos[-1]["precio"] > bajos[-2]["precio"]
    lh = altos[-1]["precio"] < altos[-2]["precio"]
    ll = bajos[-1]["precio"] < bajos[-2]["precio"]
    soporte = bajos[-1]["precio"]
    resistencia = altos[-1]["precio"]

    if hh and hl:
        estado, sesgo = "alcista", "largo"
        lectura = "Máximo más alto y mínimo más alto confirmados."
        confirmacion = resistencia
        invalidacion = soporte
        objetivo = resistencia + max(resistencia - soporte, atr or 0)
    elif lh and ll:
        estado, sesgo = "bajista", "corto"
        lectura = "Máximo más bajo y mínimo más bajo confirmados."
        confirmacion = soporte
        invalidacion = resistencia
        objetivo = max(0.0, soporte - max(resistencia - soporte, atr or 0))
    else:
        estado, sesgo = "mixta", "neutral"
        lectura = "Máximos y mínimos no confirman la misma dirección."
        confirmacion = None
        invalidacion = None
        objetivo = None

    return {
        "estado": estado, "sesgo": sesgo, "lectura": lectura,
        "resistencia": float(resistencia), "soporte": float(soporte),
        "confirmacion": float(confirmacion) if confirmacion is not None else None,
        "invalidacion": float(invalidacion) if invalidacion is not None else None,
        "objetivo": float(objetivo) if objetivo is not None else None,
        "precio_actual": float(ultimo),
        "pivotes": [altos[-2], bajos[-2], altos[-1], bajos[-1]],
    }


def _linea_en(p1, p2, indice):
    if p2["i"] == p1["i"]:
        return (p1["precio"] + p2["precio"]) / 2
    pendiente = (p2["precio"] - p1["precio"]) / (p2["i"] - p1["i"])
    return p1["precio"] + pendiente * (indice - p1["i"])


def detectar_hch(pivotes, ultimo, atr, ultimo_indice):
    """Busca el HCH o HCH invertido más reciente con tolerancias explícitas."""
    if len(pivotes) < 5 or not atr or not math.isfinite(atr):
        return None
    candidatos = []
    for inicio in range(max(0, len(pivotes) - 14), len(pivotes) - 4):
        cinco = pivotes[inicio:inicio + 5]
        tipos = [p["tipo"] for p in cinco]
        if tipos not in (["alto", "bajo", "alto", "bajo", "alto"],
                         ["bajo", "alto", "bajo", "alto", "bajo"]):
            continue
        invertido = tipos[0] == "bajo"
        h1, cuello1, cabeza, cuello2, h2 = cinco
        tolerancia_hombros = max(1.25 * atr, abs(cabeza["precio"]) * 0.025)
        sim_hombros = abs(h1["precio"] - h2["precio"]) <= tolerancia_hombros
        if invertido:
            prominente = cabeza["precio"] < min(h1["precio"], h2["precio"]) - 0.35 * atr
        else:
            prominente = cabeza["precio"] > max(h1["precio"], h2["precio"]) + 0.35 * atr
        if not (sim_hombros and prominente):
            continue

        cuello = _linea_en(cuello1, cuello2, ultimo_indice)
        altura = abs(cabeza["precio"] - _linea_en(cuello1, cuello2, cabeza["i"]))
        if altura < atr:
            continue
        if invertido:
            confirmado = ultimo > cuello
            invalidado = ultimo < cabeza["precio"] - 0.25 * atr
            objetivo = cuello + altura
            invalidacion = h2["precio"] - 0.5 * atr
            sesgo = "largo"
            nombre = "Hombro-cabeza-hombro invertido"
        else:
            confirmado = ultimo < cuello
            invalidado = ultimo > cabeza["precio"] + 0.25 * atr
            objetivo = max(0.0, cuello - altura)
            invalidacion = h2["precio"] + 0.5 * atr
            sesgo = "corto"
            nombre = "Hombro-cabeza-hombro"

        sim_precio = max(0.0, 1 - abs(h1["precio"] - h2["precio"]) / tolerancia_hombros)
        d1, d2 = cabeza["i"] - h1["i"], h2["i"] - cabeza["i"]
        sim_tiempo = min(d1, d2) / max(d1, d2) if max(d1, d2) else 0
        calidad = round((0.65 * sim_precio + 0.35 * sim_tiempo) * 100)
        estado = "invalidado" if invalidado else "confirmado" if confirmado else "formándose"
        candidatos.append({
            "nombre": nombre, "sesgo": sesgo, "estado": estado,
            "confirmacion": float(cuello), "objetivo": float(objetivo),
            "invalidacion": float(invalidacion), "altura": float(altura),
            "calidad_geometrica": int(calidad),
            "puntos": [dict(p, etiqueta=e) for p, e in zip(
                cinco, ("H1", "C1", "Cabeza", "C2", "H2"))],
        })
    if not candidatos:
        return None
    return max(candidatos, key=lambda x: x["puntos"][-1]["i"])


def mapa_volumen(perfil, ultimo):
    niveles = perfil.get("niveles") or []
    if not niveles:
        return None
    vols = np.array([n["vol"] for n in niveles], dtype=float)
    mediana = float(np.median(vols[vols > 0])) if np.any(vols > 0) else 0.0
    actual = min(niveles, key=lambda n: abs(n["precio"] - ultimo))
    umbral_alto = float(np.percentile(vols, 80))
    nodos_altos = [n for n in niveles if n["vol"] >= umbral_alto]
    arriba = [n for n in nodos_altos if n["precio"] > ultimo]
    abajo = [n for n in nodos_altos if n["precio"] < ultimo]
    return {
        "volumen_relativo_actual": float(actual["vol"] / mediana) if mediana else None,
        "nivel_actual": float(actual["precio"]),
        "nodo_alto_arriba": min(arriba, key=lambda n: n["precio"])["precio"] if arriba else None,
        "nodo_alto_abajo": max(abajo, key=lambda n: n["precio"])["precio"] if abajo else None,
        "poc": perfil.get("poc"),
        "nota": "Perfil aproximado desde velas; no es footprint tick a tick.",
    }


def canal_donchian(velas, ultimo, atr, n=20):
    if len(velas) < n:
        return None
    ventana = velas[-n:]
    alto = max(v["high"] for v in ventana)
    bajo = min(v["low"] for v in ventana)
    cerca_alto = alto - ultimo <= atr * 0.6
    cerca_bajo = ultimo - bajo <= atr * 0.6
    estado = ("ruptura alcista" if ultimo > alto else "ruptura bajista" if ultimo < bajo
              else "cerca del techo" if cerca_alto else "cerca del suelo" if cerca_bajo
              else "dentro del canal")
    return {"alto": float(alto), "bajo": float(bajo), "estado": estado,
            "cerca_alto": bool(cerca_alto), "cerca_bajo": bool(cerca_bajo), "n": n}


def pullback_medias(velas, ultimo, atr):
    cierres = np.array([v["close"] for v in velas], dtype=float)
    if len(cierres) < 120:
        return None
    m20, m60, m120 = (float(cierres[-n:].mean()) for n in (20, 60, 120))
    if m20 > m60 > m120:
        sesgo, alineacion = "largo", "alcista"
        cerca = abs(ultimo - m20) <= 0.65 * atr
        confirmacion = max(v["high"] for v in velas[-3:])
        objetivo = max(v["high"] for v in velas[-20:])
        invalidacion = m60
    elif m20 < m60 < m120:
        sesgo, alineacion = "corto", "bajista"
        cerca = abs(ultimo - m20) <= 0.65 * atr
        confirmacion = min(v["low"] for v in velas[-3:])
        objetivo = min(v["low"] for v in velas[-20:])
        invalidacion = m60
    else:
        return {"alineacion": "mixta", "estado": "sin alineación", "sesgo": "neutral",
                "m20": m20, "m60": m60, "m120": m120}
    return {"alineacion": alineacion, "estado": "setup cercano" if cerca else "espera pullback",
            "sesgo": sesgo, "m20": m20, "m60": m60, "m120": m120,
            "confirmacion": float(confirmacion), "objetivo": float(objetivo),
            "invalidacion": float(invalidacion), "cerca": bool(cerca)}


def construir_escenarios(dow, patron, perfil, ultimo, atr, donchian=None, pullback=None):
    escenarios = []
    if patron and patron["estado"] != "invalidado":
        escenarios.append({
            "nombre": patron["nombre"], "sesgo": patron["sesgo"],
            "estado": patron["estado"], "confirmacion": patron["confirmacion"],
            "objetivo": patron["objetivo"], "invalidacion": patron["invalidacion"],
            "fundamento": f"Geometría {patron['calidad_geometrica']}%; objetivo por altura cabeza-cuello.",
        })

    if dow.get("estado") in ("alcista", "bajista"):
        ya_confirmado = (ultimo > dow["confirmacion"] if dow["estado"] == "alcista"
                         else ultimo < dow["confirmacion"])
        escenarios.append({
            "nombre": "Continuación Dow simplificada", "sesgo": dow["sesgo"],
            "estado": "confirmado" if ya_confirmado else "espera ruptura",
            "confirmacion": dow["confirmacion"], "objetivo": dow["objetivo"],
            "invalidacion": dow["invalidacion"], "fundamento": dow["lectura"],
        })
    elif dow.get("soporte") is not None and dow.get("resistencia") is not None:
        amplitud = dow["resistencia"] - dow["soporte"]
        escenarios.extend([
            {"nombre": "Ruptura del rango", "sesgo": "largo", "estado": "espera ruptura",
             "confirmacion": dow["resistencia"], "objetivo": dow["resistencia"] + amplitud,
             "invalidacion": dow["soporte"], "fundamento": "Estructura mixta; exige cierre sobre resistencia."},
            {"nombre": "Ruptura del rango", "sesgo": "corto", "estado": "espera ruptura",
             "confirmacion": dow["soporte"], "objetivo": max(0.0, dow["soporte"] - amplitud),
             "invalidacion": dow["resistencia"], "fundamento": "Estructura mixta; exige cierre bajo soporte."},
        ])

    if donchian:
        if ultimo >= donchian["alto"] or donchian["cerca_alto"]:
            escenarios.append({
                "nombre": f"Ruptura Donchian {donchian['n']}", "sesgo": "largo",
                "estado": "confirmado" if ultimo > donchian["alto"] else "espera cierre",
                "confirmacion": donchian["alto"], "objetivo": donchian["alto"] + 2 * atr,
                "invalidacion": donchian["alto"] - atr,
                "fundamento": "Ruptura del máximo del canal; pide volumen y delta comprador.",
            })
        if ultimo <= donchian["bajo"] or donchian["cerca_bajo"]:
            escenarios.append({
                "nombre": f"Ruptura Donchian {donchian['n']}", "sesgo": "corto",
                "estado": "confirmado" if ultimo < donchian["bajo"] else "espera cierre",
                "confirmacion": donchian["bajo"], "objetivo": max(0.0, donchian["bajo"] - 2 * atr),
                "invalidacion": donchian["bajo"] + atr,
                "fundamento": "Ruptura del mínimo del canal; pide volumen y delta vendedor.",
            })

    if pullback and pullback.get("cerca"):
        escenarios.append({
            "nombre": "Pullback a media 20", "sesgo": pullback["sesgo"],
            "estado": "espera confirmación", "confirmacion": pullback["confirmacion"],
            "objetivo": pullback["objetivo"], "invalidacion": pullback["invalidacion"],
            "fundamento": f"Medias 20/60/120 alineadas {pullback['alineacion']}; precio junto a media 20.",
        })

    va_lo, va_hi, poc = perfil.get("va_lo"), perfil.get("va_hi"), perfil.get("poc")
    if poc is not None and va_hi is not None and ultimo > va_hi:
        escenarios.append({
            "nombre": "Reingreso al valor", "sesgo": "corto", "estado": "espera reingreso",
            "confirmacion": va_hi, "objetivo": poc, "invalidacion": ultimo + atr,
            "fundamento": "Solo se activa si el precio vuelve a cerrar dentro del área de valor.",
        })
    elif poc is not None and va_lo is not None and ultimo < va_lo:
        escenarios.append({
            "nombre": "Reingreso al valor", "sesgo": "largo", "estado": "espera reingreso",
            "confirmacion": va_lo, "objetivo": poc, "invalidacion": max(0.0, ultimo - atr),
            "fundamento": "Solo se activa si el precio vuelve a cerrar dentro del área de valor.",
        })
    return escenarios[:6]


def catalogo_metodos(dow, patron, donchian, pullback, perfil, ultimo):
    fuera_valor = (perfil.get("va_hi") is not None and ultimo > perfil["va_hi"]) or (
        perfil.get("va_lo") is not None and ultimo < perfil["va_lo"])
    return [
        {"id": "dow", "nombre": "Estructura Dow simplificada", "familia": "tendencia",
         "estado": dow.get("estado", "insuficiente"),
         "valida": "Dos máximos y dos mínimos confirman la misma dirección."},
        {"id": "hch", "nombre": "HCH / HCH invertido", "familia": "patrón",
         "estado": patron["estado"] if patron else "sin patrón limpio",
         "valida": "Cinco pivotes, hombros semejantes y ruptura de clavicular."},
        {"id": "donchian", "nombre": "Ruptura Donchian 20", "familia": "breakout",
         "estado": donchian["estado"] if donchian else "insuficiente",
         "valida": "Cierre fuera del canal, preferiblemente con volumen y delta a favor."},
        {"id": "pullback", "nombre": "Pullback medias 20/60/120", "familia": "tendencia",
         "estado": pullback["estado"] if pullback else "insuficiente",
         "valida": "Medias alineadas, retroceso a media 20 y ruptura de la vela de giro."},
        {"id": "valor", "nombre": "Reingreso al área de valor", "familia": "reversión",
         "estado": "zona activa" if fuera_valor else "precio dentro del valor",
         "valida": "Cierre de vuelta dentro de VAH/VAL; objetivo descriptivo en POC."},
        {"id": "perfil", "nombre": "Rotación entre nodos de volumen", "familia": "subasta",
         "estado": "disponible", "valida": "Aceptación/rechazo en POC y nodos; perfil aproximado."},
        {"id": "flujo", "nombre": "Delta/CVD agresor", "familia": "confirmación",
         "estado": "capa disponible", "valida": "Confirma participación; no genera entrada por sí solo."},
        {"id": "liquidez", "nombre": "Muros y desequilibrio del libro", "familia": "confirmación",
         "estado": "capa disponible", "valida": "Comprueba reacción; los muros pueden retirarse."},
    ]


def analizar_estructura(velas, perfil, ultimo, atr):
    pivotes = detectar_pivotes(velas)
    dow = estructura_dow(pivotes, ultimo, atr)
    patron = detectar_hch(pivotes, ultimo, atr, len(velas) - 1)
    volumen = mapa_volumen(perfil, ultimo)
    donchian = canal_donchian(velas, ultimo, atr)
    pullback = pullback_medias(velas, ultimo, atr)
    escenarios = construir_escenarios(dow, patron, perfil, ultimo, atr, donchian, pullback)
    metodos = catalogo_metodos(dow, patron, donchian, pullback, perfil, ultimo)
    return {"dow": dow, "patron": patron, "volumen": volumen,
            "donchian": donchian, "pullback": pullback,
            "escenarios": escenarios, "metodos": metodos, "pivotes": pivotes[-12:]}
