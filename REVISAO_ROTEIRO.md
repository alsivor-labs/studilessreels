# Revisão do roteiro — tela nova e travas automáticas

Quando um vídeo fica em **Revisão do roteiro**, ele abre numa página própria (`#/revisar/<id>`), em vez do modal:
- **Roteiro:** cada cena com o texto exato que será narrado, contagem de palavras e tempo estimado, emoção, personagens e ambiente. Edite e use **Salvar e verificar de novo**. As edições não se perdem enquanto a página atualiza.
- **Verificação da história:** problemas críticos e avisos com o trecho e a correção sugerida, mais a lista de verificações traduzida (clique para ver a justificativa).
- **Narração:** ritmo, velocidade manual, pausas, amostra da voz e a opção de gravar a narração completa antes de aprovar.
- **Chamada final:** liga/desliga, nome do canal, texto, narrada ou só escrita, pausa.
- **Aprovar e produzir:** se houver problemas, é preciso marcar que entendeu antes de seguir.
- **Histórico das verificações** em texto legível.

## Travas automáticas (narrative.local_checks)
Rodam em toda verificação, junto com a revisão da IA, e entram no ciclo de correção automática:
1. **Poucas cenas para a duração** (crítico): pelo menos 1 cena a cada ~9 s (mín. 3).
2. **Cena longa demais** (aviso): mais de 40 palavras na mesma imagem.
3. **Idioma errado** (crítico): narração fora do idioma da série.
4. **"Siga/inscreva-se" dentro da história** (crítico): a chamada final é separada.
5. **Frase repetida** (aviso).
6. **Cena sem texto** (crítico).

Testes: `python tests/test_roteiro_checks.py` e `python tests/test_narrative.py` (o exemplo deste teste passou a ter 4 cenas, por causa da trava 1).
Cópias anteriores em `backup_revisao/`.
