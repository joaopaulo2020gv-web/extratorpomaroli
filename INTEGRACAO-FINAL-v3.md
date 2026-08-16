# INTEGRACAO FINAL v3.3.2 — Extrator de Questoes Pomaroli

## 1. Correcao: Contador de Arquivos

### Regra

O Python NAO incrementa manualmente `arquivos_completed`.

Apos cada processamento:
1. Atualiza o arquivo como `completed` no WordPress
2. Consulta novamente a lista de arquivos
3. Obtem a quantidade REAL de `completed`
4. Compara com o total

### Implementacao

```python
# Recarregar status dos arquivos apos processamento
files_updated = wp_get_job_files(job_id)
if files_updated:
    files = files_updated

arquivos_completed = sum(1 for f in files if f.get('status') == 'completed')
arquivos_total = len(files)

todos_completed = arquivos_completed >= arquivos_total
```

### NUNCA fazer

```python
# ERRADO
arquivos_completed += 1
```

---

## 2. Correcao: Salvamento de Questoes

### Regra

O WordPress retorna `success: true` somente quando TODAS as questoes foram processadas.

### Resposta de sucesso

```json
{
    "success": true,
    "inserted": 20,
    "updated": 0,
    "failed": 0,
    "total": 20
}
```

### Resposta de falha

```json
{
    "success": false,
    "inserted": 18,
    "updated": 0,
    "failed": 2,
    "total": 20,
    "error": "2 questão(ões) falhou ao salvar."
}
```

### Verificacao no Python

```python
res = wp_request('POST', 'worker/questions', payload)
if res.status_code < 200 or res.status_code >= 300:
    return False, {}

body = res.json()
return body.get('success') is True, body
```

---

## 3. Correcao: Atualizacao de Progresso

### Regra

O WordPress retorna `success: true` somente quando as operacoes no banco foram bem-sucedidas.

### Resposta de sucesso

```json
{
    "success": true
}
```

### Resposta de falha

```json
{
    "success": false,
    "error": "Falha ao atualizar progresso."
}
```

### Verificacao no Python

```python
res = wp_request('POST', 'worker/update', data)
if res.status_code < 200 or res.status_code >= 300:
    return False

body = res.json()
return body.get('success') is True
```

---

## 4. Regra do Current_Page

### Ordem obrigatoria

```
1. Processar bloco
2. Salvar questoes
3. Confirmar que questoes foram salvas (success: true)
4. Atualizar current_page
5. Confirmar que current_page foi atualizado (success: true)
6. Somente entao considerar bloco concluido
```

### Se qualquer etapa falhar

```
NAO avancar current_page
NAO considerar bloco concluido
Proxima execucao reprocessa o mesmo bloco
```

### Protecao de idempotencia

Se o mesmo bloco for processado novamente:
- UNIQUE index impede duplicatas
- `ON DUPLICATE KEY UPDATE` atualiza dados existentes

---

## 5. Quando o Job e Completed

### Regra

```
Job = completed
    SOMENTE quando TODOS os arquivos estiverem completed

Job = failed
    Se QUALQUER arquivo estiver failed
```

### NUNCA

```python
# ERRADO - NAO incrementar manualmente
if arquivo_concluido:
    arquivos_completed += 1
```

### SEMPRE

```python
# CORRETO - ConsultarWordPress
files_updated = wp_get_job_files(job_id)
arquivos_completed = sum(1 for f in files_updated if f.get('status') == 'completed')
todos_completed = arquivos_completed >= len(files_updated)
```

---

## 6. Endpoints REST

### Worker → WordPress (HMAC)

| Metodo | Endpoint | Descricao |
|--------|----------|-----------|
| GET | `/wp-json/pomaroli/v1/worker/next-job` | Proximo job queued |
| POST | `/wp-json/pomaroli/v1/worker/claim-job` | Marca como processing |
| GET | `/wp-json/pomaroli/v1/worker/files/{id}` | Lista arquivos |
| POST | `/wp-json/pomaroli/v1/worker/update` | Atualiza progresso |
| POST | `/wp-json/pomaroli/v1/worker/questions` | Salva questoes |
| POST | `/wp-json/pomaroli/v1/worker/complete` | Finaliza job |

### Headers

```
X-Pomaroli-Hmac: {HMAC-SHA256}
X-Pomaroli-Timestamp: {unix_timestamp}
Content-Type: application/json
```

### Algoritmo HMAC

```
message = "{timestamp}.{body}"
signature = HMAC-SHA256(message, secret)
```
