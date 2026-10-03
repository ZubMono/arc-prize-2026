"""[arc-agi3-kaggle-agent/tests/test_bl21559_macro_novedad] BL.21559 -- contrato y EFECTO de las dos
piezas que rompen el ciclado: compromiso con la accion elegida (macro-acciones) y novedad por conteo
sobre la firma enmascarada.

EL DEFECTO, medido en produccion contra la API oficial: ar25-0c556536 {A1:15, A2:16, A3:15, A4:16,
A5:3, A6:3, A7:15}; ka59-38d34dbb {A1:24, A2:24, A3:23, A4:23, A6:6}; dc22-fdcac232 {A1:30, A2:29,
A3:30, A4:30, A6:9} -- ciclado perfecto, rachas de a lo sumo DOS pasos iguales en 83, 100 y 128
pasos. En un juego de desplazamiento las cuatro direcciones se cancelan y el episodio termina donde
empezo.

EL TEST DE EFECTO usa un entorno de juguete con reglas conocidas (mueve un marcador) pero con el
RUIDO REAL de ARC-AGI-3: una barra de progreso que enciende una celda nueva por paso, que es lo que
se midio en las cuatro partidas grabadas. La magnitud AFIRMADA es la racha maxima de una misma
accion -- el compromiso -- y no el desplazamiento: la regla anterior de ESTE puerto no era el
round-robin del runner TS sino un ranking por visitas POR FIRMA DE ESTADO que, sin firmas que se
repitan (ver test_bl21559_real_games.py), degeneraba en barajado puro, y un paseo al azar tambien se
aleja del origen. La afirmacion causal sobre desplazamiento vive del lado TS
(`arc-agi-runner/src/worldModel/__tests__/bl21559.displacement.effect.test.ts`), donde la regla
anterior si producia el ciclado medido en produccion. El desplazamiento se imprime igual.
"""
from __future__ import annotations

from arc_agent.exploration_memory import MACRO_MAX_STEPS, MacroCommitment, StateNoveltyTracker
from arc_agent.policy import ExplorationPolicy, compute_signature, rank_candidates
from arc_agent.prng import create_seeded_random
from arc_agent.types import FrameData, GameAction, GameState

DISPONIBLES = ["ACTION1", "ACTION2", "ACTION3"]


# --------------------------------------------------------------------------------------------
# MacroCommitment -- contrato
# --------------------------------------------------------------------------------------------


def test_macro_repite_mientras_haya_cambio_hasta_el_tope() -> None:
    macro = MacroCommitment()
    macro.iniciar("ACTION1")
    emitidas = ["ACTION1"]
    for _ in range(20):
        siguiente = macro.continuar("ACTION1", True, DISPONIBLES)
        if siguiente is None:
            break
        emitidas.append(siguiente)
    # El tope cuenta el paso que abrio la macro: MACRO_MAX_STEPS en total, ni uno mas.
    assert emitidas == ["ACTION1"] * MACRO_MAX_STEPS
    assert macro.accion_vigente is None


def test_macro_corta_cuando_la_accion_deja_de_cambiar_el_tablero() -> None:
    macro = MacroCommitment()
    macro.iniciar("ACTION1")
    assert macro.continuar("ACTION1", False, DISPONIBLES) is None
    assert macro.pasos_emitidos == 0


def test_macro_corta_si_la_accion_dejo_de_estar_disponible() -> None:
    macro = MacroCommitment()
    macro.iniciar("ACTION3")
    assert macro.continuar("ACTION3", True, ["ACTION1", "ACTION2"]) is None


def test_macro_corta_si_en_el_medio_se_emitio_otra_accion() -> None:
    macro = MacroCommitment()
    macro.iniciar("ACTION1")
    assert macro.continuar("ACTION2", True, DISPONIBLES) is None


def test_macro_sin_compromiso_abierto_no_inventa_ninguno() -> None:
    assert MacroCommitment().continuar("ACTION1", True, DISPONIBLES) is None


# --------------------------------------------------------------------------------------------
# StateNoveltyTracker -- contrato
# --------------------------------------------------------------------------------------------


def test_novedad_prefiere_la_accion_nunca_probada_desde_este_estado() -> None:
    novedad = StateNoveltyTracker()
    novedad.registrar_visita(1)
    novedad.registrar_transicion(1, "ACTION1", 2)
    assert novedad.clave(1, "ACTION2") < novedad.clave(1, "ACTION1")
    assert novedad.hay_accion_sin_probar(1, DISPONIBLES)


def test_novedad_prefiere_el_destino_menos_visitado() -> None:
    novedad = StateNoveltyTracker()
    for _ in range(5):
        novedad.registrar_visita(2)
    novedad.registrar_visita(3)
    novedad.registrar_transicion(1, "ACTION1", 2)  # destino con 5 visitas
    novedad.registrar_transicion(1, "ACTION2", 3)  # destino con 1 visita
    assert novedad.clave(1, "ACTION2") < novedad.clave(1, "ACTION1")
    assert novedad.visitas_de(2) == 5


