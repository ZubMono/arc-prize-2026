/* [arc-agi-runner/worldModel/bl21593.posterior.test] BL.21593 -- contrato del posterior
   jerarquico boton->mecanica con verosimilitud que explica el fallo, y de la percepcion de pared.
   Espejo EXACTO de arc-agi3-kaggle-agent/tests/test_bl21593_posterior.py: la seccion PARIDAD
   afirma los MISMOS numeros sobre la MISMA secuencia guionada -- si un puerto cambia una
   verosimilitud o el orden de una suma y el otro no, uno de los dos se pone en rojo. */
import { describe, expect, it } from 'vitest';

import { CreenciaDeDirecciones, ESTADO_REMAPEADA } from '../directionBeliefs';
import {
  ARQUETIPO_MIXTO,
  ARQUETIPO_MUEVE,
  ARQUETIPO_SIN_FLECHAS,
  ARQUETIPO_SIN_MAPEO,
  condicionalDeMecanicas,
  EVENTO_DESCONOCIDA,
  EVENTO_OTRA,
  EVENTO_SIN_CAMBIO,
  EVENTO_TRASLACION,
  MECANICA_DESCONOCIDA,
  MECANICA_INERTE,
  PISO_DESCONOCIDO,
  PosteriorDeMapeo,
  priorDeArquetipos,
  UMBRAL_RESOLUCION,
  type EventoObservado,
} from '../mechanicsPosterior';
import type { Mecanica } from '../objectMechanics';
import {
  contextoDePared,
  PARED_AUSENTE,
  PARED_DESCONOCIDA,
  PARED_PRESENTE,
  profundidadDeSondeo,
  RastreadorDeAvatar,
  type ContextoDePared,
} from '../wallPerception';

const PARED_SOLO_ARRIBA: Record<string, ContextoDePared> = {
  arriba: PARED_PRESENTE,
  abajo: PARED_AUSENTE,
  izquierda: PARED_AUSENTE,
  derecha: PARED_AUSENTE,
};
const SIN_PARED: Record<string, ContextoDePared> = {
  arriba: PARED_AUSENTE,
  abajo: PARED_AUSENTE,
  izquierda: PARED_AUSENTE,
  derecha: PARED_AUSENTE,
};

function traslacionEvento(dy: number, dx: number, enCorrida: boolean): EventoObservado {
  return { tipo: EVENTO_TRASLACION, signo: [dy, dx], enCorrida };
}

function mecanicaDeTraslacion(dy: number, dx: number): Mecanica {
  const t = { dy, dx, minY: 5, minX: 5, alto: 2, ancho: 2, cobertura: 1, relleno: 1 };
  return {
    tipo: 'traslacion',
    celdasCambiadas: 8,
    clusters: [],
    traslacionPrincipal: t,
    cambioDeColorPrincipal: null,
  };
}

