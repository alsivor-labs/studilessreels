# Instalação e uso

Este guia descreve como preparar o Histórias Studio em uma máquina Windows, escolher provedores e gerar um primeiro vídeo. O programa fornece a interface e coordena serviços externos; ele não baixa nem instala os modelos de IA por conta própria.

## 1. Requisitos do computador

### Uso com provedores na nuvem

Para usar provedores de texto, voz e imagem hospedados na nuvem, sem executar esses modelos no computador:

- Windows 10 ou 11 de 64 bits.
- Processador moderno de 4 núcleos ou equivalente.
- 8 GB de RAM como mínimo prático; 16 GB recomendados para navegador, vídeo e serviços locais auxiliares.
- 10 GB livres para o programa e arquivos temporários, além do espaço necessário para os vídeos gerados.
- Conexão estável com a internet e contas/chaves dos provedores selecionados.
- FFmpeg instalado para montar e analisar áudio/vídeo.

A máquina ainda processa a montagem final e guarda os arquivos. Projetos e vídeos longos podem exigir bastante espaço adicional.

### Geração local de imagens, texto, voz e vídeo

- GPU NVIDIA com CUDA recomendada para ComfyUI.
- Para imagens locais, 12 GB de VRAM pode ser um ponto de partida, mas resolução, precisão, modelos ativos e versão do ComfyUI mudam o consumo; pode ser necessário reduzir a resolução ou usar serviços na nuvem.
- Para o workflow de vídeo incluído, que usa LTX-2 19B FP8, recomendamos 32 GB de VRAM. Com menos memória a geração pode falhar por falta de VRAM ou exigir configurações adicionais; não há garantia de que 12 GB seja suficiente.
- 32 GB de RAM como base para uma estação local; 64 GB recomendados para executar várias ferramentas e workflows pesados.
- SSD com pelo menos 100 GB livres para modelos e cache, além do espaço para trabalhos/exportações. A coleção completa de modelos pode crescer conforme os workflows e provedores usados.
- Para geração de texto local, Ollama requer espaço para baixar o modelo escolhido. O modelo sugerido automaticamente pelo projeto pode ser `qwen3:8b`; escolha um modelo que caiba na RAM/VRAM disponível.

Esses números são recomendações práticas, não requisitos certificados do aplicativo. O consumo muda com o modelo e as configurações. Se o computador não comportar um modelo, configure um provedor de nuvem para essa etapa.

## 2. Programas e serviços necessários

### Obrigatórios para iniciar o aplicativo

- **Python 3.10+**. O `instalar_windows.ps1` tenta instalar Python 3.12 via `winget` se não encontrar `python` nem `py`. Feche e reabra o terminal depois de instalar para atualizar o `PATH`.
- **FFmpeg e ffprobe**. O script tenta instalar FFmpeg por `winget`; se não houver `winget`, instale pelo site do FFmpeg e confirme que ambos os comandos funcionam no PowerShell:

  ```powershell
  python --version
  ffmpeg -version
  ffprobe -version
  ```

- **Git**, para clonar e atualizar o projeto.
- **Edge ou Chrome** atualizado.

O servidor usa apenas a biblioteca padrão do Python; não há `pip install` de dependências Python para o aplicativo atual.

### Serviços opcionais, conforme o provedor

| Etapa | Opção local | Alternativas |
|---|---|---|
| Roteiro | Ollama com um modelo instalado | OpenAI, Google Gemini ou endpoint compatível com OpenAI (por exemplo, serviços que ofereçam essa API) |
| Voz | VoiceStudio com um mecanismo TTS configurado | ElevenLabs ou outros provedores exibidos nas configurações |
| Imagens | ComfyUI com o workflow/modelos de imagem | OpenAI, Google Gemini ou provedor KIE disponível no aplicativo |
| Movimento de vídeo | ComfyUI com o workflow de LTX-2 | Pode ser desativado; geração de movimento por imagem e montagem continuam usando processamento local |
| Música gerada | ComfyUI com ACE-Step e workflow de música | Importar arquivos de música na biblioteca do estúdio |

As alternativas dependem das opções exibidas na versão em uso, de uma chave válida e da disponibilidade/termos do provedor. Serviços locais e seus modelos precisam ser instalados separadamente. O script de preparação apenas verifica se ComfyUI, Ollama e VoiceStudio respondem.

### Workflows e modelos do ComfyUI

Os workflows versionados neste repositório apontam para estes arquivos de modelo:

- **Imagem** (`workflow.json`): `z_image_turbo_bf16.safetensors`, `qwen_3_4b.safetensors` e `ae.safetensors`.
- **Movimento** (`workflow_video.json`): `ltx-2-19b-dev-fp8.safetensors`, `ltx-2-19b-distilled-lora-384.safetensors` e `ltx-2-spatial-upscaler-x2-1.0.safetensors`.
- **Música** (`workflow_music.json`): `ace_step_1.5_turbo_aio.safetensors`.

Baixe os modelos de fontes oficiais ou autorizadas e confira as licenças de cada modelo. Coloque cada arquivo na pasta de modelos indicada pelo respectivo workflow/ComfyUI. As revisões do ComfyUI podem alterar nós e formatos: atualize o ComfyUI, abra o workflow, use o ComfyUI Manager para instalar os nós ausentes (quando houver) e reinicie o ComfyUI. Confirme que cada workflow roda no próprio ComfyUI antes de gerar pelo estúdio.

Endereços locais padrão esperados:

- ComfyUI: `http://127.0.0.1:8188`
- Ollama: `http://127.0.0.1:11434`
- VoiceStudio: `http://127.0.0.1:3900`
- Histórias Studio: `http://localhost:8787`

## 3. Instalar o Histórias Studio

1. Instale Git e Python 3.10+ no Windows. Instale FFmpeg, ou permita que o script tente fazê-lo com `winget`.
2. Instale e prepare os serviços opcionais que usará. Para ComfyUI local, carregue os modelos listados acima e confirme os workflows. Para Ollama, baixe pelo menos um modelo; por exemplo:

   ```powershell
   ollama pull qwen3:8b
   ```

3. Clone o repositório (substitua o marcador pela URL publicada pelo mantenedor):

   ```powershell
   git clone <URL-DO-REPOSITORIO> historias-studio
   cd historias-studio
   ```

