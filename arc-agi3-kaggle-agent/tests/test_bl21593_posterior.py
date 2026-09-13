"""[arc-agi3-kaggle-agent/tests/test_bl21593_posterior] BL.21593 -- contrato del posterior
jerarquico boton->mecanica con verosimilitud que explica el fallo, y de la percepcion de pared.

LOS ESCENARIOS OBLIGATORIOS DEL BL:
  1. mapeo sintetico CONTRARIO al prior -> el posterior remapea (y la creencia tambien);
  2. fallo con pared adyacente -> el posterior del mapeo NO baja (asercion numerica);
  3. el MISMO fallo sin pared -> SI baja (la diferencia entre ambos ES la pared observada);
  4. juego degenerado (nada se mueve) -> no se cuelga y el arquetipo degrada a flechasSinMapeo;
  5. la masa `desconocida` respeta el piso SIEMPRE y se registra cuando acumula;
  6. paridad TS<->Python con magnitudes exactas (seccion PARIDAD, mismos numeros que
     bl21593.posterior.test.ts sobre la misma secuencia guionada).
"""
from __future__ import annotations

import pytest

from arc_agent.direction_beliefs import ESTADO_REMAPEADA, CreenciaDeDirecciones
from arc_agent.mechanics_posterior import (
    ARQUETIPO_MIXTO,
    ARQUETIPO_MUEVE,
    ARQUETIPO_SIN_FLECHAS,
    ARQUETIPO_SIN_MAPEO,
    EVENTO_DESCONOCIDA,
    EVENTO_OTRA,
    EVENTO_SIN_CAMBIO,
    EVENTO_TRASLACION,
    MECANICA_DESCONOCIDA,
    MECANICA_INERTE,
    PISO_DESCONOCIDO,
    UMBRAL_RESOLUCION,
    EventoObservado,
    PosteriorDeMapeo,
    condicional_de_mecanicas,
    prior_de_arquetipos,
)
from arc_agent.wall_perception import (
    PARED_AUSENTE,
    PARED_DESCONOCIDA,
    PARED_PRESENTE,
    RastreadorDeAvatar,
    contexto_de_pared,
    profundidad_de_sondeo,
)
from arc_agent.world_model.object_mechanics import Mecanica, Traslacion

PARED_SOLO_ARRIBA = {
    "arriba": PARED_PRESENTE,
    "abajo": PARED_AUSENTE,
    "izquierda": PARED_AUSENTE,
    "derecha": PARED_AUSENTE,
}
SIN_PARED = {n: PARED_AUSENTE for n in ("arriba", "abajo", "izquierda", "derecha")}


def _traslacion(dy: int, dx: int, en_corrida: bool) -> EventoObservado:
    return EventoObservado(tipo=EVENTO_TRASLACION, signo=(dy, dx), en_corrida=en_corrida)


def _mecanica_de_traslacion(dy: int, dx: int) -> Mecanica:
    t = Traslacion(dy=dy, dx=dx, min_y=5, min_x=5, alto=2, ancho=2, cobertura=1.0, relleno=1.0)
    return Mecanica(
        tipo="traslacion", celdas_cambiadas=8, clusters=[], traslacion_principal=t,
        cambio_de_color_principal=None,
    )


# ── 1. el prior solo JAMAS resuelve; el contrario al prior remapea ────────────────────────────


def test_el_prior_solo_no_resuelve_en_ningun_conjunto_medido() -> None:
    for conjunto in ("1,2,3,4", "1,2,3,4,5", "1,2,3,4,5,6", "1,2,3,4,6", "1,2,3,4,6,7", "3,4,6,7"):
        post = PosteriorDeMapeo()
        post.sembrar(int(n) for n in conjunto.split(","))
        for boton in post.botones:
            dominante = post.mecanica_dominante(boton)
            assert dominante is not None and dominante[1] < UMBRAL_RESOLUCION, (conjunto, boton)
            assert not post.resuelta(boton), (conjunto, boton)


def test_mapeo_contrario_al_prior_remapea_posterior_y_creencia() -> None:
    """Una corrida monotona invertida vence al prior canonico: dominante `abajo` para ACTION1,
    resuelto, y la maquina de estados de BL.21590 remapea igual que antes."""
    creencia = CreenciaDeDirecciones()
    creencia.sembrar((1, 2, 3, 4))
    for _ in range(3):
        creencia.observar("ACTION1", _mecanica_de_traslacion(2, 0))  # abajo, contrario al prior
    assert creencia.estado_de("ACTION1") == ESTADO_REMAPEADA
    assert creencia.direccion_de("ACTION1") == (1, 0)
    dominante = creencia.posterior.mecanica_dominante("ACTION1")
    assert dominante is not None and dominante[0] == "abajo"
    assert dominante[1] >= UMBRAL_RESOLUCION
    assert creencia.posterior.direccion_de("ACTION1") == (1, 0)


