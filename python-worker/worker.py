"""
worker.py — Python Worker para processamento de PDFs via cPanel Cron.

Execução pontual: cPanel Cron chama `python worker.py` periodicamente.
Cada execução:
  1. Verifica lock (impede concorrência)
  2. Busca próximo job queued no WordPress via REST API HMAC
  3. Processa UM BLOCO de páginas (default: 20)
  4. Salva progresso + questões no WordPress
  5. Libera lock e encerra

O WordPress é a fonte oficial de estado.
NÃO depende de Render, fila em memória ou disco persistente.
"""

import os
import sys
import json
import time
import hmac
import hashlib
try:
    import fcntl
except ImportError:
    fcntl = None
import traceback

import requests

# Adiciona o diretório atual ao path para importar extrator.py e qualidade.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extrator
from qualidade import validar_questoes

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

def load_config():
    """Carrega config de variáveis de ambiente ou config.json."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    config = {}
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

    return {
        'WP_SITE_URL': os.environ.get('WP_SITE_URL', config.get('wordpress_url', '')).rstrip('/'),
        'WORKER_SECRET': os.environ.get('POMAROLI_WORKER_SECRET', config.get('worker_secret', '')),
        'GEMINI_API_KEY': os.environ.get('GEMINI_API_KEY', config.get('gemini_api_key', '')),
        'BLOCK_SIZE': int(os.environ.get('BLOCK_SIZE', config.get('block_size', 20))),
    }

CFG = load_config()
WP_SITE_URL = CFG['WP_SITE_URL']
WORKER_SECRET = CFG['WORKER_SECRET']
BLOCK_SIZE = CFG['BLOCK_SIZE']

LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.worker.lock')

# =============================================================================
# HMAC SIGNING
# =============================================================================

def sign_request(method, endpoint, body_str=''):
    """Gera headers HMAC-SHA256 para autenticação com WordPress."""
    timestamp = str(int(time.time()))
    message = f"{timestamp}.{method.upper()}.{endpoint}.{body_str}"
    signature = hmac.new(
        WORKER_SECRET.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return {
        'X-Pomaroli-Hmac': signature,
        'X-Pomaroli-Timestamp': timestamp,
        'Content-Type': 'application/json',
        'User-Agent': 'PomaroliWorker/3.2',
    }


def wp_request(method, endpoint, data=None, timeout=60):
    """Faz request autenticado ao WordPress REST API."""
    url = f"{WP_SITE_URL}/wp-json/pomaroli/v1/{endpoint}"
    body_str = json.dumps(data) if data else ''
    headers = sign_request(method, endpoint, body_str)

    if method == 'GET':
        res = requests.get(url, headers=headers, timeout=timeout)
    elif method == 'POST':
        res = requests.post(url, data=body_str, headers=headers, timeout=timeout)
    elif method == 'PUT':
        res = requests.put(url, data=body_str, headers=headers, timeout=timeout)
    else:
        raise ValueError(f"Method não suportado: {method}")

    return res

# =============================================================================
# LOCK (fcntl — Linux/cPanel)
# =============================================================================

class WorkerLock:
    """Lock baseado em arquivo para impedir execuções concorrentes."""

    def __init__(self):
        self._fd = None

    def adquirir(self):
        try:
            self._fd = open(LOCK_FILE, 'w')
            if fcntl:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._fd.write(str(os.getpid()))
            self._fd.flush()
            return True
        except (IOError, OSError):
            if self._fd:
                self._fd.close()
                self._fd = None
            return False

    def liberar(self):
        if self._fd:
            try:
                if fcntl:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                self._fd.close()
            except Exception:
                pass
            self._fd = None
        try:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
        except Exception:
            pass

# =============================================================================
# WORDPRESS API HELPERS
# =============================================================================

def wp_get_next_job():
    """Busca o próximo job com status queued."""
    res = wp_request('GET', 'worker/next-job')
    if res.status_code == 200:
        data = res.json()
        if data.get('job'):
            return data['job']
    return None


def wp_claim_job(job_id):
    """Marca um job como processing."""
    res = wp_request('POST', 'worker/claim-job', {'job_id': job_id})
    return res.status_code == 200


def wp_update_job(job_id, data):
    """Atualiza dados de um job."""
    data['job_id'] = job_id
    res = wp_request('POST', 'worker/update', data)
    return res.status_code == 200


def wp_save_questions(job_id, file_id, file_index, questions):
    """Envia questões extraídas para o WordPress."""
    payload = {
        'job_id': job_id,
        'questions': [{
            'job_id': job_id,
            'file_id': file_id,
            'file_index': file_index,
            'question_number': q.get('Numero', idx + 1),
            'question_data': q,
            'status': 'extraida',
        } for idx, q in enumerate(questions)]
    }
    res = wp_request('POST', 'worker/questions', payload)
    return res.status_code == 200, res.json() if res.status_code == 200 else {}


def wp_complete_job(job_id, success=True, total_questions=0, processed_files=0, error_message=None):
    """Notifica o WordPress que o job foi finalizado."""
    payload = {
        'job_id': job_id,
        'success': success,
        'total_questions': total_questions,
        'processed_files': processed_files,
        'error_message': error_message,
    }
    res = wp_request('POST', 'worker/complete', payload)
    return res.status_code == 200


def wp_get_job_files(job_id):
    """Busca os arquivos de um job."""
    res = wp_request('GET', f'jobs/{job_id}/files')
    if res.status_code == 200:
        return res.json()
    return []

# =============================================================================
# EXTRAÇÃO EM BLOCOS (usa extrator.py original)
# =============================================================================

def extrair_bloco_texto(caminho_pdf, bloco_inicio, bloco_fim):
    """Extrai texto de um bloco específico de páginas do PDF usando pdfplumber."""
    import pdfplumber

    texto_bloco = []
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            total = len(pdf.pages)
            for i in range(bloco_inicio, min(bloco_fim, total)):
                page = pdf.pages[i]
                txt = page.extract_text() or ""
                if txt.strip():
                    texto_bloco.append(txt)
    except Exception as e:
        print(f"[-] Erro ao extrair bloco {bloco_inicio}-{bloco_fim}: {e}")
        return None

    return '\n\n'.join(texto_bloco)


def extrair_bloco_com_ocr(caminho_pdf, bloco_inicio, bloco_fim, api_key, model):
    """Extrai texto de um bloco usando OCR via Gemini Vision."""
    import fitz  # PyMuPDF

    texto_bloco = []
    try:
        doc = fitz.open(caminho_pdf)
        total = len(doc)

        for i in range(bloco_inicio, min(bloco_fim, total)):
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")

            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                tmp.write(img_bytes)
                tmp_path = tmp.name

            try:
                texto = extrator.extrair_texto_por_ocr(
                    tmp_path,
                    provedor='gemini',
                    api_key=api_key,
                    model=model or 'gemini-2.0-flash',
                    endpoint=None
                )
                if texto:
                    texto_bloco.append(texto)
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        doc.close()
    except Exception as e:
        print(f"[-] Erro OCR bloco {bloco_inicio}-{bloco_fim}: {e}")
        return None

    return '\n\n'.join(texto_bloco)


def contar_paginas_pdf(caminho_pdf):
    """Conta o total de páginas de um PDF."""
    import pdfplumber
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            return len(pdf.pages)
    except Exception:
        return 0

# =============================================================================
# PROCESSAMENTO DE JOB
# =============================================================================

def processar_job(job, files):
    """
    Processa UM job: itera sobre seus arquivos, processando cada um em blocos.
    Retorna (all_done, total_questoes, arquivos_ok, arquivos_erro).
    """
    job_id = job['id']
    use_ocr = bool(job.get('use_ocr', 0))
    api_key = CFG['GEMINI_API_KEY']
    ocr_model = job.get('ai_model', 'gemini-2.0-flash')

    total_questoes_job = 0
    arquivos_processados = 0
    arquivos_com_erro = 0

    for file in files:
        file_id = file['id']
        file_index = file.get('file_index', 0)
        caminho_pdf = file.get('file_path', '')
        filename = file.get('filename', '')

        if not caminho_pdf or not os.path.exists(caminho_pdf):
            print(f"[*] Baixando arquivo #{file_id} ({filename}) do WordPress via REST API...")
            try:
                import tempfile
                res = wp_request('GET', f'worker/download-file/{file_id}', timeout=120)
                if res.status_code == 200 and len(res.content) > 0:
                    tmp_dir = os.path.join(tempfile.gettempdir(), 'pomaroli_worker_pdfs')
                    os.makedirs(tmp_dir, exist_ok=True)
                    caminho_pdf = os.path.join(tmp_dir, filename)
                    with open(caminho_pdf, 'wb') as f_out:
                        f_out.write(res.content)
                    print(f"[+] Download concluído com sucesso ({len(res.content)} bytes): {caminho_pdf}")
                else:
                    print(f"[-] Falha no download do PDF (HTTP {res.status_code})")
            except Exception as e_dl:
                print(f"[-] Erro ao baixar PDF: {e_dl}")

        if not caminho_pdf or not os.path.exists(caminho_pdf):
            print(f"[-] Arquivo não encontrado: {caminho_pdf}")
            wp_update_job(job_id, {
                'file_id': file_id,
                'file_status': 'erro',
                'error_message': f'Arquivo não encontrado: {caminho_pdf}',
            })
            arquivos_com_erro += 1
            continue

        wp_update_job(job_id, {
            'file_id': file_id,
            'file_status': 'processing',
        })

        total_paginas = contar_paginas_pdf(caminho_pdf)
        if total_paginas == 0:
            wp_update_job(job_id, {
                'file_id': file_id,
                'file_status': 'erro',
                'error_message': 'PDF sem páginas ou corrompido.',
            })
            arquivos_com_erro += 1
            continue

        wp_update_job(job_id, {'total_pages': total_paginas})

        print(f"[+] Processando: {filename} ({total_paginas} páginas)")
        paginas_processadas = 0
        questoes_arquivo = 0
        erro_no_arquivo = False

        # Processar em blocos
        for bloco_inicio in range(0, total_paginas, BLOCK_SIZE):
            bloco_fim = min(bloco_inicio + BLOCK_SIZE, total_paginas)
            bloco_num = (bloco_inicio // BLOCK_SIZE) + 1
            total_blocos = (total_paginas + BLOCK_SIZE - 1) // BLOCK_SIZE

            print(f"  [BLOCO {bloco_num}/{total_blocos}] Páginas {bloco_inicio+1}-{bloco_fim}")

            # Extrair texto do bloco
            if use_ocr and api_key:
                texto = extrair_bloco_com_ocr(caminho_pdf, bloco_inicio, bloco_fim, api_key, ocr_model)
            else:
                texto = extrair_bloco_texto(caminho_pdf, bloco_inicio, bloco_fim)

            if texto is None:
                print(f"  [-] Erro ao extrair texto do bloco {bloco_inicio+1}-{bloco_fim}")
                erro_no_arquivo = True
                break

            if not texto.strip():
                print(f"  [*] Bloco vazio (páginas {bloco_inicio+1}-{bloco_fim}), pulando...")
                paginas_processadas = bloco_fim
                continue

            # Parsear questões do bloco (usa extrator.py original)
            questoes = extrator.parsear_questoes_local(texto)
            print(f"  [+] {len(questoes)} questões encontradas no bloco")

            if questoes:
                # Extrair imagens das alternativas e enunciado
                questoes = extrator.extrair_imagens_alternativas_pdf(caminho_pdf, questoes)
                questoes = extrator.extrair_imagens_enunciado_pdf(caminho_pdf, questoes)

                # Validar qualidade
                questoes = validar_questoes(questoes)

                # Salvar no WordPress
                ok, _ = wp_save_questions(job_id, file_id, file_index, questoes)
                if ok:
                    questoes_arquivo += len(questoes)
                    print(f"  [+] {len(questoes)} questões salvas no WordPress")
                else:
                    print(f"  [-] Erro ao salvar questões no WordPress")

            # Atualizar progresso
            paginas_processadas = bloco_fim
            progresso_file = int((paginas_processadas / total_paginas) * 100) if total_paginas > 0 else 0

            wp_update_job(job_id, {
                'file_id': file_id,
                'file_progress': progresso_file,
                'file_current_page': paginas_processadas,
                'file_pages': total_paginas,
                'file_questions_found': questoes_arquivo,
                'current_page': paginas_processadas,
                'progress': progresso_file,
            })

            # Liberar memória
            del texto, questoes
            import gc
            gc.collect()

        # Finalizar arquivo
        if erro_no_arquivo:
            wp_update_job(job_id, {
                'file_id': file_id,
                'file_status': 'erro',
                'error_message': 'Erro durante processamento do bloco.',
            })
            arquivos_com_erro += 1
        else:
            wp_update_job(job_id, {
                'file_id': file_id,
                'file_status': 'completed',
                'file_progress': 100,
                'file_questions_found': questoes_arquivo,
            })
            arquivos_processados += 1
            total_questoes_job += questoes_arquivo

        print(f"[+] Arquivo {filename} finalizado: {questoes_arquivo} questões")

    # Verificar se todos os arquivos foram processados
    total_files = len(files)
    all_done = (arquivos_processados + arquivos_com_erro) >= total_files

    wp_update_job(job_id, {
        'processed_files': arquivos_processados + arquivos_com_erro,
        'total_questions': total_questoes_job,
    })

    return all_done, total_questoes_job, arquivos_processados, arquivos_com_erro

# =============================================================================
# EXECUÇÃO PRINCIPAL
# =============================================================================

def run_worker():
    """
    Execução pontual do worker.
    Verifica lock → busca job → processa bloco → salva → libera → encerra.
    """
    if not WP_SITE_URL:
        print("[ERRO] WP_SITE_URL não configurado.")
        return {'status': 'error', 'message': 'WP_SITE_URL não configurado.'}, 500

    if not WORKER_SECRET:
        print("[ERRO] POMAROLI_WORKER_SECRET não configurado.")
        return {'status': 'error', 'message': 'POMAROLI_WORKER_SECRET não configurado.'}, 500

    # Adquirir lock
    lock = WorkerLock()
    if not lock.adquirir():
        print("[INFO] Outro worker já está em execução. Saindo.")
        return {'status': 'busy', 'message': 'Outro worker já está em execução.'}, 200

    try:
        # Buscar próximo job queued
        job = wp_get_next_job()
        if not job:
            print("[INFO] Nenhum job na fila.")
            return {'status': 'idle', 'message': 'Nenhum job na fila.'}, 200

        job_id = job['id']

        # Claim job (marcar como processing)
        claimed = wp_claim_job(job_id)
        if not claimed:
            print(f"[ERRO] Não foi possível claim job #{job_id}.")
            return {'status': 'error', 'message': f'Não foi possível claim job #{job_id}.'}, 500

        print(f"[WORKER] Job #{job_id} claimado. Buscando arquivos...")

        # Buscar arquivos do job
        files = wp_get_job_files(job_id)
        if not files:
            wp_complete_job(job_id, success=False, error_message='Nenhum arquivo encontrado.')
            return {'status': 'error', 'message': 'Nenhum arquivo encontrado.'}, 404

        # Filtrar apenas arquivos pendentes ou com erro (para retry)
        files_pendentes = [f for f in files if f.get('status') in ('pending', 'queued', 'erro', None)]
        if not files_pendentes:
            wp_complete_job(job_id, success=True, processed_files=len(files))
            return {'status': 'completed', 'message': 'Todos os arquivos já processados.'}, 200

        # Processar job
        all_done, total_questoes, proc_ok, proc_erro = processar_job(job, files_pendentes)

        # Finalizar job
        if all_done:
            wp_complete_job(
                job_id,
                success=(proc_erro == 0),
                total_questions=total_questoes,
                processed_files=len(files),
                error_message=f'{proc_erro} arquivo(s) com erro.' if proc_erro > 0 else None
            )
            status = 'completed'
        else:
            status = 'partial'

        return {
            'status': status,
            'job_id': job_id,
            'total_questoes': total_questoes,
            'arquivos_processados': proc_ok,
            'arquivos_erro': proc_erro,
            'message': f'Job #{job_id}: {total_questoes} questões extraídas.',
        }, 200

    except Exception as e:
        traceback.print_exc()
        try:
            wp_complete_job(job_id, success=False, error_message=str(e))
        except Exception:
            pass
        return {'status': 'error', 'message': str(e)}, 500

    finally:
        lock.liberar()


if __name__ == '__main__':
    print(f"[WORKER] Iniciando Pomaroli Worker v3.2")
    print(f"[WORKER] WP_SITE_URL: {WP_SITE_URL}")
    print(f"[WORKER] Block size: {BLOCK_SIZE}")

    resultado, status_code = run_worker()
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    sys.exit(0 if status_code in (200, 204) else 1)
