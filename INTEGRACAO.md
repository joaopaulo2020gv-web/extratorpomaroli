# INTEGRACAO — Extrator de Questoes Pomaroli v3.3

## Visao Geral

O sistema e composto por dois componentes que comunicam via REST API HMAC:

1. **WordPress Plugin** (`extrator-pomaroli-FINAL.zip`) — Gerencia uploads, jobs, questions e dashboard
2. **Python Worker** (`pomaroli-python-worker-FINAL.zip`) — Processa PDFs via cPanel Cron

---

## Configuracao

### WordPress Plugin

1. Instale o plugin `extrator-pomaroli-FINAL.zip` no WordPress
2. Ative o plugin — o secret HMAC e gerado automaticamente
3. Va em **Extrator Pomaroli > Configuracoes** para ver o secret

### Python Worker

1. Extraia `pomaroli-python-worker-FINAL.zip` no cPanel
2. Configure as variaveis de ambiente ou crie `config.json`

#### Variavel de Ambiente

| Variavel | Descricao | Exemplo |
|----------|-----------|---------|
| `WP_SITE_URL` | URL do WordPress | `https://seusite.com.br` |
| `POMAROLI_WORKER_SECRET` | Secret HMAC (mesmo do WordPress) | `abc123...` |
| `GEMINI_API_KEY` | Chave API Gemini (opcional) | `AIzaSy...` |
| `BLOCK_SIZE` | Paginas por bloco (padrao: 20) | `20` |

#### config.json (alternativa)

```json
{
    "wordpress_url": "https://seusite.com.br",
    "worker_secret": "abc123...",
    "gemini_api_key": "AIzaSy...",
    "block_size": 20
}
```

### cPanel Cron

Adicione um Cron Job que executa a cada 5 minutos:

```
*/5 * * * * cd /home/usuario/extractor && /bin/bash run.sh >> /dev/null 2>&1
```

Ou execute diretamente:

```
*/5 * * * * cd /home/usuario/extractor && python3 worker.py >> /dev/null 2>&1
```

---

## Contrato de API

### Endpoints HMAC (Worker → WordPress)

| Metodo | Endpoint | Descricao |
|--------|----------|-----------|
| `GET` | `/wp-json/pomaroli/v1/worker/next-job` | Proximo job na fila |
| `POST` | `/wp-json/pomaroli/v1/worker/claim-job` | Marca job como processing |
| `GET` | `/wp-json/pomaroli/v1/worker/files/{id}` | Lista arquivos do job |
| `POST` | `/wp-json/pomaroli/v1/worker/update` | Atualiza progresso |
| `POST` | `/wp-json/pomaroli/v1/worker/questions` | Salva questoes extraidas |
| `POST` | `/wp-json/pomaroli/v1/worker/complete` | Finaliza job |

### Headers de Autenticacao

```
X-Pomaroli-Hmac: {hex_digest}
X-Pomaroli-Timestamp: {unix_timestamp}
Content-Type: application/json
```

### Algoritmo HMAC

```
message = "{timestamp}.{body}"
signature = HMAC-SHA256(message, secret)
```

- `timestamp`: Unix epoch em segundos (string)
- `body`: JSON body do request (string vazia para GET)
- `secret`: O valor de `pomaroli_worker_secret` do WordPress

---

## Status dos Jobs

### Job Status

| Valor | Descricao |
|-------|-----------|
| `queued` | Aguardando processamento |
| `processing` | Sendo processado pelo worker |
| `completed` | Finalizado com sucesso |
| `failed` | Erro no processamento |
| `cancelled` | Cancelado pelo usuario |

### File Status

| Valor | Descricao |
|-------|-----------|
| `pending` | Aguardando processamento |
| `queued` | Na fila |
| `processing` | Sendo processado |
| `completed` | Processado com sucesso |
| `failed` | Erro no processamento |
| `cancelled` | Cancelado |

---

## Fluxo de Processamento

```
USUARIO
  ↓
WORDPRESS: Upload PDF
  ↓
WORDPRESS: Job = queued
  ↓
PYTHON WORKER (Cron a cada 5min):
  1. Verifica lock
  2. GET /worker/next-job → busca job queued
  3. POST /worker/claim-job → marca como processing
  4. GET /worker/files/{id} → lista arquivos
  5. Seleciona proximo arquivo pending/processing
  6. Processa UM BLOCO (20 paginas)
  7. POST /worker/questions → salva questoes
  8. POST /worker/update → atualiza progresso
  9. Se arquivo concluido → file_status = completed
 10. Se todos arquivos concluidos → POST /worker/complete
 11. Libera lock
 12. Encerra
  ↓
PROXIMO CRON: repete processo
```