def test_una_traslacion_invertida_aislada_no_remapea() -> None:
    """La ambiguedad objeto/hueco invierte lecturas AISLADAS de forma sistematica (medido: 20
    contra 6 en un juego): una sola lectura invertida no puede tumbar el prior."""
    post = PosteriorDeMapeo()
    post.sembrar((1, 2, 3, 4))
    post.observar("ACTION1", _traslacion(1, 0, en_corrida=False))
    dominante = post.mecanica_dominante("ACTION1")
    assert dominante is not None and dominante[0] == "arriba"  # el prior sigue en pie


# ── 2 y 3. la pieza central: el fallo se pondera por cuanto lo explica el mundo ───────────────


def test_fallo_con_pared_adyacente_no_baja_el_posterior_del_mapeo() -> None:
    post = PosteriorDeMapeo()
    post.sembrar((1, 2, 3, 4, 6))
    antes = post.posterior_de("ACTION1")["arriba"]
    post.observar("ACTION1", EventoObservado(tipo=EVENTO_SIN_CAMBIO, pared=PARED_SOLO_ARRIBA))
    despues = post.posterior_de("ACTION1")["arriba"]
    # Numeros exactos (paridad con el puerto TS): el fallo explicado NO cuenta contra el mapeo.
    assert antes == pytest.approx(0.6135416666666667, abs=1e-12)
    assert despues == pytest.approx(0.705098214922535, abs=1e-12)
    assert despues >= antes  # jamas baja: quedo totalmente explicado por la pared


def test_el_mismo_fallo_sin_pared_si_lo_baja() -> None:
    post = PosteriorDeMapeo()
    post.sembrar((1, 2, 3, 4, 6))
    antes = post.posterior_de("ACTION1")["arriba"]
    post.observar("ACTION1", EventoObservado(tipo=EVENTO_SIN_CAMBIO, pared=SIN_PARED))
    despues = post.posterior_de("ACTION1")["arriba"]
    assert despues == pytest.approx(0.19662188014376653, abs=1e-12)
    assert despues < antes - 0.4  # el mundo no explica el fallo: el mapeo carga con el


def test_fallo_con_pared_inobservable_aporta_poco_pero_no_cero() -> None:
    post = PosteriorDeMapeo()
    post.sembrar((1, 2, 3, 4, 6))
    antes = post.posterior_de("ACTION1")["arriba"]
    post.observar("ACTION1", EventoObservado(tipo=EVENTO_SIN_CAMBIO, pared=None))
    despues = post.posterior_de("ACTION1")["arriba"]
    assert despues < antes  # aporta algo...
    assert antes - despues < 0.2  # ...pero mucho menos que el fallo sin pared


# ── 4. juego degenerado: el arquetipo degrada y acopla los botones ────────────────────────────


def test_juego_degenerado_resuelve_por_arquetipo_sin_colgarse() -> None:
    post = PosteriorDeMapeo()
    post.sembrar((1, 2, 3, 4, 6, 7))
    paso_resuelto: dict[str, int] = {}
    for i in range(40):
        boton = f"ACTION{(i % 4) + 1}"
        post.observar(boton, EventoObservado(tipo=EVENTO_SIN_CAMBIO))
        for b in post.botones:
            if b not in paso_resuelto and post.resuelta(b):
                paso_resuelto[b] = i + 1
        if len(paso_resuelto) == 4:
            break
    # Diez pulsaciones (2-3 por flecha) alcanzan: el acople por arquetipo hace que las flechas
    # muertas se condenen entre si -- contra 3 intentos espaciados x 4 flechas del libro solo.
    assert paso_resuelto == {"ACTION1": 9, "ACTION2": 10, "ACTION3": 10, "ACTION4": 10}
    for b in post.botones:
        assert post.inerte(b)
    arquetipo = post.posterior_de_arquetipo()
    assert arquetipo[ARQUETIPO_SIN_MAPEO] > 0.9


