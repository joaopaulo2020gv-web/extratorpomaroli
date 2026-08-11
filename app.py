import os
import sys
import json
import time
import uuid
import threading
import webbrowser
from queue import Queue
from threading import Timer
from flask import Flask, request, jsonify, render_template, send_file, Response
import pandas as pd

# Adiciona o diretório atual ao path para importar funções de extrator.py
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import extrator
from qualidade import validar_questoes

app = Flask(__name__, template_folder='templates')
app.config['UPLOAD_FOLDER'] = os.path.dirname(os.path.abspath(__file__))
ARQUIVO_SAIDA_CSV = "questoes_importar.csv"
ARQUIVO_SAIDA_JSON = "questoes_importar.json"

# Trata requisições OPTIONS preflight do ANTES do routing do Flask.
# Usar @app.before_request garante que OPTIONS seja respondido 200
# antes do Flask tentar casar a URL com rotas específicas (que retornariam 405).
@app.before_request
def handle_preflight():
    if request.method == 'OPTIONS':
        response = jsonify({"status": "ok"})
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
        return response, 200

# Aplica cabeçalhos CORS para permitir integração com WordPress em qualquer domínio
@app.after_request
def aplicar_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
    return response

# Mantém as questões na memória temporária do servidor para o fluxo da web
DADOS_MEMORIA = {
    "questoes": [],
    "gabaritos": {}
}

# Gerenciamento de Fila de Lotes (Background Tasks)
DADOS_LOTES = {}
FILA_LOTES = Queue()
ARQUIVO_LOTES_DB = os.path.join(app.config['UPLOAD_FOLDER'], 'uploads_lotes', 'lotes_db.json')

