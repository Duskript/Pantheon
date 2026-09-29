# Pantheon Self-Hosted Security White Paper

**Review date:** 2026-08-26  
**Assessment target:** Pantheon operated exclusively on infrastructure controlled by the operator, with model inference performed locally.  
**Assessment type:** Architecture and configuration review; not a penetration test, formal certification, or legal opinion.

## Executive decision

**Current Pantheon configuration: NOT APPROVED for an exclusively self-hosted security boundary.**

The repository contains useful security primitives—path traversal protection, response security headers, credential redaction, profile scoping, PBKDF2 password hashing, constant-time token checks, and approval-oriented webhook envelopes—but several production defaults and active configuration paths defeat the self-hosted claim:

1. The active Hermes configuration selects `openai-codex` by default and contains multiple cloud or remote inference endpoints.
2. The Conductor systemd unit points at `nats.theoforgesolutions.com:4222`, which is outside the host.
3. The WebUI systemd unit binds to `0.0.0.0:8787` while WebUI password authentication is optional; if no password is configured, requests are allowed.
4. Conductor authentication is disabled when `CONDUCTOR_API_KEY` is absent, while the webhook listener defaults to `0.0.0.0:8088`.
5. The sample Vaultwarden deployment has a fallback admin token of `changeme-pantheon-admin` and leaves signups enabled.
6. The self-hosted model named by the request—“Quinn 3.8 37B”—could not be matched to an authoritative public model card during this review. Hardware sizing below therefore uses a **37-billion-parameter model class**, not a claimed exact model. A vendor/model URL is required before a final procurement decision.

**Recommended disposition:** treat the current deployment as a development or trusted-tailnet configuration. Before calling it self-hosted production, enforce local-only inference, fail-closed authentication, network segmentation, immutable/pinned artifacts, service hardening, and an acceptance test that proves no prompt or telemetry leaves the approved network.

## 1. Scope and assumptions

### In scope

- Pantheon WebUI, MCP server, Conductor v2, NATS, Vaultwarden, Hermes Agent configuration, systemd/Docker deployment surfaces, model-serving boundary, secrets, logs, files, webhooks, and agent-tool execution.
- Confidentiality, integrity, availability, provenance, and data-exfiltration risks for prompts, session history, credentials, workspace files, Athenaeum data, and workflow events.
- A deployment where all model inference is served by an operator-controlled local process such as Ollama, llama.cpp, or vLLM.

### Out of scope

- Full source-code penetration test, dependency CVE scan, kernel/hypervisor review, physical security, GPU firmware review, or an attestation that every transitive dependency is safe.
- A final model-specific performance guarantee. The exact model identity, quantization, context length, and serving runtime materially change requirements.

### Security objective

The self-hosted boundary must guarantee:

- no inference request, response, system prompt, tool result, or telemetry is sent to a third-party model provider;
- only authenticated and authorized principals can reach control-plane APIs;
- the model server cannot directly reach sensitive files or management APIs unless explicitly required;
- agent tool execution is least-privilege and auditable;
- failures are fail-closed rather than silently reverting to a cloud or unauthenticated mode.

## 2. Model identity and sizing basis

### Identity finding

No authoritative public model card for “Quinn 3.8 37B” was located in this review. The official Qwen sources reviewed document Qwen3 variants, including **Qwen3-30B-A3B**, not a 37B “Qwen 3.8” release:

- Qwen official release announcement: <https://qwenlm.github.io/blog/qwen3/>
- Official model card: <https://huggingface.co/Qwen/Qwen3-30B-A3B>
- Official model configuration: <https://huggingface.co/Qwen/Qwen3-30B-A3B/raw/main/config.json>

The Qwen3-30B-A3B configuration identifies a sparse MoE architecture with 128 experts and 8 experts per token, a 40,960 maximum position embedding, and BF16 weights. That is useful as a comparison point, but it must **not** be treated as proof that the requested model is Qwen3 or that its runtime requirements are identical.

**Required before deployment:** record the exact model repository or artifact digest, architecture, total parameters, active parameters if MoE, native context length, quantization format, license, tokenizer, supported runtime, and SHA-256/SLSA provenance.

### Weight-memory estimates for a 37B model

The figures below are engineering estimates derived from parameter count × bytes per parameter, with 20% reserved for runtime overhead. They exclude potentially large KV cache, batching, CUDA graphs, framework fragmentation, adapters, and OS/application memory.

