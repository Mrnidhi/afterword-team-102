# Afterword — interactive design prototype

A private design preview for a family organizing the practical work after a death. Built from the supplied Afterword product document, with a fictional estate for Arun Rao and Priya Rao. No source-document credentials, personal records or private identifiers are included.

## Open and explore

The website starts at the family overview. Navigation gives access to nine distinct compositions:

1. **Overview** — a next step, practical task count and a gentle invitation to memories.
2. **Action plan** — a numbered list, status filters, source-linked details, completion, reopening and waiting states.
3. **Documents** — full-text search across fictional excerpts, file-type filters, readable previews and one additional sample import.
4. **Evidence review** — source beside finding; separate known, unknown and suggested-next-step content; reversible read status.
5. **Letters** — three editable information-request templates, preview, browser-local saving and text export with an on-screen copy fallback.
6. **Memories** — an editorial archive, reading dialogs and reversible favorites.
7. **Ask Afterword** — four scripted, source-linked demonstrations and an honest unsupported-question response.
8. **Privacy & processing** — a proposed HP ZGX Nano workflow, explicit disconnected states and an illustrative boundary review.
9. **Design & research** — primary references, decisions, limitations, palette and scope.

All amounts, dates, providers, people and passages are fictional. Provider response dates and user reminders are not statutory deadlines. The policy and will excerpts concern potentially different assets and do not establish a beneficiary entitlement. The medical receipt does not establish the current balance.

## Implementation

This is a buildless, dependency-free application: semantic HTML, CSS and JavaScript. `dist/` is the deployable website. The only external presentation dependency is the Google Fonts stylesheet for DM Sans and Newsreader; readable system-font fallbacks are supplied. No analytics, AI calls or account connections are included.

- `dist/app.js`: stable application shell, routing, base state, task fixtures, overview and dialog helpers.
- `dist/pages.js`: document fixtures, distinct page renderers and interaction handlers.
- `dist/styles.css`: shared tokens, task-specific layouts, responsive rules, keyboard focus and reduced-motion handling.
- `dist/assets/coastal-path.png`: original illustrative asset, included locally.

Hash routes are deep-linkable. User-entered content is escaped before HTML rendering. Task status, reviewed findings, favorite memories, one sample letter draft and reading size persist under `afterword-design-v2` in browser local storage. Search, conversation and the additional sample import are session-only. Draft-template identity is saved with the draft. Editing and previewing remain client-side. Browser storage is not encrypted and is not appropriate for real estate records.

The app also feature-detects the browser's experimental WebMCP API and registers one read-only tool for the fictional action plan. It grants no external access. Ordinary UI operation does not depend on this API.

To run locally, serve `dist/` with any static server. There is no install or build step. The Sites manifest specifies `dist` as the static directory.

## Design rationale and research

Read September 2026. These are design inputs, not evidence of clinical efficacy, legal correctness, commercial uniqueness, sponsor endorsement or validated outcomes for bereaved families.

- [Generative Interfaces for Language Models, August 2025](https://arxiv.org/html/2508.19227v1): structured, task-specific representations informed the separate planning, evidence and document surfaces. Evaluation used 100 generated prompts and preference judgments; it does not establish estate-task correctness. A polished interface can increase perceived credibility, so sources and unknowns remain visible.
- [In-Situ Adaptive Interfaces for Online Browsing, IUI 2026](https://gracekim.me/docs/AdaptiveInterfaces.pdf), [DOI](https://doi.org/10.1145/3742413.3789092): explicit control, persistent preferences and reversibility informed the interface. A qualitative probe with 10 frequent shoppers, not a controlled workload study or bereavement study. Navigation remains stable.
- [Improving Human Verification of LLM Reasoning through Interactive Explanation Interfaces, October 2025](https://arxiv.org/html/2510.22922v1): informed source inspection and highlighted excerpts. The experiment analyzed 125 undergraduates reviewing math explanations with injected errors; its results cannot establish Afterword's accuracy or speed.
- [Google Material 3 Expressive research](https://design.google/library/expressive-material-design-google-research): purposeful visual hierarchy and prominent next actions, adapted to a restrained setting.
- [Microsoft Fluent 2 color](https://fluent2.microsoft.design/color), [motion](https://fluent2.microsoft.design/motion), [accessibility](https://fluent2.microsoft.design/accessibility): neutral reading surfaces, limited semantic color, brief transitions and reduced motion.
- W3C WCAG 2.2 guidance on [contrast](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html), [reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html), [target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum), and [consistent help](https://www.w3.org/WAI/WCAG22/Understanding/consistent-help.html). Implementation checks are not an independent accessibility certification.
- Service references for wording and workflow: [Empathy](https://www.empathy.com/solutions/loss-support), [Sunset](https://www.hellosunset.com/), [Settld](https://www.settld.care/). No visual identity was copied. These services also make novelty claims inappropriate.

Warm paper and evergreen are brand choices, not claims that particular colors universally improve grief or cognition. Serif typography is reserved primarily for welcoming headings, source documents, letters and memories. Tasks and controls use a sans-serif. Amber identifies uncertainty with an accompanying text label. There is no grief score, emotional countdown or celebration animation.

## Production boundary and next engineering work

The prototype implements the frontend experience, not the estate-processing backend. Authentication, authority checks, consent, multi-user roles, encrypted ingestion, native document parsers, local inference, provenance storage, grounded retrieval, secure routing, jurisdiction-specific rules and deletion/export controls remain to be built and evaluated.

The planned HP deployment uses local parsing, a smaller model for extraction, a larger model for difficult comparisons, and explicit family review. The 8B/70B model sizes are proposed targets. No latency, memory, accuracy, cost, security or hardware results are claimed. Any optional cloud path needs threat modeling, payload review, explicit consent and leakage evaluation; removing names is not a sufficient privacy guarantee.

A production service should maintain immutable source records with span coordinates; version findings separately from source facts; store user review as an acknowledgement rather than truth; and make letter preparation distinct from any external sending. UI actions should call authorization-checked services instead of mutating browser fixtures. A realistic first backend slice is text-native files → extracted spans → insurance or billing comparison → human-reviewed information request.

## Illustration provenance

One new 1536 × 1024 image generated using OpenAI image generation, with no reference image, variants or retries. It was visually inspected and copied into the website. CSS crops the same asset for the overview and memories page. It represents an illustration, not a photograph from the fictional family.

Prompt: “Use case: stylized-concept. Asset type: original in-page website illustration for Afterword, a respectful bereavement and estate-organizing app. A quiet contemporary editorial fine-art landscape of California coastal hills and a winding footpath beneath a pale sky. Refined understated realism with subtle painted paper texture, not flat vector art. Landscape approximately 3:2; the right half must work as a standalone crop while the complete landscape works in a memories archive. Gentle hopeful afternoon light; atmospheric greens, muted olive, warm ivory and pale sky. No people, symbols of death, floating objects, text, typography, UI, logos or watermark.”

## Verification notes

JavaScript syntax checked. Browser interaction checks cover evidence selection and review/undo, evidence-to-letter navigation, letter editing and preview, correct saved-template restoration, document search and empty filters, sample import, completion and reopening, favorites and source-linked sample answers. All nine views were checked at 320px with no page-level horizontal overflow; desktop and 390px phone layouts were visually inspected. Skip navigation preserves the current page and focuses its main content; closed mobile navigation is excluded from the focus order. Browser error logs were empty during these checks. The browser's file-download event was not reported by the in-app browser; text export therefore includes a visible selectable fallback. The optional WebMCP tool was not exposed by the preview browser and could not be exercised. These checks are not a full accessibility audit.