def test_sin_flechas_no_hay_nada_que_inferir() -> None:
    post = PosteriorDeMapeo()
    assert post.sembrar((6,)) == 0
    assert post.botones == []
    assert post.posterior_de_arquetipo()[ARQUETIPO_SIN_FLECHAS] == 1.0
    assert post.posterior_de("ACTION1") is None
    post.observar("ACTION1", EventoObservado(tipo=EVENTO_SIN_CAMBIO))  # no explota ni acumula
    assert post.observaciones_de("ACTION1") == 0


# ── 5. masa reservada `desconocida`: piso y registro ──────────────────────────────────────────


def test_la_masa_desconocida_nunca_baja_del_piso() -> None:
    post = PosteriorDeMapeo()
    post.sembrar((1, 2, 3, 4))
    assert post.posterior_de("ACTION1")[MECANICA_DESCONOCIDA] >= PISO_DESCONOCIDO
    # Ni siquiera la evidencia mas concluyente (corridas fieles) la lleva por debajo del piso.
    for _ in range(10):
        post.observar("ACTION1", _traslacion(-1, 0, en_corrida=True))
    assert post.posterior_de("ACTION1")[MECANICA_DESCONOCIDA] >= PISO_DESCONOCIDO
    for arquetipo in (ARQUETIPO_MUEVE, ARQUETIPO_SIN_MAPEO, ARQUETIPO_MIXTO):
        assert condicional_de_mecanicas(arquetipo, "ACTION1")[MECANICA_DESCONOCIDA] >= PISO_DESCONOCIDO


def test_la_masa_desconocida_acumula_y_se_registra() -> None:
    post = PosteriorDeMapeo()
    post.sembrar((1, 2, 3, 4))
    for _ in range(5):
        post.observar("ACTION1", EventoObservado(tipo=EVENTO_DESCONOCIDA))
    posterior = post.posterior_de("ACTION1")
    assert posterior[MECANICA_DESCONOCIDA] > 0.9  # nada del vocabulario explica lo observado
    senal = post.senal_de_vocabulario_incompleto()
    assert senal and senal[0][0] == "ACTION1"
    assert "vocabularioIncompleto=ACTION1" in post.resumen()  # la firma que viaja al reporte


def test_sin_acumulacion_no_hay_senal() -> None:
    post = PosteriorDeMapeo()
    post.sembrar((1, 2, 3, 4))
    for _ in range(6):
        post.observar("ACTION1", _traslacion(-1, 0, en_corrida=True))
    assert post.senal_de_vocabulario_incompleto() == []
    assert "vocabularioIncompleto" not in post.resumen()


# ── percepcion de pared ───────────────────────────────────────────────────────────────────────


def test_contexto_de_pared_borde_obstaculo_y_piso_libre() -> None:
    # Tablero 6x6 de piso 0 con un muro (color 3) pegado arriba del avatar en (2,2)-(3,3).
    grilla = [[0] * 6 for _ in range(6)]
    grilla[1][2] = grilla[1][3] = 3
    contexto = contexto_de_pared(grilla, (2, 2, 2, 2), 0, 1)
    assert contexto["arriba"] == PARED_PRESENTE
    assert contexto["abajo"] == PARED_AUSENTE
    assert contexto["izquierda"] == PARED_AUSENTE
    assert contexto["derecha"] == PARED_AUSENTE
    # El borde del tablero es pared: avatar pegado a la izquierda.
    assert contexto_de_pared(grilla, (2, 0, 2, 2), 0, 1)["izquierda"] == PARED_PRESENTE
    # Sin avatar conocido, todo desconocida.
    assert set(contexto_de_pared(grilla, None, 0, 1).values()) == {PARED_DESCONOCIDA}


def test_profundidad_de_sondeo_usa_la_magnitud_medida() -> None:
    assert profundidad_de_sondeo((0, 4)) == 4
    assert profundidad_de_sondeo((-2, 0)) == 2
    assert profundidad_de_sondeo(None) == 6  # maxima magnitud medida en los 25 juegos
    # Con profundidad 3, un obstaculo a 3 celdas del avatar bloquea el paso completo.
    grilla = [[0] * 8 for _ in range(8)]
    grilla[2][6] = 5
    assert contexto_de_pared(grilla, (2, 2, 1, 2), 0, 3)["derecha"] == PARED_PRESENTE
    assert contexto_de_pared(grilla, (2, 2, 1, 2), 0, 2)["derecha"] == PARED_AUSENTE


