#!/usr/bin/env bash
# [arc-agi3-kaggle-agent/scripts/estrato_a] BL.21783 -- LA CORRIDA QUE CONTESTA "CUANTOS NIVELES
# SUMAN 4.000 ACCIONES", con el plan ADAPTATIVO que calculo `presupuesto_de_la_medicion.py`.
#
# POR QUE ADAPTATIVO Y NO 4 SEMILLAS EN LOS SEIS. El mapa decide por la semilla MEJOR (`max`), asi
# que su unico error posible es el falso negativo: un juego capaz al que ninguna semilla le salio.
# Un juego que YA puntuo no cambia de casillero por correr mas semillas. Entonces la 1ra semilla va
# en los seis y las de refuerzo se gastan SOLO donde salio cero: 11,25 partidas esperadas contra 24
# del plan fijo, con la MISMA garantia (riesgo 0,10 de perder un juego con p=0,5 por semilla).
#
# ORDEN: primero los que el mapa viejo tenia puntuando TARDE (lp85 en 68/859/1216, sc25 en
# 1298/1375, m0r0 en 1464), porque son los unicos que pueden mostrar que el tramo 1600-4000 paga.
# Si el box corta el barrido a la mitad, lo que quedo medido es lo que contesta la pregunta; vc33 y
# ft09 van al final porque puntuan temprano y su tramo hondo solo confirma.
#
# REANUDABLE, Y LA REANUDACION NO SE TRAGA UNA CORRIDA A MEDIO HACER. Cada (juego, semilla) escribe
# su propio JSON, pero "el archivo existe" NO alcanza para saltearlo: si el box mato la partida en
# la accion 1.750, ese archivo tiene un VOLCADO PARCIAL, y saltearlo dejaria ese juego truncado para
# siempre -- justo el defecto que este BL vino a cerrar del otro lado (la regla que le ponia
# casillero definitivo a una corrida truncada). El barrido saltea solo lo que esta COMPLETO; si
# encuentra un parcial lo ARCHIVA (`.parcial-N.json`, que la fusion sigue leyendo y desempata por
# completitud) y vuelve a jugar la partida desde el principio, que es la unica forma de reanudar
# que tiene el harness.
#
#     nohup setsid nice -n 19 scripts/estrato_a.sh > runtime_reports/bl21783/barrido.log 2>&1 &
set -u
cd "$(dirname "$0")/.."
DESTINO="${DESTINO:-runtime_reports/bl21783}"
ACCIONES="${ACCIONES:-4000}"
SEMILLAS_MAXIMAS="${SEMILLAS_MAXIMAS:-4}"
CARGA_MAXIMA="${CARGA_MAXIMA:-4}"
JUEGOS="${JUEGOS:-lp85 sc25 m0r0 g50t vc33 ft09}"
# TOPE DE RELOJ POR PARTIDA, porque el costo por accion NO es igual entre juegos ni constante
# dentro de uno. Medido en este BL: g50t promedio 0,151 s de CPU por accion a lo largo de 1.750
# acciones, y lp85 arranco en 0,151 y llego a 0,781 en la accion 750 (factor 5 contra si mismo).
# Sin tope, el juego mas caro se come la ventana entera y el barrido termina con UN juego medido en
# vez de cuatro. Con tope, el caro entrega su volcado parcial -- que igual contesta la curva hasta
# donde llego -- y los demas alcanzan a medirse.
# OJO AL REANUDAR: un juego que no entra en el tope nunca se completa repitiendo el barrido -- cada
# pasada lo archiva y lo vuelve a jugar desde cero, porque el harness no sabe retomar una partida a
# mitad de camino. Para terminarlo hay que SUBIRLE el tope a proposito; para dejarlo como esta y no
# gastar la ventana repitiendolo, `REJUGAR_PARCIALES=0` (abajo). 0 desactiva el tope.
SEGUNDOS_MAXIMOS_POR_PARTIDA="${SEGUNDOS_MAXIMOS_POR_PARTIDA:-9000}"
# QUE HACER CON UN PARCIAL QUE YA AGOTO SU TOPE. Por defecto (1) el barrido lo archiva y vuelve a
# jugar la partida, que es lo correcto cuando el parcial quedo de una interrupcion accidental. Pero
# si el parcial es el RESULTADO de haber agotado el tope de reloj, re-jugarlo gasta la ventana
# entera en repetir lo mismo y ademas TAPA a los juegos que todavia no se midieron: en ese caso se
# pasa 0 y el barrido lo da por medido hasta donde llego.
REJUGAR_PARCIALES="${REJUGAR_PARCIALES:-1}"
# QUE JUEGO MERECE UNA SEMILLA DE REFUERZO. Son dos preguntas distintas y el criterio NO es el mismo
# -- medido en vivo en este BL: con el criterio del mapa, el barrido salteo las segundas semillas de
# g50t y sc25, que son justo las dos que contestan la pregunta de la curva.
#   `niveles` -- "de que es capaz el juego". Un juego que ya puntuo no cambia de casillero por
#     correr mas semillas. Es el criterio del MAPA.
#   `delta`   -- "el presupuesto extra paga". Lo que cuenta es si gano niveles DESPUES del hito de
#     partida: sc25 puntua tres veces antes de la accion 800 y su delta 1.600->4.000 es CERO. Es el
#     criterio de la CURVA, y el default de este barrido porque es la pregunta que lo motiva.
# El mismo par de criterios vive en `presupuesto_de_la_medicion.plan_de_semillas`, que es quien
# calcula CUANTAS faltan; aca solo se decide a quien se le gasta la proxima.
CRITERIO_DE_REFUERZO="${CRITERIO_DE_REFUERZO:-delta}"
HITO_DE_PARTIDA="${HITO_DE_PARTIDA:-1600}"
mkdir -p -- "$DESTINO"

