/* [arc-agi-runner/worldModel/clickPriors] BL.21560 -- ARCHIVO GENERADO por
   arc-agi3-kaggle-agent/scripts/fit_click_priors.py. NO editar a mano.

   Los MISMOS numeros se emiten a `arc_agent/priors.py`: un solo ajuste, dos puertos, para que
   la politica que juega contra la API oficial y la que va al notebook de Kaggle no diverjan en
   silencio. Orden de `pesosClick`: el de `CLICK_FEATURE_NAMES` en clickFeatures.ts. */

export interface ClickPriors {
  version: number;
  generatedAt: string;
  nJuegosObservados: number;
  nTransicionesObservadas: number;
  /** Pesos posicionales, en el orden de `CLICK_FEATURE_NAMES` (clickFeatures.ts). */
  pesosClick: readonly number[];
  umbralesDetectores: {
    probabilidadMinimaDeClick: number;
    similitudDeParcheMinima: number;
  };
  ordenAcciones: readonly string[];
}

export const CLICK_PRIORS: ClickPriors = {
  version: 1,
  generatedAt: '2026-08-17T20:24:51Z',
  nJuegosObservados: 5,
  nTransicionesObservadas: 749,
  pesosClick: [-2.241823, 0.267326, 0.231820, 1.012707, -0.070761, -1.012849, -0.006758, -2.185072, -0.135375],
  umbralesDetectores: {
    probabilidadMinimaDeClick: 0.245268,
    similitudDeParcheMinima: 1.000000,
  },
  ordenAcciones: ['ACTION2', 'ACTION4', 'ACTION3', 'ACTION1', 'ACTION7', 'ACTION6', 'ACTION5'],
};
