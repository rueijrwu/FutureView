import { displayStamp } from "./replay-time.js";

export function newDisplayAggregate(bar, resolution) {
  return {
    t: displayStamp(bar.t, resolution),
    o: Number(bar.o),
    h: Number(bar.h),
    l: Number(bar.l),
    c: Number(bar.c),
    v: Number(bar.v) || 0,
  };
}

export function addToDisplayAggregate(aggregate, bar) {
  aggregate.h = Math.max(aggregate.h, Number(bar.h));
  aggregate.l = Math.min(aggregate.l, Number(bar.l));
  aggregate.c = Number(bar.c);
  aggregate.v += Number(bar.v) || 0;
  return aggregate;
}

export function asDisplayBar(aggregate, resolution) {
  return aggregate ? { ...aggregate, display_resolution: String(resolution) } : null;
}

export function consumeDisplayBars(state, rawBars, resolution) {
  const value = String(resolution || "1");
  if (value === "1") {
    return {
      state: { ...state, cursor: rawBars?.at(-1)?.t ?? state?.cursor ?? null },
      completed: (rawBars || []).map((bar) => ({ ...bar, display_resolution: "1" })),
    };
  }

  const nextState = {
    aggregate: state?.aggregate ? { ...state.aggregate } : null,
    resolution: state?.resolution ?? null,
    publishedStamp: state?.publishedStamp ?? null,
    cursor: state?.cursor ?? null,
  };
  const completed = [];

  for (const bar of rawBars || []) {
    const stamp = displayStamp(bar.t, value);
    if (!nextState.aggregate || nextState.resolution !== value) {
      nextState.aggregate = newDisplayAggregate(bar, value);
      nextState.resolution = value;
      nextState.publishedStamp = null;
    } else if (nextState.aggregate.t !== stamp) {
      if (nextState.publishedStamp !== nextState.aggregate.t) {
        completed.push(asDisplayBar(nextState.aggregate, value));
        nextState.publishedStamp = nextState.aggregate.t;
      }
      nextState.aggregate = newDisplayAggregate(bar, value);
      nextState.publishedStamp = null;
    } else {
      addToDisplayAggregate(nextState.aggregate, bar);
    }
    nextState.cursor = Number(bar.t);
  }

  return { state: nextState, completed };
}

export function finalizeDisplayBar(state, nextCanonicalBar, resolution) {
  const value = String(resolution || "1");
  if (value === "1" || !state?.aggregate) return { state, completed: [] };
  const complete = !nextCanonicalBar || displayStamp(nextCanonicalBar.t, value) !== state.aggregate.t;
  if (!complete || state.publishedStamp === state.aggregate.t) return { state, completed: [] };
  return {
    state: { ...state, publishedStamp: state.aggregate.t },
    completed: [asDisplayBar(state.aggregate, value)],
  };
}
