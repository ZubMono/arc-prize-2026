"""[arc-agi3-kaggle-agent/submission/build_agent] BL.21555 -- genera el ENTREGABLE real de la
competencia: UN solo `agent/my_agent.py` con el nucleo de `arc_agent/` inlineado mas el wrapper
`MyAgent` del contrato oficial. Ese archivo es lo UNICO que Kaggle ve: el kernel lo escribe via
`%%writefile` (ver scripts/build_kernel_notebook.py) y el framework oficial lo registra como
`myagent`.

Correr: `python3 submission/build_agent.py` (o `make agente`) -- regenera `agent/my_agent.py`.
NO editar el archivo generado a mano: editar el paquete fuente (`arc_agent/`) y regenerar.

LA FRONTERA (que viaja y que no). Viaja el nucleo de decision completo (`MODULE_ORDER`) mas
`kaggle_adapter.py`, que es el unico modulo que habla los tipos de `arcengine`. NO viajan
(`MODULOS_EXCLUIDOS`): la orquestacion propia (swarm/runner/runtime_report) porque el framework
oficial trae la suya, el mirror `agent.py` y `prometheus_agent.py` porque `MyAgent` los reemplaza
bajo el contrato real, y `local_harness.py` porque es un juego de juguete para tests. Esos modulos
SIGUEN en el repo: los usan los tests locales y `scripts/verify_no_network.py`. `types.py` en
cambio SI viaja -- dejo de ser un mirror del wire para ser la representacion INTERNA que consume
la politica; el adaptador traduce desde `arcengine` hacia ella.

Historia: hasta BL.21554 este modulo se llamaba build_notebook.py y emitia un .ipynb de 30+
celdas que ningun eslabon oficial consumia. El notebook real lo arma build_kernel_notebook.py
inlineando el my_agent.py que se genera aca."""
from __future__ import annotations

import ast
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = PROJECT_ROOT / "arc_agent"
OUTPUT_PATH = PROJECT_ROOT / "agent" / "my_agent.py"

#: Repo publico donde se abre el codigo (requisito del ARC Prize para ser evaluado). FUENTE UNICA
#: del link que viaja en el header del entregable; BL.21556 crea el repo con este slug -- si el
#: slug final difiere, se cambia ACA y se regenera.
URL_REPO_PUBLICO = "https://github.com/ZubMono/arc-prize-2026"

