# Sheet music PDF tool

Web version (use from a phone): upload a PDF, get the A4 / contrast-adjusted PDF back.

## Deploy (Render, free tier)
1. render.com -> New -> Web Service -> connect this GitHub repo, runtime **Docker**.
2. Add env var `APP_TOKEN` = your password.
3. Open the service URL on your phone, enter the password, pick a PDF, tap Convert.

Any Docker host (Fly.io, Railway, Hugging Face Spaces) works the same way.
Local: `APP_TOKEN=secret python app.py`.
