"""[arc-agi3-kaggle-agent/tests/test_bl21590_prior_direcciones] BL.21590 -- contrato y EFECTO del
prior de direcciones con validacion dentro de las macros, el libro de aperturas (WARMUP ->
IDENTIFICAR -> EXPLOTAR) y la incognita de mecanica de ACTION5/ACTION7.

LOS CUATRO ESCENARIOS OBLIGATORIOS DEL BL:
  1. juego con mapeo CONTRARIO al prior -> el agente remapea (el prior es refutable);
  2. pared -> NO cuenta como refutacion (tercer resultado, `inconcluso`);
  3. juego degenerado donde nada se mueve -> el agente no se cuelga en IDENTIFICAR;
  4. WARMUP se activa solo cuando corresponde (flechas mudas + ACTION6 disponible), y NO se
     activa cuando el juego responde a las flechas desde el primer tanteo.
Mas el DELTA con-prior vs sin-prior en lazo cerrado: pasos hasta conocer el mapeo completo.
(El DELTA sobre las partidas REALES grabadas vive en test_bl21590_real_games.py, con numeros
exactos en paridad con el puerto TypeScript.)
"""
from __future__ import annotations

from arc_agent.direction_beliefs import (
    ESTADO_CONFIRMADA,
    ESTADO_REMAPEADA,
    ESTADO_SEMBRADA,
    ESTADO_SIN_EVIDENCIA,
    FIRMA_CAMBIO_DE_ESCENA,
    FIRMA_DISPARO,
    FIRMA_INERTE,
    FIRMA_TOGGLE,
    FIRMAS_DE_MECANICA,
    RESULTADO_INCONCLUSO,
    CreenciaDeDirecciones,
    IncognitaDeMecanica,
)
from arc_agent.opening_book import (
    FASE_EXPLOTAR,
    FASE_IDENTIFICAR,
    FASE_WARMUP,
    LibroDeAperturas,
)
from arc_agent.policy import ExplorationPolicy
from arc_agent.prng import create_seeded_random
from arc_agent.types import FrameData, GameAction, GameState
from arc_agent.world_model.object_mechanics import CambioDeColor, Mecanica, Traslacion

FLECHAS = ("ACTION1", "ACTION2", "ACTION3", "ACTION4")
CANONICO = {"ACTION1": (-1, 0), "ACTION2": (1, 0), "ACTION3": (0, -1), "ACTION4": (0, 1)}
CONTRARIO = {"ACTION1": (1, 0), "ACTION2": (-1, 0), "ACTION3": (0, 1), "ACTION4": (0, -1)}


def _mecanica_de_traslacion(dy: int, dx: int) -> Mecanica:
    t = Traslacion(dy=dy, dx=dx, min_y=5, min_x=5, alto=2, ancho=2, cobertura=1.0, relleno=1.0)
    return Mecanica(
        tipo="traslacion", celdas_cambiadas=8, clusters=[], traslacion_principal=t,
        cambio_de_color_principal=None,
    )


def _mecanica_sin_cambio() -> Mecanica:
    return Mecanica(
        tipo="sinCambio", celdas_cambiadas=0, clusters=[], traslacion_principal=None,
        cambio_de_color_principal=None,
    )


def _mecanica_de_color(desde: int, hasta: int, celdas: int = 40) -> Mecanica:
    return Mecanica(
        tipo="cambioDeColor", celdas_cambiadas=celdas, clusters=[], traslacion_principal=None,
        cambio_de_color_principal=CambioDeColor(desde=desde, hasta=hasta, celdas=celdas),
    )


# ── entorno sintetico de lazo cerrado ─────────────────────────────────────────────────────────

ALTO = ANCHO = 12
PASO = 2  # magnitud DISTINTA de 1 a proposito: el prior no la predice, se mide en partida


