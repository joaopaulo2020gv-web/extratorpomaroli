"""Script de diagnostico: testa uma pagina do PDF diretamente contra o Ollama e mostra a resposta bruta."""
import os
import sys
import json
import base64
import requests
import tempfile

try:
    import fitz
except ImportError:
    print("ERRO: PyMuPDF nao instalado. Rode: pip install PyMuPDF")
    sys.exit(1)

PDF_PATH = "questoes.pdf.pdf"
if not os.path.exists(PDF_PATH):
    PDF_PATH = "vunesp_prova.pdf"
if not os.path.exists(PDF_PATH):
    print("ERRO: Nenhum PDF encontrado na pasta")
    sys.exit(1)

MODEL = "qwen3-vl:2b"
OLLAMA_URL = "http://localhost:11434"

print(f"[*] Abrindo PDF: {PDF_PATH}")
doc = fitz.open(PDF_PATH)
total = len(doc)
print(f"[*] Total de paginas: {total}")

paginas_teste = [5, 6, 7, 10, 15]

for pag_idx in paginas_teste:
    if pag_idx >= total:
        continue
    
    print(f"\n{'='*80}")
    print(f"[*] TESTANDO PAGINA {pag_idx + 1}/{total}")
    print(f"{'='*80}")
    
    page = doc.load_page(pag_idx)
    pix = page.get_pixmap(dpi=200)
    img_bytes = pix.tobytes("png")
    arquivo_base64 = base64.b64encode(img_bytes).decode('utf-8')
    
    prompt = "Analise esta imagem de pagina de prova de concurso. Extraia todas as questoes visiveis e retorne como uma lista JSON. Se nao contiver questoes, retorne: []"
    
    system_prompt = "Voce e um assistente especializado em ler provas de concurso. Para cada questao, retorne um objeto JSON com: Numero (inteiro), Enunciado (texto), Opcao_A, Opcao_B, Opcao_C, Opcao_D, Opcao_E, Texto_Associado. Retorne APENAS o JSON."
    
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt, "images": [arquivo_base64]}
        ],
        "stream": False,
        "format": "json",
        "options": {"num_ctx": 8192}
    }
    
    print(f"[*] Enviando para Ollama ({MODEL})...")
    
    try:
        response = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, headers={"Content-Type": "application/json"})
        print(f"[*] HTTP Status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"[!] ERRO HTTP: {response.text[:500]}")
            continue
        
        res_json = response.json()
        print(f"[*] Chaves na resposta: {list(res_json.keys())}")
        
        conteudo = res_json.get('message', {}).get('content', '')
        print(f"\n[*] RESPOSTA BRUTA DO MODELO (primeiros 1500 chars):")
        print("-" * 60)
        print(conteudo[:1500])
        print("-" * 60)
        
        try:
            dados = json.loads(conteudo)
            if isinstance(dados, list):
                print(f"\n[+] JSON parseado: LISTA com {len(dados)} itens")
                for i, item in enumerate(dados[:3]):
                    if isinstance(item, dict):
                        print(f"  Item {i}: chaves = {list(item.keys())}")
                        if 'Numero' in item:
                            print(f"    Numero = {item['Numero']}, Enunciado = {str(item.get('Enunciado', ''))[:100]}")
                        elif 'numero' in item:
                            print(f"    numero = {item['numero']}")
            elif isinstance(dados, dict):
                print(f"\n[+] JSON parseado: DICT com chaves = {list(dados.keys())}")
                for k, v in dados.items():
                    if isinstance(v, list):
                        print(f"  Chave '{k}' contem LISTA com {len(v)} itens")
            else:
                print(f"\n[?] JSON tipo inesperado: {type(dados)}")
        except json.JSONDecodeError as e:
            print(f"\n[!] FALHA ao parsear JSON: {e}")
    
    except requests.exceptions.ConnectionError:
        print("[!] ERRO: Nao foi possivel conectar ao Ollama.")
        break
    except Exception as e:
        print(f"[!] ERRO: {e}")

doc.close()
print(f"\n[*] Diagnostico concluido.")