4. Rode a preparação:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\instalar_windows.ps1
   ```

   O script verifica Python, FFmpeg e os endereços padrão dos serviços locais. Ele não instala nem configura ComfyUI, Ollama ou VoiceStudio; o serviço pode aparecer como indisponível se ainda não estiver aberto.
5. Se `ffmpeg` ou `ffprobe` não forem reconhecidos após a instalação, feche e reabra o PowerShell. Rode o script de preparação novamente.

## 4. Iniciar e configurar

1. Abra ComfyUI, Ollama e VoiceStudio se for usá-los localmente.
2. Na pasta do projeto, inicie:

   ```powershell
   .\iniciar_windows.bat
   ```

   Alternativamente: `python server.py` ou `py server.py`.
3. Acesse [http://localhost:8787](http://localhost:8787).
4. Abra **Configurações** e escolha o provedor de cada etapa. Para serviços na nuvem, informe a chave e o modelo aceito pela sua conta e use **Salvar e testar**. As chaves são gravadas localmente em `data/settings.json`.
5. Se um serviço estiver em outro endereço, configure as variáveis antes de iniciar o servidor. Exemplo no PowerShell:

   ```powershell
   $env:COMFY_URL = 'http://127.0.0.1:8188'
   $env:OLLAMA_URL = 'http://127.0.0.1:11434'
   $env:VOICE_URL = 'http://127.0.0.1:3900'
   python server.py
   ```

   Ajuste apenas as URLs dos serviços usados. Essas variáveis valem para aquela janela do PowerShell. O servidor usa a porta `8787` por padrão; para alterá-la, defina `$env:PORT` antes de iniciar.

## 5. Criar um vídeo

1. Na página inicial, crie uma série pelo assistente: nicho, idioma/voz, música, estilo visual, legendas, movimento, resumo das opções e detalhes.
2. Crie a série ou escolha gerar um vídeo agora. O estúdio escreve e revisa o roteiro automaticamente, aplica correções automáticas e segue para narração, imagens, movimento e montagem sem esperar aprovação manual.
3. Acompanhe as etapas de produção. A primeira geração pode demorar enquanto os modelos carregam ou são baixados pelo serviço configurado. Se quiser, abra a revisão do roteiro para conferir ou editar; isso é opcional.
4. Assista/baixe o resultado em **Vídeos**. O vídeo e o arquivo de texto com título/descrição/hashtags são exportados em `exportados/<série>/`; arquivos intermediários ficam em `videos/`.
5. Para agendamento diário, mantenha o computador ligado e o `server.py` aberto. A agenda não funciona quando o servidor está fechado ou o computador suspenso.

A tela manual anterior fica em `/estudio.html`. Para gerar música, use a biblioteca/área de músicas e o workflow ACE-Step; também é possível enviar músicas próprias.

## 6. Arquivos, privacidade e custos

- `data/`: configurações, chaves, séries, estado e dados auxiliares.
- `videos/`: projetos e artefatos intermediários de cada vídeo.
- `exportados/`: vídeos finalizados e respectivos textos de publicação.
- `audio/`: narrações e amostras de áudio.
- `music/`: músicas importadas/geradas para a biblioteca.

Esses caminhos são criados pelo programa e permanecem no seu computador. O `.gitignore` os exclui do Git. Faça cópias de segurança próprias dos arquivos que queira preservar; não compartilhe `data/settings.json` nem inclua arquivos de terceiros sem permissão.

O uso de API pode ter custo por chamada, imagem, minuto de áudio ou vídeo. Verifique preço, limites, política de privacidade e termos comerciais do provedor. O projeto não controla a retenção nem o uso dos dados dos provedores externos.

O servidor atualmente escuta em `0.0.0.0:8787`. Isso pode permitir acesso a partir de outros dispositivos na rede local. Use somente em rede confiável; não exponha a porta à internet sem autenticação, proteção contra abuso e configuração segura.

## 7. Limitações atuais

- Publicação automática em TikTok, Instagram, YouTube ou outras redes não está implementada; o estúdio exporta o vídeo e o texto para publicação manual.
- O PC precisa ficar ligado e com o servidor em execução para produzir vídeos agendados.
- Resultados e consistência de personagens variam conforme roteiro, modelo, prompt e provedor.
- A checagem narrativa e as tentativas de correção são automáticas. Se a IA revisora não conseguir eliminar todos os avisos, a produção segue com a melhor versão disponível e os problemas registrados; por isso, conferir o roteiro é opcional, mas pode ser útil.
- A geração local de vídeo pode ser pesada e depende das versões/modelos/nós disponíveis no ComfyUI.
- As integrações externas podem mudar suas APIs, limites, modelos ou preços.

## 8. Problemas comuns

- **ComfyUI indisponível:** abra o ComfyUI, confirme o endereço e defina `COMFY_URL` se a porta for diferente.
- **Ollama sem modelos:** rode `ollama list`; se necessário, baixe um modelo compatível e escolha-o em Configurações.
- **VoiceStudio indisponível:** abra o aplicativo, confirme se seu serviço responde em `/health` e revise `VOICE_URL`; ou selecione outro provedor de voz.
- **Workflow recusado ou modelo/nó ausente:** abra o workflow diretamente no ComfyUI, instale/atualize os nós faltantes pelo Manager, confira nomes e pastas dos modelos e reinicie o ComfyUI.
- **`ffmpeg`/`ffprobe` não encontrados:** instale FFmpeg, confirme que os binários estão no `PATH` e reabra o terminal.
- **Porta 8787 ocupada:** encerre o servidor anterior ou inicie com `$env:PORT = '8788'` e acesse `http://localhost:8788`.
- **Chave de API inválida:** salve novamente em Configurações e use **Salvar e testar**; consulte os limites e permissões da conta do provedor.
- **Pouca memória de vídeo:** reduza resolução/quadros, desative movimento por IA ou use geração de imagem/vídeo na nuvem.

## 9. Uso como projeto Git público

Antes de publicar o repositório, o mantenedor deve:

1. Escolher e adicionar uma licença de código. Repositório público sem licença não concede automaticamente direitos de uso, modificação ou redistribuição.
2. Revisar a lista de arquivos que entrarão no Git e confirmar que `data/`, mídias, exportações, backups e chaves ficaram de fora.
3. Verificar separadamente a licença dos workflows, modelos, vozes, músicas, fontes e demais recursos externos.
4. Substituir `<URL-DO-REPOSITORIO>` neste guia pela URL real após a criação do remoto.
5. Informar suporte/bugs por Issues e aceitar contribuições por Pull Requests, se desejar.

### Referências oficiais para configurar ComfyUI e LTX-2

- [Workflows LTX-2 no ComfyUI](https://docs.comfy.org/tutorials/video/ltx/ltx-2) e [galeria de workflows/templates](https://docs.comfy.org/interface/features/template): consulte modelos e passos da versão atual do ComfyUI.
- [Requisitos do LTX Desktop](https://github.com/Lightricks/LTX-Desktop/blob/main/README.md): referência oficial de hardware do aplicativo do fabricante. O workflow ComfyUI deste projeto é uma integração diferente; seus resultados dependem da versão, da quantização e da configuração dos nós.
