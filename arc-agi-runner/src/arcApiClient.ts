/* [arc-agi-runner/arcApiClient] BL.20775 -- cliente HTTP contra la API oficial ARC-AGI-3
   (https://docs.arcprize.org/rest_overview). Implementacion directa contra HTTP en vez de invocar
   el SDK Python arc_agi via subproceso: la decision de diseno de BL.20775 habilita ese fallback
   explicitamente ("no bloquees el BL por eso") si el SDK no se puede usar limpiamente -- el SDK
   Python es un wrapper delgado sobre ESTA MISMA API REST, asi que ir directo por HTTP es
   funcionalmente equivalente, evita acoplar el runtime Node a un venv Python pineado (peor para
   licencia de dominio publico / portabilidad) y es mucho mas facil de testear con mocks (fetch
   nativo).

   Cada llamada usa AbortSignal.timeout(stepTimeoutMs) -- tope duro de 60s por step (diseno). */

import type {
  ArcAction,
  ArcCloseScorecardResponse,
  ArcFrameResponse,
  ArcGameSummary,
  ArcOpenScorecardOptions,
  ArcOpenScorecardResponse,
} from './types';

export interface ArcApiClientOptions {
  apiKey: string;
  baseUrl: string;
  stepTimeoutMs: number;
  /** Inyectable para tests -- default: fetch nativo del runtime. */
  fetchImpl?: typeof fetch;
}

export interface ArcCommandBody {
  game_id: string;
  card_id?: string;
  guid?: string | null;
  x?: number;
  y?: number;
  reasoning?: Record<string, unknown>;
}

export interface ArcApiClient {
  listGames(): Promise<ArcGameSummary[]>;
  openScorecard(opts?: ArcOpenScorecardOptions): Promise<string>;
  closeScorecard(cardId: string): Promise<ArcCloseScorecardResponse>;
  sendCommand(action: ArcAction, body: ArcCommandBody): Promise<ArcFrameResponse>;
}

/** Crea un cliente contra la API ARC-AGI-3. Mantiene internamente la cookie de sesion
 *  (`AWSALB*`, requerida por el balanceador para rutear al mismo backend) entre llamadas del mismo
 *  cliente -- sin esto, RESET y las ACTIONs subsiguientes pueden aterrizar en instancias distintas
 *  y perder el estado del juego. */
export function createArcApiClient(opts: ArcApiClientOptions): ArcApiClient {
  const fetchFn = opts.fetchImpl ?? fetch;
  let sessionCookies: string | undefined;

  function captureSetCookie(headers: Headers): void {
    let cookiesFromResponse: string[] = [];
    // BL.20775: getSetCookie() no esta en el tipo Headers de todos los lib.dom.ts -- feature
    // detection en runtime (Node 24 / undici lo soporta).
    const headersWithGetSetCookie = headers as Headers & { getSetCookie?: () => string[] };
    if (typeof headersWithGetSetCookie.getSetCookie === 'function') {
      cookiesFromResponse = headersWithGetSetCookie.getSetCookie();
    } else {
      const single = headers.get('set-cookie');
      if (single) cookiesFromResponse = [single];
    }
    if (cookiesFromResponse.length > 0) {
      sessionCookies = cookiesFromResponse.map((c) => c.split(';')[0]).join('; ');
    }
  }

  async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers: Record<string, string> = {
      'X-API-Key': opts.apiKey,
      'Content-Type': 'application/json',
    };
    if (sessionCookies) headers.Cookie = sessionCookies;

    const res = await fetchFn(`${opts.baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(opts.stepTimeoutMs),
    });

    captureSetCookie(res.headers);

    if (!res.ok) {
      const text = await res.text().catch(() => '');
      throw new Error(
        `[arc-agi-runner/arcApiClient] ${method} ${path} -> HTTP ${res.status}: ${text.slice(0, 300)}`,
      );
    }
    return (await res.json()) as T;
  }

  return {
    listGames: () => request<ArcGameSummary[]>('GET', '/api/games'),

    async openScorecard(o?: ArcOpenScorecardOptions): Promise<string> {
      const res = await request<ArcOpenScorecardResponse>('POST', '/api/scorecard/open', o ?? {});
      return res.card_id;
    },

    closeScorecard: (cardId: string) =>
      request<ArcCloseScorecardResponse>('POST', '/api/scorecard/close', { card_id: cardId }),

    sendCommand: (action: ArcAction, body: ArcCommandBody) =>
      request<ArcFrameResponse>('POST', `/api/cmd/${action}`, body),
  };
}
