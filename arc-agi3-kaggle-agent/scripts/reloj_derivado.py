"""[arc-agi3-kaggle-agent/scripts/reloj_derivado] BL.21763 -- EN QUE ACCION HABRIA CORTADO EL RELOJ,
con el predicado REAL del entregable y no con una simplificacion.

POR QUE EXISTE, Y QUE ERROR CORRIGE. La primera version de este BL derivaba el corte como "la
primera accion cuyo CPU acumulado pasa `PRESUPUESTO / N`". Eso NO es lo que hace
`RelojDePresupuesto.debe_cortar`: el reloj mezcla DOS MONEDAS a proposito y la simplificacion las
colapsa en una. El predicado real, para la partida `k` de `N` jugadas EN SERIE, es

    corta si   (a) presupuesto - pared(t) <= margen_de_cierre          [deadline GLOBAL, en PARED]
        o si   (b) cpu_k(t) >= (cpu_k(t) + restante_de_PARED(t)) / pendientes(k)   [cuota]

con `pendientes(k) = N - (k-1)` (las que ya terminaron salen del reparto: `finalizar_partida`
devuelve su consumo al pool) y `restante = presupuesto - pared`.

Despejando (b) con `pared(t) = pared_previa + f * cpu_k(t)`, donde `f` es el factor PARED/CPU de la
maquina (1,0 en una maquina dedicada; 17,6 medido en este box compartido):

    cpu_k(t) * (N - k + f) >= presupuesto - pared_previa

CONSECUENCIA MEDIDA, y es la razon de ser del modulo: con `f = 1` y el primer juego de 25 el corte
cae en `28.800/25 = 1.152 s` de CPU -- identico a la formula vieja, que por eso parecia correcta.
Con el `f = 17,6` que este mismo BL midio en el box compartido, el juego 2 ya corta por RELOJ y muy
lejos del tope. O sea: la conclusion "manda el tope, no el reloj" vale en una maquina DEDICADA (que
es el caso de Kaggle, el unico que le importa al entregable) y es FALSA en un box contendido. Las
dos se reportan, cada una con su factor, en vez de publicar una sola y llamarla "el box".

Es aritmetica sobre la serie de CPU por accion que la medicion vuelca: se puede re-correr sin
volver a jugar, que es justo lo que hace falta cuando se discute el supuesto de contencion.
"""
from __future__ import annotations

from typing import Iterable, Sequence

#: Factor PARED/CPU de una maquina DEDICADA: cada segundo de CPU cuesta un segundo de reloj. Es el
#: escenario del entregable (Kaggle da el notebook entero) y el unico en el que la cuota del reloj
#: coincide con `presupuesto / N`.
FACTOR_DEDICADO = 1.0

#: Espejo de `arc_agent.reloj_presupuesto`: tope fijo del margen de cierre y fraccion maxima del
#: presupuesto que ese margen puede comerse. Duplicarlos aca es deliberado -- ver `margen_de_cierre_para`.
TOPE_DEL_MARGEN_SEGUNDOS = 60.0
FRACCION_MAXIMA_DEL_MARGEN = 0.01


def margen_de_cierre_para(presupuesto_segundos: float) -> float:
    """Espejo de `arc_agent.reloj_presupuesto.margen_de_cierre_para`. Se re-implementa aca en vez
    de importarse para que este modulo sea aritmetica pura y se pueda correr sobre un JSON sin
    levantar el paquete del agente.

    BL.21800: esta frase decia que el test `test_el_margen_de_cierre_espeja_al_del_entregable`
    fijaba que las dos implementaciones dieran lo mismo -- y ese test NO EXISTIA
    (`grep -rn espeja_al_del_entregable` devolvia una sola linea: la cita). O sea que la afirmacion
    que autorizaba la segunda copia no la sostenia ninguna linea de codigo (RFM-07), y las dos
    constantes duplicadas podian divergir sin que nada lo notara. Ahora el test existe, con ese
    nombre exacto, en `tests/test_bl21800_reloj_derivado.py`, y compara las dos FUNCIONES sobre una
    matriz de presupuestos -- no solo las constantes, porque dos constantes iguales con formulas
    distintas divergirian igual."""
    if presupuesto_segundos <= 0:
        return 0.0
    return min(TOPE_DEL_MARGEN_SEGUNDOS, presupuesto_segundos * FRACCION_MAXIMA_DEL_MARGEN)


def factor_pared_por_cpu(reloj_segundos: float, cpu_segundos: float) -> float:
    """Cuantos segundos de PARED cuesta un segundo de CPU en la maquina donde se midio. Nunca menos
    de 1: una partida de un solo hilo no puede consumir mas CPU que tiempo de reloj."""
    if cpu_segundos <= 0:
        return FACTOR_DEDICADO
    return max(FACTOR_DEDICADO, reloj_segundos / cpu_segundos)


