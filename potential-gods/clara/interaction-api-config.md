# Drug Interaction API Configuration

## Data Sources

### Prototype (Free) — OpenFDA
```
Endpoint: https://api.fda.gov/drug/label.json
Method: GET
Query: ?search=openfda.brand_name:"{drug}"&limit=1
Rate limit: 1000 req/min (generous)
SLA: None
BAA: Not available
Data: Unstructured label text — parse interactions section
```

How to use:
1. Search for drug by brand/generic name via OpenFDA
2. Extract the `drug_interactions` field from the label
3. For a patient on multiple drugs, search each drug and compare interaction sections
4. Cache pairs to avoid re-querying

Limitations:
- Unstructured text — you have to parse severity yourself
- No dedicated interaction endpoint (the old RxNav one was discontinued Jan 2024)
- No SLA or uptime guarantee
- Not suitable for production clinical use without a BAA-capable fallback

### Production (Recommended) — DrugsAPI
```
Endpoint: https://api.drugsapi.com/v1/interactions/check
Method: POST
Body: { "drugs": ["Eliquis", "Ozempic"] }
Auth: API key
Pricing: ~$99/month (Starter), scales from there
BAA: Available (HIPAA compliant)
Data: Structured — severity scores (contraindicated, serious, monitor, minor), source attribution
```

### Enterprise (Gold Standard) — DrugBank
```
Pricing: $10k+/year negotiated
BAA: Available
Data: Most comprehensive — pharmacokinetic, pharmacodynamic, severity, mechanism
```

## Caching Strategy

To minimize API calls and ensure Clara is fast:

```
Hash: MD5(sorted([drugA, drugB]))
Cache location: Codex-PriorAuth/interactions/known-pairs.md

On every check:
  1. Compute pair hashes for all active medications
  2. If hash exists in cache → use cached result
  3. If not → query API → store result with timestamp
  4. Expire cache entries older than 90 days
```

## Disclaimer (MUST be included with every result)

> "This interaction check is informational only. It is not a substitute for professional medical judgment. Always verify potential drug interactions with a licensed pharmacist or physician. Clara does not provide clinical recommendations."
