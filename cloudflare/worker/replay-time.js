export const DISPLAY_TIME_ZONE = "America/New_York";
export const FRAME_RESOLUTIONS = new Set(["1", "5", "30", "240", "1D"]);

const SESSION_ROLL_HOUR_ET = 18;
const ET_FORMATTER = new Intl.DateTimeFormat("en-US", {
  timeZone: DISPLAY_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

export function etParts(seconds) {
  return Object.fromEntries(
    ET_FORMATTER.formatToParts(new Date(Number(seconds) * 1000))
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, Number(part.value)]),
  );
}

export function wallToEpochSeconds(parts) {
  const wanted = Date.UTC(
    Number(parts.year),
    Number(parts.month) - 1,
    Number(parts.day),
    Number(parts.hour ?? 0),
    Number(parts.minute ?? 0),
    Number(parts.second ?? 0),
  );
  let guess = wanted;
  for (let i = 0; i < 4; i += 1) {
    const shown = etParts(guess / 1000);
    const shownWall = Date.UTC(
      shown.year,
      shown.month - 1,
      shown.day,
      shown.hour,
      shown.minute,
      shown.second || 0,
    );
    const delta = wanted - shownWall;
    guess += delta;
    if (!delta) break;
  }
  return Math.floor(guess / 1000);
}

export function sessionStart(seconds) {
  const parts = etParts(seconds);
  const day = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  if (parts.hour < SESSION_ROLL_HOUR_ET) day.setUTCDate(day.getUTCDate() - 1);
  return wallToEpochSeconds({
    year: day.getUTCFullYear(),
    month: day.getUTCMonth() + 1,
    day: day.getUTCDate(),
    hour: SESSION_ROLL_HOUR_ET,
    minute: 0,
    second: 0,
  });
}

export function tradingDayDate(seconds) {
  const parts = etParts(seconds);
  const day = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
  if (parts.hour >= SESSION_ROLL_HOUR_ET) day.setUTCDate(day.getUTCDate() + 1);
  return day;
}

export function tradingDayKey(seconds) {
  const day = tradingDayDate(seconds);
  return day.getUTCFullYear() * 10000 + (day.getUTCMonth() + 1) * 100 + day.getUTCDate();
}

export function dailyTradingStamp(seconds) {
  const day = tradingDayDate(seconds);
  return wallToEpochSeconds({
    year: day.getUTCFullYear(),
    month: day.getUTCMonth() + 1,
    day: day.getUTCDate(),
    hour: 0,
    minute: 0,
    second: 0,
  });
}

export function dailyBarTradingDayKey(seconds) {
  // Cache compatibility: both legacy 00:00 UTC and corrected 00:00 ET daily
  // timestamps keep the intended trading-day calendar date in UTC Y/M/D.
  const day = new Date(Number(seconds) * 1000);
  return day.getUTCFullYear() * 10000 + (day.getUTCMonth() + 1) * 100 + day.getUTCDate();
}

export function displayStamp(seconds, resolution) {
  const value = String(resolution);
  if (value === "1") return Number(seconds);
  if (value === "1D") return dailyTradingStamp(seconds);
  const minutes = Number(value);
  if (!Number.isFinite(minutes) || minutes <= 0) throw new Error(`Unsupported display resolution ${resolution}`);
  const start = sessionStart(seconds);
  const width = minutes * 60;
  return start + Math.floor(Math.max(0, Number(seconds) - start) / width) * width;
}

export function frameKey(seconds, resolution) {
  const value = String(resolution);
  if (value === "1D") return `D:${tradingDayKey(seconds)}`;
  return `${value}:${displayStamp(seconds, value)}`;
}
