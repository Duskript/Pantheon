---
name: conductor-design-report
description: "Use when the user says 'set up a report', 'create a digest', 'I want a daily/weekly summary of', 'monitor X and report on Y', or any request for scheduled information synthesis. Produces a Conductor workflow + rules for scheduled reports and digests."
version: 1.0.0
author: Thoth & Hermes (Pantheon)
license: MIT
metadata:
  hermes:
    tags: [conductor, report, digest, schedule, cron, monitoring]
    related_skills: [conductor-design-rule, conductor-design-workflow]
---

# Conductor Report & Digest Designer

## When to Use

Load this skill when the user wants a recurring summary of information. Keywords: "report," "digest," "daily briefing," "weekly summary," "monitor X," "keep an eye on."

## Process

### Step 1: Define the Report

Ask:
- **What information should be included?** (gods' activity, external monitoring, system health, project status)
- **What's the cadence?** (daily, weekly, monthly, on-demand)
- **Who should compile it?** (Thoth for research digests, Hermes for project status, Marvin for code activity)
- **Where should it go?** (Telegram, shared/pending/, Athenaeum report)
- **How should it be triggered?** (cron schedule, explicit command, event-driven)

### Step 2: Design as a Workflow

Scheduled reports are just Conductor workflows triggered by a cron rule.

```yaml
# workflows/daily-morning-briefing.yaml
workflow:
  id: daily-morning-briefing
  name: "Daily Morning Briefing"
  version: "1.0.0"
  description: "Compile and deliver a daily summary of Pantheon activity"

  triggers:
    - type: schedule
      expression: "0 7 * * 1-5"   # Weekdays at 7 AM

  steps:
    - id: gather
      god: thoth
      skill: dawn-patrol
      action: compile_digest
      timeout: 15m

    - id: format
      god: hermes
      skill: summarize
      input_from: gather
      timeout: 5m

    - id: deliver
      type: notify
      method: telegram
      input_from: format
```

### Step 3: Configure the Cron Rule

```yaml
# rules/daily-briefing.yaml
rules:
  - id: daily-morning-briefing
    when:
      event_type: schedule.cron
      expression: "0 7 * * 1-5"
    then:
      handling_mode: notify_and_log
      action: dispatch_workflow
      workflow: daily-morning-briefing
```

### Step 4: Validate

- [ ] Cron expression is valid
- [ ] All steps reference existing gods and skills
- [ ] Timeout values are reasonable for each step
- [ ] Delivery method is configured (Telegram, file, shared/)
- [ ] Report doesn't duplicate an existing one

### Step 5: Write

Two files:
1. Workflow → `~/pantheon/conductor/workflows/{report-id}.yaml`
2. Cron rule → `~/pantheon/conductor/rules/{report-id}-schedule.yaml`

### Step 6: Confirm

- Report name, cadence, and contents
- Which gods are involved
- How and when it will be delivered
- How to trigger it on-demand ("run briefing now")