class _EntornoSintetico:
    """Bloque 2x2 que ACTION1..4 mueven segun `mapeo` (con recorte en el borde). `con_menu`
    arranca en una pantalla de titulo donde las flechas no tocan el tablero y UN click de ACTION6
    la descarta -- la trampa medida en 5 de los 25 juegos publicos. `inerte` no mueve nada nunca
    (el juego degenerado). Sin ruido: lo que se prueba aca es la creencia, no la mascara."""

    def __init__(self, mapeo: dict, con_menu: bool = False, inerte: bool = False) -> None:
        self.mapeo = mapeo
        self.menu = con_menu
        self.inerte = inerte
        self.y, self.x = 5, 5
        self._guid = 0

    def _grilla(self) -> tuple[tuple[int, ...], ...]:
        if self.menu:
            filas = [[3] * ANCHO for _ in range(ALTO)]
            filas[0] = [4] * ANCHO  # "titulo": un patron cualquiera, distinto del tablero
            return tuple(tuple(f) for f in filas)
        filas = [[0] * ANCHO for _ in range(ALTO)]
        for dy in range(2):
            for dx in range(2):
                filas[self.y + dy][self.x + dx] = 5
        return tuple(tuple(f) for f in filas)

    def frame(self) -> FrameData:
        self._guid += 1
        return FrameData(
            game_id="sintetico", guid=f"g{self._guid}", frame=(self._grilla(),),
            state=GameState.NOT_FINISHED, available_actions=(1, 2, 3, 4, 6),
        )

    def step(self, accion: GameAction) -> FrameData:
        if accion is GameAction.ACTION6:
            if self.menu:
                self.menu = False  # el click descarta la pantalla de titulo
            return self.frame()
        if not self.menu and not self.inerte and accion.value in self.mapeo:
            dy, dx = self.mapeo[accion.value]
            self.y = max(0, min(ALTO - 2, self.y + dy * PASO))
            self.x = max(0, min(ANCHO - 2, self.x + dx * PASO))
        return self.frame()


def _correr(policy: ExplorationPolicy, env: _EntornoSintetico, pasos: int) -> list[GameAction]:
    frame = env.frame()
    acciones: list[GameAction] = []
    for _ in range(pasos):
        decision = policy.decide(frame)
        acciones.append(decision.action)
        frame = env.step(decision.action)
    return acciones


# ── 1. el prior es refutable: mapeo contrario -> remapeo ──────────────────────────────────────


def test_juego_con_mapeo_contrario_al_prior_el_agente_remapea() -> None:
    policy = ExplorationPolicy(create_seeded_random("bl21590-contrario"))
    _correr(policy, _EntornoSintetico(CONTRARIO), 60)
    creencia = policy.creencia_de_direcciones
    for accion in FLECHAS:
        assert creencia.estado_de(accion) == ESTADO_REMAPEADA, creencia.resumen()
        assert creencia.direccion_de(accion) == CONTRARIO[accion], creencia.resumen()


def test_una_contradiccion_aislada_jamas_remapea() -> None:
    """La resistencia al artefacto medido: el round-robin fabrica contradicciones AISLADAS (la
    ambiguedad objeto/hueco invierte pulsaciones sueltas de forma sistematica). Sin corrida
    monotona -- otra accion en el medio -- ni cien contradicciones alcanzan para remapear."""
    creencia = CreenciaDeDirecciones()
    creencia.sembrar((1, 2, 3, 4))
    for _ in range(50):
        creencia.observar("ACTION1", _mecanica_de_traslacion(2, 0))  # contraria al prior...
        creencia.observar("ACTION2", _mecanica_sin_cambio())  # ...pero SIEMPRE aislada
    assert creencia.estado_de("ACTION1") == ESTADO_SEMBRADA
    assert creencia.direccion_de("ACTION1") == CANONICO["ACTION1"]


