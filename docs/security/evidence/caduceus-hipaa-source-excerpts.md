# Caduceus Clinic Security Evidence Excerpts

**Captured:** 2026-08-26
**Purpose:** Verbatim source excerpts used to ground the Caduceus Clinic security and HIPAA readiness assessment.
**Method:** Official HHS/OCR and NIST pages were fetched through the configured research connector. The FDA document was located through official FDA search, but its PDF body was not extractable through the available fetchers; that limitation is recorded below.

## Evidence index

| ID | Source | Claim supported |
|---|---|---|
| HHS-SEC-01 | HHS Security Rule summary | Risk assessment and reasonable/appropriate safeguards |
| HHS-SEC-02 | HHS Security Rule summary | Minimum-necessary role access |
| HHS-SEC-03 | HHS Security Rule summary | Incident response and documentation |
| HHS-SEC-04 | HHS Security Rule summary | Backup, restore, and contingency planning |
| HHS-SEC-05 | HHS Security Rule summary | Audit controls and authentication |
| HHS-SEC-06 | HHS Security Rule summary | Business-associate written arrangement |
| HHS-RISK-01 | HHS risk-analysis guidance | Scope of all ePHI and risk analysis requirement |
| HHS-DEID-01 | HHS de-identification guidance | Safe Harbor and Expert Determination |
| HHS-DEID-02 | HHS de-identification guidance | Re-identification codes and PHI status |
| HHS-BREACH-01 | HHS breach notification rule | Breach notification responsibility |
| NIST-AI-01 | NIST AI RMF 1.0 | Trustworthiness characteristics |
| NIST-AI-02 | NIST AI RMF 1.0 | Govern, Map, Measure, Manage functions |

## HHS-SEC — Summary of the HIPAA Security Rule

**URL:** https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations

### HHS-SEC-01

> A regulated entity must perform an accurate and thorough assessment of potential risks and vulnerabilities to ePHI, and it must manage risks by implementing security measures that reduce risks and vulnerabilities to a reasonable and appropriate level.

### HHS-SEC-02

> A regulated entity must implement policies and procedures for authorizing access to ePHI only when such access is appropriate for the user or recipient's role, consistent with the Privacy Rule's "minimum necessary" standard.

### HHS-SEC-03

> A regulated entity must implement policies and procedures to identify and respond to suspected or known security incidents, mitigate harmful effects to the extent possible, and document security incidents and their outcomes.

### HHS-SEC-04

> A regulated entity must establish and implement procedures for responding to emergencies or occurrences that damage information systems containing ePHI, including plans for backing up data, restoring lost data, and continuing critical business processes while operating in emergency mode.

### HHS-SEC-05

> A regulated entity must implement hardware, software, and/or procedural mechanisms to record and examine activity in information systems containing or using ePHI.

> A regulated entity must implement procedures to verify that a person seeking access to ePHI is who they claim to be.

### HHS-SEC-06

> Before permitting a business associate to create, receive, maintain, or transmit ePHI, a regulated entity must have a compliant business associate agreement or other written arrangement in place.

## HHS-RISK — Guidance on Risk Analysis

**URL:** https://www.hhs.gov/hipaa/for-professionals/security/guidance/guidance-risk-analysis

### HHS-RISK-01

> Conduct an accurate and thorough assessment of the potential risks and vulnerabilities to the confidentiality, integrity, and availability of electronic protected health information held by the [organization].

> The scope of risk analysis that the Security Rule encompasses includes the potential risks and vulnerabilities to the confidentiality, availability and integrity of all e-PHI that an organization creates, receives, maintains, or transmits.

## HHS-DEID — De-identification Guidance

**URL:** https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification

### HHS-DEID-01

> The guidance explains and answers questions regarding the two methods that can be used to satisfy the Privacy Rule’s de-identification standard: Expert Determination and Safe Harbor.

### HHS-DEID-02

> Disclosure of a code or other means of record identification designed to enable coded or otherwise de-identified information to be re-identified is considered a disclosure of PHI.

> If a covered entity or business associate successfully undertook an effort to identify the subject of de-identified information it maintained, the health information now related to a specific individual would again be protected by the Privacy Rule, as it would meet the definition of PHI.

## HHS-BREACH — Breach Notification Rule

**URL:** https://www.hhs.gov/hipaa/for-professionals/breach-notification

### HHS-BREACH-01

> The HIPAA Breach Notification Rule, 45 CFR §§ 164.400-414, requires HIPAA covered entities and their business associates to provide notification following a breach of unsecured protected health information.

## FDA-CDS — Clinical Decision Support Software Guidance

**URL:** https://www.fda.gov/media/109618/download

Official FDA search located the current guidance titled **Clinical Decision Support Software — Guidance for Industry and Food and Drug Administration Staff**, issued January 29, 2026. The search result states the guidance includes a criterion that software be intended to enable a health care professional to independently review the basis for recommendations so the professional does not rely primarily on those recommendations for an individual patient's diagnosis or treatment decision.

The official PDF was reached, but its body was not extractable through the configured page fetchers during this review. Therefore, the FDA criterion is cited as a verified search-result summary in the paper, not presented as a verbatim evidence quote. A regulatory specialist should review the final product classification against the actual guidance before commercialization.

## NIST-AI — AI Risk Management Framework 1.0

**URL:** https://nvlpubs.nist.gov/nistpubs/ai/nist.ai.100-1.pdf

### NIST-AI-01

> The Framework is divided into two parts. Part 1 discusses how organizations can frame the risks related to AI and describes the intended audience. Next, AI risks and trustworthiness are analyzed, outlining the characteristics of trustworthy AI systems, which include valid and reliable, safe, secure and resilient, accountable and transparent, explainable and interpretable, privacy enhanced, and fair with their harmful biases managed.

### NIST-AI-02

> Part 2 comprises the "Core" of the Framework. It describes four specific functions to help organizations address the risks of AI systems in practice. These functions – GOVERN, MAP, MEASURE, and MANAGE – are broken down further into categories and subcategories.

## Review limitations

- This is an engineering and operational readiness assessment, not legal advice, HIPAA certification, a penetration test, or an FDA device determination.
- The FDA PDF body could not be extracted by the configured connectors during this run; the limitation is intentionally retained.
- The clinic's legal status, business-associate role, policies, workforce, physical safeguards, retention schedule, and incident procedures require clinic-side verification.
- The exact production model artifact, quantization, runtime, tokenizer, and digest remain deployment gates until selected.