# Orden de dependencias: cada modulo solo importa (relativamente) de los que aparecen ANTES en
# esta lista. En el archivo generado todos comparten un unico namespace plano.
MODULE_ORDER = [
    # BL.21701 -- EL SEGURO DE LAS 9 HORAS. Va PRIMERO porque no depende de nada (stdlib pura) y
    # porque su marca de tiempo se toma al importarse: cuanto antes en el archivo, mas fiel es el
    # arranque del reloj al arranque real del agente. Que este en MODULE_ORDER es el punto entero
    # del BL: el otro numero de 9 h del repo (runtime_report.py) esta EXCLUIDO y nunca viajo, asi
    # que en Kaggle no habia ningun deadline -- el Swarm oficial tampoco trae uno.
    "reloj_presupuesto.py",
    # Representacion interna de la politica (frames hasheables, enums de accion/estado). Dejo de
    # ser "mirror del wire": el wire real lo habla kaggle_adapter.py con los tipos de arcengine.
    "types.py",
    # BL.21560 -- conocimiento pre-computado offline (pesos del ranker de coordenadas, umbrales
    # medidos, orden de acciones). Va JUSTO despues de types.py: no depende de nada y lo consumen
    # tanto exploration_memory.py como click_targeting.py.
    "priors.py",
    # BL.21702 -- REGISTRO DE PALANCAS. Stdlib pura, sin dependencias, y lo consumen casi todos los
    # modulos de decision (memoria de clicks, macro, libro de aperturas, detector de congelamiento y
    # la politica). Su lectura de `ARC_AGENT_BANDERAS` ocurre al importarse; en Kaggle la variable no
    # existe y rige el default (todas encendidas), asi que el entregable viaja con las palancas
    # puestas -- el interruptor existe para medir cada una por separado, no para entregar apagado.
    "banderas.py",
    # Motor de modelo de mundo (world_model/): orden topologico de su grafo de dependencias --
    # grid <- volatility_mask, grid <- primitive_ops <- primitives, y (BL.21561)
    # object_geometry <- object_mechanics <- mechanics_memory + program_coverage <- synthesis <-
    # transition_memory (que ademas depende de volatility_mask, BL.21558), con planner/
    # state_signature dependiendo solo de grid. `world_model/__init__.py` queda AFUERA a
    # proposito: es un barrel de re-exports y en el archivo plano no hay paquetes.
    "world_model/grid.py",
    "world_model/volatility_mask.py",
    "world_model/primitive_ops.py",
    "world_model/primitives.py",
    "world_model/object_geometry.py",
    "world_model/object_mechanics.py",
    # BL.21741 (correccion): la capa de VOCABULARIO (firma_de_mecanica / firma_compuesta /
    # es_firma_de_silencio) salio de object_mechanics.py, que cruzaba el limite de 500 lineas.
    # Va DESPUES de object_mechanics (importa `Mecanica` y `TIPOS_DE_NO_MIRE`) y ANTES de
    # mechanics_memory, que acumula la Beta por firma.
    "world_model/mechanics_signature.py",
    # BL.21704 -- causa a distancia (boton que abre puerta). Los cuatro van DESPUES de
    # object_mechanics: regiones_de_cambio corre `detectar_mecanica` para excluir lo que el
    # vocabulario LOCAL ya explica, estadistica_de_coocurrencia no depende de nada,
    # evidencia_relacional depende de grid + regiones_de_cambio, y relaciones_no_locales de los
    # tres. Es un almacen APARTE: no toca `MECANICAS` de mechanics_posterior.py, que es el
    # vocabulario de mapeo boton->direccion y esta pinneado flotante a flotante contra el puerto TS.
    "world_model/regiones_de_cambio.py",
    "world_model/estadistica_de_coocurrencia.py",
    "world_model/evidencia_relacional.py",
    "world_model/relaciones_no_locales.py",
    "world_model/mechanics_memory.py",
    "world_model/program_coverage.py",
    "world_model/synthesis.py",
    "world_model/transition_memory.py",
    "world_model/planner.py",
    "world_model/state_signature.py",
    "prng.py",
    # BL.21559: macro-acciones y novedad por estado -- antes de policy.py, que las instancia.
    "exploration_memory.py",
    # BL.21560: features de celda y plantillas + memoria de clicks. Antes de policy.py.
    "click_features.py",
    "click_targeting.py",
    # BL.21593: percepcion de pared/avatar (termino observable del fallo) y el posterior
    # jerarquico boton->mecanica. wall_perception solo depende de priors + world_model;
    # mechanics_posterior importa de wall_perception; direction_beliefs de ambos.
    "wall_perception.py",
    "mechanics_posterior.py",
    # BL.21590: prior de direcciones + incognitas de ACTION5/7, y el libro de aperturas que
    # depende de ellas. Antes de policy.py, que los instancia. (En el viejo build_notebook.py
    # direction_beliefs.py FALTABA: el .ipynb generado moria con NameError en
    # CreenciaDeDirecciones -- defecto que motivo el test de ejecucion e2e.)
    "direction_beliefs.py",
    "opening_book.py",
    # BL.21702: detector de estado congelado y disparador del RESET voluntario. Depende solo de
    # banderas.py; policy.py lo instancia.
    "estado_congelado.py",
    "policy.py",
    # BL.21555: el wrapper del contrato oficial. AL FINAL: importa todo lo anterior y es el unico
    # que habla `arcengine`/`agents` (imports absolutos, que el entorno de ejecucion provee).
    "kaggle_adapter.py",
]

#: Modulos de `arc_agent/` que NO viajan al entregable, con su razon. Quedan en el repo porque
#: los tests locales y scripts/verify_no_network.py los siguen usando (ver docstring del modulo).
MODULOS_EXCLUIDOS: dict[str, str] = {
    "agent.py": "mirror del contrato: MyAgent hereda del Agent REAL del framework oficial",
    "prometheus_agent.py": "subclase del mirror; kaggle_adapter.MyAgent es su reemplazo oficial",
    "swarm.py": "el framework oficial trae su propio Swarm y orquesta los juegos el",
    "runner.py": "el loop de juego lo maneja Agent.main() del framework oficial",
    "runtime_report.py": "reporteria del runner propio; el gateway de Kaggle emite el parquet",
    "local_harness.py": "juego de juguete para tests/smoke local, jamas fue parte del entregable",
}