def salvar_lotes_disk():
    """Salva o estado atual dos lotes em arquivo JSON em disco para persistir entre reinícios do servidor."""
    try:
        os.makedirs(os.path.dirname(ARQUIVO_LOTES_DB), exist_ok=True)
        with open(ARQUIVO_LOTES_DB, 'w', encoding='utf-8') as f:
            json.dump(DADOS_LOTES, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[-] Erro ao salvar lotes em disco: {e}")

def carregar_lotes_disk():
    """Carrega lotes salvos previamente em disco no arranque da aplicação."""
    global DADOS_LOTES
    try:
        if os.path.exists(ARQUIVO_LOTES_DB):
            with open(ARQUIVO_LOTES_DB, 'r', encoding='utf-8') as f:
                DADOS_LOTES = json.load(f)
                print(f"[+] {len(DADOS_LOTES)} lotes carregados do disco.")
    except Exception as e:
        print(f"[-] Erro ao carregar lotes do disco: {e}")

# Carrega os lotes ao iniciar o app
carregar_lotes_disk()

def worker_processar_lotes():
    """Worker assíncrono que consome lotes de PDFs da fila e executa extração + IA."""
    while True:
        try:
            batch_id = FILA_LOTES.get()
            if not batch_id or batch_id not in DADOS_LOTES:
                FILA_LOTES.task_done()
                continue
                
            lote = DADOS_LOTES[batch_id]
            lote["status"] = "processando"
            lote["inicio"] = time.time()
            salvar_lotes_disk()
            
            for item in lote["arquivos"]:
                if lote.get("cancelado"):
                    item["status"] = "cancelado"
                    continue
                    
                item["status"] = "processando"
                salvar_lotes_disk()
                caminho_pdf = item["caminho"]
                
                try:
                    print(f"[LOTE] Processando arquivo: {item['filename']} (caminho: {caminho_pdf})")
                    texto = extrator.extrair_texto_pdf_colunas(
                        caminho_pdf,
                        ocr_provedor=lote.get("provedor") if lote.get("usar_ocr") else None,
                        ocr_api_key=lote.get("api_key"),
                        ocr_model=lote.get("model"),
                        ocr_endpoint=lote.get("endpoint")
                    )
                    
                    if not texto:
                        print(f"[LOTE] ERRO: Texto vazio para {item['filename']}")
                        item["status"] = "erro"
                        item["erro"] = "Falha ao extrair texto do PDF. O arquivo pode estar corrompido ou ser imagem sem OCR."
                        salvar_lotes_disk()
                        continue
                        
                    print(f"[LOTE] Texto extraido de {item['filename']}: {len(texto)} caracteres")
                    questoes = extrator.parsear_questoes_local(texto)
                    print(f"[LOTE] Questoes parseadas de {item['filename']}: {len(questoes)}")
                    questoes = extrator.extrair_imagens_alternativas_pdf(caminho_pdf, questoes)
                    questoes = extrator.extrair_imagens_enunciado_pdf(caminho_pdf, questoes)
                    questoes = validar_questoes(questoes)
                    print(f"[LOTE] Questoes finais apos validacao de {item['filename']}: {len(questoes)}")
                    
                    # Se nenhuma questão foi detectada, salva diagnóstico e marca como erro
                    if len(questoes) == 0:
                        caminho_diag = os.path.join(app.config['UPLOAD_FOLDER'], f"diagnostico_lote_{batch_id}_{item['id']}.txt")
                        try:
                            with open(caminho_diag, "w", encoding="utf-8") as f:
                                f.write(f"Arquivo: {item['filename']}\n")
                                f.write(f"Texto extraído ({len(texto)} caracteres):\n\n")
                                f.write(texto[:5000] if texto else "(vazio)")
                        except Exception as e_diag:
                            print(f"[-] Erro ao salvar diagnóstico: {e_diag}")
                        
                        item["status"] = "erro"
                        item["erro"] = (
                            "Nenhuma questão foi detectada neste PDF. "
                            "Possíveis causas: (1) O PDF é digitalizado/imagem — ative a opção 'Forçar OCR via IA' no painel de upload. "
                            "(2) O formato de numeração das questões é diferente do padrão. "
                            f"(3) Diagnóstico salvo em: {caminho_diag}"
                        )
                        salvar_lotes_disk()
                        continue
                    
                    # Refinamento por IA Grátis (Gemini) se ativado
                    if lote.get("autocorrigir_ia"):
                        provedor_ia = lote.get("provedor", "gemini")
                        api_key_ia = lote.get("api_key")
                        
                        questoes_refinadas = []
                        for q in questoes:
                            qual = q.get("Qualidade", {})
                            score = qual.get("score", 100)
                            
                            # Refina se o score for < 85 ou se foi solicitado refinar todas
                            if score < 85 or lote.get("refinar_todas"):
                                try:
                                    q_ref = extrator.refinar_questao_com_ia(
                                        q,
                                        provedor=provedor_ia,
                                        api_key=api_key_ia,
                                        model=lote.get("model"),
                                        endpoint=lote.get("endpoint")
                                    )
                                    q_ref["Refinada_IA"] = True
                                    questoes_refinadas.append(q_ref)
                                    time.sleep(0.5) # Respeita limite de RPM do tier gratuito
                                except Exception as err_ia:
                                    print(f"[-] Erro ao refinar questão #{q.get('Numero')} com IA: {err_ia}")
                                    questoes_refinadas.append(q)
                            else:
                                questoes_refinadas.append(q)
                                
                        questoes = validar_questoes(questoes_refinadas)
                    
                    item["questoes"] = questoes
                    item["total_questoes"] = len(questoes)
                    item["status"] = "concluido"
                    lote["total_questoes_extraidas"] += len(questoes)
                    salvar_lotes_disk()
                    
                    # Envio Automático robusto para o Banco de Dados do WordPress (com User-Agent e Chunking)
                    wp_site_url = lote.get("wp_site_url")
                    if wp_site_url and len(questoes) > 0:
                        try:
                            import json, requests
                            endpoint_wp = wp_site_url.rstrip("/") + "/wp-admin/admin-ajax.php"
                            print(f"[+] Enviando {len(questoes)} questões automaticamente para o WordPress em: {endpoint_wp}")
                            
                            headers = {
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 ExtratorPomaroli/2.9',
                                'Accept': 'application/json, text/plain, */*'
                            }
                            
                            # Envia em blocos de 10 questões por requisição HTTP para evitar bloqueios ou timeouts
                            chunk_size = 10
                            total_enviadas = 0
                            status_respostas = []
                            
                            for i in range(0, len(questoes), chunk_size):
                                chunk = questoes[i:i + chunk_size]
                                payload = {
                                    "action": "extrator_importar_banco_auto",
                                    "secret": "extrator_pomaroli_secret_key_2026",
                                    "questoes": json.dumps(chunk)
                                }
                                res = requests.post(endpoint_wp, data=payload, headers=headers, timeout=60)
                                status_respostas.append(f"Bloco {i//chunk_size + 1}: HTTP {res.status_code} - {res.text[:80]}")
                                if res.status_code == 200:
                                    total_enviadas += len(chunk)
                            
                            lote["wp_import_status"] = "sucesso" if total_enviadas > 0 else "falha"
                            lote["wp_import_mensagem"] = f"{total_enviadas}/{len(questoes)} enviadas. " + " | ".join(status_respostas)
                            lote["wp_import_timestamp"] = time.time()
                            print(f"[+] Auto-Import WordPress: {lote['wp_import_mensagem']}")
                        except Exception as err_wp:
                            lote["wp_import_status"] = "erro"
                            lote["wp_import_mensagem"] = str(err_wp)
                            lote["wp_import_timestamp"] = time.time()
                            print(f"[-] Erro ao enviar questões automaticamente para o WordPress: {err_wp}")
                    
                except Exception as ex_item:
                    item["status"] = "erro"
                    item["erro"] = str(ex_item)
                    salvar_lotes_disk()
                    
            lote["status"] = "concluido" if not lote.get("cancelado") else "cancelado"
            lote["fim"] = time.time()
            salvar_lotes_disk()
            FILA_LOTES.task_done()
            
        except Exception as e:
            print(f"[-] Erro inesperado no worker de lotes: {e}")

# Inicia worker thread em segundo plano
THREAD_WORKER_LOTES = threading.Thread(target=worker_processar_lotes, daemon=True)
THREAD_WORKER_LOTES.start()


# Progresso em tempo real para o frontend (thread-safe via GIL do Python)
PROGRESSO = {
    "ativo": False,
    "pagina_atual": 0,
    "total_paginas": 0,
    "questoes_encontradas": 0,
    "etapa": "",
    "inicio": 0,
    "tempo_por_pagina": 0,
}

def atualizar_progresso(pagina_atual=None, total_paginas=None, questoes_encontradas=None, etapa=None):
    """Atualiza o estado de progresso global para o frontend consultar."""
    if pagina_atual is not None:
        PROGRESSO["pagina_atual"] = pagina_atual
    if total_paginas is not None:
        PROGRESSO["total_paginas"] = total_paginas
    if questoes_encontradas is not None:
        PROGRESSO["questoes_encontradas"] = questoes_encontradas
    if etapa is not None:
        PROGRESSO["etapa"] = etapa
    # Calcula tempo médio por página
    if PROGRESSO["pagina_atual"] > 0 and PROGRESSO["inicio"] > 0:
        elapsed = time.time() - PROGRESSO["inicio"]
        PROGRESSO["tempo_por_pagina"] = elapsed / PROGRESSO["pagina_atual"]

# Injeta a função de progresso no módulo extrator para ele poder chamar
extrator.atualizar_progresso = atualizar_progresso

@app.route('/')
def index():
    """Renderiza a página principal da interface visual."""
    return render_template('index.html')

@app.route('/preview')
def preview():
    """Renderiza a página de pré-visualização isolada de uma questão."""
    return render_template('preview.html')

@app.route('/api/progresso')
def progresso_sse():
    """Endpoint SSE que envia atualizações de progresso em tempo real para o frontend."""
    def gerar_eventos():
        ultimo_estado = ""
        while True:
            estado_atual = json.dumps(PROGRESSO, ensure_ascii=False)
            if estado_atual != ultimo_estado:
                yield f"data: {estado_atual}\n\n"
                ultimo_estado = estado_atual
            if not PROGRESSO["ativo"]:
                yield f"data: {json.dumps({'ativo': False, 'etapa': 'concluido'})}\n\n"
                break
            time.sleep(0.5)
    
    return Response(gerar_eventos(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no'
    })

@app.route('/api/validar-questoes', methods=['POST'])
def validar_questoes_api():
    """Recalcula a qualidade após alterações feitas no editor."""
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict) or not isinstance(dados.get("questoes"), list):
        return jsonify({"erro": "Envie uma lista de questões para validação."}), 400

    questoes = validar_questoes(dados["questoes"])
    DADOS_MEMORIA["questoes"] = questoes
    return jsonify({"questoes": questoes})
