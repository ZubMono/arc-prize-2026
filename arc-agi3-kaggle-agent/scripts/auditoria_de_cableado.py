"""[arc-agi3-kaggle-agent/scripts/auditoria_de_cableado] BL.21763 -- ANTES DE CREER UN NUMERO,
PROBAR QUE EL CODIGO QUE LO PRODUCE SE EJECUTA.

POR QUE EXISTE. En BL.21704 el gate de merge dio 4,00 -> 4,00 (delta +0,00) y la lectura natural
habria sido "la palanca no paga". Un verificador adversarial encontro que el camino al planner era
CODIGO MUERTO: nadie llamaba a `submetas()`, asi que el gate midio un no-op. El empate no era
evidencia de nada. Una medicion sobre codigo desconectado no es conservadora: es una conclusion
falsa con forma de rigor.

Este script contesta, con TRAZA DE UNA PARTIDA REAL (no con un grep), tres preguntas que la
re-medicion de BL.21763 da por sentadas:

  1. BL.21701 -- LAS 4000 ACCIONES. Cual es el `MAX_ACTIONS` que el entregable lleva puesto, y
     se puede pedir MAS que el entregado (el `min()` que se saco de `play_local.py:164` hacia que
     pedir 800 dejara 400, o sea que medir por encima del valor entregado era imposible).
  2. BL.21701 -- EL RELOJ. `is_done` consulta al reloj UNA VEZ POR ACCION, y el reloj
     efectivamente CORTA una partida cuando el presupuesto se acaba (`cortada_por_reloj`).
  3. BL.21741 -- LA FIRMA COMPUESTA. `detectar_mecanica`/`firma_de_mecanica`/`firma_compuesta`
     corren DENTRO del lazo de decision de una partida real (no solo en los tests ni en el
     analisis offline del corpus), y producen firmas `compuesta:` distintas.

COMO LO PRUEBA: espia las funciones en el MODULO del entregable (`agent/my_agent.py` se carga por
ruta y todo vive en un solo espacio de nombres, asi que sustituir el atributo del modulo
intercepta la llamada real que hace el lazo). Cuenta llamadas y firmas y las reporta. Cero llamadas
= codigo muerto, y eso seria el hallazgo mas importante de la medicion, no una nota al pie.

DOS CORRECCIONES QUE ESTE MISMO SCRIPT SE TUVO QUE APLICAR, encontradas por un verificador
adversarial sobre su primera version. Un auditor que se equivoca es peor que no tener auditor,
porque su salida se lee como prueba:

  A) EL ALCANCE ERA MUY CHICO Y EL DETECTOR MUY LITERAL. Buscaba `.firma` solo en `arc_agent/`,
     `agent/` y `tests/`, y solo cuando la misma linea traia `==` o `startswith`. Con eso declaraba
     "NADIE lee la firma", cuando `scripts/paso_de_la_maniobra.py:193` la lee con
     `len({p.firma for p in activos})` y tiene test propio. Ahora el barrido es por AST, sobre TODO
     el arbol, y separado por CAPA: `lazoDeLaPartida` (lo unico que corre mientras el agente juega)
     vs `analisisOffline` (`scripts/`, que corre antes o despues) vs `tests`. La conclusion del BL
     sobrevive pero con la unica forma en que es cierta: la firma compuesta NO discrimina ninguna
     decision DE LA PARTIDA, y SI discrimina en el analisis offline. Y eso se PRUEBA, no se supone
     por la carpeta: se verifica ademas que el lazo no importe ningun modulo de `scripts/`.

  B) EL VEREDICTO DE LA TRAZA TENIA DENOMINADOR CERO. `firmaCompuestaLlegaAUnaDecision: false` se
     calculaba sobre las decisiones observadas en la partida... que fueron CERO, porque la traza no
     ejercito ni un predicado. Eso no distingue "la firma no cambia decisiones" de "no se consulto
     ninguna". Ahora el campo es de tres estados y declara el caso vacuo con todas las letras.

USO:
    .venv/bin/python scripts/auditoria_de_cableado.py --json runtime_reports/cableado.json
"""
from __future__ import annotations

import argparse
import ast
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from play_local import (  # noqa: E402  (necesita el sys.path de arriba)
    cargar_modulo_agente,
    configurar_reloj,
    preparar_entorno,
)
from starter_config import ENVIRONMENTS_DIR  # noqa: E402

