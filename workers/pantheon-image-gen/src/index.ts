export interface Env {
  AI: Ai;
  IMAGE_API_KEY: string;
}

type SocialPreset = "social-square" | "social-wide" | "blog-hero" | "blog-section" | "quote-bg" | "ad-concept";

interface GenerateRequest {
  prompt: string;
  preset?: SocialPreset;
  steps?: number;
  format?: "json" | "jpeg";
}

const PRESET_CONFIG: Record<SocialPreset, { model: string; defaultSteps: number }> = {
  "social-square": { model: "@cf/black-forest-labs/flux-1-schnell", defaultSteps: 4 },
  "social-wide": { model: "@cf/black-forest-labs/flux-1-schnell", defaultSteps: 4 },
  "blog-hero": { model: "@cf/black-forest-labs/flux-1-schnell", defaultSteps: 6 },
  "blog-section": { model: "@cf/black-forest-labs/flux-1-schnell", defaultSteps: 4 },
  "quote-bg": { model: "@cf/black-forest-labs/flux-1-schnell", defaultSteps: 4 },
  "ad-concept": { model: "@cf/black-forest-labs/flux-1-schnell", defaultSteps: 6 },
};

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (request.method !== "POST") {
      return new Response(JSON.stringify({ error: "Method not allowed" }), {
        status: 405,
        headers: { "Content-Type": "application/json" },
      });
    }

    const auth = request.headers.get("Authorization") || "";
    if (auth !== `Bearer ${env.IMAGE_API_KEY}`) {
      return new Response(JSON.stringify({ error: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    }

    let body: GenerateRequest;
    try {
      body = await request.json();
    } catch {
      return Response.json({ error: "Invalid JSON body" }, { status: 400 });
    }

    const prompt = body.prompt?.trim();
    if (!prompt) {
      return Response.json({ error: "Missing required field: prompt" }, { status: 400 });
    }

    const preset = body.preset || "social-square";
    const config = PRESET_CONFIG[preset];
    if (!config) {
      return Response.json({ error: `Unknown preset: ${preset}` }, { status: 400 });
    }

    const steps = Math.min(Math.max(body.steps ?? config.defaultSteps, 1), 8);

    const result = await env.AI.run(config.model, {
      prompt,
      steps,
      seed: Math.floor(Math.random() * 1_000_000),
    });

    const imageBase64 = (result as { image: string }).image;

    // Return raw JPEG if format=jpeg, otherwise JSON with data URI
    if (body.format === "jpeg") {
      const binary = Uint8Array.from(atob(imageBase64), (c) => c.charCodeAt(0));
      return new Response(binary, {
        headers: {
          "Content-Type": "image/jpeg",
          "Cache-Control": "no-store, max-age=0",
        },
      });
    }

    return Response.json({
      success: true,
      model: config.model,
      preset,
      prompt,
      steps,
      image: `data:image/jpeg;charset=utf-8;base64,${imageBase64}`,
    });
  },
};