_RELATIVE_IMPORT_RE = re.compile(r"^from \.\w* import .+$", re.MULTILINE)
_FUTURE_IMPORT_RE = re.compile(r"^from __future__ import .+\n?", re.MULTILINE)

#: BL.21560 -- forma de un game_id de ARC-AGI-3: tres o cuatro alfanumericos, guion, ocho digitos
#: hexadecimales (ej. `ft09-0d8bbf25`).
_GAME_ID_RE = re.compile(r"^[0-9a-z]{3,4}-[0-9a-f]{8}$", re.IGNORECASE)

#: Piso a partir del cual un entero (o una cadena de digitos) empieza a parecer una FIRMA DE ESTADO
#: y no un parametro: las firmas son hashes FNV de 32 bits, uniformes en [0, 2^32). 65536 deja pasar
#: cualquier constante plausible (tamanos, umbrales x1000, contadores) y atrapa todo lo demas.
_PISO_DE_FIRMA = 1 << 16
_TECHO_DE_FIRMA = 1 << 32

#: Fuente unica del archivo de priors, para que el gate y el orden de modulos no puedan divergir.
ARCHIVO_DE_PRIORS = "priors.py"

#: Tope de tamano de priors.py inlineado en el entregable. 2MB es un techo de INGENIERIA, no de
#: politica: por encima de eso el archivo se vuelve incomodo de abrir y revisar, y un archivo de
#: pesos que crece asi ya dejo de ser un prior para ser una tabla de memorizacion.
MAX_BYTES_PRIORS = 2 * 1024 * 1024


def claves_de_memorizacion(source: str) -> list[str]:
    """Claves de `priors.py` que MEMORIZAN una partida en vez de describir una regularidad.

    POR QUE ES UN GATE DEL BUILD Y NO UN LINT. Los juegos de evaluacion del ARC Prize son distintos
    de los publicos por diseno: todo lo que este indexado por game_id o por firma de estado vale
    exactamente cero ahi, y ademas ocupa lugar y da una falsa sensacion de conocimiento. La
    tentacion entra sola en un archivo GENERADO -- nadie lo lee en un diff -- asi que la unica
    defensa que funciona es que el entregable no se pueda construir.

    Se recorren TODAS las claves de diccionario del modulo, a cualquier profundidad. Son las claves
    y no los valores a proposito: memorizar es INDEXAR por partida, y un valor grande puede ser
    legitimo (`nTransicionesObservadas` crece con el corpus). Devuelve la lista de claves ofensivas;
    vacia = limpio."""
    ofensivas: list[str] = []

    def sospechosa(valor: object) -> bool:
        if isinstance(valor, bool):
            return False
        if isinstance(valor, int):
            return _PISO_DE_FIRMA <= valor < _TECHO_DE_FIRMA
        if isinstance(valor, str):
            if _GAME_ID_RE.match(valor):
                return True
            if valor.isdigit() and _PISO_DE_FIRMA <= int(valor) < _TECHO_DE_FIRMA:
                return True
        return False

    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        for clave in node.keys:
            if isinstance(clave, ast.Constant) and sospechosa(clave.value):
                ofensivas.append(repr(clave.value))

    return ofensivas


def verificar_priors(source: str, nombre: str = ARCHIVO_DE_PRIORS) -> None:
    """Falla el build si `priors.py` memoriza una partida o se paso del techo de tamano."""
    ofensivas = claves_de_memorizacion(source)
    if ofensivas:
        raise ValueError(
            f"[build_agent] {nombre} tiene {len(ofensivas)} clave(s) que memorizan una partida "
            f"(game_id o firma de estado): {', '.join(sorted(set(ofensivas))[:10])}. "
            "Los juegos de evaluacion son otros: eso no generaliza. Regenerar los priors con "
            "scripts/fit_click_priors.py sin indexar por partida."
        )
    bytes_priors = len(source.encode("utf-8"))
    if bytes_priors > MAX_BYTES_PRIORS:
        raise ValueError(
            f"[build_agent] {nombre} pesa {bytes_priors} bytes y el techo es {MAX_BYTES_PRIORS}: "
            "un prior que crece asi ya es una tabla de memorizacion."
        )


