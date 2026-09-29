-- Create minimal schema for ichor_events table required by skill crystallization analysis
-- This defines the columns used in the crystallization engine
-- Schema file for the crystallization script to run against

-- Columns used in skill crystallization analysis
-- id, subject, raw_text, god_name, event_type, importance, created_at

-- Insert example data to populate the table
INSERT INTO ichor_events VALUES (1, 'Test Insight', 'This is a test insight for skill crystallization.', 'Theoforge', 'insight', 75.0, '2026-09-18T14:00:00Z');
INSERT INTO ichor_events VALUES (2, 'Commitment', 'I need to commit to a task by 2026-10-01', 'default', 'commitment', 85.0, '2026-09-18T14:01:00Z');
INSERT INTO ichor_events VALUES (3, 'Decision', 'I made a decision on task outcome', 'default', 'decision', 60.0, '2026-09-18T14:02:00Z');
INSERT INTO ichor_events VALUES (4, 'Follow Up', 'This requires follow up action', 'default', 'follow_up', 50.0, '2026-09-18T14:03:00Z');