def accion_de_corte(
    serie_de_cpu: Sequence[float],
    *,
    presupuesto_segundos: float,
    total_de_juegos: int,
    indice_del_juego: int = 1,
    factor: float = FACTOR_DEDICADO,
    pared_previa_segundos: float = 0.0,
) -> tuple[int | None, str]:
    """Primera accion (1-indexada) en la que el reloj REAL habria cortado esta partida, y por cual
    de los dos frenos. `None` si la serie se acaba antes de que corte -- o sea, manda el tope.

    `serie_de_cpu[i]` es el CPU ACUMULADO de la partida despues de la accion `i+1`."""
    pendientes = max(1, int(total_de_juegos) - (int(indice_del_juego) - 1))
    margen = margen_de_cierre_para(presupuesto_segundos)
    for indice, cpu in enumerate(serie_de_cpu, 1):
        pared = pared_previa_segundos + factor * cpu
        restante = presupuesto_segundos - pared
        if restante <= margen:
            return (indice, "deadlineGlobal")
        if cpu >= (cpu + max(0.0, restante)) / pendientes:
            return (indice, "cuotaDeLaPartida")
    return (None, "nadie: la serie se agota antes y manda el tope de acciones")


def escenarios_de_corte(
    serie_de_cpu: Sequence[float],
    *,
    presupuesto_segundos: float,
    total_de_juegos: int,
    factor_medido: float,
) -> dict:
    """Los dos escenarios que hacen falta para leer el numero sin equivocarse, mas el barrido de
    posiciones que contesta "a partir de que juego del batch manda el reloj".

    `maquinaDedicada` es el entregable (Kaggle). `boxCompartido` es donde se midio -- se reporta
    para que nadie lea un corte local como si fuera el de la submission. El barrido supone que cada
    partida anterior gasto hasta SU corte, que es el caso de mayor presion sobre las que siguen."""
    salida: dict[str, dict] = {}
    for nombre, factor in (
        ("maquinaDedicada", FACTOR_DEDICADO),
        ("boxCompartido", float(factor_medido)),
    ):
        pared_previa = 0.0
        posiciones = []
        for k in range(1, int(total_de_juegos) + 1):
            accion, motivo = accion_de_corte(
                serie_de_cpu,
                presupuesto_segundos=presupuesto_segundos,
                total_de_juegos=total_de_juegos,
                indice_del_juego=k,
                factor=factor,
                pared_previa_segundos=pared_previa,
            )
            if accion is not None:
                cpu_gastado = serie_de_cpu[accion - 1]
            else:
                cpu_gastado = serie_de_cpu[-1] if serie_de_cpu else 0.0
            posiciones.append(
                {"posicionEnElBatch": k, "accionDeCorte": accion, "cortaPor": motivo}
            )
            pared_previa += factor * cpu_gastado
        primera_cortada = next(
            (p["posicionEnElBatch"] for p in posiciones if p["accionDeCorte"] is not None), None
        )
        salida[nombre] = {
            "factorParedPorCpu": round(factor, 2),
            "primeraPosicionQueCortaPorReloj": primera_cortada,
            "corteDeLaPrimeraPartida": posiciones[0]["accionDeCorte"] if posiciones else None,
            "posiciones": posiciones,
        }
    return salida


def cruce_de_juegos(costo_cpu_por_accion: float, tope_de_acciones: int, presupuesto: float) -> float:
    """A partir de cuantos juegos por batch la CUOTA se agota antes que el TOPE, en el escenario
    DEDICADO (`f = 1`, cuota uniforme `presupuesto / N`). Es la forma cerrada de la tabla del
    informe: `presupuesto / N < tope * c`  <=>  `N > presupuesto / (tope * c)`."""
    if costo_cpu_por_accion <= 0 or tope_de_acciones <= 0:
        return float("inf")
    return presupuesto / (tope_de_acciones * costo_cpu_por_accion)


def costo_por_accion_por_tramo(serie_de_cpu: Sequence[float], tramos: Iterable[int]) -> dict:
    """CPU por accion MARGINAL en cada tramo de la partida. Existe porque el informe afirmaba que
    "el costo crece con la profundidad" citando un numero que no estaba en ningun artefacto: aca la
    curva se deriva de la serie versionada y puede desmentirse sola."""
    cortes = [t for t in sorted({int(t) for t in tramos}) if 0 < t <= len(serie_de_cpu)]
    salida: dict[str, float] = {}
    anterior_accion, anterior_cpu = 0, 0.0
    for corte in cortes:
        acciones = corte - anterior_accion
        if acciones <= 0:
            continue
        salida[f"{anterior_accion + 1}-{corte}"] = round(
            (serie_de_cpu[corte - 1] - anterior_cpu) / acciones, 4
        )
        anterior_accion, anterior_cpu = corte, serie_de_cpu[corte - 1]
    return salida
