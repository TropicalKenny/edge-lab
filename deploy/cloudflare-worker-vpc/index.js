export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Method Not Allowed", {
        status: 405,
        headers: { Allow: "GET, HEAD" },
      });
    }

    const incoming = new URL(request.url);
    const target = new URL(`http://dashboard:8080${incoming.pathname}${incoming.search}`);
    const headers = new Headers(request.headers);
    headers.delete("host");
    headers.delete("cf-connecting-ip");
    headers.delete("x-forwarded-for");

    try {
      return await env.EDGE_DASHBOARD.fetch(
        new Request(target, {
          method: request.method,
          headers,
          redirect: "manual",
        }),
      );
    } catch {
      return new Response("Edge Lab dashboard unavailable", {
        status: 503,
        headers: {
          "content-type": "text/plain; charset=utf-8",
          "cache-control": "no-store",
        },
      });
    }
  },
};
