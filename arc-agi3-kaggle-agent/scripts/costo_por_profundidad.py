"""[arc-agi3-kaggle-agent/scripts/costo_por_profundidad] BL.21783 -- EL COSTO POR ACCION NO ES UNA
CONSTANTE: crece con la profundidad de la partida. Este modulo lo mide, lo atribuye y dice hasta
que accion alcanza el presupuesto del entregable.

POR QUE APARECIO. Toda la aritmetica de presupuesto del track (la cuota `28.800/N`, el cruce de 47
juegos, "en este box manda el tope") multiplica el tope de acciones por UN costo por accion tomado
como constante: 0,1535 s, medido en los primeros cientos de pasos. La primera corrida de este BL
hasta el fondo mostro que ese numero es el del TRAMO BARATO -- en lp85 las acciones 1-100 costaron
0,109 s y las 401-500 ya costaban 0,497 s, un factor 4,5 en 400 acciones. Con un costo que crece,
"4.000 acciones" no cuesta `4000 * c`: cuesta la INTEGRAL de la curva, y el presupuesto se agota
mucho antes de lo que dice la multiplicacion.

QUE CONTESTA, sobre las series que la medicion ya guarda (no hace falta volver a jugar):
  1. `perfilDeCosto` -- el costo por accion por tramo, y el factor entre el primer tramo y el
     ultimo. Es la evidencia de que crece, o de que no.
  2. `accionesQueEntranEnLaCuota` -- hasta que accion llega la partida con la cuota de CPU que el
     entregable le da (presupuesto / N). Sale del CPU acumulado REAL mientras la serie alcanza, y
     de la extrapolacion del ultimo tramo cuando no. Es el numero que dice si el tope de 4.000 es
     un presupuesto o un adorno.
  3. `atribucion` -- la correlacion entre el costo de cada accion y el tamano de la memoria de
     novedad (firmas de estado distintas), que es la unica estructura que crece monotona con la
     partida. Correlacion NO es causa y el nombre del campo lo dice (`correlacion...`), pero una
     correlacion alta con un costo que crece lineal es la hipotesis barata que hay que mirar
     primero; una baja la descarta y manda a buscar a otro lado.

EXTRAPOLAR SE DECLARA. Cuando la serie no llega al final, el resultado viene con
`extrapolado: true` y con el tramo que se uso para extrapolar. Un numero extrapolado que se lee
como medido es la forma mas facil de fabricar una conclusion.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mapa_de_juegos import es_medicion  # noqa: E402

#: Acciones por tramo del perfil. 250 = el mismo grano que el volcado parcial, asi que un perfil
#: sacado de un volcado y uno sacado de la corrida completa tienen los mismos cortes.
ACCIONES_POR_TRAMO = 250


def incrementos_de_cpu(fila: dict) -> list[float]:
    """CPU de cada accion, de la serie acumulada. La serie guarda el acumulado justamente para que
    esto se pueda reconstruir sin instrumentar cada accion por separado.

    EL PRIMER ELEMENTO ENTRA. `serie[0]` es el acumulado DESPUES de la primera accion, o sea su
    costo: si se lo saltea, los tramos quedan corridos una accion y el tramo `1-250` termina
    mezclando 249 acciones baratas con la primera cara del tramo siguiente. Con el offset bien
    puesto, este perfil coincide con el `cpuPorAccionPorTramo` que emite la propia medicion."""
    serie = fila.get("serieDeCpuAcumulado") or []
    if not serie:
        return []
    return [round(serie[0], 6)] + [
        round(serie[i] - serie[i - 1], 6) for i in range(1, len(serie))
    ]


def perfil_de_costo(fila: dict, acciones_por_tramo: int = ACCIONES_POR_TRAMO) -> dict:
    """Costo por accion por tramo y el factor entre el primer tramo y el ultimo."""
    incrementos = incrementos_de_cpu(fila)
    tramos: dict[str, float] = {}
    for inicio in range(0, len(incrementos), acciones_por_tramo):
        tramo = incrementos[inicio : inicio + acciones_por_tramo]
        if not tramo:
            continue
        tramos[f"{inicio + 1}-{inicio + len(tramo)}"] = round(statistics.fmean(tramo), 4)
    valores = list(tramos.values())
    return {
        "porTramo": tramos,
        "primerTramo": valores[0] if valores else None,
        "ultimoTramo": valores[-1] if valores else None,
        "factorUltimoSobrePrimero": round(valores[-1] / valores[0], 2)
        if valores and valores[0] > 0
        else None,
        "crece": bool(len(valores) >= 2 and valores[-1] > valores[0]),
    }


def acciones_que_entran_en_la_cuota(fila: dict, cuota_segundos: float) -> dict:
    """Hasta que accion llega la partida con `cuota_segundos` de CPU.

    Con la serie REAL mientras alcanza; extrapolando el ULTIMO tramo (el mas caro si el costo
    crece, o sea la extrapolacion conservadora para esta pregunta) cuando la serie se queda corta.
    """
    serie = fila.get("serieDeCpuAcumulado") or []
    if not serie:
        return {"acciones": None, "extrapolado": None, "porQue": "la corrida no guardo la serie"}
    for indice, acumulado in enumerate(serie, 1):
        if acumulado >= cuota_segundos:
            return {
                "acciones": indice,
                "extrapolado": False,
                "porQue": f"el CPU acumulado real cruza {cuota_segundos:.0f} s en la accion {indice}",
            }
    incrementos = incrementos_de_cpu(fila)
    cola = incrementos[-ACCIONES_POR_TRAMO:] or incrementos
    costo_de_cola = statistics.fmean(cola) if cola else 0.0
    if costo_de_cola <= 0:
        return {"acciones": None, "extrapolado": None, "porQue": "sin costo por accion medible"}
    faltan = (cuota_segundos - serie[-1]) / costo_de_cola
    return {
        "acciones": int(len(serie) + faltan),
        "extrapolado": True,
        "costoDeColaUsado": round(costo_de_cola, 4),
        "porQue": (
            f"la corrida llego a la accion {len(serie)} con {serie[-1]:.0f} s de CPU; el resto se "
            f"extrapola al costo del ultimo tramo ({costo_de_cola:.4f} s/accion), que es el mas "
            f"caro medido y por lo tanto la cota OPTIMISTA de cuantas acciones mas entran"
        ),
    }


#: Las estructuras del agente que crecen monotonas con la partida y que la medicion registra
#: accion por accion. La clave es como se llama en la salida; el valor, la serie que la trae.
MEMORIAS_QUE_CRECEN = {
    "memoriaDeNovedad": "serieDeFirmasDeEstado",
    "plantillasDeClick": "serieDePlantillasDeClick",
}


def _correlacion(memoria: list[float], costos: list[float]) -> float | None:
    if len(set(memoria)) < 2 or len(set(costos)) < 2:
        return None
    return round(statistics.correlation(memoria, costos), 3)


def atribucion(fila: dict) -> dict:
    """Correlacion entre el costo de cada accion y CADA estructura del agente que crece.

    POR QUE DOS Y NO UNA. La memoria de novedad crece con los estados distintos vistos, pero no se
    recorre entera en cada accion; las plantillas de click SI -- `_bono_de_plantilla` compara el
    parche de CADA CELDA contra TODAS las plantillas, o sea que el ranking de coordenadas cuesta
    O(celdas x plantillas) y crece con cada click productivo. Correlacionar contra una sola
    estructura invita a adjudicarle el crecimiento a la primera que se midio; con las dos al lado,
    el numero elige. Correlacion NO es causa y por eso el nombre lo dice: es la pista barata que
    decide DONDE mirar el codigo, no la conclusion."""
    incrementos = incrementos_de_cpu(fila)
    if len(incrementos) < 2:
        return {"porQue": "la corrida no tiene suficientes acciones para correlacionar nada"}
    salida: dict = {}
    for nombre, clave in MEMORIAS_QUE_CRECEN.items():
        # Las series tienen UNA entrada por accion y el mismo origen, asi que estan alineadas de
        # entrada: el recorte solo cubre una fila escrita a mano o un volcado partido al medio.
        serie = (fila.get(clave) or [])[: len(incrementos)]
        if len(serie) != len(incrementos):
            salida[f"correlacionCostoContra_{nombre}"] = None
            salida[f"{nombre}_porQue"] = f"la corrida no trae {clave}"
            continue
        salida[f"correlacionCostoContra_{nombre}"] = _correlacion(
            [float(v) for v in serie], [float(c) for c in incrementos]
        )
        salida[f"{nombre}_alEmpezar"] = serie[0]
        salida[f"{nombre}_alTerminar"] = serie[-1]
    salida["porQue"] = (
        "correlacion de Pearson entre cada memoria que crece y el CPU por accion. NO es causa: es "
        "la pista barata de que el costo por accion escala con una estructura que crece, que es lo "
        "que convierte una partida larga en cuadratica. El codigo que la explicaria esta en "
        "arc_agent/click_targeting.py: `_bono_de_plantilla` recorre TODAS las plantillas por CADA "
        "celda del tablero."
    )
    return salida


def informe(fila: dict, cuota_segundos: float) -> dict:
    return {
        "juego": fila["juego"],
        "semilla": fila["semilla"],
        "accionesConsumidas": fila["accionesConsumidas"],
        "parcial": bool(fila.get("parcial", False)),
        "cuotaDeRelojSegundos": cuota_segundos,
        "perfilDeCosto": perfil_de_costo(fila),
        "accionesQueEntranEnLaCuota": acciones_que_entran_en_la_cuota(fila, cuota_segundos),
        "atribucion": atribucion(fila),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="BL.21783 -- el costo por accion contra la profundidad")
    parser.add_argument("--corrida", required=True, help="JSON de UNA corrida (con las series).")
    parser.add_argument(
        "--cuota",
        type=float,
        default=None,
        help="Segundos de CPU por partida. Sin esto, la que la corrida ya trae.",
    )
    parser.add_argument("--json", default=None)
    args = parser.parse_args()

    crudo = json.loads(Path(args.corrida).read_text(encoding="utf-8"))
    filas = [f for f in crudo.get("mediciones", []) if es_medicion(f)]
    if not filas:
        raise SystemExit(f"[costo] {args.corrida} no trae mediciones.")
    salida = [
        informe(f, args.cuota if args.cuota is not None else float(f["cuotaDeRelojSegundos"]))
        for f in filas
    ]
    print(json.dumps(salida, indent=1, sort_keys=True, ensure_ascii=False))
    if args.json:
        destino = Path(args.json)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(salida, indent=1, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
