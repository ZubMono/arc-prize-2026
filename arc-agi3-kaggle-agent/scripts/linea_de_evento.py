"""[arc-agi3-kaggle-agent/scripts/linea_de_evento] Las lineas que el informe imprime por CADA
evento medido: la maniobra, sus firmas, el saldo de objetos y los contrastes.

Vive aparte de `caracterizar_completados` (que arma el informe) por tamano: ese modulo cruzo el
limite al agregarsele el fail-closed de las ventanas crudas y la cobertura sin frames informativos
(BL.21798). Aca esta la PRESENTACION de un evento; alla, el informe completo. Ningun import en
sentido contrario.

Stdlib pura. SOLO REPO."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from medicion_de_evento import MedicionDeEvento  # noqa: E402


def linea_de_evento(medicion: MedicionDeEvento) -> list[str]:
    v = medicion.maniobra
    animacion = " ANIMACION-EN-LOOP" if v.animacion_en_loop else ""
    truncada = " VENTANA-TRUNCADA" if v.ventana_truncada else ""
    click = (
        f" click={medicion.click_del_evento} color={medicion.color_clickeado} "
        f"celdas={medicion.celdas_de_la_componente_clickeada} "
        f"(linea base: {medicion.clicks_previos_en_objeto}/{medicion.clicks_previos} "
        "clicks previos cayeron sobre objeto)"
        if medicion.click_del_evento is not None
        else ""
    )
    tope = (
        " (SOBRE el tope de detectar_mecanica: cambio demasiado)"
        if medicion.sobre_el_tope_de_mecanica
        else ""
    )
    return [
        f"  {medicion.juego} paso={medicion.paso_del_evento:5} "
        f"nivel {medicion.nivel_previo}->{medicion.nivel_nuevo} "
        f"cambio={medicion.fraccion_cambiada:.3f} mecanica={medicion.firma_del_evento}",
        f"      accion={medicion.accion_del_evento}{click}",
        f"      clusters del evento: {medicion.tipos_de_cluster}{tope}",
        f"      MANIOBRA (sin el frame del evento): framesAntes={v.frames_previos}"
        f"{truncada} | pasos previos={len(v.pasos)}: {v.pasos_informativos} informativo(s), "
        f"{v.pasos_inertes} inerte(s) (0 celdas), {v.pasos_en_animacion} de animacion"
        f"{animacion} | ocupacion: {v.pasos_que_suben_la_ocupacion} paso(s) suben, "
        f"{v.pasos_que_bajan_la_ocupacion} bajan"
        + (
            f" | linea base de click SATURADA ({v.clicks_previos_en_objeto}/{v.clicks_previos} "
            "clicks previos tambien cayeron sobre objeto)"
            if v.linea_base_de_click_saturada
            else ""
        ),
        f"      FIRMAS DE LA MANIOBRA (BL.21741, solo pasos informativos): "
        f"dominante={v.firma_dominante_en_la_maniobra} x{v.pasos_con_la_firma_dominante} | "
        f"{v.firmas_distintas_en_la_maniobra} distinta(s) | clusters={v.clusters_en_la_maniobra}"
        + (" | SIN FIRMAS MEDIDAS" if v.maniobra_sin_firmas_medidas else "")
        # SIN PASOS INFORMATIVOS no es lo mismo que SIN FIRMAS MEDIDAS: el primero dice que no hay
        # nada que mirar (todo inerte o loop), el segundo que nadie corrio la percepcion. Hasta
        # BL.21765 el informe imprimia el segundo en los dos casos.
        + (" | SIN PASOS INFORMATIVOS" if v.sin_pasos_informativos else "")
        + (
            f" | PASOS NO MIRADOS por el detector: {v.pasos_no_mirados_en_la_maniobra}"
            if v.pasos_no_mirados_en_la_maniobra
            else ""
        ),
        f"      SALDO DE OBJETOS EN LA MANIOBRA: "
        f"{v.objetos_aparecidos_en_la_maniobra} aparicion(es) - "
        f"{v.objetos_desaparecidos_en_la_maniobra} desaparicion(es) = "
        f"{v.saldo_neto_de_objetos_en_la_maniobra} | "
        f"{v.clusters_sin_nombrar_en_la_maniobra} cluster(s) que el detector NO supo nombrar | "
        f"pasos con saldo NETO: {v.pasos_que_hacen_aparecer_netamente_en_la_maniobra} suman, "
        f"{v.pasos_que_hacen_desaparecer_netamente_en_la_maniobra} restan "
        f"(presencia, el instrumento viejo: {v.pasos_que_hacen_aparecer_en_la_maniobra}/"
        f"{v.pasos_que_hacen_desaparecer_en_la_maniobra})"
        + (
            f" | OSCILACION DE DOS ESTADOS: {v.pasos_en_oscilacion} de esos frames van y vuelven "
            "entre dos mecanicas"
            if v.oscilacion_de_firmas
            else ""
        ),
        f"      CONTRASTE llenado {int(medicion.llenado_monotono)}->"
        f"{int(v.llenado_monotono_en_la_maniobra)} | vaciado {int(medicion.vaciado_monotono)}->"
        f"{int(v.vaciado_monotono_en_la_maniobra)} | agotados {medicion.colores_agotados}->"
        f"{list(v.colores_agotados_en_la_maniobra)} "
        "(izquierda: CON el frame del evento = artefacto; derecha: la maniobra)",
    ]


__all__ = ["linea_de_evento"]
