# Frontend Studio

This directory contains an isolated Next.js frontend shell for the AI Novel workspace.

## Scope

- Only frontend files live here.
- Existing Python backend codepaths are intentionally untouched.
- The app is structured around product workspaces instead of one large Gradio control page.

## Proposed routes

- `/` studio landing
- `/create` unified create launcher
- `/novel` and `/novel/[id]`
- `/video` and `/video/[id]`
- `/ppt` and `/ppt/[id]`
- `/projects`
- `/tasks`
- `/settings`

## API integration plan

The frontend expects a future HTTP layer exposed by the Python backend. Suggested endpoints:

- `GET /api/projects`
- `GET /api/tasks`
- `GET /api/novels/:id`
- `GET /api/videos/:id`
- `GET /api/ppt/:id`

Set `NEXT_PUBLIC_API_BASE_URL` when the API layer is ready.

## Local development

```bash
cd frontend
npm install
npm run dev
```
