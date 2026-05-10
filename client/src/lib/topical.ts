// Pure helpers for working with topical-signature vectors served by the
// cluster API (`topical_vec` on each node). Used by the canvas v2 force
// layout (lib/forceLayout.ts) to attract topically similar nodes.

export function cosine(a: number[], b: number[]): number {
  if (a.length !== b.length) return 0;
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    na  += a[i] * a[i];
    nb  += b[i] * b[i];
  }
  if (na === 0 || nb === 0) return 0;
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

/**
 * Returns a similarity in [0, 1]. Cosine on unit-norm fastembed vectors is
 * already in [-1, 1]; we clamp the negative half to 0 since "negatively
 * correlated" is not a useful signal for force attraction (we'd be telling
 * the layout to pull two opposite-meaning nodes together, which is wrong).
 */
export function topicalSimilarity(
  a: number[] | null | undefined,
  b: number[] | null | undefined,
): number {
  if (!a || !b) return 0;
  return Math.max(0, cosine(a, b));
}

if (import.meta.env.DEV) {
  console.assert(cosine([1, 0, 0], [1, 0, 0]) === 1, "identical → 1");
  console.assert(cosine([1, 0, 0], [0, 1, 0]) === 0, "orthogonal → 0");
  console.assert(Math.abs(cosine([1, 1, 0], [1, 0, 0]) - Math.SQRT1_2) < 1e-9, "45° → √2/2");
  console.assert(cosine([], []) === 0, "empty → 0");
  console.assert(cosine([1, 0], [1, 0, 0]) === 0, "mismatched len → 0");
  console.assert(cosine([0, 0, 0], [1, 0, 0]) === 0, "zero magnitude → 0");
  console.assert(topicalSimilarity(null, [1]) === 0, "null → 0");
  console.assert(topicalSimilarity([1], null) === 0, "null → 0");
  console.assert(topicalSimilarity(undefined, undefined) === 0, "undef → 0");
  console.assert(topicalSimilarity([1, 0, 0], [-1, 0, 0]) === 0, "negative correlation clamped → 0");
  console.assert(topicalSimilarity([1, 0, 0], [1, 0, 0]) === 1, "identical → 1");
}
