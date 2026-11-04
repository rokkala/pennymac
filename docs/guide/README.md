# Platform guide build

Produces the full illustrated PDF:

- **PDF:** `docs/LBP-Platform-Guide.pdf`
- **HTML source:** `docs/guide/LBP-Platform-Guide.html`
- **Screenshots:** `docs/guide/screenshots/`

## Rebuild

1. Run the console locally: `cd frontend && npm run dev -- --host 127.0.0.1 --port 5173`
2. From repo root:

```bash
# screenshots + HTML + PDF
node docs/guide/build-platform-guide.mjs all

# HTML + PDF only (reuse screenshots)
node docs/guide/build-platform-guide.mjs pdf
```

Requires Playwright Chromium (`cd frontend && npx playwright install chromium`).