| Weight format | Raw weights | Planning budget with 20% overhead | Practical target |
|---|---:|---:|---|
| BF16/FP16 | ~74 GB / ~68.9 GiB | ~88.8 GB / ~82.7 GiB | 96 GB total VRAM minimum; 128 GB preferred, often multi-GPU |
| INT8 | ~37 GB / ~34.5 GiB | ~44.4 GB / ~41.4 GiB | 48 GB VRAM minimum; 64 GB preferred |
| 4-bit | ~18.5 GB / ~17.2 GiB | ~22.2 GB / ~20.7 GiB | 24 GB VRAM minimum for short context; 32 GB preferred |
| 3-bit | ~13.9 GB / ~12.9 GiB | ~16.7 GB / ~15.5 GiB | 20–24 GB VRAM, with quality/runtime tradeoffs |

**Important:** quantization reduces weight memory, not the need for KV cache. Long context and concurrency can consume several additional GB. A 24 GB card is therefore a constrained single-user 4-bit target, not a general production recommendation.

For vLLM, the official documentation reviewed specifies Linux, Python 3.10–3.13, and NVIDIA compute capability 7.5 or newer for the CUDA path; it also documents AMD ROCm, Intel XPU, and Apple Silicon paths. See <https://docs.vllm.ai/en/latest/getting_started/installation/gpu.html>. vLLM exposes an OpenAI-compatible serving API, documented at <https://docs.vllm.ai/en/latest/serving/online_serving/>. llama.cpp is a viable lower-cost alternative for GGUF quantized artifacts and multiple backends: <https://github.com/ggml-org/llama.cpp>.

## 3. System requirements

### Recommended production profile: single-node, 4-bit, moderate concurrency

This is the sensible starting point if the exact model is a conventional 37B model and the target is one to a few simultaneous agent turns:

- **GPU:** 1 × 32 GB VRAM NVIDIA GPU preferred; 24 GB is the hard floor for short-context 4-bit inference. For vLLM, use a CUDA-capable GPU meeting the documented compute requirement. AMD/Intel/Apple choices require runtime-specific validation.
- **System RAM:** 64 GB minimum; 128 GB preferred for model conversion, filesystem cache, embedding services, WebUI, Conductor, browser automation, and safe headroom.
- **CPU:** 8 modern physical cores recommended; 4 cores is a development floor, not a performance target.
- **Storage:** 1 TB NVMe minimum; 2 TB preferred. Reserve at least 2× the model artifact size for download, conversion, checksum verification, rollback, logs, and temporary files.
- **Network:** 1 GbE minimum for a single node; no inbound exposure from the public Internet. Use loopback or a private VLAN for model/control-plane traffic.
- **OS:** Linux. Keep the model host and control plane patched; use a supported NVIDIA/ROCm stack if applicable.
- **Power/cooling:** size for sustained GPU load, not desktop burst usage; use UPS-backed storage for state and clean shutdown.

### Higher-quality profile: 8-bit or longer context

- **GPU:** 48–64 GB total VRAM, possibly split across GPUs with high-bandwidth interconnect or tested tensor parallelism.
- **System RAM:** 128 GB.
- **Storage:** 2 TB NVMe.
- **Use case:** longer context, higher concurrency, lower quantization loss, or larger prompt/tool payloads.

### BF16/FP16 profile

- **GPU:** approximately 96 GB usable VRAM at minimum; 128 GB total is the safer target. This generally means a datacenter GPU or multiple GPUs.
- **System RAM:** 128–256 GB.
- **Storage:** 2 TB NVMe.
- **Use case:** quality-sensitive serving and larger context/concurrency; not appropriate for the current host.

### CPU-only fallback

A 37B model can be made to run on CPU with a sufficiently quantized artifact and substantial RAM, but this is not a good Pantheon production target. Plan for **64 GB RAM minimum for 4-bit experimentation and 128 GB preferred**, with materially lower latency and throughput. Keep CPU-only inference isolated from interactive control-plane workloads.

### Current host comparison

The inspected host reports:

- Intel Core i5-7200U, 4 logical CPUs;
- approximately 11.6 GB total RAM and approximately 5.1 GB available at inspection time;
- Intel integrated graphics only in the inspected DRM inventory;
- no `nvidia-smi` executable detected.

**Conclusion:** this host does not meet the practical requirements for a 37B model. It cannot hold even a conservative 4-bit model plus runtime and Pantheon services in memory. Use it as a control-plane node only, or move the model server to a dedicated GPU host on the private network.

## 4. Reference target architecture

