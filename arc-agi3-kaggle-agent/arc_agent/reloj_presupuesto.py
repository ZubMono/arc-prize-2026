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
from __future__ import annotations

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
