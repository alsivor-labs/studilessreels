# Fluxo narrativo e direção de voz

Reinicie o servidor pelo `iniciar_windows.bat` após atualizar os arquivos.

O fluxo de séries passa por planejamento, escrita do texto completo, storyboard, revisão e aprovação. O storyboard precisa preservar todas as palavras do texto narrável, em ordem. Abra o vídeo em **Revisão do roteiro** para editar cada trecho, revisar novamente, ouvir a voz e aprovar a produção. A revisão exige evidências citadas do texto narrado, e não apenas do planejamento. O histórico fica salvo junto ao roteiro em `data/videos.json`.

Há até três auditorias, com duas rodadas de correção. Respostas estruturadas inválidas têm até três tentativas. A aprovação de erros críticos exige uma opção explícita na interface.

Idioma e voz continuam na configuração da série. No painel de revisão, selecione o perfil automático ou um gênero, a velocidade manual e a intensidade das pausas. A narração é sintetizada por cena, com silêncios inseridos por FFmpeg, e a duração medida orienta os cortes. O modo automático pode ressintetizar cada trecho até duas vezes para aproximar o ritmo desejado; o ritmo efetivo e eventuais desvios aparecem no painel. A API instalada é consultada antes de enviar parâmetros opcionais.

As instruções de interpretação são enviadas fora do texto falado quando a API oferece esse campo. O efeito depende do motor e da voz; pausas são aplicadas na edição. Não há alteração global da velocidade do arquivo pronto pelo Histórias Studio.

A CTA é configurada na aprovação, em um segmento separado. Pode ser narrada ou apenas exibida como legenda, com texto, canal (`{channel}`) e intervalo personalizados. A história é auditada sem a CTA.

**Regenerar somente narração** preserva imagens e animações. A montagem é atualizada ao aprovar novamente. Editar e revisar o roteiro recalcula os prompts; os visuais anteriores são arquivados no diretório `revision_*` do vídeo para evitar reutilização de cenas incompatíveis.

O módulo `narrative.py` é carregado ao final de `pipeline.py`. As integrações existentes continuam responsáveis pela síntese, imagens, LTX-2 e montagem. As etapas locais deste fluxo são serializadas e liberam os modelos dos serviços entre as fases. Aplicações externas que utilizam a mesma GPU continuam independentes.

Teste automatizado (Python e FFmpeg no PATH):

```powershell
python tests/test_narrative.py
node tests/test_narrative_ui.js
```

Inclui correção com nova auditoria, rejeição após o limite, citações inventadas, JSON inválido, bloqueio antes da aprovação, exceção explícita, CTA e montagem real de áudio com FFmpeg. Provedores de IA são simulados nesse teste; a execução dos serviços locais é uma verificação de integração separada.
