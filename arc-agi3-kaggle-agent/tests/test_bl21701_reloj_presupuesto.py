"""[arc-agi3-kaggle-agent/tests/test_bl21701_reloj_presupuesto] BL.21701 -- el SEGURO de las 9 h,
por dentro: configuracion entregada, deadline global bajo los hilos que el Swarm realmente lanza,
corte ORDENADO dentro del contrato oficial y reparto del tiempo entre partidas.

QUE PROTEGE. El muro del notebook de Kaggle no degrada el score: MATA la submission entera. Antes
de este BL no habia ningun reloj en el entregable -- el unico 9h del repo vive en
`runtime_report.py`, que esta EXCLUIDO del build, y el `Swarm` oficial no trae deadline propio --
asi que el unico freno era una constante, y una constante no puede ser correcta cuando la cantidad
de juegos privados es desconocida.

El resto (que el guard VIAJE al notebook, la herramienta de medicion y la extrapolacion a 9 h) esta
en `test_bl21701_entregable_y_extrapolacion.py`."""
from __future__ import annotations

import threading

import pytest

from arc_agent.reloj_presupuesto import (
    COTA_DE_SEGURIDAD_DE_ACCIONES,
    MARGEN_DE_CIERRE_SEGUNDOS,
    MURO_DEL_NOTEBOOK_SEGUNDOS,
    PRESUPUESTO_POR_DEFECTO_SEGUNDOS,
    VARIABLE_DE_ENTORNO_PRESUPUESTO,
    RelojDePresupuesto,
    margen_de_cierre_para,
    presupuesto_configurado,
)
from tests.support.costos_medidos import (
    ACCIONES_DEL_BARRIDO,
    COSTO_DEL_JUEGO_MAS_CARO_POR_ACCION,
    JUEGOS_DEL_PEOR_CASO,
)
from tests.support.reloj_falso import AgenteDePrueba, reloj_de_prueba


class TestConfiguracionEntregada:
    def test_el_presupuesto_entregado_deja_una_hora_de_reserva_del_muro(self) -> None:
        """La reserva no es cautela vaga: cubre lo que corre ANTES del import (pip install de las
        wheels offline + espera al gateway, que el notebook reintenta hasta 600 s) y la cola de
        cierre (scorecard, grabaciones, parquet)."""
        assert MURO_DEL_NOTEBOOK_SEGUNDOS == 9 * 3600
        assert PRESUPUESTO_POR_DEFECTO_SEGUNDOS == 8.0 * 3600
        reserva = MURO_DEL_NOTEBOOK_SEGUNDOS - PRESUPUESTO_POR_DEFECTO_SEGUNDOS
        assert reserva >= 3600, "menos de una hora de reserva contra el muro que mata la submission"

    def test_el_margen_de_cierre_cubre_la_accion_en_vuelo_de_cada_hilo(self) -> None:
        """Cuando suena la campana cada hilo vivo puede tener una accion en vuelo y, bajo el GIL,
        esas acciones se pagan en serie. El margen tiene que pagar el peor caso completo."""
        sobrepaso = JUEGOS_DEL_PEOR_CASO * COSTO_DEL_JUEGO_MAS_CARO_POR_ACCION
        assert MARGEN_DE_CIERRE_SEGUNDOS >= sobrepaso
        assert margen_de_cierre_para(PRESUPUESTO_POR_DEFECTO_SEGUNDOS) == MARGEN_DE_CIERRE_SEGUNDOS

    def test_un_presupuesto_chico_no_se_lo_come_el_margen(self) -> None:
        """Solo pasa en pruebas locales (`--presupuesto-horas 0.001`), pero ahi el margen fijo de
        60 s cortaba en la accion CERO: parece un bug del guard y confunde a quien mide."""
        assert margen_de_cierre_para(5.4) == pytest.approx(0.054)
        assert margen_de_cierre_para(0.0) == 0.0
        reloj = RelojDePresupuesto(presupuesto_segundos=5.4)
        manija = reloj.registrar_partida("chica")
        assert reloj.debe_cortar(manija, 0.0) is False

    def test_la_cota_de_acciones_esta_holgada_sobre_lo_medido(self) -> None:
        """Dejo de ser el limite operativo: tiene que estar bien por encima del punto mas alto que
        se midio, para que el que corta sea el reloj y no la constante."""
        assert COTA_DE_SEGURIDAD_DE_ACCIONES >= 2 * ACCIONES_DEL_BARRIDO

    def test_la_variable_de_entorno_pisa_el_presupuesto(self) -> None:
        assert presupuesto_configurado({VARIABLE_DE_ENTORNO_PRESUPUESTO: "120"}) == 120.0
        assert presupuesto_configurado({VARIABLE_DE_ENTORNO_PRESUPUESTO: "0"}) == 0.0

    def test_un_valor_invalido_no_tumba_la_submission(self) -> None:
        """Un typo en una variable de entorno no puede ser la causa de que no haya entrega."""
        for basura in ("", "  ", "ocho horas", None):
            entorno = {} if basura is None else {VARIABLE_DE_ENTORNO_PRESUPUESTO: basura}
            assert presupuesto_configurado(entorno) == PRESUPUESTO_POR_DEFECTO_SEGUNDOS