```text
                    private LAN / tailnet ACL

  Operator ──HTTPS──> Reverse proxy ──mTLS/auth──> WebUI (loopback/private)
                                      │
                                      ├──> Hermes Agent / tool broker
                                      ├──> Conductor API + webhook gateway
                                      └──> MCP server (loopback only)

  WebUI/Conductor ──authenticated local HTTP──> Model server
                                             (Ollama / llama.cpp / vLLM)

  Conductor ──localhost/private VLAN──> NATS (auth + TLS, no public bind)
  Vaultwarden ──localhost/private VLAN──> encrypted persistent data
```

The model server should be a separate trust zone from the agent tool runner. It should receive only the prompt payload needed for inference and have no filesystem access to `~/.hermes`, Vaultwarden data, Git credentials, browser profiles, or arbitrary workspaces. The model endpoint should be reachable only from the agent service account or private application network.

## 5. Current controls observed

These controls reduce risk and should be retained:

- **MCP loopback default:** `pantheon-core/mcp_server.py` defaults HTTP mode to `127.0.0.1:8010`, reducing accidental LAN exposure when launched without overrides.
- **Path containment:** WebUI `safe_resolve()` resolves a requested path and requires it to remain under the configured root.
- **Response hardening:** WebUI responses set `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, a Content-Security-Policy, Referrer-Policy, Permissions-Policy, and `Cache-Control: no-store`.
- **Credential redaction:** API response redaction covers common API-key prefixes, authorization headers, environment assignments, private-key blocks, and recursively nested session/tool data. This is a response-layer control, not a substitute for preventing secrets from entering logs or storage.
- **WebUI password implementation:** when configured, the WebUI uses a persisted 32-byte signing key, PBKDF2-HMAC-SHA256 with 600,000 iterations, constant-time comparisons, signed sessions, 30-day session expiry, and a five-attempt-per-minute in-process login limiter.
- **Conductor token comparison:** the Conductor auth helper supports bearer/query-key extraction and constant-time token comparison.
- **Profile scoping:** session/project APIs include profile matching and an explicit opt-in aggregate mode.
- **Webhook quarantine intent:** webhook events are marked external and documented as `approval_required` by default; this is a useful integrity boundary if the engine enforces it consistently.
- **Atomic session/key persistence:** WebUI session and signing-key writes use restrictive `0600` modes and atomic replacement patterns.
- **Per-user services:** the inspected Conductor and WebUI systemd units run as `User=konan`, avoiding root by default.

## 6. Findings and gaps

Severity reflects the self-hosted production target, not merely whether the code works on a trusted laptop.

### CRITICAL — Cloud/remote inference remains configured

**Evidence:** `~/.hermes/config.yaml` selects `gpt-5.6-luna` via `openai-codex` and lists OpenCode, OpenRouter, Groq, Mistral, Nous, Pollinations, a tailnet Ollama endpoint, and other remote endpoints. Auxiliary services also point at non-local providers. This violates the no-third-party-inference requirement and creates a failover/data-residency risk.

**Required fix:** replace the provider allowlist with one local provider and one local model identifier; remove cloud providers from active configuration rather than merely changing the default; disable remote auxiliary providers; remove or reject any fallback route not matching an approved local CIDR/Unix socket. Add an egress test that submits a canary prompt and verifies no connection leaves the approved interface set.

### CRITICAL — Conductor depends on an external NATS hostname

**Evidence:** `conductor/conductor.service` sets `NATS_URL=nats://nats.theoforgesolutions.com:4222`.

**Risk:** workflow events, handoffs, metadata, and potentially payloads cross the self-hosted boundary; availability depends on an external service.

**Required fix:** run NATS locally or on an operator-owned private node, bind it to loopback/private VLAN, enable NATS authentication and TLS where traffic crosses hosts, pin the server identity, and fail startup if the URL is not in the approved local endpoint list.

### CRITICAL — Unauthenticated control-plane modes are available

**Evidence:** `conductor/v2/auth.py` explicitly treats an empty API key as “auth disabled,” and `webhook.py` defaults to `0.0.0.0:8088`. `webui/api/auth.py` treats missing password configuration as authentication disabled.

**Risk:** a network-adjacent attacker may submit dispatches/webhooks, read workflow state, or operate the WebUI. “Trusted tailnet” is not an authentication control.

**Required fix:** production mode must refuse to start without strong credentials. Separate health endpoints from control endpoints; require bearer/mTLS auth for API, webhook HMAC signatures per source, replay protection, body-size/rate limits, and explicit authorization by route and principal.

### HIGH — WebUI systemd service is LAN-wide and does not configure a password

**Evidence:** `pantheon-webui.service` sets `HERMES_WEBUI_HOST=0.0.0.0` and `HERMES_WEBUI_PORT=8787`, while the password is only enabled through `HERMES_WEBUI_PASSWORD` or settings.

