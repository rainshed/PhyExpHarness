// Backend offsets count Unicode code points (Python str), not UTF-16 units or bytes.
export const evidenceEnd = page => page.offset + Array.from(page.text).length;
