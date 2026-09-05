"""[arc-agi3-kaggle-agent/estado_congelado] BL.21702 -- DETECTOR DE ESTADO CONGELADO y disparador
del unico RESET VOLUNTARIO que la medicion justifica.

EL RESET VOLUNTARIO ESTA REFUTADO COMO PALANCA GENERAL, y esa es la parte importante de este
modulo. Medido en los entornos reales (151 acciones por juego, semilla bl21702a), el RESET
INVOLUNTARIO -- el que dispara el contrato ante GAME_OVER -- ya ocurre solo y no destraba nada:
sp80 6 por partida, su15 4, tn36 2, tu93 2, lf52 2, dc22 1, sb26 1, y los siete siguen en CERO
niveles. sp80 en particular recibe seis reinicios gratis por partida. Donde el juego ya se reinicia
solo, un RESET mas no puede ser la diferencia.

DONDE SI TIENE SENTIDO, y solo ahi: cuando el tablero esta CONGELADO y no hay game-over que
rescate. Eso se midio en exactamente dos de los siete -- lf52 (47 revisitas con gap=1, o sea frame
IDENTICO entre pasos consecutivos, y solo 2 game-over en 151 pasos) y dc22 (54 con gap=1). En los
otros cinco las revisitas son ciclos LARGOS de periodo FIJO (tn36 62, tu93 51, sb26 ~73, su15 ~35):
animaciones del juego, no congelamiento, y ahi el frame SI cambia paso a paso.

POR ESO EL DISPARADOR PIDE EVIDENCIA Y NO CORAZONADA. El RESET cuesta una accion y puede perder
progreso real del nivel, asi que las cinco condiciones se exigen JUNTAS:

  1. VENTANA LLENA de `VENTANA_DE_CONGELAMIENTO` pasos, con al menos `PASOS_SIN_CAMBIO_PARA_RESET`
     de ellos SIN cambio enmascarado. Ventana y no racha estricta: en dato real el congelamiento
     viene salpicado por algun frame que si se mueve, y una racha consecutiva no lo veria nunca.
  2. Se probaron al menos `ACCIONES_DISTINTAS_MINIMAS` acciones distintas en esa ventana (o todas
     las que el juego ofrece, si ofrece menos). Sin esto, un unico boton inerte repetido bastaria
     para reiniciar, y eso es "no supe que probar", no "el juego esta trabado".
  3. Si el juego ofrece ACTION6, se clickearon al menos `COORDENADAS_DISTINTAS_MINIMAS` celdas
     DISTINTAS en la ventana. En un juego de click la pregunta es DONDE, y reiniciar por no haber
     encontrado la celda seria reiniciar por no haber explorado.
  4. Quedan RESETs del presupuesto (`RESETS_VOLUNTARIOS_MAX`) y paso la espera desde el ultimo
     (`PASOS_ENTRE_RESETS_VOLUNTARIOS`). Un reset que no destraba no debe volverse un tic.
  5. No hubo progreso de nivel en los ultimos `PASOS_DE_GRACIA_TRAS_PROGRESO` pasos. Si el agente
     acaba de subir de nivel, lo que hay delante es un nivel nuevo, no un bucle -- y ahi el reset
     tira justo lo que se acaba de ganar. Esta es la condicion que protege el caso caro.

Apagable entero con la palanca `resetPorCongelamiento` (ver banderas.py): con ella apagada
`debe_resetear` devuelve False siempre y el agente se comporta exactamente como antes de BL.21702.
"""
from __future__ import annotations

from typing import Final, Iterable

from .banderas import RESET_POR_CONGELAMIENTO, Banderas, bandera_activa
# FUENTE UNICA del nombre del boton de click: lo define `opening_book.py` y aca se reusa en vez
# de re-declararlo (dos definiciones del mismo literal serian dos verdades que pueden divergir).
from .opening_book import ACCION_DE_CLICK

