"""[arc-agi3-kaggle-agent/scripts/gate_de_merge] BL.21744 -- EL GATE DE MERGE del proyecto, contra
el HARNESS REAL (`arc_agi` + `environment_files`), y NO contra el banco parametrico.

POR QUE EXISTE ESTE ARCHIVO. Hasta BL.21744 el gate que varios BLs escribieron en su brief era
"se mergea SOLO si suben los NIVELES TOTALES sobre los 25 juegos, medido con
`scripts/medir_lazo_cerrado.py`". Ese gate era INGANABLE POR CONSTRUCCION: medido con BFS sobre la
geometria del banco parametrico, 19 de los 25 mundos simulados no podian llegar al nivel 1 hicieran
lo que hicieran (ver el docstring de `tests/support/mundos_medidos.py`). Un gate que no puede subir
no es conservador: es un FALSO NEGATIVO SISTEMATICO que rechaza toda mejora real y encima se lee
como rigor.

El harness real SI produce subidas de nivel con el agente actual -- medido en este mismo repo:
frames con `levelsCompleted > 0` en ft09, g50t, lp85, m0r0, sc25 y vc33, todos con
`modelId='harness-local'`. O sea: la senal que el gate necesita existe, solo que vive aca.

QUE MIDE: `niveles` (la metrica del premio: `levels_completed` del ultimo frame de cada partida) y
`acciones` gastadas, por juego y en total, con semilla FIJA para que dos corridas sean comparables.

COMO SE CORRE (reproducible, sin red, offline por defecto):

    # linea base del candidato a mergear
    .venv/bin/python scripts/gate_de_merge.py --json runtime_reports/gate_base.json

    # tras el cambio, comparando contra esa linea base: sale con codigo 1 si NO subio
    .venv/bin/python scripts/gate_de_merge.py --json runtime_reports/gate_nuevo.json \\
        --contra runtime_reports/gate_base.json

MULTI-SEMILLA POR DEFECTO (tres). Es la leccion 3 del rescate del banco de BL.21594: "3+ seeds
siempre, el signo del delta se daba vuelta entre seeds". Una sola semilla mide el PRNG, no la
politica.

COSTO MEDIDO (BL.21744, corridas reales sobre este harness compartido con otros agentes). La
columna CPU es la comparable entre maquinas; el reloj depende de cuantos cores UTILES tenga el box
y de la carga del momento. Cuantos son hoy no se escribe aca —un resize lo dejaria mintiendo en
silencio, BL.21937—: lo imprime `--reportar-costo`, derivado del SO (`scripts/recursos_del_host.py`,
mismo dato que la SSOT `scripts/lib/host-capacity.cjs`). Al medir esta tabla habia 6 utiles de 8.

  | corrida                        | acciones | CPU     | reloj    | s de CPU por accion |
  | ------------------------------ | -------- | ------- | -------- | ------------------- |
  | 1 juego (ls20) x 40 x 1        |       41 |   3,4 s |    3,6 s |               0,084 |
  | 25 juegos x 20 x 1             |      525 |  34,8 s |   38,3 s |               0,066 |
  | 3 juegos x 200 x 1             |      603 |  87,5 s |  125,3 s |               0,145 |
  | GATE COMPLETO (25 x 200 x 3)   |   15.000 | ~36 min |  ~52 min |               0,145 |

Las dos ultimas filas son la lectura importante: el costo por accion CRECE con la profundidad de
la partida (0,066 s a 20 acciones, 0,145 s a 200), asi que una corrida corta NO se puede proyectar
linealmente en profundidad. `--reportar-costo` proyecta bien porque corre la muestra a la MISMA
profundidad y solo recorta la cantidad de partidas. El reloj de pared salio ~1,4x la CPU con un
RATIO de carga de ~1,7 (load1 10 sobre los cores utiles de ese momento); en una maquina libre se
acerca a la CPU. El gate imprime AMBOS al terminar, y el ratio ya calculado para que nadie tenga
que elegir el divisor -- elegir el equivocado es el defecto que BL.21937 vino a cerrar.

USARLO CUESTA DOS CORRIDAS, no una. La tabla de arriba es el costo de UNA; el flujo son
`make gate-base` y despues `make gate`, o sea ~74 min de CPU y ~105 de reloj la primera vez, porque
no hay linea base commiteada (los JSON de `runtime_reports/` no se versionan). Si ya tenes una base
valida de la MISMA configuracion, la segunda corrida es la unica que pagas.

Para un lazo interno rapido: `--pasos 60 --semillas gate-1` (25 juegos x 60 acciones, ~2 min). OJO:
esa medicion NO es comparable con la del gate completo y el gate lo RECHAZA -- `nivelesTotales` es
una suma que crece con los juegos, los pasos y las semillas, asi que compararla contra una corrida
de 200x3 daria un delta positivo sin que el agente haya cambiado nada. Un lazo rapido se compara
contra otro lazo rapido de la misma forma.

El reloj de presupuesto del entregable se APAGA a proposito (`--presupuesto-horas 0`): un corte por
tiempo contaminaria la medicion, que es exactamente lo que BL.21701 dejo escrito."""
from __future__ import annotations

