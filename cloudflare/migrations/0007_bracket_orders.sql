-- A bracket attaches a take-profit and/or a stop-loss to an entry order. The two
-- exit legs are one-cancels-other: a fill on either cancels its sibling. Both
-- fields live on trade_orders as extra, nullable columns rather than a separate
-- table, since a bracket is just an order with attachments, not a new entity.
ALTER TABLE trade_orders ADD COLUMN take_profit_price REAL;
ALTER TABLE trade_orders ADD COLUMN stop_loss_price REAL;
-- oco_group links the two exit legs of one bracket (and, transitively, the
-- entry order whose id it equals). bracket_role distinguishes which leg a
-- working order is once it has been attached.
ALTER TABLE trade_orders ADD COLUMN oco_group TEXT;
ALTER TABLE trade_orders ADD COLUMN bracket_role TEXT CHECK(bracket_role IN ('take_profit','stop_loss'));

CREATE INDEX IF NOT EXISTS idx_trade_orders_oco_group
  ON trade_orders(oco_group);
