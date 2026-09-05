"""[arc-agi3-kaggle-agent/banderas] BL.21702 -- REGISTRO UNICO de las palancas de exploracion,
cada una con su interruptor propio para poder medirla POR SEPARADO.

POR QUE EXISTE. BL.21594 metio tres mecanismos elegantes en un solo commit, los midio juntos y el
neto fue ruido alrededor de cero: no habia forma de saber cual pagaba y cual restaba, porque el
gate era un si/no sobre el paquete entero. Este modulo evita repetir eso. Cada palanca de BL.21702
entra APAGABLE de a una, asi que `gate_de_merge.py` puede correr la misma build con una palanca
menos y atribuirle el delta a esa palanca y a ninguna otra.

COMO SE CONFIGURA (variable de entorno, leida UNA vez al importar):

    ARC_AGENT_BANDERAS=ninguna                        # linea base: todas apagadas
    ARC_AGENT_BANDERAS=todas                          # el candidato completo
    ARC_AGENT_BANDERAS=todas,-macroCambioInformativo  # todas menos esa (leave-one-out)
    ARC_AGENT_BANDERAS=ninguna,+mascaraDeAccionUnica  # solo esa

Gramatica: tokens separados por coma. `ninguna` / `todas` / `entregadas` fijan la base (por defecto
`entregadas`); `-nombre` apaga, `nombre` o `+nombre` enciende. Un nombre desconocido es un ERROR
ruidoso y no un silencio: una bandera mal escrita en un barrido de medicion produciria una linea
base falsa, que es justo el desenlace que este modulo existe para evitar.

QUE SE ENTREGA LO DECIDE EL GATE, NO LA INTENCION. En Kaggle no hay variable, asi que rige
`BANDERAS_POR_DEFECTO`, y ahi solo entran las palancas que SUBIERON los niveles totales contra el
harness real. Ver el comentario de esa constante para la medicion vigente.

SIN DEPENDENCIAS: stdlib pura, sin imports relativos. Va primero en `MODULE_ORDER` junto con el
reloj, y `world_model/` NO lo importa a proposito: desde un subpaquete haria falta un import
relativo de DOS puntos, y el builder del notebook solo desmonta la forma de UN punto. Lo que
world_model necesita entra por parametro explicito desde `policy.py`."""
from __future__ import annotations

import os
from typing import Final, Iterable

#: Variable de entorno que configura las palancas. Ausente = todas encendidas.
NOMBRE_DE_VARIABLE: Final[str] = "ARC_AGENT_BANDERAS"

#: MEMORIA DE COORDENADAS TRANSVERSAL AL ESTADO. `ClickMemory._probadas` se indexa por
#: (firma, x, y), asi que cada firma nueva vacia la cobertura y el ranker vuelve a la misma celda
#: de mayor puntaje. Medido en entorno real, 151 acciones: tn36 9 coordenadas distintas en 149
#: clicks, su15 5 en 138, dc22 5 en 8, sb26 13 en 16 -- del orden del 0,2% de las 4.096 celdas.
#: Alcance: los cuatro juegos de click de los siete atascados, y cualquier juego de click.
MEMORIA_TRANSVERSAL_DE_CLICKS: Final[str] = "memoriaTransversalDeClicks"

#: MASCARA DE VOLATILIDAD CONSTRUIBLE CON UNA SOLA ACCION. `volatility_mask.py` corta las dos
#: familias con `< VOLATILITY_MIN_DISTINCT_ACTIONS` (=2) y SEIS de los 25 juegos publicos exponen
#: `availableActions=[6]` (ft09, lp85, r11l, s5i5, tn36, vc33): ahi la mascara es imposible POR
#: CONSTRUCCION y toda la memoria por estado del agente queda inerte. Cuatro de esos seis YA
#: puntuan, asi que la palanca tiene upside fuera de los siete atascados.
MASCARA_DE_ACCION_UNICA: Final[str] = "mascaraDeAccionUnica"

#: CORTE DE LA AMPLIFICACION DE MACROCOMMITMENT. `continuar()` solo corta con `hubo_cambio=False`,
#: asi que una accion cosmetica siempre-cambiante se lleva hasta x8 el presupuesto de una que
#: no-opea (sb26: ACTION5 82,8% de 151 acciones). Con la palanca la macro exige que el cambio sea
#: INFORMATIVO -- que el estado al que llega no sea uno ya visitado en el episodio.
MACRO_CAMBIO_INFORMATIVO: Final[str] = "macroCambioInformativo"

#: WARMUP DEL LIBRO DE APERTURAS CON LOS CLICKS SEGUIDOS. `_registrar_warmup` limpia `_tanteadas` e
#: `_intentos` en cuanto un click cambia el tablero, y la pantalla de titulo ANIMA: `hubo_cambio`
#: es SIEMPRE True, el libro vuelve a tantear las cuatro flechas entre click y click y el
#: presupuesto de 9 clicks nunca se gasta. Medido en dc22: 8 ACTION6 en 151 acciones.
WARMUP_DE_CLICKS_SEGUIDOS: Final[str] = "warmupDeClicksSeguidos"