#: Juego de la traza. vc33 sube de nivel en pocas acciones (medido: nivel 1 en el paso 2), asi que
#: una partida corta ya ejercita la transicion de nivel -- que es justo el instante donde BL.21741
#: dice que la percepcion era ciega. Un juego que nunca sube no probaria nada de eso.
JUEGO_DE_LA_TRAZA = "vc33"

#: Acciones de la traza de cableado. No es una medicion de score: alcanza con que el lazo corra.
ACCIONES_DE_LA_TRAZA = 40

#: Presupuesto (en horas) del ensayo que tiene que hacer CORTAR al reloj. Chico a proposito: la
#: prueba es que el corte ocurre, no cuanto tarda. El margen de cierre se escala solo con el
#: presupuesto (`FRACCION_MAXIMA_DEL_MARGEN`), asi que un presupuesto chico no corta en la accion
#: cero.
HORAS_DEL_ENSAYO_DE_CORTE = 6.0 / 3600.0


def _espiar_percepcion(modulo) -> dict:
    """Sustituye las tres funciones de BL.21741 en el modulo del entregable por envoltorios que
    cuentan. Devuelve el registro que se va llenando durante la partida."""
    registro = {
        "llamadasADetectarMecanica": 0,
        "llamadasAFirmaDeMecanica": 0,
        "llamadasAFirmaCompuesta": 0,
        "tiposDeMecanica": {},
        "firmas": {},
    }
    detectar, firma, compuesta = (
        modulo.detectar_mecanica,
        modulo.firma_de_mecanica,
        modulo.firma_compuesta,
    )

    def detectar_espiada(*args, **kwargs):
        registro["llamadasADetectarMecanica"] += 1
        mecanica = detectar(*args, **kwargs)
        tipos = registro["tiposDeMecanica"]
        tipos[mecanica.tipo] = tipos.get(mecanica.tipo, 0) + 1
        return mecanica

    def firma_espiada(mecanica):
        registro["llamadasAFirmaDeMecanica"] += 1
        etiqueta = firma(mecanica)
        firmas = registro["firmas"]
        firmas[etiqueta] = firmas.get(etiqueta, 0) + 1
        return etiqueta

    def compuesta_espiada(mecanica):
        registro["llamadasAFirmaCompuesta"] += 1
        return compuesta(mecanica)

    modulo.detectar_mecanica = detectar_espiada
    modulo.firma_de_mecanica = firma_espiada
    modulo.firma_compuesta = compuesta_espiada
    return registro


def _espiar_consumo_de_la_firma(modulo) -> dict:
    """Cuenta si la firma de mecanica LLEGA A UNA DECISION, no solo si se calcula.

    ESTA ES LA PREGUNTA QUE BL.21704 NO SE HIZO. Que `firma_compuesta` corra prueba que el codigo
    esta vivo; no prueba que su resultado se LEA. Los dos unicos predicados que leen la firma
    acumulada por accion son `get_direction` (exige `traslacion:`) e `is_inert_action` (exige
    `sinCambio`): se anota, por cada consulta, que firma tenia la hipotesis y que contesto el
    predicado, para poder decir con numeros si una firma `compuesta:` cambio alguna decision."""
    registro = {
        "consultasAHipotesis": 0,
        "hipotesisConFirmaCompuesta": 0,
        "consultasAGetDirection": 0,
        "consultasAIsInertAction": 0,
        "decisionesQueUnaFirmaCompuestaCambio": 0,
    }
    memoria = modulo.MechanicsMemory
    hipotesis, direccion, inerte = (
        memoria.get_hypothesis,
        memoria.get_direction,
        memoria.is_inert_action,
    )

    def hipotesis_espiada(self, accion):
        registro["consultasAHipotesis"] += 1
        salida = hipotesis(self, accion)
        if salida is not None and str(salida.firma).startswith("compuesta:"):
            registro["hipotesisConFirmaCompuesta"] += 1
        return salida

    def direccion_espiada(self, accion):
        registro["consultasAGetDirection"] += 1
        salida = direccion(self, accion)
        actual = hipotesis(self, accion)
        if salida is not None and actual is not None and str(actual.firma).startswith("compuesta:"):
            registro["decisionesQueUnaFirmaCompuestaCambio"] += 1
        return salida

    def inerte_espiada(self, accion):
        registro["consultasAIsInertAction"] += 1
        salida = inerte(self, accion)
        actual = hipotesis(self, accion)
        if salida and actual is not None and str(actual.firma).startswith("compuesta:"):
            registro["decisionesQueUnaFirmaCompuestaCambio"] += 1
        return salida

    memoria.get_hypothesis = hipotesis_espiada
    memoria.get_direction = direccion_espiada
    memoria.is_inert_action = inerte_espiada
    return registro


