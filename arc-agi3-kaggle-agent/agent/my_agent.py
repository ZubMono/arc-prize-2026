# =============================================================================
# Prometheus -- agente offline para ARC Prize 2026 (track ARC-AGI-3)
#
# SPDX-License-Identifier: MIT-0
# Copyright 2026 ZubMono
#
# MIT No Attribution: se concede permiso, sin cargo, a cualquier persona que
# obtenga una copia de este software y su documentacion asociada, para usarlo
# sin restriccion, incluyendo sin limitacion los derechos de usar, copiar,
# modificar, fusionar, publicar, distribuir, sublicenciar y/o vender copias.
# EL SOFTWARE SE ENTREGA "TAL CUAL", SIN GARANTIA DE NINGUN TIPO. Texto
# completo de la licencia: https://github.com/ZubMono/arc-prize-2026/blob/main/LICENSE
#
# Codigo fuente y historia: https://github.com/ZubMono/arc-prize-2026
#
# ARCHIVO GENERADO por submission/build_agent.py -- NO editar a mano: editar el
# paquete fuente (arc_agent/) y regenerar con `make agente`.
# =============================================================================
"""Prometheus: politica de exploracion 100% offline (sin LLM en inferencia) para
ARC-AGI-3 -- memoria de estados con firma enmascarada, modelo de mundo por sintesis
DSL, macro-acciones, ranker de coordenadas de click y prior de direcciones. La clase
`MyAgent` (al final del archivo) implementa el contrato del framework oficial
`ARC-AGI-3-Agents`; `arcengine` y `agents` los provee el entorno de ejecucion."""


# ============================== arc_agent/reloj_presupuesto.py ==============================
"""[arc-agi3-kaggle-agent/reloj_presupuesto] BL.21701 -- EL SEGURO DE LAS 9 HORAS. Unico modulo
del paquete cuya razon de ser es que la submission no MUERA: el muro del notebook de Kaggle no
degrada el score, lo anula entero.

POR QUE EXISTE (el agujero medido). Hasta BL.21701 el unico numero de 9 horas del proyecto vivia
en `runtime_report.py`, que esta en `MODULOS_EXCLUIDOS` de `submission/build_agent.py`: NO viaja
al entregable. Y el `Swarm` oficial (`vendor/ARC-AGI-3-Agents/agents/swarm.py`) no tiene deadline
propio -- lanza un hilo por juego y espera a que todos terminen. O sea: en Kaggle no habia NINGUN
reloj. El unico freno era `MyAgent.MAX_ACTIONS`, una CONSTANTE, y una constante no puede ser
correcta cuando la cantidad de juegos privados es desconocida: el mismo 400 que sobra con 25
juegos es letal con 75.

LA MEDICION QUE LO FUNDA (barrido de presupuesto, 25 juegos publicos, 2 semillas):
  - la curva de score no hace meseta (400 acciones -> 4,0 niveles; 800 -> 5,5; 1600 -> 8,5), asi
    que recortar acciones "por las dudas" cuesta score real;
  - el costo por accion es SUPERLINEAL (0,154 s en los pasos 0-400, 0,202 s en los 1200-1600:
    +31%, porque la memoria de exploracion crece), asi que extrapolar lineal SUBESTIMA;
  - extrapolado a Kaggle (x1,8 sobre el CPU local), 1600 acciones cuestan 3,61 h con 25 juegos,
    7,21 h con 50 y 10,82 h con 75 -- REVIENTA.
Conclusion de diseno: el presupuesto lo tiene que imponer EL RELOJ, no una constante.

COMO CORTA -- dentro del contrato oficial, sin matar nada. `Agent.main()` del framework evalua
`is_done(frames, latest_frame)` al tope de cada vuelta. Cuando el reloj dice basta, `is_done`
devuelve True: el `while` termina, corre `cleanup()`, el hilo muere solo y el `Swarm` cierra la
scorecard como en cualquier final normal. NUNCA se levanta una excepcion ni se mata un hilo: un
hilo muerto a la fuerza deja la scorecard sin cerrar y el gateway sin parquet, que es exactamente
el modo de falla que este modulo previene.

CONCURRENCIA. El `Swarm` construye TODOS los agentes en el hilo principal y despues arranca un
hilo por juego (swarm.py:90-99), todos en el MISMO proceso. Por eso el reloj es del BATCH y se
comparte entre hilos: toda mutacion pasa por un unico candado. El consumo de cada partida se mide
con `time.thread_time()` (CPU del hilo propio) y no con reloj de pared: bajo el GIL los N hilos se
turnan un solo nucleo, asi que el tiempo de pared de una partida es el del batch entero y no
distingue quien gasto que. La suma de los CPU por hilo si suma, aproximadamente, el tiempo de
pared del batch -- y esa es justamente la moneda que se reparte aca."""

import os
import threading
import time

#: Muro DURO del notebook de Kaggle. No es configurable: es la regla de la competencia. Vive aca
#: (y no solo en `runtime_report.py`, que no viaja) para que el entregable pueda justificarse solo.
MURO_DEL_NOTEBOOK_SEGUNDOS = 9 * 60 * 60

#: Presupuesto que se ENTREGA: 8,0 de las 9 horas. La hora que se deja afuera (11%) no es
#: cautela vaga, cubre tramos concretos que NO estan bajo el reloj de este modulo:
#:   - lo que corre ANTES del import de `my_agent.py` -- `pip install` de las wheels offline y la
#:     espera al sidecar del gateway, que el notebook reintenta hasta 600 s (ver
#:     `scripts/build_kernel_notebook.py`, `--retry-max-time 600`);
#:   - la cola: cierre de scorecard, escritura de grabaciones y emision del parquet por el gateway;
#:   - el error de la extrapolacion misma (factor x1,8 estimado sobre CPU local, en una maquina de
#:     Kaggle que no controlamos, con costo por accion superlineal y creciente).
#: Con 1 h de reserva la submission sobrevive incluso si esos tramos se van al triple de lo medido.
PRESUPUESTO_POR_DEFECTO_SEGUNDOS = 8.0 * 60 * 60

#: Margen de CIERRE, dentro del presupuesto: cuando queda menos que esto, toda partida corta ya.
#: Es distinto de la hora de reserva de arriba -- esto solo compra el ultimo tramo ordenado
#: (terminar la accion en vuelo de cada hilo, `cleanup()`, `close_scorecard()`). 60 s alcanzan de
#: sobra: aun con 75 hilos, el sobrepaso maximo es una accion por hilo (~0,8 s la mas cara medida).
MARGEN_DE_CIERRE_SEGUNDOS = 60.0

#: Techo del margen como FRACCION del presupuesto. Con el presupuesto entregado (8 h) el 1% son
#: 288 s y manda el tope fijo de 60 s, o sea que en produccion esto no cambia nada. Existe para
#: los presupuestos chicos de una prueba local (`--presupuesto-horas 0.001`): sin el, un margen
#: fijo de 60 s se comeria el presupuesto entero y la corrida cortaria en la accion cero, que
#: parece un bug del guard y no lo es.
FRACCION_MAXIMA_DEL_MARGEN = 0.01

#: Escape por entorno para medir sin tocar codigo (barridos locales, tests). Un valor <= 0 apaga
#: el reloj: sin limite de tiempo, solo queda la cota de seguridad de acciones.
VARIABLE_DE_ENTORNO_PRESUPUESTO = "ARC_PRESUPUESTO_SEGUNDOS"

#: COTA DE SEGURIDAD de acciones por partida -- lo que `MyAgent.MAX_ACTIONS` toma. Ya NO es el
#: limite operativo (BL.21701): quien decide cuantas acciones entran es el reparto del reloj,
#: porque la cantidad de juegos privados es DESCONOCIDA y ningun numero fijo puede ser correcto
#: para 25 y para 75 a la vez. Esta cota solo cumple el proposito que le da el framework oficial:
#: "to avoid looping forever if agent doesnt exit".
#: Por que 4000: es 2,5x el punto mas alto que se MIDIO (1600 acciones -> 8,5 niveles, con la
#: curva todavia subiendo), y con el presupuesto entregado el cruce esta en ~23 juegos -- al costo
#: medio extrapolado a Kaggle (0,325 s/accion) 4000 acciones cuestan 1300 s, y el reparto da 8h/N:
#: con N >= 23 manda el reloj y con batches mas chicos manda esta cota. El set publico tiene 25
#: juegos, asi que en el regimen real el limite operativo es el tiempo, como se pidio.
#: Vive ACA y no en `kaggle_adapter.py` para que sea legible sin `arcengine` ni el framework
#: vendorizado: el test de extrapolacion tiene que poder leerlo en CI, donde no hay dataset.
COTA_DE_SEGURIDAD_DE_ACCIONES = 4000

#: Se prueba UNA vez al importar si la plataforma expone CPU por hilo. Si no (`time.thread_time`
#: es "Availability: Linux, Unix, Windows" y puede faltar), se degrada a reloj de pared: con eso
#: el reparto entre partidas queda mudo -- todas reportan el tiempo del batch y ninguna supera su
#: cuota -- pero el DEADLINE GLOBAL, que es el seguro que importa, se sigue aplicando igual.
try:
    time.thread_time()
    HAY_CPU_POR_HILO = True
except (AttributeError, OSError, RuntimeError):  # pragma: no cover -- no ocurre en Linux/Kaggle
    HAY_CPU_POR_HILO = False


def medir_cpu_del_hilo() -> float:
    """Segundos de CPU consumidos por el hilo ACTUAL (origen arbitrario: solo sirve por diferencia).

    Sin soporte de la plataforma degrada a `time.monotonic()`, que en un batch concurrente devuelve
    el tiempo del batch para todos: el reparto se apaga solo y manda el deadline global."""
    if HAY_CPU_POR_HILO:
        return time.thread_time()
    return time.monotonic()


def presupuesto_configurado(entorno: dict[str, str] | None = None) -> float:
    """Presupuesto en segundos: el de `ARC_PRESUPUESTO_SEGUNDOS` si esta y es un numero, si no el
    entregado. Un valor invalido NO explota (no se puede tumbar la submission por un typo en una
    variable de entorno): se ignora y se usa el default."""
    fuente = os.environ if entorno is None else entorno
    crudo = fuente.get(VARIABLE_DE_ENTORNO_PRESUPUESTO)
    if crudo is None or not str(crudo).strip():
        return PRESUPUESTO_POR_DEFECTO_SEGUNDOS
    try:
        return float(crudo)
    except (TypeError, ValueError):
        return PRESUPUESTO_POR_DEFECTO_SEGUNDOS


def margen_de_cierre_para(presupuesto_segundos: float) -> float:
    """Margen de cierre que le corresponde a un presupuesto: el tope fijo, salvo que el
    presupuesto sea tan chico que el tope se lo coma entero (solo pasa en pruebas locales)."""
    if presupuesto_segundos <= 0:
        return 0.0
    return min(MARGEN_DE_CIERRE_SEGUNDOS, presupuesto_segundos * FRACCION_MAXIMA_DEL_MARGEN)


class RelojDePresupuesto:
    """Reloj de un BATCH completo de partidas, compartido entre los hilos que las juegan.

    Dos frenos, en este orden:

      1. DEADLINE GLOBAL -- cuando al batch le quedan menos de `margen_de_cierre` segundos, TODA
         partida corta. Es el seguro contra el muro de las 9 h y no depende de cuantos juegos haya.
      2. REPARTO ENTRE PARTIDAS -- cada partida viva puede consumir, como maximo, su parte del
         tiempo que queda. La cuota se recalcula en cada consulta:

             cuota_i = (consumo_de_las_vivas + tiempo_restante) / partidas_pendientes

         Con todas las partidas parejas eso es exactamente `presupuesto / partidas`, que es el
         reparto que se pidio; con una partida adelantada, su cuota queda por debajo de lo que ya
         gasto y corta antes, devolviendo el resto al pool. Y cuando una partida termina (gano, o
         se quedo sin cuota), `partidas_pendientes` baja y las vivas ven crecer su cuota: por eso
         NO queda tiempo sin usar al final -- la ultima partida viva tiene cuota
         `consumo + restante`, o sea que juega hasta el deadline global.

    Todo el estado mutable esta bajo un unico candado. La consulta por accion es O(1): el consumo
    agregado de las partidas vivas se mantiene incremental en vez de recorrer el diccionario.

    LAS DOS MONEDAS, y por que el desajuste cae del lado seguro. El pool se mide en tiempo de
    PARED (`segundos_restantes`) y el consumo de cada partida en CPU de su hilo. Cuando algo gasta
    pared sin gastar CPU de ninguna partida -- armar el entorno del juego, el logging, la espera de
    un harness -- pasa que `consumo_de_las_vivas + restante < presupuesto` y las cuotas se achican
    solas. O sea: el tiempo no atribuido lo paga el reparto, nunca el deadline. Medido en el loop
    local con 3 juegos y 27 s de presupuesto: 26,9 s de pared usados, ninguno de mas."""

    def __init__(
        self,
        presupuesto_segundos: float | None = None,
        margen_de_cierre: float | None = None,
        ahora=time.monotonic,
    ) -> None:
        self._ahora = ahora
        self._inicio = ahora()
        self._presupuesto = (
            presupuesto_configurado()
            if presupuesto_segundos is None
            else float(presupuesto_segundos)
        )
        self._margen_de_cierre = (
            margen_de_cierre_para(self._presupuesto)
            if margen_de_cierre is None
            else max(0.0, float(margen_de_cierre))
        )
        self._candado = threading.Lock()
        self._consumo_por_partida: dict[int, float] = {}
        self._etiquetas: dict[int, str] = {}
        self._consumo_de_las_vivas = 0.0
        self._finalizadas = 0
        self._cortadas_por_reloj = 0
        self._total_declarado = 0
        self._proxima_manija = 0

    # -- configuracion -------------------------------------------------------------------------

    def declarar_total_de_partidas(self, total: int) -> None:
        """Cuantas partidas va a tener el batch EN TOTAL, incluidas las que todavia no arrancaron.

        Hace falta cuando el orquestador arranca las partidas de a una (`scripts/play_local.py`
        juega en serie): sin esto el reloj ve UNA sola partida viva, le da todo el presupuesto y la
        primera se come el batch entero. El `Swarm` oficial no lo necesita -- construye los N
        agentes antes de arrancar ningun hilo, asi que las N quedan registradas de entrada -- pero
        declararlo igual es inofensivo: siempre se toma el maximo entre vivas y pendientes."""
        with self._candado:
            self._total_declarado = max(0, int(total))

    # -- ciclo de vida de una partida ----------------------------------------------------------

    def registrar_partida(self, etiqueta: str = "") -> int:
        """Da de alta una partida y devuelve su manija. La manija es un entero propio y no el
        `game_id`: el mismo juego puede jugarse dos veces en un batch y dos partidas nunca deben
        compartir contabilidad."""
        with self._candado:
            manija = self._proxima_manija
            self._proxima_manija += 1
            self._consumo_por_partida[manija] = 0.0
            self._etiquetas[manija] = etiqueta
            return manija

    def finalizar_partida(self, manija: int) -> None:
        """Baja de una partida: su cuota vuelve al pool de las que siguen vivas. Idempotente --
        el framework llama `cleanup()` desde `main()` y otra vez desde `Swarm.cleanup()`."""
        with self._candado:
            consumo = self._consumo_por_partida.pop(manija, None)
            if consumo is None:
                return
            self._etiquetas.pop(manija, None)
            self._consumo_de_las_vivas -= consumo
            self._finalizadas += 1

    # -- lecturas ------------------------------------------------------------------------------

    @property
    def presupuesto_segundos(self) -> float:
        return self._presupuesto

    @property
    def reloj_apagado(self) -> bool:
        """Presupuesto <= 0: sin limite de tiempo (barridos de medicion locales)."""
        return self._presupuesto <= 0

    def segundos_transcurridos(self) -> float:
        return max(0.0, self._ahora() - self._inicio)

    def segundos_restantes(self) -> float:
        """Lo que queda del presupuesto. `inf` con el reloj apagado."""
        if self.reloj_apagado:
            return float("inf")
        return self._presupuesto - self.segundos_transcurridos()

    def deadline_alcanzado(self) -> bool:
        """True cuando ya no queda mas que el margen de cierre: a partir de aca corta todo."""
        return self.segundos_restantes() <= self._margen_de_cierre

    def partidas_vivas(self) -> int:
        with self._candado:
            return len(self._consumo_por_partida)

    def partidas_pendientes(self) -> int:
        """Partidas que todavia tienen derecho a tiempo: las vivas, o las declaradas que faltan
        (lo que sea mayor). Nunca menos de 1, para no dividir por cero."""
        with self._candado:
            return self._partidas_pendientes_sin_candado()

    def cuota_de_partida(self, manija: int) -> float:
        """Segundos de CPU que esta partida tiene derecho a consumir EN TOTAL, con la foto de
        ahora. `inf` con el reloj apagado; 0.0 si la partida ya no esta viva."""
        with self._candado:
            return self._cuota_sin_candado(manija)

    def estado(self) -> dict:
        """Foto para diagnostico/log. No decide nada -- solo se mira."""
        with self._candado:
            return {
                "presupuestoSegundos": self._presupuesto,
                "transcurridoSegundos": round(self.segundos_transcurridos(), 3),
                "restanteSegundos": self.segundos_restantes(),
                "partidasVivas": len(self._consumo_por_partida),
                "juegosVivos": sorted(self._etiquetas.values()),
                "partidasFinalizadas": self._finalizadas,
                "partidasCortadasPorReloj": self._cortadas_por_reloj,
                "totalDeclarado": self._total_declarado,
                "consumoDeLasVivasSegundos": round(self._consumo_de_las_vivas, 3),
            }

    # -- la consulta por accion ----------------------------------------------------------------

    def debe_cortar(self, manija: int, consumo_segundos: float) -> bool:
        """LA consulta que hace `is_done`, una vez por accion. Anota el consumo acumulado de esta
        partida y responde si tiene que cerrar.

        Corta si (a) el batch entro en el margen de cierre del deadline global, o (b) esta partida
        ya gasto su cuota del reparto. Una manija desconocida (partida ya finalizada) corta: es el
        lado seguro del error."""
        with self._candado:
            anterior = self._consumo_por_partida.get(manija)
            if anterior is None:
                return True
            consumo = max(0.0, float(consumo_segundos))
            self._consumo_de_las_vivas += consumo - anterior
            self._consumo_por_partida[manija] = consumo

            if self.reloj_apagado:
                return False
            if self.segundos_restantes() <= self._margen_de_cierre:
                self._cortadas_por_reloj += 1
                return True
            if consumo >= self._cuota_sin_candado(manija):
                self._cortadas_por_reloj += 1
                return True
            return False

    # -- internos (siempre bajo candado) --------------------------------------------------------

    def _partidas_pendientes_sin_candado(self) -> int:
        por_declarar = self._total_declarado - self._finalizadas
        return max(1, len(self._consumo_por_partida), por_declarar)

    def _cuota_sin_candado(self, manija: int) -> float:
        if manija not in self._consumo_por_partida:
            return 0.0
        if self.reloj_apagado:
            return float("inf")
        restante = max(0.0, self.segundos_restantes())
        return (self._consumo_de_las_vivas + restante) / self._partidas_pendientes_sin_candado()


#: Reloj del proceso. La marca de tiempo se toma AL IMPORTAR este modulo, que en Kaggle ocurre
#: cuando el framework registra `MyAgent` -- o sea al principio de la corrida del agente, despues
#: de la instalacion de wheels y la espera al gateway (los dos tramos que cubre la hora de reserva).
RELOJ_GLOBAL = RelojDePresupuesto()


# ============================== arc_agent/types.py ==============================
"""[arc-agi3-kaggle-agent/types] BL.20783 -- representacion INTERNA de la politica (nacio como
mirror del wire format oficial de docs.arcprize.org/rest_overview, mismo contrato que
projects/arc-agi-runner/src/types.ts). Desde BL.21555 el wire real lo hablan los tipos de
`arcengine` y `kaggle_adapter.py` traduce hacia estos; este modulo SI viaja al entregable porque
es el vocabulario que consume todo el nucleo (frames como tuplas hasheables para la firma de
estado, enums por NOMBRE de accion). Ver submission/build_agent.py (frontera)."""

from dataclasses import dataclass
from enum import Enum


class GameState(str, Enum):
    NOT_FINISHED = "NOT_FINISHED"
    NOT_STARTED = "NOT_STARTED"
    WIN = "WIN"
    GAME_OVER = "GAME_OVER"


class GameAction(str, Enum):
    """Las 7 acciones estandar + RESET de todo juego ARC-AGI-3 (docs.arcprize.org/actions)."""

    RESET = "RESET"
    ACTION1 = "ACTION1"
    ACTION2 = "ACTION2"
    ACTION3 = "ACTION3"
    ACTION4 = "ACTION4"
    ACTION5 = "ACTION5"
    ACTION6 = "ACTION6"
    ACTION7 = "ACTION7"


COMPLEX_ACTION = GameAction.ACTION6
GRID_MAX_COORD = 63


@dataclass(frozen=True)
class FrameData:
    """Espejo de FrameData del framework oficial ARC-AGI-3-Agents. `frame` es una tupla de
    grillas 64x64 (indices de color 0-15) -- normalmente un solo frame, el wire format permite
    mas de uno por respuesta. Tuplas (no listas) para que la instancia sea hasheable -- se usa
    como firma de estado en la memoria de exploracion (ver policy.py)."""

    game_id: str
    guid: str
    frame: tuple[tuple[tuple[int, ...], ...], ...]
    state: GameState
    available_actions: tuple[int, ...]
    levels_completed: int = 0
    win_levels: int = 0


@dataclass(frozen=True)
class ActionDecision:
    """Decision de accion + razonamiento declarado -- misma transparencia/auditoria de replay
    que ArcEvaluationStep.reasoning en arc-agi-runner (BL.20775)."""

    action: GameAction
    x: int | None = None
    y: int | None = None
    reasoning: str = ""


# ============================== arc_agent/priors.py ==============================
"""[arc-agi3-kaggle-agent/priors] BL.21560 -- ARCHIVO GENERADO por
scripts/fit_click_priors.py. NO editar a mano: regenerar con
`python3 scripts/fit_click_priors.py` y volver a correr las dos suites.

Es el UNICO conocimiento pre-computado que viaja al notebook de submission: pesos del ranker
de coordenadas (regresion logistica contra clicks REALES etiquetados con 'el click cambio la
grilla'), umbrales medidos de los detectores, orden de acciones por efectividad observada y
-- BL.21590 -- el prior de DIRECCIONES indexado por CONJUNTO DE ACCIONES DISPONIBLES.

QUE NO PUEDE CONTENER: claves con forma de game_id (`abcd-01234567`) ni de firma de estado
(entero de 32 bits). Memorizar la partida no generaliza a los juegos de evaluacion, que son
distintos por diseno. `submission/build_notebook.py` FALLA el build si alguna se cuela.

Orden de `pesosClick`: sesgo, bordeDeColor, tamanoComponente, esBordeDeComponente, rarezaDeColor, esColorDeFondo, distanciaAlBboxDeForeground, componenteRodeadaDeFondo, enRegionQueCambio.

`DIRECTION_PRIORS` es una HIPOTESIS INICIAL refutable, no una certeza cableada: siembra la
creencia y `direction_beliefs.py` la confirma, la remapea o la deja sin evidencia con lo que
vea en la partida. Fija la DIRECCION, nunca la magnitud del paso (medida: 2 a 6 celdas segun
el juego). Detalle de la medicion en el docstring de `scripts/fit_click_priors.py`.
"""

CLICK_PRIORS: dict = {
    "version": 1,
    "generatedAt": "2026-08-17T20:24:51Z",
    "nJuegosObservados": 5,
    "nTransicionesObservadas": 749,
    "pesosClick": [
        -2.241823,
        0.267326,
        0.23182,
        1.012707,
        -0.070761,
        -1.012849,
        -0.006758,
        -2.185072,
        -0.135375
    ],
    "umbralesDetectores": {
        "probabilidadMinimaDeClick": 0.245268,
        "similitudDeParcheMinima": 1.0
    },
    "ordenAcciones": [
        "ACTION2",
        "ACTION4",
        "ACTION3",
        "ACTION1",
        "ACTION7",
        "ACTION6",
        "ACTION5"
    ]
}

DIRECTION_PRIORS: dict = {
    "nJuegosMedidos": 25,
    "nJuegosConFlechas": 17,
    "nJuegosQueConfirman": 11,
    "nJuegosSinMovimientoObservable": 6,
    "nAccionesDeSonda": 2673,
    "traslacionesCanonicas": 528,
    "traslacionesContradictorias": 40,
    "contradiccionesSinExplicar": 0,
    "excepcionesDeMapeo": 0,
    "mapeoCanonico": {
        "ACTION1": [
            -1,
            0
        ],
        "ACTION2": [
            1,
            0
        ],
        "ACTION3": [
            0,
            -1
        ],
        "ACTION4": [
            0,
            1
        ]
    },
    "juegosQueConfirmanPorAccion": {
        "ACTION1": 10,
        "ACTION2": 10,
        "ACTION3": 9,
        "ACTION4": 9
    },
    "juegosQueContradicenPorAccion": {
        "ACTION1": 0,
        "ACTION2": 0,
        "ACTION3": 0,
        "ACTION4": 0
    },
    "conjuntosMedidos": {
        "1,2,3,4": {
            "juegos": 3,
            "confirman": 1,
            "sinMovimiento": 2
        },
        "1,2,3,4,5": {
            "juegos": 3,
            "confirman": 2,
            "sinMovimiento": 1
        },
        "1,2,3,4,5,6": {
            "juegos": 4,
            "confirman": 3,
            "sinMovimiento": 1
        },
        "1,2,3,4,5,6,7": {
            "juegos": 1,
            "confirman": 1,
            "sinMovimiento": 0
        },
        "1,2,3,4,6": {
            "juegos": 3,
            "confirman": 3,
            "sinMovimiento": 0
        },
        "1,2,3,4,6,7": {
            "juegos": 2,
            "confirman": 1,
            "sinMovimiento": 1
        },
        "3,4,6,7": {
            "juegos": 1,
            "confirman": 0,
            "sinMovimiento": 1
        },
        "5,6,7": {
            "juegos": 1,
            "confirman": 0,
            "sinMovimiento": 1
        },
        "6": {
            "juegos": 6,
            "confirman": 0,
            "sinMovimiento": 6
        },
        "6,7": {
            "juegos": 1,
            "confirman": 0,
            "sinMovimiento": 1
        }
    },
    "accionesSinPriorDeDireccion": [
        "ACTION5",
        "ACTION6",
        "ACTION7"
    ],
    "semanticaAction5": {
        "juegosMedidos": 12,
        "comportamientosDistintos": 4,
        "juegosConDireccionConsistente": 0
    },
    "magnitudesDePasoMedidas": [
        2,
        3,
        4,
        5,
        6
    ]
}


# ============================== arc_agent/banderas.py ==============================
"""[arc-agi3-kaggle-agent/banderas] BL.21702 -- REGISTRO UNICO de las palancas de exploracion,
cada una con su interruptor propio para poder medirla POR SEPARADO.

POR QUE EXISTE. BL.21594 metio tres mecanismos elegantes en un solo commit, los midio juntos y el
neto fue ruido alrededor de cero: no habia forma de saber cual pagaba y cual restaba, porque el
gate era un si/no sobre el paquete entero. Este modulo evita repetir eso. Cada palanca de BL.21702
entra APAGABLE de a una, asi que `gate_de_merge.py` puede correr la misma build con una palanca
menos y atribuirle el delta a esa palanca y a ninguna otra.

COMO SE CONFIGURA (variable de entorno, leida UNA vez al importar):

    ARC_AGENT_BANDERAS=ninguna                        # linea base: todas apagadas
    ARC_AGENT_BANDERAS=todas                          # el candidato completo
    ARC_AGENT_BANDERAS=todas,-macroCambioInformativo  # todas menos esa (leave-one-out)
    ARC_AGENT_BANDERAS=ninguna,+mascaraDeAccionUnica  # solo esa

Gramatica: tokens separados por coma. `ninguna` / `todas` / `entregadas` fijan la base (por defecto
`entregadas`); `-nombre` apaga, `nombre` o `+nombre` enciende. Un nombre desconocido es un ERROR
ruidoso y no un silencio: una bandera mal escrita en un barrido de medicion produciria una linea
base falsa, que es justo el desenlace que este modulo existe para evitar.

QUE SE ENTREGA LO DECIDE EL GATE, NO LA INTENCION. En Kaggle no hay variable, asi que rige
`BANDERAS_POR_DEFECTO`, y ahi solo entran las palancas que SUBIERON los niveles totales contra el
harness real. Ver el comentario de esa constante para la medicion vigente.

SIN DEPENDENCIAS: stdlib pura, sin imports relativos. Va primero en `MODULE_ORDER` junto con el
reloj, y `world_model/` NO lo importa a proposito: desde un subpaquete haria falta un import
relativo de DOS puntos, y el builder del notebook solo desmonta la forma de UN punto. Lo que
world_model necesita entra por parametro explicito desde `policy.py`."""

import os
from typing import Final, Iterable

#: Variable de entorno que configura las palancas. Ausente = todas encendidas.
NOMBRE_DE_VARIABLE: Final[str] = "ARC_AGENT_BANDERAS"

#: MEMORIA DE COORDENADAS TRANSVERSAL AL ESTADO. `ClickMemory._probadas` se indexa por
#: (firma, x, y), asi que cada firma nueva vacia la cobertura y el ranker vuelve a la misma celda
#: de mayor puntaje. Medido en entorno real, 151 acciones: tn36 9 coordenadas distintas en 149
#: clicks, su15 5 en 138, dc22 5 en 8, sb26 13 en 16 -- del orden del 0,2% de las 4.096 celdas.
#: Alcance: los cuatro juegos de click de los siete atascados, y cualquier juego de click.
MEMORIA_TRANSVERSAL_DE_CLICKS: Final[str] = "memoriaTransversalDeClicks"

#: MASCARA DE VOLATILIDAD CONSTRUIBLE CON UNA SOLA ACCION. `volatility_mask.py` corta las dos
#: familias con `< VOLATILITY_MIN_DISTINCT_ACTIONS` (=2) y SEIS de los 25 juegos publicos exponen
#: `availableActions=[6]` (ft09, lp85, r11l, s5i5, tn36, vc33): ahi la mascara es imposible POR
#: CONSTRUCCION y toda la memoria por estado del agente queda inerte. Cuatro de esos seis YA
#: puntuan, asi que la palanca tiene upside fuera de los siete atascados.
MASCARA_DE_ACCION_UNICA: Final[str] = "mascaraDeAccionUnica"

#: CORTE DE LA AMPLIFICACION DE MACROCOMMITMENT. `continuar()` solo corta con `hubo_cambio=False`,
#: asi que una accion cosmetica siempre-cambiante se lleva hasta x8 el presupuesto de una que
#: no-opea (sb26: ACTION5 82,8% de 151 acciones). Con la palanca la macro exige que el cambio sea
#: INFORMATIVO -- que el estado al que llega no sea uno ya visitado en el episodio.
MACRO_CAMBIO_INFORMATIVO: Final[str] = "macroCambioInformativo"

#: WARMUP DEL LIBRO DE APERTURAS CON LOS CLICKS SEGUIDOS. `_registrar_warmup` limpia `_tanteadas` e
#: `_intentos` en cuanto un click cambia el tablero, y la pantalla de titulo ANIMA: `hubo_cambio`
#: es SIEMPRE True, el libro vuelve a tantear las cuatro flechas entre click y click y el
#: presupuesto de 9 clicks nunca se gasta. Medido en dc22: 8 ACTION6 en 151 acciones.
WARMUP_DE_CLICKS_SEGUIDOS: Final[str] = "warmupDeClicksSeguidos"

#: RESET VOLUNTARIO ANTE ESTADO CONGELADO. SOLO para el caso medido en lf52 y dc22 (47 y 54
#: revisitas con gap=1: frame identico entre pasos consecutivos, sin game-over que rescate). En el
#: resto esta REFUTADO por medicion: el RESET involuntario ya se dispara solo (sp80 6 por partida,
#: su15 4, tn36 2, tu93 2) y los siete siguen en 0 niveles. El disparador exige evidencia de
#: congelamiento, no "me parece que estoy en un bucle" -- ver `policy.py`.
RESET_POR_CONGELAMIENTO: Final[str] = "resetPorCongelamiento"

#: CASTIGO EN EL RANKING A LA ACCION QUE MATO DESDE ESE ESTADO (BL.21767). Hasta ese BL el
#: GAME_OVER ni siquiera llegaba a la politica: `kaggle_adapter` lo presentaba como NOT_STARTED,
#: asi que el evento mas informativo de la partida se procesaba como el arranque y el agente no
#: tenia DONDE anotar la muerte (sp80: 6 GAME_OVERs en 151 acciones y 0 niveles, BL.21702; g50t:
#: 15 en 1.750, BL.21763). El REGISTRO del hecho es incondicional (`MemoriaDeMuertes`, pura
#: observacion); esta palanca enciende su CONSUMO: relegar al fondo del ranking, con descuento que
#: se agota, la accion que produjo un GAME_OVER desde esa misma firma. La localidad que lo
#: justifica esta MEDIDA en `mediciones/BL21767_muertes_por_juego.json`, no asumida.
MEMORIA_DE_MUERTES: Final[str] = "memoriaDeMuertes"

#: Todas las palancas (BL.21702 + BL.21767), en el orden en que conviene medirlas (radio de
#: impacto medido decreciente). Fuente unica: el parser y los tests leen de aca.
BANDERAS_CONOCIDAS: Final[tuple[str, ...]] = (
    MEMORIA_TRANSVERSAL_DE_CLICKS,
    MASCARA_DE_ACCION_UNICA,
    MACRO_CAMBIO_INFORMATIVO,
    WARMUP_DE_CLICKS_SEGUIDOS,
    RESET_POR_CONGELAMIENTO,
    MEMORIA_DE_MUERTES,
)

#: Palancas que el ENTREGABLE lleva encendidas: las que el gate de merge APROBO contra el harness
#: real. Fuente unica de "que se entrega"; `BANDERAS_CONOCIDAS` es "que existe", que no es lo mismo.
#: El valor lo fija la MEDICION, no la intencion de quien escribio la palanca.
#:
#: LA MEDICION DE BL.21702 (harness real, 25 juegos, 200 pasos, semillas gate-1/2/3):
#:
#:   ninguna (linea base)  12 niveles      todas (candidato completo)  12 niveles   -> delta +0
#:
#: El paquete completo EMPATA, y el gate del BL dice que un empate no se mergea. Pero empatar no es
#: no pasar nada: por juego, `todas` DESBLOQUEO ar25 (0,0,0 -> 1,0,1) y PERDIO uno en ft09 y uno en
#: vc33. Ahi entra el barrido leave-one-out (`scripts/ablacion_de_palancas.py`, 3 semillas sobre los
#: tres juegos que se movieron -- los demas dieron el mismo numero en las dos puntas y no pueden
#: discriminar), que separa las dos mitades:
#:
#:   aporte = todas - (todas menos esa)      memoriaTransversalDeClicks   -2
#:                                           macroCambioInformativo       +2
#:                                           mascaraDeAccionUnica         +0
#:                                           warmupDeClicksSeguidos       +0
#:                                           resetPorCongelamiento        +0
#:
#: O sea: el neto de ruido alrededor de cero que BL.21594 nunca pudo explicar es, aca, DOS EFECTOS
#: REALES DE SIGNO OPUESTO que se cancelan. La memoria transversal de clicks RESTA dos niveles pese
#: a ganar cobertura -- en ft09 y vc33 la celda productiva ya estaba identificada y repartir clicks
#: la abandona -- y el corte de la macro SUMA dos. Sin la bandera de cada una esto era invisible.
#:
#: BL.21939 / EXP-12 (2026-08-21) -- `macroCambioInformativo` SE ENTREGA. La ablacion ORDENA pero no
#: aprueba, asi que se midio en el GATE (25 juegos x 200 pasos x 3 semillas, el mismo instrumento
#: que produjo la linea base):
#:
#:   ninguna                       12 niveles, 4 juegos con nivel
#:   ninguna,+macroCambioInformativo  14 niveles, 5 juegos con nivel   -> delta +2
#:
#: Las 15075 acciones son IDENTICAS en las dos puntas, y toda la diferencia esta en UN juego: ar25
#: pasa de 0 a 2 (gate-1 y gate-3, +1 cada una); los otros 24 dan exactamente el mismo numero. O sea
#: que no es una mejora incremental sino un juego DESBLOQUEADO -- el mismo (0,0,0 -> 1,0,1) que el
#: parrafo de arriba ya habia visto en `todas`, que ahora queda explicado: ahi lo cancelaban las
#: otras palancas. La ablacion (+2) y el gate (+2) COINCIDEN, a diferencia de `memoriaDeMuertes`,
#: donde el lazo rapido media MUERTES (metrica intermedia) y el gate midio niveles: -1 (EXP-11).
#: Por eso lo que se entrega es esta sola y NO `todas`.
BANDERAS_POR_DEFECTO: Final[tuple[str, ...]] = (MACRO_CAMBIO_INFORMATIVO,)

_TOKEN_TODAS: Final[str] = "todas"
_TOKEN_NINGUNA: Final[str] = "ninguna"
_TOKEN_ENTREGADAS: Final[str] = "entregadas"


class BanderaDesconocida(ValueError):
    """Un token de `ARC_AGENT_BANDERAS` que no nombra ninguna palanca conocida."""


class Banderas:
    """Estado de las palancas de UNA corrida. Inmutable en la practica: se construye una vez al
    importar el modulo (o a mano en un test) y se lee."""

    __slots__ = ("_activas",)

    def __init__(self, activas: Iterable[str] | None = None) -> None:
        seleccion = tuple(BANDERAS_POR_DEFECTO) if activas is None else tuple(activas)
        desconocidas = [n for n in seleccion if n not in BANDERAS_CONOCIDAS]
        if desconocidas:
            raise BanderaDesconocida(
                f"Bandera(s) desconocida(s): {', '.join(sorted(desconocidas))}. "
                f"Conocidas: {', '.join(BANDERAS_CONOCIDAS)}"
            )
        self._activas = frozenset(seleccion)

    @property
    def activas(self) -> tuple[str, ...]:
        """Palancas encendidas, en el orden canonico de `BANDERAS_CONOCIDAS`."""
        return tuple(n for n in BANDERAS_CONOCIDAS if n in self._activas)

    def activa(self, nombre: str) -> bool:
        if nombre not in BANDERAS_CONOCIDAS:
            raise BanderaDesconocida(f"Bandera desconocida: {nombre}")
        return nombre in self._activas

    def con(self, *nombres: str) -> "Banderas":
        """Copia con SOLO esas palancas encendidas -- la forma que usan los tests deterministas."""
        return Banderas(nombres)

    def sin(self, *nombres: str) -> "Banderas":
        """Copia con esas palancas apagadas y el resto como esta."""
        return Banderas(n for n in self.activas if n not in nombres)

    def resumen(self) -> str:
        """Linea legible para el reporte de una corrida -- el gate la imprime para que dos
        mediciones no se puedan confundir."""
        return ",".join(self.activas) if self._activas else _TOKEN_NINGUNA

    @classmethod
    def todas(cls) -> "Banderas":
        """Todas las palancas conocidas, aprobadas o no. Es lo que mide el candidato completo."""
        return cls(BANDERAS_CONOCIDAS)

    @classmethod
    def desde_texto(cls, texto: str | None) -> "Banderas":
        """Parsea la gramatica documentada en el encabezado del modulo. Texto vacio o None = las
        palancas ENTREGADAS (`BANDERAS_POR_DEFECTO`), no todas las conocidas."""
        if texto is None or not texto.strip():
            return cls()
        activas = set(BANDERAS_POR_DEFECTO)
        for crudo in texto.split(","):
            token = crudo.strip()
            if not token:
                continue
            if token == _TOKEN_TODAS:
                activas = set(BANDERAS_CONOCIDAS)
                continue
            if token == _TOKEN_NINGUNA:
                activas = set()
                continue
            if token == _TOKEN_ENTREGADAS:
                activas = set(BANDERAS_POR_DEFECTO)
                continue
            if token.startswith("-"):
                nombre = token[1:]
                if nombre not in BANDERAS_CONOCIDAS:
                    raise BanderaDesconocida(
                        f"Bandera desconocida en {NOMBRE_DE_VARIABLE}: {nombre}. "
                        f"Conocidas: {', '.join(BANDERAS_CONOCIDAS)}"
                    )
                activas.discard(nombre)
                continue
            nombre = token[1:] if token.startswith("+") else token
            if nombre not in BANDERAS_CONOCIDAS:
                raise BanderaDesconocida(
                    f"Bandera desconocida en {NOMBRE_DE_VARIABLE}: {nombre}. "
                    f"Conocidas: {', '.join(BANDERAS_CONOCIDAS)}"
                )
            activas.add(nombre)
        return cls(activas)

    @classmethod
    def desde_entorno(cls) -> "Banderas":
        return cls.desde_texto(os.environ.get(NOMBRE_DE_VARIABLE))


#: Palancas vigentes del proceso. Se lee UNA vez al importar: una corrida no puede cambiar de
#: configuracion a mitad de camino sin que la medicion deje de significar nada.
BANDERAS: Banderas = Banderas.desde_entorno()


def bandera_activa(nombre: str, banderas: Banderas | None = None) -> bool:
    """Atajo de lectura: `banderas` explicitas (tests) o las del proceso."""
    return (BANDERAS if banderas is None else banderas).activa(nombre)


# ============================== arc_agent/world_model/grid.py ==============================
"""[arc-agi3-kaggle-agent/world_model/grid] -- utilidades puras sobre grillas ARC
(list[list[int]], colores 4-bit 0-15). Puerto de arc-agi-runner/src/worldModel/grid.ts.
Sin red, sin I/O, sin terceros -- helpers deterministas reusados por primitive_ops.py,
primitives.py, synthesis.py, state_signature.py y planner.py."""

from dataclasses import dataclass
from typing import Final, NamedTuple

Grid = list[list[int]]

# BL.21558 -- mascara de volatilidad de UN episodio: True en las celdas cuyo valor cambia sin
# relacion con la accion ejecutada (HUD, contador de pasos, animaciones de fondo). Toda comparacion
# "enmascarada" las IGNORA. Se indexa [y][x]; una fila mas corta que la grilla (o ausente) se lee
# como "no volatil", porque la mascara se APRENDE en vivo (volatility_mask.py) y puede ir por
# detras de un cambio de forma del frame. Puerto de VolatilityMask en grid.ts.
VolatilityMask = list[list[bool]]

# Aritmetica de 32 bits: Python tiene enteros de precision arbitraria, asi que CADA paso del
# hash se enmascara para reproducir bit a bit el Math.imul del TS (ver hash_grid).
MASK32: Final[int] = 0xFFFFFFFF
FNV_OFFSET_BASIS: Final[int] = 0x811C9DC5
FNV_PRIME: Final[int] = 0x01000193
# Separador de fila -- evita que [[1],[2]] colisione con [[1,2]].
ROW_SEPARATOR: Final[int] = 0xFF
# BL.21558 -- valor que se mezcla al hash en lugar del contenido real de una celda volatil. 16 esta
# FUERA del rango de colores ARC (0-15), asi que no puede colisionar con un color legitimo.
VOLATILE_CELL_HASH_PLACEHOLDER: Final[int] = 0x10


@dataclass(frozen=True)
class BoundingBox:
    """Rectangulo inclusivo (min y max pertenecen a la caja). Campos en snake_case porque NO
    viaja al JSON del fixture: es interna del motor, el TS nunca la serializa."""

    min_x: int
    min_y: int
    max_x: int
    max_y: int


class GridDimensions(NamedTuple):
    """Orden de campos (width, height) -- coincide con la declaracion del tipo TS. Construir
    SIEMPRE por keyword para que el orden posicional no sea una trampa."""

    width: int
    height: int


def clone_grid(grid: Grid) -> Grid:
    """Copia profunda de 2 niveles: los enteros son inmutables, no hace falta mas."""
    return [row[:] for row in grid]


def grid_dimensions(grid: Grid) -> GridDimensions:
    """El ancho se deriva de la fila 0 (invariante de rectangularidad, ver CONTRATO 0.2)."""
    return GridDimensions(width=len(grid[0]) if grid else 0, height=len(grid))


def is_volatile_cell(mask: "VolatilityMask | None", y: int, x: int) -> bool:
    """Lectura tolerante de la mascara -- fuera de rango = no volatil (ver VolatilityMask).
    El chequeo explicito de indices reemplaza al `mask[y]?.[x]` del TS: en Python un indice
    negativo NO da None, lee desde el otro extremo, que seria un bug silencioso."""
    if mask is None or y < 0 or y >= len(mask):
        return False
    row = mask[y]
    if x < 0 or x >= len(row):
        return False
    return row[x] is True


def grids_equal(a: Grid, b: Grid) -> bool:
    """Comparacion explicita celda a celda en vez de `a == b`: mantiene la MISMA tolerancia del
    TS frente a filas de distinto largo (devuelve False, nunca lanza). Delega en la version
    enmascarada -- una sola implementacion, igual que en grid.ts."""
    return grids_equal_masked(a, b, None)


def grids_equal_masked(a: Grid, b: Grid, mask: "VolatilityMask | None") -> bool:
    """BL.21558 -- igualdad IGNORANDO las celdas volatiles. `mask=None` es igualdad estricta.
    La FORMA (alto y largo de cada fila) se sigue comparando siempre: un cambio de tamano nunca es
    ruido de HUD, es otro estado."""
    if len(a) != len(b):
        return False
    for y in range(len(a)):
        row_a = a[y]
        row_b = b[y]
        if len(row_a) != len(row_b):
            return False
        for x in range(len(row_a)):
            if row_a[x] != row_b[x] and not is_volatile_cell(mask, y, x):
                return False
    return True


def cell_diff_count(a: Grid, b: Grid) -> int:
    """Distancia de Hamming entre dos grillas -- cantidad de celdas distintas. Si difieren en
    forma, cada celda fuera de la interseccion cuenta como distinta (penaliza cambios de tamano
    no explicados). Heuristica admisible-en-la-practica para el planner (nunca sobreestima el
    costo real de igualar dos grillas identicas: da 0 solo si son iguales).

    El centinela -1 para "celda ausente" no colisiona nunca con un color real (0-15), asi que
    dos ausencias enfrentadas cuentan como iguales, igual que los `undefined` del TS."""
    height = max(len(a), len(b))
    diff = 0
    for y in range(height):
        row_a = a[y] if y < len(a) else []
        row_b = b[y] if y < len(b) else []
        width = max(len(row_a), len(row_b))
        for x in range(width):
            value_a = row_a[x] if x < len(row_a) else -1
            value_b = row_b[x] if x < len(row_b) else -1
            if value_a != value_b:
                diff += 1
    return diff


def detect_background_color(grid: Grid) -> int:
    """Color de fondo -- el mas frecuente en la grilla (heuristica estandar ARC: el fondo domina
    el area). Empate: el de menor indice de color, para determinismo. Grilla vacia (o de filas
    vacias): 0, igual que el `best = 0` inicial del TS."""
    counts: dict[int, int] = {}
    for row in grid:
        for cell in row:
            counts[cell] = counts.get(cell, 0) + 1
    best = 0
    best_count = -1
    # Ascendente por color + comparacion ESTRICTA: el primero en superar al mejor gana, asi el
    # empate lo resuelve siempre el indice de color mas bajo.
    for color in sorted(counts):
        count = counts[color]
        if count > best_count:
            best = color
            best_count = count
    return best


def foreground_bounding_box(grid: Grid, background_color: int) -> BoundingBox | None:
    """Bounding box de las celdas que NO son `background_color`. None si la grilla es uniforme
    (no hay foreground). El TS arranca con centinelas Infinity y compara `maxX < minX` al final;
    aca el flag `found` expresa lo mismo sin depender de un valor magico."""
    found = False
    min_x = 0
    min_y = 0
    max_x = 0
    max_y = 0
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell == background_color:
                continue
            if not found:
                found = True
                min_x = x
                max_x = x
                min_y = y
                max_y = y
                continue
            if x < min_x:
                min_x = x
            if x > max_x:
                max_x = x
            if y < min_y:
                min_y = y
            if y > max_y:
                max_y = y
    if not found:
        return None
    return BoundingBox(min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y)


def hash_grid(grid: Grid) -> int:
    """Hash entero estable (FNV-1a de 32 bits, con separador de fila para no colisionar grillas
    de distinta forma con el mismo contenido concatenado). Usado por state_signature.py para
    detectar estados repetidos y por planner.py para deduplicar nodos de la busqueda.

    Por que `& MASK32` reproduce Math.imul exactamente: Math.imul(a, b) devuelve los 32 bits
    bajos del producto interpretados como int32 con signo. Todas las operaciones posteriores
    (^, imul, el `>>> 0` final) dependen SOLO de esos 32 bits bajos, y el XOR es invariante ante
    la interpretacion con/sin signo. Mantener `h` sin signo enmascarado da el mismo valor final
    que el `hash >>> 0` del TS. Retorno: entero sin signo en [0, 2**32)."""
    return hash_grid_masked(grid, None)


def hash_grid_masked(grid: Grid, mask: "VolatilityMask | None") -> int:
    """BL.21558 -- hash que IGNORA el contenido de las celdas volatiles: cada una aporta
    VOLATILE_CELL_HASH_PLACEHOLDER en vez de su color, asi que la posicion sigue contando (la forma
    no se pierde) pero el valor cambiante no. Con `mask=None` reproduce `hash_grid` bit a bit."""
    h = FNV_OFFSET_BASIS
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            valor = VOLATILE_CELL_HASH_PLACEHOLDER if is_volatile_cell(mask, y, x) else cell
            h = (h ^ valor) & MASK32
            h = (h * FNV_PRIME) & MASK32
        h = (h ^ ROW_SEPARATOR) & MASK32
        h = (h * FNV_PRIME) & MASK32
    return h


def neutralize_volatile_cells(
    reference: Grid, target: Grid, mask: "VolatilityMask | None"
) -> Grid:
    """BL.21558 -- copia de `target` con las celdas volatiles reemplazadas por el valor que tienen
    en `reference`. Es la forma de meter la mascara en un consumidor que NO la conoce:
    `synthesize_program` recibe (pre, neutralize_volatile_cells(pre, post, mask)) y ve un par donde
    las celdas de HUD son identicas, con lo cual solo tiene que explicar el cambio REAL del
    tablero. Sin esto habria que cablear la mascara por todo el DSL y romper la paridad con el
    motor TypeScript.

    `mask=None` devuelve un clon fiel (nunca la misma referencia: quien lo recibe puede mutarlo sin
    corromper la ventana de observaciones). Una celda sin equivalente en `reference` conserva su
    valor de `target` -- sin referencia no hay con que neutralizarla."""
    salida: Grid = []
    for y, row in enumerate(target):
        fila_ref = reference[y] if y < len(reference) else []
        nueva: list[int] = []
        for x, cell in enumerate(row):
            if is_volatile_cell(mask, y, x) and x < len(fila_ref):
                nueva.append(fila_ref[x])
            else:
                nueva.append(cell)
        salida.append(nueva)
    return salida


# ============================== arc_agent/world_model/volatility_mask.py ==============================
"""[arc-agi3-kaggle-agent/world_model/volatility_mask] BL.21558 -- aprende, DURANTE el episodio,
que celdas del frame cambian sin relacion con la accion ejecutada (HUD, contador de pasos, barra de
progreso) para que el resto del modelo de mundo pueda ignorarlas. Puerto de
arc-agi-runner/src/worldModel/volatilityMask.ts.

EL PROBLEMA MEDIDO. Los juegos publicos de ARC-AGI-3 producen un frame distinto en cada paso pase
lo que pase: ar25-0c556536 = 76 firmas unicas / 78 pasos; lf52-271a04aa = 94/94; dc22-fdcac232 =
128/129; ka59 = 100/101. Con esas celdas dentro de la comparacion, `grids_equal` no devuelve True
nunca y se cae la cadena entera: no se detecta ningun no-op, `synthesize_program` tendria que
explicar tambien el contador (imposible con un DSL de tablero) y ninguna firma de estado se repite,
con lo cual la memoria por-estado de policy.py queda inerte.

DOS FAMILIAS DE RUIDO, PORQUE EL DATO REAL MOSTRO DOS FORMAS DISTINTAS. La primera version de este
modulo solo tenia la familia 1 y, medida contra frames REALES capturados de la API oficial,
enmascaraba CERO celdas en los cuatro juegos citados: el ruido de ARC-AGI-3 no es un digito que
parpadea, es una BARRA que avanza.

Familia 1 -- celda que cambia casi siempre, bajo TODAS las acciones. Se exige
VOLATILITY_MIN_TRANSITIONS transiciones, VOLATILITY_MIN_DISTINCT_ACTIONS acciones distintas y, para
CADA accion observada, un ratio de cambio >= VOLATILITY_ENTRY_RATIO en SUS transiciones. Esa ultima
condicion es la que protege el tablero: el marcador del jugador cambia bajo las acciones de
movimiento pero NO bajo una accion inerte, asi que basta una accion que no lo mueva para que nunca
entre; un contador de HUD, en cambio, cambia igual bajo todas.

Familia 2 -- CONTADOR DE BARRIDO: una barra donde se enciende UNA celda nueva por paso. Medido
sobre partidas reales completas (82-125 transiciones cada una): lf52 fila 0 (1x64, avanza en el 100%
de los pasos), ar25 columna 63 (78%), dc22 fila 63 (51%), ka59 fila 63 (64%). La familia 1 no puede
verlas: cada celda de la barra cambia UNA sola vez en todo el episodio. El criterio que si las ve
mira la REGION: una componente conexa de >= SWEEP_MIN_CELLS celdas con forma de LINEA de una celda
de ancho, cuyos cambios ocurrieron casi siempre en SOLEDAD (ninguna otra celda cambiando a distancia
SWEEP_ISOLATION_RADIUS) y que registro cambios en >= SWEEP_ENTRY_RATIO de las transiciones, bajo
>= 2 acciones distintas.

POR QUE ESE CRITERIO NO SE COME EL TABLERO. Un objeto que se mueve cambia SIEMPRE 2 celdas
adyacentes a la vez: no pasa el filtro de soledad. Un tablero que responde cambia en bloques
(mediana medida: 108 celdas por paso en ar25, 18 en ka59): tampoco. Y una region 2D de celdas que
se encienden de a una queda afuera por el requisito de forma de linea.

POR QUE CONSERVADOR. Enmascarar una celda del TABLERO es mucho peor que no enmascarar una del HUD:
el agente se volveria ciego justo donde esta la señal, y no enmascarar es exactamente el
comportamiento previo a este BL. De ahi los umbrales altos y el tope VOLATILITY_MAX_FRACTION.

HISTERESIS. Salir de la mascara pide un ratio mas bajo que entrar (VOLATILITY_EXIT_RATIO,
SWEEP_EXIT_RATIO). Sin esa banda muerta, algo parado en el umbral entraria y saldria paso a paso y
las firmas de estado volverian a ser irrepetibles -- el defecto que este modulo existe para
arreglar.
"""

from typing import Final

# Import relativo en UNA sola linea: submission/build_notebook.py los desmonta con el regex
# `^from \.\w* import .+$` y la forma con parentesis dejaria un `)` colgando en el notebook.


#: Transiciones minimas antes de afirmar nada. Por debajo, cualquier ratio es ruido.
VOLATILITY_MIN_TRANSITIONS: Final[int] = 6

#: Acciones distintas minimas. Con una sola, "cambia siempre" y "esta accion la cambia siempre" son
#: indistinguibles -- y confundirlas enmascararia justo el efecto que hay que aprender.
VOLATILITY_MIN_DISTINCT_ACTIONS: Final[int] = 2

#: BL.21702 -- MODO DE ACCION UNICA. `VOLATILITY_MIN_DISTINCT_ACTIONS` = 2 vuelve la mascara
#: IMPOSIBLE POR CONSTRUCCION en los juegos que exponen un solo boton, y SEIS de los 25 publicos
#: exponen `availableActions=[6]`: ft09, lp85, r11l, s5i5, tn36, vc33. Medido en los siete juegos
#: atascados, la mascara termino en CERO celdas en todos -- y sin mascara ninguna firma de estado
#: se repite, con lo cual la memoria por estado de `policy.py` queda inerte de punta a punta.
#:
#: EL ARGUMENTO ORIGINAL SIGUE EN PIE, y por eso el modo no relaja el criterio sino que lo CAMBIA:
#: cuando hay un solo boton no queda ninguna accion de control con la que contrastar, asi que lo
#: unico que puede separar el HUD del tablero es cuan ABSOLUTA es la regularidad. De ahi los
#: umbrales de abajo, mucho mas altos que los normales. Y la familia 2 (barra de barrido) nunca
#: dependio del conteo de acciones: su criterio es de FORMA (linea de una celda de ancho, sobre un
#: borde) y de SOLEDAD (>=90% de los cambios sin compania alrededor), que un tablero que responde
#: no cumple -- ahi el minimo de acciones era una salvaguarda redundante.
#:
#: El modo se activa SOLO cuando el juego declara un vocabulario de una accion
#: (`declarar_vocabulario`), no cuando todavia no se observo una segunda: en un juego de varias
#: acciones una macro puede dejar 8 transiciones seguidas del mismo boton, y ahi el contraste
#: existe, solo que aun no se midio.
VOLATILITY_MIN_TRANSITIONS_ACCION_UNICA: Final[int] = 12

#: Fraccion de transiciones en las que la celda debe cambiar para entrar a la mascara en modo de
#: accion unica. 0.98 y no 0.85: sin una segunda accion con la que contrastar, lo unico que
#: distingue un contador de HUD de una celda del tablero es que el contador cambia en CASI TODAS
#: las transiciones sin excepcion. Una celda del tablero de un juego de click cambia cuando se
#: clickea cerca, no en 49 de cada 50 pasos; y si el frame entero se moviera asi,
#: `VOLATILITY_MAX_FRACTION` desactiva la mascara igual.
VOLATILITY_ENTRY_RATIO_ACCION_UNICA: Final[float] = 0.98

#: Salida de la mascara en modo de accion unica (HISTERESIS). Mas alta que `VOLATILITY_EXIT_RATIO`
#: en la misma proporcion en que la entrada es mas alta: la banda muerta conserva su ancho relativo.
VOLATILITY_EXIT_RATIO_ACCION_UNICA: Final[float] = 0.85

#: Fraccion de transiciones DE CADA ACCION en las que la celda debe cambiar para entrar. Alto a
#: proposito, pero no 1.0: un digito dibujado con sprites comparte pixeles entre glifos
#: consecutivos (8 -> 9), asi que con 1.0 el contador quedaria a medio enmascarar.
VOLATILITY_ENTRY_RATIO: Final[float] = 0.85

#: Fraccion por debajo de la cual una celda ya enmascarada vuelve a contar (ver HISTERESIS).
VOLATILITY_EXIT_RATIO: Final[float] = 0.6

#: Si el conjunto volatil superara esta fraccion del frame, la mascara se desactiva por completo.
#: Un frame que muta en mas de la mitad de sus celdas pase lo que pase no tiene un HUD ruidoso: no
#: es observable con este modelo, y enmascararlo dejaria al agente decidiendo sobre casi nada.
VOLATILITY_MAX_FRACTION: Final[float] = 0.5

#: Celdas minimas de una barra de progreso. Las cuatro medidas en juego real tienen 64 (un borde
#: entero del frame); el piso tolera barras mas cortas sin que un par de celdas sueltas del tablero
#: alcancen a formar una.
SWEEP_MIN_CELLS: Final[int] = 16

#: Transiciones minimas para evaluar la familia 2: el estadistico se calcula sobre la REGION, y con
#: pocas transiciones cualquier region chica pasaria el ratio por casualidad.
SWEEP_MIN_TRANSITIONS: Final[int] = 12

#: Fraccion de las transiciones del episodio en las que la barra tiene que haber avanzado para
#: entrar. Medido: 1.00 (lf52), 0.78 (ar25), 0.64 (ka59), 0.51 (dc22).
SWEEP_ENTRY_RATIO: Final[float] = 0.4

#: Ratio por debajo del cual una barra ya enmascarada vuelve a contar (ver HISTERESIS).
SWEEP_EXIT_RATIO: Final[float] = 0.25

#: Radio (Chebyshev) dentro del cual NO puede haber otra celda cambiando en la misma transicion para
#: considerar que el cambio ocurrio en soledad.
SWEEP_ISOLATION_RADIUS: Final[int] = 2

#: Fraccion de los cambios de la REGION que tuvieron que ocurrir en soledad. Se mide sobre la region
#: entera y no celda por celda: si un cambio del tablero pasa cerca de la barra, la celda afectada
#: no puede quedar descalificada para siempre.
SWEEP_MIN_ISOLATION_RATIO: Final[float] = 0.9


class _ContadoresDeAccion:
    """Transiciones observadas de una accion y, por celda, en cuantas de ellas cambio."""

    __slots__ = ("transiciones", "cambios")

    def __init__(self) -> None:
        self.transiciones: int = 0
        self.cambios: list[list[int]] = []


def _crecer_matriz(matriz: list[list[int]], height: int, width: int) -> None:
    while len(matriz) < height:
        matriz.append([])
    for row in matriz:
        while len(row) < width:
            row.append(0)


def _crecer_matriz_bool(matriz: list[list[bool]], height: int, width: int) -> None:
    while len(matriz) < height:
        matriz.append([])
    for row in matriz:
        while len(row) < width:
            row.append(False)


def _es_linea(celdas: list[int], width: int) -> bool:
    """True si la componente es una linea de UNA celda de ancho (fila o columna). Es la forma de una
    barra de progreso y NO la de una region del tablero que se enciende de a una celda -- el falso
    positivo mas peligroso, porque dejaria al agente ciego justo donde esta la señal."""
    min_y = min(indice // width for indice in celdas)
    max_y = max(indice // width for indice in celdas)
    min_x = min(indice % width for indice in celdas)
    max_x = max(indice % width for indice in celdas)
    return min_y == max_y or min_x == max_x


class VolatilityTracker:
    """Acumula evidencia transicion a transicion y expone la mascara vigente. UNA instancia por
    episodio: la volatilidad es una propiedad del juego EN CURSO, no del agente."""

    def __init__(self, permitir_accion_unica: bool = False) -> None:
        # BL.21702 -- `permitir_accion_unica` llega por PARAMETRO y no leyendo `banderas.py`: este
        # modulo vive en el subpaquete `world_model/` y el builder del notebook solo desmonta
        # imports relativos de UN punto, asi que importar `banderas` desde aca (dos puntos) dejaria
        # el entregable con un ImportError. La palanca la resuelve `policy.py` y la baja hasta aca.
        self._permitir_accion_unica = permitir_accion_unica
        #: Acciones que el juego DECLARA (no las que se observaron todavia). 0 = sin declarar.
        self._vocabulario = 0
        self._por_accion: dict[str, _ContadoresDeAccion] = {}
        self._volatile: list[list[bool]] = []
        # Familia 1 y familia 2 se guardan por separado: comparten el tope y la version, pero cada
        # una tiene su histeresis y mezclarlas haria que una celda que entro por barrido saliera por
        # el umbral de frecuencia (y al reves).
        self._volatil_frecuencia: list[list[bool]] = []
        self._volatil_barrido: list[list[bool]] = []
        self._cambios_totales: list[list[int]] = []
        self._cambios_aislados: list[list[int]] = []
        self._height = 0
        self._width = 0
        self._transiciones = 0
        self._volatile_count = 0
        self._desactivada_por_tope = False
        self._version = 0

    def declarar_vocabulario(self, cantidad_de_acciones: int) -> None:
        """BL.21702 -- cuantas acciones OFRECE el juego. Es lo que habilita el modo de accion
        unica: que solo se haya observado un boton no significa que el juego tenga uno solo."""
        self._vocabulario = max(self._vocabulario, int(cantidad_de_acciones))

    @property
    def modo_de_accion_unica(self) -> bool:
        """El juego declara UN solo boton y la palanca de BL.21702 esta encendida."""
        return self._permitir_accion_unica and self._vocabulario == 1

    def observe(self, action: str, pre: Grid, post: Grid) -> None:
        """Registra una transicion observada `pre -> post` bajo `action`. No muta ni retiene las
        grillas."""
        height = max(len(pre), len(post))
        width = max(
            max((len(row) for row in pre), default=0),
            max((len(row) for row in post), default=0),
        )
        if height == 0 or width == 0:
            return

        self._crecer_hasta(height, width)
        self._transiciones += 1

        contadores = self._contadores_de(action)
        contadores.transiciones += 1
        _crecer_matriz(contadores.cambios, self._height, self._width)

        cambiadas: list[int] = []
        for y in range(self._height):
            fila_pre = pre[y] if y < len(pre) else []
            fila_post = post[y] if y < len(post) else []
            for x in range(self._width):
                # Celda ausente en un lado: se compara contra el centinela -1 (mismo criterio que
                # cell_diff_count), asi que aparecer/desaparecer cuenta como cambio.
                valor_pre = fila_pre[x] if x < len(fila_pre) else -1
                valor_post = fila_post[x] if x < len(fila_post) else -1
                if valor_pre != valor_post:
                    contadores.cambios[y][x] += 1
                    self._cambios_totales[y][x] += 1
                    cambiadas.append(y * self._width + x)

        self._registrar_soledad(cambiadas)
        self._recomputar()

    @property
    def mask(self) -> VolatilityMask | None:
        """Mascara vigente, o None si todavia no hay evidencia suficiente (o si se desactivo por el
        tope de fraccion). None significa "compara todo", el comportamiento previo a este BL."""
        if self._volatile_count == 0 or self._desactivada_por_tope:
            return None
        return self._volatile

    @property
    def version(self) -> int:
        """Cambia cada vez que cambia el conjunto de celdas volatiles. Quien cachee algo derivado de
        la mascara (una firma de estado, por ejemplo) compara esta version para saber que lo
        cacheado dejo de ser comparable."""
        return self._version

    def volatile_cell_count(self) -> int:
        return 0 if self._desactivada_por_tope else self._volatile_count

    def observed_transitions(self) -> int:
        return self._transiciones

    def _contadores_de(self, action: str) -> _ContadoresDeAccion:
        existente = self._por_accion.get(action)
        if existente is not None:
            return existente
        nuevo = _ContadoresDeAccion()
        _crecer_matriz(nuevo.cambios, self._height, self._width)
        self._por_accion[action] = nuevo
        return nuevo

    def _crecer_hasta(self, height: int, width: int) -> None:
        if height <= self._height and width <= self._width:
            return
        self._height = max(self._height, height)
        self._width = max(self._width, width)
        _crecer_matriz_bool(self._volatile, self._height, self._width)
        _crecer_matriz_bool(self._volatil_frecuencia, self._height, self._width)
        _crecer_matriz_bool(self._volatil_barrido, self._height, self._width)
        _crecer_matriz(self._cambios_totales, self._height, self._width)
        _crecer_matriz(self._cambios_aislados, self._height, self._width)
        for contadores in self._por_accion.values():
            _crecer_matriz(contadores.cambios, self._height, self._width)

    def _registrar_soledad(self, cambiadas: list[int]) -> None:
        """Marca cuales de los cambios de ESTA transicion ocurrieron sin compania alrededor. Es la
        unica parte del criterio de barrido que no se puede recalcular despues: depende de que
        cambio JUNTO con que, y eso se pierde al acumular los contadores."""
        if not cambiadas:
            return
        en_diff = set(cambiadas)
        for indice in cambiadas:
            y = indice // self._width
            x = indice % self._width
            solo = True
            for dy in range(-SWEEP_ISOLATION_RADIUS, SWEEP_ISOLATION_RADIUS + 1):
                if not solo:
                    break
                for dx in range(-SWEEP_ISOLATION_RADIUS, SWEEP_ISOLATION_RADIUS + 1):
                    if dy == 0 and dx == 0:
                        continue
                    ny = y + dy
                    nx = x + dx
                    if ny < 0 or nx < 0 or ny >= self._height or nx >= self._width:
                        continue
                    if ny * self._width + nx in en_diff:
                        solo = False
                        break
            if solo:
                self._cambios_aislados[y][x] += 1

    def _recomputar(self) -> None:
        """Reevalua las dos familias contra los contadores acumulados y publica la union."""
        cambio_frecuencia = self._recomputar_por_frecuencia()
        cambio_barrido = self._recomputar_por_barrido()
        if not cambio_frecuencia and not cambio_barrido:
            return

        volatiles = 0
        for y in range(self._height):
            for x in range(self._width):
                es_volatil = self._volatil_frecuencia[y][x] or self._volatil_barrido[y][x]
                self._volatile[y][x] = es_volatil
                if es_volatil:
                    volatiles += 1

        self._volatile_count = volatiles
        tope = self._height * self._width * VOLATILITY_MAX_FRACTION
        self._desactivada_por_tope = volatiles > tope
        self._version += 1

    def _recomputar_por_frecuencia(self) -> bool:
        """Familia 1: celdas que cambian casi siempre bajo TODAS las acciones.

        BL.21702 -- en MODO DE ACCION UNICA alcanza con una accion observada, pero se exigen mas
        transiciones y una regularidad casi total (ver los umbrales `_ACCION_UNICA`): sin un
        segundo boton con el que contrastar, lo unico que separa el HUD del tablero es que el HUD
        cambia SIEMPRE."""
        acciones = list(self._por_accion.values())
        accion_unica = self.modo_de_accion_unica
        minimo_transiciones = (
            VOLATILITY_MIN_TRANSITIONS_ACCION_UNICA if accion_unica else VOLATILITY_MIN_TRANSITIONS
        )
        minimo_acciones = 1 if accion_unica else VOLATILITY_MIN_DISTINCT_ACTIONS
        entrada = VOLATILITY_ENTRY_RATIO_ACCION_UNICA if accion_unica else VOLATILITY_ENTRY_RATIO
        salida = VOLATILITY_EXIT_RATIO_ACCION_UNICA if accion_unica else VOLATILITY_EXIT_RATIO
        if self._transiciones < minimo_transiciones:
            return False
        if len(acciones) < minimo_acciones:
            return False

        cambio = False
        for y in range(self._height):
            for x in range(self._width):
                era_volatil = self._volatil_frecuencia[y][x]
                umbral = salida if era_volatil else entrada
                es_volatil = all(
                    c.transiciones == 0 or c.cambios[y][x] >= c.transiciones * umbral
                    for c in acciones
                )
                if es_volatil != era_volatil:
                    self._volatil_frecuencia[y][x] = es_volatil
                    cambio = True
        return cambio

    def _recomputar_por_barrido(self) -> bool:
        """Familia 2: barras de progreso / contadores de barrido. Ver el encabezado del modulo."""
        # BL.21702 -- el criterio de la familia 2 es de FORMA y de SOLEDAD, no de contraste entre
        # acciones: el minimo de acciones distintas era una salvaguarda redundante que, en los seis
        # juegos publicos de un solo boton, apagaba la unica familia que si podia verles el HUD.
        minimo_acciones = 1 if self.modo_de_accion_unica else VOLATILITY_MIN_DISTINCT_ACTIONS
        if self._transiciones < SWEEP_MIN_TRANSITIONS:
            return False
        if len(self._por_accion) < minimo_acciones:
            return False

        nuevo = [[False] * self._width for _ in range(self._height)]
        for celdas in self._componentes_de_cambio():
            if len(celdas) < SWEEP_MIN_CELLS:
                continue
            if not _es_linea(celdas, self._width):
                continue
            if self._acciones_que_tocaron(celdas) < minimo_acciones:
                continue

            cambios = 0
            aislados = 0
            for indice in celdas:
                cambios += self._cambios_totales[indice // self._width][indice % self._width]
                aislados += self._cambios_aislados[indice // self._width][indice % self._width]
            # Que los cambios ocurran de a UNO es lo que separa una barra de un objeto que se mueve
            # (dos celdas adyacentes por paso) o de un tablero que responde (bloques enteros).
            if aislados < cambios * SWEEP_MIN_ISOLATION_RATIO:
                continue

            ya_enmascarada = any(
                self._volatil_barrido[indice // self._width][indice % self._width]
                for indice in celdas
            )
            umbral = SWEEP_EXIT_RATIO if ya_enmascarada else SWEEP_ENTRY_RATIO
            if cambios < self._transiciones * umbral:
                continue

            for indice in self._celdas_de_la_barra(celdas):
                nuevo[indice // self._width][indice % self._width] = True

        cambio = False
        for y in range(self._height):
            for x in range(self._width):
                if nuevo[y][x] != self._volatil_barrido[y][x]:
                    self._volatil_barrido[y][x] = nuevo[y][x]
                    cambio = True
        return cambio

    def _celdas_de_la_barra(self, celdas: list[int]) -> list[int]:
        """BL.21559 -- celdas a enmascarar por una barra YA reconocida.

        EL PROBLEMA QUE RESUELVE, medido en vivo. La componente crece de a UNA celda por paso (esa
        es la definicion de barra de barrido), asi que enmascarar solo lo ya observado hace que el
        conjunto volatil -- y con el la VERSION de la mascara y toda firma calculada con ella --
        cambie en cada paso durante ~48 pasos, hasta que la barra completa su primera vuelta.
        Medido reproduciendo las cuatro partidas reales con la mascara VIVA (no la final): 50
        versiones de mascara por partida y firmas unicas 78/83 en ar25, 95/100 en ka59, 123/128 en
        dc22 -- practicamente lo mismo que SIN mascara. La mejora que BL.21558 midio era
        RETROSPECTIVA (mascara final aplicada a toda la trayectoria); durante la partida no existia,
        y sin firmas que se repitan la memoria por-estado de `ExplorationPolicy` no puede disparar.

        LA REGLA. Si la barra vive sobre un BORDE del frame se enmascara la linea ENTERA desde que
        se la reconoce, no solo las celdas ya encendidas: las que faltan son las que la barra va a
        encender en los proximos pasos, y adelantarse es lo que vuelve la mascara ESTABLE. Las
        cuatro barras medidas contra la API oficial estan justo ahi (lf52 fila 0, ar25 columna 63,
        ka59 y dc22 fila 63) y ocupan el borde completo, asi que sobre dato real la extension no
        agrega NI UNA celda que la barra no vaya a ocupar igual.

        POR QUE SOLO EN EL BORDE. Extender una linea interior barreria una fila o columna entera del
        TABLERO por las dudas, que es el error que este modulo mas evita. Una barra que no este en
        un borde conserva el comportamiento previo: de a una celda, mas lento pero nunca de mas."""
        primera_y = celdas[0] // self._width
        primera_x = celdas[0] % self._width
        if all(indice // self._width == primera_y for indice in celdas) and primera_y in (
            0,
            self._height - 1,
        ):
            return [primera_y * self._width + x for x in range(self._width)]
        if all(indice % self._width == primera_x for indice in celdas) and primera_x in (
            0,
            self._width - 1,
        ):
            return [y * self._width + primera_x for y in range(self._height)]
        return celdas

    def _componentes_de_cambio(self) -> list[list[int]]:
        """Componentes conexas (8-conectividad) de TODAS las celdas que cambiaron alguna vez.
        Agrupar por region y no por celda sostiene el criterio cuando el tablero roza la barra: una
        interferencia puntual no puede sacar celdas del medio y partirla en pedazos
        irreconocibles."""
        visitada = [[False] * self._width for _ in range(self._height)]
        componentes: list[list[int]] = []
        for y0 in range(self._height):
            for x0 in range(self._width):
                if self._cambios_totales[y0][x0] == 0 or visitada[y0][x0]:
                    continue
                celdas: list[int] = []
                pila = [(y0, x0)]
                visitada[y0][x0] = True
                while pila:
                    y, x = pila.pop()
                    celdas.append(y * self._width + x)
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny = y + dy
                            nx = x + dx
                            if ny < 0 or nx < 0 or ny >= self._height or nx >= self._width:
                                continue
                            if self._cambios_totales[ny][nx] == 0 or visitada[ny][nx]:
                                continue
                            visitada[ny][nx] = True
                            pila.append((ny, nx))
                componentes.append(celdas)
        return componentes

    def _acciones_que_tocaron(self, celdas: list[int]) -> int:
        """Cuantas acciones distintas provocaron al menos un cambio dentro de la componente."""
        acciones = 0
        for contadores in self._por_accion.values():
            if any(
                contadores.cambios[indice // self._width][indice % self._width] > 0
                for indice in celdas
            ):
                acciones += 1
        return acciones


# ============================== arc_agent/world_model/primitive_ops.py ==============================
"""[arc-agi3-kaggle-agent/world_model/primitive_ops] -- tipos del DSL de transformaciones
grilla-a-grilla + ejecucion (apply_step/apply_program) de cada primitivo + serializacion
canonica (program_key). Puerto de arc-agi-runner/src/worldModel/primitiveOps.ts.
Los generadores de candidatos data-driven (propose_*) viven en primitives.py -- separado solo
para respetar el limite de 500 lineas, misma responsabilidad conceptual (el DSL)."""

from dataclasses import dataclass
from typing import Any, Final, TypedDict

# Import relativo en UNA sola linea a proposito: submission/build_notebook.py lo desmonta con
# `^from \.\w* import .+$` (regex de una linea), y la forma con parentesis dejaria los nombres
# sueltos y un `)` colgando dentro del notebook de Kaggle -- SyntaxError en la submission.


class ProgramStep(TypedDict):
    """Un paso del DSL. Es un dict PLANO a proposito: serializa directo al JSON del fixture sin
    capa de conversion, y `json.loads` de un fixture produce el mismo objeto que el codigo
    construye. TypedDict = tipado estatico con cero costo en runtime."""

    name: str
    params: dict[str, Any]

# Composicion de pasos DSL -- ES el campo `program` de una KnownTransition (ver
# transition_memory.py), no un sistema paralelo. Programa vacio = identidad (no-op).
Program = list[ProgramStep]

class TranslateParams(TypedDict):
    dx: int
    dy: int

class ReflectParams(TypedDict):
    # 'horizontal' invierte columnas (espejo izquierda-derecha); 'vertical', filas (arriba-abajo).
    axis: str

class RotateParams(TypedDict):
    quarterTurns: int

class RecolorParams(TypedDict):
    # Color-origen -> color-destino; los colores ausentes quedan sin cambios (identidad). Claves
    # int EN MEMORIA, str al serializar (JS solo admite claves string en objetos).
    mapping: dict[int, int]

class FloodFillParams(TypedDict):
    x: int
    y: int
    to: int

class CropToBBoxParams(TypedDict):
    backgroundColor: int

class ReplicateParams(TypedDict):
    timesX: int
    timesY: int

class ObjectExtractParams(TypedDict, total=False):
    # Color a extraer. Si se OMITE (clave ausente, nunca None): la componente 4-conexa mas grande.
    color: int

OverlayParams = dict[str, Any]  # el TS lo declara Record<string, never>: siempre {}

# `from` es palabra reservada de Python -> forma FUNCIONAL obligatoria. Acceso SIEMPRE por
# subscript: params["from"], nunca por atributo. predicate: 'border' = celdas de `from` que tocan
# el borde de la grilla o un color distinto; 'interior' = el complemento; 'all' = todas.
ConditionalRecolorParams = TypedDict(
    "ConditionalRecolorParams", {"from": int, "to": int, "predicate": str}
)

PROGRAM_STEP_NAMES: Final[tuple[str, ...]] = (
    "translate", "reflect", "rotate", "recolor", "floodFill",
    "cropToBBox", "overlay", "replicate", "objectExtract", "conditionalRecolor",
)

# Orden canonico de claves de params por primitivo -- ES el orden de insercion de los object
# literals del TS, y por lo tanto el orden que emite JSON.stringify. Fija el desempate por clave
# del ranking Occam (ver synthesis.rank_programs).
PARAM_KEY_ORDER: Final[dict[str, tuple[str, ...]]] = {
    "translate": ("dx", "dy"),
    "reflect": ("axis",),
    "rotate": ("quarterTurns",),
    "recolor": ("mapping",),
    "floodFill": ("x", "y", "to"),
    "cropToBBox": ("backgroundColor",),
    "overlay": (),
    "replicate": ("timesX", "timesY"),
    "objectExtract": ("color",),
    "conditionalRecolor": ("from", "to", "predicate"),
}

# Constructores -- existen para que dos implementadores produzcan dicts identicos sin
# coordinarse: misma clave, mismo tipo, `color` omitido cuando corresponde.
def make_translate(dx: int, dy: int) -> ProgramStep:
    return {"name": "translate", "params": {"dx": dx, "dy": dy}}

def make_reflect(axis: str) -> ProgramStep:
    return {"name": "reflect", "params": {"axis": axis}}

def make_rotate(quarter_turns: int) -> ProgramStep:
    return {"name": "rotate", "params": {"quarterTurns": quarter_turns}}

def make_recolor(mapping: dict[int, int]) -> ProgramStep:
    return {"name": "recolor", "params": {"mapping": dict(mapping)}}

def make_flood_fill(x: int, y: int, to: int) -> ProgramStep:
    return {"name": "floodFill", "params": {"x": x, "y": y, "to": to}}

def make_crop_to_bbox(background_color: int) -> ProgramStep:
    return {"name": "cropToBBox", "params": {"backgroundColor": background_color}}

def make_overlay() -> ProgramStep:
    return {"name": "overlay", "params": {}}

def make_replicate(times_x: int, times_y: int) -> ProgramStep:
    return {"name": "replicate", "params": {"timesX": times_x, "timesY": times_y}}

def make_object_extract(color: int | None = None) -> ProgramStep:
    """Sin color, `params` queda VACIO -- nunca {"color": None}: el TS emite
    {"name":"objectExtract","params":{}} y un `null` seria otro JSON, rompiendo el fixture y el
    desempate por clave."""
    if color is None:
        return {"name": "objectExtract", "params": {}}
    return {"name": "objectExtract", "params": {"color": color}}

def make_conditional_recolor(from_color: int, to: int, predicate: str) -> ProgramStep:
    return {
        "name": "conditionalRecolor",
        "params": {"from": from_color, "to": to, "predicate": predicate},
    }

@dataclass(frozen=True)
class PrimitiveContext:
    """Grilla ancla para 'overlay' -- por diseno, el primer frame observado del episodio. Sin
    ancla, 'overlay' degrada a identidad (defensivo). `frozen=True` con un campo Grid mutable es
    intencional: congela la REFERENCIA, no la grilla. El contexto se comparte entre miles de
    nodos de la BFS de synthesis.py; clonarlo seria costo puro. Nadie muta anchor_grid."""

    anchor_grid: Grid | None = None

    def to_dict(self) -> dict[str, Any]:
        # Clave OMITIDA cuando no hay ancla -- replica el drop de `undefined` de JSON.stringify.
        return {} if self.anchor_grid is None else {"anchorGrid": self.anchor_grid}

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "PrimitiveContext":
        return PrimitiveContext(anchor_grid=raw.get("anchorGrid"))

EMPTY_CONTEXT: Final[PrimitiveContext] = PrimitiveContext()

# Colacion raiz de ICU (la que usa String.prototype.localeCompare en Node) restringida al
# alfabeto que produce program_to_json. NO es orden de codepoint: en ASCII '}' (125) va DESPUES
# de los digitos, en ICU la puntuacion va ANTES. La diferencia es observable cuando un literal
# entero es prefijo numerico de otro en la ultima posicion de un objeto ({"color":1} vs
# {"color":15}); usar orden de codepoint invertiria ese par respecto del TS.
_PUNCTUATION_ORDER: Final[str] = '-,:"[]{}'

def _build_collation_rank() -> dict[str, int]:
    rank: dict[str, int] = {char: index for index, char in enumerate(_PUNCTUATION_ORDER)}
    for digit in range(10):
        rank[str(digit)] = len(_PUNCTUATION_ORDER) + digit
    letters_base = len(_PUNCTUATION_ORDER) + 10
    for i in range(26):
        # Rango primario por letra base; desempate terciario: minuscula ANTES de mayuscula.
        rank[chr(ord("a") + i)] = letters_base + 2 * i
        rank[chr(ord("A") + i)] = letters_base + 2 * i + 1
    return rank

_COLLATION_RANK: Final[dict[str, int]] = _build_collation_rank()

def _json_scalar(value: Any) -> str:
    """Strings entre comillas dobles sin escapes (el alfabeto del DSL es ASCII alfabetico puro),
    enteros con str() (negativos como -2, igual que JSON)."""
    if isinstance(value, bool):
        # bool es subclase de int en Python y "True" no es JSON valido: falla ruidosa antes que
        # fixture corrupto (el DSL no tiene booleanos).
        raise ValueError(f"valor booleano no admitido en params del DSL: {value!r}")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return '"' + value + '"'
    raise ValueError(f"valor no serializable en params del DSL: {value!r}")

def _mapping_to_json(mapping: dict[Any, int]) -> str:
    """`mapping` se emite con claves string y ORDENADAS ascendente por valor numerico: asi es
    como JS ordena las claves enteras de un objeto, sin importar el orden de insercion."""
    items = sorted(((int(key), value) for key, value in mapping.items()), key=lambda kv: kv[0])
    return "{" + ",".join('"' + str(k) + '":' + _json_scalar(v) for k, v in items) + "}"

def step_to_json(step: ProgramStep) -> str:
    # .get y no ["name"]: un step malformado (sin la clave) debe fallar con el MISMO ValueError en
    # espanol que un nombre desconocido, no con un KeyError que no dice nada del DSL.
    name = step.get("name")
    key_order = PARAM_KEY_ORDER.get(name)
    if key_order is None:
        raise ValueError(f"paso de DSL desconocido: {name!r}")
    params = step.get("params") or {}
    parts: list[str] = []
    for key in key_order:
        if key not in params:  # `color` de objectExtract: clave ausente, no null
            continue
        value = params[key]
        encoded = _mapping_to_json(value) if key == "mapping" else _json_scalar(value)
        parts.append('"' + key + '":' + encoded)
    return '{"name":"' + name + '","params":{' + ",".join(parts) + "}}"

def program_to_json(program: Program) -> str:
    """Reproduce byte a byte lo que produce JSON.stringify(program) en el TS: sin espacios,
    claves del step en orden name/params y claves de params en el orden de PARAM_KEY_ORDER,
    omitiendo las ausentes."""
    return "[" + ",".join(step_to_json(step) for step in program) + "]"

program_key = program_to_json  # alias publico: MISMO objeto, nunca un segundo serializador

def compare_program_keys(a: str, b: str) -> int:
    """Desempate del TS (`programKey(a).localeCompare(programKey(b))`), que NO es orden de
    codepoint. Devuelve -1 / 0 / 1.
    Por que la aproximacion caracter-a-caracter es exacta aca (ICU compara TODOS los pesos
    primarios antes de los terciarios, asi que en general no lo seria): en la gramatica de este
    DSL no existe ninguna posicion de primera divergencia entre dos claves canonicas donde ambos
    lados sean la misma letra base con distinta caja. Los 10 nombres no son prefijo unos de otros
    y divergen siempre en minusculas (recolor/reflect/replicate divergen en la posicion 2 con
    c/f/p); los valores string son todos minusculas; y las claves de params nunca divergen porque
    dentro de un mismo `name` el orden y los nombres son fijos.
    Solo se valida el caracter de la PRIMERA divergencia: uno fuera de la tabla ahi significa que
    el DSL crecio y la tabla quedo desactualizada, y fallar ruidosamente es la unica forma de que
    un desempate nuevo no se rompa en silencio."""
    for char_a, char_b in zip(a, b):
        if char_a == char_b:
            continue
        rank_a = _COLLATION_RANK.get(char_a)
        rank_b = _COLLATION_RANK.get(char_b)
        if rank_a is None or rank_b is None:
            desconocido = char_a if rank_a is None else char_b
            raise ValueError(
                f"caracter fuera de la tabla de colacion del DSL: {desconocido!r} -- "
                "actualizar _COLLATION_RANK al ampliar el alfabeto"
            )
        return -1 if rank_a < rank_b else 1
    # Prefijo propio: el mas corto va primero (coincide ICU y codepoint).
    if len(a) == len(b):
        return 0
    return -1 if len(a) < len(b) else 1

def _flood_region(grid: Grid, sx: int, sy: int, color: int) -> list[tuple[int, int]]:
    """DFS 4-conexa con PILA EXPLICITA -- nunca recursion: una region de 64x64 desborda el limite
    de recursion de Python. El orden de push (derecha, izquierda, abajo, arriba) + pop() LIFO fija
    el orden de la region resultante, load-bearing para el determinismo de los fixtures.
    `visited` es un set de tuplas donde el TS usa strings "x,y": mismo conjunto de claves, mas
    rapido. La guarda de limites va ANTES de todo acceso a grid[y][x] porque en Python un indice
    negativo NO falla, envuelve por el otro extremo (en TS daria undefined)."""
    h = len(grid)
    w = len(grid[0]) if grid else 0
    visited: set[tuple[int, int]] = set()
    stack: list[tuple[int, int]] = [(sx, sy)]
    region: list[tuple[int, int]] = []
    while stack:
        x, y = stack.pop()
        if (x, y) in visited:
            continue
        if x < 0 or y < 0 or x >= w or y >= h:
            continue
        if grid[y][x] != color:
            continue
        visited.add((x, y))
        region.append((x, y))
        stack.append((x + 1, y))
        stack.append((x - 1, y))
        stack.append((x, y + 1))
        stack.append((x, y - 1))
    return region

def _find_components(
    grid: Grid, background_color: int, only_color: int | None = None
) -> list[list[tuple[int, int]]]:
    """Barrido row-major saltando celdas ya vistas, de fondo y (si only_color no es None) de otro
    color. Devuelve las componentes en ORDEN DE DESCUBRIMIENTO."""
    h = len(grid)
    w = len(grid[0]) if grid else 0
    seen: set[tuple[int, int]] = set()
    components: list[list[tuple[int, int]]] = []
    for y in range(h):
        for x in range(w):
            color = grid[y][x]
            if (x, y) in seen:
                continue
            if color == background_color:
                continue
            if only_color is not None and color != only_color:
                continue
            region = _flood_region(grid, x, y, color)
            for cell in region:
                seen.add(cell)
            components.append(region)
    return components

def _bbox_of_cells(cells: list[tuple[int, int]]) -> BoundingBox:
    if not cells:
        # Nunca ocurre con componentes reales (siempre traen al menos una celda). El TS devuelve
        # centinelas Infinity, que hacen que ningun recorrido posterior itere; el rectangulo
        # degenerado (max < min) tiene ese mismo efecto en Python.
        return BoundingBox(min_x=0, min_y=0, max_x=-1, max_y=-1)
    xs = [cell[0] for cell in cells]
    ys = [cell[1] for cell in cells]
    return BoundingBox(min_x=min(xs), min_y=min(ys), max_x=max(xs), max_y=max(ys))

# Los params se leen con .get y defaults inertes: params invalidos dentro de un primitivo
# CONOCIDO nunca lanzan, degradan a un no-op defensivo -- mismo comportamiento que los
# `undefined` del TS, donde toda comparacion contra undefined es false.

def _apply_translate(params: dict[str, Any], grid: Grid) -> Grid:
    dx = params.get("dx", 0)
    dy = params.get("dy", 0)
    bg = detect_background_color(grid)
    h = len(grid)
    w = len(grid[0]) if grid else 0
    out: Grid = []
    for y in range(h):
        row: list[int] = []
        for x in range(w):
            sx = x - dx
            sy = y - dy
            # Guarda de limites OBLIGATORIA en AMBOS extremos: con sx = -1, grid[y][-1] en Python
            # devuelve la ULTIMA columna (en TS seria undefined) y el translate "envolveria" el
            # contenido en vez de rellenar con fondo -- el bug de port mas probable de este DSL.
            row.append(grid[sy][sx] if 0 <= sy < h and 0 <= sx < w else bg)
        out.append(row)
    return out

def _apply_reflect(params: dict[str, Any], grid: Grid) -> Grid:
    if params.get("axis") == "horizontal":
        return [row[::-1] for row in grid]
    # El TS trata todo lo que no sea 'horizontal' como vertical (no valida el axis): replicado.
    return [row[:] for row in reversed(grid)]

def _rotate90_cw(grid: Grid) -> Grid:
    h = len(grid)
    w = len(grid[0]) if grid else 0
    out: Grid = [[0] * h for _ in range(w)]
    for y in range(h):
        for x in range(w):
            out[x][h - 1 - y] = grid[y][x]
    return out

def _apply_rotate(params: dict[str, Any], grid: Grid) -> Grid:
    quarter_turns = params.get("quarterTurns", 0)
    # Con quarter_turns <= 0 el bucle no corre y queda el clon. El TS devuelve la MISMA
    # referencia; el clon es equivalente en valor y evita aliasing accidental en Python.
    out = clone_grid(grid)
    for _ in range(quarter_turns if quarter_turns > 0 else 0):
        out = _rotate90_cw(out)
    return out

def _apply_recolor(params: dict[str, Any], grid: Grid) -> Grid:
    """BL.20865 -- las claves pueden venir en int O en str, y las dos tienen que funcionar.

    En TypeScript el mapping es `Record<number, number>`, pero las claves de objeto de JavaScript
    son strings por debajo, asi que `mapping[5]` y el JSON `{"5": 3}` son la MISMA cosa y el
    round-trip por JSON es transparente. En Python no: un mapping construido a mano tiene claves
    int y uno deserializado de JSON las tiene str, y `{"5": 3}.get(5)` falla en silencio dejando la
    celda intacta -- el recolor se vuelve un no-op y el agente aprende un modelo de mundo
    equivocado sin que nada explote.

    No es hipotetico: es la via por la que viaja el conocimiento destilado al notebook de Kaggle
    (JSON embebido). Los tests unitarios no lo veian porque construyen el mapping en Python; lo
    caza el fixture de paridad, que cruza el limite JSON de verdad.
    """
    crudo = params.get("mapping") or {}
    mapping: dict[int, int] = {}
    for clave, valor in crudo.items():
        try:
            mapping[int(clave)] = int(valor)
        except (TypeError, ValueError):
            continue  # @no-log-ok: clave no numerica = mapping corrupto, se ignora esa entrada
    return [[mapping.get(cell, cell) for cell in row] for row in grid]

def _apply_flood_fill(params: dict[str, Any], grid: Grid) -> Grid:
    # Defaults -1: una semilla ausente cae fuera de rango y degrada a no-op igual que el
    # undefined del TS, y de paso ningun indice negativo llega a envolver por el otro extremo.
    x = params.get("x", -1)
    y = params.get("y", -1)
    to = params.get("to", 0)
    h = len(grid)
    w = len(grid[0]) if grid else 0
    if y < 0 or y >= h or x < 0 or x >= w:
        return clone_grid(grid)
    from_color = grid[y][x]
    region = _flood_region(grid, x, y, from_color)
    out = clone_grid(grid)
    for rx, ry in region:
        out[ry][rx] = to
    return out

def _apply_crop_to_bbox(params: dict[str, Any], grid: Grid) -> Grid:
    # Default -1: nunca coincide con un color real (0-15), asi que el bbox cubre la grilla entera
    # y el recorte equivale a un clon -- exactamente lo que hace el TS con undefined.
    background_color = params.get("backgroundColor", -1)
    bbox = foreground_bounding_box(grid, background_color)
    if bbox is None:
        return clone_grid(grid)
    return [grid[y][bbox.min_x : bbox.max_x + 1] for y in range(bbox.min_y, bbox.max_y + 1)]

def _apply_overlay(params: dict[str, Any], grid: Grid, ctx: PrimitiveContext) -> Grid:
    anchor = ctx.anchor_grid
    if anchor is None:
        return clone_grid(grid)
    bg = detect_background_color(grid)  # el fondo se calcula sobre `grid`, NO sobre el ancla
    out: Grid = []
    for y, row in enumerate(grid):
        new_row: list[int] = []
        for x, cell in enumerate(row):
            if cell != bg:
                new_row.append(cell)
            elif 0 <= y < len(anchor) and 0 <= x < len(anchor[y]):
                # `anchor[y]?.[x] ?? cell` del TS: el ancla puede ser mas chica que la grilla.
                new_row.append(anchor[y][x])
            else:
                new_row.append(cell)
        out.append(new_row)
    return out

def _apply_replicate(params: dict[str, Any], grid: Grid) -> Grid:
    times_x = params.get("timesX", 0)
    times_y = params.get("timesY", 0)
    h = len(grid)
    w = len(grid[0]) if grid else 0
    out: Grid = []
    # Con h == 0 (o times_* <= 0) el rango es vacio y nunca se divide por cero.
    for y in range(h * times_y):
        out.append([grid[y % h][x % w] for x in range(w * times_x)])
    return out

def _apply_object_extract(params: dict[str, Any], grid: Grid) -> Grid:
    bg = detect_background_color(grid)
    components = _find_components(grid, bg, params.get("color"))
    if not components:
        return clone_grid(grid)
    with_bbox = [(cells, _bbox_of_cells(cells)) for cells in components]
    # Desempate critico: mayor cantidad de celdas primero; a igual cantidad, menor min_y; a igual
    # min_y, menor min_x. sorted() de Python es estable igual que Array.prototype.sort en V8.
    with_bbox.sort(key=lambda item: (-len(item[0]), item[1].min_y, item[1].min_x))
    chosen_cells, bbox = with_bbox[0]
    chosen_set = set(chosen_cells)
    out: Grid = []
    for y in range(bbox.min_y, bbox.max_y + 1):
        row: list[int] = []
        for x in range(bbox.min_x, bbox.max_x + 1):
            # Las celdas del rectangulo que NO pertenecen a la componente se ponen en fondo.
            row.append(grid[y][x] if (x, y) in chosen_set else bg)
        out.append(row)
    return out

def _apply_conditional_recolor(params: dict[str, Any], grid: Grid) -> Grid:
    from_color = params.get("from")
    to = params.get("to", 0)
    predicate = params.get("predicate")
    h = len(grid)
    w = len(grid[0]) if grid else 0
    out = clone_grid(grid)
    for y in range(h):
        for x in range(w):
            if grid[y][x] != from_color:
                continue
            is_border = x == 0 or y == 0 or x == w - 1 or y == h - 1
            if not is_border:
                # Los 4 vecinos ortogonales estan SIEMPRE dentro de rango justamente porque la
                # celda no toca el borde -- por eso no hace falta guarda de limites aca.
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if grid[ny][nx] != from_color:
                        is_border = True
                        break
            should_recolor = (
                predicate == "all"
                or (predicate == "border" and is_border)
                or (predicate == "interior" and not is_border)
            )
            if should_recolor:
                out[y][x] = to
    return out

def apply_step(step: ProgramStep, grid: Grid, ctx: PrimitiveContext | None = None) -> Grid:
    """Ejecuta un unico paso del DSL sobre `grid`. Un primitivo CONOCIDO con params invalidos
    (fuera de rango, sin ancla, etc.) degrada a un no-op defensivo (clon sin cambios); un NOMBRE
    desconocido lanza. El TS cubre el nombre con exhaustividad en compilacion y su rama default
    devolveria basura en runtime: en Python la falla ruidosa es la traduccion honesta."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    name = step.get("name")  # ver step_to_json: sin la clave, ValueError del DSL, no KeyError
    params = step.get("params") or {}
    if name == "translate":
        return _apply_translate(params, grid)
    if name == "reflect":
        return _apply_reflect(params, grid)
    if name == "rotate":
        return _apply_rotate(params, grid)
    if name == "recolor":
        return _apply_recolor(params, grid)
    if name == "floodFill":
        return _apply_flood_fill(params, grid)
    if name == "cropToBBox":
        return _apply_crop_to_bbox(params, grid)
    if name == "overlay":
        return _apply_overlay(params, grid, ctx)
    if name == "replicate":
        return _apply_replicate(params, grid)
    if name == "objectExtract":
        return _apply_object_extract(params, grid)
    if name == "conditionalRecolor":
        return _apply_conditional_recolor(params, grid)
    raise ValueError(f"paso de DSL desconocido: {name!r}")

def apply_program(program: Program, grid: Grid, ctx: PrimitiveContext | None = None) -> Grid:
    """Ejecuta un programa (secuencia de pasos) sobre `grid`. Programa vacio = identidad, pero
    devuelve un CLON, nunca la grilla de entrada."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    acc = clone_grid(grid)
    for step in program:
        acc = apply_step(step, acc, ctx)
    return acc


# ============================== arc_agent/world_model/primitives.py ==============================
"""[arc-agi3-kaggle-agent/world_model/primitives] -- generadores de candidatos DATA-DRIVEN del
DSL a partir de un par (pre, post) observado. Cada propose_* se AUTO-VERIFICA (aplica y compara)
antes de proponerse -- solo devuelve pasos que YA explican el par completo en un solo paso.
enumerate_structural_steps es la contraparte CIEGA (sin `post`) que usa synthesis.py para
componer varios pasos. Puerto de arc-agi-runner/src/worldModel/primitives.ts (BL.20860).

El ORDEN de generacion es load-bearing: synthesis.py rankea los candidatos por prior de Occam con
desempate determinista por clave canonica, y consume esta enumeracion tal cual sale. Cambiar el
orden de un proposer, o el orden en que propose_all_steps los concatena, cambia QUE programa gana
un empate y por lo tanto que modelo de mundo aprende el agente. No reordenar por estetica."""

from typing import Final

# Los imports relativos van UNO POR LINEA a proposito: submission/build_notebook.py los desmonta
# con una regex de una sola linea (`^from \.\w* import .+$`) para aplanar el paquete dentro del
# notebook de Kaggle. Un import multilinea entre parentesis dejaria las lineas del medio sueltas
# y romperia el .ipynb generado.







__all__ = [
    "propose_all_steps",
    "enumerate_structural_steps",
    "apply_step",
    "apply_program",
    "program_key",
    "PrimitiveContext",
    "EMPTY_CONTEXT",
    "Program",
    "ProgramStep",
]

# Desplazamientos que enumera la busqueda ciega. Incluye 0 en cada eje POR SEPARADO para cubrir
# movimientos puramente horizontales o verticales; el par (0, 0) se excluye porque seria un no-op.
_TRANSLATE_DELTAS: Final[tuple[int, ...]] = (-2, -1, 0, 1, 2)
# Factores de tileo de la busqueda ciega. (1, 1) se excluye por la misma razon: es identidad.
_REPLICATE_FACTORS: Final[tuple[int, ...]] = (1, 2, 3)
# Tope duro de tileos por eje al INFERIR replicate de un par observado. Sin el, una grilla de una
# celda "explicaria" cualquier post uniforme con un factor gigante -- coincidencia numerica, no
# una regla de tileo.
_MAX_INFERRED_REPLICATE_FACTOR: Final[int] = 6


def _row_width(grid: Grid) -> int:
    """Ancho segun la fila 0, igual que `grid[0]?.length ?? 0` del TS. Las grillas se asumen
    rectangulares (invariante del world model); grilla vacia y filas vacias dan 0."""
    return len(grid[0]) if grid else 0


def _verifies(step: ProgramStep, pre: Grid, post: Grid, ctx: PrimitiveContext) -> bool:
    """Auto-verificacion: un candidato solo se propone si YA explica el par COMPLETO en un paso.
    Proponer sin verificar ensuciaria la busqueda con hipotesis que despues hay que descartar
    contra todas las observaciones, que es el trabajo caro."""
    return grids_equal(apply_step(step, pre, ctx), post)


def _diff_cells(pre: Grid, post: Grid) -> list[tuple[int, int]] | None:
    """Celdas que cambiaron, en orden ROW-MAJOR (y externo, x interno). Devuelve `None` si las
    grillas no tienen la misma forma -- distinto de `[]` (misma forma, sin cambios): un cambio de
    forma no lo puede explicar ningun primitivo local, mientras que un diff vacio lo explica el
    programa identidad. El orden row-major es load-bearing: la semilla de floodFill es diffs[0]."""
    if len(pre) != len(post):
        return None
    diffs: list[tuple[int, int]] = []
    for y in range(len(pre)):
        row_pre = pre[y]
        row_post = post[y]
        if len(row_pre) != len(row_post):
            return None
        for x in range(len(row_pre)):
            if row_pre[x] != row_post[x]:
                diffs.append((x, y))
    return diffs


def _single_color_diff(pre: Grid, post: Grid) -> tuple[list[tuple[int, int]], int, int] | None:
    """(diffs, color_origen, color_destino) cuando el cambio observado sustituye UN solo color por
    UN solo color. `None` en cualquier otro caso. Es la precondicion compartida de floodFill y
    conditionalRecolor: ambos solo saben expresar un reemplazo mono-color."""
    diffs = _diff_cells(pre, post)
    if not diffs:
        return None
    from_colors = {pre[y][x] for x, y in diffs}
    to_colors = {post[y][x] for x, y in diffs}
    if len(from_colors) != 1 or len(to_colors) != 1:
        return None
    return diffs, next(iter(from_colors)), next(iter(to_colors))


def _flood_region_for_proposal(
    grid: Grid, sx: int, sy: int, color: int
) -> list[tuple[int, int]]:
    """Recalcula la region 4-conexa desde una semilla -- misma logica que el `_flood_region`
    interno de primitive_ops.py, REIMPLEMENTADA aca a proposito (ese helper es privado de aquel
    modulo, no se exporta): permite VERIFICAR que el diff observado es EXACTAMENTE una region
    completa antes de proponer floodFill, en vez de proponer a ciegas y descartar despues.

    Pila explicita, nunca recursion: una region de 64x64 (4096 celdas) desborda el limite de
    recursion de Python."""
    h = len(grid)
    w = _row_width(grid)
    visited: set[tuple[int, int]] = set()
    stack: list[tuple[int, int]] = [(sx, sy)]
    region: list[tuple[int, int]] = []
    while stack:
        x, y = stack.pop()
        if (x, y) in visited:
            continue
        # Las cotas se chequean ANTES de indexar. En JS `grid[-1]` es `undefined` (inofensivo);
        # en Python `grid[-1]` es la ULTIMA fila y la region envolveria la grilla en silencio.
        if x < 0 or y < 0 or x >= w or y >= h:
            continue
        if grid[y][x] != color:
            continue
        visited.add((x, y))
        region.append((x, y))
        stack.append((x + 1, y))
        stack.append((x - 1, y))
        stack.append((x, y + 1))
        stack.append((x, y - 1))
    return region


def _propose_translate(pre: Grid, post: Grid) -> list[ProgramStep]:
    if len(pre) != len(post) or _row_width(pre) != _row_width(post):
        return []
    # El fondo se detecta sobre `pre` y se usa para AMBOS bbox: medir cada grilla con su propio
    # fondo cambiaria el marco de referencia y el desplazamiento dejaria de ser comparable.
    bg = detect_background_color(pre)
    bbox_pre = foreground_bounding_box(pre, bg)
    bbox_post = foreground_bounding_box(post, bg)
    if bbox_pre is None or bbox_post is None:
        return []
    # Ancho/alto medidos como max - min (SIN +1), igual que el TS: solo se comparan entre si para
    # descartar cambios de forma del foreground, nunca se usan como dimension real.
    if (bbox_pre.max_x - bbox_pre.min_x) != (bbox_post.max_x - bbox_post.min_x):
        return []
    if (bbox_pre.max_y - bbox_pre.min_y) != (bbox_post.max_y - bbox_post.min_y):
        return []
    dx = bbox_post.min_x - bbox_pre.min_x
    dy = bbox_post.min_y - bbox_pre.min_y
    if dx == 0 and dy == 0:
        return []
    step = make_translate(dx, dy)
    return [step] if _verifies(step, pre, post, EMPTY_CONTEXT) else []


def _propose_reflect(pre: Grid, post: Grid) -> list[ProgramStep]:
    out: list[ProgramStep] = []
    for axis in ("horizontal", "vertical"):
        step = make_reflect(axis)
        if _verifies(step, pre, post, EMPTY_CONTEXT):
            out.append(step)
    return out


def _propose_rotate(pre: Grid, post: Grid) -> list[ProgramStep]:
    out: list[ProgramStep] = []
    for quarter_turns in (1, 2, 3):
        step = make_rotate(quarter_turns)
        if _verifies(step, pre, post, EMPTY_CONTEXT):
            out.append(step)
    return out


def _propose_recolor(pre: Grid, post: Grid) -> list[ProgramStep]:
    if len(pre) != len(post):
        return []
    mapping: dict[int, int] = {}
    for y in range(len(pre)):
        if len(pre[y]) != len(post[y]):
            return []
        for x in range(len(pre[y])):
            from_color = pre[y][x]
            to_color = post[y][x]
            # Contradiccion: el mismo color de origen apunta a dos destinos distintos, asi que
            # NINGUN recolor global explica el par. Abandonar entero, no quedarse con la mitad.
            if from_color in mapping and mapping[from_color] != to_color:
                return []
            mapping[from_color] = to_color
    # Recorrido ASCENDENTE por color de origen: el TS itera `Object.entries(mapping)`, que para
    # claves enteras devuelve orden numerico ascendente sin importar el orden de insercion. Fijarlo
    # aca mantiene identica la clave canonica del paso y, con ella, el desempate del ranking.
    non_trivial = {color: mapping[color] for color in sorted(mapping) if color != mapping[color]}
    if not non_trivial:
        return []
    # UNICO proposer que no se auto-verifica: el mapping se construyo recorriendo TODAS las celdas,
    # asi que aplicarlo reproduce `post` por construccion (misma excepcion que el TS).
    return [make_recolor(non_trivial)]


def _propose_flood_fill(pre: Grid, post: Grid) -> list[ProgramStep]:
    single = _single_color_diff(pre, post)
    if single is None:
        return []
    diffs, from_color, to_color = single
    # Semilla = primera celda en row-major. Cualquier celda de la region sirve para pintar lo
    # mismo, pero fijar la primera hace la propuesta DETERMINISTA y la clave canonica estable.
    seed_x, seed_y = diffs[0]
    region = _flood_region_for_proposal(pre, seed_x, seed_y, from_color)
    # El diff tiene que ser la region COMPLETA, no una parte ni una union de blobs sueltos: si
    # sobran o faltan celdas, lo que paso no fue un flood fill aunque los colores coincidan.
    if len(region) != len(diffs):
        return []
    region_set = set(region)
    for cell in diffs:
        if cell not in region_set:
            return []
    step = make_flood_fill(seed_x, seed_y, to_color)
    return [step] if _verifies(step, pre, post, EMPTY_CONTEXT) else []


def _propose_crop_to_bbox(pre: Grid, post: Grid) -> list[ProgramStep]:
    step = make_crop_to_bbox(detect_background_color(pre))
    return [step] if _verifies(step, pre, post, EMPTY_CONTEXT) else []


def _propose_overlay(pre: Grid, post: Grid, ctx: PrimitiveContext) -> list[ProgramStep]:
    # Sin ancla el primitivo degrada a identidad: proponerlo seria proponer un no-op disfrazado.
    if ctx.anchor_grid is None:
        return []
    step = make_overlay()
    # Unico proposer que verifica con el `ctx` recibido en vez de EMPTY_CONTEXT: overlay es el
    # unico primitivo cuyo resultado depende del contexto.
    return [step] if _verifies(step, pre, post, ctx) else []


def _propose_replicate(pre: Grid, post: Grid) -> list[ProgramStep]:
    pre_h = len(pre)
    pre_w = _row_width(pre)
    post_h = len(post)
    post_w = _row_width(post)
    if pre_h == 0 or pre_w == 0:
        return []
    if post_h % pre_h != 0 or post_w % pre_w != 0:
        return []
    # Division entera: la divisibilidad ya quedo validada arriba, asi que el cociente es exacto
    # (el `/` de JS produce un entero aca por la misma razon).
    times_y = post_h // pre_h
    times_x = post_w // pre_w
    if times_x == 1 and times_y == 1:
        return []
    if times_x > _MAX_INFERRED_REPLICATE_FACTOR or times_y > _MAX_INFERRED_REPLICATE_FACTOR:
        return []
    step = make_replicate(times_x, times_y)
    return [step] if _verifies(step, pre, post, EMPTY_CONTEXT) else []


def _propose_object_extract(pre: Grid, post: Grid) -> list[ProgramStep]:
    bg = detect_background_color(pre)
    colors: set[int] = set()
    for row in pre:
        for cell in row:
            if cell != bg:
                colors.add(cell)
    # `None` primero (el objeto mas grande, sin fijar color) y despues cada color ASCENDENTE: el
    # candidato mas GENERAL se enumera antes que los especificos, que es exactamente lo que
    # premia el prior de Occam aguas arriba (a igual longitud gana el que hardcodea menos params).
    candidates: list[int | None] = [None]
    candidates.extend(sorted(colors))
    out: list[ProgramStep] = []
    for color in candidates:
        step = make_object_extract(color)
        if _verifies(step, pre, post, EMPTY_CONTEXT):
            out.append(step)
    return out


def _propose_conditional_recolor(pre: Grid, post: Grid) -> list[ProgramStep]:
    single = _single_color_diff(pre, post)
    if single is None:
        return []
    _diffs, from_color, to_color = single
    out: list[ProgramStep] = []
    # Orden "all" -> "border" -> "interior": con una sola observacion los tres predicados pueden
    # coincidir, y el desempate de complejidad aguas arriba penaliza "all" (es redundante con
    # recolor). El orden de enumeracion se mantiene igual al TS para no mover ese empate.
    for predicate in ("all", "border", "interior"):
        step = make_conditional_recolor(from_color, to_color, predicate)
        if _verifies(step, pre, post, EMPTY_CONTEXT):
            out.append(step)
    return out


def propose_all_steps(
    pre: Grid, post: Grid, ctx: PrimitiveContext | None = None
) -> list[ProgramStep]:
    """TODOS los candidatos data-driven de UN solo paso que expliquen `pre -> post`, cada uno ya
    auto-verificado. Se usa como "finisher" en cada nodo de la busqueda de synthesis.py (tanto en
    profundidad 0 como para cerrar la brecha despues de expandir pasos estructurales).

    Pares identicos devuelven `[]`: ese caso lo cubre el programa vacio (identidad), y proponer un
    paso que no cambia nada solo agregaria ruido al ranking."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    if grids_equal(pre, post):
        return []
    steps: list[ProgramStep] = []
    steps.extend(_propose_translate(pre, post))
    steps.extend(_propose_reflect(pre, post))
    steps.extend(_propose_rotate(pre, post))
    steps.extend(_propose_recolor(pre, post))
    steps.extend(_propose_flood_fill(pre, post))
    steps.extend(_propose_crop_to_bbox(pre, post))
    steps.extend(_propose_overlay(pre, post, ctx))
    steps.extend(_propose_replicate(pre, post))
    steps.extend(_propose_object_extract(pre, post))
    steps.extend(_propose_conditional_recolor(pre, post))
    return steps


def enumerate_structural_steps(grid: Grid) -> list[ProgramStep]:
    """Enumeracion CIEGA y acotada de pasos "estructurales" (geometricos, no necesitan el `post`
    final) -- la usa synthesis.py para EXPANDIR la busqueda mas alla de profundidad 1, ya que los
    propose_* data-driven solo pueden inferir params comparando contra el `post` final, que en una
    composicion de 2+ pasos no coincide con el resultado de un paso intermedio.

    Los primitivos "semanticos" (recolor / floodFill / overlay / conditionalRecolor) se excluyen a
    proposito: solo se prueban como finisher data-driven (propose_all_steps), nunca a ciegas --
    su espacio de params es enorme y sin el `post` no hay nada que lo acote.

    Son 39 pasos en orden fijo (24 translate + 2 reflect + 3 rotate + 8 replicate + 1 cropToBBox
    + 1 objectExtract); ese orden fija el orden de expansion de la BFS y, con el, que programa se
    encuentra primero."""
    steps: list[ProgramStep] = []
    for dx in _TRANSLATE_DELTAS:
        for dy in _TRANSLATE_DELTAS:
            if dx == 0 and dy == 0:
                continue
            steps.append(make_translate(dx, dy))
    for axis in ("horizontal", "vertical"):
        steps.append(make_reflect(axis))
    for quarter_turns in (1, 2, 3):
        steps.append(make_rotate(quarter_turns))
    for times_x in _REPLICATE_FACTORS:
        for times_y in _REPLICATE_FACTORS:
            if times_x == 1 and times_y == 1:
                continue
            steps.append(make_replicate(times_x, times_y))
    steps.append(make_crop_to_bbox(detect_background_color(grid)))
    # objectExtract sin color: la variante mas general (el objeto mas grande). Las variantes por
    # color solo tienen sentido con el `post` a la vista, asi que viven en el proposer.
    steps.append(make_object_extract())
    return steps


# ============================== arc_agent/world_model/object_geometry.py ==============================
"""[arc-agi3-kaggle-agent/world_model/object_geometry] BL.21561 -- geometria de objetos sobre una
grilla: agrupacion de celdas cambiadas en clusters, bounding boxes y las dos mediciones que
distinguen "aca se movio un OBJETO" de "aca se recorto un pedazo del fondo".

Puerto de arc-agi-runner/src/worldModel/objectGeometry.ts. Sin estado y sin dependencias fuera de
grid.py.
"""

from typing import Final

# Imports relativos en UNA sola linea a proposito: submission/build_notebook.py los desmonta con
# un regex de una linea y la forma con parentesis dejaria un `)` colgando en el notebook.


# Radio del anillo de contexto con el que se estima el fondo LOCAL alrededor de un cluster. El
# fondo GLOBAL de la grilla no sirve: en dc22-fdcac232 el color mas frecuente del frame es la pared
# del marco (4) y el piso de la arena por el que se mueve el cursor es otro (2).
RADIO_DE_FONDO_LOCAL: Final[int] = 2

Celda = tuple[int, int]


def agrupar_en_clusters(celdas: list[Celda]) -> list[list[Celda]]:
    """Agrupa celdas en clusters 8-conexos. 8 y no 4 a proposito: un objeto que se mueve en
    diagonal deja la region que abandona y la que ocupa tocandose solo por la esquina, y son UN
    evento."""
    pendientes = set(celdas)
    grupos: list[list[Celda]] = []
    for inicio in celdas:
        if inicio not in pendientes:
            continue
        pendientes.discard(inicio)
        pila = [inicio]
        grupo: list[Celda] = []
        while pila:
            y, x = pila.pop()
            grupo.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    vecina = (y + dy, x + dx)
                    if vecina in pendientes:
                        pendientes.discard(vecina)
                        pila.append(vecina)
        grupos.append(grupo)
    return grupos


def caja_de_celdas(celdas: list[Celda]) -> BoundingBox:
    ys = [c[0] for c in celdas]
    xs = [c[1] for c in celdas]
    return BoundingBox(min_x=min(xs), min_y=min(ys), max_x=max(xs), max_y=max(ys))


def cobertura_de_objetos(grid: Grid, caja: BoundingBox, max_tamano_objeto: int) -> float:
    """Fraccion de `caja` ocupada por componentes 4-conexas monocromas ENTERAMENTE contenidas en
    ella y de tamano <= `max_tamano_objeto` -- la definicion operativa de "aca hay un objeto
    acotado". Un cursor da 1.0; un recorte del piso da 0, porque su componente se escapa."""
    alto = len(grid)
    ancho = len(grid[0]) if grid else 0
    visto: set[Celda] = set()
    cubiertas = 0
    for y0 in range(caja.min_y, caja.max_y + 1):
        for x0 in range(caja.min_x, caja.max_x + 1):
            if (y0, x0) in visto:
                continue
            color = grid[y0][x0]
            visto.add((y0, x0))
            pila = [(y0, x0)]
            tamano = 0
            se_escapa = False
            while pila:
                y, x = pila.pop()
                tamano += 1
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if ny < 0 or nx < 0 or ny >= alto or nx >= ancho:
                        continue
                    if grid[ny][nx] != color:
                        continue
                    if ny < caja.min_y or ny > caja.max_y or nx < caja.min_x or nx > caja.max_x:
                        se_escapa = True
                        continue
                    if (ny, nx) in visto:
                        continue
                    visto.add((ny, nx))
                    pila.append((ny, nx))
            if not se_escapa and tamano <= max_tamano_objeto:
                cubiertas += tamano
    area = (caja.max_y - caja.min_y + 1) * (caja.max_x - caja.min_x + 1)
    return cubiertas / area


def fondo_local(grid: Grid, excluidas: list[Celda], caja: BoundingBox) -> int:
    """Color mas frecuente de `grid` en el anillo que rodea a `caja`, IGNORANDO `excluidas` (las
    celdas que cambiaron: son el evento, no el contexto). Empate: el color de menor indice, para
    determinismo bit a bit con el motor TypeScript."""
    fuera = set(excluidas)
    conteo: dict[int, int] = {}
    desde_y = max(0, caja.min_y - RADIO_DE_FONDO_LOCAL)
    hasta_y = min(len(grid) - 1, caja.max_y + RADIO_DE_FONDO_LOCAL)
    for y in range(desde_y, hasta_y + 1):
        desde_x = max(0, caja.min_x - RADIO_DE_FONDO_LOCAL)
        hasta_x = min(len(grid[y]) - 1, caja.max_x + RADIO_DE_FONDO_LOCAL)
        for x in range(desde_x, hasta_x + 1):
            if (y, x) in fuera:
                continue
            conteo[grid[y][x]] = conteo.get(grid[y][x], 0) + 1
    fondo = -1
    mejor = -1
    for color in sorted(conteo):
        if conteo[color] > mejor:
            fondo = color
            mejor = conteo[color]
    return fondo


# ── BL.21853 -- objeto ENTERO: la via que ve al multicelda que se va lejos ─────────────────────

#: Tope de celdas de un OBJETO (no del area de su caja). Es la diferencia que hace a esta via: el
#: analisis por cluster acota el AREA DE LA CAJA (`MAX_TAMANO_OBJETO`, 256) y un objeto de 153
#: celdas repartido en una caja de 17x17=289 ya no entra, aunque el objeto sea chico. Medido sobre
#: las 7.258 transiciones de `arcReplayFrames` (BL.21853): los objetos que esta via recupera miden
#: 53 y 153 celdas, o sea que 256 celdas los cubre a los dos.
MAX_CELDAS_DE_OBJETO_ENTERO: Final[int] = 256

#: Tope de pares (objeto de pre, objeto de post) con la MISMA forma que se prueban antes de
#: rendirse. Guarda de costo para el tablero embaldosado: una grilla con 40 fichas identicas da
#: 1.600 pares y ninguno explica el cambio.
MAX_PARES_DE_OBJETO: Final[int] = 64


def objetos_que_tocan(
    grid: Grid, fondo: int, semillas: list[Celda], max_celdas: int
) -> list[list[Celda]]:
    """Componentes 4-conexas de celdas distintas de `fondo` que contienen alguna celda de
    `semillas`. Color-AGNOSTICO puertas adentro: un avatar de dos colores es UN objeto, no dos.

    NO es la misma nocion de objeto que `cobertura_de_objetos`: aquella exige MONOCROMIA y se ata a
    una caja; esta no hace ninguna de las dos cosas. Son dos definiciones distintas de "objeto"
    conviviendo en el arbol (la tercera es `primitive_ops._find_components`, 4-conexa monocroma,
    que alimenta las features de click) -- esta enumerado a proposito en vez de decir que se reusa
    una sola: BL.21853 lo afirmo de mas y la revision lo midio.

    Descarta la componente que supera `max_celdas` celdas -- eso ya no es un objeto, es el tablero
    -- y la descarta ENTERA: al pasarse el tope sigue recorriendola solo para marcarla como vista,
    porque cortar el recorrido dejaba el resto sin visitar y una semilla posterior lo volvia a
    floodear y emitia un PEDAZO de esa misma componente como si fuera un objeto. Medido (BL.21853,
    revision): corredor 4-conexo de 304 celdas con tope 256, semillas en los dos extremos ->
    devolvia un "objeto" de 47 celdas; con una sola semilla devolvia []. O sea que la salida
    dependia de QUE celdas cambiaron y no solo de la grilla.

    Orden DETERMINISTA (el de `semillas`, que llega en barrido por filas): los dos puertos tienen
    que elegir el mismo candidato cuando hay varios."""
    alto = len(grid)
    ancho = len(grid[0]) if alto else 0
    visto: set[Celda] = set()
    salida: list[list[Celda]] = []
    for (sy, sx) in semillas:
        if (sy, sx) in visto or grid[sy][sx] == fondo:
            continue
        pila = [(sy, sx)]
        visto.add((sy, sx))
        celdas: list[Celda] = []
        excedido = False
        while pila:
            y, x = pila.pop()
            if not excedido:
                celdas.append((y, x))
                if len(celdas) > max_celdas:
                    # Al pasarse el tope se sigue recorriendo SOLO para dejar la componente entera
                    # en `visto`. Sin esto, el remanente no visitado quedaba disponible para una
                    # semilla posterior y salia como objeto propio.
                    excedido = True
                    celdas = []
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if ny < 0 or nx < 0 or ny >= alto or nx >= ancho:
                    continue
                if (ny, nx) in visto or grid[ny][nx] == fondo:
                    continue
                visto.add((ny, nx))
                pila.append((ny, nx))
        if not excedido:
            celdas.sort()
            salida.append(celdas)
    return salida


def forma_con_color(celdas: list[Celda], grid: Grid) -> tuple[frozenset, Celda]:
    """Forma del objeto normalizada a su esquina superior izquierda, con el color de cada celda, y
    esa esquina. Dos objetos con la misma `forma_con_color` son el MISMO objeto en otra posicion."""
    my = min(c[0] for c in celdas)
    mx = min(c[1] for c in celdas)
    return frozenset((y - my, x - mx, grid[y][x]) for y, x in celdas), (my, mx)


def _objeto_explica_el_cambio(
    pre: Grid,
    post: Grid,
    cambios: set[Celda],
    fondo: int,
    objeto: list[Celda],
    dy: int,
    dx: int,
    mask: VolatilityMask | None,
) -> bool:
    """RECONSTRUYE `post` a partir de `pre` moviendo `objeto` por (dy,dx) y exige que quede EXACTO.

    Es lo que separa esta via de un match de formas: en un tablero embaldosado hay decenas de
    objetos con la misma forma y "alguno coincide desplazado" no dice nada. Aca se pide (a) que
    TODA celda cambiada este en el origen o en el destino y (b) que el destino tenga el contenido
    del objeto y el origen desalojado tenga el fondo. La diferencia entre los dos criterios esta
    MEDIDA sobre el corpus: 564 transiciones con el criterio flojo contra 146 con este."""
    alto = len(pre)
    ancho = len(pre[0])
    destino: dict[Celda, int] = {}
    for (y, x) in objeto:
        ny, nx = y + dy, x + dx
        if ny < 0 or nx < 0 or ny >= alto or nx >= ancho:
            return False
        destino[(ny, nx)] = pre[y][x]
    tocadas = set(objeto) | set(destino)
    for celda in cambios:
        if celda not in tocadas:
            return False
    for (y, x) in tocadas:
        if is_volatile_cell(mask, y, x):
            continue
        if post[y][x] != destino.get((y, x), fondo):
            return False
    return True


def traslacion_de_objeto_entero(
    pre: Grid,
    post: Grid,
    cambios: list[Celda],
    fondo: int,
    mask: VolatilityMask | None = None,
    max_celdas: int = MAX_CELDAS_DE_OBJETO_ENTERO,
    max_pares: int = MAX_PARES_DE_OBJETO,
) -> tuple[int, int, list[Celda]] | None:
    """(dy, dx, celdas del objeto) si UN objeto entero se movio y eso explica TODO el cambio.

    POR QUE HACE FALTA (BL.21853, medido sobre 7.258 transiciones reales). El analisis por cluster
    de `object_mechanics` despeja la caja `R` del bbox del cluster, o sea que solo ve al objeto que
    se mueve MENOS que su propio ancho; y acota `R` por AREA (256), que un objeto grande desborda
    aunque tenga pocas celdas. Un objeto que salta lejos deja dos clusters disjuntos y ninguno se
    explica solo. Resultado medido: 146 transiciones (2,01% del corpus) que hoy caen en
    `desconocida` son traslaciones rigidas CARDINALES de objetos de 53 y 153 celdas.

    ALCANCE DE ESE 146, que la revision midio y el enunciado original no decia: las 146 salen de
    DOS juegos de los 27 con transiciones (re86-8af5384d 77, cn04-2fe56bfb 69). Es el mismo
    criterio con el que el BL descarto `rotacion` por venir de un solo juego, asi que lo honesto es
    "medido en dos escenas", no "confirmado sobre el corpus". Se conserva porque es la unica
    informacion NUEVA del paquete y porque su criterio de aceptacion es una reconstruccion exacta;
    no hay evidencia de que generalice a los otros 25 juegos.

    NO reemplaza al analisis por cluster: `object_mechanics` la llama SOLO cuando ese analisis y su
    respaldo fusionado no dieron NINGUNA traslacion (`if not con_traslacion`). Esa guarda no dice
    "la transicion no estaba explicada": un paso cuyo tipo global es `recoloreo`/`aparicion`/
    `desaparicion` entra igual y estructuralmente puede cambiar de respuesta. Lo medido es mas
    chico que eso -- sobre las 7.258 transiciones del corpus las 146 salen las 146 de
    `desconocida` -- y es lo unico que se afirma. La version anterior de esta linea decia "ninguna
    transicion que hoy se explica cambia de respuesta", que es una propiedad universal que el
    codigo no sostiene (RFM-07, corregido en la revision de BL.21853)."""
    if not cambios:
        return None
    conjunto = set(cambios)
    objetos_pre = objetos_que_tocan(pre, fondo, cambios, max_celdas)
    if not objetos_pre:
        return None
    objetos_post = objetos_que_tocan(post, fondo, cambios, max_celdas)
    if not objetos_post:
        return None
    indice: dict[frozenset, list[Celda]] = {}
    for celdas in objetos_post:
        forma, esquina = forma_con_color(celdas, post)
        indice.setdefault(forma, []).append(esquina)
    aceptadas: list[tuple[int, int, int, int, list[Celda]]] = []
    pares = 0
    for celdas in objetos_pre:
        forma, esquina = forma_con_color(celdas, pre)
        for destino in indice.get(forma, ()):
            dy = destino[0] - esquina[0]
            dx = destino[1] - esquina[1]
            if dy == 0 and dx == 0:
                continue
            pares += 1
            if pares > max_pares:
                return None
            if _objeto_explica_el_cambio(pre, post, conjunto, fondo, celdas, dy, dx, mask):
                aceptadas.append((abs(dy) + abs(dx), dy, dx, -len(celdas), celdas))
    if not aceptadas:
        return None
    aceptadas.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
    elegida = aceptadas[0]
    return (elegida[1], elegida[2], elegida[4])


# ============================== arc_agent/world_model/object_mechanics.py ==============================
"""[arc-agi3-kaggle-agent/world_model/object_mechanics] BL.21561 -- analizador de mecanicas
OBJETO-CENTRICO. REEMPLAZA a `propose_all_steps` como el analizador que alimenta
`TransitionMemory.record_observation`: en vez de preguntar "que funcion grilla->grilla explica el
par", pregunta "que le paso a los OBJETOS". Puerto de
arc-agi-runner/src/worldModel/objectMechanics.ts.

POR QUE. Medido sobre 1.569 pasos reales de ARC-AGI-3, el DSL global confirmo regla en 253 pasos y
las 253 son la IDENTIDAD -- cero reglas no triviales. Las causas son estructurales, no de
presupuesto: `propose_translate` usa el bbox GLOBAL del foreground, que las paredes del tablero
fijan; `propose_recolor` exige un mapping color->color consistente en TODA la grilla, y un objeto
que se mueve pide mapear fondo->jugador y jugador->fondo a la vez; flood fill y conditional recolor
exigen UN color origen y UNO destino sobre el diff, y un movimiento tiene dos.

QUE DETECTA (parametrico sobre objetos y deltas, NUNCA sobre game_id):
1. traslacion -- una region acotada se movio (dy,dx) conservando su contenido: cursor/jugador.
2. recoloreo -- un grupo de celdas cambio de color en el lugar: toggle/pintado.
3. aparicion / desaparicion -- un grupo aparecio sobre el fondo o volvio al fondo.
Los detectores 4 (marco/HUD estatico) y 5 (contador monotono) son de EPISODIO: mechanics_memory.py.

BL.21741 -- EL SILENCIO TIENE QUE DECIR POR QUE. Medido sobre el corpus persistido de subidas de
nivel (14 eventos, 8 transiciones distintas, 6 juegos), `firma_de_mecanica` valia "desconocida" en
14 de 14: la percepcion objeto-centrica era ciega EXACTAMENTE en el instante que decide el score, y
las 8 transiciones distintas eran indistinguibles entre si. Dos causas, las dos arregladas aca:
  a) `_mecanica_vacia("desconocida")` se devolvia tanto cuando el analisis miro y no supo nombrar
     como cuando NO MIRO (por el tope de celdas, o por grillas de forma distinta). Ahora esos dos
     casos tienen tipo propio -- `sobreElTope` y `formaIncompatible` -- y el silencio deja de
     leerse como quietud.
  b) la firma global colapsaba a "desconocida" en cuanto los clusters no eran todos del mismo tipo,
     y una subida de nivel es SIEMPRE una mezcla. Para ese caso la firma ahora es COMPUESTA: el
     desglose por tipo de cluster (ver `firma_compuesta`).
Resultado medido tras el cambio: 7 firmas distintas sobre 8 transiciones (antes 1), sin ninguna
firma inestable -- con el caveat de que solo 4 de las 8 transiciones tienen mas de una captura con
que contrastarse (ver `mechanics_signature`).

LO QUE ESTE BL NO PROBO (correccion, con los numeros al lado). El cierre original vendio
"vc33:nivel1 y vc33:nivel2 comparten firma" como la evidencia de que la firma GENERALIZA en vez de
memorizar. Es falso en las dos mitades: (a) la firma que comparten es `compuesta:desconocida=1`, un
solo cluster que el detector NO supo nombrar -- compartir el silencio no es generalizar; (b) son dos
niveles del MISMO juego. De los 28 pares de transiciones, 26 son entre juegos DISTINTOS y NINGUNO
comparte firma. Con 6 juegos salen 6 familias de firma disjuntas, que es compatible con memorizar la
escena de cada mundo. La cuenta honesta: 6 de 8 transiciones con firma propia informativa, 2 con la
firma del silencio, 0 de 26 pares entre juegos con firma compartida. Ver
`mechanics_signature.es_firma_de_silencio`, que existe para que la distincion no se pierda otra vez
en un `startswith`.
"""

from dataclasses import dataclass
from typing import Final






# Area maxima del bbox de un cluster de cambios que se analiza. Por encima, el "objeto" seria medio
# tablero y la hipotesis de traslacion rigida no describe nada.
MAX_AREA_CAJA_DE_CAMBIOS: Final[int] = 4096

# Tope de celdas cambiadas analizadas en una transicion. Por encima, `detectar_mecanica` NO ANALIZA
# y lo dice con un tipo propio (`sobreElTope`), nunca con `desconocida`.
#
# EL NUMERO SALE DE UN EXPERIMENTO (BL.21741), no de ser redondo. 2048 -- la mitad exacta de una
# grilla 64x64 -- venia de BL.21561 sin medicion detras y sin ningun test que lo fijara. Medido con
# `scripts/medir_tope_de_mecanica.py` sobre el corpus persistido (8 transiciones de subida de nivel
# distintas), cuantas quedan con firmas DIFERENTES entre si y cuantas quedan CALLADAS -- con firma
# que no nombra NINGUNA mecanica, contada con `es_firma_de_silencio`:
#   tope 1024 -> 3 firmas distintas | 6 transiciones calladas
#   tope 2048 -> 5 firmas distintas | 4 calladas   <- el corte historico
#   tope 3072 -> 7 firmas distintas | 3 calladas
#   tope 4096 -> 7 firmas distintas | 2 calladas   <- este
# ESTA TABLA NO ES UN COMENTARIO QUE PUEDA DRIFTEAR: la mide `mediciones/BL21741_tope_de_mecanica.json`
# y `test_la_tabla_del_tope_escrita_aca_es_la_medida` la parsea de ESTE texto y la compara. La
# version anterior decia "3072 -> 1 callada" y "4096 -> 0 calladas", numeros producidos por un
# contador de silencio que no veia `compuesta:desconocida=N`.
# POR QUE 4096 Y NO 3072, con la cuenta corregida: empatan en firmas distintas y 4096 calla una
# transicion menos. Ninguno de los dos "salva" a las dos transiciones de vc33: con la grilla entera
# mirada, el detector las MIRA y sigue sin saber nombrarlas (`compuesta:desconocida=1`), o sea que
# el tope ya no es lo que las calla y subirlo mas no compra nada. Efecto colateral honesto: con el
# tope en el area de la grilla, `sobreElTope` es INALCANZABLE en ARC-AGI-3 (harian falta 4097 celdas
# de 4096) -- queda como guard estructural para grillas de otro tamano, no como camino vivo.
# COSTO MEDIDO (272 pares consecutivos del corpus, minimo de 5 repeticiones interleaved, separado
# por CAMINO DE CODIGO): el sobrecosto NO esta repartido. 266 de los 272 pares recorren el mismo
# camino con los dos topes y miden igual (3,72s contra 3,72-3,76s: la diferencia es ruido); los 6
# que cruzan el corte pasan de 0,003s a 0,51-0,72s, o sea 85 ms por par con la maquina tranquila y
# 120 ms con load 30 (dos corridas, misma forma). Amortizado: 1,9-2,8 ms/paso. El paso caro es
# EXACTAMENTE el de la subida de nivel -- +85-120 ms sobre un costo por accion de 0,154-0,202s
# (+40-60%), UNA vez por nivel, contra un presupuesto ENTREGADO de 8,0 h (`reloj_presupuesto.py`;
# las 9 h son el techo duro de Kaggle, no lo que se reparte). La version anterior publicaba
# "mediana 0,001554 -> 0,002938" y "+4 ms por paso": la mediana no puede casi duplicarse porque
# cambiaron 6 de 272 pares -- esa columna era ruido de la maquina, no senal del tope.
MAX_CELDAS_CAMBIADAS: Final[int] = 4096

# `k` del enunciado: tamano maximo (en celdas) de la caja que puede ser un OBJETO. Los cursores de
# los juegos medidos miden 4-27 celdas.
MAX_TAMANO_OBJETO: Final[int] = 256

# Evidencia minima (0-1) para aceptar una hipotesis de traslacion. Se mide de dos formas
# independientes y alcanza con UNA (ver `_traslacion_de_cluster`).
MIN_EVIDENCIA_DE_OBJETO: Final[float] = 0.5

TIPOS_DE_MECANICA: Final[tuple[str, ...]] = (
    "sinCambio",
    "traslacion",
    "recoloreo",
    "aparicion",
    "desaparicion",
    "desconocida",
    # BL.21741 -- los dos casos de "NO MIRE", que hasta este BL se confundian con "mire y no
    # encontre". El silencio del detector se leia como quietud: `caracterizar_completados.py`
    # tenia que mirar un booleano aparte (`sobre_el_tope_de_mecanica`) para saber de cual de los
    # dos silencios se trataba, y ninguna capa aguas abajo lo hacia.
    "sobreElTope",
    "formaIncompatible",
)

# Los tipos que significan "NO MIRE" -- el detector no analizo los clusters, ni bien ni mal.
# FUENTE UNICA (BL.21741) para cualquier consumidor que distinga "no paso nada" de "no se".
TIPOS_DE_NO_MIRE: Final[tuple[str, ...]] = ("sobreElTope", "formaIncompatible")

# El unico tipo cuyo `celdas_cambiadas` NO ES UNA MEDICION sino la ausencia de una.
#
# POR QUE ESTA SEPARADO DE `TIPOS_DE_NO_MIRE` (BL.21741). Los dos tipos de "no mire" no son
# igual de ciegos: `sobreElTope` no analizo los CLUSTERS, pero conto las celdas antes de rendirse
# y ese conteo es exacto -- un consumidor que solo mira el tamano del cambio (la firma
# `cambioDeEscena` de `IncognitaDeMecanica`) sigue teniendo dato bueno y clasificar ahi como
# "desconocida" PERDERIA informacion. `formaIncompatible`, en cambio, sale con `celdas_cambiadas
# == 0` sin haber contado nada, y ese cero es indistinguible del cero legitimo de `sinCambio`:
# los dos consumidores que deciden si una accion es INERTE (`_evento_sin_traslacion` e
# `IncognitaDeMecanica._clasificar`, en direction_beliefs.py) preguntaban `celdas_cambiadas == 0`,
# o sea que "ni pude comparar las grillas" alimentaba la evidencia de que el boton no hace nada
# -- la inferencia OPUESTA a la correcta. Nombrar el tipo en `detectar_mecanica` no alcanzaba si
# aguas abajo nadie lo leia.
TIPO_SIN_MEDICION: Final[str] = "formaIncompatible"

# El tipo de cluster que el detector MIRO y no supo nombrar. Constante y no literal porque la firma
# compuesta lo deletrea DENTRO de la etiqueta (`compuesta:desconocida=1`) y hay consumidores que
# necesitan reconocerlo ahi adentro -- ver `mechanics_signature.es_firma_de_silencio`.
TIPO_SIN_NOMBRAR: Final[str] = "desconocida"


@dataclass(frozen=True)
class Traslacion:
    """La caja `[min_y..min_y+alto-1] x [min_x..min_x+ancho-1]` de `pre` reaparece intacta en
    `post` desplazada (dy,dx). `cobertura` y `relleno` son las dos evidencias de que lo que se
    movio es un objeto y no un recorte del fondo."""

    dy: int
    dx: int
    min_y: int
    min_x: int
    alto: int
    ancho: int
    cobertura: float
    relleno: float


@dataclass(frozen=True)
class CambioDeColor:
    desde: int
    hasta: int
    celdas: int


@dataclass(frozen=True)
class MecanicaDeCluster:
    tipo: str
    celdas: int
    caja: BoundingBox
    traslacion: Traslacion | None
    cambio_de_color: CambioDeColor | None


@dataclass(frozen=True)
class Mecanica:
    tipo: str
    celdas_cambiadas: int
    clusters: list[MecanicaDeCluster]
    traslacion_principal: Traslacion | None
    cambio_de_color_principal: CambioDeColor | None


def _mecanica_vacia(tipo: str, celdas_cambiadas: int) -> Mecanica:
    return Mecanica(
        tipo=tipo,
        celdas_cambiadas=celdas_cambiadas,
        clusters=[],
        traslacion_principal=None,
        cambio_de_color_principal=None,
    )


def _misma_forma(a: Grid, b: Grid) -> bool:
    if len(a) != len(b):
        return False
    for y in range(len(a)):
        if len(a[y]) != len(b[y]):
            return False
    return len(a) > 0 and len(a[0]) > 0


def detectar_mecanica(
    pre: Grid,
    post: Grid,
    mask: VolatilityMask | None = None,
    max_tamano_objeto: int = MAX_TAMANO_OBJETO,
    min_evidencia: float = MIN_EVIDENCIA_DE_OBJETO,
    max_celdas_cambiadas: int | None = None,
) -> Mecanica:
    """Detecta que le paso a los objetos entre `pre` y `post`, ignorando las celdas volatiles
    (BL.21558: la barra de progreso avanza una celda por paso y no es mecanica de tablero). Nunca
    lanza: ante dos grillas que ni siquiera se pueden comparar devuelve `formaIncompatible`, y por
    encima de `MAX_CELDAS_CAMBIADAS` devuelve `sobreElTope` sin analizar (BL.21741). Ninguno de los
    dos es `desconocida`, que significa "mire los clusters y no supe nombrarlos".

    `max_celdas_cambiadas` mueve el tope SOLO en esta llamada: existe para que el experimento del
    tope y el fixture de paridad no tengan que parchear la constante del modulo y restaurarla en un
    `finally` (que es lo que hacia `medir_tope_de_mecanica.py`). None = la constante."""
    if not _misma_forma(pre, post):
        # BL.21741: NO es "desconocida". "Desconocida" significa "mire los clusters y no supe
        # nombrarlos"; esto significa "ni siquiera pude comparar las dos grillas".
        return _mecanica_vacia("formaIncompatible", 0)

    cambios: list[Celda] = []
    for y in range(len(pre)):
        fila = pre[y]
        fila_post = post[y]
        for x in range(len(fila)):
            if fila[x] != fila_post[x] and not is_volatile_cell(mask, y, x):
                cambios.append((y, x))
    if not cambios:
        return _mecanica_vacia("sinCambio", 0)
    tope = MAX_CELDAS_CAMBIADAS if max_celdas_cambiadas is None else max_celdas_cambiadas
    if len(cambios) > tope:
        # BL.21741: tipo PROPIO. Devolver "desconocida" aca hacia que "no mire porque cambio
        # demasiado" fuera indistinguible de "mire y no encontre" -- y como la transicion de nivel
        # es siempre el frame que mas cambia, el detector callaba justo donde se decide el score.
        return _mecanica_vacia("sobreElTope", len(cambios))

    clusters = [
        _clasificar_cluster(pre, post, grupo, max_tamano_objeto, min_evidencia)
        for grupo in agrupar_en_clusters(cambios)
    ]
    con_traslacion = [c for c in clusters if c.traslacion is not None]
    if not con_traslacion and len(clusters) > 1:
        # Un objeto que se mueve MENOS que su propio ancho deja dos regiones cambiadas separadas
        # por la parte que se solapa y no cambio. Son dos clusters y ninguno se explica solo, pero
        # la union si. Respaldo y no primera opcion: fusionar de entrada juntaria eventos
        # independientes, y sobre las partidas reales el analisis por cluster ya resuelve todo.
        fusionado = _clasificar_cluster(pre, post, cambios, max_tamano_objeto, min_evidencia)
        if fusionado.traslacion is not None:
            clusters = [fusionado]
            con_traslacion = [fusionado]

    # BL.21853 -- ULTIMO respaldo: el objeto ENTERO. Las dos vias de arriba despejan la caja `R` del
    # bbox del CLUSTER (solo ven al objeto que se mueve menos que su propio ancho) y la acotan por
    # AREA (256): un objeto de 153 celdas en una caja de 17x17 no entra aunque el objeto sea chico.
    # Medido sobre 7.258 transiciones: 146 (2,01%) son traslaciones rigidas CARDINALES de objetos
    # de 53 y 153 celdas que hoy caen en `desconocida`. Esas 146 salen de DOS juegos de los 27 con
    # transiciones (re86 77, cn04 69): es una medicion en dos escenas, no una propiedad del corpus.
    # Va TERCERA a proposito: si una de las dos vias anteriores ya explico el paso, esta ni se
    # llama. ALCANCE EXACTO de eso, que no es "solo toca `desconocida`": estructuralmente tambien
    # puede reetiquetar un paso cuyo tipo global era `recoloreo`/`aparicion`/`desaparicion`. Sobre
    # el corpus NO paso -- las 146 salen las 146 de `desconocida` -- pero la guarda no lo impide.
    traslacion_entera: Traslacion | None = None
    if not con_traslacion:
        fondo_del_cambio = fondo_local(pre, cambios, caja_de_celdas(cambios))
        entera = traslacion_de_objeto_entero(pre, post, cambios, fondo_del_cambio, mask)
        if entera is not None:
            dy, dx, objeto = entera
            caja_obj = caja_de_celdas(objeto)
            alto_obj = caja_obj.max_y - caja_obj.min_y + 1
            ancho_obj = caja_obj.max_x - caja_obj.min_x + 1
            # `cobertura` y `relleno` NO se miden igual que en `_traslacion_de_cluster`: alla son
            # las dos evidencias que rompen la ambiguedad objeto/hueco, aca esa ambiguedad ya la
            # rompio la RECONSTRUCCION exacta, que es mas fuerte que las dos.
            # `cobertura` es la fraccion de la caja que ocupa el objeto; `relleno` es 1.0 porque la
            # reconstruccion exigio el fondo en cada celda desalojada -- salvo las VOLATILES, que
            # saltea: el 1.0 es exacto solo fuera de la mascara.
            traslacion_entera = Traslacion(
                dy=dy,
                dx=dx,
                min_y=caja_obj.min_y,
                min_x=caja_obj.min_x,
                alto=alto_obj,
                ancho=ancho_obj,
                cobertura=len(objeto) / (alto_obj * ancho_obj),
                relleno=1.0,
            )

    con_traslacion.sort(
        key=lambda c: (
            -(c.traslacion.alto * c.traslacion.ancho),
            c.traslacion.min_y,
            c.traslacion.min_x,
        )
    )

    if con_traslacion or traslacion_entera is not None:
        tipo = "traslacion"
    else:
        tipos = {c.tipo for c in clusters}
        tipo = clusters[0].tipo if len(tipos) == 1 else "desconocida"

    con_color = sorted(
        (c for c in clusters if c.cambio_de_color is not None),
        key=lambda c: -c.cambio_de_color.celdas,
    )

    return Mecanica(
        tipo=tipo,
        celdas_cambiadas=len(cambios),
        clusters=clusters,
        traslacion_principal=(
            con_traslacion[0].traslacion if con_traslacion else traslacion_entera
        ),
        cambio_de_color_principal=con_color[0].cambio_de_color if con_color else None,
    )


def _clasificar_cluster(
    pre: Grid,
    post: Grid,
    grupo: list[Celda],
    max_tamano_objeto: int,
    min_evidencia: float,
) -> MecanicaDeCluster:
    caja = caja_de_celdas(grupo)
    traslacion = _traslacion_de_cluster(
        pre, post, grupo, caja, max_tamano_objeto, min_evidencia
    )
    if traslacion is not None:
        return MecanicaDeCluster(
            tipo="traslacion",
            celdas=len(grupo),
            caja=caja,
            traslacion=traslacion,
            cambio_de_color=None,
        )

    # Sin traslacion: el cluster entero tiene que ser UN solo par (desde -> hasta) para llamarse
    # mecanica. Dos pares distintos son un cambio compuesto que este analizador no pretende
    # nombrar -- decir "desconocida" es informacion; inventar un nombre, no.
    y0, x0 = grupo[0]
    desde = pre[y0][x0]
    hasta = post[y0][x0]
    for y, x in grupo:
        if pre[y][x] != desde or post[y][x] != hasta:
            return MecanicaDeCluster(
                tipo="desconocida",
                celdas=len(grupo),
                caja=caja,
                traslacion=None,
                cambio_de_color=None,
            )

    fondo = fondo_local(pre, grupo, caja)
    if desde == fondo:
        tipo = "aparicion"
    elif hasta == fondo:
        tipo = "desaparicion"
    else:
        tipo = "recoloreo"
    return MecanicaDeCluster(
        tipo=tipo,
        celdas=len(grupo),
        caja=caja,
        traslacion=None,
        cambio_de_color=CambioDeColor(desde=desde, hasta=hasta, celdas=len(grupo)),
    )


def _traslacion_de_cluster(
    pre: Grid,
    post: Grid,
    grupo: list[Celda],
    caja: BoundingBox,
    max_tamano_objeto: int,
    min_evidencia: float,
) -> Traslacion | None:
    """Busca una caja `R` de `pre` y un desplazamiento `d != 0` tales que `post[R+d] == pre[R]` y
    todo cambio del cluster caiga dentro de `R U (R+d)`.

    LA AMBIGUEDAD QUE HAY QUE ROMPER (medida en dato real): cuando un objeto se mueve a un hueco
    vacio, la hipotesis simetrica "el HUECO se movio en sentido contrario" satisface las MISMAS
    ecuaciones y devuelve la direccion INVERTIDA. Se rompe con dos evidencias independientes:
    `cobertura` (fraccion de R ocupada por componentes contenidas en la caja) y `relleno`
    (fraccion de celdas desalojadas que quedaron del color del fondo local). Alcanza con UNA por
    encima del umbral: hay objetos articulados que solo pasan por relleno y tableros con fondo
    texturado que solo pasan por cobertura."""
    alto_caja = caja.max_y - caja.min_y + 1
    ancho_caja = caja.max_x - caja.min_x + 1
    if alto_caja * ancho_caja > MAX_AREA_CAJA_DE_CAMBIOS:
        return None

    alto = len(pre)
    ancho = len(pre[0])
    fondo = fondo_local(pre, grupo, caja)
    candidatas: list[Traslacion] = []

    for dy in range(-(alto_caja - 1), alto_caja):
        for dx in range(-(ancho_caja - 1), ancho_caja):
            if dy == 0 and dx == 0:
                continue
            # `R U (R+d)` tiene exactamente el bbox del cluster, asi que `R` se despeja del bbox y
            # de d sin buscar: el desplazamiento come |dy| filas y |dx| columnas.
            r = BoundingBox(
                min_y=caja.min_y - min(0, dy),
                max_y=caja.max_y - max(0, dy),
                min_x=caja.min_x - min(0, dx),
                max_x=caja.max_x - max(0, dx),
            )
            if r.min_y > r.max_y or r.min_x > r.max_x:
                continue
            if (r.max_y - r.min_y + 1) * (r.max_x - r.min_x + 1) > max_tamano_objeto:
                continue
            if not _contenido_se_movio(pre, post, r, dy, dx, alto, ancho):
                continue
            if not _cambios_dentro_de_la_union(grupo, r, dy, dx):
                continue
            cobertura = cobertura_de_objetos(pre, r, max_tamano_objeto)
            relleno = _relleno_de_fondo(post, r, dy, dx, fondo)
            if cobertura < min_evidencia and relleno < min_evidencia:
                continue
            candidatas.append(
                Traslacion(
                    dy=dy,
                    dx=dx,
                    min_y=r.min_y,
                    min_x=r.min_x,
                    alto=r.max_y - r.min_y + 1,
                    ancho=r.max_x - r.min_x + 1,
                    cobertura=cobertura,
                    relleno=relleno,
                )
            )

    if not candidatas:
        return None
    candidatas.sort(
        key=lambda t: (
            -t.cobertura,
            -t.relleno,
            abs(t.dy) + abs(t.dx),
            t.alto * t.ancho,
            t.dy,
            t.dx,
        )
    )
    return candidatas[0]


def _contenido_se_movio(
    pre: Grid, post: Grid, r: BoundingBox, dy: int, dx: int, alto: int, ancho: int
) -> bool:
    """`post[R+d] == pre[R]` celda a celda, y el movimiento tiene que cambiar ALGO -- si no,
    cualquier region de fondo "se traslada" a otra region de fondo identica."""
    algo_cambio = False
    for y in range(r.min_y, r.max_y + 1):
        for x in range(r.min_x, r.max_x + 1):
            ny = y + dy
            nx = x + dx
            if ny < 0 or nx < 0 or ny >= alto or nx >= ancho:
                return False
            if post[ny][nx] != pre[y][x]:
                return False
            if pre[y][x] != post[y][x]:
                algo_cambio = True
    return algo_cambio


def _cambios_dentro_de_la_union(
    grupo: list[Celda], r: BoundingBox, dy: int, dx: int
) -> bool:
    for y, x in grupo:
        en_r = r.min_y <= y <= r.max_y and r.min_x <= x <= r.max_x
        en_destino = (
            r.min_y + dy <= y <= r.max_y + dy and r.min_x + dx <= x <= r.max_x + dx
        )
        if not en_r and not en_destino:
            return False
    return True


def _relleno_de_fondo(
    post: Grid, r: BoundingBox, dy: int, dx: int, fondo: int
) -> float:
    desalojadas = 0
    con_fondo = 0
    for y in range(r.min_y, r.max_y + 1):
        for x in range(r.min_x, r.max_x + 1):
            en_destino = (
                r.min_y + dy <= y <= r.max_y + dy and r.min_x + dx <= x <= r.max_x + dx
            )
            if en_destino:
                continue
            desalojadas += 1
            if post[y][x] == fondo:
                con_fondo += 1
    return 0.0 if desalojadas == 0 else con_fondo / desalojadas


# ============================== arc_agent/world_model/mechanics_signature.py ==============================
"""[arc-agi3-kaggle-agent/world_model/mechanics_signature] BL.21741 -- la capa de VOCABULARIO de
`object_mechanics`: como se NOMBRA una transicion ya detectada. Puerto de la mitad de firma de
arc-agi-runner/src/worldModel/objectMechanics.ts.

POR QUE VIVE APARTE (BL.21741 correccion). `object_mechanics.py` cruzo el limite de 500 lineas del
repo al agregarsele `es_firma_de_silencio`. El corte no es arbitrario: DETECTAR (que le paso a los
objetos) y NOMBRAR (con que etiqueta se acumula la evidencia) son dos responsabilidades con
consumidores distintos -- `mechanics_memory` acumula por firma, `direction_beliefs` decide por
TIPO. La dependencia va en un solo sentido: este modulo importa de `object_mechanics` y nunca al
reves.

LO QUE LA FIRMA SI SOSTIENE Y LO QUE NO, MEDIDO SOBRE EL CORPUS PERSISTIDO (14 eventos, 8
transiciones distintas, 6 juegos; sha256 86ec7f5ffe39):
  - SI: 7 firmas distintas sobre 8 transiciones. Con la firma anterior a BL.21741 era 1 sola
    ("desconocida" en 14 de 14).
  - CON QUE FUERZA ES "ESTABLE" (corregido): la estabilidad se afirmaba "en los 14 eventos", pero
    solo 4 de las 8 transiciones tienen mas de una captura con que compararse (ft09:nivel1 x2,
    g50t:nivel1 x2, lp85:nivel1 x4, vc33:nivel1 x2); las otras cuatro tienen UNA sola. O sea: 0
    firmas inestables sobre las 4 transiciones que se pueden contrastar, y 4 sin medir. Ademas cada
    firma tiene al menos un componente pegado al borde de su cubo (sc25 recoloreo=9 en el cubo 4-9,
    vc33 desconocida=1 en el cubo exacto "1"), asi que un cluster de mas o de menos -- ruido de
    segmentacion, no cambio de mecanica -- puede moverla: un roll global de control (3,5) sobre pre
    y post cambia la firma en 2 de los 14 eventos.
  - NO: NO hay evidencia de que el vocabulario transfiera entre mundos. De los 28 pares de
    transiciones, 26 son entre juegos DISTINTOS y NINGUNO comparte firma. El unico par que
    comparte (vc33:nivel1 + vc33:nivel2) es del MISMO juego y lo que comparte es
    `compuesta:desconocida=1`: UN cluster que el detector no supo nombrar. Compartir el silencio
    no es generalizar -- es fallar igual. El commit 246fc969fc vendio ese par como "la evidencia de
    que generaliza en vez de memorizar"; la cuenta honesta es 6 de 8 transiciones con firma propia
    informativa, 2 con la firma del silencio, y 0 de 26 pares entre juegos con firma compartida.
`es_firma_de_silencio` existe para que esa distincion no vuelva a perderse en un `startswith`.
"""

from typing import Final



# Prefijo de la firma COMPUESTA. Constante y no literal suelto: lo leen `firma_compuesta`,
# `es_firma_de_silencio` y los scripts de analisis, y una copia desincronizada del literal es
# exactamente como `FIRMAS_DE_SILENCIO` quedo ciega a `compuesta:desconocida=N`.
PREFIJO_DE_FIRMA_COMPUESTA: Final[str] = "compuesta:"

# Cortes de los cubos con que la firma compuesta cuenta clusters. NO son un adorno: con el conteo
# EXACTO, la misma transicion medida dos veces produce firmas distintas (ft09:nivel1 da 3 clusters
# `desconocida` en un evento y 2 en el otro), o sea que memoriza el evento en vez de nombrar la
# transicion; con el conjunto de tipos PELADO (sin conteo), 4 de las 8 transiciones del corpus
# colapsan en la misma etiqueta `aparicion+desaparicion+desconocida+recoloreo` y la firma vuelve a
# no distinguir nada. Los cubos por orden de magnitud son el punto medio MEDIDO entre esos dos
# fracasos: 7 firmas distintas sobre 8 transiciones, estables en los 14 eventos.
CORTES_DE_CUBO: Final[tuple[int, ...]] = (1, 2, 4, 10)


def conteo_de_tipos_de_cluster(mecanica: Mecanica) -> dict[str, int]:
    """Cuantos clusters de cada tipo trae la transicion, ordenado por nombre de tipo.

    FUENTE UNICA de ese desglose (BL.21741): antes lo recontaban por su cuenta el informe de
    completados y el script del tope, con la misma logica escrita dos veces."""
    conteo: dict[str, int] = {}
    for cluster in mecanica.clusters:
        conteo[cluster.tipo] = conteo.get(cluster.tipo, 0) + 1
    return {tipo: conteo[tipo] for tipo in sorted(conteo)}


def _cubo(cantidad: int) -> str:
    """Cubo por orden de magnitud de `cantidad`: "1", "2-3", "4-9", "10+"."""
    for i in range(len(CORTES_DE_CUBO) - 1, -1, -1):
        piso = CORTES_DE_CUBO[i]
        if cantidad >= piso:
            if i + 1 >= len(CORTES_DE_CUBO):
                return f"{piso}+"
            techo = CORTES_DE_CUBO[i + 1] - 1
            return str(piso) if piso == techo else f"{piso}-{techo}"
    return str(cantidad)


def firma_compuesta(mecanica: Mecanica) -> str:
    """Firma de una transicion HETEROGENEA: el desglose por tipo de cluster, con los conteos
    cubeteados por orden de magnitud.

    POR QUE EXISTE (BL.21741, medido). `firma_de_mecanica` colapsaba a "desconocida" en cuanto los
    clusters de cambio no eran todos del mismo tipo -- y las subidas de nivel medidas son SIEMPRE
    mezclas (lp85:nivel1 = 17 apariciones + 9 desconocidas + 4 desapariciones + 1 recoloreo;
    sc25:nivel1 = 9 recoloreos + 3 desapariciones + 2 desconocidas + 1 aparicion). Resultado: la
    firma valia "desconocida" en los 14 eventos del corpus y las 8 transiciones distintas eran
    indistinguibles entre si. "6 desapariciones + 1 recoloreo" distingue un objetivo de otro;
    "desconocida" no distingue nada.

    OJO -- LA ETIQUETA NO GARANTIZA CONTENIDO. `compuesta:desconocida=1` es una firma compuesta
    cuyo unico componente es el silencio, y en el corpus le toca a las dos transiciones de vc33.
    Un consumidor que solo mire el prefijo `compuesta:` la lee como si nombrara algo: para eso esta
    `es_firma_de_silencio`.

    Devuelve "desconocida" si no hay clusters que desglosar: sin desglose no hay firma compuesta
    que dar, y inventar una seria peor que admitir el silencio."""
    conteo = conteo_de_tipos_de_cluster(mecanica)
    if not conteo:
        return TIPO_SIN_NOMBRAR
    partes = ",".join(f"{tipo}={_cubo(cantidad)}" for tipo, cantidad in conteo.items())
    return f"{PREFIJO_DE_FIRMA_COMPUESTA}{partes}"


def firma_de_mecanica(mecanica: Mecanica) -> str:
    """Etiqueta canonica -- la unidad sobre la que mechanics_memory.py acumula evidencia Beta por
    accion. Dos pasos con la misma firma son "la misma mecanica, dos veces"."""
    if mecanica.tipo == "sinCambio":
        return "sinCambio"
    if mecanica.tipo == "traslacion":
        t = mecanica.traslacion_principal
        return f"traslacion:{t.dy},{t.dx}"
    if mecanica.tipo in ("recoloreo", "aparicion", "desaparicion"):
        c = mecanica.cambio_de_color_principal
        if c is None:
            return mecanica.tipo
        return f"{mecanica.tipo}:{c.desde}>{c.hasta}"
    # Los dos silencios de "no mire" se nombran, no se disfrazan de "desconocida" (BL.21741). La
    # lista sale de `TIPOS_DE_NO_MIRE` y no de dos literales repetidos aca: la constante se declara
    # FUENTE UNICA y hasta esta correccion su propio modulo la ignoraba dos lineas mas abajo.
    if mecanica.tipo in TIPOS_DE_NO_MIRE:
        return mecanica.tipo
    return firma_compuesta(mecanica)


def es_firma_de_silencio(firma: str) -> bool:
    """La firma NO NOMBRA NINGUNA mecanica: es el silencio del detector, con cualquiera de sus
    tres deletreos.

    POR QUE EXISTE (correccion de BL.21741, defecto medido). El experimento del tope contaba las
    "transiciones en silencio" con
    `firma.startswith(("sobreElTope", "formaIncompatible", "desconocida"))`, y
    `"compuesta:desconocida=1".startswith(...)` es False. Con esa ceguera la tabla imprimia "0
    transiciones calladas" con el tope en 4096 cuando en realidad hay DOS (vc33:nivel1 y
    vc33:nivel2), y ese "0" era el unico argumento que separaba 4096 de 3072. Aguas abajo pasaba lo
    mismo: `MECANICAS_DE_OBJETO_UNICA` excluye todo `compuesta:` en bloque, asi que
    `compuesta:desconocida=1` (nada nombrado) y
    `compuesta:aparicion=10+,desaparicion=4-9,desconocida=4-9,recoloreo=1` (cuatro tipos nombrados)
    se leian igual -- justo la distincion que BL.21741 dice haber comprado.

    Los tres deletreos del silencio:
      1. los dos tipos de NO MIRE (`sobreElTope`, `formaIncompatible`);
      2. `desconocida` pelada (mire y no supe nombrar, sin clusters que desglosar);
      3. una firma compuesta cuyos componentes son TODOS `desconocida`.
    Una compuesta con al menos un tipo nombrado NO es silencio, aunque tambien traiga desconocidas:
    "9 recoloreos + 2 desconocidas" dice algo."""
    if firma in TIPOS_DE_NO_MIRE or firma == TIPO_SIN_NOMBRAR:
        return True
    if not firma.startswith(PREFIJO_DE_FIRMA_COMPUESTA):
        return False
    componentes = [
        parte for parte in firma[len(PREFIJO_DE_FIRMA_COMPUESTA) :].split(",") if parte
    ]
    if not componentes:
        return True
    return all(parte.split("=")[0] == TIPO_SIN_NOMBRAR for parte in componentes)


# SIN `__all__` a proposito: en el entregable plano (`agent/my_agent.py`) todos los modulos
# comparten UN namespace, y un segundo `__all__` top-level pisaria al de `primitives.py` en
# silencio. Lo verifica `tests/test_build_agent.py::test_ningun_nombre_top_level_se_repite...`.
# La superficie publica la declara el barrel `world_model/__init__.py`.


# ============================== arc_agent/world_model/regiones_de_cambio.py ==============================
"""[arc-agi3-kaggle-agent/world_model/regiones_de_cambio] BL.21704 -- historial de cambios por
celda y agrupacion en REGIONES POR FIRMA DE CO-CAMBIO. Es la capa de percepcion sobre la que
`relaciones_no_locales.py` mina la causa a distancia (boton que abre puerta).

POR QUE ESTA GRANULARIDAD Y NO OTRA -- SALE DE UNA MEDICION, NO DE UNA OPINION. La etapa 1 de
BL.21704 corrio sobre 5.490 frames reales (103 partidas, 20 de los 25 juegos publicos) y midio las
tres granularidades posibles:

  * CELDA (la que proponia el brief): 4.513.968 pares con al menos una co-ocurrencia, 757.920 con
    soporte >= 5, y 518.658 sobreviven a Benjamini-Hochberg. Medio millon de "relaciones causales"
    no es un vocabulario, es ruido con formato: las celdas de un mismo objeto co-cambian
    perfectamente y el nulo de independencia por celda es falso por construccion. DESCARTADA.
  * COMPONENTE 8-CONEXA de la mascara activa acumulada: colapsa. Da 1 a 4 regiones por juego
    (ar25 UNA sola region de 1.664 celdas, cn04 dos con una de 2.286) y deja 5 de 20 juegos con
    CERO pares testeables. DESCARTADA.
  * FIRMA DE CO-CAMBIO (esta): agrupar las celdas activas por el CONJUNTO EXACTO de pasos en que
    cambiaron, y fusionar grupos con Jaccard >= 0,9. Da 32 a 253 regiones por juego, de 2 a 25
    celdas. Deduplica la redundancia intra-objeto que hace explotar el nivel celda y no colapsa
    como la adyacencia espacial. ELEGIDA.

EL PRE-FILTRO DE PASOS MASIVOS NO ES COSMETICA. Descartar las celdas que nunca cambian era lo unico
que el brief pedia; medido, lo que domina el ruido es OTRA cosa: un paso que cambia mas del 25% de
la grilla (RESET, transicion de nivel) hace co-ocurrir todo con todo y genera una clique gigante de
co-ocurrencia falsa. Fue el confound DOMINANTE en lp85 (49.883 pares espurios a nivel celda). Un
paso masivo no se registra: no aporta ni marginales ni co-ocurrencias.

EL AREA ACTIVA ES UN PISO, NO UNA CONSTANTE. El brief afirmaba "56 a 684 celdas activas por juego"
con >80% de grilla estatica en todos. Medido sobre el corpus completo (150-751 pasos por partida en
vez de los 20-45 de la sonda de BL.21590) el rango real es 64 a 2.318 (mediana 736), y CRECE con
los pasos observados: cn04 queda 56,6% activa, vc33 45,8%, bp35 42,3%. Por eso el modulo acota el
costo con `MAX_REGIONES` y con la ventana deslizante de `MAX_PASOS_RETENIDOS`, en vez de confiar en
que el pre-filtro de estaticas alcance.

Sin estado global, sin red y solo stdlib -- viaja al entregable de Kaggle.
"""

from dataclasses import dataclass
from typing import Final, Sequence

# Imports relativos en UNA sola linea a proposito: submission/build_agent.py los desmonta con el
# regex `^from \.\w* import .+$` y la forma con parentesis dejaria un `)` colgando en el entregable.




#: Fraccion de la grilla por encima de la cual un paso se considera MASIVO y NO se registra. 0,25
#: es el corte medido: RESET y transiciones de nivel quedan afuera, y ningun evento de mecanica
#: local del corpus (cursor, toggle, aparicion) se acerca a ese volumen.
FRACCION_DE_PASO_MASIVO: Final[float] = 0.25

#: Similitud de Jaccard entre dos firmas de co-cambio a partir de la cual los dos grupos de celdas
#: se consideran la MISMA region. 0,9 y no 1,0 porque un objeto real pierde o gana una celda suelta
#: por oclusion en algunos pasos; 0,9 y no menos porque por debajo empiezan a fusionarse regiones
#: que solo comparten los pasos en que el tablero entero se movio.
JACCARD_DE_FUSION: Final[float] = 0.9

#: Tope de regiones retenidas por partida. El maximo MEDIDO fue 253 (cn04); 300 deja margen y a la
#: vez acota el enumerado de pares, que es cuadratico. Por encima se conservan las regiones con mas
#: celdas: las chicas son las que mas se parecen a ruido de una celda suelta.
MAX_REGIONES: Final[int] = 300

#: Separacion de Chebyshev minima entre los bounding boxes de dos regiones para llamar NO LOCAL a
#: su co-ocurrencia. La distancia SOLA no alcanza -- medido, sk48 genero 20.856 pares lag-1 con
#: traslaciones perfectamente legitimas -- por eso es condicion NECESARIA y no suficiente, y la
#: exclusion por detectores locales de `relaciones_no_locales.py` es obligatoria ademas de esta.
SEPARACION_CHEBYSHEV_MINIMA: Final[int] = 8

#: Cotas de COSTO de la agrupacion, no de estadistica. `MAX_PARTES_POR_FIRMA` acota en cuantos
#: pedazos no locales se puede partir UNA firma, y `MAX_GRUPOS_A_FUSIONAR` cuantos pedazos entran a
#: la fusion por Jaccard, que es cuadratica. Los dos conservan los grupos con MAS celdas: en un area
#: activa de 2.318 celdas (el maximo medido, cn04) sin estas cotas la pasada deja de ser barata, y
#: lo que se pierde son grupos de una o dos celdas sueltas -- el material del que esta hecho el
#: ruido. Sobre-fragmentar o descartar grupos chicos solo puede QUITAR sensibilidad, nunca inventar
#: un par: es el lado correcto en el que fallar.
MAX_PARTES_POR_FIRMA: Final[int] = 64
MAX_GRUPOS_A_FUSIONAR: Final[int] = 400

#: Pasos retenidos en la ventana. 751 fue la partida mas larga del corpus; 1200 la cubre entera con
#: margen y acota el ancho de los enteros que hacen de mascara de pasos. Al llegar al tope se podan
#: los `PASOS_PODADOS` mas viejos en vez de dejar de aprender: una relacion que aparece recien en
#: el paso 1.300 es exactamente la que un agente que ya exploro tiene que poder ver.
MAX_PASOS_RETENIDOS: Final[int] = 1200
PASOS_PODADOS: Final[int] = 400


@dataclass(frozen=True)
class RegionDeCambio:
    """Un grupo de celdas que cambian JUNTAS. `firma` es la mascara de bits de los pasos en que la
    region cambio (bit i = paso i de la ventana) y `pasos` su popcount -- el marginal que el nulo
    de `relaciones_no_locales.py` conserva."""

    id: int
    celdas: tuple[Celda, ...]
    caja: BoundingBox
    firma: int
    pasos: int


@dataclass(frozen=True)
class PasoObservado:
    """Lo que hace falta recordar de un paso REGISTRADO: que accion lo produjo, DONDE (si la accion
    lleva coordenada) y que cajas del tablero quedan explicadas por los detectores LOCALES de
    `object_mechanics.py`.

    LA COORDENADA NO ES UN EXTRA. Una accion de click no se repite repitiendo su nombre: el mismo
    ACTION6 en otra celda es otra intervencion. Sin este campo, la confirmacion activa de una
    relacion disparada por clicks esta condenada a fallar siempre -- medido en vivo sobre lp85, con
    las 8 relaciones retenidas refutadas en su primera repeticion por ese motivo y no porque fueran
    falsas. El modulo no sabe QUE accion lleva coordenada (eso es vocabulario del wire): sabe que
    algunas la traen y que esas solo se pueden repetir con ella."""

    accion: str
    cajas_locales: tuple[BoundingBox, ...]
    coordenada: tuple[int, int] | None = None


def _union_de_cajas(a: BoundingBox, b: BoundingBox) -> BoundingBox:
    return BoundingBox(
        min_x=min(a.min_x, b.min_x),
        min_y=min(a.min_y, b.min_y),
        max_x=max(a.max_x, b.max_x),
        max_y=max(a.max_y, b.max_y),
    )


def cajas_explicadas_por_locales(mecanica: Mecanica | None) -> tuple[BoundingBox, ...]:
    """Cajas del tablero cuyo cambio YA tiene nombre en el vocabulario local.

    Son dos familias, y la segunda es la que importa para el control negativo del objeto que se
    traslada: (1) la caja de cada cluster de cambios, y (2) la UNION de la caja ORIGEN y la caja
    DESTINO de cada traslacion detectada. Un objeto que se mueve deja dos regiones cambiadas lejos
    entre si -- la que abandona y la que ocupa -- y sin la union esa traslacion se leeria como una
    relacion causal a distancia entre su celda vieja y la nueva."""
    if mecanica is None:
        return ()
    cajas: list[BoundingBox] = []
    for cluster in mecanica.clusters:
        if _puede_contener_un_par_no_local(cluster.caja):
            # PODA EXACTA, no heuristica: una caja que mide menos de
            # SEPARACION_CHEBYSHEV_MINIMA en los dos ejes no puede contener dos regiones separadas
            # por ese hueco, asi que guardarla solo agrega trabajo al filtro que la consulta. Los
            # clusters chicos -- que son casi todos -- salen aca.
            cajas.append(cluster.caja)
        traslacion = cluster.traslacion
        if traslacion is None:
            continue
        origen = BoundingBox(
            min_x=traslacion.min_x,
            min_y=traslacion.min_y,
            max_x=traslacion.min_x + traslacion.ancho - 1,
            max_y=traslacion.min_y + traslacion.alto - 1,
        )
        destino = BoundingBox(
            min_x=origen.min_x + traslacion.dx,
            min_y=origen.min_y + traslacion.dy,
            max_x=origen.max_x + traslacion.dx,
            max_y=origen.max_y + traslacion.dy,
        )
        cajas.append(_union_de_cajas(origen, destino))
    return tuple(cajas)


def _puede_contener_un_par_no_local(caja: BoundingBox) -> bool:
    ancho = caja.max_x - caja.min_x
    alto = caja.max_y - caja.min_y
    return max(ancho, alto) - SEPARACION_CHEBYSHEV_MINIMA >= 0


def _contenida(interior: BoundingBox, exterior: BoundingBox) -> bool:
    return (
        interior.min_x >= exterior.min_x
        and interior.max_x <= exterior.max_x
        and interior.min_y >= exterior.min_y
        and interior.max_y <= exterior.max_y
    )


def separacion_chebyshev(a: BoundingBox, b: BoundingBox) -> int:
    """Distancia de Chebyshev entre dos cajas (0 si se tocan o se solapan)."""
    hueco_y = max(0, a.min_y - b.max_y, b.min_y - a.max_y)
    hueco_x = max(0, a.min_x - b.max_x, b.min_x - a.max_x)
    return max(hueco_y, hueco_x)


def _separar_por_localidad(celdas: list[Celda]) -> list[list[Celda]]:
    """Parte un grupo de celdas en sub-grupos que NO estan separados por un hueco no local.

    Se apoya en la MISMA segmentacion 8-conexa que usa el vocabulario local
    (`agrupar_en_clusters`) y despues vuelve a unir los clusters que quedaron a menos de
    `SEPARACION_CHEBYSHEV_MINIMA`: un objeto real se fragmenta en varios clusters por un hueco de
    dos celdas y partirlo ahi seria inventar regiones. Lo que nunca se une es lo que esta lejos."""
    clusters = agrupar_en_clusters(celdas)
    if len(clusters) <= 1:
        return clusters
    # Los mas grandes primero (y por posicion ante empate, para que sea determinista): son los que
    # absorben a los chicos. Si una firma se dispersa en mas de `MAX_PARTES_POR_FIRMA` pedazos, se
    # conservan los mayores -- un enjambre de celdas sueltas con la misma firma es ruido, y ademas
    # es el unico caso donde esta pasada dejaria de ser barata.
    clusters.sort(key=lambda c: (-len(c), min(c)))
    del clusters[MAX_PARTES_POR_FIRMA:]
    partes: list[list[Celda]] = []
    cajas: list[BoundingBox] = []
    for cluster in clusters:
        caja = caja_de_celdas(cluster)
        for i, otra in enumerate(cajas):
            if separacion_chebyshev(caja, otra) < SEPARACION_CHEBYSHEV_MINIMA:
                partes[i].extend(cluster)
                cajas[i] = _union_de_cajas(otra, caja)
                break
        else:
            partes.append(list(cluster))
            cajas.append(caja)
    return partes


def particionar_pares(
    regiones: Sequence[RegionDeCambio],
) -> tuple[list[tuple[int, int]], list[list[int]]]:
    """Un SOLO recorrido de los pares de regiones que devuelve las dos particiones a la vez: los
    pares NO LOCALES (el denominador honesto de la multiplicidad) y la lista de adyacencia de los
    CERCANOS (el grafo sobre el que se decide si dos regiones lejanas estan unidas por una cadena
    de cambios). Son complementarios por definicion, y con 300 regiones el doble bucle es 45.000
    comparaciones: hacerlo dos veces era pagar el mismo precio dos veces."""
    pares: list[tuple[int, int]] = []
    adyacencia: list[list[int]] = [[] for _ in regiones]
    for i in range(len(regiones)):
        caja_i = regiones[i].caja
        for j in range(i + 1, len(regiones)):
            if separacion_chebyshev(caja_i, regiones[j].caja) - SEPARACION_CHEBYSHEV_MINIMA >= 0:
                pares.append((i, j))
            else:
                adyacencia[i].append(j)
                adyacencia[j].append(i)
    return pares, adyacencia


def regiones_contiguas(regiones: Sequence[RegionDeCambio]) -> list[list[int]]:
    """Solo la adyacencia de `particionar_pares`. Se conserva por claridad de lectura."""
    return particionar_pares(regiones)[1]


def componentes_por_paso(
    regiones: Sequence[RegionDeCambio], adyacencia: list[list[int]], pasos: int
) -> list[dict[int, int]]:
    """Para cada paso, en que COMPONENTE DE CAMBIO CONTIGUO cayo cada region activa.

    POR QUE ESTO ES NECESARIO Y NO UN LUJO. Medido en vivo sobre lp85 (200 acciones, harness real),
    las 8 relaciones que el detector confirmaba eran pares de celdas de la MISMA fila (fila 26,
    x = 17, 20, 23, 26, ..., separadas de a 3) disparadas por el MISMO click: una franja contigua
    que se repinta entera. Pasaban la no localidad porque dos celdas de esa franja separadas por 9
    columnas superan el Chebyshev >= 8, y pasaban la confirmacion intervencional porque repetir el
    click vuelve a repintar la franja -- una tautologia, no una causa a distancia. La distancia
    entre los EXTREMOS no distingue una causa a distancia de una franja larga; lo que la distingue
    es el HUECO: en un boton que abre una puerta no hay nada que cambie en el medio, y en una
    franja que se repinta hay cambios cada 3 celdas todo a lo largo.

    Dos regiones activas en el mismo paso caen en la misma componente si existe una cadena de
    regiones activas ESE PASO donde cada eslabon esta a menos de `SEPARACION_CHEBYSHEV_MINIMA` del
    siguiente. La componente se calcula UNA vez por paso y no por candidato: el costo es lineal en
    las activaciones, no cuadratico en los pares."""
    activas_por_paso: list[list[int]] = [[] for _ in range(pasos)]
    for indice, region in enumerate(regiones):
        pendiente = region.firma
        while pendiente:
            bit = pendiente & -pendiente
            paso = bit.bit_length() - 1
            if paso < pasos:
                activas_por_paso[paso].append(indice)
            pendiente ^= bit

    salida: list[dict[int, int]] = []
    for activas in activas_por_paso:
        en_paso = set(activas)
        componente: dict[int, int] = {}
        siguiente = 0
        for raiz in activas:
            if raiz in componente:
                continue
            componente[raiz] = siguiente
            pila = [raiz]
            while pila:
                actual = pila.pop()
                for vecino in adyacencia[actual]:
                    if vecino in en_paso and vecino not in componente:
                        componente[vecino] = siguiente
                        pila.append(vecino)
            siguiente += 1
        salida.append(componente)
    return salida


class HistorialDeCambios:
    """Acumula, paso a paso, QUE celdas cambiaron y BAJO QUE ACCION. Una instancia por partida.

    No decide nada: es el sustrato del que `relaciones_no_locales.py` saca regiones, marginales y
    co-ocurrencias. Se mantiene aparte a proposito -- la mineria se recalcula cada tantos pasos y
    la observacion tiene que ser barata en TODOS los pasos."""

    def __init__(self) -> None:
        self._alto = 0
        self._ancho = 0
        self._cambios_por_celda: dict[Celda, int] = {}
        self._pasos: list[PasoObservado] = []
        self._descartados_por_masivos = 0
        self._descartados_por_forma = 0
        self._reinicios_por_forma = 0

    @property
    def pasos(self) -> int:
        """Pasos REGISTRADOS en la ventana (los masivos no cuentan: no ocurrieron para el conteo)."""
        return len(self._pasos)

    @property
    def descartados_por_masivos(self) -> int:
        return self._descartados_por_masivos

    @property
    def descartados_por_forma(self) -> int:
        """Transiciones descartadas porque `pre` y `post` no son comparables entre si. Se expone
        para que el diagnostico pueda distinguir un cero por AUSENCIA DE SENAL de un cero por
        transiciones que nunca entraron -- un cero por bug y un cero honesto se leian igual."""
        return self._descartados_por_forma

    @property
    def reinicios_por_forma(self) -> int:
        """Veces que la grilla cambio de tamano y el historial se reinicio (tipicamente, un cambio
        de NIVEL). Ver `observar`: antes de BL.21704-v2 el primer cambio de tamano dejaba el
        detector MUERTO por el resto de la partida."""
        return self._reinicios_por_forma

    @property
    def celdas_activas(self) -> int:
        return len(self._cambios_por_celda)

    def accion_de(self, paso: int) -> str:
        return self._pasos[paso].accion

    def coordenada_de(self, paso: int) -> tuple[int, int] | None:
        return self._pasos[paso].coordenada

    def observar(
        self,
        accion: str,
        pre: Sequence[Sequence[int]] | Grid,
        post: Sequence[Sequence[int]] | Grid,
        mecanica: Mecanica | None = None,
        mask: VolatilityMask | None = None,
        coordenada: tuple[int, int] | None = None,
    ) -> bool:
        """Registra la transicion `pre -> post` producida por `accion` (en `coordenada`, si la
        accion lleva uno).

        Devuelve True si el paso quedo REGISTRADO y False si se descarto (grillas incomparables o
        paso masivo). `mecanica` se recibe ya calculada porque la politica la computa una vez por
        paso para el modelo de mundo y correr `detectar_mecanica` de nuevo seria un SEGUNDO
        detector sobre la misma transicion; si no llega, se calcula aca con el detector REAL --
        nunca con una aproximacion propia."""
        alto = len(pre)
        if alto == 0 or len(post) != alto or len(pre[0]) != len(post[0]):
            self._descartados_por_forma += 1
            return False
        ancho = len(pre[0])
        if self._alto and (alto != self._alto or ancho != self._ancho):
            # LA GRILLA CAMBIO DE TAMANO: es OTRO TABLERO, tipicamente un cambio de NIVEL. Las
            # firmas de co-cambio acumuladas hablan de coordenadas que ya no existen, asi que se
            # reinicia el historial y se sigue aprendiendo sobre el tablero nuevo.
            #
            # ANTES ESTO MATABA AL DETECTOR. La version anterior hacia `return False` sin tocar
            # `self._alto`, de modo que las dimensiones quedaban latcheadas en las del PRIMER paso
            # y TODOS los pasos posteriores al cambio de tamano se descartaban: el almacen no
            # volvia a minar, ni a confirmar, ni a refutar. Y como el objetivo del BL es subir de
            # NIVEL -- el evento que justamente cambia el tablero --, el detector se apagaba
            # exactamente en la mitad de la partida donde la senal importaba. Medido en vivo sobre
            # lp85: 160 pasos registrados de ~199 ofrecidos, con las ~38 restantes desaparecidas
            # por esta via y sin ninguna traza en el diagnostico.
            self._reinicios_por_forma += 1
            self._cambios_por_celda = {}
            self._pasos = []
        self._alto, self._ancho = alto, ancho

        cambios: list[Celda] = []
        tope = int(FRACCION_DE_PASO_MASIVO * alto * ancho)
        for y in range(alto):
            fila_pre = pre[y]
            fila_post = post[y]
            for x in range(ancho):
                if fila_pre[x] != fila_post[x] and not is_volatile_cell(mask, y, x):
                    cambios.append((y, x))
            if len(cambios) > tope:
                # Corte temprano: en cuanto se supera el tope el paso ya esta descartado y seguir
                # recorriendo la grilla es trabajo puro. Ver el docstring del modulo: un RESET
                # registrado genera una clique de co-ocurrencia que se come toda la senal.
                self._descartados_por_masivos += 1
                return False

        if mecanica is None:
            mecanica = detectar_mecanica([list(f) for f in pre], [list(f) for f in post], mask)

        indice = len(self._pasos)
        bit = 1 << indice
        for celda in cambios:
            self._cambios_por_celda[celda] = self._cambios_por_celda.get(celda, 0) | bit
        self._pasos.append(
            PasoObservado(
                accion=accion,
                cajas_locales=cajas_explicadas_por_locales(mecanica),
                coordenada=coordenada,
            )
        )
        if len(self._pasos) >= MAX_PASOS_RETENIDOS:
            self._podar()
        return True

    def _podar(self) -> None:
        """Ventana deslizante: descarta los `PASOS_PODADOS` mas viejos. Las celdas que quedan sin
        ningun cambio en la ventana salen del area activa -- es el pre-filtro de estaticas aplicado
        de nuevo sobre la ventana vigente, no una sola vez al principio."""
        self._pasos = self._pasos[PASOS_PODADOS:]
        supervivientes: dict[Celda, int] = {}
        for celda, firma in self._cambios_por_celda.items():
            recortada = firma >> PASOS_PODADOS
            if recortada:
                supervivientes[celda] = recortada
        self._cambios_por_celda = supervivientes

    def regiones(self) -> list[RegionDeCambio]:
        """Agrupa el area activa en regiones por FIRMA DE CO-CAMBIO (ver docstring del modulo).

        Tres etapas, y la del medio NO estaba en el diseno original -- es una correccion obligada,
        no un refinamiento: (1) agrupacion exacta por firma, que ya deduplica casi toda la
        redundancia intra-objeto porque las celdas de un mismo objeto comparten la mascara de pasos
        bit a bit; (2) SEPARACION POR LOCALIDAD dentro de cada firma; (3) fusion de grupos con
        Jaccard >= `JACCARD_DE_FUSION`, que absorbe al objeto que pierde una celda suelta por
        oclusion, y que TAMPOCO puede cruzar la frontera de no localidad.

        POR QUE LA ETAPA 2 ES OBLIGATORIA. Un boton y la puerta que abre co-cambian EXACTAMENTE en
        los mismos pasos: esa es la definicion del fenomeno que este modulo existe para detectar. Y
        justamente por eso comparten la firma bit a bit y la etapa 1 los mete en UNA sola region --
        con lo cual no queda ningun par que testear y el detector se come su propia senal. Una
        region es un OBJETO; dos grupos de celdas separados por mas de
        `SEPARACION_CHEBYSHEV_MINIMA` no son un objeto por muy correlacionados que esten. El
        invariante que sale de aca es que NINGUNA region abarca un hueco no local."""
        por_firma: dict[int, list[Celda]] = {}
        for celda, firma in self._cambios_por_celda.items():
            por_firma.setdefault(firma, []).append(celda)

        # Orden por popcount descendente y despues por la firma: determinista y con las regiones
        # mas activas primero, que son las que absorben a las parecidas en la fusion.
        grupos: list[tuple[int, list[Celda]]] = []
        for firma, miembros in sorted(
            por_firma.items(), key=lambda par: (-par[0].bit_count(), par[0])
        ):
            for parte in _separar_por_localidad(miembros):
                grupos.append((firma, parte))
        grupos.sort(key=lambda par: (-len(par[1]), min(par[1])))
        del grupos[MAX_GRUPOS_A_FUSIONAR:]

        firmas: list[int] = []
        celdas: list[list[Celda]] = []
        cajas: list[BoundingBox] = []
        for firma, miembros in grupos:
            caja = caja_de_celdas(miembros)
            destino = -1
            for i, otra in enumerate(firmas):
                if separacion_chebyshev(caja, cajas[i]) >= SEPARACION_CHEBYSHEV_MINIMA:
                    # La fusion por Jaccard nunca cruza la frontera de no localidad: si lo hiciera,
                    # reintroduciria por la puerta de atras el colapso que la etapa 2 evita.
                    continue
                interseccion = (firma & otra).bit_count()
                union = (firma | otra).bit_count()
                if union and interseccion / union >= JACCARD_DE_FUSION:
                    destino = i
                    break
            if destino >= 0:
                firmas[destino] |= firma
                celdas[destino].extend(miembros)
                cajas[destino] = _union_de_cajas(cajas[destino], caja)
            else:
                firmas.append(firma)
                celdas.append(list(miembros))
                cajas.append(caja)

        indices = sorted(range(len(firmas)), key=lambda i: (-len(celdas[i]), sorted(celdas[i])[0]))
        salida: list[RegionDeCambio] = []
        for nuevo_id, i in enumerate(indices[:MAX_REGIONES]):
            miembros = sorted(celdas[i])
            salida.append(
                RegionDeCambio(
                    id=nuevo_id,
                    celdas=tuple(miembros),
                    caja=caja_de_celdas(miembros),
                    firma=firmas[i],
                    pasos=firmas[i].bit_count(),
                )
            )
        return salida

    def pares_no_locales(self, regiones: list[RegionDeCambio]) -> list[tuple[int, int]]:
        """Pares de regiones separadas por al menos `SEPARACION_CHEBYSHEV_MINIMA` celdas entre sus
        bounding boxes. Es el DENOMINADOR HONESTO de la correccion por multiplicidad: se testean
        todos, co-ocurran o no."""
        pares: list[tuple[int, int]] = []
        for i in range(len(regiones)):
            caja_i = regiones[i].caja
            for j in range(i + 1, len(regiones)):
                if separacion_chebyshev(caja_i, regiones[j].caja) >= SEPARACION_CHEBYSHEV_MINIMA:
                    pares.append((i, j))
        return pares

    def explicado_por_locales(self, paso: int, caja_a: BoundingBox, caja_b: BoundingBox) -> bool:
        """True si en ese paso ALGUNA caja explicada por los detectores locales contiene a las DOS
        regiones -- o sea, si lo que parece causa a distancia es en realidad un unico cluster o una
        unica traslacion ya nombrada por el vocabulario local."""
        for caja in self._pasos[paso].cajas_locales:
            if _contenida(caja_a, caja) and _contenida(caja_b, caja):
                return True
        return False

    def acciones_de(self, mascara: int) -> dict[str, int]:
        """Histograma de acciones sobre los pasos marcados en `mascara`. La accion de un paso es la
        que PRODUJO esa transicion, asi que el histograma es directamente la evidencia de que la
        co-activacion esta ligada a UN boton."""
        conteo: dict[str, int] = {}
        pendiente = mascara
        while pendiente:
            bit = pendiente & -pendiente
            indice = bit.bit_length() - 1
            accion = self._pasos[indice].accion
            conteo[accion] = conteo.get(accion, 0) + 1
            pendiente ^= bit
        return conteo

    def pasos_de(self, mascara: int) -> list[int]:
        """Indices de los pasos marcados en `mascara`, en orden ascendente."""
        indices: list[int] = []
        pendiente = mascara
        while pendiente:
            bit = pendiente & -pendiente
            indices.append(bit.bit_length() - 1)
            pendiente ^= bit
        return indices


# ============================== arc_agent/world_model/estadistica_de_coocurrencia.py ==============================
"""[arc-agi3-kaggle-agent/world_model/estadistica_de_coocurrencia] BL.21704 -- la maquinaria
estadistica con la que `relaciones_no_locales.py` decide si una co-ocurrencia entre dos regiones
lejanas es senal o ruido. Sin estado: funciones puras sobre mascaras de bits.

EL RIESGO PRINCIPAL NO ES "CORRELACION NO ES CAUSA": ES QUE EL NULO ANALITICO MIENTE. La etapa 1 de
BL.21704 corrio el pipeline entero sobre datos PERMUTADOS -- o sea, sobre puro ruido con los
marginales reales -- y sobrevivieron 45 pares a Benjamini-Hochberg y 34 a Bonferroni, con 11 de 20
juegos mostrando al menos un par "significativo" falso por construccion. Esa es la razon de que
este modulo tenga DOS nulos y no uno:

  * `cola_binomial` es el nulo ANALITICO. Sirve para ORDENAR candidatos barato y alimentar BH; su
    supuesto de independencia entre pasos es falso en un juego (las trayectorias son suaves).
  * `umbral_del_nulo_empirico` es el nulo que MANDA: desplazamiento CIRCULAR de la region destino,
    que conserva sus marginales exactos y destruye solo la alineacion temporal.

Y el denominador de BH es HONESTO: se corrige por TODOS los tests hechos (pares no locales x 3
direcciones), no por los que llegaron a co-ocurrir. Elegir el denominador despues de ver el dato es
la forma mas comun de fabricar significancia.

Solo stdlib -- viaja al entregable de Kaggle.
"""

import math
from typing import Final

#: Co-activaciones minimas para siquiera testear un par. Medido: por debajo de 5 el conteo explota
#: (757.920 candidatos a nivel celda); con 5 quedan 1.696 candidatos sobre 223.302 tests.
MIN_SOPORTE: Final[int] = 5

#: Alfa de Benjamini-Hochberg. Bonferroni queda como referencia (213 pares contra 318 de BH sobre
#: el mismo corpus): NO es la restriccion vinculante -- la restriccion vinculante es que el nulo
#: binomial esta equivocado, y eso no lo arregla apretar el alfa.
ALFA_BH: Final[float] = 0.05

#: lag0 + las dos direcciones de lag1. La ventana de desfase es {0, 1} y NADA MAS: medido, lag0
#: lleva la senal y lag1 es sensiblemente mas ruidoso (en sp80 el nulo dio 8-14 sobrevivientes de
#: lag1 contra 5 observados), asi que lag1 solo entra con el nulo condicionado a la accion.
DIRECCIONES_POR_PAR: Final[int] = 3

#: Barajas del nulo empirico. 20 era el minimo para leer un percentil 95 sin interpolar (el 19.o
#: valor ordenado) y era TAMBIEN el defecto medido como SESGADO: con `paso = pasos // (cuantos+1)`
#: los 20 offsets caian todos en multiplos de ese paso, o sea en una sub-red de los desplazamientos
#: posibles. Contrastado sobre los candidatos reales de cuatro partidas de lp85, ese nulo aceptaba
#: entre 14% y 26% MAS pares que el nulo circular exhaustivo (86->64, 636->528, 1032->734,
#: 547->415), siempre en la direccion permisiva. Ahora el nulo es EXHAUSTIVO mientras la ventana lo
#: permita -- rotar enteros es barato -- y por encima de ese tope se muestrea con un paso COPRIMO
#: con `pasos-1`, que recorre todos los residuos en vez de una sub-red.
BARAJAS_DEL_NULO: Final[int] = 120
PERCENTIL_DEL_NULO: Final[int] = 95

#: Por debajo de esta cantidad de desplazamientos posibles el nulo se corre ENTERO (todos los
#: offsets de 1 a `pasos-1`). Es el nulo de referencia, no una aproximacion.
MAX_OFFSETS_EXHAUSTIVOS: Final[int] = 240


def cola_binomial(exitos: int, ensayos: int, p: float) -> float:
    """P(X >= exitos) con X ~ Binomial(ensayos, p), por recurrencia sobre la razon de terminos
    consecutivos -- sin factoriales gigantes, sin tabla y sin dependencias.

    Es el nulo ANALITICO, y la etapa 1 midio que MIENTE (deja pasar ~45 pares de puro ruido). Se
    conserva porque ordena los candidatos para BH de forma barata; el filtro vinculante es
    `umbral_del_nulo_empirico`."""
    if exitos <= 0:
        return 1.0
    if ensayos <= 0 or exitos > ensayos:
        return 0.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    log_termino = (
        math.lgamma(ensayos + 1)
        - math.lgamma(exitos + 1)
        - math.lgamma(ensayos - exitos + 1)
        + exitos * math.log(p)
        + (ensayos - exitos) * math.log1p(-p)
    )
    if log_termino < -745.0:
        return 0.0
    termino = math.exp(log_termino)
    total = termino
    razon_base = p / (1.0 - p)
    for k in range(exitos, ensayos):
        termino *= (ensayos - k) / (k + 1) * razon_base
        total += termino
        if termino < total * 1e-15:
            break
    return min(1.0, total)


def indice_de_corte_bh(p_valores: list[float], denominador: int) -> int:
    """Cuantos de los p-valores ORDENADOS ascendentemente sobreviven a Benjamini-Hochberg.

    `denominador` es la cantidad TOTAL de tests hechos, que casi nunca coincide con
    `len(p_valores)`: los pares que ni siquiera llegaron al soporte minimo tambien se testearon."""
    if not p_valores or denominador <= 0:
        return 0
    corte = 0
    for rango, p in enumerate(p_valores, 1):
        if p <= ALFA_BH * rango / denominador:
            corte = rango
    return corte


def _coprimo_con(n: int, arranque: int) -> int:
    """Primer entero >= `arranque` (y < n) coprimo con `n`. Un paso coprimo recorre TODOS los
    residuos modulo n antes de repetirse; uno que comparta divisor con n recorre solo la sub-red de
    sus multiplos -- que es exactamente el defecto que se midio en el nulo anterior."""
    if n <= 2:
        return 1
    for candidato in range(max(1, min(arranque, n - 1)), n):
        if math.gcd(candidato, n) == 1:
            return candidato
    return 1


def desplazamientos_del_nulo(pasos: int, cuantos: int = BARAJAS_DEL_NULO) -> list[int]:
    """Desplazamientos circulares del nulo empirico, DETERMINISTAS a proposito.

    El repo pinnea flotantes en tests de paridad entre el puerto Python y el TS; un nulo sembrado
    con el `rng` de la politica haria que dos corridas con la MISMA semilla dieran vocabularios
    distintos segun cuantos numeros consumio antes la exploracion.

    EL NULO ES EXHAUSTIVO MIENTRAS LA VENTANA LO PERMITA. Rotar un entero y contar sus bits cuesta
    nanosegundos, asi que con `pasos - 1 <= MAX_OFFSETS_EXHAUSTIVOS` se corren TODOS los
    desplazamientos y el percentil 95 es el del nulo circular completo, sin muestreo ni sesgo. Por
    encima de ese tope se toma un paso COPRIMO con `pasos - 1`, que barre todos los residuos; el
    defecto medido de la version anterior era justamente que su paso (`pasos // 21`) divide a la
    ventana y solo visitaba sus multiplos."""
    if pasos <= 2 or cuantos <= 0:
        return []
    posibles = pasos - 1
    if posibles <= MAX_OFFSETS_EXHAUSTIVOS:
        return list(range(1, pasos))
    paso = _coprimo_con(posibles, max(1, posibles // (cuantos + 1)))
    vistos: list[int] = []
    visto: set[int] = set()
    for i in range(1, cuantos * 3 + 1):
        offset = ((i * paso) % posibles) + 1
        if offset not in visto:
            visto.add(offset)
            vistos.append(offset)
        if len(vistos) >= cuantos:
            break
    return vistos


def rotar_circular(mascara: int, offset: int, pasos: int) -> int:
    """Rota la mascara de pasos dentro de la ventana de `pasos` bits. Conserva el popcount EXACTO
    -- por eso el nulo mantiene los marginales de la region y solo rompe la alineacion temporal."""
    if pasos <= 0:
        return 0
    total = (1 << pasos) - 1
    offset %= pasos
    if offset == 0:
        return mascara & total
    return ((mascara << offset) | ((mascara & total) >> (pasos - offset))) & total


def coocurrencias(firma_origen: int, firma_destino: int, desfase: int) -> int:
    """Mascara de los pasos en que se da la co-activacion, indexada por el paso de ORIGEN -- que es
    donde vive la accion que la causo, y por eso el histograma de acciones se arma sobre esta
    mascara y no sobre la del destino."""
    if desfase == 0:
        return firma_origen & firma_destino
    return firma_origen & (firma_destino >> 1)


def umbral_del_nulo_empirico(
    firma_origen: int, firma_destino: int, desfase: int, pasos: int
) -> float:
    """Percentil `PERCENTIL_DEL_NULO` del soporte bajo desplazamiento circular del DESTINO.

    Devuelve `inf` cuando la ventana es demasiado corta para barajar: sin nulo no se acepta nada,
    que es el lado correcto en el que fallar."""
    offsets = desplazamientos_del_nulo(pasos)
    if not offsets:
        return math.inf
    nulos = sorted(
        coocurrencias(firma_origen, rotar_circular(firma_destino, o, pasos), desfase).bit_count()
        for o in offsets
    )
    indice = min(len(nulos) - 1, (PERCENTIL_DEL_NULO * len(nulos) + 99) // 100 - 1)
    return float(nulos[indice])


# ============================== arc_agent/world_model/evidencia_relacional.py ==============================
"""[arc-agi3-kaggle-agent/world_model/evidencia_relacional] BL.21704 -- el TIPO de una relacion
causal a distancia y, sobre todo, el MODELO DE EVIDENCIA que distingue haberla observado de haberla
probado. La mineria vive en `relaciones_no_locales.py`; aca vive que significa creerle.

POR QUE LA EVIDENCIA TIENE DOS CANALES Y NO UNO. El corpus con el que se calibro este detector
viene de una politica EXPLORATORIA: en un juego donde el baseline nunca dispara el boton, no hay
NADA que minar por mas frames que se junten -- y eso no se arregla con mas observacion, se arregla
PROBANDO. El agente elige sus acciones, asi que puede repetir la accion sospechosa y ver si el
efecto lejano vuelve. Esa es la ventaja que el aprendizaje sobre juegos tiene sobre el aprendizaje
sobre mercados, y el modelo de evidencia la hace explicita en vez de dejarla en un comentario:

  * canal OBSERVACIONAL: cada co-activacion aporta 0,10 en log-odds, con TOPE de 2,0. Partiendo de
    un prior esceptico de -2,0 eso significa que la evidencia puramente observacional TIENE TECHO
    0,5 -- por muchas veces que se repita, observar no desconfunde.
  * canal INTERVENCIONAL: una repeticion exitosa aporta 1,20 (doce veces una observacion) y una
    fallida CASTIGA 1,80. El castigo es mayor que el premio a proposito: un exito todavia puede ser
    coincidencia, mientras que un fallo contradice la relacion de frente.

El veredicto es 3 de 4. Con ese corte, una relacion falsa que "acierta" la mitad de las veces por
azar pasa con probabilidad 5/16; y dos fallos la refutan de inmediato, sin gastar el cuarto intento.

Solo stdlib -- viaja al entregable de Kaggle.
"""

import math
from dataclasses import dataclass
from typing import Final

# Imports relativos en UNA sola linea a proposito: submission/build_agent.py los desmonta con el
# regex `^from \.\w* import .+$` y la forma con parentesis dejaria un `)` colgando en el entregable.



#: Confirmacion activa: `CONFIRMACIONES_REQUERIDAS` de `INTENTOS_DE_CONFIRMACION`.
CONFIRMACIONES_REQUERIDAS: Final[int] = 3
INTENTOS_DE_CONFIRMACION: Final[int] = 4

#: Evidencia en log-odds (ver el docstring del modulo para el por que de cada numero).
LOG_ODDS_INICIAL: Final[float] = -2.0
APORTE_OBSERVACIONAL: Final[float] = 0.10
TOPE_DE_APORTE_OBSERVACIONAL: Final[float] = 2.0
APORTE_INTERVENCIONAL: Final[float] = 1.20
CASTIGO_INTERVENCIONAL: Final[float] = 1.80

#: Piso de evidencia para que una relacion se ofrezca como SUB-META al planner. 0,55 esta por
#: encima del techo observacional (0,5) A PROPOSITO. PERO EL PISO SOLO NO ALCANZA, y esto se
#: midio: con soporte alto el aporte observacional satura en +2,0, cancela el prior -2,0, y UN
#: SOLO exito intervencional deja la evidencia en 0,77 -- por encima del piso. O sea que el piso,
#: por si mismo, dejaba pasar relaciones con exitos=1 y fallos=0 mientras el BL exige 3 de 4.
#: Por eso submetas() exige AHORA las dos cosas: piso de evidencia Y veredicto intervencional.
PISO_DE_EVIDENCIA_PARA_SUBMETA: Final[float] = 0.55

#: CONDICION DE CONTROL de la via intervencional. Una repeticion "exitosa" solo prueba algo si el
#: destino NO cambia solo: sin comparar contra la tasa base, una puerta que parpadea en todos los
#: pasos llega a 3 de 4 y emite sub-meta -- verificado con un test adversarial contra la version
#: anterior. Con 3 de 4 exigidas (0,75) la tasa base tiene que quedar por debajo de 0,25 para que
#: el contraste do(accion) contra no-accion diga algo; y hacen falta al menos MIN_PASOS_DE_CONTROL
#: pasos sin la accion para estimarla. Sin control suficiente NO se confirma: el lado correcto en
#: el que fallar es el que no otorga permiso para dirigir el plan.
TASA_BASE_MAXIMA: Final[float] = 0.25
MIN_PASOS_DE_CONTROL: Final[int] = 10

ClaveDeRelacion = tuple[int, int, int, int, int, int, int, int, int]


def clave_de_relacion(
    origen: BoundingBox, destino: BoundingBox, desfase: int
) -> ClaveDeRelacion:
    """Identidad ESTABLE de una relacion, para que la evidencia intervencional sobreviva a que la
    mineria se vuelva a correr y renumere las regiones. Se apoya en la geometria (las dos cajas) y
    no en los ids, que cambian en cada pasada."""
    return (
        origen.min_y,
        origen.min_x,
        origen.max_y,
        origen.max_x,
        destino.min_y,
        destino.min_x,
        destino.max_y,
        destino.max_x,
        desfase,
    )


@dataclass
class Candidato:
    """Un par no local en evaluacion. Existe como tipo propio y no como diccionario para que las
    etapas del pipeline (soporte -> exclusion local -> BH -> nulo empirico -> pureza) se pasen algo
    con nombres, y no un mapa de claves que cualquiera puede escribir mal."""

    origen: RegionDeCambio
    destino: RegionDeCambio
    desfase: int
    mascara: int
    soporte: int
    esperado: float
    p_valor: float
    umbral_del_nulo: float = 0.0


@dataclass
class RelacionNoLocal:
    """Una relacion causal a distancia. NUNCA un booleano: la etapa 1 midio que el mismo par puede
    ser senal fuerte en un juego y ruido en otro, asi que lo que se guarda es la FUERZA (log-razon
    observado/esperado), el SOPORTE, la accion ligada, su pureza y el estado de confirmacion."""

    origen: RegionDeCambio
    destino: RegionDeCambio
    desfase: int
    soporte: int
    esperado: float
    fuerza: float
    p_valor: float
    umbral_del_nulo: float
    accion: str
    pureza: float
    #: Coordenada con la que se dispara, cuando la accion la lleva (un click). REPETIR la accion
    #: sin ella no es repetir nada, asi que una relacion de click sin coordenada no se retiene.
    coordenada: tuple[int, int] | None = None
    exitos: int = 0
    fallos: int = 0
    #: CONDICION DE CONTROL: pasos observados en que la accion de la relacion NO se ejecuto, y en
    #: cuantos de ellos el destino cambio igual. Es el nulo de la via intervencional. El argumento
    #: viejo, "pasa con probabilidad 5/16 tirando una moneda", usa p=0,5, que no es el nulo
    #: relevante: el nulo es la tasa base de cambio del destino, medida entre 0,06 y 0,24 en lp85
    #: y jamas comparada.
    pasos_de_control: int = 0
    cambios_sin_accion: int = 0

    @property
    def clave(self) -> ClaveDeRelacion:
        return clave_de_relacion(self.origen.caja, self.destino.caja, self.desfase)

    @property
    def intentos(self) -> int:
        return self.exitos + self.fallos

    @property
    def control_suficiente(self) -> bool:
        return self.pasos_de_control >= MIN_PASOS_DE_CONTROL

    @property
    def tasa_base(self) -> float:
        """Probabilidad de que el destino cambie CUANDO NO se ejecuto la accion. Es contra esto que
        hay que leer los exitos intervencionales, no contra una moneda."""
        if self.pasos_de_control <= 0:
            return 0.0
        return self.cambios_sin_accion / self.pasos_de_control

    @property
    def cambia_sola(self) -> bool:
        """El destino cambia por su cuenta lo bastante seguido como para que repetir la accion no
        pruebe nada. Es el control negativo del BL aplicado en la etapa que otorga el permiso de
        dirigir el plan, y no solo en la mineria."""
        return self.control_suficiente and self.tasa_base - TASA_BASE_MAXIMA - 1e-12 > 0.0

    @property
    def refutada(self) -> bool:
        """Con 3 de 4, dos fallos ya hacen imposible el veredicto positivo: se refuta ahi mismo, en
        vez de gastar el cuarto intento en una relacion que ya no puede pasar. Y una relacion cuyo
        destino cambia solo queda refutada aunque acierte todas: no hay contraste que medir."""
        return (
            self.fallos - (INTENTOS_DE_CONFIRMACION - CONFIRMACIONES_REQUERIDAS) - 1 >= 0
            or self.cambia_sola
        )

    @property
    def confirmacion(self) -> str:
        """"intervencional" exige las TRES cosas: 3 de 4 repeticiones, control suficiente para
        estimar la tasa base, y tasa base por debajo de TASA_BASE_MAXIMA."""
        if self.exitos - CONFIRMACIONES_REQUERIDAS < 0:
            return "observacional"
        if not self.control_suficiente or self.cambia_sola:
            return "observacional"
        return "intervencional"

    @property
    def evidencia(self) -> float:
        """Log-odds -> probabilidad. Ver las constantes: la via observacional tiene TECHO 0,5."""
        aporte = min(self.soporte * APORTE_OBSERVACIONAL, TOPE_DE_APORTE_OBSERVACIONAL)
        log_odds = (
            LOG_ODDS_INICIAL
            + aporte
            + self.exitos * APORTE_INTERVENCIONAL
            - self.fallos * CASTIGO_INTERVENCIONAL
        )
        return 1.0 / (1.0 + math.exp(-log_odds))

    def resumen(self) -> dict[str, object]:
        """Fila de reporte: la relacion tiene que ser AUDITABLE desde fuera del agente."""
        return {
            "origen": [self.origen.caja.min_y, self.origen.caja.min_x],
            "destino": [self.destino.caja.min_y, self.destino.caja.min_x],
            "desfase": self.desfase,
            "fuerza": round(self.fuerza, 4),
            "soporte": self.soporte,
            "esperado": round(self.esperado, 4),
            "umbralDelNulo": round(self.umbral_del_nulo, 4),
            "accion": self.accion,
            "coordenada": list(self.coordenada) if self.coordenada is not None else None,
            "pureza": round(self.pureza, 4),
            "confirmacion": self.confirmacion,
            "exitos": self.exitos,
            "fallos": self.fallos,
            "pasosDeControl": self.pasos_de_control,
            "tasaBase": round(self.tasa_base, 4),
            "evidencia": round(self.evidencia, 4),
        }


@dataclass(frozen=True)
class SubMeta:
    """Lo que el almacen le ofrece al planner: "repetir `accion` hace cambiar `caja_destino`". Es
    accionable -- una sub-meta, no una descripcion."""

    accion: str
    coordenada: tuple[int, int] | None
    caja_origen: BoundingBox
    caja_destino: BoundingBox
    desfase: int
    fuerza: float
    soporte: int
    evidencia: float
    confirmacion: str


# ============================== arc_agent/world_model/relaciones_no_locales.py ==============================
"""[arc-agi3-kaggle-agent/world_model/relaciones_no_locales] BL.21704 -- detector de CAUSA A
DISTANCIA: un cambio en A que va junto con un cambio en B EN OTRA PARTE DEL TABLERO. Un solo
detector parametrico cubre toda la familia boton/puerta, palanca/plataforma, interruptor/color,
placa de presion y llave/cerradura, sin escribir un concepto por juego -- que es lo que lo hace
valer tambien en los juegos PRIVADOS, el criterio de aceptacion de todo prior de este proyecto.

ES UN ALMACEN APARTE, NO UN SIMBOLO MAS DE `MECANICAS`. `mechanics_posterior.MECANICAS` es el
vocabulario de MAPEO BOTON->DIRECCION, cuyo unico consumidor es `direction_beliefs` (BL.21853 lo
llevo de siete simbolos a diez agregando `recoloreo`, `aparicion` y `desaparicion`; el argumento de
abajo no depende del largo de la lista, asi que aca NO se copia -- se lee del modulo). Una relacion causal no local NO es una direccion: no hay lugar semantico donde
meterla. Y ese modulo es espejo exacto de `arc-agi-runner/src/worldModel/mechanicsPosterior.ts` con
tests que pinnean los mismos flotantes, asi que un simbolo nuevo renormaliza TODOS los priors y
rompe la paridad de los dos puertos. La integracion honesta es esta: un almacen propio que alimenta
SUB-METAS del planner.

LA CONFIRMACION INTERVENCIONAL ES EL MECANISMO CENTRAL, NO UN ADORNO. El corpus viene de una
politica EXPLORATORIA, asi que en un juego donde el baseline nunca dispara el boton NO HAY nada que
minar por mas corpus que se junte. Eso solo lo resuelve PROBAR -- el agente elige sus acciones,
repite la accion sospechosa y exige 3 de 4 repeticiones CONTRA LA TASA BASE del destino. Esa es la
ventaja que los juegos tienen sobre los mercados, y es aca donde se cobra. Para dirigir el plan
(`submetas()`) hacen falta las DOS cosas: veredicto intervencional y piso de evidencia.

LO QUE EL CORPUS OFFLINE MIDIO Y LO QUE EL HARNESS DESMINTIO -- dicho junto, porque leer solo lo
primero es lo que llevo a sobrestimar este detector. Sobre el corpus, la pureza de accion subia la
relacion senal/ruido de 4,5x a 15x (48 pares contra 3,3 del nulo, FDR ~7%) y la exclusion por
detectores locales cortaba de 318 pares a 72. Sobre el HARNESS REAL, con el agente jugando, esos
dos numeros no se reprodujeron: en lp85 el diagnostico daba `conSoporte 613 -> trasExclusionLocal
613` (la exclusion local descartaba CERO) y `trasBH 298 -> trasNuloEmpirico 298` (el nulo empirico
descartaba CERO), con entre 0 y 1.008 relaciones sobrevivientes por ventana y el vocabulario
decidido por el TOPE DE COSTO K=8 y no por el control de falsos positivos. La causa estaba
identificada y esta corregida aca: lo que sobrevivia eran FRANJAS CONTIGUAS repintadas por un mismo
click, partidas en pedazos por la agrupacion por firma (ver `_encadenado`). Un tope de vocabulario
no es un control de descubrimientos falsos, y un numero medido offline no es una propiedad del
detector hasta que se reproduce en el lazo cerrado.

QUE ESPERAR, DICHO ANTES Y NO DESPUES. La tesis original del BL ("la causa a distancia explica los
11 juegos que no convierten exploracion en progreso") esta REFUTADA por medicion: de esos 11 solo
re86 tiene senal sobre el nulo (10 contra 2,3), tr87 y sp80 caen dentro del ruido, y ar25, bp35,
cd82, cn04, ka59, ls20, sk48 y wa30 dan CERO. La senal fuerte esta en lp85 (44), m0r0 (13) y g50t
(2) -- juegos donde el agente YA completa niveles. La relacion existe y es detectable; la
expectativa de subida por la via OBSERVACIONAL es baja, y lo que puede moverla es la via
intervencional, que un corpus de observacion pasiva no podia medir.

Sin estado global, sin red y solo stdlib -- viaja al entregable de Kaggle.
"""

import math
from typing import Final, Sequence

# Imports relativos en UNA sola linea a proposito: submission/build_agent.py los desmonta con el
# regex `^from \.\w* import .+$` y la forma con parentesis dejaria un `)` colgando en el entregable.












#: Pureza minima de la accion dominante entre las co-activaciones. 0,8 es el corte medido sobre el
#: corpus offline, donde era el filtro individual de mejor rendimiento (48 pares contra 3,3 del
#: nulo, FDR ~7%). Se aplica sobre los pasos de la accion dominante, no sobre el soporte total: ver
#: `_con_accion`, donde el denominador equivocado borraba en silencio las relaciones de teclado.
PUREZA_MINIMA_DE_ACCION: Final[float] = 0.8

#: Fraccion de co-ocurrencias que alcanza con que expliquen los detectores LOCALES para descartar
#: el par entero. Impacto sobre el corpus offline: 318 pares -> 72. Impacto medido EN VIVO sobre
#: lp85 con el harness real: CERO (613 -> 613), porque `agrupar_en_clusters` usa 8-conexidad de
#: radio 1 y dos regiones separadas por el minimo no local casi nunca caen en una misma caja: solo
#: la caja union de una TRASLACION puede lograrlo. Sigue siendo obligatoria -- es lo unico que
#: separa una causa a distancia de un objeto que se movio, y hay un test que la hace portante
#: (`test_la_exclusion_por_detectores_locales_es_la_que_mata_la_traslacion`) -- pero no es el filtro
#: de mayor impacto que el corpus sugeria.
FRACCION_EXPLICADA_POR_LOCALES: Final[float] = 0.5

#: Tope de vocabulario: como maximo K relaciones por partida, ordenadas por FUERZA. Acota el riesgo
#: que BL.21593 ya tuvo que acotar con masa reservada de desconocido: un vocabulario inflado
#: reparte masa del posterior y sube la probabilidad de elegir con confianza la menos mala de las
#: opciones equivocadas -- el peor modo de falla que este proyecto midio.
TOPE_DE_VOCABULARIO: Final[int] = 8

#: Cada cuantos pasos REGISTRADOS se vuelve a minar, EN EL ARRANQUE de la partida. La mineria es
#: cuadratica en regiones y no aporta nada nuevo paso a paso.
#:
#: COSTO. La cifra que este modulo declaraba ("3,9 ms de CPU por accion, ~3%") se tomo en el peor
#: caso del CORPUS a 200 pasos. Instrumentado dentro del harness real sobre lp85, el costo CRECE
#: con la profundidad: 200 pasos -> 0,37 ms/accion (0,2% del CPU), 800 -> 5,59 ms (1,8%), 1600 ->
#: 15,65 ms (4,56%). El gate mide a 200 pasos, pero el entregable juega hasta ~1600 acciones por
#: juego bajo el reloj de 8 h, y ahi el detector se comia casi el 5% de las acciones -- que con la
#: curva de score de BL.21701 (800 -> 5,5 niveles, 1600 -> 8,5) es score real. De ahi el escalon de
#: `PASOS_POR_ESCALON_DE_MINERIA` y el corte de mineria al agotarse el presupuesto de
#: intervenciones. `detectar_mecanica` NO entra en esa cuenta porque la politica ya la calcula una
#: vez por paso para el modelo de mundo y se la pasa hecha.
#:
#: Ese mismo banco es ademas una prueba del pipeline: la grilla se mueve al AZAR y el almacen
#: retiene CERO relaciones (0 tras BH, 0 tras el nulo empirico). Sobre ruido puro, no inventa.
INTERVALO_DE_MINERIA: Final[int] = 40

#: EL INTERVALO CRECE CON LA PARTIDA, y esto sale de una medicion que desmiente el "3% del
#: presupuesto" que este modulo declaraba. Instrumentando `observar`/`sugerir_intervencion` con
#: `time.thread_time()` dentro del harness real sobre lp85: 200 pasos -> 0,37 ms por accion (0,2%
#: del CPU), 800 pasos -> 5,59 ms (1,8%), 1600 pasos -> 15,65 ms (4,56%). La medicion del BL se
#: habia tomado a 200 pasos, que es la profundidad del GATE, pero el entregable juega hasta ~1600
#: acciones por juego bajo el reloj de 8 h -- y ahi el detector se comia casi el 5% de las
#: acciones. Con un escalon cada `PASOS_POR_ESCALON_DE_MINERIA` el intervalo pasa de 40 a 160 en
#: esa cola, que es donde el area activa (y con ella el costo cuadratico) esta en su maximo.
PASOS_POR_ESCALON_DE_MINERIA: Final[int] = 400

#: Pasos registrados antes de la primera mineria. Por debajo no hay ni marginales para el nulo ni
#: soporte posible (`MIN_SOPORTE` son 5 co-activaciones).
PASOS_MINIMOS_PARA_MINAR: Final[int] = 40

#: Tope de tests por pasada de mineria. Es una cota de COSTO, no de estadistica: el denominador de
#: BH sigue siendo el de TODOS los pares no locales. Si se pasa, se testean los de mayor soporte.
MAX_TESTS_POR_MINERIA: Final[int] = 4000

#: Acciones que el almacen puede gastar por partida en confirmar relaciones. 24 sobre las 200 del
#: gate es el 12%: alcanza para llevar 6 relaciones a veredicto (4 intentos cada una) y deja el
#: presupuesto de exploracion practicamente intacto.
MAX_INTERVENCIONES_POR_PARTIDA: Final[int] = 24

#: Intentos que se pueden gastar en UN MISMO disparador (accion + coordenada). Sin este tope se
#: midio en vivo lo peor de los dos mundos: en lp85 las 24 intervenciones fueron el MISMO ACTION6
#: en (48,25), una detras de otra, porque seis relaciones distintas compartian ese click. Repetir
#: el mismo click seis veces no son seis experimentos: es UN experimento repetido. Ahora el
#: disparador se agota en `INTENTOS_DE_CONFIRMACION` repeticiones y CADA repeticion juzga a TODAS
#: las relaciones vivas que comparten ese disparador -- una accion, todos los veredictos.
MAX_INTENTOS_POR_DISPARADOR: Final[int] = INTENTOS_DE_CONFIRMACION

#: EXPLOTACION de una relacion ya confirmada (ver `Policy._explotar_submeta`, el consumidor de
#: `submetas()`). Se dispara cuando el tablero lleva `PASOS_SIN_CAMBIO_PARA_SUBMETA` pasos sin
#: moverse: ahi el ranker de novedad esta proponiendo lo menos visitado a ciegas, y una relacion
#: PROBADA es lo unico que el agente sabe que cambia una region lejana. `MAX_EXPLOTACIONES` acota
#: lo que puede costar equivocarse -- repetir algo ya conocido no aporta informacion nueva -- con
#: el mismo criterio con que `MAX_INTERVENCIONES_POR_PARTIDA` acota la via activa.
PASOS_SIN_CAMBIO_PARA_SUBMETA: Final[int] = 3
MAX_EXPLOTACIONES_DE_SUBMETA: Final[int] = 12


class AlmacenDeRelaciones:
    """Almacen relacional de una partida: observa, mina y CONFIRMA ACTIVAMENTE.

    Una instancia por partida. `observar()` corre en todos los pasos y es barato; `minar()` se
    dispara solo cada `INTERVALO_DE_MINERIA` pasos registrados. El llamador envuelve en try/except
    con el mismo criterio de fail-open que el resto del modelo de mundo: el modelo asiste, jamas
    bloquea la partida."""

    def __init__(self) -> None:
        self._historial = HistorialDeCambios()
        self._relaciones: list[RelacionNoLocal] = []
        self._confirmaciones: dict[ClaveDeRelacion, tuple[int, int]] = {}
        self._refutadas: set[ClaveDeRelacion] = set()
        self._control: dict[ClaveDeRelacion, tuple[int, int]] = {}
        self._pendiente: RelacionNoLocal | None = None
        self._diferidas: tuple[RelacionNoLocal, ...] = ()
        self._intentos_por_disparador: dict[tuple[str, tuple[int, int] | None], int] = {}
        self._intervenciones_gastadas = 0
        self._pasos_desde_mineria = 0
        self._excepciones_del_llamador = 0
        self._transiciones_no_ofrecidas = 0
        self._diagnostico: dict[str, int] = {}

    def anotar_transicion_no_ofrecida(self) -> None:
        """El llamador tenia un paso pero NO una transicion comparable que ofrecer (arranque de la
        partida, RESET, frame ausente). Se cuenta para que el diagnostico cierre: medido en lp85,
        `pasos` daba 160 sobre ~199 decisiones y los 38 restantes no aparecian en ningun contador,
        con lo cual no habia forma de distinguir "el detector vio poco" de "el detector se apago"."""
        self._transiciones_no_ofrecidas += 1

    def anotar_excepcion(self) -> None:
        """El llamador envuelve al almacen en un `try/except` fail-open (el modelo asiste, jamas
        bloquea la partida). Ese fail-open era MUDO: si `observar` lanzaba en todos los pasos, el
        diagnostico devolvia el dict inicializado en ceros -- exactamente el mismo reporte que "no
        hay senal". Un cero por excepcion y un cero honesto tienen que poder distinguirse, asi que
        el llamador anota aca cada excepcion capturada y el conteo viaja en `diagnostico()`."""
        self._excepciones_del_llamador += 1

    # -- observacion ---------------------------------------------------------------------------

    def observar(
        self,
        accion: str,
        pre: Sequence[Sequence[int]] | Grid,
        post: Sequence[Sequence[int]] | Grid,
        mecanica: Mecanica | None = None,
        mask: VolatilityMask | None = None,
        coordenada: tuple[int, int] | None = None,
    ) -> None:
        """Registra la transicion y, si hay una intervencion pendiente, la juzga."""
        reinicios_previos = self._historial.reinicios_por_forma
        registrado = self._historial.observar(accion, pre, post, mecanica, mask, coordenada)
        if not registrado:
            # PASO MASIVO (RESET, transicion de nivel) o grillas incomparables. No se juzga NADA
            # contra el: cambia medio tablero, asi que el destino de cualquier relacion pendiente
            # cambia casi con seguridad y la "confirmacion" seria un exito regalado -- justo la
            # clase de evidencia falsa que la via intervencional existe para no producir. La
            # intervencion se descarta sin contar, ni a favor ni en contra.
            self._pendiente = None
            self._diferidas = ()
            return
        if self._historial.reinicios_por_forma != reinicios_previos:
            # La grilla cambio de tamano y el historial se reinicio: es OTRO tablero. Las firmas y
            # las cajas de las relaciones vigentes hablan de coordenadas que ya no existen.
            #
            # SE DETECTA POR EL CONTADOR DEL HISTORIAL, no por una caida de `pasos`: la ventana
            # deslizante de `MAX_PASOS_RETENIDOS` tambien hace caer `pasos` (1.200 -> 800) y eso NO
            # es un tablero nuevo -- confundirlos tiraria el vocabulario entero cada 1.200 pasos,
            # justo en las partidas largas del entregable.
            self._relaciones = []
            self._pendiente = None
            self._diferidas = ()
            self._pasos_desde_mineria = 0
            # La evidencia esta indexada por GEOMETRIA (las dos cajas): en otro tablero esas cajas
            # no significan lo mismo, asi que no se hereda. El PRESUPUESTO de intervenciones si se
            # hereda: es por partida, y el agente ya gasto esas acciones.
            self._confirmaciones = {}
            self._control = {}
            self._refutadas = set()
        self._resolver_diferidas(pre, post)
        self._juzgar_intervencion(accion, coordenada, pre, post)
        self._contar_control(accion, coordenada, pre, post)
        self._pasos_desde_mineria += 1
        if (
            self._pasos_desde_mineria >= self._intervalo_de_mineria()
            and self._historial.pasos >= PASOS_MINIMOS_PARA_MINAR
            and self._intervenciones_gastadas < MAX_INTERVENCIONES_POR_PARTIDA
        ):
            # SE DEJA DE MINAR CUANDO SE AGOTA EL PRESUPUESTO DE INTERVENCIONES. Una relacion solo
            # dirige el plan con veredicto intervencional, y sin presupuesto ya no puede haber
            # veredicto: seguir minando solo gasta CPU y rota el vocabulario. Es tambien la cota
            # dura de costo en las partidas largas del entregable (ver PASOS_POR_ESCALON_DE_MINERIA).
            self._pasos_desde_mineria = 0
            self.minar()

    def _intervalo_de_mineria(self) -> int:
        escalon = 1 + self._historial.pasos // PASOS_POR_ESCALON_DE_MINERIA
        return INTERVALO_DE_MINERIA * escalon

    def _contar_control(
        self,
        accion: str,
        coordenada: tuple[int, int] | None,
        pre: Sequence[Sequence[int]] | Grid,
        post: Sequence[Sequence[int]] | Grid,
    ) -> None:
        """CONDICION DE CONTROL de la via intervencional: en los pasos en que la accion de la
        relacion NO se ejecuto, cuantas veces cambio igual su destino.

        Sin esto, la confirmacion activa no desconfunde nada -- que es lo unico que se le pedia. Un
        test adversarial contra la version anterior lo mostro: una puerta que parpadea en TODOS los
        pasos llega a 3 de 4 exitos y emite sub-meta, porque `_cambio_el_destino` solo pregunta si
        el destino cambio, nunca contra que. El nulo relevante no es una moneda (p=0,5) sino esta
        tasa base, que en lp85 se midio entre 0,06 y 0,24.

        Para las relaciones de desfase 1 la tasa se estima con la MISMA transicion inmediata: lo
        que se quiere medir es P(el destino cambia | no hubo accion) y esa probabilidad no depende
        del desfase con que se la mire mientras el proceso sea estacionario dentro de la ventana."""
        for relacion in self._relaciones:
            if accion == relacion.accion and (
                relacion.coordenada is None or coordenada == relacion.coordenada
            ):
                continue
            relacion.pasos_de_control += 1
            if self._cambio_el_destino(relacion, pre, post):
                relacion.cambios_sin_accion += 1
            self._control[relacion.clave] = (
                relacion.pasos_de_control,
                relacion.cambios_sin_accion,
            )
        self._relaciones = [r for r in self._relaciones if not r.refutada]

    def _resolver_diferidas(
        self, pre: Sequence[Sequence[int]] | Grid, post: Sequence[Sequence[int]] | Grid
    ) -> None:
        """Las relaciones de desfase 1 se juzgan en el paso SIGUIENTE al de la accion: por
        definicion el cambio del destino llega un paso mas tarde."""
        diferidas = self._diferidas
        if not diferidas:
            return
        self._diferidas = ()
        for relacion in diferidas:
            self.registrar_intervencion(relacion, self._cambio_el_destino(relacion, pre, post))

    @staticmethod
    def _disparador(relacion: RelacionNoLocal) -> tuple[str, tuple[int, int] | None]:
        """Identidad del EXPERIMENTO: la accion y, si la lleva, su coordenada. Dos relaciones con
        el mismo disparador se prueban con la MISMA repeticion."""
        return (relacion.accion, relacion.coordenada)

    def _juzgar_intervencion(
        self,
        accion: str,
        coordenada: tuple[int, int] | None,
        pre: Sequence[Sequence[int]] | Grid,
        post: Sequence[Sequence[int]] | Grid,
    ) -> None:
        """Juzga la intervencion sugerida -- si es que la politica la ejecuto DE VERDAD.

        LA COORDENADA SE VERIFICA ACA Y NO SOLO EN EL LLAMADOR. Antes, `_juzgar_intervencion`
        comparaba unicamente el nombre de la accion, asi que un ACTION6 en OTRA celda se acreditaba
        como confirmacion: verificado con un test adversarial que confirmaba una relacion clickeando
        en (47,47) en vez de su coordenada. Que la politica hoy alimente la coordenada correcta no
        es garantia -- ademas la clampea a la grilla, asi que un cambio de tamano bastaba para
        acreditar una repeticion que no ocurrio. El invariante vive donde se dictamina."""
        relacion = self._pendiente
        if relacion is None:
            return
        self._pendiente = None
        if accion != relacion.accion:
            # La politica no ejecuto la accion sugerida. NO se cuenta ni a favor ni en contra:
            # evidencia INTERVENCIONAL es la que produce una intervencion, no la que se mira pasar.
            return
        if relacion.coordenada is not None and coordenada != relacion.coordenada:
            return
        cohorte = self._cohorte(relacion)
        for companera in cohorte:
            if companera.desfase == 0:
                self.registrar_intervencion(
                    companera, self._cambio_el_destino(companera, pre, post)
                )
        self._diferidas = tuple(r for r in cohorte if r.desfase == 1)

    def _cohorte(self, relacion: RelacionNoLocal) -> tuple[RelacionNoLocal, ...]:
        """Relaciones vivas que comparten el disparador de `relacion` -- ella incluida.

        UNA REPETICION, TODOS LOS VEREDICTOS. Repetir el mismo click seis veces para juzgar seis
        relaciones que ese click dispara no son seis experimentos: es uno solo, repetido, y en lp85
        se comio las 24 intervenciones del presupuesto sin agregar informacion."""
        disparador = self._disparador(relacion)
        cohorte = [r for r in self._relaciones if self._disparador(r) == disparador]
        if all(r is not relacion for r in cohorte):
            cohorte.append(relacion)
        return tuple(cohorte)

    @staticmethod
    def _cambio_el_destino(
        relacion: RelacionNoLocal,
        pre: Sequence[Sequence[int]] | Grid,
        post: Sequence[Sequence[int]] | Grid,
    ) -> bool:
        alto = len(pre)
        if alto == 0 or len(post) != alto:
            return False
        for y, x in relacion.destino.celdas:
            if y < alto and x < len(pre[y]) and pre[y][x] != post[y][x]:
                return True
        return False

    # -- confirmacion activa -------------------------------------------------------------------

    def sugerir_intervencion(self, acciones_disponibles: Sequence[str]) -> str | None:
        """Accion que conviene REPETIR ahora para llevar una relacion a veredicto, o None.

        Elige la relacion con menos intentos gastados y mayor fuerza: la evidencia intervencional
        cuesta una accion del presupuesto y hay que gastarla donde mas mueve el veredicto."""
        if self._pendiente is not None or self._diferidas:
            return None
        if self._intervenciones_gastadas >= MAX_INTERVENCIONES_POR_PARTIDA:
            return None
        disponibles = set(acciones_disponibles)
        candidatas = [
            r
            for r in self._relaciones
            if r.accion in disponibles
            and not r.refutada
            # NO SE GASTA UNA ACCION EN UN EXPERIMENTO QUE NO PUEDE DISCRIMINAR. Una relacion sin
            # `control_suficiente` todavia no tiene estimada su tasa base, y una con `cambia_sola`
            # ya la tiene y dice que el destino cambia por su cuenta: en los dos casos repetir la
            # accion no prueba nada. Medido en lp85 con el harness real: las 8 relaciones minadas
            # terminaron refutadas por la tasa base, DESPUES de haberse comido 5 acciones del
            # presupuesto en intentar confirmarlas.
            and r.control_suficiente
            and r.exitos < CONFIRMACIONES_REQUERIDAS
            and r.intentos < INTENTOS_DE_CONFIRMACION
            and self._intentos_por_disparador.get(self._disparador(r), 0)
            < MAX_INTENTOS_POR_DISPARADOR
        ]
        if not candidatas:
            return None
        candidatas.sort(key=lambda r: (r.intentos, -r.fuerza, -r.soporte, r.clave))
        elegida = candidatas[0]
        disparador = self._disparador(elegida)
        self._intentos_por_disparador[disparador] = (
            self._intentos_por_disparador.get(disparador, 0) + 1
        )
        self._pendiente = elegida
        self._intervenciones_gastadas += 1
        return elegida.accion

    def registrar_intervencion(self, relacion: RelacionNoLocal, exito: bool) -> None:
        """Anota el resultado de UNA repeticion. Al segundo fallo la relacion queda refutada y sale
        del vocabulario para siempre: un control negativo en vivo vale mas que cualquier correccion
        offline, y una relacion refutada que vuelve a entrar en la proxima mineria seria un bucle."""
        if exito:
            relacion.exitos += 1
        else:
            relacion.fallos += 1
        self._confirmaciones[relacion.clave] = (relacion.exitos, relacion.fallos)
        self._control[relacion.clave] = (relacion.pasos_de_control, relacion.cambios_sin_accion)
        # `minar()` es publica y reconstruye la lista: si corriera entre la sugerencia y el
        # veredicto, `relacion` seria un objeto DESPRENDIDO y la copia viva de `_relaciones`
        # quedaria con los contadores viejos -- se volveria a sugerir la misma relacion y se
        # gastaria un intento de mas. El almacen de la verdad es `_confirmaciones`; esto solo
        # mantiene sincronizada la copia que se esta usando para decidir.
        for viva in self._relaciones:
            if viva is not relacion and viva.clave == relacion.clave:
                viva.exitos, viva.fallos = relacion.exitos, relacion.fallos
                viva.pasos_de_control = relacion.pasos_de_control
                viva.cambios_sin_accion = relacion.cambios_sin_accion
        if relacion.refutada:
            self._refutadas.add(relacion.clave)
            self._relaciones = [r for r in self._relaciones if r.clave != relacion.clave]

    @property
    def relacion_pendiente(self) -> RelacionNoLocal | None:
        """Relacion que se esta confirmando ahora mismo. La expone para que el llamador pueda
        dirigir la intervencion (por ejemplo, clickear el centro de la region ORIGEN): sin eso, un
        ACTION6 sugerido caeria en una celda cualquiera y no repetiria nada."""
        if self._pendiente is not None:
            return self._pendiente
        return self._diferidas[0] if self._diferidas else None

    @property
    def intervenciones_gastadas(self) -> int:
        return self._intervenciones_gastadas

    # -- mineria -------------------------------------------------------------------------------

    def minar(self) -> list[RelacionNoLocal]:
        """Corre el pipeline completo y deja el vocabulario vigente en `relaciones()`.

        ORDEN DE LOS FILTROS: no localidad (Chebyshev >= 8) -> soporte >= 5 -> CADENA DE CAMBIO
        CONTIGUO (una franja repintada no es causa a distancia) -> exclusion por detectores locales
        -> Benjamini-Hochberg con denominador honesto -> pureza de accion >= 0,8 -> NULO EMPIRICO
        por desplazamiento circular (sin el se cuelan ~45 falsos por corpus) -> tope K = 8.

        La pureza y el nulo empirico son dos predicados deterministas sobre el MISMO candidato, asi
        que su orden relativo no cambia el conjunto final: esta elegido por COSTO. El de BH si
        importa y por eso corre donde corre, con el denominador fijado de antemano."""
        pasos = self._historial.pasos
        regiones = self._historial.regiones()
        pares, adyacencia = particionar_pares(regiones)
        self._diagnostico = {
            "pasos": pasos,
            "pasosMasivosDescartados": self._historial.descartados_por_masivos,
            "celdasActivas": self._historial.celdas_activas,
            "regiones": len(regiones),
            "paresNoLocales": len(pares),
            "testsHechos": len(pares) * DIRECCIONES_POR_PAR,
            "conSoporte": 0,
            "trasCadenaDeCambios": 0,
            "trasExclusionLocal": 0,
            "trasBH": 0,
            "trasPureza": 0,
            "trasNuloEmpirico": 0,
            "retenidas": 0,
            "conEvidenciaIntervencional": 0,
        }
        if pasos < PASOS_MINIMOS_PARA_MINAR or not pares:
            self._relaciones = []
            return []

        candidatos = self._candidatos_con_soporte(regiones, pares, pasos)
        self._diagnostico["conSoporte"] = len(candidatos)
        componentes = componentes_por_paso(regiones, adyacencia, pasos)
        candidatos = [c for c in candidatos if not self._encadenado(c, componentes)]
        self._diagnostico["trasCadenaDeCambios"] = len(candidatos)
        candidatos = [c for c in candidatos if not self._explicado_por_locales(c)]
        self._diagnostico["trasExclusionLocal"] = len(candidatos)

        candidatos.sort(key=lambda c: c.p_valor)
        corte = indice_de_corte_bh([c.p_valor for c in candidatos], len(pares) * DIRECCIONES_POR_PAR)
        candidatos = candidatos[:corte]
        self._diagnostico["trasBH"] = len(candidatos)

        # LA PUREZA VA ANTES QUE EL NULO EMPIRICO, y no es una preferencia estetica: los dos son
        # filtros deterministas sobre el mismo candidato, asi que el conjunto final no depende del
        # orden, pero el COSTO si. El nulo exhaustivo cuesta `pasos` rotaciones por candidato y la
        # pureza cuesta un histograma sobre sus co-ocurrencias; medido en el peor caso del corpus,
        # la pureza descarta 1.383 -> 35, o sea que correr el nulo primero pagaba 40 veces el
        # trabajo para tirar el resultado.
        relaciones: list[RelacionNoLocal] = []
        con_pureza = 0
        for candidato in candidatos:
            relacion = self._con_accion(candidato)
            if relacion is None:
                continue
            con_pureza += 1
            if not self._supera_al_nulo_empirico(candidato, pasos):
                continue
            relacion.umbral_del_nulo = candidato.umbral_del_nulo
            relaciones.append(relacion)
        self._diagnostico["trasPureza"] = con_pureza
        self._diagnostico["trasNuloEmpirico"] = len(relaciones)

        # LA EVIDENCIA INTERVENCIONAL SE RESTAURA ANTES DEL TOPE, NO DESPUES. Hacerlo despues fue un
        # defecto medido en vivo: en lp85 el almacen gasto sus 24 intervenciones, llevo CINCO
        # relaciones a 3 de 3 exitos... y despues el tope K=8 las expulsaba en favor de candidatas
        # meramente OBSERVACIONALES con mas fuerza bruta, asi que `submetas()` devolvia cero. Eso
        # invierte la doctrina entera del BL: una relacion PROBADA no puede perder un lugar contra
        # una que solo se vio pasar.
        for relacion in relaciones:
            relacion.exitos, relacion.fallos = self._confirmaciones.get(relacion.clave, (0, 0))
            relacion.pasos_de_control, relacion.cambios_sin_accion = self._control.get(
                relacion.clave, (0, 0)
            )
        relaciones = [r for r in relaciones if not r.refutada]
        probadas = sorted(
            (r for r in relaciones if r.intentos > 0), key=lambda r: (-r.evidencia, -r.fuerza, r.clave)
        )
        sin_probar = sorted(
            (r for r in relaciones if r.intentos == 0), key=lambda r: (-r.fuerza, -r.soporte, r.clave)
        )
        relaciones = (probadas + sin_probar)[:TOPE_DE_VOCABULARIO]
        self._diagnostico["retenidas"] = len(relaciones)
        self._diagnostico["conEvidenciaIntervencional"] = len(probadas)
        self._relaciones = relaciones
        return relaciones

    def _candidatos_con_soporte(
        self, regiones: list[RegionDeCambio], pares: list[tuple[int, int]], pasos: int
    ) -> list[Candidato]:
        """Enumera las tres direcciones de cada par no local y se queda con las que llegan a
        `MIN_SOPORTE`. El popcount de enteros hace de motor de conteo: una mascara de bits por
        region y la co-ocurrencia es un AND -- por eso el pipeline entero cabe en el presupuesto
        por accion aunque el area activa llegue a las 2.318 celdas medidas en cn04."""
        total = (1 << pasos) - 1
        solo_izquierda = total >> 1
        solo_derecha = total ^ 1
        candidatos: list[Candidato] = []
        for i, j in pares:
            a, b = regiones[i], regiones[j]
            for origen, destino, desfase in ((a, b, 0), (a, b, 1), (b, a, 1)):
                if clave_de_relacion(origen.caja, destino.caja, desfase) in self._refutadas:
                    continue
                mascara = coocurrencias(origen.firma, destino.firma, desfase)
                soporte = mascara.bit_count()
                if soporte < MIN_SOPORTE:
                    continue
                # LOS ENSAYOS SON LAS ACTIVACIONES DEL ORIGEN, no los pasos de la ventana.
                # Bajo el nulo, cada vez que el origen cambia acierta un paso del destino con
                # probabilidad `p = activaciones del destino / pasos`; con `ensayos = pasos` la
                # media del binomial daria las activaciones del DESTINO en vez del esperado
                # `n_origen * n_destino / pasos`, y el p-valor no describiria nada.
                if desfase == 0:
                    ensayos = origen.pasos
                    p = destino.pasos / pasos
                else:
                    if pasos <= 1:
                        continue
                    ensayos = (origen.firma & solo_izquierda).bit_count()
                    p = (destino.firma & solo_derecha).bit_count() / (pasos - 1)
                esperado = ensayos * p
                if ensayos <= 0:
                    continue
                if esperado <= 0.0 or soporte <= esperado:
                    continue
                candidatos.append(
                    Candidato(
                        origen=origen,
                        destino=destino,
                        desfase=desfase,
                        mascara=mascara,
                        soporte=soporte,
                        esperado=esperado,
                        p_valor=cola_binomial(soporte, ensayos, p),
                    )
                )
        candidatos.sort(key=lambda c: (-c.soporte, c.p_valor))
        return candidatos[:MAX_TESTS_POR_MINERIA]

    def _encadenado(self, candidato: Candidato, componentes: list[dict[int, int]]) -> bool:
        """True si las dos regiones son, la mayoria de las veces que co-cambian, PEDAZOS DE UNA
        MISMA FRANJA DE CAMBIO CONTIGUA -- y entonces no hay ninguna causa a distancia que explicar.

        ES EL FILTRO QUE FALTABA, y su ausencia era lo que producia los unicos "exitos" del
        detector. Volcando el almacen al terminar lp85 con el harness real, las 8 relaciones
        retenidas eran [26,20]->[26,29], [26,17]->[26,26], [26,20]->[26,41], [26,17]->[26,38],
        [26,32]->[26,41], [26,29]->[26,38] (todas en la fila 26, todas disparadas por el mismo
        click en (47,25)) mas dos en la columna 23. Es UN repintado de franja partido en pedazos
        por la agrupacion por firma, con la separacion Chebyshev >= 8 entre extremos convirtiendolo
        en "no local". Y la confirmacion intervencional era trivialmente cierta: repetir el click
        vuelve a repintar la franja.

        Lo que separa un boton de una franja NO es la distancia entre los extremos -- una franja
        larga tambien la tiene -- sino el HUECO: entre el boton y la puerta no cambia nada, y a lo
        largo de la franja cambia todo cada pocas celdas. Por eso el criterio es la conectividad
        del cambio: si en ese paso hay una cadena de regiones activas que va del origen al destino
        saltando menos de `SEPARACION_CHEBYSHEV_MINIMA` cada vez, es una franja."""
        pasos = self._historial.pasos_de(candidato.mascara)
        if not pasos:
            return True
        origen = candidato.origen.id
        destino = candidato.destino.id
        encadenadas = 0
        for paso in pasos:
            if candidato.desfase == 0:
                mapa = componentes[paso]
            elif paso + 1 < len(componentes):
                # En desfase 1 el destino cambia al paso SIGUIENTE: la franja, si existe, se lee
                # ahi (el origen suele seguir activo mientras el cambio se propaga).
                mapa = componentes[paso + 1]
            else:
                continue
            a = mapa.get(origen)
            b = mapa.get(destino)
            if a is not None and a == b:
                encadenadas += 1
        return encadenadas - FRACCION_EXPLICADA_POR_LOCALES * len(pasos) > 0.0

    def _explicado_por_locales(self, candidato: Candidato) -> bool:
        """Descarta el par si mas de la mitad de sus co-ocurrencias las explica ya el vocabulario
        LOCAL -- el mismo objeto que se traslado, o un unico cluster de cambios. Es el filtro que
        impide que un objeto en movimiento invente una relacion entre su celda vieja y la nueva, y
        corre con el detector REAL (`detectar_mecanica`), nunca con una aproximacion propia."""
        pasos = self._historial.pasos_de(candidato.mascara)
        if not pasos:
            return True
        caja_origen = candidato.origen.caja
        caja_destino = candidato.destino.caja
        # Corte temprano: en cuanto la mitad esta explicada el par ya esta descartado, y en cuanto
        # los pasos que quedan no alcanzan para llegar a la mitad ya esta salvado. Recorrer las
        # co-ocurrencias enteras era el segundo costo de la mineria.
        necesarias = len(pasos) // 2 + 1
        explicadas = 0
        for indice, paso in enumerate(pasos):
            if explicadas - necesarias >= 0:
                return True
            if explicadas + (len(pasos) - indice) - necesarias < 0:
                return False
            if self._historial.explicado_por_locales(paso, caja_origen, caja_destino):
                explicadas += 1
            elif candidato.desfase == 1 and paso + 1 < self._historial.pasos:
                # En desfase 1 la traslacion que explica el par puede estar detectada en el paso
                # SIGUIENTE (el objeto se termina de mover ahi): mirar solo el paso de origen
                # dejaria pasar justo el confound que este filtro existe para atrapar.
                if self._historial.explicado_por_locales(paso + 1, caja_origen, caja_destino):
                    explicadas += 1
        return explicadas > FRACCION_EXPLICADA_POR_LOCALES * len(pasos)

    @staticmethod
    def _supera_al_nulo_empirico(candidato: Candidato, pasos: int) -> bool:
        candidato.umbral_del_nulo = umbral_del_nulo_empirico(
            candidato.origen.firma, candidato.destino.firma, candidato.desfase, pasos
        )
        return candidato.soporte > candidato.umbral_del_nulo

    def _con_accion(self, candidato: Candidato) -> RelacionNoLocal | None:
        """Exige que la co-activacion este ligada a UNA accion (pureza >= 0,8) -- y, si esa accion
        lleva COORDENADA, tambien a UNA coordenada. Es el filtro de mejor rendimiento medido y el
        puente con la via intervencional: sin algo repetible no hay nada que probar.

        LA COORDENADA NO ES OPCIONAL CUANDO EXISTE, y esto salio de una medicion en vivo, no de la
        teoria: corriendo lp85 con el harness real, las 8 relaciones retenidas eran todas de click
        y las 8 quedaron refutadas en su PRIMERA repeticion. No porque fueran falsas, sino porque
        la intervencion clickeaba el centro de la region ORIGEN -- que en lag 0 es un EFECTO del
        click, no el lugar donde se clickeo. Repetir "ACTION6" sin su coordenada no repite nada, y
        un test que no puede salir bien no es un test: es una refutacion automatica disfrazada."""
        pasos_de_la_mascara = self._historial.pasos_de(candidato.mascara)
        conteo = self._historial.acciones_de(candidato.mascara)
        if not conteo:
            return None
        accion, veces = max(conteo.items(), key=lambda par: (par[1], par[0]))
        pureza = veces / candidato.soporte
        if pureza - PUREZA_MINIMA_DE_ACCION < 0.0:
            return None
        # LA PUREZA DE COORDENADA SE MIDE SOBRE LOS PASOS DE LA ACCION DOMINANTE, no sobre el
        # soporte total, y solo se exige si la accion dominante LLEVA coordenada. Con el
        # denominador anterior, UNA sola co-activacion caida bajo un ACTION6 suelto borraba una
        # relacion de teclado perfectamente pura: medido, la partida positiva del propio test suite
        # con 1 de 14 pulsaciones cambiada por un click pasaba de 1 relacion retenida a 0. En una
        # politica exploratoria que clickea seguido ese es el caso COMUN, y explica que las 8
        # relaciones retenidas en lp85 fueran todas de click: no es que el mundo sea asi, es que el
        # filtro eliminaba las de teclado. Perder sensibilidad en silencio no es conservadurismo.
        pasos_dominantes = [
            paso for paso in pasos_de_la_mascara if self._historial.accion_de(paso) == accion
        ]
        coordenadas: dict[tuple[int, int], int] = {}
        for paso in pasos_dominantes:
            donde = self._historial.coordenada_de(paso)
            if donde is not None:
                coordenadas[donde] = coordenadas.get(donde, 0) + 1
        coordenada = None
        if coordenadas:
            coordenada, repeticiones = max(coordenadas.items(), key=lambda par: (par[1], par[0]))
            if repeticiones - PUREZA_MINIMA_DE_ACCION * len(pasos_dominantes) < 0.0:
                # La accion lleva coordenada pero las co-activaciones vienen de celdas distintas:
                # no hay una intervencion unica que repetir, asi que la relacion no se retiene.
                return None
        return RelacionNoLocal(
            origen=candidato.origen,
            destino=candidato.destino,
            desfase=candidato.desfase,
            soporte=candidato.soporte,
            esperado=candidato.esperado,
            fuerza=math.log(candidato.soporte / candidato.esperado),
            p_valor=candidato.p_valor,
            umbral_del_nulo=candidato.umbral_del_nulo,
            accion=accion,
            pureza=pureza,
            coordenada=coordenada,
        )

    # -- superficie de consumo -----------------------------------------------------------------

    def relaciones(self) -> tuple[RelacionNoLocal, ...]:
        return tuple(self._relaciones)

    def submetas(self) -> tuple[SubMeta, ...]:
        """Sub-metas accionables para la politica. Piden las DOS cosas: veredicto INTERVENCIONAL
        (3 de 4 repeticiones, con control suficiente y tasa base baja) y piso de evidencia.

        EL PISO SOLO NO ALCANZABA. Con soporte alto el aporte observacional satura y cancela el
        prior, y UN solo exito dejaba la evidencia en 0,77 -- por encima de 0,55. En la corrida de
        lp85 habia relaciones con `exitos=1, fallos=0` y confirmacion "observacional" emitiendo
        sub-meta: exactamente lo que la regla de 3 de 4 existe para impedir."""
        salida = [
            SubMeta(
                accion=r.accion,
                coordenada=r.coordenada,
                caja_origen=r.origen.caja,
                caja_destino=r.destino.caja,
                desfase=r.desfase,
                fuerza=r.fuerza,
                soporte=r.soporte,
                evidencia=r.evidencia,
                confirmacion=r.confirmacion,
            )
            for r in self._relaciones
            if r.confirmacion == "intervencional"
            and r.evidencia - PISO_DE_EVIDENCIA_PARA_SUBMETA >= 0.0
        ]
        salida.sort(key=lambda s: (-s.evidencia, -s.fuerza))
        return tuple(salida)

    def diagnostico(self) -> dict[str, int]:
        """Conteo por etapa del pipeline. Es la unica forma honesta de reportar "no encontro nada":
        un cero al final, con el numero de cada filtro al lado, dice DONDE murio la senal.

        Los tres ultimos campos son los que faltaban para que esa honestidad fuera real: una
        transicion descartada por forma, un reinicio por cambio de nivel y una excepcion capturada
        por el llamador producian antes el MISMO reporte que "no hay senal"."""
        salida = dict(self._diagnostico)
        salida["descartadosPorForma"] = self._historial.descartados_por_forma
        salida["reiniciosPorForma"] = self._historial.reinicios_por_forma
        salida["excepcionesDelLlamador"] = self._excepciones_del_llamador
        salida["transicionesNoOfrecidas"] = self._transiciones_no_ofrecidas
        # `pasos` es una FOTO del momento de la ultima mineria (se mina cada N pasos, asi que al
        # terminar la partida queda corto); `pasosRegistrados` es el conteo VIVO. Sin los dos, la
        # cuenta no cerraba: medido en lp85, `pasos` decia 160 sobre 200 transiciones ofrecidas y
        # los 39 restantes parecian perdidos cuando en realidad estaban registrados.
        salida["pasosRegistrados"] = self._historial.pasos
        return salida

    def resumen(self) -> dict[str, object]:
        return {
            "diagnostico": self.diagnostico(),
            "intervencionesGastadas": self._intervenciones_gastadas,
            "relaciones": [r.resumen() for r in self._relaciones],
            "submetas": len(self.submetas()),
        }


# ============================== arc_agent/world_model/mechanics_memory.py ==============================
"""[arc-agi3-kaggle-agent/world_model/mechanics_memory] BL.21561 -- memoria de mecanicas POR ACCION
y por EPISODIO, construida sobre `detectar_mecanica`. Puerto de
arc-agi-runner/src/worldModel/mechanicsMemory.ts.

POR ACCION acumula la firma de mecanica observada como distribucion Beta -- alpha son las veces que
la accion volvio a hacer LO MISMO, beta las veces que hizo otra cosa. Nunca un booleano: en
ARC-AGI-3 una accion de movimiento choca contra la pared cada tantos pasos y ahi no mueve nada, y
con verificacion de cero tolerancia esa unica observacion mataba la regla correcta.

POR EPISODIO implementa los dos detectores que no son de transicion:
4. MARCO/HUD: las celdas que no cambiaron NUNCA. Su complemento -- el bbox de lo que si cambio
   alguna vez -- es la ARENA: todo lo de afuera es decorado.
5. CONTADOR: un color cuya cantidad de celdas se mueve siempre en el mismo sentido es puntaje o
   vidas: senal densa de progreso.
"""

from dataclasses import dataclass
from typing import Final





# Observaciones minimas de una accion antes de afirmar que su mecanica es conocida. 2 y no 1: una
# sola coincidencia no distingue una regla de una casualidad.
MIN_OBSERVACIONES_DE_MECANICA: Final[int] = 2

# Fraccion minima de observaciones que tienen que coincidir con la firma dominante. 0.6 deja pasar
# la regla de movimiento que falla contra la pared un tercio de las veces, y no la que acierta la
# mitad.
MIN_COBERTURA_DE_MECANICA: Final[float] = 0.6

# Cambios minimos de la cuenta de un color para llamarlo contador.
MIN_CAMBIOS_DE_CONTADOR: Final[int] = 3


@dataclass(frozen=True)
class HipotesisDeMecanica:
    action: str
    firma: str
    traslacion: Traslacion | None
    alpha: int
    beta: int
    observaciones: int
    cobertura: float


@dataclass(frozen=True)
class ContadorDeColor:
    color: int
    direccion: str
    cambios: int
    delta: int


class MechanicsMemory:
    def __init__(self) -> None:
        self._por_accion: dict[str, dict[str, object]] = {}
        self._cambio_alguna_vez: list[list[bool]] | None = None
        self._alto = 0
        self._ancho = 0
        self._observaciones_totales = 0
        self._conteo_anterior: dict[int, int] | None = None
        self._contadores: dict[int, dict[str, object]] = {}

    def observe(
        self, action: str, pre: Grid, post: Grid, mask: VolatilityMask | None = None
    ) -> Mecanica:
        """Registra el efecto de `action` y devuelve la mecanica detectada (logs y tests)."""
        mecanica = self._registrar_por_accion(action, pre, post, mask)
        self._registrar_celdas_cambiadas(pre, post, mask)
        self._registrar_contadores(post, mask)
        self._observaciones_totales += 1
        return mecanica

    def observe_evidencia_adicional(
        self, action: str, pre: Grid, post: Grid, mask: VolatilityMask | None = None
    ) -> Mecanica:
        """BL.22236 -- variante de `observe()` para evidencia INTERMEDIA: una transicion entre dos
        capas de animacion del MISMO frame (`state_signature.extraer_grid_multicapa`), no el
        pre/post asentado de la accion.

        Actualiza SOLO el detector 3 (hipotesis de mecanica por-accion, via
        `_registrar_por_accion`) y NO los detectores 4/5 (arena / contador), que son POR EPISODIO
        y describen el tablero ASENTADO: una celda que aparece y desaparece durante una animacion
        de "pouring" no es parte de la arena jugable ni de un contador de progreso monotono -- es
        evidencia de la MECANICA de la accion, que es justo lo que 13/25 juegos publicos esconden
        en capas intermedias. La hipotesis por-accion ya tolera evidencia ruidosa por diseno
        (Beta + `MIN_COBERTURA_DE_MECANICA=0.6`), asi que sumar observaciones intermedias no puede
        voltear una regla bien establecida por una minoria de capas transitorias."""
        return self._registrar_por_accion(action, pre, post, mask)

    def _registrar_por_accion(
        self, action: str, pre: Grid, post: Grid, mask: VolatilityMask | None
    ) -> Mecanica:
        mecanica = detectar_mecanica(pre, post, mask)
        firma = firma_de_mecanica(mecanica)

        registro = self._por_accion.setdefault(
            action, {"conteo": {}, "traslaciones": {}, "observaciones": 0}
        )
        registro["observaciones"] = int(registro["observaciones"]) + 1
        conteo: dict[str, int] = registro["conteo"]  # type: ignore[assignment]
        conteo[firma] = conteo.get(firma, 0) + 1
        if mecanica.traslacion_principal is not None:
            traslaciones: dict[str, Traslacion] = registro["traslaciones"]  # type: ignore[assignment]
            traslaciones[firma] = mecanica.traslacion_principal
        return mecanica

    def get_hypothesis(self, action: str) -> HipotesisDeMecanica | None:
        """Firma mas observada de `action` con su Beta. None si la accion nunca se observo."""
        registro = self._por_accion.get(action)
        if registro is None:
            return None
        conteo: dict[str, int] = registro["conteo"]  # type: ignore[assignment]
        # Desempate por firma (orden lexicografico) y no por orden de insercion: dos firmas
        # empatadas tienen que resolver igual aca y en el motor TypeScript.
        firma = sorted(conteo.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        aciertos = conteo[firma]
        observaciones = int(registro["observaciones"])
        traslaciones: dict[str, Traslacion] = registro["traslaciones"]  # type: ignore[assignment]
        return HipotesisDeMecanica(
            action=action,
            firma=firma,
            traslacion=traslaciones.get(firma),
            alpha=1 + aciertos,
            beta=1 + observaciones - aciertos,
            observaciones=observaciones,
            cobertura=aciertos / observaciones,
        )

    def get_direction(self, action: str) -> tuple[int, int] | None:
        """Direccion (dy,dx) CONFIRMADA de `action`, o None si no mueve nada / falta evidencia. Es
        el mapeo ACTION1..5 -> direccion que el DSL global nunca pudo dar sobre dato real."""
        h = self.get_hypothesis(action)
        if h is None or h.traslacion is None:
            return None
        if not h.firma.startswith("traslacion:"):
            return None
        if h.observaciones < MIN_OBSERVACIONES_DE_MECANICA:
            return None
        if h.cobertura < MIN_COBERTURA_DE_MECANICA:
            return None
        return (h.traslacion.dy, h.traslacion.dx)

    def get_movement_actions(self) -> list[str]:
        return [a for a in self._por_accion if self.get_direction(a) is not None]

    def is_inert_action(self, action: str) -> bool:
        """Accion cuya mecanica dominante es `sinCambio` con evidencia suficiente -- no-op
        observacional, sin pasar por la sintesis DSL."""
        h = self.get_hypothesis(action)
        if h is None:
            return False
        return (
            h.firma == "sinCambio"
            and h.observaciones >= MIN_OBSERVACIONES_DE_MECANICA
            and h.cobertura >= MIN_COBERTURA_DE_MECANICA
        )

    def get_active_bounding_box(self) -> BoundingBox | None:
        """DETECTOR 4 -- caja de lo que cambio alguna vez: la ARENA. Todo lo de afuera es marco
        estatico. None mientras no se observo ningun cambio."""
        if self._cambio_alguna_vez is None:
            return None
        ys: list[int] = []
        xs: list[int] = []
        for y in range(self._alto):
            for x in range(self._ancho):
                if self._cambio_alguna_vez[y][x]:
                    ys.append(y)
                    xs.append(x)
        if not ys:
            return None
        return BoundingBox(min_y=min(ys), max_y=max(ys), min_x=min(xs), max_x=max(xs))

    def get_static_cell_count(self) -> int:
        """DETECTOR 4 -- celdas que no cambiaron NUNCA en todo lo observado."""
        if self._cambio_alguna_vez is None:
            return 0
        return sum(1 for fila in self._cambio_alguna_vez for c in fila if not c)

    def is_static_cell(self, y: int, x: int) -> bool:
        if self._cambio_alguna_vez is None:
            return True
        if y < 0 or x < 0 or y >= self._alto or x >= self._ancho:
            return True
        return not self._cambio_alguna_vez[y][x]

    def get_counters(self) -> list[ContadorDeColor]:
        """DETECTOR 5 -- colores cuya cantidad de celdas se movio SIEMPRE en el mismo sentido."""
        salida: list[ContadorDeColor] = []
        for color in sorted(self._contadores):
            c = self._contadores[color]
            if c["roto"] or c["direccion"] is None:
                continue
            if int(c["cambios"]) < MIN_CAMBIOS_DE_CONTADOR:
                continue
            salida.append(
                ContadorDeColor(
                    color=color,
                    direccion=str(c["direccion"]),
                    cambios=int(c["cambios"]),
                    delta=int(c["delta"]),
                )
            )
        salida.sort(key=lambda c: (-c.cambios, c.color))
        return salida

    def get_observation_count(self) -> int:
        return self._observaciones_totales

    def _registrar_celdas_cambiadas(
        self, pre: Grid, post: Grid, mask: VolatilityMask | None
    ) -> None:
        alto = len(pre)
        ancho = len(pre[0]) if pre else 0
        if alto == 0 or ancho == 0:
            return
        # Un cambio de forma del frame reinicia el mapa: las coordenadas viejas ya no describen el
        # mismo tablero, y mezclarlas produciria una arena inventada.
        if self._cambio_alguna_vez is None or self._alto != alto or self._ancho != ancho:
            self._cambio_alguna_vez = [[False] * ancho for _ in range(alto)]
            self._alto = alto
            self._ancho = ancho
        for y in range(alto):
            fila = pre[y]
            fila_post = post[y] if y < len(post) else []
            for x in range(min(len(fila), ancho)):
                valor_post = fila_post[x] if x < len(fila_post) else None
                if fila[x] != valor_post and not is_volatile_cell(mask, y, x):
                    self._cambio_alguna_vez[y][x] = True

    def _registrar_contadores(self, post: Grid, mask: VolatilityMask | None) -> None:
        conteo: dict[int, int] = {}
        for y in range(len(post)):
            fila = post[y]
            for x in range(len(fila)):
                if is_volatile_cell(mask, y, x):
                    continue
                conteo[fila[x]] = conteo.get(fila[x], 0) + 1
        anterior = self._conteo_anterior
        self._conteo_anterior = conteo
        if anterior is None:
            return
        for color in set(anterior) | set(conteo):
            antes = anterior.get(color, 0)
            ahora = conteo.get(color, 0)
            if antes == ahora:
                continue
            direccion = "sube" if ahora > antes else "baja"
            estado = self._contadores.setdefault(
                color, {"direccion": None, "cambios": 0, "delta": 0, "roto": False}
            )
            if estado["direccion"] is not None and estado["direccion"] != direccion:
                estado["roto"] = True
            if estado["direccion"] is None:
                estado["direccion"] = direccion
            estado["cambios"] = int(estado["cambios"]) + 1
            estado["delta"] = int(estado["delta"]) + (ahora - antes)


# ============================== arc_agent/world_model/program_coverage.py ==============================
"""[arc-agi3-kaggle-agent/world_model/program_coverage] BL.21561 -- cuanto de la evidencia explica
un programa del DSL. Puerto de arc-agi-runner/src/worldModel/programCoverage.ts; separado de
synthesis.py por el mismo motivo que alla (limite de tamano de archivo) pero conceptualmente parte
de la sintesis: es el criterio con el que se acepta o se descarta una hipotesis.

POR QUE DEJO DE SER UN BOOLEANO. `verify_program` exigia que TODAS las observaciones encajaran con
cero contradicciones, asi que una regla CORRECTA moria en la primera observacion que no encajaba
-- y en ARC-AGI-3 esa observacion llega siempre: es el choque contra la pared. "Mover a la
izquierda" explica 9 de cada 10 pasos y falla el decimo porque el cursor ya estaba pegado al borde;
con cero tolerancia el agente concluye que no entiende la accion y vuelve a explorar al azar. La
cobertura puntuada conserva la regla y manda los fallos a la Beta(alpha, beta), que es donde el
modelo de mundo ya representa la incertidumbre.
"""

from dataclasses import dataclass
from typing import Any, Final, NamedTuple




# Cobertura minima para aceptar un programa como hipotesis vigente. Por debajo, la "regla" no
# explica ni dos de cada tres observaciones: es ruido y conviene decir None.
MIN_PROGRAM_COVERAGE: Final[float] = 0.6


@dataclass(frozen=True)
class Observation:
    """Un par (pre, post) observado para una misma accion. Vive aca y no en synthesis.py porque
    este modulo es el que lo consume primero; synthesis.py lo re-exporta para no cambiarle el
    import a ningun consumidor."""

    pre: Grid
    post: Grid

    def to_dict(self) -> dict[str, Grid]:
        return {"pre": self.pre, "post": self.post}

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Observation":
        return Observation(pre=raw["pre"], post=raw["post"])


class ProgramCoverage(NamedTuple):
    aciertos: int
    fallos: int
    # aciertos / (aciertos + fallos). Sin observaciones vale 1 (nada que contradiga).
    cobertura: float


def program_coverage(
    program: Program,
    observations: list[Observation],
    ctx: PrimitiveContext | None = None,
) -> ProgramCoverage:
    """Cuenta cuantas observaciones reproduce el programa y cuantas no -- la evidencia con la que
    se alimenta la Beta(alpha, beta) de la transicion."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    aciertos = 0
    fallos = 0
    for obs in observations:
        if grids_equal(apply_program(program, obs.pre, ctx), obs.post):
            aciertos += 1
        else:
            fallos += 1
    total = aciertos + fallos
    return ProgramCoverage(
        aciertos=aciertos, fallos=fallos, cobertura=1.0 if total == 0 else aciertos / total
    )


def cobertura_suficiente(
    program: Program,
    observations: list[Observation],
    ctx: PrimitiveContext | None = None,
    min_coverage: float = MIN_PROGRAM_COVERAGE,
) -> ProgramCoverage | None:
    """Igual que `program_coverage` pero ABANDONA en cuanto el candidato ya no puede llegar a
    `min_coverage` (devuelve None). Es lo que mantiene el costo de la sintesis donde estaba: la
    verificacion de cero tolerancia cortaba en el PRIMER fallo, y contar siempre las N
    observaciones multiplicaba por N el precio de descartar un candidato malo.

    Recorre de la observacion MAS NUEVA a la mas vieja: tras una contradiccion, la evidencia que
    descarta al candidato suele ser la ultima, asi que el abandono llega en el primer paso."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    total = len(observations)
    if total == 0:
        return ProgramCoverage(aciertos=0, fallos=0, cobertura=1.0)
    fallos_tolerados = int(total * (1 - min_coverage))
    aciertos = 0
    fallos = 0
    for obs in reversed(observations):
        if grids_equal(apply_program(program, obs.pre, ctx), obs.post):
            aciertos += 1
        else:
            fallos += 1
            if fallos > fallos_tolerados:
                return None
    return ProgramCoverage(aciertos=aciertos, fallos=fallos, cobertura=aciertos / total)


def verify_program(
    program: Program,
    observations: list[Observation],
    ctx: PrimitiveContext | None = None,
) -> bool:
    """Verificacion de CERO tolerancia. Sigue siendo la regla dura para preguntas de "esto encaja
    exacto?" -- por ejemplo, si la hipotesis vigente sobrevive a la ultima observacion. La
    SELECCION de hipotesis ya no la usa: ver `synthesize_program_scored` en synthesis.py. Sin
    observaciones devuelve True, misma semantica que Array.every sobre una lista vacia."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    return all(grids_equal(apply_program(program, obs.pre, ctx), obs.post) for obs in observations)


# ============================== arc_agent/world_model/synthesis.py ==============================
"""[arc-agi3-kaggle-agent/world_model/synthesis] -- sintesis bottom-up de programas del DSL:
busqueda de composiciones cortas (profundidad <=3-4) que expliquen TODAS las observaciones
(pre, post) sin contradicciones, rankeadas por prior de Occam (longitud + simplicidad de params).
Puerto de arc-agi-runner/src/worldModel/synthesis.ts (BL.20860 + BL.20861 + BL.21026/BL.21029).

Estrategia de busqueda (2 niveles, ver enumerate_structural_steps en primitives.py para el
razonamiento completo):
1. Tier "finisher": los propose_* de primitives.py ya se auto-verifican contra UN par -- si alguno
   explica pre->post en un solo paso, listo (camino rapido, cubre la mayoria de transformaciones
   ARC reales).
2. Si ningun paso unico alcanza: busqueda en anchura acotada que expande con pasos
   "estructurales" ciegos (enumerate_structural_steps, sin necesitar el post) y en CADA nodo nuevo
   reintenta el finisher data-driven para cerrar la brecha con un ultimo paso "semantico"
   (recolor/floodFill/overlay/conditionalRecolor/cropToBBox/objectExtract).

Por que los presupuestos estan en unidades de CELDAS y no de nodos: el costo de un nodo es
proporcional al AREA de su grilla intermedia, y `replicate` (hasta 3x3) la infla -- una 64x64 pasa
a 192x192, y compuesta a profundidad 2 a 576x576 (331k celdas). Medido contra la API oficial de
ARC-AGI-3: 40-110 SEGUNDOS por decision, creciendo con los pasos. Un tope de expansiones solo NO
acota nada porque los nodos no cuestan igual entre si.

Por que el barrido de ENTRADA se cobra aparte (max_seed_sweep_cells) y los finishers de adentro de
la BFS no: sobre una grilla por encima de max_structural_search_area la busqueda retorna ANTES de
descontar expansiones o celdas, asi que el contador compartido de synthesize_program nunca bajaba y
cada semilla del historial pagaba un barrido entero -- medido en 64x64, 22ms con 1 observacion y
1861ms con 100, crecimiento LINEAL con lo aprendido (BL.21026). Los finishers, en cambio, ya estan
acotados por expansiones y celdas: cobrarlos contra la misma perilla recortaria la busqueda en
grillas chicas ~40x (un finisher sobre una intermedia inflada cuesta 10x lo que el nodo).
"""

from dataclasses import dataclass
from functools import cmp_to_key
from typing import Any, Final, NamedTuple

# Cada import relativo va en UNA sola linea, nunca partido entre parentesis: el builder del
# notebook de Kaggle los desmonta con una regex de LINEA (^from \.\w* import .+$) y un import
# multilinea dejaria las lineas de adentro sueltas, rompiendo el .ipynb de submission.







# Profundidad de pasos ESTRUCTURALES ciegos antes del finisher final -- combinada con el finisher
# da una profundidad total de programa de hasta max_depth+1 (3 structural + 1 finisher = 4).
DEFAULT_MAX_DEPTH: Final[int] = 3

# Tope duro de expansiones de nodos. NO alcanza por si solo (ver docstring de modulo): los
# presupuestos que de verdad acotan el tiempo estan en celdas.
MAX_NODE_EXPANSIONS: Final[int] = 2000

# Trabajo total permitido por busqueda, en celdas de grillas intermedias procesadas.
DEFAULT_MAX_CELLS_TOUCHED: Final[int] = 2_000_000

# Un nodo cuya grilla intermedia supera este multiplo del area objetivo se poda. Multiplo generoso
# a proposito: una composicion valida PUEDE necesitar agrandar y despues recortar (replicate ->
# cropToBBox). 4x deja pasar replicate 2x2 y corta el 3x3 y los encadenamientos, que son los que
# explotan. La busqueda ya era incompleta por diseno; esto la hace incompleta de forma ACOTADA Y
# MEDIBLE en vez de lenta.
DEFAULT_MAX_INTERMEDIATE_AREA_RATIO: Final[int] = 4

# Area maxima de grilla para la que se intenta la BFS estructural CIEGA. Por encima solo corre el
# tier data-driven de profundidad 1. No es una heuristica de escritorio: medido contra la API
# oficial sobre tr87-cd924810, en 10 transiciones reales de 64x64 la BFS profunda explico CERO y
# costo entre 6 y 56 segundos cada vez (profundidad 1: 12-196ms, tambien cero). El motivo es de
# dominio -- en ARC-AGI-3 una accion produce un cambio LOCAL y semantico (un cursor que se mueve,
# una celda que cambia), no una transformacion geometrica de la grilla entera, que es lo unico que
# la enumeracion ciega sabe expresar. 1024 = 32x32 deja pasar entera la busqueda para ARC-AGI-1/2
# (<=30x30), donde las transformaciones globales SI son la respuesta.
DEFAULT_MAX_STRUCTURAL_SEARCH_AREA: Final[int] = 1024

# Cuantas pasadas sobre la grilla cuesta UN barrido de propose_all_steps -- una por proposer
# data-driven. Cobra el barrido en las MISMAS unidades (celdas) que max_cells_touched, de modo que
# las dos perillas sean comparables entre si.
PROPOSER_PASSES_PER_SWEEP: Final[int] = 10

# Trabajo total permitido en barridos de ENTRADA (ver docstring de modulo, BL.21026/BL.21029).
# 500k celdas ~= 12 semillas de 64x64 (4096 celdas x 10 proposers = 40960 c/u), o sea ~225ms de
# techo por decision. Las semillas se prueban de la mas reciente a la mas vieja -- que es donde
# suele estar la evidencia util -- asi que lo que se corta es la cola larga del historial.
DEFAULT_MAX_SEED_SWEEP_CELLS: Final[int] = 500_000


@dataclass(frozen=True)
class SynthesisBudget:
    """Presupuesto de una busqueda. Inyectable para que el harness offline de Kaggle (9h totales,
    sin internet) pueda aflojarlo y una corrida en vivo contra la API pueda apretarlo, sin tocar
    la logica de busqueda."""

    max_node_expansions: int = MAX_NODE_EXPANSIONS
    max_cells_touched: int = DEFAULT_MAX_CELLS_TOUCHED
    max_intermediate_area_ratio: int = DEFAULT_MAX_INTERMEDIATE_AREA_RATIO
    max_structural_search_area: int = DEFAULT_MAX_STRUCTURAL_SEARCH_AREA
    max_seed_sweep_cells: int = DEFAULT_MAX_SEED_SWEEP_CELLS

    def to_dict(self) -> dict[str, int]:
        return {
            "maxNodeExpansions": self.max_node_expansions,
            "maxCellsTouched": self.max_cells_touched,
            "maxIntermediateAreaRatio": self.max_intermediate_area_ratio,
            "maxStructuralSearchArea": self.max_structural_search_area,
            "maxSeedSweepCells": self.max_seed_sweep_cells,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "SynthesisBudget":
        return SynthesisBudget(
            max_node_expansions=raw.get("maxNodeExpansions", MAX_NODE_EXPANSIONS),
            max_cells_touched=raw.get("maxCellsTouched", DEFAULT_MAX_CELLS_TOUCHED),
            max_intermediate_area_ratio=raw.get(
                "maxIntermediateAreaRatio", DEFAULT_MAX_INTERMEDIATE_AREA_RATIO
            ),
            max_structural_search_area=raw.get(
                "maxStructuralSearchArea", DEFAULT_MAX_STRUCTURAL_SEARCH_AREA
            ),
            max_seed_sweep_cells=raw.get("maxSeedSweepCells", DEFAULT_MAX_SEED_SWEEP_CELLS),
        )


DEFAULT_SYNTHESIS_BUDGET: Final[SynthesisBudget] = SynthesisBudget()


@dataclass(frozen=True)
class SynthesisUsage:
    """Consumo REAL de una busqueda, en unidades de presupuesto. Existe para que el costo se pueda
    afirmar de forma DETERMINISTA: medir milisegundos contra umbrales fijos falla bajo contencion
    de CPU ajena sin que haya regresion alguna (BL.21029). Un contador de unidades mide el TRABAJO,
    que es lo que el presupuesto acota, y no depende de la maquina que lo corra."""

    expansions_used: int
    cells_used: int
    # Celdas de barridos de ENTRADA -- lo que se cobra contra max_seed_sweep_cells.
    seed_sweep_cells_used: int
    # Barridos data-driven totales, de entrada y finishers. Observabilidad, no se cobra.
    proposer_sweeps: int
    # Alguna perilla corto la busqueda antes de agotar el espacio alcanzable.
    budget_exhausted: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "expansionsUsed": self.expansions_used,
            "cellsUsed": self.cells_used,
            "seedSweepCellsUsed": self.seed_sweep_cells_used,
            "proposerSweeps": self.proposer_sweeps,
            "budgetExhausted": self.budget_exhausted,
        }


def _area_of(grid: Grid) -> int:
    return len(grid) * (len(grid[0]) if grid else 0)


@dataclass
class _BudgetCounter:
    """Contador MUTABLE de presupuesto restante. Existe para que synthesize_program pueda repartir
    UN unico presupuesto entre todas sus semillas en vez de darle uno entero a cada una. Nunca se
    expone: los callers pasan un SynthesisBudget inmutable y cada uno arranca con el suyo."""

    expansions_left: int
    cells_left: int
    seed_sweep_cells_left: int
    max_intermediate_area_ratio: int
    max_structural_search_area: int
    expansions_used: int = 0
    cells_used: int = 0
    seed_sweep_cells_used: int = 0
    proposer_sweeps: int = 0


@dataclass
class _SynthesisNode:
    """Nodo de la frontera de la BFS estructural: el programa acumulado y la grilla que produce.

    El nombre lleva el modulo adentro y NO es un generico "nodo de busqueda": planner.py tiene su
    propio nodo de busqueda (grid/path/g) y el builder del notebook de Kaggle aplana los modulos
    en UN solo namespace, donde el ultimo en definirse le pisaria la clase al otro y el
    constructor del perdedor explotaria en runtime dentro de la submission."""

    program: Program
    grid: Grid


def _counter_from(budget: SynthesisBudget) -> _BudgetCounter:
    return _BudgetCounter(
        expansions_left=budget.max_node_expansions,
        cells_left=budget.max_cells_touched,
        seed_sweep_cells_left=budget.max_seed_sweep_cells,
        max_intermediate_area_ratio=budget.max_intermediate_area_ratio,
        max_structural_search_area=budget.max_structural_search_area,
    )


def _usage_from(counter: _BudgetCounter) -> SynthesisUsage:
    return SynthesisUsage(
        expansions_used=counter.expansions_used,
        cells_used=counter.cells_used,
        seed_sweep_cells_used=counter.seed_sweep_cells_used,
        proposer_sweeps=counter.proposer_sweeps,
        budget_exhausted=_sin_credito_para_otra_semilla(counter),
    )


def _sin_credito_para_la_bfs(counter: _BudgetCounter) -> bool:
    """Corte de la BFS ciega: solo las perillas que ella consume. NO mira el credito de semillas --
    si lo hiciera, el barrido de entrada que se acaba de cobrar podria apagar la BFS de esa misma
    semilla, que tiene expansiones y celdas de sobra."""
    return counter.expansions_left <= 0 or counter.cells_left <= 0


def _sin_credito_para_otra_semilla(counter: _BudgetCounter) -> bool:
    """Corte del loop de semillas de synthesize_program. Suma el credito de barridos de entrada:
    sin eso, sobre una grilla por encima de max_structural_search_area la BFS retorna sin gastar
    nada, el contador queda intacto para siempre y el historial entero se recorre a costo lineal
    (BL.21026)."""
    return _sin_credito_para_la_bfs(counter) or counter.seed_sweep_cells_left <= 0


def _sweep_seed_proposers(
    pre: Grid, post: Grid, ctx: PrimitiveContext, counter: _BudgetCounter
) -> list[ProgramStep]:
    """Barrido de ENTRADA (profundidad 1), cobrado contra el presupuesto compartido de la sintesis.
    Devuelve vacio -- sin recorrer la grilla -- cuando ya no queda credito: eso es lo que corta la
    cola larga del historial de observaciones."""
    if counter.seed_sweep_cells_left <= 0:
        return []
    costo = max(_area_of(pre), _area_of(post)) * PROPOSER_PASSES_PER_SWEEP
    counter.seed_sweep_cells_left -= costo
    counter.seed_sweep_cells_used += costo
    counter.proposer_sweeps += 1
    return propose_all_steps(pre, post, ctx)


def _sweep_finisher_proposers(
    pre: Grid, post: Grid, ctx: PrimitiveContext, counter: _BudgetCounter
) -> list[ProgramStep]:
    """Barrido "finisher" dentro de la BFS. No se cobra -- ya lo acotan expansiones y celdas --
    pero se cuenta para poder afirmar el trabajo total sin cronometro."""
    counter.proposer_sweeps += 1
    return propose_all_steps(pre, post, ctx)


def program_complexity(program: Program) -> int:
    """Puntaje de complejidad para el ranking Occam: la LONGITUD domina (menos pasos = mejor), y a
    igual longitud se prefiere el programa mas "general" -- menos parametros hardcodeados
    (mappings chicos, desplazamientos cortos, predicados simples)."""
    score = len(program) * 1000
    for step in program:
        name = step["name"]
        params = step["params"]
        if name == "translate":
            score += abs(params["dx"]) + abs(params["dy"])
        elif name == "recolor":
            # Primitivo mas general para un swap de color puro (sin dependencia posicional) --
            # costo bajo para que gane el desempate frente a conditionalRecolor cuando ambos
            # explican el mismo par (border/interior coinciden con "todas las celdas" cuando esas
            # celdas resultan estar todas en el borde, ambiguedad tipica con una sola observacion).
            score += len(params["mapping"])
        elif name == "floodFill":
            score += 3
        elif name == "conditionalRecolor":
            # predicate 'all' es redundante con recolor(mapping) para un swap de un solo color --
            # se penaliza mas fuerte. border/interior expresan semantica POSICIONAL que recolor no
            # puede capturar; siguen costando mas que recolor para que este gane los empates, pero
            # se eligen igual cuando son la UNICA explicacion disponible (recolor no sobrevive).
            score += 5 if params["predicate"] == "all" else 3
        elif name == "objectExtract":
            score += 1 if "color" in params else 0
        elif name == "replicate":
            score += params["timesX"] + params["timesY"]
        elif name in ("reflect", "rotate", "cropToBBox", "overlay"):
            score += 1
    return score


def rank_programs(programs: list[Program]) -> list[Program]:
    """Ordena por Occam (complejidad ascendente) con desempate deterministico por clave
    serializada. No muta la entrada. sorted() es estable, igual que Array.prototype.sort en V8."""

    def comparar(a: Program, b: Program) -> int:
        diff = program_complexity(a) - program_complexity(b)
        if diff != 0:
            return diff
        return compare_program_keys(program_key(a), program_key(b))

    return sorted(programs, key=cmp_to_key(comparar))


def search_programs(
    pre: Grid,
    post: Grid,
    ctx: PrimitiveContext | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
) -> list[Program]:
    """Busca programas (composiciones bottom-up, profundidad acotada) que expliquen pre -> post
    para UN par observado -- devuelve todos los sobrevivientes encontrados, rankeados por Occam.
    Semilla de candidatos para synthesize_program, que despues verifica contra el historial
    COMPLETO de observaciones."""
    return search_programs_with_usage(pre, post, ctx, max_depth, budget).programs


class SearchResult(NamedTuple):
    programs: list[Program]
    usage: SynthesisUsage


def search_programs_with_usage(
    pre: Grid,
    post: Grid,
    ctx: PrimitiveContext | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
) -> SearchResult:
    """Igual que search_programs pero devuelve ademas el consumo de presupuesto. Es la unica forma
    de afirmar el costo sin cronometro (BL.21029). Arranca con un contador PROPIO (presupuesto
    fresco); synthesize_program*, en cambio, comparte el suyo entre semillas."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    counter = _counter_from(budget)
    programs = _search_with_counter(pre, post, ctx, max_depth, counter)
    return SearchResult(programs=programs, usage=_usage_from(counter))


def _search_with_counter(
    pre: Grid,
    post: Grid,
    ctx: PrimitiveContext,
    max_depth: int,
    counter: _BudgetCounter,
) -> list[Program]:
    # dict preserva orden de insercion, igual que un Map de JS.
    found: dict[str, Program] = {}

    if grids_equal(pre, post):
        found[program_key([])] = []
        return rank_programs(list(found.values()))

    for step in _sweep_seed_proposers(pre, post, ctx, counter):
        found[program_key([step])] = [step]
    if found:
        return rank_programs(list(found.values()))

    area_base = max(_area_of(pre), _area_of(post))

    # Grilla demasiado grande para que la BFS ciega valga lo que cuesta (ver
    # DEFAULT_MAX_STRUCTURAL_SEARCH_AREA). Devolver vacio aca NO es una perdida de capacidad: el
    # resultado con BFS sobre estas grillas tambien era vacio, solo que 40 segundos despues.
    if area_base > counter.max_structural_search_area:
        return []

    # Area maxima tolerada para una grilla intermedia. Se toma sobre el MAYOR entre pre y post: si
    # la transformacion buscada agranda (post > pre), el margen se mide contra el destino real.
    max_intermediate_area = area_base * counter.max_intermediate_area_ratio

    frontier: list[_SynthesisNode] = [_SynthesisNode(program=[], grid=pre)]

    depth = 0
    while depth < max_depth and not found and not _sin_credito_para_la_bfs(counter):
        next_frontier: list[_SynthesisNode] = []
        for node in frontier:
            if _sin_credito_para_la_bfs(counter):
                break
            for structural_step in enumerate_structural_steps(node.grid):
                if _sin_credito_para_la_bfs(counter):
                    break
                counter.expansions_left -= 1
                counter.expansions_used += 1

                next_grid = apply_step(structural_step, node.grid, ctx)
                next_area = _area_of(next_grid)
                # Poda ANTES de pagar el finisher: propose_all_steps recorre la grilla diez veces
                # (una por proposer), asi que un nodo inflado cuesta un orden de magnitud mas que
                # uno normal.
                if next_area > max_intermediate_area:
                    continue
                counter.cells_left -= next_area
                counter.cells_used += next_area

                next_program: Program = [*node.program, structural_step]

                for finisher_step in _sweep_finisher_proposers(next_grid, post, ctx, counter):
                    full_program: Program = [*next_program, finisher_step]
                    found[program_key(full_program)] = full_program

                next_frontier.append(_SynthesisNode(program=next_program, grid=next_grid))
        frontier = next_frontier
        depth += 1

    return rank_programs(list(found.values()))


def synthesize_program(
    observations: list[Observation],
    ctx: PrimitiveContext | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
) -> Program | None:
    """Sintetiza el MEJOR programa que explica las observaciones de una accion, o None si ninguna
    composicion de profundidad acotada llega al minimo de cobertura (BL.21561). Siembra la busqueda
    desde cada observacion, empezando por las mas recientes."""
    return synthesize_program_with_usage(observations, ctx, max_depth, budget).program


class SynthesisResult(NamedTuple):
    program: Program | None
    usage: SynthesisUsage


def synthesize_program_with_usage(
    observations: list[Observation],
    ctx: PrimitiveContext | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
) -> SynthesisResult:
    """Igual que synthesize_program pero devuelve ademas el consumo de presupuesto de la sintesis
    COMPLETA -- la unidad en la que se afirma que el costo no crece con el historial (BL.21029)."""
    scored = synthesize_program_scored(observations, ctx, max_depth, budget)
    return SynthesisResult(program=scored.program, usage=scored.usage)


def _sin_hipotesis(counter: "_BudgetCounter") -> "ScoredProgram":
    """Ningun candidato aceptable: cobertura 0 y el presupuesto ya consumido."""
    return ScoredProgram(None, 0, 0, 0.0, _usage_from(counter))


class ScoredProgram(NamedTuple):
    program: Program | None
    aciertos: int
    fallos: int
    cobertura: float
    usage: SynthesisUsage


def synthesize_program_scored(
    observations: list[Observation],
    ctx: PrimitiveContext | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
    min_coverage: float = MIN_PROGRAM_COVERAGE,
) -> ScoredProgram:
    """BL.21561 -- sintesis por COBERTURA PUNTUADA en vez de por verificacion de cero tolerancia:
    se acepta el programa que explica MAS observaciones (por encima de `min_coverage`) y se
    devuelven sus aciertos/fallos para que quien lo use los contabilice en alpha/beta.

    El presupuesto de busqueda NO cambia: el recorrido de semillas se sigue cortando en cuanto
    aparece un candidato de cobertura 1, la misma condicion de antes; los candidatos parciales se
    puntuan al pasar, sin gastar una expansion de mas.

    La IDENTIDAD (programa vacio) es la unica que se exige exacta: aceptarla parcialmente equivale
    a declarar no-op una accion que a veces SI hace algo, y eso la borra de la exploracion -- el
    lockout que BL.21500/BL.21501 tuvieron que desarmar."""
    ctx = ctx if ctx is not None else EMPTY_CONTEXT
    # El presupuesto es de la SINTESIS entera, no de cada semilla: si no fuera asi, el costo
    # creceria linealmente con el historial de observaciones (medido: 51s en el paso 2 y 110s en el
    # paso 8) y el agente se volveria mas lento cuanto mas aprende -- exactamente al reves.
    counter = _counter_from(budget)
    if not observations:
        return _sin_hipotesis(counter)

    # DOS PASADAS, y la primera es identica a la de antes de este BL. Pasada 1: verificacion de
    # cero tolerancia con corte en el primer fallo -- si hay un programa que explica TODO se
    # devuelve sin pagar un centavo mas que el codigo viejo (es el caso comun). Pasada 2, SOLO si
    # la pasada 1 no encontro nada -- o sea, exactamente cuando el codigo viejo devolvia None --:
    # se puntua por cobertura a los candidatos YA enumerados, sin volver a buscar.
    candidatos: dict[str, Program] = {}
    exactos: dict[str, Program] = {}
    seed_order = list(reversed(observations))

    for seed in seed_order:
        # Corta tambien por el tier data-driven: en grillas por encima de
        # max_structural_search_area la BFS retorna sin gastar expansiones ni celdas, asi que ESTA
        # es la unica perilla que frena el recorrido del historial (BL.21026).
        if _sin_credito_para_otra_semilla(counter):
            break
        for candidate in _search_with_counter(seed.pre, seed.post, ctx, max_depth, counter):
            key = program_key(candidate)
            if key in candidatos:
                continue
            candidatos[key] = candidate
            if verify_program(candidate, observations, ctx):
                exactos[key] = candidate
        if exactos:
            break

    if exactos:
        program = rank_programs(list(exactos.values()))[0]
        return ScoredProgram(
            program=program,
            aciertos=len(observations),
            fallos=0,
            cobertura=1.0,
            usage=_usage_from(counter),
        )

    parciales: dict[str, tuple[Program, ProgramCoverage]] = {}
    for key, program in candidatos.items():
        # La IDENTIDAD no se acepta parcialmente: equivale a declarar no-op una accion que a veces
        # SI hace algo (el lockout de BL.21500/BL.21501). Si fuera exacta ya habria salido arriba.
        if len(program) == 0:
            continue
        puntaje = cobertura_suficiente(program, observations, ctx, min_coverage)
        if puntaje is not None:
            parciales[key] = (program, puntaje)
    if not parciales:
        return _sin_hipotesis(counter)

    mejor_cobertura = max(p.cobertura for _, p in parciales.values())
    mejores = [prog for prog, p in parciales.values() if p.cobertura == mejor_cobertura]
    program = rank_programs(mejores)[0]
    puntaje = parciales[program_key(program)][1]
    return ScoredProgram(
        program=program,
        aciertos=puntaje.aciertos,
        fallos=puntaje.fallos,
        cobertura=puntaje.cobertura,
        usage=_usage_from(counter),
    )


# ============================== arc_agent/world_model/transition_memory.py ==============================
"""[arc-agi3-kaggle-agent/world_model/transition_memory] -- modelo de mundo tipo STRIPS aprendido
POR ACCION: mantiene observaciones (pre, post) capadas y sintetiza (synthesis.py) el programa DSL
que las explica sin contradicciones. Confianza como distribucion Beta (alpha=exitos, beta=fracasos)
-- NUNCA un booleano. Puerto de arc-agi-runner/src/worldModel/transitionMemory.ts (BL.20860).

Shape de KnownTransition espejado a proposito del futuro `prometheusActivityMemory.
knownTransitions[]`: el campo `program` de una KnownTransition ES el programa verificado de
synthesis.py, no un sistema paralelo. Esta clase vive SOLO en memoria del proceso (un episodio de
juego) -- la persistencia entre episodios es responsabilidad de una wave posterior.
"""

from dataclasses import dataclass
from typing import Any, Final

# Imports relativos en UNA sola linea a proposito: submission/build_notebook.py los desmonta con
# `^from \.\w* import .+$` (regex de una linea) y la forma con parentesis dejaria los nombres
# sueltos y un `)` colgando dentro del notebook de Kaggle -- SyntaxError en la submission.








# Tope de observaciones retenidas POR ACCION -- eviction FIFO simple (la mas nueva reemplaza a la
# mas vieja). Analogo acotado a la eviction por confidence x recencia x generalidad prevista para
# la coleccion persistente; aca alcanza con no crecer sin cota dentro de un episodio.
MAX_OBSERVATIONS_PER_ACTION: Final[int] = 20

# Profundidad de sintesis usada al re-sintetizar tras cada observacion -- ver synthesis.py.
SYNTHESIS_MAX_DEPTH: Final[int] = 3

# BL.21501 -- observaciones minimas antes de que un programa-identidad cuente como no-op a efectos
# de EXCLUIR la accion (ver `is_known_no_op`). Port del fix de BL.21500 en el runner TS, hecho
# ANTES de cablear este motor a la inferencia: con 1 sola observacion, `synthesize_program`
# devuelve el programa vacio en cuanto ve un pre==post (la identidad explica esa unica observacion
# a la perfeccion) y la accion quedaba descartada para siempre. Medido en juego real con el motor
# TS: ACTION6 -- el click -- se probo una vez en el paso 2 y no volvio a usarse en 76 pasos.
MIN_OBSERVATIONS_FOR_NO_OP: Final[int] = 3

# BL.21558 -- cuantas REVISIONES de la mascara de volatilidad disparan una re-sintesis completa
# (todas las acciones, no solo la observada). Hace falta porque la mascara es una PREMISA de cada
# hipotesis: un programa sintetizado antes de saber que el contador del HUD era ruido explica ese
# ruido, y queda congelado si la accion no vuelve a observarse -- que es exactamente lo que pasa,
# porque un programa no trivial la manda al fondo del ranking de exploracion. El tope acota el
# costo (una sintesis por accion y por revision); la mascara converge en las primeras decenas de
# pasos, asi que 10 revisiones cubren de sobra el arranque.
MAX_MASK_REVISIONS_RESYNTHESIZED: Final[int] = 10


def _mask_observations(
    window: list[Observation], mask: VolatilityMask | None
) -> list[Observation]:
    """Aplica la mascara a una ventana: cada `post` pasa a tener, en las celdas volatiles, el mismo
    valor que su `pre`. Asi la sintesis solo tiene que explicar el cambio REAL del tablero -- y un
    paso que solo movio el contador queda como identidad, que es justo lo que habilita a detectar
    el no-op. Sin mascara devuelve la ventana tal cual (cero copias)."""
    if mask is None:
        return window
    return [
        Observation(pre=obs.pre, post=neutralize_volatile_cells(obs.pre, obs.post, mask))
        for obs in window
    ]


def _cobertura_de_beta(alpha: int, beta: int) -> float:
    """BL.21561 -- cobertura de la hipotesis VIGENTE derivada de su propia Beta: `alpha-1` son sus
    aciertos y `beta-1` sus fallos, contados desde que se sintetizo. Esta funcion en si NUNCA
    reaplica el programa a ninguna grilla -- es aritmetica pura sobre alpha/beta. BL.22237 corrigio
    la parte que si evitaba pagar ese costo: `record_observation` ahora SI reverifica la hipotesis
    vigente contra la ventana retenida completa (`cobertura_suficiente` sobre `masked_window`) antes
    de aceptar que "sigue vigente" -- verificar contra el registro ya grabado cuesta cero acciones
    reales, a diferencia de descubrir la misma contradiccion jugando en vivo."""
    aciertos = alpha - 1
    fallos = beta - 1
    total = aciertos + fallos
    return 1.0 if total <= 0 else aciertos / total


@dataclass(frozen=True)
class KnownTransition:
    """`program`: programa DSL verificado contra TODAS las observaciones retenidas -- None si aun
    no hay una hipotesis sin contradicciones (accion todavia no comprendida).
    `alpha`/`beta`: Beta(alpha, beta), exitos/fracasos de la hipotesis ACTUAL, no un booleano.
    `observation_count`: total de veces que se observo esta accion (crece mas alla de la ventana).
    `contradiction_count`: cuantas veces una hipotesis confirmada fue contradicha por evidencia
    nueva.
    `coverage` (BL.21561): fraccion de las observaciones RETENIDAS que el programa vigente
    reproduce. 1 = la regla no falla nunca (lo unico que antes se aceptaba); 0.8 = falla una de
    cada cinco, tipico de una regla de movimiento que choca contra la pared. 0 si no hay
    programa."""

    action: str
    program: Program | None
    alpha: int
    beta: int
    observation_count: int
    contradiction_count: int
    coverage: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "program": self.program,
            "alpha": self.alpha,
            "beta": self.beta,
            "observationCount": self.observation_count,
            "contradictionCount": self.contradiction_count,
            "coverage": self.coverage,
        }


class TransitionMemory:
    """`budget`, `max_observations` y `max_depth` son parametros aditivos con defaults que
    reproducen el TS exacto (alla son constantes de modulo). Estan expuestos porque el presupuesto
    de sintesis DEBE ser inyectable para el harness offline de Kaggle: dejarlos cerrados obligaria
    a tocar el motor mas tarde."""

    def __init__(
        self,
        ctx: PrimitiveContext | None = None,
        budget: SynthesisBudget = DEFAULT_SYNTHESIS_BUDGET,
        max_observations: int = MAX_OBSERVATIONS_PER_ACTION,
        max_depth: int = SYNTHESIS_MAX_DEPTH,
        mascara_de_accion_unica: bool = False,
    ) -> None:
        self._observations: dict[str, list[Observation]] = {}
        self._transitions: dict[str, KnownTransition] = {}
        self._ctx: PrimitiveContext = ctx if ctx is not None else EMPTY_CONTEXT
        self._budget = budget
        self._max_observations = max_observations
        self._max_depth = max_depth
        # BL.21558 -- que celdas del frame cambian sin relacion con la accion (HUD/contador). Vive
        # aca y no en la politica porque se aprende del MISMO flujo de observaciones que alimenta
        # la sintesis: una sola fuente, imposible que las dos se desincronicen.
        # BL.21702 -- `mascara_de_accion_unica` viaja por parametro desde `policy.py` (la palanca
        # `mascaraDeAccionUnica` de banderas.py): world_model/ no importa banderas, ver el
        # comentario en VolatilityTracker.__init__.
        self._volatility = VolatilityTracker(permitir_accion_unica=mascara_de_accion_unica)
        # BL.21561 -- analizador OBJETO-CENTRICO. Corre sobre el MISMO flujo de observaciones que
        # la sintesis DSL y es el que de verdad nombra la mecanica de la accion: en dato real el
        # DSL confirma la identidad y nada mas, mientras que este recupera el mapeo ACTION1..4 ->
        # arriba/abajo/izquierda/derecha en los cuatro juegos medidos.
        self._mechanics = MechanicsMemory()
        self._mask_version_sincronizada = 0
        self._revisiones_resintetizadas = 0

    def record_observation(self, action: str, pre: Grid, post: Grid) -> Mecanica:
        """Registra el efecto observado de `action`: pre -> post. Actualiza (o sintetiza desde
        cero) la KnownTransition de esa accion, y DEVUELVE la mecanica de objetos detectada en esa
        transicion (BL.21590: la creencia de direcciones la necesita y calcularla de nuevo en la
        politica seria correr el mismo detector dos veces por paso). Las grillas se guardan POR
        REFERENCIA, sin clonar (igual que el TS): quien llama no debe mutar las grillas que entrego,
        o la ventana de observaciones describiria un pasado que nunca ocurrio.

        BL.21558 -- la ventana guarda las grillas CRUDAS y el enmascarado se aplica recien al
        sintetizar/verificar. Guardar ya neutralizado seria un bug sutil: la mascara CRECE durante
        el episodio y las observaciones viejas habrian quedado congeladas con una mascara mas
        chica, o sea con ruido de HUD adentro que ninguna hipotesis puede explicar."""
        self._volatility.observe(action, pre, post)

        window = self._observations.get(action, [])
        window.append(Observation(pre=pre, post=post))
        if len(window) > self._max_observations:
            window.pop(0)
        self._observations[action] = window

        mask = self._volatility.mask
        # BL.21561 -- el analizador objeto-centrico ve el par CRUDO con la mascara vigente: no
        # necesita que le neutralicen nada porque ya ignora las celdas volatiles el mismo.
        mecanica = self._mechanics.observe(action, pre, post, mask)

        masked_window = _mask_observations(window, mask)
        last_observation = masked_window[-1]

        # La mascara cambio: toda hipotesis vigente se dedujo bajo OTRAS premisas y hay que
        # rehacerla. Sin esto el fix no llega a la partida -- una accion observada antes de que la
        # mascara existiera se queda con un programa que "explica" el avance del contador, y ese
        # programa no trivial la manda al fondo del ranking de exploracion.
        mascara_cambio = self._volatility.version != self._mask_version_sincronizada
        if mascara_cambio:
            self._mask_version_sincronizada = self._volatility.version
            if self._revisiones_resintetizadas < MAX_MASK_REVISIONS_RESYNTHESIZED:
                self._revisiones_resintetizadas += 1
                self._resintetizar_otras_acciones(action, mask)

        previous = self._transitions.get(action)
        observation_count = (previous.observation_count if previous else 0) + 1
        alpha = previous.alpha if previous else 1
        beta = previous.beta if previous else 1
        contradiction_count = previous.contradiction_count if previous else 0
        program = previous.program if previous else None
        coverage = previous.coverage if previous else 0.0

        had_confirmed = previous is not None and previous.program is not None
        # Con la mascara recien cambiada NO se acepta la hipotesis previa aunque verifique contra
        # la ultima observacion: se dedujo mirando celdas que ahora se sabe que son ruido.
        coincide_con_la_ultima = (
            had_confirmed
            and not mascara_cambio
            and verify_program(previous.program, [last_observation], self._ctx)
        )
        # BL.22237 -- coincidir con la ultima observacion YA NO ALCANZA: una hipotesis puede pasar
        # ese chequeo y sin embargo contradecir una observacion MAS VIEJA que sigue retenida en la
        # ventana, sin que nada lo detecte hasta que falle de nuevo EN VIVO -- gastando una accion
        # real para descubrir una contradiccion que ya estaba en la propia memoria. Es la capacidad
        # que la ablacion aislada de Rodionov/SingularityNET mide con MAYOR impacto (~99% RHAE,
        # tambien nombrada "Retrodict"): verificar contra el registro YA GRABADO cuesta cero
        # acciones reales. Se revalida entonces contra la VENTANA RETENIDA COMPLETA
        # (`masked_window`, hasta MAX_OBSERVATIONS_PER_ACTION), con la MISMA tolerancia que ya usa
        # la sintesis puntuada (BL.21561): identidad EXACTA -- aceptarla a medias equivale a
        # declarar no-op una accion que a veces SI hace algo -- y el resto hasta
        # MIN_PROGRAM_COVERAGE, el mismo umbral, fuente de la verdad unica. `cobertura_suficiente`
        # abandona temprano (recorre de la mas nueva a la mas vieja), asi que el costo de este
        # chequeo extra no es sistematicamente 20x -- solo lo paga completo una hipotesis que de
        # verdad sigue siendo buena.
        cobertura_retenida = (
            cobertura_suficiente(
                previous.program,
                masked_window,
                self._ctx,
                1.0 if len(previous.program) == 0 else MIN_PROGRAM_COVERAGE,
            )
            if coincide_con_la_ultima
            else None
        )
        still_holds = cobertura_retenida is not None

        if still_holds:
            # alpha/beta se recalculan contra la ventana COMPLETA en vez de incrementarse a
            # ciegas: antes `beta` quedaba CONGELADO en el valor de la ultima resintesis y
            # `coverage` nunca podia volver a 1.0 aunque la observacion que la contradijo ya
            # hubiera salido de la ventana por FIFO -- `is_known_no_op` excluia esa accion de la
            # exploracion PARA SIEMPRE por una contradiccion que la propia memoria ya olvido.
            alpha = 1 + cobertura_retenida.aciertos
            beta = 1 + cobertura_retenida.fallos
        else:
            # Una hipotesis descartada por CAMBIO DE PREMISAS (la mascara) no es una contradiccion
            # de la evidencia: no dice nada sobre lo predecible que es la accion, y contarla como
            # fracaso hundiria la confianza de acciones que nunca fallaron.
            if had_confirmed and not mascara_cambio:
                contradiction_count += 1
            # BL.21561 -- se acepta el programa de MAYOR cobertura y sus fallos se contabilizan en
            # beta en vez de matar la hipotesis. alpha/beta describen la hipotesis VIGENTE, y esta
            # es NUEVA: se recalculan desde su propia evidencia, con prior Beta(1,1).
            puntuado = synthesize_program_scored(
                masked_window, self._ctx, self._max_depth, self._budget
            )
            program = puntuado.program
            alpha = 1 + puntuado.aciertos
            beta = 1 + puntuado.fallos
        coverage = 0.0 if program is None else _cobertura_de_beta(alpha, beta)

        self._transitions[action] = KnownTransition(
            action=action,
            program=program,
            alpha=alpha,
            beta=beta,
            observation_count=observation_count,
            contradiction_count=contradiction_count,
            coverage=coverage,
        )
        return mecanica

    def get_transition(self, action: str) -> KnownTransition | None:
        return self._transitions.get(action)

    def get_known_transitions(self) -> list[KnownTransition]:
        # Orden de primera insercion: el dict de Python se comporta como el Map de JS.
        return list(self._transitions.values())

    def get_confidence(self, action: str) -> float:
        """Confianza actual (0-1) en la hipotesis vigente de `action`. Prior uniforme (0.5) si
        nunca se observo."""
        t = self._transitions.get(action)
        if t is None:
            return 0.5
        return t.alpha / (t.alpha + t.beta)

    def predict(self, action: str, grid: Grid) -> Grid | None:
        """Predice el resultado de aplicar `action` sobre `grid` usando el programa confirmado --
        None si la accion aun no tiene una hipotesis sin contradicciones."""
        t = self._transitions.get(action)
        if t is None or t.program is None:
            return None
        return apply_program(t.program, grid, self._ctx)

    def is_known_no_op(self, action: str) -> bool:
        """True si la accion tiene un programa confirmado que es la identidad (no cambia nada) Y
        hay evidencia suficiente -- no-op conocido, el equivalente de `no_op_actions` en policy.py
        pero derivado del MISMO mecanismo de sintesis, no de un chequeo separado.

        BL.21501: exige MIN_OBSERVATIONS_FOR_NO_OP observaciones. La SINTESIS sigue concluyendo
        identidad con una sola (y `predict` lo refleja); lo que cambia es cuando esa conclusion
        habilita a EXCLUIR la accion de la exploracion. Sin esto, cablear este motor a la politica
        reintroduciria el lockout que BL.21500 (runner TS) y BL.21518 (politica Python) acaban de
        eliminar -- en ARC-AGI-3 una accion parametrizada por coordenada es no-op donde no hay
        nada y significativa en otro lado."""
        t = self._transitions.get(action)
        if t is None or t.program is None or len(t.program) != 0:
            return False
        # BL.21561 -- con cobertura puntuada, un programa puede ser "el que mejor explica" sin
        # explicar todo. Para EXCLUIR una accion se sigue exigiendo evidencia exacta: una identidad
        # que falla una de cada cinco veces significa que la accion SI hace algo a veces.
        if t.coverage < 1:
            return False
        # Y si el analizador objeto-centrico vio a esta accion mover un objeto, no es un no-op por
        # mas que la ventana retenida de la sintesis diga identidad.
        if self._mechanics.get_direction(action) is not None:
            return False
        return t.observation_count >= MIN_OBSERVATIONS_FOR_NO_OP

    def get_observation_count(self, action: str) -> int:
        t = self._transitions.get(action)
        return t.observation_count if t is not None else 0

    def declarar_acciones_disponibles(self, cantidad_de_acciones: int) -> None:
        """BL.21702 -- le informa al rastreador de volatilidad cuantos botones OFRECE el juego. Es
        lo que habilita el modo de accion unica de la mascara en los seis juegos publicos que
        exponen `availableActions=[6]`."""
        self._volatility.declarar_vocabulario(cantidad_de_acciones)

    def get_volatility_mask(self) -> VolatilityMask | None:
        """BL.21558 -- mascara de volatilidad vigente (None mientras no haya evidencia suficiente).
        La expone la politica para firmar estados y comparar frames sobre las MISMAS celdas que el
        modelo de mundo considera informativas."""
        return self._volatility.mask

    def get_volatility_version(self) -> int:
        """Version del conjunto de celdas volatiles -- cambia cuando la mascara cambia. Quien
        compare dos firmas calculadas en momentos distintos tiene que verificar que sean de la
        MISMA version, o estaria comparando hashes de dos definiciones de "estado"."""
        return self._volatility.version

    def get_volatile_cell_count(self) -> int:
        """Celdas actualmente enmascaradas -- solo para observabilidad (logs y tests de efecto)."""
        return self._volatility.volatile_cell_count()

    def get_mechanic(self, action: str) -> HipotesisDeMecanica | None:
        """BL.21561 -- mecanica de objetos dominante de `action` (traslacion / recoloreo /
        aparicion / desaparicion / sinCambio) con su Beta. None si nunca se observo."""
        return self._mechanics.get_hypothesis(action)

    def get_movement_direction(self, action: str) -> tuple[int, int] | None:
        """BL.21561 -- direccion (dy,dx) que `action` imprime al objeto controlado, o None si no
        mueve nada / falta evidencia. ES el mapeo ACTION1..5 -> direccion que el DSL global nunca
        pudo dar sobre dato real."""
        return self._mechanics.get_direction(action)

    def get_mechanics_memory(self) -> MechanicsMemory:
        """BL.21561 -- analizador objeto-centrico completo: detectores de marco estatico (4) y de
        contadores monotonos (5), ademas de las hipotesis por accion."""
        return self._mechanics

    def analyze_transition(self, pre: Grid, post: Grid) -> Mecanica:
        """BL.21561 -- mecanica detectada para un par suelto, sin registrarla."""
        return detectar_mecanica(pre, post, self._volatility.mask)

    def _resintetizar_otras_acciones(
        self, actual: str, mask: VolatilityMask | None
    ) -> None:
        """Rehace la hipotesis de todas las acciones MENOS la observada (esa la rehace el flujo
        normal de `record_observation`, que ya tiene la ventana actualizada). Se sintetiza sobre la
        ventana cruda reenmascarada, y la confianza vuelve al prior: alpha y beta describen los
        exitos/fracasos de la hipotesis VIGENTE, y esta es otra."""
        for accion, window in self._observations.items():
            if accion == actual:
                continue
            previa = self._transitions.get(accion)
            if previa is None:
                continue
            puntuado = synthesize_program_scored(
                _mask_observations(window, mask), self._ctx, self._max_depth, self._budget
            )
            alpha = 1 + puntuado.aciertos
            beta = 1 + puntuado.fallos
            self._transitions[accion] = KnownTransition(
                action=previa.action,
                program=puntuado.program,
                alpha=alpha,
                beta=beta,
                observation_count=previa.observation_count,
                contradiction_count=previa.contradiction_count,
                coverage=0.0 if puntuado.program is None else _cobertura_de_beta(alpha, beta),
            )


# ============================== arc_agent/world_model/planner.py ==============================
"""[arc-agi3-kaggle-agent/world_model/planner] -- planificacion con busqueda acotada (variante de
A-estrella) sobre el modelo de mundo aprendido (transition_memory.py), con profundidad ligada al
presupuesto de acciones restante. ANYTIME: si no hay plan completo dentro del presupuesto, cae a
greedy sobre la heuristica de distancia-al-objetivo. Puerto de
arc-agi-runner/src/worldModel/planner.ts (BL.20860).

Heuristica: estimate_distance combina un termino ESPACIAL (distancia Manhattan entre las esquinas
superior-izquierda de los bounding boxes de foreground de `grid` y `goal`) con la distancia de
Hamming cruda (cell_diff_count). El termino de Hamming solo no sirve de guia para navegar un objeto
puntual (queda constante hasta el paso exacto que lo alinea); el termino espacial da gradiente
continuo. La suma NO es necesariamente admisible en sentido estricto de A-estrella (una sola accion
puede cambiar muchas celdas a la vez, ej. recolor global) -- esto es busqueda SATISFICING:
encuentra un plan valido rapido, no garantiza el mas corto posible.
"""

from dataclasses import dataclass
from typing import Any, Protocol

# Imports relativos en UNA sola linea a proposito: submission/build_notebook.py los desmonta con
# `^from \.\w* import .+$` (regex de una linea) y la forma con parentesis dejaria los nombres
# sueltos y un `)` colgando dentro del notebook de Kaggle -- SyntaxError en la submission.




class TransitionPredictor(Protocol):
    """Lo UNICO que el planner necesita de la memoria de transiciones. Se declara como Protocol en
    vez de importar TransitionMemory por dos razones: (1) mantiene el planner testeable con un
    doble trivial, (2) el builder del notebook de Kaggle aplana los modulos en un solo namespace y
    un import relativo de dos puntos no sobrevive al stripping. TransitionMemory lo satisface
    ESTRUCTURALMENTE, sin herencia ni registro."""

    def predict(self, action: str, grid: Grid) -> Grid | None: ...


@dataclass(frozen=True)
class PlanOptions:
    """Las acciones son str ("ACTION1", ...): el caller convierte desde GameAction, el world model
    no conoce el enum del wire format."""

    current_grid: Grid
    available_actions: list[str]
    memory: TransitionPredictor
    goal_grid: Grid
    # Profundidad estructural maxima del plan. Default efectivo 6.
    max_depth: int | None = None
    # Acciones restantes reales del episodio -- acota la profundidad efectiva (nunca planifica mas
    # alla de lo que el presupuesto permite gastar). Default efectivo: max_depth.
    budget: int | None = None
    # Tope duro de nodos expandidos, independiente del branching real. Default efectivo 500.
    max_expansions: int | None = None


@dataclass(frozen=True)
class PlanResult:
    """`plan`: secuencia completa de acciones hasta el goal, si se encontro dentro del presupuesto;
    [] si ya se esta en el goal; None si no se encontro plan completo.
    `fallback_action` (ANYTIME): mejor accion individual (la que mas reduce la heuristica en un
    paso) entre las acciones con efecto conocido -- solo presente cuando `plan` es None. None si
    ninguna accion conocida aporta progreso medible (el llamador debe caer a active learning).
    `current_distance`: heuristica de distancia del estado actual al goal (diagnostico)."""

    plan: list[str] | None
    current_distance: int
    fallback_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        # `fallbackAction` se OMITE cuando es None -- replica el drop de `undefined` que hace
        # JSON.stringify en el TS, para que el JSON del fixture sea byte a byte el mismo.
        salida: dict[str, Any] = {"plan": self.plan, "currentDistance": self.current_distance}
        if self.fallback_action is not None:
            salida["fallbackAction"] = self.fallback_action
        return salida


def estimate_distance(grid: Grid, goal: Grid) -> int:
    """Heuristica espacial + residual (ver docstring de modulo). Publica a proposito (es privada
    en el TS): es una ley afirmable directamente contra fixtures, sin pasar por una busqueda."""
    residual = cell_diff_count(grid, goal)
    ancho_grid = len(grid[0]) if grid else 0
    ancho_goal = len(goal[0]) if goal else 0
    if len(grid) != len(goal) or ancho_grid != ancho_goal:
        return residual
    # El fondo se toma del GOAL, no de grid: el objetivo define que es "figura" y que es "fondo".
    bg = detect_background_color(goal)
    bbox_grid = foreground_bounding_box(grid, bg)
    bbox_goal = foreground_bounding_box(goal, bg)
    if bbox_grid is None or bbox_goal is None:
        return residual
    spatial = abs(bbox_grid.min_x - bbox_goal.min_x) + abs(bbox_grid.min_y - bbox_goal.min_y)
    return spatial + residual


def _pick_greedy_fallback(
    current_grid: Grid,
    known_actions: list[str],
    memory: TransitionPredictor,
    goal_grid: Grid,
) -> str | None:
    best_action: str | None = None
    best_distance = estimate_distance(current_grid, goal_grid)
    for action in known_actions:
        predicted = memory.predict(action, current_grid)
        if predicted is None:
            continue
        distance = estimate_distance(predicted, goal_grid)
        # Estricto: una accion que empata la distancia actual no es progreso medible.
        if distance < best_distance:
            best_distance = distance
            best_action = action
    return best_action


@dataclass
class _SearchNode:
    grid: Grid
    path: list[str]
    g: int


def plan_actions(opts: PlanOptions) -> PlanResult:
    max_depth = opts.max_depth if opts.max_depth is not None else 6
    max_expansions = opts.max_expansions if opts.max_expansions is not None else 500
    budget = opts.budget if opts.budget is not None else max_depth
    effective_depth = max(0, min(max_depth, budget))

    current_grid = opts.current_grid
    goal_grid = opts.goal_grid
    memory = opts.memory

    current_distance = estimate_distance(current_grid, goal_grid)
    if grids_equal(current_grid, goal_grid):
        # El 0 es literal (no current_distance): estar en el goal es distancia cero por definicion.
        return PlanResult(plan=[], current_distance=0)

    known_actions = [
        a for a in opts.available_actions if memory.predict(a, current_grid) is not None
    ]

    if effective_depth == 0 or not known_actions:
        return PlanResult(
            plan=None,
            current_distance=current_distance,
            fallback_action=_pick_greedy_fallback(current_grid, known_actions, memory, goal_grid),
        )

    frontier: list[_SearchNode] = [_SearchNode(grid=current_grid, path=[], g=0)]
    visited: set[int] = {hash_grid(current_grid)}
    expansions = 0

    while frontier and expansions < max_expansions:
        # Reordena la frontera ENTERA en cada vuelta y saca el primero. Es lo que hace el TS
        # (frontier.sort + shift): ineficiente, pero el desempate ante f-scores iguales depende del
        # orden de insercion, y el sort estable de Python coincide con el de V8. Cambiarlo por un
        # heap elegiria otro nodo ante empates y el plan dejaria de ser el mismo.
        frontier.sort(key=lambda n: n.g + estimate_distance(n.grid, goal_grid))
        node = frontier.pop(0)

        if grids_equal(node.grid, goal_grid):
            return PlanResult(plan=node.path, current_distance=current_distance)
        if node.g >= effective_depth:
            continue

        for action in known_actions:
            if expansions >= max_expansions:
                break
            # Se cuenta ANTES de predecir: la prediccion es el trabajo que el tope acota.
            expansions += 1
            predicted = memory.predict(action, node.grid)
            if predicted is None:
                continue
            h = hash_grid(predicted)
            if h in visited:
                continue
            visited.add(h)
            frontier.append(_SearchNode(grid=predicted, path=[*node.path, action], g=node.g + 1))

    return PlanResult(
        plan=None,
        current_distance=current_distance,
        fallback_action=_pick_greedy_fallback(current_grid, known_actions, memory, goal_grid),
    )


# ============================== arc_agent/world_model/state_signature.py ==============================
"""[arc-agi3-kaggle-agent/world_model/state_signature] -- firma hasheable de un estado (grilla +
acciones disponibles) y deteccion de no-ops entre frames sucesivos. Puerto de
arc-agi-runner/src/worldModel/stateSignature.ts (BL.20860).

Misma idea que policy.py::compute_signature, pero sobre el tipo Grid del world model y con un hash
entero estable y portable: NO se usa el hash() de Python, que esta aleatorizado por proceso via
PYTHONHASHSEED y por lo tanto no es reproducible entre corridas ni comparable contra un fixture.
"""

from collections.abc import Sequence
from typing import Final, Protocol

# MASK32 se importa de grid.py (fuente unica de la aritmetica de 32 bits del motor): Python tiene
# enteros de precision arbitraria y sin la mascara el hash divergiria del TS al primer overflow.


# Constante de mezcla de la familia Fibonacci hashing (2^32 / phi), la misma del TS.
_GOLDEN_RATIO_32: Final[int] = 0x9E3779B9


class FrameLike(Protocol):
    """Lo UNICO que este modulo necesita del wire format ARC-AGI-3. Protocol en vez de importar
    FrameData desde `..types`: el builder del notebook solo desmonta imports relativos de UN punto,
    asi que un import de dos puntos sobrevive al stripping y rompe el .ipynb de submission (que
    corre en namespace plano, sin paquetes). arc_agent.types.FrameData lo satisface
    ESTRUCTURALMENTE, sin herencia ni registro."""

    frame: Sequence[Sequence[Sequence[int]]]
    available_actions: Sequence[int]


def extract_grid(frame: "FrameLike") -> Grid | None:
    """Grilla observable de un frame: la API devuelve UNA O MAS capas consecutivas y la ultima es
    el estado visible tras aplicar el comando. None cuando el frame no trae capas o la ultima viene
    vacia -- ningun consumidor debe asumir grilla presente.

    Fuente unica: la usan la politica y el runner, que DEBEN coincidir en que es "el estado" o la
    firma persistida describiria otra cosa que la que vio quien decidio.

    La conversion a list[list[int]] es la frontera unica entre el wire format (FrameData guarda
    tuplas para ser hasheable) y el world model (listas mutables). La copia ademas protege la
    inmutabilidad del frame frente a los primitivos que mutan celdas por indice."""
    layers = frame.frame
    if not layers:
        return None
    last = layers[len(layers) - 1]
    if not last:
        return None
    return [list(row) for row in last]


def extraer_grid_multicapa(frame: "FrameLike") -> list[Grid]:
    """BL.22236 -- TODAS las capas OBSERVABLES de un frame, no solo la ultima (ver `extract_grid`).

    El wire oficial `arcengine.FrameData.frame` es `list[list[list[int]]]`: el motor acumula UNA
    capa por cada `step()` interno mientras la accion anima antes de asentarse
    (arcengine/base_game.py:210-253). `extract_grid` toma deliberadamente SOLO la ultima -- "el
    estado visible tras aplicar el comando" -- porque asi debe seguir siendo LA firma de estado
    (memoria de exploracion, no-ops, mascara de volatilidad: todas comparan el mismo "estado" o
    dejan de ser comparables entre si). Pero esa decision descarta evidencia real: el hilo de
    Kaggle discussion/734369 midio 13/25 juegos publicos con informacion que SOLO existe en una
    capa intermedia (ej. sp80, 624 pixeles visibles unicamente durante la animacion de "pouring").

    Esta funcion NO reemplaza `extract_grid` en ningun consumidor de firma -- expone las capas
    intermedias para que OTRO consumidor (memoria de mecanica objeto-centrica, BL.22236) las use
    como evidencia ADICIONAL de la transicion, nunca como el estado. Capas vacias se descartan
    (mismo criterio que `extract_grid`: ninguna vale como grilla)."""
    layers = frame.frame
    if not layers:
        return []
    return [[list(row) for row in layer] for layer in layers if layer]


def compute_frame_signature(
    frame: "FrameLike", mask: VolatilityMask | None = None
) -> str | None:
    """Firma de un frame completo, lista para persistir. Un frame sin grilla devuelve None en vez
    de una firma inventada: el campo ausente se trata como "sin evidencia" y no como "no hubo
    cambio" -- afirmar una firma falsa marcaria transiciones reales como no-ops."""
    grid = extract_grid(frame)
    if grid is None:
        return None
    return str(compute_state_signature(grid, frame.available_actions or [], mask))


def compute_state_signature(
    grid: Grid, available_actions: Sequence[int], mask: VolatilityMask | None = None
) -> int:
    """Firma entera estable de un estado -- combina el hash de la grilla con las acciones
    disponibles NORMALIZADAS (el orden no importa: se ordenan ascendente antes de mezclar). Dos
    frames con la MISMA firma se consideran el mismo estado a efectos de memoria de exploracion y
    deduplicacion de nodos visitados en el planner. Devuelve un entero SIN SIGNO en [0, 2**32).

    Por que esto reproduce el TS exactamente: en JS la suma es aritmetica de Number (exacta, todos
    los operandos caben en 2^53) y solo el ^ posterior aplica ToInt32. `hash << 6` en JS es un
    int32 con signo, pero la diferencia entre su lectura con y sin signo es exactamente 2**32, que
    se cancela al enmascarar la suma; y `hash >>> 2` con hash ya en [0, 2**32) es identico al >> 2
    de Python. El `hash >>> 0` final del TS equivale al & MASK32.

    BL.21558 -- `mask` firma SOLO las celdas estables. Sin ella, un contador de HUD que avanza en
    cada frame hace que ninguna firma se repita jamas y toda la memoria por-estado queda inerte. El
    default None conserva la firma historica exacta."""
    h = hash_grid_masked(grid, mask)
    for action in sorted(available_actions):
        mixed = (action + _GOLDEN_RATIO_32 + ((h << 6) & MASK32) + (h >> 2)) & MASK32
        h = (h ^ mixed) & MASK32
    return h


def is_no_op_transition(
    before: Grid | None, after: Grid | None, mask: VolatilityMask | None = None
) -> bool:
    """True cuando una accion NO cambio nada visible en la grilla -- no-op observado. None en
    cualquiera de los dos lados (sin grilla previa/actual conocida) nunca se afirma no-op: no hay
    evidencia suficiente.

    BL.21558 -- con `mask`, "nada visible" excluye las celdas volatiles. Ese es el punto: sin
    mascara, en ar25-0c556536 se detecto UN solo no-op en 77 pasos pese al round-robin contra las
    paredes del tablero."""
    if before is None or after is None:
        return False
    return grids_equal_masked(before, after, mask)


# ============================== arc_agent/prng.py ==============================
"""[arc-agi3-kaggle-agent/prng] BL.20783 -- PRNG semillado y deterministico. A diferencia de
projects/arc-agi-runner/src/prng.ts (BL.20775, mulberry32 escrito a mano), aca se usa
`random.Random(seed)` de la stdlib: mismo PRINCIPIO (mismo seed produce siempre la misma
secuencia, reproducible para replay) pero SIN portar el algoritmo mulberry32 bit a bit -- la
stdlib de Python ya es deterministica y esta bien probada; portar bit-twiddling a mano entre
lenguajes es fuente comun de bugs sutiles que tests superficiales no detectan."""

import random as _random_module
import time
from typing import Callable


def create_seeded_random(seed: str) -> Callable[[], float]:
    """Generador deterministico en [0, 1) -- mismo seed produce siempre la misma secuencia."""
    return _random_module.Random(seed).random


def generate_seed() -> str:
    """Seed nuevo no deterministico -- se persiste (ver runtime_report.py) para poder reproducir
    la corrida en un replay, mismo criterio que prng.ts::generateSeed en arc-agi-runner."""
    return f"{int(time.time() * 1000):x}-{_random_module.SystemRandom().getrandbits(32):x}"


# ============================== arc_agent/exploration_memory.py ==============================
"""[arc-agi3-kaggle-agent/exploration_memory] BL.21559 -- las dos piezas que rompen el ciclado de
la exploracion: COMPROMISO con la accion elegida (`MacroCommitment`) y NOVEDAD por conteo sobre la
firma enmascarada (`StateNoveltyTracker`). Espejo de `worldModel/macroCommitment.ts` y
`worldModel/stateNovelty.ts` del runner TS, donde vive la medicion completa.

EL DEFECTO, medido en produccion contra la API oficial de ARC-AGI-3. La distribucion de acciones por
partida era ciclado PERFECTO: ar25-0c556536 {A1:15, A2:16, A3:15, A4:16, A5:3, A6:3, A7:15};
ka59-38d34dbb {A1:24, A2:24, A3:23, A4:23, A6:6}; dc22-fdcac232 {A1:30, A2:29, A3:30, A4:30, A6:9}
-- con rachas de a lo sumo DOS pasos iguales en 83, 100 y 128 pasos. Sale de que el unico desempate
era "la menos visitada primero", que fuerza rotacion estricta. En un juego de desplazamiento es la
peor politica posible: arriba + abajo + izquierda + derecha se cancelan exacto y el agente termina el
episodio donde empezo. Random puro tiene mas varianza.

LAS DOS RESPUESTAS. (1) La macro convierte "probar ACTION1" en "avanzar hasta chocar": repite la
accion mientras siga produciendo cambio ENMASCARADO. (2) La novedad reemplaza el reparto parejo por
"ir donde no estuve": ordena por visitas del estado DESTINO, con las aristas nunca probadas primero.

POR QUE LAS DOS DEPENDEN DE LA MASCARA DE VOLATILIDAD (BL.21558 + BL.21559). Sin ella el frame
cambia en cada paso pase lo que pase -- la barra de progreso avanza una celda -- asi que "produjo
cambio" seria siempre verdadero y "estado nuevo" tambien: los dos criterios quedarian mudos.
"""

from dataclasses import dataclass, field
from typing import Callable, Iterable




# Import a UN solo nivel (`.world_model`, no `.world_model.state_signature`): el builder del
# notebook desmonta los imports relativos con el regex `^from \.\w* import .+$`, que no cubre un
# segundo punto -- con la forma anidada el notebook de submission queda con un ImportError.



def hubo_cambio_enmascarado(
    prev_grid: tuple[tuple[int, ...], ...] | None,
    current_grid: tuple[tuple[int, ...], ...] | None,
    mask: "VolatilityMask | None",
) -> bool:
    """La transicion cambio el tablero ignorando las celdas volatiles. Sin grilla en alguno de
    los dos lados no hay evidencia: se responde False, que es el lado del error que CORTA el
    compromiso de la macro en vez de sostenerlo a ciegas. (Vivia como metodo de la politica;
    BL.21593 lo mudo aca -- es memoria de exploracion, no decision.)"""
    if prev_grid is None or current_grid is None:
        return False
    return not grids_equal_masked(
        [list(fila) for fila in prev_grid],
        [list(fila) for fila in current_grid],
        mask,
    )

#: Tope de pasos consecutivos de una misma macro-accion. 8 es un compromiso medido: los episodios
#: reales duran 83-128 pasos, asi que una macro completa gasta ~7-10% del presupuesto -- suficiente
#: para cruzar un tablero tipico de ARC-AGI-3 y lo bastante corto como para que el episodio pruebe
#: del orden de una decena de macros. Subirlo arriesga monopolizar la partida con una sola accion;
#: bajarlo a 2-3 devuelve el problema original, porque cuatro direcciones que se alternan cada dos
#: pasos siguen cancelandose.
MACRO_MAX_STEPS = 8


#: BL.21518 -- probabilidad de reconsiderar los no-ops conocidos de un estado en una decision.
#: Sin esto el descarte es ABSORBENTE: una accion excluida no vuelve a elegirse desde ese estado,
#: por lo tanto no vuelve a observarse, por lo tanto el `discard` que la rehabilitaria jamas corre.
#: Y en ARC-AGI-3 el efecto de una accion depende del ESTADO GLOBAL del juego (una palanca inerte
#: empieza a servir cuando se abre una puerta), asi que "no hizo nada 2 veces" no es "no hara nada
#: nunca". Chico a proposito: reconsiderar es la excepcion, no la regla.
NOOP_REEXPLORATION_EPSILON = 0.05

#: BL.21559 -- probabilidad POR PASO del turno de reexploracion de no-ops. Es EL MISMO presupuesto de
#: BL.21518, medido donde corresponde: por paso de juego y no por decision. Con macro-acciones una
#: decision cubre hasta MACRO_MAX_STEPS pasos, asi que sortearlo por decision lo dividia por ocho y
#: los no-ops conocidos dejaban de reconsiderarse. Fuente unica: no se redefine el valor.
RECONSIDERATION_PER_STEP_EPSILON = NOOP_REEXPLORATION_EPSILON

#: BL.21518 -- observaciones no-op consecutivas antes de excluir una accion desde un estado.
#: 2 y no 1 porque una sola puede ser ruido del entorno (frame identico por lag, no por la accion);
#: mismo criterio que `SEED_MIN_NONOP_CONFIRMATIONS` del runner TS, que ya lo documentaba asi.
#: ACTION6 queda EXENTA (ver `_record_outcome` en policy.py): su efecto depende de la coordenada.
NO_OP_CONFIRMATIONS = 2

#: BL.21557 -- SENAL DENSA como RECOMPENSA EXTRINSECA. `FrameData` trae `levels_completed` desde
#: BL.20783 y la politica no lo miraba: exploraba con recompensa puramente INTRINSECA (novedad de
#: estado + menos-visitado), o sea que un ACTION3 que hizo SUBIR DE NIVEL valia exactamente lo mismo
#: que uno que no hizo nada. Es la misma ceguera que el runner TS tenia al persistir score binario
#: (BL.21557 lado A) y la que corrige el leaderboard oficial, cuyo `score` es ENTERO por niveles.
#: Nivel superado con exito = la mejor evidencia disponible de que una accion sirve.
#:
#: Cuantas decisiones conserva una accion su prioridad tras hacer subir de nivel. La marca NO es
#: permanente: los juegos de ARC-AGI-3 repiten estructura entre niveles, pero la MISMA accion desde
#: el MISMO estado no siempre vuelve a funcionar (el estado global cambio). Un valor alto convertiria
#: la recompensa en un lockout simetrico al que BL.21518 tuvo que desarmar del lado de los no-ops.
LEVEL_REWARD_PRIORITY_USES = 3

#: BL.21767 -- cuantas aplicaciones dura el CASTIGO de una accion que produjo GAME_OVER desde un
#: estado. El doble del credito de recompensa (LEVEL_REWARD_PRIORITY_USES) a proposito: la muerte
#: es la evidencia negativa mas fuerte que existe en la partida (la TERMINA, y con ella el rastro
#: del episodio), pero el descuento se agota igual -- fijarlo seria el lockout que BL.21518 tuvo
#: que desarmar del lado de los no-ops, y un mismo (estado, accion) puede ser mortal en un contexto
#: y necesario en otro (el estado global que la firma no ve pudo cambiar). El descuento se PONDERA
#: por evidencia: cada muerte lo re-arma, cada supervivencia observada del mismo par y cada
#: aplicacion en un ranking lo gastan.
CASTIGO_POR_MUERTE_USOS = 6


def compute_signature(frame: FrameData, mask: VolatilityMask | None = None) -> int:
    """Firma hasheable de un estado -- combina la grilla y las acciones disponibles. Dos frames
    con la MISMA firma se consideran el mismo estado a efectos de memoria de exploracion.

    BL.21558 -- con `mask` la firma ignora las celdas volatiles (HUD, contador de pasos). Sin eso,
    en los juegos publicos de ARC-AGI-3 NINGUNA firma se repite jamas (medido: 76 unicas en 78
    pasos, 94/94, 128/129, 100/101), asi que `_record_outcome` no puede detectar un solo no-op y
    toda la memoria por-estado de esta politica queda inerte. Sin mascara se conserva el hash de
    tuplas historico: es mas barato y no hay nada que neutralizar."""
    if mask is None:
        return hash((frame.frame, frame.available_actions))
    grid = [list(row) for row in frame.frame[-1]] if frame.frame else []
    return compute_state_signature(grid, frame.available_actions, mask)


@dataclass
class EntradaDeExploracion:
    """Lo que la politica recuerda de UN estado (una firma): que probo ahi, que resulto inutil y
    que le dio progreso real."""

    visits: dict[GameAction, int] = field(default_factory=dict)
    no_op_actions: set[GameAction] = field(default_factory=set)
    # BL.21518 -- observaciones no-op CONSECUTIVAS por accion desde este estado. Se resetea en
    # cuanto la accion cambia el frame: lo que importa es evidencia sostenida, no acumulada.
    no_op_streak: dict[GameAction, int] = field(default_factory=dict)
    # BL.21557 -- usos de prioridad que le quedan a cada accion que hizo subir de nivel desde este
    # estado (recompensa extrinseca). Se decrementa al elegirla; a 0 vuelve al ranking normal.
    reward_credits: dict[GameAction, int] = field(default_factory=dict)


def rank_candidates(
    available_actions: tuple[int, ...],
    visits: dict[GameAction, int],
    no_op_actions: set[GameAction],
    rng: Callable[[], float],
    rewarded_actions: set[GameAction] | None = None,
    novelty_key: Callable[[GameAction], tuple[int, ...]] | None = None,
    turno_reexploracion: bool | None = None,
    prior_de_arranque: bool = False,
    castigadas: set[GameAction] | None = None,
) -> list[GameAction]:
    """Ordena las acciones disponibles: filtra las que son no-op CONOCIDO desde este estado
    (salvo que eso vacie la lista -- nunca se queda sin candidatos), baraja de forma
    reproducible para romper empates sin sesgo posicional, y ordena por menos-visitado primero.

    BL.21557 -- `rewarded_actions` son las que HICIERON SUBIR DE NIVEL desde este estado (senal
    densa, recompensa extrinseca). Van al frente del ranking y nunca se filtran como no-op: una
    accion que produjo progreso real no puede ser "la que no hizo nada". La prioridad se aplica
    DESPUES del barajado y del sort, como particion estable, para no consumir numeros del `rng`:
    la reproducibilidad exacta de una partida dado su seed depende de que la secuencia del rng no
    varie con el contenido de la memoria.

    BL.21559 -- `novelty_key` reemplaza el desempate por menos-visitada por NOVEDAD: una tupla por
    accion que ordena primero las nunca probadas desde ESTE estado y despues por visitas del estado
    DESTINO. El conteo de visitas queda como ultimo criterio, solo para empates. Sin `novelty_key`
    rige el orden previo, intacto. `turno_reexploracion` deja que el llamador sortee el turno de los
    no-ops POR PASO en vez de por decision -- con macro-acciones una decision cubre hasta ocho pasos
    y el presupuesto se dividia por ocho (ver `RECONSIDERATION_PER_STEP_EPSILON`).

    BL.21560 -- `prior_de_arranque` agrega, SOLO en la primera decision de la partida, el orden de
    acciones por efectividad medida en partidas reales (ver `prioridad_por_priors`, que documenta por
    que no puede aplicarse siempre).

    BL.21767 -- `castigadas` son las que produjeron GAME_OVER desde este estado con descuento
    vigente (ver `MemoriaDeMuertes`). Van al FONDO del ranking como particion estable -- nunca se
    FILTRAN: relegar no es excluir, y si todas las candidatas estan castigadas el orden interno
    sobrevive y algo se elige igual. La particion se aplica despues del barajado y del sort, como
    la de `rewarded_actions`, para no consumir numeros del rng: la reproducibilidad por seed exige
    que la secuencia del rng no dependa del contenido de la memoria. Una accion premiada nunca se
    relega: el progreso real (subio de nivel) es evidencia mas fuerte y mas especifica que la del
    descuento, que ya se esta agotando solo."""
    candidates = [GameAction(f"ACTION{n}") for n in available_actions]
    premiadas = rewarded_actions or set()
    # Una accion premiada jamas se trata como no-op, venga la marca de la memoria de exploracion o
    # del modelo de mundo: la evidencia de progreso real gana sobre la de "no cambio el frame".
    no_op_actions = no_op_actions - premiadas
    # BL.21518: el epsilon se consume SIEMPRE, antes de ramificar, para que la secuencia del rng
    # dependa solo de la cantidad de decisiones y no de que acciones haya en memoria -- condicion
    # para que un mismo seed reproduzca la misma partida.
    sorteo = rng()
    reexplorar = sorteo < NOOP_REEXPLORATION_EPSILON if turno_reexploracion is None else turno_reexploracion
    if no_op_actions:
        conocidos = [a for a in candidates if a in no_op_actions]
        # Cuando toca reexplorar se elige ENTRE los no-ops, no entre todo: meterlos al pozo comun
        # no alcanza porque el sort de abajo desempata por menos-visitado y un no-op confirmado
        # siempre acumulo mas visitas, asi que quedaria ultimo y nunca saldria. Darles el turno
        # completo es lo unico que los devuelve al ciclo de observacion.
        if reexplorar and conocidos:
            candidates = conocidos
        else:
            filtered = [a for a in candidates if a not in no_op_actions]
            if filtered:
                candidates = filtered

    order = list(candidates)
    for i in range(len(order) - 1, 0, -1):
        j = int(rng() * (i + 1))
        order[i], order[j] = order[j], order[i]
    # BL.21560 -- `prioridad_por_priors` entra SOLO en el arranque en frio (ver `prior_de_arranque`).
    # `sort` es estable: dentro de un empate sobrevive el orden del barajado, igual que antes.
    prior = prioridad_por_priors if prior_de_arranque else (lambda _a: 0)
    if novelty_key is None:
        order.sort(key=lambda a: (visits.get(a, 0), prior(a)))
    else:
        order.sort(key=lambda a: (*novelty_key(a), visits.get(a, 0), prior(a)))
    # BL.21767 -- las castigadas al fondo ANTES de subir las premiadas: si una accion estuviera en
    # los dos conjuntos, la particion de premiadas (que corre despues) la devuelve al frente -- el
    # progreso real gana, mismo criterio que `no_op_actions - premiadas` mas arriba.
    relegadas = (castigadas or set()) - premiadas
    if relegadas:
        order = [a for a in order if a not in relegadas] + [a for a in order if a in relegadas]
    if premiadas:
        # Particion ESTABLE (no un sort nuevo): preserva el orden ya resuelto dentro de cada grupo.
        order = [a for a in order if a in premiadas] + [a for a in order if a not in premiadas]
    return order


_RANKING_DE_ACCIONES: dict[str, int] = {
    accion: i for i, accion in enumerate(CLICK_PRIORS["ordenAcciones"])
}


def prioridad_por_priors(accion: GameAction) -> int:
    """BL.21560 -- prioridad de una accion segun la efectividad MEDIDA en las partidas reales
    grabadas (`ordenAcciones` de priors.py, fraccion de pasos en que movio el tablero). Menor = mejor.

    SOLO SE APLICA EN LA PRIMERA DECISION DE LA PARTIDA (`prior_de_arranque`), y el motivo es una
    medicion: usarla como desempate permanente convierte la exploracion en una sola accion repetida.
    Cuando ninguna firma de estado se repite -- que es el caso de varios juegos publicos -- TODAS las
    acciones empatan en novedad y en visitas en TODOS los pasos, asi que el ultimo componente de la
    clave deja de ser un desempate y pasa a ser el criterio unico: medido sobre el escenario de
    desplazamiento de BL.21559, la racha maxima saltaba a 24 de 24 pasos con la misma accion.
    Un prior es para cuando no hay evidencia; en cuanto la hay, manda la evidencia."""
    return _RANKING_DE_ACCIONES.get(accion.value, len(_RANKING_DE_ACCIONES))


class MacroCommitment:
    """Compromiso con la accion elegida. UNA instancia por partida: el compromiso vive ENTRE
    decisiones, que es justamente lo que no existia.

    BL.21702 -- EL COMPROMISO AMPLIFICABA x8 A CUALQUIER ACCION QUE MOVIERA UN PIXEL. `continuar()`
    solo cortaba con `hubo_cambio=False`, asi que una accion COSMETICA pero siempre-cambiante (un
    disparo que anima, una barra que parpadea) se llevaba ocho de cada nueve pasos frente a una que
    no-opea. Medido en entorno real, 151 acciones: sb26 gasto 125 en ACTION5 (82,8%). Eso -- y no
    ninguna ganancia de informacion, que no existe en este codigo -- es lo que produce la
    "degeneracion en una accion sin prior".

    LA PALANCA `macroCambioInformativo` exige que el cambio ademas sea INFORMATIVO: que el estado
    al que la macro llega no sea uno YA VISITADO en el episodio. Es la definicion honesta de
    "avanzar hasta chocar", que es para lo que la macro se creo: recorrer un tablero produce
    estados nuevos; recorrer una animacion en bucle, no. En sb26 el ciclo medido tiene periodo ~73,
    asi que a partir de la primera vuelta cada paso de la macro cae en un estado ya visto y el
    compromiso se corta en el acto."""

    def __init__(self, banderas: Banderas | None = None) -> None:
        self._accion: str | None = None
        self._pasos = 0
        self._exige_cambio_informativo = bandera_activa(MACRO_CAMBIO_INFORMATIVO, banderas)
        #: Observabilidad: cuantas veces se corto por caer en un estado ya visitado (metrica de la
        #: palanca -- sin esto no se puede saber si se disparo o no).
        self.cortes_por_estado_repetido = 0

    @property
    def accion_vigente(self) -> str | None:
        return self._accion

    @property
    def pasos_emitidos(self) -> int:
        return self._pasos

    def iniciar(self, accion: str) -> None:
        """Abre un compromiso nuevo -- el paso que se esta por emitir cuenta como el primero."""
        self._accion = accion
        self._pasos = 1

    def cancelar(self) -> None:
        self._accion = None
        self._pasos = 0

    def continuar(
        self,
        accion_anterior: str | None,
        hubo_cambio: bool,
        disponibles: Iterable[str],
        estado_ya_visitado: bool = False,
    ) -> str | None:
        """Accion a repetir, o None si el compromiso termino (y entonces se vuelve a elegir).

        Cancela en cuanto deja de cumplirse una condicion: nunca queda un compromiso a medias que
        reviva mas tarde con evidencia vieja. Las condiciones son, en orden: que la accion anterior
        haya sido la de la macro (si no, se metio algo en el medio -- un RESET), que la transicion
        anterior haya cambiado el tablero enmascarado, que ese cambio haya sido INFORMATIVO
        (BL.21702, ver el docstring de la clase -- solo con `macroCambioInformativo` encendida),
        que el juego siga ofreciendo la accion, y que no se haya alcanzado el tope.

        `estado_ya_visitado` lo aporta el llamador desde su contador de novedad: es el unico que
        sabe cuantas veces se vio la firma a la que la transicion llego."""
        accion = self._accion
        if accion is None:
            return None
        if accion_anterior != accion:
            self.cancelar()
            return None
        if not hubo_cambio:
            self.cancelar()
            return None
        if self._exige_cambio_informativo and estado_ya_visitado:
            self.cortes_por_estado_repetido += 1
            self.cancelar()
            return None
        if accion not in set(disponibles):
            self.cancelar()
            return None
        if self._pasos >= MACRO_MAX_STEPS:
            self.cancelar()
            return None
        self._pasos += 1
        return accion


class StateNoveltyTracker:
    """Conteo de visitas por estado y por arista (estado, accion) sobre la firma ENMASCARADA.

    SOBRE-COLAPSO (limitacion conocida, no defecto). Si el agente no consigue cambiar NADA del
    tablero en todo el episodio, todas las firmas colapsan a una sola (medido en lf52-271a04aa: 3
    firmas enmascaradas en 92 pasos) y el criterio se queda sin señal: todos los destinos son el
    mismo estado con las mismas visitas y el desempate cae, correctamente, en "la menos probada desde
    aca". Ahi el que sostiene el comportamiento es `MacroCommitment`, no la novedad."""

    def __init__(self) -> None:
        self._visitas_por_firma: dict[int, int] = {}
        self._intentos_por_par: dict[tuple[int, str], int] = {}
        # Se guarda el ULTIMO destino y no todos: el efecto de una accion en ARC-AGI-3 depende del
        # estado global del juego, asi que el destino de hace 40 pasos puede ya no valer.
        self._destino_por_par: dict[tuple[int, str], int] = {}

    def registrar_visita(self, firma: int) -> None:
        self._visitas_por_firma[firma] = self._visitas_por_firma.get(firma, 0) + 1

    def registrar_transicion(self, origen: int, accion: str, destino: int) -> None:
        """El llamador NO debe invocarla cuando las dos firmas se calcularon con mascaras distintas:
        serian hashes de dos definiciones de "estado" y el destino no describiria nada."""
        par = (origen, accion)
        self._intentos_por_par[par] = self._intentos_por_par.get(par, 0) + 1
        self._destino_por_par[par] = destino

    def visitas_de(self, firma: int) -> int:
        return self._visitas_por_firma.get(firma, 0)

    def intentos_de(self, firma: int, accion: str) -> int:
        return self._intentos_por_par.get((firma, accion), 0)

    def firmas_distintas(self) -> int:
        """Estados distintos vistos en el episodio -- solo observabilidad (logs y tests de efecto)."""
        return len(self._visitas_por_firma)

    def hay_accion_sin_probar(self, firma: int, disponibles: Iterable[str]) -> bool:
        """Queda al menos una accion sin probar desde `firma` -- la señal que el criterio necesita
        para poder discriminar. Solo observabilidad."""
        return any(self.intentos_de(firma, accion) == 0 for accion in disponibles)

    def clave(self, firma: int, accion: str) -> tuple[int, int, int]:
        """Clave de orden por novedad, menor primero:
          (0, 0, 0)                      nunca probada desde este estado -- maxima novedad;
          (1, visitas_destino, intentos) ya probada: gana la que lleva al estado menos visitado.
        Destino desconocido cuenta como 0 visitas: sin evidencia se asume novedoso, que es el lado
        del error que hace explorar en vez de dejar de explorar."""
        intentos = self.intentos_de(firma, accion)
        if intentos == 0:
            return (0, 0, 0)
        destino = self._destino_por_par.get((firma, accion))
        visitas = 0 if destino is None else self.visitas_de(destino)
        return (1, visitas, intentos)


@dataclass(frozen=True)
class HechoDeMuerte:
    """BL.21767 -- UNA transicion terminal observada, con el contexto que el BL exige: la firma
    del estado previo, la accion que la produjo, la coordenada si fue un click y si habia una
    macro en curso. Es el HECHO del modelo de mundo; el descuento del ranking es su consumo."""

    firma: int
    accion: str
    click: tuple[int, int] | None
    con_macro: bool
    paso: int


class MemoriaDeMuertes:
    """BL.21767 -- el lugar donde se ANOTA la muerte. Hasta este BL no existia: GAME_OVER llegaba
    a la politica disfrazado de NOT_STARTED (`kaggle_adapter`) y el vocabulario de mecanicas solo
    describe COMO CAMBIA el tablero, no "esta accion desde este estado TERMINA la partida". El
    agente no podia aprender a evitar la muerte porque no tenia donde escribirla (sp80: 6
    GAME_OVERs en 151 acciones con exploracion sana -- 131 firmas distintas -- y 0 niveles).

    EL REGISTRO ES INCONDICIONAL Y EL CONSUMO ES UNA PALANCA (`memoriaDeMuertes` en banderas.py):
    anotar un hecho no consume rng ni cambia una decision, asi que puede correr siempre; relegar
    la accion en el ranking es lo que el gate tiene que aprobar por separado (BL.21702).

    POR QUE EL PAR INMEDIATO (firma previa, accion) Y NO UNA CADENA: la localidad se MIDIO antes
    de elegir el mecanismo (`scripts/medicion_de_muertes.py`, exigencia expresa del BL -- si el
    agente muriera por lo que hizo cinco pasos antes, castigar la ultima accion seria
    supersticion). El resultado vive en `mediciones/BL21767_muertes_por_juego.json`.

    EL DESCUENTO NO ES UN LOCKOUT. `CASTIGO_POR_MUERTE_USOS` aplicaciones y se agota; cada
    supervivencia observada del MISMO par lo gasta tambien (evidencia en contra); cada muerte
    nueva lo re-arma. Mismo cuidado que BL.21518 exigio del lado de los no-ops y BL.21557 del de
    la recompensa: en ARC-AGI-3 el efecto de una accion depende del estado global que la firma no
    ve, asi que "mato una vez" no es "mata siempre"."""

    def __init__(self) -> None:
        self._castigos: dict[tuple[int, str], int] = {}
        self._muertes_por_par: dict[tuple[int, str], int] = {}
        self._supervivencias_por_par: dict[tuple[int, str], int] = {}
        self._hechos: list[HechoDeMuerte] = []

    def registrar_transicion(
        self,
        firma: int,
        accion: str,
        murio: bool,
        click: tuple[int, int] | None = None,
        con_macro: bool = False,
        paso: int = 0,
    ) -> None:
        """Toda transicion observada entra por aca; `murio` dice si termino en GAME_OVER.

        La supervivencia solo se contabiliza para pares que YA mataron alguna vez: contar cada
        paso del episodio dejaria la memoria O(pasos) sin que ningun consumidor lea esas filas."""
        par = (firma, accion)
        if murio:
            self._muertes_por_par[par] = self._muertes_por_par.get(par, 0) + 1
            self._castigos[par] = CASTIGO_POR_MUERTE_USOS
            self._hechos.append(HechoDeMuerte(firma, accion, click, con_macro, paso))
            return
        if par not in self._muertes_por_par:
            return
        self._supervivencias_por_par[par] = self._supervivencias_por_par.get(par, 0) + 1
        self._gastar(par)

    def castigadas(self, firma: int, available_actions: Iterable[int]) -> set[GameAction]:
        """Acciones disponibles con descuento vigente desde `firma` -- lo que `rank_candidates`
        relega al fondo. Devuelve set nuevo: el llamador no puede mutar la memoria por accidente."""
        if not self._castigos:
            return set()
        return {
            accion
            for n in available_actions
            if self._castigos.get((firma, (accion := GameAction(f"ACTION{n}")).value), 0) > 0
        }

    def aplicar_castigo(self, firma: int, accion: str) -> None:
        """Gasta un uso del descuento: se llama por cada accion efectivamente relegada en un
        ranking. Que se agote es el punto entero -- ver el docstring de la clase."""
        self._gastar((firma, accion))

    def _gastar(self, par: tuple[int, str]) -> None:
        restante = self._castigos.get(par)
        if restante is None:
            return
        if restante > 1:
            self._castigos[par] = restante - 1
        else:
            self._castigos.pop(par, None)

    @property
    def hechos(self) -> tuple[HechoDeMuerte, ...]:
        """Los hechos registrados, en orden de ocurrencia. Observabilidad: es lo que un reporte de
        corrida (o un test de efecto) lee para saber DONDE murio la partida."""
        return tuple(self._hechos)

    @property
    def muertes_registradas(self) -> int:
        return len(self._hechos)

    def evidencia_de(self, firma: int, accion: str) -> dict[str, int]:
        """Muertes, supervivencias y descuento restante del par -- el resumen que pondera la
        evidencia, para observabilidad y tests."""
        par = (firma, accion)
        return {
            "muertes": self._muertes_por_par.get(par, 0),
            "supervivencias": self._supervivencias_por_par.get(par, 0),
            "castigoRestante": self._castigos.get(par, 0),
        }


# ============================== arc_agent/click_features.py ==============================
"""[arc-agi3-kaggle-agent/click_features] BL.21560 -- vector de features POR CELDA para decidir donde
clickear (ACTION6) y su combinacion lineal con los pesos de priors.py. Espejo de
arc-agi-runner/src/worldModel/clickFeatures.ts.

POR QUE ESTAS FEATURES. Todas salen de helpers que YA existen (`grid.py` + `_find_components`): es la
misma segmentacion que ve el modelo de mundo, no una vision paralela. Y ninguna mira coordenadas
absolutas ni identificadores de partida -- un peso aprendido en un juego tiene que poder servir en
otro, que es la unica razon para transportar pesos.

La feature que mas separa en el corpus real es `componenteRodeadaDeFondo`: el mismo dibujo (una ficha
6x6 de color 9) aparece DOS veces en pantalla de ft09 -- como panel decorativo rodeado por el fondo, y
como ficha jugable rodeada por el marco del tablero. Clickear la primera no hace nada (62 clicks
muertos medidos); clickear la segunda funciono 32 de 32 veces. Nada del color ni del tamano las
distingue: lo hace el VECINDARIO de su componente. OJO con generalizar de mas -- en lp85-305b61c3 la
relacion es la inversa, y por eso el peso de esta feature esta regularizado y la evidencia del
episodio (plantillas de click_targeting.py) pesa mas que el prior.
"""

import math
from typing import Sequence

# Import a UN solo nivel (`.world_model`): el builder del notebook desmonta los imports relativos
# con el regex `^from \.\w* import .+$`, que no cubre un segundo punto.




CLICK_FEATURE_NAMES: tuple[str, ...] = (
    "sesgo",
    "bordeDeColor",
    "tamanoComponente",
    "esBordeDeComponente",
    "rarezaDeColor",
    "esColorDeFondo",
    "distanciaAlBboxDeForeground",
    "componenteRodeadaDeFondo",
    "enRegionQueCambio",
)

CLICK_FEATURE_COUNT = len(CLICK_FEATURE_NAMES)

#: Normalizador de `tamanoComponente`. 256 celdas = 1/16 de un frame 64x64: por encima de eso la
#: "componente" ya es una region de fondo o un panel entero, no un objeto clickeable.
TAMANO_COMPONENTE_SATURACION = 256


def _bbox_contiene(bbox: tuple[int, int, int, int], x: int, y: int) -> bool:
    min_x, min_y, max_x, max_y = bbox
    return min_x <= x <= max_x and min_y <= y <= max_y


def _distancia_al_bbox(bbox: tuple[int, int, int, int], x: int, y: int) -> int:
    """Distancia Chebyshev al rectangulo, 0 si (x,y) esta adentro."""
    min_x, min_y, max_x, max_y = bbox
    dx = max(min_x - x, 0, x - max_x)
    dy = max(min_y - y, 0, y - max_y)
    return max(dx, dy)


class ClickFeatureBoard:
    """Features de TODAS las celdas de una grilla, calculadas una sola vez por frame: segmentar en
    componentes es O(celdas) y rehacerlo por candidato seria cuadratico."""

    __slots__ = (
        "_grid",
        "ancho",
        "alto",
        "color_de_fondo",
        "_etiqueta",
        "_tamanos",
        "_rodeada_de_fondo",
        "_conteo_de_color",
        "_fg_bbox",
        "_region_cambiada",
        "_total",
    )

    def __init__(
        self, grid: Grid, region_cambiada: tuple[int, int, int, int] | None = None
    ) -> None:
        self._grid = grid
        self.alto = len(grid)
        self.ancho = len(grid[0]) if self.alto > 0 else 0
        self._total = self.ancho * self.alto
        self.color_de_fondo = detect_background_color(grid)
        caja = foreground_bounding_box(grid, self.color_de_fondo)
        self._fg_bbox = (
            None if caja is None else (caja.min_x, caja.min_y, caja.max_x, caja.max_y)
        )
        self._region_cambiada = region_cambiada

        conteo: dict[int, int] = {}
        for fila in grid:
            for celda in fila:
                conteo[celda] = conteo.get(celda, 0) + 1
        self._conteo_de_color = conteo

        etiqueta = [-1] * self._total
        componentes = _find_components(grid, self.color_de_fondo)
        tamanos = [len(c) for c in componentes]
        for i, celdas in enumerate(componentes):
            for cx, cy in celdas:
                etiqueta[cy * self.ancho + cx] = i
        self._etiqueta = etiqueta
        self._tamanos = tamanos

        # Fraccion del CONTORNO de cada componente que toca el color de fondo. Es lo que separa un
        # panel decorativo (flotando sobre el fondo) de una ficha dentro de un tablero (rodeada por
        # el marco): en ft09 el MISMO dibujo aparece de las dos formas y solo la segunda responde al
        # click -- 32 de 32 productivos contra 62 muertos sobre el dibujo gemelo.
        rodeada = [0.0] * len(componentes)
        for i, celdas in enumerate(componentes):
            contorno = 0
            contorno_de_fondo = 0
            for cx, cy in celdas:
                for vx, vy in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    dentro = 0 <= vx < self.ancho and 0 <= vy < self.alto
                    if dentro and etiqueta[vy * self.ancho + vx] == i:
                        continue
                    contorno += 1
                    if dentro and grid[vy][vx] == self.color_de_fondo:
                        contorno_de_fondo += 1
            rodeada[i] = contorno_de_fondo / contorno if contorno > 0 else 0.0
        self._rodeada_de_fondo = rodeada

    def tamano_de_componente(self, x: int, y: int) -> int:
        if not (0 <= x < self.ancho and 0 <= y < self.alto):
            return 0
        ident = self._etiqueta[y * self.ancho + x]
        return 0 if ident < 0 else self._tamanos[ident]

    def features(self, x: int, y: int) -> list[float]:
        if not (0 <= x < self.ancho and 0 <= y < self.alto):
            return [0.0] * CLICK_FEATURE_COUNT
        grid = self._grid
        valor = grid[y][x]
        ident = self._etiqueta[y * self.ancho + x]

        borde_de_color = 0
        if x > 0 and grid[y][x - 1] != valor:
            borde_de_color += 1
        if x + 1 < self.ancho and grid[y][x + 1] != valor:
            borde_de_color += 1
        if y > 0 and grid[y - 1][x] != valor:
            borde_de_color += 1
        if y + 1 < self.alto and grid[y + 1][x] != valor:
            borde_de_color += 1

        tamano = 0 if ident < 0 else self._tamanos[ident]
        # Borde de la COMPONENTE, no de la grilla: una celda cuya componente se corta contra el
        # limite del frame tambien cuenta (el vecino inexistente no pertenece a la componente).
        es_borde = ident >= 0 and (
            x == 0
            or y == 0
            or x == self.ancho - 1
            or y == self.alto - 1
            or self._etiqueta[y * self.ancho + (x - 1)] != ident
            or self._etiqueta[y * self.ancho + (x + 1)] != ident
            or self._etiqueta[(y - 1) * self.ancho + x] != ident
            or self._etiqueta[(y + 1) * self.ancho + x] != ident
        )

        conteo = self._conteo_de_color.get(valor, 0)
        rareza = 1 - conteo / self._total if self._total > 0 else 0.0
        max_distancia = max(self.ancho, self.alto, 1)

        return [
            1.0,
            borde_de_color / 4,
            min(1.0, tamano / TAMANO_COMPONENTE_SATURACION),
            1.0 if es_borde else 0.0,
            rareza,
            1.0 if valor == self.color_de_fondo else 0.0,
            1.0
            if self._fg_bbox is None
            else _distancia_al_bbox(self._fg_bbox, x, y) / max_distancia,
            0.0 if ident < 0 else self._rodeada_de_fondo[ident],
            1.0
            if self._region_cambiada is not None
            and _bbox_contiene(self._region_cambiada, x, y)
            else 0.0,
        ]


def puntuar_celda(features: Sequence[float], pesos: Sequence[float]) -> float:
    """Producto punto features x pesos (logit). Largos distintos se recortan al minimo comun: unos
    priors regenerados con una feature de mas nunca deben tumbar una partida."""
    return sum(f * p for f, p in zip(features, pesos))


def sigmoide(logit: float) -> float:
    """Probabilidad logistica -- solo para reportar/umbralar; el ranking usa el logit directo.
    Formulada por rama para no desbordar `exp` con logits grandes."""
    if logit >= 0:
        return 1 / (1 + math.exp(-logit))
    e = math.exp(logit)
    return e / (1 + e)


# ============================== arc_agent/click_targeting.py ==============================
"""[arc-agi3-kaggle-agent/click_targeting] BL.21560 -- DONDE clickear (ACTION6): plantillas de parche
y memoria de clicks del episodio, sobre el ranker de click_features.py.

EL PROBLEMA, medido sobre el corpus real (`arcReplayFrames`, corrida ft09-0d8bbf25): 346 clicks,
32 productivos (9,2%). La heuristica previa (`pick_click_target`) elegia UNIFORMEMENTE entre el decil
superior de celdas "borde de color" -- unos 410 candidatos de 4096, de los cuales solo ~36 son las
esquinas de las fichas del tablero jugable. 36/410 = 8,8%: la tasa medida no era mala suerte, era
exactamente lo que predice tirar al azar dentro de ese conjunto. Y sin memoria: 117 de esos 346
clicks repitieron una coordenada ya probada.

TRES CAPAS, en el orden en que actuan sobre una decision:
  1. PRIOR (offline): puntaje lineal de features de la celda, con pesos ajustados por regresion
     logistica contra clicks reales etiquetados con "el click cambio la grilla" (auto-supervisado,
     no exige haber ganado nunca). Ver scripts/fit_click_priors.py.
  2. PLANTILLA (en vivo): al detectar un click CON efecto se guarda el parche 3x3 que lo rodeaba;
     toda celda con un parche parecido sube al frente. Es lo que convierte un acierto en una
     politica: en ft09 las nueve fichas del tablero tienen el mismo parche en sus esquinas.
  3. MEMORIA (en vivo): mapa (firma, x, y) -> ya probado / produjo cambio. La clave lleva la FIRMA
     del estado y no solo la coordenada -- es exactamente lo que policy.py documentaba como "la
     clave correcta, que hoy no existe": si el tablero cambio, la misma coordenada vuelve a ser
     informativa; si no cambio, repetirla es puro costo.

LA JERARQUIA IMPORTA, y esta medida. El prior sale de UN solo juego, asi que sus pesos estan
regularizados a |2,3| como maximo mientras que plantillas y anti-plantillas valen +-6: la evidencia
que el agente junta DENTRO del episodio manda sobre la que trajo de afuera. Sin eso, en
lp85-305b61c3 -- un juego que no esta en el corpus -- el prior mandaba al agente a la cenefa
decorativa y gasto 403 de 499 clicks ahi.
"""

from typing import Callable, Sequence

# Import a UN solo nivel: el builder del notebook desmonta los imports relativos con el regex
# `^from \.\w* import .+$`, que no cubre un segundo punto.
# Se re-exportan `CLICK_FEATURE_NAMES`, `ClickFeatureBoard`, `puntuar_celda` y `sigmoide`:
# son la superficie publica de 'donde clickear' y viven aca desde que el modulo existe; el
# split en dos archivos es por limite de tamano, no un cambio de contrato.







#: Radio del parche que se guarda como plantilla al detectar un click con efecto (3x3 = radio 1).
RADIO_PARCHE = 1

#: Valor de una celda del parche que cae FUERA de la grilla. -1 no colisiona con ningun color ARC.
PARCHE_FUERA_DE_GRILLA = -1

#: Cuanto suma al logit que el parche de la celda se parezca a una plantilla aprendida. Grande a
#: proposito: una plantilla es evidencia DE ESTA PARTIDA (algo que ya funciono aca), y tiene que
#: pesar mas que cualquier prior aprendido en otras -- los pesos ajustados no pasan de |2,3|.
#: Sigue siendo finito: la memoria de coordenadas probadas se aplica ANTES, asi que una plantilla
#: nunca reancla el agente sobre la misma celda.
BONO_POR_PLANTILLA = 6.0

#: Penalizacion simetrica de una ANTI-PLANTILLA: un parche que ya fallo varias veces. Misma
#: magnitud que el bono porque es la misma clase de evidencia, con el signo dado vuelta.
PENALIZACION_POR_ANTI_PLANTILLA = 6.0

#: Clicks muertos con el MISMO parche antes de descartar toda la clase.
#:
#: POR QUE EXISTE, medido contra la API oficial. Sin esto, el agente recorre las 4096 celdas en
#: orden de prior y, si el prior apunta a una region grande e inerte, se la barre entera: en
#: lp85-305b61c3 gasto 403 de 499 clicks en la cenefa decorativa del borde. Con anti-plantillas esa
#: region completa se descarta a los dos fallos, porque todas sus celdas comparten el mismo parche.
#: Es la mitad negativa de la misma idea que ya hacia falta para la positiva: lo que importa no es
#: la coordenada, es el TIPO DE LUGAR.
#:
#: 2 y no 1 por el mismo criterio que `NO_OP_CONFIRMATIONS`: un solo frame identico puede ser ruido
#: del entorno. Una plantilla POSITIVA sobre el mismo parche gana siempre -- evidencia de efecto
#: real le gana a "aca no paso nada", igual que una accion premiada nunca se trata como no-op.
ANTI_PLANTILLA_MIN_FALLOS = 2

#: BL.21702 -- cuanto BAJA el puntaje de una celda por cada vez que se la REPITE en el episodio,
#: MIRE LA FIRMA QUE MIRE. El primer click de cada celda es gratis; el segundo y los siguientes
#: pagan.
#:
#: POR QUE, medido en los entornos reales (151 acciones por juego, semilla bl21702a): la memoria de
#: clicks se indexa por `(firma, x, y)`, asi que una firma nueva vacia la cobertura y
#: `elegir_objetivo` devuelve OTRA VEZ la celda de mayor puntaje. En los juegos donde el frame
#: nunca se repite -- que son justo aquellos donde la mascara de volatilidad quedo en 0 celdas --
#: eso degenera en clickear siempre el mismo punado de celdas: tn36 9 coordenadas distintas en 149
#: clicks, su15 5 en 138, dc22 5 en 8, sb26 13 en 16. Cobertura del orden del 0,2% de las 4.096
#: celdas del frame. La decision que importa en un juego de click no es QUE accion sino DONDE, y
#: esa dimension no tenia ninguna memoria transversal al estado.
#:
#: QUE SE CUENTA DEPENDE DE SI LA SENAL DE CAMBIO INFORMA ALGO, y las dos variantes se MIDIERON,
#: cada una gana en un regimen y pierde en el otro:
#:
#:   | penalizar por...        | ft09 (corpus real, senal util) | juguete su15/tn36 (senal muerta) |
#:   | ----------------------- | ------------------------------ | -------------------------------- |
#:   | clicks ESTERILES        | 232 -> 293 productivos         | 16 -> 16 celdas (nada)           |
#:   | REPETICIONES a secas    | 232 -> 210 productivos         | 16 -> 36 celdas                  |
#:
#: La lectura: donde el cambio DISCRIMINA (ft09: muchos clicks no mueven nada), castigar fallos es
#: estrictamente mejor -- el agente vuelve gratis a la celda que funciona. Donde el cambio NO
#: discrimina -- que es el caso de los siete juegos atascados, con la mascara en 0 celdas y el
#: frame animando en cada paso, asi que `hubo_cambio` es SIEMPRE verdadero -- una memoria de fallos
#: no acumula nada y la unica senal que queda es la repeticion misma.
#:
#: Por eso `penalizacion_transversal` elige el contador segun el REGIMEN OBSERVADO (ver
#: `senal_de_cambio_degenerada`), en vez de apostar a uno de los dos.
#:
#: LA MAGNITUD NO ES LIBRE: `TOPE_DE_REPETICIONES_POR_CELDA` repeticiones saturan la penalizacion
#: justo en `PENALIZACION_POR_ANTI_PLANTILLA` -- y tambien en `BONO_POR_PLANTILLA`, que es la parte
#: importante: una celda que YA FUNCIONO conserva su bono de plantilla y sale empatada consigo
#: misma en el peor caso, nunca por debajo del fondo. El castigo mueve al agente de una celda
#: gastada; no lo ciega frente a un boton que sirve.
PENALIZACION_POR_REPETICION_DE_CELDA = 2.0

#: Clicks minimos antes de juzgar si la senal de cambio DISCRIMINA. Con menos, "todos cambiaron"
#: es una coincidencia esperable y no una propiedad del juego.
CLICKS_PARA_JUZGAR_LA_SENAL = 8

#: Repeticiones que acumula UNA celda antes de saturar la penalizacion. Que sature es deliberado:
#: sin tope, una celda castigada mil veces quedaria por debajo de cualquier otra para siempre y la
#: memoria transversal se volveria el lockout absorbente que BL.21518 tuvo que desarmar del lado de
#: los no-ops. En ARC-AGI-3 el efecto de un click depende del estado global: un boton inerte
#: empieza a servir cuando se abre una puerta.
TOPE_DE_REPETICIONES_POR_CELDA = 3

Coordenada = tuple[int, int]


def extraer_parche(grid: Grid, x: int, y: int) -> tuple[int, ...]:
    """Parche cuadrado de lado 2*RADIO_PARCHE+1 centrado en (x,y), aplanado en orden row-major.
    Las celdas fuera de la grilla valen PARCHE_FUERA_DE_GRILLA."""
    alto = len(grid)
    ancho = len(grid[0]) if alto > 0 else 0
    parche: list[int] = []
    for dy in range(-RADIO_PARCHE, RADIO_PARCHE + 1):
        for dx in range(-RADIO_PARCHE, RADIO_PARCHE + 1):
            px, py = x + dx, y + dy
            dentro = 0 <= px < ancho and 0 <= py < alto
            parche.append(grid[py][px] if dentro else PARCHE_FUERA_DE_GRILLA)
    return tuple(parche)


def similitud_de_parche(a: Sequence[int], b: Sequence[int]) -> float:
    """Fraccion de celdas iguales entre dos parches, en [0,1]."""
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return sum(1 for i in range(n) if a[i] == b[i]) / n


def region_que_cambio(
    pre: Grid | None, post: Grid | None
) -> tuple[int, int, int, int] | None:
    """Rectangulo que cambio entre dos grillas, o None si no cambio nada / no son comparables."""
    if pre is None or post is None:
        return None
    min_x = min_y = 1 << 30
    max_x = max_y = -1
    for y in range(min(len(pre), len(post))):
        for x in range(min(len(pre[y]), len(post[y]))):
            if pre[y][x] == post[y][x]:
                continue
            min_x = min(min_x, x)
            max_x = max(max_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y)
    if max_x < min_x:
        return None
    return (min_x, min_y, max_x, max_y)


def _random_coord(rng: Callable[[], float]) -> int:
    return int(rng() * (GRID_MAX_COORD + 1))


def pick_click_target(
    grid: tuple[tuple[int, ...], ...], rng: Callable[[], float]
) -> tuple[int, int]:
    """HEURISTICA PREVIA a BL.21560, conservada como CAMINO DE RESPALDO: elige (x, y) priorizando
    celdas en el BORDE de una region de color distinto, uniformemente dentro del decil superior.

    Ya no decide una partida -- decide `ClickMemory.elegir_objetivo`, que la contiene como caso
    particular (la feature `bordeDeColor` sigue en el vector) y le agrega prior aprendido, plantillas
    y memoria. Se mantiene porque es la referencia contra la que se mide la mejora: su tasa de
    acierto sobre la partida real grabada es 9,2%, y ese numero solo se puede volver a medir si la
    funcion existe. Vive en este modulo y no en policy.py porque comparte dominio (donde clickear) y
    porque policy.py esta en su limite de tamano."""
    if not grid or not grid[0]:
        return _random_coord(rng), _random_coord(rng)

    height = len(grid)
    width = len(grid[0])
    scored: list[tuple[int, int, int]] = []
    for y in range(height):
        row = grid[y]
        for x in range(width):
            value = row[x]
            score = 0
            if x > 0 and row[x - 1] != value:
                score += 1
            if x + 1 < width and row[x + 1] != value:
                score += 1
            if y > 0 and grid[y - 1][x] != value:
                score += 1
            if y + 1 < height and grid[y + 1][x] != value:
                score += 1
            if score > 0:
                scored.append((score, x, y))

    if not scored:
        return _random_coord(rng), _random_coord(rng)

    scored.sort(key=lambda item: item[0], reverse=True)
    top_k = scored[: max(1, len(scored) // 10)]
    choice_index = int(rng() * len(top_k))
    _, x, y = top_k[choice_index]
    return x, y


class ClickMemory:
    """Memoria de clicks de UN episodio (capas 2 y 3). Una instancia por partida, igual que la
    politica que la contiene."""

    __slots__ = (
        "_probadas",
        "_clicks_por_celda",
        "_esteriles_por_celda",
        "_clicks_totales",
        "_clicks_sin_cambio",
        "_celdas_clickeadas",
        "_transversal",
        "_plantillas",
        "_anti_plantillas",
        "_fallos_por_parche",
        "_centros_de_plantilla",
        "_pesos",
        "_umbral_similitud",
        "_cache_clave",
        "_cache_puntajes",
        "_cache_orden",
    )

    def __init__(
        self,
        pesos: Sequence[float] | None = None,
        umbral_similitud: float | None = None,
        banderas: Banderas | None = None,
    ) -> None:
        # (firma, x, y) -> el click produjo cambio.
        self._probadas: dict[tuple[int, int, int], bool] = {}
        # BL.21702 -- COBERTURA TRANSVERSAL AL ESTADO: (x, y) -> clicks acumulados en el episodio,
        # sin importar desde que firma. Es la memoria que faltaba; `_probadas` la tenia solo DENTRO
        # de una firma y en estos juegos la firma no se repite nunca.
        self._clicks_por_celda: dict[Coordenada, int] = {}
        # Clicks esteriles por celda, tambien transversal. Es el contador PREFERIDO cuando la senal
        # de cambio discrimina: castiga lo que no sirvio sin castigar lo que si.
        self._esteriles_por_celda: dict[Coordenada, int] = {}
        # Totales del episodio, para decidir el regimen (ver `senal_de_cambio_degenerada`).
        self._clicks_totales = 0
        self._clicks_sin_cambio = 0
        # Coordenadas distintas clickeadas en el episodio -- la METRICA de la palanca (medido antes:
        # 9 en 149 clicks, 5 en 138, 5 en 8, 13 en 16).
        self._celdas_clickeadas: set[Coordenada] = set()
        self._transversal = bandera_activa(MEMORIA_TRANSVERSAL_DE_CLICKS, banderas)
        self._plantillas: list[tuple[int, ...]] = []
        # Parches que ya fallaron `ANTI_PLANTILLA_MIN_FALLOS` veces, y el conteo que lleva a serlo.
        self._anti_plantillas: set[tuple[int, ...]] = set()
        self._fallos_por_parche: dict[tuple[int, ...], int] = {}
        # Valores centrales presentes entre las plantillas -- rechazo rapido: una celda cuyo color no
        # es el centro de NINGUNA plantilla no puede parecerse a ninguna con un umbral alto, y
        # saltearla evita extraer su parche. Es lo que hace que puntuar 4096 celdas sea barato.
        self._centros_de_plantilla: set[int] = set()
        self._pesos = tuple(pesos if pesos is not None else CLICK_PRIORS["pesosClick"])
        self._umbral_similitud = (
            umbral_similitud
            if umbral_similitud is not None
            else CLICK_PRIORS["umbralesDetectores"]["similitudDeParcheMinima"]
        )
        # Cache de UNA entrada de los puntajes por celda. En ARC-AGI-3 la mayoria de los clicks no
        # cambian nada, asi que la MISMA grilla se puntua muchos pasos seguidos: sin cache, cada
        # decision re-segmenta el frame entero (medido: 33 grillas distintas en 346 pasos de ft09).
        self._cache_clave: tuple[int, object, int] | None = None
        self._cache_puntajes: list[float] = []
        self._cache_orden: list[int] = []

    @property
    def plantillas_aprendidas(self) -> int:
        return len(self._plantillas)

    @property
    def anti_plantillas_aprendidas(self) -> int:
        return len(self._anti_plantillas)

    @property
    def coordenadas_probadas(self) -> int:
        return len(self._probadas)

    @property
    def celdas_distintas_clickeadas(self) -> int:
        """BL.21702 -- coordenadas DISTINTAS clickeadas en el episodio, sin importar la firma. Es
        la magnitud que la palanca de memoria transversal existe para mover; los tests de efecto y
        el reporte de corrida la afirman."""
        return len(self._celdas_clickeadas)

    @property
    def memoria_transversal_activa(self) -> bool:
        """Observabilidad: si la palanca de BL.21702 esta encendida en esta partida."""
        return self._transversal

    def clicks_en(self, x: int, y: int) -> int:
        """Clicks que acumulo esa celda en el episodio, mire la firma que mire."""
        return self._clicks_por_celda.get((x, y), 0)

    def clicks_esteriles_en(self, x: int, y: int) -> int:
        """Clicks sin cambio que acumulo esa celda en el episodio, mire la firma que mire."""
        return self._esteriles_por_celda.get((x, y), 0)

    @property
    def senal_de_cambio_degenerada(self) -> bool:
        """La senal `hubo_cambio` dejo de distinguir: TODOS los clicks del episodio "cambiaron el
        tablero".

        Es exactamente el estado de los siete juegos atascados -- mascara de volatilidad en 0
        celdas y frame que anima en cada paso -- y es lo que decide cual de los dos contadores
        transversales manda. Se exigen `CLICKS_PARA_JUZGAR_LA_SENAL` clicks antes de afirmarlo:
        con dos o tres, "todos cambiaron" es coincidencia."""
        return (
            self._clicks_totales >= CLICKS_PARA_JUZGAR_LA_SENAL
            and self._clicks_sin_cambio == 0
        )

    def penalizacion_transversal(self, x: int, y: int) -> float:
        """Cuanto baja el puntaje de una celda por su historial en CUALQUIER estado.

        Cuando la senal de cambio discrimina se cuentan los clicks ESTERILES de la celda: el agente
        vuelve gratis a lo que funciona. Cuando la senal es degenerada se cuentan las REPETICIONES
        (el primer click de cada celda sigue siendo gratis), porque ahi "no fallo nunca" no
        significa nada. Los dos regimenes estan medidos en el encabezado de las constantes.

        Con la palanca apagada devuelve 0.0 exacto -- y `puntaje - 0.0 == puntaje` en coma
        flotante, asi que el orden de seleccion queda IDENTICO al previo a BL.21702. Esa identidad
        es lo que permite medir la linea base con la misma build."""
        if not self._transversal or not self._clicks_por_celda:
            return 0.0
        if self.senal_de_cambio_degenerada:
            unidades = self._clicks_por_celda.get((x, y), 0) - 1
        else:
            unidades = self._esteriles_por_celda.get((x, y), 0)
        if unidades <= 0:
            return 0.0
        return PENALIZACION_POR_REPETICION_DE_CELDA * min(
            unidades, TOPE_DE_REPETICIONES_POR_CELDA
        )

    def registrar_resultado(
        self, firma: int, x: int, y: int, hubo_cambio: bool, grid_previa: Grid | None
    ) -> None:
        """Atribuye el resultado del click anterior. `grid_previa` es la grilla SOBRE LA QUE se
        clickeo: el parche de la plantilla tiene que describir lo que se veia al decidir, no lo que
        quedo despues (que ya cambio justamente por el click)."""
        self._probadas[(firma, x, y)] = hubo_cambio
        self._celdas_clickeadas.add((x, y))
        # BL.21702 -- se llevan LOS DOS contadores transversales porque `penalizacion_transversal`
        # elige entre ellos segun el regimen: clicks totales (repeticion) y clicks esteriles. Un
        # click con efecto BORRA el historial esteril de esa celda -- evidencia de efecto real
        # desmiente el historial de fallos, igual que una plantilla positiva desmiente su
        # anti-plantilla -- pero NO borra el conteo de repeticiones, que es puro presupuesto.
        self._clicks_por_celda[(x, y)] = self._clicks_por_celda.get((x, y), 0) + 1
        self._clicks_totales += 1
        if hubo_cambio:
            self._esteriles_por_celda.pop((x, y), None)
        else:
            self._clicks_sin_cambio += 1
            self._esteriles_por_celda[(x, y)] = self._esteriles_por_celda.get((x, y), 0) + 1
        if grid_previa is None:
            return
        parche = extraer_parche(grid_previa, x, y)

        if not hubo_cambio:
            fallos = self._fallos_por_parche.get(parche, 0) + 1
            self._fallos_por_parche[parche] = fallos
            if fallos >= ANTI_PLANTILLA_MIN_FALLOS and parche not in self._anti_plantillas:
                self._anti_plantillas.add(parche)
                self._centros_de_plantilla.add(parche[len(parche) // 2])
                self._cache_clave = None  # la anti-plantilla nueva cambia los puntajes
            return

        if parche in self._plantillas:
            return
        self._plantillas.append(parche)
        self._centros_de_plantilla.add(parche[len(parche) // 2])
        # Evidencia de efecto real desmiente cualquier marca de "aca no pasa nada" sobre ese parche.
        self._anti_plantillas.discard(parche)
        self._fallos_por_parche.pop(parche, None)
        self._cache_clave = None  # la plantilla nueva cambia los puntajes

    def _bono_de_plantilla(self, grid: Grid, x: int, y: int) -> float:
        """Ajuste del puntaje por evidencia DE ESTA PARTIDA: +bono si el parche de la celda coincide
        con uno que ya funciono, -penalizacion si coincide con uno que ya fallo varias veces. La
        positiva gana: haber visto un efecto real le gana a no haber visto nada."""
        if not self._centros_de_plantilla or grid[y][x] not in self._centros_de_plantilla:
            return 0.0
        parche = extraer_parche(grid, x, y)
        if self._plantillas:
            mejor = max(similitud_de_parche(parche, p) for p in self._plantillas)
            if mejor >= self._umbral_similitud:
                return BONO_POR_PLANTILLA
        if self._anti_plantillas:
            peor = max(similitud_de_parche(parche, p) for p in self._anti_plantillas)
            if peor >= self._umbral_similitud:
                return -PENALIZACION_POR_ANTI_PLANTILLA
        return 0.0

    def puntajes_por_celda(
        self, grid: Grid, region_cambiada: tuple[int, int, int, int] | None = None
    ) -> list[float]:
        """Puntaje (logit + bono de plantilla) de cada celda, row-major. Cacheado por grilla y por
        cantidad de plantillas: es puro, depende solo de esos dos."""
        clave = (
            hash_grid(grid),
            region_cambiada,
            len(self._plantillas) * 1000 + len(self._anti_plantillas),
        )
        if self._cache_clave == clave:
            return self._cache_puntajes

        tablero = ClickFeatureBoard(grid, region_cambiada)
        pesos = self._pesos
        puntajes: list[float] = []
        for y in range(tablero.alto):
            for x in range(tablero.ancho):
                puntajes.append(
                    puntuar_celda(tablero.features(x, y), pesos)
                    + self._bono_de_plantilla(grid, x, y)
                )
        self._cache_clave = clave
        self._cache_puntajes = puntajes
        self._cache_orden = sorted(range(len(puntajes)), key=lambda i: -puntajes[i])
        return puntajes

    def elegir_objetivo(
        self,
        grid: Grid,
        firma: int,
        rng: Callable[[], float],
        region_cambiada: tuple[int, int, int, int] | None = None,
    ) -> Coordenada:
        """Coordenada a clickear: la celda NO PROBADA en este estado con mayor puntaje EFECTIVO. Si
        todas se probaron, se prefiere una que YA produjo cambio (un boton que funciono vuelve a
        funcionar) antes que una muerta.

        BL.21702 -- puntaje EFECTIVO = puntaje de la celda menos su `penalizacion_transversal`, o
        sea su historial en CUALQUIER estado (fallos o repeticiones, segun el regimen). Sin ese
        termino, en los juegos donde la firma nunca se repite la memoria por firma no bloquea nada
        y el ranker devuelve siempre la misma celda (medido: 5 coordenadas en 138 clicks). Con la
        palanca apagada la penalizacion es 0.0 exacto y la seleccion es identica a la previa.

        Recorre las celdas en orden de puntaje BASE descendente (precalculado junto con los
        puntajes) y corta apenas el puntaje base ya no puede superar al mejor efectivo encontrado
        -- la penalizacion solo RESTA, asi que ese corte es exacto, no una aproximacion.

        Consume EXACTAMENTE un numero del rng, igual que la heuristica que reemplaza: la
        reproducibilidad de una partida dado su seed depende de que la secuencia del rng no varie
        con el contenido de la memoria."""
        alto = len(grid)
        ancho = len(grid[0]) if alto > 0 else 0
        if ancho == 0 or alto == 0:
            return 0, 0

        puntajes = self.puntajes_por_celda(grid, region_cambiada)
        orden = self._cache_orden
        probadas = self._probadas
        sorteo = rng()

        # Primera pasada: el mejor puntaje EFECTIVO entre las celdas no probadas en esta firma.
        mejor: float | None = None
        for i in orden:
            if mejor is not None and puntajes[i] <= mejor:
                break  # ninguna celda posterior puede superarlo: la penalizacion nunca suma
            x, y = i % ancho, i // ancho
            if (firma, x, y) in probadas:
                continue
            efectivo = puntajes[i] - self.penalizacion_transversal(x, y)
            if mejor is None or efectivo > mejor:
                mejor = efectivo

        # Segunda pasada: TODAS las empatadas en ese maximo, para que el sorteo elija entre ellas
        # sin sesgo posicional (mismo criterio que antes de BL.21702).
        empatadas: list[int] = []
        if mejor is not None:
            for i in orden:
                if puntajes[i] < mejor:
                    break
                x, y = i % ancho, i // ancho
                if (firma, x, y) in probadas:
                    continue
                if puntajes[i] - self.penalizacion_transversal(x, y) == mejor:
                    empatadas.append(i)
        if not empatadas:
            # Todas probadas en este estado: se prefiere la de mayor puntaje que YA produjo cambio.
            for productiva in (True, False):
                for i in orden:
                    if probadas.get((firma, i % ancho, i // ancho)) is productiva:
                        empatadas = [i]
                        break
                if empatadas:
                    break
        if not empatadas:
            return 0, 0
        elegida = empatadas[int(sorteo * len(empatadas)) % len(empatadas)]
        return elegida % ancho, elegida // ancho


# ============================== arc_agent/wall_perception.py ==============================
"""[arc-agi3-kaggle-agent/wall_perception] BL.21593 -- PERCEPCION del termino observable de la
verosimilitud del fallo: `P(pared | grilla)`. La pared se VE -- este modulo la mira. Espejo exacto
de la seccion homonima de arc-agi-runner/src/worldModel/mechanicsPosterior.ts.

Dos piezas, ambas capa de percepcion (consumen grilla y mecanicas de BL.21561, nunca game_id):

  - `RastreadorDeAvatar`: el avatar es el ultimo objeto que se TRASLADO (el cursor que BL.21561
    ya detecta) y el PISO es el color que dejan las celdas que desaloja -- la misma evidencia
    `relleno` que el detector de traslaciones exige. Sin esto la pared no es evaluable: saber si
    hay pared "adelante" exige saber donde esta el avatar y de que color es el suelo.
  - `contexto_de_pared`: para cada direccion, mira la franja de celdas por delante de la caja del
    avatar; borde del tablero o cualquier celda que no sea piso = pared presente.

El consumidor es la capa de creencia (mechanics_posterior.py): un fallo de movimiento con pared
presente en la direccion de la hipotesis queda TOTALMENTE explicado y no mueve el posterior."""

from typing import Final


# Import a UN solo nivel (`.world_model`): el builder del notebook desmonta los imports relativos
# con el regex `^from \.\w* import .+$` -- la forma anidada romperia el entregable.


MECANICA_ARRIBA: Final[str] = "arriba"
MECANICA_ABAJO: Final[str] = "abajo"
MECANICA_IZQUIERDA: Final[str] = "izquierda"
MECANICA_DERECHA: Final[str] = "derecha"

#: Signo (dy,dx) de cada mecanica direccional -- y crece hacia abajo, x hacia la derecha. Vive en
#: la capa de percepcion porque el contexto de pared se evalua POR DIRECCION; la capa de creencia
#: lo importa como parte del vocabulario.
DIRECCIONES: Final[dict[str, tuple[int, int]]] = {
    MECANICA_ARRIBA: (-1, 0),
    MECANICA_ABAJO: (1, 0),
    MECANICA_IZQUIERDA: (0, -1),
    MECANICA_DERECHA: (0, 1),
}

PARED_PRESENTE: Final[str] = "presente"
PARED_AUSENTE: Final[str] = "ausente"
PARED_DESCONOCIDA: Final[str] = "desconocida"


def profundidad_de_sondeo(magnitud: tuple[int, int] | None, prior: dict | None = None) -> int:
    """Cuantas celdas por delante del avatar se inspeccionan buscando pared. Si la magnitud del
    paso del boton ya se midio, el camino que el paso necesita libre es exactamente esa; si no,
    la maxima magnitud medida en los 25 juegos (conservador: ante la duda, mas fallos quedan
    explicados por pared y el posterior se mueve menos -- el lado seguro del error)."""
    if magnitud is not None:
        return max(1, abs(magnitud[0]) + abs(magnitud[1]))
    p = prior if prior is not None else DIRECTION_PRIORS
    magnitudes = [int(m) for m in p.get("magnitudesDePasoMedidas", [])]
    return max(magnitudes) if magnitudes else 1


def contexto_de_pared(
    grilla: Grid | None,
    caja: tuple[int, int, int, int] | None,
    piso: int | None,
    profundidad: int,
) -> dict[str, str]:
    """`presente`/`ausente` por direccion, mirando la franja de `profundidad` celdas por delante
    de la caja del avatar: cualquier celda que no sea del color del piso (o el borde del tablero)
    es pared. Sin avatar o sin piso conocidos, todo es `desconocida` -- el fallo inexplicable que
    aporta poco pero no cero."""
    if grilla is None or caja is None or piso is None or not grilla or not grilla[0]:
        return {nombre: PARED_DESCONOCIDA for nombre in DIRECCIONES}
    alto, ancho = len(grilla), len(grilla[0])
    min_y, min_x, alto_caja, ancho_caja = caja
    contexto: dict[str, str] = {}
    for nombre, (dy, dx) in DIRECCIONES.items():
        hay_pared = False
        for paso in range(1, profundidad + 1):
            if dy != 0:
                fila = (min_y - paso) if dy < 0 else (min_y + alto_caja - 1 + paso)
                celdas = [(fila, x) for x in range(min_x, min_x + ancho_caja)]
            else:
                columna = (min_x - paso) if dx < 0 else (min_x + ancho_caja - 1 + paso)
                celdas = [(y, columna) for y in range(min_y, min_y + alto_caja)]
            for y, x in celdas:
                if y < 0 or x < 0 or y >= alto or x >= ancho or grilla[y][x] != piso:
                    hay_pared = True
                    break
            if hay_pared:
                break
        contexto[nombre] = PARED_PRESENTE if hay_pared else PARED_AUSENTE
    return contexto


class RastreadorDeAvatar:
    """Posicion vigente del objeto controlado y el color del PISO que deja al moverse.

    El avatar es el ultimo objeto que se traslado (el cursor de BL.21561); el piso se lee de las
    celdas que DESALOJO. Es la percepcion que vuelve observable a `P(pared | grilla)`."""

    def __init__(self) -> None:
        self.caja: tuple[int, int, int, int] | None = None
        self.piso: int | None = None

    def observar(self, mecanica: Mecanica | None, post: Grid | None) -> None:
        if mecanica is None or mecanica.traslacion_principal is None or post is None:
            return
        t = mecanica.traslacion_principal
        self.caja = (t.min_y + t.dy, t.min_x + t.dx, t.alto, t.ancho)
        conteo: dict[int, int] = {}
        for y in range(t.min_y, t.min_y + t.alto):
            for x in range(t.min_x, t.min_x + t.ancho):
                en_destino = (
                    t.min_y + t.dy <= y < t.min_y + t.dy + t.alto
                    and t.min_x + t.dx <= x < t.min_x + t.dx + t.ancho
                )
                if en_destino or y < 0 or x < 0 or y >= len(post) or x >= len(post[0]):
                    continue
                color = post[y][x]
                conteo[color] = conteo.get(color, 0) + 1
        if conteo:
            # Desempate por color menor: identico en el puerto TS (orden estable, sin depender
            # del orden de insercion del diccionario).
            self.piso = max(sorted(conteo), key=lambda c: conteo[c])


# ============================== arc_agent/mechanics_posterior.py ==============================
"""[arc-agi3-kaggle-agent/mechanics_posterior] BL.21593 -- INFERENCIA BAYESIANA EXACTA sobre el
mapeo boton -> mecanica, con un latente JERARQUICO enumerable y una verosimilitud que EXPLICA el
fallo. Espejo exacto de arc-agi-runner/src/worldModel/mechanicsPosterior.ts (tests homonimos
pinnean los MISMOS numeros).

EL MODELO, en dos capas y sin EM ni aproximaciones (todo cabe en un diccionario):

  1. ARQUETIPO del juego -- variable latente de la capa alta, con prior observable en el PRIMER
     frame: P(arquetipo | conjunto de acciones disponibles) sale de `conjuntosMedidos` del prior
     generado (25 juegos publicos, BL.21590). Los arquetipos son los que la medicion encontro:
     `mueveCanonico` (11/17 juegos con flechas), `flechasSinMapeo` (6/17: flechas presentes que
     no mueven nada), `mixto` (D-pad parcial o mecanica no direccional; masa de Laplace) y
     `sinFlechas` (8/25: el conjunto no trae ACTION1..4 y no hay mapeo que inferir).
  2. MECANICA por boton -- P(boton -> mecanica | arquetipo): condicional PARAMETRICA (jamas por
     game_id; el gate del build lo enforcea) derivada de `juegosQueConfirmanPorAccion`. Soporte
     por flecha (BL.21853, ya no son siete): cuatro direcciones + `inerte` + las tres mecanicas
     visibles NOMBRADAS (`recoloreo`, `aparicion`, `desaparicion`) + `otra` (visible sin nombre,
     residual) + `desconocida` (masa RESERVADA, ver abajo). El vocabulario de siete metia las tres
     nombradas en `otra` con UNA verosimilitud: un boton que recolorea y uno que borra objetos
     eran indistinguibles. Los conteos que justifican cada simbolo estan en `CONTEO_VISIBLE_MEDIDO`.
     ALCANCE de esa distincion (revision de BL.21853, para no repetir RFM-08): el posterior los
     distingue PUERTAS ADENTRO y ningun consumidor actua sobre CUAL de los tres gano -- fuera de
     este modulo y sus tests nadie importa los tres simbolos, y a `mecanica_dominante` la leen
     `direccion_de` (filtra por `DIRECCIONES`), `resuelta` e `inerte` (solo masa) y `resumen`
     (log). NO son codigo muerto (se emiten 1.267/199/12 veces y ganan en 38 de 386 botones),
     pero el efecto medido de separarlos es +1 acierto direccional sobre 182 pares.

  Los botones son condicionalmente independientes dado el arquetipo, asi que el posterior es
  exacto por enumeracion: P(a|datos) proporcional a P(a) * prod_b sum_m P(m|a,b) * L(b,m), donde
  L(b,m) es el producto de verosimilitudes de las observaciones del boton b bajo la mecanica m
  (no depende del arquetipo dado m: se acumula UNA vez y se comparte). Esto acopla los botones:
  tres flechas muertas suben P(flechasSinMapeo) y la cuarta llega casi resuelta.

LA PIEZA CENTRAL -- la verosimilitud del fallo se DESCOMPONE (idea del usuario, 2026-08-17):

    P(no se movio | boton = direccion d) = P(pared en d | grilla) + P(desconocido)

  `P(pared | grilla)` es OBSERVABLE (wall_perception.py la mira). Un fallo con pared adyacente en
  la direccion de la hipotesis queda TOTALMENTE explicado y NO mueve el posterior del mapeo; el
  mismo fallo sin pared SI lo mueve; y un fallo con pared inobservable (avatar aun no visto)
  aporta poco pero no cero. Con esto el caso "inconcluso" de BL.21590 deja de ser una rama
  cableada: es la consecuencia numerica de cuanto explica el mundo a la observacion.

MASA RESERVADA `desconocida` (defensa contra vocabulario incompleto, propuesta del usuario): si
falta una mecanica en el vocabulario, el posterior elegiria CON CONFIANZA la menos mala de las
opciones equivocadas -- el peor modo de fallo. La categoria `desconocida` tiene verosimilitud
agnostica (explica cualquier cosa a medias) y un PISO que nunca baja; si acumula masa, se REGISTRA
(resumen -> reasoning persistido) como senal de que el vocabulario de BL.21561 necesita una
mecanica nueva -- informacion, no fallo. NADA de crear categorias online: decision de alcance."""

from dataclasses import dataclass
from typing import Final, Iterable




# ── vocabulario enumerable ────────────────────────────────────────────────────────────────────

MECANICA_INERTE: Final[str] = "inerte"
MECANICA_OTRA: Final[str] = "otra"
MECANICA_DESCONOCIDA: Final[str] = "desconocida"

# BL.21853 -- LOS TRES SIMBOLOS QUE ANTES COMPARTIAN EL CAJON `otra`. No se inventaron aca: son
# tipos que `object_mechanics._clasificar_cluster` ya emitia y que `direction_beliefs` colapsaba.
# FRECUENCIA MEDIDA sobre las 7.258 transiciones de `arcReplayFrames`, en el pozo de 3.000:
# recoloreo 1.539 (25 juegos), desaparicion 248 (9), aparicion 78 (8). Ninguno "por si acaso".
MECANICA_RECOLOREO: Final[str] = "recoloreo"
MECANICA_APARICION: Final[str] = "aparicion"
MECANICA_DESAPARICION: Final[str] = "desaparicion"

#: Las mecanicas VISIBLES y NO DIRECCIONALES con nombre propio. `MECANICA_OTRA` queda como el
#: residual de esa misma clase (visible, no direccional, sin nombre), no como su sinonimo.
MECANICAS_NOMBRADAS: Final[tuple[str, ...]] = (
    MECANICA_RECOLOREO,
    MECANICA_APARICION,
    MECANICA_DESAPARICION,
)

#: Orden FIJO: las sumas flotantes se hacen en este orden en los dos puertos (paridad exacta).
#: Las cuatro primeras son las direcciones de wall_perception.DIRECCIONES.
MECANICAS: Final[tuple[str, ...]] = (
    "arriba",
    "abajo",
    "izquierda",
    "derecha",
    MECANICA_INERTE,
    MECANICA_RECOLOREO,
    MECANICA_APARICION,
    MECANICA_DESAPARICION,
    MECANICA_OTRA,
    MECANICA_DESCONOCIDA,
)

ARQUETIPO_MUEVE: Final[str] = "mueveCanonico"
ARQUETIPO_SIN_MAPEO: Final[str] = "flechasSinMapeo"
ARQUETIPO_MIXTO: Final[str] = "mixto"
ARQUETIPO_SIN_FLECHAS: Final[str] = "sinFlechas"

ARQUETIPOS: Final[tuple[str, ...]] = (
    ARQUETIPO_MUEVE,
    ARQUETIPO_SIN_MAPEO,
    ARQUETIPO_MIXTO,
    ARQUETIPO_SIN_FLECHAS,
)

BOTONES_DE_FLECHA: Final[tuple[str, ...]] = ("ACTION1", "ACTION2", "ACTION3", "ACTION4")

# ── parametros del modelo (medidos o derivados de la medicion de 25 juegos) ───────────────────

#: Reparto de la masa "visible y no direccional" que antes se llevaba entera `otra`: los EVENTOS
#: que el pipeline emite sobre el corpus persistido (BL.21853, 7.258 transiciones), Laplace +1.
#: OJO CON EL DENOMINADOR -- aca estuvo MAL una vez: contar las familias del corpus ANTES del
#: cambio deja el residual en 0, `otra` en prior 1,6e-5, y los 270 pasos que SI salen `otra`
#: (mezclas de nombradas) sin donde concentrar; medido, 134 botones direccionales contra 140 sin
#: tocar nada. Estos numeros son los eventos del pipeline YA cambiado: los decide el detector, no
#: el prior, asi que no son circulares. FUENTE UNICA:
#: `mediciones/BL21853_vocabulario_de_mecanicas.json`, que `test_bl21853_vocabulario.py` compara.
CONTEO_VISIBLE_MEDIDO: Final[dict[str, int]] = {
    MECANICA_RECOLOREO: 1267,
    MECANICA_APARICION: 12,
    MECANICA_DESAPARICION: 199,
    MECANICA_OTRA: 270,
}

REPARTO_VISIBLE: Final[dict[str, float]] = {
    m: (n + 1) / (sum(CONTEO_VISIBLE_MEDIDO.values()) + len(CONTEO_VISIBLE_MEDIDO))
    for m, n in CONTEO_VISIBLE_MEDIDO.items()
}

#: Piso de la masa reservada `desconocida`: NUNCA baja de aca. 0.02 es masa suficiente para que
#: unas pocas observaciones agnosticas la hagan visible sin robarle sensibilidad al resto.
PISO_DESCONOCIDO: Final[float] = 0.02

#: Un boton esta RESUELTO cuando una mecanica concentra este posterior. Derivado, no arbitrario:
#: es el valor que UNA corrida monotona de confirmacion supera y que el prior solo (cero
#: observaciones) no alcanza en ningun conjunto medido (numeros pinneados en tests de paridad).
UMBRAL_RESOLUCION: Final[float] = 0.85

#: La senal de vocabulario incompleto se emite cuando `desconocida` acumula esta masa con al
#: menos MIN_OBSERVACIONES_VOCABULARIO observaciones del boton.
UMBRAL_VOCABULARIO_INCOMPLETO: Final[float] = 0.35
MIN_OBSERVACIONES_VOCABULARIO: Final[int] = 4

#: Verosimilitud de una traslacion observada bajo la hipotesis de direccion: DENTRO de una
#: corrida monotona el sensor es fiel (0 remapeos espurios medidos en 4 partidas); AISLADA es
#: sospechosa -- la ambiguedad objeto/hueco de BL.21561 invierte el signo de forma sistematica
#: (medido: un juego dio 20 lecturas invertidas contra 6), por eso la contraria aislada conserva
#: verosimilitud alta bajo la hipotesis correcta.
L_TRASLACION_FIEL: Final[float] = 0.9
L_TRASLACION_CONTRARIA_FIEL: Final[float] = 0.01
L_TRASLACION_AISLADA: Final[float] = 0.65
L_TRASLACION_CONTRARIA_AISLADA: Final[float] = 0.35
L_TRASLACION_ORTOGONAL: Final[float] = 0.02
L_TRASLACION_SI_INERTE: Final[float] = 0.01
#: Vale para `otra` Y para las tres nombradas: bajo CUALQUIER visible no direccional, ver una
#: traslacion limpia es igual de improbable. Un solo numero, no cuatro copias.
L_TRASLACION_SI_OTRA: Final[float] = 0.05
L_TRASLACION_AGNOSTICA: Final[float] = 0.125

#: P(pared | contexto observado). `presente` no es 1.0 ni `ausente` 0.0 a proposito: la
#: percepcion de pared es un detector (piso estimado de celdas desalojadas), no un oraculo.
P_PARED: Final[dict[str, float]] = {"presente": 0.95, "ausente": 0.05, "desconocida": 0.5}

#: P(desconocido) del fallo: el termino residual de la descomposicion del usuario. "Un fallo
#: inexplicable aporta poco pero no cero" -- este es el poco.
PISO_FALLO_INEXPLICADO: Final[float] = 0.05

L_SIN_CAMBIO_SI_INERTE: Final[float] = 0.95
L_SIN_CAMBIO_SI_OTRA: Final[float] = 0.3
L_SIN_CAMBIO_AGNOSTICA: Final[float] = 0.5

#: L(evento `otra` | mecanica). BL.21853 le cambio DOS numeros y los dos por la misma razon: el
#: evento `otra` ya no significa lo que significaba. Antes era una mecanica visible LIMPIA (un
#: recoloreo, una desaparicion) y por eso `direccion` valia 0.02 -- "un boton direccional
#: practicamente nunca hace eso". Esos casos ahora tienen simbolo propio, y lo que queda en `otra`
#: es una MEZCLA de mecanicas nombradas, que no dice nada sobre la direccion: pasa a 0.05, el mismo
#: valor agnostico de `L_DETECTOR_DESCONOCIDA`. `nombrada` es la fila nueva.
#: MEDIDO sobre 7.258 transiciones: con 0.02 el vocabulario ampliado acierta 144 botones
#: direccionales de 204 (el detector solo acierta 150); con 0.05 sube a 151.
L_OTRA_MECANICA: Final[dict[str, float]] = {
    "direccion": 0.05, "inerte": 0.02, "nombrada": 0.15, "otra": 0.6, "desconocida": 0.3,
}
L_DETECTOR_DESCONOCIDA: Final[dict[str, float]] = {
    "direccion": 0.05, "inerte": 0.03, "nombrada": 0.15, "otra": 0.2, "desconocida": 0.4,
}

#: BL.21853 -- L(evento de una mecanica NOMBRADA | mecanica del boton): la tabla que hace que el
#: simbolo nuevo VALGA algo. `propia` conserva el 0.6 que tenia `otra` -> `otra`; `hermana` (otra de
#: las nombradas) baja a 0.05; `residual` es la mecanica `otra` vista desde un evento con nombre.
#: ALCANCE HONESTO DE ESE 0.05: barrido de 0.05 a 0.60 sobre las 7.258 transiciones, las cinco
#: corridas dieron 144 aciertos direccionales de 204 -- sobre ESTE corpus el valor no decide nada.
L_MECANICA_NOMBRADA: Final[dict[str, float]] = {
    "direccion": 0.02, "inerte": 0.02, "propia": 0.6, "hermana": 0.05,
    "residual": 0.1, "desconocida": 0.3,
}

EVENTO_TRASLACION: Final[str] = "traslacion"
EVENTO_SIN_CAMBIO: Final[str] = "sinCambio"
EVENTO_OTRA: Final[str] = "otra"
EVENTO_DESCONOCIDA: Final[str] = "desconocida"

#: BL.21853 -- un evento por mecanica nombrada. El TIPO del evento es el MISMO string que el de la
#: mecanica a proposito: son la observacion y la hipotesis de la misma cosa, y tener dos alfabetos
#: paralelos (`EVENTO_RECOLOREO = "eventoRecoloreo"`) es exactamente como se desincronizan.
EVENTO_RECOLOREO: Final[str] = MECANICA_RECOLOREO
EVENTO_APARICION: Final[str] = MECANICA_APARICION
EVENTO_DESAPARICION: Final[str] = MECANICA_DESAPARICION

#: Tipos de evento que nombran una mecanica visible. FUENTE UNICA para los dos consumidores.
EVENTOS_NOMBRADOS: Final[tuple[str, ...]] = (
    EVENTO_RECOLOREO,
    EVENTO_APARICION,
    EVENTO_DESAPARICION,
)


@dataclass(frozen=True)
class EventoObservado:
    """Observacion de UN paso de UN boton, ya clasificada por la percepcion (BL.21561) y con el
    contexto de pared observado en la grilla. `pared` mapea nombre de direccion -> presente/
    ausente/desconocida; None equivale a todo desconocida (avatar aun no visto)."""

    tipo: str
    signo: tuple[int, int] | None = None
    en_corrida: bool = False
    pared: dict[str, str] | None = None


def prior_de_arquetipos(clave_conjunto: str, prior: dict | None = None) -> dict[str, float]:
    """P(arquetipo | conjunto de acciones), con Laplace sobre los juegos medidos de ESE conjunto.
    Un conjunto con flechas nunca visto cae en la tasa base de los 17 juegos con flechas. Sin
    flechas en el conjunto no hay mapeo que inferir: `sinFlechas` se lleva todo."""
    p = prior if prior is not None else DIRECTION_PRIORS
    numeros = {int(n) for n in clave_conjunto.split(",") if n.strip().isdigit()}
    if not numeros & {1, 2, 3, 4}:
        return {a: (1.0 if a == ARQUETIPO_SIN_FLECHAS else 0.0) for a in ARQUETIPOS}
    entrada = p.get("conjuntosMedidos", {}).get(clave_conjunto)
    if entrada is not None and int(entrada["juegos"]) > 0:
        juegos = int(entrada["juegos"])
        confirman = int(entrada["confirman"])
        sin_movimiento = int(entrada["sinMovimiento"])
    else:
        juegos = int(p.get("nJuegosConFlechas", 0))
        confirman = int(p.get("nJuegosQueConfirman", 0))
        sin_movimiento = int(p.get("nJuegosSinMovimientoObservable", 0))
    total = juegos + 3
    return {
        ARQUETIPO_MUEVE: (confirman + 1) / total,
        ARQUETIPO_SIN_MAPEO: (sin_movimiento + 1) / total,
        ARQUETIPO_MIXTO: (juegos - confirman - sin_movimiento + 1) / total,
        ARQUETIPO_SIN_FLECHAS: 0.0,
    }


def _con_piso(distribucion: dict[str, float]) -> dict[str, float]:
    """Clampa `desconocida` al piso reservado y renormaliza el resto: la masa nunca baja de ahi."""
    actual = distribucion[MECANICA_DESCONOCIDA]
    if actual >= PISO_DESCONOCIDO:
        return distribucion
    resto = 1.0 - actual
    escala = (1.0 - PISO_DESCONOCIDO) / resto if resto > 0 else 0.0
    salida = {m: v * escala for m, v in distribucion.items()}
    salida[MECANICA_DESCONOCIDA] = PISO_DESCONOCIDO
    return salida


def condicional_de_mecanicas(
    arquetipo: str, boton: str, prior: dict | None = None
) -> dict[str, float]:
    """P(mecanica | arquetipo, boton) -- parametrica, derivada de la medicion de 25 juegos.

    `mueveCanonico`: la masa canonica del boton sale de `juegosQueConfirmanPorAccion` (10/11 para
    A1/A2, 9/11 para A3/A4: en los juegos que confirman, una flecha individual puede seguir
    muerta -- se midio medio D-pad inerte). El resto se reparte segun los modos de fallo medidos.
    `flechasSinMapeo`: inerte domina, `otra` cubre el selector/recoloreo medido. `mixto`: difusa
    a proposito -- es el arquetipo de lo no medido."""
    p = prior if prior is not None else DIRECTION_PRIORS
    canonica_de = {a: (int(v[0]), int(v[1])) for a, v in p["mapeoCanonico"].items()}
    canonica = canonica_de.get(boton)

    def repartir(masa_canonica: float, inerte: float, visible: float, desconocida: float) -> dict[str, float]:
        """`visible` es la masa de "visible y no direccional" ENTERA -- la que antes se llevaba
        `otra` sola; BL.21853 la reparte con `REPARTO_VISIBLE`. El total no cambia."""
        otras_direcciones = 1.0 - masa_canonica - inerte - visible - desconocida
        por_direccion = otras_direcciones / 3.0
        d: dict[str, float] = {}
        for m in MECANICAS:
            if m in DIRECCIONES:
                d[m] = masa_canonica if DIRECCIONES[m] == canonica else por_direccion
            elif m == MECANICA_INERTE:
                d[m] = inerte
            elif m in REPARTO_VISIBLE:
                d[m] = visible * REPARTO_VISIBLE[m]
            else:
                d[m] = desconocida
        return _con_piso(d)

    if arquetipo == ARQUETIPO_MUEVE:
        confirman_boton = int(p.get("juegosQueConfirmanPorAccion", {}).get(boton, 0))
        confirman_total = int(p.get("nJuegosQueConfirman", 0))
        base = (confirman_boton + 1) / (confirman_total + 2) if confirman_total else 0.75
        resto = 1.0 - base
        return repartir(base, resto * 0.55, resto * 0.20, resto * 0.10)
    if arquetipo == ARQUETIPO_SIN_MAPEO:
        return repartir(0.0125, 0.60, 0.25, 0.10)
    # `mixto` y (por completitud) `sinFlechas`: difusas. Bajo `sinFlechas` no hay botones de
    # flecha sembrados, asi que su condicional jamas pesa en la practica.
    return repartir(0.30, 0.25, 0.20, 0.10)


def _verosimilitud(evento: EventoObservado, mecanica: str) -> float:
    """L(evento | mecanica del boton). No depende del arquetipo dado la mecanica: se acumula una
    sola vez por boton y se comparte entre arquetipos."""
    if evento.tipo == EVENTO_TRASLACION and evento.signo is not None:
        if mecanica in DIRECCIONES:
            d = DIRECCIONES[mecanica]
            if evento.signo == d:
                return L_TRASLACION_FIEL if evento.en_corrida else L_TRASLACION_AISLADA
            if evento.signo == (-d[0], -d[1]):
                return (
                    L_TRASLACION_CONTRARIA_FIEL if evento.en_corrida else L_TRASLACION_CONTRARIA_AISLADA
                )
            return L_TRASLACION_ORTOGONAL
        if mecanica == MECANICA_INERTE:
            return L_TRASLACION_SI_INERTE
        if mecanica in REPARTO_VISIBLE:
            return L_TRASLACION_SI_OTRA
        return L_TRASLACION_AGNOSTICA
    if evento.tipo == EVENTO_SIN_CAMBIO:
        if mecanica in DIRECCIONES:
            contexto = (evento.pared or {}).get(mecanica, PARED_DESCONOCIDA)
            p_pared = P_PARED.get(contexto, P_PARED[PARED_DESCONOCIDA])
            return p_pared + (1.0 - p_pared) * PISO_FALLO_INEXPLICADO
        if mecanica == MECANICA_INERTE:
            return L_SIN_CAMBIO_SI_INERTE
        if mecanica in REPARTO_VISIBLE:
            return L_SIN_CAMBIO_SI_OTRA
        return L_SIN_CAMBIO_AGNOSTICA
    if evento.tipo in EVENTOS_NOMBRADOS:
        # BL.21853: el evento nombra UNA mecanica. La fila que se elige es lo unico que distingue a
        # `recoloreo` de `desaparicion`; con el vocabulario de siete las dos caian en L_OTRA_MECANICA
        # y el posterior no podia separarlas ni con mil observaciones.
        if mecanica in DIRECCIONES:
            return L_MECANICA_NOMBRADA["direccion"]
        if mecanica == MECANICA_INERTE:
            return L_MECANICA_NOMBRADA["inerte"]
        if mecanica == MECANICA_DESCONOCIDA:
            return L_MECANICA_NOMBRADA["desconocida"]
        if mecanica == MECANICA_OTRA:
            return L_MECANICA_NOMBRADA["residual"]
        return L_MECANICA_NOMBRADA["propia" if mecanica == evento.tipo else "hermana"]
    tabla = L_OTRA_MECANICA if evento.tipo == EVENTO_OTRA else L_DETECTOR_DESCONOCIDA
    if mecanica in DIRECCIONES:
        return tabla["direccion"]
    if mecanica in MECANICAS_NOMBRADAS:
        return tabla["nombrada"]
    return tabla[mecanica]


class PosteriorDeMapeo:
    """Posterior conjunto {arquetipo} x {boton -> mecanica}, exacto por enumeracion. UNA instancia
    por partida. `sembrar` fija el conjunto (la clave del prior); `observar` acumula verosimilitud;
    las lecturas se recalculan al pedirlas (tabla chica: 4 arquetipos x <=4 botones x 7 mecanicas)."""

    def __init__(self, prior: dict | None = None) -> None:
        self._prior = prior if prior is not None else DIRECTION_PRIORS
        self._arquetipos: dict[str, float] = {a: 0.0 for a in ARQUETIPOS}
        self._condicionales: dict[str, dict[str, dict[str, float]]] = {}
        self._lambda: dict[str, dict[str, float]] = {}
        self._observaciones: dict[str, int] = {}
        self._sembrado = False

    def sembrar(self, available_actions: Iterable[int]) -> int:
        """Idempotente; devuelve cuantos botones de flecha quedaron bajo inferencia."""
        if self._sembrado:
            return 0
        self._sembrado = True
        numeros = sorted(set(int(n) for n in available_actions))
        clave = ",".join(str(n) for n in numeros)
        self._arquetipos = prior_de_arquetipos(clave, self._prior)
        presentes = {f"ACTION{n}" for n in numeros}
        for boton in BOTONES_DE_FLECHA:
            if boton not in presentes:
                continue
            self._lambda[boton] = {m: 1.0 for m in MECANICAS}
            self._observaciones[boton] = 0
            self._condicionales[boton] = {
                a: condicional_de_mecanicas(a, boton, self._prior) for a in ARQUETIPOS
            }
        return len(self._lambda)

    @property
    def botones(self) -> list[str]:
        return [b for b in BOTONES_DE_FLECHA if b in self._lambda]

    def observaciones_de(self, boton: str) -> int:
        return self._observaciones.get(boton, 0)

    def observar(self, boton: str, evento: EventoObservado) -> None:
        acumulado = self._lambda.get(boton)
        if acumulado is None:
            return
        maximo = 0.0
        for m in MECANICAS:
            acumulado[m] *= _verosimilitud(evento, m)
            if acumulado[m] > maximo:
                maximo = acumulado[m]
        # Renormalizacion por el maximo: evita el underflow de cientos de productos y se cancela
        # en todos los cocientes del posterior (misma operacion en los dos puertos).
        if maximo > 0.0:
            for m in MECANICAS:
                acumulado[m] /= maximo
        self._observaciones[boton] = self._observaciones.get(boton, 0) + 1

    def posterior_de_arquetipo(self) -> dict[str, float]:
        pesos: dict[str, float] = {}
        for a in ARQUETIPOS:
            v = self._arquetipos.get(a, 0.0)
            for b in self.botones:
                cond = self._condicionales[b][a]
                v *= sum(cond[m] * self._lambda[b][m] for m in MECANICAS)
            pesos[a] = v
        total = sum(pesos.values())
        if total <= 0.0:
            return {a: 1.0 / len(ARQUETIPOS) for a in ARQUETIPOS}
        return {a: v / total for a, v in pesos.items()}

    def posterior_de(self, boton: str) -> dict[str, float] | None:
        """P(mecanica | boton, datos), marginalizando el arquetipo. Con el piso aplicado: la masa
        `desconocida` nunca baja de PISO_DESCONOCIDO."""
        if boton not in self._lambda:
            return None
        post_a = self.posterior_de_arquetipo()
        resultado = {m: 0.0 for m in MECANICAS}
        for a in ARQUETIPOS:
            pa = post_a[a]
            if pa <= 0.0:
                continue
            cond = self._condicionales[boton][a]
            z = sum(cond[m] * self._lambda[boton][m] for m in MECANICAS)
            if z <= 0.0:
                continue
            for m in MECANICAS:
                resultado[m] += pa * cond[m] * self._lambda[boton][m] / z
        return _con_piso(resultado)

    def mecanica_dominante(self, boton: str) -> tuple[str, float] | None:
        posterior = self.posterior_de(boton)
        if posterior is None:
            return None
        dominante = max(MECANICAS, key=lambda m: posterior[m])
        return (dominante, posterior[dominante])

    def direccion_de(self, boton: str) -> tuple[int, int] | None:
        dominante = self.mecanica_dominante(boton)
        if dominante is None or dominante[0] not in DIRECCIONES:
            return None
        return DIRECCIONES[dominante[0]]

    def resuelta(self, boton: str) -> bool:
        """El posterior concentro: deja de valer la pena gastar presupuesto en este boton. Exige
        al menos una observacion -- el prior solo jamas resuelve (el mas confiado de los conjuntos
        medidos queda por debajo del umbral, pinneado en tests)."""
        if self._observaciones.get(boton, 0) < 1:
            return False
        dominante = self.mecanica_dominante(boton)
        return dominante is not None and dominante[1] >= UMBRAL_RESOLUCION

    def inerte(self, boton: str) -> bool:
        dominante = self.mecanica_dominante(boton)
        return (
            dominante is not None
            and dominante[0] == MECANICA_INERTE
            and dominante[1] >= UMBRAL_RESOLUCION
        )

    def senal_de_vocabulario_incompleto(self) -> list[tuple[str, float]]:
        """Botones cuya masa `desconocida` acumulo por encima del umbral con evidencia suficiente:
        el vocabulario de mecanicas no explica lo observado. Se registra, no se inventa online."""
        senal: list[tuple[str, float]] = []
        for boton in self.botones:
            if self._observaciones.get(boton, 0) < MIN_OBSERVACIONES_VOCABULARIO:
                continue
            posterior = self.posterior_de(boton)
            if posterior is not None and posterior[MECANICA_DESCONOCIDA] >= UMBRAL_VOCABULARIO_INCOMPLETO:
                senal.append((boton, posterior[MECANICA_DESCONOCIDA]))
        return senal

    def resumen(self) -> str:
        """Linea legible para el reasoning persistido (la 'firma en el reporte' del BL: la senal
        de vocabulario incompleto viaja aca y queda registrada en el corpus de la partida)."""
        if not self._lambda:
            return "posterior sin botones de flecha"
        post_a = self.posterior_de_arquetipo()
        arquetipo = max(ARQUETIPOS, key=lambda a: post_a[a])
        partes = [f"arquetipo={arquetipo}:{post_a[arquetipo]:.2f}"]
        for boton in self.botones:
            dominante = self.mecanica_dominante(boton)
            if dominante is not None:
                partes.append(f"{boton}={dominante[0]}:{dominante[1]:.2f}")
        vocabulario = self.senal_de_vocabulario_incompleto()
        if vocabulario:
            detalle = ",".join(f"{b}:{masa:.2f}" for b, masa in vocabulario)
            partes.append(f"vocabularioIncompleto={detalle}")
        return " ".join(partes)


# ============================== arc_agent/direction_beliefs.py ==============================
"""[arc-agi3-kaggle-agent/direction_beliefs] BL.21590 -- CREENCIA de mapeo de direcciones sembrada
por el prior y VALIDADA EN PARTIDA dentro de las macro-acciones, mas la INCOGNITA de mecanica de
ACTION5/ACTION7. Espejo de arc-agi-runner/src/worldModel/directionBeliefs.ts (paridad exacta:
tests homonimos sobre la misma grabacion real).

QUE PROBLEMA RESUELVE. El detector de BL.21561 recupera (dy,dx) de forma parametrica, pero exige
MIN_OBSERVACIONES_DE_MECANICA observaciones de la MISMA firma por accion antes de afirmar nada.
Medido sobre las partidas grabadas, eso son 10+ pasos de redescubrimiento por juego -- y en un
episodio de ARC cada paso gastado en aprender lo que ya sabemos de 25 juegos es un paso que el
score penaliza de forma cuadratica. El prior siembra la creencia en el paso CERO; el detector, sin
cambios, la confirma o la corrige.

TRES RESULTADOS POR PULSACION, NUNCA DOS:
  - se movio como predecia el prior  -> `confirma`
  - se movio en otra direccion       -> `refuta`
  - NO se movio (o hizo otra cosa)   -> `inconcluso`, que NO es una refutacion: puede ser una pared,
    una pantalla de titulo o una mecanica no direccional. Tratarlo como refutacion es el error facil
    de este BL y produce remapeo espurio -- con una pared el posterior casi no se mueve.

LA VALIDACION VIAJA DENTRO DE LAS MACROS (BL.21559), NO EN UNA SONDA APARTE. La medicion dejo dos
trampas escritas: la pantalla de titulo (quien mide sin clickear mide el menu -- de eso se ocupa
opening_book.py) y el round-robin, que FABRICA mapeos invertidos: un juego dio ACTION4->izquierda
20 veces contra 6 por la ambiguedad objeto/hueco de BL.21561, y el protocolo guionado (misma
accion N veces seguidas, posicion absoluta monotona) lo desarmo. Por eso confirmar, remapear y
adoptar exigen una CORRIDA MONOTONA: `PASOS_DE_CORRIDA_MONOTONA` traslaciones del MISMO signo en
pulsaciones CONSECUTIVAS de la MISMA accion. Las macro-acciones ya repiten la accion mientras
mueva el tablero, asi que la corrida sale gratis: CERO acciones dedicadas solo a validar. Una
pulsacion sin movimiento en el medio de la corrida NO la rompe (la posicion absoluta no
retrocedio: es una pared); una traslacion de otro signo, o una pulsacion de otra accion, si.

EL PRIOR ES REFUTABLE POR DISENO. Si el juego privado contradice, gana la OBSERVACION: la creencia
se remapea y el estado pasa a `remapeada`. Un agente que no puede refutar su propio prior es peor
que uno sin prior, porque falla con confianza.

ACTION5/ACTION7 NO TIENEN PRIOR POSIBLE (medido: cuatro comportamientos distintos en 12 juegos y
ninguno predomina). Entran como INCOGNITA UNIFORME sobre firmas de mecanica {inerte, toggle,
disparo, cambioDeEscena, desconocido}: `IncognitasDeMecanica` acumula evidencia por accion y su
posterior arranca uniforme -- que significa "no sabemos", no "no hace nada".
"""

from dataclasses import dataclass, field
from typing import Final, Iterable

# Imports relativos SIEMPRE en una linea: el builder del notebook los desmonta con un regex
# ^from \.\w* import .+$ que no cubre la forma con parentesis multilinea.




# Import a UN solo nivel (`.world_model`, no `.world_model.object_mechanics`): el builder del
# notebook desmonta los imports relativos con el regex `^from \.\w* import .+$`, que no cubre un
# segundo punto -- con la forma anidada el notebook de submission queda con un ImportError.



#: Mapeo canonico medido, ya normalizado a SIGNO. Fuente unica: priors.py (generado).
MAPEO_CANONICO: Final[dict[str, tuple[int, int]]] = {
    accion: (int(v[0]), int(v[1]))
    for accion, v in DIRECTION_PRIORS["mapeoCanonico"].items()
}

#: Las cuatro acciones con prior de direccion, en orden canonico. ACTION5/6/7 NO estan y es un
#: resultado medido, no una omision (ver `accionesSinPriorDeDireccion` en priors.py).
ACCIONES_CON_PRIOR: Final[tuple[str, ...]] = tuple(sorted(MAPEO_CANONICO))

RESULTADO_CONFIRMA: Final[str] = "confirma"
RESULTADO_REFUTA: Final[str] = "refuta"
RESULTADO_INCONCLUSO: Final[str] = "inconcluso"

ESTADO_SIN_PRIOR: Final[str] = "sinPrior"
ESTADO_SEMBRADA: Final[str] = "sembrada"
ESTADO_CONFIRMADA: Final[str] = "confirmada"
ESTADO_REMAPEADA: Final[str] = "remapeada"
ESTADO_OBSERVADA: Final[str] = "observada"
ESTADO_SIN_EVIDENCIA: Final[str] = "sinEvidencia"

#: Pulsaciones CONSECUTIVAS de la misma accion con traslacion del MISMO signo que hacen falta para
#: fijar una creencia -- confirmar el prior, remapearlo o adoptar direccion en una accion sin prior.
#: 2 es el minimo que constituye una corrida monotona: el numero que sale de UNA pulsacion aislada
#: es exactamente el que la ambiguedad objeto/hueco invierte de forma sistematica (medido: la unica
#: "excepcion" candidata de los 25 juegos era ese artefacto, y la corrida monotona la tumbo).
PASOS_DE_CORRIDA_MONOTONA: Final[int] = 2


def clave_de_conjunto(available_actions: Iterable[int]) -> str:
    """Forma canonica del conjunto de acciones disponibles -- la UNICA clave con la que se indexa el
    prior. Nunca el game_id: los juegos de la evaluacion son privados y una clave por partida vale
    cero ahi, mientras que `available_actions` viene en cada frame."""
    return ",".join(str(n) for n in sorted(set(int(n) for n in available_actions)))


def _signo(valor: int) -> int:
    return (valor > 0) - (valor < 0)


def direccion_de_traslacion(mecanica: Mecanica | None) -> tuple[int, int] | None:
    """Signo (dy,dx) de la traslacion de una mecanica, o None si el paso no es una traslacion util.

    Se descartan las DIAGONALES: ninguna flecha de un D-pad mueve en diagonal, y las dos que se
    midieron eran basura (un salto espurio de (-6,+18) y un cambio de escena de ACTION5). Contarlas
    como direccion habria producido un remapeo a una direccion que no existe en el mando."""
    if mecanica is None or mecanica.tipo != "traslacion":
        return None
    t = mecanica.traslacion_principal
    if t is None:
        return None
    dy, dx = _signo(t.dy), _signo(t.dx)
    if dy != 0 and dx != 0:
        return None
    if dy == 0 and dx == 0:
        return None
    return (dy, dx)


def _evento_sin_traslacion(
    mecanica: Mecanica | None, pared: dict[str, str] | None
) -> EventoObservado:
    """BL.21593 -- clasifica para el posterior un paso SIN traslacion util: `sinCambio` lleva el
    contexto de pared (la descomposicion del fallo); una mecanica visible no direccional es
    `otra`; lo que el detector no supo nombrar (incluida una traslacion diagonal) es
    `desconocida` y alimenta la masa reservada.

    BL.21741 -- "no lo medi" NO es "no paso nada": ver `TIPO_SIN_MEDICION`. Va a la masa reservada
    `desconocida`, que es lo que "no se" significa en el posterior.

    BL.21741 (correccion) -- Y LOS DOS "NO MIRE" TAMPOCO SON LO MISMO. `sobreElTope` caia por todas
    las ramas hasta el `desconocida` del final, o sea a `L_DETECTOR_DESCONOCIDA`, una verosimilitud
    calibrada para "el detector MIRO y no supo". Un cambio por encima del tope no es eso: el
    detector no miro los CLUSTERS pero conto las celdas, y ese conteo es exacto y enorme. Una
    mecanica visible que ademas NO puede ser una traslacion (un cluster de mas de
    2 * MAX_TAMANO_OBJETO celdas jamas cabe en `R U (R+d)`) es exactamente `otra` -- la misma
    lectura que hace `IncognitaDeMecanica` mandandolo a `cambioDeEscena`. Hoy la rama es
    inalcanzable en ARC-AGI-3 (el tope es el area de la grilla), y esa es justamente la razon por la
    que el defecto era invisible: queda correcta para cualquier grilla de otro tamano."""
    if mecanica is not None and mecanica.tipo == TIPO_SIN_MEDICION:
        return EventoObservado(tipo=EVENTO_DESCONOCIDA)
    if mecanica is not None and mecanica.tipo in TIPOS_DE_NO_MIRE:
        # El unico "no mire" que queda: `sobreElTope`. Se lee de la fuente unica y no del literal,
        # para que agregar un tipo de "no mire" obligue a decidir aca en vez de caer por descarte.
        return EventoObservado(tipo=EVENTO_OTRA)
    if mecanica is None or mecanica.tipo == "sinCambio" or mecanica.celdas_cambiadas == 0:
        return EventoObservado(tipo=EVENTO_SIN_CAMBIO, pared=pared)
    if mecanica.tipo in EVENTOS_NOMBRADOS:
        # BL.21853 -- antes los tres caian juntos en `EVENTO_OTRA` y el posterior no podia separar
        # un boton que recolorea de uno que borra objetos. La lista es la constante que define los
        # simbolos, no un literal repetido: tipo de cluster y tipo de evento comparten string.
        return EventoObservado(tipo=mecanica.tipo)
    if (
        mecanica.tipo == TIPO_SIN_NOMBRAR
        and mecanica.clusters
        and all(c.tipo != TIPO_SIN_NOMBRAR for c in mecanica.clusters)
    ):
        # BL.21853 -- "mire, NOMBRE cada parte y el conjunto es una MEZCLA" no es "no supe que
        # paso": `detectar_mecanica` devuelve `desconocida` en los dos casos (el tipo global
        # colapsa en cuanto los clusters difieren) y los dos alimentaban la masa reservada. Una
        # mezcla de mecanicas nombradas es una mecanica VISIBLE no direccional -- `otra` -- y es
        # la poblacion viva que le queda a ese simbolo sobre las 7.258 transiciones del corpus.
        return EventoObservado(tipo=EVENTO_OTRA)
    return EventoObservado(tipo=EVENTO_DESCONOCIDA)


@dataclass
class CreenciaDeDireccion:
    """Creencia vigente sobre UNA accion. `direccion` es SIEMPRE un signo; `magnitud` es el ultimo
    (dy,dx) crudo observado y arranca en None a proposito: el prior fija la direccion y jamas la
    magnitud, que se midio entre 2 y 6 celdas segun el juego."""

    accion: str
    direccion: tuple[int, int] | None
    origen: str
    estado: str
    confirmaciones: int = 0
    refutaciones: int = 0
    inconclusos: int = 0
    magnitud: tuple[int, int] | None = None
    #: Corrida monotona vigente: signo observado y cuantas pulsaciones CONSECUTIVAS de esta accion
    #: lo repitieron. Se corta con otra accion en el medio o con una traslacion de otro signo; una
    #: pulsacion sin movimiento (pared) la pausa pero no la corta.
    corrida_direccion: tuple[int, int] | None = None
    corrida_pasos: int = 0


class CreenciaDeDirecciones:
    """Mapeo accion -> direccion del episodio. UNA instancia por partida."""

    def __init__(self, prior: dict | None = None) -> None:
        self._prior = prior if prior is not None else DIRECTION_PRIORS
        self._canonico = {
            accion: (int(v[0]), int(v[1]))
            for accion, v in self._prior["mapeoCanonico"].items()
        }
        self._creencias: dict[str, CreenciaDeDireccion] = {}
        self._sembradas: list[str] = []
        self._sembrada = False
        self._clave_del_conjunto = ""
        self._accion_previa: str | None = None
        self.observaciones = 0
        # BL.21593 -- el posterior jerarquico {arquetipo} x {boton -> mecanica} corre en paralelo
        # a la maquina de estados: recibe CADA observacion (con su contexto de pared) y es quien
        # decide `resuelta` cuando concentra. La maquina de estados de BL.21590 conserva la
        # decision de REMAPEO (corrida monotona) y la auditoria (confirmada/remapeada/...).
        self.posterior = PosteriorDeMapeo(prior)

    # ── siembra ────────────────────────────────────────────────────────────────────────────────

    def sembrar(self, available_actions: Iterable[int]) -> int:
        """Siembra la creencia inicial para las flechas presentes en `available_actions`. Devuelve
        cuantas sembro. Idempotente: solo la PRIMERA siembra del episodio cuenta.

        Se siembra el SUBCONJUNTO presente, no las cuatro: la medicion encontro un juego con D-pad
        parcial (solo horizontal), asi que asumir que las cuatro flechas vienen siempre juntas es
        falso. Un conjunto nunca visto recibe el mismo trato -- el prior describe el BOTON, no el
        conjunto, y el conjunto solo aporta la confianza."""
        if self._sembrada:
            return 0
        self._sembrada = True
        acciones = list(available_actions)
        self._clave_del_conjunto = clave_de_conjunto(acciones)
        self.posterior.sembrar(acciones)  # BL.21593: mismo conjunto, misma unica siembra
        disponibles = {f"ACTION{n}" for n in acciones}
        sembradas = 0
        for accion in sorted(self._canonico):
            if accion not in disponibles:
                continue
            self._creencias[accion] = CreenciaDeDireccion(
                accion=accion,
                direccion=self._canonico[accion],
                origen="prior",
                estado=ESTADO_SEMBRADA,
            )
            self._sembradas.append(accion)
            sembradas += 1
        return sembradas

    @property
    def clave_del_conjunto(self) -> str:
        return self._clave_del_conjunto

    def confianza_del_conjunto(self) -> float:
        """Probabilidad estimada de que el prior aplique en un juego de ESTE conjunto de acciones,
        con suavizado de Laplace sobre los juegos medidos. Un conjunto nunca visto cae en la tasa
        base de todos los juegos con flechas. NO se usa para decidir: se usa para poder decir en voz
        alta cuanta evidencia hay detras -- 11 juegos confirman y 6 no falsifican."""
        medidos = self._prior.get("conjuntosMedidos", {})
        entrada = medidos.get(self._clave_del_conjunto)
        if entrada is not None and int(entrada["juegos"]) > 0:
            return (int(entrada["confirman"]) + 1) / (int(entrada["juegos"]) + 2)
        confirman = int(self._prior.get("nJuegosQueConfirman", 0))
        con_flechas = int(self._prior.get("nJuegosConFlechas", 0))
        return (confirman + 1) / (con_flechas + 2) if con_flechas else 0.5

    # ── validacion en partida ──────────────────────────────────────────────────────────────────

    def observar(
        self, accion: str, mecanica: Mecanica | None, pared: dict[str, str] | None = None
    ) -> str:
        """Clasifica el efecto observado de `accion` contra la creencia vigente y la actualiza.
        Devuelve `confirma`, `refuta` o `inconcluso`.

        TODA fijacion exige una corrida monotona (ver el docstring del modulo): la evidencia se
        acumula solo mientras la MISMA accion se repite en pasos consecutivos con el mismo signo,
        que es exactamente lo que una macro-accion produce. Una accion SIN prior (ACTION5/6/7 o
        cualquiera fuera del D-pad) nunca confirma ni refuta -- no hay prediccion que contrastar --
        pero una corrida monotona suya le adjudica direccion con estado `observada`.

        BL.21593 -- la MISMA observacion alimenta el posterior jerarquico, con `pared` como
        contexto observable del fallo (wall_perception.py): un fallo con pared adyacente en la
        direccion de la hipotesis queda explicado y no mueve el posterior del mapeo."""
        self.observaciones += 1
        observada = direccion_de_traslacion(mecanica)
        creencia = self._creencias.get(accion)
        misma_corrida = accion == self._accion_previa
        self._accion_previa = accion

        if creencia is None:
            creencia = CreenciaDeDireccion(
                accion=accion, direccion=None, origen="observacion", estado=ESTADO_SIN_PRIOR
            )
            self._creencias[accion] = creencia

        if observada is None:
            self.posterior.observar(accion, _evento_sin_traslacion(mecanica, pared))
            creencia.inconclusos += 1
            # Pared en el medio de la corrida: la posicion absoluta no retrocedio, la corrida se
            # PAUSA. Si en cambio la accion viene de interrumpir a otra, no hay corrida que heredar.
            if not misma_corrida:
                creencia.corrida_direccion = None
                creencia.corrida_pasos = 0
            return RESULTADO_INCONCLUSO

        if mecanica is not None and mecanica.traslacion_principal is not None:
            creencia.magnitud = (
                mecanica.traslacion_principal.dy,
                mecanica.traslacion_principal.dx,
            )

        if misma_corrida and creencia.corrida_direccion == observada:
            creencia.corrida_pasos += 1
        else:
            creencia.corrida_direccion = observada
            creencia.corrida_pasos = 1

        # BL.21593 -- la traslacion entra al posterior con su fiabilidad medida: dentro de una
        # corrida monotona el sensor es fiel; aislada, la ambiguedad objeto/hueco la vuelve
        # sospechosa y su verosimilitud lo refleja.
        self.posterior.observar(
            accion,
            EventoObservado(
                tipo=EVENTO_TRASLACION,
                signo=observada,
                en_corrida=creencia.corrida_pasos >= PASOS_DE_CORRIDA_MONOTONA,
            ),
        )

        if creencia.direccion == observada:
            creencia.confirmaciones += 1
            if creencia.corrida_pasos >= PASOS_DE_CORRIDA_MONOTONA:
                if creencia.origen == "prior":
                    creencia.estado = ESTADO_CONFIRMADA
                elif creencia.estado != ESTADO_REMAPEADA:
                    # `remapeada` NO se pisa con `observada`: que el prior fue refutado es
                    # informacion que la auditoria de la partida necesita conservar.
                    creencia.estado = ESTADO_OBSERVADA
            return RESULTADO_CONFIRMA

        # Contradiccion (o traslacion de una accion sin prediccion). Solo una corrida monotona
        # remapea/adopta: la pulsacion aislada es la forma exacta del artefacto medido.
        habia_prediccion = creencia.direccion is not None
        if habia_prediccion:
            creencia.refutaciones += 1
        if creencia.corrida_pasos >= PASOS_DE_CORRIDA_MONOTONA:
            creencia.direccion = observada
            creencia.origen = "observacion"
            creencia.estado = ESTADO_REMAPEADA if habia_prediccion else ESTADO_OBSERVADA
            creencia.confirmaciones = 0

        # Sin prediccion previa no hay nada que refutar: la traslacion es evidencia pura y el
        # resultado honesto es INCONCLUSO respecto del prior (que para esa accion no existe).
        return RESULTADO_REFUTA if habia_prediccion else RESULTADO_INCONCLUSO

    def declarar_sin_evidencia(self, accion: str) -> None:
        """El libro de aperturas agoto sus intentos sin ver una sola traslacion. La creencia NO se
        borra (el prior sigue siendo la mejor hipotesis disponible), pero se marca para no seguir
        gastando acciones en confirmarla: en 6 de los 17 juegos medidos con flechas, no hay mapeo
        que confirmar y el presupuesto se redistribuye."""
        creencia = self._creencias.get(accion)
        if creencia is not None and creencia.estado == ESTADO_SEMBRADA:
            creencia.estado = ESTADO_SIN_EVIDENCIA

    # ── lectura ────────────────────────────────────────────────────────────────────────────────

    def direccion_de(self, accion: str) -> tuple[int, int] | None:
        creencia = self._creencias.get(accion)
        return None if creencia is None else creencia.direccion

    def magnitud_de(self, accion: str) -> tuple[int, int] | None:
        """(dy,dx) CRUDO de la ultima traslacion observada. None mientras no se haya medido: el
        prior no predice magnitudes."""
        creencia = self._creencias.get(accion)
        return None if creencia is None else creencia.magnitud

    def estado_de(self, accion: str) -> str:
        creencia = self._creencias.get(accion)
        return ESTADO_SIN_PRIOR if creencia is None else creencia.estado

    def resuelta(self, accion: str) -> bool:
        """La creencia sobre `accion` ya no necesita mas sondeo.

        BL.21593 -- ademas de los estados terminales de la maquina de BL.21590, resuelve el
        POSTERIOR cuando concentra (>= UMBRAL_RESOLUCION): es lo que deja de gastar presupuesto
        en una flecha muerta a la que el arquetipo ya condeno con la evidencia de sus hermanas,
        sin esperar los intentos espaciados del libro."""
        if self.estado_de(accion) in (
            ESTADO_CONFIRMADA,
            ESTADO_REMAPEADA,
            ESTADO_OBSERVADA,
            ESTADO_SIN_EVIDENCIA,
        ):
            return True
        return self.posterior.resuelta(accion)

    def acciones_sembradas(self) -> list[str]:
        """Flechas que el prior sembro al arrancar, en orden canonico. Es la lista que el libro de
        aperturas valida: una accion que aparecio solo por observacion no tiene prior que confirmar."""
        return list(self._sembradas)

    def mapeo(self) -> dict[str, tuple[int, int]]:
        """Mapeo vigente accion -> signo (dy,dx), solo con las acciones que tienen creencia."""
        return {
            a: c.direccion
            for a, c in sorted(self._creencias.items())
            if c.direccion is not None
        }

    def resumen(self) -> str:
        """Linea legible para el `reasoning` persistido -- auditar la partida sin re-derivar nada."""
        if not self._creencias:
            return "sin creencia de direcciones (el juego no habilita flechas)"
        partes = [
            f"{a}={c.direccion[0]},{c.direccion[1]}:{c.estado}"
            if c.direccion is not None
            else f"{a}=?:{c.estado}"
            for a, c in sorted(self._creencias.items())
        ]
        return " ".join(partes)


# ── ACTION5/ACTION7: incognita uniforme sobre firmas de mecanica ──────────────────────────────

FIRMA_INERTE: Final[str] = "inerte"
FIRMA_TOGGLE: Final[str] = "toggle"
FIRMA_DISPARO: Final[str] = "disparo"
FIRMA_CAMBIO_DE_ESCENA: Final[str] = "cambioDeEscena"
FIRMA_DESCONOCIDA: Final[str] = "desconocido"

#: El soporte COMPLETO de la incognita. Son las cuatro firmas que la sonda de 25 juegos midio para
#: ACTION5/ACTION7 (inerte en 4 juegos, toggle en 1, recoloreo tipo disparo en 2, cambio masivo de
#: escena en 1) mas `desconocido` para lo que no calza en ninguna.
FIRMAS_DE_MECANICA: Final[tuple[str, ...]] = (
    FIRMA_INERTE,
    FIRMA_TOGGLE,
    FIRMA_DISPARO,
    FIRMA_CAMBIO_DE_ESCENA,
    FIRMA_DESCONOCIDA,
)

#: Acciones que entran como incognita: las dos sin prior posible. ACTION6 queda AFUERA porque su
#: efecto depende de la coordenada y ya tiene su propia maquinaria (BL.21560).
ACCIONES_DE_INCOGNITA: Final[tuple[str, ...]] = ("ACTION5", "ACTION7")

#: Celdas cambiadas a partir de las cuales una observacion se clasifica cambio de escena. Medido:
#: el unico juego con esa firma cambiaba 180-190 celdas por pulsacion; el recoloreo tipo disparo,
#: 30-60. 100 parte esa distancia sin rozar ninguno de los dos lados.
CELDAS_DE_CAMBIO_DE_ESCENA: Final[int] = 100


@dataclass
class IncognitaDeMecanica:
    """Evidencia acumulada sobre la mecanica de UNA accion sin prior. El posterior arranca UNIFORME
    (Laplace +1 sobre cero observaciones): la ausencia de prior es "no sabemos", jamas "no hace
    nada". Bayes exacto enumerable: cinco firmas, conteos enteros, sin aproximaciones."""

    conteos: dict[str, int] = field(
        default_factory=lambda: {firma: 0 for firma in FIRMAS_DE_MECANICA}
    )
    _ultimo_cambio_de_color: tuple[int, int] | None = None

    def observar(self, mecanica: Mecanica) -> str:
        firma = self._clasificar(mecanica)
        self.conteos[firma] += 1
        return firma

    def _clasificar(self, mecanica: Mecanica) -> str:
        # BL.21741: "no lo medi" antes de "no paso nada" (ver `TIPO_SIN_MEDICION`). `sobreElTope`
        # NO entra aca a proposito: su conteo de celdas es exacto y cae solo en `cambioDeEscena`.
        if mecanica.tipo == TIPO_SIN_MEDICION:
            self._ultimo_cambio_de_color = None
            return FIRMA_DESCONOCIDA
        if mecanica.tipo == "sinCambio" or mecanica.celdas_cambiadas == 0:
            self._ultimo_cambio_de_color = None
            return FIRMA_INERTE
        if mecanica.celdas_cambiadas >= CELDAS_DE_CAMBIO_DE_ESCENA:
            self._ultimo_cambio_de_color = None
            return FIRMA_CAMBIO_DE_ESCENA
        cambio = mecanica.cambio_de_color_principal
        if cambio is None:
            self._ultimo_cambio_de_color = None
            return FIRMA_DESCONOCIDA
        par = (cambio.desde, cambio.hasta)
        previo = self._ultimo_cambio_de_color
        self._ultimo_cambio_de_color = par
        if previo == (par[1], par[0]):
            return FIRMA_TOGGLE  # alterna A->B, B->A: el boton des-hace lo que hizo
        if previo == par:
            return FIRMA_DISPARO  # repite el MISMO recoloreo: tipo "usar/disparar"
        return FIRMA_DESCONOCIDA  # primer recoloreo: todavia no se sabe si alterna o repite

    def posterior(self) -> dict[str, float]:
        total = sum(self.conteos.values()) + len(FIRMAS_DE_MECANICA)
        return {firma: (n + 1) / total for firma, n in self.conteos.items()}

    def dominante(self) -> str | None:
        """Firma con mas evidencia, o None mientras el posterior siga uniforme o empatado."""
        maximo = max(self.conteos.values())
        if maximo == 0:
            return None
        ganadoras = [f for f, n in self.conteos.items() if n == maximo]
        return ganadoras[0] if len(ganadoras) == 1 else None


class IncognitasDeMecanica:
    """Incognitas por accion. UNA instancia por partida; solo acumula para ACTION5/ACTION7."""

    def __init__(self) -> None:
        self._por_accion: dict[str, IncognitaDeMecanica] = {}

    def observar(self, accion: str, mecanica: Mecanica) -> str | None:
        if accion not in ACCIONES_DE_INCOGNITA:
            return None
        incognita = self._por_accion.setdefault(accion, IncognitaDeMecanica())
        return incognita.observar(mecanica)

    def posterior_de(self, accion: str) -> dict[str, float]:
        incognita = self._por_accion.get(accion, IncognitaDeMecanica())
        return incognita.posterior()

    def dominante_de(self, accion: str) -> str | None:
        incognita = self._por_accion.get(accion)
        return None if incognita is None else incognita.dominante()

    def conteos_de(self, accion: str) -> dict[str, int]:
        incognita = self._por_accion.get(accion, IncognitaDeMecanica())
        return dict(incognita.conteos)

    def resumen(self) -> str:
        if not self._por_accion:
            return "sin observaciones de ACTION5/ACTION7"
        partes = [
            f"{a}={self._por_accion[a].dominante() or 'incognita'}"
            for a in sorted(self._por_accion)
        ]
        return " ".join(partes)


# ============================== arc_agent/opening_book.py ==============================
"""[arc-agi3-kaggle-agent/opening_book] BL.21590 -- LIBRO DE APERTURAS: maquina de fases
WARMUP -> IDENTIFICAR -> EXPLOTAR que saca al agente de la trampa de la pantalla de titulo y
dirige la PRIMERA macro de cada flecha, sin gastar una sola accion dedicada solo a validar.

LA TRAMPA, medida sobre los 25 juegos publicos: 5 arrancan en un estado donde las flechas no
tocan el tablero. Sin clicks previos un juego daba ACTION1 == ACTION3 y ACTION2 == ACTION4 -- un
mapeo imposible; tras nueve clicks de ACTION6 el mapeo canonico salio limpio. Quien mide sin
clickear primero mide el menu, no el juego. Y ACTION6 esta disponible en el 100% de los juegos
sin flechas medidos: cuando las flechas no hacen nada, el click es la unica llave plausible.

LAS TRES FASES, con transiciones observables (cada una tiene test propio):

  WARMUP       una pulsacion de TANTEO por flecha sembrada, en orden canonico. El tanteo no mide
               direccion (eso exige corridas monotonas, ver direction_beliefs.py): mide si el
               tablero RESPONDE. Alguna flecha movio -> IDENTIFICAR. Ninguna movio y hay ACTION6
               -> clickear (hasta CLICS_DE_WARMUP); tras cada click QUE CAMBIO el tablero se
               vuelve a tantear (el estado pudo dejar de ser el menu), hasta RONDAS_DE_TANTEO
               rondas. Los tanteos previos a un click efectivo midieron EL MENU y no cuentan como
               intentos de identificacion. Presupuesto agotado -> IDENTIFICAR igual.

  IDENTIFICAR  dirige la PRIMERA macro de cada flecha sin resolver: la macro repite la accion
               mientras mueva el tablero (BL.21559), que es exactamente la corrida monotona que
               la creencia exige para confirmar o remapear. Un `inconcluso` difiere el reintento
               PASOS_ANTES_DE_REINTENTAR pasos -- reintentar en el acto vuelve a medir la MISMA
               pared -- y al agotar INTENTOS_POR_ACCION intentos ESPACIADOS la flecha queda
               `sinEvidencia`: en 6 de los 17 juegos medidos con flechas no hay mapeo que
               confirmar (medio D-pad muerto, eje no observable, flechas inertes) y el presupuesto
               se redistribuye solo, porque el libro deja de sugerirla. Nada de insistir contra la
               evidencia. Todas resueltas -> EXPLOTAR.

  EXPLOTAR     el libro no sugiere mas y la politica explora con la creencia ya validada. Un
               juego sin flechas sembradas arranca directamente aca.

COSTO CERO POR DISENO. Ninguna sugerencia es una accion "solo para validar": los tanteos y las
macros son exploracion que la politica haria igual, y los clicks de warmup son lo unico que puede
arrancar un juego que espera un click. El libro elige el ORDEN de la exploracion, no agrega pasos
-- `pasos_guiados` lo cuenta para poder auditarlo, no porque sea un gasto.
"""

from typing import Final, Iterable




FASE_WARMUP: Final[str] = "warmup"
FASE_IDENTIFICAR: Final[str] = "identificar"
FASE_EXPLOTAR: Final[str] = "explotar"

#: Clicks de ACTION6 que el warmup puede gastar. Nueve destrabaron a los dos juegos con pantalla
#: de titulo que la sonda midio de punta a punta; mas alla de eso, si el juego sigue sin responder
#: a las flechas, el diagnostico es "flechas inertes" y lo maneja IDENTIFICAR, no mas clicks.
CLICS_DE_WARMUP: Final[int] = 9

#: Rondas de tanteo de flechas dentro del warmup (la inicial mas las que re-arma un click
#: efectivo). Acota el ciclo click->tantear en juegos donde el click siempre cambia algo pero las
#: flechas siguen muertas: sin el tope, el warmup se comeria el episodio entero.
RONDAS_DE_TANTEO: Final[int] = 3

#: Intentos INCONCLUSOS ESPACIADOS por flecha antes de declararla `sinEvidencia`. 3 sale de la
#: medicion: 6 de los 17 juegos con flechas no producen una sola traslacion en 80 pulsaciones, asi
#: que insistir mas alla de esto es gastar presupuesto en un mapeo que no existe.
INTENTOS_POR_ACCION: Final[int] = 3

#: Pasos de juego entre dos intentos de la misma flecha. Un `inconcluso` puede ser una pared:
#: reintentar en el acto vuelve a medir la MISMA pared. Se difiere para probar desde otra posicion
#: del tablero, que es lo que el tercer resultado pide hacer.
PASOS_ANTES_DE_REINTENTAR: Final[int] = 8

ACCION_DE_CLICK: Final[str] = "ACTION6"


def motivo_de_apertura(accion: str, fase: str, creencia: CreenciaDeDirecciones) -> str:
    """BL.21590 -- razon legible de una accion sugerida por el libro (vivia en policy.py; es
    prosa del libro y BL.21593 la muda aca para dejarle sitio a la percepcion de pared)."""
    if accion == ACCION_DE_CLICK:
        return (
            "libro de aperturas (warmup): las flechas no movieron el tablero todavia -- se "
            "clickea antes de medir direcciones, 5 de 25 juegos publicos arrancan en un menu"
        )
    if fase == FASE_WARMUP:
        return (
            f"libro de aperturas (warmup): tanteo de {accion} para saber si el tablero "
            "responde a las flechas"
        )
    direccion = creencia.direccion_de(accion)
    predicho = "?" if direccion is None else f"({direccion[0]},{direccion[1]})"
    return (
        f"libro de aperturas (identificar): {accion} deberia mover {predicho} segun el "
        f"prior de 25 juegos (confianza del conjunto "
        f"{creencia.clave_del_conjunto or 'vacio'}: "
        f"{creencia.confianza_del_conjunto():.2f}); la macro que sigue es la corrida "
        "monotona que lo confirma o lo remapea -- no moverse NO es refutacion"
    )


class LibroDeAperturas:
    """Maquina de fases del arranque de episodio. UNA instancia por partida, casada con la
    `CreenciaDeDirecciones` del mismo episodio.

    Contrato con la politica: `sugerir()` devuelve la accion que el libro quiere que la proxima
    macro pruebe (o None: exploracion libre), y `registrar()` recibe el resultado de CADA paso
    observado -- lo haya sugerido el libro o no, porque la evidencia vale igual venga de donde
    venga. Los intentos de identificacion solo cuentan ESPACIADOS (paso >= proximo permitido):
    tres pulsaciones contra la misma pared en tres pasos seguidos son UNA medicion, no tres."""

    def __init__(
        self,
        creencia: CreenciaDeDirecciones,
        clics_de_warmup: int = CLICS_DE_WARMUP,
        rondas_de_tanteo: int = RONDAS_DE_TANTEO,
        intentos_por_accion: int = INTENTOS_POR_ACCION,
        espera_entre_intentos: int = PASOS_ANTES_DE_REINTENTAR,
        banderas: Banderas | None = None,
    ) -> None:
        self._creencia = creencia
        self._clics_max = clics_de_warmup
        self._rondas_max = rondas_de_tanteo
        self._intentos_max = intentos_por_accion
        self._espera = espera_entre_intentos
        self._fase = FASE_WARMUP
        self._tanteadas: set[str] = set()
        self._rondas = 1
        self._clics = 0
        self._hubo_click_efectivo = False
        # BL.21702 -- ver `_registrar_warmup`: con la palanca encendida el re-tanteo de flechas se
        # DIFIERE hasta agotar el presupuesto de clicks, en vez de dispararse con cada click que
        # mueva un pixel (la pantalla de titulo anima, asi que eso era siempre).
        self._clicks_seguidos = bandera_activa(WARMUP_DE_CLICKS_SEGUIDOS, banderas)
        self._retanteo_pendiente = False
        self._intentos: dict[str, int] = {}
        self._proximo_paso: dict[str, int] = {}
        #: Paso en el que la fase llego a EXPLOTAR -- la metrica "acciones hasta mapeo resuelto".
        self.paso_de_resolucion: int | None = None
        #: Decisiones cuyo orden eligio el libro (tanteos, clicks de warmup, primeras macros).
        self.pasos_guiados = 0

    @property
    def fase(self) -> str:
        return self._fase

    @property
    def clics_de_warmup_gastados(self) -> int:
        return self._clics

    def anotar_paso_guiado(self) -> None:
        self.pasos_guiados += 1

    # ── sugerencia ─────────────────────────────────────────────────────────────────────────────

    def sugerir(self, disponibles: Iterable[str], paso: int) -> str | None:
        """Accion que el libro quiere que la proxima macro pruebe, o None (exploracion libre)."""
        if self._fase == FASE_EXPLOTAR:
            return None
        presentes = set(disponibles)
        sembradas = self._creencia.acciones_sembradas()
        if not sembradas:
            self._pasar_a_explotar(paso)
            return None
        if self._fase == FASE_WARMUP:
            sugerida = self._sugerir_warmup(presentes, sembradas)
            if self._fase == FASE_WARMUP:
                return sugerida
        return self._sugerir_identificar(presentes, sembradas, paso)

    def _sugerir_warmup(self, presentes: set[str], sembradas: list[str]) -> str | None:
        # BL.21702 -- re-tanteo DIFERIDO: se aplica recien cuando el presupuesto de clicks se
        # agoto. Cubre tambien el caso en que el ULTIMO click no cambio nada (ahi `registrar` no
        # llega a aplicarlo) -- sin esta linea, un re-tanteo legitimamente ganado se perderia.
        if self._retanteo_pendiente and self._clics >= self._clics_max:
            self._aplicar_retanteo()
        pendientes = [
            a
            for a in sembradas
            if a in presentes and a not in self._tanteadas and not self._creencia.resuelta(a)
        ]
        if pendientes:
            return pendientes[0]
        if ACCION_DE_CLICK in presentes and self._clics < self._clics_max:
            return ACCION_DE_CLICK
        # Sin click disponible (o presupuesto agotado) y ninguna flecha respondio: a identificar,
        # cuyos reintentos espaciados y su `sinEvidencia` son el camino de salida.
        self._pasar_a_identificar()
        return None

    def _sugerir_identificar(
        self, presentes: set[str], sembradas: list[str], paso: int
    ) -> str | None:
        sin_resolver = False
        for accion in sembradas:
            if self._creencia.resuelta(accion):
                continue
            if self._intentos.get(accion, 0) >= self._intentos_max:
                self._creencia.declarar_sin_evidencia(accion)
                continue
            sin_resolver = True
            if accion not in presentes or paso < self._proximo_paso.get(accion, 0):
                continue
            return accion
        if not sin_resolver and all(self._creencia.resuelta(a) for a in sembradas):
            self._pasar_a_explotar(paso)
        return None

    # ── registro ───────────────────────────────────────────────────────────────────────────────

    def registrar(self, accion: str, resultado: str, hubo_cambio: bool, paso: int) -> None:
        """Contabiliza el resultado del paso ANTERIOR (cualquier accion, la haya sugerido el libro
        o no) y mueve la maquina de fases."""
        if self._fase == FASE_EXPLOTAR:
            return
        sembradas = self._creencia.acciones_sembradas()
        if self._fase == FASE_WARMUP:
            self._registrar_warmup(accion, resultado, hubo_cambio, sembradas)
        if self._fase == FASE_IDENTIFICAR:
            self._registrar_identificacion(accion, resultado, paso, sembradas)
            if sembradas and all(self._creencia.resuelta(a) for a in sembradas):
                self._pasar_a_explotar(paso)

    def _registrar_warmup(
        self, accion: str, resultado: str, hubo_cambio: bool, sembradas: list[str]
    ) -> None:
        if accion in sembradas:
            if resultado != RESULTADO_INCONCLUSO:
                # El tablero respondio a una flecha: el juego ya no es (o nunca fue) el menu.
                self._pasar_a_identificar()
                return
            self._tanteadas.add(accion)
            self._intentos[accion] = self._intentos.get(accion, 0) + 1
            return
        if accion == ACCION_DE_CLICK:
            self._clics += 1
            if not hubo_cambio:
                return
            if self._clicks_seguidos or self._rondas < self._rondas_max:
                self._hubo_click_efectivo = True
            # BL.21702 -- EL DEFECTO QUE ESTA RAMA TENIA, medido en dc22 (entorno real, 151
            # acciones): el re-tanteo se disparaba con cualquier click que cambiara el tablero, y
            # la PANTALLA DE TITULO ANIMA, asi que `hubo_cambio` era SIEMPRE True. Entre click y
            # click el libro volvia a tantear las cuatro flechas -- y cada tanteo abre una macro de
            # hasta 8 pasos -- de modo que `CLICS_DE_WARMUP=9` no se gastaba nunca: solo 8 ACTION6
            # en 151 acciones, cuando la medicion de BL.21590 fijo que hacian falta 9 SEGUIDOS para
            # salir del menu. No era un problema de exploracion: era de SECUENCIA DE APERTURA.
            #
            # Con la palanca, mientras queden clicks de warmup el re-tanteo queda PENDIENTE y los
            # clicks salen seguidos; al agotar el presupuesto se aplica el re-tanteo diferido y las
            # flechas se vuelven a medir UNA vez, ya del otro lado del menu.
            if self._clicks_seguidos:
                if self._clics < self._clics_max:
                    self._retanteo_pendiente = True
                    return
                self._aplicar_retanteo()
                return
            # Camino previo a BL.21702, INTACTO para que la palanca apagada mida exactamente la
            # linea base: `_hubo_click_efectivo` solo se marcaba cuando ademas quedaban rondas.
            if self._rondas < self._rondas_max:
                self._aplicar_retanteo()

    def _aplicar_retanteo(self) -> None:
        """Re-tantea las flechas: lo medido ANTES describia el menu, no el juego. Acotado por
        `RONDAS_DE_TANTEO` para que el ciclo click->tantear no se coma el episodio."""
        self._retanteo_pendiente = False
        if self._rondas >= self._rondas_max:
            return
        self._rondas += 1
        self._tanteadas.clear()
        self._intentos.clear()

    def _registrar_identificacion(
        self, accion: str, resultado: str, paso: int, sembradas: list[str]
    ) -> None:
        if accion not in sembradas or self._creencia.resuelta(accion):
            return
        if resultado != RESULTADO_INCONCLUSO:
            return
        if paso < self._proximo_paso.get(accion, 0):
            return  # pulsaciones contra la misma pared en pasos seguidos: UNA medicion, no varias
        self._intentos[accion] = self._intentos.get(accion, 0) + 1
        self._proximo_paso[accion] = paso + self._espera
        if self._intentos[accion] >= self._intentos_max:
            self._creencia.declarar_sin_evidencia(accion)

    # ── transiciones ───────────────────────────────────────────────────────────────────────────

    def _pasar_a_identificar(self) -> None:
        self._fase = FASE_IDENTIFICAR
        if self._hubo_click_efectivo:
            # Los inconclusos previos al click efectivo midieron el menu: la identificacion
            # arranca con el contador limpio.
            self._intentos = {}
            self._proximo_paso = {}

    def _pasar_a_explotar(self, paso: int) -> None:
        self._fase = FASE_EXPLOTAR
        if self.paso_de_resolucion is None:
            self.paso_de_resolucion = paso

    def resumen(self) -> str:
        """Linea legible para el `reasoning` persistido."""
        return (
            f"fase={self._fase} clicsWarmup={self._clics} pasosGuiados={self.pasos_guiados}"
            + (
                f" mapeoResueltoEnPaso={self.paso_de_resolucion}"
                if self.paso_de_resolucion is not None
                else ""
            )
        )


# ============================== arc_agent/estado_congelado.py ==============================
"""[arc-agi3-kaggle-agent/estado_congelado] BL.21702 -- DETECTOR DE ESTADO CONGELADO y disparador
del unico RESET VOLUNTARIO que la medicion justifica.

EL RESET VOLUNTARIO ESTA REFUTADO COMO PALANCA GENERAL, y esa es la parte importante de este
modulo. Medido en los entornos reales (151 acciones por juego, semilla bl21702a), el RESET
INVOLUNTARIO -- el que dispara el contrato ante GAME_OVER -- ya ocurre solo y no destraba nada:
sp80 6 por partida, su15 4, tn36 2, tu93 2, lf52 2, dc22 1, sb26 1, y los siete siguen en CERO
niveles. sp80 en particular recibe seis reinicios gratis por partida. Donde el juego ya se reinicia
solo, un RESET mas no puede ser la diferencia.

DONDE SI TIENE SENTIDO, y solo ahi: cuando el tablero esta CONGELADO y no hay game-over que
rescate. Eso se midio en exactamente dos de los siete -- lf52 (47 revisitas con gap=1, o sea frame
IDENTICO entre pasos consecutivos, y solo 2 game-over en 151 pasos) y dc22 (54 con gap=1). En los
otros cinco las revisitas son ciclos LARGOS de periodo FIJO (tn36 62, tu93 51, sb26 ~73, su15 ~35):
animaciones del juego, no congelamiento, y ahi el frame SI cambia paso a paso.

POR ESO EL DISPARADOR PIDE EVIDENCIA Y NO CORAZONADA. El RESET cuesta una accion y puede perder
progreso real del nivel, asi que las cinco condiciones se exigen JUNTAS:

  1. VENTANA LLENA de `VENTANA_DE_CONGELAMIENTO` pasos, con al menos `PASOS_SIN_CAMBIO_PARA_RESET`
     de ellos SIN cambio enmascarado. Ventana y no racha estricta: en dato real el congelamiento
     viene salpicado por algun frame que si se mueve, y una racha consecutiva no lo veria nunca.
  2. Se probaron al menos `ACCIONES_DISTINTAS_MINIMAS` acciones distintas en esa ventana (o todas
     las que el juego ofrece, si ofrece menos). Sin esto, un unico boton inerte repetido bastaria
     para reiniciar, y eso es "no supe que probar", no "el juego esta trabado".
  3. Si el juego ofrece ACTION6, se clickearon al menos `COORDENADAS_DISTINTAS_MINIMAS` celdas
     DISTINTAS en la ventana. En un juego de click la pregunta es DONDE, y reiniciar por no haber
     encontrado la celda seria reiniciar por no haber explorado.
  4. Quedan RESETs del presupuesto (`RESETS_VOLUNTARIOS_MAX`) y paso la espera desde el ultimo
     (`PASOS_ENTRE_RESETS_VOLUNTARIOS`). Un reset que no destraba no debe volverse un tic.
  5. No hubo progreso de nivel en los ultimos `PASOS_DE_GRACIA_TRAS_PROGRESO` pasos. Si el agente
     acaba de subir de nivel, lo que hay delante es un nivel nuevo, no un bucle -- y ahi el reset
     tira justo lo que se acaba de ganar. Esta es la condicion que protege el caso caro.

Apagable entero con la palanca `resetPorCongelamiento` (ver banderas.py): con ella apagada
`debe_resetear` devuelve False siempre y el agente se comporta exactamente como antes de BL.21702.
"""

from typing import Final, Iterable


# FUENTE UNICA del nombre del boton de click: lo define `opening_book.py` y aca se reusa en vez
# de re-declararlo (dos definiciones del mismo literal serian dos verdades que pueden divergir).


#: Pasos de la ventana deslizante sobre la que se juzga el congelamiento.
VENTANA_DE_CONGELAMIENTO: Final[int] = 24

#: Pasos SIN cambio enmascarado dentro de la ventana para considerar el tablero congelado. 18 de 24
#: = 75%: tolera la animacion intermitente que el dato real muestra sin aceptar un tablero que
#: responde tres de cada cuatro pasos.
PASOS_SIN_CAMBIO_PARA_RESET: Final[int] = 18

#: Acciones distintas que hay que haber probado en la ventana (o todas las disponibles si son
#: menos). Distingue "el juego esta trabado" de "todavia no probe nada".
ACCIONES_DISTINTAS_MINIMAS: Final[int] = 2

#: Coordenadas distintas que hay que haber clickeado en la ventana cuando el juego ofrece ACTION6.
#: En un juego de click la decision es DONDE: reiniciar antes de haber barrido nada seria confundir
#: falta de exploracion con bloqueo.
COORDENADAS_DISTINTAS_MINIMAS: Final[int] = 8

#: Tope de RESETs voluntarios por episodio. Bajo a proposito: cada uno cuesta una accion y puede
#: perder progreso, y la evidencia dice que reiniciar no es lo que destraba (ver el encabezado).
RESETS_VOLUNTARIOS_MAX: Final[int] = 3

#: Pasos minimos entre dos RESETs voluntarios: dos ventanas completas. Si el primero no destrabo,
#: hay que darle al agente el tiempo de medir de nuevo antes de volver a gastar la accion.
PASOS_ENTRE_RESETS_VOLUNTARIOS: Final[int] = 2 * VENTANA_DE_CONGELAMIENTO

#: Pasos de gracia tras una subida de nivel. Es la condicion que protege el progreso real: recien
#: superado un nivel, lo que hay delante es un tablero nuevo que todavia no se entiende.
PASOS_DE_GRACIA_TRAS_PROGRESO: Final[int] = 60



class DetectorDeCongelamiento:
    """Ventana deslizante de evidencia de congelamiento. UNA instancia por partida.

    Contrato con la politica: `observar()` una vez por decision, con lo que se sabe de la
    transicion ANTERIOR; `debe_resetear()` justo antes de elegir accion; `registrar_reset()` cuando
    la politica efectivamente emite el RESET voluntario."""

    __slots__ = (
        "_activo",
        "_ventana",
        "_sin_cambio",
        "_acciones",
        "_coordenadas",
        "_resets",
        "_paso_del_ultimo_reset",
        "_paso_del_ultimo_progreso",
    )

    def __init__(self, banderas: Banderas | None = None) -> None:
        self._activo = bandera_activa(RESET_POR_CONGELAMIENTO, banderas)
        # Ventana como lista de tuplas (hubo_cambio, accion, coordenada). Acotada a
        # VENTANA_DE_CONGELAMIENTO elementos: los conteos se recalculan sobre ella, que es barato
        # con 24 entradas y evita el error clasico de contadores incrementales que se desincronizan
        # del contenido de la ventana.
        self._ventana: list[tuple[bool, str | None, tuple[int, int] | None]] = []
        self._sin_cambio = 0
        self._acciones: set[str] = set()
        self._coordenadas: set[tuple[int, int]] = set()
        self._resets = 0
        self._paso_del_ultimo_reset: int | None = None
        self._paso_del_ultimo_progreso: int | None = None

    @property
    def activo(self) -> bool:
        """Si la palanca `resetPorCongelamiento` esta encendida en esta partida."""
        return self._activo

    @property
    def resets_voluntarios(self) -> int:
        """RESETs voluntarios emitidos en el episodio -- la metrica de la palanca."""
        return self._resets

    @property
    def pasos_sin_cambio_en_ventana(self) -> int:
        return self._sin_cambio

    @property
    def coordenadas_en_ventana(self) -> int:
        return len(self._coordenadas)

    def observar(
        self,
        hubo_cambio: bool,
        accion: str | None,
        coordenada: tuple[int, int] | None,
        subio_de_nivel: bool,
        paso: int,
    ) -> None:
        """Registra la transicion ANTERIOR. `accion`/`coordenada` son las que la produjeron
        (None en el primer paso del episodio o tras un RESET, donde no hay transicion atribuible).

        Una subida de nivel arma el periodo de gracia: es la unica evidencia dura de que el agente
        NO esta en un bucle, y es tambien lo que un RESET podria tirar a la basura."""
        if subio_de_nivel:
            self._paso_del_ultimo_progreso = paso
        self._ventana.append((hubo_cambio, accion, coordenada))
        if len(self._ventana) > VENTANA_DE_CONGELAMIENTO:
            self._ventana.pop(0)
        self._recontar()

    def _recontar(self) -> None:
        self._sin_cambio = sum(1 for cambio, _, _ in self._ventana if not cambio)
        self._acciones = {a for _, a, _ in self._ventana if a is not None}
        self._coordenadas = {c for _, _, c in self._ventana if c is not None}

    def debe_resetear(self, paso: int, acciones_disponibles: Iterable[str]) -> bool:
        """Las cinco condiciones del encabezado, evaluadas juntas. Cualquiera que falte devuelve
        False: el RESET voluntario es la excepcion, nunca el reflejo."""
        if not self._activo:
            return False
        if len(self._ventana) < VENTANA_DE_CONGELAMIENTO:
            return False
        if self._sin_cambio < PASOS_SIN_CAMBIO_PARA_RESET:
            return False
        disponibles = tuple(acciones_disponibles)
        if not disponibles:
            return False
        if len(self._acciones) < min(ACCIONES_DISTINTAS_MINIMAS, len(disponibles)):
            return False
        if ACCION_DE_CLICK in disponibles and len(self._coordenadas) < COORDENADAS_DISTINTAS_MINIMAS:
            return False
        if self._resets >= RESETS_VOLUNTARIOS_MAX:
            return False
        if (
            self._paso_del_ultimo_reset is not None
            and paso - self._paso_del_ultimo_reset < PASOS_ENTRE_RESETS_VOLUNTARIOS
        ):
            return False
        if (
            self._paso_del_ultimo_progreso is not None
            and paso - self._paso_del_ultimo_progreso < PASOS_DE_GRACIA_TRAS_PROGRESO
        ):
            return False
        return True

    def decidir_reset(self, paso: int, acciones_disponibles: Iterable[str]) -> str | None:
        """Punto de entrada de la POLITICA: devuelve el motivo legible del RESET voluntario y lo
        contabiliza, o None si no corresponde reiniciar.

        Junta la decision y su registro a proposito. Separarlos deja abierta la unica forma de
        romper este detector desde afuera -- preguntar y no registrar, o registrar sin preguntar --
        y el segundo caso es el que convierte el reset en un tic: la ventana no se vaciaria y el
        siguiente paso volveria a dispararlo con la evidencia del tablero ANTERIOR al reinicio."""
        if not self.debe_resetear(paso, acciones_disponibles):
            return None
        self.registrar_reset(paso)
        return (
            "RESET voluntario: el tablero esta congelado y no hay game-over que rescate -- "
            f"{self.resumen()}"
        )

    def registrar_reset(self, paso: int) -> None:
        """La politica emitio el RESET voluntario. La ventana se VACIA: lo que viene despues es
        otro episodio de tablero y juzgarlo con evidencia previa al reinicio dispararia el segundo
        reset en el paso siguiente."""
        self._resets += 1
        self._paso_del_ultimo_reset = paso
        self._ventana.clear()
        self._recontar()

    def resumen(self) -> str:
        """Linea legible para el `reasoning` persistido."""
        return (
            f"congelamiento={self._sin_cambio}/{len(self._ventana)} "
            f"acciones={len(self._acciones)} coordenadas={len(self._coordenadas)} "
            f"resetsVoluntarios={self._resets}"
        )


# ============================== arc_agent/policy.py ==============================
"""[arc-agi3-kaggle-agent/policy] BL.20783 -- politica de decision 100% local: SIN red, SIN
llamadas a APIs de LLM en inferencia (restriccion dura del notebook Kaggle). Exploracion con
memoria de estados visitados (evita reintentar acciones que no cambiaron el frame desde el MISMO
estado -- deteccion de loops/dead-ends, "menos visitado primero" al estilo bandit) + deteccion de
bordes de color para elegir el punto de click de ACTION6 (heuristica de vision simple: una celda
en el borde de una region de color distinto es mas "interesante" que una celda interior uniforme).
Determinista dado un `rng` semillado -- mismo principio de reproducibilidad que baselineAgent.ts
en BL.20775, con una politica mas informada que la eleccion puramente uniforme del MVP."""

from typing import Callable


# BL.21702 -- las cuatro palancas de exploracion y el RESET voluntario, cada una apagable de a una
# para poder medirla por separado. Ver banderas.py: el gate corre la MISMA build con una palanca
# menos y le atribuye el delta a esa y a ninguna otra.


# Import a UN solo nivel (`.world_model`, no `.world_model.transition_memory`): el builder del
# notebook desmonta los imports relativos con el regex `^from \.\w* import .+$`, que no cubre un
# segundo punto -- con la forma anidada el notebook de submission queda con un ImportError.

# BL.21560 -- `rank_candidates` y los dos epsilon se mudaron a exploration_memory.py (son memoria de
# exploracion, no politica de decision) para dejarle sitio a la eleccion de coordenada. BL.21590
# mudo tambien la firma de estado, la entrada de memoria por estado y sus dos umbrales, por el mismo
# motivo y para dejarle sitio a la creencia de direcciones. Se re-exportan: superficie publica de
# este modulo desde BL.20783 y los tests los importan de aca.





# BL.21767 -- la muerte como HECHO del modelo de mundo: donde se anota la transicion a GAME_OVER
# (firma previa, accion, click, macro en curso) y el descuento agotable que la consume.


# BL.21590 -- prior de direcciones sembrado por conjunto de acciones disponibles y validado en
# partida DENTRO de las macros, con tres resultados por boton; ACTION5/ACTION7 entran como
# incognita uniforme sobre firmas de mecanica. Ver direction_beliefs.py y opening_book.py.


# BL.21593 -- percepcion de pared: el termino observable de la verosimilitud del fallo. El avatar
# es el ultimo objeto trasladado y el piso, el color que deja al moverse; con ambos, un fallo de
# flecha se descompone en P(pared|grilla) + P(mapeo equivocado) + P(desconocido).


# BL.22236 -- capas de animacion intermedias de `frame.frame` (evidencia adicional de transicion,
# ver `_feed_capas_intermedias`).

# BL.21704 -- almacen de relaciones causales A DISTANCIA (boton que abre puerta) y su confirmacion
# INTERVENCIONAL. Es un almacen APARTE del vocabulario de `mechanics_posterior.MECANICAS`, que es el
# mapeo boton->direccion: una relacion no local no es una direccion y no hay lugar semantico donde
# meterla (medido en la etapa 1 de BL.21704).




class ExplorationPolicy:
    """Politica offline con estado (una instancia por partida). `decide()` es el unico punto de
    entrada: internamente actualiza la memoria de exploracion comparando el estado actual contra
    el de la decision anterior (sin depender de la forma exacta de `frames`, solo del estado
    interno propio -- mas robusto que asumir un indice fijo en el historial)."""

    def __init__(self, rng: Callable[[], float], banderas: Banderas | None = None) -> None:
        self._rng = rng
        # BL.21702 -- palancas de esta partida (ver banderas.py). Se guardan para que un reporte de
        # corrida pueda declarar con cual configuracion se midio.
        self._banderas = banderas
        self._memory: dict[int, EntradaDeExploracion] = {}
        self._prev_signature: int | None = None
        self._prev_action: GameAction | None = None
        # BL.21501 -- modelo de mundo (sintesis DSL) alimentado con cada transicion observada.
        # Hasta ahora world_model/ viajaba al notebook de submission (2.052 lineas, ~79% del
        # codigo) sin que NINGUN modulo de inferencia lo importara: era codigo muerto en la
        # partida real, mientras el runner TS si usaba IntelligentPolicy sobre el mismo motor.
        self._world_model = TransitionMemory(
            mascara_de_accion_unica=bandera_activa(MASCARA_DE_ACCION_UNICA, banderas)
        )
        self._prev_grid: tuple[tuple[int, ...], ...] | None = None
        # BL.21557 -- senal densa. `_max_levels_completed` es el MAXIMO observado, no el ultimo: el
        # frame terminal de un GAME_OVER puede traer el contador ya en cero y quedarse con ese valor
        # tiraria justo el credito parcial que la metrica de seleccion mide.
        self._max_levels_completed = 0
        self._win_levels = 0
        self._prev_levels_completed = 0
        # BL.21558 -- version de la mascara con la que se calculo `_prev_signature`. Dos firmas de
        # versiones distintas NO son comparables (son hashes de dos definiciones de "estado"), asi
        # que la comparacion de `_record_outcome` se saltea en el paso en que la mascara cambia.
        self._prev_mask_version = 0
        # BL.21559 -- compromiso con la accion elegida y novedad por conteo sobre la firma
        # ENMASCARADA. Los dos viven en el objeto y no en el paso: `decide()` se llama una vez por
        # accion, y sin estado entre llamadas no hay macro posible -- ese era, literalmente, el
        # defecto. Ver exploration_memory.py.
        self._macro = MacroCommitment(banderas)
        self._novedad = StateNoveltyTracker()
        # BL.21560 -- DONDE clickear. `_prev_click` es lo que permite atribuirle el resultado a un
        # ACTION6: sin la coordenada, el par (accion, resultado) no dice nada de un click, que es
        # justo el motivo por el que `_record_outcome` lo tenia exento. Ver click_targeting.py.
        self._clicks = ClickMemory(banderas=banderas)
        self._prev_click: tuple[int, int] | None = None
        self._region_cambiada: tuple[int, int, int, int] | None = None
        # BL.21590 -- creencia de direcciones sembrada por el prior (por CONJUNTO de acciones
        # disponibles, jamas por game_id), el libro de aperturas que dirige la primera macro de
        # cada flecha (y clickea primero cuando el juego arranca en un menu), y la incognita de
        # mecanica de ACTION5/ACTION7. `_pasos` es el contador de decisiones del episodio: el
        # libro lo usa para DIFERIR un reintento en vez de volver a medir contra la misma pared.
        self._direcciones = CreenciaDeDirecciones()
        self._libro = LibroDeAperturas(self._direcciones, banderas=banderas)
        self._incognitas = IncognitasDeMecanica()
        self._pasos = 0
        # BL.21593 -- rastreador del avatar (posicion + color del piso) para el contexto de pared.
        self._avatar = RastreadorDeAvatar()
        # BL.21702 -- evidencia de tablero CONGELADO y disparador del RESET voluntario, que esta
        # REFUTADO como palanca general (ver estado_congelado.py).
        self._congelamiento = DetectorDeCongelamiento(banderas)
        self._resets_voluntarios = 0
        # BL.21704 -- causa a distancia. Observa TODA transicion, mina cada 40 pasos registrados y
        # gasta hasta `MAX_INTERVENCIONES_POR_PARTIDA` acciones en CONFIRMAR activamente: repetir la
        # accion sospechosa y exigir 3 de 4. Nunca decide sola -- alimenta sub-metas y una
        # preferencia de accion, y toda su superficie hacia `decide` esta envuelta en fail-open.
        self._relaciones = AlmacenDeRelaciones()
        # BL.21704 -- estado de EXPLOTACION de las sub-metas confirmadas. Ver `_explotar_submeta`:
        # sin esto el almacen gastaba acciones en confirmar relaciones y despues TIRABA el
        # resultado, porque nadie llamaba a `submetas()`.
        self._pasos_sin_cambio = 0
        self._explotaciones_de_submeta = 0
        self._submeta_vigente: SubMeta | None = None
        # BL.21767 -- la muerte como HECHO. El registro corre SIEMPRE (pura observacion, sin rng);
        # el consumo -- relegar en el ranking la accion que mato desde esta firma -- lo enciende la
        # palanca, porque es lo que el gate tiene que aprobar por separado (BL.21702).
        self._muertes = MemoriaDeMuertes()
        self._castigo_de_muerte_activo = bandera_activa(MEMORIA_DE_MUERTES, banderas)

    @property
    def creencia_de_direcciones(self) -> CreenciaDeDirecciones:
        """BL.21590 -- mapeo accion -> direccion vigente y su estado (sembrada / confirmada /
        remapeada / sinEvidencia). Observabilidad: es lo que los tests de efecto miden."""
        return self._direcciones

    @property
    def libro_de_aperturas(self) -> LibroDeAperturas:
        """BL.21590 -- fase vigente (warmup/identificar/explotar), clicks de warmup gastados y el
        paso en que el mapeo quedo resuelto. METRICA del BL: cero acciones dedicadas solo a
        validar -- el libro elige el orden de la exploracion, no agrega pasos."""
        return self._libro

    @property
    def incognitas_de_mecanica(self) -> IncognitasDeMecanica:
        """BL.21590 -- posterior por firma de mecanica de ACTION5/ACTION7 (arranca uniforme)."""
        return self._incognitas

    @property
    def memoria_de_clicks(self) -> ClickMemory:
        """BL.21702 -- cobertura de coordenadas del episodio (metrica de la palanca de clicks)."""
        return self._clicks

    @property
    def detector_de_congelamiento(self) -> DetectorDeCongelamiento:
        """BL.21702 -- evidencia de tablero congelado y RESETs voluntarios emitidos."""
        return self._congelamiento

    @property
    def resets_voluntarios(self) -> int:
        """BL.21702 -- RESETs que decidio la POLITICA, nunca los que dispara el contrato ante
        GAME_OVER (esos ya se median solos y no destraban nada)."""
        return self._resets_voluntarios

    @property
    def cortes_de_macro_por_estado_repetido(self) -> int:
        """BL.21702 -- veces que la macro se corto por llegar a un estado ya visitado."""
        return self._macro.cortes_por_estado_repetido

    @property
    def memoria_de_muertes(self) -> MemoriaDeMuertes:
        """BL.21767 -- los hechos de muerte registrados (firma previa, accion, click, macro) y la
        evidencia por par. Observabilidad: es lo que un reporte o un test de efecto lee."""
        return self._muertes

    @property
    def relaciones_no_locales(self) -> AlmacenDeRelaciones:
        """BL.21704 -- almacen de causa a distancia. Observabilidad: `resumen()` trae el conteo por
        etapa del pipeline (regiones, pares no locales, tras BH, tras nulo empirico, tras pureza,
        retenidas), que es la unica forma honesta de reportar un CERO -- dice donde murio la senal."""
        return self._relaciones

    @property
    def max_levels_completed(self) -> int:
        """BL.21557 -- nivel maximo alcanzado en la partida. METRICA DE SELECCION OFFLINE: ordena
        dos versiones del agente aunque ninguna gane (espejo de `levelProgress.ts` en el runner TS)."""
        return self._max_levels_completed

    @property
    def win_levels(self) -> int:
        """Niveles totales que exige el juego; 0 si el entorno no lo informo."""
        return self._win_levels

    def decide(self, frame: FrameData) -> ActionDecision:
        current_grid = frame.frame[-1] if frame.frame else None
        mecanica = self._feed_world_model(current_grid)  # BL.21501: aprende ANTES de decidir
        # BL.22236 -- ademas de la transicion macro (arriba), expone las capas de animacion
        # intermedias de ESTE frame como evidencia adicional. Nunca toca `current_grid` ni la
        # firma de estado: solo alimenta la memoria de mecanica objeto-centrica.
        self._feed_capas_intermedias(frame)
        # BL.21590 -- la creencia de direcciones se actualiza con la MISMA mecanica que ya calculo el
        # modelo de mundo (nunca un segundo detector) y con TRES resultados posibles, no dos.
        resultado_direcciones = self._observar_direcciones(mecanica)
        self._avatar.observar(mecanica, current_grid)  # BL.21593: tras evaluar pared, nunca antes
        self._alimentar_relaciones(current_grid, mecanica)  # BL.21704: causa a distancia
        # BL.21557: la recompensa extrinseca se acredita antes de rankear. BL.21702: el aviso de
        # progreso arma el periodo de gracia del RESET voluntario -- subir de nivel es la evidencia
        # dura de que el agente NO esta en un bucle, y es justo lo que un reset tiraria.
        # OJO al integrar BL.21704 (rescate 2026-08-19): su version descartaba el retorno de
        # `_observe_levels`, que en dev pasó a alimentar ese periodo de gracia. Quedarse con
        # cualquiera de los dos lados rompia el otro, asi que se conservan AMBOS: la alimentacion de
        # relaciones va primero (orden de BL.21704) y `subio_de_nivel` se sigue capturando.
        subio_de_nivel = self._observe_levels(frame)
        # BL.21558 -- la mascara sale del modelo de mundo, ya actualizado con la transicion
        # anterior: firmar y comparar usan EXACTAMENTE las mismas celdas que la sintesis considera
        # informativas. Por eso la firma se calcula ACA y no al entrar a `decide`.
        mask, mask_version = self._volatility_mask_segura()
        signature = compute_signature(frame, mask)
        self._record_outcome(signature, mask_version)
        # BL.21767 -- la transicion anterior entra a la memoria de muertes ANTES de que la rama de
        # reset corte la continuidad (macro, click): es el unico momento en que el contexto del
        # hecho -- desde que firma, con que accion, con que click, con macro en curso -- existe.
        if self._prev_signature is not None and self._prev_action is not None:
            self._muertes.registrar_transicion(
                self._prev_signature,
                self._prev_action.value,
                frame.state == GameState.GAME_OVER,
                self._prev_click if self._prev_action is GameAction.ACTION6 else None,
                # "Con macro en curso" = la accion que mato era una REPETICION comprometida (paso
                # 2+), no el primer paso: `iniciar` corre en casi toda decision y con el solo
                # `accion_vigente` el campo diria True siempre y no discriminaria nada.
                self._macro.accion_vigente is not None and self._macro.pasos_emitidos > 1,
                self._pasos,
            )
        # BL.21559 -- la transicion anterior leida IGNORANDO las celdas volatiles: es a la vez el
        # criterio de corte de la macro y la definicion de "el tablero se movio".
        hubo_cambio = self._hubo_cambio_enmascarado(current_grid, mask)
        # BL.21704 -- racha de pasos sin que el tablero se mueva. Es el disparador de la
        # EXPLOTACION de una sub-meta confirmada: una relacion causal a distancia probada es
        # justamente una forma conocida de cambiar el mundo cuando la exploracion local se estanco.
        self._pasos_sin_cambio = 0 if hubo_cambio else self._pasos_sin_cambio + 1
        # BL.21590 -- el libro de aperturas recibe el resultado de CADA paso observado (la evidencia
        # vale igual la haya sugerido el o no) y mueve su maquina de fases con el.
        if resultado_direcciones is not None and self._prev_action is not None:
            self._libro.registrar(
                self._prev_action.value, resultado_direcciones, hubo_cambio, self._pasos
            )
        # BL.21560 -- se le atribuye el resultado al click anterior ANTES de pisar `_prev_signature`:
        # la clave de la memoria es la firma del estado DESDE EL QUE se clickeo, no la del que quedo.
        self._atribuir_click(hubo_cambio)
        self._region_cambiada = region_que_cambio(
            None if self._prev_grid is None else [list(f) for f in self._prev_grid],
            None if current_grid is None else [list(f) for f in current_grid],
        )
        self._registrar_novedad(signature, mask_version)
        # BL.21702 -- cuantos botones OFRECE el juego (no cuantos se observaron): es lo que habilita
        # el modo de accion unica de la mascara. Idempotente, por eso se declara en cada paso.
        self._declarar_vocabulario(frame.available_actions)
        # Evidencia de congelamiento de la transicion ANTERIOR, antes de decidir nada.
        self._congelamiento.observar(
            hubo_cambio,
            None if self._prev_action is None else self._prev_action.value,
            self._prev_click,
            subio_de_nivel,
            self._pasos,
        )

        # BL.21702 -- RESET VOLUNTARIO. Solo con las cinco condiciones de estado_congelado.py
        # cumplidas a la vez (tablero congelado en la ventana, varias acciones probadas, cobertura
        # de coordenadas si el juego es de click, presupuesto y espera disponibles, y ningun
        # progreso de nivel reciente). Esta REFUTADO como palanca general -- el RESET involuntario
        # ya se dispara solo en los siete juegos atascados y no destraba nada -- asi que el
        # disparador exige evidencia. En NOT_STARTED no se consulta: ahi ya se resetea igual.
        # BL.21767 -- GAME_OVER llega CRUDO desde el adaptador (antes se disfrazaba de NOT_STARTED
        # y el evento mas informativo de la partida se procesaba como el arranque). Se responde
        # igual que siempre -- RESET y cortar la continuidad -- pero el hecho ya quedo anotado en
        # la memoria de muertes unas lineas mas arriba, con su contexto intacto.
        es_terminal = frame.state in (GameState.NOT_STARTED, GameState.GAME_OVER)
        motivo_de_reset = (
            None
            if es_terminal
            else self._congelamiento.decidir_reset(
                self._pasos, [f"ACTION{n}" for n in frame.available_actions]
            )
        )
        if es_terminal or not frame.available_actions or motivo_de_reset:
            # Un RESET rompe la continuidad de la trayectoria: la accion de la macro ya no puede
            # evaluarse contra el estado que la motivo, y el frame que viene ya no es consecuencia
            # del ultimo click.
            self._macro.cancelar()
            self._prev_click = None
            self._region_cambiada = None
            if motivo_de_reset is not None:
                self._resets_voluntarios += 1
            decision = ActionDecision(
                action=GameAction.RESET,
                reasoning=motivo_de_reset
                or "Estado NOT_STARTED/GAME_OVER o sin acciones -- se reinicia el juego.",
            )
        else:
            # BL.21590 -- la siembra ocurre con el primer frame jugable: `available_actions` es la
            # unica clave legitima del prior (existe igual en los juegos privados, a diferencia del
            # game_id). Ningun juego medido cambio su conjunto durante el episodio, y la siembra es
            # idempotente de todos modos.
            self._direcciones.sembrar(frame.available_actions)
            entry = self._memory.get(signature)
            visits = entry.visits if entry is not None else {}
            no_op_actions = entry.no_op_actions if entry is not None else set()
            # BL.21501 -- las dos fuentes de no-op se UNEN, no se reemplazan. La memoria de
            # exploracion (`entry`) es por FIRMA DE ESTADO y barata; el modelo de mundo generaliza
            # sobre el efecto de la accion en cualquier estado y aporta lo que la firma no ve.
            # Ambas exigen ya evidencia suficiente antes de excluir (BL.21518 y BL.21501), asi que
            # unirlas no reintroduce el lockout. ACTION6 nunca entra por la via de `entry`.
            no_op_actions = no_op_actions | self._world_model_no_ops(frame.available_actions)
            # BL.21557 -- acciones con credito de recompensa extrinseca vigente desde este estado.
            rewarded = set(entry.reward_credits) if entry is not None else set()
            # BL.21559 -- el turno de reexploracion de no-ops se sortea POR PASO (ver la constante):
            # con macro-acciones una decision cubre hasta ocho pasos y el presupuesto se dividia por
            # ocho. Cuando sale, la macro cede.
            turno = self._rng() < RECONSIDERATION_PER_STEP_EPSILON
            if turno:
                self._macro.cancelar()
            # BL.21702 -- `> 1` y no `> 0`: `_registrar_novedad` ya conto la visita de ESTE paso
            # unas lineas mas arriba, asi que la firma actual siempre tiene al menos una.
            estado_ya_visitado = self._novedad.visitas_de(signature) > 1
            # BL.21767 -- acciones que MATARON desde esta firma, con descuento vigente. Se calcula
            # UNA sola vez y la consultan las CUATRO vias que pueden elegir accion, no solo el
            # ranker: leerlo dos veces era ademas dos respuestas distintas en potencia.
            # Con la palanca apagada es el conjunto VACIO, que deja cada via identica a como era —
            # es lo que hace medible el delta de la palanca y nada mas que el (BL.21702).
            castigadas = (
                self._muertes.castigadas(signature, frame.available_actions)
                if self._castigo_de_muerte_activo
                else set()
            )
            # BL.21913 -- MEDIDO (2026-08-21): antes de este arreglo la palanca se calculaba y se
            # IGNORABA. En PasilloConPozo con la palanca encendida, 7 de 12 decisiones las tomaba el
            # LIBRO DE APERTURAS, que devolvia ACTION1 desde la firma del borde del pozo teniendo
            # `castigadas={ACTION1}` en la mano: 27 muertes con palanca y 27 sin ella, secuencia de
            # acciones IDENTICA. El corte de la macro (abajo) existia desde el primer dia; el libro,
            # la intervencion y la submeta no lo tenian, y son exactamente el mismo agujero — vias
            # que eligen ANTES del ranking y por eso nunca ven el castigo.
            # Ninguna de las tres se filtra ni se prohibe: se DESCARTA la sugerencia castigada y se
            # cae al ranker, que la relega al fondo y ademas gasta el descuento. Asi el descuento
            # sigue agotandose (nada de lockout) y el orden del rng no cambia.
            #
            # una macro cuya accion tiene castigo de muerte VIGENTE desde esta firma se corta ANTES
            # de continuar: el compromiso re-emite sin pasar por el ranking, asi que sin este corte
            # la palanca no podria evitar exactamente la muerte mas comun (la que ocurre en el paso
            # 2+ de una macro -- `con_macro` en los hechos registrados).
            if (
                self._macro.accion_vigente is not None
                and GameAction(self._macro.accion_vigente) in castigadas
            ):
                self._macro.cancelar()
            action = self._continuar_macro(
                frame.available_actions, hubo_cambio, estado_ya_visitado
            )
            macro = action is not None
            apertura = None
            intervencion = None
            if action is None:
                # BL.21590 -- el libro de aperturas elige la PROXIMA macro mientras el mapeo no
                # este resuelto: tanteo o click de warmup si el juego arranca en un menu, y la
                # primera macro de cada flecha en identificacion (la macro ES la corrida monotona
                # que confirma o remapea el prior). Nunca interrumpe una macro en curso y en
                # `explotar` devuelve None: cero acciones dedicadas solo a validar.
                apertura = self._libro.sugerir(
                    [f"ACTION{n}" for n in frame.available_actions], self._pasos
                )
                # BL.21913 -- ver arriba: el libro elige antes del ranking y no ve el castigo.
                if apertura is not None and GameAction(apertura) in castigadas:
                    apertura = None
            if apertura is not None:
                action = GameAction(apertura)
                self._macro.iniciar(action.value)
                self._libro.anotar_paso_guiado()
            elif action is None:
                # BL.21704 -- CONFIRMACION INTERVENCIONAL. Va despues del libro de aperturas (que
                # resuelve el mapeo boton->direccion, y ese orden esta medido) y antes del ranker de
                # novedad: una relacion candidata a causa a distancia solo se puede desconfundir
                # REPITIENDO la accion, y cada repeticion cuesta una accion del presupuesto. Es un
                # paso suelto y NO abre macro: el almacen juzga la transicion inmediata siguiente,
                # y una macro de hasta ocho pasos haria imposible atribuirle el efecto a esta.
                intervencion = self._sugerir_intervencion(frame.available_actions)
                # BL.21913 -- mismo agujero que el libro: confirmar una relacion NO justifica
                # repetir la accion que acaba de matar desde esta misma firma.
                if intervencion is not None and intervencion in castigadas:
                    intervencion = None
            submeta = None
            if intervencion is None and action is None:
                # BL.21704 -- EXPLOTACION de una relacion ya CONFIRMADA. Este es el consumidor de
                # `submetas()`: sin el, el agente gastaba acciones probando relaciones y despues
                # descartaba el veredicto, con lo cual el gate no media la hipotesis del BL sino
                # el costo de confirmarla.
                submeta = self._explotar_submeta(frame.available_actions)
                # BL.21913 -- mismo agujero: explotar una relacion confirmada tampoco puede
                # re-emitir la accion castigada sin pasar por el ranking.
                if submeta is not None and GameAction(submeta.accion) in castigadas:
                    submeta = None
            if intervencion is not None:
                action = intervencion
            elif submeta is not None:
                action = GameAction(submeta.accion)
            elif action is None:
                # BL.21767 -- las castigadas van al fondo del ranking (relegadas, jamas filtradas).
                # BL.21913: `castigadas` ya se calculo arriba, una sola vez para las cuatro vias.
                ranked = rank_candidates(
                    frame.available_actions,
                    visits,
                    no_op_actions,
                    self._rng,
                    rewarded,
                    self._clave_de_novedad(signature),
                    turno,
                    # BL.21560 -- prior de arranque: solo cuando todavia no se ejecuto ninguna
                    # accion en la partida. Ver `prioridad_por_priors`.
                    self._prev_action is None,
                    castigadas,
                )
                action = ranked[0]
                # El descuento se GASTA por aplicacion (cada accion efectivamente relegada en este
                # ranking; una premiada no se relega y no gasta), simetrico al credito de
                # recompensa: agotarse es lo que impide el lockout.
                for castigada in castigadas - rewarded:
                    self._muertes.aplicar_castigo(signature, castigada.value)
                self._macro.iniciar(action.value)
            self._consume_reward_credit(entry, action)

            if intervencion is not None:
                motivo = (
                    "confirmacion INTERVENCIONAL de una relacion causal a distancia: se repite la "
                    "accion sospechosa para ver si el cambio lejano vuelve (3 de 4 exigidas)"
                )
            elif submeta is not None:
                motivo = (
                    "SUB-META de una relacion causal a distancia ya CONFIRMADA "
                    f"(evidencia {submeta.evidencia:.2f}): el tablero lleva "
                    f"{self._pasos_sin_cambio} pasos sin moverse y esta accion es una forma "
                    "PROBADA de cambiar una region lejana"
                )
            elif apertura is not None:
                motivo = motivo_de_apertura(action.value, self._libro.fase, self._direcciones)
            elif macro:
                motivo = (
                    f"Macro-accion: sigue cambiando el tablero (paso {self._macro.pasos_emitidos}/"
                    f"{MACRO_MAX_STEPS} del compromiso), se repite hasta que deje de tener efecto"
                )
            else:
                motivo = "elegida por novedad: lleva al estado menos visitado desde esta firma"
            if action is GameAction.ACTION6:
                # BL.21704 -- si el click ES la intervencion, la coordenada no puede salir del
                # ranker de exploracion: un ACTION6 en otra celda no repite NADA y contaria como
                # fallo una relacion que nunca se probo. Se clickea el centro de la region ORIGEN.
                if intervencion is not None:
                    x, y = self._coordenada_de_intervencion(current_grid)
                    self._prev_click = (x, y)
                    detalle = "coordenada con la que la relacion se disparo cuando se observo"
                elif submeta is not None:
                    x, y = self._coordenada_de_submeta(submeta, current_grid)
                    self._prev_click = (x, y)
                    detalle = "coordenada de la sub-meta confirmada que se esta explotando"
                else:
                    x, y = self._elegir_coordenada(current_grid, signature)
                    detalle = (
                        "celda no probada de mayor prioridad segun el ranker de coordenadas "
                        f"({self._clicks.plantillas_aprendidas} plantilla(s) aprendida(s) en esta "
                        "partida)"
                    )
                decision = ActionDecision(
                    action=action,
                    x=x,
                    y=y,
                    reasoning=f"Exploracion: ACTION6 en ({x},{y}) -- {detalle} -- {motivo}.",
                )
            else:
                self._prev_click = None
                decision = ActionDecision(
                    action=action,
                    reasoning=f"Exploracion: {action.value} -- {motivo}.",
                )

        self._prev_signature = signature
        self._prev_action = decision.action
        self._prev_grid = current_grid  # BL.21501: el `pre` de la proxima transicion observada
        self._prev_mask_version = mask_version
        self._pasos += 1
        return decision

    def _observar_direcciones(self, mecanica: Mecanica | None) -> str | None:
        """BL.21590 -- clasifica el efecto de la accion ANTERIOR contra la creencia de direcciones
        y alimenta la incognita de mecanica de ACTION5/ACTION7 con la MISMA mecanica.

        Se observa TODA transicion, no solo las que sugirio el libro de aperturas: una confirmacion
        que llega desde cualquier macro es gratis. Devuelve el resultado para que `decide` se lo
        pase al libro junto con `hubo_cambio`, que a esta altura todavia no se calculo.

        BL.21593 -- si la flecha NO produjo traslacion, se mira la grilla PREVIA buscando pared por
        delante del avatar (estado del rastreador ANTES de esta transicion): ese contexto decide
        cuanto mueve el fallo al posterior del mapeo. El avatar se actualiza despues, en `decide`."""
        if self._prev_action is None:
            return None
        accion = self._prev_action.value
        if mecanica is not None:
            self._incognitas.observar(accion, mecanica)
        pared = None
        if accion in self._direcciones.posterior.botones and (
            mecanica is None or mecanica.traslacion_principal is None
        ):
            pared = contexto_de_pared(
                None if self._prev_grid is None else self._prev_grid,
                self._avatar.caja,
                self._avatar.piso,
                profundidad_de_sondeo(self._direcciones.magnitud_de(accion)),
            )
        return self._direcciones.observar(accion, mecanica, pared)

    def _atribuir_click(self, hubo_cambio: bool) -> None:
        """BL.21560 -- registra en la memoria de clicks el resultado del ACTION6 anterior. Solo se
        atribuye cuando la accion previa FUE un click: cualquier otra accion pudo mover el tablero
        por su cuenta y anotarselo a una coordenada seria evidencia falsa."""
        if (
            self._prev_click is None
            or self._prev_action is not GameAction.ACTION6
            or self._prev_signature is None
        ):
            return
        x, y = self._prev_click
        self._clicks.registrar_resultado(
            self._prev_signature,
            x,
            y,
            hubo_cambio,
            None if self._prev_grid is None else [list(f) for f in self._prev_grid],
        )

    def _elegir_coordenada(
        self, current_grid: tuple[tuple[int, ...], ...] | None, signature: int
    ) -> tuple[int, int]:
        """Coordenada del proximo ACTION6, recordada para poder atribuirle el resultado. Sin grilla
        observable cae a la heuristica previa, que ya resolvia ese caso tirando al azar."""
        if not current_grid or not current_grid[0]:
            objetivo = pick_click_target(current_grid or (), self._rng)
        else:
            objetivo = self._clicks.elegir_objetivo(
                [list(fila) for fila in current_grid],
                signature,
                self._rng,
                self._region_cambiada,
            )
        self._prev_click = objetivo
        return objetivo

    def _declarar_vocabulario(self, available_actions: tuple[int, ...]) -> None:
        """BL.21702 -- cuantos botones ofrece el juego, hacia el rastreador de volatilidad.
        Fail-open con el MISMO criterio que el resto de los usos del modelo de mundo."""
        try:
            self._world_model.declarar_acciones_disponibles(len(available_actions))
        except Exception:  # noqa: BLE001 -- el modelo asiste, nunca bloquea la decision
            return

    def _continuar_macro(
        self,
        available_actions: tuple[int, ...],
        hubo_cambio: bool,
        estado_ya_visitado: bool = False,
    ) -> GameAction | None:
        """BL.21559 -- accion a repetir, o None si el compromiso termino. La logica vive en
        `MacroCommitment` (exploration_memory.py); aca solo se traduce entre el enum y su nombre.

        BL.21702 -- `estado_ya_visitado` corta la amplificacion x8 de una accion cosmetica: la
        macro se sostiene mientras el cambio sea INFORMATIVO, no mientras mueva un pixel."""
        anterior = self._prev_action.value if self._prev_action is not None else None
        disponibles = [f"ACTION{n}" for n in available_actions]
        repetida = self._macro.continuar(anterior, hubo_cambio, disponibles, estado_ya_visitado)
        return None if repetida is None else GameAction(repetida)

    def _hubo_cambio_enmascarado(
        self, current_grid: tuple[tuple[int, ...], ...] | None, mask: VolatilityMask | None
    ) -> bool:
        """La transicion anterior cambio el tablero ignorando las celdas volatiles -- la logica
        vive en `exploration_memory.hubo_cambio_enmascarado` (BL.21593 la mudo ahi)."""
        return hubo_cambio_enmascarado(self._prev_grid, current_grid, mask)

    def _registrar_novedad(self, signature: int, mask_version: int) -> None:
        """BL.21559 -- suma una visita al estado y, si la transicion anterior es comparable, la
        arista (firma origen, accion) -> firma destino.

        La transicion NO se registra cuando la mascara cambio entre las dos firmas: serian hashes de
        dos definiciones distintas de "estado" y el destino guardado no describiria nada (mismo
        criterio que `_record_outcome`)."""
        if (
            self._prev_signature is not None
            and self._prev_action is not None
            and mask_version == self._prev_mask_version
        ):
            self._novedad.registrar_transicion(
                self._prev_signature, self._prev_action.value, signature
            )
        self._novedad.registrar_visita(signature)

    def _clave_de_novedad(self, signature: int) -> Callable[[GameAction], tuple[int, ...]]:
        """Clave de orden por novedad para `rank_candidates` -- ver `StateNoveltyTracker.clave`."""
        return lambda accion: self._novedad.clave(signature, accion.value)

    def _observe_levels(self, frame: FrameData) -> bool:
        """BL.21557 -- lee la senal densa del frame y acredita la RECOMPENSA EXTRINSECA. Devuelve
        si el contador de niveles SUBIO en este paso (BL.21702: el detector de congelamiento lo usa
        para su periodo de gracia -- nunca reiniciar sobre progreso reciente).

        Si `levels_completed` subio respecto de la decision anterior, la accion que se acaba de
        ejecutar produjo el progreso: se le da prioridad en las proximas
        `LEVEL_REWARD_PRIORITY_USES` visitas a ESE mismo estado. Un salto de mas de un nivel no
        multiplica el credito -- el credito mide "esta accion sirve", no "cuanto sirvio", y darle mas
        peso solo alargaria el lockout.

        Defensivo con el wire: `levels_completed`/`win_levels` podrian llegar ausentes o negativos
        desde un entorno que no los implemente, y un contador basura corromperia el ranking."""
        niveles = max(0, int(getattr(frame, "levels_completed", 0) or 0))
        totales = max(0, int(getattr(frame, "win_levels", 0) or 0))
        if totales > self._win_levels:
            self._win_levels = totales
        if niveles > self._max_levels_completed:
            self._max_levels_completed = niveles

        subio = niveles > self._prev_levels_completed
        self._prev_levels_completed = niveles
        if not subio or self._prev_signature is None or self._prev_action is None:
            return subio

        entry = self._memory.setdefault(self._prev_signature, EntradaDeExploracion())
        entry.reward_credits[self._prev_action] = LEVEL_REWARD_PRIORITY_USES
        # Progreso real desmiente cualquier marca de no-op previa sobre esa accion.
        entry.no_op_actions.discard(self._prev_action)
        entry.no_op_streak.pop(self._prev_action, None)
        return True

    @staticmethod
    def _consume_reward_credit(entry: EntradaDeExploracion | None, action: GameAction) -> None:
        """Gasta un uso del credito de recompensa. Que se agote es DELIBERADO: la marca permanente
        seria un lockout simetrico al de los no-ops que BL.21518 tuvo que desarmar -- en ARC-AGI-3 el
        efecto de una accion depende del estado global, asi que "funciono una vez" no es "funciona
        siempre"."""
        if entry is None:
            return
        restante = entry.reward_credits.get(action)
        if restante is None:
            return
        if restante > 1:
            entry.reward_credits[action] = restante - 1
        else:
            entry.reward_credits.pop(action, None)

    def _alimentar_relaciones(
        self, current_grid: tuple[tuple[int, ...], ...] | None, mecanica: Mecanica | None
    ) -> None:
        """BL.21704 -- alimenta el almacen de causa a distancia con la transicion observada.

        La `mecanica` se le pasa YA CALCULADA por el modelo de mundo: la exclusion de lo que el
        vocabulario local ya explica tiene que correr con el detector REAL, y recalcularlo seria un
        segundo detector sobre la misma transicion. Mismo fail-open que `_feed_world_model`: el
        almacen asiste, jamas bloquea la partida."""
        if self._prev_action is None or self._prev_grid is None or current_grid is None:
            # No hay transicion comparable que ofrecer (arranque, RESET, frame ausente). Se cuenta:
            # sin este contador el diagnostico no cerraba y un detector apagado se leia igual que
            # uno sin senal.
            self._relaciones.anotar_transicion_no_ofrecida()
            return
        try:
            mask, _ = self._volatility_mask_segura()
            self._relaciones.observar(
                self._prev_action.value,
                [list(fila) for fila in self._prev_grid],
                [list(fila) for fila in current_grid],
                mecanica,
                mask,
                # La coordenada SOLO cuando la accion previa fue un click: es lo que hace repetible
                # a una relacion disparada por ACTION6. Ver `_con_accion` en el almacen.
                self._prev_click if self._prev_action is GameAction.ACTION6 else None,
            )
        except Exception:  # noqa: BLE001 -- ver docstring: nunca romper la partida por el modelo
            # EL FAIL-OPEN NO PUEDE SER MUDO. Si `observar` lanzara en todos los pasos, el
            # diagnostico devolveria el dict en ceros -- el MISMO reporte que "no hay senal" -- y
            # un cero por bug seria indistinguible de un cero honesto. El conteo viaja en
            # `diagnostico()["excepcionesDelLlamador"]`.
            self._relaciones.anotar_excepcion()
            return

    def _sugerir_intervencion(self, available_actions: tuple[int, ...]) -> GameAction | None:
        """BL.21704 -- accion a REPETIR para llevar una relacion no local a veredicto, o None.

        ACTION6 SI entra, a diferencia de lo que pasa con los no-ops: aca la coordenada no se
        pierde, porque `_coordenada_de_intervencion` clickea el centro de la region ORIGEN de la
        relacion pendiente. Un boton que abre una puerta es justamente el caso donde la accion es
        un click, y excluirla dejaria a la via intervencional sin la mitad de la familia."""
        try:
            disponibles = [f"ACTION{n}" for n in available_actions]
            sugerida = self._relaciones.sugerir_intervencion(disponibles)
            if sugerida is None:
                return None
            return GameAction(sugerida)
        except Exception:  # noqa: BLE001 -- el almacen asiste, nunca bloquea la decision
            self._relaciones.anotar_excepcion()
            return None

    def _explotar_submeta(self, available_actions: tuple[int, ...]) -> SubMeta | None:
        """BL.21704 -- USA una relacion causal a distancia ya CONFIRMADA, o None.

        ESTE METODO ES EL CONSUMIDOR QUE FALTABA. La version anterior del BL construia el almacen,
        gastaba hasta 24 acciones por partida confirmando relaciones... y nadie llamaba nunca a
        `submetas()`: `grep -rn 'submetas' arc_agent/` fuera del propio almacen daba CERO. El unico
        cambio de comportamiento era el GASTO, asi que el gate de merge no midio "sirve la causa a
        distancia" sino "sirve gastar acciones en intervenciones cuyo resultado se descarta". Un
        empate medido asi no es evidencia sobre la hipotesis del BL.

        CUANDO SE EXPLOTA: cuando el tablero lleva `PASOS_SIN_CAMBIO_PARA_SUBMETA` pasos sin
        moverse. Ese es el momento en que una relacion probada vale mas que el ranker de novedad:
        el ranker propone lo menos visitado, pero una sub-meta confirmada es lo unico que el agente
        SABE que cambia una region lejana -- y en el caso de un click, saberlo incluye la celda
        exacta, que entre 4.096 el ranker no vuelve a encontrar por casualidad.

        POR QUE CON PRESUPUESTO: explotar es repetir algo ya conocido, o sea CERO informacion nueva
        si el efecto no destraba nada. `MAX_EXPLOTACIONES_DE_SUBMETA` acota lo que puede costar
        equivocarse, igual que el presupuesto de la via intervencional."""
        if self._pasos_sin_cambio < PASOS_SIN_CAMBIO_PARA_SUBMETA:
            return None
        if self._explotaciones_de_submeta >= MAX_EXPLOTACIONES_DE_SUBMETA:
            return None
        try:
            disponibles = {f"ACTION{n}" for n in available_actions}
            for submeta in self._relaciones.submetas():
                if submeta.accion in disponibles:
                    self._explotaciones_de_submeta += 1
                    self._submeta_vigente = submeta
                    return submeta
            return None
        except Exception:  # noqa: BLE001 -- el almacen asiste, nunca bloquea la decision
            self._relaciones.anotar_excepcion()
            return None

    @property
    def explotaciones_de_submeta(self) -> int:
        """Acciones gastadas en EXPLOTAR una relacion confirmada. Observabilidad del unico camino
        por el que el detector de causa a distancia puede mover la metrica del gate."""
        return self._explotaciones_de_submeta

    def _coordenada_de_submeta(
        self, submeta: SubMeta, current_grid: tuple[tuple[int, ...], ...] | None
    ) -> tuple[int, int]:
        """Coordenada con la que la sub-meta se disparo. Sin ella un ACTION6 no repite NADA."""
        if submeta.coordenada is None or not current_grid or not current_grid[0]:
            return pick_click_target(current_grid or (), self._rng)
        x, y = submeta.coordenada
        alto = len(current_grid)
        ancho = len(current_grid[0])
        return min(max(x, 0), ancho - 1), min(max(y, 0), alto - 1)

    def _coordenada_de_intervencion(
        self, current_grid: tuple[tuple[int, ...], ...] | None
    ) -> tuple[int, int]:
        """Coordenada con la que la relacion se disparo cuando se OBSERVO -- la unica que repite la
        intervencion. Acotada a la grilla; sin relacion pendiente cae al ranker de clicks.

        NO es el centro de la region origen. Eso fue lo primero que se probo y se midio en vivo
        sobre lp85: las 8 relaciones retenidas quedaron refutadas en su primera repeticion, porque
        en desfase 0 la region origen es un EFECTO del click y no el lugar donde se clickeo."""
        relacion = self._relaciones.relacion_pendiente
        if relacion is None or relacion.coordenada is None or not current_grid or not current_grid[0]:
            return pick_click_target(current_grid or (), self._rng)
        x, y = relacion.coordenada
        alto = len(current_grid)
        ancho = len(current_grid[0])
        return min(max(x, 0), ancho - 1), min(max(y, 0), alto - 1)

    def _world_model_no_ops(self, available_actions: tuple[int, ...]) -> set[GameAction]:
        """BL.21501 -- no-ops que el modelo de mundo confirmo por sintesis (programa identidad con
        evidencia suficiente, ver MIN_OBSERVATIONS_FOR_NO_OP).

        ACTION6 queda EXENTA por el mismo motivo que en `_record_outcome`: su efecto depende de la
        coordenada, y el motor solo ve el par (accion, grilla) -- no distingue un click en (0,0)
        de uno en (32,17), asi que su veredicto de 'identidad' no es concluyente para esta accion.

        BL.21593 -- se suman las flechas que el POSTERIOR jerarquico condeno como inertes: el
        acople por arquetipo las excluye con menos observaciones propias que el programa
        identidad, y el epsilon de reexploracion las sigue reconsiderando igual.

        Fail-open: si el modelo lanza, se devuelve el conjunto vacio y decide la heuristica sola."""
        try:
            posterior = self._direcciones.posterior
            return {
                a
                for n in available_actions
                if (a := GameAction(f"ACTION{n}")) is not GameAction.ACTION6
                and (self._world_model.is_known_no_op(a.value) or posterior.inerte(a.value))
            }
        except Exception:  # noqa: BLE001 -- el modelo asiste, nunca bloquea la decision
            return set()

    def _volatility_mask_segura(self) -> tuple[VolatilityMask | None, int]:
        """BL.21558 -- mascara vigente del modelo de mundo y su version.

        Fail-open con el MISMO criterio que `_world_model_no_ops` y `_feed_world_model`: si el
        modelo lanza, se devuelve (None, version previa) y la politica decide con la heuristica
        sola. Devolver la version PREVIA y no 0 es deliberado -- un cambio de version inventado
        haria que `_record_outcome` se saltee la comparacion de firmas por un fallo del modelo."""
        try:
            return self._world_model.get_volatility_mask(), (
                self._world_model.get_volatility_version()
            )
        except Exception:  # noqa: BLE001 -- el modelo asiste, nunca bloquea la decision
            return None, self._prev_mask_version

    def _feed_world_model(
        self, current_grid: tuple[tuple[int, ...], ...] | None
    ) -> Mecanica | None:
        """BL.21501 -- alimenta el motor de sintesis con la transicion (accion, pre, post) y
        devuelve la mecanica de objetos que el modelo detecto en ella (BL.21590: la creencia de
        direcciones la consume, y recalcularla seria correr el detector dos veces por paso).

        Fail-open: la sintesis es una BUSQUEDA acotada por presupuesto (SynthesisBudget), pero si
        algun caso patologico lanzara, la partida debe seguir -- el modelo de mundo es una ayuda
        para decidir, nunca un requisito para jugar."""
        if self._prev_action is None or self._prev_grid is None or current_grid is None:
            return None
        try:
            # El motor trabaja con grillas MUTABLES (list[list[int]]) porque sus primitivas hacen
            # asignacion por indice; `FrameData.frame` son tuplas inmutables (hasheables, para la
            # firma de estado). Sin esta conversion, record_observation lanza
            # "'tuple' object does not support item assignment" y el fail-open de abajo se lo
            # tragaba en silencio -- el modelo quedaba vacio y el DSL seguia sin usarse.
            return self._world_model.record_observation(
                self._prev_action.value,
                [list(row) for row in self._prev_grid],
                [list(row) for row in current_grid],
            )
        except Exception:  # noqa: BLE001 -- ver docstring: nunca romper la partida por el modelo
            return None

    def _feed_capas_intermedias(self, frame: FrameData) -> None:
        """BL.22236 -- `frame.frame` trae TODAS las capas que el motor genero mientras la accion
        animaba antes de asentarse (arcengine/base_game.py acumula una capa por `step()` interno);
        el resto de la politica solo mira la ULTIMA (`current_grid` arriba) porque esa es LA firma
        de estado -- decision deliberada de `state_signature.extract_grid`. Pero 13/25 juegos
        publicos esconden informacion que SOLO existe en una capa intermedia (ej. sp80: 624
        pixeles visibles unicamente durante la animacion de "pouring", uno de nuestros
        `environment_files/`) y esa evidencia no llega a ningun lado si nadie la mira.

        Expone las capas intermedias al analizador de mecanica OBJETO-CENTRICO
        (`MechanicsMemory.observe_evidencia_adicional`, sin busqueda ni presupuesto -- nunca la
        sintesis DSL, que si tiene costo de busqueda) como transiciones adicionales de la MISMA
        accion: `self._prev_action` es quien produjo TODAS las capas de este frame. No toca la
        firma de estado, la mascara de volatilidad ni la sintesis DSL.

        Fail-open: mismo criterio que `_feed_world_model` -- el modelo de mundo asiste, nunca
        bloquea la partida."""
        if self._prev_action is None:
            return
        try:
            capas = extraer_grid_multicapa(frame)
            if len(capas) < 2:
                return
            mask = self._world_model.get_volatility_mask()
            memoria = self._world_model.get_mechanics_memory()
            for anterior, siguiente in zip(capas, capas[1:]):
                memoria.observe_evidencia_adicional(
                    self._prev_action.value, anterior, siguiente, mask
                )
        except Exception:  # noqa: BLE001 -- ver docstring: nunca romper la partida por el modelo
            return

    def _record_outcome(self, signature: int, mask_version: int) -> None:
        if self._prev_signature is None or self._prev_action is None:
            return
        entry = self._memory.setdefault(self._prev_signature, EntradaDeExploracion())
        entry.visits[self._prev_action] = entry.visits.get(self._prev_action, 0) + 1

        # BL.21558 -- la mascara cambio entre las dos firmas: no describen el mismo "estado" y
        # compararlas afirmaria un cambio (o una ausencia de cambio) que no se observo. Se cuenta
        # la visita y se espera a la proxima transicion, ya bajo una unica definicion.
        if mask_version != self._prev_mask_version:
            return

        if signature != self._prev_signature:
            # La accion SI cambio el estado: deja de ser no-op y se resetea su conteo.
            entry.no_op_actions.discard(self._prev_action)
            entry.no_op_streak.pop(self._prev_action, None)
            return

        # BL.21518 -- ACTION6 (el click) NUNCA se marca no-op por observacion de estado. Su efecto
        # depende de la COORDENADA, que `pick_click_target` elige con el rng en cada decision: un
        # click sin efecto en (0,0) no dice absolutamente nada sobre (32,17). Marcarla descartaria
        # todas las coordenadas restantes de este estado por haber probado UNA. Si algun dia se
        # quiere memoria de clicks fallidos, la clave tiene que ser (firma, x, y), no (firma, accion).
        if self._prev_action is GameAction.ACTION6:
            return

        # Para el resto: se exigen NO_OP_CONFIRMATIONS observaciones antes de excluir. Una sola
        # puede ser ruido del entorno (frame identico por lag, no por la accion) -- mismo criterio
        # que SEED_MIN_NONOP_CONFIRMATIONS del runner TS, que ya lo documentaba asi.
        streak = entry.no_op_streak.get(self._prev_action, 0) + 1
        entry.no_op_streak[self._prev_action] = streak
        if streak >= NO_OP_CONFIRMATIONS:
            entry.no_op_actions.add(self._prev_action)


# ============================== arc_agent/kaggle_adapter.py ==============================
"""[arc-agi3-kaggle-agent/kaggle_adapter] BL.21555 -- adaptador delgado entre el nucleo offline
(`arc_agent/`, stdlib pura) y el contrato OFICIAL del framework `ARC-AGI-3-Agents` de Kaggle.

LA FRONTERA. El nucleo de decision (policy, world_model, priors, exploration_memory, clicks,
direcciones) no importa terceros: trabaja sobre los tipos internos de `types.py` y se testea sin
red ni framework. Este modulo es el UNICO que importa `arcengine` y `agents` (los provee el
entorno de ejecucion: el venv local con las wheels del dataset, o la imagen de Kaggle) y hace dos
traducciones y nada mas:

  arcengine.FrameData  ->  types.FrameData   (grillas a tuplas hasheables, estado, acciones)
  types.ActionDecision ->  arcengine.GameAction  (con `set_data({"x","y"})` para ACTION6)

CONTRATO OFICIAL que implementa `MyAgent` (fijado por `agents.agent.Agent` del starter):
  - Clase llamada exactamente `MyAgent`; `self.game_id` lo inyecta el framework.
  - `__init__(self, *args, **kwargs)` delegando en `super().__init__`.
  - `is_done` devuelve True al ganar (`GameState.WIN`) o cuando el reloj del batch se acaba
    (BL.21701, `reloj_presupuesto.py`): ante GAME_OVER NO corta -- se devuelve `GameAction.RESET`
    y se sigue jugando (comentario literal del starter: "Don't stop on GAME_OVER, we want to
    RESET and retry").
  - ACTION6 viaja con `set_data({"x": 0..63, "y": 0..63})` mas `action.reasoning`.

En el entregable generado (`submission/build_agent.py`) este modulo va AL FINAL del archivo unico:
sus imports relativos se eliminan y los nombres del nucleo ya viven en el mismo namespace. Los
imports de `arcengine` van con alias (`FrameOficial`, ...) a proposito: en ese namespace plano los
nombres pelados `FrameData`/`GameAction`/`GameState` son los INTERNOS de `types.py`."""

import time
from typing import Any

from agents.agent import Agent
from arcengine import FrameData as FrameOficial
from arcengine import GameAction as AccionOficial
from arcengine import GameState as EstadoOficial






#: Estado oficial (por su `value`) -> estado interno. `NOT_PLAYED` es el `NOT_STARTED` interno
#: (mismo significado, otro nombre en el wire). Un estado desconocido degrada a NOT_FINISHED:
#: "jugable" es el lado del error que mantiene la partida viva.
_ESTADO_INTERNO: dict[str, GameState] = {
    "NOT_PLAYED": GameState.NOT_STARTED,
    "NOT_FINISHED": GameState.NOT_FINISHED,
    "WIN": GameState.WIN,
    "GAME_OVER": GameState.GAME_OVER,
}


def frame_oficial_a_interno(frame: FrameOficial) -> FrameData:
    """Convierte el FrameData de `arcengine` al FrameData interno de la politica.

    Las grillas pasan de listas mutables a tuplas: el nucleo exige instancias hasheables (la
    firma de estado de `exploration_memory.compute_signature` hashea `frame.frame` directo).
    `available_actions` filtra ids fuera de 1..7: el nucleo los mapea a `ACTION{n}` y el id 0
    (RESET) no es una accion de exploracion -- resetear es una decision del wrapper/la politica,
    nunca un candidato del ranking."""
    return FrameData(
        game_id=str(frame.game_id or ""),
        guid=str(frame.guid or ""),
        frame=tuple(
            tuple(tuple(int(celda) for celda in fila) for fila in grilla)
            for grilla in (frame.frame or [])
        ),
        state=_ESTADO_INTERNO.get(getattr(frame.state, "value", ""), GameState.NOT_FINISHED),
        available_actions=tuple(
            sorted(int(n) for n in (frame.available_actions or []) if 1 <= int(n) <= 7)
        ),
        levels_completed=max(0, int(frame.levels_completed or 0)),
        win_levels=max(0, int(frame.win_levels or 0)),
    )


def decision_a_accion_oficial(decision: ActionDecision) -> AccionOficial:
    """Convierte la ActionDecision interna a la GameAction de `arcengine`, lista para emitir.

    ACTION6 exige coordenada: se clampa a la grilla oficial de 64x64 por defensa (el nucleo ya
    elige dentro de rango) y viaja via `set_data`, que es la UNICA via que el gateway valida. El
    razonamiento interno se declara en `action.reasoning` -- misma transparencia de replay que
    pide el starter."""
    accion = AccionOficial.from_name(decision.action.value)
    if accion.is_complex():
        x = min(GRID_MAX_COORD, max(0, int(decision.x if decision.x is not None else 0)))
        y = min(GRID_MAX_COORD, max(0, int(decision.y if decision.y is not None else 0)))
        accion.set_data({"x": x, "y": y})
        accion.reasoning = {"x": x, "y": y, "razonamiento": decision.reasoning}
    else:
        accion.reasoning = decision.reasoning
    return accion


class MyAgent(Agent):
    """Agente Prometheus: politica de exploracion offline adaptada al framework oficial.

    Wrapper DELGADO a proposito: toda la decision vive en `ExplorationPolicy` (una instancia por
    partida, con memoria de estados, modelo de mundo y ranker de clicks). Aca solo se traducen
    formatos y se cumple la semantica del loop oficial."""

    #: COTA DE SEGURIDAD, ya NO el limite operativo (BL.21701): el limite operativo lo pone
    #: `RELOJ`. El numero y su justificacion viven en `reloj_presupuesto.py`, que es donde vive
    #: todo el presupuesto -- aca solo se adopta, para que no haya dos verdades.
    MAX_ACTIONS = COTA_DE_SEGURIDAD_DE_ACCIONES

    #: Reloj del batch (BL.21701). Atributo de CLASE para poder inyectar uno de prueba sin tocar
    #: el global del proceso; en produccion es el que marca su inicio al importar el modulo.
    RELOJ = RELOJ_GLOBAL

    #: Semilla opcional para reproducir una partida (tests/depuracion). None = semilla por tiempo:
    #: dos corridas exploran distinto, que es lo deseable en la evaluacion real.
    SEMILLA: str | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        semilla = self.SEMILLA if self.SEMILLA is not None else f"{self.game_id}.{time.time_ns()}"
        self._politica = ExplorationPolicy(create_seeded_random(semilla))
        # El Swarm construye TODOS los agentes en el hilo principal antes de arrancar ningun hilo,
        # asi que al registrarse aca el reloj ya conoce el tamano del batch cuando reparte.
        # Se BINDEA el reloj en la instancia: cada partida vive bajo el reloj que estaba
        # vigente cuando se la construyo, y un cambio posterior del atributo de clase no le
        # mueve el piso a una partida en curso (la manija dejaria de existir en su reloj).
        self._reloj = self.RELOJ
        self._manija_de_reloj = self._reloj.registrar_partida(str(self.game_id))
        self._cpu_al_arrancar: float | None = None
        self.cortada_por_reloj = False

    @property
    def name(self) -> str:
        return f"{super().name}.{self.MAX_ACTIONS}"

    @property
    def niveles_maximos(self) -> int:
        """Nivel maximo alcanzado segun la politica (metrica de seleccion offline, BL.21557)."""
        return self._politica.max_levels_completed

    def consumo_de_la_partida(self) -> float:
        """Segundos de CPU que consumio ESTA partida. La linea base se toma en la primera consulta
        y no en `__init__` a proposito: `__init__` corre en el hilo principal del Swarm y el juego
        corre en el suyo, y `time.thread_time()` mide el hilo que pregunta."""
        actual = medir_cpu_del_hilo()
        if self._cpu_al_arrancar is None:
            self._cpu_al_arrancar = actual
        return max(0.0, actual - self._cpu_al_arrancar)

    def is_done(self, frames: list[FrameOficial], latest_frame: FrameOficial) -> bool:
        """Corta al ganar o cuando el reloj del batch dice basta. Ante GAME_OVER NO corta:
        `choose_action` resetea y sigue jugando.

        EL CORTE POR RELOJ VIVE ACA (BL.21701) y no en un watchdog aparte porque este es el unico
        punto de salida que el contrato oficial ofrece: `Agent.main()` evalua `is_done` al tope de
        cada vuelta, asi que devolver True termina el `while`, dispara `cleanup()` y deja que el
        Swarm cierre la scorecard. Matar el hilo o levantar una excepcion dejaria la corrida sin
        parquet -- justo el desenlace que el reloj existe para evitar."""
        if latest_frame.state is EstadoOficial.WIN:
            return True
        if self._reloj.debe_cortar(self._manija_de_reloj, self.consumo_de_la_partida()):
            self.cortada_por_reloj = True
            return True
        return False

    def cleanup(self, scorecard: Any = None) -> None:
        """Devuelve el tiempo no usado de esta partida al pool ANTES del cierre del framework.

        Se engancha aca y no en `is_done` porque `Agent.main()` tambien sale por
        `action_counter > MAX_ACTIONS`, sin pasar por un `is_done` que diga True: sin este gancho
        una partida que agota la cota de seguridad quedaria contada como viva para siempre y
        estrangularia la cuota de las demas. `finalizar_partida` es idempotente -- el framework
        llama `cleanup()` desde `main()` y otra vez desde `Swarm.cleanup()`."""
        self._reloj.finalizar_partida(self._manija_de_reloj)
        super().cleanup(scorecard)

    def choose_action(self, frames: list[FrameOficial], latest_frame: FrameOficial) -> AccionOficial:
        # BL.21767 -- GAME_OVER viaja CRUDO a la politica. Hasta ese BL se disfrazaba aca de
        # NOT_STARTED para reusar la rama de reset, y la consecuencia era que el evento mas
        # informativo de la partida se procesaba como el arranque: el agente no tenia DONDE
        # anotar la muerte. Ahora la rama terminal de `decide` cubre los dos estados (mismo
        # RESET, mismo corte de continuidad de macro y click) y ademas registra el hecho en la
        # memoria de muertes ANTES de cortar -- con la mascara puesta, ese contexto no existia.
        decision = self._politica.decide(frame_oficial_a_interno(latest_frame))
        return decision_a_accion_oficial(decision)
