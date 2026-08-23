export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/api/health") {
      return Response.json({
        service: "futureview-api",
        status: "ok",
      });
    }

    return env.ASSETS.fetch(request);
  },
};
