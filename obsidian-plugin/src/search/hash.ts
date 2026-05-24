export async function sha256(text: string): Promise<string> {
  const cryptoApi = (globalThis as { crypto?: Crypto }).crypto;
  if (cryptoApi?.subtle) {
    const data = new TextEncoder().encode(text);
    const digest = await cryptoApi.subtle.digest("SHA-256", data);
    return Array.from(new Uint8Array(digest))
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
  }
  // Fallback: simple non-crypto hash; only used in test environments without
  // SubtleCrypto. Keep deterministic so warm-start comparisons remain stable.
  let hash = 0;
  for (let i = 0; i < text.length; i++) {
    hash = (Math.imul(31, hash) + text.charCodeAt(i)) | 0;
  }
  return `fallback-${(hash >>> 0).toString(16)}`;
}
