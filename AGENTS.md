# Regras do Projeto Extrator de Questoes Pomaroli

## Plugin WordPress (wordpress-plugin/extrator-questoes-wp/)

- **OBRIGATORIO**: Sempre que alterar `extrator-questoes-wp.php` ou `index.html` do plugin, ATUALIZAR o campo `Version:` no header do PHP (Plugin Name header). Incrementar a versao (ex: 3.0.3 -> 3.0.4).
- **OBRIGATORIO**: Sempre que gerar ou atualizar o pacote `extrator-questoes-wp.zip`, COPIAR o arquivo `.zip` para a Área de Trabalho do Usuário (Desktop).
- Manter `render.yaml` e `app.py` sincronizados. O Render faz deploy automatico via GitHub.

## Deploy

- Push no GitHub = auto-deploy no Render (branch main).
- Plugin WordPress: usuario atualiza os arquivos manualmente no servidor WordPress.
- Sempre fazer commit + push apos cada alteracao relevante.

## Arquivos importantes

- `app.py` - Backend Flask (deployed no Render)
- `extrator.py` - Logica de extracao de texto e parsing de questoes
- `qualidade.py` - Validacao de qualidade das questoes
- `render.yaml` - Configuracao do Render
- `wordpress-plugin/` - Plugin WordPress (frontend + backend WP)
