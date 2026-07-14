# Ledger — Complete Core Product Visual Front-End

> For: Iris (build the full visual front-end)
> From: Thoth (research synthesis)
> Date: 2026-06-12
> Scope: EVERY planned surface in the core product. Not just a demo — the complete visual.

---

## Architecture — Two Surfaces

| Surface | User | Purpose |
|---------|------|---------|
| **Web app** | Owner / Manager / Partner | Full dashboard + persistent Ops Manager chat. Navigate normally OR ask. |
| **Browser extension** | Staff / Employees | Push notification feed. Ops Manager sends tasks, you act on them. |

Both surfaces ship in v1. The two-surface pattern is the differentiator — neither Digits nor Qount have it.

---

## Layout — Four-Zone

```
┌────────────────────────────────────────────────────────┐
│  ┌──┬──────────┬──────────────────────────────────┐   │
│  │  │ CHAT     │   MAIN WORKSPACE                 │   │
│  │N │ PANE     │                                  │   │
│  │A │ 320px    │   (fills remaining width)        │   │
│  │V │          │                                  │   │
│  │  │ Always   │   Changes based on sidebar nav   │   │
│  │  │ visible  │   OR Ops Manager query           │   │
│  │  │          │                                  │   │
│  │  │ Collaps- │   Default: Dashboard Home with   │   │
│  │  │ ible     │   vitals + widget grid           │   │
│  │  └──────────┴──────────────────────────────────┘   │
│  └──                                                   │
└────────────────────────────────────────────────────────┘
```

### Zone 1: Sidebar Nav (far left, ~64px icon strip)

Company wordmark at top (small, 24px, glass-style). Below it, vertical icon nav:

1. 💬 **Chat** — the Ops Manager (default active)
2. 📋 **Tasks** — Kanban + assignments
3. 👥 **Clients** — directory + scoped views
4. 📄 **Documents** — per-client document portal
5. ⏱ **Time** — time tracking + approvals
6. 💰 **Billing** — invoices, WIP, payments
7. 📊 **Reports** — saved + quick generate
8. 👤 **Staff** — org chart, capacity, utilization
9. 🔑 **Credentials** — client-gated access
10. 📅 **Calendar** — deadlines, busy season heatmap
11. 🧩 **Integrations** — connected apps, sync status
12. ⚙️ **Settings** — firm config, roles, billing

Bottom-pinned: Active client name + small avatar/initial badge. Global search (Cmd+K) accessible from anywhere.

### Zone 2: Chat Pane (left, ~320px persistent)

The Ops Manager conversation. Always visible. Collapsible via chevron.

**Header:** "Ops Manager" + status dot (green = online/working, yellow = processing, red = attention needed)

