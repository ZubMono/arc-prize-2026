"""[arc-agi3-kaggle-agent/tests] BL.21695 paso 1 -- la CAPTURA de "como se ve ganar": deteccion del
evento, recorte de la ventana, registro de la accion emitida y JSONL.

Lo que se protege aca es la HONESTIDAD del corpus, no la elegancia del codigo: una ventana mal
recortada, un frame inventado, una accion mal atribuida o un evento detectado donde no lo hubo
producen evidencia falsa sobre cual era el objetivo del juego -- el error mas caro de este BL,
porque a partir de esa evidencia se deriva el vocabulario y despues el agente persigue la meta
equivocada durante todo el episodio.

La CARACTERIZACION de lo capturado se prueba en `test_bl21695_caracterizacion.py`.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from captura_de_niveles import (  # noqa: E402
    ACCION_DESCONOCIDA,
    VENTANA_POR_DEFECTO,
    AccionRegistrada,
    acciones_alineadas,
    agregar_a_jsonl,
    describir_accion,
    leer_jsonl,
    normalizar_frame,
    pasos_de_subida_de_nivel,
    registrar_acciones,
    ventanas_de_nivel,
)


# --- Dobles del wire oficial -------------------------------------------------------------------
# Se imitan los ATRIBUTOS de `arcengine.FrameData` (pydantic) y no se importa el paquete: el
# framework oficial no esta instalado en CI y la captura lee todo por `getattr`, asi que un doble
# con los mismos nombres ejercita exactamente el mismo camino.


@dataclass
class EntradaFalsa:
    id: Any = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class IdFalso:
    name: str


@dataclass
class FrameFalso:
    frame: list[list[list[int]]]
    levels_completed: int = 0
    win_levels: int = 3
    available_actions: list[int] = field(default_factory=lambda: [1, 2, 3, 4])
    state: Any = "NOT_FINISHED"
    full_reset: bool = False
    action_input: EntradaFalsa = field(default_factory=EntradaFalsa)


def _grilla(alto: int = 4, ancho: int = 4, valor: int = 0) -> list[list[int]]:
    return [[valor for _ in range(ancho)] for _ in range(alto)]


def _frame(niveles: int, valor: int = 0, con_grilla: bool = True) -> FrameFalso:
    return FrameFalso(frame=[_grilla(valor=valor)] if con_grilla else [], levels_completed=niveles)


# --- Deteccion del evento ----------------------------------------------------------------------


def test_detecta_solo_los_incrementos_de_nivel():
    frames = [_frame(0), _frame(0), _frame(1), _frame(1), _frame(2)]
    assert pasos_de_subida_de_nivel(frames) == [2, 4]


def test_la_bajada_por_reset_no_es_un_evento_pero_la_resubida_si():
    # GAME_OVER + RESET devuelve el contador a 0: eso NO es un completado. Volver a subir SI lo es.
    frames = [_frame(1), _frame(0), _frame(1)]
    assert pasos_de_subida_de_nivel(frames) == [2]


def test_un_contador_basura_no_inventa_eventos():
    frames = [_frame(0), FrameFalso(frame=[_grilla()], levels_completed=None), _frame(0)]  # type: ignore[arg-type]
    assert pasos_de_subida_de_nivel(frames) == []


# --- Ventanas ----------------------------------------------------------------------------------


def test_la_ventana_se_recorta_en_los_bordes_sin_rellenar():
    # Evento en el paso 1 de una partida de 4 frames: no hay 10 frames antes ni 10 despues.
    frames = [_frame(0), _frame(1), _frame(1), _frame(1)]
    ventanas = ventanas_de_nivel(frames, juego="ft09", corrida="c1", modelo="harness-local")
    assert len(ventanas) == 1
    ventana = ventanas[0]
    assert ventana.paso_del_evento == 1
    assert ventana.frames_antes == 1
    assert ventana.frames_despues == 2
    assert [f.paso for f in ventana.frames] == [0, 1, 2, 3]


def test_la_ventana_respeta_el_ancho_pedido():
    frames = [_frame(0) for _ in range(40)]
    frames[20] = _frame(1)
    frames[21:] = [_frame(1) for _ in frames[21:]]
    ventanas = ventanas_de_nivel(
        frames, juego="g50t", corrida="c1", modelo="harness-local", antes=3, despues=2
    )
    assert [f.paso for f in ventanas[0].frames] == [17, 18, 19, 20, 21, 22]


def test_el_ancho_por_defecto_cubre_una_macro_completa():
    # MACRO_MAX_STEPS = 8 en arc_agent/exploration_memory.py: la ventana tiene que contenerla.
    from arc_agent.exploration_memory import MACRO_MAX_STEPS

    assert VENTANA_POR_DEFECTO >= MACRO_MAX_STEPS + 2


def test_los_frames_sin_grilla_no_entran_al_corpus():
    frames = [_frame(0, con_grilla=False), _frame(0), _frame(1)]
    ventanas = ventanas_de_nivel(frames, juego="vc33", corrida="c1", modelo="harness-local")
    assert [f.paso for f in ventanas[0].frames] == [1, 2]


def test_sin_el_frame_del_evento_la_ventana_se_descarta_entera():
    frames = [_frame(0), _frame(1, con_grilla=False), _frame(1)]
    assert ventanas_de_nivel(frames, juego="vc33", corrida="c1", modelo="harness-local") == []


def test_normalizar_frame_recupera_la_coordenada_del_click():
    frame = FrameFalso(
        frame=[_grilla()],
        action_input=EntradaFalsa(id=IdFalso("ACTION6"), data={"x": 12, "y": 34}),
    )
    capturado = normalizar_frame(frame, paso=7)
    assert (capturado.accion, capturado.x, capturado.y) == ("ACTION6", 12, 34)


def test_normalizar_frame_no_inventa_accion_cuando_el_wire_no_la_declara():
    capturado = normalizar_frame(FrameFalso(frame=[_grilla()], action_input=None), paso=0)  # type: ignore[arg-type]
    assert capturado.accion == ACCION_DESCONOCIDA


# --- Registro de la accion EMITIDA -------------------------------------------------------------
# El motor offline NO informa `action_input` y su default es RESET: sin este registro el corpus
# afirmaba que los 235 frames capturados los produjo un RESET, incluidos los juegos de clicks.


@dataclass
class DatosDeAccionFalsos:
    x: int
    y: int


class AccionFalsa:
    def __init__(self, name: str, x: int | None = None, y: int | None = None) -> None:
        self.name = name
        self.action_data = None if x is None else DatosDeAccionFalsos(x=x, y=y or 0)

    def is_complex(self) -> bool:
        return self.action_data is not None


class AgenteFalso:
    """Imita lo justo de `agents.agent.Agent`: `take_action` devuelve frame (o None) y `frames`."""

    def __init__(self, respuestas: list[Any]) -> None:
        self._respuestas = list(respuestas)
        self.frames = [_frame(0)]

    def take_action(self, accion: Any) -> Any:
        frame = self._respuestas.pop(0)
        if frame is not None:
            self.frames.append(frame)
        return frame


def test_describir_accion_lee_la_coordenada_del_click():
    assert describir_accion(AccionFalsa("ACTION6", 31, 12)) == AccionRegistrada("ACTION6", 31, 12)
    assert describir_accion(AccionFalsa("ACTION3")) == AccionRegistrada("ACTION3", None, None)


def test_registrar_acciones_engancha_la_instancia_y_deja_la_clase_intacta():
    # Se sustituye el metodo LIGADO de UNA instancia: otra instancia de la misma clase (y la clase
    # entregada, con su `name` y su MRO) no se enteran.
    agente = AgenteFalso([_frame(0)])
    registradas = registrar_acciones(agente)
    agente.take_action(AccionFalsa("ACTION1"))
    assert [a.nombre for a in registradas] == ["ACTION1"]

    otro = AgenteFalso([_frame(0)])
    otro.take_action(AccionFalsa("ACTION2"))
    assert registradas == [AccionRegistrada("ACTION1", None, None)]
    assert otro.take_action.__func__ is AgenteFalso.take_action


def test_una_accion_sin_frame_no_se_registra():
    # `Agent.main()` solo agrega a `frames` cuando `take_action` devuelve algo: registrar la accion
    # igual correria la lista y le atribuiria a cada frame la accion del anterior.
    agente = AgenteFalso([_frame(0), None, _frame(1)])
    registradas = registrar_acciones(agente)
    for nombre in ("ACTION1", "ACTION2", "ACTION3"):
        agente.take_action(AccionFalsa(nombre))
    assert [a.nombre for a in registradas] == ["ACTION1", "ACTION3"]
    assert len(agente.frames) == len(registradas) + 1


def test_las_acciones_se_alinean_con_los_frames_dejando_el_frame_cero_sin_accion():
    frames = [_frame(0), _frame(0), _frame(1)]
    acciones = [AccionRegistrada("ACTION1"), AccionRegistrada("ACTION6", 4, 5)]
    alineadas = acciones_alineadas(frames, acciones)
    assert alineadas[0] is None
    assert alineadas[2] == AccionRegistrada("ACTION6", 4, 5)


def test_una_lista_de_acciones_desalineada_se_descarta_entera():
    frames = [_frame(0), _frame(0), _frame(1)]
    assert acciones_alineadas(frames, [AccionRegistrada("ACTION1")]) == [None, None, None]


def test_la_ventana_usa_la_accion_emitida_y_no_el_default_del_motor():
    frames = [_frame(0), _frame(0), _frame(1)]
    acciones = [AccionRegistrada("ACTION1"), AccionRegistrada("ACTION6", 31, 12)]
    ventana = ventanas_de_nivel(
        frames, juego="vc33", corrida="c1", modelo="harness-local", acciones=acciones
    )[0]
    evento = next(f for f in ventana.frames if f.paso == 2)
    assert (evento.accion, evento.x, evento.y) == ("ACTION6", 31, 12)
    # El frame inicial sintetico no lo produjo ninguna accion: no se le inventa una.
    assert ventana.frames[0].accion == ACCION_DESCONOCIDA


# --- JSONL -------------------------------------------------------------------------------------


def test_el_jsonl_acumula_y_sobrevive_a_una_linea_truncada(tmp_path: Path):
    frames = [_frame(0), _frame(1)]
    ventanas = ventanas_de_nivel(frames, juego="ft09", corrida="c1", modelo="harness-local")
    destino = tmp_path / "ventanas.jsonl"
    assert agregar_a_jsonl(destino, ventanas) == 1
    assert agregar_a_jsonl(destino, ventanas) == 1  # append, no overwrite
    assert len(leer_jsonl(destino)) == 2

    with destino.open("a", encoding="utf-8") as archivo:
        archivo.write('{"juego": "ft09", "frames": [')  # proceso muerto a mitad de una escritura
    assert len(leer_jsonl(destino)) == 2


def test_el_jsonl_conserva_las_claves_del_contrato(tmp_path: Path):
    frames = [_frame(0), _frame(1)]
    destino = tmp_path / "v.jsonl"
    agregar_a_jsonl(
        destino, ventanas_de_nivel(frames, juego="ft09", corrida="c1", modelo="harness-local")
    )
    ventana = leer_jsonl(destino)[0]
    assert ventana["juego"] == "ft09"
    assert ventana["nivelPrevio"] == 0 and ventana["nivelNuevo"] == 1
    assert ventana["frames"][0]["nivelesCompletados"] == 0
    assert ventana["frames"][-1]["grilla"] == _grilla()