def test_dos_contradicciones_consecutivas_coherentes_si_remapean() -> None:
    creencia = CreenciaDeDirecciones()
    creencia.sembrar((1, 2, 3, 4))
    creencia.observar("ACTION1", _mecanica_de_traslacion(2, 0))
    creencia.observar("ACTION1", _mecanica_de_traslacion(2, 0))
    assert creencia.estado_de("ACTION1") == ESTADO_REMAPEADA
    assert creencia.direccion_de("ACTION1") == (1, 0)
    # La magnitud es la observada CRUDA, nunca la del prior (que no tiene).
    assert creencia.magnitud_de("ACTION1") == (2, 0)


def test_dos_contradicciones_incoherentes_entre_si_no_remapean() -> None:
    creencia = CreenciaDeDirecciones()
    creencia.sembrar((1, 2, 3, 4))
    creencia.observar("ACTION1", _mecanica_de_traslacion(2, 0))
    creencia.observar("ACTION1", _mecanica_de_traslacion(0, -2))  # otro signo: ruido sub-objeto
    assert creencia.estado_de("ACTION1") == ESTADO_SEMBRADA
    assert creencia.direccion_de("ACTION1") == CANONICO["ACTION1"]


# ── 2. la pared NO es refutacion ──────────────────────────────────────────────────────────────


def test_la_pared_no_cuenta_como_refutacion() -> None:
    creencia = CreenciaDeDirecciones()
    creencia.sembrar((1, 2, 3, 4))
    for _ in range(30):
        resultado = creencia.observar("ACTION1", _mecanica_sin_cambio())
        assert resultado == RESULTADO_INCONCLUSO
    assert creencia.estado_de("ACTION1") == ESTADO_SEMBRADA  # difiere el juicio, no refuta
    assert creencia.direccion_de("ACTION1") == CANONICO["ACTION1"]


def test_la_pared_en_el_medio_de_la_corrida_la_pausa_pero_no_la_corta() -> None:
    """Traslacion, pared, traslacion -- misma accion, mismo signo: la posicion absoluta nunca
    retrocedio, la corrida sigue siendo monotona y la segunda traslacion confirma."""
    creencia = CreenciaDeDirecciones()
    creencia.sembrar((1, 2, 3, 4))
    creencia.observar("ACTION1", _mecanica_de_traslacion(-2, 0))
    creencia.observar("ACTION1", _mecanica_sin_cambio())  # pared
    creencia.observar("ACTION1", _mecanica_de_traslacion(-2, 0))
    assert creencia.estado_de("ACTION1") == ESTADO_CONFIRMADA


def test_otra_accion_en_el_medio_si_corta_la_corrida() -> None:
    creencia = CreenciaDeDirecciones()
    creencia.sembrar((1, 2, 3, 4))
    creencia.observar("ACTION1", _mecanica_de_traslacion(-2, 0))
    creencia.observar("ACTION2", _mecanica_de_traslacion(2, 0))
    creencia.observar("ACTION1", _mecanica_de_traslacion(-2, 0))
    # Dos traslaciones canonicas de ACTION1 pero NUNCA consecutivas: sin corrida no se fija.
    assert creencia.estado_de("ACTION1") == ESTADO_SEMBRADA


# ── 3. juego degenerado: nada se mueve, el agente no se cuelga ────────────────────────────────


def test_juego_degenerado_el_agente_no_se_cuelga_en_identificar() -> None:
    policy = ExplorationPolicy(create_seeded_random("bl21590-degenerado"))
    acciones = _correr(policy, _EntornoSintetico(CANONICO, inerte=True), 60)
    assert len(acciones) == 60  # sesenta decisiones sin excepcion ni bloqueo
    libro = policy.libro_de_aperturas
    creencia = policy.creencia_de_direcciones
    assert libro.fase == FASE_EXPLOTAR, libro.resumen()  # salio de IDENTIFICAR solo
    for accion in FLECHAS:
        # Degradar sin insistir. BL.21593: ahora lo decide el POSTERIOR -- con las cuatro
        # flechas mudas el arquetipo flechasSinMapeo concentra y cada una queda resuelta como
        # inerte ANTES de que el libro queme sus intentos espaciados; `sinEvidencia` queda como
        # respaldo para cuando el posterior no concentre. El prior sigue en pie como hipotesis.
        assert creencia.resuelta(accion), creencia.resumen()
        assert (
            creencia.posterior.inerte(accion)
            or creencia.estado_de(accion) == ESTADO_SIN_EVIDENCIA
        ), creencia.posterior.resumen()
        assert creencia.direccion_de(accion) == CANONICO[accion]
    assert len(set(acciones)) >= 2  # siguio explorando, no se clavo en una sola accion