import argparse
import json
import logging
import os
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from play_local import (  # noqa: E402  (necesita el sys.path de arriba)
    aplicar_tope_de_pasos,
    cargar_modulo_agente,
    configurar_reloj,
    preparar_entorno,
    resolver_juegos,
)
from metricas_densas import agregar_densas, metricas_de_partida  # noqa: E402
from starter_config import ENVIRONMENTS_DIR  # noqa: E402

# BL.21937 — cores utiles/totales/reservados y el ratio de carga viven en UN modulo, derivados del
# SO y jamas escritos a mano. Ver su docstring para por que hacen falta los tres numeros y no uno.
from recursos_del_host import metricas_de_carga, texto_de_cores  # noqa: E402

#: Semillas por defecto. TRES y no una: leccion medida del intento fallido de BL.21594 ("el signo
#: del delta se daba vuelta entre seeds"). Fijas y no aleatorias para que el gate sea reproducible.
SEMILLAS_POR_DEFECTO = ("gate-1", "gate-2", "gate-3")

#: Acciones por partida. 200 es el mismo presupuesto por partida que usaba el banco parametrico,
#: para que los numeros de un BL viejo y uno nuevo se puedan leer en la misma escala.
PASOS_POR_DEFECTO = 200

#: Muestra de `--reportar-costo`. TRES juegos y no uno porque el costo por accion depende del juego
#: (tablero, mecanica y cuanto estado acumula la politica en el), y una muestra de uno solo es una
#: muestra de tamano 1. Los tres estan elegidos para cubrir el rango: ls20 mueve con flechas, vc33
#: y ft09 suben de nivel por click. Fijos, para que dos calibraciones sean comparables entre si.
JUEGOS_DE_CALIBRACION = ("ls20", "vc33", "ft09")


def _cpu_segundos() -> float:
    """CPU de ESTE proceso y sus hijos. Es la magnitud que no depende de la contencion de la
    maquina -- el reloj de pared si, y por eso se informan las dos."""
    propio = resource.getrusage(resource.RUSAGE_SELF)
    hijos = resource.getrusage(resource.RUSAGE_CHILDREN)
    return propio.ru_utime + propio.ru_stime + hijos.ru_utime + hijos.ru_stime




