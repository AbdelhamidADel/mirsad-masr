# MIRSAD MASR web

Static Next.js frontend for `https://egxdesk.ashh.me`.

## Local development

```bash
pnpm install
pnpm dev
```

The live demo calls `NEXT_PUBLIC_EGXDESK_API_URL`, defaulting to:

```dotenv
NEXT_PUBLIC_EGXDESK_API_URL=https://demo.egxdesk.ashh.me
```

Set the same variable in Vercel if the API endpoint changes.