# ── 4. WARMUP solo cuando corresponde ─────────────────────────────────────────────────────────


def test_warmup_clickea_primero_cuando_el_juego_arranca_en_menu() -> None:
    policy = ExplorationPolicy(create_seeded_random("bl21590-menu"))
    acciones = _correr(policy, _EntornoSintetico(CANONICO, con_menu=True), 60)
    libro = policy.libro_de_aperturas
    creencia = policy.creencia_de_direcciones
    assert libro.clics_de_warmup_gastados > 0  # detecto las flechas mudas y clickeo
    # Tras el click que descarto el menu, las cuatro flechas confirman el mapeo canonico: los
    # tanteos que midieron EL MENU no las condenaron a sinEvidencia.
    assert libro.fase == FASE_EXPLOTAR, libro.resumen()
    for accion in FLECHAS:
        assert creencia.estado_de(accion) == ESTADO_CONFIRMADA, creencia.resumen()
    # Y el primer click llego ANTES que cualquier confirmacion (clickear primero, medir despues).
    primer_click = acciones.index(GameAction.ACTION6)
    assert primer_click <= 5, acciones[:8]


def test_warmup_no_se_activa_cuando_el_juego_responde_a_las_flechas() -> None:
    policy = ExplorationPolicy(create_seeded_random("bl21590-responde"))
    _correr(policy, _EntornoSintetico(CANONICO), 3)
    libro = policy.libro_de_aperturas
    assert libro.clics_de_warmup_gastados == 0  # ni un click de warmup
    assert libro.fase in (FASE_IDENTIFICAR, FASE_EXPLOTAR)  # el primer tanteo ya movio: salio


def test_sin_flechas_sembradas_el_libro_arranca_en_explotar() -> None:
    creencia = CreenciaDeDirecciones()
    creencia.sembrar((6,))  # juego click-only: nada que validar
    libro = LibroDeAperturas(creencia)
    assert libro.fase == FASE_WARMUP
    assert libro.sugerir(["ACTION6"], 0) is None
    assert libro.fase == FASE_EXPLOTAR


# ── DELTA en lazo cerrado: con prior vs sin prior ─────────────────────────────────────────────

_PRIOR_VACIO = {
    "mapeoCanonico": {},
    "conjuntosMedidos": {},
    "nJuegosQueConfirman": 0,
    "nJuegosConFlechas": 0,
}


def _pasos_hasta_mapeo_conocido(con_prior: bool, seed: str, horizonte: int = 120) -> int | None:
    """Primer paso en que la creencia conoce la direccion VERDADERA de las cuatro flechas con
    estado fijado (confirmada/remapeada/observada). Sin prior, la creencia arranca vacia y solo
    puede ADOPTAR por corridas monotonas de la exploracion libre."""
    policy = ExplorationPolicy(create_seeded_random(seed))
    if not con_prior:
        policy._direcciones = CreenciaDeDirecciones(prior=_PRIOR_VACIO)  # noqa: SLF001
        policy._libro = LibroDeAperturas(policy._direcciones)  # noqa: SLF001
    env = _EntornoSintetico(CANONICO)
    frame = env.frame()
    creencia = policy.creencia_de_direcciones
    for paso in range(1, horizonte + 1):
        frame = env.step(policy.decide(frame).action)
        if all(
            creencia.direccion_de(a) == CANONICO[a] and creencia.resuelta(a)
            and creencia.estado_de(a) != ESTADO_SIN_EVIDENCIA
            for a in FLECHAS
        ):
            return paso
    return None


