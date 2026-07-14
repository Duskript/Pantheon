# Pantheon — The Stack

> Source: Constitution Section 2
> Read this document when: making decisions about hardware, software dependencies, or infrastructure. Do not assume any component not listed here exists. Do not introduce new dependencies without explicit instruction.

---

## Hardware

### Primary Workstation — Active
- OS: CachyOS (Arch-based), KDE Plasma
- GPU: NVIDIA RTX 3060 12GB VRAM
- Role: Primary user interaction, all Phase 1 Pantheon services, Claude Code and CLI build sessions
- Note: All Phase 1 gods run here until homelab is operational

### Homelab Server — Planned, Not Yet Built
- CPU: AMD Ryzen 7 (Zen 1)
- RAM: Maxed DDR4
- GPU: AMD Radeon 12GB
- Hypervisor: Proxmox (planned)
- Role (future): Always-on services, Ollama inference, Athenaeum hosting, vector DB, background god processes
- Note: Pantheon itself will assist in planning and building this server once Phase 1 is operational on the workstation

### Network
- Tailscale running across all nodes
- All Pantheon services accessible via Tailscale without port exposure

---

## Core Software

### Inference
- Ollama — primary local inference engine
- Primary model: Gemma 4 (subject to change per god/studio assignment)
- Embedding model: nomic-embed-text via Ollama
- Cloud models supported via Prometheus when local inference is insufficient

### Frontend
- Forked Open WebUI — primary user-facing interface
- Rebuilt as Sanctuary-based workspace system
- Accessible via Tailscale on all user devices

### Knowledge Store
- The Athenaeum — filesystem of markdown files organized into Codices
- Obsidian — optional human interaction layer for the Athenaeum, not a dependency

### Vector Database
- Chroma (Phase 1) — local semantic search and embedding store
- Qdrant (Phase 2+ migration target) — higher performance at scale

### Version Control
- Git — all Pantheon code and harness files under version control
- GitHub — remote under Duskript developer identity

### Networking
- Tailscale — secure mesh access across all devices
- Proxmox — VM and container management on homelab server (planned)
- Syncthing — Phase 4, syncs ~/Pantheon/ and harnesses/ from workstation to Proxmox

### Backup Targets by Phase

| Phase | Target | Method |
|---|---|---|
| Phase 1 | Workstation only | Btrfs/Snapper snapshots (implicit — no off-machine backup) |
| Phase 4 | Proxmox homelab | Syncthing sync, Proxmox handles backup from there |
| Phase 5 | Cloud (optional) | rclone — OneDrive/Google Drive; encryption future work |

### Containerization
- Docker Compose + Portainer — service management on homelab
- Background gods run as containerized services where applicable

### Scripts

- `scripts/init-athenaeum.sh` — builds Athenaeum and Staging folder structure from scaffold
- `scripts/migrate-oracle-vault.sh` — migrates existing ORACLE vault content into Athenaeum
- `scripts/reset-auth.sh` — CLI credential reset tool, requires host machine access, bypasses UI entirely
- `scripts/migrate-harness.sh` — upgrades a single harness file from schema version N to N+1, run deliberately never automatically
