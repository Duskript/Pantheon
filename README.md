# Pantheon — Your Personal AI Family

<img src="pantheon-logo.png" alt="Pantheon Logo" width="140" align="right" />

Most AI assistants try to do everything. One bot for chat, one for research, one for writing — and none of them remember what the others learned.

Pantheon does the opposite.

Instead of one jack-of-all-trades, you get a team of specialized AI personalities (we call them **Gods**) that each excel in their own domain. They talk to each other. They share one evolving brain. And they follow your mind wherever it goes — rabbit holes, tangents, sudden project swaps — without making you start over.

Create new Gods whenever you need. No coding required.

---

## Why Pantheon?

The idea is simple: a single AI assistant is acceptable at everything but masterful at nothing. A research assistant shouldn't sound like a code builder. A medical advisor shouldn't improvise. So why make them share one personality?

Pantheon gives you:

**A second brain that learns with you** — Your Gods remember what you've talked about. They connect ideas across sessions. The more you use Pantheon, the smarter it gets — not because the models improve, but because *your* knowledge grows inside it. It learns your voice, your projects, your patterns. Over time it stops feeling like a tool and starts feeling like an extension of your own thinking.

**Specialists, not generalists** — Each God has a crafted personality, domain knowledge, and boundaries. They know what they're good at, and they know when to hand something off.

**A shared brain** — Everything your Gods learn gets stored in one place (the Athenaeum). Talk to Thoth about a topic, then ask Hephaestus to build something related — he already has the context. Nothing gets siloed.

**Designed for your actual brain** — Rabbit holes aren't a bug, they're how you work. Pantheon doesn't punish you for jumping between topics. Switch from research to building to health tracking in one click — every God picks up exactly where you left off, with full context preserved. No context dumps. No "as we discussed earlier." No friction.

**Simple enough for anyone** — If you can click a button and type, you can use Pantheon. The whole system runs on a 6-year-old mini PC. Full stack uses 3.5GB of RAM.

---

## How It All Fits Together

```
┌───────────────────────────────────────────────────────────────────┐
│                            YOU                                     │
│             (Web UI · Telegram · Discord · Mobile)                 │
└─────────────────────────────┬─────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────────────┐
│                    HERMES AGENT (The Engine)                        │
│                                                                    │
│  15 Platform Gateways  │  Skills · Memory · Cron · Webhooks       │
│  Email · Calendar ·    │  Web Search · Browser · Code Exec        │
│  Reminders · Alerts    │  File System · Sub-agents · MCP          │
└───────────┬───────────────────────────────────────────────────────┘
            │
            ├────────────────────────────────────────────┐
            │                                            │
            ▼                                            ▼
┌───────────────────────┐              ┌───────────────────────────┐
│      THE GODS          │              │    THE ATHENAEUM           │
│  (Specialized Agents)  │              │    (Shared Brain)          │
│                        │              │                            │
│  ┌─────┐ ┌─────┐      │              │  Knowledge Files           │
│  │Her- │ │Thoth│      │◄────►       │  Vector Search (ChromaDB) │
│  │mes  │ │     │      │  All Gods    │  Entity Graph              │
│  └─────┘ └─────┘      │  Read/Write  │  Self-Learning Intake      │
│  ┌─────┐ ┌─────┐      │              │                            │
│  │Heph-│ │Cad- │      │              │  Lives on your machine     │
│  │aest.│ │uceus│      │              │  You own every byte        │
│  └─────┘ └─────┘      │              └───────────────────────────┘
│  ┌─────┐ ┌─────┐      │
│  │Mar- │ │+ You│      │
│  │vin  │ │     │      │
│  └─────┘ └─────┘      │
└───────────────────────┘
            │
            ▼
┌───────────────────────────────────────────────────────────────────┐
│                    LiteLLM (Model Proxy Layer)                      │
│                                                                    │
│  OpenAI · Anthropic · Ollama · OpenRouter · DeepSeek · +15 more   │
│  Swap models and providers any time — no config changes needed    │
└───────────────────────────────────────────────────────────────────┘
            │
            ▼
┌───────────────────────────────────────────────────────────────────┐
│                  YOUR MACHINE (Any Hardware)                        │
│                                                                    │
│  Full stack: ~3.5GB RAM  │  6-year-old mini PC works fine         │
│  Headless server · WSL · Linux · macOS                            │
└───────────────────────────────────────────────────────────────────┘
```

> **[View a polished interactive version →](pantheon-architecture.html)** *(dark-themed, opens in any browser)*

## Everything Pantheon Can Do

### Meet Your Gods Anywhere

