-- Chart annotations (trend lines, rectangles, fib retracements, etc.) belong to
-- the same save slot as the replay cursor and trading record. The column is an
-- opaque JSON array: the worker never interprets it, only the frontend does
-- (site/chart-tools.js serializeDrawings()/loadDrawings()).
ALTER TABLE saved_sessions ADD COLUMN drawings TEXT;
