# Python Worker — Extrator Pomaroli

Worker de processamento de PDFs que roda no cPanel/Turbo Cloud via Cron.

## O que faz

- Consome jobs enfileirados no WordPress via REST API (autenticação HMAC-SHA256)
- Processa PDFs em blocos configuráveis (default: 20 páginas)
- Salva progresso e questões extraídas no WordPress a cada bloco
- Utiliza o `extrator.py` original para parsing determinístico (regex + máquina de estados)
- Extrai imagens de alternativas e enunciados
- Valida qualidade das questões extraídas

## Arquivos

```
python-worker/
├── worker.py              # Script principal do worker
├── extrator.py            # Lógica de extração de texto (original)
├── qualidade.py           # Validação de qualidade
├── requirements.txt       # Dependências Python
├── run.sh                 # Script para cPanel Cron
├── config.json.example    # Exemplo de configuração
├── .htaccess              # Bloqueio de acesso direto
└── README.md              # Este arquivo
```

## Instalação no cPanel

### 1. Copiar arquivos

Copie toda a pasta `python-worker/` para o servidor via FTP/SSH:
```
/home/usuario/public_html/python-worker/
```

### 2. Configurar

Copie `config.json.example` para `config.json` e preencha:
```json
{
    "wordpress_url": "https://seudominio.com",
    "worker_secret": "SUA_CHAVE_SECRETA_HMAC",
    "gemini_api_key": "",
    "block_size": 20
}
```

O `worker_secret` deve ser o mesmo valor configurado no plugin WordPress.

### 3. Instalar dependências

```bash
cd /home/usuario/public_html/python-worker
pip3 install -r requirements.txt
```

### 4. Configurar permissões

```bash
chmod +x run.sh
chmod 600 config.json
chmod 700 .
```

### 5. Configurar Cron no cPanel

Acesse **Cron Jobs** no cPanel e adicione:

```bash
*/2 * * * * /home/usuario/public_html/python-worker/run.sh >> /home/usuario/logs/worker.log 2>&1
```

**Intervalo recomendado:** A cada 2 minutos. O worker processa UM bloco por execução e libera o lock, permitindo que a próxima execução continue de onde parou.

## Fluxo de Execução

```
Cada tick do Cron (2 min):
  1. Verifica lock → se ocupado, sai
  2. GET /wp-json/pomaroli/v1/worker/next-job → busca próximo job queued
  3. POST /wp-json/pomaroli/v1/worker/claim-job → marca como processing
  4. GET /wp-json/pomaroli/v1/jobs/{id}/files → busca arquivos do job
  5. Para cada arquivo:
     a. Extrai texto do bloco (20 páginas) via pdfplumber
     b. Parseia questões via extrator.parsear_questoes_local()
     c. Extrai imagens de alternativas e enunciados
     d. Valida qualidade via validar_questoes()
     e. POST /wp-json/pomaroli/v1/worker/questions → salva questões
     f. POST /wp-json/pomaroli/v1/worker/update → atualiza progresso
  6. Se todos os arquivos processados → POST /worker/complete
  7. Libera lock e encerra
```

## Debugging

```bash
# Testar manualmente
cd /home/usuario/public_html/python-worker
python3 worker.py

# Ver logs
tail -f /home/usuario/logs/worker.log

# Verificar status
curl https://seudominio.com/wp-json/pomaroli/v1/worker/status
```

## Segurança

- Autenticação HMAC-SHA256 entre Python e WordPress
- Lock de arquivo impede execuções concorrentes
- `.htaccess` bloqueia acesso direto aos arquivos Python
- Nunca exponha `config.json` publicamente
