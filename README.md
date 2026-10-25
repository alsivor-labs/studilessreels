# Histórias Studio

Aplicação local para planejar séries de histórias, gerar narração e criar vídeos verticais com imagens, movimento, legendas e trilha sonora. A interface roda no navegador; os serviços de IA e os arquivos de trabalho ficam no seu computador ou nas contas de API que você configurar.

> Projeto em desenvolvimento. Consulte [Instalação e uso](docs/INSTALACAO_E_USO.md) antes de começar. Os resultados e o tempo de geração dependem dos modelos, serviços, hardware e configurações escolhidos.

## O que faz

- Cria séries e roteiros em episódios, com verificação/correção automática; revisar o roteiro manualmente é opcional.
- Gera narração por serviço local ou provedor compatível.
- Cria imagens e, opcionalmente, clipes de movimento com workflows do ComfyUI.
- Monta vídeos verticais com legendas, música e efeitos usando FFmpeg.
- Guarda séries, configurações, trabalhos e exportações no computador.
- Pode agendar a produção diária enquanto o computador e o servidor estiverem ligados.

Depois que você inicia a série, o estúdio gera e revisa o roteiro e continua automaticamente para narração, imagens e montagem. Não é preciso aprovar cada roteiro; a revisão manual fica disponível como opção.

A publicação automática em redes sociais não está implementada. As integrações e os limites conhecidos estão descritos no guia.

## Requisitos resumidos

- Windows 10/11 de 64 bits é o ambiente documentado pelos atalhos incluídos.
- Python 3.10 ou superior e FFmpeg com `ffprobe`.
- Navegador atualizado, como Edge ou Chrome.
- Para geração local de IA: ComfyUI e/ou Ollama e VoiceStudio, conforme os provedores usados.
- Uma GPU NVIDIA com CUDA é recomendada para geração local no ComfyUI. Para o fluxo completo com LTX-2, considere 32 GB de VRAM, 64 GB de RAM e ao menos 100 GB livres para modelos e arquivos. Esse perfil é uma recomendação para ter margem, não uma garantia de desempenho ou compatibilidade.
- Se usar provedores de IA na nuvem, o PC não precisa executar esses modelos localmente; é preciso internet e contas/chaves dos serviços escolhidos.

Veja as configurações mínimas, recomendadas e os requisitos por provedor em [Instalação e uso](docs/INSTALACAO_E_USO.md).

## Início rápido no Windows

1. Instale Git, Python 3.10+ e FFmpeg. Instale e prepare os serviços que pretende usar; o script do projeto verifica, mas não instala ComfyUI, Ollama nem VoiceStudio.
2. Clone o repositório e abra a pasta do projeto no PowerShell:

   ```powershell
   git clone <URL-DO-REPOSITORIO> historias-studio
   cd historias-studio
   ```

3. Execute a verificação do ambiente:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\instalar_windows.ps1
   ```

4. Inicie o estúdio:

   ```powershell
   .\iniciar_windows.bat
   ```

   Ou use `python server.py` no terminal.
5. Abra [http://localhost:8787](http://localhost:8787).

Siga o guia completo para baixar modelos, instalar nós ausentes do ComfyUI, selecionar provedores, gerar o primeiro vídeo e resolver problemas comuns.

## Segurança e dados locais

- Configurações e chaves de API ficam em `data/settings.json` no seu computador. Não publique nem envie esse arquivo.
- Séries, histórico, mídia, exportações e backups locais não fazem parte do código-fonte. O `.gitignore` exclui essas pastas e arquivos para reduzir o risco de publicar dados pessoais, credenciais ou conteúdo protegido.
- Antes de enviar mudanças ao Git, revise `git status` e confirme que nenhum arquivo pessoal ou chave está na lista.
- Por padrão o servidor escuta em `0.0.0.0:8787`, o que pode expô-lo a outros dispositivos na rede local. Use em uma rede confiável; não encaminhe a porta para a internet nem exponha o serviço publicamente sem adicionar autenticação e controles de segurança.
- Chaves de API podem gerar custos conforme os termos e preços do provedor. Confira sua conta antes de ativar geração na nuvem.

## Estrutura

- `server.py`, `pipeline.py`, `narrative.py`, `score.py`, `music_generation.py`: servidor e fluxos de geração.
- `static/`: interface web.
- `workflow.json`, `workflow_video.json`, `workflow_music.json`: workflows usados no ComfyUI.
- `instalar_windows.ps1`, `iniciar_windows.bat`: verificação e inicialização no Windows.
- `docs/INSTALACAO_E_USO.md`: configuração detalhada, requisitos, operação e solução de problemas.

## Contribuições e licença

Contribuições podem ser propostas por issues e pull requests depois que o repositório remoto for publicado. A licença do projeto precisa ser escolhida pelo mantenedor antes da publicação: tornar o código público no Git, por si só, não concede uma licença de uso, modificação ou redistribuição. Os pesos dos modelos e os serviços de terceiros têm licenças e termos próprios; eles não são distribuídos por este repositório.