class TestDeadlineGlobalConcurrente:
    """El escenario del Swarm oficial: N partidas concurrentes en el MISMO proceso, un reloj."""

    def test_ninguna_accion_termina_despues_del_presupuesto(self) -> None:
        presupuesto, margen, costo, partidas = 1000.0, 10.0, 1.0, 8
        reloj, falso = reloj_de_prueba(presupuesto, margen)
        assert partidas * costo < margen, "el margen cubre la accion en vuelo de cada hilo"

        fin_de_accion: list[float] = []
        registro = threading.Lock()
        fallas: list[BaseException] = []
        # Igual que el Swarm oficial: TODAS las partidas se dan de alta en el hilo principal ANTES
        # de arrancar ningun hilo (swarm.py construye los agentes y recien despues los lanza).
        manijas = [reloj.registrar_partida(f"juego-{i}") for i in range(partidas)]

        def jugar(manija: int) -> None:
            try:
                consumo = 0.0
                while not reloj.debe_cortar(manija, consumo):
                    consumo += costo
                    falso.avanzar(costo)
                    with registro:
                        fin_de_accion.append(falso())
                reloj.finalizar_partida(manija)
            except BaseException as exc:  # noqa: BLE001 -- el test tiene que VER la excepcion
                fallas.append(exc)

        hilos = [threading.Thread(target=jugar, args=(m,)) for m in manijas]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=30)

        assert not fallas, f"el reloj rompio bajo concurrencia: {fallas}"
        assert all(not hilo.is_alive() for hilo in hilos), "algun hilo no cerro"
        assert max(fin_de_accion) <= presupuesto, "una accion termino despues del presupuesto"
        assert reloj.partidas_vivas() == 0

    def test_el_reparto_entre_hilos_es_parejo_y_la_contabilidad_cierra(self) -> None:
        """Thread-safety de verdad: sin candado se pierden incrementos, el consumo agregado deja de
        coincidir con el tiempo de pared y ahi el reparto miente -- alguna partida come de mas.

        La cuota es invariante al entrelazado de hilos, y es lo que hace al reparto defendible: con
        `k` partidas ya cerradas habiendo gastado `q` cada una, la cuota vale
        `(presupuesto - k*q) / (partidas - k)`, o sea `presupuesto / partidas` mientras el reparto
        sea parejo -- no importa en que orden el planificador les de el GIL."""
        presupuesto, margen, costo, partidas = 1000.0, 10.0, 1.0, 8
        reloj, falso = reloj_de_prueba(presupuesto, margen)
        consumos: dict[int, float] = {}
        candado = threading.Lock()
        manijas = [reloj.registrar_partida(f"juego-{i}") for i in range(partidas)]

        def jugar(indice: int, manija: int) -> None:
            consumo = 0.0
            while not reloj.debe_cortar(manija, consumo):
                consumo += costo
                falso.avanzar(costo)
            with candado:
                consumos[indice] = consumo
            reloj.finalizar_partida(manija)

        hilos = [
            threading.Thread(target=jugar, args=(i, manija)) for i, manija in enumerate(manijas)
        ]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=30)

        cuota_pareja = presupuesto / partidas
        assert len(consumos) == partidas
        for indice, consumo in consumos.items():
            assert consumo <= cuota_pareja + costo, f"la partida {indice} se paso de su cuota"
        assert sum(consumos.values()) == pytest.approx(falso(), abs=1e-6), "contabilidad rota"
        assert falso() <= presupuesto
        assert presupuesto - falso() <= margen, "quedo presupuesto sin usar"


