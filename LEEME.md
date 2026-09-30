# Kraken Scope

Ayuda visual para leer estructura de mercado mientras operás. **Vos hacés el trade**, esto solo
quita ruido y te muestra lo que no se ve mirando una vela.

## Arrancar

```bash
cd ~/Herramientas/kraken-scope
PYTHONPATH=~/Herramientas/pylibs python3 app.py
```

Y abrir **http://127.0.0.1:8777**. El precio ligero se actualiza cada 3 segundos y la analítica
completa cada 20 segundos.

## No pide tu API key, y es a propósito

Kraken expone públicamente todo lo que esta herramienta necesita: velas, libro de órdenes y
operaciones **con el lado agresor marcado**. Tu clave solo añadiría saldos y posiciones, que no
hacen falta para leer estructura ni para decidir un stop.

Así que no hay credenciales que guardar, que filtrar ni que rotar. Si algún día querés ver tus
posiciones encima del gráfico, se puede añadir una clave **de solo lectura** — pero hasta que
ese día llegue, el riesgo es cero.

## Qué muestra y por qué

| Panel | Qué responde |
|---|---|
| **Precio real y latencia** | Último trade, bid, ask, medio, spread, mark del perpetuo, RTT del navegador, tiempo backend y edad del dato publicado. |
| **Opciones técnicas** | Escenarios condicionales con confirmación, objetivo geométrico e invalidación. No ejecutan ni prometen el recorrido. |
| **Por qué se está moviendo** | Una frase que encadena los hechos medidos: cuánto se movió, con cuánta participación, qué dice el posicionamiento y dónde está respecto al valor. |
| **Perfil de volumen** | Dónde se negoció de verdad. El POC es el precio con más volumen; el área de valor cubre el 70% de la actividad. Fuera de esa banda hay poco negociado, y el precio suele moverse rápido. |
| **Dónde poner el stop** | Distancias en múltiplos de ATR, y si cada una cae dentro o fuera del movimiento normal del par. |
| **Análisis fundamental** | Funding (y su percentil sobre un año), interés abierto y su cambio, prima del perpetuo, y la lectura del cuadrante precio/interés abierto. |
| **Análisis técnico** | Posición respecto al área de valor, alineación de medias, participación de volumen, lugar dentro del rango de 24 h y beta/correlación contra BTC. |
| **Contexto de volatilidad** | El ATR de ahora contra su propia historia. Con volatilidad alta, el mismo stop en porcentaje es mucho más fácil de tocar. |
| **Flujo agresor / CVD** | Quién está cruzando el spread ahora mismo. Delta **real**, no estimado: Kraken marca el lado en cada operación. |
| **Liquidez en el libro** | Niveles con volumen muy por encima de lo normal. El precio tiende a frenarse ahí o a acelerar cuando los rompe. |

## Los dos análisis: qué significan de verdad

**Fundamental = posicionamiento, no valoración.** En cripto no hay balance ni beneficios que
analizar, así que lo "fundamental" útil es quién está posicionado y a qué coste. Sale de Kraken
Futures (también público):

- **Funding y su percentil.** El funding es lo que un lado paga al otro por mantener
  apalancamiento. El número suelto no dice nada; el percentil sobre su propio año sí. Percentil
  95 significa que los largos están pagando más caro que el 95% del año: el posicionamiento está
  cargado de ese lado. Es una medida de **quién está incómodo**, no de hacia dónde irá el precio.
- **Cuadrante precio / interés abierto.** Sube el precio y se abren contratos → dinero nuevo
  comprando. Sube el precio y se cierran → cortos cubriéndose, que suele agotarse antes. Baja y
  se abren → cortos nuevos. Baja y se cierran → largos liquidándose. Esta es la respuesta más
  directa a "por qué se mueve". Necesita una hora de historial acumulado: no hay histórico
  público de interés abierto, así que la app lo va guardando en `oi_historico.json`.
- **Prima del perpetuo** sobre el índice: cuánto paga el mercado por la exposición apalancada.

**Técnico = descripción de estado, no señal.** Cada línea es un hecho medible ahora:

- **Beta y correlación contra BTC.** Si una alt sube 5% con correlación 0,9 y beta 2, no está
  pasando nada propio: es el mercado. Esa distinción sola explica buena parte de los movimientos
  de altcoins.
- **Participación de volumen** contra la **mediana** de 96 velas, no la media. El volumen está
  muy sesgado a la derecha y una sola vela de pico arrastra la media 2-3× por encima de lo
  típico: con la media, casi cualquier vela normal salía "por debajo de lo normal".
- **Alineación de medias 20/60/120.** Es un hecho, no una señal. Odette2 valida la confirmación
  multi-plazo en horizontes de días y semanas; en scalping no tiene valor predictivo demostrado,
  y así está etiquetado en la propia interfaz.
- **Dow simplificado.** Compara los dos últimos máximos y mínimos locales confirmados. Dos altos
  y dos bajos crecientes describen estructura alcista; ambos decrecientes, bajista. Si discrepan,
  se etiqueta mixta. El objetivo es una extensión del último rango, no una predicción estadística.
- **HCH/HCH invertido.** Exige cinco pivotes alternos, cabeza prominente y hombros semejantes.
  Distingue “formándose” de “confirmado” según cruce de la clavicular. La calidad mostrada mide
  solo simetría de precio/tiempo y nunca debe leerse como probabilidad de éxito.
