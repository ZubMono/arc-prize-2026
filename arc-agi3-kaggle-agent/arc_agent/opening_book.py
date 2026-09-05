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
from __future__ import annotations

from typing import Final, Iterable

from .banderas import WARMUP_DE_CLICKS_SEGUIDOS, Banderas, bandera_activa
from .direction_beliefs import RESULTADO_INCONCLUSO, CreenciaDeDirecciones

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