def correr(arcade, clase_agente, juegos: list[str], semilla: str) -> dict[str, dict[str, object]]:
    """Una pasada completa de los juegos pedidos con UNA semilla."""
    salida: dict[str, dict[str, object]] = {}
    for indice, juego in enumerate(juegos, 1):
        entorno = arcade.make(juego, render_mode=None)
        if entorno is None:
            print(f"  [{indice}/{len(juegos)}] {juego}: no se pudo crear el entorno, se saltea")
            continue
        agente = clase_agente(
            card_id="gate-de-merge",
            game_id=juego,
            agent_name=f"MyAgent.gate.{juego}",
            ROOT_URL="http://localhost",
            record=False,
            arc_env=entorno,
            tags=["gate-de-merge"],
        )
        agente.main()
        ultimo = agente.frames[-1]
        salida[juego] = {
            # MAXIMO observado y no el del ultimo frame. El propio agente lo advierte
            # (`policy.py`: "el frame terminal de un GAME_OVER puede traer el contador ya en cero"),
            # y quedarse con el ultimo tiraria justo el credito parcial que la metrica del premio
            # cuenta -- un falso negativo de la misma especie que BL.21744 vino a eliminar, dentro
            # del instrumento que lo reemplaza. `getattr` porque el agente inlineado del entregable
            # tambien tiene que poder correr el gate aunque no exponga la propiedad.
            "niveles": max(int(ultimo.levels_completed), int(getattr(agente, "niveles_maximos", 0))),
            "acciones": int(agente.action_counter),
            "estado": str(ultimo.state),
            # BL.22856 -- las densas se derivan de los frames YA jugados: costo de medir ~cero,
            # y el agente no se toca. Que candidata ENTRA al veredicto lo decide la calibracion
            # contra el par conocidamente distinto, no este archivo.
            "densas": metricas_de_partida(agente.frames),
        }
        print(
            f"  [{indice}/{len(juegos)}] {juego}: niveles={salida[juego]['niveles']} "
            f"acciones={salida[juego]['acciones']} (semilla {semilla})"
        )
    return salida


def agregar(por_semilla: dict[str, dict[str, dict[str, int]]]) -> dict[str, object]:
    """Suma los niveles de todas las semillas y juegos: la fila unica que decide el merge."""
    niveles = 0
    acciones = 0
    por_juego: dict[str, int] = {}
    for medicion in por_semilla.values():
        for juego, fila in medicion.items():
            niveles += int(fila["niveles"])
            acciones += int(fila["acciones"])
            por_juego[juego] = por_juego.get(juego, 0) + int(fila["niveles"])
    return {
        "nivelesTotales": niveles,
        "accionesTotales": acciones,
        "juegosConNivel": sum(1 for v in por_juego.values() if v > 0),
        "nivelesPorJuego": dict(sorted(por_juego.items())),
        # BL.22856 -- totales de las metricas densas. SOLO se agregan al JSON: el veredicto del
        # gate (delta de niveles) NO cambia aca; cambiarlo es decision de BL.22855 y recien
        # despues de que la calibracion demuestre que candidata separa el par conocido.
        "densasTotales": agregar_densas(por_semilla),
    }


#: Campos de `config` que TIENEN que coincidir para que dos mediciones se puedan restar. No es una
#: lista de higiene: `nivelesTotales` es una SUMA sobre juegos x semillas y crece con cada uno de
#: ellos, asi que comparar contra una base medida con menos juegos, menos pasos o menos semillas
#: produce un "delta positivo" sin que el agente haya cambiado una linea. `juegosMedidos` esta
#: aparte de `juegos` a proposito: `correr()` SALTEA en silencio todo juego cuyo entorno no se pudo
#: crear, asi que dos corridas pueden pedir los mismos 25 y haber medido conjuntos distintos.
CAMPOS_COMPARABLES = ("juegos", "juegosMedidos", "pasos", "semillas", "modo")


def motivos_de_incomparabilidad(config_base, config_ahora, campos=CAMPOS_COMPARABLES) -> list[str]:
    """Por que NO se pueden restar estas dos mediciones. Lista vacia = son comparables.

    Existe por el falso POSITIVO que la refutacion de BL.21744 encontro en este mismo gate: una
    linea base sin bloque `config` (o con un campo faltante) pasaba el control y el gate imprimia
    "APROBADO" comparando dos corridas de configuracion distinta. Reproducido el 2026-08-19 con una
    base fabricada de tres claves: `0 -> 1 (delta +1)` y exit code 0, sin tocar el agente. El error
    es el espejo exacto del falso negativo que el BL vino a eliminar, y en un gate de merge es el
    mas caro de los dos: uno rechaza mejoras, el otro MERGEA lo que no mejoro.

    `banderas` NO entra en la lista: comparar dos paquetes de palancas es justamente para lo que
    existe la bandera (la ablacion de BL.21702). Se imprime siempre, para que la comparacion quede
    declarada."""
    if not isinstance(config_base, dict) or not config_base:
        return [
            "la linea base no trae bloque `config`: no hay forma de saber con que juegos, cuantos "
            "pasos ni cuantas semillas se midio, y `nivelesTotales` crece con las tres. Una base "
            "sin config solo puede venir de una version vieja del gate o de un archivo a mano"
        ]
    motivos = []
    for campo in campos:
        if campo not in config_base:
            motivos.append(f"la linea base no declara `{campo}`")
            continue
        antes, ahora = config_base[campo], config_ahora.get(campo)
        if antes != ahora:
            motivos.append(f"`{campo}`: la base midio {antes!r} y esta corrida {ahora!r}")
    return motivos


