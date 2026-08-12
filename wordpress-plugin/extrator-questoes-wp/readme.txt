=== Extrator de Questões AI (Lotes & Nuvem) ===
Contributors: antigravity
Tags: questoes, concursos, pdf, gemini, ia, lotes, importador
Requires at least: 5.8
Tested up to: 6.6
Stable tag: 2.0.0
License: GPLv2 or later

Plugin WordPress para extração automatizada de questões de concursos de múltiplos arquivos PDF simultaneamente, utilizando o motor determinístico Python em nuvem e a API do Google Gemini (IA Grátis).

== Descrição ==

O Extrator de Questões AI permite enviar até 10+ arquivos PDF de provas de uma única vez. O servidor processa os arquivos em segundo plano em uma fila assíncrona, liberando o navegador do usuário.

Recursos principais:
- **Upload em Lote**: Arraste 10+ arquivos PDF de provas de concursos de uma só vez.
- **Processamento sem Travar o PC**: O backend Python aceita a fila e você pode fechar o computador.
- **Autocorreção via Google Gemini (IA Grátis)**: Limpeza de erros de OCR, pontuação e falta de espaços em questões com alertas de qualidade.
- **Importador Nascido para o WordPress**: Grava cada questão automaticamente como Custom Post Type 'questao' com todos os meta fields (opções A a E, gabarito, banca, ano, disciplina e comentários).

== Instalação ==

1. Faça o upload da pasta `extrator-questoes-wp` para o diretório `/wp-content/plugins/`.
2. Ative o plugin no menu 'Plugins' do WordPress.
3. Acesse o menu 'Extrator de Questões' no painel admin do WordPress.
4. Insira a URL do seu servidor Python (ex: `http://127.0.0.1:5000` ou a URL do seu servidor na nuvem) e a sua chave gratuita do Google Gemini AI.
5. Arraste as suas provas em PDF e clique em "Iniciar Processamento em Lote"!
