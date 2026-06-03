# harnesses/ — DEPRECATED

This directory's YAML harness definitions are no longer maintained.

The active Hephaestus identity lives at `~/.hermes/profiles/hephaestus/SOUL.md`
after install. Non-core god harnesses (Apollo, Caduceus, Thoth) live in each
god's profile directory on the system, not in the public repo.

For new god creation, see `docs/HOW_TO_CREATE_A_GOD.md` (TODO: write this doc).

## History

The `harnesses/` directory saw oscillation between "delete" / "gitignore" / "untrack"
in commits `8b655c8`, `20ad3c6`, `ee3ca6d`, `f5b36ed`, `f3a0597`. The YAMLs
were never load-bearing: the only `load_harness` callers are the loader
itself (`pantheon-core/harness/loader.py`, since pruned) and planning docs
that mention them in prose. Runtime never touched `harnesses/`.
