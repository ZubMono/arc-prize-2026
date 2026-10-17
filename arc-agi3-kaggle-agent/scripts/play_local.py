"""[arc-agi3-kaggle-agent/scripts/play_local] BL.21554 -- corre `agent/my_agent.py` contra los
juegos REALES de ARC-AGI-3, en proceso y sin red.

Es el loop interno rapido de la cadena de entrega: el motor de juego lo hospeda el paquete
`arc-agi` (la misma wheel que corre el gateway de Kaggle) y el loop lo maneja `Agent.main()` del
framework oficial. Lo unico que cambia respecto de Kaggle es que aca no hay gateway HTTP: el
entorno es local.

MODO OFFLINE POR DEFECTO, a proposito. Los juegos ya vienen en el dataset de la competencia
(`environment_files/`, los baja `scripts/fetch_competition_data.py`), asi que no hay ninguna razon
para que el modo NORMAL del paquete salga a la API oficial a pedir una API key anonima y
re-descargar lo que ya tenemos. Es ademas la unica configuracion coherente con la restriccion dura
del proyecto: el notebook de evaluacion corre SIN INTERNET. `--modo normal` existe como escape si
alguna vez hay que refrescar un juego contra la API.

`--max-pasos` PISA `MyAgent.MAX_ACTIONS`, hacia arriba o hacia abajo (BL.21701). Hasta ese BL la
linea era `MAX_ACTIONS = min(MAX_ACTIONS, args.max_pasos)`, o sea que pedir 800 dejaba 400: NADIE
podia medir por encima del valor entregado ni por accidente, y por eso el proyecto entrego durante
meses un presupuesto de acciones que jamas se habia medido. Sin la bandera no se toca nada y se
juega con el tope del entregable.

`--presupuesto-horas` fija el reloj global del entregable (`arc_agent/reloj_presupuesto.py`) para
la corrida local. 0 lo APAGA, que es lo que quiere un barrido de medicion: ahi se mide el costo de
un presupuesto de acciones, y un corte por tiempo contaminaria la medicion.

`--capturar-niveles` (BL.21695) graba a un JSONL la VENTANA de frames alrededor de cada subida de
`levels_completed`. Es el unico lugar del proyecto donde se observa COMO SE VE GANAR: el corpus
online (`arcReplayFrames`) tenia 2.456 documentos y CERO con `levelsCompleted > 0`, porque las
subidas de nivel medidas ocurrieron todas aca, en el harness local, que no persistia nada. La
justificacion del ancho de ventana esta en `scripts/captura_de_niveles.py`. El ingestor a Mongo
vive en el monorepo (`node scripts/ingestar-ventanas-nivel-arc.cjs`) y no aca: este sub-proyecto es
stdlib pura y no habla con Mongo ni con la red.

Uso:
    .venv/bin/python scripts/play_local.py --listar
    .venv/bin/python scripts/play_local.py --juego ls20,vc33 --max-pasos 50
    .venv/bin/python scripts/play_local.py --max-pasos 1600 --presupuesto-horas 0  # barrido
    .venv/bin/python scripts/play_local.py                      # todos los juegos
    .venv/bin/python scripts/play_local.py --juego vc33 --max-pasos 80 \\
        --presupuesto-horas 0 --capturar-niveles runtime_reports/ventanas_de_nivel.jsonl
"""
from __future__ import annotations

import argparse
import importlib.util
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from captura_de_niveles import (  # noqa: E402  (necesita el sys.path de arriba)
    VENTANA_POR_DEFECTO,
    agregar_a_jsonl,
    registrar_acciones,
    ventanas_de_nivel,
)
from cobertura_de_fondo import (  # noqa: E402  (necesita el sys.path de arriba)
    FRACCION_POR_DEFECTO,
    RedireccionAlFondo,
)
from starter_config import (  # noqa: E402  (necesita el sys.path de arriba)
    AGENT_SRC_PATH,
    ENVIRONMENTS_DIR,
    VENDOR_DIR,
    exportar_environments_dir,
    faltantes_para_jugar,
)

#: Identidad del productor del corpus dentro de `arcReplayFrames.modelId`. Distinta de la del
#: runner online a proposito: quien lea el corpus tiene que poder separar "esto lo jugo el harness
#: local offline" de "esto lo jugo el runner contra la API oficial" sin adivinar.
MODELO_DE_CAPTURA = "harness-local"