class TestCorteOrdenado:
    def test_el_lazo_oficial_termina_solo_y_corre_cleanup(self) -> None:
        """`is_done` True corta el `while` y deja correr `cleanup()`. Nada de matar hilos ni de
        levantar excepciones: un hilo muerto a la fuerza deja la scorecard sin cerrar."""
        reloj, falso = reloj_de_prueba(100.0, 5.0)
        agente = AgenteDePrueba(reloj, falso, costo=1.0, etiqueta="solo")
        agente.main()
        assert agente.cortada_por_reloj is True
        assert agente.veces_que_limpio == 1
        assert falso() <= 100.0
        assert reloj.partidas_vivas() == 0

    def test_un_swarm_simulado_cierra_todos_los_hilos_y_la_scorecard(self) -> None:
        """El `Swarm` oficial arranca un hilo por juego, hace join de TODOS y recien ahi cierra la
        scorecard. Si un hilo no cerrara, el join no volveria nunca y la corrida moriria en el muro
        sin parquet -- exactamente el desenlace que este BL evita."""
        presupuesto = 500.0
        reloj, falso = reloj_de_prueba(presupuesto, 10.0)
        agentes = [AgenteDePrueba(reloj, falso, costo=1.0, etiqueta=f"j{i}") for i in range(6)]
        hilos = [threading.Thread(target=a.main, daemon=True) for a in agentes]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=30)

        assert all(not hilo.is_alive() for hilo in hilos), "el join del Swarm no habria vuelto"
        assert all(a.veces_que_limpio == 1 for a in agentes)
        assert all(a.action_counter > 0 for a in agentes), "todas jugaron antes de cortar"
        assert reloj.partidas_vivas() == 0, "la scorecard se cierra con todas las partidas dadas de baja"
        assert falso() <= presupuesto

    def test_la_partida_que_agota_la_cota_de_acciones_tambien_libera_su_cuota(self) -> None:
        """`Agent.main()` tambien sale por `action_counter > MAX_ACTIONS`, SIN pasar por un
        `is_done` que diga True. Por eso el gancho esta en `cleanup()` y no en `is_done`: si no,
        esa partida quedaria contada como viva para siempre y estrangularia a las demas."""
        reloj, falso = reloj_de_prueba(10000.0, 10.0)
        reloj.declarar_total_de_partidas(2)
        agente = AgenteDePrueba(reloj, falso, costo=1.0, etiqueta="corta", max_actions=5)
        agente.main()
        assert agente.cortada_por_reloj is False, "corto por la cota de acciones, no por el reloj"
        assert reloj.partidas_vivas() == 0

    def test_ganar_devuelve_el_tiempo_no_usado_al_pool(self) -> None:
        reloj, falso = reloj_de_prueba(1000.0, 10.0)
        reloj.declarar_total_de_partidas(4)
        agente = AgenteDePrueba(reloj, falso, costo=1.0, etiqueta="ganadora", gana_en=7)
        agente.main()
        assert agente.gano is True
        assert agente.consumo == pytest.approx(7.0)
        assert reloj.partidas_vivas() == 0

    def test_finalizar_partida_es_idempotente(self) -> None:
        """El framework llama `cleanup()` desde `main()` y otra vez desde `Swarm.cleanup()`. Si el
        segundo llamado descontara de nuevo, el consumo agregado quedaria negativo y el reparto
        regalaria tiempo que no existe."""
        reloj, _ = reloj_de_prueba(100.0, 5.0)
        manija = reloj.registrar_partida("j")
        reloj.debe_cortar(manija, 10.0)
        reloj.finalizar_partida(manija)
        reloj.finalizar_partida(manija)
        assert reloj.partidas_vivas() == 0
        assert reloj.estado()["consumoDeLasVivasSegundos"] == 0.0

    def test_una_manija_desconocida_corta(self) -> None:
        """Lado seguro del error: si la contabilidad de una partida se perdio, la partida cierra."""
        reloj, _ = reloj_de_prueba(100.0, 5.0)
        assert reloj.debe_cortar(9999, 0.0) is True

    def test_dos_partidas_del_mismo_juego_no_comparten_contabilidad(self) -> None:
        """La manija es un entero propio y no el `game_id`: un batch puede repetir un juego."""
        reloj, _ = reloj_de_prueba(1000.0, 10.0)
        primera = reloj.registrar_partida("ft09")
        segunda = reloj.registrar_partida("ft09")
        assert primera != segunda
        reloj.debe_cortar(primera, 100.0)
        assert reloj.estado()["consumoDeLasVivasSegundos"] == pytest.approx(100.0)


