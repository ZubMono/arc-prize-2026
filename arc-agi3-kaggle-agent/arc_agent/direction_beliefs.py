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
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Iterable

# Imports relativos SIEMPRE en una linea: el builder del notebook los desmonta con un regex
# ^from \.\w* import .+$ que no cubre la forma con parentesis multilinea.
from .mechanics_posterior import EVENTO_DESCONOCIDA, EVENTO_OTRA, EVENTO_SIN_CAMBIO
from .mechanics_posterior import EVENTO_TRASLACION, EventoObservado, PosteriorDeMapeo
from .mechanics_posterior import EVENTOS_NOMBRADOS
from .priors import DIRECTION_PRIORS
# Import a UN solo nivel (`.world_model`, no `.world_model.object_mechanics`): el builder del
# notebook desmonta los imports relativos con el regex `^from \.\w* import .+$`, que no cubre un
# segundo punto -- con la forma anidada el notebook de submission queda con un ImportError.
from .world_model import Mecanica, TIPOS_DE_NO_MIRE, TIPO_SIN_MEDICION
from .world_model import TIPO_SIN_NOMBRAR

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