def preparar_entorno() -> None:
    """Deja el proceso listo para importar el framework y encontrar los juegos.

    Falla con instrucciones (no con un ImportError críptico) si falta el dataset."""
    faltan = faltantes_para_jugar()
    if faltan:
        raise SystemExit(
            "[play_local] Falta el dataset de la competencia:\n  - "
            + "\n  - ".join(faltan)
            + "\nCorre `make setup` (baja el dataset con el token del repo y arma el venv)."
        )
    exportar_environments_dir()
    sys.path.insert(0, str(VENDOR_DIR))


def cargar_modulo_agente():
    """Importa `agent/my_agent.py` por ruta (no por nombre de paquete) y devuelve el MODULO.

    Se hace por ruta para que el archivo del agente sea exactamente el mismo objeto que
    `build_kernel_notebook.py` inlinea en el notebook: un unico archivo, sin capa de indireccion
    que pueda divergir entre lo que se prueba local y lo que se entrega. Devuelve el modulo entero
    y no solo la clase porque el reloj de presupuesto (BL.21701) tambien vive ahi."""
    if not AGENT_SRC_PATH.exists():
        raise SystemExit(f"[play_local] No existe {AGENT_SRC_PATH}.")
    spec = importlib.util.spec_from_file_location("agente_del_usuario", AGENT_SRC_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit(f"[play_local] No se pudo cargar {AGENT_SRC_PATH}.")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    if not hasattr(modulo, "MyAgent"):
        raise SystemExit(
            f"[play_local] {AGENT_SRC_PATH} tiene que definir una clase llamada `MyAgent` "
            "(lo exige el registro de agentes del framework oficial)."
        )
    return modulo


def aplicar_tope_de_pasos(clase_agente: type, max_pasos: int | None) -> int | None:
    """Pisa `MAX_ACTIONS` con lo pedido y devuelve el valor que queda vigente.

    SIN `min()` A PROPOSITO (BL.21701). El `min` anterior convertia el tope entregado en un techo
    infranqueable para la herramienta de medicion: cualquier barrido por encima de ese valor
    devolvia silenciosamente el mismo numero de siempre, y el barrido "medido" no media nada nuevo.
    `--max-pasos` es una orden del que mide, no una sugerencia. Sin la bandera (None) no se toca
    nada y se juega con el tope del entregable."""
    if not hasattr(clase_agente, "MAX_ACTIONS"):
        return None
    if max_pasos is not None:
        clase_agente.MAX_ACTIONS = int(max_pasos)
    return clase_agente.MAX_ACTIONS


def configurar_reloj(modulo_agente, total_de_juegos: int, presupuesto_horas: float | None):
    """Deja el reloj global del entregable listo para la corrida local. Devuelve el reloj (o None
    si el agente cargado no lo trae, ej. un my_agent.py viejo).

    Declarar el total de juegos es OBLIGATORIO aca y no en Kaggle: este script juega EN SERIE, asi
    que el reloj solo veria una partida viva y le daria el presupuesto entero a la primera. El
    Swarm oficial construye los N agentes antes de arrancar los hilos y no necesita el aviso."""
    reloj = getattr(modulo_agente, "RELOJ_GLOBAL", None)
    if reloj is None:
        print("[play_local] AVISO: el agente cargado no trae reloj de presupuesto (BL.21701).")
        return None
    if presupuesto_horas is not None:
        clase_reloj = type(reloj)
        reloj = clase_reloj(presupuesto_segundos=float(presupuesto_horas) * 3600.0)
        modulo_agente.MyAgent.RELOJ = reloj
    reloj.declarar_total_de_partidas(total_de_juegos)
    if reloj.reloj_apagado:
        print("[play_local] Reloj de presupuesto APAGADO: solo corta --max-pasos.\n")
    else:
        horas = reloj.presupuesto_segundos / 3600.0
        print(
            f"[play_local] Reloj de presupuesto: {horas:.2f} h para {total_de_juegos} juego(s) "
            f"({reloj.presupuesto_segundos / max(1, total_de_juegos):.0f} s por juego).\n"
        )
    return reloj


def resolver_juegos(arcade, pedidos: str | None) -> list[str]:
    """Ids cortos de los juegos a jugar. Sin `--juego`, todos los del dataset."""
    disponibles = [entorno.game_id.split("-")[0] for entorno in arcade.get_environments()]
    if not pedidos:
        print(f"[play_local] Sin --juego: se juegan los {len(disponibles)} juegos del dataset.\n")
        return disponibles

    querido = {pedido.strip().split("-")[0] for pedido in pedidos.split(",") if pedido.strip()}
    elegidos = [juego for juego in disponibles if juego in querido]
    faltantes = querido - set(elegidos)
    if faltantes:
        raise SystemExit(
            f"[play_local] Juego(s) desconocido(s): {sorted(faltantes)}. "
            "Corre `--listar` para ver los disponibles."
        )
    return elegidos


def capturar_niveles(
    agente,
    juego: str,
    lote: str,
    destino: Path,
    ventana: int,
    acciones,
    semilla: str = "",
) -> int:
    """BL.21695 -- graba la ventana de frames de cada subida de nivel de ESTA partida.

    Corre DESPUES de `main()`: `Agent.frames` es la grabacion completa que el framework oficial ya
    mantiene, asi que el analisis de la ventana no cuesta nada dentro del loop de decision -- y un
    analisis ahi alteraria el costo por accion, que es una de las magnitudes medidas del proyecto
    (0,154 s a 0,202 s por accion, BL.21701). Lo unico que si vive dentro del loop es el registro de
    la accion emitida (`registrar_acciones`), un append a una lista: el motor offline no informa la
    accion en el frame y sin ese append el corpus atribuiria TODO a un RESET.

    NUNCA tumba la partida: la captura es un subproducto y ya se jugo. Mismo invariante que el sink
    del runner online (`replayFrameStore.ts`: "la captura nunca tumba la partida")."""
    try:
        ventanas = ventanas_de_nivel(
            agente.frames,
            juego=juego,
            corrida=f"{MODELO_DE_CAPTURA}:{juego}:{lote}",
            modelo=MODELO_DE_CAPTURA,
            # BL.21798 -- la semilla DECLARADA viaja con la ventana. Vacia si no se paso
            # `--semilla`: ahi la partida no es reproducible y el corpus tiene que poder decirlo.
            semilla=semilla,
            antes=ventana,
            despues=ventana,
            acciones=acciones,
        )
        escritas = agregar_a_jsonl(destino, ventanas)
        if escritas:
            pasos = ", ".join(str(v.paso_del_evento) for v in ventanas)
            print(f"  -> capturadas {escritas} ventana(s) de subida de nivel (pasos: {pasos})")
        else:
            print("  -> sin subidas de nivel que capturar en esta partida")
        return escritas
    except Exception as error:  # noqa: BLE001 -- la captura jamas puede costar una partida
        print(f"  -> AVISO: fallo la captura de niveles de {juego}: {error}")
        return 0


def jugar(
    arcade,
    clase_agente: type,
    juegos: list[str],
    render: str | None,
    destino_de_captura: Path | None = None,
    ventana: int = VENTANA_POR_DEFECTO,
    fraccion_al_fondo: float = 0.0,
    etiqueta_de_corrida: str = "",
    semilla: str = "",
    lote_fijo: str = "",
) -> list[tuple]:
    resultados: list[tuple] = []
    # BL.21819 -- `--lote` PISA el reloj. El lote es lo unico variable del `runId`
    # (`<modelo>:<juego>:<lote>`) y el corpus se upsertea por {runId, stepNum}: con el lote sacado
    # del reloj, RE-jugar el mismo slice produce otro runId y DUPLICA corpus. Cuando la partida
    # corre en una tarea efimera de Fargate que Spot puede interrumpir y hay que relanzar, esa
    # duplicacion pasa de hipotetica a rutinaria, asi que el lanzador manda el lote y la
    # idempotencia queda del lado del dato. Sin la bandera no cambia nada: sigue el reloj.
    lote = lote_fijo or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    # BL.21794 -- la etiqueta viaja DENTRO del lote, o sea dentro del `runId`. Tiene que quedar en
    # el corpus persistido: una corrida con cobertura de fondo forzada NO es una muestra de la
    # politica entregada, y quien la lea despues tiene que poder separarlas sin adivinar. El
    # prefijo `harness-local:` se conserva intacto porque es el filtro del exportador.
    if etiqueta_de_corrida:
        lote = f"{lote}-{etiqueta_de_corrida}"
    for indice, juego in enumerate(juegos, 1):
        print(f"=== [{indice}/{len(juegos)}] {juego} ===")
        entorno = arcade.make(juego, render_mode=render)
        if entorno is None:
            print(f"  no se pudo crear el entorno de {juego!r}, se saltea")
            continue

        agente = clase_agente(
            card_id="dev-local",
            game_id=juego,
            agent_name=f"MyAgent.local.{juego}",
            ROOT_URL="http://localhost",
            record=False,
            arc_env=entorno,
            tags=["dev-local"],
        )
        # Solo con captura activa: sin la bandera, la partida corre exactamente como siempre.
        acciones = registrar_acciones(agente) if destino_de_captura is not None else None
        # BL.21794 -- cobertura de fondo forzada. Se engancha DESPUES de `registrar_acciones` y
        # sobre otro metodo (`choose_action` contra `take_action`), asi que lo que se registra en el
        # corpus es la coordenada REDIRIGIDA: el corpus tiene que decir donde se clickeo, no donde
        # el ranker hubiera querido clickear.
        # La semilla de la redireccion sale de `MyAgent.SEMILLA` y NO del lote: el lote lleva la
        # hora, asi que sembrar con el haria que la misma corrida con la misma `--semilla` sorteara
        # OTROS clicks y produjera OTRA partida. Una ventana que no se puede volver a producir no
        # es evidencia reproducible, que es la garantia sobre la que se apoya todo el corpus. Sin
        # `--semilla` la partida ya es irreproducible por su propio rng y el lote es lo unico que
        # hay: ahi el fallback no empeora nada.
        semilla_de_la_partida = getattr(clase_agente, "SEMILLA", None) or lote
        redireccion = (
            RedireccionAlFondo(fraccion_al_fondo, f"{juego}:{semilla_de_la_partida}")
            if fraccion_al_fondo > 0
            else None
        )
        if redireccion is not None:
            redireccion.enganchar(agente)
        agente.main()

        ultimo = agente.frames[-1]
        resultados.append((juego, ultimo.state, ultimo.levels_completed, agente.action_counter))
        print(
            f"  -> estado={ultimo.state}, niveles={ultimo.levels_completed}, "
            f"acciones={agente.action_counter}"
        )
        if redireccion is not None:
            print(f"  -> cobertura de fondo: {redireccion.resumen()}")
        if destino_de_captura is not None:
            capturar_niveles(
                agente, juego, lote, destino_de_captura, ventana, acciones, semilla
            )
    return resultados


def main() -> None:
    parser = argparse.ArgumentParser(description="Corre MyAgent contra juegos reales de ARC-AGI-3.")
    parser.add_argument(
        "--juego",
        default=None,
        help="Id(s) de juego separados por coma (ej. ls20,vc33). Sin esto se juegan todos.",
    )
    parser.add_argument(
        "--max-pasos",
        type=int,
        default=None,
        help="Tope de acciones por juego: PISA MAX_ACTIONS hacia arriba o hacia abajo. Sin la "
        "bandera se juega con el tope del entregable.",
    )
    parser.add_argument(
        "--presupuesto-horas",
        type=float,
        default=None,
        help="Presupuesto de reloj del batch entero, en horas (0 = sin reloj, para barridos de "
        "medicion). Sin la bandera rige el presupuesto entregado.",
    )
    parser.add_argument(
        "--capturar-niveles",
        default=None,
        metavar="RUTA_JSONL",
        help="BL.21695: graba (append) la ventana de frames alrededor de cada subida de nivel al "
        "JSONL indicado. Sin la bandera no se captura nada.",
    )
    parser.add_argument(
        "--ventana",
        type=int,
        default=VENTANA_POR_DEFECTO,
        help=f"Frames a cada lado del evento de nivel (default {VENTANA_POR_DEFECTO}: cubre una "
        "macro-accion completa de 8 pasos mas contexto).",
    )
    parser.add_argument(
        "--semilla",
        default=None,
        help="Fija MyAgent.SEMILLA para que la partida sea REPRODUCIBLE. Sin la bandera la semilla "
        "sale del reloj (dos corridas exploran distinto, que es lo deseable en evaluacion). Con "
        "captura de niveles activa conviene fijarla: una ventana capturada sin semilla no se puede "
        "volver a producir.",
    )
    parser.add_argument(
        "--fraccion-de-clicks-al-fondo",
        type=float,
        default=0.0,
        metavar="F",
        help="BL.21794: redirige esa FRACCION de los ACTION6 a una celda de fondo elegida al azar "
        f"(sugerido {FRACCION_POR_DEFECTO}). La partida PUNTUA PEOR a proposito: es una corrida de "
        "MEDICION, para que la linea base de 'clicks previos sobre un objeto' deje de tener "
        "varianza cero. 0 (default) = la politica entregada, sin tocar nada.",
    )
    parser.add_argument(
        "--etiqueta-de-corrida",
        default="",
        metavar="ETIQUETA",
        help="Sufijo del lote, y por lo tanto del `runId` que se persiste (ej. `fondo30`). Una "
        "corrida con cobertura de fondo NO es una muestra de la politica entregada y el corpus "
        "tiene que poder separarlas.",
    )
    parser.add_argument(
        "--lote",
        default=None,
        metavar="LOTE",
        help="BL.21819: PISA el lote que sale del reloj. El lote es la unica parte variable del "
        "`runId` y el corpus se upsertea por {runId, stepNum}: fijarlo hace que RE-jugar el mismo "
        "slice colapse sobre los mismos documentos en vez de duplicar corpus. Lo usa el worker de "
        "Fargate, donde una interrupcion de Spot obliga a relanzar. Sin la bandera rige el reloj.",
    )
    parser.add_argument("--listar", action="store_true", help="Lista los juegos y sale.")
    parser.add_argument(
        "--render", default=None, choices=["terminal"], help="Render opcional en la terminal."
    )
    parser.add_argument(
        "--modo",
        default="offline",
        choices=["offline", "normal"],
        help="offline (default): solo juegos ya bajados. normal: permite que el paquete los baje.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    preparar_entorno()

    import arc_agi
    from arc_agi import OperationMode

    modo = OperationMode.OFFLINE if args.modo == "offline" else OperationMode.NORMAL
    arcade = arc_agi.Arcade(operation_mode=modo, environments_dir=str(ENVIRONMENTS_DIR))

    if args.listar:
        entornos = arcade.get_environments()
        print(f"{len(entornos)} entornos disponibles:")
        for entorno in entornos:
            print(f"  {entorno.game_id}: {getattr(entorno, 'title', '?')}")
        return

    juegos = resolver_juegos(arcade, args.juego)
    modulo_agente = cargar_modulo_agente()
    clase_agente = modulo_agente.MyAgent
    tope = aplicar_tope_de_pasos(clase_agente, args.max_pasos)
    print(f"[play_local] Cota de acciones por juego: {tope}")
    if args.semilla is not None:
        clase_agente.SEMILLA = args.semilla
        print(f"[play_local] Semilla fijada: {args.semilla!r} (partida reproducible).")
    reloj = configurar_reloj(modulo_agente, len(juegos), args.presupuesto_horas)

    destino_de_captura = Path(args.capturar_niveles) if args.capturar_niveles else None
    if destino_de_captura is not None:
        print(
            f"[play_local] Captura de subidas de nivel ACTIVA -> {destino_de_captura} "
            f"(ventana +-{args.ventana} frames).\n"
        )

    if args.fraccion_de_clicks_al_fondo > 0:
        print(
            f"[play_local] COBERTURA DE FONDO {args.fraccion_de_clicks_al_fondo:.2f}: corrida de "
            "MEDICION, va a puntuar peor a proposito (BL.21794).\n"
        )

    resultados = jugar(
        arcade,
        clase_agente,
        juegos,
        args.render,
        destino_de_captura,
        args.ventana,
        args.fraccion_de_clicks_al_fondo,
        args.etiqueta_de_corrida,
        "" if args.semilla is None else str(args.semilla),
        "" if args.lote is None else str(args.lote),
    )

    print("\n========= RESUMEN =========")
    for juego, estado, niveles, acciones in resultados:
        print(f"  {juego:8} niveles={niveles:3}  acciones={acciones:5}  estado={estado}")
    tarjeta = arcade.get_scorecard()
    puntaje = tarjeta.score if hasattr(tarjeta, "score") else tarjeta
    print(f"\nPuntaje agregado de la tarjeta: {puntaje}")
    if reloj is not None:
        print(f"Reloj de presupuesto: {reloj.estado()}")


if __name__ == "__main__":
    main()
