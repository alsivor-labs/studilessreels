"""Windows desktop launcher: diagnose the PC, guide setup, and open the local studio."""
import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from runtime_paths import data_home

APP_URL = 'http://127.0.0.1:8787'
COMFY_MODELS = 'https://huggingface.co/Comfy-Org/Z-Image-Turbo'
COMFY_VIDEO = 'https://huggingface.co/Comfy-Org/ltx-2'
COMFY_MUSIC = 'https://huggingface.co/Comfy-Org/ace_step_1.5_ComfyUI_files'
COMFY_INSTALL = 'https://docs.comfy.org/installation/desktop/windows'
COMFY_MANAGER = 'https://docs.comfy.org/manager/install'


def _url_ok(url, timeout=1.5):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'HistoriasStudio/1.0'})
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except Exception:
        return False


def _windows_gpu_names():
    if os.name != 'nt':
        return []
    command = "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name | ConvertTo-Json -Compress"
    try:
        result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', command],
                                capture_output=True, text=True, timeout=5, creationflags=0x08000000)
        value = json.loads(result.stdout.strip() or '[]') if result.returncode == 0 else []
        return [value] if isinstance(value, str) else [str(x) for x in value]
    except Exception:
        return []


def _nvidia_info():
    exe = shutil.which('nvidia-smi')
    if not exe:
        return None
    try:
        result = subprocess.run([exe, '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
                                capture_output=True, text=True, timeout=5,
                                creationflags=0x08000000 if os.name == 'nt' else 0)
        rows = []
        for line in result.stdout.splitlines():
            parts = [x.strip() for x in line.split(',')]
            if len(parts) >= 2:
                rows.append((parts[0], int(parts[1]) / 1024))
        return rows or None
    except Exception:
        return None


def _ram_gb():
    if os.name == 'nt':
        class MemoryStatus(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullTotalPhys / (1024 ** 3)
    return 0.0


def _probe_system():
    ram = _ram_gb()
    try:
        free_gb = shutil.disk_usage(data_home()).free / (1024 ** 3)
    except OSError:
        free_gb = 0
    gpu_names = _windows_gpu_names()
    nvidia = _nvidia_info()
    local_images = bool(nvidia and max(vram for _, vram in nvidia) >= 12 and ram >= 32 and free_gb >= 100)
    local_video = bool(nvidia and max(vram for _, vram in nvidia) >= 32 and ram >= 64 and free_gb >= 100)
    ffmpeg = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))
    comfy = _url_ok(os.environ.get('COMFY_URL', 'http://127.0.0.1:8188').rstrip('/') + '/system_stats')
    git = bool(shutil.which('git'))
    try:
        import platform
        windows = f'{platform.system()} {platform.release()} ({platform.machine()})'
    except Exception:
        windows = 'Windows'
    return {'windows': windows, 'ram': ram, 'disk': free_gb, 'gpu_names': gpu_names,
            'nvidia': nvidia, 'local_images': local_images, 'local_video': local_video,
            'ffmpeg': ffmpeg, 'comfy': comfy, 'git': git, 'cores': os.cpu_count() or 0}


