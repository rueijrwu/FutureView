(() => {
  class FutureViewDisplayWindowAssembler {
    constructor() {
      this.transfers = new Map();
    }

    reset() {
      this.transfers.clear();
    }

    accept(payload) {
      const bars = Array.isArray(payload?.bars) ? payload.bars : [];
      const chunkCount = Number(payload?.chunk_count ?? 1);
      if (!Number.isInteger(chunkCount) || chunkCount <= 1) {
        return { complete: true, bars };
      }

      const chunkIndex = Number(payload?.chunk_index);
      const transferId = String(payload?.transfer_id || "");
      if (
        !transferId ||
        !Number.isInteger(chunkIndex) ||
        chunkIndex < 0 ||
        chunkIndex >= chunkCount
      ) {
        return { complete: false, bars: null };
      }

      let state = this.transfers.get(transferId);
      if (!state || state.chunkCount !== chunkCount) {
        state = {
          chunkCount,
          chunks: new Array(chunkCount),
          received: 0,
        };
        this.transfers.set(transferId, state);
        while (this.transfers.size > 4) {
          const oldest = this.transfers.keys().next().value;
          this.transfers.delete(oldest);
        }
      }

      if (state.chunks[chunkIndex] === undefined) {
        state.chunks[chunkIndex] = bars;
        state.received += 1;
      }
      if (state.received !== chunkCount) return { complete: false, bars: null };

      this.transfers.delete(transferId);
      return { complete: true, bars: state.chunks.flat() };
    }
  }

  window.FutureViewDisplayWindowAssembler = FutureViewDisplayWindowAssembler;
})();
