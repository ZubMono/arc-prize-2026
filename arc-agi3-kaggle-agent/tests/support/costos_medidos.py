"""[arc-agi3-kaggle-agent/tests/support/costos_medidos] BL.21701 -- FUENTE UNICA de lo que MIDIO el
barrido de presupuesto (25 juegos publicos, 2 semillas) y del modelo de extrapolacion a Kaggle.

Vive en `tests/support/` y no en `arc_agent/` a proposito: es una tabla de medicion, no conocimiento
que el agente use para decidir. Lo consume el test de extrapolacion, que es el que tiene que FALLAR
si alguien afloja el presupuesto entregado hasta un punto donde el peor caso razonable se pasa de
las 9 horas del notebook.

QUE SE PUBLICO EN LA MEDICION (y de donde sale cada numero de abajo):
  - curva de score, sin meseta: 400 acciones -> 4,0 niveles; 800 -> 5,5; 1200 -> 6,0; 1600 -> 8,5;
  - costo por accion SUPERLINEAL en CPU local: 0,154 s en los pasos 0-400 y 0,202 s en los
    1200-1600 (+31%), porque la memoria de exploracion crece con la partida;
  - extrapolacion a Kaggle con factor x1,8 sobre el CPU local, a 1600 acciones por juego:
    25 juegos 3,61 h; 50 juegos 7,21 h; 75 juegos 10,82 h (REVIENTA las 9 h);
  - peor caso con el juego mas caro medido (ft09) en los 25: 8,87 h, ya temerario.

Los costos por accion se DERIVAN de esas proyecciones publicadas en vez de escribirse a mano: si
alguien corrige una proyeccion, el costo se mueve con ella y no quedan dos verdades."""
from __future__ import annotations

#: Acciones por juego del punto mas alto que se midio (el que produjo 8,5 niveles).
ACCIONES_DEL_BARRIDO = 1600

#: Juegos publicos del barrido.
JUEGOS_DEL_BARRIDO = 25

#: Proyecciones publicadas a Kaggle, en horas, con `ACCIONES_DEL_BARRIDO` acciones por juego.
HORAS_PROYECTADAS_POR_JUEGOS: dict[int, float] = {25: 3.61, 50: 7.21, 75: 10.82}

#: Peor caso publicado: los 25 juegos costando todos como ft09, el mas caro que se midio.
HORAS_PROYECTADAS_PEOR_CASO_25 = 8.87

#: Cuantos juegos tiene el peor escenario que hay que aguantar. El set privado es de tamano
#: DESCONOCIDO -- 75 es el techo que la medicion uso para dimensionar el riesgo.
JUEGOS_DEL_PEOR_CASO = 75


def _costo_por_accion(horas: float, juegos: int, acciones: int) -> float:
    return horas * 3600.0 / (juegos * acciones)


#: Segundos de CPU de Kaggle por accion, juego PROMEDIO (deriva de la proyeccion de 25 juegos).
COSTO_MEDIO_POR_ACCION = _costo_por_accion(
    HORAS_PROYECTADAS_POR_JUEGOS[25], JUEGOS_DEL_BARRIDO, ACCIONES_DEL_BARRIDO
)

#: Segundos de CPU de Kaggle por accion del juego MAS CARO medido (ft09). Es el que manda en el
#: peor caso: nada garantiza que el set privado no sea todo ft09.
COSTO_DEL_JUEGO_MAS_CARO_POR_ACCION = _costo_por_accion(
    HORAS_PROYECTADAS_PEOR_CASO_25, JUEGOS_DEL_BARRIDO, ACCIONES_DEL_BARRIDO
)


def horas_sin_guard(juegos: int, acciones_por_juego: int, costo_por_accion: float) -> float:
    """Horas de pared de un batch SIN reloj: bajo el GIL los hilos se turnan un solo nucleo, asi
    que el tiempo de pared es la SUMA del CPU de todas las partidas. Es el modelo con el que la
    medicion produjo 3,61 / 7,21 / 10,82 h."""
    return juegos * acciones_por_juego * costo_por_accion / 3600.0


def horas_con_guard(
    juegos: int,
    acciones_por_juego: int,
    costo_por_accion: float,
    presupuesto_segundos: float,
    margen_de_cierre_segundos: float,
) -> float:
    """Horas de pared del MISMO batch con el reloj de `arc_agent/reloj_presupuesto.py`.

    El reloj corta cuando quedan menos de `margen_de_cierre` segundos, pero el corte se evalua
    ENTRE acciones: cada hilo vivo puede tener una accion en vuelo cuando suena la campana, y bajo
    el GIL esas acciones se pagan en serie. De ahi el sobrepaso `juegos * costo_por_accion` -- es
    el peor caso exacto, no una cota vaga, y es justamente lo que el margen de cierre compra.

    Un batch que termina antes de gastar el presupuesto (pocos juegos, o pocas acciones por juego)
    cuesta lo que cuesta: por eso el `min`."""
    sobrepaso = juegos * costo_por_accion
    tope_del_reloj = presupuesto_segundos - margen_de_cierre_segundos + sobrepaso
    return min(horas_sin_guard(juegos, acciones_por_juego, costo_por_accion), tope_del_reloj / 3600.0)