#: Las CAPAS del arbol, porque "produccion" no es una sola cosa y confundirlas produjo un falso
#: negativo grave en la primera version de este BL.
#:   - `lazoDeLaPartida`: el paquete fuente y el entregable generado. Lo unico que corre MIENTRAS
#:     el agente juega, o sea lo unico que puede cambiar una decision de la partida.
#:   - `analisisOffline`: `scripts/`. Corre ANTES o DESPUES de jugar (caracteriza el corpus, deriva
#:     el vocabulario de objetivos, mide). Sus lecturas de la firma son reales y cambian
#:     conclusiones -- pero no cambian lo que el agente hace en una accion.
#:   - `tests`: no deciden nada; se cuentan aparte.
#: La version anterior tenia RAICES = (arc_agent, agent, tests) y por eso declaraba "NADIE lee la
#: firma" cuando `scripts/paso_de_la_maniobra.py` la lee de verdad. El alcance ahora es TODO el
#: arbol y la distincion se hace explicita en la salida, no por omision.
CAPAS_DEL_CODIGO = {
    "lazoDeLaPartida": ("arc_agent", "agent"),
    "analisisOffline": ("scripts",),
    "tests": ("tests",),
}

#: Predicados de produccion que leen la firma ACUMULADA por accion y solo pueden reaccionar a un
#: prefijo/igualdad fija. Una etiqueta `compuesta:...` no satisface ninguno.
LECTURAS_CIEGAS_A_LA_FIRMA_COMPUESTA = ("traslacion:", "sinCambio")


#: BL.21800 -- EL ATRIBUTO `.firma` ESTA SOBRECARGADO EN ESTE ARBOL Y EL AUDITOR NO LO SABIA.
#: `mechanics_memory.Mechanic.firma` es `str` (la firma COMPUESTA que este BL mide) y
#: `regiones_de_cambio.Region.firma` es `int` (un bitmask de celdas). Al ensanchar el detector de
#: "`.firma` con `==`/`startswith` en la misma linea" a un walk AST por nombre de atributo, entraron
#: las lecturas del bitmask; como la clasificacion final se decide por el TEXTO de la linea
#: (`_es_ciega_a_la_firma_compuesta` busca `traslacion:`/`sinCambio`), ninguna de ellas parece ciega
#: y todas cuentan como "discrimina". Medido antes del fix:
#: `firmaCompuestaDiscriminaEnElLazoDeLaPartida = True` con 14 supuestas discriminantes, de las
#: cuales CERO son la firma de mecanica -- son `pendiente = region.firma`,
#: `(origen.firma & solo_izquierda).bit_count()`, etc. O sea que el auditor afirmaba lo CONTRARIO del
#: hallazgo de BL.21763 que su propio docstring dice preservar, y el aviso "CABLEADO PARTIDO" de
#: `main()` (que esta detras de `if not estaticos[...]`) no se imprimia nunca.
TIPO_DE_LA_FIRMA_COMPUESTA = "str"


def _clases_con_firma(raiz: Path) -> dict[str, dict]:
    """Clase -> {tipo de su campo `firma`, conjunto de sus campos}, sobre TODO el arbol. Se lee la
    anotacion real: es la unica forma de separar dos atributos que se llaman igual."""
    fuera: dict[str, dict] = {}
    for carpetas in CAPAS_DEL_CODIGO.values():
        for carpeta in carpetas:
            for ruta in sorted((raiz / carpeta).rglob("*.py")):
                if not ruta.is_file():
                    continue
                try:
                    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
                except SyntaxError:  # pragma: no cover
                    continue
                for nodo in ast.walk(arbol):
                    if not isinstance(nodo, ast.ClassDef):
                        continue
                    campos = {
                        c.target.id
                        for c in nodo.body
                        if isinstance(c, ast.AnnAssign) and isinstance(c.target, ast.Name)
                    }
                    if "firma" not in campos:
                        continue
                    tipo = next(
                        _nombre_de_tipo(c.annotation)
                        for c in nodo.body
                        if isinstance(c, ast.AnnAssign)
                        and isinstance(c.target, ast.Name)
                        and c.target.id == "firma"
                    )
                    fuera[nodo.name] = {"tipoDeFirma": tipo, "campos": campos}
    return fuera