**Three message types:**
- **User message** — right-aligned, dark bubble (#1a1a1a), gold accent border
- **Ops response** — left-aligned, parchment bubble (#f5f0e8), oxblood name tag. Can contain rich content: mini-charts, status cards, action buttons, confirmations
- **System event** — centered, small, monochrome, timeline-style ("Smith tax review captured → filed. Deadlines flagged.")

**Input bar:** Glassy semi-transparent, pinned bottom, gold send button, paperclip attachment. You can upload PDFs, receipts, images — Ops Manager processes them.

**Suggested action chips** (up to 4): Context-aware, appear above the input. Change based on active client, open view, or recent conversation. "Send Jones letter", "Smith status", "Run payroll", "Flag for review".

**Chat scopes:** Default is the firm-wide conversation. @mention a client to switch to a scoped sub-thread. "Show me Smith's AR" → dashboard navigates + chat stays in Smith scope. "Back to firm" returns to global.

### Zone 3: Main Workspace (center + right, everything else)

Changes based on sidebar nav OR Ops Manager query. The chat can navigate this surface.

### Zone 4: Slide-over panels

Certain actions open a right-side slide-over (like Linear's issue panel). Documents, client details, task details, integration configs. Doesn't replace the main view — overlays it, dismissible via Escape.

---

## Complete Surface Types

### A. Dashboard Home (default view)

Vitals row top + widget grid below. Borrowed from Digits — tuned for practice management.

**Vitals row** (horizontal, 5 KPI cards with trend arrows):
- Active clients (count + MoM change)
- Outstanding AR (total + aging breakdown: <30 / 30-60 / 60-90 / 90+)
- Tasks pending (count, flagged items in red)
- Practice revenue (MTD vs target)
- Ops Manager flags (unread count)

**Widget grid** (2-column, drag-reorderable, per-user layout):
- Revenue by client (bar chart, MTD)
- Aging AR (heatmap by client, color-coded by days)
- Upcoming deadlines (timeline, next 14 days)
- Recent activity feed (Ops Manager actions in last 24h)
- Staff utilization (gauge per team member)
- Client sentiment / flags (if we have engagement data)
- Firm-wide completion rate (% of tasks done on time this month)

Ops Manager can suggest pins: "I notice you check Smith daily — want me to pin them to your dashboard?"

---

### B. Chat / Ops Manager (always present, covered in Zone 2 above)

---

### C. Tasks View

Three-column Kanban (like Qount's Workspace):

| Today | This Week | Backburner |
|-------|-----------|------------|
| Time-sensitive, Ops-surfaced | Deadlines ahead | Waiting on others |
| Red urgency bar for overdue | Yellow for approaching | Neutral |

**Each card:** Client name, task title, deadline, status bar (0-100%), assignee avatar. Click → slide-over with task detail: description, related docs, client history, Ops Manager context, activity log.

**Filters:** By client, by assignee, by engagement type, by priority. Search bar at top.

**Actions inline:** Assign, reprioritize, add note, mark complete. Ops Manager suggestion at bottom: "Want me to reprioritize based on tomorrow's deadlines?"

---

### D. Clients View

**List mode:** Searchable, filterable table. Columns: Client name, engagement type (Tax/Review/Audit/CAS), status dot (green/yellow/red), last activity, open tasks count, AR outstanding.

**Click → scoped client workspace:**
- Left rail: Client info (contacts, address, engagement type, since date, partner assigned)
- Center: Activity feed — all Ops Manager actions, chat messages, document uploads, task completions scoped to this client
- Right: Quick actions panel — "Send engagement letter", "Run status check", "Upload document", "View credentials", "Add note"
- Tab bar: Overview | Tasks | Documents | Billing | Communications

**Client health score** (if we build it): Composite of AR aging, response time, sentiment flags, deadline adherence. Visual gauge.

---

### E. Documents View

Per-client document portal. **Two views:**

**Grid view:** Document cards showing name, type icon, client, date, status (unsigned / signed / filed / pending).
**List view:** Compact table with same data.

**Status workflow:** Draft → Sent → Waiting → Signed → Filed. Visual pipeline per document.

**Actions:** Upload (drag-drop anywhere in UI), request signature, send to client portal, download, archive.

**Ops Manager integration:** Drop a PDF in the chat → "File this under Jones" → Ops Manager extracts, names, tags, and files it. Shows confirmation in chat.

---

### F. Time Tracking View

**Weekly timesheet grid:** Days as columns, clients/projects as rows. Enter hours directly.

**Start/stop timer:** Global timer in the nav bar. Click to start tracking against a client/task.

**Approvals:** Manager view — pending time entries, flag anomalies (over 8h on a task, weekend entries), approve/reject in bulk.

**Reports:** Utilization by staff, billable vs non-billable breakdown, realized vs written-off.

---

### G. Billing & Invoicing View

**WIP (Work in Progress):** All unbilled time and expenses by client. Running total. Flag items approaching write-off thresholds.

**Invoice generation:** Select WIP items → preview invoice → send. Supports subscriptions and recurring invoices.

**Payment tracking:** Invoice list with status (draft/sent/paid/overdue). Payment methods: ACH, credit card. Aging report.

**Subscription management:** Recurring billing for CAS/retainer clients. Create plans, auto-invoice, track MRR.

**Ops Manager loop:** "Run billing for Smith this month" → Ops Manager drafts invoices, presents for review, sends on approval.

---

### H. Reports View

**Saved reports:** Library of standard reports (P&L, Balance Sheet, Cash Flow, AR Aging, Utilization, Realization). Per-client and firm-wide.

**Quick generate:** Type in chat "Run the monthly Jones summary" → Ops Manager generates and pins it here.

**Drag-drop report builder:** Select metrics, dimensions, date range, chart type. Save as template.

**Export:** PDF, CSV, XLSX. Scheduled delivery (email reports automatically).

---

### I. Staff / Team View

**Org chart:** Visual hierarchy. Partner → Manager → Senior → Staff. Avatar, name, title.

**Capacity view:** Horizontal bar chart showing each person's week/month. Utilization percentage. Overbooked = red, at capacity = yellow, available = green.

**Workload distribution:** Open tasks per person. Who's overloaded, who has bandwidth. Ops Manager suggestions: "Alex is at 120% this week — want to reassign Smith's QBR prep to Jordan?"

**Time off:** PTO calendar overlay. Shows who's out and when.

---

### J. Credentials View

Client-gated access. See only what you're assigned.

**List:** Client name, service (bank, payroll, tax portal, insurance), username, last accessed, status.

**Actions:** One-click copy to clipboard (auto-clears after 30s). Launch portal URL directly.

**Audit log:** Who accessed what credential, when. Scrollable timeline at bottom of view.

---

### K. Calendar / Deadline View

**Firm-wide calendar:** All deadlines, filing dates, client meetings, internal reviews. Color-coded by engagement type.

**Busy season heatmap:** Daily task count across the firm. Spikes show crunch periods.

**Personal view:** Your deadlines, meetings, and Ops Manager reminders.

**Ops Manager proactive:** "Three deadlines tomorrow: Jones filing, Smith QBR, Wilson signature. Want me to prep the checklists?"

---

### L. Integrations View

**Connected services:** Each integration shown as a card — logo, name, sync status (green/yellow/red), last sync time.

**Supported integrations (steal from Qount's list):**
- QuickBooks Online
- Tax software (UltraTax, ProConnect, Drake)
- Bank feeds (Plaid)
- Email (Gmail, Outlook)
- Payment processing (Stripe, ACH)
- CRM (HubSpot, Salesforce)
- Payroll (Gusto, ADP)
- Document signing (DocuSign, PandaDoc)

**Add new:** Search available integrations, OAuth connect flow.

**API keys:** Generate/manage API tokens for custom integrations.

---

### M. Settings View

**Firm profile:** Firm name, logo, address, phone, website. White-label options (firm-branded client portal).

**User management:** Invite/remove users, assign roles (Partner, Manager, Senior, Staff, Admin). Role-based permissions matrix.

**Billing & plan:** Current plan, usage stats, invoice history, payment method.

**Notification preferences:** Which events trigger email/push/extension alerts.

**Security:** SSO (SAML/Google), 2FA enforcement, session timeout, IP whitelist.

**Data:** Export all firm data, retention policies, delete firm.

---

### N. Browser Extension (Employee Surface)

**THIS IS THE DIFFERENTIATOR.** Neither Digits nor Qount push work to employees like this.

**Popup layout (~360x500px):**

```
┌────────────────────────────────────┐
│  Ledger · Employee                 │
│  👤 You — Staff Accountant         │
├────────────────────────────────────┤
│                                    │
│  🔴 Jones engagement letter        │
│     Ops Manager · 2m ago          │
│     Needs your signature — due EOD │
│     [Review] [Dismiss]            │
│                                    │
│  ─────────────────────────────     │
│                                    │
│  📋 Smith QBR — slides v3          │
│     Ops Manager · 15m ago         │
│     Review before tomorrow's call  │
│     [View] [Dismiss]              │
│                                    │
│  ─────────────────────────────     │
│                                    │
│  ✅ Wilson tax filed               │
│     System · 1h ago               │
│     Filed successfully              │
│     [View receipt]                  │
│                                    │
│  ─────────────────────────────     │
│                                    │
│  ⚪ No more notifications          │
│                                    │
├────────────────────────────────────┤
│  🟢 7 tasks done this week         │
└────────────────────────────────────┘
```

**Three notification types:**
- **🔴 Task (needs action)** — signature, review, upload, approval. Red left border. "Due EOD" badge.
- **📋 Notification (info)** — "Filed", "Updated", "Completed". No action required.
- **⚠️ Flag (urgent)** — amber/orange left border. "Overdue", "Client waiting", "Partner flagged".

**Chrome badge:** Unread count on the extension icon in the browser toolbar.

**Employee does NOT navigate.** There is no dashboard, no search, no nav bar. Just receive → act → done.

**Two-way sync:** When an employee acts, the owner's chat sees:
> ✅ Wilson signed the engagement letter (via Employee Portal)

---

## The Ops Manager Query Loop (core interaction)

This is the magic that sells the product. It works across ALL surfaces:

1. **User types in chat:** "Show me Smith's AR aging"
2. **Ops Manager responds in chat:** "Pulling up Smith Engineering AR..."
3. **Dashboard navigates automatically** — opens the Reports surface, filters to Smith, shows the aging chart
4. **Chat message updates:** "✅ Done. $12,400 outstanding, 3 items over 60 days. Want me to flag them?"
5. **User:** "Do it."
6. **Ops Manager:** "Flagged. I've also pushed a reminder to Alex to follow up."

The user can ALSO just click sidebar nav. Chat is an alternative input, not the only one. Both paths converge on the same surfaces.

---

## The Complete Loop (owner → Ops → employee → done)

1. Owner asks Ops Manager → Dashboard updates
2. Ops Manager pushes subtasks to employees → Extension lights up
3. Employee receives, acts → Extension badge decrements
4. Ops Manager reports completion back to owner's chat
5. Owner never left their flow

---

## Visual Language

| Element | Style |
|---------|-------|
| Background | Warm light #f7f5f0. Clean dark #1a1b1e as optional mode. |
| Chat pane | Light parchment #f5f0e8 background |
| Sidebar icons | Clean line icons, muted default, oxblood hover, gold active |
| Primary accent | Oxblood #8b1a2b |
| CTAs / send button | Gold #c9a84c |
| Chat bubbles (Ops) | Parchment bg, oxblood name tag, hard offset shadow |
| Chat bubbles (User) | Dark #1a1a1a, gold accent border, right-aligned |
| System events | Centered, small, monochrome, timeline style |
| Success state | Muted green #2d6a4f |
| Warning state | Amber #d4a373 |
| Danger state | Red #c1121f |
| Typography (sidebar) | System sans-serif |
| Typography (chat) | Editorial serif for Ops messages, weight 400 |
| Typography (data) | Tabular figures for numbers, monospace optional |
| Nav terms | Standard business English. No forge imagery. |

Not forge-themed. This is professional accounting practice management software. Think Linear's cleanliness meets a CPA firm lobby.

---

## Deliverable for Iris

Single HTML file with embedded CSS/JS. Full interactive front-end showing ALL the above surfaces. Clickable nav between all views. Chat pane responds with dashboard navigation. Extension popup shown as a modal/overlay or separate panel.

Style as specified above. Light mode default. Interactive enough to click through the entire product surface area and see the Ops Manager loop in action.