def test_rastreador_de_avatar_caja_destino_y_piso_desalojado() -> None:
    tracker = RastreadorDeAvatar()
    assert tracker.caja is None and tracker.piso is None
    # Objeto 2x2 en (5,5) que se mueve (0,+2); las celdas desalojadas quedaron color 7.
    post = [[7] * 10 for _ in range(10)]
    tracker.observar(_mecanica_de_traslacion(0, 2), post)
    assert tracker.caja == (5, 7, 2, 2)
    assert tracker.piso == 7
    tracker.observar(None, post)  # sin mecanica no se pierde lo aprendido
    assert tracker.caja == (5, 7, 2, 2)


# ── 6. PARIDAD TS<->Python: secuencia guionada, numeros exactos ───────────────────────────────


def test_paridad_con_el_puerto_typescript_numeros_exactos() -> None:
    """Los MISMOS valores que `bl21593.posterior.test.ts` afirma sobre la MISMA secuencia. Si un
    puerto cambia una verosimilitud o el orden de una suma y el otro no, uno se pone en rojo."""
    prior = prior_de_arquetipos("1,2,3,4,6")
    assert prior[ARQUETIPO_MUEVE] == pytest.approx(0.6666666666666666, abs=1e-12)
    assert prior[ARQUETIPO_SIN_MAPEO] == pytest.approx(0.16666666666666666, abs=1e-12)

    condicional = condicional_de_mecanicas(ARQUETIPO_MUEVE, "ACTION1")
    # BL.21853 -- estos TRES no se movieron y eso es parte del contrato: ampliar el vocabulario
    # reparte la masa de `otra`, no le saca nada a la direccion canonica ni a `inerte`.
    assert condicional["arriba"] == pytest.approx(0.8421875, abs=1e-12)
    assert condicional[MECANICA_INERTE] == pytest.approx(0.08421875, abs=1e-12)
    assert condicional[MECANICA_DESCONOCIDA] == pytest.approx(0.02, abs=1e-12)

    post = PosteriorDeMapeo()
    post.sembrar((1, 2, 3, 4, 6))
    secuencia = [
        ("ACTION1", _traslacion(-1, 0, False)),
        ("ACTION1", _traslacion(-1, 0, True)),
        ("ACTION1", EventoObservado(tipo=EVENTO_SIN_CAMBIO, pared=PARED_SOLO_ARRIBA)),
        ("ACTION2", EventoObservado(tipo=EVENTO_SIN_CAMBIO)),
        ("ACTION2", EventoObservado(tipo=EVENTO_OTRA)),
        ("ACTION3", _traslacion(0, 1, False)),
        ("ACTION3", _traslacion(0, 1, True)),
        ("ACTION4", EventoObservado(tipo=EVENTO_DESCONOCIDA)),
    ]
    for boton, evento in secuencia:
        post.observar(boton, evento)

    # BL.21853 -- estos SI se movieron, y el motivo esta acotado: la secuencia trae un
    # `EVENTO_OTRA` (ACTION2) y ese evento cambio de significado. Antes era una mecanica visible
    # LIMPIA y valia 0.02 contra direccion; ahora las limpias tienen simbolo propio y `otra` es una
    # MEZCLA de nombradas, que no dice nada de la direccion (0.05, el agnostico). Los numeros
    # viejos eran 0.3776718132885108 / 0.010309277864293129 / 0.6120189088471961 y
    # 0.9789587996514236 / 0.0001636974977446143 / 0.8163523655691687 / 0.12215670282992136 /
    # 0.28209776424641375.
    arquetipo = post.posterior_de_arquetipo()
    assert arquetipo[ARQUETIPO_MUEVE] == pytest.approx(0.5688291285974195, abs=1e-12)
    assert arquetipo[ARQUETIPO_SIN_MAPEO] == pytest.approx(0.005828319251220946, abs=1e-12)
    assert arquetipo[ARQUETIPO_MIXTO] == pytest.approx(0.42534255215135947, abs=1e-12)

    a1 = post.posterior_de("ACTION1")
    assert a1["arriba"] == pytest.approx(0.9792963850466587, abs=1e-12)
    assert a1[MECANICA_INERTE] == pytest.approx(0.0001093939908892459, abs=1e-12)
    assert a1[MECANICA_DESCONOCIDA] == pytest.approx(0.02, abs=1e-12)

    a3 = post.posterior_de("ACTION3")
    assert a3["derecha"] == pytest.approx(0.7743672062320239, abs=1e-12)  # remapeo en curso
    assert a3["izquierda"] == pytest.approx(0.16786683056108737, abs=1e-12)

    a4 = post.posterior_de("ACTION4")
    assert a4[MECANICA_DESCONOCIDA] == pytest.approx(0.2566517422907669, abs=1e-12)
