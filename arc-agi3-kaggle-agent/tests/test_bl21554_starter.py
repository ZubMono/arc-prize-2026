"""[arc-agi3-kaggle-agent/tests/test_bl21554_starter] BL.21554 -- contrato de la cadena de entrega
adoptada del starter oficial de Kaggle.

QUE PROTEGE. Este BL es el primer eslabon de la cadena que termina en una submission (BL.21555 ->
BL.21556), y sus modos de falla son silenciosos y caros: un `requires-python` desalineado hace que
`make setup` explote recien al instalar, un placeholder olvidado en la metadata hace que Kaggle
rechace el push, un acelerador en GPU quema cuota que este agente no usa, y un activo del dataset
sin gitignorear mete cientos de MB de terceros en un repo que se abre publico.

AISLAMIENTO. Nada de lo que se afirma aca toca la red ni depende de que el dataset este bajado:
los tests que SI necesitan el dataset (el loop local contra juegos reales) se skipean limpio
cuando no esta, para que CI no dependa de un token ni de 42 MB de descarga."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# Los scripts del andamiaje se importan por ruta (no son un paquete instalable): hay que poner su
# directorio en sys.path para que resuelvan `starter_config` entre ellos.
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def cargar_script(nombre: str) -> ModuleType:
    """Importa `scripts/<nombre>.py` como modulo, sin ejecutar su `main()`."""
    spec = importlib.util.spec_from_file_location(nombre, SCRIPTS_DIR / f"{nombre}.py")
    assert spec is not None and spec.loader is not None
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def config() -> ModuleType:
    return cargar_script("starter_config")


@pytest.fixture(scope="module")
def constructor() -> ModuleType:
    return cargar_script("build_kernel_notebook")


def test_pyproject_exige_python_312() -> None:
    """El motor de juego oficial (`arc-agi`) exige 3.12: declarar menos rompe `make setup`."""
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["requires-python"] == ">=3.12"


def test_metadata_del_kernel_lista_para_publicar(config: ModuleType) -> None:
    """La metadata no puede tener el placeholder del starter ni pedir GPU/internet."""
    metadata = json.loads(config.KERNEL_METADATA_PATH.read_text(encoding="utf-8"))
    crudo = config.KERNEL_METADATA_PATH.read_text(encoding="utf-8")

    assert config.PLACEHOLDER_USUARIO not in crudo, "el Makefile se niega a publicar con el placeholder"
    assert metadata["id"].startswith("luisignaciomoreno/")
    assert config.usuario_kaggle() == "luisignaciomoreno"
    assert metadata["code_file"] == "submission.ipynb"
    assert metadata["enable_internet"] is False, "la competencia corre sin internet"
    assert metadata["enable_gpu"] is False, "el agente no usa ML: la GPU es cuota desperdiciada"
    assert metadata["is_private"] is False, (
        "BL.21556: el kernel se publica PUBLICO — abrir la solucion es requisito del ARC Prize "
        "para ser evaluado, y el repo github.com/ZubMono/arc-prize-2026 ya es publico."
    )
    assert config.slug_competencia() == "arc-prize-2026-arc-agi-3"


def test_acelerador_en_cpu(constructor: ModuleType) -> None:
    """`ACELERADOR` es la fuente unica y tiene que estar en cpu."""
    assert constructor.ACELERADOR == "cpu"
    kaggle = constructor.construir()["metadata"]["kaggle"]
    assert kaggle["accelerator"] == "none"
    assert kaggle["isGpuEnabled"] is False
    assert kaggle["isInternetEnabled"] is False


def test_acelerador_y_metadata_no_pueden_divergir(constructor: ModuleType, config: ModuleType) -> None:
    """`enable_gpu` de la metadata deriva de `ACELERADOR`, no se escribe a mano."""
    metadata = json.loads(config.KERNEL_METADATA_PATH.read_text(encoding="utf-8"))
    assert metadata["enable_gpu"] == constructor.ACELERADORES[constructor.ACELERADOR]["gpu"]


def test_notebook_arma_el_patron_oficial(constructor: ModuleType, config: ModuleType) -> None:
    """El notebook instala offline, inlinea el agente y lo corre como `myagent` en el gateway."""
    notebook = constructor.construir()
    fuentes = [celda["source"] for celda in notebook["cells"]]
    unido = "\n".join(fuentes)
    slug = config.slug_competencia()

    assert f"/kaggle/input/competitions/{slug}/arc_agi_3_wheels" in unido
    assert "--no-index" in unido, "en Kaggle no hay internet: las wheels salen del dataset"
    assert "%%writefile /tmp/my_agent.py" in unido, "el agente NO puede quedar como output del notebook"
    assert "--agent myagent" in unido
    assert "submission.parquet" in unido
    # El cuerpo del agente viaja tal cual: una copia divergente seria un agente distinto al probado.
    assert "class MyAgent(Agent):" in unido


def test_agente_cumple_el_contrato_del_framework(config: ModuleType) -> None:
    """`agent/my_agent.py` define `MyAgent` con `is_done` y `choose_action` (contrato oficial).

    Se verifica sobre el AST y no importando el modulo a proposito: importarlo exigiria tener
    `arcengine` y el framework instalados, y este test tiene que correr en CI sin dataset."""
    import ast

    arbol = ast.parse(config.AGENT_SRC_PATH.read_text(encoding="utf-8"))
    clases = {nodo.name: nodo for nodo in ast.walk(arbol) if isinstance(nodo, ast.ClassDef)}
    assert "MyAgent" in clases, "el framework registra la clase por nombre exacto"
    metodos = {n.name for n in clases["MyAgent"].body if isinstance(n, ast.FunctionDef)}
    assert {"is_done", "choose_action"} <= metodos


def test_gitignore_cubre_los_activos_descargados() -> None:
    """Nada de lo que baja del dataset puede entrar al repo."""
    ignorado = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    entradas = {linea.strip() for linea in ignorado if linea.strip() and not linea.startswith("#")}
    for esperado in (
        ".venv/",
        "vendor/",
        "environment_files/",
        "wheels/",
        ".cache/",
        ".kaggle/",
        "notebooks/submission.ipynb",
    ):
        assert esperado in entradas, f"{esperado} tiene que estar gitignoreado"


def test_faltantes_reporta_lo_que_falta(config: ModuleType, tmp_path: Path, monkeypatch) -> None:
    """`faltantes_para_jugar` es el detector que usan el loop local y los skips de estos tests."""
    monkeypatch.setattr(config, "VENDOR_DIR", tmp_path / "sin-framework")
    monkeypatch.setattr(config, "ENVIRONMENTS_DIR", tmp_path / "sin-juegos")
    assert len(config.faltantes_para_jugar()) == 2


def test_instalacion_offline_en_x86_y_pypi_en_otras_arquitecturas(monkeypatch) -> None:
    """En x86_64 (la de Kaggle) todo sale del dataset; en otras se cae a PyPI para lo binario."""
    instalador = cargar_script("install_arc_agi")
    if not instalador.WHEELS_DIR.is_dir():
        pytest.skip("wheels/ no esta: correr `make setup` para bajarlas del dataset")

    monkeypatch.setattr(instalador.platform, "machine", lambda: "x86_64")
    assert "--no-index" in instalador.comando_de_instalacion()

    monkeypatch.setattr(instalador.platform, "machine", lambda: "aarch64")
    comando = instalador.comando_de_instalacion()
    assert "--no-index" not in comando
    assert any(arg.endswith(".whl") and "arc_agi-" in arg for arg in comando)


def test_framework_vendorizado_quedo_adelgazado(config: ModuleType) -> None:
    """Sin el recorte, importar el framework arrastra langgraph/smolagents y el loop no arranca."""
    if config.faltantes_para_jugar():
        pytest.skip("dataset no descargado: correr `make setup`")
    recortador = cargar_script("slim_framework")
    assert recortador.INIT_PATH.read_text(encoding="utf-8") == recortador.CONTENIDO_ADELGAZADO


def test_loop_local_corre_contra_un_juego_real(config: ModuleType) -> None:
    """Prueba de vida de la cadena: el agente juega un juego REAL de punta a punta, sin red.

    Se skipea limpio si falta el dataset o el venv del proyecto -- CI no baja 42 MB ni necesita
    token para el resto de la suite."""
    if config.faltantes_para_jugar():
        pytest.skip("dataset no descargado: correr `make setup`")
    if not config.VENV_PYTHON.exists():
        pytest.skip("no hay venv del proyecto: correr `make setup`")

    proceso = subprocess.run(
        [
            str(config.VENV_PYTHON),
            str(SCRIPTS_DIR / "play_local.py"),
            "--juego",
            "ls20",
            "--max-pasos",
            "5",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proceso.returncode == 0, proceso.stderr[-2000:]
    salida = proceso.stdout
    assert "=== [1/1] ls20 ===" in salida
    assert "RESUMEN" in salida
    assert "Puntaje agregado de la tarjeta:" in salida