@app.route('/api/processar', methods=['POST'])
def processar_pdf():
    """Recebe o PDF de questões, faz o processamento local determinístico
    de colunas e Regex offline em segundos e retorna as questões estruturadas."""
    try:
        # Verifica se o arquivo foi enviado
        if 'questoes_pdf' not in request.files:
            return jsonify({"erro": "Nenhum arquivo de questões enviado."}), 400
            
        file = request.files['questoes_pdf']
        if file.filename == '':
            return jsonify({"erro": "Nenhum arquivo selecionado."}), 400
            
        # Salva localmente na pasta do projeto
        caminho_salvo = os.path.join(app.config['UPLOAD_FOLDER'], "questoes.pdf.pdf")
        file.save(caminho_salvo)
        
        # Inicializa o progresso em tempo real
        PROGRESSO["ativo"] = True
        PROGRESSO["pagina_atual"] = 0
        PROGRESSO["total_paginas"] = 0
        PROGRESSO["questoes_encontradas"] = 0
        PROGRESSO["etapa"] = "Preparando..."
        PROGRESSO["inicio"] = time.time()
        PROGRESSO["tempo_por_pagina"] = 0
        
        # Parâmetros de IA Local/Nuvem passados pelo formulário para segmentação e OCR
        usar_ia_local = request.form.get('usar_ia_local', 'false').lower() == 'true'
        usar_ocr = request.form.get('usar_ocr', 'false').lower() == 'true'
        provedor = request.form.get('provedor', 'ollama').strip()
        api_key = request.form.get('api_key', '').strip()
        model = request.form.get('model', '').strip()
        endpoint = request.form.get('endpoint', '').strip()
        
        # Se usar_ocr for True, força o OCR via IA
        ocr_provedor = provedor if usar_ocr else None
        
        if usar_ia_local:
            print(f"[*] Solicitado processamento via IA ({provedor.upper()}) com o modelo '{model}'...")
            questoes = extrator.parsear_questoes_ia_local(
                caminho_salvo,
                provedor=provedor,
                model=model,
                endpoint=endpoint,
                api_key=api_key
            )
        else:
            # Executa a extração offline robusta determinística (Regex/Máquina de Estados)
            # Passa parâmetros de OCR caso o PDF seja digitalizado/imagem
            texto = extrator.extrair_texto_pdf_colunas(
                caminho_salvo,
                ocr_provedor=ocr_provedor,
                ocr_api_key=api_key,
                ocr_model=model,
                ocr_endpoint=endpoint
            )
            if not texto:
                return jsonify({"erro": "Falha ao extrair texto do PDF. O PDF pode estar digitalizado (imagem) e nenhuma chave de API ou provedor de OCR por IA foi configurado no painel lateral."}), 500
            questoes = extrator.parsear_questoes_local(texto)
            
            # Diagnóstico: salva texto extraído se nenhuma questão foi detectada
            if len(questoes) == 0:
                caminho_diag = os.path.join(app.config['UPLOAD_FOLDER'], "diagnostico_texto_extraido.txt")
                with open(caminho_diag, "w", encoding="utf-8") as f:
                    f.write(texto)
                print(f"[!] ATENÇÃO: 0 questões detectadas. Texto extraído salvo em '{caminho_diag}' para diagnóstico.")
                
                # Mostra as primeiras 30 linhas no log para diagnóstico rápido
                import re as _re
                linhas = [l.strip() for l in texto.split('\n') if l.strip()]
                print("[*] Primeiras 30 linhas extraídas do PDF:")
                for i, l in enumerate(linhas[:30]):
                    l_sem_html = _re.sub(r'<[^>]+>', '', l)
                    print(f"  {i+1:3d}: {l_sem_html[:120]}")
                
                return jsonify({
                    "erro": (
                        "Nenhuma questão foi detectada neste PDF. "
                        "O arquivo 'diagnostico_texto_extraido.txt' foi salvo na pasta do projeto para análise. "
                        "Possíveis causas: (1) O PDF está digitalizado (imagem) — tente habilitar OCR via IA. "
                        "(2) O formato de numeração das questões é diferente do padrão (ex: 'Q1', '1 -', 'QUESTÃO 1:' com dois pontos). "
                        "(3) A prova inicia em uma numeração diferente de 1. "
                        "Verifique o console do servidor para ver as primeiras linhas extraídas."
                    ),
                    "total": 0,
                    "questoes": []
                }), 422
            

        atualizar_progresso(etapa="Extraindo imagens das alternativas...")
        questoes = extrator.extrair_imagens_alternativas_pdf(caminho_salvo, questoes)
        atualizar_progresso(etapa="Extraindo imagens dos enunciados...")
        questoes = extrator.extrair_imagens_enunciado_pdf(caminho_salvo, questoes)
        
        # Finaliza progresso
        PROGRESSO["ativo"] = False
        PROGRESSO["etapa"] = "concluido"
        
        # Valida qualidade das questões extraídas
        questoes = validar_questoes(questoes)
        
        # Guarda na memória temporária do servidor
        DADOS_MEMORIA["questoes"] = questoes
        DADOS_MEMORIA["gabaritos"] = {}
        
        return jsonify({
            "mensagem": f"Sucesso! {len(questoes)} questões estruturadas com sucesso de forma 100% local!",
            "total": len(questoes),
            "questoes": questoes
        })
        
    except Exception as e:
        PROGRESSO["ativo"] = False
        PROGRESSO["etapa"] = "erro"
        return jsonify({"erro": f"Erro interno no processamento do PDF: {str(e)}"}), 500

@app.route('/api/gabarito-gemini', methods=['POST'])
def extrair_gabarito_gemini():
    """Envia o PDF de gabarito em imagem para a API do Gemini extrair as respostas
    de forma 100% automática e retorna o mapeamento de letras."""
    try:
        if 'gabarito_pdf' not in request.files:
            return jsonify({"erro": "Nenhum arquivo de gabarito enviado."}), 400
            
        file = request.files['gabarito_pdf']
        if file.filename == '':
            return jsonify({"erro": "Nenhum arquivo selecionado."}), 400
            
        # Obtém a extensão original do arquivo para que a API do Gemini identifique o Mime Type correto (PDF ou Imagem)
        ext = os.path.splitext(file.filename)[1].lower()
        if not ext:
            ext = '.pdf'
            
        caminho_salvo = os.path.join(app.config['UPLOAD_FOLDER'], f"gabarito_temp{ext}")
        file.save(caminho_salvo)
        
        # Tenta a chamada inteligente da API do Provedor de IA
        provedor = request.form.get('provedor', 'gemini').strip()
        api_key = request.form.get('api_key', '').strip()
        model = request.form.get('model', '').strip()
        endpoint = request.form.get('endpoint', '').strip()
        
        gabarito_map = extrator.extrair_gabarito_multiprovedor(
            caminho_salvo, 
            provedor=provedor, 
            api_key=api_key, 
            model=model, 
            endpoint=endpoint
        )
        
        if not gabarito_map or len(gabarito_map) == 0:
            return jsonify({
                "erro": "A IA não conseguiu ler as respostas do arquivo enviado (retornou um gabarito vazio). DICA: Tire um print ou tire uma foto apenas da tabela de respostas e envie em formato de imagem (PNG ou JPG) no botão de IA."
            }), 500
            
        # Converte as chaves do dicionário para strings para o JSON do JS
        gabarito_json = {str(k): v for k, v in gabarito_map.items()}
        DADOS_MEMORIA["gabaritos"] = gabarito_json
        
        return jsonify({
            "mensagem": f"Gabarito extraído com sucesso pela IA ({provedor.upper()})!",
            "gabaritos": gabarito_json
        })
        
    except Exception as e:
        msg_erro = str(e)
        prov_nome = provedor.upper() if 'provedor' in locals() else "IA"
        if "API_KEY_INVALID" in msg_erro or "API key not valid" in msg_erro or "invalid_api_key" in msg_erro:
            msg_erro = f"A Chave de API do {prov_nome} fornecida é inválida. Por favor, gere uma nova chave no painel do provedor e cole nas configurações de IA."
        elif "429" in msg_erro or "Quota exceeded" in msg_erro or "insufficient_quota" in msg_erro:
            msg_erro = f"Limite de cota excedido (Erro 429) no provedor {prov_nome}. Verifique seus créditos/faturamento (contas novas da OpenAI exigem inserção de créditos para funcionar) ou mude o provedor de IA."
        return jsonify({"erro": f"Erro na decodificação por IA ({prov_nome}): {msg_erro}"}), 500

@app.route('/api/gerar-comentario', methods=['POST'])
def gerar_comentario_questao():
    """Gera o comentário didático para uma única questão de cada vez, permitindo
    que o frontend exiba uma barra de progresso fluida em tempo real."""
    try:
        dados = request.json
        if not dados or 'questao' not in dados:
            return jsonify({"erro": "Dados da questão ausentes."}), 400
            
        q = dados['questao']
        gabarito = dados.get('gabarito', 'A')
        provedor = dados.get('provedor', 'gemini').strip()
        api_key = dados.get('api_key', '').strip()
        model = dados.get('model', '').strip()
        endpoint = dados.get('endpoint', '').strip()
        
        # Atualiza o gabarito na questão recebida
        q['Gabarito'] = gabarito
        
        # Cria a chamada individual e otimizada do Provedor de IA para gerar o comentário rico
        lista_questao = [q]
        lista_comentada = extrator.gerar_comentarios_ricos_multiprovedor(
            lista_questao, 
            provedor=provedor, 
            api_key=api_key, 
            model=model, 
            endpoint=endpoint
        )
        questao_final = lista_comentada[0]
        
        return jsonify({
            "mensagem": f"Comentário da Questão {q['Numero']} gerado!",
            "questao": questao_final
        })
        
    except Exception as e:
        msg_erro = str(e)
        if "API_KEY_INVALID" in msg_erro or "API key not valid" in msg_erro or "invalid_api_key" in msg_erro:
            msg_erro = f"A Chave de API fornecida para o provedor {provedor.upper()} é inválida. Por favor, gere uma nova chave ativa no painel do provedor e cole no painel lateral."
        elif "429" in msg_erro or "Quota exceeded" in msg_erro or "insufficient_quota" in msg_erro:
            msg_erro = f"Limite de cota excedido (Erro 429) no provedor {provedor.upper()}. Por favor, verifique seus créditos, troque o provedor de IA ou gere uma nova chave de API limpa."
        return jsonify({"erro": f"Erro na geração do comentário via {provedor.upper()}: {msg_erro}"}), 500

@app.route('/api/refinar-questao', methods=['POST'])
def refinar_questao():
    """Envia uma única questão para a IA limpar ruídos de cabeçalho, rodapé ou formatação."""
    try:
        dados = request.json
        if not dados or 'questao' not in dados:
            return jsonify({"erro": "Dados da questão ausentes."}), 400
            
        q = dados['questao']
        provedor = dados.get('provedor', 'gemini').strip()
        api_key = dados.get('api_key', '').strip()
        model = dados.get('model', '').strip()
        endpoint = dados.get('endpoint', '').strip()
        
        questao_refinada = extrator.refinar_questao_com_ia(
            q, 
            provedor=provedor, 
            api_key=api_key, 
            model=model, 
            endpoint=endpoint
        )
        
        return jsonify({
            "mensagem": f"Questão {q['Numero']} refinada com sucesso!",
            "questao": questao_refinada
        })
        
    except Exception as e:
        msg_erro = str(e)
        if "API_KEY_INVALID" in msg_erro or "API key not valid" in msg_erro or "invalid_api_key" in msg_erro:
            msg_erro = f"A Chave de API fornecida para o provedor {provedor.upper()} é inválida."
        return jsonify({"erro": f"Erro ao refinar questão via {provedor.upper()}: {msg_erro}"}), 500


@app.route('/api/exportar', methods=['POST'])
def exportar_csv():
    """Recebe os dados das questões finais preenchidas no painel visual e grava
    o arquivo CSV de importação em lote com ponto-e-vírgula e codificação correta."""
    try:
        dados = request.json
        if not dados or 'questoes' not in dados:
            return jsonify({"erro": "Nenhum dado de questões enviado para exportação."}), 400
            
        questoes_finais = validar_questoes(dados['questoes'])
        
        # Garante a estrutura correta de colunas exigida pelo importador
        df = pd.DataFrame(questoes_finais)
        
        colunas_wp = [
            "Enunciado", "Texto_Associado", "Opcao_A", "Opcao_B", "Opcao_C", "Opcao_D", "Opcao_E",
            "Gabarito", "Disciplina", "Assunto", "Banca", "Instituicao", "Cargo",
            "Ano", "Carreira", "Formacao", "Escolaridade", "Dificuldade", "Comentario", "Video_URL"
        ]
        
        # Blindagem de campos ausentes
        for col in colunas_wp:
            if col not in df.columns:
                df[col] = ""
                
        df = df[colunas_wp]
        
        # Grava o CSV final na pasta do projeto
        caminho_csv = os.path.join(app.config['UPLOAD_FOLDER'], ARQUIVO_SAIDA_CSV)
        df.to_csv(caminho_csv, sep=";", index=False, encoding="utf-8-sig")
        
        return jsonify({
            "mensagem": "Planilha CSV exportada com sucesso!",
            "caminho": caminho_csv,
            "total": len(df)
        })
        
    except Exception as e:
        return jsonify({"erro": f"Erro ao exportar planilha CSV: {str(e)}"}), 500

@app.route('/api/baixar-csv')
def baixar_csv():
    """Garante o download direto do CSV gerado no navegador do usuário."""
    caminho_csv = os.path.join(app.config['UPLOAD_FOLDER'], ARQUIVO_SAIDA_CSV)
    if os.path.exists(caminho_csv):
        return send_file(caminho_csv, as_attachment=True, download_name=ARQUIVO_SAIDA_CSV)
    else:
        return "Arquivo CSV de exportação não encontrado.", 404

@app.route('/api/exportar-json', methods=['POST'])
def exportar_json():
    """Recebe os dados das questões finais preenchidas no painel visual e grava
    o arquivo JSON de importação contendo todas as imagens e comentários."""
    try:
        dados = request.json
        if not dados or 'questoes' not in dados:
            return jsonify({"erro": "Nenhum dado de questões enviado para exportação."}), 400
            
        questoes_finais = validar_questoes(dados['questoes'])
        
        caminho_json = os.path.join(app.config['UPLOAD_FOLDER'], ARQUIVO_SAIDA_JSON)
        with open(caminho_json, 'w', encoding='utf-8') as f:
            json.dump(questoes_finais, f, ensure_ascii=False, indent=2)
            
        return jsonify({
            "mensagem": "Arquivo JSON exportado com sucesso contendo todas as imagens!",
            "caminho": caminho_json,
            "total": len(questoes_finais)
        })
        
    except Exception as e:
        return jsonify({"erro": f"Erro ao exportar arquivo JSON: {str(e)}"}), 500

@app.route('/api/baixar-json')
def baixar_json():
    """Garante o download direto do JSON gerado no navegador do usuário."""
    caminho_json = os.path.join(app.config['UPLOAD_FOLDER'], ARQUIVO_SAIDA_JSON)
    if os.path.exists(caminho_json):
        return send_file(caminho_json, as_attachment=True, download_name=ARQUIVO_SAIDA_JSON)
    else:
        return "Arquivo JSON de exportação não encontrado.", 404

@app.route('/api/aquecer-ia', methods=['POST'])
def aquecer_ia():
    """Rota assíncrona para pré-carregar o modelo no Ollama, evitando
    o atraso de inicialização fria (cold start) no envio de gabaritos."""
    try:
        dados = request.json or {}
        provedor = dados.get('provedor', '').strip().lower()
        model = dados.get('model', '').strip()
        endpoint = dados.get('endpoint', '').strip()
        
        if provedor == 'ollama' and model:
            base_url = endpoint if endpoint else "http://localhost:11434"
            url = f"{base_url.rstrip('/')}/api/generate"
            
            def rodar_warmup():
                import requests
                try:
                    payload = {
                        "model": model,
                        "prompt": "",
                        "keep_alive": "10m"
                    }
                    # O timeout é curto (5s) para soltar o Flask rapidamente, o Ollama cuidará do resto
                    requests.post(url, json=payload, timeout=5)
                    print(f"[+] Ollama Warm-up: Modelo '{model}' carregado com sucesso via background thread.")
                except Exception as ex:
                    print(f"[-] Ollama Warm-up: Falha ao pré-carregar modelo '{model}': {ex}")
                    
            import threading
            threading.Thread(target=rodar_warmup, daemon=True).start()
            return jsonify({"mensagem": "Iniciado aquecimento do Ollama em segundo plano."})
            
        return jsonify({"mensagem": "Provedor não requer aquecimento."})
    except Exception as e:
        return jsonify({"erro": str(e)}), 500

# ==============================================================================
# ENDPOINTS DE PROCESSAMENTO EM LOTE (WordPress & Async API)
# ==============================================================================

@app.route('/api/lote/upload', methods=['POST'])
def lote_upload():
    """Recebe múltiplos arquivos PDF de uma só vez para processamento em fila assíncrona."""
    try:
        files = request.files.getlist('pdf_files')
        if not files or len(files) == 0:
            files = [file for k, file in request.files.items() if file.filename]
            
        if not files:
            return jsonify({"erro": "Nenhum arquivo PDF enviado no lote."}), 400
            
        batch_id = str(uuid.uuid4())[:8]
        pasta_lote = os.path.join(app.config['UPLOAD_FOLDER'], 'uploads_lotes', f"lote_{batch_id}")
        os.makedirs(pasta_lote, exist_ok=True)
        
        autocorrigir_ia = request.form.get('autocorrigir_ia', 'true').lower() == 'true'
        provedor = request.form.get('provedor', 'gemini').strip()
        api_key = request.form.get('api_key', '').strip()
        model = request.form.get('model', '').strip()
        endpoint = request.form.get('endpoint', '').strip()
        usar_ocr = request.form.get('usar_ocr', 'false').lower() == 'true'
        refinar_todas = request.form.get('refinar_todas', 'false').lower() == 'true'
        wp_site_url = request.form.get('wp_site_url', '').strip()
        
        arquivos_lote = []
        for idx, file in enumerate(files):
            if not file.filename or not file.filename.lower().endswith('.pdf'):
                continue
            nome_seguro = f"{idx+1:02d}_{file.filename}"
            caminho_salvo = os.path.join(pasta_lote, nome_seguro)
            file.save(caminho_salvo)
            
            arquivos_lote.append({
                "id": f"{batch_id}_{idx+1}",
                "filename": file.filename,
                "caminho": caminho_salvo,
                "status": "pendente",
                "total_questoes": 0,
                "questoes": [],
                "erro": None
            })
            
        if not arquivos_lote:
            return jsonify({"erro": "Nenhum arquivo PDF válido foi encontrado."}), 400
            
        DADOS_LOTES[batch_id] = {
            "batch_id": batch_id,
            "status": "na_fila",
            "autocorrigir_ia": autocorrigir_ia,
            "provedor": provedor,
            "api_key": api_key,
            "model": model,
            "endpoint": endpoint,
            "usar_ocr": usar_ocr,
            "refinar_todas": refinar_todas,
            "wp_site_url": wp_site_url,
            "arquivos": arquivos_lote,
            "total_arquivos": len(arquivos_lote),
            "total_questoes_extraidas": 0,
            "cancelado": False,
            "inicio": None,
            "fim": None
        }
        
        # Enfileira o lote no worker assíncrono
        FILA_LOTES.put(batch_id)
        
        return jsonify({
            "mensagem": f"Lote #{batch_id} iniciado com sucesso! {len(arquivos_lote)} PDFs na fila de processamento.",
            "batch_id": batch_id,
            "total_arquivos": len(arquivos_lote),
            "status": "na_fila"
        })
        
    except Exception as e:
        return jsonify({"erro": f"Erro ao receber lote de arquivos: {str(e)}"}), 500

@app.route('/api/lote/status/<batch_id>', methods=['GET'])
def lote_status(batch_id):
    """Consulta o status em tempo real do processamento de um lote."""
    lote = DADOS_LOTES.get(batch_id)
    if not lote:
        return jsonify({"erro": "Lote não encontrado."}), 404
        
    resumo_arquivos = []
    concluidos = 0
    erros = 0
    
    for arq in lote["arquivos"]:
        if arq["status"] == "concluido":
            concluidos += 1
        elif arq["status"] == "erro":
            erros += 1
            
        resumo_arquivos.append({
            "id": arq["id"],
            "filename": arq["filename"],
            "status": arq["status"],
            "total_questoes": arq["total_questoes"],
            "erro": arq["erro"],
            "questoes": arq["questoes"] if request.args.get('incluir_questoes') == 'true' else None
        })
        
    return jsonify({
        "batch_id": batch_id,
        "status": lote["status"],
        "total_arquivos": lote["total_arquivos"],
        "concluidos": concluidos,
        "erros": erros,
        "total_questoes_extraidas": lote["total_questoes_extraidas"],
        "arquivos": resumo_arquivos,
        "inicio": lote.get("inicio"),
        "fim": lote.get("fim")
    })

@app.route('/api/lote/cancelar/<batch_id>', methods=['POST'])
def lote_cancelar(batch_id):
    """Cancela o processamento de um lote pendente."""
    lote = DADOS_LOTES.get(batch_id)
    if not lote:
        return jsonify({"erro": "Lote não encontrado."}), 404
        
    lote["cancelado"] = True
    lote["status"] = "cancelado"
    return jsonify({"mensagem": f"Lote #{batch_id} cancelado com sucesso."})

@app.route('/api/lote/listar', methods=['GET'])
def lote_listar():
    """Lista todos os lotes criados na sessão do servidor."""
    lista = []
    for b_id, lote in DADOS_LOTES.items():
        lista.append({
            "batch_id": b_id,
            "status": lote["status"],
            "total_arquivos": lote["total_arquivos"],
            "total_questoes_extraidas": lote["total_questoes_extraidas"],
            "wp_import_status": lote.get("wp_import_status"),
            "wp_import_mensagem": lote.get("wp_import_mensagem")
        })
    return jsonify({"lotes": lista})

@app.route('/api/lote/ultimo', methods=['GET'])
def lote_ultimo():
    """Retorna o lote mais recente para restauração automática no frontend."""
    if not DADOS_LOTES:
        return jsonify({"erro": "Nenhum lote recente encontrado."}), 404
    ultimo_id = list(DADOS_LOTES.keys())[-1]
    return lote_status(ultimo_id)



def abrir_navegador():
    """Abre a ferramenta visual automaticamente no navegador do usuário."""
    webbrowser.open_new("http://127.0.0.1:5000/")

if __name__ == '__main__':
    # Configura para abrir o navegador 1.5 segundos após iniciar o servidor
    Timer(1.5, abrir_navegador).start()
    
    print("=" * 80)
    # Servidor local Flask rodando na porta 5000
    app.run(host='127.0.0.1', port=5000, debug=False)