def test_novedad_desempata_por_intentos_cuando_el_destino_empata() -> None:
    novedad = StateNoveltyTracker()
    novedad.registrar_visita(2)
    novedad.registrar_transicion(1, "ACTION1", 2)
    novedad.registrar_transicion(1, "ACTION1", 2)
    novedad.registrar_transicion(1, "ACTION2", 2)
    assert novedad.clave(1, "ACTION2") < novedad.clave(1, "ACTION1")
    assert novedad.intentos_de(1, "ACTION1") == 2


def test_rank_candidates_con_novedad_le_gana_al_menos_visitada() -> None:
    """La afirmacion central de la mitad (b) del BL: el criterio viejo -- menos visitada primero --
    elegiria ACTION2, pero desde ESTE estado ACTION2 devuelve a un estado ya pisado seis veces y
    ACTION1 nunca se probo."""
    novedad = StateNoveltyTracker()
    for _ in range(6):
        novedad.registrar_visita(99)
    novedad.registrar_visita(1)
    novedad.registrar_transicion(1, "ACTION2", 99)
    visitas = {GameAction.ACTION1: 8, GameAction.ACTION2: 1}

    sin_novedad = rank_candidates((1, 2), visitas, set(), create_seeded_random("bl21559"))
    con_novedad = rank_candidates(
        (1, 2),
        visitas,
        set(),
        create_seeded_random("bl21559"),
        None,
        lambda accion: novedad.clave(1, accion.value),
    )
    assert sin_novedad[0] is GameAction.ACTION2  # criterio viejo: la menos visitada
    assert con_novedad[0] is GameAction.ACTION1  # criterio nuevo: la que lleva a lo desconocido


# --------------------------------------------------------------------------------------------
# EFECTO: desplazamiento con el entorno respondiendo
# --------------------------------------------------------------------------------------------

ALTO = 3
ANCHO = 16
INICIO = (8, 1)
PASOS = 24
#: Fila de la barra de progreso: el ultimo borde del frame, como en las cuatro partidas reales
#: (lf52 fila 0, ar25 columna 63, ka59 y dc22 fila 63). Dos filas de aire la separan del tablero.
FILA_BARRA = ALTO + 2
DISPONIBLES_ENV = (1, 2, 3, 4, 5)


class _EntornoDeDesplazamiento:
    """Entorno de juguete: ACTION1..4 mueven el marcador una celda (con recorte en el borde) y
    ACTION5 nunca hace nada -- cuatro direcciones que, repartidas parejo, se cancelan EXACTO. La
    barra de progreso avanza en CADA paso pase lo que pase: es el ruido real de ARC-AGI-3, y sin el
    la macro nunca sabria cuando cortar."""

    def __init__(self) -> None:
        self.x, self.y = INICIO
        self._contador = 0
        self._guid = 0

    def _grilla(self) -> tuple[tuple[int, ...], ...]:
        filas = [[0] * ANCHO for _ in range(FILA_BARRA + 1)]
        filas[self.y][self.x] = 5
        for i in range(ANCHO):
            vueltas = (self._contador - i) // ANCHO
            if self._contador >= i and vueltas >= 0:
                filas[FILA_BARRA][i] = 1 + (vueltas % 3)
        return tuple(tuple(fila) for fila in filas)

    def frame(self) -> FrameData:
        self._guid += 1
        return FrameData(
            game_id="desplazamiento",
            guid=f"g{self._guid}",
            frame=(self._grilla(),),
            state=GameState.NOT_FINISHED,
            available_actions=DISPONIBLES_ENV,
        )

    def step(self, accion: GameAction) -> FrameData:
        self._contador += 1
        if accion is GameAction.ACTION1:
            self.x = min(ANCHO - 1, self.x + 1)
        elif accion is GameAction.ACTION2:
            self.y = min(ALTO - 1, self.y + 1)
        elif accion is GameAction.ACTION3:
            self.x = max(0, self.x - 1)
        elif accion is GameAction.ACTION4:
            self.y = max(0, self.y - 1)
        return self.frame()

    @property
    def distancia_al_inicio(self) -> int:
        return abs(self.x - INICIO[0]) + abs(self.y - INICIO[1])


def _racha_maxima(secuencia: list[GameAction]) -> int:
    maxima = actual = 1
    for i in range(1, len(secuencia)):
        if secuencia[i] is secuencia[i - 1]:
            actual += 1
            maxima = max(maxima, actual)
        else:
            actual = 1
    return maxima


