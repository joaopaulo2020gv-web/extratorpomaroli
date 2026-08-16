"""
worker.py — Worker de processamento de PDFs para Turbo Cloud (cPanel).

Execução pontual: cPanel Cron chama /worker/run periodicamente.
Cada execução:
  1. Verifica lock
  2. Busca próximo job queued no WordPress
  3. Processa UM BLOCO de páginas (ex: 20 páginas)
  4. Salva progresso + questões no WordPress
  5. Libera lock
  6. Encerra

NÃO depende de Render, fila em memória ou disco persistente do servidor.
O WordPress é a fonte oficial de estado.
"""

import os
import sys
import json
import time
import hmac
import hashlib
import fcntl
import traceback

import requests

# Adiciona o diretório atual ao path para importar extrator.py
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import extrator
from qualidade import validar_questoes

# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

WORKER_TOKEN = os.environ.get('POMAROLI_WORKER_TOKEN', '')
POMAROLI_WORKER_SECRET = os.environ.get('POMAROLI_WORKER_SECRET', '')
WP_SITE_URL = os.environ.get('WP_SITE_URL', '').rstrip('/')

BLOC_SIZE = 20  # Páginas por bloco de processamento
LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.worker.lock')

# =============================================================================
# HMAC SIGNING
# =============================================================================

