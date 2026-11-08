// Cloudflare supplies this country code; no IP address or location is stored.
// Missing geolocation lets the browser apply its own language fallback.
export function localeForCountry(country) {
  if (typeof country !== 'string' || !/^[A-Z]{2}$/.test(country) || country === 'XX') return null;
  return country === 'KR' ? 'ko' : 'en';
}

export default {
  async fetch(request, env) {
    if (new URL(request.url).pathname !== '/api/locale') return env.ASSETS.fetch(request);
    const headers = {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    };
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return new Response(JSON.stringify({ error: 'method_not_allowed' }), {
        status: 405,
        headers: { ...headers, Allow: 'GET, HEAD' },
      });
    }
    // Do not trust query parameters or caller-supplied country/language headers.
    const locale = localeForCountry(request.cf?.country);
    return new Response(request.method === 'HEAD' ? null : JSON.stringify({ locale }), { headers });
  },
};