# Devuelve 0 si el juego YA mostro lo que se estaba buscando (segun CRITERIO_DE_REFUERZO) en alguna
# corrida, parcial o completa: un exito ganado no se pierde, asi que ese juego no necesita mas
# semillas.
ya_mostro_lo_que_se_busca() {
  .venv/bin/python - "$DESTINO" "$1" "$CRITERIO_DE_REFUERZO" "$HITO_DE_PARTIDA" <<'PY'
import glob, json, sys
destino, juego, criterio, hito = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
if criterio not in ("niveles", "delta"):
    raise SystemExit(f"criterio desconocido: {criterio}")
for ruta in glob.glob(f"{destino}/{juego}.*.json"):
    try:
        datos = json.loads(open(ruta, encoding="utf-8").read())
    except (OSError, ValueError):
        continue
    for fila in datos.get("mediciones", []):
        if fila.get("juego") != juego:
            continue
        finales = int(fila.get("nivelesFinales") or 0)
        if criterio == "niveles":
            if finales > 0:
                raise SystemExit(0)
            continue
        hitos = fila.get("nivelesPorHito") or {}
        if hito in hitos and finales > int(hitos[hito]):
            raise SystemExit(0)
raise SystemExit(1)
PY
}

# Devuelve 0 si ese archivo trae la corrida COMPLETA de ese (juego, semilla): una partida que
# termino sola o que llego al tope pedido. Un volcado parcial devuelve 1.
esta_completa() {
  .venv/bin/python - "$1" "$2" <<'PY'
import json, sys
ruta, tope = sys.argv[1], int(sys.argv[2])
try:
    datos = json.loads(open(ruta, encoding="utf-8").read())
except (OSError, ValueError):
    raise SystemExit(1)
for fila in datos.get("mediciones", []):
    if "nivelesPorHito" not in fila:
        continue
    if not fila.get("parcial", True) or int(fila.get("accionesConsumidas", 0)) >= tope:
        raise SystemExit(0)
raise SystemExit(1)
PY
}

corrida() {
  local juego="$1" semilla="$2"
  local salida="$DESTINO/$juego.$semilla.json"
  if [ -f "$salida" ]; then
    if esta_completa "$salida" "$ACCIONES"; then
      echo "[estrato-a] $juego $semilla ya esta completa, la salteo"
      return 0
    fi
    if [ "$REJUGAR_PARCIALES" != "1" ]; then
      echo "[estrato-a] $juego $semilla quedo parcial y REJUGAR_PARCIALES=0: se da por medida"
      return 0
    fi
    local archivo="$DESTINO/$juego.$semilla.parcial-$(date -u +%Y%m%dT%H%M%SZ).json"
    mv -- "$salida" "$archivo"
    echo "[estrato-a] $juego $semilla estaba a medio hacer: archivada en $archivo, se re-juega"
  fi
  echo "[estrato-a] $(date -u +%FT%TZ) $juego x $ACCIONES x $semilla -> $salida"
  local reloj=()
  if [ "$SEGUNDOS_MAXIMOS_POR_PARTIDA" -gt 0 ]; then
    # `--signal=INT` y no el KILL por defecto: el volcado parcial ya esta en disco al terminar cada
    # tramo de 250 acciones, asi que lo que se pierde es a lo sumo ese tramo, y una interrupcion
    # limpia deja el JSON bien formado en vez de a medio escribir.
    reloj=(timeout --signal=INT "$SEGUNDOS_MAXIMOS_POR_PARTIDA")
  fi
  "${reloj[@]}" nice -n 19 .venv/bin/python scripts/clasificacion_de_juegos.py \
    --juegos "$juego" --acciones "$ACCIONES" --semillas "$semilla" \
    --carga-maxima "$CARGA_MAXIMA" --json "$salida"
  local estado=$?
  if [ "$estado" -ne 0 ]; then
    echo "[estrato-a] $juego $semilla corto con estado $estado (tope de reloj o interrupcion): " \
      "queda el volcado parcial y el barrido sigue con el proximo juego"
  fi
  return 0
}

for ronda in $(seq 1 "$SEMILLAS_MAXIMAS"); do
  for juego in $JUEGOS; do
    if [ "$ronda" -gt 1 ] && ya_mostro_lo_que_se_busca "$juego"; then
      echo "[estrato-a] $juego ya cerro el criterio '$CRITERIO_DE_REFUERZO', no gasta mapa-$ronda"
      continue
    fi
    corrida "$juego" "mapa-$ronda"
  done
done

echo "[estrato-a] $(date -u +%FT%TZ) fin del barrido"
