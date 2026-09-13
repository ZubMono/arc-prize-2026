"""[arc-agi3-kaggle-agent/tests/test_build_agent] BL.20783/BL.21555 -- tests de
submission/build_agent.py, el build del ENTREGABLE (un unico agent/my_agent.py).

QUE PROTEGE. Tres modos de falla silenciosos y caros: (1) un modulo nuevo de arc_agent/ que no
entra a MODULE_ORDER ni se declara excluido -- exactamente el defecto que tuvo direction_beliefs.py
en el viejo build_notebook.py: el entregable moria con NameError recien en Kaggle; (2) el gate
anti-memorizacion de BL.21560 dejando pasar un priors.py indexado por partida; (3) un
agent/my_agent.py commiteado que quedo VIEJO respecto del paquete fuente (drift build/entregable).
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from submission.build_agent import (
    ARCHIVO_DE_PRIORS,
    MAX_BYTES_PRIORS,
    MODULE_ORDER,
    MODULOS_EXCLUIDOS,
    OUTPUT_PATH,
    PACKAGE_DIR,
    URL_REPO_PUBLICO,
    claves_de_memorizacion,
    construir_fuente,
    verificar_priors,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def test_fuente_generada_sin_imports_relativos_y_compila() -> None:
    fuente = construir_fuente()
    assert "from ." not in fuente, "quedo un import relativo sin desmontar"
    compile(fuente, "<my_agent>", "exec")


def test_todo_modulo_del_paquete_viaja_o_esta_excluido_con_razon() -> None:
    """El defecto real que motiva este test: BL.21590 agrego direction_beliefs.py y el viejo
    build_notebook.py no lo sumo a MODULE_ORDER -- el .ipynb generado moria con NameError donde
    nadie debuguea. Un modulo nuevo TIENE que declararse: o viaja, o se excluye con razon."""
    en_paquete = {
        str(ruta.relative_to(PACKAGE_DIR)).replace("\\", "/")
        for ruta in PACKAGE_DIR.rglob("*.py")
        if ruta.name != "__init__.py"  # barrels: en el archivo plano no hay paquetes
    }
    declarados = set(MODULE_ORDER) | set(MODULOS_EXCLUIDOS)
    sin_declarar = en_paquete - declarados
    assert not sin_declarar, (
        f"modulos de arc_agent/ sin declarar en el build: {sorted(sin_declarar)} -- "
        "sumalos a MODULE_ORDER (viajan) o a MODULOS_EXCLUIDOS (con la razon)."
    )
    assert not set(MODULE_ORDER) & set(MODULOS_EXCLUIDOS), "un modulo no puede viajar Y estar excluido"
    faltantes = declarados - en_paquete
    assert not faltantes, f"el build declara modulos que ya no existen: {sorted(faltantes)}"


def test_los_modulos_excluidos_no_viajan_en_el_entregable() -> None:
    fuente = construir_fuente()
    for modulo in MODULOS_EXCLUIDOS:
        assert f"arc_agent/{modulo} " not in fuente, f"{modulo} esta excluido pero viaja igual"
    # Los simbolos estrella de la orquestacion propia tampoco pueden colarse por otra via.
    for simbolo in ("class PrometheusOfflineAgent", "def run_swarm", "def play_game", "class LocalGameEnvironment"):
        assert simbolo not in fuente, f"{simbolo} pertenece a un modulo excluido del entregable"


def test_contrato_oficial_presente_en_el_entregable() -> None:
    fuente = construir_fuente()
    assert "class MyAgent(Agent):" in fuente, "el framework registra la clase por nombre exacto"
    assert "from agents.agent import Agent" in fuente
    assert "from arcengine import" in fuente, "los tipos del wire son los de arcengine, no el mirror"


def test_header_abre_con_licencia_mit0_y_repo_publico() -> None:
    """El archivo generado es LO UNICO que Kaggle ve, y el ARC Prize exige la solucion abierta
    bajo licencia permisiva antes de la evaluacion privada: la licencia viaja EN el archivo."""
    encabezado = "".join(construir_fuente().splitlines(keepends=True)[:30])
    assert "SPDX-License-Identifier: MIT-0" in encabezado
    assert URL_REPO_PUBLICO in encabezado
    assert "GENERADO" in encabezado, "quien lo abra tiene que saber que no se edita a mano"


def test_agente_commiteado_sincronizado_con_el_build() -> None:
    """`agent/my_agent.py` se commitea (play_local y el notebook lo consumen tal cual): si alguien
    toca arc_agent/ sin regenerar, lo que se prueba local deja de ser lo que se entrega."""
    assert OUTPUT_PATH.exists(), "falta agent/my_agent.py: correr `make agente`"
    assert OUTPUT_PATH.read_text(encoding="utf-8") == construir_fuente(), (
        "agent/my_agent.py quedo viejo respecto de arc_agent/: correr `make agente` y commitear."
    )


def test_ningun_nombre_top_level_se_repite_entre_modulos() -> None:
    """En el entregable TODOS los modulos comparten un unico namespace: dos definiciones top-level
    con el mismo nombre no dan error, la segunda simplemente pisa a la primera y el modulo de mas
    arriba queda usando la clase/funcion equivocada en runtime. Es un fallo SILENCIOSO (el paquete
    Python sigue funcionando perfecto, porque ahi cada modulo tiene su namespace) que solo aparece
    dentro del archivo generado -- justo donde no hay quien lo debuguee. Caso real: el nodo de
    busqueda de world_model/synthesis.py y el de world_model/planner.py se llamaban los dos
    `_SearchNode` con campos distintos."""
    definiciones: dict[str, str] = {}
    colisiones: list[str] = []
    for filename in MODULE_ORDER:
        tree = ast.parse((PACKAGE_DIR / filename).read_text(encoding="utf-8"))
        for node in tree.body:
            nombres: list[str] = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                nombres = [node.name]
            elif isinstance(node, ast.Assign):
                nombres = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                nombres = [node.target.id]
            for nombre in nombres:
                previo = definiciones.get(nombre)
                if previo is not None:
                    colisiones.append(f"{nombre}: {previo} y {filename}")
                definiciones[nombre] = filename
    assert not colisiones, "nombres top-level repetidos en el namespace plano: " + "; ".join(
        colisiones
    )


"""BL.21560 -- EL GATE: el build no puede producir un entregable cuyos priors memoricen una partida.

