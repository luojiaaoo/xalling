# Development

This project uses `uv` to manage its environment and dependencies.

```powershell
uv sync
Set-Location frontend
npm install
npm run build
Set-Location ..
uv run python main.py
```

Run the quality checks with:

```powershell
uv run ruff check .
uv run pytest
```

The initial `main.py` window uses inline HTML so it runs immediately. Move the UI
into separate HTML, CSS, and JavaScript files as the application grows.