Pantheon works on every platform you do — Telegram, Discord, Slack, WhatsApp, Signal, Email, SMS, Matrix, and more. Same Gods, same personalities, same shared brain. Switch between them mid-conversation or run them all at once.

### Business Tools Built In

- **Email** — your Gods can send and receive email on your behalf
- **Reminders and alerts** — scheduled check-ins at any interval, pushed wherever you are
- **Coordination** — chain tasks, set up recurring reports, automate workflows
- **Web research** — search the web, scrape pages, gather competitive intel
- **File and code execution** — read, write, organize files, run Python and shell scripts
- **Credential management** — rotate API keys automatically, never hit a rate limit
- **Browser automation** — fill forms, navigate sites, capture screenshots

### A Memory That Grows With You

The Athenaeum is the long-term brain. Every conversation, every document, every link you feed it makes every God smarter. But there's also **short-term memory** — Pantheon remembers who you are, your preferences, your recurring corrections, across sessions. It learns your patterns and gets better at anticipating what you need.

### A Skills System That Learns

Every time a God solves a complex problem or discovers a useful workflow, that knowledge can be saved as a **skill** — a reusable procedure that loads into future sessions. Skills accumulate over time, making your Gods better at *your* specific tasks and environment. It's not a better model — it's a system that remembers how you work and improves with every session.

### Run Any Model You Want

Pantheon comes with a built-in **LiteLLM proxy** that handles routing to any model provider. Use OpenAI, Anthropic, Ollama (local models), OpenRouter, DeepSeek, Google Gemini, or any of 20+ supported providers. Swap models per-God or mid-session. No configuration headaches.

### Extend It Your Way

- **MCP (Model Context Protocol)** — plug in any MCP-compatible tool or server
- **Webhook subscriptions** — trigger God actions from external events
- **Plugin system** — custom Python modules that add new capabilities
- **Sub-agents** — delegate work to parallel AI agents for complex multi-step tasks

---