class TestRepartoDelTiempo:
    def test_con_partidas_parejas_cada_una_recibe_su_fraccion(self) -> None:
        reloj, _ = reloj_de_prueba(1000.0, 10.0)
        manijas = [reloj.registrar_partida(f"j{i}") for i in range(5)]
        for manija in manijas:
            assert reloj.cuota_de_partida(manija) == pytest.approx(200.0)

    def test_una_partida_que_termina_le_devuelve_su_tiempo_a_las_vivas(self) -> None:
        reloj, _ = reloj_de_prueba(1000.0, 10.0)
        manijas = [reloj.registrar_partida(f"j{i}") for i in range(4)]
        assert reloj.cuota_de_partida(manijas[0]) == pytest.approx(250.0)
        reloj.finalizar_partida(manijas[3])
        assert reloj.cuota_de_partida(manijas[0]) == pytest.approx(1000.0 / 3)

    def test_una_partida_adelantada_corta_antes_que_las_demas(self) -> None:
        """El reparto tiene que ser correctivo, no solo un promedio: la que gasto de mas cierra, y
        lo que devuelve va a parar a la que se quedo atras."""
        reloj, falso = reloj_de_prueba(1000.0, 10.0)
        glotona = reloj.registrar_partida("glotona")
        tranquila = reloj.registrar_partida("tranquila")
        falso.avanzar(610.0)  # el reloj de pared avanza con lo que las partidas consumen (GIL)

        assert reloj.debe_cortar(tranquila, 10.0) is False
        assert reloj.debe_cortar(glotona, 600.0) is True
        reloj.finalizar_partida(glotona)
        assert reloj.cuota_de_partida(tranquila) == pytest.approx(400.0), (
            "el tiempo que devolvio la glotona tiene que quedar disponible para la tranquila"
        )

    def test_el_reparto_no_deja_tiempo_sin_usar_al_final(self) -> None:
        """EL test del reparto. Batch en serie de 5 partidas: las 4 primeras ganan enseguida y la
        quinta tiene que poder usar TODO lo que sobro, no su quinta parte. Sin redistribucion el
        batch terminaria con el grueso del presupuesto sin gastar."""
        presupuesto, margen, costo = 1000.0, 10.0, 1.0
        reloj, falso = reloj_de_prueba(presupuesto, margen)
        reloj.declarar_total_de_partidas(5)

        rapidas = [
            AgenteDePrueba(reloj, falso, costo=costo, etiqueta=f"rapida-{i}", gana_en=20)
            for i in range(4)
        ]
        for agente in rapidas:
            agente.main()
            assert agente.gano is True

        ultima = AgenteDePrueba(reloj, falso, costo=costo, etiqueta="ultima")
        ultima.main()

        sin_usar = presupuesto - falso()
        assert sin_usar <= margen, f"quedaron {sin_usar:.1f} s de presupuesto sin usar"
        assert ultima.consumo > presupuesto / 5, "la ultima no absorbio el tiempo devuelto"

    def test_declarar_el_total_evita_que_la_primera_partida_se_coma_el_batch(self) -> None:
        """`scripts/play_local.py` juega EN SERIE: sin declarar el total, el reloj ve una sola
        partida viva y le da el presupuesto entero a la primera."""
        a_ciegas, _ = reloj_de_prueba(1000.0, 10.0)
        sin_declarar = a_ciegas.registrar_partida("primera")
        assert a_ciegas.cuota_de_partida(sin_declarar) == pytest.approx(1000.0)

        avisado, _ = reloj_de_prueba(1000.0, 10.0)
        avisado.declarar_total_de_partidas(25)
        con_declaracion = avisado.registrar_partida("primera")
        assert avisado.cuota_de_partida(con_declaracion) == pytest.approx(40.0)

    def test_el_deadline_manda_sobre_la_cuota(self) -> None:
        """Aunque a una partida le sobre cuota, el deadline global la corta igual: el muro es del
        BATCH, no de la partida."""
        reloj, falso = reloj_de_prueba(1000.0, 10.0)
        reloj.declarar_total_de_partidas(50)
        manija = reloj.registrar_partida("tardia")
        falso.avanzar(995.0)
        assert reloj.deadline_alcanzado() is True
        assert reloj.debe_cortar(manija, 0.0) is True

    def test_el_reloj_apagado_no_corta_nunca(self) -> None:
        """Presupuesto 0 = barrido de medicion: ahi se mide el costo de un presupuesto de acciones
        y un corte por tiempo contaminaria la medicion."""
        reloj, falso = reloj_de_prueba(0.0, 10.0)
        manija = reloj.registrar_partida("barrido")
        falso.avanzar(10 * 3600)
        assert reloj.reloj_apagado is True
        assert reloj.segundos_restantes() == float("inf")
        assert reloj.debe_cortar(manija, 9999.0) is False
        assert reloj.cuota_de_partida(manija) == float("inf")
