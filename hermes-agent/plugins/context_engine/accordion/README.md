# Accordion Context Engine

Phase C of the unified-upgrade plan.

## Behavior

- Keeps the most recent working tail of the conversation in full fidelity.
- Folds older turns into Ichor `episodic_folds` records.
- Stores a per-session fold index under `~/.hermes/accordion/fold-index/`.
- Provides reversible expansion through `accordion_expand`.

## Defaults

| Setting | Default |
|---|---:|
| `working_tail` | `7` turns |
| `threshold_percent` | `0.75` |
| `context_length` | `200000` tokens |

## Selection

Set in `config.yaml`:

```yaml
context:
  engine: accordion
```
