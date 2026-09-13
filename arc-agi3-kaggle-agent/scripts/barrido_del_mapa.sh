#!/usr/bin/env bash
# [arc-agi3-kaggle-agent/scripts/barrido_del_mapa] BL.21763 -- el barrido de la re-medicion, en
# ORDEN DE INFORMACION POR SEGUNDO DE CPU y con una corrida por archivo para que sea reanudable.
#
# POR QUE ESTE ORDEN, y no "los 25 juegos de arriba a abajo". El box comparte 6 vCPU con el cron
# horario de partidas reales y la contencion medida hace que un segundo de CPU cueste ~13 de pared:
# el barrido completo no entra en ninguna ventana razonable. Entonces se ordena por lo que cada
# tramo CONTESTA:
#   1. g50t y vc33 a 400 acciones con TRES semillas cada uno. Es el tramo mas barato del barrido
#      (~64 s de CPU por corrida) y es el unico que puede distinguir las dos lecturas del dato mas
#      fuerte del BL: el mapa viejo tenia a g50t subiendo de nivel en la accion 154 y la re-medicion
#      da 0 niveles. O es varianza entre semillas -- y entonces el mapa viejo era fragil -- o el
#      agente de hoy REGRESIONO en ese juego, que seria un hallazgo mas grande que todo el mapa.
#      vc33 va como CONTROL: es un juego que si puntua temprano hoy, asi que si sus tres semillas
#      puntuan y las tres de g50t no, el instrumento no es el culpable.
#   2. Profundidad a 4000 sobre los juegos que el mapa viejo llamaba "limitados por presupuesto",
#      que es la pregunta cara del BL. Cada corrida vuelca parciales cada 250 acciones, asi que una
#      interrupcion entrega igual la curva hasta donde llego.
#
# Cada paso escribe su propio JSON: repetir el comando salteando los que ya existen reanuda el
# barrido sin re-jugar nada.
set -u
cd "$(dirname "$0")/.."
DESTINO="runtime_reports/bl21763"
mkdir -p "$DESTINO"

corrida() {
  local juego="$1" acciones="$2" semillas="$3" nombre="$4"
  local salida="$DESTINO/$nombre.json"
  if [ -f "$salida" ]; then
    echo "[barrido] $nombre ya existe, lo salteo"
    return 0
  fi
  echo "[barrido] $(date -u +%H:%M:%S) $juego x $acciones x [$semillas] -> $salida"
  nice -n 19 .venv/bin/python scripts/clasificacion_de_juegos.py \
    --juegos "$juego" --acciones "$acciones" --semillas "$semillas" --json "$salida"
}

# --- 1) el tramo que contesta varianza-vs-regresion, con margen de ruido -----------------------
corrida g50t 400 mapa-1,mapa-2,mapa-3 g50t.ruido400
corrida vc33 400 mapa-1,mapa-2,mapa-3 vc33.ruido400

# --- 2) profundidad: la pregunta de las 4000 acciones ------------------------------------------
corrida g50t 4000 mapa-1 g50t.hondo.mapa-1
corrida vc33 4000 mapa-1 vc33.hondo.mapa-1
corrida sc25 4000 mapa-1 sc25.hondo.mapa-1
corrida lp85 4000 mapa-1 lp85.hondo.mapa-1
corrida ft09 4000 mapa-1 ft09.hondo.mapa-1
corrida m0r0 4000 mapa-1 m0r0.hondo.mapa-1
corrida g50t 4000 mapa-2 g50t.hondo.mapa-2
corrida vc33 4000 mapa-2 vc33.hondo.mapa-2

echo "[barrido] $(date -u +%H:%M:%S) fin"
