"""
Script de diagnóstico focado: mostra exatamente o que o parser de questões recebe linha a linha.
"""
import sys
import re
import extrator

caminho_pdf = sys.argv[1] if len(sys.argv) > 1 else extrator.ARQUIVO_QUESTOES_PDF
print(f"=== DIAGNÓSTICO PARSER: {caminho_pdf} ===\n")

texto = extrator.extrair_texto_pdf_colunas(caminho_pdf)
linhas = [l.strip() for l in texto.split('\n')]

num_esperado = 1
questao_atual = None

def eh_numero_questao_aceitavel(num, num_esperado, questao_atual):
    if not questao_atual:
        return 1 <= num <= 200
    if num_esperado <= num <= num_esperado + 3:
        return True
    return False

print(f"Total de linhas extraídas: {len(linhas)}\n")
print("=== PRIMEIRAS 80 LINHAS (linha original e versão sem HTML) ===")
for i, linha in enumerate(linhas[:80]):
    if not linha:
        continue
    linha_sem_html = re.sub(r'<[^>]+>', '', linha)
    
    # Testa cada padrão
    m1 = re.match(r'^(?:Quest[aã]o|Questo|Questao|Q\.)\s*(\d+)(?:\b|[\.\-\)]|$)(.*)', linha_sem_html, re.IGNORECASE)
    m2 = re.match(r'^(\d+)\s*[\.\-\)]\s+(.*)', linha_sem_html)
    m3 = re.match(r'^(\d+)\s*(?:ª|º|°|ª\.|º\.)\s*(?:QUEST[AÃ]O|Questo|Questao|Q\.)\s*[-–\.]?\s*(.*)', linha_sem_html, re.IGNORECASE)
    m4 = re.match(r'^(\d+)$', linha_sem_html)
    
    detectado = ""
    if m1: detectado = f"[OK] PADRAO 1 (Questao N) -> num={m1.group(1)}"
    elif m2: detectado = f"[OK] PADRAO 2 (N. texto) -> num={m2.group(1)}"
    elif m3: detectado = f"[OK] PADRAO 3 (No Questao) -> num={m3.group(1)}"
    elif m4: detectado = f"[OK] PADRAO 4 (N isolado) -> num={m4.group(1)}"
    
    if detectado or i < 30:
        print(f"\nLinha {i+1}: {detectado}")
        print(f"  ORIG    : {repr(linha[:120])}")
        print(f"  SEM_HTML: {repr(linha_sem_html[:120])}")