def _refresh_windows_path():
    if os.name != 'nt':
        return
    try:
        import winreg
        values = []
        for hive, key in ((winreg.HKEY_CURRENT_USER, r'Environment'),
                          (winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment')):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    value, kind = winreg.QueryValueEx(handle, 'Path')
                    values.extend(os.path.expandvars(value).split(os.pathsep))
            except OSError:
                pass
        links = Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WinGet' / 'Links'
        if links.is_dir():
            values.append(str(links))
        merged = os.pathsep.join(x for x in dict.fromkeys([*os.environ.get('PATH', '').split(os.pathsep), *values]) if x)
        os.environ['PATH'] = merged
    except Exception:
        pass


class Launcher:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('Histórias Studio · Preparação do computador')
        self.root.geometry('800x740')
        self.root.minsize(700, 620)
        self.root.configure(bg='#f4f5f8')
        self.server = None
        self.server_log = None
        self.report = None
        self._style()
        self._build()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.scan()
        self.root.mainloop()

    def _style(self):
        style = ttk.Style()
        try: style.theme_use('clam')
        except tk.TclError: pass
        style.configure('TFrame', background='#f4f5f8')
        style.configure('TLabel', background='#f4f5f8', foreground='#202432', font=('Segoe UI', 10))
        style.configure('Title.TLabel', font=('Segoe UI', 22, 'bold'), foreground='#111827')
        style.configure('Hint.TLabel', foreground='#5e6472', font=('Segoe UI', 10))
        style.configure('TButton', font=('Segoe UI', 10), padding=(12, 8))
        style.configure('Accent.TButton', font=('Segoe UI', 11, 'bold'), padding=(15, 10))

    def _build(self):
        outer = ttk.Frame(self.root, padding=22); outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Histórias Studio', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Verifique este computador e escolha como gerar imagens e vídeos.', style='Hint.TLabel').pack(anchor='w', pady=(3, 14))
        self.status = ttk.Label(outer, text='Verificando o computador…', style='Hint.TLabel'); self.status.pack(anchor='w', pady=(0, 8))
        self.output = scrolledtext.ScrolledText(outer, height=22, wrap='word', font=('Segoe UI', 10),
                                                 bg='white', fg='#202432', relief='flat', padx=14, pady=12)
        self.output.pack(fill='both', expand=True)
        self.output.configure(state='disabled')
        actions = ttk.Frame(outer); actions.pack(fill='x', pady=(12, 0))
        self.scan_btn = ttk.Button(actions, text='Diagnosticar novamente', command=self.scan); self.scan_btn.pack(side='left')
        self.ffmpeg_btn = ttk.Button(actions, text='Instalar FFmpeg', command=self.install_ffmpeg); self.ffmpeg_btn.pack(side='left', padx=8)
        ttk.Button(actions, text='Guia ComfyUI e modelos', command=self.show_guide).pack(side='left')
        self.start_btn = ttk.Button(actions, text='Abrir Histórias Studio', style='Accent.TButton', command=self.start_app); self.start_btn.pack(side='right')
        ttk.Label(outer, text='Python já vem incluído neste executável. Git só é necessário para baixar o código-fonte; provedores de nuvem dispensam ComfyUI e modelos locais.', style='Hint.TLabel', wraplength=740).pack(anchor='w', pady=(12, 0))

    def _show(self, text):
        self.output.configure(state='normal'); self.output.delete('1.0', 'end'); self.output.insert('1.0', text); self.output.configure(state='disabled')

    def scan(self):
        self.status.configure(text='Lendo memória, GPU, espaço livre e serviços locais…')
        self.scan_btn.configure(state='disabled'); self.start_btn.configure(state='disabled')
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self):
        try: report = _probe_system()
        except Exception as exc: report = {'error': str(exc)}
        self.root.after(0, lambda: self._render(report))

    def _render(self, r):
        self.report = r; self.scan_btn.configure(state='normal'); self.start_btn.configure(state='normal')
        if r.get('error'):
            self.status.configure(text='O diagnóstico teve uma falha; você ainda pode abrir o aplicativo.')
            self._show('Não foi possível ler todos os dados deste computador.\n\nDetalhe: ' + r['error'] + '\n\nO estúdio ainda pode ser aberto e usado com provedores de IA na nuvem.')
            return
        gpu = ', '.join(r['gpu_names']) if r['gpu_names'] else 'não identificada'
        if r['nvidia']:
            gpu += ' · ' + ', '.join(f'{name}, {vram:.0f} GB VRAM' for name, vram in r['nvidia'])
        lines = [f"SISTEMA  {r['windows']} · {r['cores']} núcleos",
                 f"MEMÓRIA  {r['ram']:.0f} GB RAM",
                 f"GRÁFICOS  {gpu}",
                 f"ARMAZENAMENTO  {r['disk']:.0f} GB livres na unidade de dados",
                 f"FFmpeg/ffprobe  {'Encontrados' if r['ffmpeg'] else 'Não encontrados — necessários para exportar vídeos'}",
                 f"Git  {'Encontrado' if r['git'] else 'Não encontrado — opcional para quem baixa o executável'}",
                 f"ComfyUI  {'Respondendo em localhost:8188' if r['comfy'] else 'Não está aberto neste computador'}",
                 'Python  Incluído no executável; não precisa instalar.']
        if r['local_video']:
            lines += ['', 'RECOMENDAÇÃO  O computador atende ao perfil recomendado para experimentar geração local de vídeo com o workflow LTX-2: GPU NVIDIA com pelo menos 32 GB de VRAM, 64 GB de RAM e 100 GB livres. O desempenho depende do modelo e do driver.']
        elif r['local_images']:
            lines += ['', 'RECOMENDAÇÃO  O computador parece adequado para experimentar imagens locais no ComfyUI. Para o movimento LTX-2, a recomendação é uma GPU NVIDIA de 32 GB VRAM, 64 GB RAM e 100 GB livres. Para vídeo, prefira um provedor de nuvem neste PC.']
        else:
            lines += ['', 'RECOMENDAÇÃO  Este computador não atende ao perfil recomendado para os workflows locais pesados do ComfyUI/LTX-2. Use provedores de nuvem para roteiro, voz, imagens e movimento; o computador ainda monta e exporta o vídeo com FFmpeg.']
        if not r['ffmpeg']:
            lines += ['', 'PRÓXIMO PASSO  Clique em “Instalar FFmpeg” para instalar pelo winget, ou instale manualmente pelo guia.']
        if not r['comfy'] and (r['local_images'] or r['local_video']):
            lines += ['', 'Para geração local, instale e abra o ComfyUI, baixe os modelos do guia e carregue os workflows. A primeira configuração pode ocupar dezenas de GB.']
        else:
            lines += ['', 'A orientação detalhada dos modelos e pastas do ComfyUI está no botão “Guia ComfyUI e modelos”. Os workflows do projeto são incluídos no executável.']
        self._show('\n'.join(lines))
        self.status.configure(text='Diagnóstico concluído · escolha a opção local ou na nuvem dentro de Configurações › Provedores de IA.')
        self.ffmpeg_btn.configure(state='disabled' if r['ffmpeg'] else 'normal')

    def install_ffmpeg(self):
        if not shutil.which('winget'):
            messagebox.showinfo('Instalação manual', 'O winget não está disponível. Abra https://ffmpeg.org/download.html, instale FFmpeg e ffprobe e reinicie o Histórias Studio.')
            webbrowser.open('https://ffmpeg.org/download.html'); return
        if not messagebox.askyesno('Instalar FFmpeg', 'O winget vai baixar e instalar FFmpeg neste computador. Deseja continuar?'):
            return
        self.ffmpeg_btn.configure(state='disabled'); self.status.configure(text='Instalando FFmpeg pelo winget…')
        threading.Thread(target=self._install_worker, daemon=True).start()

    def _install_worker(self):
        try:
            result = subprocess.run(['winget', 'install', '--id', 'Gyan.FFmpeg', '-e', '--accept-package-agreements', '--accept-source-agreements'],
                                    capture_output=True, text=True, timeout=900,
                                    creationflags=0x08000000 if os.name == 'nt' else 0)
            _refresh_windows_path()
            found = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))
            message = ('FFmpeg instalado e encontrado.' if found else
                       'A instalação terminou. Se o FFmpeg não aparecer após a atualização do PATH, feche e abra novamente o Histórias Studio.')
            if result.returncode and not found:
                message += '\n\n' + (result.stderr or result.stdout or f'winget retornou código {result.returncode}')[-900:]
            self.root.after(0, lambda: self._install_done(message, found))
        except Exception as exc:
            self.root.after(0, lambda: self._install_done(f'Não foi possível instalar automaticamente: {exc}', False))

    def _install_done(self, message, found):
        self.status.configure(text=message)
        if self.report is not None:
            self.report['ffmpeg'] = found
            self._render(self.report)
        if not found:
            messagebox.showinfo('FFmpeg', message)

    def show_guide(self):
        win = tk.Toplevel(self.root); win.title('Guia ComfyUI · Histórias Studio'); win.geometry('730x650'); win.configure(bg='#f4f5f8')
        frame = ttk.Frame(win, padding=20); frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Configurar geração local', style='Title.TLabel').pack(anchor='w')
        body = scrolledtext.ScrolledText(frame, wrap='word', font=('Segoe UI', 10), bg='white', relief='flat', padx=14, pady=12)
        body.pack(fill='both', expand=True, pady=12)
        guide = '''1. Instale o ComfyUI Desktop para Windows e abra-o. O Histórias Studio espera o endereço local http://127.0.0.1:8188.\n\n2. Baixe os modelos compatíveis com os workflows incluídos. No ComfyUI, confira os nomes e pastas:\n\nIMAGENS — Z-Image Turbo\n• z_image_turbo_bf16.safetensors → models/diffusion_models/\n• qwen_3_4b.safetensors → models/text_encoders/\n• ae.safetensors → models/vae/\n\nMOVIMENTO — LTX-2 (workflow pesado; recomendamos GPU NVIDIA 32 GB VRAM, 64 GB RAM e 100 GB livres)\n• ltx-2-19b-dev-fp8.safetensors → models/checkpoints/\n• gemma_3_12B_it_fp4_mixed.safetensors → models/text_encoders/\n• ltx-2-19b-distilled-lora-384.safetensors → models/loras/\n• ltx-2-spatial-upscaler-x2-1.0.safetensors → models/upscale_models/\n\nMÚSICA — ACE-Step\n• ace_step_1.5_turbo_aio.safetensors → models/checkpoints/\n\n3. Atualize para uma versão recente do ComfyUI. Os workflows deste projeto usam nós nativos e não exigem extensões adicionais quando a instalação está atualizada. Se o ComfyUI mostrar “nó ausente”, instale/atualize o ComfyUI Manager, procure o nó indicado em Custom Nodes e reinicie o ComfyUI.\n\n4. Volte ao Histórias Studio, execute novamente o diagnóstico e selecione ComfyUI para imagem ou movimento em Configurações › Provedores de IA. Para texto local, configure Ollama separadamente.\n\nOs pesos são grandes e têm licenças próprias. Confira origem, espaço e licença antes de baixar. Se o hardware não atender, escolha provedores na nuvem nas configurações: fal.ai, Replicate, Kie AI, OpenAI, Google Gemini e ElevenLabs, conforme a etapa. A nuvem requer conta, conexão e chave; podem existir cobranças.\n\nSem FFmpeg e ffprobe, o aplicativo não consegue montar o MP4 final. Instale-os pelo botão de diagnóstico ou pelo site oficial.'''
        body.insert('1.0', guide); body.configure(state='disabled')
        links = ttk.Frame(frame); links.pack(fill='x')
        for label, url in (('Baixar ComfyUI', COMFY_INSTALL), ('Modelos de imagem', COMFY_MODELS), ('Modelos de vídeo', COMFY_VIDEO), ('Modelos de música', COMFY_MUSIC), ('ComfyUI Manager', COMFY_MANAGER)):
            ttk.Button(links, text=label, command=lambda u=url: webbrowser.open(u)).pack(side='left', padx=(0, 5))

    def start_app(self):
        if _url_ok(APP_URL, timeout=.4):
            webbrowser.open(APP_URL); self.status.configure(text='O estúdio já estava aberto no navegador.'); return
        if self.server and self.server.poll() is None:
            webbrowser.open(APP_URL); return
        if self.report is not None and not self.report.get('ffmpeg'):
            if not messagebox.askyesno('FFmpeg ainda não encontrado', 'O estúdio pode abrir, mas não poderá exportar o vídeo final sem FFmpeg e ffprobe. Abrir mesmo assim?'):
                return
        try:
            logdir = data_home() / 'logs'; logdir.mkdir(parents=True, exist_ok=True)
            self.server_log = open(logdir / 'server.log', 'a', encoding='utf-8')
            flags = 0x08000000 if os.name == 'nt' else 0
            self.server = subprocess.Popen([sys.executable, '--server'], cwd=str(data_home()),
                                            stdin=subprocess.DEVNULL, stdout=self.server_log,
                                            stderr=subprocess.STDOUT, creationflags=flags)
            self.status.configure(text='Iniciando o servidor local…')
            self.start_btn.configure(state='disabled')
            threading.Thread(target=self._wait_server, daemon=True).start()
        except Exception as exc:
            messagebox.showerror('Não foi possível abrir', str(exc)); self.start_btn.configure(state='normal')

    def _wait_server(self):
        for _ in range(60):
            if _url_ok(APP_URL, timeout=.5):
                self.root.after(0, self._server_ready); return
            if self.server and self.server.poll() is not None:
                break
            time.sleep(.5)
        self.root.after(0, self._server_failed)

    def _server_ready(self):
        self.status.configure(text='Histórias Studio está aberto no navegador. Deixe esta janela aberta enquanto estiver usando.'); self.start_btn.configure(state='normal', text='Abrir novamente'); webbrowser.open(APP_URL)

    def _server_failed(self):
        self.start_btn.configure(state='normal', text='Abrir Histórias Studio')
        try:
            path = data_home() / 'logs' / 'server.log'
            detail = path.read_text(encoding='utf-8', errors='replace')[-1800:]
        except Exception:
            detail = 'Consulte os requisitos e tente novamente.'
        self.status.configure(text='O servidor local não iniciou.')
        messagebox.showerror('Erro ao iniciar', 'Não foi possível iniciar o servidor. Verifique se a porta 8787 está livre e se o arquivo de log apresenta algum erro.\n\n' + detail)

    def close(self):
        if self.server and self.server.poll() is None:
            try: self.server.terminate(); self.server.wait(timeout=5)
            except Exception:
                try: self.server.kill()
                except Exception: pass
        try:
            if self.server_log: self.server_log.close()
        except Exception: pass
        self.root.destroy()


if __name__ == '__main__':
    if '--server' in sys.argv:
        from server import serve_forever
        serve_forever()
    else:
        Launcher()