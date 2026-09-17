import { ReplaySession as CoreReplaySession } from "./replay-session-core.js";

export class ReplaySession extends CoreReplaySession {
  _maybePrefetchCanonicalShard(contract) {
    const currentIndex = Number(this.session?.shardIndex);
    const currentBars = this.shard;
    if (!Number.isInteger(currentIndex) || !Array.isArray(currentBars) || currentBars.length < 1024) return;
    const threshold = Math.floor((currentBars.length - 1) * 0.75);
    if (Number(this.session?.barIndex) < threshold) return;

    const nextIndex = currentIndex + 1;
    const nextMeta = contract?.shards?.[nextIndex];
    if (!nextMeta) return;
    const existing = this._fvCanonicalPrefetch;
    if (existing?.index === nextIndex && existing?.key === nextMeta.key) return;

    const entry = {
      index: nextIndex,
      key: nextMeta.key,
      bars: null,
      promise: null,
    };
    entry.promise = this._loadShardForContract(contract, nextIndex)
      .then((bars) => {
        entry.bars = bars;
        return bars;
      })
      .catch((error) => {
        if (this._fvCanonicalPrefetch === entry) this._fvCanonicalPrefetch = null;
        throw error;
      });
    this._fvCanonicalPrefetch = entry;
    this.ctx?.waitUntil?.(entry.promise.then(() => undefined, () => undefined));
  }

  async _loadCanonicalShardForRelease(contract, index) {
    const meta = contract?.shards?.[index];
    if (!meta) return null;
    if (this.shard && this.shardKey === meta.key) return this.shard;

    const prefetched = this._fvCanonicalPrefetch;
    if (prefetched?.index === index && prefetched?.key === meta.key) {
      try {
        const bars = prefetched.bars ?? await prefetched.promise;
        if (bars) {
          this.shard = bars;
          this.shardKey = meta.key;
          if (this._fvCanonicalPrefetch === prefetched) this._fvCanonicalPrefetch = null;
          return bars;
        }
      } catch {
        if (this._fvCanonicalPrefetch === prefetched) this._fvCanonicalPrefetch = null;
      }
    }

    return this._loadShard(index);
  }

  async init(body) {
    const result = await super.init(body);
    const contract = this.manifest?.contracts?.[this.session?.contract];
    if (contract) this._maybePrefetchCanonicalShard(contract);
    return result;
  }

  _findShardAtOrAfter(contract, start) {
    const shards = contract?.shards || [];
    let lo = 0;
    let hi = shards.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (Number(shards[mid].last_time) >= Number(start)) hi = mid;
      else lo = mid + 1;
    }
    return lo < shards.length ? lo : -1;
  }

  _findBarAtOrAfter(bars, start) {
    let lo = 0;
    let hi = bars.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (Number(bars[mid].t) >= Number(start)) hi = mid;
      else lo = mid + 1;
    }
    return lo < bars.length ? lo : -1;
  }

  _residentShard(contract, index) {
    const meta = contract?.shards?.[index];
    if (!meta || !this.shard || this.shardKey !== meta.key) return null;
    return this.shard;
  }

  async _warmupBars(shardIndex, barIndex, count) {
    const manifest = this.manifest ?? await this._manifest();
    const contract = manifest.contracts[this.session.contract];
    let remaining = count;
    let index = shardIndex;
    const chunks = [];

    while (index >= 0 && remaining > 0) {
      const bars = this._residentShard(contract, index)
        ?? await this._loadShardForContract(contract, index);
      const takeEnd = index === shardIndex ? barIndex + 1 : bars.length;
      const takeStart = Math.max(0, takeEnd - remaining);
      chunks.unshift(bars.slice(takeStart, takeEnd));
      remaining -= takeEnd - takeStart;
      index -= 1;
    }

    const current = this._residentShard(contract, shardIndex)
      ?? await this._loadShardForContract(contract, shardIndex);
    const cursor = current[barIndex];
    const flattened = chunks.flat();
    if (!flattened.length || flattened.at(-1)?.t !== cursor.t) flattened.push(cursor);
    return flattened;
  }

  _lowerBoundCanonicalTime(bars, target, start = 0) {
    let lo = Math.max(0, Number(start) || 0);
    let hi = bars.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (Number(bars[mid].t) >= Number(target)) hi = mid;
      else lo = mid + 1;
    }
    return lo;
  }

  async _releaseUntilBefore(targetExclusive, maxCount = 2000) {
    const contract = (await this._manifest()).contracts[this.session.contract];
    const released = [];
    const trading = this._trading();
    targetExclusive = Number(targetExclusive);

    while (released.length < maxCount) {
      const shardMeta = contract.shards[this.session.shardIndex];
      if (!shardMeta) {
        this.session.state = "FINISHED";
        break;
      }
      if (!this.shard || this.shardKey !== shardMeta.key) {
        await this._loadCanonicalShardForRelease(contract, this.session.shardIndex);
      }

      const start = this.session.barIndex + 1;
      const end = this._lowerBoundCanonicalTime(this.shard, targetExclusive, start);
      const available = Math.max(0, end - start);
      const take = Math.min(available, maxCount - released.length);
      for (let index = start; index < start + take; index += 1) {
        this.session.barIndex = index;
        const bar = this.shard[index];
        if (trading.pendingOrders.length) await this._fillPendingOrders(bar);
        trading.lastPrice = bar.c;
        released.push(bar);
      }
      this._maybePrefetchCanonicalShard(contract);

      if (take < available) {
        throw new Error("Timestamp-bounded replay release exceeded safety bound");
      }
      if (end < this.shard.length) break;

      const nextIndex = this.session.shardIndex + 1;
      if (nextIndex >= contract.shards.length) {
        if (this.session.barIndex >= this.shard.length - 1) this.session.state = "FINISHED";
        break;
      }
      const nextMeta = contract.shards[nextIndex];
      if (Number.isFinite(Number(nextMeta?.first_time)) && Number(nextMeta.first_time) >= targetExclusive) break;

      this.session.shardIndex = nextIndex;
      this.session.barIndex = -1;
      this.shard = null;
      this.shardKey = null;
    }

    return released;
  }

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
        await this._loadCanonicalShardForRelease(contract, this.session.shardIndex);
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
        this._maybePrefetchCanonicalShard(contract);
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