- **Mapa de volumen.** Compara el volumen aproximado del nivel actual con la mediana del perfil y
  señala los nodos de volumen fuerte más cercanos por arriba y por abajo.

El catálogo visible incluye ocho métodos o capas: Dow simplificado, HCH/HCH invertido, ruptura
Donchian 20, pullback de medias 20/60/120, reingreso al área de valor, rotación entre nodos de
volumen, delta/CVD agresor y muros/desequilibrio del libro. Los dos últimos son confirmaciones,
no entradas autónomas. El tablero muestra todos aunque no haya setup, para que Marcel pueda
elegir el enfoque, validar el contexto y ejecutar por su cuenta.

## Qué significa la latencia

- **RTT navegador:** tiempo real desde que la página solicita el snapshot hasta que recibe JSON.
- **Backend:** tiempo empleado dentro de Flask, incluidas las consultas públicas a Kraken que no
  salgan de caché.
- **Edad del trade:** diferencia entre el timestamp del último trade y el momento de respuesta,
  más el tramo observado fuera del backend.
- **No es latencia unidireccional exacta:** para medirla harían falta relojes sincronizados con el
  motor del exchange y un feed WebSocket. La pantalla separa las cantidades medibles y no las
  mezcla bajo una sola cifra.

## La parte del stop, que es la que más te importa

No inventa una regla. Mide, sobre ese mismo par e intervalo, **cuánto recorre el precio contra
una posición larga o corta en las 12 barras siguientes**, y da por separado los percentiles en
unidades de ATR. La medición supone entrada al cierre y empieza en la vela siguiente: no atribuye
a la operación un máximo o mínimo ocurrido antes de que la entrada fuera posible.

Si la mediana adversa de los largos es 2,7 ATR, un stop largo a 1 ATR queda dentro del recorrido
normal observado del par. Las referencias de 50%, 80% y 90% describen cobertura histórica; no
prescriben cuánto riesgo asumir ni convierten un stop amplio en una buena operación.

## Lo que deliberadamente NO hace

No da señales de compra ni venta, no pronostica dirección y no trae una pila de indicadores.

Nueve meses de investigación en esta misma casa lo establecieron: los experimentos 5 y 6 de
Odette (redes LTC sobre flujo de órdenes) y las 212 configuraciones del proyecto de order flow
mostraron que **la predicción direccional de corto plazo no sobrevive fuera de muestra**. Meter
aquí un RSI que diga "sobrevendido" sería contradecir la evidencia que tanto costó reunir.

Lo que sí sobrevive es la descripción del estado: dónde hay volumen, cuánto se mueve esto,
quién es agresivo, dónde está la liquidez. Eso es lo que muestra.

## Detalles técnicos

- `app.py` — servidor Flask. Llama a Kraken con caché corta (5-20 s según endpoint) para no
  castigar la API al refrescar. Toda la analítica se calcula en Python.
- `static/index.html` — una sola página, sin dependencias externas. El gráfico está dibujado a
  mano en canvas, así que no necesita CDN ni internet más allá de la propia API de Kraken.
- El perfil de volumen reparte el volumen de cada vela por su rango, no lo concentra en el
  cierre. Es una aproximación: el perfil exacto necesitaría datos tick a tick.
- La última vela de Kraken aún está abierta: aparece en el gráfico para mostrar el precio actual,
  pero no entra en ATR, perfil, participación ni estadísticas de stops.
- `GET /api/salud` permite comprobar el servidor sin depender de que Kraken esté disponible.
- `GET /api/precio` entrega el snapshot ligero usado por el refresco de 3 segundos.
- `GET /api/mapa` resume pares USD líquidos y movers con volumen para el mapa de calor.
- `technical.py` contiene detección de pivotes, estructura Dow simplificada, HCH y escenarios.

La portada muestra un mapa de calor de hasta 30 criptoactivos: el tamaño relativo prioriza
el volumen negociado en USD durante 24 horas y el color refleja el cambio desde las 00:00 UTC,
que es como Kraken define la apertura diaria. Incluye también movers destacados solo cuando superan un
umbral mínimo de volumen; tocar una celda selecciona ese par y abre su análisis completo.

### Acceso temporal por IPv6

Por defecto sigue escuchando únicamente en `127.0.0.1`. Para probarlo desde un dispositivo
con una IPv6 concreta, se puede escuchar por IPv6 y activar una lista de clientes permitidos:

```bash
KRAKEN_SCOPE_HOST='::' \
KRAKEN_SCOPE_ALLOWED_IPS='2001:db8::1234' \
PYTHONPATH=~/Herramientas/pylibs:. python3 app.py
```

La lista acepta varias direcciones separadas por comas. `127.0.0.1` y `::1` siempre quedan
permitidas para las comprobaciones locales. Esto filtra en la aplicación; si el sistema tiene
un cortafuegos activo, también debe aceptar TCP/8777 para ese cliente.

## Comprobar los cálculos

```bash
cd ~/Herramientas/kraken-scope
PYTHONPATH=~/Herramientas/pylibs:. python3 -m unittest discover -s tests -v
```

## Ideas para después

- Overlay de posiciones propias (necesitaría clave de solo lectura).
- Perfil de volumen tick a tick usando `/0/public/Trades` paginado hacia atrás.
- Marcar sesiones (Asia / Europa / EE.UU.) sobre el gráfico.
- Alerta cuando el precio entra o sale del área de valor.
