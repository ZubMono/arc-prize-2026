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
from __future__ import annotations

import time
from typing import Any

from agents.agent import Agent
from arcengine import FrameData as FrameOficial
from arcengine import GameAction as AccionOficial
from arcengine import GameState as EstadoOficial

from .policy import ExplorationPolicy
from .prng import create_seeded_random
from .reloj_presupuesto import COTA_DE_SEGURIDAD_DE_ACCIONES, RELOJ_GLOBAL, medir_cpu_del_hilo
from .types import ActionDecision, FrameData, GameAction, GameState, GRID_MAX_COORD

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
