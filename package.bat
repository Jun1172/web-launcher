pyinstaller -F -w -i .\doc\images\launcher.ico ^
    --add-data "launcher\templates;launcher\templates" ^
    --hidden-import=clr ^
    --hidden-import=webview.platforms.edgechromium ^
    --hidden-import=webview.platforms.winforms ^
    --collect-submodules=webview ^
    --clean ^
    .\launcher.py
