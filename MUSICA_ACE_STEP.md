# Geração de música instrumental — ACE-Step

O workflow fornecido foi copiado para `workflow_music.json` e adaptado para instrumental, sem alterar o arquivo original em `D:\videos_animados`.

## Onde usar

- **Configurações → Músicas → Criar trilha instrumental**.
- Na criação de uma série: **Música de Fundo → Criar com IA**. Depois de ouvir, clique em **Usar nesta série**.

Escolha Terror, Suspense, Mistério, Emocional ou Personalizado. Ajuste descrição, duração (10–180 segundos), andamento (30–200 BPM) e, opcionalmente, o número da variação. A duração real aparece ao concluir. Os arquivos gerados entram na biblioteca normal, com nome, etiquetas e parâmetros registrados em `data/music.json`.

A geração passa por uma fila com até quatro solicitações ativas. Ela compartilha a trava de GPU do fluxo narrativo, aguarda o ComfyUI ficar livre e libera os modelos de outros serviços antes de carregar o ACE-Step. Não depende de uma API de música externa. O checkpoint utilizado é `ace_step_1.5_turbo_aio.safetensors`, já disponível na instalação verificada.

O cancelamento remove uma solicitação pendente. Se ela já estiver em execução, aguarda essa etapa terminar e descarta o resultado, sem interromper outros trabalhos do ComfyUI. Solicitações interrompidas pelo reinício do servidor aparecem como erro e podem ser reenviadas. As músicas concluídas permanecem na biblioteca.

## Arquivos

- `music_generation.py`: validação, fila, integração ComfyUI, persistência e rotas HTTP.
- `static/music-generation.js`: formulário, andamento, reprodução e seleção da trilha.
- `workflow_music.json`: cópia instrumental do workflow ACE-Step fornecido.
- `pipeline.py`: carregamento da integração e leitura de saídas de áudio do ComfyUI.
- `narrative.py`: compartilhamento da trava de GPU e liberação dos modelos.
- `static/index.html`: acesso pelo assistente de séries e pela biblioteca.

Cópias dos arquivos anteriores alterados estão em `backup_music`.

## Validação

```powershell
python tests/test_music_generation.py
node tests/test_music_ui.js
```

Sete testes de backend passaram, cobrindo controles, modelo/nós ausentes, recusa do ComfyUI, ausência de MP3, cancelamento enquanto aguarda GPU, persistência e integração da biblioteca. Os testes de interface verificam os estados da geração, presets, seleção da série e exibição segura de textos. As verificações anteriores do fluxo narrativo também passaram.

Teste real: instrumental de terror gerado em MP3 com **20 segundos**, salvo na biblioteca como **Terror instrumental - demonstração ACE-Step**. O áudio também foi usado na montagem real de um vídeo de **18,16 segundos**, com narração, legendas e redução automática da trilha durante a fala. As rotas HTTP, inclusive reprodução por intervalos de bytes, foram verificadas.

**Reinicie o servidor e atualize a página com Ctrl+F5 para ativar a integração.**
