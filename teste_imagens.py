"""
Teste de extração de imagens do PDF CEBRASPE.
Verifica quantas questões tiveram imagens detectadas e salva um exemplo.
"""
import sys
import os
import extrator

caminho_pdf = sys.argv[1] if len(sys.argv) > 1 else extrator.ARQUIVO_QUESTOES_PDF
print(f"=== TESTE DE IMAGENS: {caminho_pdf} ===\n")

texto = extrator.extrair_texto_pdf_colunas(caminho_pdf)
questoes = extrator.parsear_questoes_local(texto)
print(f"Questoes extraidas: {len(questoes)}")

questoes = extrator.extrair_imagens_alternativas_pdf(caminho_pdf, questoes)
questoes = extrator.extrair_imagens_enunciado_pdf(caminho_pdf, questoes)

com_imagem = [q for q in questoes if q.get('Enunciado_Imagem')]
print(f"\nQuestoes com imagem no enunciado: {len(com_imagem)}")
for q in com_imagem[:3]:
    img = q['Enunciado_Imagem']
    print(f"  Questao {q['Numero']}: {len(img)} bytes base64")
    # Salva como arquivo para visualizar
    import base64
    img_data = base64.b64decode(img.split(',')[1])
    fname = f"teste_imagem_q{q['Numero']}.jpg"
    with open(fname, 'wb') as f:
        f.write(img_data)
    print(f"    Salva em: {fname}")

if not com_imagem:
    print("\n[!] Nenhuma imagem detectada no enunciado.")
    print("Verificando imagens brutas do PDF...")
    import pdfplumber
    with pdfplumber.open(caminho_pdf) as pdf:
        total_imgs = 0
        for i, page in enumerate(pdf.pages):
            if page.images:
                print(f"  Pagina {i+1}: {len(page.images)} imagem(ns)")
                for img in page.images[:2]:
                    print(f"    x0={img['x0']:.1f} top={img['top']:.1f} x1={img['x1']:.1f} bottom={img['bottom']:.1f} w={img['width']:.1f} h={img['height']:.1f}")
                total_imgs += len(page.images)
        print(f"Total de imagens no PDF: {total_imgs}")
