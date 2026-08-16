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

## Arquitetura v3.1.0 (Persistência)

### Backend WordPress (Plugin)
- `includes/class-pomaroli-db.php` - Tabelas customizadas + CRUD (jobs, files, questions, ai_jobs, logs)
- `includes/class-pomaroli-migrate.php` - Migração do wp_options antigo
- `includes/class-pomaroli-rest.php` - Endpoints REST API (/wp-json/pomaroli/v1/*)
- `includes/class-pomaroli-worker-auth.php` - Autenticação HMAC Python↔WP

### Frontend Dashboard SPA
- `index.html` - Shell do SPA com templates HTML
- `assets/css/dashboard.css` - Design system completo (dark theme)
- `assets/js/api.js` - Camada de API REST
- `assets/js/app.js` - Router + renderização das páginas

### Tabelas WordPress
- `wp_pomaroli_jobs` - Jobs de processamento
- `wp_pomaroli_files` - Arquivos PDF individuais
- `wp_pomaroli_questions` - Questões extraídas (staging antes de CPT)
- `wp_pomaroli_ai_jobs` - Jobs de IA (revisão em massa)
- `wp_pomaroli_logs` - Logs de atividade

### Segurança
- Secret fixo `extrator_pomaroli_secret_key_2026` REMOVIDO
- HMAC-SHA256 para comunicação Python↔WordPress
- Variável de ambiente `POMAROLI_WORKER_SECRET` necessária no Render
- API keys nunca expostas no frontend

---

# PROTOCOLO DE BUILD DO PLUGIN

**NÃO GERAR ZIP SEM SEGUIR ESTE PROTOCOLO.**

## Regra Principal

O ZIP é o artefato que será instalado no WordPress. Se o ZIP tiver erro, o plugin não ativa. Portanto, a validação final deve ser feita NO ZIP, e não somente no código-fonte.

## Fluxo Obrigatório

```
CÓDIGO-FONTE
     ↓
1. Buscar padrões proibidos
     ↓
2. Corrigir código-fonte
     ↓
3. Criar ZIP
     ↓
4. Extrair ZIP em pasta temporária
     ↓
5. Buscar padrões proibidos no extraído
     ↓
6. Verificar conteúdo correto no extraído
     ↓
7. Entregar ZIP
```

## Passo 1: Buscar Padrões Proibidos no Código-Fonte

Antes de gerar qualquer ZIP, buscar nos PHP do plugin:

### Padrão proibido: `??` dentro de string interpolada

```php
// ERRADO - NÃO PODE EXISTIR
"texto {$params['status'] ?? ''}"
"texto {$var['key'] ?? ''}"
"texto {$arr[$idx] ?? default}"
```

Busca:
```
grep "\{\$.*\?\?" includes/*.php extrator-questoes-wp.php
```

Se encontrar QUALQUER ocorrência, PARAR e corrigir.

### Como corrigir

Substituir por variável intermediária:

```php
// CORRETO
$worker_status = isset($params['status']) ? $params['status'] : '';
$this->db->log('info', "Worker update: status={$worker_status}", 0, $job_id, $params);
```

## Passo 2: Criar ZIP

Usar Python com `zipfile` para criar ZIP com caminhos Linux (forward-slash):

```python
import zipfile, os

source_dir = r"wordpress-plugin/extrator-questoes-wp"
zip_path = r"caminho/para/extrator-questoes-wp.zip"

with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk(source_dir):
        for file in files:
            file_path = os.path.join(root, file)
            arcname = os.path.relpath(file_path, source_dir).replace('\\', '/')
            zf.write(file_path, arcname)
```

NÃO usar `Compress-Archive` do PowerShell (cria backslash paths que quebram no Linux).

## Passo 3: Extrair e Validar o ZIP

```python
import zipfile, os, tempfile, shutil

tmp_dir = os.path.join(tempfile.gettempdir(), "pomaroli-validation")
if os.path.exists(tmp_dir):
    shutil.rmtree(tmp_dir)

with zipfile.ZipFile(zip_path, 'r') as zf:
    zf.extractall(tmp_dir)
```

## Passo 4: Buscar Padrões Proibidos no ZIP Extraído

```python
for root, dirs, files in os.walk(tmp_dir):
    for f in files:
        if f.endswith('.php'):
            fp = os.path.join(root, f)
            with open(fp, 'r', encoding='utf-8', errors='ignore') as fh:
                content = fh.read()
            if "{$params['status'] ?? ''}" in content:
                print(f"ERRO: Padrão proibido em {f}")
```

**Se encontrar QUALQUER ocorrência, NÃO ENTREGAR o ZIP.**

## Passo 5: Verificar Conteúdo Correto

```python
for root, dirs, files in os.walk(tmp_dir):
    for f in files:
        if f.endswith('.php'):
            fp = os.path.join(root, f)
            with open(fp, 'r', encoding='utf-8', errors='ignore') as fh:
                content = fh.read()
            if "$worker_status = isset($params['status']) ? $params['status'] : '';" in content:
                print(f"OK: {f}")
```

## Passo 6: Entregar

Só depois de:
- ZIP criado
- ZIP extraído
- Padrões proibidos: **NENHUM encontrado**
- Conteúdo correto: **ENCONTRADO**

Então o ZIP está pronto para instalação.

---

# REGRAS DE COMPATIBILIDADE PHP

## SQL

- NÃO usar `DATETIME DEFAULT '0000-00-00 00:00:00'` — usar `DATETIME NULL`
- NÃO usar `CONSTRAINT FOREIGN KEY` em `dbDelta()`
- NÃO usar `DEFAULT CURRENT_TIMESTAMP` ou `ON UPDATE CURRENT_TIMESTAMP`
- `PRIMARY KEY` deve ter dois espaços: `PRIMARY KEY  (id)`
- Cada coluna em sua própria linha

## PHP

- NÃO usar `catch (\Throwable $e)` — usar `catch (Exception $e)`
- NÃO usar `??` dentro de `{$...}` em strings interpoladas
- Usar `isset($var) ? $var : default` como alternativa
- `random_bytes()` precisa de fallback para PHP < 7.0

## WordPress

- Classes devem ter `get_instance()` singleton
- `register_activation_hook` deve ser seguro (sem dependências externas)
- REST API deve ser inicializada via `rest_api_init` hook
- Nunca chamar `dbDelta()` fora do activation hook