def sign_hmac_wp(payload_str):
    """Assina payload com HMAC-SHA256 para autenticação com WordPress."""
    timestamp = str(int(time.time()))
    if not POMAROLI_WORKER_SECRET:
        return {
            'X-Pomaroli-Hmac': '',
            'X-Pomaroli-Timestamp': timestamp,
            'Content-Type': 'application/json',
            'User-Agent': 'ExtratorPomaroli/3.2 Worker',
        }
    message = f"{timestamp}.{payload_str}"
    h = hmac.new(
        POMAROLI_WORKER_SECRET.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return {
        'X-Pomaroli-Hmac': h,
        'X-Pomaroli-Timestamp': timestamp,
        'Content-Type': 'application/json',
        'User-Agent': 'ExtratorPomaroli/3.2 Worker',
    }


def wp_request(method, endpoint, data=None, timeout=60):
    """Faz request autenticado ao WordPress REST API."""
    url = f"{WP_SITE_URL}/wp-json/pomaroli/v1/{endpoint}"
    headers = {'Content-Type': 'application/json', 'User-Agent': 'ExtratorPomaroli/3.2 Worker'}
    payload_str = json.dumps(data) if data else '{}'
    hmac_headers = sign_hmac_wp(payload_str)
    headers.update(hmac_headers)

    if method == 'GET':
        res = requests.get(url, headers=headers, timeout=timeout)
    elif method == 'POST':
        res = requests.post(url, data=payload_str, headers=headers, timeout=timeout)
    elif method == 'PUT':
        res = requests.put(url, data=payload_str, headers=headers, timeout=timeout)
    else:
        raise ValueError(f"Method não suportado: {method}")

    return res


# =============================================================================
# LOCK
# =============================================================================

class WorkerLock:
    """Lock baseado em arquivo para impedir concorrência."""

    def __init__(self):
        self._fd = None

    def adquirir(self):
        """Tenta adquirir o lock. Retorna True se conseguiu."""
        try:
            self._fd = open(LOCK_FILE, 'w')
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
        """Libera o lock."""
        if self._fd:
            try:
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
# WORDPRESS API
# =============================================================================

def wp_get_next_job():
    """Busca o próximo job com status queued no WordPress."""
    res = wp_request('GET', 'worker/next-job')
    if res.status_code == 200:
        data = res.json()
        if data.get('job'):
            return data['job']
    return None


def wp_claim_job(job_id):
    """Marca um job como processing no WordPress."""
    res = wp_request('POST', 'worker/claim-job', {'job_id': job_id})
    return res.status_code == 200


def wp_update_job(job_id, data):
    """Atualiza dados de um job no WordPress."""
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
    """Busca os arquivos de um job no WordPress."""
    res = wp_request('GET', f'jobs/{job_id}/files')
    if res.status_code == 200:
        return res.json()
    return []


# =============================================================================
# EXTRAÇÃO EM BLOCOS
# =============================================================================

def extrair_bloco_texto(caminho_pdf, bloco_inicio, bloco_fim):
    """Extrai texto de um bloco específico de páginas do PDF."""
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


def extrair_bloco_com_ocr(caminho_pdf, bloco_inicio, bloco_fim, ocr_provedor, ocr_api_key, ocr_model, ocr_endpoint):
    """Extrai texto de um bloco usando OCR (para PDFs escaneados)."""
    import pdfplumber
    import fitz  # PyMuPDF

    texto_bloco = []
    try:
        doc = fitz.open(caminho_pdf)
        total = len(doc)

        for i in range(bloco_inicio, min(bloco_fim, total)):
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")

            # Salvar temporário e usar OCR
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                tmp.write(img_bytes)
                tmp_path = tmp.name

            try:
                texto = extrator.extrair_texto_por_ocr(
                    tmp_path,  # Usa imagem como PDF-like input
                    provedor=ocr_provedor,
                    api_key=ocr_api_key,
                    model=ocr_model,
                    endpoint=ocr_endpoint
                )
                if texto:
                    texto_bloco.append(texto)
            finally:
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
    Retorna True se o job foi concluído, False se há mais trabalho.
    """
    job_id = job['id']
    use_ocr = bool(job.get('use_ocr', 0))
    ocr_provedor = job.get('ai_provider', 'gemini') if use_ocr else None
    ocr_api_key = os.environ.get('GEMINI_API_KEY', '')
    ocr_model = job.get('ai_model', 'gemini-2.5-flash') if use_ocr else None

    total_questoes_job = 0
    arquivos_processados = 0
    arquivos_com_erro = 0

    for file in files:
        file_id = file['id']
        file_index = file.get('file_index', 0)
        caminho_pdf = file.get('file_path', '')
        filename = file.get('filename', '')

        if not caminho_pdf or not os.path.exists(caminho_pdf):
            print(f"[-] Arquivo não encontrado: {caminho_pdf}")
            wp_update_job(job_id, {
                'file_id': file_id,
                'file_status': 'erro',
                'error_message': f'Arquivo não encontrado: {caminho_pdf}',
            })
            arquivos_com_erro += 1
            continue

        # Marcar arquivo como processando
        wp_update_job(job_id, {
            'file_id': file_id,
            'file_status': 'processando',
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

        # Atualizar total de páginas no job
        wp_update_job(job_id, {
            'total_pages': total_paginas,
        })

        print(f"[+] Processando: {filename} ({total_paginas} páginas)")
        paginas_processadas = 0
        questoes_arquivo = 0
        erro_no_arquivo = False

        # Processar em blocos
        for bloco_inicio in range(0, total_paginas, BLOC_SIZE):
            bloco_fim = min(bloco_inicio + BLOC_SIZE, total_paginas)
            bloco_num = (bloco_inicio // BLOC_SIZE) + 1
            total_blocos = (total_paginas + BLOC_SIZE - 1) // BLOC_SIZE

            print(f"  [BLOCO {bloco_num}/{total_blocos}] Páginas {bloco_inicio+1}-{bloco_fim}")

            # Extrair texto do bloco
            if use_ocr and ocr_provedor:
                texto = extrair_bloco_com_ocr(
                    caminho_pdf, bloco_inicio, bloco_fim,
                    ocr_provedor, ocr_api_key, ocr_model, None
                )
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

            # Parsear questões do bloco
            questoes = extrator.parsear_questoes_local(texto)
            print(f"  [+] {len(questoes)} questões encontradas no bloco")

            if questoes:
                # Extrair imagens
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
                'file_status': 'concluido',
                'file_progress': 100,
                'file_questions_found': questoes_arquivo,
            })
            arquivos_processados += 1
            total_questoes_job += questoes_arquivo

        print(f"[+] Arquivo {filename} finalizado: {questoes_arquivo} questões")

    # Verificar se todos os arquivos foram processados
    total_files = len(files)
    all_done = (arquivos_processados + arquivos_com_erro) >= total_files

    # Atualizar job
    wp_update_job(job_id, {
        'processed_files': arquivos_processados + arquivos_com_erro,
        'total_questions': total_questoes_job,
    })

    return all_done, total_questoes_job, arquivos_processados, arquivos_com_erro


# =============================================================================
# ENDPOINT /worker/run
# =============================================================================

def run_worker(token):
    """
    Execução pontual do worker.
    Verifica lock → busca job → processa bloco → salva → libera → encerra.
    """
    # Validar token
    if not WORKER_TOKEN:
        return {'status': 'error', 'message': 'POMAROLI_WORKER_TOKEN não configurado.'}, 500

    if token != WORKER_TOKEN:
        return {'status': 'error', 'message': 'Token inválido.'}, 403

    # Verificar configuração
    if not WP_SITE_URL:
        return {'status': 'error', 'message': 'WP_SITE_URL não configurado.'}, 500

    # Adquirir lock
    lock = WorkerLock()
    if not lock.adquirir():
        return {'status': 'busy', 'message': 'Outro worker já está em execução.'}, 409

    try:
        # Buscar próximo job queued
        job = wp_get_next_job()
        if not job:
            return {'status': 'idle', 'message': 'Nenhum job na fila.'}, 200

        job_id = job['id']

        # Claim job (marcar como processing)
        claimed = wp_claim_job(job_id)
        if not claimed:
            return {'status': 'error', 'message': f'Não foi possível claim job #{job_id}.'}, 500

        print(f"[WORKER] Job #{job_id} claimado. Buscando arquivos...")

        # Buscar arquivos do job
        files = wp_get_job_files(job_id)
        if not files:
            wp_complete_job(job_id, success=False, error_message='Nenhum arquivo encontrado.')
            return {'status': 'error', 'message': 'Nenhum arquivo encontrado.'}, 404

        # Filtrar apenas arquivos pendentes ou com erro (para retry)
        files_pendentes = [f for f in files if f.get('status') in ('pendente', 'erro', None)]
        if not files_pendentes:
            # Todos já processados
            wp_complete_job(job_id, success=True, processed_files=len(files))
            return {'status': 'completed', 'message': 'Todos os arquivos já processados.'}, 200

        # Processar job
        all_done, total_questoes, proc_ok, proc_erro = processar_job(job, files_pendentes)

        # Finalizar job se todos os arquivos foram processados
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


# =============================================================================
# MAIN (execução direta via cron)
# =============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Pomaroli Worker')
    parser.add_argument('--token', default=WORKER_TOKEN, help='Token de autenticação')
    parser.add_argument('--url', default=WP_SITE_URL, help='URL do WordPress')
    args = parser.parse_args()

    if args.url:
        WP_SITE_URL = args.url.rstrip('/')

    resultado, status_code = run_worker(args.token)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    sys.exit(0 if status_code in (200, 204) else 1)
