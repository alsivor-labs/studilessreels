# Trilha sonora automática (por vídeo, a partir do roteiro)

Na criação da série, etapa **Música de Fundo**, escolha **Trilha criada pela IA** (padrão em séries novas).

Para cada vídeo, depois da narração:
1. A IA de roteiro (Ollama, OpenAI, Gemini... a mesma configurada em Provedores de IA) lê o plano da história, o resumo e a emoção de cada cena e escreve a *direção musical*: estilo, instrumentos, clima, arco emocional (começo, crescimento, final), andamento (BPM) e tonalidade.
2. O ACE-Step (`workflow_music.json`, pelo ComfyUI) compõe uma música instrumental com a **duração exata do vídeo** (+1,5 s), sem vocais e sem melodia que dispute com a voz.
3. A montagem coloca a trilha sob a narração, com a redução automática de volume durante a fala.

- A trilha fica em `videos/<id>/score.mp3` e a direção musical em `data/videos.json` (campo `script.score`). Ao refazer o vídeo, a trilha é reaproveitada.
- Se a composição falhar, o vídeo usa uma **música reserva** escolhida na biblioteca (opcional) ou sai sem música, com um aviso na tela do vídeo.
- Se a IA de roteiro não responder, a direção musical usa um padrão pelo gênero da história.
- A geração respeita a trava de GPU e libera Ollama/voz/ComfyUI antes de carregar o ACE-Step.
- Séries antigas continuam usando a biblioteca.

Arquivos: `score.py` (novo), `pipeline.py` (etapa "Compondo trilha" antes da montagem), `static/index.html` (escolha na etapa 3, etapa "Trilha" na tela de geração). Cópias anteriores em `backup_score/`.

Também corrigido: a aba "Criar com IA" aparecia por engano na etapa do nicho; agora está na etapa de música.

Teste: `python tests/test_score.py`
