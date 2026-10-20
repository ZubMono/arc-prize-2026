"""[tests/test_bl21741_fragmentacion_de_la_memoria] BL.21741 (correccion) -- QUE LE HACE LA FIRMA
COMPUESTA AL UNICO CONSUMIDOR DE PRODUCCION DE LA FIRMA: `MechanicsMemory`.

EL DEFECTO QUE CUBREN ESTOS TESTS (medido en la refutacion de BL.21741). `firma_de_mecanica` no es
solo la etiqueta del informe: es la CLAVE sobre la que `MechanicsMemory` acumula la Beta por accion,
y `get_hypothesis` devuelve la firma MAS OBSERVADA. Antes de BL.21741 TODO frame heterogeneo caia en
un unico bucket "desconocida" que podia GANAR el argmax; con la firma compuesta ese bucket se parte
en una firma por composicion, asi que una firma `traslacion:` puede pasar a ganar donde antes perdia
contra la masa desconocida. Replay del corpus persistido por `MechanicsMemory` (firma legada contra
firma vigente, al MISMO tope): 9 de 25 pares (ventana, accion) cambian la firma DOMINANTE, los
buckets de firma pasan de 98 a 109 y la cobertura del dominante cae hasta 0,5. El commit e5892b0d0a
midio el radio de explosion del TOPE (6 de 272 pares cambian de firma, 0 pasan a `traslacion`) pero
NO el de la FIRMA sobre el argmax, y ningun test lo fijaba.

QUE FIJAN, entonces: (1) que la fragmentacion ocurre -- no es teorica; (2) que lo unico que impide
que una traslacion minoritaria se lleve el mando es el piso `MIN_COBERTURA_DE_MECANICA`, con lo cual
bajarlo se pone rojo; (3) que `get_mechanic` expone la hipotesis SIN ese piso, que es la puerta por
la que el efecto llegaria a una decision el dia que alguien la use.

CONTEXTO MEDIDO (BL.21763, cruzado en esta correccion y sin cambios tras arreglar el motor TS):
`TransitionMemory.get_mechanic` -- el unico acceso a la hipotesis CON su firma -- no tiene ni un
llamador en `arc_agent/`, `agent/` ni `tests/` fuera de estos contratos, y los dos predicados que si
leen la firma en produccion exigen `traslacion:` (get_direction) o `== "sinCambio"`
(is_inert_action), que una etiqueta `compuesta:` no puede satisfacer. O sea: el poder discriminativo
de la firma compuesta se calcula, se guarda y HOY no llega a ninguna decision. Lo mismo vale del
lado TypeScript tras el puerto: `getMechanic` tampoco tiene llamadores y `getDirection`/
`isInertAction` filtran igual. Es instrumentacion, no score -- y eso hay que decirlo con numeros en
vez de dejarlo implicito.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arc_agent.world_model.mechanics_memory import (  # noqa: E402
    MIN_COBERTURA_DE_MECANICA,
    MIN_OBSERVACIONES_DE_MECANICA,
    MechanicsMemory,
)
from arc_agent.world_model.mechanics_signature import firma_de_mecanica  # noqa: E402
from arc_agent.world_model.object_mechanics import detectar_mecanica  # noqa: E402

FONDO = 0
LADO = 24


def _lienzo() -> list[list[int]]:
    return [[FONDO] * LADO for _ in range(LADO)]


def _mezcla(color_a: int, color_b: int, clusters: int) -> tuple[list[list[int]], list[list[int]]]:
    """Par (pre, post) HETEROGENEO: `clusters` clusters que el detector no puede nombrar con un
    solo par (desde -> hasta), mas una aparicion. Distintas cantidades dan firmas compuestas
    distintas -- que es exactamente lo que fragmenta el bucket."""
    pre, post = _lienzo(), _lienzo()
    for i in range(clusters):
        y = 2 * i
        pre[y][0], pre[y][1] = 3, 3
        post[y][0], post[y][1] = color_a, color_b
    pre[LADO - 1][LADO - 1] = FONDO
    post[LADO - 1][LADO - 1] = 5
    return pre, post


def _traslacion() -> tuple[list[list[int]], list[list[int]]]:
    pre, post = _lienzo(), _lienzo()
    for dy in range(2):
        pre[4 + dy][4], pre[4 + dy][5] = 7, 7
        post[4 + dy][5], post[4 + dy][6] = 7, 7
    return pre, post


def _firma_legada(pre: list[list[int]], post: list[list[int]]) -> str:
    """La firma ANTERIOR a BL.21741: toda mezcla heterogenea era la misma palabra."""
    firma = firma_de_mecanica(detectar_mecanica(pre, post))
    return "desconocida" if firma.startswith("compuesta:") else firma


def test_la_firma_compuesta_fragmenta_el_bucket_desconocida() -> None:
    """Tres mezclas que el vocabulario viejo metia en UN bucket hoy son tres firmas distintas."""
    mezclas = [_mezcla(7, 9, n) for n in (1, 4, 10)]
    legadas = {_firma_legada(pre, post) for pre, post in mezclas}
    vigentes = {firma_de_mecanica(detectar_mecanica(pre, post)) for pre, post in mezclas}

    assert legadas == {"desconocida"}, "el reproductor del vocabulario viejo dejo de colapsar"
    assert len(vigentes) == 3, f"la firma compuesta no fragmenta: {vigentes}"
    assert all(f.startswith("compuesta:") for f in vigentes)


def test_una_traslacion_minoritaria_no_se_lleva_el_mando_por_la_fragmentacion() -> None:
    """EL RIESGO CONCRETO, y lo unico que lo contiene.

    Cinco observaciones de la misma accion: 2 traslaciones iguales y 3 mezclas DISTINTAS entre si.
    Con el vocabulario viejo las 3 mezclas eran un solo bucket "desconocida" (3) que le ganaba a la
    traslacion (2). Con la firma compuesta las mezclas valen 1 cada una y la traslacion pasa a ser
    el ARGMAX con cobertura 0,4 -- o sea que `get_hypothesis` cambia de respuesta. El mando NO
    cambia solo por `MIN_COBERTURA_DE_MECANICA`: 0,4 < 0,6. Bajar ese piso pone rojo este test, que
    es exactamente la senal que faltaba."""
    memoria = MechanicsMemory()
    for _ in range(2):
        memoria.observe("ACTION1", *_traslacion())
    for n in (1, 4, 10):
        memoria.observe("ACTION1", *_mezcla(7, 9, n))

    hipotesis = memoria.get_hypothesis("ACTION1")
    assert hipotesis is not None
    assert hipotesis.firma.startswith("traslacion:"), (
        "la fragmentacion deberia dejar a la traslacion como firma mas observada: "
        f"salio {hipotesis.firma}"
    )
    assert hipotesis.observaciones == 5
    assert abs(hipotesis.cobertura - 0.4) < 1e-9
    assert hipotesis.cobertura < MIN_COBERTURA_DE_MECANICA

    # El piso es lo unico que separa "la firma dominante es una traslacion" de "el mando cree que
    # esta accion mueve en esa direccion".
    assert memoria.get_direction("ACTION1") is None
    assert memoria.get_movement_actions() == []
    assert memoria.is_inert_action("ACTION1") is False


def test_con_evidencia_suficiente_la_traslacion_si_manda() -> None:
    """El riesgo simetrico: el piso no puede volverse un tapon. Con cobertura por encima del piso y
    observaciones suficientes, la direccion sale."""
    memoria = MechanicsMemory()
    for _ in range(4):
        memoria.observe("ACTION2", *_traslacion())
    memoria.observe("ACTION2", *_mezcla(7, 9, 4))

    hipotesis = memoria.get_hypothesis("ACTION2")
    assert hipotesis is not None
    assert hipotesis.cobertura >= MIN_COBERTURA_DE_MECANICA
    assert hipotesis.observaciones >= MIN_OBSERVACIONES_DE_MECANICA
    assert memoria.get_direction("ACTION2") == (0, 1)


def test_get_mechanic_expone_la_hipotesis_SIN_el_piso_y_hoy_no_tiene_llamadores() -> None:
    """LA PUERTA POR LA QUE EL EFECTO LLEGARIA A UNA DECISION.

    `TransitionMemory.get_mechanic` devuelve el argmax crudo, sin `MIN_COBERTURA_DE_MECANICA` y sin
    minimo de observaciones. Medido en BL.21763 y re-verificado en esta correccion: no tiene ni un
    llamador de produccion, ni de este lado ni del TypeScript. Este test deja el contrato escrito --
    quien lo use tiene que poner su propio piso -- y si manana `get_mechanic` empezara a filtrar por
    su cuenta, se pone rojo y obliga a decidirlo a proposito."""
    from arc_agent.world_model.transition_memory import TransitionMemory

    memoria = TransitionMemory()
    for _ in range(2):
        pre, post = _traslacion()
        memoria.record_observation("ACTION1", pre, post)
    for n in (1, 4, 10):
        pre, post = _mezcla(7, 9, n)
        memoria.record_observation("ACTION1", pre, post)

    hipotesis = memoria.get_mechanic("ACTION1")
    assert hipotesis is not None
    assert hipotesis.firma.startswith("traslacion:")
    assert hipotesis.cobertura < MIN_COBERTURA_DE_MECANICA  # el piso NO se aplica aca
    # ...y el consumidor que si lo aplica sigue diciendo que no sabe.
    assert memoria.get_movement_direction("ACTION1") is None


def test_ninguna_firma_compuesta_puede_satisfacer_a_los_lectores_de_produccion() -> None:
    """LA CUENTA QUE DEFINE SI BL.21741 PUEDE PAGAR EN SCORE HOY: no puede, y por construccion.

    Los dos unicos predicados de produccion que leen la firma exigen prefijo `traslacion:` o
    igualdad con `sinCambio`. Una etiqueta `compuesta:...` no cumple ninguno de los dos, asi que las
    7 firmas distintas que BL.21741 recupero son instrumentacion mientras nadie use `get_mechanic`
    ni baje el piso. Fijarlo como test evita que la afirmacion se degrade a una nota de commit."""
    memoria = MechanicsMemory()
    for n in (1, 4, 10, 4, 1):
        memoria.observe("ACTION6", *_mezcla(7, 9, n))

    hipotesis = memoria.get_hypothesis("ACTION6")
    assert hipotesis is not None
    assert hipotesis.firma.startswith("compuesta:")
    assert not hipotesis.firma.startswith("traslacion:")
    assert hipotesis.firma != "sinCambio"
    assert memoria.get_direction("ACTION6") is None
    assert memoria.is_inert_action("ACTION6") is False
