# INTEGRACAO FINAL — Extrator de Questoes Pomaroli v3.3.1

## 1. Idempotencia de Questoes

### Como funciona

A tabela `wp_pomaroli_questions` possui um indice UNIQUE na combinacao:

```
(job_id, file_id, question_number)
```

Isso garante que nao existam duas questoes com o mesmo numero para o mesmo arquivo/job.

### Protecao no codigo

O metodo `create_questions_batch()` utiliza `INSERT ... ON DUPLICATE KEY UPDATE`:

```sql
INSERT INTO wp_pomaroli_questions (job_id, file_id, question_number, ...)
VALUES (...)
ON DUPLICATE KEY UPDATE
    question_data = VALUES(question_data),
    status = VALUES(status),
    ...
```

Se uma questao ja existe (mesmo job_id + file_id + question_number):
- Nao insere duplicata
- Atualiza os dados existentes
- Retorna 0 insercoes (nao incrementa o contador)

### Comportamento

Se o mesmo bloco for processado duas vezes:
- 1a execucao: insere N questoes
- 2a execucao: atualiza as mesmas N questoes (zero duplicatas)

---

## 2. Protecao de current_page

### Regra obrigatoria

```
SE salvar questoes falhar:
    NAO atualizar current_page

SE atualizar progresso falhar:
    NAO considerar o bloco concluido
```

### Implementacao no Python

```python
# 1. Salvar questoes
ok, _ = wp_save_questions(job_id, file_id, file_index, questoes)
if not ok:
    # FALHA: nao avanca
    return False, 0, False, True

# 2. Atualizar progresso
progresso_ok = wp_update_job(job_id, {
    'current_page': novo_current,
    'progress': progresso,
    ...
})
if not progresso_ok:
    # FALHA: nao avanca
    return False, questoes_salvas, False, True
```

### Verificacao de sucesso

`wp_update_job()` verifica:
1. HTTP status == 200
2. JSON retornado contem `{"ok": true}`

Se qualquer condicao falhar, retorna `False`.

---

## 3. Tratamento de Falhas

### Erros de rede (timeout, 500, 502, 503)

- `wp_request()` lance excecao
- `run_worker()` captura na bloco `except`
- Nao avanca current_page
- Nao marca job como completed
- Proximo Cron tenta novamente

### Erro ao salvar questoes

- `wp_save_questions()` retorna `(False, {})`
- `processar_um_bloco()` retorna erro
- current_page NAO e atualizado
- Proximo Cron reprocessa o mesmo bloco

### Erro ao atualizar progresso

- `wp_update_job()` retorna `False`
- `processar_um_bloco()` retorna erro
- current_page NAO e atualizado
- Questoes ja salvas NAO sao perdidas (estao no banco)

### Dados nunca sao perdos

- Questoes salvas permanecem no banco
- current_page so avanca com confirmacao
- Progresso so atualiza com confirmacao

---

## 4. Quando o Job vira Completed

### Regra

```
Job = completed
    SOMENTE quando TODOS os arquivos estiverem com status = completed

Job = failed
    Se QUALQUER arquivo estiver com status = failed
```

### Exemplos

```
PDF 1 = completed
PDF 2 = completed
PDF 3 = completed
→ JOB = completed

PDF 1 = completed
PDF 2 = completed
PDF 3 = failed
→ JOB = failed

PDF 1 = completed
PDF 2 = processing
PDF 3 = pending
→ JOB = processing (nenhum dos dois)
```

### Implementacao

```python
arquivos_completed = sum(1 for f in files if f.get('status') == 'completed')
arquivos_failed = sum(1 for f in files if f.get('status') == 'failed')

todos_completed = arquivos_completed >= arquivos_total
tem_falha = arquivos_failed > 0

if todos_completed and not tem_falha:
    # Job concluido com sucesso
    wp_complete_job(job_id, success=True)
elif tem_falha:
    # Job finalizado com falha
    wp_complete_job(job_id, success=False)
else:
    # Job em andamento
    status = 'partial'
```

---

## 5. Como o Cron deve executar o worker

### Configuracao do Cron

```
*/5 * * * * cd /home/usuario/extractor && python3 worker.py >> /dev/null 2>&1
```

### Fluxo de cada execucao

```
1. Verifica lock (impede execucoes concorrentes)
2. Busca proximo job com status 'queued'
3. Marca job como 'processing' (claim)
4. Lista arquivos do job
5. Seleciona proximo arquivo 'pending' ou 'processing'
6. Processa UM BLOCO (20 paginas)
7. Salva questoes
8. Atualiza progresso
9. Libera lock
10. Encerra
```

### Block size

```
BLOCK_SIZE = 20 paginas por execucao
```

Nao usar `while True`.
Nao manter processo permanente.
Cada execucao processa UM bloco e encerra.

### Retomada

```
Execucao 1: paginas 1-20   → current_page = 20
Execucao 2: paginas 21-40  → current_page = 40
Execucao 3: paginas 41-60  → current_page = 60
...
```

O ponto de retomada esta salvo no WordPress (campo `current_page`).
Nao depende da memoria do processo anterior.

---

## Endpoints REST

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