describe('BL.21593 -- posterior jerarquico con verosimilitud que explica el fallo', () => {
  it('el prior solo JAMAS resuelve en ningun conjunto medido', () => {
    for (const conjunto of [
      '1,2,3,4',
      '1,2,3,4,5',
      '1,2,3,4,5,6',
      '1,2,3,4,6',
      '1,2,3,4,6,7',
      '3,4,6,7',
    ]) {
      const post = new PosteriorDeMapeo();
      post.sembrar(conjunto.split(',').map(Number));
      for (const boton of post.botones) {
        const dominante = post.mecanicaDominante(boton);
        expect(dominante, `${conjunto} ${boton}`).not.toBeNull();
        expect((dominante as [string, number])[1], `${conjunto} ${boton}`).toBeLessThan(
          UMBRAL_RESOLUCION,
        );
        expect(post.resuelta(boton), `${conjunto} ${boton}`).toBe(false);
      }
    }
  });

  it('mapeo sintetico CONTRARIO al prior: el posterior remapea y la creencia tambien', () => {
    const creencia = new CreenciaDeDirecciones();
    creencia.sembrar([1, 2, 3, 4]);
    for (let i = 0; i < 3; i++) creencia.observar('ACTION1', mecanicaDeTraslacion(2, 0));
    expect(creencia.estadoDe('ACTION1')).toBe(ESTADO_REMAPEADA);
    expect(creencia.direccionDe('ACTION1')).toEqual([1, 0]);
    const dominante = creencia.posterior.mecanicaDominante('ACTION1') as [string, number];
    expect(dominante[0]).toBe('abajo');
    expect(dominante[1]).toBeGreaterThanOrEqual(UMBRAL_RESOLUCION);
    expect(creencia.posterior.direccionDe('ACTION1')).toEqual([1, 0]);
  });

  it('una traslacion invertida AISLADA no remapea (ambiguedad objeto/hueco medida)', () => {
    const post = new PosteriorDeMapeo();
    post.sembrar([1, 2, 3, 4]);
    post.observar('ACTION1', traslacionEvento(1, 0, false));
    expect((post.mecanicaDominante('ACTION1') as [string, number])[0]).toBe('arriba');
  });

  it('fallo con pared adyacente: el posterior del mapeo NO baja (numeros exactos)', () => {
    const post = new PosteriorDeMapeo();
    post.sembrar([1, 2, 3, 4, 6]);
    const antes = (post.posteriorDe('ACTION1') as Record<string, number>).arriba;
    post.observar('ACTION1', { tipo: EVENTO_SIN_CAMBIO, pared: PARED_SOLO_ARRIBA });
    const despues = (post.posteriorDe('ACTION1') as Record<string, number>).arriba;
    expect(antes).toBeCloseTo(0.6135416666666667, 12);
    expect(despues).toBeCloseTo(0.705098214922535, 12);
    expect(despues).toBeGreaterThanOrEqual(antes); // quedo totalmente explicado por la pared
  });

  it('el MISMO fallo sin pared SI lo baja', () => {
    const post = new PosteriorDeMapeo();
    post.sembrar([1, 2, 3, 4, 6]);
    const antes = (post.posteriorDe('ACTION1') as Record<string, number>).arriba;
    post.observar('ACTION1', { tipo: EVENTO_SIN_CAMBIO, pared: SIN_PARED });
    const despues = (post.posteriorDe('ACTION1') as Record<string, number>).arriba;
    expect(despues).toBeCloseTo(0.19662188014376653, 12);
    expect(despues).toBeLessThan(antes - 0.4);
  });

  it('fallo con pared inobservable: aporta poco pero no cero', () => {
    const post = new PosteriorDeMapeo();
    post.sembrar([1, 2, 3, 4, 6]);
    const antes = (post.posteriorDe('ACTION1') as Record<string, number>).arriba;
    post.observar('ACTION1', { tipo: EVENTO_SIN_CAMBIO });
    const despues = (post.posteriorDe('ACTION1') as Record<string, number>).arriba;
    expect(despues).toBeLessThan(antes);
    expect(antes - despues).toBeLessThan(0.2);
  });

  it('juego degenerado: resuelve por arquetipo sin colgarse, en los pasos exactos', () => {
    const post = new PosteriorDeMapeo();
    post.sembrar([1, 2, 3, 4, 6, 7]);
    const pasoResuelto: Record<string, number> = {};
    for (let i = 0; i < 40 && Object.keys(pasoResuelto).length < 4; i++) {
      const boton = `ACTION${(i % 4) + 1}`;
      post.observar(boton, { tipo: EVENTO_SIN_CAMBIO });
      for (const b of post.botones) {
        if (pasoResuelto[b] === undefined && post.resuelta(b)) pasoResuelto[b] = i + 1; // @proto-safe: claves ACTION1..4
      }
    }
    expect(pasoResuelto).toEqual({ ACTION1: 9, ACTION2: 10, ACTION3: 10, ACTION4: 10 });
    for (const b of post.botones) expect(post.inerte(b), b).toBe(true);
    expect(post.posteriorDeArquetipo()[ARQUETIPO_SIN_MAPEO]).toBeGreaterThan(0.9);
  });

  it('sin flechas no hay nada que inferir', () => {
    const post = new PosteriorDeMapeo();
    expect(post.sembrar([6])).toBe(0);
    expect(post.botones).toEqual([]);
    expect(post.posteriorDeArquetipo()[ARQUETIPO_SIN_FLECHAS]).toBe(1.0);
    expect(post.posteriorDe('ACTION1')).toBeNull();
    post.observar('ACTION1', { tipo: EVENTO_SIN_CAMBIO }); // no explota ni acumula
    expect(post.observacionesDe('ACTION1')).toBe(0);
  });

  it('la masa desconocida NUNCA baja del piso', () => {
    const post = new PosteriorDeMapeo();
    post.sembrar([1, 2, 3, 4]);
    expect(
      (post.posteriorDe('ACTION1') as Record<string, number>)[MECANICA_DESCONOCIDA],
    ).toBeGreaterThanOrEqual(PISO_DESCONOCIDO);
    for (let i = 0; i < 10; i++) post.observar('ACTION1', traslacionEvento(-1, 0, true));
    expect(
      (post.posteriorDe('ACTION1') as Record<string, number>)[MECANICA_DESCONOCIDA],
    ).toBeGreaterThanOrEqual(PISO_DESCONOCIDO);
    for (const arquetipo of [ARQUETIPO_MUEVE, ARQUETIPO_SIN_MAPEO, ARQUETIPO_MIXTO]) {
      expect(
        condicionalDeMecanicas(arquetipo, 'ACTION1')[MECANICA_DESCONOCIDA],
      ).toBeGreaterThanOrEqual(PISO_DESCONOCIDO);
    }
  });

  it('la masa desconocida acumula y se REGISTRA como senal de vocabulario incompleto', () => {
    const post = new PosteriorDeMapeo();
    post.sembrar([1, 2, 3, 4]);
    for (let i = 0; i < 5; i++) post.observar('ACTION1', { tipo: EVENTO_DESCONOCIDA });
    expect(
      (post.posteriorDe('ACTION1') as Record<string, number>)[MECANICA_DESCONOCIDA],
    ).toBeGreaterThan(0.9);
    const senal = post.senalDeVocabularioIncompleto();
    expect(senal.length).toBeGreaterThan(0);
    expect(senal[0][0]).toBe('ACTION1');
    expect(post.resumen()).toContain('vocabularioIncompleto=ACTION1');
  });

  it('sin acumulacion no hay senal', () => {
    const post = new PosteriorDeMapeo();
    post.sembrar([1, 2, 3, 4]);
    for (let i = 0; i < 6; i++) post.observar('ACTION1', traslacionEvento(-1, 0, true));
    expect(post.senalDeVocabularioIncompleto()).toEqual([]);
    expect(post.resumen()).not.toContain('vocabularioIncompleto');
  });
});

