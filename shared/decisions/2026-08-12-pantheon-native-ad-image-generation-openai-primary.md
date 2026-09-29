# 2026-08-12 — Pantheon-native ad image generation uses OpenAI/ChatGPT as primary image engine

**Decision:** Pantheon-native ad image generation should use ChatGPT / OpenAI GPT Image as the primary image-generation path. Pantheon owns the ad brief, campaign memory, offer/template selection, prompt assembly, QA, export variants, and performance feedback loop; other image models are fallbacks for specialized cases.

**Rationale:** Konan clarified that the desired system is not primarily a third-party ad-creative SaaS comparison or a generic multi-model router. The product shape is Pantheon-native: Kairos/Pantheon should generate paid-ad visuals from its own campaign context while using ChatGPT as the primary image model.

**Alternatives considered:**
- Human-operated SaaS stack such as Canva Grow or AdCreative.ai. Useful for immediate manual work, but not the native Pantheon capability Konan was asking for.
- Model-first router with Ideogram/Recraft/FLUX/Gemini/OpenAI as peers. Still useful internally, but it should not obscure the primary default: ChatGPT/OpenAI image generation first, specialized fallbacks only when needed.

**Evidence:** Discord thread `1536470984712917034`, message `1537079698784522350`: "Ok I was more referring to a pantheon native ad image generation. That uses chatgpt for the primary image generation". Skill `paid-ad-visual-production` patched on 2026-08-12 to encode OpenAI/ChatGPT as the primary native path.

**Reversibility:** Easy. This is a design/product-direction decision. Pantheon can later promote another model to primary if live ad generation QA or cost/performance data shows OpenAI is inferior.

**Decided by:** Konan, transcribed by Thoth on 2026-08-12

**Operator sign-off:** konan
