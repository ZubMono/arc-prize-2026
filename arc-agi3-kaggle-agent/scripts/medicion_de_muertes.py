"""[arc-agi3-kaggle-agent/scripts/medicion_de_muertes] BL.21767 -- LA MEDICION QUE VA ANTES DEL
MECANISMO: cuantos juegos MUEREN (GAME_OVER) con el agente de HOY, y si la muerte es LOCAL (la
accion inmediata la causa) o viene de una CADENA.

POR QUE EXISTE. sp80 muere seis veces en 151 acciones (BL.21702) y el modelo de mundo no tiene
donde anotarlo: `kaggle_adapter.choose_action` le presenta el GAME_OVER a la politica como
NOT_STARTED, asi que el evento mas informativo de la partida se procesa como el arranque. Antes de
construir la memoria de muertes hay que contestar DOS preguntas con numeros, no con intuicion:

 1. TRANSVERSALIDAD. sp80 es UN juego de 25. Si es el unico que muere, la respuesta correcta es el
    abandono con reasignacion (BL.21701) y NO construir nada. La re-medicion de BL.21763 que iba a
    regalar este conteo quedo truncada en 1 juego de 25 (g50t: 15 GAME_OVERs en 1.750 acciones,
    `mediciones/BL21763_mapa_de_los_25_juegos.md` seccion 4.1), asi que el barrido se corre aca.
 2. LOCALIDAD. Si el agente muere por lo que hizo cinco pasos antes, penalizar la ultima accion es
    supersticion. Por cada muerte se graba la ventana de los ultimos `PROFUNDIDAD_DE_CONTEXTO`
    pares (firma de estado, accion), y sobre ellas se mide, POR PROFUNDIDAD, si el mismo par se
    repite entre muertes y que fraccion de sus ocurrencias termina en muerte (letalidad).

QUE ESPIA Y COMO. El instrumento envuelve `take_action` igual que `partida_instrumentada.py` y lee
con `getattr` las estructuras internas de la politica (`_prev_signature`, `_prev_mask_version`,
`_macro`): en el momento en que el framework emite la accion, `_prev_signature` es la firma del
estado DESDE el que se decidio y la accion emitida es la decidida -- exactamente el par que una
memoria de muertes registraria. Si una variante de la politica no expone esas estructuras, la
serie sale con None y el informe lo declara; la partida jamas se cae por el espia.

LOS PARES SE INDEXAN (firma, version de mascara, accion). Dos firmas calculadas con mascaras
distintas son hashes de dos definiciones de "estado" (BL.21558) y contarlas como el mismo par
inventaria repeticiones que no ocurrieron.

USO (mismo regimen de cortesia de carga que `clasificacion_de_juegos.py`):

    nice -n 19 .venv/bin/python scripts/medicion_de_muertes.py \\
        --pasos 200 --semillas bl21767-1,bl21767-2 \\
        --json mediciones/BL21767_muertes_por_juego.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from captura_de_niveles import describir_accion  # noqa: E402
from partida_instrumentada import (  # noqa: E402
    ACCIONES_ENTRE_MIRADAS_DE_CARGA,
    CARGA_MAXIMA_POR_DEFECTO,
    esperar_a_que_baje_la_carga,
)
from play_local import (  # noqa: E402
    aplicar_tope_de_pasos,
    cargar_modulo_agente,
    configurar_reloj,
    preparar_entorno,
    resolver_juegos,
)
from starter_config import ENVIRONMENTS_DIR  # noqa: E402

#: Cuantos pares (firma, accion) previos a cada muerte se graban. 5 y no mas: la hipotesis de
#: cadena que el BL manda a medir es "murio por lo que hizo cinco pasos antes"; una ventana mayor
#: multiplica el JSON sin agregar poder de decision sobre el mecanismo (depth-1 vs. traza).
PROFUNDIDAD_DE_CONTEXTO = 5

#: Umbral de LETALIDAD para el veredicto de localidad: fraccion de las ocurrencias de un par que
#: termina en muerte inmediata. 0,5 = "mas veces mata que no mata". Es deliberadamente grueso: el
#: veredicto por juego reporta la letalidad cruda al lado, asi que quien quiera otro corte lo
#: re-deriva del JSON sin volver a jugar.
LETALIDAD_MINIMA_LOCAL = 0.5

SEMILLAS_POR_DEFECTO = ("bl21767-1", "bl21767-2")
PASOS_POR_DEFECTO = 200


def analizar_localidad(
    muertes: list[dict], conteo_de_pares: dict[str, int]
) -> dict[str, object]:
    """El analisis que decide el MECANISMO, por profundidad de contexto.

    `muertes` trae por muerte la ventana `contexto` (pares serializados, el mas reciente ULTIMO).
    `conteo_de_pares` cuenta cuantas veces se emitio cada par en toda la corrida. Para cada
    profundidad d (1 = la accion inmediata):

      - `paresDistintos`: cuantos pares distintos aparecen a esa profundidad entre las muertes.
      - `repeticionMaxima`: cuantas muertes comparte el par mas repetido de esa profundidad.
      - `letalidadDelParMasRepetido`: muertes con ese par a profundidad d / ocurrencias totales
        del par. A d=1 es P(muerte inmediata | par); si es alta, la muerte es LOCAL y penalizar
        el par inmediato NO es supersticion.

    Vive como funcion pura (sin harness) para que el test la ejercite con muertes sinteticas."""
    por_profundidad: dict[str, dict[str, object]] = {}
    for d in range(1, PROFUNDIDAD_DE_CONTEXTO + 1):
        pares_a_esta_profundidad: dict[str, int] = {}
        for muerte in muertes:
            contexto = muerte.get("contexto") or []
            if len(contexto) < d:
                continue
            par = contexto[-d]
            pares_a_esta_profundidad[par] = pares_a_esta_profundidad.get(par, 0) + 1
        if not pares_a_esta_profundidad:
            continue
        par_mas_repetido, repeticiones = max(
            pares_a_esta_profundidad.items(), key=lambda kv: (kv[1], kv[0])
        )
        ocurrencias = conteo_de_pares.get(par_mas_repetido, 0)
        por_profundidad[str(d)] = {
            "paresDistintos": len(pares_a_esta_profundidad),
            "repeticionMaxima": repeticiones,
            "parMasRepetido": par_mas_repetido,
            "ocurrenciasDelParMasRepetido": ocurrencias,
            "letalidadDelParMasRepetido": (
                round(repeticiones / ocurrencias, 4) if ocurrencias else None
            ),
        }

    veredicto = "sinMuertes"
    if muertes:
        d1 = por_profundidad.get("1")
        if d1 is None:
            veredicto = "sinContextoObservable"
        elif (
            int(d1["repeticionMaxima"]) >= 2
            and d1["letalidadDelParMasRepetido"] is not None
            and float(d1["letalidadDelParMasRepetido"]) >= LETALIDAD_MINIMA_LOCAL
        ):
            # El MISMO par inmediato mato mas de una vez y mata en la mayoria de sus ocurrencias.
            veredicto = "local"
        elif int(d1["repeticionMaxima"]) >= 2:
            # El par inmediato se repite entre muertes pero casi siempre sobrevive: la accion
            # inmediata no explica la muerte por si sola. Contexto mas profundo o estado oculto.
            veredicto = "localDebil"
        elif any(
            int(por_profundidad[str(d)]["repeticionMaxima"]) >= 2
            for d in range(2, PROFUNDIDAD_DE_CONTEXTO + 1)
            if str(d) in por_profundidad
        ):
            veredicto = "cadena"
        else:
            veredicto = "sinPatronRepetido"
    return {"porProfundidad": por_profundidad, "veredicto": veredicto}


def resumir_partida(
    juego: str,
    semilla: str,
    acciones: int,
    niveles: int,
    muertes: list[dict],
    conteo_de_pares: dict[str, int],
    estado_final: str,
) -> dict:
    """La fila (juego, semilla), con el presupuesto perdido por morir ya derivado.

    `accionesEnTrayectoriasMortales` cuenta las acciones de cada tramo que TERMINO en GAME_OVER
    (desde el arranque o desde la muerte anterior): es el presupuesto cuyo rastro la muerte corto.
    No todas esas acciones fueron inutiles -- exploraron --, pero es la cota honesta de lo que el
    juego pierde por morir, que es el numero que el alcance del BL pide."""
    acciones_mortales = 0
    anterior = 0
    for muerte in muertes:
        acciones_mortales += int(muerte["accion"]) - anterior
        anterior = int(muerte["accion"])
    return {
        "juego": juego,
        "semilla": semilla,
        "accionesConsumidas": acciones,
        "nivelesFinales": niveles,
        "estadoFinal": estado_final,
        "gameOvers": len(muertes),
        "gameOversPor100Acciones": round(100.0 * len(muertes) / acciones, 2) if acciones else 0.0,
        "accionesEnTrayectoriasMortales": acciones_mortales,
        "fraccionDelPresupuestoEnTrayectoriasMortales": (
            round(acciones_mortales / acciones, 4) if acciones else 0.0
        ),
        "muertes": muertes,
        "localidad": analizar_localidad(muertes, conteo_de_pares),
    }


def medir_partida_con_muertes(arcade, modulo, juego: str, semilla: str, carga_maxima: float) -> dict:
    """Una partida contra el harness real con el espia de muertes puesto."""
    clase_agente = modulo.MyAgent
    entorno = arcade.make(juego, render_mode=None)
    if entorno is None:
        raise SystemExit(f"[muertes] no se pudo crear el entorno de {juego!r}.")
    clase_agente.SEMILLA = semilla
    agente = clase_agente(
        card_id="bl21767",
        game_id=juego,
        agent_name=f"MyAgent.bl21767.{juego}",
        ROOT_URL="http://localhost",
        record=False,
        arc_env=entorno,
        tags=["bl21767"],
    )
    politica = agente._politica
    emitir = agente.take_action

    contexto: deque[str] = deque(maxlen=PROFUNDIDAD_DE_CONTEXTO)
    conteo_de_pares: dict[str, int] = {}
    muertes: list[dict] = []
    pasos = [0]
    niveles = [0]

    def take_action(accion):
        descripcion = describir_accion(accion)
        firma = getattr(politica, "_prev_signature", None)
        mascara = getattr(politica, "_prev_mask_version", None)
        macro = getattr(politica, "_macro", None)
        macro_activa = getattr(macro, "accion_vigente", None)
        macro_pasos = int(getattr(macro, "pasos_emitidos", 0) or 0)
        click = (
            f"@{descripcion.x},{descripcion.y}"
            if descripcion.x is not None and descripcion.y is not None
            else ""
        )
        par = f"{firma}/m{mascara}:{descripcion.nombre}{click}"
        frame = emitir(accion)
        if frame is None:
            return frame
        pasos[0] += 1
        contexto.append(par)
        conteo_de_pares[par] = conteo_de_pares.get(par, 0) + 1
        niveles[0] = max(niveles[0], int(getattr(frame, "levels_completed", 0) or 0))
        if str(getattr(frame, "state", "")).endswith("GAME_OVER"):
            muertes.append(
                {
                    "accion": pasos[0],
                    "contexto": list(contexto),
                    "conMacroEnCurso": bool(macro_activa) and macro_pasos > 1,
                    "nivelesAlMorir": niveles[0],
                }
            )
        if carga_maxima > 0 and pasos[0] % ACCIONES_ENTRE_MIRADAS_DE_CARGA == 0:
            esperar_a_que_baje_la_carga(carga_maxima)
        return frame

    agente.take_action = take_action
    agente.main()
    return resumir_partida(
        juego,
        semilla,
        pasos[0],
        max(niveles[0], int(getattr(agente, "niveles_maximos", 0) or 0)),
        muertes,
        conteo_de_pares,
        str(agente.frames[-1].state),
    )


def agregar_barrido(filas: list[dict]) -> dict:
    """El veredicto de TRANSVERSALIDAD sobre todas las filas (juego x semilla) medidas."""
    por_juego: dict[str, dict] = {}
    for fila in filas:
        acumulado = por_juego.setdefault(
            fila["juego"],
            {"gameOvers": 0, "acciones": 0, "niveles": 0, "semillas": 0, "veredictosDeLocalidad": []},
        )
        acumulado["gameOvers"] += int(fila["gameOvers"])
        acumulado["acciones"] += int(fila["accionesConsumidas"])
        acumulado["niveles"] += int(fila["nivelesFinales"])
        acumulado["semillas"] += 1
        acumulado["veredictosDeLocalidad"].append(fila["localidad"]["veredicto"])
    juegos_que_mueren = sorted(j for j, v in por_juego.items() if v["gameOvers"] > 0)
    return {
        "juegosMedidos": len(por_juego),
        "juegosQueMueren": juegos_que_mueren,
        "cuantosMueren": len(juegos_que_mueren),
        "gameOversPorJuego": {
            j: v["gameOvers"] for j, v in sorted(por_juego.items()) if v["gameOvers"] > 0
        },
        "porJuego": dict(sorted(por_juego.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="BL.21767 -- muertes por juego y su localidad")
    parser.add_argument("--juegos", default=None, help="Ids separados por coma. Sin esto, los 25.")
    parser.add_argument("--pasos", type=int, default=PASOS_POR_DEFECTO)
    parser.add_argument("--semillas", default=",".join(SEMILLAS_POR_DEFECTO))
    parser.add_argument("--json", default=None, help="Ruta de salida.")
    parser.add_argument("--carga-maxima", type=float, default=CARGA_MAXIMA_POR_DEFECTO)
    parser.add_argument("--modo", default="offline", choices=["offline", "normal"])
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    preparar_entorno()
    import arc_agi
    from arc_agi import OperationMode

    modo = OperationMode.OFFLINE if args.modo == "offline" else OperationMode.NORMAL
    arcade = arc_agi.Arcade(operation_mode=modo, environments_dir=str(ENVIRONMENTS_DIR))
    juegos = resolver_juegos(arcade, args.juegos)
    modulo = cargar_modulo_agente()
    aplicar_tope_de_pasos(modulo.MyAgent, args.pasos)
    configurar_reloj(modulo, len(juegos), 0.0)  # reloj APAGADO: se mide presupuesto de acciones

    semillas = [s.strip() for s in args.semillas.split(",") if s.strip()]
    filas: list[dict] = []
    arranque = time.monotonic()
    for semilla in semillas:
        for indice, juego in enumerate(juegos, 1):
            esperar_a_que_baje_la_carga(args.carga_maxima)
            fila = medir_partida_con_muertes(arcade, modulo, juego, semilla, args.carga_maxima)
            filas.append(fila)
            print(
                f"  [{semilla} {indice}/{len(juegos)}] {juego}: gameOvers={fila['gameOvers']} "
                f"niveles={fila['nivelesFinales']} acciones={fila['accionesConsumidas']} "
                f"localidad={fila['localidad']['veredicto']}",
                flush=True,
            )
            if args.json:
                # Volcado incremental: una corrida interrumpida conserva lo ya medido (leccion de
                # BL.21763, cuyo barrido murio a 1 juego de 25 y perdio el resto por no volcar).
                volcar(args.json, filas, semillas, args.pasos, time.monotonic() - arranque)
    if not args.json:
        print(json.dumps(agregar_barrido(filas), indent=1, sort_keys=True))
    return 0


def volcar(ruta: str, filas: list[dict], semillas: list[str], pasos: int, reloj: float) -> None:
    destino = Path(ruta)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(
            {
                "bl": "BL.21767",
                "config": {
                    "pasos": pasos,
                    "semillas": semillas,
                    "profundidadDeContexto": PROFUNDIDAD_DE_CONTEXTO,
                    "letalidadMinimaLocal": LETALIDAD_MINIMA_LOCAL,
                },
                "relojSegundos": round(reloj, 1),
                "cargaAlVolcar": round(os.getloadavg()[0], 2),
                "resumen": agregar_barrido(filas),
                "filas": filas,
            },
            indent=1,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
