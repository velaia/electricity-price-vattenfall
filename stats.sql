-- Database statistics for energy_prices.db
-- Usage: sqlite3 energy_prices.db < stats.sql

.headers on
.mode column

.print
.print === Coverage ===
SELECT
    COUNT(*)               AS days_stored,
    MIN(date)              AS first_date,
    MAX(date)              AS last_date,
    CAST(julianday(MAX(date)) - julianday(MIN(date)) + 1 AS INT) AS span_days,
    CAST(julianday(MAX(date)) - julianday(MIN(date)) + 1 AS INT) - COUNT(*) AS missing_days,
    MAX(fetched_at)        AS last_fetch
FROM price_days;

.print
.print === Missing dates in range ===
WITH RECURSIVE range(d) AS (
    SELECT MIN(date) FROM price_days
    UNION ALL
    SELECT date(d, '+1 day') FROM range
    WHERE d < (SELECT MAX(date) FROM price_days)
)
SELECT d AS missing_date
FROM range
WHERE d NOT IN (SELECT date FROM price_days);

.print
.print === Intervals ===
SELECT
    COUNT(*)                            AS total_intervals,
    ROUND(AVG(c), 2)                    AS avg_intervals_per_day,
    MIN(c)                              AS min_intervals_per_day,
    MAX(c)                              AS max_intervals_per_day
FROM (
    SELECT day_id, COUNT(*) AS c
    FROM price_intervals
    GROUP BY day_id
);

.print
.print === Days with incomplete intervals (not 96) ===
SELECT
    d.date,
    COUNT(i.id) AS interval_count
FROM price_days d
LEFT JOIN price_intervals i ON i.day_id = d.id
GROUP BY d.id
HAVING interval_count <> 96
ORDER BY d.date;

.print
.print === Price summary (ct/kWh, netto) ===
SELECT
    ROUND(MIN(price_netto), 3) AS min_price,
    ROUND(MAX(price_netto), 3) AS max_price,
    ROUND(AVG(price_netto), 3) AS avg_price,
    COUNT(CASE WHEN price_netto < 0 THEN 1 END) AS negative_intervals
FROM price_intervals;

.print
.print === Cheapest 5 intervals ===
SELECT
    d.date,
    i.interval_index,
    printf('%02d:%02d', i.interval_index / 4, (i.interval_index % 4) * 15) AS time,
    ROUND(i.price_netto, 3) AS price
FROM price_intervals i
JOIN price_days d ON d.id = i.day_id
ORDER BY i.price_netto ASC
LIMIT 5;

.print
.print === Most expensive 5 intervals ===
SELECT
    d.date,
    i.interval_index,
    printf('%02d:%02d', i.interval_index / 4, (i.interval_index % 4) * 15) AS time,
    ROUND(i.price_netto, 3) AS price
FROM price_intervals i
JOIN price_days d ON d.id = i.day_id
ORDER BY i.price_netto DESC
LIMIT 5;

.print
.print === Per-day min / max / avg ===
SELECT
    d.date,
    ROUND(MIN(i.price_netto), 3) AS min,
    ROUND(MAX(i.price_netto), 3) AS max,
    ROUND(AVG(i.price_netto), 3) AS avg
FROM price_days d
JOIN price_intervals i ON i.day_id = d.id
GROUP BY d.id
ORDER BY d.date;