describe('BL.21593 -- percepcion de pared', () => {
  it('borde, obstaculo y piso libre', () => {
    const grilla = Array.from({ length: 6 }, () => Array<number>(6).fill(0));
    grilla[1][2] = 3;
    grilla[1][3] = 3;
    const contexto = contextoDePared(grilla, [2, 2, 2, 2], 0, 1);
    expect(contexto.arriba).toBe(PARED_PRESENTE);
    expect(contexto.abajo).toBe(PARED_AUSENTE);
    expect(contexto.izquierda).toBe(PARED_AUSENTE);
    expect(contexto.derecha).toBe(PARED_AUSENTE);
    expect(contextoDePared(grilla, [2, 0, 2, 2], 0, 1).izquierda).toBe(PARED_PRESENTE);
    expect(new Set(Object.values(contextoDePared(grilla, null, 0, 1)))).toEqual(
      new Set([PARED_DESCONOCIDA]),
    );
  });

  it('la profundidad de sondeo usa la magnitud medida', () => {
    expect(profundidadDeSondeo([0, 4])).toBe(4);
    expect(profundidadDeSondeo([-2, 0])).toBe(2);
    expect(profundidadDeSondeo(null)).toBe(6); // maxima magnitud medida en los 25 juegos
    const grilla = Array.from({ length: 8 }, () => Array<number>(8).fill(0));
    grilla[2][6] = 5;
    expect(contextoDePared(grilla, [2, 2, 1, 2], 0, 3).derecha).toBe(PARED_PRESENTE);
    expect(contextoDePared(grilla, [2, 2, 1, 2], 0, 2).derecha).toBe(PARED_AUSENTE);
  });

  it('el rastreador de avatar aprende caja destino y piso desalojado', () => {
    const tracker = new RastreadorDeAvatar();
    expect(tracker.caja).toBeNull();
    expect(tracker.piso).toBeNull();
    const post = Array.from({ length: 10 }, () => Array<number>(10).fill(7));
    tracker.observar(mecanicaDeTraslacion(0, 2), post);
    expect(tracker.caja).toEqual([5, 7, 2, 2]);
    expect(tracker.piso).toBe(7);
    tracker.observar(null, post); // sin mecanica no se pierde lo aprendido
    expect(tracker.caja).toEqual([5, 7, 2, 2]);
  });
});