def _nombre_de_tipo(anotacion: ast.expr | None) -> str:
    """Nombre de la clase de una anotacion, desarmando `X | None` y `Optional[X]`. '' si no se puede."""
    if anotacion is None:
        return ""
    if isinstance(anotacion, ast.Name):
        return anotacion.id
    if isinstance(anotacion, ast.Constant) and isinstance(anotacion.value, str):
        return anotacion.value.split("|")[0].strip()
    if isinstance(anotacion, ast.Attribute):
        return anotacion.attr
    if isinstance(anotacion, ast.BinOp) and isinstance(anotacion.op, ast.BitOr):
        izq = _nombre_de_tipo(anotacion.left)
        return izq if izq and izq != "None" else _nombre_de_tipo(anotacion.right)
    if isinstance(anotacion, ast.Subscript):
        base = _nombre_de_tipo(anotacion.value)
        if base in {"Optional", "list", "List"}:
            return _nombre_de_tipo(anotacion.slice)
        return base
    return ""


def _atributos_por_receptor(arbol: ast.AST) -> dict[str, set[str]]:
    """Nombre de variable -> todos los atributos que se le leen en el archivo. `self` incluido."""
    fuera: dict[str, set[str]] = {}
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Attribute):
            continue
        base = nodo.value
        nombre = (
            base.id if isinstance(base, ast.Name)
            else base.attr if isinstance(base, ast.Attribute)
            else ""
        )
        if nombre:
            fuera.setdefault(nombre, set()).add(nodo.attr)
    return fuera


def _clase_por_huella(atributos: set[str], clases: dict[str, dict]) -> str:
    """Clase del receptor por HUELLA DE CAMPOS: la que contiene MAS de los atributos observados.

    BL.21800 -- por que la huella y no una inferencia de tipos. Resolver `h` en
    `h = self.get_hypothesis(a)` requeriria seguir el retorno de cada funcion a traves de alias,
    parametros y comprensiones; una version a medias de eso es un proxy sintactico que se lee como
    prueba, que es EL modo de falla que este script existe para no cometer. La huella, en cambio, es
    una medicion directa: `h.traslacion/.observaciones/.cobertura/.firma` solo encaja en
    `HipotesisDeMecanica`, y `origen.firma/.celdas/...` solo en `RegionDeCambio`. Empate o cero
    coincidencias fuera de `firma` -> '' (no resuelto), y lo no resuelto se REPORTA, nunca se cuenta.
    """
    mejor, puntaje, empate = "", 0, False
    for nombre, info in clases.items():
        coincidencias = len(atributos & info["campos"])
        if coincidencias > puntaje:
            mejor, puntaje, empate = nombre, coincidencias, False
        elif coincidencias == puntaje and puntaje > 0 and nombre != mejor:
            empate = True
    if empate or puntaje <= 1:  # solo `firma` en comun no distingue nada
        return ""
    return mejor


def _lecturas_de_la_firma(ruta: Path) -> list[tuple[int, str]]:
    """Toda lectura del atributo `.firma` en un archivo, por AST y no por texto.

    POR QUE AST. El detector anterior solo reconocia `.firma` en la misma linea que un `==` o un
    `startswith`, asi que una comprension de conjunto -- `len({p.firma for p in activos})`, que es
    exactamente como la lee `es_animacion_en_loop` -- era INVISIBLE. Un auditor que mide un proxy
    sintactico y se lee como prueba es el modo de falla de BL.21704 aplicado al auditor mismo."""
    try:
        arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover -- ningun archivo del arbol la tiene
        return []
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    atributos = _atributos_por_receptor(arbol)
    encontradas: list[tuple[int, str, str, set[str]]] = []
    for nodo in ast.walk(arbol):
        if (
            isinstance(nodo, ast.Attribute)
            and nodo.attr == "firma"
            and isinstance(nodo.ctx, ast.Load)
        ):
            numero = nodo.lineno
            texto = lineas[numero - 1].strip() if 0 < numero <= len(lineas) else ""
            # BL.21800: de que CLASE es este `.firma`. `` = no se pudo resolver.
            receptor = nodo.value
            base = receptor.id if isinstance(receptor, ast.Name) else (
                receptor.attr if isinstance(receptor, ast.Attribute) else ""
            )
            encontradas.append((numero, texto, base, atributos.get(base, set())))
    return encontradas


