"""Start the local backend and host the Histórias Studio UI in a native WebView2 window."""
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path
from runtime_paths import data_home

if not getattr(sys, 'frozen', False):
    vendor=Path(__file__).resolve().parent/'build-native'/'vendor'
    if vendor.is_dir(): sys.path.insert(0,str(vendor))

HOST=os.environ.get('HOST','127.0.0.1')
PORT=int(os.environ.get('PORT','8787'))
URL=f'http://{HOST}:{PORT}/#/guides'

def _ready():
    try:
        with urllib.request.urlopen(f'http://{HOST}:{PORT}/api/auth/status',timeout=.5): return True
    except Exception: return False

def _error(text):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,text,'Histórias Studio',0x10)
    except Exception: pass

def main():
    logs=data_home()/'logs';logs.mkdir(parents=True,exist_ok=True)
    log=open(logs/'server.log','a',encoding='utf-8',buffering=1)
    sys.stdout=sys.stderr=log
    try:
        import webview
        import server
    except Exception as exc:
        import traceback
        traceback.print_exc(file=log); log.flush()
        _error(f'Não foi possível carregar a janela desktop do Histórias Studio.\n\nDetalhe: {exc}\n\nConsulte o log em:\n{logs / "server.log"}')
        return
    if not _ready():
        thread=threading.Thread(target=server.serve_forever,name='HistoriasStudioServer',daemon=True)
        thread.start()
        for _ in range(60):
            if _ready(): break
            if not thread.is_alive(): break
            time.sleep(.5)
        if not _ready():
            _error(f'Não foi possível iniciar o Histórias Studio em {HOST}:{PORT}. Verifique se a porta está livre.\n\nConsulte o log em:\n{logs / "server.log"}')
            return
    try:
        window=webview.create_window('Histórias Studio',URL,width=1440,height=920,min_size=(1024,700),background_color='#f4f5f8')
        webview.start(gui='edgechromium',debug=False)
    except Exception as exc:
        import traceback
        traceback.print_exc(file=log); log.flush()
        _error(f'Não foi possível abrir a janela nativa do Histórias Studio. O Microsoft Edge WebView2 Runtime precisa estar instalado.\n\nDetalhe: {exc}\n\nBaixe o runtime em:\nhttps://developer.microsoft.com/microsoft-edge/webview2/')
    finally:
        if server.HTTP_SERVER:
            try: server.HTTP_SERVER.shutdown()
            except Exception: pass
            try: server.HTTP_SERVER.server_close()
            except Exception: pass
        log.close()

if __name__=='__main__':
    main()