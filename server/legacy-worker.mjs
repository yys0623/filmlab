import app from './worker.mjs';

// Keep asset/API URLs available for tabs opened before the hostname migration.
// New visits to either entry point move to sosang, retaining query parameters.
export default {
  async fetch(request, env) {
    const target = new URL(request.url);
    if ((request.method === 'GET' || request.method === 'HEAD') &&
        (target.pathname === '/' || target.pathname === '/index.html')) {
      target.protocol = 'https:';
      target.host = 'sosang.film-lab-jc.workers.dev';
      return Response.redirect(target.toString(), 308);
    }
    return app.fetch(request, env);
  },
};
