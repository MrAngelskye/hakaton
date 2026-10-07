-- Synthetic examples only. Run after importing exports/postgresql.sql.
SET search_path TO naryadai_ai_training;

-- 1. Unplanned orders per conveyor compared with the other conveyors.
WITH failures AS (
  SELECT e.id, e.name, COUNT(o.id) FILTER (WHERE o.kind = 'unplanned') AS failures
  FROM equipment e LEFT JOIN work_orders o ON o.equipment_id = e.id
  WHERE e.category = 'Конвейер' GROUP BY e.id, e.name
)
SELECT id, name, failures,
       ROUND(((SUM(failures) OVER () - failures)::numeric /
              NULLIF(COUNT(*) OVER () - 1, 0)), 2) AS peer_mean
FROM failures ORDER BY failures DESC, id;

-- 2. Simulated rework frequency: labels were generated, not rated by a real master.
SELECT p.username, p.name, COUNT(*) AS orders,
       COUNT(*) FILTER (WHERE a.verdict = 'rework_required') AS rework,
       ROUND(100.0 * COUNT(*) FILTER (WHERE a.verdict = 'rework_required') /
             COUNT(*), 2) AS simulated_rework_percent
FROM work_orders o JOIN people p ON p.id = o.assignee_id
JOIN answer_keys a ON a.work_order_id = o.id
GROUP BY p.id, p.username, p.name ORDER BY simulated_rework_percent DESC, p.username;

-- 3. Same-equipment, same-code recurrence within 14 days after a previous report.
WITH previous AS (
  SELECT o.id, o.number, o.equipment_id, o.fault_code, o.issued_at,
         MAX(p.reported_at) AS previous_reported_at
  FROM work_orders o JOIN work_orders p
    ON p.equipment_id = o.equipment_id AND p.fault_code = o.fault_code
   AND p.issued_at < o.issued_at AND p.reported_at < o.issued_at
   AND p.kind = 'unplanned' AND o.kind = 'unplanned'
  GROUP BY o.id, o.number, o.equipment_id, o.fault_code, o.issued_at
)
SELECT * FROM previous
WHERE issued_at - previous_reported_at <= INTERVAL '14 days'
ORDER BY equipment_id, issued_at;

-- 4. Observational shift comparison; this does not establish a cause of downtime.
SELECT s.shift_code, COUNT(*) AS intervals,
       ROUND(AVG(d.duration_minutes)::numeric, 2) AS mean_minutes,
       COUNT(*) FILTER (WHERE d.duration_minutes > 150) AS over_150_minutes
FROM downtime_intervals d JOIN work_orders o ON o.id = d.work_order_id
JOIN shifts s ON s.id = o.shift_id GROUP BY s.shift_code ORDER BY s.shift_code;