**Required fix:** bind loopback and front it with an authenticated TLS reverse proxy, or set a secret through a protected `EnvironmentFile` and add firewall rules limiting the port to the approved private network. Add `Secure`, `HttpOnly`, and `SameSite=Strict` cookie attributes and CSRF protection for state-changing browser requests.

### HIGH — Docker examples publish sensitive services broadly

**Evidence:** `scripts/docker-compose.yml` publishes Ollama as `11434:11434` and Pantheon Core as `8001:8000`. The Ollama endpoint is not an authenticated public service by default.

**Required fix:** publish neither service to all interfaces. Use a private Docker network, loopback-only port bindings when host access is required, explicit auth at a local proxy, and network policy denying model-server access to the Internet and sensitive host mounts.

### HIGH — Vaultwarden defaults are unsafe for production

**Evidence:** `vaultwarden/docker-compose.yml` uses `VAULTWARDEN_ADMIN_TOKEN:-changeme-pantheon-admin` and `SIGNUPS_ALLOWED=true`.

**Required fix:** require a non-empty secret from a root-readable `EnvironmentFile` or secret manager; refuse the default; disable signups after bootstrap; pin the Vaultwarden image by digest; back up encrypted data; restrict `/admin`; configure HTTPS and secure headers.

### HIGH — Mutable and unverified supply chain

**Evidence:** the Vaultwarden compose file uses `vaultwarden/server:latest`; the requested model artifact has not been identified or digest-pinned; the Pantheon compose references `pantheon-core/Dockerfile`, but that file was absent at the inspected path.

**Required fix:** pin container images by digest, verify model and tokenizer hashes, generate an SBOM, scan Python/Node/system dependencies, review licenses, and make deployment fail when required build artifacts are missing or unexpected.

### HIGH — Service units lack defense-in-depth hardening

**Evidence:** inspected systemd units do not set `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=strict`, `ProtectHome=read-only`, `RestrictAddressFamilies=`, capability bounding, resource limits, or an explicit protected `EnvironmentFile`.

**Required fix:** add systemd sandboxing appropriate to each service, a dedicated service account per trust zone, read-only code mounts, narrowly writable state directories, CPU/memory/task limits, and explicit network-family restrictions. Validate each unit with a smoke test because over-hardening can break legitimate tool paths.

### MEDIUM — Webhook ingestion is not cryptographically authenticated in the route code

**Evidence:** webhook routes accept arbitrary JSON/raw bodies and queue them. The module description says external events default to approval, but the route itself does not show source-specific signature verification, timestamp validation, or replay protection.

**Required fix:** implement per-source HMAC/signature verification before writing to the inbox, enforce maximum body size before reading the full body, reject unknown sources, include event IDs/timestamps, and deduplicate/reject replays.

### MEDIUM — WebUI redaction is configurable and response-layer only

**Evidence:** `redact_session_data()` reads an `api_redact_enabled` setting; redaction does not modify underlying session files. It can also miss novel secret formats.

**Required fix:** keep redaction always-on for external responses in production, prevent secret-bearing fields from being persisted where possible, add structured secret detectors/tests, and treat logs, crash dumps, browser storage, and backups as separate data stores.

### MEDIUM — Operational observability is not yet a security evidence chain

**Evidence:** services write to journal and jobs write to local log files, but the reviewed deployment files do not establish immutable retention, alerting, clock synchronization, or an audit trail for model/provider changes and privileged tool actions.

**Required fix:** centralize append-only audit events locally, record actor/route/decision/tool/model/digest/outcome, protect logs from the service account, configure retention and alerting, and verify time synchronization.

### LOW — MCP graceful probe response advertises permissive CORS

**Evidence:** the bare GET `/mcp` response sets `access-control-allow-origin: *`.

**Required fix:** remove the wildcard or constrain it to the exact local UI origin. Keep MCP loopback-only unless a separately authenticated gateway is present.

## 7. Self-hosted threat model