def _strip_module_source(source: str) -> str:
    """Quita imports relativos (`from .foo import bar`) y `from __future__ import annotations` --
    en el archivo final todo vive en un unico namespace compartido, y el proyecto ya requiere
    Python >= 3.12 (sintaxis `X | None` nativa, sin necesitar el future import)."""
    source = _RELATIVE_IMPORT_RE.sub("", source)
    source = _FUTURE_IMPORT_RE.sub("", source)
    return source.strip() + "\n"


def _encabezado() -> str:
    """Header del entregable: licencia MIT-0 completa + link al repo publico + aviso de generado.

    Es lo primero que ve cualquiera que abra el archivo en Kaggle -- y el requisito del ARC Prize
    es que la solucion este abierta bajo licencia permisiva ANTES de la evaluacion privada."""
    return (
        "# =============================================================================\n"
        "# Prometheus -- agente offline para ARC Prize 2026 (track ARC-AGI-3)\n"
        "#\n"
        "# SPDX-License-Identifier: MIT-0\n"
        "# Copyright 2026 ZubMono\n"
        "#\n"
        "# MIT No Attribution: se concede permiso, sin cargo, a cualquier persona que\n"
        "# obtenga una copia de este software y su documentacion asociada, para usarlo\n"
        "# sin restriccion, incluyendo sin limitacion los derechos de usar, copiar,\n"
        "# modificar, fusionar, publicar, distribuir, sublicenciar y/o vender copias.\n"
        "# EL SOFTWARE SE ENTREGA \"TAL CUAL\", SIN GARANTIA DE NINGUN TIPO. Texto\n"
        f"# completo de la licencia: {URL_REPO_PUBLICO}/blob/main/LICENSE\n"
        "#\n"
        f"# Codigo fuente y historia: {URL_REPO_PUBLICO}\n"
        "#\n"
        "# ARCHIVO GENERADO por submission/build_agent.py -- NO editar a mano: editar el\n"
        "# paquete fuente (arc_agent/) y regenerar con `make agente`.\n"
        "# =============================================================================\n"
        '"""Prometheus: politica de exploracion 100% offline (sin LLM en inferencia) para\n'
        "ARC-AGI-3 -- memoria de estados con firma enmascarada, modelo de mundo por sintesis\n"
        "DSL, macro-acciones, ranker de coordenadas de click y prior de direcciones. La clase\n"
        "`MyAgent` (al final del archivo) implementa el contrato del framework oficial\n"
        "`ARC-AGI-3-Agents`; `arcengine` y `agents` los provee el entorno de ejecucion.\"\"\"\n"
    )


def construir_fuente() -> str:
    """Arma el texto completo de `agent/my_agent.py` y corre TODAS las verificaciones del build:
    el gate anti-memorizacion sobre priors.py (BL.21560), que no queden imports relativos, que el
    resultado compile y que el contrato oficial (`class MyAgent(Agent):`) este presente."""
    partes = [_encabezado()]
    for filename in MODULE_ORDER:
        source = (PACKAGE_DIR / filename).read_text(encoding="utf-8")
        if filename == ARCHIVO_DE_PRIORS:
            verificar_priors(source, filename)
        partes.append(
            "\n\n# ============================== arc_agent/"
            + filename
            + " ==============================\n"
            + _strip_module_source(source)
        )

    fuente = "".join(partes)

    if "from ." in fuente:
        linea = next(l for l in fuente.splitlines() if "from ." in l)
        raise ValueError(f"[build_agent] quedo un import relativo sin desmontar: {linea!r}")
    if "class MyAgent(Agent):" not in fuente:
        raise ValueError(
            "[build_agent] el entregable no define `class MyAgent(Agent):` -- el framework "
            "oficial registra la clase por nombre exacto y sin ella la submission no corre."
        )
    compile(fuente, str(OUTPUT_PATH), "exec")  # error de sintaxis = build roto, mejor aca que en Kaggle
    return fuente


def main() -> None:
    fuente = construir_fuente()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(fuente, encoding="utf-8")
    lineas = fuente.count("\n")
    print(f"[build_agent] escrito {OUTPUT_PATH} ({lineas} lineas, {len(MODULE_ORDER)} modulos).")


if __name__ == "__main__":
    main()
