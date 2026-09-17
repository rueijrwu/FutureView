import { ReplaySession as DisplayReplaySession } from "./replay-session-display.js";

export class ReplaySession extends DisplayReplaySession {
  async fetch(request) {
    if (request.headers.get("upgrade")?.toLowerCase() === "websocket") {
      if (!this.session) return new Response("Session not initialized", { status: 409 });
      const requestUserId = Number(request.headers.get("x-futureview-user-id"));
      if (!Number.isFinite(requestUserId) || requestUserId <= 0) {
        return new Response("Replay session authentication is unavailable", { status: 401 });
      }
      if (this.session.userId == null) {
        // Transitional compatibility for sessions created before ownership was persisted.
        this.session.userId = requestUserId;
        await this.ctx.storage.put("session", this.session);
      } else if (Number(this.session.userId) !== requestUserId) {
        return new Response("Replay session belongs to another user", { status: 403 });
      }
    }
    return super.fetch(request);
  }
}

export { default } from "./main.js";