| Threat actor/event | Asset at risk | Attack path | Required control |
|---|---|---|---|
| Internet scanner or tailnet peer | WebUI, Conductor, workflows | Broad bind, missing auth | Loopback/private ACL, mandatory auth, TLS/mTLS, rate limits |
| Malicious webhook sender | Workflow integrity | Unsigned `/webhook/*` or `/dispatch` | Per-source signatures, replay protection, approval quarantine |
| Prompt injection in web/file content | Credentials, tools, external accounts | Model-induced tool calls | Capability allowlists, HITL for high-impact actions, egress policy, taint-aware review |
| Compromised model artifact | Agent and host | Trojanized weights/tokenizer/runtime | Signed provenance, digest pinning, sandboxed model host, offline import scanning |
| Cloud/provider misconfiguration | Confidential prompts and session data | Default/fallback/auxiliary provider | Local-only allowlist, DNS/egress deny, canary exfiltration test |
| Compromised plugin/dependency | Host filesystem and secrets | Python/Node package or MCP server | Lockfiles, SBOM, vulnerability scanning, least privilege, service sandbox |
| Local unprivileged user | Sessions, keys, Vaultwarden data | Readable files/process env/logs | `0600`, dedicated accounts, protected env files, encrypted disk, audit |
| Resource exhaustion | Model and control-plane availability | Long context, large webhook/body, concurrency | Body/context/token limits, queue quotas, cgroups, watchdogs |
| Backup theft/ransomware | Durable memories and secrets | Unencrypted state/backups | Encrypted backups, offline copy, restore tests, retention policy |
| Operator error | Entire trust boundary | Dangerous defaults and drift | Fail-closed startup checks, config lint, signed deployment manifest |