#: Pasos de la ventana deslizante sobre la que se juzga el congelamiento.
VENTANA_DE_CONGELAMIENTO: Final[int] = 24

#: Pasos SIN cambio enmascarado dentro de la ventana para considerar el tablero congelado. 18 de 24
#: = 75%: tolera la animacion intermitente que el dato real muestra sin aceptar un tablero que
#: responde tres de cada cuatro pasos.
PASOS_SIN_CAMBIO_PARA_RESET: Final[int] = 18

#: Acciones distintas que hay que haber probado en la ventana (o todas las disponibles si son
#: menos). Distingue "el juego esta trabado" de "todavia no probe nada".
ACCIONES_DISTINTAS_MINIMAS: Final[int] = 2

#: Coordenadas distintas que hay que haber clickeado en la ventana cuando el juego ofrece ACTION6.
#: En un juego de click la decision es DONDE: reiniciar antes de haber barrido nada seria confundir
#: falta de exploracion con bloqueo.
COORDENADAS_DISTINTAS_MINIMAS: Final[int] = 8

#: Tope de RESETs voluntarios por episodio. Bajo a proposito: cada uno cuesta una accion y puede
#: perder progreso, y la evidencia dice que reiniciar no es lo que destraba (ver el encabezado).
RESETS_VOLUNTARIOS_MAX: Final[int] = 3

#: Pasos minimos entre dos RESETs voluntarios: dos ventanas completas. Si el primero no destrabo,
#: hay que darle al agente el tiempo de medir de nuevo antes de volver a gastar la accion.
PASOS_ENTRE_RESETS_VOLUNTARIOS: Final[int] = 2 * VENTANA_DE_CONGELAMIENTO

#: Pasos de gracia tras una subida de nivel. Es la condicion que protege el progreso real: recien
#: superado un nivel, lo que hay delante es un tablero nuevo que todavia no se entiende.
PASOS_DE_GRACIA_TRAS_PROGRESO: Final[int] = 60