POR QUE ES UN GATE Y NO UN LINT. Los juegos de evaluacion del ARC Prize son DISTINTOS de los
publicos por diseno: todo lo que este indexado por game_id o por firma de estado vale exactamente
cero ahi. La tentacion de guardar "lo que funciono en ft09" entra sola en un archivo GENERADO --
nadie lee un diff de numeros -- asi que la unica defensa que funciona es que el entregable no se
pueda construir. Los casos de abajo son las DOS formas concretas de memorizar que existen hoy: la
clave game_id (`ft09-0d8bbf25`) y la firma de estado (entero FNV de 32 bits, `3567569901`).
"""


@pytest.mark.parametrize(
    "clave",
    [
        '"ft09-0d8bbf25"',  # game_id de la corrida real que genero el corpus
        '"lp85-305b61c3"',  # game_id de cuatro alfanumericos
        '"ka59-38d34dbb"',
        '"3567569901"',  # firma de estado observada en arcReplayFrames, como cadena
        "3567569901",  # la misma, como entero
        "70000",  # entero cualquiera dentro del rango de una firma de 32 bits
    ],
)
def test_el_build_falla_si_los_priors_memorizan_una_partida(clave: str) -> None:
    fuente = f"CLICK_PRIORS = {{\n    'porPartida': {{{clave}: [1.0, 2.0]}},\n}}\n"
    assert claves_de_memorizacion(fuente), f"{clave} deberia detectarse como memorizacion"
    with pytest.raises(ValueError, match="memorizan una partida"):
        verificar_priors(fuente)


@pytest.mark.parametrize(
    "clave",
    [
        '"pesosClick"',  # las claves reales del contrato
        '"ordenAcciones"',
        '"ACTION6"',  # nombre de accion: se parece a un id pero no matchea el patron
        "6",  # entero chico: un indice de accion o de color, no una firma
        "65535",  # justo debajo del piso de firma
    ],
)
def test_el_gate_no_confunde_una_clave_legitima_con_memorizacion(clave: str) -> None:
    """Contracara obligatoria: un gate que rechaza todo no protege nada, molesta."""
    fuente = f"CLICK_PRIORS = {{{clave}: 1}}\n"
    assert claves_de_memorizacion(fuente) == []


def test_el_gate_deja_pasar_los_priors_reales() -> None:
    """Contracara obligatoria: un gate que rechaza todo no protege nada, molesta."""
    fuente = (PACKAGE_DIR / ARCHIVO_DE_PRIORS).read_text(encoding="utf-8")
    assert claves_de_memorizacion(fuente) == []
    verificar_priors(fuente)  # no lanza
    assert len(fuente.encode("utf-8")) < MAX_BYTES_PRIORS


def test_el_gate_falla_si_los_priors_se_pasan_del_techo_de_tamano() -> None:
    relleno = "# " + "x" * MAX_BYTES_PRIORS + "\nCLICK_PRIORS = {}\n"
    with pytest.raises(ValueError, match="techo"):
        verificar_priors(relleno)


def test_orden_de_modulos_respeta_las_dependencias() -> None:
    # BL.21701: el reloj abre el archivo. No depende de nada (stdlib pura) y su marca de tiempo se
    # toma al importarse, asi que cuanto antes, mas fiel es el arranque del reloj al del agente.
    assert MODULE_ORDER[0] == "reloj_presupuesto.py"
    assert MODULE_ORDER[1] == "types.py"
    assert MODULE_ORDER[2] == ARCHIVO_DE_PRIORS
    assert MODULE_ORDER.index("click_targeting.py") < MODULE_ORDER.index("policy.py")
    assert MODULE_ORDER.index("direction_beliefs.py") < MODULE_ORDER.index("policy.py")
    assert MODULE_ORDER[-1] == "kaggle_adapter.py", "el wrapper del contrato cierra el archivo"


def test_build_agent_script_escribe_python_valido() -> None:
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "submission" / "build_agent.py")],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert OUTPUT_PATH.exists()
    compile(OUTPUT_PATH.read_text(encoding="utf-8"), str(OUTPUT_PATH), "exec")


def test_entregable_ejecuta_de_punta_a_punta_con_el_framework_real() -> None:
    """Reemplazo del viejo test de ejecucion del notebook: exec del archivo generado COMPLETO con
    `arcengine` y `agents` reales, una decision de MyAgent incluida. Es el test que habria cazado
    el NameError de direction_beliefs. Se skipea limpio sin el dataset (CI): correr `make setup`
    y `make test` para ejercitarlo."""
    pytest.importorskip("arcengine", reason="arcengine no instalado: correr `make setup` + `make test`")
    from starter_config import VENDOR_DIR, faltantes_para_jugar

    if faltantes_para_jugar():
        pytest.skip("dataset no descargado: correr `make setup`")
    if str(VENDOR_DIR) not in sys.path:
        sys.path.insert(0, str(VENDOR_DIR))
    pytest.importorskip("agents.agent", reason="framework vendorizado no importable: correr `make setup`")

    import arcengine

    fuente = construir_fuente()
    namespace: dict[str, object] = {"__name__": "entregable_kaggle"}
    exec(  # noqa: S102 -- codigo propio, generado por construir_fuente()
        compile(fuente, "<my_agent>", "exec", dont_inherit=True), namespace
    )

    clase = namespace["MyAgent"]
    clase.SEMILLA = "test-e2e"  # type: ignore[attr-defined]
    try:
        agente = clase(  # type: ignore[operator]
            card_id="test",
            game_id="ls20",
            agent_name="MyAgent.test",
            ROOT_URL="http://localhost",
            record=False,
            arc_env=None,
        )
        frame = arcengine.FrameData(
            game_id="ls20",
            frame=[[[0] * 8 for _ in range(8)]],
            state=arcengine.GameState.NOT_FINISHED,
            levels_completed=0,
            win_levels=2,
            available_actions=[1, 2, 3, 6],
        )
        assert agente.is_done([frame], frame) is False
        accion = agente.choose_action([frame], frame)
        assert isinstance(accion, arcengine.GameAction)
        ganado = arcengine.FrameData(game_id="ls20", state=arcengine.GameState.WIN)
        assert agente.is_done([frame, ganado], ganado) is True
    finally:
        clase.SEMILLA = None  # type: ignore[attr-defined]