The dominant AI-specific risk is not that the local model can magically escape its process; it is that model output is connected to tools with authority. A local model removes provider-side exposure but does not remove prompt injection, unsafe tool invocation, malicious documents, data poisoning, or compromised model files. Follow the control themes in the OWASP LLM Top 10 (<https://owasp.org/www-project-top-10-for-large-language-model-applications/>) and manage AI-specific risk alongside conventional system security using the NIST AI RMF (<https://www.nist.gov/itl/ai-risk-management-framework>).

## 8. Required security gates before production

### Gate A — Model and egress proof

- Exact model URL, license, architecture, quantization, and artifact digests recorded.
- Local model server starts with the approved artifact only.
- Hermes config contains no cloud providers, remote inference URLs, or cloud auxiliary routes.
- DNS, firewall, and egress tests prove inference traffic stays on loopback/private addresses.
- Packet capture or connection audit during a canary prompt shows no unauthorized destination.

### Gate B — Authentication and authorization

- WebUI production startup fails without configured auth.
- Conductor API, webhook, and live stream all require the intended credential mechanism.
- Webhook signatures, replay checks, body limits, and rate limits pass tests.
- Cookies are secure and CSRF tests pass.
- Health endpoints disclose no filesystem paths, queue locations, or sensitive topology.

### Gate C — Isolation and least privilege

- Model server cannot read Hermes state, credentials, browser profiles, or arbitrary workspaces.
- MCP remains loopback-only or sits behind a separately authenticated gateway.
- Each systemd/container service has a dedicated account and tested sandbox policy.
- Tool capabilities are explicitly allowlisted; destructive/external actions require approval.

### Gate D — Supply chain and recovery

- Images and model artifacts are digest-pinned and hash-verified.
- SBOM and vulnerability scan are stored with the release.
- Backups are encrypted and a restore test succeeds.
- Logs are protected, retained, and auditable.
- A rollback to the prior model/runtime is documented and tested.

### Gate E — Performance and availability

- Benchmark with the actual context length, tool payloads, concurrency, and quantization.
- Verify VRAM headroom, RAM pressure, swap behavior, thermal stability, and restart recovery.
- Enforce request/token/time quotas so an agent or webhook cannot starve the model server or control plane.

## 9. Prioritized remediation plan

### P0 — Before any claim of self-hosting

1. Identify the exact model and pin its digest.
2. Replace all active and auxiliary remote model routes with one approved local endpoint.
3. Move NATS to an operator-controlled local/private endpoint.
4. Make WebUI and Conductor auth mandatory in production; bind control services to loopback/private interfaces.
5. Remove default Vaultwarden credentials and disable public signup.
6. Add startup assertions that refuse cloud providers, external NATS, empty auth keys, wildcard binds, and mutable image tags.

### P1 — Before handling sensitive data

1. Add systemd/container sandboxing and dedicated service accounts.
2. Add webhook signature verification, replay protection, quotas, and source allowlists.
3. Separate model-server and tool-runner trust zones with firewall/egress policy.
4. Pin dependencies/images, produce SBOMs, verify model/tokenizer provenance.
5. Add append-only security audit events and encrypted backups with restore tests.

### P2 — Hardening and continuous assurance

1. Add CI security tests for path traversal, auth-disabled startup, CORS, secret leakage, webhook replay, and provider egress.
2. Run dependency and container vulnerability scans on every release.
3. Add canary prompts and scheduled egress checks.
4. Benchmark every model/quantization change and retain the results with the deployment manifest.
5. Perform an independent penetration test after P0/P1 closure.

## 10. HIPAA-specific assessment for Thoth and Caduceus

### Compliance boundary

This paper does **not** certify Pantheon as HIPAA compliant. HIPAA compliance belongs to the covered entity/business associate operating the system, including its policies, workforce, contracts, risk analysis, incident response, and evidence. HHS describes the Security Rule as requiring reasonable and appropriate **administrative, physical, and technical safeguards** for ePHI, alongside the Privacy Rule and Breach Notification Rule.[15]

HHS also states that the current Security Rule is technology-neutral and scalable: the organization must choose safeguards based on its size, complexity, capabilities, infrastructure, cost, and the probability and criticality of risks.[15] Therefore, the BOSGAME hardware can be an appropriate platform, but the hardware is only one part of the compliance system.

### Intended role separation

- **Thoth:** research synthesis and evidence weighing. Default mode should be de-identified/public research. Thoth must not receive identifiable patient data merely to improve a literature summary.
- **Caduceus:** medical research assistance and health-information structuring. It may process ePHI only inside the controlled PHI zone, under an approved use case, minimum-necessary policy, access control, audit logging, and human clinical oversight.
- **Neither god:** diagnoses, prescribes, authorizes treatment, or autonomously communicates clinical instructions. Caduceus’s existing identity boundary—inform, structure, and support rather than diagnose or prescribe—is a useful safety control, but it is not a HIPAA control.

### PHI/ePHI data inventory that must be controlled

For this deployment, treat all of the following as potentially ePHI when they contain identifiers or reasonably linkable health information:

1. Chat prompts and model responses.
2. Tool calls, tool results, browser content, downloaded papers, uploaded documents, and generated reports.
3. Caduceus Ichor raw-turn SQLite data and any session/index JSON.
4. Athenaeum Codex-Asclepius files, embeddings, vector indexes, caches, and backups.
5. Conductor/NATS events, handoffs, webhook payloads, A2A messages, crash dumps, swap/page files, and temporary files.
6. WebUI, gateway, systemd, reverse-proxy, model-server, and audit logs.
7. Discord or other messaging traffic. The current Caduceus profile has Discord enabled; PHI must not be routed there until a separate contractual/privacy review approves that channel for the intended use.
8. Model-server request logs, metrics, traces, prompt caches, GPU memory, and diagnostic bundles.

HHS risk-analysis guidance says the analysis must cover all ePHI an organization creates, receives, maintains, or transmits, regardless of the electronic medium or location, and that risk analysis is foundational to selecting safeguards.[16]

### HIPAA status of the current Thoth/Caduceus configuration

**Status: FAIL — research-only or de-identified use until remediated.**

Observed blockers:

- Caduceus has `context.engine: ichor` with raw-turn storage enabled, creating a durable PHI retention surface.
- Caduceus has Discord enabled and configured for free responses; this is not an approved PHI channel by default.
- Thoth and Caduceus retain cloud/remote provider definitions and remote Ollama routes; this violates the intended PHI locality boundary until removed and egress-tested.
- A2A bearer credentials are present in profile configuration and are shared across multiple god endpoints; rotate and replace with per-service identities before PHI use.
- The current WebUI/Conductor authentication and broad-bind findings remain production blockers.
- No evidence was found in this review of a completed HIPAA risk analysis, system-wide PHI inventory, retention schedule, access review, incident/breach procedure, contingency/restore test, workforce training record, or business associate register.

### Required HIPAA control set

#### Administrative safeguards

- Name a security/privacy owner and a clinical safety owner.
- Complete and sign an accurate risk analysis and risk-management plan; update it after model, runtime, network, workflow, or data-store changes.
- Define permitted uses, minimum necessary data, retention/deletion, access approval, sanctions, incident response, breach assessment, and downtime procedures.
- Document whether the operator is a covered entity, business associate, or neither for each use case. HHS defines business associates as organizations performing specified services involving PHI and requires written protections in the business-associate contract where applicable.[17]
- Maintain a vendor/contract register. Self-hosting eliminates a model API provider from the inference path, but it does not automatically resolve obligations for hardware support, managed networking, backup providers, messaging platforms, or other contractors.
- Train operators and users on PHI handling, prompt injection, minimum necessary use, unsafe clinical output, and reporting obligations.

#### Technical safeguards

- Unique user identity; MFA for all administrative and PHI access; role-based access separating operator, researcher, clinician reviewer, and service accounts.
- Mandatory TLS for every cross-host hop; mTLS or narrowly scoped service credentials for WebUI, Conductor, NATS, A2A, and the model server.
- Encryption at rest for the NVMe volume and encrypted, access-controlled backups; document key ownership, rotation, recovery, and destruction.
- Tamper-evident audit logs recording user/service identity, timestamp, source, patient/workspace scope, model and artifact digest, prompt/response access, tool invocation, approval, export, deletion, and failure. Protect logs from ordinary service accounts and test that audit failure cannot silently disable the system.
- Automatic session expiry, revocation, idle timeout, rate limits, CSRF protection, secure cookies, and no PHI in URLs or query strings.
- Egress deny-by-default from the model server, tool runner, and PHI datastore. Allow only explicitly approved local/private destinations.
- No PHI in Discord, public web search, general browser automation, cloud telemetry, third-party embeddings, or unreviewed A2A routes.
- Retention controls for Ichor raw turns, session history, reports, indexes, logs, backups, and model-server caches. “Redaction in API responses” is not deletion.
- Human approval before any external communication, clinical recommendation, medication-related output, record mutation, or destructive action.

#### Physical and availability safeguards

- Place the M5 in a controlled location with restricted physical access, secured boot/firmware settings, and a documented device inventory.
- Use full-disk encryption with a recovery process that does not place keys beside the device.
- UPS protection, tested graceful shutdown, spare/rollback media, encrypted backups, and a disaster-recovery runbook.
- Test restoration of Caduceus codexes, Ichor data, audit logs, configuration, and model artifacts without restoring secrets into an untrusted environment.

### HIPAA-safe operating modes

| Mode | Data allowed | Status |
|---|---|---|
| Public research | Public papers, public datasets, no identifiers | Suitable starting mode |
| De-identified research | Properly de-identified data with re-identification controls held separately | Requires documented method and review |
| Limited-data clinical research | Minimum-necessary ePHI in isolated PHI workspace | Requires completed risk analysis and controls |
| Patient-facing or treatment-support workflow | ePHI plus clinical-impacting outputs | Separate clinical governance, validation, human sign-off, and legal review required |

## 11. BOSGAME M5 deployment assessment

The BOSGAME product page lists the M5 configuration as 128 GB LPDDR5X memory, 2 TB SSD, a 40-compute-unit RDNA 3.5 integrated GPU, and 2.5 GbE.[19] AMD’s official Ryzen AI Max+ 395 material describes 128 GB unified memory, up to 112 GB allocatable by the GPU, 40 RDNA 3.5 compute units, and on-device large-model workloads.[18] These are vendor specifications and capability claims, not a Pantheon throughput or HIPAA certification.

The unified-memory architecture is an important distinction: this is not 128 GB of dedicated VRAM. CPU processes, the operating system, the model, KV cache, embeddings, WebUI, Conductor, and audit services compete for the same memory pool. AMD’s ROCm guidance describes Strix Halo as GPU virtual memory mapped over shared system memory and calls out kernel/driver requirements for Ryzen AI Max APUs.[20]

### Recommended M5 configuration

- **OS:** Ubuntu LTS with a documented, tested kernel/firmware/ROCm stack. Pin the exact kernel, amdgpu/ROCm version, model runtime, and container/runtime digests.
- **Memory policy:** reserve 32–48 GB for OS and Pantheon services; allocate the remaining pool conservatively to inference. Do not configure the model to consume the entire 128 GB.
- **Model:** 37B-class 4-bit artifact as the default target. The calculated weight budget is approximately 22.2 GB before KV-cache growth, so the M5 has substantial capacity if the runtime uses the integrated GPU efficiently.
- **Runtime:** validate llama.cpp/Vulkan or ROCm first on this APU; treat vLLM on gfx1151 as a compatibility/performance experiment until the exact installed stack passes benchmarks and restart tests.
- **Storage:** use LUKS/full-disk encryption, separate encrypted PHI and non-PHI data roots, 2 TB NVMe with quota/retention controls, and encrypted offline backups.
- **Network:** 2.5 GbE is adequate for a single-node or private inference/control-plane segment, but expose no model, NATS, MCP, WebUI, or database port to the Internet.
- **Thermals:** run sustained-load tests and record temperature, throttling, latency, memory pressure, and restart behavior. Do not treat a short vendor benchmark as production capacity.

### M5 acceptance tests

1. Confirm the exact model artifact, tokenizer, quantization, license, and SHA-256 digest.
2. Run a 37B 4-bit benchmark at the real context length and concurrency used by Thoth/Caduceus.
3. Prove the model server cannot read `~/.hermes`, Vaultwarden data, browser profiles, or unrestricted workspaces.
4. Submit a canary prompt containing a unique marker; inspect DNS, sockets, firewall logs, and packet capture for unauthorized egress.
5. Confirm no request/response/prompt is written to model-server logs, traces, crash dumps, or external telemetry.
6. Exercise Caduceus raw-turn retention, deletion, backup, restore, and audit-log paths with synthetic PHI.
7. Verify Discord, public search, cloud providers, remote Ollama, A2A, and webhooks are blocked or explicitly controlled in PHI mode.
8. Test a user access review, session revocation, failed-login alert, incident ticket, backup restore, and full service restart.
9. Obtain an independent HIPAA/security review before live patient data is introduced.

## 12. Bottom line

Pantheon has a promising control-plane foundation, but its current operational configuration is **not self-hosted in the strict security sense and is not ready for HIPAA-regulated PHI**. The M5 hardware is likely capable of hosting a quantized 37B-class model, but that is only the compute layer.

The safe rollout path is: **public research first → de-identified research → controlled limited-data research → only then any clinically consequential workflow**. Caduceus must be isolated from Discord and uncontrolled A2A/cloud routes; Thoth should default to de-identified research; raw-turn storage, logs, backups, embeddings, and model-server diagnostics must all be included in the PHI inventory.

A HIPAA-ready deployment is achievable only after the P0 network/provider fixes, a documented HHS-aligned risk analysis, administrative/physical safeguards, mandatory technical controls, clinical governance, tested recovery, and independent review are complete. Hardware does not confer HIPAA compliance. No oracle, no loophole—just controls that hold under pressure.

## Sources

[15] HHS Summary of the HIPAA Security Rule — <https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations>  
[16] HHS Guidance on Risk Analysis — <https://www.hhs.gov/hipaa/for-professionals/security/guidance/guidance-risk-analysis>  
[17] HHS Summary of the HIPAA Privacy Rule — <https://www.hhs.gov/hipaa/for-professionals/privacy/laws-regulations/index.html>  
[18] AMD Ryzen AI Max+ 395 AI article — <https://www.amd.com/en/developer/resources/technical-articles/2025/amd-ryzen-ai-max-395--a-leap-forward-in-generative-ai-performanc.html>  
[19] BOSGAME M5 product page — <https://www.bosgame.com/products/bosgame-m5-ai-mini-desktop-ryzen-ai-max-395-96gb-128gb-2tb>  
[20] AMD ROCm Strix Halo system optimization — <https://rocm.docs.amd.com/en/latest/how-to/system-optimization/strixhalo.html>

## Evidence register

### Local evidence inspected

- `/home/konan/.hermes/config.yaml` — active model/provider and auxiliary routes.
- `/home/konan/pantheon/conductor/conductor.service` — external NATS URL and service identity.
- `/home/konan/pantheon/conductor/v2/auth.py` — bearer/query-key handling and auth-disabled behavior.
- `/home/konan/pantheon/conductor/v2/webhook.py` — default bind and webhook routes.
- `/home/konan/pantheon/webui/api/auth.py` — optional auth, session signing, password hashing, rate limiting.
- `/home/konan/pantheon/webui/api/helpers.py` — path containment and response security headers/redaction helpers.
- `/home/konan/pantheon/webui/pantheon-webui.service` — `0.0.0.0:8787` binding.
- `/home/konan/pantheon/webui/docker-compose.yml` — loopback example and optional password.
- `/home/konan/pantheon/scripts/docker-compose.yml` — broad Ollama/Core port publication and missing `pantheon-core/Dockerfile` at review path.
- `/home/konan/pantheon/vaultwarden/docker-compose.yml` — default admin token fallback and enabled signup.
- `/home/konan/pantheon/pantheon-core/mcp_server.py` — loopback HTTP default and MCP transport behavior.

### External evidence

- Qwen3 announcement: <https://qwenlm.github.io/blog/qwen3/>
- Qwen3-30B-A3B model card: <https://huggingface.co/Qwen/Qwen3-30B-A3B>
- Qwen3-30B-A3B config: <https://huggingface.co/Qwen/Qwen3-30B-A3B/raw/main/config.json>
- vLLM GPU installation requirements: <https://docs.vllm.ai/en/latest/getting_started/installation/gpu.html>
- vLLM online serving/OpenAI-compatible API: <https://docs.vllm.ai/en/latest/serving/online_serving/>
- llama.cpp project: <https://github.com/ggml-org/llama.cpp>
- OWASP Top 10 for LLM Applications: <https://owasp.org/www-project-top-10-for-large-language-model-applications/>
- NIST AI Risk Management Framework: <https://www.nist.gov/itl/ai-risk-management-framework>
