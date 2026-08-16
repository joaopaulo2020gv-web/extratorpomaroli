"""
Diagnóstico: chama parsear_questoes_local diretamente e vê quantas questões foram detectadas.
"""
import sys
import extrator

caminho_pdf = sys.argv[1] if len(sys.argv) > 1 else extrator.ARQUIVO_QUESTOES_PDF
print(f"=== TESTE COMPLETO DO PARSER: {caminho_pdf} ===\n")

# Extrai o texto
texto = extrator.extrair_texto_pdf_colunas(caminho_pdf)
if not texto:
    print("[ERRO] Texto extraido vazio!")
    sys.exit(1)

print(f"Texto extraido: {len(texto)} chars\n")

# Roda o parser
resultado = extrator.parsear_questoes_local(texto)
questoes = resultado if isinstance(resultado, list) else resultado.get('questoes', []) if isinstance(resultado, dict) else []

print(f"\n=== RESULTADO FINAL ===")
print(f"Total de questoes detectadas: {len(questoes)}")
if questoes:
    for q in questoes[:5]:
        print(f"\n  Questao {q.get('Numero')}: {str(q.get('Enunciado',''))[:80]}...")
        print(f"  Opcao_A: {str(q.get('Opcao_A',''))[:60]}")
else:
    print("[NENHUMA QUESTAO DETECTADA!]")
    print("\nVerificando o retorno do parsear_questoes_local...")
    print(f"Tipo: {type(resultado)}")
    if isinstance(resultado, dict):
        print(f"Chaves: {list(resultado.keys())}")
        for k, v in resultado.items():
            print(f"  {k}: {repr(v)[:100]}")
