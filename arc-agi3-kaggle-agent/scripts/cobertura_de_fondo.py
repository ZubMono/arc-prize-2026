"""[arc-agi3-kaggle-agent/scripts/cobertura_de_fondo] BL.21794 -- POLITICA DE CAPTURA que fuerza
una fraccion de los clicks sobre el FONDO, para romper una linea base con VARIANZA CERO.

POR QUE EXISTE (defecto MEDIDO, BL.21765). El candidato `resueltoTocandoUnObjeto` murio 0/14 y NO
por falta de percepcion: murio porque en los 6 eventos de click del corpus TODOS los clicks previos
de la ventana cayeron tambien sobre un objeto (ft09 9/9, lp85 9/9, vc33 1/1 y 9/9). El criterio
exige que la linea base NO este saturada, y con `clicks_previos_en_objeto == clicks_previos` en el
100% de la muestra el rasgo tiene VARIANZA CERO: el click que gano no se distingue de los que no
ganaron. Ninguna percepcion nueva arregla eso -- ni el criterio mas fino puede discriminar sobre un
insumo que no tomo dos valores distintos en toda la muestra. Hace falta OTRA MUESTRA, y esa muestra
solo aparece si el agente clickea el fondo alguna vez.

EL OBJETIVO DE ESTAS CORRIDAS ES MEDIR, NO PUNTUAR. Una fraccion de los clicks se redirige a una
celda de FONDO aunque el ranker de coordenadas hubiera elegido otra cosa, asi que estas partidas
puntuan PEOR a proposito. Por eso la redireccion vive en `scripts/` (SOLO REPO, no viaja al
entregable de Kaggle) y se engancha en la INSTANCIA del agente: la clase `MyAgent` queda intacta,
`arc_agent/` no se toca, y el entregable no cambia ni una linea. Una corrida sin la bandera corre
exactamente como siempre.

LA ATRIBUCION SE MANTIENE HONESTA, Y ES LA PARTE QUE PODIA SALIR MAL. La politica le atribuye el
resultado del click a `_prev_click` (`policy._atribuir_click` -> `ClickMemory.registrar_resultado`),
que es la celda que ELLA eligio. Si se redirige el click sin corregir ese campo, la memoria de
clicks aprende plantillas, anti-plantillas y penalizaciones transversales sobre una celda que nunca
se clickeo: evidencia FALSA dentro del agente, que es exactamente el error que este corpus existe
para no cometer. Por eso `_prev_click` se corrige en el mismo paso y, si la politica no expone ese
campo, la redireccion se APAGA ENTERA con un aviso ruidoso en vez de degradar en silencio.

QUE ES "FONDO": el color mas frecuente de la grilla, `detect_background_color` de
`arc_agent/world_model/grid.py`. Es la MISMA definicion con la que `componente_bajo_el_click`
(`scripts/caracterizacion_de_niveles.py`) decide si un click cayo sobre un objeto -- si la captura
y el analisis usaran definiciones distintas de fondo, la muestra nueva no contestaria la pregunta
que la motivo.

Stdlib pura (mas `arc_agent`, que ya vive en el proceso). SOLO REPO."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from arc_agent.prng import create_seeded_random  # noqa: E402
from arc_agent.world_model.grid import detect_background_color  # noqa: E402
from captura_de_niveles import grilla_visible  # noqa: E402

#: Fraccion de clicks al fondo que usa el barrido de BL.21794 cuando no se le pasa otra. 0,30 y no
#: 0,50: en vc33 el 98,5% de las acciones son clicks (3.942 de 4.001, BL.21783), asi que la mitad
#: de los clicks al fondo seria la mitad de la partida tirada y probablemente ninguna subida de
#: nivel que capturar -- una corrida sin evento no aporta NADA, ni siquiera linea base, porque la
#: linea base se mide DENTRO de la ventana de un evento. 0,30 deja 7 de cada 10 clicks al ranker.
FRACCION_POR_DEFECTO = 0.30

#: Prefijo de la etiqueta que identifica una corrida de cobertura de fondo DENTRO del `runId`
#: persistido (`harness-local:<juego>:<lote>-fondo30`). FUENTE UNICA: lo escribe `etiqueta_de_corrida`
#: en el barrido y lo lee `es_corrida_con_fondo` en el informe. Si cada lado tuviera su literal, el
#: dia que cambie la etiqueta el informe seguiria contando esas ventanas como politica entregada --
#: y sumar dos poblaciones distintas sin decirlo es el error que esta marca existe para evitar.
PREFIJO_DE_ETIQUETA_DE_FONDO = "fondo"


def etiqueta_de_corrida(fraccion: float) -> str:
    """Etiqueta que va al `runId` de una corrida de cobertura de fondo, con la fraccion adentro:
    dos barridos con fracciones distintas NO son la misma poblacion y el corpus tiene que decirlo."""
    return f"{PREFIJO_DE_ETIQUETA_DE_FONDO}{int(round(max(0.0, min(1.0, fraccion)) * 100)):02d}"


def es_corrida_con_fondo(corrida: str) -> bool:
    """El `runId` corresponde a una corrida de MEDICION con cobertura de fondo forzada.

    Se mira el ULTIMO segmento (el lote) y no la cadena entera: un juego que se llamara `fondo42`
    no puede convertir su corrida normal en una de medicion."""
    lote = corrida.rsplit(":", 1)[-1]
    return f"-{PREFIJO_DE_ETIQUETA_DE_FONDO}" in lote


def celdas_de_fondo(grilla: list[list[int]]) -> list[tuple[int, int]]:
    """Coordenadas `(x, y)` cuyo color es el de FONDO. Lista vacia si la grilla esta vacia o si no
    hay una sola celda de fondo (imposible con `detect_background_color`, que devuelve el color mas
    frecuente, pero se contempla para que el llamador no tenga que confiar)."""
    if not grilla or not grilla[0]:
        return []
    fondo = detect_background_color(grilla)
    return [
        (x, y)
        for y, fila in enumerate(grilla)
        for x, celda in enumerate(fila)
        if celda == fondo
    ]


def elegir_celda_de_fondo(
    grilla: list[list[int]], rng: Callable[[], float]
) -> tuple[int, int] | None:
    """Una celda de fondo elegida UNIFORMEMENTE. None si no hay ninguna.

    Uniforme y no "la mas lejana al objeto mas cercano": el objetivo es que la linea base de clicks
    deje de ser constante, y cualquier regla que elija la celda de fondo por una propiedad
    geometrica introduce ESA propiedad como confusor en la muestra nueva. El sorteo sale de un rng
    PROPIO y nunca del de la politica: consumir numeros del rng del agente cambiaria la partida que
    una misma semilla reproduce, que es la garantia sobre la que se apoya toda medicion de este
    proyecto."""
    celdas = celdas_de_fondo(grilla)
    if not celdas:
        return None
    return celdas[min(len(celdas) - 1, int(rng() * len(celdas)))]


class RedireccionAlFondo:
    """Engancha en UNA instancia de agente la redireccion de clicks al fondo y lleva su contabilidad.

    No hereda ni parchea la clase: sustituye el metodo ligado `choose_action` del objeto, igual que
    `captura_de_niveles.registrar_acciones` hace con `take_action`. El framework oficial sigue viendo
    la misma clase, el mismo `name` y la misma scorecard."""

    def __init__(self, fraccion: float, semilla: str) -> None:
        self.fraccion = max(0.0, min(1.0, float(fraccion)))
        self._rng = create_seeded_random(f"cobertura-de-fondo:{semilla}")
        self.clicks_emitidos = 0
        self.clicks_redirigidos = 0
        self.clicks_del_agente_ya_en_el_fondo = 0
        self.clicks_sin_fondo_disponible = 0
        self.apagada_por_atribucion = False

    # -- enganche ---------------------------------------------------------------------------------

    def enganchar(self, agente: Any) -> bool:
        """Envuelve `agente.choose_action`. Devuelve False (y no engancha nada) si la fraccion es 0
        o si la politica no expone `_prev_click`, que es el campo por el que se le atribuye el
        resultado al click. Sin ese campo la redireccion produciria evidencia falsa DENTRO del
        agente, asi que no se hace: fail-closed y ruidoso."""
        if self.fraccion <= 0.0:
            return False
        politica = getattr(agente, "_politica", None)
        if politica is None or not hasattr(politica, "_prev_click"):
            self.apagada_por_atribucion = True
            print(
                "[cobertura-de-fondo] APAGADA: la politica de este agente no expone `_prev_click`, "
                "asi que un click redirigido se le atribuiria a la celda que el ranker eligio y "
                "nunca se clickeo. Antes que meter evidencia falsa en la memoria de clicks, no se "
                "redirige nada.",
                flush=True,
            )
            return False

        elegir = agente.choose_action

        def choose_action(frames: Any, latest_frame: Any) -> Any:
            accion = elegir(frames, latest_frame)
            return self._quizas_redirigir(accion, latest_frame, politica)

        agente.choose_action = choose_action
        return True

    # -- redireccion ------------------------------------------------------------------------------

    def _quizas_redirigir(self, accion: Any, frame: Any, politica: Any) -> Any:
        """Redirige el click con probabilidad `fraccion`. Cualquier accion que no sea un click sale
        intacta y ni siquiera consume el sorteo: el rng tiene que avanzar una vez por CLICK para que
        la fraccion efectiva sea la pedida y no la pedida por la proporcion de clicks del juego."""
        if not _es_click(accion):
            return accion
        self.clicks_emitidos += 1
        grilla = grilla_visible(frame)
        if _cae_en_el_fondo(accion, grilla):
            self.clicks_del_agente_ya_en_el_fondo += 1
        if self._rng() >= self.fraccion:
            return accion
        celda = elegir_celda_de_fondo(grilla, self._rng)
        if celda is None:
            self.clicks_sin_fondo_disponible += 1
            return accion
        x, y = celda
        accion.set_data({"x": x, "y": y})
        # La atribucion del resultado se corrige EN EL MISMO PASO: ver el docstring de la clase.
        politica._prev_click = (x, y)
        razonamiento = accion.reasoning if isinstance(accion.reasoning, dict) else {}
        accion.reasoning = {
            **razonamiento,
            "x": x,
            "y": y,
            "redirigidoAlFondo": True,
            "razonamiento": (
                "BL.21794 -- corrida de CAPTURA con cobertura de fondo forzada "
                f"({self.fraccion:.2f}): el click se movio a una celda de fondo para que la linea "
                "base de clicks previos deje de tener varianza cero. "
                + str(razonamiento.get("razonamiento", ""))
            ),
        }
        self.clicks_redirigidos += 1
        return accion

    # -- contabilidad -----------------------------------------------------------------------------

    def resumen(self) -> dict[str, Any]:
        """Lo que hay que poder leer al lado de la muestra que produjo esta corrida."""
        return {
            "fraccionPedida": round(self.fraccion, 4),
            "clicksEmitidos": self.clicks_emitidos,
            "clicksRedirigidos": self.clicks_redirigidos,
            "clicksDelAgenteYaEnElFondo": self.clicks_del_agente_ya_en_el_fondo,
            "clicksSinFondoDisponible": self.clicks_sin_fondo_disponible,
            "fraccionEfectiva": (
                round(self.clicks_redirigidos / self.clicks_emitidos, 4)
                if self.clicks_emitidos
                else None
            ),
            "apagadaPorAtribucion": self.apagada_por_atribucion,
        }


def _es_click(accion: Any) -> bool:
    """ACTION6 del framework oficial: la unica accion que lleva coordenada (`is_complex`)."""
    try:
        return bool(accion.is_complex())
    except Exception:  # noqa: BLE001 -- una accion que no sabe contestar no es un click
        return False


def _cae_en_el_fondo(accion: Any, grilla: list[list[int]]) -> bool:
    """El click que el AGENTE eligio, cae sobre el fondo? Se mide antes de redirigir: es la linea
    base contra la que se lee la muestra nueva -- si el agente ya clickeara el fondo por su cuenta,
    esta corrida no haria falta."""
    if not grilla or not grilla[0]:
        return False
    datos = getattr(accion, "action_data", None)
    x, y = getattr(datos, "x", None), getattr(datos, "y", None)
    if not isinstance(x, int) or not isinstance(y, int):
        return False
    if not (0 <= y < len(grilla) and 0 <= x < len(grilla[y])):
        return False
    return grilla[y][x] == detect_background_color(grilla)


__all__ = [
    "FRACCION_POR_DEFECTO",
    "PREFIJO_DE_ETIQUETA_DE_FONDO",
    "RedireccionAlFondo",
    "celdas_de_fondo",
    "elegir_celda_de_fondo",
    "es_corrida_con_fondo",
    "etiqueta_de_corrida",
]
