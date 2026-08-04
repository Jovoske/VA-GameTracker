@echo off
REM Double-click to put the GameSense dashboard on a public HTTPS URL for your phone.
REM The app itself must already be running (start.bat / docker compose up -d).
REM A fresh URL is printed each time; keep this window open while you use it on mobile.
echo Starting a secure tunnel to the dashboard (http://localhost:8080)...
echo Look for the https://....trycloudflare.com line below, open it on your phone.
echo Close this window to stop sharing.
echo.
"%LOCALAPPDATA%\cloudflared\cloudflared.exe" tunnel --url http://localhost:8080
pause