class DetectorDeCongelamiento:
    """Ventana deslizante de evidencia de congelamiento. UNA instancia por partida.

    Contrato con la politica: `observar()` una vez por decision, con lo que se sabe de la
    transicion ANTERIOR; `debe_resetear()` justo antes de elegir accion; `registrar_reset()` cuando
    la politica efectivamente emite el RESET voluntario."""

    __slots__ = (
        "_activo",
        "_ventana",
        "_sin_cambio",
        "_acciones",
        "_coordenadas",
        "_resets",
        "_paso_del_ultimo_reset",
        "_paso_del_ultimo_progreso",
    )

    def __init__(self, banderas: Banderas | None = None) -> None:
        self._activo = bandera_activa(RESET_POR_CONGELAMIENTO, banderas)
        # Ventana como lista de tuplas (hubo_cambio, accion, coordenada). Acotada a
        # VENTANA_DE_CONGELAMIENTO elementos: los conteos se recalculan sobre ella, que es barato
        # con 24 entradas y evita el error clasico de contadores incrementales que se desincronizan
        # del contenido de la ventana.
        self._ventana: list[tuple[bool, str | None, tuple[int, int] | None]] = []
        self._sin_cambio = 0
        self._acciones: set[str] = set()
        self._coordenadas: set[tuple[int, int]] = set()
        self._resets = 0
        self._paso_del_ultimo_reset: int | None = None
        self._paso_del_ultimo_progreso: int | None = None

    @property
    def activo(self) -> bool:
        """Si la palanca `resetPorCongelamiento` esta encendida en esta partida."""
        return self._activo

    @property
    def resets_voluntarios(self) -> int:
        """RESETs voluntarios emitidos en el episodio -- la metrica de la palanca."""
        return self._resets

    @property
    def pasos_sin_cambio_en_ventana(self) -> int:
        return self._sin_cambio

    @property
    def coordenadas_en_ventana(self) -> int:
        return len(self._coordenadas)

    def observar(
        self,
        hubo_cambio: bool,
        accion: str | None,
        coordenada: tuple[int, int] | None,
        subio_de_nivel: bool,
        paso: int,
    ) -> None:
        """Registra la transicion ANTERIOR. `accion`/`coordenada` son las que la produjeron
        (None en el primer paso del episodio o tras un RESET, donde no hay transicion atribuible).

        Una subida de nivel arma el periodo de gracia: es la unica evidencia dura de que el agente
        NO esta en un bucle, y es tambien lo que un RESET podria tirar a la basura."""
        if subio_de_nivel:
            self._paso_del_ultimo_progreso = paso
        self._ventana.append((hubo_cambio, accion, coordenada))
        if len(self._ventana) > VENTANA_DE_CONGELAMIENTO:
            self._ventana.pop(0)
        self._recontar()

    def _recontar(self) -> None:
        self._sin_cambio = sum(1 for cambio, _, _ in self._ventana if not cambio)
        self._acciones = {a for _, a, _ in self._ventana if a is not None}
        self._coordenadas = {c for _, _, c in self._ventana if c is not None}

    def debe_resetear(self, paso: int, acciones_disponibles: Iterable[str]) -> bool:
        """Las cinco condiciones del encabezado, evaluadas juntas. Cualquiera que falte devuelve
        False: el RESET voluntario es la excepcion, nunca el reflejo."""
        if not self._activo:
            return False
        if len(self._ventana) < VENTANA_DE_CONGELAMIENTO:
            return False
        if self._sin_cambio < PASOS_SIN_CAMBIO_PARA_RESET:
            return False
        disponibles = tuple(acciones_disponibles)
        if not disponibles:
            return False
        if len(self._acciones) < min(ACCIONES_DISTINTAS_MINIMAS, len(disponibles)):
            return False
        if ACCION_DE_CLICK in disponibles and len(self._coordenadas) < COORDENADAS_DISTINTAS_MINIMAS:
            return False
        if self._resets >= RESETS_VOLUNTARIOS_MAX:
            return False
        if (
            self._paso_del_ultimo_reset is not None
            and paso - self._paso_del_ultimo_reset < PASOS_ENTRE_RESETS_VOLUNTARIOS
        ):
            return False
        if (
            self._paso_del_ultimo_progreso is not None
            and paso - self._paso_del_ultimo_progreso < PASOS_DE_GRACIA_TRAS_PROGRESO
        ):
            return False
        return True

    def decidir_reset(self, paso: int, acciones_disponibles: Iterable[str]) -> str | None:
        """Punto de entrada de la POLITICA: devuelve el motivo legible del RESET voluntario y lo
        contabiliza, o None si no corresponde reiniciar.

        Junta la decision y su registro a proposito. Separarlos deja abierta la unica forma de
        romper este detector desde afuera -- preguntar y no registrar, o registrar sin preguntar --
        y el segundo caso es el que convierte el reset en un tic: la ventana no se vaciaria y el
        siguiente paso volveria a dispararlo con la evidencia del tablero ANTERIOR al reinicio."""
        if not self.debe_resetear(paso, acciones_disponibles):
            return None
        self.registrar_reset(paso)
        return (
            "RESET voluntario: el tablero esta congelado y no hay game-over que rescate -- "
            f"{self.resumen()}"
        )

    def registrar_reset(self, paso: int) -> None:
        """La politica emitio el RESET voluntario. La ventana se VACIA: lo que viene despues es
        otro episodio de tablero y juzgarlo con evidencia previa al reinicio dispararia el segundo
        reset en el paso siguiente."""
        self._resets += 1
        self._paso_del_ultimo_reset = paso
        self._ventana.clear()
        self._recontar()

    def resumen(self) -> str:
        """Linea legible para el `reasoning` persistido."""
        return (
            f"congelamiento={self._sin_cambio}/{len(self._ventana)} "
            f"acciones={len(self._acciones)} coordenadas={len(self._coordenadas)} "
            f"resetsVoluntarios={self._resets}"
        )
