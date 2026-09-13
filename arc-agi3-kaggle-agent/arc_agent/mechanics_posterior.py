"""[arc-agi3-kaggle-agent/mechanics_posterior] BL.21593 -- INFERENCIA BAYESIANA EXACTA sobre el
mapeo boton -> mecanica, con un latente JERARQUICO enumerable y una verosimilitud que EXPLICA el
fallo. Espejo exacto de arc-agi-runner/src/worldModel/mechanicsPosterior.ts (tests homonimos
pinnean los MISMOS numeros).

EL MODELO, en dos capas y sin EM ni aproximaciones (todo cabe en un diccionario):

  1. ARQUETIPO del juego -- variable latente de la capa alta, con prior observable en el PRIMER
     frame: P(arquetipo | conjunto de acciones disponibles) sale de `conjuntosMedidos` del prior
     generado (25 juegos publicos, BL.21590). Los arquetipos son los que la medicion encontro:
     `mueveCanonico` (11/17 juegos con flechas), `flechasSinMapeo` (6/17: flechas presentes que
     no mueven nada), `mixto` (D-pad parcial o mecanica no direccional; masa de Laplace) y
     `sinFlechas` (8/25: el conjunto no trae ACTION1..4 y no hay mapeo que inferir).
  2. MECANICA por boton -- P(boton -> mecanica | arquetipo): condicional PARAMETRICA (jamas por
     game_id; el gate del build lo enforcea) derivada de `juegosQueConfirmanPorAccion`. Soporte
     por flecha (BL.21853, ya no son siete): cuatro direcciones + `inerte` + las tres mecanicas
     visibles NOMBRADAS (`recoloreo`, `aparicion`, `desaparicion`) + `otra` (visible sin nombre,
     residual) + `desconocida` (masa RESERVADA, ver abajo). El vocabulario de siete metia las tres
     nombradas en `otra` con UNA verosimilitud: un boton que recolorea y uno que borra objetos
     eran indistinguibles. Los conteos que justifican cada simbolo estan en `CONTEO_VISIBLE_MEDIDO`.
     ALCANCE de esa distincion (revision de BL.21853, para no repetir RFM-08): el posterior los
     distingue PUERTAS ADENTRO y ningun consumidor actua sobre CUAL de los tres gano -- fuera de
     este modulo y sus tests nadie importa los tres simbolos, y a `mecanica_dominante` la leen
     `direccion_de` (filtra por `DIRECCIONES`), `resuelta` e `inerte` (solo masa) y `resumen`
     (log). NO son codigo muerto (se emiten 1.267/199/12 veces y ganan en 38 de 386 botones),
     pero el efecto medido de separarlos es +1 acierto direccional sobre 182 pares.

  Los botones son condicionalmente independientes dado el arquetipo, asi que el posterior es
  exacto por enumeracion: P(a|datos) proporcional a P(a) * prod_b sum_m P(m|a,b) * L(b,m), donde
  L(b,m) es el producto de verosimilitudes de las observaciones del boton b bajo la mecanica m
  (no depende del arquetipo dado m: se acumula UNA vez y se comparte). Esto acopla los botones:
  tres flechas muertas suben P(flechasSinMapeo) y la cuarta llega casi resuelta.

LA PIEZA CENTRAL -- la verosimilitud del fallo se DESCOMPONE (idea del usuario, 2026-08-17):

    P(no se movio | boton = direccion d) = P(pared en d | grilla) + P(desconocido)

  `P(pared | grilla)` es OBSERVABLE (wall_perception.py la mira). Un fallo con pared adyacente en
  la direccion de la hipotesis queda TOTALMENTE explicado y NO mueve el posterior del mapeo; el
  mismo fallo sin pared SI lo mueve; y un fallo con pared inobservable (avatar aun no visto)
  aporta poco pero no cero. Con esto el caso "inconcluso" de BL.21590 deja de ser una rama
  cableada: es la consecuencia numerica de cuanto explica el mundo a la observacion.

MASA RESERVADA `desconocida` (defensa contra vocabulario incompleto, propuesta del usuario): si
falta una mecanica en el vocabulario, el posterior elegiria CON CONFIANZA la menos mala de las
opciones equivocadas -- el peor modo de fallo. La categoria `desconocida` tiene verosimilitud
agnostica (explica cualquier cosa a medias) y un PISO que nunca baja; si acumula masa, se REGISTRA
(resumen -> reasoning persistido) como senal de que el vocabulario de BL.21561 necesita una
mecanica nueva -- informacion, no fallo. NADA de crear categorias online: decision de alcance."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Iterable

from .priors import DIRECTION_PRIORS
from .wall_perception import DIRECCIONES, PARED_DESCONOCIDA

# ── vocabulario enumerable ────────────────────────────────────────────────────────────────────

MECANICA_INERTE: Final[str] = "inerte"
MECANICA_OTRA: Final[str] = "otra"
MECANICA_DESCONOCIDA: Final[str] = "desconocida"

# BL.21853 -- LOS TRES SIMBOLOS QUE ANTES COMPARTIAN EL CAJON `otra`. No se inventaron aca: son
# tipos que `object_mechanics._clasificar_cluster` ya emitia y que `direction_beliefs` colapsaba.
# FRECUENCIA MEDIDA sobre las 7.258 transiciones de `arcReplayFrames`, en el pozo de 3.000:
# recoloreo 1.539 (25 juegos), desaparicion 248 (9), aparicion 78 (8). Ninguno "por si acaso".
MECANICA_RECOLOREO: Final[str] = "recoloreo"
MECANICA_APARICION: Final[str] = "aparicion"
MECANICA_DESAPARICION: Final[str] = "desaparicion"

#: Las mecanicas VISIBLES y NO DIRECCIONALES con nombre propio. `MECANICA_OTRA` queda como el
#: residual de esa misma clase (visible, no direccional, sin nombre), no como su sinonimo.
MECANICAS_NOMBRADAS: Final[tuple[str, ...]] = (
    MECANICA_RECOLOREO,
    MECANICA_APARICION,
    MECANICA_DESAPARICION,
)

#: Orden FIJO: las sumas flotantes se hacen en este orden en los dos puertos (paridad exacta).
#: Las cuatro primeras son las direcciones de wall_perception.DIRECCIONES.
MECANICAS: Final[tuple[str, ...]] = (
    "arriba",
    "abajo",
    "izquierda",
    "derecha",
    MECANICA_INERTE,
    MECANICA_RECOLOREO,
    MECANICA_APARICION,
    MECANICA_DESAPARICION,
    MECANICA_OTRA,
    MECANICA_DESCONOCIDA,
)

ARQUETIPO_MUEVE: Final[str] = "mueveCanonico"
ARQUETIPO_SIN_MAPEO: Final[str] = "flechasSinMapeo"
ARQUETIPO_MIXTO: Final[str] = "mixto"
ARQUETIPO_SIN_FLECHAS: Final[str] = "sinFlechas"

ARQUETIPOS: Final[tuple[str, ...]] = (
    ARQUETIPO_MUEVE,
    ARQUETIPO_SIN_MAPEO,
    ARQUETIPO_MIXTO,
    ARQUETIPO_SIN_FLECHAS,
)

BOTONES_DE_FLECHA: Final[tuple[str, ...]] = ("ACTION1", "ACTION2", "ACTION3", "ACTION4")

# ── parametros del modelo (medidos o derivados de la medicion de 25 juegos) ───────────────────

#: Reparto de la masa "visible y no direccional" que antes se llevaba entera `otra`: los EVENTOS
#: que el pipeline emite sobre el corpus persistido (BL.21853, 7.258 transiciones), Laplace +1.
#: OJO CON EL DENOMINADOR -- aca estuvo MAL una vez: contar las familias del corpus ANTES del
#: cambio deja el residual en 0, `otra` en prior 1,6e-5, y los 270 pasos que SI salen `otra`
#: (mezclas de nombradas) sin donde concentrar; medido, 134 botones direccionales contra 140 sin
#: tocar nada. Estos numeros son los eventos del pipeline YA cambiado: los decide el detector, no
#: el prior, asi que no son circulares. FUENTE UNICA:
#: `mediciones/BL21853_vocabulario_de_mecanicas.json`, que `test_bl21853_vocabulario.py` compara.
CONTEO_VISIBLE_MEDIDO: Final[dict[str, int]] = {
    MECANICA_RECOLOREO: 1267,
    MECANICA_APARICION: 12,
    MECANICA_DESAPARICION: 199,
    MECANICA_OTRA: 270,
}

REPARTO_VISIBLE: Final[dict[str, float]] = {
    m: (n + 1) / (sum(CONTEO_VISIBLE_MEDIDO.values()) + len(CONTEO_VISIBLE_MEDIDO))
    for m, n in CONTEO_VISIBLE_MEDIDO.items()
}

#: Piso de la masa reservada `desconocida`: NUNCA baja de aca. 0.02 es masa suficiente para que
#: unas pocas observaciones agnosticas la hagan visible sin robarle sensibilidad al resto.
PISO_DESCONOCIDO: Final[float] = 0.02

#: Un boton esta RESUELTO cuando una mecanica concentra este posterior. Derivado, no arbitrario:
#: es el valor que UNA corrida monotona de confirmacion supera y que el prior solo (cero
#: observaciones) no alcanza en ningun conjunto medido (numeros pinneados en tests de paridad).
UMBRAL_RESOLUCION: Final[float] = 0.85

#: La senal de vocabulario incompleto se emite cuando `desconocida` acumula esta masa con al
#: menos MIN_OBSERVACIONES_VOCABULARIO observaciones del boton.
UMBRAL_VOCABULARIO_INCOMPLETO: Final[float] = 0.35
MIN_OBSERVACIONES_VOCABULARIO: Final[int] = 4

#: Verosimilitud de una traslacion observada bajo la hipotesis de direccion: DENTRO de una
#: corrida monotona el sensor es fiel (0 remapeos espurios medidos en 4 partidas); AISLADA es
#: sospechosa -- la ambiguedad objeto/hueco de BL.21561 invierte el signo de forma sistematica
#: (medido: un juego dio 20 lecturas invertidas contra 6), por eso la contraria aislada conserva
#: verosimilitud alta bajo la hipotesis correcta.
L_TRASLACION_FIEL: Final[float] = 0.9
L_TRASLACION_CONTRARIA_FIEL: Final[float] = 0.01
L_TRASLACION_AISLADA: Final[float] = 0.65
L_TRASLACION_CONTRARIA_AISLADA: Final[float] = 0.35
L_TRASLACION_ORTOGONAL: Final[float] = 0.02
L_TRASLACION_SI_INERTE: Final[float] = 0.01
#: Vale para `otra` Y para las tres nombradas: bajo CUALQUIER visible no direccional, ver una
#: traslacion limpia es igual de improbable. Un solo numero, no cuatro copias.
L_TRASLACION_SI_OTRA: Final[float] = 0.05
L_TRASLACION_AGNOSTICA: Final[float] = 0.125

#: P(pared | contexto observado). `presente` no es 1.0 ni `ausente` 0.0 a proposito: la
#: percepcion de pared es un detector (piso estimado de celdas desalojadas), no un oraculo.
P_PARED: Final[dict[str, float]] = {"presente": 0.95, "ausente": 0.05, "desconocida": 0.5}

#: P(desconocido) del fallo: el termino residual de la descomposicion del usuario. "Un fallo
#: inexplicable aporta poco pero no cero" -- este es el poco.
PISO_FALLO_INEXPLICADO: Final[float] = 0.05

L_SIN_CAMBIO_SI_INERTE: Final[float] = 0.95
L_SIN_CAMBIO_SI_OTRA: Final[float] = 0.3
L_SIN_CAMBIO_AGNOSTICA: Final[float] = 0.5

#: L(evento `otra` | mecanica). BL.21853 le cambio DOS numeros y los dos por la misma razon: el
#: evento `otra` ya no significa lo que significaba. Antes era una mecanica visible LIMPIA (un
#: recoloreo, una desaparicion) y por eso `direccion` valia 0.02 -- "un boton direccional
#: practicamente nunca hace eso". Esos casos ahora tienen simbolo propio, y lo que queda en `otra`
#: es una MEZCLA de mecanicas nombradas, que no dice nada sobre la direccion: pasa a 0.05, el mismo
#: valor agnostico de `L_DETECTOR_DESCONOCIDA`. `nombrada` es la fila nueva.
#: MEDIDO sobre 7.258 transiciones: con 0.02 el vocabulario ampliado acierta 144 botones
#: direccionales de 204 (el detector solo acierta 150); con 0.05 sube a 151.
L_OTRA_MECANICA: Final[dict[str, float]] = {
    "direccion": 0.05, "inerte": 0.02, "nombrada": 0.15, "otra": 0.6, "desconocida": 0.3,
}
L_DETECTOR_DESCONOCIDA: Final[dict[str, float]] = {
    "direccion": 0.05, "inerte": 0.03, "nombrada": 0.15, "otra": 0.2, "desconocida": 0.4,
}

#: BL.21853 -- L(evento de una mecanica NOMBRADA | mecanica del boton): la tabla que hace que el
#: simbolo nuevo VALGA algo. `propia` conserva el 0.6 que tenia `otra` -> `otra`; `hermana` (otra de
#: las nombradas) baja a 0.05; `residual` es la mecanica `otra` vista desde un evento con nombre.
#: ALCANCE HONESTO DE ESE 0.05: barrido de 0.05 a 0.60 sobre las 7.258 transiciones, las cinco
#: corridas dieron 144 aciertos direccionales de 204 -- sobre ESTE corpus el valor no decide nada.
L_MECANICA_NOMBRADA: Final[dict[str, float]] = {
    "direccion": 0.02, "inerte": 0.02, "propia": 0.6, "hermana": 0.05,
    "residual": 0.1, "desconocida": 0.3,
}

EVENTO_TRASLACION: Final[str] = "traslacion"
EVENTO_SIN_CAMBIO: Final[str] = "sinCambio"
EVENTO_OTRA: Final[str] = "otra"
EVENTO_DESCONOCIDA: Final[str] = "desconocida"

#: BL.21853 -- un evento por mecanica nombrada. El TIPO del evento es el MISMO string que el de la
#: mecanica a proposito: son la observacion y la hipotesis de la misma cosa, y tener dos alfabetos
#: paralelos (`EVENTO_RECOLOREO = "eventoRecoloreo"`) es exactamente como se desincronizan.
EVENTO_RECOLOREO: Final[str] = MECANICA_RECOLOREO
EVENTO_APARICION: Final[str] = MECANICA_APARICION
EVENTO_DESAPARICION: Final[str] = MECANICA_DESAPARICION

#: Tipos de evento que nombran una mecanica visible. FUENTE UNICA para los dos consumidores.
EVENTOS_NOMBRADOS: Final[tuple[str, ...]] = (
    EVENTO_RECOLOREO,
    EVENTO_APARICION,
    EVENTO_DESAPARICION,
)


@dataclass(frozen=True)
class EventoObservado:
    """Observacion de UN paso de UN boton, ya clasificada por la percepcion (BL.21561) y con el
    contexto de pared observado en la grilla. `pared` mapea nombre de direccion -> presente/
    ausente/desconocida; None equivale a todo desconocida (avatar aun no visto)."""

    tipo: str
    signo: tuple[int, int] | None = None
    en_corrida: bool = False
    pared: dict[str, str] | None = None


def prior_de_arquetipos(clave_conjunto: str, prior: dict | None = None) -> dict[str, float]:
    """P(arquetipo | conjunto de acciones), con Laplace sobre los juegos medidos de ESE conjunto.
    Un conjunto con flechas nunca visto cae en la tasa base de los 17 juegos con flechas. Sin
    flechas en el conjunto no hay mapeo que inferir: `sinFlechas` se lleva todo."""
    p = prior if prior is not None else DIRECTION_PRIORS
    numeros = {int(n) for n in clave_conjunto.split(",") if n.strip().isdigit()}
    if not numeros & {1, 2, 3, 4}:
        return {a: (1.0 if a == ARQUETIPO_SIN_FLECHAS else 0.0) for a in ARQUETIPOS}
    entrada = p.get("conjuntosMedidos", {}).get(clave_conjunto)
    if entrada is not None and int(entrada["juegos"]) > 0:
        juegos = int(entrada["juegos"])
        confirman = int(entrada["confirman"])
        sin_movimiento = int(entrada["sinMovimiento"])
    else:
        juegos = int(p.get("nJuegosConFlechas", 0))
        confirman = int(p.get("nJuegosQueConfirman", 0))
        sin_movimiento = int(p.get("nJuegosSinMovimientoObservable", 0))
    total = juegos + 3
    return {
        ARQUETIPO_MUEVE: (confirman + 1) / total,
        ARQUETIPO_SIN_MAPEO: (sin_movimiento + 1) / total,
        ARQUETIPO_MIXTO: (juegos - confirman - sin_movimiento + 1) / total,
        ARQUETIPO_SIN_FLECHAS: 0.0,
    }


def _con_piso(distribucion: dict[str, float]) -> dict[str, float]:
    """Clampa `desconocida` al piso reservado y renormaliza el resto: la masa nunca baja de ahi."""
    actual = distribucion[MECANICA_DESCONOCIDA]
    if actual >= PISO_DESCONOCIDO:
        return distribucion
    resto = 1.0 - actual
    escala = (1.0 - PISO_DESCONOCIDO) / resto if resto > 0 else 0.0
    salida = {m: v * escala for m, v in distribucion.items()}
    salida[MECANICA_DESCONOCIDA] = PISO_DESCONOCIDO
    return salida


def condicional_de_mecanicas(
    arquetipo: str, boton: str, prior: dict | None = None
) -> dict[str, float]:
    """P(mecanica | arquetipo, boton) -- parametrica, derivada de la medicion de 25 juegos.

    `mueveCanonico`: la masa canonica del boton sale de `juegosQueConfirmanPorAccion` (10/11 para
    A1/A2, 9/11 para A3/A4: en los juegos que confirman, una flecha individual puede seguir
    muerta -- se midio medio D-pad inerte). El resto se reparte segun los modos de fallo medidos.
    `flechasSinMapeo`: inerte domina, `otra` cubre el selector/recoloreo medido. `mixto`: difusa
    a proposito -- es el arquetipo de lo no medido."""
    p = prior if prior is not None else DIRECTION_PRIORS
    canonica_de = {a: (int(v[0]), int(v[1])) for a, v in p["mapeoCanonico"].items()}
    canonica = canonica_de.get(boton)

    def repartir(masa_canonica: float, inerte: float, visible: float, desconocida: float) -> dict[str, float]:
        """`visible` es la masa de "visible y no direccional" ENTERA -- la que antes se llevaba
        `otra` sola; BL.21853 la reparte con `REPARTO_VISIBLE`. El total no cambia."""
        otras_direcciones = 1.0 - masa_canonica - inerte - visible - desconocida
        por_direccion = otras_direcciones / 3.0
        d: dict[str, float] = {}
        for m in MECANICAS:
            if m in DIRECCIONES:
                d[m] = masa_canonica if DIRECCIONES[m] == canonica else por_direccion
            elif m == MECANICA_INERTE:
                d[m] = inerte
            elif m in REPARTO_VISIBLE:
                d[m] = visible * REPARTO_VISIBLE[m]
            else:
                d[m] = desconocida
        return _con_piso(d)

    if arquetipo == ARQUETIPO_MUEVE:
        confirman_boton = int(p.get("juegosQueConfirmanPorAccion", {}).get(boton, 0))
        confirman_total = int(p.get("nJuegosQueConfirman", 0))
        base = (confirman_boton + 1) / (confirman_total + 2) if confirman_total else 0.75
        resto = 1.0 - base
        return repartir(base, resto * 0.55, resto * 0.20, resto * 0.10)
    if arquetipo == ARQUETIPO_SIN_MAPEO:
        return repartir(0.0125, 0.60, 0.25, 0.10)
    # `mixto` y (por completitud) `sinFlechas`: difusas. Bajo `sinFlechas` no hay botones de
    # flecha sembrados, asi que su condicional jamas pesa en la practica.
    return repartir(0.30, 0.25, 0.20, 0.10)


def _verosimilitud(evento: EventoObservado, mecanica: str) -> float:
    """L(evento | mecanica del boton). No depende del arquetipo dado la mecanica: se acumula una
    sola vez por boton y se comparte entre arquetipos."""
    if evento.tipo == EVENTO_TRASLACION and evento.signo is not None:
        if mecanica in DIRECCIONES:
            d = DIRECCIONES[mecanica]
            if evento.signo == d:
                return L_TRASLACION_FIEL if evento.en_corrida else L_TRASLACION_AISLADA
            if evento.signo == (-d[0], -d[1]):
                return (
                    L_TRASLACION_CONTRARIA_FIEL if evento.en_corrida else L_TRASLACION_CONTRARIA_AISLADA
                )
            return L_TRASLACION_ORTOGONAL
        if mecanica == MECANICA_INERTE:
            return L_TRASLACION_SI_INERTE
        if mecanica in REPARTO_VISIBLE:
            return L_TRASLACION_SI_OTRA
        return L_TRASLACION_AGNOSTICA
    if evento.tipo == EVENTO_SIN_CAMBIO:
        if mecanica in DIRECCIONES:
            contexto = (evento.pared or {}).get(mecanica, PARED_DESCONOCIDA)
            p_pared = P_PARED.get(contexto, P_PARED[PARED_DESCONOCIDA])
            return p_pared + (1.0 - p_pared) * PISO_FALLO_INEXPLICADO
        if mecanica == MECANICA_INERTE:
            return L_SIN_CAMBIO_SI_INERTE
        if mecanica in REPARTO_VISIBLE:
            return L_SIN_CAMBIO_SI_OTRA
        return L_SIN_CAMBIO_AGNOSTICA
    if evento.tipo in EVENTOS_NOMBRADOS:
        # BL.21853: el evento nombra UNA mecanica. La fila que se elige es lo unico que distingue a
        # `recoloreo` de `desaparicion`; con el vocabulario de siete las dos caian en L_OTRA_MECANICA
        # y el posterior no podia separarlas ni con mil observaciones.
        if mecanica in DIRECCIONES:
            return L_MECANICA_NOMBRADA["direccion"]
        if mecanica == MECANICA_INERTE:
            return L_MECANICA_NOMBRADA["inerte"]
        if mecanica == MECANICA_DESCONOCIDA:
            return L_MECANICA_NOMBRADA["desconocida"]
        if mecanica == MECANICA_OTRA:
            return L_MECANICA_NOMBRADA["residual"]
        return L_MECANICA_NOMBRADA["propia" if mecanica == evento.tipo else "hermana"]
    tabla = L_OTRA_MECANICA if evento.tipo == EVENTO_OTRA else L_DETECTOR_DESCONOCIDA
    if mecanica in DIRECCIONES:
        return tabla["direccion"]
    if mecanica in MECANICAS_NOMBRADAS:
        return tabla["nombrada"]
    return tabla[mecanica]


class PosteriorDeMapeo:
    """Posterior conjunto {arquetipo} x {boton -> mecanica}, exacto por enumeracion. UNA instancia
    por partida. `sembrar` fija el conjunto (la clave del prior); `observar` acumula verosimilitud;
    las lecturas se recalculan al pedirlas (tabla chica: 4 arquetipos x <=4 botones x 7 mecanicas)."""

    def __init__(self, prior: dict | None = None) -> None:
        self._prior = prior if prior is not None else DIRECTION_PRIORS
        self._arquetipos: dict[str, float] = {a: 0.0 for a in ARQUETIPOS}
        self._condicionales: dict[str, dict[str, dict[str, float]]] = {}
        self._lambda: dict[str, dict[str, float]] = {}
        self._observaciones: dict[str, int] = {}
        self._sembrado = False

    def sembrar(self, available_actions: Iterable[int]) -> int:
        """Idempotente; devuelve cuantos botones de flecha quedaron bajo inferencia."""
        if self._sembrado:
            return 0
        self._sembrado = True
        numeros = sorted(set(int(n) for n in available_actions))
        clave = ",".join(str(n) for n in numeros)
        self._arquetipos = prior_de_arquetipos(clave, self._prior)
        presentes = {f"ACTION{n}" for n in numeros}
        for boton in BOTONES_DE_FLECHA:
            if boton not in presentes:
                continue
            self._lambda[boton] = {m: 1.0 for m in MECANICAS}
            self._observaciones[boton] = 0
            self._condicionales[boton] = {
                a: condicional_de_mecanicas(a, boton, self._prior) for a in ARQUETIPOS
            }
        return len(self._lambda)

    @property
    def botones(self) -> list[str]:
        return [b for b in BOTONES_DE_FLECHA if b in self._lambda]

    def observaciones_de(self, boton: str) -> int:
        return self._observaciones.get(boton, 0)

    def observar(self, boton: str, evento: EventoObservado) -> None:
        acumulado = self._lambda.get(boton)
        if acumulado is None:
            return
        maximo = 0.0
        for m in MECANICAS:
            acumulado[m] *= _verosimilitud(evento, m)
            if acumulado[m] > maximo:
                maximo = acumulado[m]
        # Renormalizacion por el maximo: evita el underflow de cientos de productos y se cancela
        # en todos los cocientes del posterior (misma operacion en los dos puertos).
        if maximo > 0.0:
            for m in MECANICAS:
                acumulado[m] /= maximo
        self._observaciones[boton] = self._observaciones.get(boton, 0) + 1

    def posterior_de_arquetipo(self) -> dict[str, float]:
        pesos: dict[str, float] = {}
        for a in ARQUETIPOS:
            v = self._arquetipos.get(a, 0.0)
            for b in self.botones:
                cond = self._condicionales[b][a]
                v *= sum(cond[m] * self._lambda[b][m] for m in MECANICAS)
            pesos[a] = v
        total = sum(pesos.values())
        if total <= 0.0:
            return {a: 1.0 / len(ARQUETIPOS) for a in ARQUETIPOS}
        return {a: v / total for a, v in pesos.items()}

    def posterior_de(self, boton: str) -> dict[str, float] | None:
        """P(mecanica | boton, datos), marginalizando el arquetipo. Con el piso aplicado: la masa
        `desconocida` nunca baja de PISO_DESCONOCIDO."""
        if boton not in self._lambda:
            return None
        post_a = self.posterior_de_arquetipo()
        resultado = {m: 0.0 for m in MECANICAS}
        for a in ARQUETIPOS:
            pa = post_a[a]
            if pa <= 0.0:
                continue
            cond = self._condicionales[boton][a]
            z = sum(cond[m] * self._lambda[boton][m] for m in MECANICAS)
            if z <= 0.0:
                continue
            for m in MECANICAS:
                resultado[m] += pa * cond[m] * self._lambda[boton][m] / z
        return _con_piso(resultado)

    def mecanica_dominante(self, boton: str) -> tuple[str, float] | None:
        posterior = self.posterior_de(boton)
        if posterior is None:
            return None
        dominante = max(MECANICAS, key=lambda m: posterior[m])
        return (dominante, posterior[dominante])

    def direccion_de(self, boton: str) -> tuple[int, int] | None:
        dominante = self.mecanica_dominante(boton)
        if dominante is None or dominante[0] not in DIRECCIONES:
            return None
        return DIRECCIONES[dominante[0]]

    def resuelta(self, boton: str) -> bool:
        """El posterior concentro: deja de valer la pena gastar presupuesto en este boton. Exige
        al menos una observacion -- el prior solo jamas resuelve (el mas confiado de los conjuntos
        medidos queda por debajo del umbral, pinneado en tests)."""
        if self._observaciones.get(boton, 0) < 1:
            return False
        dominante = self.mecanica_dominante(boton)
        return dominante is not None and dominante[1] >= UMBRAL_RESOLUCION

    def inerte(self, boton: str) -> bool:
        dominante = self.mecanica_dominante(boton)
        return (
            dominante is not None
            and dominante[0] == MECANICA_INERTE
            and dominante[1] >= UMBRAL_RESOLUCION
        )

    def senal_de_vocabulario_incompleto(self) -> list[tuple[str, float]]:
        """Botones cuya masa `desconocida` acumulo por encima del umbral con evidencia suficiente:
        el vocabulario de mecanicas no explica lo observado. Se registra, no se inventa online."""
        senal: list[tuple[str, float]] = []
        for boton in self.botones:
            if self._observaciones.get(boton, 0) < MIN_OBSERVACIONES_VOCABULARIO:
                continue
            posterior = self.posterior_de(boton)
            if posterior is not None and posterior[MECANICA_DESCONOCIDA] >= UMBRAL_VOCABULARIO_INCOMPLETO:
                senal.append((boton, posterior[MECANICA_DESCONOCIDA]))
        return senal

    def resumen(self) -> str:
        """Linea legible para el reasoning persistido (la 'firma en el reporte' del BL: la senal
        de vocabulario incompleto viaja aca y queda registrada en el corpus de la partida)."""
        if not self._lambda:
            return "posterior sin botones de flecha"
        post_a = self.posterior_de_arquetipo()
        arquetipo = max(ARQUETIPOS, key=lambda a: post_a[a])
        partes = [f"arquetipo={arquetipo}:{post_a[arquetipo]:.2f}"]
        for boton in self.botones:
            dominante = self.mecanica_dominante(boton)
            if dominante is not None:
                partes.append(f"{boton}={dominante[0]}:{dominante[1]:.2f}")
        vocabulario = self.senal_de_vocabulario_incompleto()
        if vocabulario:
            detalle = ",".join(f"{b}:{masa:.2f}" for b, masa in vocabulario)
            partes.append(f"vocabularioIncompleto={detalle}")
        return " ".join(partes)
