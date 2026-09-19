"""[arc-agi3-kaggle-agent/tests/support/reloj_falso] BL.21701 -- utileria compartida por los tests
del guard de las 9 horas: un reloj de pared simulado y una replica de la FORMA del lazo oficial.

POR QUE UN RELOJ SIMULADO. Un test que espere de verdad a que se agote un presupuesto tarda horas y
ademas es flakeante en CI. Aca el tiempo lo avanzan los tests a mano, con el mismo modelo con el
que la medicion extrapolo: bajo el GIL los N hilos del Swarm se turnan un solo nucleo, asi que cada
accion consume CPU de SU partida y avanza el reloj de pared del batch en la misma cantidad.

POR QUE SE REPLICA EL LAZO OFICIAL EN VEZ DE IMPORTARLO. El framework `ARC-AGI-3-Agents` no esta en
el repo: lo baja `make setup` con el token de Kaggle, y CI tiene que poder correr estos tests igual.
El cableado contra el framework REAL lo cubre `tests/test_kaggle_adapter.py`, que se skipea limpio
sin el dataset."""
from __future__ import annotations

import threading

from arc_agent.reloj_presupuesto import RelojDePresupuesto


class RelojFalso:
    """Reloj de pared simulado, thread-safe (lo comparten los hilos que simulan partidas)."""

    def __init__(self) -> None:
        self._t = 0.0
        self._candado = threading.Lock()

    def __call__(self) -> float:
        with self._candado:
            return self._t

    def avanzar(self, segundos: float) -> None:
        with self._candado:
            self._t += segundos


def reloj_de_prueba(
    presupuesto: float = 1000.0, margen: float = 10.0
) -> tuple[RelojDePresupuesto, RelojFalso]:
    """Un `RelojDePresupuesto` con tiempo simulado, mas la manija para avanzarlo."""
    falso = RelojFalso()
    reloj = RelojDePresupuesto(
        presupuesto_segundos=presupuesto, margen_de_cierre=margen, ahora=falso
    )
    return reloj, falso


class AgenteDePrueba:
    """Replica de la FORMA del lazo oficial (`vendor/ARC-AGI-3-Agents/agents/agent.py:main`):

        while not self.is_done(...) and self.action_counter <= self.MAX_ACTIONS:
            ...
            self.action_counter += 1
        self.cleanup()

    Reproduce el cableado que `kaggle_adapter.MyAgent` hace contra el framework real: `is_done`
    consulta el reloj y `cleanup` devuelve el tiempo no usado al pool."""

    def __init__(
        self,
        reloj: RelojDePresupuesto,
        falso: RelojFalso,
        costo: float,
        etiqueta: str,
        gana_en: int | None = None,
        max_actions: int = 100000,
    ) -> None:
        self._reloj = reloj
        self._falso = falso
        self._costo = costo
        self._gana_en = gana_en
        self.MAX_ACTIONS = max_actions
        self.action_counter = 0
        self.consumo = 0.0
        self.veces_que_limpio = 0
        self.cortada_por_reloj = False
        self.gano = False
        self._manija = reloj.registrar_partida(etiqueta)

    def is_done(self) -> bool:
        if self._gana_en is not None and self.action_counter >= self._gana_en:
            self.gano = True
            return True
        if self._reloj.debe_cortar(self._manija, self.consumo):
            self.cortada_por_reloj = True
            return True
        return False

    def cleanup(self) -> None:
        self._reloj.finalizar_partida(self._manija)
        self.veces_que_limpio += 1

    def main(self) -> None:
        while not self.is_done() and self.action_counter <= self.MAX_ACTIONS:
            self.consumo += self._costo
            self._falso.avanzar(self._costo)
            self.action_counter += 1
        self.cleanup()