#: RESET VOLUNTARIO ANTE ESTADO CONGELADO. SOLO para el caso medido en lf52 y dc22 (47 y 54
#: revisitas con gap=1: frame identico entre pasos consecutivos, sin game-over que rescate). En el
#: resto esta REFUTADO por medicion: el RESET involuntario ya se dispara solo (sp80 6 por partida,
#: su15 4, tn36 2, tu93 2) y los siete siguen en 0 niveles. El disparador exige evidencia de
#: congelamiento, no "me parece que estoy en un bucle" -- ver `policy.py`.
RESET_POR_CONGELAMIENTO: Final[str] = "resetPorCongelamiento"

#: CASTIGO EN EL RANKING A LA ACCION QUE MATO DESDE ESE ESTADO (BL.21767). Hasta ese BL el
#: GAME_OVER ni siquiera llegaba a la politica: `kaggle_adapter` lo presentaba como NOT_STARTED,
#: asi que el evento mas informativo de la partida se procesaba como el arranque y el agente no
#: tenia DONDE anotar la muerte (sp80: 6 GAME_OVERs en 151 acciones y 0 niveles, BL.21702; g50t:
#: 15 en 1.750, BL.21763). El REGISTRO del hecho es incondicional (`MemoriaDeMuertes`, pura
#: observacion); esta palanca enciende su CONSUMO: relegar al fondo del ranking, con descuento que
#: se agota, la accion que produjo un GAME_OVER desde esa misma firma. La localidad que lo
#: justifica esta MEDIDA en `mediciones/BL21767_muertes_por_juego.json`, no asumida.
MEMORIA_DE_MUERTES: Final[str] = "memoriaDeMuertes"

#: Todas las palancas (BL.21702 + BL.21767), en el orden en que conviene medirlas (radio de
#: impacto medido decreciente). Fuente unica: el parser y los tests leen de aca.
BANDERAS_CONOCIDAS: Final[tuple[str, ...]] = (
    MEMORIA_TRANSVERSAL_DE_CLICKS,
    MASCARA_DE_ACCION_UNICA,
    MACRO_CAMBIO_INFORMATIVO,
    WARMUP_DE_CLICKS_SEGUIDOS,
    RESET_POR_CONGELAMIENTO,
    MEMORIA_DE_MUERTES,
)

#: Palancas que el ENTREGABLE lleva encendidas: las que el gate de merge APROBO contra el harness
#: real. Fuente unica de "que se entrega"; `BANDERAS_CONOCIDAS` es "que existe", que no es lo mismo.
#: El valor lo fija la MEDICION, no la intencion de quien escribio la palanca.
#:
#: LA MEDICION DE BL.21702 (harness real, 25 juegos, 200 pasos, semillas gate-1/2/3):
#:
#:   ninguna (linea base)  12 niveles      todas (candidato completo)  12 niveles   -> delta +0
#:
#: El paquete completo EMPATA, y el gate del BL dice que un empate no se mergea. Pero empatar no es
#: no pasar nada: por juego, `todas` DESBLOQUEO ar25 (0,0,0 -> 1,0,1) y PERDIO uno en ft09 y uno en
#: vc33. Ahi entra el barrido leave-one-out (`scripts/ablacion_de_palancas.py`, 3 semillas sobre los
#: tres juegos que se movieron -- los demas dieron el mismo numero en las dos puntas y no pueden
#: discriminar), que separa las dos mitades:
#:
#:   aporte = todas - (todas menos esa)      memoriaTransversalDeClicks   -2
#:                                           macroCambioInformativo       +2
#:                                           mascaraDeAccionUnica         +0
#:                                           warmupDeClicksSeguidos       +0
#:                                           resetPorCongelamiento        +0
#:
#: O sea: el neto de ruido alrededor de cero que BL.21594 nunca pudo explicar es, aca, DOS EFECTOS
#: REALES DE SIGNO OPUESTO que se cancelan. La memoria transversal de clicks RESTA dos niveles pese
#: a ganar cobertura -- en ft09 y vc33 la celda productiva ya estaba identificada y repartir clicks
#: la abandona -- y el corte de la macro SUMA dos. Sin la bandera de cada una esto era invisible.
#:
#: BL.21939 / EXP-12 (2026-08-21) -- `macroCambioInformativo` SE ENTREGA. La ablacion ORDENA pero no
#: aprueba, asi que se midio en el GATE (25 juegos x 200 pasos x 3 semillas, el mismo instrumento
#: que produjo la linea base):
#:
#:   ninguna                       12 niveles, 4 juegos con nivel
#:   ninguna,+macroCambioInformativo  14 niveles, 5 juegos con nivel   -> delta +2
#:
#: Las 15075 acciones son IDENTICAS en las dos puntas, y toda la diferencia esta en UN juego: ar25
#: pasa de 0 a 2 (gate-1 y gate-3, +1 cada una); los otros 24 dan exactamente el mismo numero. O sea
#: que no es una mejora incremental sino un juego DESBLOQUEADO -- el mismo (0,0,0 -> 1,0,1) que el
#: parrafo de arriba ya habia visto en `todas`, que ahora queda explicado: ahi lo cancelaban las
#: otras palancas. La ablacion (+2) y el gate (+2) COINCIDEN, a diferencia de `memoriaDeMuertes`,
#: donde el lazo rapido media MUERTES (metrica intermedia) y el gate midio niveles: -1 (EXP-11).
#: Por eso lo que se entrega es esta sola y NO `todas`.
BANDERAS_POR_DEFECTO: Final[tuple[str, ...]] = (MACRO_CAMBIO_INFORMATIVO,)