def _correr_politica_nueva(seed: str) -> tuple[int, list[GameAction]]:
    env = _EntornoDeDesplazamiento()
    policy = ExplorationPolicy(create_seeded_random(seed))
    frame = env.frame()
    distancia_maxima = 0
    acciones: list[GameAction] = []
    for _ in range(PASOS):
        decision = policy.decide(frame)
        acciones.append(decision.action)
        frame = env.step(decision.action)
        distancia_maxima = max(distancia_maxima, env.distancia_al_inicio)
    return distancia_maxima, acciones


def _correr_regla_vieja(seed: str) -> tuple[int, list[GameAction]]:
    """Regla ANTERIOR a este BL: el mismo `rank_candidates` de produccion invocado sin novedad y sin
    turno externo, con las visitas por FIRMA DE ESTADO que mantenia la politica. Sin compromiso entre
    pasos, que es exactamente lo que falta."""
    env = _EntornoDeDesplazamiento()
    rng = create_seeded_random(seed)
    visitas: dict[int, dict[GameAction, int]] = {}
    frame = env.frame()
    distancia_maxima = 0
    acciones: list[GameAction] = []
    for _ in range(PASOS):
        firma = compute_signature(frame)
        del_estado = visitas.setdefault(firma, {})
        accion = rank_candidates(frame.available_actions, del_estado, set(), rng)[0]
        del_estado[accion] = del_estado.get(accion, 0) + 1
        acciones.append(accion)
        frame = env.step(accion)
        distancia_maxima = max(distancia_maxima, env.distancia_al_inicio)
    return distancia_maxima, acciones


#: Los episodios se corren UNA vez: cada uno arrastra el modelo de mundo completo (sintesis DSL por
#: observacion) y repetirlos por test haria de este archivo el cuello del presupuesto de suite.
SEEDS = ("bl21559-d1", "bl21559-d2")
EPISODIOS = {
    seed: (_correr_regla_vieja(seed), _correr_politica_nueva(seed)) for seed in SEEDS
}


def test_la_politica_se_compromete_en_vez_de_repartir_acciones() -> None:
    """MAGNITUD MEDIDA: racha maxima de una misma accion y desplazamiento del marcador.

    Por que la afirmacion fuerte es la RACHA y no el desplazamiento: la regla anterior de ESTE puerto
    no era el round-robin del runner TS sino un ranking por visitas POR FIRMA DE ESTADO que, sin
    firmas que se repitan (ver test_bl21559_real_games.py), degeneraba en barajado puro. Un paseo al
    azar TAMBIEN se aleja del origen, solo que sin ir a ningun lado: la diferencia observable es que
    nunca sostiene una direccion."""
    for seed, ((vieja_distancia, vieja_acciones), (nueva_distancia, nueva_acciones)) in (
        EPISODIOS.items()
    ):
        print(
            f"[BL.21559][{seed}] en {PASOS} pasos -- regla vieja: racha maxima "
            f"{_racha_maxima(vieja_acciones)}, distancia maxima {vieja_distancia} | politica nueva: "
            f"racha maxima {_racha_maxima(nueva_acciones)}, distancia maxima {nueva_distancia}"
        )
        # La regla vieja no sostiene NUNCA una direccion: lo que se ve son rachas de barajado.
        assert _racha_maxima(vieja_acciones) <= 4, f"{seed}: la regla vieja ya se comprometia"
        # La nueva llega a macros de verdad. El desplazamiento se imprime pero no se afirma aca: la
        # regla anterior de ESTE puerto era un paseo al azar, y un paseo al azar tambien se aleja del
        # origen. La afirmacion CAUSAL sobre desplazamiento vive en el puerto TS, cuya regla anterior
        # si era el round-robin medido en produccion.
        assert _racha_maxima(nueva_acciones) >= 6, f"{seed}: no hubo compromiso"
        assert nueva_distancia >= 1, f"{seed}: el marcador no se movio nunca"


def test_la_macro_no_se_compromete_con_la_accion_INERTE_una_vez_formada_la_mascara() -> None:
    """La otra mitad del criterio de corte: repetir algo que no hace nada es gastar presupuesto, y el
    score de ARC-AGI-3 penaliza CUADRATICAMENTE cada accion de mas.

    ACTION5 es no-op siempre en este entorno, pero la barra de progreso avanza igual en cada paso:
    hasta que la mascara la reconoce (~paso 17 con estos parametros) TODA transicion parece cambio y
    la macro corre hasta el tope -- eso es esperado y esta documentado. Lo que se afirma aca es que
    DESPUES, con la mascara puesta, la accion inerte deja de sostener una macro."""
    for seed, (_, (_, acciones)) in EPISODIOS.items():
        cola = acciones[-6:]
        repetida_inerte = any(
            cola[i] is GameAction.ACTION5 and cola[i - 1] is GameAction.ACTION5
            for i in range(1, len(cola))
        )
        assert not repetida_inerte, f"{seed}: la macro se comprometio con la accion inerte"