---

## Testes de Compatibilidade

### Teste 1: WordPress cria job
- WordPress cria job com `status = 'queued'`
- Python encontra via `GET /worker/next-job`

### Teste 2: Autenticacao HMAC
- Python assina com `HMAC-SHA256("{timestamp}.{body}", secret)`
- WordPress valida com `hash_hmac('sha256', "{timestamp}.{body}", secret)`

### Teste 3: Acesso a PDFs
- Python chama `GET /worker/files/{job_id}` com HMAC
- WordPress retorna lista de arquivos com `file_path`

### Teste 4: Processamento por bloco
- Python processa EXATAMENTE 20 paginas por execucao
- Nao usa `while True` nem mantem processo permanente

### Teste 5: Progresso salvo
- Python envia `current_page`, `progress`, `file_current_page`
- WordPress armazena no banco de dados

### Teste 6: Retomada
- Python le `current_page` do banco
- Proxima execucao comeca de onde parou

### Teste 7: Questoes salvas
- Python envia questoes via `POST /worker/questions`
- WordPress armazena na tabela `wp_pomaroli_questions`

### Teste 8: Falha nao avanca
- Se salvar questoes falhar, `current_page` NAO e atualizado
- Proxima execucao tenta novamente o mesmo bloco

### Teste 9: PDF concluido
- Quando todas as paginas sao processadas
- `file_status = completed`
- `job_status = completed` (se ultimo arquivo)

### Teste 10: Sequencia
- Somente um job em `processing` por vez
- Proximo job so comeca quando anterior termina

### Teste 11: Fila
- 10 PDFs = 1 processing + 9 queued
- Worker so pega um por execucao

### Teste 12: Navegador
- Fechar navegador nao interrompe processamento
- Worker roda via cPanel Cron independentemente

---

## Endpoints REST (Admin)

| Metodo | Endpoint | Auth | Descricao |
|--------|----------|------|-----------|
| `GET` | `/pomaroli/v1/jobs` | Login | Lista jobs |
| `POST` | `/pomaroli/v1/jobs` | Login | Cria job |
| `GET` | `/pomaroli/v1/jobs/{id}` | Login | Detalhes do job |
| `DELETE` | `/pomaroli/v1/jobs/{id}` | Login | Exclui job |
| `POST` | `/pomaroli/v1/jobs/{id}/retry` | Login | Reenfileira job com erro |
| `GET` | `/pomaroli/v1/jobs/{id}/files` | Login | Lista arquivos |
| `POST` | `/pomaroli/v1/jobs/{id}/process` | Login | Processa job manualmente |
| `POST` | `/pomaroli/v1/jobs/{id}/cancel` | Login | Cancela job |
| `GET` | `/pomaroli/v1/questions` | Login | Lista questoes |
| `GET` | `/pomaroli/v1/stats` | Login | Estatisticas |
| `GET` | `/pomaroli/v1/health` | Login | Health check |
| `POST` | `/pomaroli/v1/upload-local` | Login | Upload de PDFs |

---

## Solucao de Problemas

### Worker nao encontre jobs
1. Verifique se `WP_SITE_URL` esta correto
2. Verifique se `POMAROLI_WORKER_SECRET` esta configurado
3. Teste o endpoint manualmente: `GET /wp-json/pomaroli/v1/worker/next-job`

### Autenticacao falhou
1. Verifique se o secret e igual em ambos os lados
2. Verifique se os headers `X-Pomaroli-Hmac` e `X-Pomaroli-Timestamp` estao sendo enviados
3. Verifique se o timestamp nao e muito antigo (max 300 segundos)

### PDF nao e encontrado
1. Verifique se o `file_path` esta correto
2. Verifique se o arquivo existe no servidor
3. Verifique permissoes de acesso

### Questoes nao sao salvas
1. Verifique se o job esta em status `processing`
2. Verifique os logs do WordPress
3. Verifique se a tabela `wp_pomaroli_questions` existe
