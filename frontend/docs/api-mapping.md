# API Mapping

This frontend was added without modifying the Python backend. It assumes an HTTP adapter layer can be exposed later.

## Shared surfaces

### Project Center

- `GET /api/projects`
  - Returns cross-product project summaries for novel, video and PPT.

### Task Center

- `GET /api/tasks`
  - Returns queue items from the existing task system.
- `POST /api/tasks/:id/cancel`
- `DELETE /api/tasks/:id`

## Novel workspace

- `POST /api/novels`
- `GET /api/novels/:id`
- `POST /api/novels/:id/generate`
- `POST /api/novels/:id/polish`
- `POST /api/novels/:id/feedback/analyze`
- `POST /api/novels/:id/feedback/apply`
- `POST /api/novels/:id/edit`
- `GET /api/novels/:id/export`

## Video workspace

- `POST /api/videos`
- `GET /api/videos/:id`
- `POST /api/videos/:id/generate`

## PPT workspace

- `POST /api/ppt`
- `GET /api/ppt/:id`
- `POST /api/ppt/:id/generate`
- `GET /api/ppt/:id/export`

## Integration note

The current frontend uses mocked data in `frontend/lib/mock-data.ts`. Replacing the mocks should be done in feature-level hooks rather than page components.
