Output docs/assets/demo.gif

Require curl
Require python

Set Shell "powershell"
Set FontSize 16
Set Width 1180
Set Height 720
Set Theme "Catppuccin Mocha"
Set Padding 28
Set Margin 12
Set MarginFill "#11111b"
Set BorderRadius 10
Set WindowBar "Colorful"
Set TypingSpeed 30ms

Hide
Type "function prompt { 'MIRSAD MASR $ ' }"
Enter
Type "curl.exe -s http://127.0.0.1:8000/v1/quote/COMI | Out-Null"
Enter
Type "cls"
Enter
Show

Sleep 500ms
Type "# MIRSAD MASR: self-hosted EGX market data API"
Enter
Sleep 700ms

Type "# Start the app with Docker, then call the API:"
Enter
Type "# docker compose up --build"
Enter
Sleep 1000ms

Type "# python -m json.tool only formats the JSON output"
Enter
Sleep 700ms

Type "# Check that MIRSAD MASR is running"
Enter
Type "curl.exe -s http://127.0.0.1:8000/v1/health | python -m json.tool"
Enter
Sleep 2500ms

Type "# Get one live EGX quote"
Enter
Type "curl.exe -s http://127.0.0.1:8000/v1/quote/COMI | python -m json.tool"
Enter
Sleep 4500ms

Type "# Explore the rest at http://127.0.0.1:8000/docs"
Enter
Sleep 1600ms

Sleep 1s