describe('BL.21593 -- PARIDAD TS<->Python: secuencia guionada, numeros exactos', () => {
  it('los mismos valores que test_bl21593_posterior.py', () => {
    const prior = priorDeArquetipos('1,2,3,4,6');
    expect(prior[ARQUETIPO_MUEVE]).toBeCloseTo(0.6666666666666666, 12);
    expect(prior[ARQUETIPO_SIN_MAPEO]).toBeCloseTo(0.16666666666666666, 12);

    const condicional = condicionalDeMecanicas(ARQUETIPO_MUEVE, 'ACTION1');
    expect(condicional.arriba).toBeCloseTo(0.8421875, 12);
    expect(condicional[MECANICA_INERTE]).toBeCloseTo(0.08421875, 12);
    expect(condicional[MECANICA_DESCONOCIDA]).toBeCloseTo(0.02, 12);

    const post = new PosteriorDeMapeo();
    post.sembrar([1, 2, 3, 4, 6]);
    const secuencia: Array<[string, EventoObservado]> = [
      ['ACTION1', traslacionEvento(-1, 0, false)],
      ['ACTION1', traslacionEvento(-1, 0, true)],
      ['ACTION1', { tipo: EVENTO_SIN_CAMBIO, pared: PARED_SOLO_ARRIBA }],
      ['ACTION2', { tipo: EVENTO_SIN_CAMBIO }],
      ['ACTION2', { tipo: EVENTO_OTRA }],
      ['ACTION3', traslacionEvento(0, 1, false)],
      ['ACTION3', traslacionEvento(0, 1, true)],
      ['ACTION4', { tipo: EVENTO_DESCONOCIDA }],
    ];
    for (const [boton, evento] of secuencia) post.observar(boton, evento);

    /* BL.21853 -- estos numeros se movieron y el motivo esta acotado: la secuencia trae un
       `EVENTO_OTRA` (ACTION2) y ese evento cambio de significado. Antes era una mecanica visible
       LIMPIA y valia 0.02 contra direccion; ahora las limpias tienen simbolo propio y `otra` es una
       MEZCLA de nombradas, que no dice nada de la direccion (0.05, el agnostico). Los viejos:
       0.3776718132885108 / 0.010309277864293129 / 0.6120189088471961 y 0.9789587996514236 /
       0.0001636974977446143 / 0.8163523655691687 / 0.12215670282992136 / 0.28209776424641375. */
    const arquetipo = post.posteriorDeArquetipo();
    expect(arquetipo[ARQUETIPO_MUEVE]).toBeCloseTo(0.5688291285974195, 12);
    expect(arquetipo[ARQUETIPO_SIN_MAPEO]).toBeCloseTo(0.005828319251220946, 12);
    expect(arquetipo[ARQUETIPO_MIXTO]).toBeCloseTo(0.42534255215135947, 12);

    const a1 = post.posteriorDe('ACTION1') as Record<string, number>;
    expect(a1.arriba).toBeCloseTo(0.9792963850466587, 12);
    expect(a1[MECANICA_INERTE]).toBeCloseTo(0.0001093939908892459, 12);
    expect(a1[MECANICA_DESCONOCIDA]).toBeCloseTo(0.02, 12);

    const a3 = post.posteriorDe('ACTION3') as Record<string, number>;
    expect(a3.derecha).toBeCloseTo(0.7743672062320239, 12); // remapeo en curso
    expect(a3.izquierda).toBeCloseTo(0.16786683056108737, 12);

    const a4 = post.posteriorDe('ACTION4') as Record<string, number>;
    expect(a4[MECANICA_DESCONOCIDA]).toBeCloseTo(0.2566517422907669, 12);
  });
});
