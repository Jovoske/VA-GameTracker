@echo off
REM GameSense one-command startup (Windows).

where docker >nul 2>nul
if errorlevel 1 (
  echo.
  echo Docker was not found. Install Docker Desktop first:
  echo   https://www.docker.com/products/docker-desktop/
  echo Then re-run start.bat.
  echo.
  exit /b 1
)

if not exist .env (
  echo Creating .env from .env.example ^(edit it to set secrets^)...
  copy /Y .env.example .env >nul
)

echo Starting GameSense ^(db, redis, api, worker, beat, frontend^)...
docker compose up --build
