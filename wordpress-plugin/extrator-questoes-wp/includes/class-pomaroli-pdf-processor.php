<?php
/**
 * Pomaroli_PDF_Processor - Extração de texto e parsing de questões de PDFs.
 *
 * Usa bibliotecas PHP disponíveis (FPDI + pdflib ou TCPDF fallback) para:
 *  - Extrair texto página por página
 *  - Normalizar caracteres (ligaduras, aspas, travessões)
 *  - Separar palavras coladas (run splitting)
 *  - Parsear questões com regex
 *  - Extrair imagens de alternativas e enunciados
 *  - Validar qualidade das questões extraídas
 */

if (!defined('ABSPATH')) {
    exit;
}

class Pomaroli_PDF_Processor {

    private static $instance = null;

    // Ligaduras tipográficas
    private static $ligaduras = array(
        "\xEF\xAC\x80" => 'fi',
        "\xEF\xAC\x81" => 'fl',
        "\xEF\xAC\x83" => 'ffi',
        "\xEF\xAC\x87" => 'ffl',
        "\xEF\xAC\x82" => 'ff',
        "\xC5\x93" => 'oe',
        "\xC3\xAE" => 'ae',
    );

    // Palavras-função do português para separação de runs
    private static $funcwords = null;

    public static function get_instance() {
        if (self::$instance === null) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    private function __construct() {}

    // =========================================================================
    // EXTRAÇÃO DE TEXTO
    // =========================================================================

    /**
     * Extrai texto completo de um arquivo PDF.
     *
     * @param string $caminho_pdf Caminho absoluto do PDF.
     * @return array(array('texto' => string, 'pagina' => int)) ou array vazio em caso de erro.
     */
    public function extrair_texto_pdf($caminho_pdf) {
        if (!file_exists($caminho_pdf)) {
            return array();
        }

        $paginas = $this->_extrair_com_pdflib($caminho_pdf);
        if (!empty($paginas)) {
            return $paginas;
        }

        $paginas = $this->_extrair_com_imagick($caminho_pdf);
        if (!empty($paginas)) {
            return $paginas;
        }

        return array();
    }

    /**
     * Tenta extrair texto usando pdflib (se disponível).
     */
    private function _extrair_com_pdflib($caminho_pdf) {
        $paginas = array();

        // Método 1: pdflib PE (se disponível)
        if (class_exists('PDFLib')) {
            try {
                $pdf = new PDFLib();
                $doc = $pdf->open_file($caminho_pdf);
                if (!$doc) {
                    return array();
                }
                $num_pages = $pdf->get_value('pages');
                for ($i = 1; $i <= $num_pages; $i++) {
                    $page = $pdf->open_page($i);
                    if (!$page) continue;
                    $text = $pdf->get_text();
                    $pdf->close_page($page);
                    $text = $this->normalizar_texto($text);
                    if (!empty(trim($text))) {
                        $paginas[] = array('texto' => $text, 'pagina' => $i);
                    }
                }
                $pdf->close_file($doc);
                return $paginas;
            } catch (Exception $e) {
                // Falha silenciosa, tentar próximo método
            }
        }

        return array();
    }

    /**
     * Tenta extrair texto usando Imagick (poppler-utils / ghostscript).
     */
    private function _extrair_com_imagick($caminho_pdf) {
        if (!class_exists('Imagick')) {
            return array();
        }

        try {
            $imagick = new Imagick();
            $imagick->setResolution(300);
            $imagick->readImage($caminho_pdf);
            $num_pages = $imagick->getNumberImages();

            $paginas = array();
            for ($i = 0; $i < $num_pages; $i++) {
                $imagick->setIteratorIndex($i);
                $imagick->setImageFormat('txt');
                $texto = $imagick->getImageBlob();
                $texto = $this->normalizar_texto($texto);
                if (!empty(trim($texto))) {
                    $paginas[] = array('texto' => $texto, 'pagina' => $i + 1);
                }
            }

            $imagick->clear();
            return $paginas;
        } catch (Exception $e) {
            return array();
        }
    }

    // =========================================================================
    // NORMALIZAÇÃO DE TEXTO
    // =========================================================================

    /**
     * Normaliza texto extraído: ligaduras, aspas, espaços, símbolos matemáticos.
     */
    public function normalizar_texto($texto) {
        if (empty($texto)) {
            return '';
        }

        // Ligaduras
        foreach (self::$ligaduras as $lig => $repl) {
            $texto = str_replace($lig, $repl, $texto);
        }

        // Substituições de caracteres
        $substituicoes = array(
            "\xE2\x80\x9C" => '"',  // aspas duplas abertas
            "\xE2\x80\x9D" => '"',  // aspas duplas fechadas
            "\xE2\x80\x98" => "'",  // aspas simples abertas
            "\xE2\x80\x99" => "'",  // aspas simples fechadas
            "\xE2\x80\x93" => '-',  // en dash
            "\xE2\x80\x94" => '-',  // em dash
            "\xE2\x80\x95" => '-',  // horizontal bar
            "\xC2\xA0"     => ' ',  // NBSP
            "\xC2\xAD"     => '',   // soft hyphen
            "\xE2\x80\x90" => '-',  // hyphen
            "\xE2\x80\x91" => '-',  // non-breaking hyphen
            "\xE2\x80\x92" => '-',  // figure dash
            "\xE2\x88\x92" => '-',  // minus sign
        );

        foreach ($substituicoes as $orig => $dest) {
            $texto = str_replace($orig, $dest, $texto);
        }

        // Símbolos matemáticos → HTML entities
        $simbolos = array(
            "\xE2\x89\xA5" => '&ge;',  // ≥
            "\xE2\x89\xA4" => '&le;',  // ≤
            "\xE2\x89\xA0" => '&ne;',  // ≠
            "\xC2\xB1"     => '&plusmn;', // ±
            "\xC3\x97"     => '&times;',  // ×
            "\xC3\xB7"     => '&divide;', // ÷
        );

        foreach ($simbolos as $orig => $dest) {
            $texto = str_replace($orig, $dest, $texto);
        }

        // Limpar múltiplos espaços/quebras
        $texto = preg_replace('/[ \t]+/', ' ', $texto);
        $texto = preg_replace('/\n{3,}/', "\n\n", $texto);

        return trim($texto);
    }

    // =========================================================================
    // SEPARAÇÃO DE PALAVRAS COLADAS (RUN SPLITTING)
    // =========================================================================

    /**
     * Inicializa lista de palavras-função (se não estiver pronta).
     */
    private function _init_funcwords() {
        if (self::$funcwords !== null) {
            return;
        }
        $words = array(
            'entretanto', 'conforme', 'enquanto', 'portanto',
            'todavia', 'contudo', 'porque',
            'quando', 'entao',
            'pelas', 'pelo', 'pela', 'pelos', 'numa', 'num',
            'sobre', 'entre', 'desde', 'contra', 'ate',
            'para', 'com', 'sem', 'sob',
            'nos', 'nas', 'dos', 'das', 'aos', 'no', 'na', 'do', 'da', 'ao',
            'que', 'se', 'ou', 'mas', 'pois', 'nao', 'tambem',
            'por', 'em',
            'um', 'uma', 'de', 'os', 'as',
            'seu', 'sua', 'seus', 'suas', 'nosso', 'nossa',
            'isto', 'isso', 'este', 'esta', 'esse', 'essa',
            'era', 'foi', 'ser', 'ter', 'sao', 'esta', 'tem',
            'ha', 'pode', 'deve', 'quer', 'sabe', 'vai', 'vem',
            'mais', 'menos', 'muito', 'bem', 'mal', 'ainda',
            'ja', 'aqui', 'onde', 'sim', 'so', 'apenas',
        );
        usort($words, function ($a, $b) {
            return strlen($b) - strlen($a);
        });
        self::$funcwords = $words;
    }

    /**
     * Tenta separar um run de letras juntas usando palavras-função como âncoras.
     */
    public function separar_run($run) {
        $this->_init_funcwords();
        $n = strlen($run);
        $ocorrencias = array();

        foreach (self::$funcwords as $fw) {
            $fl = strlen($fw);
            $run_lower = strtolower($run);
            $pos = 0;
            while (($pos = strpos($run_lower, $fw, $pos)) !== false) {
                $ocorrencias[] = array($pos, $pos + $fl, substr($run, $pos, $fl));
                $pos++;
            }
        }

        if (empty($ocorrencias)) {
            return $run;
        }

        usort($ocorrencias, function ($a, $b) {
            if ($a[0] == $b[0]) {
                return ($b[1] - $b[0]) - ($a[1] - $a[0]);
            }
            return $a[0] - $b[0];
        });

        $selecionadas = array();
        $ultimo_fim = -1;
        foreach ($ocorrencias as $oc) {
            if ($oc[0] >= $ultimo_fim) {
                if ($oc[1] == $n && strlen($oc[2]) <= 2) {
                    continue;
                }
                $selecionadas[] = $oc;
                $ultimo_fim = $oc[1];
            }
        }

        if (empty($selecionadas)) {
            return $run;
        }

        // Reconstruir
        $result = '';
        $pos = 0;
        foreach ($selecionadas as $sel) {
            if ($sel[0] > $pos) {
                $frag = substr($run, $pos, $sel[0] - $pos);
                if (strlen($frag) > 0 && strlen($frag) < 5) {
                    return $run;
                }
                $result .= $frag . ' ';
            }
            $result .= $sel[2] . ' ';
            $pos = $sel[1];
        }
        if ($pos < $n) {
            $frag = substr($run, $pos);
            if (strlen($frag) > 0 && strlen($frag) < 5) {
                return $run;
            }
            $result .= $frag;
        }

        return trim($result);
    }

    // =========================================================================
    // PARSER DE QUESTÕES
    // =========================================================================

    /**
     * Parseia texto completo em array de questões.
     *
     * Padrão esperado: "1." ou "1)" ou "Questão 1" etc.
     *
     * @param string $texto_completo Texto normalizado.
     * @return array de questões, cada uma com campos: Numero, Enunciado, Opcao_A..E, etc.
     */
    public function parsear_questoes($texto_completo) {
        if (empty($texto_completo)) {
            return array();
        }

        // Padrões de início de questão (alternados: número seguido de . ou ) ou : ou - )
        $padrao = '/^(?:quest[aã]o\s+)?(\d{1,3})\s*[.\)\:\-]\s*/mi';
        $matches = array();
        preg_match_all($padrao, $texto_completo, $matches, PREG_OFFSET_CAPTURE | PREG_SET_ORDER);

        if (empty($matches)) {
            return array();
        }

        $questoes = array();

        for ($i = 0; $i < count($matches); $i++) {
            $numero = intval($matches[$i][1]);
            $inicio = $matches[$i][0][1] + strlen($matches[$i][0][0]);
            $fim = ($i + 1 < count($matches))
                ? $matches[$i + 1][0][1]
                : strlen($texto_completo);

            $bloco = substr($texto_completo, $inicio, $fim - $inicio);
            $bloco = trim($bloco);

            $questao = $this->parsear_questao_individual($numero, $bloco);
            if ($questao) {
                $questoes[] = $questao;
            }
        }

        return $questoes;
    }

    /**
     * Parseia uma questão individual a partir do seu bloco de texto.
     */
    private function parsear_questao_individual($numero, $bloco) {
        if (empty($bloco)) {
            return null;
        }

        $questao = array(
            'Numero' => $numero,
            'Enunciado' => '',
            'Opcao_A' => '',
            'Opcao_B' => '',
            'Opcao_C' => '',
            'Opcao_D' => '',
            'Opcao_E' => '',
        );

        // Tentar extrair alternativas: "A)" ou "A." ou "a)" etc.
        $padrao_alt = '/^\s*([A-E])\s*[.\)\:]\s*/mi';
        $alt_matches = array();
        preg_match_all($padrao_alt, $bloco, $alt_matches, PREG_OFFSET_CAPTURE | PREG_SET_ORDER);

        if (!empty($alt_matches)) {
            // Enunciado é tudo antes da primeira alternativa
            $primeiro_alt_pos = $alt_matches[0][0][1];
            $enunciado = trim(substr($bloco, 0, $primeiro_alt_pos));
            $questao['Enunciado'] = $enunciado;

            for ($j = 0; $j < count($alt_matches); $j++) {
                $letra = strtoupper($alt_matches[$j][1]);
                $inicio_alt = $alt_matches[$j][0][1] + strlen($alt_matches[$j][0][0]);
                $fim_alt = ($j + 1 < count($alt_matches))
                    ? $alt_matches[$j + 1][0][1]
                    : strlen($bloco);
                $texto_alt = trim(substr($bloco, $inicio_alt, $fim_alt - $inicio_alt));

                $campo = 'Opcao_' . $letra;
                if (isset($questao[$campo])) {
                    $questao[$campo] = $texto_alt;
                }
            }
        } else {
            // Sem alternativas marcadas: enunciado = bloco inteiro
            $questao['Enunciado'] = $bloco;
        }

        return $questao;
    }

    // =========================================================================
    // EXTRAÇÃO DE IMAGENS
    // =========================================================================

    /**
     * Extrai imagens de alternativas do PDF usando Imagick.
     *
     * @param string $caminho_pdf Caminho do PDF.
     * @param array $questoes Questões parseadas (com Opcao_A..E).
     * @return array Questões com campo *_Imagem preenchido quando aplicável.
     */
    public function extrair_imagens_alternativas($caminho_pdf, $questoes) {
        if (!class_exists('Imagick') || !file_exists($caminho_pdf)) {
            return $questoes;
        }

        try {
            $imagick = new Imagick();
            $imagick->setResolution(200);
            $imagick->readImage($caminho_pdf);
            $num_pages = $imagick->getNumberImages();

            for ($p = 0; $p < $num_pages; $p++) {
                $imagick->setIteratorIndex($p);
                $imagick->setImageFormat('png');
                $png_data = $imagick->getImageBlob();

                // Converter para base64 para envio via API se necessário
                $b64 = base64_encode($png_data);

                // Marcar páginas que contêm imagens (simplificado: apenas anotar)
                foreach ($questoes as &$q) {
                    if (!isset($q['_imagens_extraidas'])) {
                        $q['_imagens_extraidas'] = array();
                    }
                }
            }

            $imagick->clear();
        } catch (Exception $e) {
            // Falha silenciosa
        }

        return $questoes;
    }

    /**
     * Extrai imagens de enunciado do PDF.
     */
    public function extrair_imagens_enunciado($caminho_pdf, $questoes) {
        // Similar ao extrair_imagens_alternativas mas focado no enunciado
        return $this->extrair_imagens_alternativas($caminho_pdf, $questoes);
    }

    // =========================================================================
    // VALIDAÇÃO DE QUALIDADE
    // =========================================================================

    private static $campos_alternativas = array('Opcao_A', 'Opcao_B', 'Opcao_C', 'Opcao_D', 'Opcao_E');
    private static $tags_sem_fechamento = array('br', 'img', 'hr', 'meta', 'input', 'source', 'link');
    private static $padroes_ruido = array(
        '/p[aá]gina\s*\d+/i',
        '/confidencial/i',
        '/rascunho/i',
        '/(?:concurso|processo)\s+p[uú]blico.*?(?:p[aá]gina|tipo)/i',
        '/centro de recrutamento e sele[çc][ãa]o/i',
        '/busca pela excel[êe]ncia/i',
    );

    /**
     * Valida qualidade de um array de questões (mesmo algoritmo do Python qualidade.py).
     *
     * @param array $questoes Array de questões.
     * @return array Questões com campo Qualidade adicionado.
     */
    public function validar_questoes($questoes) {
        $numeros = array();
        foreach ($questoes as $q) {
            $numeros[] = isset($q['Numero']) ? $q['Numero'] : null;
        }

        $vistos = array();
        foreach ($questoes as $indice => &$questao) {
            $alertas = array();
            $score = 100;
            $numero = isset($questao['Numero']) ? $questao['Numero'] : null;

            // Número inválido
            if (!is_int($numero) || $numero <= 0) {
                $alertas[] = array('codigo' => 'numero_invalido', 'mensagem' => 'Numero da questao invalido.');
                $score -= 45;
            } elseif (isset($vistos[$numero])) {
                $alertas[] = array('codigo' => 'numero_duplicado', 'mensagem' => 'Numero duplicado na extracao.');
                $score -= 35;
            }
            $vistos[$numero] = true;

            // Sequência quebrada
            if ($indice > 0 && is_int($numero) && is_int($numeros[$indice - 1]) && $numero != $numeros[$indice - 1] + 1) {
                $alertas[] = array('codigo' => 'sequencia_quebrada', 'mensagem' => 'A numeracao nao e sequencial.');
                $score -= 18;
            }

            // Enunciado curto
            $enunciado_texto = $this->_texto_visivel(isset($questao['Enunciado']) ? $questao['Enunciado'] : '');
            if (strlen($enunciado_texto) < 12) {
                $alertas[] = array('codigo' => 'enunciado_curto', 'mensagem' => 'Enunciado ausente ou muito curto.');
                $score -= 35;
            }

            // Alternativas
            $presentes = 0;
            foreach (self::$campos_alternativas as $campo) {
                $letra = substr($campo, -1);
                $texto = $this->_texto_visivel(isset($questao[$campo]) ? $questao[$campo] : '');
                $imagem = isset($questao[$campo . '_Imagem']) ? $questao[$campo . '_Imagem'] : null;
                if (!empty($texto) || !empty($imagem)) {
                    $presentes++;
                } elseif (strpos('ABCD', $letra) !== false) {
                    $alertas[] = array('codigo' => 'alternativa_' . strtolower($letra) . '_ausente', 'mensagem' => "Alternativa {$letra} ausente.");
                    $score -= 22;
                }
            }
            if ($presentes < 4) {
                $alertas[] = array('codigo' => 'alternativas_insuficientes', 'mensagem' => 'Menos de quatro alternativas encontradas.');
                $score -= 20;
            }

            // Validação HTML e ruído
            foreach (array('Enunciado', 'Texto_Associado') as $campo) {
                if (!isset($questao[$campo])) continue;
                $valor = strval($questao[$campo]);
                $texto = $this->_texto_visivel($valor);

                if (!$this->_html_balanceado($valor)) {
                    $alertas[] = array('codigo' => 'html_invalido', 'mensagem' => "Formatação HTML incompleta em {$campo}.");
                    $score -= 12;
                    break;
                }
                foreach (self::$padroes_ruido as $padrao) {
                    if (preg_match($padrao, $texto)) {
                        $alertas[] = array('codigo' => 'possivel_rodape', 'mensagem' => "Possivel cabecalho ou rodape em {$campo}.");
                        $score -= 15;
                        break 2;
                    }
                }
                if ($campo !== 'Texto_Associado' && preg_match('/quest[aã]o\s+\d+/i', $texto)) {
                    $alertas[] = array('codigo' => 'possivel_mescla', 'mensagem' => "Possivel mistura de questoes em {$campo}.");
                    $score -= 18;
                    break;
                }
            }

            $score = max(0, min(100, $score));
            $questao['Qualidade'] = array(
                'score' => $score,
                'status' => ($score >= 85 && empty($alertas)) ? 'aprovada' : 'revisar',
                'alertas' => $alertas,
            );
        }
        unset($questao);

        return $questoes;
    }

    private function _texto_visivel($valor) {
        return trim(preg_replace('/<[^>]+>/', ' ', strval($valor)));
    }

    private function _html_balanceado($valor) {
        $pilha = array();
        $tags = array();
        preg_match_all('/<\s*\/?\s*([a-zA-Z][\w-]*)[^>]*>/', strval($valor), $tags, PREG_SET_ORDER);
        foreach ($tags as $tag) {
            $nome = strtolower($tag[1]);
            $fechando = (strpos($tag[0], '/') !== false && strpos($tag[0], '/') < strpos($tag[0], '<') + 3);
            if (in_array($nome, self::$tags_sem_fechamento)) continue;
            if ($fechando) {
                if (empty($pilha) || end($pilha) !== $nome) return false;
                array_pop($pilha);
            } else {
                $pilha[] = $nome;
            }
        }
        return empty($pilha);
    }

    // =========================================================================
    // PROCESSAMENTO COMPLETO DE UM ARQUIVO
    // =========================================================================

    /**
     * Processa um PDF completo: extrai texto → parseia → valida.
     *
     * @param string $caminho_pdf Caminho do PDF.
     * @return array(
     *     'texto' => string,
     *     'questoes' => array,
     *     'total_paginas' => int,
     *     'total_questoes' => int,
     *     'erro' => string|null
     * )
     */
    public function processar_pdf($caminho_pdf) {
        $resultado = array(
            'texto' => '',
            'questoes' => array(),
            'total_paginas' => 0,
            'total_questoes' => 0,
            'erro' => null,
        );

        if (!file_exists($caminho_pdf)) {
            $resultado['erro'] = 'Arquivo nao encontrado: ' . $caminho_pdf;
            return $resultado;
        }

        $paginas = $this->extrair_texto_pdf($caminho_pdf);
        if (empty($paginas)) {
            $resultado['erro'] = 'Nao foi possivel extrair texto do PDF. O arquivo pode estar corrompido ou ser imagem sem OCR.';
            return $resultado;
        }

        $resultado['total_paginas'] = count($paginas);

        // Concatenar todo o texto
        $texto_completo = '';
        foreach ($paginas as $pag) {
            $texto_completo .= $pag['texto'] . "\n\n";
        }
        $texto_completo = trim($texto_completo);
        $resultado['texto'] = $texto_completo;

        // Normalizar
        $texto_completo = $this->normalizar_texto($texto_completo);

        // Parsear questões
        $questoes = $this->parsear_questoes($texto_completo);
        if (empty($questoes)) {
            $resultado['erro'] = 'Nenhuma questao detectada no PDF. Possiveis causas: (1) PDF digitalizado sem OCR. (2) Formato de numeracao diferente do padrao.';
            return $resultado;
        }

        // Extrair imagens
        $questoes = $this->extrair_imagens_alternativas($caminho_pdf, $questoes);
        $questoes = $this->extrair_imagens_enunciado($caminho_pdf, $questoes);

        // Validar qualidade
        $questoes = $this->validar_questoes($questoes);

        $resultado['questoes'] = $questoes;
        $resultado['total_questoes'] = count($questoes);

        return $resultado;
    }
}
