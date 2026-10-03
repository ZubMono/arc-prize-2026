/* [arc-agi-runner/worldModel/directionPriors] BL.21590 -- ARCHIVO GENERADO por
   arc-agi3-kaggle-agent/scripts/fit_click_priors.py. NO editar a mano.

   Los MISMOS numeros que `DIRECTION_PRIORS` de `arc_agent/priors.py`: un solo lugar los
   emite, dos puertos los consumen. Prior de direcciones indexado por CONJUNTO DE ACCIONES
   DISPONIBLES -- jamas por game_id, que en la evaluacion privada vale cero.

   Es una HIPOTESIS INICIAL REFUTABLE: `directionBeliefs.ts` la confirma o la remapea con
   una CORRIDA MONOTONA (traslaciones del mismo signo en pulsaciones consecutivas de la
   misma accion -- la macro de BL.21559 la produce gratis), y la deja en 'sinEvidencia'
   cuando la flecha no mueve nada. Fija la DIRECCION, nunca la magnitud. */

export interface ConfianzaDeConjunto {
  juegos: number;
  confirman: number;
  sinMovimiento: number;
}

export interface DirectionPriors {
  version: number;
  generatedAt: string;
  nJuegosMedidos: number;
  nJuegosConFlechas: number;
  nJuegosQueConfirman: number;
  nJuegosSinMovimientoObservable: number;
  nAccionesDeSonda: number;
  traslacionesCanonicas: number;
  traslacionesContradictorias: number;
  contradiccionesSinExplicar: number;
  excepcionesDeMapeo: number;
  /** (dy, dx) normalizados a SIGNO -- y crece hacia abajo, x hacia la derecha. */
  mapeoCanonico: Readonly<Record<string, readonly number[]>>;
  juegosQueConfirmanPorAccion: Readonly<Record<string, number>>;
  juegosQueContradicenPorAccion: Readonly<Record<string, number>>;
  /** Clave = numeros de accion disponibles, ordenados y separados por coma. */
  conjuntosMedidos: Readonly<Record<string, ConfianzaDeConjunto>>;
  accionesSinPriorDeDireccion: readonly string[];
  semanticaAction5: {
    juegosMedidos: number;
    comportamientosDistintos: number;
    juegosConDireccionConsistente: number;
  };
  magnitudesDePasoMedidas: readonly number[];
}

export const DIRECTION_PRIORS: DirectionPriors = {
  version: 1,
  generatedAt: '2026-08-17T20:24:51Z',
  nJuegosMedidos: 25,
  nJuegosConFlechas: 17,
  nJuegosQueConfirman: 11,
  nJuegosSinMovimientoObservable: 6,
  nAccionesDeSonda: 2673,
  traslacionesCanonicas: 528,
  traslacionesContradictorias: 40,
  contradiccionesSinExplicar: 0,
  excepcionesDeMapeo: 0,
  mapeoCanonico: {
    ACTION1: [-1, 0],
    ACTION2: [1, 0],
    ACTION3: [0, -1],
    ACTION4: [0, 1],
  },
  juegosQueConfirmanPorAccion: {
    ACTION1: 10,
    ACTION2: 10,
    ACTION3: 9,
    ACTION4: 9,
  },
  juegosQueContradicenPorAccion: {
    ACTION1: 0,
    ACTION2: 0,
    ACTION3: 0,
    ACTION4: 0,
  },
  conjuntosMedidos: {
    '1,2,3,4': {
      juegos: 3,
      confirman: 1,
      sinMovimiento: 2,
    },
    '1,2,3,4,5': {
      juegos: 3,
      confirman: 2,
      sinMovimiento: 1,
    },
    '1,2,3,4,5,6': {
      juegos: 4,
      confirman: 3,
      sinMovimiento: 1,
    },
    '1,2,3,4,5,6,7': {
      juegos: 1,
      confirman: 1,
      sinMovimiento: 0,
    },
    '1,2,3,4,6': {
      juegos: 3,
      confirman: 3,
      sinMovimiento: 0,
    },
    '1,2,3,4,6,7': {
      juegos: 2,
      confirman: 1,
      sinMovimiento: 1,
    },
    '3,4,6,7': {
      juegos: 1,
      confirman: 0,
      sinMovimiento: 1,
    },
    '5,6,7': {
      juegos: 1,
      confirman: 0,
      sinMovimiento: 1,
    },
    '6': {
      juegos: 6,
      confirman: 0,
      sinMovimiento: 6,
    },
    '6,7': {
      juegos: 1,
      confirman: 0,
      sinMovimiento: 1,
    },
  },
  accionesSinPriorDeDireccion: ['ACTION5', 'ACTION6', 'ACTION7'],
  semanticaAction5: {
    juegosMedidos: 12,
    comportamientosDistintos: 4,
    juegosConDireccionConsistente: 0,
  },
  magnitudesDePasoMedidas: [2, 3, 4, 5, 6],
};