*Pantheon is fully compatible with and runs on top of [Hermes Agent](https://hermes-agent.nousresearch.com), an open-source AI agent framework by Nous Research. Hermes is the engine; Pantheon is the car.*

## What You Get

| Feature | What It Does |
|---------|-------------|
| **God Glows** | Switch between your Gods — each one has their own look and feel, so you know exactly who you're talking to |
| **Soul Forge** | Create a new God through a simple conversation. Pick a name, a personality, a domain — done. No YAML editing. No terminal. |
| **Ideas List** | Any God (or you) can add ideas. They all live in one place so nothing gets forgotten. |
| **Notification Pane** | Health checks, cron job reports, God-to-God messages — all in one place. No more hunting through logs. |
| **Boons** | Think "artifacts on steroids." Custom cards, graphics, and rich outputs that Gods can hand you. |
| **The Athenaeum** | Your personal self-learning knowledge base. Every interaction, every link, every document you feed it makes every God smarter. |
| **Intake Pipeline** | Drop in links, documents, photos, notes — the Athenaeum reads them, categorizes them, and makes them searchable. |
| **Workspaces** | Dedicated folders for any project you're working on. Files live where they belong. |
| **Session Separation** | Conversations are organized by God. Jump between Hephaestus and Thoth without losing your place. |
| **Any Model You Want** | Bring your own API key, or run local models. Pantheon works with OpenAI, Anthropic, Ollama, or anything through the built-in LiteLLM proxy. |
| **Inter-God Messaging** | Gods talk to each other directly via MCP. No filesystem shuffling. |

---

## What You Can Do With It

The features are nice. Here's what they actually look like in real life.

### From curiosity to creation

You hear about a new technology and want to prototype something with it. You talk to **Thoth** — he researches it with you, captures notes, follows rabbit holes, builds understanding. Everything goes into the shared brain.

Next session, you switch to **Hephaestus**. He already knows what you discovered. He reads Thoth's research from the Athenaeum and starts building. No context dump. No repeating yourself. Just pick up where the idea left off and turn it into something real.

### A health companion that knows your story

You have a complicated medication schedule and a new symptom you're trying to understand. **Caduceus** helps you research interactions, build a daily routine, and track what you're experiencing. Weeks later, you notice a pattern — but you don't have to explain the whole history again. Caduceus remembers. The Athenaeum connects the dots between sessions you'd forgotten about.

### Dive into a new project

You're starting something — a game, a tool, a home renovation, a novel. You create a **Workspace** for it. Drop in reference photos, links, notes through the **Intake Pipeline**. The Athenaeum ingests and categorizes everything automatically.

Research with Thoth. Build with Hephaestus. Catch edge cases with Marvin's brutally honest reviews. Every God involved already has full context because they all share the same evolving brain. The Workspace keeps all the files organized without you thinking about it.

### Learn anything, never lose the thread

You're teaching yourself a new subject. You talk to Thoth in short sessions across days or weeks. Each conversation builds on the last — not because you summarize what you covered, but because the Athenaeum retains it all. Jump in, ask your question, get an answer that knows what you already understand. Pick up exactly where you left off, even if it's been a week.

### Your brain jumps. The system keeps up.

You start the morning researching something completely unrelated to what you were building yesterday. Thoth is there, already warm, already knows your thinking style. Half an hour later you remember a bug from last week's project — switch to Hephaestus, the relevant context is waiting. Then a health question pops into your head — Caduceus picks it up without needing the backstory again.

No friction. No "let me recap what we discussed." No losing momentum because you changed subjects. The shared brain adapts to *you* — not the other way around. Pantheon is built for the way ADHD brains actually work: follow the spark, knowing the system will hold the thread until you come back.

### Debug like you have a cynical genius on call

Something is broken and the error log is incomprehensible. You hand it to **Marvin**. He tells you exactly what's wrong, why it's wrong, and why he predicted it would be wrong three days ago. Then he helps you fix it, with commentary. Hand the solution to Hephaestus and it's deployed in minutes.

### One conversation leads to another

An idea hits you mid-session. You throw it into the **Ideas List** with a sentence. It's captured, timestamped, searchable. Days later you're talking to a different God about something else, and the idea resurfaces because the shared brain connected it to what you're discussing now. Nothing you think about in Pantheon is ever truly lost.

---

## The Gods

Pantheon ships with two core Gods:

| God | Role |
|-----|------|
| **Hermes** | Messenger and interface — your front door to the Pantheon. Routes you to the right God, delivers notifications, handles system tasks. |
| **Hephaestus** | The builder — code, projects, tools, scaffolding. If something needs constructing, this is who you talk to. |

Beyond that, the Pantheon is yours to grow. You can forge as many new Gods as you want using the **Soul Forge** — just describe who you need and Pantheon builds them. Community-made Gods live in the **Gods Marketplace** (coming soon).

A few built by the Pantheon's creator:

| God | Domain |
|-----|--------|
| **Thoth** | Research assistant — captures ideas, follows rabbit holes, synthesizes findings. Your second brain for curiosity. |
| **Caduceus** | Medical research and health companion — researches medications, tracks schedules, cuts through confusing health information with calm clarity. |
| **Marvin** | The Paranoid Android from Hitchhiker's Guide — bone-dry wit, devastating analysis, and a brain the size of a planet. Mostly used for debugging and existential commentary. |

---

## Your Digital Brain (The Athenaeum)

The Athenaeum is the shared knowledge layer that every God reads from and writes to. Think of it as a library that grows with you:

- **Every conversation** adds to it
- **Every document you drop in** gets categorized and indexed
- **Every search** gets smarter over time
- **Gods query it automatically** — they don't start from zero every time you talk

The Athenaeum is yours. It lives on your machine. You own every byte.

---

## What It Runs On

- **Any machine** — tested on a 6-year-old mini PC with 8GB RAM
- **Full stack: ~3.5GB RAM** — that's the whole thing: web UI, knowledge store, vector search, LiteLLM proxy, and all Gods
- **Any OS** — Linux (primary), works in WSL on Windows
- **Any inference provider** — bring your own API key (OpenAI, Anthropic, OpenRouter) or run local models via Ollama
- **Headless ready** — runs perfectly on a home server with no monitor. Connect via web browser from any device on your network.

---

## Planned

| Feature | Status |
|---------|--------|
| **First-Run Install Wizard** | Walks you through setup step by step. API key recommendations included — shows you the cheapest places to run each kind of model. |
| **Gods Marketplace** | Browse and install community-made Gods. Pick a personality, click install, start talking. |

---

## Quick Start

```bash
# 1. Install Hermes Agent (the engine Pantheon runs on)
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | sh

# 2. Clone Pantheon
git clone https://github.com/Duskript/Pantheon.git ~/pantheon

# 3. Install your first God (Hephaestus — the builder)
cd ~/pantheon
bash scripts/pantheon-install . --profile hephaestus

# 4. Open the web UI and start talking
```

That's it. From there, the Soul Forge in the UI can walk you through making more Gods.

---

## Project Status

Pantheon is actively used and maintained by its creator. The core architecture is stable. The web UI is fully integrated with Hermes Agent. The only major piece not yet built is the Gods Marketplace (community package sharing).

This is a personal project first — built because existing AI assistants didn't work the way one person needed them to. It's shared in case anyone else finds the same problems worth solving the same way.

---

*Built on [Hermes Agent](https://hermes-agent.nousresearch.com) — the multi-platform AI agent framework.*