def _es_ciega_a_la_firma_compuesta(texto: str) -> bool:
    """La lectura solo puede reaccionar a un prefijo o igualdad fija que una etiqueta `compuesta:`
    nunca satisface. Ante la duda devuelve False -- el sesgo va a declarar que SI discrimina, para
    que el auditor nunca vuelva a subestimar el cableado."""
    return any(marca in texto for marca in LECTURAS_CIEGAS_A_LA_FIRMA_COMPUESTA)


def _modulos_de_scripts_importados_por_el_lazo(raiz: Path) -> list[str]:
    """Modulos de `scripts/` que el lazo de la partida importa. Si la lista esta vacia, ninguna
    lectura de `analisisOffline` puede correr durante una partida -- y eso hay que PROBARLO, no
    suponerlo por la ubicacion del archivo."""
    nombres = {ruta.stem for ruta in (raiz / "scripts").glob("*.py")}
    importados: set[str] = set()
    for carpeta in CAPAS_DEL_CODIGO["lazoDeLaPartida"]:
        for ruta in (raiz / carpeta).rglob("*.py"):
            try:
                arbol = ast.parse(ruta.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.Import):
                    importados.update(a.name.split(".")[0] for a in nodo.names)
                elif isinstance(nodo, ast.ImportFrom) and nodo.module:
                    importados.add(nodo.module.split(".")[0])
    return sorted(importados & nombres)


def _auditar_consumidores_estaticos() -> dict:
    """Cuenta LLAMADORES, no definiciones, sobre TODO el arbol y separando por capa. La traza de una
    partida corta puede no ejercitar un camino y eso no prueba que el camino este muerto; que NADIE
    lo llame en todo el arbol, si.

    Es el mismo instrumento que encontro el codigo muerto de BL.21704 (`submetas()` definida y sin
    llamadores), corregido por dos agujeros que un verificador adversarial encontro en el:
      1. el alcance excluia `scripts/`, donde vive un consumidor REAL de la firma
         (`es_animacion_en_loop`, con test propio en `test_bl21765_semantica_del_saldo.py`);
      2. el detector solo veia `.firma` junto a `==` o `startswith`, asi que una comprension de
         conjunto no contaba.
    Las dos cosas juntas producian el veredicto "nadie la lee", que era falso."""
    raiz = Path(__file__).resolve().parents[1]
    por_capa: dict[str, list[str]] = {capa: [] for capa in CAPAS_DEL_CODIGO}
    discriminantes: dict[str, list[str]] = {capa: [] for capa in CAPAS_DEL_CODIGO}
    # BL.21800: lo que NO es la firma compuesta (el bitmask de Region) y lo que no se pudo tipar.
    otra_firma: dict[str, list[str]] = {capa: [] for capa in CAPAS_DEL_CODIGO}
    sin_tipar: dict[str, list[str]] = {capa: [] for capa in CAPAS_DEL_CODIGO}
    clases_con_firma = _clases_con_firma(raiz)
    llamadores_de_get_mechanic: list[str] = []
    revisados = 0
    for capa, carpetas in CAPAS_DEL_CODIGO.items():
        for carpeta in carpetas:
            for ruta in sorted((raiz / carpeta).rglob("*.py")):
                if not ruta.is_file():
                    continue
                revisados += 1
                relativa = str(ruta.relative_to(raiz))
                for numero, texto, base, atributos in _lecturas_de_la_firma(ruta):
                    etiqueta = f"{relativa}:{numero}: {texto}"
                    por_capa[capa].append(etiqueta)
                    clase = _clase_por_huella(atributos, clases_con_firma)
                    tipo = clases_con_firma.get(clase, {}).get("tipoDeFirma", "")
                    if not clase or not tipo:
                        # No se pudo tipar el receptor: se REPORTA, no se cuenta. El sesgo optimista
                        # ("ante la duda, discrimina") es lo que invirtio el veredicto.
                        sin_tipar[capa].append(f"{etiqueta}  [receptor '{base}' sin tipar]")
                        continue
                    if tipo != TIPO_DE_LA_FIRMA_COMPUESTA:
                        otra_firma[capa].append(f"{etiqueta}  [{clase}.firma: {tipo}]")
                        continue
                    if not _es_ciega_a_la_firma_compuesta(texto):
                        discriminantes[capa].append(etiqueta)
                for numero, linea in enumerate(
                    ruta.read_text(encoding="utf-8").splitlines(), 1
                ):
                    pelada = linea.strip()
                    if "get_mechanic(" in pelada and not pelada.startswith("def "):
                        llamadores_de_get_mechanic.append(f"{relativa}:{numero}: {pelada}")
    puente = _modulos_de_scripts_importados_por_el_lazo(raiz)
    return {
        "archivosRevisados": revisados,
        "llamadoresDeGetMechanic": len(llamadores_de_get_mechanic),
        "detalleDeLlamadoresDeGetMechanic": llamadores_de_get_mechanic,
        "lecturasDeLaFirmaPorCapa": {capa: sorted(v) for capa, v in por_capa.items()},
        "lecturasQueDiscriminanFirmasCompuestasPorCapa": {
            capa: sorted(v) for capa, v in discriminantes.items()
        },
        # BL.21800 -- lo que el veredicto DESCARTA, explicito para que nadie tenga que confiar.
        "clasesQueDeclaranFirma": {
            n: i["tipoDeFirma"] for n, i in clases_con_firma.items()
        },
        "lecturasDeOtraFirmaPorCapa": {capa: sorted(v) for capa, v in otra_firma.items()},
        "lecturasConReceptorSinTiparPorCapa": {capa: sorted(v) for capa, v in sin_tipar.items()},
        # EL VEREDICTO, PARTIDO EN DOS PORQUE SON DOS PREGUNTAS DISTINTAS.
        "firmaCompuestaDiscriminaEnElLazoDeLaPartida": bool(discriminantes["lazoDeLaPartida"]),
        "firmaCompuestaDiscriminaEnElAnalisisOffline": bool(discriminantes["analisisOffline"]),
        # Y la prueba de que la segunda no se cuela en la primera: si el lazo no importa ningun
        # modulo de `scripts/`, esas lecturas no pueden ejecutarse durante una partida.
        "modulosDeScriptsImportadosPorElLazo": puente,
        "elAnalisisOfflineNoCorreDuranteLaPartida": not puente,
    }


