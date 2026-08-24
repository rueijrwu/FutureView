function meanLast(values, size) {
  if (values.length < size) throw new Error(`rolling window requires ${size} values`);
  let sum = 0;
  for (let i = values.length - size; i < values.length; i += 1) sum += Number(values[i]);
  return sum / size;
}

function appendTrim(values, value, size) {
  const out = [...values, Number(value)];
  return out.slice(Math.max(0, out.length - size));
}

export function trueRange(high, low, previousClose) {
  return Math.max(
    Number(high) - Number(low),
    Math.abs(Number(high) - Number(previousClose)),
    Math.abs(Number(low) - Number(previousClose)),
  );
}

export function updateSymbolState(state, bar, tradingDate) {
  if (tradingDate <= state.as_of) {
    throw new Error(`${state.symbol}: update date is not newer than state`);
  }
  if (state.closes.length < 200 || state.highs.length < 50 || state.volumes.length < 20) {
    throw new Error(`${state.symbol}: incremental state is not fully bootstrapped`);
  }

  const previousClose = Number(state.closes.at(-1));
  const tr = trueRange(Number(bar.high), Number(bar.low), previousClose);
  const closes = appendTrim(state.closes, bar.close, 200);
  const highs = appendTrim(state.highs, bar.high, 50);
  const volumes = appendTrim(state.volumes, bar.volume, 20);
  const trueRanges = appendTrim(state.true_ranges, tr, 14);

  const sma5 = meanLast(closes, 5);
  const sma10 = meanLast(closes, 10);
  const sma20 = meanLast(closes, 20);
  const sma50 = meanLast(closes, 50);
  const sma200 = meanLast(closes, 200);
  const avgVolume20 = meanLast(volumes, 20);
  const atr14 = meanLast(trueRanges, 14);
  const sma50History = appendTrim(state.sma50_history, sma50, 11);
  const sma50Prior10 = sma50History.length === 11 ? Number(sma50History[0]) : null;

  const priorHigh20 = Math.max(...state.highs.slice(-20).map(Number));
  const priorHigh50 = Math.max(...state.highs.slice(-50).map(Number));
  const return20 = Number(bar.close) / Number(state.closes.at(-20)) - 1;
  const return60 = Number(bar.close) / Number(state.closes.at(-60)) - 1;

  const feature = {
    symbol: state.symbol,
    date: tradingDate,
    open: Number(bar.open),
    high: Number(bar.high),
    low: Number(bar.low),
    close: Number(bar.close),
    volume: Number(bar.volume),
    sma5,
    sma10,
    sma20,
    sma50,
    sma200,
    avg_volume20: avgVolume20,
    return20,
    return60,
    high20_prior: priorHigh20,
    high50_prior: priorHigh50,
    true_range: tr,
    atr14,
    avg_dollar_volume20: Number(bar.close) * avgVolume20,
    volume_ratio20: avgVolume20 ? Number(bar.volume) / avgVolume20 : null,
    sma50_slope10: sma50Prior10 ? sma50 / sma50Prior10 - 1 : null,
    extension_atr: atr14 ? (Number(bar.close) - sma20) / atr14 : null,
    breakout20: Number(bar.close) >= priorHigh20,
    breakout50: Number(bar.close) >= priorHigh50,
    distance_from_high20: Number(bar.close) / priorHigh20 - 1,
  };

  const nextState = {
    symbol: state.symbol,
    as_of: tradingDate,
    closes,
    highs,
    volumes,
    true_ranges: trueRanges,
    sma50_history: sma50History,
  };
  return { nextState, feature };
}
