export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api/health") {
      return Response.json({
        service: "futureview-api",
        status: "ok",
      });
    }

    if (url.pathname === "/api/rankings/latest") {
      const object = await env.RESEARCH.get("dashboard/latest.json");
      if (object === null) {
        return Response.json(
          {
            error: "latest ranking is not available",
          },
          { status: 503 },
        );
      }

      return new Response(object.body, {
        headers: {
          "content-type": "application/json; charset=utf-8",
          "cache-control": "no-store",
        },
      });
    }

    return env.ASSETS.fetch(request);
  },
};
