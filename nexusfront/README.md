# NEXUS Forensics (standalone)

A standalone extraction of the `nexus-forensics` UI mockup — a
self-contained React app with no backend/DB dependency. All data
(cases, suspects, graph nodes) is hardcoded in `src/App.tsx`; the
login screen accepts any Badge ID / password combo since it's just a
local state transition, not real auth.

## Run locally

```bash
npm install
npm run dev
```

Then open http://localhost:5173

## Build for deployment

```bash
npm run build   # outputs static files to dist/
npm run serve   # preview the production build locally
```

`dist/` is a plain static site — you can host it anywhere (Netlify,
Vercel, GitHub Pages, S3, nginx, etc.) with no server-side code
required.

## Structure

- `src/App.tsx` — all screens/views and mock data (cases, graph edges,
  evidence records)
- `src/index.css` — theme tokens (dark navy palette, fonts, grid
  background, noise overlay)
- `src/components/ui/` — shadcn/ui-style components (Radix + Tailwind)
- `src/components/error-boundary.tsx` — top-level error boundary

## Customizing

- Edit the `cases`, `graphNodes`, and `edges` arrays near the top of
  `src/App.tsx` to change the fake case data.
- Edit CSS variables at the top of `src/index.css` (`--ink`, `--cyan`,
  `--amber`, etc.) to change the color scheme.
