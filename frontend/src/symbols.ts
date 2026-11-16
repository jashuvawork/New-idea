/** Active symbols from deployment status, else equity defaults. */

export const DEFAULT_SYMBOLS = ['NIFTY', 'SENSEX'] as const;

export type TradeSymbol = string;

export function symbolsFromDeployment(
  deployment: { symbols?: string[] | null; flags?: Record<string, unknown> | null } | null | undefined,
): readonly TradeSymbol[] {
  const direct = deployment?.symbols;
  const fromFlags = deployment?.flags?.symbols;
  const raw = (Array.isArray(direct) && direct.length ? direct : fromFlags) as unknown;
  const fromApi = Array.isArray(raw)
    ? raw.map((s) => String(s || '').trim().toUpperCase()).filter(Boolean)
    : [];
  if (fromApi.length) {
    return fromApi;
  }
  return DEFAULT_SYMBOLS;
}