"""[arc-agi3-kaggle-agent/tests/test_bl21701_entregable_y_extrapolacion] BL.21701 -- las tres cosas
que, sin test, se rompen sin sintoma local:

  1. que el guard VIAJE al notebook. El defecto original en una linea: `NINE_HOURS_SECONDS` vivia
     en `runtime_report.py`, que esta en `MODULOS_EXCLUIDOS` del build. Un reloj que no viaja no
     protege nada, y no hay forma de notarlo corriendo tests locales.
  2. que la HERRAMIENTA DE MEDICION deje medir. `play_local.py` hacia
     `MAX_ACTIONS = min(MAX_ACTIONS, args.max_pasos)`: pedir 800 dejaba 400, asi que nadie podia
     medir por encima del valor entregado NI POR ACCIDENTE. Por eso "entregamos con un presupuesto
     que nunca se midio" era literal.
  3. que la EXTRAPOLACION siga entrando en las 9 h. Es el gate: falla si alguien afloja el
     presupuesto hasta un punto donde el peor caso razonable (75 juegos al costo del juego mas
     caro medido) deja de tener reserva contra el muro."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from arc_agent.reloj_presupuesto import (
    COTA_DE_SEGURIDAD_DE_ACCIONES,
    MARGEN_DE_CIERRE_SEGUNDOS,
    MURO_DEL_NOTEBOOK_SEGUNDOS,
    PRESUPUESTO_POR_DEFECTO_SEGUNDOS,
    RelojDePresupuesto,
)
from submission.build_agent import MODULE_ORDER, construir_fuente
from tests.support.costos_medidos import (
    ACCIONES_DEL_BARRIDO,
    COSTO_DEL_JUEGO_MAS_CARO_POR_ACCION,
    COSTO_MEDIO_POR_ACCION,
    HORAS_PROYECTADAS_POR_JUEGOS,
    JUEGOS_DEL_PEOR_CASO,
    horas_con_guard,
    horas_sin_guard,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

MURO_EN_HORAS = MURO_DEL_NOTEBOOK_SEGUNDOS / 3600.0

#: Reserva minima exigible contra el muro en el peor caso proyectado. Media hora sobre una
#: proyeccion con factor estimado (x1,8) y costo por accion creciente no es holgura de lujo: es lo
#: minimo para que un error del modelo no se coma la entrega.
RESERVA_MINIMA_EN_HORAS = 0.5


class TestElGuardViajaEnElEntregable:
    def test_el_modulo_esta_en_module_order(self) -> None:
        assert "reloj_presupuesto.py" in MODULE_ORDER

    def test_el_entregable_lleva_el_reloj_y_lo_consulta_en_is_done(self) -> None:
        fuente = construir_fuente()
        assert "class RelojDePresupuesto:" in fuente
        assert "RELOJ_GLOBAL = RelojDePresupuesto()" in fuente
        assert "self._reloj.debe_cortar(" in fuente, "is_done tiene que consultar el reloj"
        assert "self._reloj.finalizar_partida(" in fuente, "cleanup tiene que devolver el tiempo"
        assert "MURO_DEL_NOTEBOOK_SEGUNDOS" in fuente

    def test_el_corte_no_usa_ni_excepciones_ni_matar_hilos(self) -> None:
        """El corte vive DENTRO del contrato oficial: `is_done` devuelve True y el framework cierra
        solo. Matar el proceso o levantar una excepcion deja la scorecard sin cerrar y el gateway
        sin parquet, o sea la submission muerta igual -- por otra puerta."""
        fuente = construir_fuente()
        for prohibido in ("os._exit", "sys.exit(", "interrupt_main", "signal.alarm"):
            assert prohibido not in fuente, f"{prohibido} no puede estar en el entregable"

    def test_el_entregable_declara_la_cota_de_acciones_una_sola_vez(self) -> None:
        """Fuente unica: `MyAgent.MAX_ACTIONS` ADOPTA la constante del reloj, no la repite."""
        fuente = construir_fuente()
        assert "MAX_ACTIONS = COTA_DE_SEGURIDAD_DE_ACCIONES" in fuente
        assert f"COTA_DE_SEGURIDAD_DE_ACCIONES = {COTA_DE_SEGURIDAD_DE_ACCIONES}" in fuente


class TestPlayLocal:
    def _play_local(self):
        import play_local

        return play_local

    def test_permite_pedir_mas_pasos_que_max_actions(self) -> None:
        """EL defecto de herramienta: el `min` convertia el tope entregado en un techo
        infranqueable, asi que un barrido a 1600 media 400 y nadie se enteraba."""
        play_local = self._play_local()

        class ClaseFalsa:
            MAX_ACTIONS = 400

        assert play_local.aplicar_tope_de_pasos(ClaseFalsa, 1600) == 1600
        assert ClaseFalsa.MAX_ACTIONS == 1600

    def test_tambien_permite_pedir_menos(self) -> None:
        play_local = self._play_local()

        class ClaseFalsa:
            MAX_ACTIONS = 4000

        assert play_local.aplicar_tope_de_pasos(ClaseFalsa, 50) == 50

    def test_sin_bandera_rige_el_tope_del_entregable(self) -> None:
        play_local = self._play_local()

        class ClaseFalsa:
            MAX_ACTIONS = COTA_DE_SEGURIDAD_DE_ACCIONES

        assert play_local.aplicar_tope_de_pasos(ClaseFalsa, None) == COTA_DE_SEGURIDAD_DE_ACCIONES

    def test_configurar_reloj_declara_el_total_y_permite_apagarlo(self) -> None:
        play_local = self._play_local()

        class ModuloFalso:
            class MyAgent:
                RELOJ = None

            RELOJ_GLOBAL = RelojDePresupuesto(presupuesto_segundos=1000.0)

        reloj = play_local.configurar_reloj(ModuloFalso, 25, None)
        assert reloj.partidas_pendientes() == 25

        apagado = play_local.configurar_reloj(ModuloFalso, 25, 0.0)
        assert apagado.reloj_apagado is True
        assert ModuloFalso.MyAgent.RELOJ is apagado, "el agente tiene que usar el reloj configurado"

    def test_un_agente_sin_reloj_avisa_en_vez_de_romper(self) -> None:
        """Un `my_agent.py` viejo (pre BL.21701) no trae reloj: la herramienta avisa y sigue."""
        play_local = self._play_local()

        class ModuloViejo:
            class MyAgent:
                pass

        assert play_local.configurar_reloj(ModuloViejo, 5, None) is None

    def test_el_makefile_no_fija_un_tope_por_defecto(self) -> None:
        """`PASOS ?= 200` hacia que el loop local midiera SIEMPRE 200 acciones aunque el entregable
        llevara otro tope: el numero que se medía nunca era el que se entregaba."""
        makefile = (PROJECT_ROOT / "Makefile").read_text(encoding="utf-8")
        assert "PASOS        ?=\n" in makefile, "PASOS tiene que quedar vacio"
        assert "--max-pasos $(PASOS)" not in makefile.replace("$(if $(PASOS),--max-pasos $(PASOS))", "")


class TestExtrapolacionDeTiempo:
    def test_el_modelo_reproduce_la_medicion_publicada(self) -> None:
        """Si el modelo no reprodujera las horas publicadas, el gate de abajo no probaria nada."""
        for juegos, horas in HORAS_PROYECTADAS_POR_JUEGOS.items():
            proyectadas = horas_sin_guard(juegos, ACCIONES_DEL_BARRIDO, COSTO_MEDIO_POR_ACCION)
            assert proyectadas == pytest.approx(horas, rel=0.01)

    def test_sin_guard_el_peor_caso_reventaba_el_muro(self) -> None:
        """La razon de ser del BL, en numeros: 75 juegos al costo del mas caro medido, con la cota
        de acciones que se entrega y sin reloj."""
        sin_reloj = horas_sin_guard(
            JUEGOS_DEL_PEOR_CASO, COTA_DE_SEGURIDAD_DE_ACCIONES, COSTO_DEL_JUEGO_MAS_CARO_POR_ACCION
        )
        assert sin_reloj > MURO_EN_HORAS, (
            "si el peor caso ya no reventara sin reloj, este BL sobraria -- revisar la medicion"
        )

    def test_el_peor_caso_con_la_configuracion_entregada_se_mantiene_bajo_las_9h(self) -> None:
        """EL GATE. Falla si alguien afloja el presupuesto o el margen hasta un punto donde 75
        juegos al costo del juego mas caro medido no entran en el muro con reserva."""
        proyectadas = horas_con_guard(
            JUEGOS_DEL_PEOR_CASO,
            COTA_DE_SEGURIDAD_DE_ACCIONES,
            COSTO_DEL_JUEGO_MAS_CARO_POR_ACCION,
            PRESUPUESTO_POR_DEFECTO_SEGUNDOS,
            MARGEN_DE_CIERRE_SEGUNDOS,
        )
        assert proyectadas < MURO_EN_HORAS, f"peor caso proyectado {proyectadas:.2f} h >= muro"
        assert MURO_EN_HORAS - proyectadas >= RESERVA_MINIMA_EN_HORAS, (
            f"peor caso proyectado {proyectadas:.2f} h: quedan menos de "
            f"{RESERVA_MINIMA_EN_HORAS * 60:.0f} min de reserva contra el muro de 9 h, y el muro "
            "MATA la submission entera"
        )

    def test_el_gate_tiene_dientes(self) -> None:
        """Con 8,9 h de presupuesto la reserva desaparece: el gate de arriba tiene que fallar ahi.
        Sin esta prueba, un gate que no puede fallar nunca es decoracion."""
        proyectadas = horas_con_guard(
            JUEGOS_DEL_PEOR_CASO,
            COTA_DE_SEGURIDAD_DE_ACCIONES,
            COSTO_DEL_JUEGO_MAS_CARO_POR_ACCION,
            8.9 * 3600,
            MARGEN_DE_CIERRE_SEGUNDOS,
        )
        assert MURO_EN_HORAS - proyectadas < RESERVA_MINIMA_EN_HORAS

    def test_en_el_regimen_real_manda_el_reloj_y_no_la_constante(self) -> None:
        """Lo que se pidio: que el limite operativo sea el TIEMPO, no un numero fijo. Con 25 juegos
        (el set publico), con 50 y con 75, el reloj corta antes que la cota de acciones."""
        for juegos in (25, 50, JUEGOS_DEL_PEOR_CASO):
            sin_reloj = horas_sin_guard(juegos, COTA_DE_SEGURIDAD_DE_ACCIONES, COSTO_MEDIO_POR_ACCION)
            con_reloj = horas_con_guard(
                juegos,
                COTA_DE_SEGURIDAD_DE_ACCIONES,
                COSTO_MEDIO_POR_ACCION,
                PRESUPUESTO_POR_DEFECTO_SEGUNDOS,
                MARGEN_DE_CIERRE_SEGUNDOS,
            )
            assert con_reloj < sin_reloj, f"con {juegos} juegos la constante seguiria mandando"

    def test_el_presupuesto_se_usa_casi_entero_en_el_regimen_real(self) -> None:
        """La otra cara del gate: un guard que corta de mas tambien es un defecto. Con 25 juegos y
        el costo medio, el batch tiene que llegar a gastar el presupuesto y no una fraccion."""
        con_reloj = horas_con_guard(
            25,
            COTA_DE_SEGURIDAD_DE_ACCIONES,
            COSTO_MEDIO_POR_ACCION,
            PRESUPUESTO_POR_DEFECTO_SEGUNDOS,
            MARGEN_DE_CIERRE_SEGUNDOS,
        )
        assert con_reloj >= PRESUPUESTO_POR_DEFECTO_SEGUNDOS / 3600.0 - 0.05
