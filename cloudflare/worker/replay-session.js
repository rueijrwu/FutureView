import { ReplaySession as CoreReplaySession } from "./replay-session-core.js";

export class ReplaySession extends CoreReplaySession {
  async _release(count) {
    const contract = (await this._manifest()).contracts[this.session.contract];
    const released = [];
    const trading = this._trading();

    while (released.length < count) {
      const shardMeta = contract.shards[this.session.shardIndex];
      if (!shardMeta) {
        this.session.state = "FINISHED";
        break;
      }

      if (!this.shard || this.shardKey !== shardMeta.key) {
        await this._loadShard(this.session.shardIndex);
      }

      const start = this.session.barIndex + 1;
      if (start < this.shard.length) {
        const take = Math.min(count - released.length, this.shard.length - start);
        const end = start + take;
        for (let index = start; index < end; index += 1) {
          this.session.barIndex = index;
          const bar = this.shard[index];
          if (trading.pendingOrders.length) await this._fillPendingOrders(bar);
          trading.lastPrice = bar.c;
          released.push(bar);
        }
        continue;
      }

      if (this.session.shardIndex + 1 >= contract.shards.length) {
        this.session.state = "FINISHED";
        break;
      }

      this.session.shardIndex += 1;
      this.session.barIndex = -1;
      this.shard = null;
      this.shardKey = null;
    }

    return released;
  }
}
