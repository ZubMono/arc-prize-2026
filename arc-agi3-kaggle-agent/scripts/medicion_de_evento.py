"""[arc-agi3-kaggle-agent/scripts/medicion_de_evento] BL.21695/BL.21728 -- el REGISTRO de todo lo
medible de un completado capturado.

Vive aparte de `caracterizacion_de_niveles.py` (que es quien lo LLENA) por tamano: ese modulo cruzo
el limite de 500 lineas al agregarsele la vista de la maniobra de BL.21728. Aca solo hay datos y su
serializacion; ninguna medicion.

DOS FAMILIAS DE CAMPOS QUE NO SIGNIFICAN LO MISMO, y confundirlas fue el defecto de BL.21695:
  - los campos planos (`vaciado_monotono`, `llenado_monotono`, `colores_agotados`, ...) se miden CON
    el frame del evento adentro, asi que describen el DESENLACE;
  - `maniobra` (`VistaDeLaManiobra`) se mide EXCLUYENDO ese frame, asi que describe lo que el agente
    hizo para llegar. Es la unica familia que puede sostener un candidato a objetivo.

Stdlib pura. SOLO REPO."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from maniobra_previa import VistaDeLaManiobra


@dataclass
class MedicionDeEvento:
    """Todo lo medible de UN completado capturado. Campos crudos: la interpretacion la hace el
    informe, no este objeto."""

    juego: str
    corrida: str
    paso_del_evento: int
    nivel_previo: int
    nivel_nuevo: int
    frames_antes: int
    frames_despues: int
    celdas_cambiadas: int
    fraccion_cambiada: float
    pantalla_nueva: bool
    firma_del_evento: str
    #: Que hizo el agente en el paso que subio el nivel. Con el motor offline esto solo existe desde
    #: que `captura_de_niveles.registrar_acciones` lo anota: el frame no lo trae.
    accion_del_evento: str = "DESCONOCIDA"
    click_del_evento: tuple[int, int] | None = None
    #: Color de la celda clickeada EN LA GRILLA PREVIA y tamano de su componente. Responde "el
    #: nivel se resolvio tocando un objeto, y de que tipo": si el click cae sobre el fondo, la
    #: hipotesis "hay que tocar el objeto correcto" pierde fuerza en ese caso.
    color_clickeado: int | None = None
    celdas_de_la_componente_clickeada: int | None = None
    #: Cuantos clusters de cambio de cada tipo trae la transicion del evento. Es la materia prima
    #: de la firma COMPUESTA de BL.21741: "6 desapariciones + 1 recoloreo" distingue un objetivo de
    #: otro, y hasta ese BL la firma global decia "desconocida" en los 14 eventos del corpus.
    #: Se llena con `conteo_de_tipos_de_cluster`, la fuente unica del modulo de percepcion.
    tipos_de_cluster: dict[str, int] = field(default_factory=dict)
    #: El evento cambio MAS celdas que `MAX_CELDAS_CAMBIADAS` y `detectar_mecanica` NO LO ANALIZO
    #: (devuelve tipo `sobreElTope` desde BL.21741). Cuando esto es True, `tipos_de_cluster` esta
    #: vacio POR EL TOPE y no porque no haya cambios -- distinguir las dos cosas es obligatorio
    #: para no leer el silencio del detector como evidencia de quietud.
    sobre_el_tope_de_mecanica: bool = False
    firmas_previas: list[str] = field(default_factory=list)
    colores_agotados: list[int] = field(default_factory=list)
    colores_reducidos: list[int] = field(default_factory=list)
    colores_aparecidos: list[int] = field(default_factory=list)
    fraccion_no_fondo: list[float] = field(default_factory=list)
    llenado_monotono: bool = False
    vaciado_monotono: bool = False
    pasos_con_traslacion: int = 0
    colores_alcanzados: list[int] = field(default_factory=list)
    aproximacion_monotona: list[int] = field(default_factory=list)
    caja_del_frente_antes: tuple[int, int, int, int] | None = None
    caja_del_frente_despues: tuple[int, int, int, int] | None = None
    #: BL.21728 -- lo mismo, pero medido SIN el frame del evento. Todos los campos de arriba que
    #: hablan de "monotonia" o de "colores agotados" incluyen la transicion que DEFINE el evento y
    #: por eso describen el resultado, no la maniobra (medido: excluyendo ese frame,
    #: `vaciado_monotono` cae de 6 eventos a 0). Los criterios del vocabulario de objetivos leen
    #: EXCLUSIVAMENTE esta vista; los de arriba quedan para poder mostrar el contraste.
    maniobra: VistaDeLaManiobra = field(
        default_factory=lambda: VistaDeLaManiobra(frames_previos=0)
    )

    @property
    def clicks_previos(self) -> int:
        """LINEA BASE del click ganador, DELEGADA a la vista de la maniobra.

        FUENTE UNICA (correccion de BL.21728): estos dos contadores vivian a la vez aca y en
        `VistaDeLaManiobra`, se llenaban de los mismos locales de `medir_evento` y salian
        DUPLICADOS en el JSON (`clicksPrevios` y `maniobra.clicksPrevios`) y dos veces en la misma
        linea del informe de texto. Dos copias del mismo concepto es exactamente lo que este BL
        argumenta que no puede pasar -- y el criterio que las usa MATA candidatos."""
        return self.maniobra.clicks_previos

    @property
    def clicks_previos_en_objeto(self) -> int:
        """Espejo del anterior. Ver `clicks_previos`."""
        return self.maniobra.clicks_previos_en_objeto

    def a_json(self) -> dict[str, Any]:
        return {
            "juego": self.juego,
            "corrida": self.corrida,
            "pasoDelEvento": self.paso_del_evento,
            "nivelPrevio": self.nivel_previo,
            "nivelNuevo": self.nivel_nuevo,
            "framesAntes": self.frames_antes,
            "framesDespues": self.frames_despues,
            "celdasCambiadas": self.celdas_cambiadas,
            "fraccionCambiada": round(self.fraccion_cambiada, 4),
            "pantallaNueva": self.pantalla_nueva,
            "firmaDelEvento": self.firma_del_evento,
            "accionDelEvento": self.accion_del_evento,
            "clickDelEvento": self.click_del_evento,
            "colorClickeado": self.color_clickeado,
            "celdasDeLaComponenteClickeada": self.celdas_de_la_componente_clickeada,
            "clicksPrevios": self.clicks_previos,
            "clicksPreviosEnObjeto": self.clicks_previos_en_objeto,
            "tiposDeCluster": dict(self.tipos_de_cluster),
            "sobreElTopeDeMecanica": self.sobre_el_tope_de_mecanica,
            "firmasPrevias": list(self.firmas_previas),
            "coloresAgotados": list(self.colores_agotados),
            "coloresReducidos": list(self.colores_reducidos),
            "coloresAparecidos": list(self.colores_aparecidos),
            "fraccionNoFondo": [round(f, 4) for f in self.fraccion_no_fondo],
            "llenadoMonotono": self.llenado_monotono,
            "vaciadoMonotono": self.vaciado_monotono,
            "pasosConTraslacion": self.pasos_con_traslacion,
            "coloresAlcanzados": list(self.colores_alcanzados),
            "aproximacionMonotona": list(self.aproximacion_monotona),
            "cajaDelFrenteAntes": self.caja_del_frente_antes,
            "cajaDelFrenteDespues": self.caja_del_frente_despues,
            "maniobra": self.maniobra.a_json(),
        }


__all__ = ["MedicionDeEvento"]
