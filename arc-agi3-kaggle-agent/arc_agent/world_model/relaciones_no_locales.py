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
from __future__ import annotations

import math
from typing import Final, Sequence

# Imports relativos en UNA sola linea a proposito: submission/build_agent.py los desmonta con el
# regex `^from \.\w* import .+$` y la forma con parentesis dejaria un `)` colgando en el entregable.
from .grid import Grid, VolatilityMask
from .object_mechanics import Mecanica
from .regiones_de_cambio import HistorialDeCambios, RegionDeCambio
from .regiones_de_cambio import componentes_por_paso, particionar_pares
from .estadistica_de_coocurrencia import ALFA_BH, DIRECCIONES_POR_PAR, MIN_SOPORTE  # noqa: F401
from .estadistica_de_coocurrencia import coocurrencias, cola_binomial, indice_de_corte_bh
from .estadistica_de_coocurrencia import umbral_del_nulo_empirico
from .evidencia_relacional import CONFIRMACIONES_REQUERIDAS, INTENTOS_DE_CONFIRMACION  # noqa: F401
from .evidencia_relacional import PISO_DE_EVIDENCIA_PARA_SUBMETA, ClaveDeRelacion
from .evidencia_relacional import MIN_PASOS_DE_CONTROL, TASA_BASE_MAXIMA  # noqa: F401
from .evidencia_relacional import Candidato, RelacionNoLocal, SubMeta, clave_de_relacion

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
