<?php
/**
 * Pomaroli_Gemini - Integração com Google Gemini API para OCR e revisão.
 *
 * Fornece:
 *  - OCR de páginas digitalizadas via Vision API
 *  - Refinamento de questões com baixa qualidade
 *  - Revisão em lote de questões
 *
 * Usa wp_remote_post para chamadas HTTP (sem dependência externa).
 */

if (!defined('ABSPATH')) {
    exit;
}

class Pomaroli_Gemini {

    const API_BASE = 'https://generativelanguage.googleapis.com/v1beta';

    private static $instance = null;

    public static function get_instance() {
        if (self::$instance === null) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    private function __construct() {}

    // =========================================================================
    // CONFIGURAÇÃO
    // =========================================================================

    /**
     * Retorna a API key do Gemini (opcional, pode ser passada por parâmetro).
     */
    public function get_api_key($api_key = '') {
        if (!empty($api_key)) {
            return $api_key;
        }
        return get_option('pomaroli_gemini_api_key', '');
    }

    /**
     * Retorna o modelo padrão.
     */
    public function get_model($model = '') {
        if (!empty($model)) {
            return $model;
        }
        return get_option('pomaroli_ai_model', 'gemini-2.5-flash');
    }

    // =========================================================================
    // CHAMADA À API
    // =========================================================================

    /**
     * Envia conteúdo para o Gemini API (generateContent).
     *
     * @param array $contents Array de parts (text e/ou inline_data).
     * @param string $api_key Chave da API.
     * @param string $model Modelo a usar.
     * @return array|WP_Error Resposta decodificada ou erro.
     */
    private function _call_api($contents, $api_key, $model) {
        $endpoint = self::API_BASE . '/models/' . $model . ':generateContent?key=' . $api_key;

        $payload = array(
            'contents' => $contents,
            'generationConfig' => array(
                'temperature' => 0.2,
                'maxOutputTokens' => 8192,
            ),
        );

        $response = wp_remote_post($endpoint, array(
            'headers' => array('Content-Type' => 'application/json'),
            'body'    => wp_json_encode($payload),
            'timeout' => 120,
        ));

        if (is_wp_error($response)) {
            return $response;
        }

        $code = wp_remote_retrieve_response_code($response);
        $body = wp_remote_retrieve_body($response);
        $decoded = json_decode($body, true);

        if ($code !== 200) {
            $msg = isset($decoded['error']['message']) ? $decoded['error']['message'] : 'Erro desconhecido da API Gemini.';
            return new WP_Error('gemini_api_error', $msg, array('status' => $code));
        }

        return $decoded;
    }

    /**
     * Extrai texto da resposta do Gemini.
     */
    private function _extract_text($response) {
        if (is_wp_error($response)) {
            return '';
        }
        if (isset($response['candidates'][0]['content']['parts'])) {
            $text = '';
            foreach ($response['candidates'][0]['content']['parts'] as $part) {
                if (isset($part['text'])) {
                    $text .= $part['text'];
                }
            }
            return $text;
        }
        return '';
    }

    // =========================================================================
    // OCR VIA VISION
    // =========================================================================

    /**
     * Usa Gemini Vision para extrair texto de uma imagem (página digitalizada).
     *
     * @param string $image_base64 Conteúdo da imagem em base64.
     * @param string $api_key Chave da API.
     * @param string $model Modelo (padrão: gemini-2.5-flash).
     * @return string|WP_Error Texto extraído ou erro.
     */
    public function ocr_image($image_base64, $api_key = '', $model = '') {
        $api_key = $this->get_api_key($api_key);
        if (empty($api_key)) {
            return new WP_Error('missing_api_key', 'Chave da API Gemini nao configurada.');
        }

        $model = $this->get_model($model);

        $prompt = "Extraia TODO o texto desta imagem de prova/concurso. "
            . "Mantenha a formatacao original: numeros de questoes (1. 2. 3.), "
            . "letras de alternativas (A. B. C. D. E.), e qualquer texto associado. "
            . "Retorne APENAS o texto extraido, sem comentarios adicionais.";

        $contents = array(
            array(
                'parts' => array(
                    array('text' => $prompt),
                    array(
                        'inline_data' => array(
                            'mime_type' => 'image/png',
                            'data'      => $image_base64,
                        ),
                    ),
                ),
            ),
        );

        $response = $this->_call_api($contents, $api_key, $model);
        return $this->_extract_text($response);
    }

    /**
     * OCR de múltiplas páginas (em loop).
     *
     * @param array $imagens_base64 Array de imagens em base64.
     * @param string $api_key Chave da API.
     * @param string $model Modelo.
     * @return array Array de textos extraídos.
     */
    public function ocr_multiplas_paginas($imagens_base64, $api_key = '', $model = '') {
        $resultados = array();
        foreach ($imagens_base64 as $idx => $img_b64) {
            $texto = $this->ocr_image($img_b64, $api_key, $model);
            $resultados[] = array(
                'pagina' => $idx + 1,
                'texto'  => is_wp_error($texto) ? '' : $texto,
                'erro'   => is_wp_error($texto) ? $texto->get_error_message() : null,
            );
            // Respeitar rate limit do tier gratuito (1 RPM para vision)
            sleep(1);
        }
        return $resultados;
    }

    // =========================================================================
    // REFINAMENTO DE QUESTÕES
    // =========================================================================

    /**
     * Refina uma questão com baixa qualidade usando Gemini.
     *
     * @param array $questao Dados da questão.
     * @param string $api_key Chave da API.
     * @param string $model Modelo.
     * @return array|WP_Error Questão refinada ou erro.
     */
    public function refinar_questao($questao, $api_key = '', $model = '') {
        $api_key = $this->get_api_key($api_key);
        if (empty($api_key)) {
            return new WP_Error('missing_api_key', 'Chave da API Gemini nao configurada.');
        }

        $model = $this->get_model($model);

        $questao_json = wp_json_encode($questao, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);

        $prompt = "Voce e um editor especializado em provas de concursos publicos brasileiros. "
            . "Refine a seguinte questao, corrigindo:\n"
            . "- Erros de OCR (letras trocadas, espacos faltando, acentos errados)\n"
            . "- Pontuacao e gramatica\n"
            . "- Formatacao HTML quebrada\n"
            . "- Alternativas incompletas ou com texto truncado\n\n"
            . "IMPORTANTE:\n"
            . "- NAO altere o sentido ou conteudo da questao\n"
            . "- NAO adicione informacoes novas\n"
            . "- Mantenha o numero da questao e as letras das alternativas\n"
            . "- Retorne APENAS o JSON da questao refinada, sem markdown, sem comentarios\n\n"
            . "Questao:\n" . $questao_json;

        $contents = array(
            array(
                'parts' => array(
                    array('text' => $prompt),
                ),
            ),
        );

        $response = $this->_call_api($contents, $api_key, $model);
        $texto = $this->_extract_text($response);

        if (empty($texto)) {
            return new WP_Error('empty_response', 'Gemini retornou resposta vazia.');
        }

        // Limpar possíveis markers markdown
        $texto = trim($texto);
        $texto = preg_replace('/^```json\s*/i', '', $texto);
        $texto = preg_replace('/```\s*$/', '', $texto);
        $texto = trim($texto);

        $decodificado = json_decode($texto, true);
        if (!is_array($decodificado)) {
            return new WP_Error('invalid_json', 'Gemini retornou JSON invalido.');
        }

        return $decodificado;
    }

    // =========================================================================
    // REVISÃO EM LOTE
    // =========================================================================

    /**
     * Revisa múltiplas questões de uma vez (batch review).
     *
     * @param array $questoes Array de questões.
     * @param string $api_key Chave da API.
     * @param string $model Modelo.
     * @return array Array de questões revisadas.
     */
    public function revisar_lote($questoes, $api_key = '', $model = '') {
        $api_key = $this->get_api_key($api_key);
        if (empty($api_key)) {
            return $questoes;
        }

        $model = $this->get_model($model);

        // Processar em blocos de 5 (limitar tokens)
        $batches = array_chunk($questoes, 5);
        $revisadas = array();

        foreach ($batches as $batch) {
            $batch_json = wp_json_encode($batch, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT);

            $prompt = "Voce e um revisor de provas de concursos. Revise as seguintes questoes. "
                . "Para cada questao, verifique:\n"
                . "1. Se o enunciado esta completo e claro\n"
                . "2. Se as alternativas estao semanticamente corretas\n"
                . "3. Se ha erros de portugues ou formatacao\n\n"
                . "Retorne o array JSON das questoes com campo 'revisao_ia' adicionado contendo: "
                . "'aprovada' ou 'revisar' + 'observacoes' (string).\n"
                . "Retorne APENAS o JSON, sem markdown.\n\n"
                . "Questoes:\n" . $batch_json;

            $contents = array(
                array(
                    'parts' => array(
                        array('text' => $prompt),
                    ),
                ),
            );

            $response = $this->_call_api($contents, $api_key, $model);
            $texto = $this->_extract_text($response);

            if (!empty($texto)) {
                $texto = trim($texto);
                $texto = preg_replace('/^```json\s*/i', '', $texto);
                $texto = preg_replace('/```\s*$/', '', $texto);
                $decodificado = json_decode(trim($texto), true);
                if (is_array($decodificado)) {
                    $revisadas = array_merge($revisadas, $decodificado);
                } else {
                    $revisadas = array_merge($revisadas, $batch);
                }
            } else {
                $revisadas = array_merge($revisadas, $batch);
            }

            // Rate limit
            sleep(1);
        }

        return $revisadas;
    }

    // =========================================================================
    // HEALTH CHECK
    // =========================================================================

    /**
     * Verifica se a API key está funcionando.
     *
     * @param string $api_key Chave da API.
     * @return array|WP_Error Status da API.
     */
    public function health_check($api_key = '') {
        $api_key = $this->get_api_key($api_key);
        if (empty($api_key)) {
            return new WP_Error('missing_api_key', 'Chave da API Gemini nao configurada.');
        }

        $model = $this->get_model();
        $contents = array(
            array(
                'parts' => array(
                    array('text' => 'Responda apenas: OK'),
                ),
            ),
        );

        $response = $this->_call_api($contents, $api_key, $model);
        if (is_wp_error($response)) {
            return $response;
        }

        return array(
            'status' => 'ok',
            'model'  => $model,
            'message' => 'API Gemini funcionando.',
        );
    }
}