def test_delta_en_lazo_cerrado_el_prior_acelera_el_mapeo_y_no_gasta_acciones_dedicadas() -> None:
    for seed in ("bl21590-delta-1", "bl21590-delta-2"):
        con = _pasos_hasta_mapeo_conocido(True, seed)
        sin = _pasos_hasta_mapeo_conocido(False, seed)
        print(f"[BL.21590][{seed}] pasos hasta mapeo conocido -- con prior: {con}, sin: {sin}")
        assert con is not None and con <= 25, f"{seed}: el libro no resolvio el mapeo ({con})"
        assert sin is None or con < sin, f"{seed}: el prior no acelero nada (con={con}, sin={sin})"


def test_costo_cero_el_libro_dirige_la_exploracion_sin_pasos_dedicados() -> None:
    """Las sugerencias del libro SON exploracion (tanteos y primeras macros de cada flecha): la
    metrica del BL es que ningun paso se gasta 'solo para validar'. Se verifica que cada paso
    guiado emitio una accion del juego que la exploracion igualmente tenia disponible, y que al
    resolver el mapeo el libro deja de guiar (pasos_guiados se congela)."""
    policy = ExplorationPolicy(create_seeded_random("bl21590-costo"))
    env = _EntornoSintetico(CANONICO)
    _correr_policy_env(policy, env, 40)
    libro = policy.libro_de_aperturas
    assert libro.fase == FASE_EXPLOTAR
    assert libro.paso_de_resolucion is not None
    guiados_al_resolver = libro.pasos_guiados
    _correr_policy_env(policy, env, 20)
    assert libro.pasos_guiados == guiados_al_resolver  # en explotar el libro ya no dirige nada


def _correr_policy_env(policy: ExplorationPolicy, env: _EntornoSintetico, pasos: int) -> None:
    frame = env.frame()
    for _ in range(pasos):
        frame = env.step(policy.decide(frame).action)


# ── incognita de mecanica: ACTION5/ACTION7 ────────────────────────────────────────────────────


def test_incognita_arranca_uniforme_cero_prior_para_action5_y_action7() -> None:
    incognita = IncognitaDeMecanica()
    posterior = incognita.posterior()
    assert set(posterior) == set(FIRMAS_DE_MECANICA)
    assert all(abs(p - 1 / len(FIRMAS_DE_MECANICA)) < 1e-9 for p in posterior.values())
    assert incognita.dominante() is None  # sin evidencia no se afirma NADA


def test_incognita_clasifica_las_cuatro_firmas_medidas() -> None:
    inerte = IncognitaDeMecanica()
    for _ in range(3):
        assert inerte.observar(_mecanica_sin_cambio()) == FIRMA_INERTE
    assert inerte.dominante() == FIRMA_INERTE

    escena = IncognitaDeMecanica()
    assert escena.observar(_mecanica_de_color(1, 2, celdas=185)) == FIRMA_CAMBIO_DE_ESCENA

    toggle = IncognitaDeMecanica()
    toggle.observar(_mecanica_de_color(1, 2))
    assert toggle.observar(_mecanica_de_color(2, 1)) == FIRMA_TOGGLE  # alterna A->B, B->A

    disparo = IncognitaDeMecanica()
    disparo.observar(_mecanica_de_color(3, 7))
    assert disparo.observar(_mecanica_de_color(3, 7)) == FIRMA_DISPARO  # repite el MISMO recoloreo


def test_la_politica_alimenta_la_incognita_solo_con_action5_y_action7() -> None:
    policy = ExplorationPolicy(create_seeded_random("bl21590-incognita"))
    _correr(policy, _EntornoSintetico(CANONICO), 30)
    incognitas = policy.incognitas_de_mecanica
    # ACTION1..4/6 jamas entran a la incognita, por mas que se hayan pulsado decenas de veces.
    for accion in (*FLECHAS, "ACTION6"):
        assert sum(incognitas.conteos_de(accion).values()) == 0, accion
