"""[arc-agi3-kaggle-agent/world_model/evidencia_relacional] BL.21704 -- el TIPO de una relacion
causal a distancia y, sobre todo, el MODELO DE EVIDENCIA que distingue haberla observado de haberla
probado. La mineria vive en `relaciones_no_locales.py`; aca vive que significa creerle.

POR QUE LA EVIDENCIA TIENE DOS CANALES Y NO UNO. El corpus con el que se calibro este detector
viene de una politica EXPLORATORIA: en un juego donde el baseline nunca dispara el boton, no hay
NADA que minar por mas frames que se junten -- y eso no se arregla con mas observacion, se arregla
PROBANDO. El agente elige sus acciones, asi que puede repetir la accion sospechosa y ver si el
efecto lejano vuelve. Esa es la ventaja que el aprendizaje sobre juegos tiene sobre el aprendizaje
sobre mercados, y el modelo de evidencia la hace explicita en vez de dejarla en un comentario:

  * canal OBSERVACIONAL: cada co-activacion aporta 0,10 en log-odds, con TOPE de 2,0. Partiendo de
    un prior esceptico de -2,0 eso significa que la evidencia puramente observacional TIENE TECHO
    0,5 -- por muchas veces que se repita, observar no desconfunde.
  * canal INTERVENCIONAL: una repeticion exitosa aporta 1,20 (doce veces una observacion) y una
    fallida CASTIGA 1,80. El castigo es mayor que el premio a proposito: un exito todavia puede ser
    coincidencia, mientras que un fallo contradice la relacion de frente.

El veredicto es 3 de 4. Con ese corte, una relacion falsa que "acierta" la mitad de las veces por
azar pasa con probabilidad 5/16; y dos fallos la refutan de inmediato, sin gastar el cuarto intento.

Solo stdlib -- viaja al entregable de Kaggle.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

# Imports relativos en UNA sola linea a proposito: submission/build_agent.py los desmonta con el
# regex `^from \.\w* import .+$` y la forma con parentesis dejaria un `)` colgando en el entregable.
from .grid import BoundingBox
from .regiones_de_cambio import RegionDeCambio

#: Confirmacion activa: `CONFIRMACIONES_REQUERIDAS` de `INTENTOS_DE_CONFIRMACION`.
CONFIRMACIONES_REQUERIDAS: Final[int] = 3
INTENTOS_DE_CONFIRMACION: Final[int] = 4

#: Evidencia en log-odds (ver el docstring del modulo para el por que de cada numero).
LOG_ODDS_INICIAL: Final[float] = -2.0
APORTE_OBSERVACIONAL: Final[float] = 0.10
TOPE_DE_APORTE_OBSERVACIONAL: Final[float] = 2.0
APORTE_INTERVENCIONAL: Final[float] = 1.20
CASTIGO_INTERVENCIONAL: Final[float] = 1.80

#: Piso de evidencia para que una relacion se ofrezca como SUB-META al planner. 0,55 esta por
#: encima del techo observacional (0,5) A PROPOSITO. PERO EL PISO SOLO NO ALCANZA, y esto se
#: midio: con soporte alto el aporte observacional satura en +2,0, cancela el prior -2,0, y UN
#: SOLO exito intervencional deja la evidencia en 0,77 -- por encima del piso. O sea que el piso,
#: por si mismo, dejaba pasar relaciones con exitos=1 y fallos=0 mientras el BL exige 3 de 4.
#: Por eso submetas() exige AHORA las dos cosas: piso de evidencia Y veredicto intervencional.
PISO_DE_EVIDENCIA_PARA_SUBMETA: Final[float] = 0.55

#: CONDICION DE CONTROL de la via intervencional. Una repeticion "exitosa" solo prueba algo si el
#: destino NO cambia solo: sin comparar contra la tasa base, una puerta que parpadea en todos los
#: pasos llega a 3 de 4 y emite sub-meta -- verificado con un test adversarial contra la version
#: anterior. Con 3 de 4 exigidas (0,75) la tasa base tiene que quedar por debajo de 0,25 para que
#: el contraste do(accion) contra no-accion diga algo; y hacen falta al menos MIN_PASOS_DE_CONTROL
#: pasos sin la accion para estimarla. Sin control suficiente NO se confirma: el lado correcto en
#: el que fallar es el que no otorga permiso para dirigir el plan.
TASA_BASE_MAXIMA: Final[float] = 0.25
MIN_PASOS_DE_CONTROL: Final[int] = 10

ClaveDeRelacion = tuple[int, int, int, int, int, int, int, int, int]


def clave_de_relacion(
    origen: BoundingBox, destino: BoundingBox, desfase: int
) -> ClaveDeRelacion:
    """Identidad ESTABLE de una relacion, para que la evidencia intervencional sobreviva a que la
    mineria se vuelva a correr y renumere las regiones. Se apoya en la geometria (las dos cajas) y
    no en los ids, que cambian en cada pasada."""
    return (
        origen.min_y,
        origen.min_x,
        origen.max_y,
        origen.max_x,
        destino.min_y,
        destino.min_x,
        destino.max_y,
        destino.max_x,
        desfase,
    )


@dataclass
class Candidato:
    """Un par no local en evaluacion. Existe como tipo propio y no como diccionario para que las
    etapas del pipeline (soporte -> exclusion local -> BH -> nulo empirico -> pureza) se pasen algo
    con nombres, y no un mapa de claves que cualquiera puede escribir mal."""

    origen: RegionDeCambio
    destino: RegionDeCambio
    desfase: int
    mascara: int
    soporte: int
    esperado: float
    p_valor: float
    umbral_del_nulo: float = 0.0


@dataclass
class RelacionNoLocal:
    """Una relacion causal a distancia. NUNCA un booleano: la etapa 1 midio que el mismo par puede
    ser senal fuerte en un juego y ruido en otro, asi que lo que se guarda es la FUERZA (log-razon
    observado/esperado), el SOPORTE, la accion ligada, su pureza y el estado de confirmacion."""

    origen: RegionDeCambio
    destino: RegionDeCambio
    desfase: int
    soporte: int
    esperado: float
    fuerza: float
    p_valor: float
    umbral_del_nulo: float
    accion: str
    pureza: float
    #: Coordenada con la que se dispara, cuando la accion la lleva (un click). REPETIR la accion
    #: sin ella no es repetir nada, asi que una relacion de click sin coordenada no se retiene.
    coordenada: tuple[int, int] | None = None
    exitos: int = 0
    fallos: int = 0
    #: CONDICION DE CONTROL: pasos observados en que la accion de la relacion NO se ejecuto, y en
    #: cuantos de ellos el destino cambio igual. Es el nulo de la via intervencional. El argumento
    #: viejo, "pasa con probabilidad 5/16 tirando una moneda", usa p=0,5, que no es el nulo
    #: relevante: el nulo es la tasa base de cambio del destino, medida entre 0,06 y 0,24 en lp85
    #: y jamas comparada.
    pasos_de_control: int = 0
    cambios_sin_accion: int = 0

    @property
    def clave(self) -> ClaveDeRelacion:
        return clave_de_relacion(self.origen.caja, self.destino.caja, self.desfase)

    @property
    def intentos(self) -> int:
        return self.exitos + self.fallos

    @property
    def control_suficiente(self) -> bool:
        return self.pasos_de_control >= MIN_PASOS_DE_CONTROL

    @property
    def tasa_base(self) -> float:
        """Probabilidad de que el destino cambie CUANDO NO se ejecuto la accion. Es contra esto que
        hay que leer los exitos intervencionales, no contra una moneda."""
        if self.pasos_de_control <= 0:
            return 0.0
        return self.cambios_sin_accion / self.pasos_de_control

    @property
    def cambia_sola(self) -> bool:
        """El destino cambia por su cuenta lo bastante seguido como para que repetir la accion no
        pruebe nada. Es el control negativo del BL aplicado en la etapa que otorga el permiso de
        dirigir el plan, y no solo en la mineria."""
        return self.control_suficiente and self.tasa_base - TASA_BASE_MAXIMA - 1e-12 > 0.0

    @property
    def refutada(self) -> bool:
        """Con 3 de 4, dos fallos ya hacen imposible el veredicto positivo: se refuta ahi mismo, en
        vez de gastar el cuarto intento en una relacion que ya no puede pasar. Y una relacion cuyo
        destino cambia solo queda refutada aunque acierte todas: no hay contraste que medir."""
        return (
            self.fallos - (INTENTOS_DE_CONFIRMACION - CONFIRMACIONES_REQUERIDAS) - 1 >= 0
            or self.cambia_sola
        )

    @property
    def confirmacion(self) -> str:
        """"intervencional" exige las TRES cosas: 3 de 4 repeticiones, control suficiente para
        estimar la tasa base, y tasa base por debajo de TASA_BASE_MAXIMA."""
        if self.exitos - CONFIRMACIONES_REQUERIDAS < 0:
            return "observacional"
        if not self.control_suficiente or self.cambia_sola:
            return "observacional"
        return "intervencional"

    @property
    def evidencia(self) -> float:
        """Log-odds -> probabilidad. Ver las constantes: la via observacional tiene TECHO 0,5."""
        aporte = min(self.soporte * APORTE_OBSERVACIONAL, TOPE_DE_APORTE_OBSERVACIONAL)
        log_odds = (
            LOG_ODDS_INICIAL
            + aporte
            + self.exitos * APORTE_INTERVENCIONAL
            - self.fallos * CASTIGO_INTERVENCIONAL
        )
        return 1.0 / (1.0 + math.exp(-log_odds))

    def resumen(self) -> dict[str, object]:
        """Fila de reporte: la relacion tiene que ser AUDITABLE desde fuera del agente."""
        return {
            "origen": [self.origen.caja.min_y, self.origen.caja.min_x],
            "destino": [self.destino.caja.min_y, self.destino.caja.min_x],
            "desfase": self.desfase,
            "fuerza": round(self.fuerza, 4),
            "soporte": self.soporte,
            "esperado": round(self.esperado, 4),
            "umbralDelNulo": round(self.umbral_del_nulo, 4),
            "accion": self.accion,
            "coordenada": list(self.coordenada) if self.coordenada is not None else None,
            "pureza": round(self.pureza, 4),
            "confirmacion": self.confirmacion,
            "exitos": self.exitos,
            "fallos": self.fallos,
            "pasosDeControl": self.pasos_de_control,
            "tasaBase": round(self.tasa_base, 4),
            "evidencia": round(self.evidencia, 4),
        }


@dataclass(frozen=True)
class SubMeta:
    """Lo que el almacen le ofrece al planner: "repetir `accion` hace cambiar `caja_destino`". Es
    accionable -- una sub-meta, no una descripcion."""

    accion: str
    coordenada: tuple[int, int] | None
    caja_origen: BoundingBox
    caja_destino: BoundingBox
    desfase: int
    fuerza: float
    soporte: int
    evidencia: float
    confirmacion: str
