# Prompt Collection and Professional Master Prompt

This document consolidates prompt content found in this codespace and provides one merged professional master prompt for production use.

## Collected Prompt Building Blocks

### 1) Core Generation Instruction Block
Source context: gem.py get_prompt static_prompt

Generate a premium, flat graphic design for a square adhesive wrap (1:1 aspect ratio) based on strict parameters:

- Core medium: Flat, strictly 2D graphic design only.
- Full bleed: Edge-to-edge print layout.
- Do not render physical objects, hardware, or mockups.
- Perspective: Orthographic top-down, no 3D perspective.
- Exclusions: No shadows, no curved surfaces, no dimension lines, no white borders, no product mockup backgrounds.
- Theme and geometry: Based on selected theme, background texture, and mathematical/physical rules.
- Aesthetics: High contrast, vector-like crispness.
- Color control: Strict palette usage.
- Banned effects: No smoke, no bokeh, no reflections, no out-of-focus blur.
- Typography mode: Include product name with style, or generate no text at all.
- Output target: Square, print-ready, seamless/tileable, near 68x67mm intent.

### 2) Parameter Defaults Used Across App
Source context: gem.py parser defaults, server.py request defaults, frontend.py form defaults, output args.json

- Theme: Mathematical and physical futuristic
- Background texture: sharp
- Geometry rule: golden ratio proportions
- Product name: empty by default
- Typography style: futuristic
- Color palette: black and white
- Tags: A colorful luxury cyberpunk lighter-cover with glowing orange neon elements and elegant typography.
- Output intent: square print cover, digital print suitability

### 3) Interactive Prompting Questions
Source context: gem.py interactive mode

- Where are the images located (folder, file, or URL)?
- Which tags describe the cover?
- What is the core theme?
- How should the background texture look?
- Is there a geometric rule?
- What is the product name (or none)?
- Which typography style should be used?
- What is the color palette?
- Additional free-text description?

## Professional Merged Master Prompt

Use this as a single master prompt for image generation pipelines and application integrations.

You are generating a premium, print-ready, seamless 2D artwork for a square adhesive wrap product.

Objective:
Create one high-quality, edge-to-edge flat graphic design that is visually striking, mathematically coherent, and suitable for immediate digital print production.

Mandatory constraints:

1. Medium and composition
- Produce only pure 2D artwork.
- Maintain a strict square composition, optimized for 1:1 ratio.
- Keep the layout full bleed, with no borders and no framing margins.

2. Hard exclusions
- Do not depict physical objects, hardware, packaging mockups, devices, or scenes.
- Do not use 3D perspective, depth simulation, curved surfaces, realistic lens blur, smoke, haze, bokeh, or reflective highlight tricks.
- Do not add measurement lines, technical annotations, or external text overlays.

3. Design direction
- Theme: {{THEME}}
- Background texture style: {{BACKGROUND_TEXTURE}}
- Mathematical or physical structure rule: {{GEOMETRY_RULE}}
- Color palette restrictions: {{COLOR_PALETTE}}
- Additional style intent: {{TAGS}}

4. Geometry and visual logic
- Build the composition around mathematically consistent structures.
- Enforce proportion harmony and repeatable visual rhythm.
- Keep edges and shape transitions crisp and controlled.

5. Typography handling
- If product name is provided, integrate it deliberately using {{TYPOGRAPHY_STYLE}}.
- If product name is empty, include no text at all.
- Never place accidental or decorative random text.

6. Production quality
- Output must be clean, high-resolution, and print-safe.
- Prioritize vector-like sharpness and high local contrast.
- Ensure pattern continuity suitable for seamless or tileable usage.
- Target practical wrap usage with near-square physical intent such as around 68x67mm.

7. Final validation checklist
Before finalizing, verify:
- Strictly 2D result
- No banned effects or mockup artifacts
- Palette compliance
- Geometric consistency
- Print-readiness and seamless visual continuity

Return only the final artwork output with no extra explanation.

## Ready-to-Fill Example Prompt

Theme: Mathematical and physical futuristic
Background texture: sharp
Geometry rule: golden ratio proportions
Typography style: futuristic
Product name: none
Color palette: black and white
Additional tags: A colorful luxury cyberpunk lighter-cover with glowing orange neon elements and elegant typography.

Generate one premium, seamless, print-ready square 2D wrap artwork following all mandatory constraints above.

## SaaS Deployment and Operations Prompt Section

Use this section when you need an operations-grade prompt for running lighter0 in Cloud Run or similar environments.

You are an AI engineering assistant responsible for deploying and operating lighter0 as a production SaaS service.

Deployment goals:

1. Build minimal, secure containers with small attack surface.
2. Use environment-driven configuration only (no hardcoded secrets).
3. Ensure reliable startup, health checks, logging, and graceful failure handling.
4. Keep runtime costs low while maintaining stable performance.

Operational constraints:

1. The app must listen on the platform-provided PORT.
2. Secret material must be injected via secret manager or environment variables.
3. Build context must exclude local artifacts (`.env`, `.venv`, outputs, git metadata).
4. All webhook and billing flows must be observable via structured logs.
5. Email notification workflows must fail gracefully and never crash request handling.

Validation checklist:

1. Container boots successfully with `python main.py`.
2. `/api/docs` and root UI are reachable.
3. Stripe webhook endpoint validates signatures and logs events.
4. Zero-credit path blocks paid generation and triggers notification email.
5. Free-generation and paid-generation flows are both verified end-to-end.

Return deployment instructions, env requirements, and risk notes in concise production runbook style.