def _jugar(arcade, clase_agente, juego: str, semilla: str):
    """Una partida con la clase del entregable, sin tocar la clase mas que la semilla."""
    entorno = arcade.make(juego, render_mode=None)
    if entorno is None:
        raise SystemExit(f"[auditoria] no se pudo crear el entorno de {juego!r}.")
    clase_agente.SEMILLA = semilla
    agente = clase_agente(
        card_id="auditoria-de-cableado",
        game_id=juego,
        agent_name=f"MyAgent.auditoria.{juego}",
        ROOT_URL="http://localhost",
        record=False,
        arc_env=entorno,
        tags=["auditoria-de-cableado"],
    )
    agente.main()
    return agente


def auditar(arcade, modulo) -> dict:
    clase = modulo.MyAgent
    entregado = {
        "maxActionsDelEntregable": int(clase.MAX_ACTIONS),
        "cotaDeSeguridadDeAcciones": int(modulo.COTA_DE_SEGURIDAD_DE_ACCIONES),
        "presupuestoPorDefectoSegundos": float(modulo.PRESUPUESTO_POR_DEFECTO_SEGUNDOS),
        "muroDelNotebookSegundos": float(modulo.MURO_DEL_NOTEBOOK_SEGUNDOS),
    }

    # --- 1) se puede PEDIR mas que lo entregado (el min() que saco BL.21701) ------------------
    from play_local import aplicar_tope_de_pasos

    vigente = aplicar_tope_de_pasos(clase, entregado["maxActionsDelEntregable"] * 2)
    entregado["pedirElDobleDeja"] = int(vigente)
    entregado["sePuedeMedirPorEncimaDeLoEntregado"] = (
        int(vigente) > entregado["maxActionsDelEntregable"]
    )

    # --- 2) traza con el reloj APAGADO: cuenta consultas y firmas ------------------------------
    percepcion = _espiar_percepcion(modulo)
    consumo = _espiar_consumo_de_la_firma(modulo)
    reloj_apagado = configurar_reloj(modulo, 1, 0.0)
    consultas = {"n": 0}
    original_debe_cortar = reloj_apagado.debe_cortar

    def debe_cortar_espiado(*args, **kwargs):
        consultas["n"] += 1
        return original_debe_cortar(*args, **kwargs)

    reloj_apagado.debe_cortar = debe_cortar_espiado
    aplicar_tope_de_pasos(clase, ACCIONES_DE_LA_TRAZA)
    agente = _jugar(arcade, clase, JUEGO_DE_LA_TRAZA, "auditoria-de-cableado")
    ultimo = agente.frames[-1]

    # COPIA, no referencia: el ensayo de corte que viene despues sigue usando los MISMOS
    # espias, y un dict compartido haria que la traza reportara conteos de una partida que
    # todavia no ocurrio -- evidencia falsa del tipo que este script existe para evitar.
    firmas = dict(percepcion.pop("firmas"))
    percepcion = {
        clave: dict(valor) if isinstance(valor, dict) else valor
        for clave, valor in percepcion.items()
    }
    compuestas = {k: v for k, v in firmas.items() if k.startswith("compuesta:")}
    traza = {
        "juego": JUEGO_DE_LA_TRAZA,
        "accionesJugadas": int(agente.action_counter),
        "nivelesAlCerrar": int(ultimo.levels_completed),
        "consultasAlReloj": consultas["n"],
        "firmasDeMecanicaDistintas": len(firmas),
        "firmasCompuestasDistintas": len(compuestas),
        "muestraDeFirmasCompuestas": sorted(compuestas)[:5],
        "firmasDeEstadoDistintas": int(agente._politica._novedad.firmas_distintas()),
        **percepcion,
    }
    consumo = dict(consumo)
    # EL DENOMINADOR, DECLARADO. Un "no cambio ninguna decision" calculado sobre CERO consultas no
    # dice que la firma no importe: dice que la traza no ejercito ni un predicado, y las dos cosas
    # son distintas. Publicar un booleano ahi era el modo de falla de BL.21704 aplicado al propio
    # auditor. Por eso el veredicto de la TRAZA es de tres estados y el peso lo lleva la auditoria
    # estatica, que no depende de que camino ejercito una partida de 40 acciones.
    consultas = (
        consumo["consultasAHipotesis"]
        + consumo["consultasAGetDirection"]
        + consumo["consultasAIsInertAction"]
    )
    consumo["consultasATodosLosPredicados"] = consultas
    if consultas == 0:
        consumo["firmaCompuestaLlegaAUnaDecision"] = (
            "sinConsultas: la traza no ejercito NINGUN predicado que lea la firma, asi que este "
            "veredicto es vacuo. Lo que decide es `consumidoresEstaticos`."
        )
    elif consumo["decisionesQueUnaFirmaCompuestaCambio"] > 0:
        consumo["firmaCompuestaLlegaAUnaDecision"] = "si"
    else:
        consumo["firmaCompuestaLlegaAUnaDecision"] = "no"
    consumo["consumidoresEstaticos"] = _auditar_consumidores_estaticos()

    # --- 3) ensayo de corte: el reloj TIENE que cortar la partida ------------------------------
    reloj_corto = configurar_reloj(modulo, 1, HORAS_DEL_ENSAYO_DE_CORTE)
    aplicar_tope_de_pasos(clase, entregado["maxActionsDelEntregable"])
    agente_cortado = _jugar(arcade, clase, JUEGO_DE_LA_TRAZA, "auditoria-de-corte")
    corte = {
        "presupuestoSegundos": round(HORAS_DEL_ENSAYO_DE_CORTE * 3600.0, 3),
        "topeDeAcciones": entregado["maxActionsDelEntregable"],
        "accionesJugadas": int(agente_cortado.action_counter),
        "cortadaPorReloj": bool(agente_cortado.cortada_por_reloj),
        "estadoDelReloj": reloj_corto.estado(),
    }

    veredicto = {
        "bl21701_topeDe4000Cableado": entregado["maxActionsDelEntregable"] == 4000,
        "bl21701_relojConsultadoPorAccion": traza["consultasAlReloj"] >= traza["accionesJugadas"],
        "bl21701_relojCortaDeVerdad": corte["cortadaPorReloj"]
        and corte["accionesJugadas"] < corte["topeDeAcciones"],
        "bl21701_mediblePorEncimaDeLoEntregado": entregado["sePuedeMedirPorEncimaDeLoEntregado"],
        "bl21741_percepcionCorreEnElLazo": traza["llamadasADetectarMecanica"] > 0,
        "bl21741_firmaCompuestaCorreEnElLazo": traza["llamadasAFirmaCompuesta"] > 0,
        "bl21741_firmaCompuestaProduceEtiquetas": traza["firmasCompuestasDistintas"] > 0,
    }
    # Estos DOS no entran en `todoCableado` porque no son fallas del instrumento: son el HALLAZGO.
    # `todoCableado` responde "puedo creerle a los numeros que voy a medir"; el cableado partido de
    # la firma compuesta responde "a que se le puede atribuir un movimiento de categoria".
    hallazgo = {
        "bl21741_firmaCompuestaDiscriminaEnElLazoDeLaPartida": consumo["consumidoresEstaticos"][
            "firmaCompuestaDiscriminaEnElLazoDeLaPartida"
        ],
        "bl21741_firmaCompuestaDiscriminaEnElAnalisisOffline": consumo["consumidoresEstaticos"][
            "firmaCompuestaDiscriminaEnElAnalisisOffline"
        ],
        "bl21741_elAnalisisOfflineNoCorreDuranteLaPartida": consumo["consumidoresEstaticos"][
            "elAnalisisOfflineNoCorreDuranteLaPartida"
        ],
    }
    return {
        "entregado": entregado,
        "traza": traza,
        "consumoDeLaFirma": consumo,
        "ensayoDeCorteDelReloj": corte,
        "veredicto": veredicto,
        "hallazgoDeCableado": hallazgo,
        "todoCableado": all(veredicto.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="BL.21763 -- prueba con traza que el reloj, las 4000 acciones y la firma "
        "compuesta se EJECUTAN en el lazo del entregable."
    )
    parser.add_argument("--json", default=None, help="Ruta donde dejar el informe.")
    parser.add_argument("--modo", default="offline", choices=["offline", "normal"])
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    preparar_entorno()

    import arc_agi
    from arc_agi import OperationMode

    modo = OperationMode.OFFLINE if args.modo == "offline" else OperationMode.NORMAL
    arcade = arc_agi.Arcade(operation_mode=modo, environments_dir=str(ENVIRONMENTS_DIR))
    informe = auditar(arcade, cargar_modulo_agente())

    print("\n========= AUDITORIA DE CABLEADO (BL.21763) =========")
    print(json.dumps(informe, indent=1, sort_keys=True, ensure_ascii=False))
    if args.json:
        destino = Path(args.json)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(informe, indent=1, sort_keys=True), encoding="utf-8")
        print(f"\nInforme escrito en {destino}")

    estaticos = informe["consumoDeLaFirma"]["consumidoresEstaticos"]
    if not estaticos["firmaCompuestaDiscriminaEnElLazoDeLaPartida"]:
        print(
            "\nAVISO -- CABLEADO PARTIDO DE BL.21741, con la distincion que importa:\n"
            "  * EN EL LAZO DE LA PARTIDA (arc_agent/ + agent/) la firma compuesta se CALCULA y se "
            "GUARDA en cada paso, pero ninguna decision la lee como discriminador: `get_mechanic` "
            "-- unico acceso a la hipotesis con su firma -- no tiene llamadores, y los dos "
            "predicados que si leen la firma exigen `traslacion:` o `sinCambio`, que una etiqueta "
            "`compuesta:` nunca cumple. Ningun movimiento de categoria del mapa puede atribuirsele.\n"
            f"  * EN EL ANALISIS OFFLINE (scripts/) SI discrimina: "
            f"{len(estaticos['lecturasQueDiscriminanFirmasCompuestasPorCapa']['analisisOffline'])} "
            "lectura(s), entre ellas `es_animacion_en_loop`, que decide con "
            "`len({p.firma for p in activos})` y tiene test propio. Eso cambia el vocabulario de "
            "objetivos que se deriva del corpus, no lo que el agente hace en una accion.\n"
            "  * La mitad de BL.21741 que SI cambia decisiones DENTRO de la partida es "
            "`TIPO_SIN_MEDICION`, que `direction_beliefs` lee para no contar el silencio como "
            "quietud."
        )
    if not informe["todoCableado"]:
        fallados = [k for k, v in informe["veredicto"].items() if not v]
        print(f"\nCABLEADO INCOMPLETO: {fallados}. NINGUN numero medido sobre esto es evidencia.")
        return 1
    print("\nCABLEADO COMPLETO: los tres mecanismos corren en el lazo de una partida real.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
