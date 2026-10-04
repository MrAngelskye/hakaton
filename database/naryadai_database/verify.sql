-- Read-only examples. Time boundaries are inclusive start / exclusive end.
SET search_path TO naryadai,public;
SELECT 'sites' AS entity,count(*) FROM sites
UNION ALL SELECT 'equipment',count(*) FROM equipment
UNION ALL SELECT 'masters',count(*) FROM users WHERE role='master'
UNION ALL SELECT 'workers',count(*) FROM users WHERE role='worker'
UNION ALL SELECT 'brigades',count(*) FROM brigades
UNION ALL SELECT 'defect_codes',count(*) FROM defect_codes
UNION ALL SELECT 'materials',count(*) FROM materials
UNION ALL SELECT 'tasks',count(*) FROM tasks
UNION ALL SELECT 'reports',count(*) FROM reports;

-- Frequent breakdowns: expected leader is DEMO-0001 / conveyor K-01.
SELECT * FROM equipment_failures ORDER BY unplanned_repairs DESC LIMIT 5;

-- Recurring defects: pump N-07 / hydraulic oil leak G-01.
SELECT t.equipment,d.code,count(*) AS occurrences
FROM reports r JOIN tasks t ON t.id=r.task_id JOIN defect_codes d ON d.id=r.defect_code_id
WHERE r.status='approved'
GROUP BY t.equipment,d.code ORDER BY occurrences DESC LIMIT 5;

-- Late reports: worker15 is the deliberately planted outlier.
SELECT username,closed_tasks,on_time_tasks,
  round(100.0*(closed_tasks-on_time_tasks)/NULLIF(closed_tasks,0),1) AS late_percent
FROM employee_metrics ORDER BY late_percent DESC;

-- Grease consumption: conveyor K-01 has 3 kg per approved report versus 0.25 kg elsewhere.
SELECT t.equipment,round(avg(rm.quantity),2) AS average_quantity
FROM report_materials rm JOIN reports r ON r.id=rm.report_id JOIN tasks t ON t.id=r.task_id
JOIN materials m ON m.id=rm.material_id
WHERE r.status='approved' AND m.code='MAT-016'
GROUP BY t.equipment ORDER BY average_quantity DESC;

-- Shift / period totals. Only approved report versions contribute to consumed materials.
SELECT t.day,count(*) AS issued,
  count(*) FILTER (WHERE t.status='approved') AS closed,
  count(*) FILTER (WHERE t.status NOT IN ('approved','cancelled') AND t.deadline<now()) AS overdue
FROM tasks t GROUP BY t.day ORDER BY t.day DESC;
SELECT * FROM material_usage ORDER BY cost DESC;

-- These integrity counts must be zero.
SELECT count(*) AS unknown_equipment FROM tasks WHERE equipment_id IS NULL;
SELECT count(*) AS wrong_report_worker FROM reports r JOIN tasks t ON t.id=r.task_id WHERE r.worker_id<>t.worker_id;
SELECT count(*) AS orphan_report_photo FROM task_photos p JOIN reports r ON r.id=p.report_id WHERE p.task_id<>r.task_id;
SELECT count(*) AS overlapping_schedules FROM tasks a JOIN tasks b
  ON a.worker_id=b.worker_id AND a.day=b.day AND a.id<b.id
WHERE a.status<>'cancelled' AND b.status<>'cancelled'
  AND a.start<b.start+b.duration AND b.start<a.start+a.duration;