def salida_config_juegos_medidos(por_semilla: dict) -> list[str]:
    """Los juegos que TODAS las semillas midieron. Interseccion y no union: si una semilla se salteo
    un juego, esa semilla midio otra cosa y el total ya no es comparable."""
    medidos = [set(m) for m in por_semilla.values()]
    if not medidos:
        return []
    return sorted(set.intersection(*medidos))


def calibrar_costo(
    arcade, clase_agente, juegos_del_gate: list[str], pasos: int, semillas: int
) -> dict[str, object]:
    """Corre una MUESTRA chica y proyecta lo que va a costar el gate completo, en CPU y en reloj.

    Existe porque el gate completo son ~15.000 acciones y nadie deberia enterarse de lo que cuesta
    DESPUES de haberlo pagado -- menos todavia en una maquina compartida con otros agentes.

    La muestra corre a la MISMA profundidad (`--pasos`) que el gate, y eso no es un detalle: el
    costo por accion CRECE con la profundidad de la partida, porque la memoria de estados de la
    politica se agranda y cada decision mira mas historia. Medido en BL.21744 sobre este mismo
    harness: 0,066 s de CPU por accion a 20 acciones por partida contra 0,145 s a 200. Una
    calibracion corta proyectada linealmente subestimaria el gate a menos de la mitad, que es
    justo el error que esta bandera existe para evitar. Lo que la muestra SI recorta es la
    CANTIDAD de partidas (3 juegos x 1 semilla en vez de 25 x 3), y ahi la proyeccion SI es
    lineal: cada partida es independiente de las demas."""
    presupuesto = len(juegos_del_gate) * pasos * semillas
    print(
        f"[calibracion] muestra: {len(JUEGOS_DE_CALIBRACION)} juego(s) x {pasos} acciones "
        f"(la MISMA profundidad del gate). Se proyecta a sus {presupuesto} acciones.\n"
    )
    aplicar_tope_de_pasos(clase_agente, pasos)
    clase_agente.SEMILLA = "calibracion"
    cpu0, reloj0 = _cpu_segundos(), time.monotonic()
    medicion = correr(arcade, clase_agente, list(JUEGOS_DE_CALIBRACION), "calibracion")
    cpu = _cpu_segundos() - cpu0
    reloj = time.monotonic() - reloj0
    acciones = sum(int(f["acciones"]) for f in medicion.values()) or 1
    por_accion_cpu = cpu / acciones
    por_accion_reloj = reloj / acciones
    proyeccion = {
        "accionesDeLaMuestra": acciones,
        "cpuSegundosPorAccion": round(por_accion_cpu, 4),
        "relojSegundosPorAccion": round(por_accion_reloj, 4),
        "accionesDelGateCompleto": presupuesto,
        "cpuMinutosProyectados": round(por_accion_cpu * presupuesto / 60.0, 1),
        "relojMinutosProyectados": round(por_accion_reloj * presupuesto / 60.0, 1),
        **metricas_de_carga(),
    }
    print("\n========= COSTO PROYECTADO DEL GATE =========")
    print(json.dumps(proyeccion, indent=1, sort_keys=True))
    print(
        "\nEl reloj de pared depende de la contencion de la maquina y el de arriba se midio con la "
        f"carga que habia: load1 {proyeccion['cargaAlMedir']} sobre "
        f"{texto_de_cores()} = ratio {proyeccion['ratioDeCargaAlMedir']}. "
        "La CPU es la magnitud comparable entre corridas."
    )
    return proyeccion


