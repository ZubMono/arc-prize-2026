"""[arc-agi3-kaggle-agent/policy] BL.20783 -- politica de decision 100% local: SIN red, SIN
llamadas a APIs de LLM en inferencia (restriccion dura del notebook Kaggle). Exploracion con
memoria de estados visitados (evita reintentar acciones que no cambiaron el frame desde el MISMO
estado -- deteccion de loops/dead-ends, "menos visitado primero" al estilo bandit) + deteccion de
bordes de color para elegir el punto de click de ACTION6 (heuristica de vision simple: una celda
en el borde de una region de color distinto es mas "interesante" que una celda interior uniforme).
Determinista dado un `rng` semillado -- mismo principio de reproducibilidad que baselineAgent.ts
en BL.20775, con una politica mas informada que la eleccion puramente uniforme del MVP."""
from __future__ import annotations

from typing import Callable

from .types import ActionDecision, FrameData, GameAction, GameState
# BL.21702 -- las cuatro palancas de exploracion y el RESET voluntario, cada una apagable de a una
# para poder medirla por separado. Ver banderas.py: el gate corre la MISMA build con una palanca
# menos y le atribuye el delta a esa y a ninguna otra.
from .banderas import MASCARA_DE_ACCION_UNICA, MEMORIA_DE_MUERTES, Banderas, bandera_activa
from .estado_congelado import DetectorDeCongelamiento
# Import a UN solo nivel (`.world_model`, no `.world_model.transition_memory`): el builder del
# notebook desmonta los imports relativos con el regex `^from \.\w* import .+$`, que no cubre un
# segundo punto -- con la forma anidada el notebook de submission queda con un ImportError.
from .exploration_memory import MACRO_MAX_STEPS, MacroCommitment, StateNoveltyTracker
# BL.21560 -- `rank_candidates` y los dos epsilon se mudaron a exploration_memory.py (son memoria de
# exploracion, no politica de decision) para dejarle sitio a la eleccion de coordenada. BL.21590
# mudo tambien la firma de estado, la entrada de memoria por estado y sus dos umbrales, por el mismo
# motivo y para dejarle sitio a la creencia de direcciones. Se re-exportan: superficie publica de
# este modulo desde BL.20783 y los tests los importan de aca.
from .exploration_memory import LEVEL_REWARD_PRIORITY_USES, NO_OP_CONFIRMATIONS  # noqa: F401
from .exploration_memory import EntradaDeExploracion, compute_signature
from .exploration_memory import NOOP_REEXPLORATION_EPSILON  # noqa: F401
from .exploration_memory import RECONSIDERATION_PER_STEP_EPSILON, rank_candidates
from .exploration_memory import hubo_cambio_enmascarado
# BL.21767 -- la muerte como HECHO del modelo de mundo: donde se anota la transicion a GAME_OVER
# (firma previa, accion, click, macro en curso) y el descuento agotable que la consume.
from .exploration_memory import CASTIGO_POR_MUERTE_USOS, MemoriaDeMuertes  # noqa: F401
from .click_targeting import ClickMemory, pick_click_target, region_que_cambio  # noqa: F401
# BL.21590 -- prior de direcciones sembrado por conjunto de acciones disponibles y validado en
# partida DENTRO de las macros, con tres resultados por boton; ACTION5/ACTION7 entran como
# incognita uniforme sobre firmas de mecanica. Ver direction_beliefs.py y opening_book.py.
from .direction_beliefs import CreenciaDeDirecciones, IncognitasDeMecanica
from .opening_book import FASE_WARMUP, LibroDeAperturas, motivo_de_apertura  # noqa: F401
# BL.21593 -- percepcion de pared: el termino observable de la verosimilitud del fallo. El avatar
# es el ultimo objeto trasladado y el piso, el color que deja al moverse; con ambos, un fallo de
# flecha se descompone en P(pared|grilla) + P(mapeo equivocado) + P(desconocido).
from .wall_perception import RastreadorDeAvatar, contexto_de_pared, profundidad_de_sondeo
from .world_model import Mecanica, TransitionMemory, VolatilityMask, grids_equal_masked
# BL.22236 -- capas de animacion intermedias de `frame.frame` (evidencia adicional de transicion,
# ver `_feed_capas_intermedias`).
from .world_model import extraer_grid_multicapa
# BL.21704 -- almacen de relaciones causales A DISTANCIA (boton que abre puerta) y su confirmacion
# INTERVENCIONAL. Es un almacen APARTE del vocabulario de `mechanics_posterior.MECANICAS`, que es el
# mapeo boton->direccion: una relacion no local no es una direccion y no hay lugar semantico donde
# meterla (medido en la etapa 1 de BL.21704).
from .world_model import MAX_EXPLOTACIONES_DE_SUBMETA, PASOS_SIN_CAMBIO_PARA_SUBMETA
from .world_model import AlmacenDeRelaciones, SubMeta


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