_TOKEN_TODAS: Final[str] = "todas"
_TOKEN_NINGUNA: Final[str] = "ninguna"
_TOKEN_ENTREGADAS: Final[str] = "entregadas"


class BanderaDesconocida(ValueError):
    """Un token de `ARC_AGENT_BANDERAS` que no nombra ninguna palanca conocida."""


class Banderas:
    """Estado de las palancas de UNA corrida. Inmutable en la practica: se construye una vez al
    importar el modulo (o a mano en un test) y se lee."""

    __slots__ = ("_activas",)

    def __init__(self, activas: Iterable[str] | None = None) -> None:
        seleccion = tuple(BANDERAS_POR_DEFECTO) if activas is None else tuple(activas)
        desconocidas = [n for n in seleccion if n not in BANDERAS_CONOCIDAS]
        if desconocidas:
            raise BanderaDesconocida(
                f"Bandera(s) desconocida(s): {', '.join(sorted(desconocidas))}. "
                f"Conocidas: {', '.join(BANDERAS_CONOCIDAS)}"
            )
        self._activas = frozenset(seleccion)

    @property
    def activas(self) -> tuple[str, ...]:
        """Palancas encendidas, en el orden canonico de `BANDERAS_CONOCIDAS`."""
        return tuple(n for n in BANDERAS_CONOCIDAS if n in self._activas)

    def activa(self, nombre: str) -> bool:
        if nombre not in BANDERAS_CONOCIDAS:
            raise BanderaDesconocida(f"Bandera desconocida: {nombre}")
        return nombre in self._activas

    def con(self, *nombres: str) -> "Banderas":
        """Copia con SOLO esas palancas encendidas -- la forma que usan los tests deterministas."""
        return Banderas(nombres)

    def sin(self, *nombres: str) -> "Banderas":
        """Copia con esas palancas apagadas y el resto como esta."""
        return Banderas(n for n in self.activas if n not in nombres)

    def resumen(self) -> str:
        """Linea legible para el reporte de una corrida -- el gate la imprime para que dos
        mediciones no se puedan confundir."""
        return ",".join(self.activas) if self._activas else _TOKEN_NINGUNA

    @classmethod
    def todas(cls) -> "Banderas":
        """Todas las palancas conocidas, aprobadas o no. Es lo que mide el candidato completo."""
        return cls(BANDERAS_CONOCIDAS)

    @classmethod
    def desde_texto(cls, texto: str | None) -> "Banderas":
        """Parsea la gramatica documentada en el encabezado del modulo. Texto vacio o None = las
        palancas ENTREGADAS (`BANDERAS_POR_DEFECTO`), no todas las conocidas."""
        if texto is None or not texto.strip():
            return cls()
        activas = set(BANDERAS_POR_DEFECTO)
        for crudo in texto.split(","):
            token = crudo.strip()
            if not token:
                continue
            if token == _TOKEN_TODAS:
                activas = set(BANDERAS_CONOCIDAS)
                continue
            if token == _TOKEN_NINGUNA:
                activas = set()
                continue
            if token == _TOKEN_ENTREGADAS:
                activas = set(BANDERAS_POR_DEFECTO)
                continue
            if token.startswith("-"):
                nombre = token[1:]
                if nombre not in BANDERAS_CONOCIDAS:
                    raise BanderaDesconocida(
                        f"Bandera desconocida en {NOMBRE_DE_VARIABLE}: {nombre}. "
                        f"Conocidas: {', '.join(BANDERAS_CONOCIDAS)}"
                    )
                activas.discard(nombre)
                continue
            nombre = token[1:] if token.startswith("+") else token
            if nombre not in BANDERAS_CONOCIDAS:
                raise BanderaDesconocida(
                    f"Bandera desconocida en {NOMBRE_DE_VARIABLE}: {nombre}. "
                    f"Conocidas: {', '.join(BANDERAS_CONOCIDAS)}"
                )
            activas.add(nombre)
        return cls(activas)

    @classmethod
    def desde_entorno(cls) -> "Banderas":
        return cls.desde_texto(os.environ.get(NOMBRE_DE_VARIABLE))


#: Palancas vigentes del proceso. Se lee UNA vez al importar: una corrida no puede cambiar de
#: configuracion a mitad de camino sin que la medicion deje de significar nada.
BANDERAS: Banderas = Banderas.desde_entorno()


def bandera_activa(nombre: str, banderas: Banderas | None = None) -> bool:
    """Atajo de lectura: `banderas` explicitas (tests) o las del proceso."""
    return (BANDERAS if banderas is None else banderas).activa(nombre)
