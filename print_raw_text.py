import extrator

caminho_pdf = "questoes.pdf.pdf"
print("Extraindo texto completo...")
texto = extrator.extrair_texto_pdf_colunas(caminho_pdf)

# Vamos achar o bloco correspondente à página 6 (index 5)
paginas = texto.split("[METADADOS_PAGINA:")
for p in paginas:
    if p.startswith("5:"):
        print("\n=== RAW TEXT FOR PAGE 6 ===")
        print(p)
        break
