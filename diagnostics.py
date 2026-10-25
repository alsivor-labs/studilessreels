"""Hardware and prerequisite checks shown inside the Histórias Studio interface."""
import ctypes, json, os, shutil, subprocess, urllib.request
from pathlib import Path
from runtime_paths import data_home

def _url_ok(url, timeout=1.5):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'HistoriasStudio/1.0'}), timeout=timeout): return True
    except Exception: return False

def _gpu_names():
    if os.name!='nt': return []
    command="Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name | ConvertTo-Json -Compress"
    try:
        r=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,timeout=5,creationflags=0x08000000)
        v=json.loads(r.stdout.strip() or '[]') if r.returncode==0 else []
        return [v] if isinstance(v,str) else [str(x) for x in v]
    except Exception: return []

def _nvidia():
    exe=shutil.which('nvidia-smi')
    if not exe: return []
    try:
        r=subprocess.run([exe,'--query-gpu=name,memory.total','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=5,creationflags=0x08000000 if os.name=='nt' else 0)
        rows=[]
        for line in r.stdout.splitlines():
            p=[x.strip() for x in line.split(',')]
            if len(p)>=2: rows.append({'name':p[0],'vram_gb':round(int(p[1])/1024,1)})
        return rows
    except Exception: return []

def _ram_gb():
    if os.name!='nt': return 0.0
    class Status(ctypes.Structure):
        _fields_=[('dwLength',ctypes.c_ulong),('dwMemoryLoad',ctypes.c_ulong),('ullTotalPhys',ctypes.c_ulonglong),('ullAvailPhys',ctypes.c_ulonglong),('ullTotalPageFile',ctypes.c_ulonglong),('ullAvailPageFile',ctypes.c_ulonglong),('ullTotalVirtual',ctypes.c_ulonglong),('ullAvailVirtual',ctypes.c_ulonglong),('ullAvailExtendedVirtual',ctypes.c_ulonglong)]
    s=Status();s.dwLength=ctypes.sizeof(s)
    try: return round(s.ullTotalPhys/(1024**3),1) if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)) else 0.0
    except Exception: return 0.0

def _webview2_installed():
    if os.name!='nt': return False
    try:
        import winreg
        roots=((winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients'),(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\EdgeUpdate\Clients'),(winreg.HKEY_CURRENT_USER,r'SOFTWARE\Microsoft\EdgeUpdate\Clients'))
        for hive,path in roots:
            try:
                with winreg.OpenKey(hive,path) as parent:
                    for i in range(winreg.QueryInfoKey(parent)[0]):
                        try:
                            with winreg.OpenKey(parent,winreg.EnumKey(parent,i)) as item:
                                name=winreg.QueryValueEx(item,'name')[0]
                                version=winreg.QueryValueEx(item,'pv')[0]
                                if 'WebView2 Runtime' in name and version and version!='0.0.0.0': return True
                        except OSError: pass
            except OSError: pass
    except Exception: pass
    return False
def scan():
    try:
        import platform
        system=f'{platform.system()} {platform.release()} ({platform.machine()})'
    except Exception: system='Windows'
    try: free=round(shutil.disk_usage(data_home()).free/(1024**3),1)
    except OSError: free=0
    nvidia=_nvidia();vram=max((g['vram_gb'] for g in nvidia),default=0);ram=_ram_gb()
    comfy_url=os.environ.get('COMFY_URL','http://127.0.0.1:8188').rstrip('/')
    return {'system':system,'cores':os.cpu_count() or 0,'ram_gb':ram,'disk_free_gb':free,'gpu_names':_gpu_names(),'nvidia':nvidia,'ffmpeg':bool(shutil.which('ffmpeg') and shutil.which('ffprobe')),'webview2':_webview2_installed(),'git':bool(shutil.which('git')),'python':__import__('sys').version.split()[0],'frozen':bool(getattr(__import__('sys'),'frozen',False)),'comfy_url':comfy_url,'comfy':_url_ok(comfy_url+'/system_stats'),'local_images':bool(vram>=12 and ram>=32 and free>=100),'local_video':bool(vram>=32 and ram>=64 and free>=100)}

def install_ffmpeg():
    if os.name!='nt': return {'ok':False,'error':'A instalação automática está disponível apenas no Windows.'}
    if not shutil.which('winget'): return {'ok':False,'error':'winget não está instalado. Instale FFmpeg e ffprobe manualmente em https://ffmpeg.org/download.html.'}
    try:
        r=subprocess.run(['winget','install','--id','Gyan.FFmpeg','-e','--accept-package-agreements','--accept-source-agreements'],capture_output=True,text=True,timeout=900,creationflags=0x08000000)
        _refresh_path()
        if shutil.which('ffmpeg') and shutil.which('ffprobe'): return {'ok':True,'message':'FFmpeg e ffprobe foram encontrados. Já pode gerar vídeos.'}
        detail=(r.stderr or r.stdout or '').strip()[-700:]
        return {'ok':False,'error':'A instalação terminou, mas o Windows ainda não atualizou o PATH. Feche e reabra o Histórias Studio.'+(('\n'+detail) if detail else '')}
    except Exception as exc: return {'ok':False,'error':f'Não foi possível instalar FFmpeg: {exc}'}

def _refresh_path():
    try:
        import winreg
        values=[]
        for hive,key in ((winreg.HKEY_CURRENT_USER,r'Environment'),(winreg.HKEY_LOCAL_MACHINE,r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment')):
            try:
                with winreg.OpenKey(hive,key) as handle: value,_=winreg.QueryValueEx(handle,'Path');values.extend(os.path.expandvars(value).split(os.pathsep))
            except OSError: pass
        links=Path(os.environ.get('LOCALAPPDATA',''))/'Microsoft'/'WinGet'/'Links'
        if links.is_dir():values.append(str(links))
        os.environ['PATH']=os.pathsep.join(x for x in dict.fromkeys([*os.environ.get('PATH','').split(os.pathsep),*values]) if x)
    except Exception:pass