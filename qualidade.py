"""Regras determinísticas de controle de qualidade das questões extraídas."""
import re

_CAMPOS_ALTERNATIVAS = ("Opcao_A", "Opcao_B", "Opcao_C", "Opcao_D", "Opcao_E")
_TAGS_SEM_FECHAMENTO = {"br", "img", "hr", "meta", "input", "source", "link"}
_PADROES_RUIDO = (
    r"\bp[aá]gina\s*\d+\b", r"\bconfidencial\b", r"\brascunho\b",
    r"\b(?:concurso|processo)\s+p[úu]blico\b.*\b(?:p[aá]gina|tipo)\b",
    r"\bcentro de recrutamento e sele[çc][ãa]o\b", r"\bbusca pela excel[êe]ncia\b"
)

def _texto_visivel(valor):
    return re.sub(r"<[^>]+>", " ", str(valor or "")).strip()

def _html_balanceado(valor):
    pilha = []
    for fechando, nome in re.findall(r"<\s*(/)?\s*([a-zA-Z][\w-]*)[^>]*>", str(valor or "")):
        nome = nome.lower()
        if nome in _TAGS_SEM_FECHAMENTO:
            continue
        if fechando:
            if not pilha or pilha[-1] != nome:
                return False
            pilha.pop()
        else:
            pilha.append(nome)
    return not pilha

def validar_questoes(questoes):
    """Inclui ``Qualidade`` sem alterar o conteúdo extraído."""
    numeros = [q.get("Numero") for q in questoes]
    vistos = set()
    for indice, questao in enumerate(questoes):
        alertas, score = [], 100
        numero = questao.get("Numero")
        if not isinstance(numero, int) or numero <= 0:
            alertas.append({"codigo": "numero_invalido", "mensagem": "Número da questão inválido."}); score -= 45
        elif numero in vistos:
            alertas.append({"codigo": "numero_duplicado", "mensagem": "Número duplicado na extração."}); score -= 35
        vistos.add(numero)
        if indice and isinstance(numero, int) and isinstance(numeros[indice - 1], int) and numero != numeros[indice - 1] + 1:
            alertas.append({"codigo": "sequencia_quebrada", "mensagem": "A numeração não é sequencial."}); score -= 18
        if len(_texto_visivel(questao.get("Enunciado"))) < 12:
            alertas.append({"codigo": "enunciado_curto", "mensagem": "Enunciado ausente ou muito curto."}); score -= 35
        presentes = 0
        for campo in _CAMPOS_ALTERNATIVAS:
            letra, texto = campo[-1], _texto_visivel(questao.get(campo))
            imagem = questao.get(f"{campo}_Imagem")
            if texto or imagem:
                presentes += 1
            elif letra in "ABCD":
                alertas.append({"codigo": f"alternativa_{letra.lower()}_ausente", "mensagem": f"Alternativa {letra} ausente."}); score -= 22
        if presentes < 4:
            alertas.append({"codigo": "alternativas_insuficientes", "mensagem": "Foram encontradas menos de quatro alternativas."}); score -= 20
        for campo in ("Enunciado", "Texto_Associado", *_CAMPOS_ALTERNATIVAS):
            valor, texto = str(questao.get(campo) or ""), _texto_visivel(questao.get(campo))
            if not _html_balanceado(valor):
                alertas.append({"codigo": "html_invalido", "mensagem": f"Formatação HTML incompleta em {campo}."}); score -= 12; break
            if any(re.search(padrao, texto, re.IGNORECASE) for padrao in _PADROES_RUIDO):
                alertas.append({"codigo": "possivel_rodape", "mensagem": f"Possível cabeçalho ou rodapé em {campo}."}); score -= 15; break
            if campo != "Texto_Associado" and re.search(r"\bquest[aã]o\s+\d+\b", texto, re.IGNORECASE):
                alertas.append({"codigo": "possivel_mescla", "mensagem": f"Possível mistura de questões em {campo}."}); score -= 18; break
        score = max(0, min(100, score))
        questao["Qualidade"] = {"score": score, "status": "aprovada" if score >= 85 and not alertas else "revisar", "alertas": alertas}
    return questoes
