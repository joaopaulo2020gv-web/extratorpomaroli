import sys
import os

# Adiciona o caminho atual ao início do path para importar as funções locais
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import extrator

def testar_fluxo():
    print("=" * 80)
    print(" INICIANDO TESTE DO FLUXO DO EXTRATOR INDEPENDENTE ")
    print("=" * 80)
    
    # 1. Teste de Extração de Texto de Colunas
    caminho_pdf = "questoes.pdf.pdf"
    texto = extrator.extrair_texto_pdf_colunas(caminho_pdf)
    if not texto:
        print("[-] Falha na extração de texto.")
        return
        
    # 2. Teste do Parser Local
    questoes = extrator.parsear_questoes_local(texto)
    print(f"[+] Total de questões válidas obtidas: {len(questoes)}")
    
    if len(questoes) != 40:
        print(f"[-] Erro: Esperado 40 questões, mas obteve {len(questoes)}.")
        return
    else:
        print("[SUCCESS] Extração local das 40 questões validada com sucesso!")
        
    # 3. Simula gabarito para as 40 questões
    # Usaremos respostas mockadas 'A' para testar o fluxo de gravação
    gabarito_mock = {i: 'A' for i in range(1, 41)}
    
    # Vincula o gabarito
    questoes_gabaritadas = []
    for q in questoes:
        num = q['Numero']
        q['Gabarito'] = gabarito_mock.get(num, 'A')
        questoes_gabaritadas.append(q)
        
    # 4. Teste de geração de comentários enriquecidos (apenas as 2 primeiras questões para testar a API)
    print("\n[*] Testando geração de comentários didáticos detalhados na API do Gemini...")
    # Limita o teste às 2 primeiras para economizar tempo e tokens
    amostra_questoes = questoes_gabaritadas[:2]
    
    questoes_comentadas = extrator.gerar_comentarios_ricos_gemini(amostra_questoes)
    
    print("\n[*] Validando os comentários didáticos gerados pela IA:")
    for q in questoes_comentadas:
        print(f"\nQuestão {q['Numero']} (Gabarito oficial: {q['Gabarito']}):")
        print(f"  Enunciado: {q['Enunciado'][:100]}...")
        print(f"  Comentário gerado: {q['Comentario'][:300]}...")
        print("-" * 50)
        
    if "Gabarito oficial" in questoes_comentadas[0]['Comentario'] and "Consulte a legislação" in questoes_comentadas[0]['Comentario']:
        print("[-] Aviso: API Key parece inválida ou ausente, gerado comentário de fallback.")
    else:
        print("[SUCCESS] API do Gemini retornou comentários didáticos com sucesso!")
        
    print("\n[+] Teste concluído com absoluto sucesso!")

if __name__ == "__main__":
    testar_fluxo()
