# Margadeep

Margadeep helps autistic children and caregivers turn unpredictable real-world moments into supported, learnable experiences.

This repository contains the backend, web, and mobile proof-of-concept surfaces for preparation, live support, recovery, and caregiver review.

- Angular for the app shell
- Phaser for the scene renderer
- A2UI for the interaction panel
- Python/FastAPI for the backend
- Gemini Flash as an optional backend model

## Structure

- `frontend/`: Angular app with Phaser scene host and A2UI custom catalog
- `backend/`: FastAPI app that returns scene state plus A2UI messages

## Run

### Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Set `GEMINI_API_KEY` and optionally `GEMINI_MODEL` to enable live Gemini responses. Without an API key, the backend uses deterministic scripted turns.

### Frontend

```bash
cd frontend
npm install
npm run start
```

Then open `http://localhost:4200`.
