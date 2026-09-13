"""[arc-agi3-kaggle-agent/scripts/clasificacion_de_juegos] BL.21763 -- RE-MEDIR EL MAPA DE LOS 25
JUEGOS con el agente de HOY, contra el harness REAL (`arc_agi` + `environment_files`).

POR QUE EXISTE. El mapa que guia las decisiones del track -- 6 juegos limitados por PRESUPUESTO,
7 que CICLAN sin avanzar, el resto que NO CONVIERTE exploracion en progreso -- se midio ANTES de
tres cambios que tocan exactamente esas tres categorias:
  - BL.21701: MAX_ACTIONS 400 -> 4000 y el limite operativo paso a ser el RELOJ. La categoria
    "limitado por presupuesto" se definio con el tope viejo; ademas, hasta ese BL el `min()` de
    `play_local.py` hacia IMPOSIBLE medir por encima del valor entregado.
  - BL.21741: la percepcion objeto-centrica dejo de ser ciega a la transicion de nivel (1 firma
    para las 8 transiciones -> 7 firmas distintas). La categoria "no convierte" se definio ciega.
  - BL.21744: el banco parametrico con el que se midio parte de esto era INGANABLE en 19 de 25
    mundos. Ningun "niveles" de ese banco anterior a BL.21744 es comparable con los de hoy.

QUE MIDE, por juego y semilla: niveles completados, acciones consumidas, quien corto la partida,
distribucion de acciones, coordenadas distintas clickeadas, firmas de estado distintas, firmas de
mecanica distintas (BL.21741 en situ) y GAME_OVERs (insumo de BL.21767: se cuenta SIEMPRE).

EL RELOJ SE MIDE, NO SE SUFRE -- Y SE SIMULA CON SU FORMULA REAL, NO CON UNA SIMPLIFICACION. La
partida corre con el reloj APAGADO y el tope en 4000, y el CPU acumulado se anota accion por accion.
La serie entera se vuelca al JSON, y sobre ella `reloj_derivado.py` re-ejecuta el PREDICADO REAL de
`RelojDePresupuesto.debe_cortar` -- los dos frenos, la cuota `(consumo_CPU + restante_de_PARED) /
pendientes` y el deadline global de PARED -- para dos escenarios: `maquinaDedicada` (factor
PARED/CPU = 1, que es Kaggle y el unico que le importa al entregable) y `boxCompartido` (con el
factor medido en la propia corrida).

POR QUE DOS ESCENARIOS Y NO UNO. La version anterior derivaba el corte como "primera accion cuyo
CPU pasa 28.800/25 = 1.152 s". Eso coincide con el reloj real SOLO si un segundo de CPU cuesta un
segundo de pared. En este box la contencion medida fue de un orden 17x, y con ese factor el reloj
corta desde la SEGUNDA partida del batch. Publicar un solo numero y llamarlo "el box" daba una
conclusion falsa sobre quien manda; publicar los dos deja explicito que la conclusion
"manda el tope" es del escenario DEDICADO. Correr con el reloj PUESTO tampoco sirve: mediria la
carga ajena. El CPU si es comparable entre corridas y maquinas (salvo factor de maquina, el 1,8x
estimado en BL.21701).

LA CURVA SALE DE UNA SOLA PARTIDA. Una corrida de 4000 acciones CONTIENE las de 400, 800 y 1600:
anotando los niveles en cada hito, un solo juego responde toda la curva de presupuesto. Medir cada
hito por separado costaria 6.200 acciones por juego en vez de 4.000 y daria lo mismo.

AL REANUDAR UN JUEGO, LA CORRIDA COMPLETA PISA A SU PROPIO VOLCADO PARCIAL (BL.21783). Las dos
filas son la misma `(juego, semilla)`, no dos semillas: `mapa_de_juegos.una_fila_por_semilla` las
colapsa quedandose con la que termino. Y cuantas semillas hacen falta para que el casillero deje de
ser una apuesta lo calcula `scripts/presupuesto_de_la_medicion.py`, que ademas contesta -- con la
cuenta, no de memoria -- si en un batch dado manda el reloj o el tope.

USO (una semilla por vez y `nice -n 19`: el box comparte 6 vCPU con el cron horario de partidas
reales, que se saltea si el ratio de carga pasa de 1,5):

    nice -n 19 .venv/bin/python scripts/clasificacion_de_juegos.py \\
        --juegos vc33 --acciones 4000 --semillas mapa-1 \\
        --json runtime_reports/bl21763/vc33.mapa-1.json

    # fusionar las corridas parciales en el mapa final
    .venv/bin/python scripts/clasificacion_de_juegos.py --fusionar 'runtime_reports/bl21763/*.json' \\
        --json mediciones/clasificacion_de_juegos_2026-08-19.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from play_local import (  # noqa: E402
    aplicar_tope_de_pasos,
    cargar_modulo_agente,
    configurar_reloj,
    preparar_entorno,
    resolver_juegos,
)
from mapa_de_juegos import (  # noqa: E402
    HITOS_POR_DEFECTO,
    UMBRAL_DE_NOVEDAD_MUERTA,
    fusionar,
    una_fila_por_semilla,
)
from curva_de_presupuesto import (  # noqa: E402
    HITO_DEL_ENTREGABLE,
    HITO_VIEJO_LARGO,
    curva,
)
from partida_instrumentada import (  # noqa: E402
    CARGA_MAXIMA_POR_DEFECTO,
    esperar_a_que_baje_la_carga,
    medir_partida,
)
from starter_config import ENVIRONMENTS_DIR  # noqa: E402


def _cuota_de_reloj(modulo, juegos_del_batch: int) -> float:
    """Segundos de CPU que el reloj del entregable le da a UNA partida de un batch de N juegos EN
    EL ESCENARIO DEDICADO (factor PARED/CPU = 1). Se lee del modulo del agente y no se re-escribe
    aca: fuente unica (BL.21701).

    OJO: este numero NO es "el corte del reloj" en general. Es el caso particular `f = 1` del
    predicado real que implementa `reloj_derivado.accion_de_corte`; en una maquina contendida la
    cuota es otra y mucho mas chica. Se sigue reportando porque es la referencia del entregable."""
    return float(modulo.PRESUPUESTO_POR_DEFECTO_SEGUNDOS) / max(1, juegos_del_batch)


def main() -> int:
    parser = argparse.ArgumentParser(description="BL.21763 -- re-medicion del mapa de los 25 juegos")
    parser.add_argument("--juegos", default=None, help="Ids separados por coma. Sin esto, los 25.")
    parser.add_argument("--acciones", type=int, default=None, help="Tope. Sin esto, el entregado.")
    parser.add_argument("--semillas", default="mapa-1", help="Semillas separadas por coma.")
    parser.add_argument("--json", default=None, help="Ruta de salida.")
    parser.add_argument("--modo", default="offline", choices=["offline", "normal"])
    parser.add_argument(
        "--juegos-del-batch",
        type=int,
        default=25,
        help="Tamano del batch con el que se calcula la cuota de reloj por partida. 25 = el set "
        "publico: la cuota medida es la que ese juego tendria en la corrida real, aunque aca se "
        "mida un subconjunto.",
    )
    parser.add_argument(
        "--carga-maxima",
        type=float,
        default=CARGA_MAXIMA_POR_DEFECTO,
        help="Ratio de carga por vCPU por encima del cual se espera antes de cada juego. 0 lo "
        "desactiva (no recomendado: el box comparte 6 vCPU con el cron de partidas reales).",
    )
    parser.add_argument("--umbral-novedad", type=float, default=UMBRAL_DE_NOVEDAD_MUERTA)
    parser.add_argument("--fusionar", default=None, help="Patron glob de corridas parciales.")
    parser.add_argument(
        "--hito-desde",
        type=int,
        default=HITO_VIEJO_LARGO,
        help="Hito de PARTIDA del veredicto de la curva (default 1600: el ultimo que midio el "
        "mapa viejo, o sea el presupuesto que ya estaba pago).",
    )
    parser.add_argument(
        "--hito-hasta",
        type=int,
        default=HITO_DEL_ENTREGABLE,
        help="Hito de LLEGADA del veredicto (default 4000: el tope del entregable de hoy).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    if args.fusionar:
        salida = fusionar(args.fusionar, args.umbral_novedad)
        # EL VEREDICTO VIAJA CON EL MAPA (BL.21783). El mapa dice en que casillero quedo cada
        # juego; la pregunta del BL es otra -- si el tramo 1600->4000 PAGA -- y su respuesta se
        # calcula sobre las mismas filas ya deduplicadas. Emitirlas juntas es lo que evita que
        # alguien lea el promedio de la curva como si fuera el veredicto: `curvaDePresupuesto`
        # trae la comparacion contra el ruido entre semillas, que el promedio no puede dar.
        salida["curvaDePresupuesto"] = curva(
            una_fila_por_semilla(salida["mediciones"]),
            args.hito_desde,
            args.hito_hasta,
        )
        print(json.dumps(salida["mapa"], indent=1, sort_keys=True, ensure_ascii=False))
        print(f"\nCURVA (niveles por semilla): {salida['curvaDePresupuestoNivelesPorSemilla']}")
        veredicto = salida["curvaDePresupuesto"]
        print(
            f"VEREDICTO {args.hito_desde}->{args.hito_hasta}: {veredicto['veredicto']} -- "
            f"{veredicto['porQue']}"
        )
        if args.json:
            destino = Path(args.json)
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(json.dumps(salida, indent=1, sort_keys=True), encoding="utf-8")
            print(f"Mapa escrito en {destino}")
        return 0

    preparar_entorno()
    import arc_agi
    from arc_agi import OperationMode

    modo = OperationMode.OFFLINE if args.modo == "offline" else OperationMode.NORMAL
    arcade = arc_agi.Arcade(operation_mode=modo, environments_dir=str(ENVIRONMENTS_DIR))
    juegos = resolver_juegos(arcade, args.juegos)
    modulo = cargar_modulo_agente()
    clase = modulo.MyAgent
    tope = aplicar_tope_de_pasos(clase, args.acciones)
    # Reloj APAGADO: el corte por reloj se DERIVA del CPU acumulado (ver docstring). Un corte por
    # tiempo de pared en un box compartido mediria la carga ajena, no el presupuesto.
    configurar_reloj(modulo, len(juegos), 0.0)
    cuota = _cuota_de_reloj(modulo, args.juegos_del_batch)
    semillas = [s.strip() for s in args.semillas.split(",") if s.strip()]

    print(
        f"[clasificacion] {len(juegos)} juego(s) x {tope} acciones x {len(semillas)} semilla(s). "
        f"Cuota de reloj derivada: {cuota:.0f} s de CPU por partida "
        f"(batch declarado de {args.juegos_del_batch} juegos)."
    )
    mediciones: list[dict] = []
    salida = {
        "config": {
            "juegos": juegos,
            "tope": tope,
            "semillas": semillas,
            "juegosDelBatch": args.juegos_del_batch,
            "cuotaDeRelojSegundos": round(cuota, 1),
            "cargaMaxima": args.carga_maxima,
        },
        "mediciones": mediciones,
    }
    destino = Path(args.json) if args.json else None
    if destino is not None:
        destino.parent.mkdir(parents=True, exist_ok=True)

    def escribir() -> None:
        if destino is not None:
            destino.write_text(json.dumps(salida, indent=1, sort_keys=True), encoding="utf-8")

    for semilla in semillas:
        for indice, juego in enumerate(juegos, 1):
            ratio, _ = esperar_a_que_baje_la_carga(args.carga_maxima)
            # La fila en curso ocupa su lugar definitivo desde el primer volcado parcial: cada
            # avance la PISA en el mismo indice, asi que el JSON siempre tiene una sola fila por
            # juego y semilla, parcial o final, y nunca las dos.
            ranura = len(mediciones)
            mediciones.append({"juego": juego, "semilla": semilla, "parcial": True})

            def al_avanzar(parcial: dict, ranura: int = ranura, ratio: float = ratio) -> None:
                parcial["ratioDeCargaAlArrancar"] = round(ratio, 2)
                mediciones[ranura] = parcial
                escribir()

            try:
                fila = medir_partida(
                    arcade,
                    modulo,
                    juego,
                    semilla,
                    HITOS_POR_DEFECTO,
                    cuota,
                    al_avanzar,
                    presupuesto=float(modulo.PRESUPUESTO_POR_DEFECTO_SEGUNDOS),
                    juegos_del_batch=args.juegos_del_batch,
                    carga_maxima=args.carga_maxima,
                )
            except KeyboardInterrupt:
                # UNA INTERRUPCION NO PUEDE DEJAR EL ARCHIVO SIN ESCRIBIR (BL.21783). Un barrido
                # con tope de reloj por partida corta con SIGINT a proposito, y si eso se
                # propagara sin escribir, una partida interrumpida ANTES de su primer volcado
                # (250 acciones) desapareceria entera -- incluido el hecho de que se intento.
                # Lo que hay en `mediciones` es el ultimo volcado parcial, o la ranura reservada
                # si no hubo ninguno; `es_medicion` filtra la segunda al fusionar, asi que el
                # archivo nunca miente sobre lo que se llego a medir.
                escribir()
                print(
                    f"  [{indice}/{len(juegos)}] {juego} ({semilla}): INTERRUMPIDO. Lo medido "
                    f"hasta el ultimo volcado quedo en {destino}.",
                    flush=True,
                )
                return 130
            fila["ratioDeCargaAlArrancar"] = round(ratio, 2)
            mediciones[ranura] = fila
            print(
                f"  [{indice}/{len(juegos)}] {juego} ({semilla}): niveles={fila['nivelesFinales']} "
                f"acciones={fila['accionesConsumidas']} corte={fila['corteFue']} "
                f"cpu={fila['costo']['cpuSegundos']}s "
                f"({fila['costo']['cpuSegundosPorAccion']}s/accion)",
                flush=True,
            )
            escribir()

    if destino is not None:
        print(f"Medicion escrita en {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