from arc_agent.veredicto_de_merge import MODO_MEJORA, MODO_SIN_REGRESION, evaluar as evaluar_veredicto


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate de merge contra el harness REAL de ARC-AGI-3 (no el banco parametrico)"
    )
    parser.add_argument("--juego", default=None, help="Ids separados por coma. Sin esto, los 25.")
    parser.add_argument("--pasos", type=int, default=PASOS_POR_DEFECTO)
    parser.add_argument(
        "--semillas",
        default=",".join(SEMILLAS_POR_DEFECTO),
        help="Semillas separadas por coma. Una sola mide el PRNG, no la politica.",
    )
    parser.add_argument("--json", default=None, help="Ruta donde dejar la medicion completa.")
    parser.add_argument(
        "--contra",
        default=None,
        help="JSON de una corrida anterior. El gate FALLA (codigo 1) si los niveles totales no "
        "superan a los de esa corrida.",
    )
    parser.add_argument("--modo", default="offline", choices=["offline", "normal"])
    # BL.22855 — QUE se esta juzgando. Se llama --juicio y no --modo porque ese nombre ya estaba
    # tomado por offline/normal, que es otra cosa (el entorno de la corrida, no el veredicto).
    parser.add_argument(
        "--juicio",
        default=None,
        choices=[MODO_MEJORA, MODO_SIN_REGRESION],
        help="QUE se le pide a este cambio. 'mejora': el delta tiene que SUPERAR la banda de ruido "
        "medida. 'sin-regresion': alcanza con que no baje MAS ALLA de esa banda -- es lo que necesita "
        "una correccion. Sin este flag rige el criterio historico (delta>0), que MIDE RUIDO: 5 "
        "corridas del mismo codigo dieron 7 a 11 niveles (BL.22395).",
    )
    parser.add_argument(
        "--resolucion",
        default=None,
        help="JSON de resolucion_del_gate.py, del que sale la BANDA DE RUIDO. Sin el, --juicio no "
        "puede decidir y lo dice (fail-closed) en vez de asumir un numero.",
    )
    parser.add_argument(
        "--banderas",
        default=None,
        help="Palancas de arc_agent/banderas.py para ESTA corrida (BL.21702). Ej.: 'ninguna' para "
        "la linea base, '-macroCambioInformativo' para medir todo menos esa. Se aplica antes de "
        "cargar el agente y queda anotado en el JSON: dos mediciones con palancas distintas no se "
        "pueden confundir.",
    )
    parser.add_argument(
        "--reportar-costo",
        action="store_true",
        help="No corre el gate: mide una muestra chica y proyecta lo que costaria la corrida "
        "completa en CPU y en reloj. Correlo ANTES de ocupar la maquina media hora.",
    )
    args = parser.parse_args()

    # WARNING y no INFO: el harness real loguea una linea por accion, y 15.000 lineas de log
    # cuestan mas I/O que la propia medicion.
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    # BL.21702 -- las palancas se leen al IMPORTAR el agente, asi que la variable tiene que estar
    # puesta antes de `cargar_modulo_agente()`. Fijarla aca (y no exigir un `export` al que la
    # corre) es lo que permite que el JSON declare con que configuracion se midio.
    if args.banderas is not None:
        os.environ["ARC_AGENT_BANDERAS"] = args.banderas
    banderas_efectivas = os.environ.get("ARC_AGENT_BANDERAS", "(default: las entregadas)")
    print(f"[gate] palancas de exploracion: {banderas_efectivas}")
    preparar_entorno()

    import arc_agi
    from arc_agi import OperationMode

    modo = OperationMode.OFFLINE if args.modo == "offline" else OperationMode.NORMAL
    arcade = arc_agi.Arcade(operation_mode=modo, environments_dir=str(ENVIRONMENTS_DIR))
    juegos = resolver_juegos(arcade, args.juego)
    modulo_agente = cargar_modulo_agente()
    clase_agente = modulo_agente.MyAgent
    aplicar_tope_de_pasos(clase_agente, args.pasos)
    # 0 = reloj APAGADO: un corte por tiempo contaminaria la medicion (BL.21701).
    configurar_reloj(modulo_agente, len(juegos), 0.0)

    semillas = [s.strip() for s in args.semillas.split(",") if s.strip()]
    if args.reportar_costo:
        calibrar_costo(arcade, clase_agente, juegos, args.pasos, len(semillas))
        return 0

    # LA COMPARACION SE VALIDA ANTES DE MEDIR, no despues. El gate completo son ~36 min de CPU:
    # descubrir al final que la base no existe (traceback) o que se midio con otra configuracion es
    # tirar media hora de maquina compartida. Los tres campos que se pueden verificar sin medir
    # -- juegos, pasos y semillas -- se verifican aca; `juegosMedidos` recien existe despues de
    # correr, y lo verifica `motivos_de_incomparabilidad` al final.
    if args.contra:
        ruta_base = Path(args.contra)
        if not ruta_base.exists():
            print(
                f"GATE: RECHAZADO -- no existe la linea base {args.contra}. Medila primero con "
                f"`--json {args.contra}` (o `make gate-base`) SIN el cambio que queres evaluar: "
                "usar el gate cuesta DOS corridas, no una."
            )
            return 1
        previos = motivos_de_incomparabilidad(
            json.loads(ruta_base.read_text(encoding="utf-8")).get("config"),
            {"juegos": juegos, "pasos": args.pasos, "semillas": semillas, "modo": args.modo},
            campos=("juegos", "pasos", "semillas", "modo"),
        )
        if previos:
            print("GATE: RECHAZADO -- la linea base no es comparable con esta corrida:")
            for motivo in previos:
                print(f"  - {motivo}")
            print("No se midio nada: el gate se niega ANTES de gastar la CPU.")
            return 1

    print(
        f"[gate] {len(juegos)} juego(s) x {args.pasos} acciones x {len(semillas)} semilla(s) = "
        f"{len(juegos) * args.pasos * len(semillas)} acciones de presupuesto.\n"
    )

    cpu0, reloj0 = _cpu_segundos(), time.monotonic()
    por_semilla: dict[str, dict[str, dict[str, int]]] = {}
    for semilla in semillas:
        clase_agente.SEMILLA = semilla
        print(f"--- semilla {semilla!r} ---")
        por_semilla[semilla] = correr(arcade, clase_agente, juegos, semilla)
    cpu = _cpu_segundos() - cpu0
    reloj = time.monotonic() - reloj0

    resumen = agregar(por_semilla)
    acciones = int(resumen["accionesTotales"]) or 1
    costo = {
        "cpuSegundos": round(cpu, 2),
        "cpuMinutos": round(cpu / 60.0, 2),
        "relojSegundos": round(reloj, 2),
        "relojMinutos": round(reloj / 60.0, 2),
        "cpuSegundosPorAccion": round(cpu / acciones, 4),
        "relojSegundosPorAccion": round(reloj / acciones, 4),
        # BL.21937 — `cargaAlMedir` aca es la carga AL TERMINAR la corrida; se conserva el nombre
        # anterior (`cargaAlTerminar`) como alias para no romper un lector viejo del JSON.
        **metricas_de_carga(),
        "cargaAlTerminar": round(os.getloadavg()[0], 2),
    }

    print("\n========= GATE DE MERGE (harness real) =========")
    for juego, niveles in resumen["nivelesPorJuego"].items():  # type: ignore[union-attr]
        print(f"  {juego:8} niveles={niveles}")
    print(
        f"\nNIVELES TOTALES: {resumen['nivelesTotales']}  "
        f"(juegos con al menos un nivel: {resumen['juegosConNivel']}/{len(juegos)})"
    )
    print(f"COSTO: {json.dumps(costo, sort_keys=True)}")
    # LINEA CONTRATO con la valvula de submission de Kaggle (`scripts/lib/arcKaggleBanco.cjs`).
    # Desde la correccion de BL.21744 esa valvula decide con el HARNESS REAL y no con el banco
    # parametrico, y lee esta linea con el mismo parser de siempre (`parsearTotalesBanco`). Lleva
    # `juegosMedidos` porque `correr()` saltea en silencio el juego cuyo entorno no se pudo crear:
    # sin ese numero, una corrida a la que le faltan juegos se leeria como una caida del agente.
    print(
        "TOTALES: "
        + json.dumps(
            {
                "niveles": resumen["nivelesTotales"],
                "acciones": resumen["accionesTotales"],
                "juegosConNivel": resumen["juegosConNivel"],
                "juegosMedidos": len(salida_config_juegos_medidos(por_semilla)),
                "juegosPedidos": len(juegos),
            },
            sort_keys=True,
        )
    )

    salida = {
        "config": {
            "juegos": juegos,
            # Los que de verdad se midieron: `correr()` saltea el juego cuyo entorno no se pudo
            # crear, y una base con juegos saltados infla el delta contra una corrida completa.
            "juegosMedidos": salida_config_juegos_medidos(por_semilla),
            "pasos": args.pasos,
            "semillas": semillas,
            "modo": args.modo,
            # BL.21702 -- con que palancas se midio. Es lo que vuelve comparable (o incomparable)
            # una corrida con otra; sin este campo dos JSON identicos podrian ser dos agentes
            # distintos.
            "banderas": banderas_efectivas,
        },
        "porSemilla": por_semilla,
        "totales": resumen,
        "costo": costo,
    }
    if args.json:
        destino = Path(args.json)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(salida, indent=1, sort_keys=True), encoding="utf-8")
        print(f"Medicion escrita en {destino}")

    if args.contra:
        base = json.loads(Path(args.contra).read_text(encoding="utf-8"))
        motivos = motivos_de_incomparabilidad(base.get("config"), salida["config"])
        if motivos:
            print("\nGATE: RECHAZADO -- la linea base no es comparable con esta corrida:")
            for motivo in motivos:
                print(f"  - {motivo}")
            print(
                "Volve a medir la linea base con la MISMA configuracion "
                f"(`--pasos {args.pasos} --semillas {','.join(semillas)}`) o compara contra otra."
            )
            return 1
        antes = int(base["totales"]["nivelesTotales"])
        ahora = int(resumen["nivelesTotales"])
        delta = ahora - antes
        print(
            f"\nCONTRA {args.contra}: {antes} -> {ahora} (delta {delta:+d})  "
            f"[palancas base={base['config'].get('banderas', 'desconocidas')!r} "
            f"vs. ahora={banderas_efectivas!r}]"
        )
        # BL.22855 — con --juicio, el veredicto lo decide veredicto_de_merge contra la BANDA DE
        # RUIDO medida. Sin --juicio se conserva el criterio historico, que MIDE RUIDO: 5 corridas
        # del MISMO codigo dieron 7 a 11 niveles (rango 4), asi que un delta=+1 es indistinguible
        # de una corrida afortunada y un delta=0 de una mejora que el instrumento no ve.
        if args.juicio:
            medicion = None
            if args.resolucion:
                try:
                    medicion = json.loads(Path(args.resolucion).read_text(encoding="utf-8"))
                except (OSError, ValueError) as e:
                    print(f"GATE: no se pudo leer la resolucion ({e}). No se asume ninguna banda.")
            v = evaluar_veredicto(delta, args.juicio, medicion)
            print(f"\nGATE: {v['texto']}")
            if v["indeterminado"]:
                # 2 y no 1: "no pude juzgar" NO es "rechazado". Confundirlos es la misma clase de
                # defecto que este BL cierra un nivel mas arriba.
                return 2
            return 0 if v["aprobado"] else 1

        if delta <= 0:
            print("GATE: RECHAZADO -- los niveles totales no subieron. No se mergea.")
            print(
                "  OJO (BL.22395): este criterio MIDE RUIDO. 5 corridas del MISMO codigo dieron 7 a 11\n"
                "  niveles. Si este cambio es una CORRECCION y no una mejora de score, el juicio\n"
                "  correcto es otro:  --juicio sin-regresion --resolucion <medicion.json>"
            )
            return 1
        print("GATE: APROBADO -- los niveles totales subieron.")
        print(
            "  OJO (BL.22395): con 1 corrida por lado, lo minimo distinguible del ruido es un salto de\n"
            "  ~4 niveles. Un delta chico puede ser una corrida afortunada:  --juicio mejora"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
