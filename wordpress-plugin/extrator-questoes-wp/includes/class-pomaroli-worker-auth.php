<?php
/**
 * Pomaroli_Worker_Auth - Autenticação HMAC para comunicação Python ↔ WordPress.
 *
 * Substitui o secret fixo por assinatura HMAC.
 * O worker (Python) assina cada request com o segredo compartilhado.
 * O WordPress valida a assinatura antes de processar.
 */

if (!defined('ABSPATH')) {
    exit;
}

class Pomaroli_Worker_Auth {

    const SECRET_OPTION = 'pomaroli_worker_secret';
    const HMAC_HEADER   = 'X-Pomaroli-Hmac';
    const TIMESTAMP_HEADER = 'X-Pomaroli-Timestamp';
    const MAX_AGE_SECONDS = 300; // Requests com mais de 5 minutos são rejeitadas

    private static $instance = null;

    public static function get_instance() {
        if (self::$instance === null) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    private function __construct() {}

    /**
     * Obtém ou gera o segredo do worker.
     */
    public function get_secret() {
        $secret = get_option(self::SECRET_OPTION, '');
        if (empty($secret)) {
            $secret = $this->generate_secret();
            update_option(self::SECRET_OPTION, $secret);
        }
        return $secret;
    }

    /**
     * Gera um novo segredo aleatório de 64 caracteres.
     */
    public function generate_secret() {
        if (function_exists('random_bytes')) {
            return bin2hex(random_bytes(32));
        }
        $secret = '';
        for ($i = 0; $i < 64; $i++) {
            $secret .= dechex(mt_rand(0, 15));
        }
        return $secret;
    }

    /**
     * Regenera o segredo (útil se comprometido).
     */
    public function regenerate_secret() {
        $new_secret = $this->generate_secret();
        update_option(self::SECRET_OPTION, $new_secret);
        return $new_secret;
    }

    /**
     * Calcula HMAC-SHA256 para dados.
     */
    public function compute_hmac($payload, $timestamp) {
        $secret = $this->get_secret();
        $message = $timestamp . '.' . $payload;
        return hash_hmac('sha256', $message, $secret);
    }

    /**
     * Valida o HMAC de um request recebido.
     *
     * @param string $body         Corpo do request (raw).
     * @param string $hmac_header  Valor do header X-Pomaroli-Hmac.
     * @param string $ts_header    Valor do header X-Pomaroli-Timestamp.
     * @return true|WP_Error true se válido, WP_Error caso contrário.
     */
    public function validate_hmac($body, $hmac_header, $ts_header) {
        if (empty($hmac_header) || empty($ts_header)) {
            return new WP_Error('missing_hmac', 'Headers de autenticação HMAC ausentes.');
        }

        $timestamp = intval($ts_header);
        $age = abs(time() - $timestamp);
        if ($age > self::MAX_AGE_SECONDS) {
            return new WP_Error('expired_hmac', 'Request HMAC expirado (idade: ' . $age . 's).');
        }

        $expected_hmac = $this->compute_hmac($body, $timestamp);
        if (!hash_equals($expected_hmac, $hmac_header)) {
            return new WP_Error('invalid_hmac', 'Assinatura HMAC inválida.');
        }

        return true;
    }

    /**
     * Valida um request HTTP do workerPython.
     *
     * @return true|WP_Error
     */
    public function validate_worker_request() {
        $hmac = isset($_SERVER['HTTP_X_POMAROLI_HMAC']) ? sanitize_text_field($_SERVER['HTTP_X_POMAROLI_HMAC']) : '';
        $timestamp = isset($_SERVER['HTTP_X_POMAROLI_TIMESTAMP']) ? sanitize_text_field($_SERVER['HTTP_X_POMAROLI_TIMESTAMP']) : '';

        $raw_body = file_get_contents('php://input');
        return $this->validate_hmac($raw_body, $hmac, $timestamp);
    }

    /**
     * Gera headers HMAC para um request de saída (para uso pelo Python).
     *
     * @param string $payload Corpo da request.
     * @return array Headers para adicionar ao request HTTP.
     */
    public function sign_request($payload) {
        $timestamp = strval(time());
        $hmac = $this->compute_hmac($payload, $timestamp);
        return array(
            self::HMAC_HEADER       => $hmac,
            self::TIMESTAMP_HEADER  => $timestamp,
            'Content-Type'          => 'application/json',
        );
    }

    /**
     * Retorna informações sobre o status da autenticação (para debug/admin).
     */
    public function get_status() {
        $secret = get_option(self::SECRET_OPTION, '');
        return array(
            'has_secret'  => !empty($secret),
            'secret_length' => strlen($secret),
            'secret_preview' => !empty($secret) ? substr($secret, 0, 8) . '...' : 'N/A',
        );
    }
}
