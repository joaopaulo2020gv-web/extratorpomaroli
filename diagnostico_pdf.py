"""
Script de diagnóstico para entender como o novo PDF está formatado.
Mostra as primeiras linhas do texto extraído, útil para identificar
por que as questões não estão sendo detectadas.
"""
import sys
import pdfplumber
import extrator

# Aceita o nome do PDF como argumento ou usa o padrão
if len(sys.argv) > 1:
    caminho_pdf = sys.argv[1]
else:
    caminho_pdf = extrator.ARQUIVO_QUESTOES_PDF

print(f"=== DIAGNÓSTICO DO PDF: {caminho_pdf} ===\n")

# 1. Mostra metadados do PDF
try:
    with pdfplumber.open(caminho_pdf) as pdf:
        print(f"Número de páginas: {len(pdf.pages)}")
        print(f"Metadados: {pdf.metadata}\n")
        
        # Mostra o texto bruto das primeiras 3 páginas
        for i, page in enumerate(pdf.pages[:3]):
            print(f"\n{'='*60}")
            print(f"PÁGINA {i+1} — Texto bruto (pdfplumber):")
            print(f"{'='*60}")
            texto = page.extract_text()
            if texto:
                print(texto[:3000])
            else:
                print("[VAZIO - sem texto extraível]")
except Exception as e:
    print(f"Erro ao abrir PDF: {e}")

# 2. Tenta extrair com o método do extrator e mostra as primeiras linhas
print(f"\n\n{'='*60}")
print("TEXTO EXTRAÍDO PELO EXTRATOR (primeiras 200 linhas):")
print(f"{'='*60}")
try:
    texto = extrator.extrair_texto_pdf_colunas(caminho_pdf)
    linhas = texto.split('\n')
    for i, linha in enumerate(linhas[:200]):
        print(f"{i+1:4d} | {repr(linha)}")
except Exception as e:
    print(f"Erro ao extrair texto: {e}")
    import traceback
    traceback.print_exc()
