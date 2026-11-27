# vhs showcase/demo.tape  — renders showcase/demo.gif + showcase/demo.mp4 (run from repo root)
Output showcase/demo.gif
Output showcase/demo.mp4
Require python3
Set Shell "bash"
Set FontSize 15
Set Width 1280
Set Height 760
Set Padding 18
Set Theme "Catppuccin Mocha"
Set TypingSpeed 35ms
Set Framerate 12
Hide
Type "source .venv/bin/activate 2>/dev/null; export PS1='$ '; clear" Enter
Show
Type "make demo" Sleep 300ms Enter
Sleep 28s
Sleep 4s
