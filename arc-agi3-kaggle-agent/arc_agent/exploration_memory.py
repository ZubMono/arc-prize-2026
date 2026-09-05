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
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from .banderas import MACRO_CAMBIO_INFORMATIVO, Banderas, bandera_activa
from .priors import CLICK_PRIORS
from .types import FrameData, GameAction
# Import a UN solo nivel (`.world_model`, no `.world_model.state_signature`): el builder del
# notebook desmonta los imports relativos con el regex `^from \.\w* import .+$`, que no cubre un
# segundo punto -- con la forma anidada el notebook de submission queda con un ImportError.
from .world_model import VolatilityMask, compute_state_signature, grids_equal_masked


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
