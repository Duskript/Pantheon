# Fusion Brief for Iris — Business Newsletter Landing Page

Generated: 2026-08-09T17:47:49Z
Owner: Hermes planner/reviewer
Target god: Iris

## Objective

Design/build the first-pass landing page concept for Konan's business-centric newsletter pipeline.

The page should sell a practical newsletter/resource hub around business automation, AI agents, workflow tools, and what actually produces money — not generic AI hype.

## Core offer

Working positioning:

> A weekly field report on AI agents, business automation, workflow tools, and revenue experiments that are useful to operators — not vibes, not hype.

Primary CTA:

> Join the field report

Secondary CTA/resource hook:

> Browse the Best GitHub Tools for Business Automation

## Required page sections

1. Hero
   - Clear promise in one sentence.
   - Email signup CTA.
   - Resource hook: curated GitHub tools/repo as immediate value.

2. Who it is for
   - Small-business operators.
   - Automation consultants/builders.
   - Founders trying to convert AI/workflow knowledge into revenue.
   - People who want tested tools, not AI-news dopamine.

3. What readers get
   - Best GitHub tools worth knowing.
   - Practical workflow breakdowns.
   - AI-agent/MCP/n8n/automation stack notes.
   - Revenue experiment lessons.
   - Operator checklists/templates.

4. Resource attachment
   - Design a visible block for a companion curated repo/resource named something like:
     - `Best GitHub Tools for Business Automation`
     - `Operator Tools Index`
     - `The Automation Field Kit`
   - Treat it as a lead magnet attached to the landing page.
   - It can start as a GitHub repo/README or static resource page later.

5. Trust/proof
   - Tie lightly to Pantheon/TheoForge/operator-building experience.
   - Avoid overclaiming revenue.
   - Validation rule: money/replies/booked calls/source material/subscribers beat vanity metrics.

6. Footer
   - Simple, low-friction.
   - Optional links: TheoForge, resource repo, contact/reply path.

## Visual direction

- Business/operator focused, not neon AI casino.
- Clean, credible, slightly technical.
- Dark or light is Iris's call, but prioritize legibility and conversion.
- Should feel like: Linear/Vercel clarity + field-notes practicality.

## Constraints

- Do not publicly mention Android phone automation workers.
- Keep consignment/flipping out of this public newsletter surface.
- No health content.
- Do not position n8n as the final strategic workflow engine; mention n8n only as a practical tool/resource if needed. TheoForge/Pantheon direction remains broader than n8n.
- No fake testimonials, revenue claims, or audience-size claims.
- No deployment yet unless Konan explicitly approves.

## Candidate implementation targets

Known Iris deploy context from Athenaeum:

- Current TheoForge root landing page: `theoforgesolutions.com/`, Node monolith on relay-7, backend `127.0.0.1:4321`, owned by Iris.
- Static pages commonly deploy under `/var/www/theoforge/<page>/` on relay-7.
- A newsletter page could be a static route, e.g. `/newsletter`, before touching root.

## Requested Iris output

Produce one of these, in order of preference:

1. A static HTML landing page mockup artifact with CSS included, plus a short design rationale.
2. If code is not appropriate yet, a detailed landing page wireframe + visual direction + copy skeleton.

## Done means

- Iris replies in Discord with artifact path(s) or design file path(s).
- The page includes the newsletter CTA and the GitHub tools/resource hook.
- The output explicitly respects the constraints above.
- No deployment performed unless approved.

## Executor return shape

STATUS: complete | partial | blocked | escalate
CHANGES:
ARTIFACTS:
VERIFIED:
GAPS:
NEXT MOVE:
