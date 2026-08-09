import os
import sys
import json
import re
import base64
import requests
import pdfplumber
import pandas as pd
import google.generativeai as genai

try:
    import fitz # PyMuPDF
    PYMUPDF_DISPONIVEL = True
except ImportError:
    PYMUPDF_DISPONIVEL = False

# ==============================================================================
# CONFIGURAÇÕES DO PROJETO (WHITE LABEL & LOCAL)
# ==============================================================================
# Defina GEMINI_API_KEY no ambiente; nunca registre chaves diretamente no código.
# (Necessária apenas se desejar ler o gabarito ou gerar os comentários via IA de forma cirúrgica)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# Mapeia caminhos dos arquivos PDF locais
ARQUIVO_QUESTOES_PDF = "questoes.pdf.pdf" if os.path.exists("questoes.pdf.pdf") else "questoes.pdf"
ARQUIVO_GABARITO_PDF = "gabarito.pdf.pdf" if os.path.exists("gabarito.pdf.pdf") else "gabarito.pdf"

# Nome da planilha CSV gerada (Padrão de Importação do Plugin)
ARQUIVO_SAIDA_CSV = "questoes_importar.csv"

# Metadados padrões da prova para classificação do WordPress
BANCA_PADRAO = "Instituto AOCP"
ANO_PADRAO = "2025"
CARGO_PADRAO = "Policial Penal"
INSTITUICAO_PADRAO = "SEJUSP MG"
CARREIRA_PADRAO = "Policial"
FORMACAO_PADRAO = "Geral"
DIFICULDADE_PADRAO = "Médio"
ESCOLARIDADE_PADRAO = "Médio"

# Mapeamento para normalização de ligaduras tipográficas comuns em PDFs
LIGATURAS = {
    'ﬁ': 'fi',
    'ﬂ': 'fl',
    'ﬃ': 'ffi',
    'ﬄ': 'ffl',
    'ﬀ': 'ff',
    'œ': 'oe',
    'æ': 'ae',
    'Œ': 'OE',
    'Æ': 'AE'
}

def normalizar_texto_pdf(texto):
    """Realiza a normalização de aspas, travessões, espaços não-quebráveis e ligaduras."""
    if not texto:
        return texto
    
    # 1. Substitui ligaduras tipográficas
    for lig, repl in LIGATURAS.items():
        texto = texto.replace(lig, repl)
        
    # 2. Substitui aspas e travessões especiais para formato comum/ASCII
    substituicoes = {
        '“': '"', '”': '"',
        '‘': "'", '’': "'",
        '–': '-', '—': '-', '―': '-',
        '\u00a0': ' ',  # Espaço não-quebrável (NBSP)
        '\u00ad': '',   # Soft hyphen (remove totalmente pois é apenas quebra silábica invisível)
        '\u2010': '-',  # Hífen
        '\u2011': '-',  # Hífen não-quebrável
        '\u2012': '-',  # Figure dash
        '\u2013': '-',  # En dash
        '\u2014': '-',  # Em dash
        '\u2212': '-',  # Minus sign
    }
    for orig, dest in substituicoes.items():
        texto = texto.replace(orig, dest)
        
    # 3. Substitui símbolos lógicos/matemáticos comuns por entidades HTML amigáveis
    simbolos_mat = {
        '≥': '&ge;',
        '≤': '&le;',
        '≠': '&ne;',
        '±': '&plusmn;',
        '×': '&times;',
        '÷': '&divide;',
    }
    for orig, dest in simbolos_mat.items():
        texto = texto.replace(orig, dest)
        
    return texto



def detectar_corrupcao_texto(texto):
    """Detecta se o texto extraído do PDF está corrompido (garbage text devido a codificação de fontes).
    Retorna True se o texto parecer muito ilegível (baixa taxa de palavras reais)."""
    if not texto or len(texto.strip()) < 30:
        return False
        
    # Remove tags HTML para análise
    texto_limpo = re.sub(r'<[^>]+>', ' ', texto)
    
    # Palavras comuns em Língua Portuguesa
    palavras_comuns = {
        'o', 'a', 'os', 'as', 'um', 'uma', 'de', 'do', 'da', 'dos', 'das',
        'em', 'no', 'na', 'nos', 'nas', 'para', 'com', 'por', 'que', 'se',
        'um', 'uma', 'ao', 'aos', 'ou', 'e', 'como', 'mais', 'esta', 'este',
        'isso', 'aquilo', 'sobre', 'sob', 'entre', 'sua', 'seu', 'suas', 'seus'
    }
    
    # Encontra todas as palavras (sequências de letras) no texto
    palavras = re.findall(r'\b[a-zA-ZÀ-ÿ]+\b', texto_limpo.lower())
    if not palavras:
        return True # Sem nenhuma palavra com letras, está suspeito
        
    # Conta quantas palavras do texto são palavras válidas ou estão no conjunto comum
    validas = sum(1 for p in palavras if p in palavras_comuns or len(p) > 3)
    taxa_validas = validas / len(palavras)
    
    # Verifica caracteres estranhos/repetitivos (como quadrados ou sequências de símbolos)
    caracteres_estranhos = sum(1 for c in texto_limpo if c in ['☐', '☒', '🞎', '￮'])
    taxa_estranhos = caracteres_estranhos / len(texto_limpo) if len(texto_limpo) > 0 else 0
    
    # Se a taxa de palavras válidas for muito baixa (menos de 35%) ou tiver muitos caracteres estranhos, considera corrompido
    if taxa_validas < 0.35 or taxa_estranhos > 0.05:
        return True
        
    return False

def detectar_limite_superior_duas_colunas(page):
    """Detecta se há um cabeçalho de coluna única no topo da página
    e retorna a coordenada Y onde as duas colunas realmente começam."""
    meio = page.width / 2
    y_min = page.height * 0.02
    y_max = page.height * 0.3 # Limita a busca ao primeiro terço da página
    
    # Agrupa caracteres por suas coordenadas de linha Y
    linhas_y = {}
    for c in page.chars:
        if c['text'].isspace():
            continue
        if y_min <= c['top'] <= y_max:
            found = False
            for k in list(linhas_y.keys()):
                if abs(k - c['top']) < 3.0:
                    linhas_y[k].append(c)
                    found = True
                    break
            if not found:
                linhas_y[c['top']] = [c]
                
    # Procura a última linha de texto que atravessa o centro da página de forma contínua
    limite_y = y_min
    for y_top in sorted(linhas_y.keys()):
        chars_linha = sorted(linhas_y[y_top], key=lambda c: c['x0'])
        cruza_centro = False
        for c in chars_linha:
            if c['x0'] < meio - 15 and c['x1'] > meio + 15:
                cruza_centro = True
                break
                
        if not cruza_centro:
            left_chars = [c for c in chars_linha if c['x1'] < meio]
            right_chars = [c for c in chars_linha if c['x0'] >= meio]
            if left_chars and right_chars:
                max_left = max([c['x1'] for c in left_chars])
                min_right = min([c['x0'] for c in right_chars])
                if min_right - max_left < 10.0:
                    cruza_centro = True
        
        if cruza_centro:
            limite_y = max(limite_y, y_top + 10.0)
            
    return limite_y

# Definição das faixas de disciplinas da Prova SEJUSP MG (AOCP 2025)
def obter_meta_materia(num_questao):
    """Mapeia dinamicamente as disciplinas e assuntos oficiais da prova
    de acordo com o número da questão."""
    if 1 <= num_questao <= 10:
        return "Língua Portuguesa", "Interpretação de Texto e Gramática"
    elif 11 <= num_questao <= 15:
        return "Informática Básica", "Sistemas Operacionais, Pacote Office e Ameaças Digitais"
    elif 16 <= num_questao <= 32:
        return "Noções de Direito", "Direito Constitucional, Direito Penal e Processual"
    elif 33 <= num_questao <= 40:
        return "Direitos Humanos", "Declaração Universal, Corte IDH e Pactos Internacionais"
    else:
        return "Legislação Especial", "Lei de Execução Penal (LEP) e Regulamentos Estaduais"

# ==============================================================================
# DETECÇÃO AUTOMÁTICA DE BANCA, ANO, CARGO E ÓRGÃO
# ==============================================================================

MAPEAMENTO_BANCAS = [
    # (palavras-chave no PDF, nome oficial da banca)
    (['cebraspe', 'cespe'], 'CEBRASPE'),
    (['vunesp'], 'VUNESP'),
    (['fgv conhecimento', 'fgv projetos', 'fundacao getulio'], 'FGV'),
    (['fundacao carlos chagas', ' fcc '], 'FCC'),
    (['ibfc'], 'IBFC'),
    (['quadrix'], 'QUADRIX'),
    (['iades'], 'IADES'),
    (['idecan'], 'IDECAN'),
    (['objetiva concursos', 'objetiva software'], 'OBJETIVA'),
    (['fundep', 'gestao de concursos'], 'FUNDEP'),
    (['consulplan'], 'CONSULPLAN'),
    (['nc-ufpr', 'nucleo de concursos'], 'NC-UFPR'),
    (['faurgs'], 'FAURGS'),
    (['instituto aocp', 'aocp'], 'AOCP'),
    (['instituto acesso'], 'ACESSO'),
    (['copeve', 'ufal'], 'COPEVE-UFAL'),
    (['fepese'], 'FEPESE'),
    (['fafipa'], 'FAFIPA'),
    (['movimentar'], 'MOVIMENTAR'),
    (['fcc'], 'FCC'),
    (['enem', 'inep'], 'INEP/ENEM'),
]

def detectar_banca_do_pdf(texto_completo):
    """Detecta automaticamente a banca organizadora, ano, cargo e órgão
    a partir do texto extraído do PDF (geralmente presente no cabeçalho).
    Retorna um dicionário com os metadados detectados."""
    meta = {}
    # Usa apenas as primeiras 3000 chars (cabeçalho/capa) para performance
    amostra = re.sub(r'<[^>]+>', ' ', texto_completo[:3000]).lower()
    
    # Detecta banca
    for palavras_chave, nome_banca in MAPEAMENTO_BANCAS:
        if any(kw in amostra for kw in palavras_chave):
            meta['banca'] = nome_banca
            break
    
    # Detecta ano (formato 20XX ou 19XX)
    match_ano = re.search(r'\b(20[0-9]{2}|19[0-9]{2})\b', amostra)
    if match_ano:
        meta['ano'] = match_ano.group(1)
    
    # Detecta órgão/instituição por palavras-chave comuns em concursos brasileiros
    orgaos = [
        ('inss', 'INSS'), ('receita federal', 'Receita Federal'),
        ('tribunal de justica', 'Tribunal de Justiça'), ('tj ', 'Tribunal de Justiça'),
        ('ministerio publico', 'Ministério Público'), ('mp ', 'Ministério Público'),
        ('policia federal', 'Polícia Federal'), ('policia civil', 'Polícia Civil'),
        ('policia militar', 'Polícia Militar'), ('bombeiro', 'Corpo de Bombeiros'),
        ('prefeitura', 'Prefeitura Municipal'), ('camara municipal', 'Câmara Municipal'),
        ('senado', 'Senado Federal'), ('camara federal', 'Câmara dos Deputados'),
        ('tcu', 'TCU'), ('trf', 'TRF'), ('tst', 'TST'), ('stj', 'STJ'),
        ('banco do brasil', 'Banco do Brasil'), ('caixa economica', 'Caixa Econômica Federal'),
        ('petrobras', 'Petrobras'), ('correios', 'Correios'),
        ('sejusp', 'SEJUSP'), ('seap', 'SEAP'), ('senad', 'SENAD'),
    ]
    for kw, nome_orgao in orgaos:
        if kw in amostra:
            meta['instituicao'] = nome_orgao
            break
    
    if meta:
        partes = []
        if 'banca' in meta: partes.append(f"Banca={meta['banca']}")
        if 'ano' in meta: partes.append(f"Ano={meta['ano']}")
        if 'instituicao' in meta: partes.append(f"Orgao={meta['instituicao']}")
        print(f"[+] Metadados detectados automaticamente: {', '.join(partes)}")
    
    return meta

# ==============================================================================
# FASE 0: SUPORTE OCR E DETECÇÃO DINÂMICA DE LAYOUT
# ==============================================================================

def converter_pdf_para_imagens(caminho_pdf):
    """Converte todas as páginas do PDF em imagens PNG na memória."""
    imagens = []
    if not PYMUPDF_DISPONIVEL:
        print("[-] PyMuPDF não instalado. Não é possível rodar o fallback de OCR.")
        return imagens
        
    try:
        doc = fitz.open(caminho_pdf)
        for i in range(len(doc)):
            page = doc.load_page(i)
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            imagens.append((i, img_bytes))
    except Exception as e:
        print(f"[-] Erro ao converter PDF para imagens com PyMuPDF: {e}")
    return imagens

def extrair_texto_por_ocr(caminho_pdf, provedor="gemini", api_key=None, model=None, endpoint=None):
    """Renderiza as páginas do PDF como imagem e executa OCR estruturado via Vision IA."""
    print(f"[*] Iniciando OCR via Vision IA ({provedor.upper()})...")
    imagens = converter_pdf_para_imagens(caminho_pdf)
    if not imagens:
        print("[-] Nenhuma página convertida para imagem. Abortando OCR.")
        return None
        
    texto_completo = []
    prompt_ocr = """Você é um leitor de OCR de altíssima precisão. 
Transcreva todo o texto contido nesta página de prova de concurso. 
Preserve a formatação original do texto, mantendo as questões estruturadas em parágrafos.
Se houver duas colunas, leia primeiro a coluna da esquerda inteira, depois a da direita.
Não adicione observações, explicações extras ou cabeçalhos que não façam parte da prova. Transcreva apenas o texto contido na imagem."""

    import tempfile
    
    _progresso = getattr(sys.modules[__name__], 'atualizar_progresso', None)
    def _notificar(**kw):
        if _progresso:
            _progresso(**kw)
    
    for page_idx, img_bytes in imagens:
        print(f"[*] Executando OCR na página {page_idx + 1}/{len(imagens)}...")
        _notificar(pagina_atual=page_idx + 1, total_paginas=len(imagens),
                   etapa=f"Executando OCR na página {page_idx + 1} de {len(imagens)}...")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
            tmp_file.write(img_bytes)
            tmp_path = tmp_file.name
        
        try:
            modelo_vision = model
            if not modelo_vision:
                if provedor == "gemini":
                    modelo_vision = "gemini-2.5-flash"
                elif provedor == "openai":
                    modelo_vision = "gpt-4o-mini"
                elif provedor == "ollama":
                    modelo_vision = "qwen3-vl:2b"
                else:
                    modelo_vision = "gemini-2.5-flash"
                    
            resposta = chamar_api_ia(
                provedor=provedor,
                prompt=prompt_ocr,
                api_key=api_key,
                model=modelo_vision,
                endpoint=endpoint,
                is_image=True,
                caminho_imagem=tmp_path
            )
            # Adiciona com marcador de metadados padrão para o parser
            texto_completo.append(f"[METADADOS_PAGINA:{page_idx}:{page_idx+1}:esquerda]\n" + resposta)
        except Exception as e:
            print(f"[-] Erro no OCR da página {page_idx + 1}: {e}")
            # Fallback de string vazia para preservar numeração de páginas
            texto_completo.append(f"[METADADOS_PAGINA:{page_idx}:{page_idx+1}:esquerda]\n")
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except:
                    pass
        
        # Parseia as questões acumuladas até agora para informar o frontend em tempo real
        try:
            texto_parcial = "\n\n".join(texto_completo)
            questoes_parciais = parsear_questoes_local(texto_parcial)
            qtd_encontradas = len(questoes_parciais)
        except Exception:
            qtd_encontradas = 0

        _notificar(pagina_atual=page_idx + 1, total_paginas=len(imagens),
                   questoes_encontradas=qtd_encontradas,
                   etapa=f"Analisando página {page_idx + 1} de {len(imagens)} ({qtd_encontradas} questões encontradas)...")
                   
    return "\n\n".join(texto_completo)

def verificar_se_duas_colunas_pagina(page):
    """Analisa se uma página específica do PDF possui duas colunas,
    procurando por um corredor vertical vazio (calha) na faixa central do corpo."""
    if not page or not page.chars:
        return False
    
    total = len(page.chars)
    if total < 50:
        return False
        
    w = page.width
    min_crossings = total
    
    # Testa linhas verticais na faixa de 40% a 60% da largura, a cada 2 pontos
    start_x = int(w * 0.40)
    end_x = int(w * 0.60)
    
    for x in range(start_x, end_x, 2):
        # Conta caracteres do corpo (Y de 10% a 90%) que cruzam a linha x
        crossings = sum(1 for c in page.chars 
                        if c['x0'] < x < c['x1'] 
                        and not c['text'].isspace()
                        and page.height*0.1 < c['top'] < page.height*0.9)
        if crossings < min_crossings:
            min_crossings = crossings
            
    # Se encontramos pelo menos uma linha vertical central com menos de 5 cruzamentos,
    # significa que há um corredor em branco (calha), logo é duas colunas (DC).
    return min_crossings < 5

def detectar_meio_colunas(page):
    """Encontra dinamicamente a coordenada X que representa o vão entre as duas colunas
    para páginas com layout em duas colunas."""
    meio_padrao = page.width / 2
    if not page or not page.chars:
        return meio_padrao
        
    inicio_x = int(page.width * 0.40)
    fim_x = int(page.width * 0.60)
    
    passo = 2
    min_cruzamentos = len(page.chars)
    melhor_x = meio_padrao
    
    for x in range(inicio_x, fim_x, passo):
        cruzam = sum(1 for c in page.chars if c['x0'] < x < c['x1'] and not c['text'].isspace())
        if cruzam < min_cruzamentos:
            min_cruzamentos = cruzam
            melhor_x = x
            
    return melhor_x

def detectar_cabecalhos_rodapes_repetitivos(pdf):
    """Examina as margens superior e inferior de todas as páginas e mapeia 
    cabeçalhos e rodapés repetitivos que ocorrem em 2 ou mais páginas."""
    from collections import Counter
    linhas_topo = []
    linhas_base = []
    
    for page in pdf.pages:
        h = page.height
        # Topo (8% superior)
        topo_bbox = (0, 0, page.width, h * 0.08)
        try:
            cropped_topo = page.within_bbox(topo_bbox)
            txt_topo = cropped_topo.extract_text()
            if txt_topo:
                for l in txt_topo.split('\n'):
                    l_clean = l.strip()
                    if len(l_clean) > 5:
                        linhas_topo.append(l_clean)
        except:
            pass
            
        # Base (8% inferior)
        base_bbox = (0, h * 0.92, page.width, h)
        try:
            cropped_base = page.within_bbox(base_bbox)
            txt_base = cropped_base.extract_text()
            if txt_base:
                for l in txt_base.split('\n'):
                    l_clean = l.strip()
                    if len(l_clean) > 5:
                        linhas_base.append(l_clean)
        except:
            pass
            
    c_topo = Counter(linhas_topo)
    c_base = Counter(linhas_base)
    
    repetitivos = set()
    for k, count in c_topo.items():
        if count >= 2:
            repetitivos.add(k)
    for k, count in c_base.items():
        if count >= 2:
            repetitivos.add(k)
            
    return repetitivos

# ==============================================================================
# FASE 1: LEITURA DE TEXTO EM DUAS COLUNAS (LOCAL E OFFLINE)
# ==============================================================================


def remover_prefixo_html(html_str, num_chars_para_remover):
    """Remove o número especificado de caracteres de texto simples do início de uma string HTML,
    preservando as tags HTML."""
    res = []
    chars_removidos = 0
    i = 0
    while i < len(html_str):
        if html_str[i] == '<':
            fim_tag = html_str.find('>', i)
            if fim_tag != -1:
                res.append(html_str[i:fim_tag+1])
                i = fim_tag + 1
                continue
        
        if chars_removidos < num_chars_para_remover:
            chars_removidos += 1
        else:
            res.append(html_str[i])
        i += 1
    return "".join(res)

def limpar_tags_vazias(html_str):
    """Remove tags HTML vazias de forma recursiva até estabilizar."""
    antigo = ""
    while antigo != html_str:
        antigo = html_str
        html_str = re.sub(r'<(\w+)[^>]*>\s*</\1>', '', html_str)
    return html_str

def remover_hifens_quebra_linha(texto):
    if not texto:
        return texto
    
    # 1. Trata ênclises/mesóclises de pronomes múltiplos (ex: "realizar- se- lhe- á" -> "realizar-se-lhe-á")
    pronomes = r'(?:se|me|te|nos|vos|o|a|os|as|lhe|lhes|la|lo|las|los|na|no|nas|nos|á|ás|é|és|ia|ias|emos|eis|ão|ãos)'
    
    # Loop para juntar encadeamentos de pronomes com hífen
    for _ in range(3):
        texto = re.sub(rf'\b([A-Za-zÀ-ÿ]+)-\s+({pronomes})\b', r'\1-\2', texto)
        texto = re.sub(rf'\b({pronomes})-\s+([A-Za-zÀ-ÿ]+)\b', r'\1-\2', texto)
    
    # 2. Mantém hifens em palavras compostas por prefixos conhecidos (ex: "decreto- lei" -> "decreto-lei")
    prefixes = r'(?:anti|auto|contra|extra|infra|intra|neo|proto|pseudo|retro|semi|super|ultra|vice|co|ex|pre|pr[oó]|p[oó]s|sub|super|trans|inter|luso|afro|euro|latino|socio|politico|fisico|quimico|decreto|segunda|terca|terça|quarta|quinta|sexta|guarda|para|mao|mão|porta)'
    texto = re.sub(rf'\b({prefixes})-\s+([A-Za-zÀ-ÿ]+)\b', r'\1-\2', texto, flags=re.IGNORECASE)
    
    # 3. Para os demais casos de translineação (quebra de linha), remove o hífen (ex: "des- tacada" -> "destacada")
    texto = re.sub(r'\b([A-Za-zÀ-ÿ]+)-\s+([A-Za-zÀ-ÿ]+)\b', r'\1\2', texto)
    
    return texto

def eh_tabela_real(table):
    """Verifica se um objeto de tabela do pdfplumber é uma tabela de dados real,
    evitando blocos de layout e listas de opções."""
    data = table.extract()
    if not data or len(data) < 2:
        return False
    num_rows = len(data)
    num_cols = len(data[0])
    if num_cols < 2:
        return False
        
    # Evita tabelas com excesso de células vazias (típico de layouts)
    total_cells = num_rows * num_cols
    non_empty_cells = sum(1 for row in data for cell in row if cell is not None and str(cell).strip() != "")
    if total_cells == 0:
        return False
        
    # Conta linhas com múltiplos dados preenchidos
    rows_with_data = 0
    for row in data:
        filled_in_row = sum(1 for cell in row if cell is not None and str(cell).strip() != "")
        if filled_in_row >= 2:
            rows_with_data += 1
            
    if rows_with_data < 2:
        return False
        
    # Evita tabelas cuja primeira coluna contém opções como (A), (B) etc.
    pattern_opcao = re.compile(r'^\s*(?:\([A-E]\)|\[[A-E]\]|[A-E]\)\s|[A-E]\.\s)', re.IGNORECASE)
    for row in data:
        if row and row[0]:
            if pattern_opcao.match(str(row[0])):
                return False
                
    return True

def formatar_tabela_html(table, page):
    """Converte o objeto de tabela do pdfplumber em um elemento HTML <table> bem estruturado,
    preservando as tags de formatação e os subscritos químicos nas células."""
    html = []
    html.append('<div class="table-container" style="margin: 15px 0; overflow-x: auto; width: 100%;">')
    html.append('<table style="border-collapse: collapse; width: 100%; max-width: 100%; border: 1px solid #e2e8f0; font-family: sans-serif; font-size: 14px; text-align: center;">')
    
    for r_idx, row in enumerate(table.rows):
        is_header = (r_idx == 0)
        row_style = "background-color: #f8fafc; border-bottom: 2px solid #e2e8f0; font-weight: bold;" if is_header else "border-bottom: 1px solid #edf2f7;"
        html.append(f'  <tr style="{row_style}">')
        
        for cell in row.cells:
            if cell is None:
                continue
                
            x0, top, x1, bottom = cell
            cell_bbox = (x0 - 2.0, top - 2.0, x1 + 2.0, bottom + 2.0)
            
            try:
                cropped = page.within_bbox(cell_bbox)
                cell_text = extrair_texto_limpo(cropped, x_limite_palavra=1.2, in_table_cell=True).strip()
            except Exception as e:
                cell_text = ""
                
            cell_text = cell_text.replace('\n', '<br>')
            
            # Formata subscritos químicos (ex: Cu2O -> Cu<sub>2</sub>O, O2 -> O<sub>2</sub>)
            cell_text = re.sub(r'([A-Z][a-z]?)(\d+\b|\d+(?=[A-Z]))', r'\1<sub>\2</sub>', cell_text)
            
            tag = 'th' if is_header else 'td'
            cell_style = "padding: 10px; border: 1px solid #e2e8f0;"
            html.append(f'    <{tag} style="{cell_style}">{cell_text}</{tag}>')
            
        html.append('  </tr>')
        
    html.append('</table>')
    html.append('</div>')
    return "\n".join(html)
 
def extrair_texto_limpo(page, x_limite_palavra=1.2, in_table_cell=False):
    """Reconstrói o texto a partir das coordenadas físicas de cada caractere
    visível (não-espaço), inferindo os espaços legítimos por proximidade horizontal.
    Preserva negrito, itálico e sublinhado convertendo-os em tags HTML correspondentes.
    Ignora caracteres de tabelas reais para processá-los como tabelas HTML estruturadas."""
    if not page or not page.chars:
        return ""
        
    # Busca tabelas reais se não estivermos processando uma célula de tabela recursivamente
    real_tables = []
    if not in_table_cell:
        try:
            tables = page.find_tables({
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance": 8,
                "join_tolerance": 5,
                "intersection_tolerance": 5
            })
            if tables:
                for t in tables:
                    if eh_tabela_real(t):
                        real_tables.append(t)
        except Exception as e:
            print(f"[-] Erro ao buscar tabelas: {e}")
            
    table_bboxes = [t.bbox for t in real_tables]
    
    # Filtra caracteres fora das tabelas para o fluxo de texto geral
    chars = [dict(c) for c in page.chars]
    chars_no_tables = []
    for c in chars:
        if c['text'].isspace():
            continue
        # Ignora caracteres invisíveis ou de tamanho nulo
        if c.get('width', 0) <= 0.1 or c.get('height', 0) <= 0.1:
            continue
            
        # Ignora marcas d'água inclinadas (rotacionadas)
        if not c.get('upright', True):
            continue
            
        # Ignora marcas d'água com cor de preenchimento cinza muito clara (RGB, CMYK ou Greyscale)
        color = c.get('non_stroking_color')
        if color is not None:
            if isinstance(color, (list, tuple)):
                if len(color) == 3 and all(isinstance(v, (int, float)) and v > 0.82 for v in color):
                    continue
                elif len(color) == 4 and all(isinstance(v, (int, float)) and v < 0.18 for v in color):
                    continue
            elif isinstance(color, (int, float)) and color > 0.82:
                continue
        inside = False
        for bbox in table_bboxes:
            if (bbox[0] - 1.0 <= c['x0'] <= bbox[2] + 1.0) and (bbox[1] - 1.0 <= c['top'] <= bbox[3] + 1.0):
                inside = True
                break
        if not inside:
            chars_no_tables.append(c)
            
    chars = chars_no_tables
    
    # Reconstrução de frações empilhadas verticalmente (apenas para fluxo principal de texto)
    def char_faz_parte_de_palavra_texto(char, all_chars, group):
        grupo_ids = {id(x) for x in group}
        for other in all_chars:
            if id(other) in grupo_ids:
                continue
            if abs(other['top'] - char['top']) < 2.0:
                if abs(other['x1'] - char['x0']) < 3.0 or abs(char['x1'] - other['x0']) < 3.0:
                    return True
        return False

    frac_lines = []
    chars_to_remove = set()
    if not in_table_cell:
        if hasattr(page, "rects") and page.rects:
            for r in page.rects:
                if r.get('height', 0) < 1.5 and 3.0 < r.get('width', 0) < 30.0:
                    frac_lines.append({
                        'x0': r['x0'], 'x1': r['x1'], 'top': r['top'], 'bottom': r['bottom']
                    })
        if hasattr(page, "lines") and page.lines:
            for l in page.lines:
                h = abs(l.get('top', 0) - l.get('bottom', 0))
                w = abs(l.get('x1', 0) - l.get('x0', 0))
                if h < 1.5 and 3.0 < w < 30.0:
                    frac_lines.append({
                        'x0': min(l['x0'], l['x1']), 'x1': max(l['x0'], l['x1']),
                        'top': min(l['top'], l['bottom']), 'bottom': max(l['top'], l['bottom'])
                    })
                    
        for fl in frac_lines:
            chars_above = []
            chars_below = []
            for c in chars:
                if c['text'].isspace():
                    continue
                char_mid = (c['x0'] + c['x1']) / 2
                if fl['x0'] - 2 <= char_mid <= fl['x1'] + 2:
                    if fl['top'] - 10.0 <= c['bottom'] <= fl['top'] + 1.0:
                        chars_above.append(c)
                    elif fl['bottom'] - 1.0 <= c['top'] <= fl['bottom'] + 10.0:
                        chars_below.append(c)
                        
            if chars_above and chars_below:
                chars_above_sorted = sorted(chars_above, key=lambda c: c['x0'])
                chars_below_sorted = sorted(chars_below, key=lambda c: c['x0'])
                num_text = "".join([c['text'] for c in chars_above_sorted])
                den_text = "".join([c['text'] for c in chars_below_sorted])
                
                # Filtro para evitar converter falsos positivos (como bordas de tabelas com palavras normais)
                has_lowercase_word_num = re.search(r'[a-zà-ÿ]{2,}', num_text.lower())
                has_lowercase_word_den = re.search(r'[a-zà-ÿ]{2,}', den_text.lower())
                is_valid_num = len(num_text) <= 6 and not has_lowercase_word_num
                is_valid_den = len(den_text) <= 6 and not has_lowercase_word_den
                
                if is_valid_num and is_valid_den:
                    # Proteção para evitar engolir caracteres de palavras de texto regular
                    has_text_adj = False
                    for c_ab in chars_above:
                        if char_faz_parte_de_palavra_texto(c_ab, chars, chars_above):
                            has_text_adj = True
                            break
                    if not has_text_adj:
                        for c_bl in chars_below:
                            if char_faz_parte_de_palavra_texto(c_bl, chars, chars_below):
                                has_text_adj = True
                                break
                    if has_text_adj:
                        is_valid_num = False
                
                if is_valid_num and is_valid_den:
                    frac_text = f"{num_text}/{den_text}"
                    ref_top = fl['top'] - 3.2 # Alinhamento padrão
                    # Tenta sincronizar a coordenada vertical com caracteres adjacentes da mesma linha de texto
                    for c in chars:
                        if c not in chars_above and c not in chars_below:
                            if abs(c['top'] - (fl['top'] - 3.2)) < 5.0:
                                ref_top = c['top']
                                break
                                
                    first_char = chars_above_sorted[0]
                    first_char['text'] = frac_text
                    first_char['top'] = ref_top
                    first_char['bottom'] = ref_top + 10.0
                    
                    for c in chars_above_sorted[1:]:
                        chars_to_remove.add(id(c))
                    for c in chars_below_sorted:
                        chars_to_remove.add(id(c))
                        
    chars_clean = [c for c in chars if id(c) not in chars_to_remove]

    thin_rects = []
    if hasattr(page, "rects") and page.rects:
        thin_rects = [r for r in page.rects if r.get('height', 0) < 1.5]
        
    thin_lines = []
    if hasattr(page, "lines") and page.lines:
        thin_lines = [l for l in page.lines if abs(l.get('top', 0) - l.get('bottom', 0)) < 1.5]
        
    linhas = {}
    for c in chars_clean:
        if c['text'].isspace():
            continue
            
        # Agrupa caracteres que estão na mesma linha vertical (tolerância de 4.0 unidades para subscritos)
        linha_key = None
        for k in list(linhas.keys()):
            if abs(k - c['top']) < 4.0:
                linha_key = k
                break
                
        if linha_key is None:
            linha_key = c['top']
            linhas[linha_key] = []
            
        linhas[linha_key].append(c)
        
    rendering_items = []
    for top_linha in linhas.keys():
        rendering_items.append({
            'type': 'line',
            'top': top_linha,
            'chars': linhas[top_linha]
        })
        
    for t in real_tables:
        rendering_items.append({
            'type': 'table',
            'top': t.bbox[1],
            'table': t
        })
        
    rendering_items = sorted(rendering_items, key=lambda item: item['top'])
        
    texto_pag = []
    for item in rendering_items:
        if item['type'] == 'line':
            chars_linha = sorted(item['chars'], key=lambda c: c['x0'])
            if not chars_linha:
                continue
                
            # Determina a formatação para cada caractere
            line_styled_chars = []
            for c in chars_linha:
                font_lower = c.get('fontname', '').lower()
                is_bold = "bold" in font_lower or "black" in font_lower or "heavy" in font_lower
                is_italic = "italic" in font_lower or "oblique" in font_lower
                
                is_underlined = False
                for r in thin_rects:
                    if abs(r['top'] - c['bottom']) < 3.0:
                        if (r['x0'] - 2.0 <= c['x0'] <= r['x1'] + 2.0 or 
                            r['x0'] - 2.0 <= c['x1'] <= r['x1'] + 2.0 or 
                            (c['x0'] <= r['x0'] and c['x1'] >= r['x1'])):
                            is_underlined = True
                            break
                if not is_underlined:
                    for l in thin_lines:
                        if abs(l['top'] - c['bottom']) < 3.0:
                            if (l['x0'] - 2.0 <= c['x0'] <= l['x1'] + 2.0 or 
                                l['x0'] - 2.0 <= c['x1'] <= l['x1'] + 2.0 or 
                                (c['x0'] <= l['x0'] and c['x1'] >= l['x1'])):
                                is_underlined = True
                                break
                                
                line_styled_chars.append((c, is_bold, is_italic, is_underlined))
                
            texto_linha = ""
            current_b, current_i, current_u = False, False, False
            
            def close_tags(b, i, u):
                closed = ""
                if u:
                    closed += "</u>"
                if i:
                    closed += "</em>"
                if b:
                    closed += "</strong>"
                return closed
                
            def open_tags(b, i, u):
                opened = ""
                if b:
                    opened += "<strong>"
                if i:
                    opened += "<em>"
                if u:
                    opened += "<u>"
                return opened

            char_anterior = None
            for c, b, i, u in line_styled_chars:
                # Determina o limite de espaçamento dinamicamente com base no tamanho da fonte (kerning/tracking)
                font_size = c.get('size', 10.0)
                limite_espaco = max(1.1, min(font_size * 0.22, 2.5))
                
                # Normaliza o caractere individualmente (ligaduras, aspas, travessões, símbolos)
                char_text = normalizar_texto_pdf(c['text'])
                
                if char_anterior is not None:
                    distancia = c['x0'] - char_anterior['x1']
                    if distancia > limite_espaco:
                        if b == current_b and i == current_i and u == current_u:
                            texto_linha += " "
                        else:
                            texto_linha += close_tags(current_b, current_i, current_u)
                            texto_linha += " "
                            current_b, current_i, current_u = False, False, False

                if (b != current_b) or (i != current_i) or (u != current_u):
                    texto_linha += close_tags(current_b, current_i, current_u)
                    texto_linha += open_tags(b, i, u)
                    current_b, current_i, current_u = b, i, u
                    
                texto_linha += char_text
                char_anterior = c
                
            texto_linha += close_tags(current_b, current_i, current_u)
            texto_pag.append(texto_linha)
            
        elif item['type'] == 'table':
            html_tabela = formatar_tabela_html(item['table'], page)
            if html_tabela:
                texto_pag.append(html_tabela)
                
    # 3. Reconstrução Inteligente de Parágrafos (Evita quebras de linha físicas \n artificiais no meio de frases)
    res_linhas = []
    for idx_linha, linha in enumerate(texto_pag):
        if not res_linhas:
            res_linhas.append(linha)
            continue
            
        anterior = res_linhas[-1]
        
        # Limpa HTML da linha anterior e atual para analisar o texto puro nas extremidades
        ant_texto = re.sub(r'<[^>]+>', '', anterior).strip()
        at_texto = re.sub(r'<[^>]+>', '', linha).strip()
        
        if not ant_texto or not at_texto:
            res_linhas.append(linha)
            continue
            
        # Padrões que indicam que as linhas não devem ser unidas:
        # 1. Se a linha anterior termina com pontuação de fim de frase (., !, ?, :, ;, ou fechamento de aspas/parênteses)
        termina_pontuacao = ant_texto[-1] in ['.', '!', '?', ':', ';', '"', "'", ')']
        
        # 2. Se a linha atual parece o início de uma alternativa (ex: (A) ou A.)
        e_alternativa = re.match(r'^\s*(?:\([A-E]\)|\[[A-E]\]|[A-E]\)\s|[A-E]\.\s)', at_texto, re.IGNORECASE)
        
        # 3. Se a linha atual começa com letra maiúscula ou dígito (inicia nova frase, item de lista ou número)
        comeca_maiuscula_ou_digito = at_texto[0].isupper() or at_texto[0].isdigit()
        
        # 4. Se qualquer uma das duas linhas contiver tags de tabela
        tem_tabela = any(tag in anterior.lower() or tag in linha.lower() for tag in ["<table", "<tr", "<td", "<th", "</table>"])
        
        # 5. Se a linha anterior termina com hífen
        termina_com_hifen = ant_texto.endswith('-')
        
        # 6. Se a linha atual parece o início de uma questão (para evitar juntá-la com o fim do texto da questão anterior)
        e_inicio_questao = (
            re.match(r'^(?:Quest[aã]o|Questo|Questao|Q[\._-]?|Item)\s*[n\xba\xaa\xb0]?[\s.]*?(\d+)', at_texto, re.IGNORECASE) or
            re.match(r'^(\d+)\s*[\.\-\)\u2013\u2014]\s+', at_texto) or
            re.match(r'^(\d+)\s*(?:ª|º|°|ª\.|º\.)\s*(?:QUEST[AÃ]O|Questo|Questao|Q\.)', at_texto, re.IGNORECASE) or
            re.match(r'^(\d+)\s+[A-ZÁÀÃÂÉÈÊÍÏÓÔÕÚÜÇ"\']', at_texto)  # CEBRASPE: "1 Texto..."
        )
        
        if not tem_tabela and not e_alternativa and not e_inicio_questao and not termina_pontuacao and (not comeca_maiuscula_ou_digito or termina_com_hifen):
            # Une as linhas de forma inteligente
            if anterior.endswith('-'):
                res_linhas[-1] = anterior + linha
            else:
                res_linhas[-1] = anterior + " " + linha
        else:
            res_linhas.append(linha)
            
    return "\n".join(res_linhas)

def verificar_se_duas_colunas(pdf):
    """Analisa uma amostra das páginas do PDF (pulando a primeira se possível)
    e conta quantos caracteres cruzam a linha vertical média da página.
    Se a média for baixa, o PDF possui duas colunas verticais."""
    paginas_analisar = [p for p in pdf.pages if p.page_number > 1][:5]
    if not paginas_analisar:
        paginas_analisar = pdf.pages[:1]
        
    soma_cruzamentos = 0
    for p in paginas_analisar:
        meio = p.width / 2
        cruzamentos = sum(1 for c in p.chars if c['x0'] < meio < c['x1'] and not c['text'].isspace())
        soma_cruzamentos += cruzamentos
        
    media = soma_cruzamentos / len(paginas_analisar)
    print(f"[*] Média de cruzamentos no centro da página: {media:.2f}")
    return media < 5.0

def extrair_texto_pdf_colunas(caminho_pdf, ocr_provedor=None, ocr_api_key=None, ocr_model=None, ocr_endpoint=None):
    """Extrai o texto do PDF com base no layout detectado (coluna única ou duas colunas)
    avaliado página a página. Caso o PDF seja digitalizado/escaneado (sem texto vetorial),
    executa o OCR inteligente automaticamente se configurado."""
    if not os.path.exists(caminho_pdf):
        print(f"[-] Arquivo PDF não encontrado: {caminho_pdf}")
        return None
        
    # 1. Verifica se o PDF possui texto selecionável
    possui_texto = False
    try:
        with pdfplumber.open(caminho_pdf) as pdf_temp:
            total_chars = 0
            for p in pdf_temp.pages[:3]: # Checa as primeiras 3 páginas
                if p.chars:
                    total_chars += len(p.chars)
            if total_chars > 150:
                possui_texto = True
    except Exception as e:
        print(f"[-] Erro ao checar texto do PDF: {e}")

    # Se não tiver texto selecionável e tivermos OCR configurado, roda OCR fallback
    if (not possui_texto or ocr_provedor) and ocr_provedor not in [None, '', 'false']:
        print("[*] PDF detectado como ESCANEADO/IMAGEM ou OCR explicitamente ativado.")
        return extrair_texto_por_ocr(caminho_pdf, provedor=ocr_provedor, api_key=ocr_api_key, model=ocr_model, endpoint=ocr_endpoint)
    elif not possui_texto:
        print("[-] ATENÇÃO: O PDF parece digitalizado/imagem e nenhuma configuração de OCR por IA foi fornecida.")

    print(f"[*] Analisando layout e extraindo texto vetorial de '{caminho_pdf}'...")
    paginas_texto = []
    
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            # Detecta cabeçalhos e rodapés repetitivos de forma inteligente
            linhas_repetitivas = detectar_cabecalhos_rodapes_repetitivos(pdf)
            print(f"[+] Detectadas {len(linhas_repetitivas)} linhas repetitivas de cabeçalho/rodapé para filtragem dinâmica.")
            
            for i, page in enumerate(pdf.pages):
                # Extrai o texto de forma simples para busca de palavras-chave administrativas
                txt_simples = page.extract_text() or ""
                txt_simples_lower = txt_simples.lower()
                
                # Cover page check
                has_alternatives = re.search(r'^\s*(?:\([A-E]\)|[A-E]\)|[A-E]\.\s*\(\s*\)|[A-E]\.\s+|\[[A-E]\])', txt_simples, re.MULTILINE)
                cover_terms = ["duração:", "duracao:", "leia atentamente", "caderno de questões", "folha de resposta", "instruções abaixo"]
                if any(term in txt_simples_lower for term in cover_terms) and not has_alternatives:
                    print(f"[*] Ignorando página {i+1} por ser detectada como capa/instruções.")
                    continue

                termos_ignorar = [
                    "orientações aos candidatos",
                    "orientacoes aos candidatos",
                    "gabarito preliminar",
                    "gabarito oficial",
                    "instruções aos candidatos",
                    "instrucoes aos candidatos",
                    "folha de respostas",
                    "folha de resposta",
                    "folha de rascunho",
                    "rascunho"
                ]
                
                if any(termo in txt_simples_lower for termo in termos_ignorar) and not has_alternatives:
                    print(f"[*] Ignorando página {i+1} do PDF por conter termos administrativos.")
                    continue
                
                # 1. Executa extração vetorial rápida preliminar para verificação de corrupção de fontes
                txt_preliminar = page.extract_text() or ""
                corrompido = detectar_corrupcao_texto(txt_preliminar)
                
                if corrompido:
                    print(f"[!] Detectada corrupção de fontes/codificação na página {page.page_number}. Ativando OCR Fallback para esta página...")
                    import tempfile
                    
                    img_bytes = None
                    if PYMUPDF_DISPONIVEL:
                        try:
                            doc_temp = fitz.open(caminho_pdf)
                            page_fitz = doc_temp.load_page(i)
                            pix = page_fitz.get_pixmap(dpi=150)
                            img_bytes = pix.tobytes("png")
                            doc_temp.close()
                        except Exception as e_render:
                            print(f"[-] Erro ao renderizar página {page.page_number} para OCR: {e_render}")
                            
                    if img_bytes:
                        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
                            tmp_file.write(img_bytes)
                            tmp_path = tmp_file.name
                            
                        try:
                            # Determina modelo de OCR com base nos parâmetros ou usa padrão gemini
                            modelo_vision = ocr_model or "gemini-2.5-flash"
                            provedor_ocr = ocr_provedor or "gemini"
                            
                            prompt_ocr = """Você é um leitor de OCR de altíssima precisão. 
                            Transcreva todo o texto contido nesta página de prova de concurso. 
                            Preserve a formatação original do texto, mantendo as questões estruturadas em parágrafos.
                            Se houver duas colunas, leia primeiro a coluna da esquerda inteira, depois a da direita.
                            Não adicione observações, explicações extras ou cabeçalhos que não façam parte da prova. Transcreva apenas o texto contido na imagem."""
                            
                            txt_ocr = chamar_api_ia(
                                provedor=provedor_ocr,
                                prompt=prompt_ocr,
                                api_key=ocr_api_key,
                                model=modelo_vision,
                                endpoint=ocr_endpoint,
                                is_image=True,
                                caminho_imagem=tmp_path
                            )
                            
                            if txt_ocr and txt_ocr.strip():
                                if txt_ocr.startswith("```"):
                                    txt_ocr = "\n".join(txt_ocr.splitlines()[1:-1]).strip()
                                paginas_texto.append(f"[METADADOS_PAGINA:{i}:{page.page_number}:esquerda]\n" + txt_ocr)
                                try:
                                    os.remove(tmp_path)
                                except:
                                    pass
                                continue
                        except Exception as err_ocr:
                            print(f"[-] Erro ao executar OCR de fallback na página {page.page_number}: {err_ocr}")
                        try:
                            os.remove(tmp_path)
                        except:
                            pass
                    else:
                        print("[-] OCR Fallback não pôde ser executado: PyMuPDF indisponível ou falha de renderização.")
                
                # Detecção de colunas em nível de página individual
                duas_colunas = verificar_se_duas_colunas_pagina(page)
                
                def limpar_texto_linha(txt):
                    if not txt:
                        return ""
                    linhas_limpas = []
                    for l in txt.split('\n'):
                        l_strip = l.strip()
                        # Se a linha contém marcador/início de questão, NUNCA descarta como cabeçalho/rodapé
                        parece_linha_questao = bool(re.search(r'^\s*(?:<[^>]+>)*\s*(?:\d+[\s.ªº°]|quest[aã]o|item\b)', l_strip, re.IGNORECASE))
                        if not parece_linha_questao:
                            # Se a linha faz parte dos cabeçalhos repetitivos detectados, ignora
                            if l_strip in linhas_repetitivas:
                                continue
                            # Ignora se corresponder a padrões comuns de número de página ou rodapé dinâmico
                            if re.search(r'^\s*(?:p[aá]gina|pag|pag\.)\s*\d+\s*(?:de\s*\d+)?\s*$', l_strip, re.IGNORECASE):
                                continue
                            if re.search(r'^\s*\d+\s*/\s*\d+\s*$', l_strip): # Ex: "5 / 12"
                                continue
                            if re.search(r'^\s*(?:<[^>]+>)*\s*(?:centro\s+de\s+recrutamento|busca\s+pela\s+excel[êe]ncia|prova\s+para\s+admiss[ãa]o|concurso\s+p[úu]blico\s+para)', l_strip, re.IGNORECASE):
                                continue
                        linhas_limpas.append(l)
                    return "\n".join(linhas_limpas)

                y0 = page.height * 0.02
                y1 = page.height * 0.97

                if duas_colunas:
                    meio = detectar_meio_colunas(page)
                    # 2. Segmentação de Layout Multi-Região: Detecta se há um cabeçalho/título de coluna única no topo
                    limite_y = detectar_limite_superior_duas_colunas(page)
                    
                    txt_topo = ""
                    if limite_y > y0 + 10.0:
                        # Extrai a região superior (cabeçalho da página) como coluna única
                        topo_box = page.within_bbox((0, y0, page.width, limite_y))
                        txt_topo = extrair_texto_limpo(topo_box, x_limite_palavra=1.2)
                        txt_topo = limpar_texto_linha(txt_topo)
                    
                    # Recorta e extrai a coluna da esquerda com margens seguras e Y do limite_y
                    esquerda = page.within_bbox((0, limite_y, meio, y1))
                    txt_esq = extrair_texto_limpo(esquerda, x_limite_palavra=1.2)
                    txt_esq = limpar_texto_linha(txt_esq)
                    
                    # Recorta e extrai a coluna da direita com margens seguras e Y do limite_y
                    direita = page.within_bbox((meio, limite_y, page.width, y1))
                    txt_dir = extrair_texto_limpo(direita, x_limite_palavra=1.2)
                    txt_dir = limpar_texto_linha(txt_dir)
                    
                    # Une o cabeçalho e as duas colunas
                    texto_pagina = []
                    if txt_topo and txt_topo.strip():
                        texto_pagina.append(txt_topo)
                    if txt_esq and txt_esq.strip():
                        texto_pagina.append(txt_esq)
                    
                    txt_acumulado_esquerda = "\n\n".join(texto_pagina)
                    
                    texto_completo_pagina = []
                    if txt_acumulado_esquerda.strip():
                        texto_completo_pagina.append(f"[METADADOS_PAGINA:{i}:{page.page_number}:esquerda]\n" + txt_acumulado_esquerda)
                    if txt_dir and txt_dir.strip():
                        texto_completo_pagina.append(f"[METADADOS_PAGINA:{i}:{page.page_number}:direita]\n" + txt_dir)
                        
                    if texto_completo_pagina:
                        paginas_texto.append('\n\n'.join(texto_completo_pagina))
                else:
                    # Recorta as margens superior e inferior para eliminar cabeçalhos e rodapés
                    pagina_cortada = page.within_bbox((0, y0, page.width, y1))
                    txt = extrair_texto_limpo(pagina_cortada, x_limite_palavra=1.2)
                    txt = limpar_texto_linha(txt)
                    if txt and txt.strip():
                        paginas_texto.append(f"[METADADOS_PAGINA:{i}:{page.page_number}:esquerda]\n" + txt)
                
        print("[+] Extração de texto concluída com sucesso!")
        return '\n\n'.join(paginas_texto)
    except Exception as e:
        print(f"[-] Erro ao ler e processar layout do PDF: {e}")
        return None

# ==============================================================================
# FASE 2: PARSER DETERMINÍSTICO (REGEX & MÁQUINA DE ESTADOS LOCAL)
# ==============================================================================

def parsear_questoes_local(texto_completo):
    """Varre as linhas do texto extraído utilizando uma máquina de estados robusta.
    Detecta os números das questões, os enunciados e as opções de A a E."""
    print("[*] Iniciando análise gramatical e estrutural das questões por Regex local...")
    
    # Correção de espaçamentos estranhos de caracteres do PDF (Wide Tracking / Character Spacing)
    texto_completo = texto_completo.replace("E m m u n i c í p i o q u e n ã o", "Em município que não")
    texto_completo = texto_completo.replace("E m m u n i c í p i o q u e n ão", "Em município que não")
    texto_completo = texto_completo.replace("e x p e d i d o", "expedido")
    texto_completo = texto_completo.replace("q u e s e a f i r m a", "que se afirma")
    texto_completo = texto_completo.replace("N o r m a s d e P r", "Normas de Pr")
    
    linhas = [l.strip() for l in texto_completo.split('\n')]
    
    questoes = []
    questao_atual = None
    estado = None  # 'enunciado', 'opcao_a', 'opcao_b', etc.
    texto_acumulado_inicial = []
    
    apoios_mapeados = {}
    blocos_compartilhados = []
    texto_de_apoio_atual = []
    questoes_do_apoio_atual = []
    
    num_esperado = 1
    materia_atual = None
    assunto_atual = None
    
    # Auto-detecta banca, ano e órgão do cabeçalho do PDF
    meta_detectada = detectar_banca_do_pdf(texto_completo)
    banca_detectada    = meta_detectada.get('banca', BANCA_PADRAO)
    ano_detectado      = meta_detectada.get('ano', ANO_PADRAO)
    instituicao_detectada = meta_detectada.get('instituicao', INSTITUICAO_PADRAO)
    

    def eh_numero_questao_aceitavel(num, num_esperado, estado, questao_atual):
        if not questao_atual:
            return 1 <= num <= 200
        # Pequeno salto/lacuna ou sequência exata (ex: se o PDF saltou uma questão ou foi mal lida)
        if num_esperado <= num <= num_esperado + 3:
            return True
        # Se já saímos do enunciado e estamos lendo alternativas, permitimos reiniciar do 1
        if estado in ['opcao_a', 'opcao_b', 'opcao_c', 'opcao_d', 'opcao_e']:
            if num == 1:
                return True
        return False
    
    current_page_idx = 0
    current_page_num = 1
    current_col = 'esquerda'
    
    for linha in linhas:
        if not linha:
            continue
            
        # Detecção dinâmica de matérias
        linha_limpa_materias = re.sub(r'<[^>]+>', '', linha).strip().lower()
        if linha_limpa_materias in ["língua portuguesa", "lingua portuguesa"]:
            materia_atual, assunto_atual = "Língua Portuguesa", "Interpretação de Texto e Gramática"
        elif linha_limpa_materias in ["matemática", "matematica", "raciocínio lógico e matemático", "raciocínio lógico"]:
            materia_atual, assunto_atual = "Matemática", "Raciocínio Lógico e Matemática"
        elif linha_limpa_materias in ["noções básicas de informática", "noções de informática", "informática básica", "informatica basica"]:
            materia_atual, assunto_atual = "Informática Básica", "Sistemas Operacionais, Pacote Office e Ameaças Digitais"
        elif linha_limpa_materias in ["noções de direito", "noções básicas de direito"]:
            materia_atual, assunto_atual = "Noções de Direito", "Direito Constitucional, Direito Penal e Processual"
        elif linha_limpa_materias in ["direitos humanos", "direitos humanos e cidadania"]:
            materia_atual, assunto_atual = "Direitos Humanos", "Declaração Universal, Corte IDH e Pactos Internacionais"
        elif linha_limpa_materias in ["conhecimentos gerais", "atualidades"]:
            materia_atual, assunto_atual = "Atualidades", "Atualidades e Conhecimentos Gerais"
        elif "história geral" in linha_limpa_materias:
            materia_atual, assunto_atual = "História", "História Geral"
        elif "história do brasil" in linha_limpa_materias:
            materia_atual, assunto_atual = "História", "História do Brasil"
        elif "geografia geral" in linha_limpa_materias:
            materia_atual, assunto_atual = "Geografia", "Geografia Geral"
        elif "geografia do brasil" in linha_limpa_materias:
            materia_atual, assunto_atual = "Geografia", "Geografia do Brasil"
        elif "administração pública" in linha_limpa_materias or "administracao publica" in linha_limpa_materias:
            materia_atual, assunto_atual = "Legislação Especial", "Direito Administrativo e Administração Pública"
            
        # Detecta marcador de metadados de página
        match_meta = re.match(r'^\[METADADOS_PAGINA:(\d+):(\d+):(\w+)\]$', linha)
        if match_meta:
            current_page_idx = int(match_meta.group(1))
            current_page_num = int(match_meta.group(2))
            current_col = match_meta.group(3)
            continue
            
        # Cria uma versão limpa sem tags HTML apenas para as validações de Regex
        linha_sem_html = re.sub(r'<[^>]+>', '', linha)
        linha_lower = linha_sem_html.lower()
        linha_clean = linha_lower.strip()
        
        # Se chegamos à seção de redação / prova discursiva, encerramos a extração de questões de múltipla escolha!
        if (linha_clean in ["redação", "redacao", "prova de redação", "prova de redacao", "folha de redação", "folha de redacao", "prova discursiva"] or
            "instruções para a redação" in linha_lower or "instrucoes para a redacao" in linha_lower or
            "prova discursiva" in linha_lower or "proposta de redação" in linha_lower or "proposta de redacao" in linha_lower or
            "a redação para os cargos" in linha_lower or "a redacao para os cargos" in linha_lower or
            "critérios de avaliação" in linha_lower or "criterios de avaliacao" in linha_lower):
            print("[*] Seção de Redação/Discursiva detectada. Encerrando o parsing de questões.")
            break
            
        # Ignora linhas avulsas muito curtas (ex: letras ou números perdidos de corte de coluna),
        # exceto se for o número da questão isolado ou contiver tags HTML de tabela/div.
        if len(linha_clean) < 3 and not re.match(r'^\d+$', linha_clean):
            if not any(tag in linha.lower() for tag in ["<td", "<th", "<tr", "<table", "</table>", "</td>", "</th>", "</tr>", "<div", "</div>"]):
                continue
            
        # Filtro de cabeçalhos/rodapés específicos de cargo/prova (ex: "100 - Cadete BM - TIPO A")
        if re.search(r'^\d+\s*[-–]\s*cadete\s+bm', linha_lower) or re.search(r'\bcadete\s+bm\s*[-–]\s*tipo', linha_lower):
            continue
            
        # Filtros de rodapé com número de página (suporta Tipo Branca - Página 12)
        if re.search(r'tipo\s+\w+\s*[-–]\s*p[aá]gina\s+\d+', linha_lower) or re.search(r'\bp[aá]gina\s+\d+\b', linha_lower):
            continue
            
        # Verifica se a linha original começa com tag de negrito (metadados visuais)
        linha_original_clean = linha.strip()
        comeca_negrito = (
            linha_original_clean.startswith("<strong>") or 
            linha_original_clean.startswith("<b>") or 
            linha_original_clean.startswith("<span style=\"font-weight:bold")
        )
        
        # Verifica se a linha parece o início de uma questão (para evitar descartá-la indevidamente)
        parece_questao = (
            re.match(r'^(?:Quest[aã]o|Questo|Questao|Q[\._-]?|Item)\s*[n\xba\xaa\xb0]?[\s.]*?(\d+)', linha_sem_html, re.IGNORECASE) or
            re.match(r'^(\d+)\s*[\.\-\)\u2013\u2014]\s+', linha_sem_html) or
            re.match(r'^(\d+)\s*(?:ª|º|°|ª\.|º\.)\s*(?:QUEST[AÃ]O|Questo|Questao|Q\.)', linha_sem_html, re.IGNORECASE) or
            (comeca_negrito and re.match(r'^\s*(\d+)\s*$', linha_sem_html)) or
            re.match(r'^(\d+)\s+[A-ZÁÀÃÂÉÈÊÍÏÓÔÕÚÜÇ"\']', linha_sem_html)  # CEBRASPE: "1 Texto..."
        )
        
        if not parece_questao:
            # Filtro para módulos/capítulos com numeração romana (ex: M II, Módulo IV)
            if re.search(r'\b(módulo|modulo|mód|ódulo|m\s+[ivx]+)\b', linha_lower) and len(linha_clean) < 60:
                continue
                
            palavras_ignorar = [
                "investigador de pol", "escrivão de pol", "escrivao de pol",
                "noções de", "nocoes de", "noões de", "nooes de",
                "onhecimentos", "específicos", "especificos", "specíficos", "specificos",
                "básicos", "basicos", "ásicos", "asicos",
                "tipo branca", "tipo amarela", "tipo azul", "tipo verde",
                "página", "pagina", "t1932001n", "instituto aocp",
                "pcmg", "minas gerais", "governo do estado", "secretaria de estado"
            ]
            if any(kw in linha_clean for kw in palavras_ignorar) and len(linha_clean) < 60:
                continue

            
        # Filtro de rodapé específico de cursos ou provas para evitar falsos positivos
        if re.search(r'\d+\s*-\s*soldado\s+bombeiro', linha_lower) or re.search(r'cfsd\s+bm', linha_lower):
            continue
            
        # Filtro de linhas puramente decorativas (linhas de sublinhado, hifens, etc.)
        if re.match(r'^[\s_–\-\*]*$', linha_sem_html):
            if not any(tag in linha.lower() for tag in ["<td", "<th", "<tr", "<table", "</table>", "</td>", "</th>", "</tr>", "<div", "</div>"]):
                continue
            
        # Se a linha parece o início de uma questão, salvamos o texto de apoio pendente
        # e limpamos o estado para que ela seja parseada normalmente pela máquina de estados.
        if parece_questao:
            if estado == 'texto_de_apoio' and texto_de_apoio_atual:
                texto_apoio_html = "<br>".join(texto_de_apoio_atual).strip()
                match_num = (
                    re.match(r'^(?:Quest[aã]o|Questo|Questao|Q[\._-]?|Item)\s*[n\xba\xaa\xb0]?[\s.]*?(\d+)', linha_sem_html, re.IGNORECASE) or
                    re.match(r'^(\d+)\s*[\.\-\)\u2013\u2014]\s+(.*)', linha_sem_html) or
                    re.match(r'^(\d+)\s*(?:ª|º|°|ª\.|º\.)\s*(?:QUEST[AÃ]O|Questo|Questao|Q\.)', linha_sem_html, re.IGNORECASE) or
                    re.match(r'^(\d+)\s+[A-ZÁÀÃÂÉÈÊÍÏÓÔÕÚÜÇ"\']', linha_sem_html)  # CEBRASPE
                )
                num_detectado_temp = int(match_num.group(1)) if match_num else num_esperado
                
                if not questoes_do_apoio_atual:
                    questoes_do_apoio_atual = [num_detectado_temp]
                for q_num in questoes_do_apoio_atual:
                    apoios_mapeados[q_num] = texto_apoio_html
                blocos_compartilhados.append(list(questoes_do_apoio_atual))
                print(f"[+] Finalizado bloco de apoio para questões: {questoes_do_apoio_atual}")
                
                texto_de_apoio_atual = []
                questoes_do_apoio_atual = []
            if estado == 'texto_de_apoio':
                estado = None

        # Verifica se a linha indica transição para um novo bloco de texto de apoio
        eh_inicio_apoio = False
        
        if not parece_questao:
            # 1. Padrão explícito de responder a questões (Ex: "questões 01 e 02", "questões de 13 a 15")
            match_bloco_apoio = re.search(
                r'quest[õo]es\s+(?:de\s+)?(\d+)\s*(?:a|e|às|,)\s*(\d+)(?:\s*(?:e|,)\s*(\d+))?', 
                linha_lower
            )
            if match_bloco_apoio:
                if estado != 'texto_de_apoio':
                    eh_inicio_apoio = True
                elif questoes_do_apoio_atual:
                    n1_temp = int(match_bloco_apoio.group(1))
                    if n1_temp not in questoes_do_apoio_atual:
                        eh_inicio_apoio = True
                else:
                    eh_inicio_apoio = True
                    
            # 2. Títulos de Texto (Ex: "TEXTO 1", "Texto II", "Tira 1")
            if not eh_inicio_apoio and estado not in ['enunciado', 'opcao_a', 'opcao_b', 'opcao_c', 'opcao_d', 'opcao_e'] and re.match(r'^(?:texto|text|tira|tirinha|poema|infográfico|tabela|gráfico)\s+[ivx\d]+', linha_clean):
                eh_inicio_apoio = True
                
            # 3. Comando de leitura no início (Ex: "Leia a tira...")
            if not eh_inicio_apoio and estado not in ['enunciado', 'opcao_a', 'opcao_b', 'opcao_c', 'opcao_d', 'opcao_e'] and re.match(r'^(?:leia|considere|analise)\s+(?:o|a|os|as)\s+(?:texto|tira|tirinha|poema|infográfico|tabela|gráfico|imagem)', linha_clean):
                eh_inicio_apoio = True

            # 4. Padrões típicos do CEBRASPE para novos blocos ("Julgue os itens...", "A respeito de...", "Com relação a...")
            if not eh_inicio_apoio and re.match(r'^(?:julgue\s+os\s+itens|a\s+respeito\s+d[eo]|com\s+rela[çc][ãa]o\s+a|tendo\s+por\s+base|considerando\s+os\s+aspectos)\b', linha_clean):
                eh_inicio_apoio = True

        if eh_inicio_apoio:
            # Se estávamos em uma questão ativa (enunciado/alternativa), salva a questão anterior e fecha seu estado
            if questao_atual:
                questoes.append(questao_atual)
                questao_atual = None
                
            # Se vínhamos de um texto de apoio anterior e havia questões associadas, salva-as
            if estado == 'texto_de_apoio' and texto_de_apoio_atual:
                texto_apoio_html = "<br>".join(texto_de_apoio_atual).strip()
                if questoes_do_apoio_atual:
                    for q_num in questoes_do_apoio_atual:
                        apoios_mapeados[q_num] = texto_apoio_html
                    blocos_compartilhados.append(list(questoes_do_apoio_atual))
            
            estado = 'texto_de_apoio'
            texto_de_apoio_atual = [linha]
            if match_bloco_apoio:
                n1 = int(match_bloco_apoio.group(1))
                n2 = int(match_bloco_apoio.group(2))
                conectivo = re.search(r'quest[õo]es\s+(?:de\s+)?\d+\s+([a-z,]+)\s+\d+', linha_lower)
                tipo_con = conectivo.group(1).strip() if conectivo else "e"
                if 'a' in tipo_con or 'à' in tipo_con:
                    questoes_do_apoio_atual = list(range(n1, n2 + 1))
                else:
                    questoes_do_apoio_atual = [n1, n2]
                    if match_bloco_apoio.group(3):
                        questoes_do_apoio_atual.append(int(match_bloco_apoio.group(3)))
                print(f"[*] Detectado novo bloco de apoio para questões: {questoes_do_apoio_atual}")
            else:
                questoes_do_apoio_atual = []
            continue

        # Se já estamos em bloco de apoio e a linha não inicia um novo apoio, acumula
        if estado == 'texto_de_apoio' and not parece_questao:
            if not questoes_do_apoio_atual and match_bloco_apoio:
                n1 = int(match_bloco_apoio.group(1))
                n2 = int(match_bloco_apoio.group(2))
                conectivo = re.search(r'quest[õo]es\s+(?:de\s+)?\d+\s+([a-z,]+)\s+\d+', linha_lower)
                tipo_con = conectivo.group(1).strip() if conectivo else "e"
                if 'a' in tipo_con or 'à' in tipo_con:
                    questoes_do_apoio_atual = list(range(n1, n2 + 1))
                else:
                    questoes_do_apoio_atual = [n1, n2]
                    if match_bloco_apoio.group(3):
                        questoes_do_apoio_atual.append(int(match_bloco_apoio.group(3)))
                print(f"[*] Vinculado range tardio ao bloco de apoio: {questoes_do_apoio_atual}")
            texto_de_apoio_atual.append(linha)
            continue

        # Verifica transição de disciplina para limpar o estado e evitar vazamento
        eh_disciplina = False
        if linha_lower in [
            "língua portuguesa", "lingua portuguesa",
            "literatura",
            "noções de língua inglesa", "nocoes de lingua inglesa", "noções de lingua inglesa",
            "noções de direito e direitos humanos", "noções de direito", "direitos humanos",
            "raciocínio lógico-matemático", "raciocínio lógico", "raciocinio logico",
            "informática básica", "informatica basica",
            "legislação especial", "legislacao especial"
        ] or any(disc in linha_lower for disc in ["noções de língua inglesa", "noções de direito e direitos humanos", "raciocínio lógico-matemático"]):
            eh_disciplina = True
            
        if eh_disciplina:
            estado = None
            continue
        # TENTATIVA DE DETECTAR QUESTÃO (HÍBRIDO E SEQUENCIAL)
        eh_questao = False
        num_detectado = None
        resto_enunciado = ""
        
        # Ignora linhas que pertencem a tabelas HTML para detecção de questões
        eh_linha_tabela = any(tag in linha.lower() for tag in ["<td", "<th", "<tr", "<table", "</table>", "</td>", "</th>", "</tr>"])
        
        if not eh_linha_tabela:
            # 1. Padrão explícito: "Questão N", "Q. N", "Q1", "Q-1", "Item N", "Questão nº N" etc.
            match_q = re.match(
                r'^(?:Quest[a\xE3]o|Questo|Questao|Q[\._\-]?|Item)\s*[n\xba\xaa\xb0]?[\s.]*?(\d+)'
                r'(?:\b|[\.<br>\-\):]|$)(.*)',
                linha_sem_html, re.IGNORECASE)
            if match_q:
                num = int(match_q.group(1))
                if eh_numero_questao_aceitavel(num, num_esperado, estado, questao_atual):
                    eh_questao = True
                    num_detectado = num
                    resto_enunciado = remover_prefixo_html(linha, match_q.start(2))
                    resto_enunciado = limpar_tags_vazias(resto_enunciado).strip()
                    
            # 2. Padrão numérico com pontuação separadora: "1. ", "02 - ", "3) ", "01 \u2013 " (travessão)
            if not eh_questao:
                match_n = re.match(r'^(\d+)\s*[\.\-\)\u2013\u2014]\s+(.*)', linha_sem_html)
                if match_n:
                    num = int(match_n.group(1))
                    if eh_numero_questao_aceitavel(num, num_esperado, estado, questao_atual):
                        eh_questao = True
                        num_detectado = num
                        resto_enunciado = remover_prefixo_html(linha, match_n.start(2))
                        resto_enunciado = limpar_tags_vazias(resto_enunciado).strip()
                        
            # 3. Padrão número solitário na linha (ex: "1", "02")
            if not eh_questao:
                match_s = re.match(r'^(\d+)$', linha_sem_html)
                if match_s:
                    num = int(match_s.group(1))
                    if eh_numero_questao_aceitavel(num, num_esperado, estado, questao_atual):
                        eh_questao = True
                        num_detectado = num
                        resto_enunciado = ""
                        
            # 4. Padrão ordinal: "1\xaa QUEST\xc3O - ", "1\xba Quest\xe3o:" etc.
            if not eh_questao:
                match_ord = re.match(
                    r'^(\d+)\s*(?:\xaa|\xba|\xb0|\xaa\.|\xba\.)\s*(?:QUEST[A\xc3]O|Questo|Questao|Q\.)\s*[-\u2013\.]?\s*(.*)',
                    linha_sem_html, re.IGNORECASE)
                if match_ord:
                    num = int(match_ord.group(1))
                    if eh_numero_questao_aceitavel(num, num_esperado, estado, questao_atual):
                        eh_questao = True
                        num_detectado = num
                        resto_enunciado = remover_prefixo_html(linha, match_ord.start(2))
                        resto_enunciado = limpar_tags_vazias(resto_enunciado).strip()

            # 5. Padrão CEBRASPE/CESPE: n\xfamero + espa\xe7o + texto mai\xfasculo (ex: "1 Conclui-se...")
            if not eh_questao:
                match_ceb = re.match(r'^(\d+)\s+([A-Z\xc1\xc0\xc3\xc2\xc9\xc8\xca\xcd\xcf\xd3\xd4\xd5\xda\xdc\xc7"\'].+)', linha_sem_html)
                if match_ceb:
                    num = int(match_ceb.group(1))
                    if eh_numero_questao_aceitavel(num, num_esperado, estado, questao_atual):
                        eh_questao = True
                        num_detectado = num
                        resto_enunciado = remover_prefixo_html(linha, match_ceb.start(2))
                        resto_enunciado = limpar_tags_vazias(resto_enunciado).strip()
                        
        if eh_questao and num_detectado:
            # Se vínhamos de um texto de apoio anterior, salva-o e mapeia para as questões
            if estado == 'texto_de_apoio' and texto_de_apoio_atual:
                texto_apoio_html = "<br>".join(texto_de_apoio_atual).strip()
                if not questoes_do_apoio_atual:
                    questoes_do_apoio_atual = [num_detectado]
                for q_num in questoes_do_apoio_atual:
                    apoios_mapeados[q_num] = texto_apoio_html
                blocos_compartilhados.append(list(questoes_do_apoio_atual))
                
                texto_de_apoio_atual = []
                questoes_do_apoio_atual = []

            # Salva a questão anterior se já finalizada
            if questao_atual:
                questoes.append(questao_atual)
            
            materia, assunto = obter_meta_materia(num_detectado)
            if materia_atual:
                materia = materia_atual
            if assunto_atual:
                assunto = assunto_atual
            questao_atual = {
                'Numero': num_detectado,
                'Page_Idx': current_page_idx,
                'Page_Num': current_page_num,
                'Column': current_col,
                'Enunciado': resto_enunciado,
                'Texto_Associado': '',
                'Opcao_A': '',
                'Opcao_B': '',
                'Opcao_C': '',
                'Opcao_D': '',
                'Opcao_E': '',
                'Gabarito': '',
                'Disciplina': materia,
                'Assunto': assunto,
                'Banca': banca_detectada,
                'Instituicao': instituicao_detectada,
                'Cargo': CARGO_PADRAO,
                'Ano': ano_detectado,
                'Carreira': CARREIRA_PADRAO,
                'Formacao': FORMACAO_PADRAO,
                'Dificuldade': DIFICULDADE_PADRAO,
                'Escolaridade': ESCOLARIDADE_PADRAO,
                'Comentario': '',
                'Video_URL': '',
                'Tem_Alternativas': False,
                'Tipo_Questao': 'multipla_escolha'  # Será 'certo_errado' se detectado
            }
            num_esperado = num_detectado + 1
            estado = 'enunciado'
            continue
                
        if not questao_atual:
            # Acumula o texto lido antes de iniciar a Questão 1 (Texto de Apoio da Prova de Português)
            # Evitamos acumular cabeçalhos repetitivos da capa e instruções de preenchimento do edital
            cabecalhos_ignorar = [
                "T1932001N", "GOVERNO DO ESTADO", "SECRETARIA DE ESTADO", 
                "EDITAL DE CONCURSO", "POLICIAL PENAL", 
                "Após a autorização", "A segurança ganha força", "PROVA", 
                "Nível", "MÉDIO", "Material recebido", "Material a ser devolvido", 
                "Duração da prova", "Divulgação", "institutoaocp", "SEJUSP (MG)",
                "INSTITUTO AOCP", "Tipo 01", "Página", "Língua Portuguesa"
            ]
            if not any(cab.lower() in linha_lower for cab in cabecalhos_ignorar):
                texto_acumulado_inicial.append(linha)
            continue
            
        # Detecta a transição de texto para as alternativas
        # Suporta: (A) / A) / A. / [A] / A.() / a) / (a) / a. (maiúsculas e minúsculas)
        match_alt_1 = re.match(r'^\(([A-Ea-e])\)\s*(.*)', linha_sem_html)          # (A) / (a)
        match_alt_2 = re.match(r'^([A-Ea-e])\.\s*\(\s*\)\s*(.*)', linha_sem_html)  # A.() marcação
        match_alt_3 = re.match(r'^([A-Ea-e])\)\s*(.*)', linha_sem_html)            # A) / a)
        match_alt_4 = re.match(r'^([A-Ea-e])\.\s+(.*)', linha_sem_html)           # A. / a.
        match_alt_5 = re.match(r'^\[([A-Ea-e])\]\s*(.*)', linha_sem_html)         # [A] / [a]
        match_alt_6 = re.match(r'^([A-Ea-e])\s+-\s+(.*)', linha_sem_html)         # A - texto (FGV)
        
        match_alt = match_alt_1 or match_alt_2 or match_alt_3 or match_alt_4 or match_alt_5 or match_alt_6
        
        if match_alt:
            letra = match_alt.group(1).upper()
            # O texto da opção contendo as tags HTML
            texto_opcao = remover_prefixo_html(linha, match_alt.start(2))
            texto_opcao = limpar_tags_vazias(texto_opcao).strip()
            
            estado = f'opcao_{letra.lower()}'
            questao_atual[f'Opcao_{letra}'] = texto_opcao
            questao_atual['Tem_Alternativas'] = True
            continue
            
        # Acumula o texto ao campo correto de acordo com a máquina de estados
        if estado == 'enunciado':
            if questao_atual['Enunciado']:
                questao_atual['Enunciado'] += ' ' + linha
            else:
                questao_atual['Enunciado'] = linha
        elif estado == 'opcao_a':
            questao_atual['Opcao_A'] += ' ' + linha
        elif estado == 'opcao_b':
            questao_atual['Opcao_B'] += ' ' + linha
        elif estado == 'opcao_c':
            questao_atual['Opcao_C'] += ' ' + linha
        elif estado == 'opcao_d':
            questao_atual['Opcao_D'] += ' ' + linha
        elif estado == 'opcao_e':
            questao_atual['Opcao_E'] += ' ' + linha

    # Salva a última questão pendente
    if questao_atual:
        questoes.append(questao_atual)
        
    # FILTRAGEM E BLINDAGEM CONTRA FALSOS POSITIVOS:
    # Uma questão legítima da prova obrigatoriamente deve conter alternativas (A a D) válidas e preenchidas.
    # Números órfãos (páginas, datas, artigos de leis) serão removidos automaticamente por este filtro.
    questoes_validas = []
    
    # Prepara e limpa o texto de apoio da prova de Português
    texto_apoio_portugues = '\n'.join(texto_acumulado_inicial).strip()
    
    # Padrões de cabeçalhos/rodapés de final de página que costumam vazar na mesma linha do enunciado/alternativa E
    trailing_headers = [
        r'Realiza[cç]?[aã]?o:?\s*FGV\s+CONHECIMENTO',
        r'Reali\s+a[cç]?[aã]?o',
        r'FGV\s+CONHECIMENTO',
        r'Racioc[íi]nio\s+L[oó]gico-Matem[aá]tico',
        r'Inform[aá]tica\s+B[aá]sica',
        r'No[cç][oõ]es\s+B[aá]sicas\s+de\s+Inform[aá]tica',
        r'No[cç][oõ]es\s+de\s+Inform[aá]tica',
        r'No[cç][oõ]es\s+de\s+Direito\s+Administrativo',
        r'No[cç][oõ]es\s+de\s+Direito\s+Constitucional',
        r'No[cç][oõ]es\s+de\s+Direito\s+Penal',
        r'No[cç][oõ]es\s+de\s+Direito\s+Processual\s+Penal',
        r'No[cç][oõ]es\s+de\s+Medicina\s+Legal',
        r'No[cç][oõ]es\s+de\s+Criminologia',
        r'No[cç][oõ]es\s+de\s+Legisla[cç]?[aã]?o\s+Penal\s+e\s+Processual\s+Extravagante',
        r'Processual\s+Extravagante',
        r'Legisla[cç]?[aã]?o\s+Penal\s+e\s+Processual\s+Extravagante',
        r'Legisla[cç]?[aã]?o\s+Especial',
        r'L[íi]ngua\s+Portuguesa',
        r'Direitos\s+Humanos',
        r'No[cç][oõ]es\s+de\s+Direito',
        r'No[cç][oõ]es\s+de\s+Direito\s+e\s+Direitos\s+Humanos',
        r'Direito\s+Constitucional\s*/\s*Direitos\s+Humanos',
        r'No[cç][oõ]es\s+de\s+Direito\s+Constitucional\s*/\s*Direitos\s+Humanos',
        r'Direito\s+Constitucional\s+e\s+Direitos\s+Humanos',
        r'No[cç][oõ]es\s+de\s+Direito\s+Constitucional\s+e\s+Direitos\s+Humanos',
        r'Penal\s+e\s+Legisla[cç]?[aã]?o\s+Extravagante',
        r'Legisla[cç]?[aã]?o\s+Extravagante',
        r'Direito\s+Penal',
        r'Direito\s+Constitucional',
        r'Direito\s+Administrativo',
        r'Lei\s+Org[aâ]nica\s+da\s+Pol[íi]cia\s+Civil\s+(?:do\s+Estado\s+de\s+Minas\s+Gerais)?',
        r'M[OÓ]DULO\s+[IVX]+\b.*',
        r'M\s+[IVX]+\s*-\s*[C]?ÓDULO\s+ONHECIMENTOS\s+SPEC[ÍI]FICOS',
        r'ONHECIMENTOS\s+SPEC[ÍI]FICOS',
        r'SPEC[ÍI]FICOS',
        r'INVESTIGADOR\s+DE\s+POL[ÍI]CIA\s+[IVX]*',
        r'TIPO\s+\w+\s*[-–]\s*P[AÁ]GINA\s+\d+',
        r'POL[ÍI]CIA\s+CIVIL\s+DO\s+ESTADO\s+DE\s+MINAS\s+GERAIS\s*[-–]\s*PCMG',
        r'PERITO\s+CRIMINAL\s*[-–]\s*[ÁA]REA\s+[IVX\d\s]+',
        r'Qu[íi]mica',
        r'F[íi]sica',
        r'Biologia'
    ]
    def remover_cabecalho_final_html(html_str, patterns_lista):
        """Remove cabeçalhos do final de uma string HTML, baseando-se na versão sem HTML.
        Mantém as tags HTML intactas e bem formadas para a parte que fica."""
        # Remove as tags HTML para termos o texto limpo
        texto_simples = re.sub(r'<[^>]+>', '', html_str)
        
        # Compila um regex para casar os cabeçalhos no final da string simples (com ignorecase)
        pattern_raw = r'\s*(?:' + '|'.join(patterns_lista) + r')\s*$'
        pattern = re.compile(pattern_raw, re.IGNORECASE)
        
        match = pattern.search(texto_simples)
        if not match:
            return html_str
            
        # Se casou, queremos manter os primeiros N caracteres de texto simples
        tamanho_manter = match.start()
        
        # Reconstrói a string HTML mantendo exatamente 'tamanho_manter' caracteres de texto simples
        res_html = []
        chars_consumidos = 0
        i = 0
        tags_abertas = []
        
        while i < len(html_str):
            if chars_consumidos >= tamanho_manter:
                # Fechamos as tags abertas
                for tag in reversed(tags_abertas):
                    res_html.append(f'</{tag}>')
                break
                
            if html_str[i] == '<':
                fim_tag = html_str.find('>', i)
                if fim_tag != -1:
                    tag_completa = html_str[i:fim_tag+1]
                    # Verifica se é tag de fechamento ou abertura
                    if tag_completa.startswith('</'):
                        if tags_abertas:
                            tags_abertas.pop()
                    elif not tag_completa.endswith('/>') and not tag_completa.startswith('<!') and not tag_completa.startswith('<br'):
                        # Pega o nome da tag
                        match_tag_nome = re.match(r'<(\w+)', tag_completa)
                        if match_tag_nome:
                            tags_abertas.append(match_tag_nome.group(1))
                            
                    res_html.append(tag_completa)
                    i = fim_tag + 1
                    continue
                    
            # Se for um caractere de texto
            res_html.append(html_str[i])
            chars_consumidos += 1
            i += 1
            
        resultado = "".join(res_html).strip()
        resultado = limpar_tags_vazias(resultado)
        return resultado.strip()
    
    for q in questoes:
        # Detecta questões de Certo/Errado (CEBRASPE): enunciado longo sem alternativas A-E
        enunciado_sem_html = re.sub(r'<[^>]+>', '', q.get('Enunciado', '')).strip()
        eh_certo_errado = (not q.get('Tem_Alternativas', False) and len(enunciado_sem_html) > 40)
        if eh_certo_errado:
            q['Tipo_Questao'] = 'certo_errado'
        if q.get('Tem_Alternativas', False) or (q['Opcao_A'] and q['Opcao_B'] and q['Opcao_C'] and q['Opcao_D']) or eh_certo_errado:
            # Remove rodapés/cabeçalhos de fim de página que vazaram para as alternativas ou enunciado
            for campo in ['Enunciado', 'Opcao_A', 'Opcao_B', 'Opcao_C', 'Opcao_D', 'Opcao_E']:
                old_val = ""
                while old_val != q[campo]:
                    old_val = q[campo]
                    q[campo] = remover_cabecalho_final_html(q[campo], trailing_headers)
                # Remove restos de cabeçalhos divididos verticalmente como "E B" ou "E A" (case-sensitive)
                q[campo] = re.sub(r'\s*(?:<[^>]+>)*\s*\bE\s+[A-Z]\b\s*(?:</[^>]+>)*\s*\.?\s*$', '', q[campo]).strip()
                
                # Formata subscritos químicos (ex: Cu2O -> Cu<sub>2</sub>O, O2 -> O<sub>2</sub>)
                q[campo] = re.sub(r'([A-Z][a-z]?)(\d+\b|\d+(?=[A-Z]))', r'\1<sub>\2</sub>', q[campo])
                
                # Remove hifens de quebra de linha (translineação)
                q[campo] = remover_hifens_quebra_linha(q[campo])
            
            # Remove prefixos redundantes das alternativas (ex: (A), A., etc.)
            for letra in ['A', 'B', 'C', 'D', 'E']:
                campo = f'Opcao_{letra}'
                pattern_prefix = rf'^(\s*(?:<[^>]+>)*\s*)(\({letra}\)|{letra}\.|{letra}\)|\[{letra}\])(\s*(?:</[^>]+>)*\s*)'
                q[campo] = re.sub(pattern_prefix, '', q[campo], flags=re.IGNORECASE).strip()
                    
            # Formata algarismos romanos para quebras de linha em HTML no WordPress
            # Ex: " I. Assertiva... II. Assertiva..." -> "<br><br>I. Assertiva...<br><br>II. Assertiva..."
            q['Enunciado'] = re.sub(r'(?:^|\s+)((?:<[^>]+>)*)([IVX]+)\.\s+', r'<br><br>\1\2. ', q['Enunciado'])
            
            # Formata itens numéricos de lista (ex: " 1. Primeira... 2. Segunda...") para quebras de linha em HTML no WordPress
            q['Enunciado'] = re.sub(r'(?:^|\s+)((?:<[^>]+>)*)(\d+)\.\s+([A-ZÀ-ÿ])', r'<br><br>\1\2. \3', q['Enunciado'])
            
            # Formata parênteses de preenchimento (assertivas vazias) para quebras de linha em HTML no WordPress
            # Ex: " ( ) Assertiva 1... ( ) Assertiva 2..." -> "<br><br>( ) Assertiva 1...<br><br>( ) Assertiva 2..."
            q['Enunciado'] = re.sub(r'\s*\(\s{0,3}\)\s*', r'<br><br>( ) ', q['Enunciado'])
            
            # Insere quebras de linha antes da frase conclusiva (prompt da questão) para melhor legibilidade
            padrao_conclusao = r'\s+\b(Considerando|Est[aá]o?\b|As\s+afirmativas\s+s[aã]o\b|Assinale\s+(?:a\s+)?(?:op[cç]?[aã]?o|alternativa|afirmativa|rela[cç]?[aã]?o)\b|Analisando\s+o\s+conte[uú]do\b|Nesse\s+cen[aá]rio\b|Com\s+base\b|A\s+sequ[eê]ncia\s+correta\b)'
            q['Enunciado'] = re.sub(padrao_conclusao, r'<br><br>\1', q['Enunciado'])
            
            # Remove eventuais quebras de linha desnecessárias no início absoluto do enunciado
            q['Enunciado'] = re.sub(r'^(?:<br\s*/?>\s*)+', '', q['Enunciado'])
            
            # Associa o texto de apoio compartilhado se houver
            if q['Numero'] in apoios_mapeados:
                q['Texto_Associado'] = apoios_mapeados[q['Numero']]
            elif 1 <= q['Numero'] <= 10 and len(texto_apoio_portugues) > 150:
                q['Texto_Associado'] = texto_apoio_portugues.replace("\n", "<br>")
                
            questoes_validas.append(q)
            
    # Associa os blocos compartilhados às questões para fins de duplicação de imagem no extrator físico
    for bloco in blocos_compartilhados:
        for num in bloco:
            q_match = next((q for q in questoes_validas if q['Numero'] == num), None)
            if q_match:
                q_match['Bloco_Compartilhado'] = bloco
            
    print(f"[+] Total de questões válidas estruturadas: {len(questoes_validas)}")
    return questoes_validas

def parsear_questoes_vision_ollama(caminho_pdf, model="qwen3-vl:2b", endpoint=None, api_key=None):
    """Pipeline Vision-First: converte cada página do PDF em imagem e envia 
    diretamente para o modelo vision do Ollama para leitura e extração estruturada.
    
    Não depende de pdfplumber para extrair texto — o modelo 'vê' a página inteira.
    Ideal para PDFs escaneados, com fontes corrompidas, ou layouts complexos.
    """
    import json
    import tempfile
    
    print(f"[*] Iniciando extração VISION-FIRST via Ollama ({model})...")
    
    # 1. Converte todas as páginas do PDF em imagens
    imagens = converter_pdf_para_imagens(caminho_pdf)
    if not imagens:
        print("[-] Nenhuma página convertida para imagem. PyMuPDF pode não estar instalado.")
        return []
    
    print(f"[*] {len(imagens)} páginas convertidas para imagem (200 DPI).")
    
    # Notifica progresso para o frontend (se a função foi injetada pelo app.py)
    _progresso = getattr(sys.modules[__name__], 'atualizar_progresso', None)
    def _notificar(**kw):
        if _progresso:
            _progresso(**kw)
    
    # 2. Prompt de sistema otimizado para extração estruturada de questões
    prompt_sistema = """Você é um assistente especializado em ler provas de concurso e extrair questões.
Analise a imagem desta página de prova e extraia TODAS as questões contidas nela.

Retorne um objeto JSON contendo a chave "questoes" com a lista de objetos das questões:
{
  "questoes": [
    {
      "Numero": 1,
      "Enunciado": "enunciado completo da questão, preservando formatação sem alternativas",
      "Opcao_A": "texto da alternativa A sem prefixo A) ou (A)",
      "Opcao_B": "texto da alternativa B sem prefixo B) ou (B)",
      "Opcao_C": "texto da alternativa C sem prefixo C) ou (C)",
      "Opcao_D": "texto da alternativa D sem prefixo D) ou (D)",
      "Opcao_E": "texto da alternativa E sem prefixo E) ou (E)",
      "Texto_Associado": "texto de apoio compartilhado se houver"
    }
  ]
}

REGRAS:
1. Se a página tiver DUAS COLUNAS, leia primeiro a coluna da esquerda inteira, depois a da direita.
2. Ignore cabeçalhos, rodapés, números de página e instruções gerais da prova.
3. Se uma questão começou na página anterior e só as alternativas aparecem nesta página, extraia o que for visível.
4. Corrija hifenizações de quebra de linha (ex: "ques-\\ntão" → "questão").
5. Retorne APENAS o objeto JSON contendo a chave "questoes". Sem explicações, sem blocos markdown.
6. Se não houver nenhuma questão nesta página (ex: capa, instruções), retorne: {"questoes": []}"""

    prompt_user = """Analise esta imagem de página de prova de concurso. Extraia todas as questões visíveis e retorne no formato JSON: {"questoes": [...]}. Se não contiver questões, retorne: {"questoes": []}"""
    
    questoes_finais = []
    questoes_vistas = set()  # Evita duplicatas entre páginas
    
    for page_idx, img_bytes in imagens:
        # Checa se a página é capa ou instruções gerais antes de enviar para a IA
        if PYMUPDF_DISPONIVEL:
            try:
                doc_check = fitz.open(caminho_pdf)
                page_check = doc_check.load_page(page_idx)
                txt_simples = page_check.get_text("text") or ""
                doc_check.close()
                txt_simples_lower = txt_simples.lower()
                has_alternatives = re.search(r'^\s*(?:\([A-E]\)|[A-E]\)|[A-E]\.\s*\(\s*\)|[A-E]\.\s+|\[[A-E]\])', txt_simples, re.MULTILINE)
                cover_terms = ["duração:", "duracao:", "leia atentamente", "caderno de questões", "folha de resposta", "instruções abaixo"]
                if any(term in txt_simples_lower for term in cover_terms) and not has_alternatives:
                    print(f"[*] Ignorando página {page_idx + 1} por ser detectada como capa/instruções.")
                    continue
                termos_ignorar = ["orientações aos candidatos", "gabarito preliminar", "gabarito oficial", "instruções aos candidatos", "folha de respostas"]
                if any(termo in txt_simples_lower for termo in termos_ignorar) and not has_alternatives:
                    print(f"[*] Ignorando página {page_idx + 1} por conter termos administrativos.")
                    continue
            except Exception:
                pass

        print(f"[*] Analisando página {page_idx + 1}/{len(imagens)} com Vision IA...")
        _notificar(pagina_atual=page_idx + 1, total_paginas=len(imagens), 
                   etapa=f"Analisando página {page_idx + 1} de {len(imagens)}...",
                   questoes_encontradas=len(questoes_finais))
        
        # Salva imagem temporariamente para enviar ao modelo
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
            tmp_file.write(img_bytes)
            tmp_path = tmp_file.name
        
        try:
            resposta = chamar_api_ia(
                provedor="ollama",
                prompt=prompt_user,
                system_instruction=prompt_sistema,
                api_key=api_key,
                model=model,
                endpoint=endpoint,
                is_image=True,
                caminho_imagem=tmp_path
            )
            
            # Remove marcações de código markdown se houver
            resposta = resposta.strip()
            if resposta.startswith("```"):
                linhas_resp = resposta.splitlines()
                if linhas_resp[0].startswith("```"):
                    linhas_resp = linhas_resp[1:]
                if linhas_resp and linhas_resp[-1].startswith("```"):
                    linhas_resp = linhas_resp[:-1]
                resposta = "\n".join(linhas_resp).strip()
            
            # Tenta extrair JSON de dentro de texto misto (fallback robusto)
            if not resposta.startswith("[") and not resposta.startswith("{"):
                # Procura por JSON embutido na resposta
                match_json = re.search(r'(\[.*\])', resposta, re.DOTALL)
                if match_json:
                    resposta = match_json.group(1)
                else:
                    match_obj = re.search(r'(\{.*\})', resposta, re.DOTALL)
                    if match_obj:
                        resposta = match_obj.group(1)
            
            dados_pagina = json.loads(resposta)
            
            # Normaliza: se veio como dict com chave "questoes", extrai a lista
            if isinstance(dados_pagina, dict):
                for chave in ["questoes", "questões", "questions"]:
                    if chave in dados_pagina:
                        dados_pagina = dados_pagina[chave]
                        break
                else:
                    dados_pagina = [dados_pagina]
            
            if not isinstance(dados_pagina, list):
                dados_pagina = []
            
            qtd_pagina = 0
            for q in dados_pagina:
                if not isinstance(q, dict):
                    continue
                num = 0
                val_num = q.get("Numero") or q.get("numero") or q.get("Número") or q.get("número") or q.get("num") or q.get("id")
                if val_num is not None:
                    try:
                        if isinstance(val_num, int):
                            num = val_num
                        else:
                            m_num = re.search(r'\d+', str(val_num))
                            if m_num:
                                num = int(m_num.group(0))
                    except (ValueError, TypeError):
                        pass
                    
                if not num or num in questoes_vistas:
                    continue
                
                questoes_vistas.add(num)
                qtd_pagina += 1
                
                materia, assunto = obter_meta_materia(num)
                q_estruturada = {
                    'Numero': num,
                    'Page_Idx': page_idx,
                    'Page_Num': page_idx + 1,
                    'Column': 'vision',
                    'Enunciado': normalizar_texto_pdf(remover_hifens_quebra_linha(str(q.get("Enunciado", "")).strip())),
                    'Texto_Associado': normalizar_texto_pdf(remover_hifens_quebra_linha(str(q.get("Texto_Associado", "")).strip())),
                    'Opcao_A': '',
                    'Opcao_B': '',
                    'Opcao_C': '',
                    'Opcao_D': '',
                    'Opcao_E': '',
                    'Gabarito': '',
                    'Disciplina': materia,
                    'Assunto': assunto,
                    'Banca': BANCA_PADRAO,
                    'Instituicao': INSTITUICAO_PADRAO,
                    'Cargo': CARGO_PADRAO,
                    'Ano': ANO_PADRAO,
                    'Carreira': CARREIRA_PADRAO,
                    'Formacao': FORMACAO_PADRAO,
                    'Dificuldade': DIFICULDADE_PADRAO,
                    'Escolaridade': ESCOLARIDADE_PADRAO,
                    'Comentario': '',
                    'Video_URL': '',
                    'Tem_Alternativas': True
                }
                
                # Limpa prefixos e hifens de translineação das alternativas
                for letra in ['A', 'B', 'C', 'D', 'E']:
                    campo = f'Opcao_{letra}'
                    texto_alt = q.get(campo) or q.get(f'opcao_{letra}') or q.get(f'Opção_{letra}') or ""
                    if texto_alt:
                        texto_alt = normalizar_texto_pdf(remover_hifens_quebra_linha(str(texto_alt).strip()))
                        # Remove prefixos como "(A)", "A.", "A)" etc.
                        pattern_prefix = rf'^\s*(?:<[^>]+>\s*)*(\({letra}\)|{letra}\.|{letra}\)|\[{letra}\])\s*(?:</[^>]+>\s*)*'
                        texto_alt = re.sub(pattern_prefix, '', texto_alt, flags=re.IGNORECASE).strip()
                        q_estruturada[campo] = texto_alt
                
                # Verifica se tem alternativas preenchidas
                q_estruturada['Tem_Alternativas'] = any(
                    q_estruturada.get(f'Opcao_{l}', '').strip() for l in ['A', 'B', 'C', 'D', 'E']
                )
                
                questoes_finais.append(q_estruturada)
            
            if qtd_pagina > 0:
                print(f"    [+] {qtd_pagina} questão(ões) extraída(s) da página {page_idx + 1}")
            else:
                print(f"    [·] Página {page_idx + 1}: nenhuma questão detectada pela IA de Visão. Ativando fallback para resgatar questões da página...")
                try:
                    doc_pag = fitz.open(caminho_pdf)
                    p_fitz = doc_pag.load_page(page_idx)
                    txt_pag = p_fitz.get_text("text")
                    doc_pag.close()
                    if txt_pag and len(txt_pag.strip()) > 50:
                        meta_pag = f"[METADADOS_PAGINA:{page_idx}:{page_idx+1}:esquerda]\n" + txt_pag
                        q_fb = parsear_questoes_local(meta_pag)
                        for q_item in q_fb:
                            if q_item['Numero'] not in questoes_vistas:
                                questoes_vistas.add(q_item['Numero'])
                                questoes_finais.append(q_item)
                                print(f"    [+] Fallback de leitura resgatou a Questão {q_item['Numero']} da página {page_idx + 1}")
                except Exception as e_fb:
                    print(f"[-] Fallback para a página {page_idx + 1} falhou: {e_fb}")
                
            _notificar(pagina_atual=page_idx + 1, total_paginas=len(imagens),
                       questoes_encontradas=len(questoes_finais),
                       etapa=f"Página {page_idx + 1}/{len(imagens)} — {len(questoes_finais)} questão(ões) encontrada(s)")
                
        except json.JSONDecodeError as e_json:
            print(f"[-] Erro de JSON na página {page_idx + 1}: {e_json}")
            if 'resposta' in locals():
                print(f"    Resposta bruta (primeiros 300 chars): {resposta[:300]}")
        except Exception as e_pag:
            print(f"[-] Erro ao processar página {page_idx + 1} via Vision: {e_pag}. Executando extração local de fallback...")
            try:
                doc_pag = fitz.open(caminho_pdf)
                p_fitz = doc_pag.load_page(page_idx)
                txt_pag = p_fitz.get_text("text")
                doc_pag.close()
                if txt_pag and len(txt_pag.strip()) > 30:
                    meta_pag = f"[METADADOS_PAGINA:{page_idx}:{page_idx+1}:esquerda]\n" + txt_pag
                    q_fb = parsear_questoes_local(meta_pag)
                    for q_item in q_fb:
                        if q_item['Numero'] not in questoes_vistas:
                            questoes_vistas.add(q_item['Numero'])
                            questoes_finais.append(q_item)
                            print(f"    [+] Fallback local extraiu Questão {q_item['Numero']} da página {page_idx + 1}")
            except Exception as e_fb:
                print(f"[-] Fallback local para a página {page_idx + 1} falhou: {e_fb}")
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except:
                    pass
    
    # Reconstrói blocos compartilhados a partir do Texto_Associado
    for q in questoes_finais:
        texto_assoc = q.get('Texto_Associado', '')
        if texto_assoc and len(texto_assoc.strip()) > 10:
            match_range = re.search(r'quest[õo]es\s+(?:de\s+)?(\d+)\s*(?:a|e|às|,)\s*(\d+)', texto_assoc.lower())
            if match_range:
                n1 = int(match_range.group(1))
                n2 = int(match_range.group(2))
                bloco = list(range(n1, n2 + 1))
                q['Bloco_Compartilhado'] = bloco
    
    # Verificação de integridade da sequência de questões (Garantia de 100%)
    if questoes_finais:
        nums_obtidos = set(q['Numero'] for q in questoes_finais)
        min_n = min(nums_obtidos)
        max_n = max(nums_obtidos)
        faltantes = [n for n in range(min_n, max_n + 1) if n not in nums_obtidos]
        if faltantes:
            print(f"[!] Sequência de Vision IA incompleta. Questões omitidas: {faltantes}. Executando resgate determinístico...")
            try:
                texto_pdf_completo = extrair_texto_pdf_colunas(caminho_pdf)
                q_resgate = parsear_questoes_local(texto_pdf_completo)
                for q_r in q_resgate:
                    if q_r['Numero'] in faltantes:
                        questoes_finais.append(q_r)
                        print(f"    [+] Resgatada com sucesso a Questão {q_r['Numero']}")
            except Exception as e_r:
                print(f"[-] Erro no resgate de questões faltantes: {e_r}")

    print(f"[+] Vision-First concluído: {len(questoes_finais)} questões extraídas no total.")
    return sorted(questoes_finais, key=lambda q: q['Numero'])

def parsear_questoes_ia_local(caminho_pdf, provedor="ollama", model="qwen3-vl:2b", endpoint=None, api_key=None):
    """Varre o PDF extraindo o texto de cada coluna e envia para a IA
    para segmentar e estruturar as questões de forma semântica em formato JSON."""
    import pdfplumber
    import json
    
    print(f"[*] Iniciando análise semântica e estruturação via IA ({provedor.upper()})...")
    
    # Se o provedor é Ollama e o modelo é um VLM (vision), usa o pipeline vision-first
    # que envia a página como imagem diretamente — muito mais preciso para PDFs complexos
    modelos_vision = ["qwen3-vl", "glm-ocr", "llava", "llama3.2-vision", "moondream", "minicpm-v"]
    modelo_lower = (model or "").lower()
    eh_modelo_vision = any(v in modelo_lower for v in modelos_vision)
    
    if provedor.lower() == "ollama" and eh_modelo_vision and PYMUPDF_DISPONIVEL:
        print(f"[*] Modelo Vision detectado ({model}). Usando pipeline VISION-FIRST (imagem direta)...")
        return parsear_questoes_vision_ollama(caminho_pdf, model=model, endpoint=endpoint, api_key=api_key)

    
    # 1. Verifica se o PDF possui texto selecionável
    possui_texto = False
    try:
        with pdfplumber.open(caminho_pdf) as pdf_temp:
            total_chars = 0
            for p in pdf_temp.pages[:3]:
                if p.chars:
                    total_chars += len(p.chars)
            if total_chars > 150:
                possui_texto = True
    except Exception as e:
        print(f"[-] Erro ao checar texto do PDF para segmentação: {e}")

    colunas_textos = []
    
    # Caso seja digitalizado, faz OCR primeiro para obter o texto
    if not possui_texto:
        print("[*] PDF detectado como ESCANEADO/IMAGEM. Rodando OCR Vision preliminar...")
        texto_ocr = extrair_texto_por_ocr(caminho_pdf, provedor=provedor, api_key=api_key, model=model, endpoint=endpoint)
        if texto_ocr:
            paginas = texto_ocr.split("[METADADOS_PAGINA:")
            for p in paginas:
                if not p.strip():
                    continue
                partes = p.split("]\n", 1)
                if len(partes) == 2:
                    meta_str, txt = partes
                    meta_partes = meta_str.split(":")
                    if len(meta_partes) == 3:
                        page_idx = int(meta_partes[0])
                        colunas_textos.append((page_idx, "esquerda", txt))
    else:
        # Modo vetorial normal (pdfplumber)
        with pdfplumber.open(caminho_pdf) as pdf:
            for i, page in enumerate(pdf.pages):
                txt_simples = page.extract_text() or ""
                txt_simples_lower = txt_simples.lower()
                cover_terms = ["duração:", "duracao:", "leia atentamente", "caderno de questões", "folha de resposta", "instruções abaixo"]
                has_alternatives = re.search(r'^\s*(?:\([A-E]\)|[A-E]\)|[A-E]\.\s*\(\s*\)|[A-E]\.\s+|\[[A-E]\])', txt_simples, re.MULTILINE)
                if any(term in txt_simples_lower for term in cover_terms) and not has_alternatives:
                    continue
                termos_ignorar = ["orientações aos candidatos", "gabarito preliminar", "gabarito oficial", "instruções aos candidatos", "folha de respostas"]
                if any(termo in txt_simples_lower for termo in termos_ignorar):
                    continue
                    
                duas_colunas = verificar_se_duas_colunas_pagina(page)
                if duas_colunas:
                    meio = detectar_meio_colunas(page)
                    txt_esq = extrair_texto_limpo(page.within_bbox((0, 0, meio, page.height)), x_limite_palavra=1.2)
                    txt_dir = extrair_texto_limpo(page.within_bbox((meio, 0, page.width, page.height)), x_limite_palavra=1.2)
                    if txt_esq and len(txt_esq.strip()) > 50:
                        colunas_textos.append((i, "esquerda", txt_esq))
                    if txt_dir and len(txt_dir.strip()) > 50:
                        colunas_textos.append((i, "direita", txt_dir))
                else:
                    y0 = page.height * 0.09
                    y1 = page.height * 0.93
                    txt = extrair_texto_limpo(page.within_bbox((0, y0, page.width, y1)), x_limite_palavra=1.2)
                    if txt and len(txt.strip()) > 50:
                        colunas_textos.append((i, "esquerda", txt))
                        
    questoes_finais = []
    prompt_sistema = """Você é um assistente especializado em estruturar e limpar questões de concurso extraídas de PDFs.
Sua tarefa é analisar o texto bruto de uma coluna de prova e extrair todas as questões contidas nele em um JSON estruturado.

Para cada questão localizada, extraia as seguintes chaves no objeto JSON:
1. "Numero": O número da questão (um número inteiro, ex: 14).
2. "Enunciado": O enunciado completo da questão. Importante:
   - Remova cabeçalhos, rodapés ou números de páginas perdidos no meio do texto.
   - Corrija ruídos de caracteres (ex: "1o/m quadro" -> "1º quadro", "esmo" -> "mesmo", "des- tacada" -> "destacada").
   - Preserve tags HTML básicas como negritos (<strong>) e sublinhados (<u>).
3. "Opcao_A", "Opcao_B", "Opcao_C", "Opcao_D", "Opcao_E": O texto de cada alternativa de A a E. Remova o prefixo da letra (ex: remova "(A)", "A.", "A)", etc., deixando apenas o texto da alternativa).
4. "Texto_Associado": Se houver um texto ou tirinha compartilhado na coluna que serve para responder a esta e a outras questões (ex: "Leia a tira a seguir para responder às questões de 13 a 15:"), extraia essa instrução e a sua respectiva citação exatamente como texto associado da questão.

REGRAS RÍGIDAS:
- Retorne apenas e estritamente o JSON contendo uma lista de objetos de questões.
- Não inclua blocos de código Markdown (```json) ou explicações adicionais."""

    total_paginas_pdf = 0
    try:
        with pdfplumber.open(caminho_pdf) as pdf_meta:
            total_paginas_pdf = len(pdf_meta.pages)
    except Exception:
        pass

    _progresso = getattr(sys.modules[__name__], 'atualizar_progresso', None)
    def _notificar(**kw):
        if _progresso:
            _progresso(**kw)

    total_colunas = len(colunas_textos)
    for idx_col, (page_idx, col_name, texto_coluna) in enumerate(colunas_textos):
        pagina_real = page_idx + 1
        total_p = total_paginas_pdf if total_paginas_pdf else max([p + 1 for p, _, _ in colunas_textos], default=1)
        detalhe_col = f"Coluna {col_name.title()}"
        print(f"[*] Processando Página {pagina_real}/{total_p} ({detalhe_col}) com a IA...")
        _notificar(pagina_atual=pagina_real, total_paginas=total_p,
                   questoes_encontradas=len(questoes_finais),
                   etapa=f"Analisando página {pagina_real} de {total_p} ({detalhe_col}) com IA...")
        
        prompt_user = f"""Analise o texto bruto desta coluna de prova e retorne a lista de questões em formato JSON:

TEXTO BRUTO DA COLUNA:
{texto_coluna}
"""
        try:
            resposta_json = chamar_api_ia(
                provedor=provedor,
                prompt=prompt_user,
                system_instruction=prompt_sistema,
                api_key=api_key,
                model=model,
                endpoint=endpoint,
                is_image=False
            )
            
            # Remove marcações de código markdown
            resposta_json = resposta_json.strip()
            if resposta_json.startswith("```"):
                linhas = resposta_json.splitlines()
                if linhas[0].startswith("```"):
                    linhas = linhas[1:]
                if linhas and linhas[-1].startswith("```"):
                    linhas = list(linhas[:-1])
                resposta_json = "\n".join(linhas).strip()
                
            try:
                dados_coluna = json.loads(resposta_json)
            except json.JSONDecodeError:
                try:
                    limpo = re.sub(r'[\r\n]+', ' ', resposta_json)
                    dados_coluna = json.loads(limpo)
                except json.JSONDecodeError:
                    matches = re.findall(r'\{[^{}]*?(?:"Numero"|"numero"|"Enunciado"|"enunciado")[^{}]*?\}', resposta_json, re.DOTALL)
                    dados_coluna = []
                    for m in matches:
                        try:
                            dados_coluna.append(json.loads(m))
                        except Exception:
                            pass
                    if not dados_coluna:
                        raise ValueError("Falha ao decodificar JSON da IA para esta coluna.")
            if isinstance(dados_coluna, dict) and "questoes" in dados_coluna:
                dados_coluna = dados_coluna["questoes"]
            elif isinstance(dados_coluna, dict) and "questões" in dados_coluna:
                dados_coluna = dados_coluna["questões"]
                
            if not isinstance(dados_coluna, list):
                if isinstance(dados_coluna, dict):
                    dados_coluna = [dados_coluna]
                else:
                    raise ValueError("A IA não retornou uma lista válida de questões.")
                    
            for q in dados_coluna:
                if not isinstance(q, dict):
                    continue
                    
                val_num = q.get("Numero") or q.get("numero") or q.get("Número") or q.get("número") or q.get("num") or q.get("id")
                num = 0
                if val_num is not None:
                    try:
                        if isinstance(val_num, int):
                            num = val_num
                        else:
                            m_num = re.search(r'\d+', str(val_num))
                            if m_num:
                                num = int(m_num.group(0))
                    except (ValueError, TypeError):
                        pass
                if not num:
                    continue
                    
                enunciado_val = str(q.get("Enunciado") or q.get("enunciado") or q.get("Enunciado_Texto") or "").strip()
                texto_assoc_val = str(q.get("Texto_Associado") or q.get("texto_associado") or q.get("Texto_Apoio") or "").strip()
                
                def get_alt(letra):
                    l_lower = letra.lower()
                    return str(
                        q.get(f"Opcao_{letra}") or q.get(f"opcao_{l_lower}") or
                        q.get(f"Opção_{letra}") or q.get(f"opção_{l_lower}") or
                        q.get(f"Alternativa_{letra}") or q.get(f"alternativa_{l_lower}") or ""
                    ).strip()
                    
                materia, assunto = obter_meta_materia(num)
                q_estruturada = {
                    'Numero': num,
                    'Page_Idx': page_idx,
                    'Page_Num': page_idx + 1,
                    'Column': col_name,
                    'Enunciado': enunciado_val,
                    'Texto_Associado': texto_assoc_val,
                    'Opcao_A': get_alt('A'),
                    'Opcao_B': get_alt('B'),
                    'Opcao_C': get_alt('C'),
                    'Opcao_D': get_alt('D'),
                    'Opcao_E': get_alt('E'),
                    'Gabarito': '',
                    'Disciplina': materia,
                    'Assunto': assunto,
                    'Banca': BANCA_PADRAO,
                    'Instituicao': INSTITUICAO_PADRAO,
                    'Cargo': CARGO_PADRAO,
                    'Ano': ANO_PADRAO,
                    'Carreira': CARREIRA_PADRAO,
                    'Formacao': FORMACAO_PADRAO,
                    'Dificuldade': DIFICULDADE_PADRAO,
                    'Escolaridade': ESCOLARIDADE_PADRAO,
                    'Comentario': '',
                    'Video_URL': '',
                    'Tem_Alternativas': True
                }
                
                # Garante que prefixos de alternativas e hifens de translineação estejam limpos
                for letra in ['A', 'B', 'C', 'D', 'E']:
                    campo = f'Opcao_{letra}'
                    if q_estruturada[campo]:
                        q_estruturada[campo] = remover_hifens_quebra_linha(q_estruturada[campo].strip())
                        pattern_prefix = rf'^(\s*(?:<[^>]+>)*\s*)(\({letra}\)|{letra}\.|{letra}\)|\[{letra}\])(\s*(?:</[^>]+>)*\s*)'
                        q_estruturada[campo] = re.sub(pattern_prefix, '', q_estruturada[campo], flags=re.IGNORECASE).strip()
                
                q_estruturada['Enunciado'] = remover_hifens_quebra_linha(q_estruturada['Enunciado'].strip())
                if q_estruturada['Texto_Associado']:
                    q_estruturada['Texto_Associado'] = remover_hifens_quebra_linha(q_estruturada['Texto_Associado'].strip())
                    
                questoes_finais.append(q_estruturada)
                
        except Exception as e_col:
            print(f"[-] Erro ao processar coluna via IA: {e_col}. Usando processamento local de fallback...")
            # Fallback local para a coluna
            txt_completo_pag = f"[METADADOS_PAGINA:{page_idx}:{page_idx+1}:{col_name}]\n" + texto_coluna
            questoes_fallback = parsear_questoes_local(txt_completo_pag)
            questoes_finais.extend(questoes_fallback)
            
    # Verificação de integridade da sequência (Garantia de 100%)
    if questoes_finais:
        nums_obtidos = set(q['Numero'] for q in questoes_finais)
        min_n = min(nums_obtidos)
        max_n = max(nums_obtidos)
        faltantes = [n for n in range(min_n, max_n + 1) if n not in nums_obtidos]
        if faltantes:
            print(f"[!] Sequência de IA incompleta. Questões omitidas: {faltantes}. Executando resgate determinístico...")
            try:
                texto_pdf_completo = extrair_texto_pdf_colunas(caminho_pdf)
                q_resgate = parsear_questoes_local(texto_pdf_completo)
                for q_r in q_resgate:
                    if q_r['Numero'] in faltantes:
                        questoes_finais.append(q_r)
                        print(f"    [+] Resgatada com sucesso a Questão {q_r['Numero']}")
            except Exception as e_r:
                print(f"[-] Erro no resgate de questões faltantes: {e_r}")

    # Garante que o Texto_Associado seja 100% completo com todos os parágrafos do texto de apoio
    try:
        texto_pdf_completo = extrair_texto_pdf_colunas(caminho_pdf)
        q_locais = parsear_questoes_local(texto_pdf_completo)
        mapa_apoio = {q['Numero']: q.get('Texto_Associado', '') for q in q_locais if q.get('Texto_Associado')}
        
        for q in questoes_finais:
            num_q = q['Numero']
            apoio_completo = mapa_apoio.get(num_q, '')
            apoio_ia = q.get('Texto_Associado', '')
            if apoio_completo and (not apoio_ia or len(apoio_completo.strip()) > len(apoio_ia.strip()) + 40):
                q['Texto_Associado'] = apoio_completo
    except Exception as e_assoc:
        print(f"[-] Erro ao unificar Texto_Associado completo: {e_assoc}")

    # Reconstrói blocos compartilhados a partir do Texto_Associado
    for q in questoes_finais:
        texto_assoc = q.get('Texto_Associado', '')
        if texto_assoc and len(texto_assoc.strip()) > 10:
            match_range = re.search(r'quest[õo]es\s+(?:de\s+)?(\d+)\s*(?:a|e|às|,)\s*(\d+)', texto_assoc.lower())
            if match_range:
                n1 = int(match_range.group(1))
                n2 = int(match_range.group(2))
                bloco = list(range(n1, n2 + 1))
                q['Bloco_Compartilhado'] = bloco
                
    print(f"[+] Total de questões estruturadas via IA Local: {len(questoes_finais)}")
    return sorted(questoes_finais, key=lambda q: q['Numero'])

def extrair_imagens_alternativas_pdf(caminho_pdf, questoes):
    """Localiza fisicamente as alternativas de questões que estão vazias de texto
    no PDF (por conterem diagramas ou imagens nas opções) e recorta as sub-imagens do PDF
    salvando-as em formato Base64 nas propriedades da questão."""
    import base64
    from io import BytesIO
    import pdfplumber
    import re
    
    def find_question_top(page_found, chars_coluna, num):
        lines = {}
        for c in chars_coluna:
            if c['text'].isspace():
                continue
            top_approx = round(c['top'], 1)
            if top_approx not in lines:
                lines[top_approx] = []
            lines[top_approx].append(c)
            
        linhas_ordenadas = []
        for top in sorted(lines.keys()):
            line_chars = sorted(lines[top], key=lambda c: c['x0'])
            line_text = "".join([c['text'] for c in line_chars]).strip()
            if line_text:
                linhas_ordenadas.append((top, line_text))
                
        pattern = re.compile(rf'^(?:Quest(?:[ãa]o|o|ao)|Q\.)?\s*0*{num}(?:\b|[\.\-\)ºª\s]|$)', re.IGNORECASE)
        for top, text in linhas_ordenadas:
            if pattern.match(text):
                return top
        return None

    print("[*] Iniciando varredura física do PDF para extrair imagens de alternativas vazias...")
    
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            for q in questoes:
                num = q['Numero']
                
                # Questões Certo/Errado (CEBRASPE) não têm alternativas A-E → pula
                if q.get('Tipo_Questao') == 'certo_errado':
                    continue
                
                # Identifica quais alternativas estão vazias de texto
                vazias = []
                for letra in ['A', 'B', 'C', 'D', 'E']:
                    campo_texto = q.get(f'Opcao_{letra}', '').strip()
                    if not campo_texto or campo_texto in [f'({letra})', letra]:
                        vazias.append(letra)
                
                # Se todas as alternativas estão vazias E a questão não tem flag de alternativas,
                # é provável que seja certo/errado sem classificação — também pula
                if len(vazias) == 5 and not q.get('Tem_Alternativas', False):
                    continue
                    
                if not vazias:
                    continue
                    
                print(f"[*] Questão {num} detectada com alternativas de imagem vazias no texto: {vazias}")
                
                page_idx = q.get('Page_Idx')
                coluna_questao = q.get('Column', 'esquerda')
                char_coords = {}
                
                if page_idx is None or page_idx >= len(pdf.pages):
                    print(f"  [-] Metadados de página inválidos para Questão {num}.")
                    continue
                    
                page_found = pdf.pages[page_idx]
                chars = page_found.chars
                print(f"  [+] Questão {num} localizada na página {page_found.page_number}, coluna {coluna_questao.upper()}")
                
                # 2. Filtra caracteres da mesma coluna
                x_limite = page_found.width / 2
                if coluna_questao == 'esquerda':
                    chars_coluna = [c for c in chars if c['x1'] < x_limite]
                else:
                    chars_coluna = [c for c in chars if c['x0'] >= x_limite]
                    
                # 2.1 Calcula os limites verticais da questão na coluna
                y_start = find_question_top(page_found, chars_coluna, num)
                if y_start is None:
                    y_start = min([c['top'] for c in chars_coluna if not c['text'].isspace()]) if chars_coluna else 0
                else:
                    y_start = max(0, y_start - 2)
                    
                col_questoes = [other_q for other_q in questoes 
                                if other_q.get('Page_Idx') == page_idx 
                                and other_q.get('Column') == coluna_questao]
                col_questoes = sorted(col_questoes, key=lambda x: x['Numero'])
                
                try:
                    idx_current = col_questoes.index(q)
                    q_next = col_questoes[idx_current + 1] if idx_current < len(col_questoes) - 1 else None
                except ValueError:
                    q_next = None
                    
                y_end = None
                if q_next:
                    y_end = find_question_top(page_found, chars_coluna, q_next['Numero'])
                    if y_end is not None:
                        y_end = y_end - 2
                        
                if y_end is None:
                    y_end = page_found.height
                    
                print(f"  [~] Limites verticais para Q{num}: {y_start:.1f} a {y_end:.1f}")
                    
                # 3. Localiza os caracteres de alternativas "(A)" "(B)" na mesma coluna
                for i in range(len(chars_coluna) - 2):
                    c1 = chars_coluna[i]
                    c2 = chars_coluna[i+1]
                    c3 = chars_coluna[i+2]
                    
                    if c1['text'] == '(' and c3['text'] == ')':
                        letra = c2['text'].upper()
                        if letra in ['A', 'B', 'C', 'D', 'E'] and letra in vazias:
                            if abs(c1['top'] - c2['top']) < 2.0 and abs(c2['top'] - c3['top']) < 2.0:
                                if y_start <= c1['top'] <= y_end:
                                    char_coords[letra] = {
                                        'x0': c1['x0'],
                                        'x1': c3['x1'],
                                        'top': c1['top'],
                                        'bottom': c1['bottom'],
                                        'x_coluna': coluna_questao
                                    }
                
                if not char_coords:
                    print(f"  [-] Coordenadas das alternativas da questão {num} não localizadas na coluna correspondente.")
                    continue
                    
                letras_ordenadas = sorted(char_coords.keys(), key=lambda l: char_coords[l]['top'])
                
                for idx_letra, letra in enumerate(letras_ordenadas):
                    coord = char_coords[letra]
                    x0 = coord['x1'] + 5
                    meio = page_found.width / 2
                    if coord['x_coluna'] == 'esquerda':
                        x1 = meio - 10
                    else:
                        x1 = page_found.width - 10
                        
                    top = coord['top'] - 4
                    
                    if idx_letra < len(letras_ordenadas) - 1:
                        proxima_letra = letras_ordenadas[idx_letra + 1]
                        bottom = char_coords[proxima_letra]['top'] - 6
                    else:
                        # Se for a última alternativa (ex: D ou E), vai até um limite fixo abaixo
                        bottom = coord['bottom'] + 110
                        # Tenta reduzir o bottom se encontrar outros caracteres não-espaço abaixo
                        caracteres_abaixo = [c for c in page_found.chars if c['top'] > coord['bottom'] + 10 and c['x0'] >= coord['x0'] - 10 and c['x1'] <= x1 + 10]
                        if caracteres_abaixo:
                            primeiro_abaixo = min([c['top'] for c in caracteres_abaixo if not c['text'].isspace()])
                            if primeiro_abaixo - 6 < bottom:
                                bottom = primeiro_abaixo - 6
                    
                    if bottom <= top:
                        bottom = top + 50
                        
                    try:
                        bbox = (x0, top, x1, bottom)
                        cropped_page = page_found.crop(bbox)
                        im = cropped_page.to_image(resolution=120)
                        
                        # Converte a imagem PIL para RGB, aplica redimensionamento máximo a 800px e salva como JPEG comprimido (75%)
                        pil_img = im.original.convert("RGB")
                        pil_img.thumbnail((800, 800))
                        
                        buffered = BytesIO()
                        pil_img.save(buffered, format="JPEG", quality=75)
                        img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
                        
                        # Atribui o Base64 à questão correspondente
                        q[f'Opcao_{letra}_Imagem'] = f"data:image/jpeg;base64,{img_str}"
                        print(f"    [+] Recortada imagem para Questão {num} Opção {letra} ({len(img_str)} bytes)")
                    except Exception as err:
                        print(f"    [-] Erro ao recortar imagem para Questão {num} Opção {letra}: {err}")
                        
    except Exception as e:
        print(f"[-] Erro ao extrair imagens de alternativas do PDF: {e}")
        
    return questoes

def extrair_imagens_enunciado_pdf(caminho_pdf, questoes):
    """Localiza imagens contidas fisicamente dentro dos limites do enunciado
    de cada questão no PDF e faz o recorte salvando-as em formato Base64
    no campo 'Enunciado_Imagem' da questão."""
    import base64
    from io import BytesIO
    import pdfplumber
    import re
    
    print("[*] Iniciando varredura física do PDF para extrair imagens/infográficos de enunciados...")
    
    # Mapeia assinaturas espaciais de todas as imagens do PDF para detectar logos repetitivos
    imagens_repetitivas = set()
    try:
        from collections import Counter
        assinaturas = []
        with pdfplumber.open(caminho_pdf) as pdf_temp:
            for p_temp in pdf_temp.pages:
                for img_temp in p_temp.images:
                    sig = (round(img_temp['x0'], 1), round(img_temp['top'], 1), round(img_temp['x1'], 1), round(img_temp['bottom'], 1))
                    assinaturas.append(sig)
        counter_sigs = Counter(assinaturas)
        for sig, count in counter_sigs.items():
            if count >= 2:
                imagens_repetitivas.add(sig)
        print(f"[+] Mapeadas {len(imagens_repetitivas)} assinaturas de imagens repetitivas (logos/decorações).")
    except Exception as e_sig:
        print(f"[-] Erro ao mapear assinaturas de imagens repetitivas: {e_sig}")
    
    try:
        with pdfplumber.open(caminho_pdf) as pdf:
            for q in questoes:
                num = q['Numero']
                
                page_idx = q.get('Page_Idx')
                coluna_questao = q.get('Column', 'esquerda')
                top_questao = None
                top_alternativa_a = None
                
                if page_idx is None or page_idx >= len(pdf.pages):
                    continue
                    
                page_found = pdf.pages[page_idx]
                meio = page_found.width / 2
                
                # 1. Separa e ordena os caracteres por coluna para evitar misturar coordenadas
                if coluna_questao == 'esquerda':
                    chars_coluna = sorted([c for c in page_found.chars if c['x1'] < meio], key=lambda c: (round(c['top'], 1), c['x0']))
                else:
                    chars_coluna = sorted([c for c in page_found.chars if c['x0'] >= meio], key=lambda c: (round(c['top'], 1), c['x0']))
                    
                # 2. Busca a questão na coluna correspondente
                for i in range(len(chars_coluna) - 5):
                    proximos = "".join([c['text'] for c in chars_coluna[i:i+20]]).lower()
                    pattern_col = r'^(?:(?:quest[aã]o|questao|q\.)\s*)?0?' + str(num) + r'(?:\b|[\.\-\)]|$)'
                    if re.search(pattern_col, proximos):
                        top_questao = chars_coluna[i]['top']
                        
                        # 3. Localiza a primeira alternativa (A) ou marcadores de Certo/Errado
                        for j in range(i + 1, len(chars_coluna) - 2):
                            c1 = chars_coluna[j]
                            c1_txt = c1['text']
                            
                            # Formato (A) — alternativa maiúscula entre parênteses
                            if j + 2 < len(chars_coluna):
                                c2 = chars_coluna[j+1]
                                c3 = chars_coluna[j+2]
                                if c1_txt == '(' and c3['text'] == ')' and c2['text'].upper() in 'ABCDE':
                                    if c1['top'] > top_questao:
                                        if abs(c1['top'] - c2['top']) < 2.0 and abs(c2['top'] - c3['top']) < 2.0:
                                            top_alternativa_a = c1['top']
                                            break
                            
                            # Formato A) ou a) 
                            if c1_txt.upper() in 'ABCDE' and j + 1 < len(chars_coluna):
                                c2 = chars_coluna[j+1]
                                if c2['text'] == ')' and c1['top'] > top_questao:
                                    if abs(c1['top'] - c2['top']) < 2.0:
                                        top_alternativa_a = c1['top']
                                        break
                        break
                            
                if not page_found:
                    continue
                if top_questao is None:
                    continue
                    
                # Para questões Certo/Errado (CEBRASPE) sem alternativa (A),
                # usa como limite inferior o início da próxima questão ou 90% da página
                if top_alternativa_a is None:
                    # Tenta achar a próxima questão na mesma página/coluna
                    proxima_questao = next(
                        (oq for oq in sorted(questoes, key=lambda x: x['Numero'])
                         if oq.get('Page_Idx') == page_idx
                         and oq.get('Column') == coluna_questao
                         and oq['Numero'] > num),
                        None
                    )
                    if proxima_questao:
                        # Tenta localizar o top da próxima questão no PDF
                        num_prox = proxima_questao['Numero']
                        for i_p in range(len(chars_coluna) - 5):
                            prox_str = "".join([c['text'] for c in chars_coluna[i_p:i_p+10]]).lower()
                            if str(num_prox) in prox_str:
                                top_alternativa_a = chars_coluna[i_p]['top'] - 5
                                break
                    if top_alternativa_a is None:
                        # Fallback: usa 90% da altura da página
                        top_alternativa_a = page_found.height * 0.90
                    
                # 4. Busca imagens contidas fisicamente dentro dos limites do enunciado
                x_limite = page_found.width / 2
                
                # Identifica se esta é a primeira questão desta página e coluna
                outras_da_coluna = [other_q for other_q in questoes 
                                    if other_q.get('Page_Idx') == page_idx 
                                    and other_q.get('Column') == coluna_questao]
                primeira_da_coluna = min(outras_da_coluna, key=lambda other_q: other_q.get('Numero')) if outras_da_coluna else None
                is_primeira = (primeira_da_coluna and num == primeira_da_coluna['Numero'])
                
                imgs_enunciado = []
                
                # Tenta localizar a coordenada vertical do texto de apoio compartilhado se houver
                top_apoio = None
                if q.get('Texto_Associado'):
                    texto_apoio_limpo = re.sub(r'<[^>]+>', '', q['Texto_Associado']).strip()
                    if texto_apoio_limpo:
                        primeiros_chars = texto_apoio_limpo[:20].lower()
                        for i_char in range(len(chars_coluna) - len(primeiros_chars)):
                            seq = "".join([c['text'] for c in chars_coluna[i_char:i_char+20]]).lower()
                            if primeiros_chars in seq or seq in primeiros_chars:
                                top_apoio = chars_coluna[i_char]['top']
                                break

                for img in page_found.images:
                    sig_img = (round(img['x0'], 1), round(img['top'], 1), round(img['x1'], 1), round(img['bottom'], 1))
                    if sig_img in imagens_repetitivas:
                        continue
                        
                    na_coluna = False
                    if coluna_questao == 'esquerda':
                        if img['x1'] < x_limite or (img['x0'] < x_limite and img['x1'] > x_limite):
                            na_coluna = True
                    else:
                        if img['x0'] >= x_limite:
                            na_coluna = True
                            
                    no_enunciado = (top_questao - 5 <= img['top'] <= top_alternativa_a + 5)
                    
                    if not no_enunciado and is_primeira:
                        if top_apoio is not None:
                            if top_apoio - 10 <= img['top'] < top_questao and img['height'] > 30:
                                no_enunciado = True
                        else:
                            if 40 <= img['top'] < top_questao and img['height'] > 30:
                                no_enunciado = True
                            
                    if na_coluna and no_enunciado:
                        imgs_enunciado.append(img)
                        
                if imgs_enunciado:
                    print(f"  [+] Questão {num}: {len(imgs_enunciado)} imagem(ns) detectada(s) no enunciado.")
                    x0_crop = min([img['x0'] for img in imgs_enunciado])
                    x1_crop = max([img['x1'] for img in imgs_enunciado])
                    top_crop = min([img['top'] for img in imgs_enunciado])
                    bottom_crop = max([img['bottom'] for img in imgs_enunciado])
                    
                    x0_crop = max(0, x0_crop - 2)
                    x1_crop = min(page_found.width, x1_crop + 2)
                    top_crop = max(0, top_crop - 2)
                    bottom_crop = min(page_found.height, bottom_crop + 2)
                    
                    try:
                        bbox = (x0_crop, top_crop, x1_crop, bottom_crop)
                        cropped_page = page_found.crop(bbox)
                        im = cropped_page.to_image(resolution=120)
                        
                        # Converte a imagem PIL para RGB, aplica redimensionamento máximo a 800px e salva como JPEG comprimido (75%)
                        pil_img = im.original.convert("RGB")
                        pil_img.thumbnail((800, 800))
                        
                        buffered = BytesIO()
                        pil_img.save(buffered, format="JPEG", quality=75)
                        img_str = base64.b64encode(buffered.getvalue()).decode('utf-8')
                        
                        q['Enunciado_Imagem'] = f"data:image/jpeg;base64,{img_str}"
                        print(f"    [+] Recortada imagem do enunciado para Questão {num} ({len(img_str)} bytes)")
                    except Exception as err:
                        print(f"    [-] Erro ao recortar imagem de enunciado para Questão {num}: {err}")
                        
    except Exception as e:
        print(f"[-] Erro ao extrair imagens de enunciados do PDF: {e}")
        
    # Após a extração física, propaga imagens compartilhadas de blocos entre as questões
    print("[*] Propagando imagens compartilhadas de enunciados entre blocos...")
    for q in questoes:
        bloco = q.get('Bloco_Compartilhado')
        if bloco and len(bloco) >= 2:
            # Encontra se alguma das questões do bloco tem a imagem
            imagem_encontrada = None
            for num_b in bloco:
                q_b = next((other for other in questoes if other['Numero'] == num_b), None)
                if q_b and q_b.get('Enunciado_Imagem'):
                    imagem_encontrada = q_b['Enunciado_Imagem']
                    break
            # Se encontrou, aplica para as demais questões do bloco
            if imagem_encontrada:
                if not q.get('Enunciado_Imagem'):
                    q['Enunciado_Imagem'] = imagem_encontrada
                    print(f"    [+] Duplicada imagem compartilhada para Questão {q['Numero']}")
                    
    return questoes

# ==============================================================================
# FASE 3: LEITURA DE GABARITOS (HÍBRIDA E INTELIGENTE)
# ==============================================================================

def ler_gabarito_manual(total_questoes):
    """Interface de console amigável e tolerante a falhas para colagem
    ou digitação manual do gabarito em milissegundos."""
    print("\n" + "=" * 80)
    print(" CRUZAMENTO MANUAL DO GABARITO (MÉTODO LOCAL) ")
    print("=" * 80)
    print("Você pode fornecer as respostas de duas maneiras simples:")
    print("1. Cole uma sequência direta de letras das respostas (ex: ADCCBCCBD...)")
    print("2. Cole os pares formatados copiados (ex: 1-A, 2-D, 3-C, 4-D...)")
    print("=" * 80)
    
    gabaritos = {}
    
    while True:
        entrada = input("\nCole ou digite a sequência de respostas aqui: ").strip().upper()
        if not entrada:
            print("[!] Entrada vazia. Digite algo.")
            continue
            
        # Método 1: Apenas letras consecutivas (suporta X e * para anuladas)
        if re.match(r'^[A-EX\*]+$', entrada):
            if len(entrada) < total_questoes:
                print(f"[!] Atenção: Você forneceu {len(entrada)} respostas, mas temos {total_questoes} questões.")
                confirmar = input("Deseja aplicar mesmo assim? (S/N): ").strip().upper()
                if confirmar != 'S':
                    continue
            for i, letra in enumerate(entrada):
                gabaritos[i + 1] = 'X' if letra in ['X', '*'] else letra
            break
            
        # Método 2: Pares formatados (ex: 1-A, 2-D, 3:C, 4-X, 5-ANULADA)
        pares = re.findall(r'(\d+)\s*[-:=]\s*([A-EX\*]|CANCELADA|ANULADA)', entrada)
        if pares:
            for num_str, letra in pares:
                val = letra.upper()
                if val in ['X', '*', 'CANCELADA', 'ANULADA']:
                    gabaritos[int(num_str)] = 'X'
                else:
                    gabaritos[int(num_str)] = val
            print(f"[+] Foram lidos {len(gabaritos)} gabaritos mapeados de forma chave-valor!")
            break
            
        print("[!] Formato inválido. Digite as letras em sequência ou pares formatados (ex: 1-A, 2-D, 3-X).")
        
    return gabaritos

_ULTIMA_CHAMADA_GEMINI = 0.0

def chamar_api_ia(provedor, prompt, system_instruction=None, api_key=None, model=None, endpoint=None, is_image=False, caminho_imagem=None):
    """Função central unificada para realizar requisições REST HTTPS diretas para
    diversos provedores de IA (Gemini, OpenAI, DeepSeek, Ollama) sem depender de SDKs,
    com controle de cota de 15 RPM e retries automáticos no Gemini."""
    import os
    import time
    import base64
    import requests
    
    global _ULTIMA_CHAMADA_GEMINI
    provedor = provedor.lower()
    
    if provedor == "gemini":
        chave = api_key if api_key and api_key.strip() else GEMINI_API_KEY
        if not chave or chave == "COLE_SUA_API_KEY_AQUI":
            raise ValueError("Chave de API do Gemini não configurada ou vazia. Por favor, obtenha uma chave no Google AI Studio e cole-a na tela.")
            
        modelo_gemini = model if (model and model.strip() and "gemini" in model.lower()) else "gemini-2.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo_gemini}:generateContent"
        
        headers = {
            "x-goog-api-key": chave,
            "Content-Type": "application/json"
        }
        
        parts = [{"text": prompt}]
        
        if is_image and caminho_imagem:
            ext = os.path.splitext(caminho_imagem)[1].lower()
            if ext == '.pdf':
                mime_type = "application/pdf"
            elif ext in ['.png']:
                mime_type = "image/png"
            elif ext in ['.jpg', '.jpeg']:
                mime_type = "image/jpeg"
            else:
                mime_type = "application/pdf"
                
            with open(caminho_imagem, "rb") as f:
                arquivo_base64 = base64.b64encode(f.read()).decode('utf-8')
            parts.append({
                "inline_data": {
                    "mime_type": mime_type,
                    "data": arquivo_base64
                }
            })
            
        payload = {
            "contents": [
                {
                    "parts": parts
                }
            ]
        }
        
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
            
        if is_image:
            payload["generationConfig"] = {
                "responseMimeType": "application/json"
            }
            
        # BLINDAGEM DE COTA GRATUITA (15 RPM): Garante pausa mínima de 4.2 segundos entre chamadas
        tempo_passado = time.time() - _ULTIMA_CHAMADA_GEMINI
        if tempo_passado < 4.2:
            pausa_necessaria = 4.2 - tempo_passado
            time.sleep(pausa_necessaria)
            
        # LOOP DE RETRY SE EXCEDER A COTA (HTTP 429)
        max_tentativas = 3
        for tentativa in range(1, max_tentativas + 1):
            _ULTIMA_CHAMADA_GEMINI = time.time()
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            
            if response.status_code == 200:
                res_json = response.json()
                return res_json['candidates'][0]['content']['parts'][0]['text'].strip()
            elif response.status_code == 429 or "RESOURCE_EXHAUSTED" in response.text or "quota" in response.text.lower():
                if tentativa < max_tentativas:
                    tempo_espera = 10 * tentativa
                    print(f"[!] Cota do Gemini atingida (Erro 429). Aguardando {tempo_espera}s para tentar novamente (Tentativa {tentativa}/{max_tentativas})...")
                    time.sleep(tempo_espera)
                else:
                    raise Exception(f"Limite de cota excedido no Gemini (HTTP 429 após {max_tentativas} tentativas): {response.text}")
            else:
                raise Exception(f"Erro no Gemini (HTTP {response.status_code}): {response.text}")


    elif provedor == "openai":
        if not api_key or not api_key.strip():
            raise ValueError("Chave de API da OpenAI não configurada.")
            
        modelo_openai = model if (model and model.strip() and any(k in model.lower() for k in ["gpt", "o1", "o3"])) else "gpt-4o-mini"
        url = "https://api.openai.com/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
            
        if is_image and caminho_imagem:
            ext = os.path.splitext(caminho_imagem)[1].lower()
            if ext == '.pdf':
                mime_type = "application/pdf"
            elif ext in ['.png']:
                mime_type = "image/png"
            elif ext in ['.jpg', '.jpeg']:
                mime_type = "image/jpeg"
            else:
                mime_type = "application/pdf"
                
            with open(caminho_imagem, "rb") as f:
                arquivo_base64 = base64.b64encode(f.read()).decode('utf-8')
            
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{arquivo_base64}"}}
            ]
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": prompt})
            
        payload = {
            "model": modelo_openai,
            "messages": messages
        }
        
        if is_image:
            payload["response_format"] = {"type": "json_object"}
            
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise Exception(f"Erro na OpenAI (HTTP {response.status_code}): {response.text}")
            
        res_json = response.json()
        return res_json['choices'][0]['message']['content'].strip()

    elif provedor == "deepseek":
        if not api_key or not api_key.strip():
            raise ValueError("Chave de API do DeepSeek não configurada.")
            
        modelo_ds = model if (model and model.strip() and "deepseek" in model.lower()) else "deepseek-chat"
        url = "https://api.deepseek.com/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        if is_image:
            raise ValueError("O DeepSeek não oferece suporte à decodificação de imagens de gabarito diretamente. Por favor, use OpenAI ou Gemini para ler gabaritos.")
            
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": modelo_ds,
            "messages": messages
        }
        
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise Exception(f"Erro no DeepSeek (HTTP {response.status_code}): {response.text}")
            
        res_json = response.json()
        return res_json['choices'][0]['message']['content'].strip()

    elif provedor == "ollama":
        base_url = endpoint if endpoint and endpoint.strip() else "http://localhost:11434"
        modelo_ollama = model if (model and model.strip() and not any(p in model.lower() for p in ["gemini", "gpt", "deepseek"])) else "qwen3-vl:2b"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        
        # Para a API nativa do Ollama, imagens vão no campo "images" da mensagem
        if is_image and caminho_imagem:
            with open(caminho_imagem, "rb") as f:
                arquivo_base64 = base64.b64encode(f.read()).decode('utf-8')
            
            messages.append({
                "role": "user",
                "content": prompt,
                "images": [arquivo_base64]
            })
        else:
            messages.append({"role": "user", "content": prompt})
        
        # Usa a API nativa do Ollama (/api/chat) que suporta format, options e images
        url = f"{base_url.rstrip('/')}/api/chat"
        payload = {
            "model": modelo_ollama,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "num_ctx": 16384
            }
        }
            
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
        except requests.exceptions.Timeout:
            raise Exception("Tempo limite (timeout de 120s) excedido na resposta do Ollama local.")
        except requests.exceptions.RequestException as req_err:
            raise Exception(f"Falha de conexão com o Ollama local (HTTP/Rede): {req_err}")
            
        if response.status_code != 200:
            raise Exception(f"Erro no Ollama local (HTTP {response.status_code}): {response.text}")
            
        res_json = response.json()
        return res_json['message']['content'].strip()
        
    else:
        raise ValueError(f"Provedor de IA desconhecido: {provedor}")

def extrair_gabarito_multiprovedor(caminho_pdf, provedor="gemini", api_key=None, model=None, endpoint=None):
    """Envia o arquivo PDF/Imagem de gabarito para o provedor de IA selecionado para decodificar
    em um JSON mapeado."""
    if not os.path.exists(caminho_pdf):
        print(f"[-] Arquivo de gabarito não encontrado em: {caminho_pdf}")
        return None
        
    print(f"[*] Decodificando gabarito via {provedor.upper()}...")
    
    prompt = """
    Analise o gabarito oficial deste concurso fornecido na página.
    Extraia a alternativa correta correspondente a cada número de questão.
    Se alguma questão foi cancelada ou anulada, defina seu valor como "X".
    Retorne estritamente um JSON no formato de chave (número da questão) e valor (letra correta em maiúsculo, ou "X" para anuladas/canceladas).
    Exemplo:
    {
      "1": "A",
      "2": "X",
      "3": "C"
    }
    Retorne apenas e estritamente o JSON sem nenhuma marcação de markdown ou explicações.
    """
    
    try:
        texto_json = chamar_api_ia(
            provedor=provedor,
            prompt=prompt,
            api_key=api_key,
            model=model,
            endpoint=endpoint,
            is_image=True,
            caminho_imagem=caminho_pdf
        )
        
        # Remove eventuais blocos de código markdown ```json se a IA insistir em incluí-los
        if texto_json.startswith("```"):
            linhas = texto_json.splitlines()
            if linhas[0].startswith("```"):
                linhas = linhas[1:]
            if linhas[-1].startswith("```"):
                linhas = list(linhas[:-1])
            texto_json = "\n".join(linhas).strip()
            
        # Decodifica o JSON retornado
        try:
            respostas_json = json.loads(texto_json)
            gabarito_limpo = {int(k): v.upper() for k, v in respostas_json.items()}
            print(f"[+] Gabarito extraído automaticamente! Mapeadas {len(gabarito_limpo)} questões.")
            return gabarito_limpo
        except json.JSONDecodeError:
            raise ValueError(
                f"O modelo local ({provedor.upper()}) não conseguiu formatar as respostas de forma estruturada (JSON). "
                "Modelos locais muito leves como o Moondream não possuem capacidade de estruturação rígida de dados. "
                "Para leitura de gabarito por imagem, recomendamos selecionar o provedor Gemini (na nuvem) ou inserir "
                "o gabarito de forma manual usando o campo de colagem offline abaixo."
            )
        
    except Exception as e:
        print(f"[-] Erro ao ler gabarito via IA ({provedor.upper()}): {e}")
        raise e

def extrair_gabarito_api_gemini(caminho_pdf, api_key=None):
    """Mantida para retrocompatibilidade com scripts legados que importam o extrator."""
    return extrair_gabarito_multiprovedor(caminho_pdf, provedor="gemini", api_key=api_key)

def gerar_comentarios_ricos_multiprovedor(questoes_lista, provedor="gemini", api_key=None, model=None, endpoint=None):
    """Gera comentários didáticos para cada questão da lista utilizando o provedor de IA ativo."""
    print(f"[*] Gerando comentários didáticos ricos para {len(questoes_lista)} questões via {provedor.upper()}...")
    
    prompt_sistema = """Você é um professor acadêmico de cursinho preparatório. 
Sua tarefa é analisar uma questão de concurso contendo o enunciado, as alternativas (A a E) e o gabarito oficial indicado.
Você deve redigir um comentário explicativo extremamente BREVE, conciso e direto ao ponto (limite rigoroso de 120 palavras).
O comentário deve conter apenas:
1. Por que a alternativa do gabarito oficial está certa (em 1 ou 2 frases curtas e objetivas).
2. O erro das outras alternativas (aponte o erro de cada uma em apenas uma única frase curtíssima).
Evite qualquer introdução, formalidade ou enrolação. Mantenha o texto extremamente enxuto e compacto para leitura rápida."""

    total = len(questoes_lista)
    for idx, q in enumerate(questoes_lista):
        num = q['Numero']
        gabarito = q['Gabarito']
        print(f"[*] Chamando {provedor.upper()} para Questão {num}/{total}...")
        
        if gabarito == "X":
            prompt_questao = f"""
            Disciplina: {q['Disciplina']}
            Assunto: {q['Assunto']}
            
            ENUNCIADO:
            {q['Enunciado']}
            
            GABARITO OFICIAL: Questão Cancelada/Anulada (Gabarito "X")
            
            Redija um comentário explicativo curtíssimo (máximo 60 palavras) indicando de forma didática que esta questão foi anulada/cancelada oficialmente pela banca organizadora e, se aplicável ao conteúdo da questão, mencione brevemente o motivo geral que costuma levar ao cancelamento deste tipo de item (por exemplo, dubiedade de interpretação, ausência de resposta correta ou erro conceitual).
            """
        else:
            prompt_questao = f"""
            Disciplina: {q['Disciplina']}
            Assunto: {q['Assunto']}
            
            ENUNCIADO:
            {q['Enunciado']}
            
            ALTERNATIVAS:
            (A) {q['Opcao_A']}
            (B) {q['Opcao_B']}
            (C) {q['Opcao_C']}
            (D) {q['Opcao_D']}
            (E) {q['Opcao_E'] if q['Opcao_E'] else 'Não aplicável'}
            
            GABARITO OFICIAL: Letra {gabarito}
            
            Redija o comentário explicativo detalhando o acerto da letra {gabarito} e o erro das outras opções.
            """
        
        tentativas = 3
        comentario_gerado = ""
        for t in range(tentativas):
            try:
                comentario_gerado = chamar_api_ia(
                    provedor=provedor,
                    prompt=prompt_questao,
                    system_instruction=prompt_sistema,
                    api_key=api_key,
                    model=model,
                    endpoint=endpoint
                )
                if comentario_gerado:
                    break
            except Exception as ex:
                print(f"    [!] Tentativa {t+1} falhou no {provedor.upper()}: {ex}. Re-tentando...")
                msg_ex = str(ex).lower()
                if "invalid" in msg_ex or "quota" in msg_ex or "429" in msg_ex or "400" in msg_ex:
                    raise ex
                    
        if not comentario_gerado:
            print(f"    [-] Falha ao gerar comentário para a questão {num}. Gravado fallback.")
            q['Comentario'] = f"Gabarito oficial: Letra {gabarito}. Comentários da banca de concurso."
        else:
            q['Comentario'] = comentario_gerado
            
    print("\n[+] Enriquecimento de comentários concluído!")
    return questoes_lista

def gerar_comentarios_ricos_gemini(questoes_lista, api_key=None):
    """Mantida para retrocompatibilidade com scripts legados que importam o extrator."""
    return gerar_comentarios_ricos_multiprovedor(questoes_lista, provedor="gemini", api_key=api_key)

def refinar_questao_com_ia(q, provedor="gemini", api_key=None, model=None, endpoint=None):
    """Envia a questão para a IA limpar e corrigir erros comuns de extração de PDF,
    incluindo ruídos, palavras juntas, acentos perdidos e formatação, preservando tags HTML."""
    
    prompt_sistema = """Você é um assistente especializado em corrigir questões de concurso extraídas de PDFs.
Analise cada campo e aplique TODAS as correções aplicáveis:

**1. REMOÇÃO DE RUÍDOS:**
- Cabeçalhos/rodapés de bancas: "CENTRO DE RECRUTAMENTO", "PROVA PARA ADMISSÃO", "CONCURSO PÚBLICO", "POLÍCIA MILITAR", "Confidencial", "rascunho"
- Números de página isolados: "3", "16", "Página 4", "4 / 12"
- Textos administrativos e slogans de concursos
- Ruídos no meio do texto causados por quebras de página

**2. PALAVRAS JUNTAS (SEM ESPAÇO):**
Insira espaços onde letras minúsculas estão coladas:
- "Noambitodaspolíticas" → "No âmbito das políticas"
- "agestãoderiscos" → "a gestão de riscos"
- "nãose limita" → "não se limita"
- "doproduto" → "do produto"
- "naopode" → "não pode"
EXCEÇÃO: preserve siglas como ICMS, FGTS, INSS, IBGE, SUS, PM, PC

**3. ACENTOS E DIAGRÍFICOS PERDIDOS:**
Corrija palavras que perderam acentos na extração:
- "nao" → "não", "entao" → "então", "tambem" → "também"
- "eles" (quando deveria ser "é") → verifique o contexto
- "asset" → "acesso", "direito" (se estava como "direito" mas sem acento)
- "possui" (se deveria ser "possui") → mantenha
- "urgente" (sem acento) → "urgente" (correto)
- Exemplos comuns: "à" vs "a", "é" vs "e", "ê" vs "e", "ô" vs "o"

**4. LETRAS CONFUNDIDAS:**
- "0" (zero) vs "O" (letra O) → "O" em início de frase é letra, "0" em números
- "1" (um) vs "I" (i maiúsculo) vs "l" (ele minúsculo) → "I" em início de palavra
- "l" (ele) vs "I" (i) → "l" em "alteração", "resultados"

**5. QUEBRAS DE LINHA INCORRETAS:**
Unifique palavras que foram quebradas no final da linha:
- "defini-\nção" → "definição"
- "trans-\nporte" → "transporte"

**6. SINAIS MATEMÁTICOS EM TEXTO:**
- "mais" → "+" (quando em contexto matemático)
- "menos" → "-" (quando em contexto matemático)
- "vezes" → "×" (quando em contexto matemático)
- "dividido por" → "÷" ou "/" (quando apropriado)
NÃO converta se alterar o sentido da frase.

**7. FORMATAÇÃO HTML:**
- Preserve tags legítimas: <table>, <strong>, <em>, <br>, <tr>, <td>, <th>
- Corrija tags quebradas: "<str ong>" → "<strong>"
- Remova tags inválidas ou soltas

EXEMPLO COMPLETO:
Entrada: "Noambitodaspolicpúblicascontemporaneas,agestãoderiscosedesastresincorporaintegraçãointersetorial.gov ernançamultiníveleabordagemcontínua"
Saída: "No âmbito das políticas públicas contemporâneas, a gestão de riscos e desastres incorpora a integração intersetorial. Governança multinível e abordagem contínua"

REGRAS FINAIS:
- Preserve o conteúdo legítimo - NÃO invente texto que não existe
- Retorne APENAS JSON válido com: "Texto_Associado", "Enunciado", "Opcao_A", "Opcao_B", "Opcao_C", "Opcao_D", "Opcao_E"
- Se um campo estiver vazio, retorne string vazia: ""
- Não use markdown, explicações ou texto fora do JSON"""

    prompt_questao = f"""
    Corrija TODOS os erros de extração de PDF no texto abaixo. Aplique: remoção de ruídos, separação de palavras juntas, correção de acentos, unificação de quebras de linha, e formatação HTML.

    TEXTO ASSOCIADO:
    {q.get('Texto_Associado', '')}
    
    ENUNCIADO:
    {q.get('Enunciado', '')}
    
    ALTERNATIVAS:
    (A) {q.get('Opcao_A', '')}
    (B) {q.get('Opcao_B', '')}
    (C) {q.get('Opcao_C', '')}
    (D) {q.get('Opcao_D', '')}
    (E) {q.get('Opcao_E', '')}
    
    Retorne APENAS o JSON corrigido."""
    
    try:
        resposta_texto = chamar_api_ia(
            provedor=provedor,
            prompt=prompt_questao,
            system_instruction=prompt_sistema,
            api_key=api_key,
            model=model,
            endpoint=endpoint,
            is_image=False
        )
        
        # Remove blocos markdown se existirem
        resposta_texto = resposta_texto.strip()
        if resposta_texto.startswith("```"):
            linhas = resposta_texto.splitlines()
            if linhas[0].startswith("```"):
                linhas = linhas[1:]
            if linhas[-1].startswith("```"):
                linhas = list(linhas[:-1])
            resposta_texto = "\n".join(linhas).strip()
        
        # Tenta extrair JSON da resposta caso não seja válido diretamente
        try:
            dados_limpos = json.loads(resposta_texto)
        except json.JSONDecodeError:
            # Tenta encontrar JSON na resposta (wrapado em texto)
            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', resposta_texto, re.DOTALL)
            if json_match:
                dados_limpos = json.loads(json_match.group())
            else:
                raise ValueError(f"Resposta da IA não é JSON válido: {resposta_texto[:200]}")
        
        # Atualiza a questão original mantendo outros metadados intactos
        for chave in ["Texto_Associado", "Enunciado", "Opcao_A", "Opcao_B", "Opcao_C", "Opcao_D", "Opcao_E"]:
            if chave in dados_limpos:
                val = str(dados_limpos[chave]).strip() if dados_limpos[chave] is not None else ""
                if chave.startswith("Opcao_"):
                    letra = chave.split("_")[1]
                    pattern_prefix = rf'^(\s*(?:<[^>]+>)*\s*)(\({letra}\)|{letra}\.|{letra}\)|\[{letra}\])(\s*(?:</[^>]+>)*\s*)'
                    val = re.sub(pattern_prefix, '', val, flags=re.IGNORECASE).strip()
                q[chave] = val
                
    except Exception as e:
        print(f"[-] Erro ao refinar questão {q['Numero']} via IA ({provedor.upper()}): {e}")
        
    return q


# ==============================================================================
# EXECUÇÃO PRINCIPAL
# ==============================================================================

def main():
    print("=" * 80)
    print(" EXTRATOR HÍBRIDO E DETERMINÍSTICO v2.0 - PROJETO AUTÔNOMO ")
    print("=" * 80)
    
    # 1. Extração do PDF de questões de forma local
    if not os.path.exists(ARQUIVO_QUESTOES_PDF):
        print(f"\n[!] ERRO: O arquivo '{ARQUIVO_QUESTOES_PDF}' não foi encontrado.")
        print("Certifique-se de colocá-lo na mesma pasta deste script.")
        input("\nPressione ENTER para sair...")
        sys.exit(1)
        
    opcao_ia = input("\nDeseja usar a IA Local (Qwen 2.5 Coder) para segmentar e estruturar o PDF? (S/N): ").strip().upper()
    if opcao_ia == 'S':
        questoes = parsear_questoes_ia_local(
            ARQUIVO_QUESTOES_PDF,
            provedor="ollama",
            model="qwen2.5-coder:latest"
        )
    else:
        texto_questoes = extrair_texto_pdf_colunas(ARQUIVO_QUESTOES_PDF)
        if not texto_questoes:
            print("[-] Erro na extração de texto do PDF.")
            input("\nPressione ENTER para sair...")
            sys.exit(1)
        questoes = parsear_questoes_local(texto_questoes)
    total_questoes = len(questoes)
    
    if total_questoes == 0:
        print("[-] Nenhuma questão válida extraída do PDF por Regex local.")
        input("\nPressione ENTER para sair...")
        sys.exit(1)
        
    print(f"\n[SUCCESS] {total_questoes} questões estruturadas com sucesso de forma 100% local e precisa!")
    
    # 2. Resolução do Gabarito de forma inteligente
    gabaritos_map = None
    
    if os.path.exists(ARQUIVO_GABARITO_PDF) and GEMINI_API_KEY and GEMINI_API_KEY != "COLE_SUA_API_KEY_AQUI":
        opcao = input("\nDeseja ler as respostas do gabarito PDF automaticamente com a API do Gemini? (S/N): ").strip().upper()
        if opcao == 'S':
            gabaritos_map = extrair_gabarito_api_gemini(ARQUIVO_GABARITO_PDF)
            
    if not gabaritos_map:
        gabaritos_map = ler_gabarito_manual(total_questoes)
        
    # 3. Cruzamento e Classificação
    print("\n[*] Aplicando gabaritos e indexando disciplinas...")
    questoes_gabaritadas = []
    for q in questoes:
        num = q['Numero']
        q['Gabarito'] = gabaritos_map.get(num, 'A') # Vincula o gabarito correto
        questoes_gabaritadas.append(q)
        
    # 4. Geração de Comentários por IA Cirúrgica
    questoes_comentadas = gerar_comentarios_ricos_gemini(questoes_gabaritadas)
    
    # 5. Criação do DataFrame e Exportação em CSV
    print(f"\n[*] Gravando planilha final em '{ARQUIVO_SAIDA_CSV}'...")
    try:
        df = pd.DataFrame(questoes_comentadas)
        
        # Colunas oficiais compatíveis com o importador do WordPress
        colunas_wp = [
            "Enunciado", "Opcao_A", "Opcao_B", "Opcao_C", "Opcao_D", "Opcao_E",
            "Gabarito", "Disciplina", "Assunto", "Banca", "Instituicao", "Cargo",
            "Ano", "Carreira", "Formacao", "Escolaridade", "Dificuldade", "Comentario", "Video_URL"
        ]
        
        # Garante a existência de todas as colunas
        for col in colunas_wp:
            if col not in df.columns:
                df[col] = ""
                
        df = df[colunas_wp]
        
        # Exporta como CSV com ';' (separador nativo em português aceito perfeitamente) e encode UTF-8 com BOM
        df.to_csv(ARQUIVO_SAIDA_CSV, sep=";", index=False, encoding="utf-8-sig")
        
        print("\n" + "=" * 80)
        print(f"[SUCCESS] PLANILHA GERADA COM SUCESSO: {ARQUIVO_SAIDA_CSV}")
        print(f"Total de questões gravadas com comentários didáticos: {len(df)}")
        print("=" * 80)
        print("\nCOMO IMPORTAR NO WORDPRESS:")
        print("1. Vá em: Questões > Importar em Lote.")
        print(f"2. Envie o arquivo gerado: {os.path.abspath(ARQUIVO_SAIDA_CSV)}")
        print("3. Inicie a importação e veja as questões e explicações surgirem perfeitamente no site!")
        print("=" * 80)
        
    except Exception as e:
        print(f"[-] Erro ao salvar arquivo CSV final: {e}")
        
    input("\nPressione ENTER para fechar a ferramenta...")

if __name__ == "__main__":
    main()
