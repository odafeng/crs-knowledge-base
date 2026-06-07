# 0001. Zero-Build Static SPA

**Status**: Accepted

## Context

This is a clinical knowledge base for colorectal surgeons to consult during rounds or in the OR. The primary requirements are: instant load, offline capability, and zero maintenance burden on the infrastructure side. The content update frequency (weekly at most) is far lower than a typical web app's UI iteration frequency.

Choosing React/Vue/Svelte would add a build step, node_modules, bundler config, and deployment complexity. The audience (surgeons) needs reliability over aesthetics.

## Decision

Use a single `index.html` file with vanilla HTML/CSS/JS. No framework, no bundler, no npm. Deploy directly to GitHub Pages from the repo root.

## Consequences

- **Positive**: Zero build time, zero dependency rot, trivial deployment (push = live), any browser can open the file
- **Positive**: PWA via Service Worker is straightforward without framework hydration concerns
- **Negative**: No component reuse — similar UI patterns (cards, timelines) are repeated as template literals
- **Negative**: Data was initially embedded inline (fixed in ADR-0006)
- **Negative**: No HMR or dev server convenience — must use `python -m http.server`
- **Negative**: Scaling to 50+ views in one file will become unwieldy (not yet a problem at 8 topics)
