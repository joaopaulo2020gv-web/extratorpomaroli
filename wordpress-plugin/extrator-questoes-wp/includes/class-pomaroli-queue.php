<?php
/**
 * Pomaroli_Queue - Fila de jobs delegada ao Python Worker (cPanel).
 *
 * O processamento de PDF é feita EXCLUSIVAMENTE pelo Python Worker.
 * Esta classe gerencia apenas o estado dos jobs no WordPress.
 *
 * Fluxo:
 *  1. Upload → job criado (status=queued)
 *  2. Python Worker (cPanel Cron) consome via REST API HMAC
 *  3. Worker processa em blocos, salva progresso/questões via REST
 *  4. WordPress é a fonte oficial de estado
 */

if (!defined('ABSPATH')) {
    exit;
}

class Pomaroli_Queue {

    private static $instance = null;
    private $db;

    public static function get_instance() {
        if (self::$instance === null) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    private function __construct() {
        $this->db = Pomaroli_DB::get_instance();
    }

    // =========================================================================
    // INICIALIZAÇÃO
    // =========================================================================

    /**
     * Inicializa a fila. Sem WP-Cron. O Python worker é o único processador.
     */
    public function init() {
        // Nada a fazer — Python worker acionado pelo cPanel Cron
    }

    /**
     * Remove hooks na desativação.
     */
    public function deinit() {
        // Nada a limpar
    }

    // =========================================================================
    // ENFILEIRAR
    // =========================================================================

    /**
     * Enfileira um job para processamento pelo Python Worker.
     *
     * @param int $job_id ID do job.
     * @return bool Sucesso.
     */
    public function enqueue($job_id) {
        $job = $this->db->get_job($job_id);
        if (!$job) {
            return false;
        }

        if (!in_array($job->status, array('queued', 'failed'))) {
            return false;
        }

        $this->db->update_job($job_id, array(
            'status' => 'queued',
        ));

        $this->db->log('info', "Job #{$job_id} enfileirado (aguardando Python Worker)", 0, $job_id);

        return true;
    }

    // =========================================================================
    // CONTROLE
    // =========================================================================

    /**
     * Cancela um job.
     */
    public function cancelar($job_id) {
        $job = $this->db->get_job($job_id);
        if (!$job) {
            return false;
        }

        $this->db->update_job($job_id, array(
            'status'      => 'cancelled',
            'finished_at' => current_time('mysql'),
        ));

        $files = $this->db->get_files_by_job($job_id);
        foreach ($files as $file) {
            if (in_array($file->status, array('pending', 'queued', 'processing'))) {
                $this->db->update_file($file->id, array(
                    'status' => 'cancelled',
                ));
            }
        }

        $this->db->log('info', "Job #{$job_id} cancelado", 0, $job_id);
        return true;
    }

    /**
     * Reprocessa um job com erro (reseta status para queued).
     */
    public function reprocessar($job_id) {
        $job = $this->db->get_job($job_id);
        if (!$job) {
            return false;
        }

        if (!in_array($job->status, array('failed', 'cancelled'))) {
            return false;
        }

        global $wpdb;
        $table = $this->db->table_files();
        $wpdb->query($wpdb->prepare(
            "UPDATE {$table} SET status = 'queued', error_message = NULL, progress = 0 WHERE job_id = %d AND status IN ('failed', 'cancelled')",
            $job_id
        ));

        return $this->enqueue($job_id);
    }

    /**
     * Retorna status da fila.
     */
    public function get_queue_status() {
        global $wpdb;
        $table = $this->db->table_jobs();

        $queued = intval($wpdb->get_var(
            "SELECT COUNT(*) FROM {$table} WHERE status = 'queued'"
        ));
        $processing = intval($wpdb->get_var(
            "SELECT COUNT(*) FROM {$table} WHERE status = 'processing'"
        ));
        $completed_today = intval($wpdb->get_var(
            $wpdb->prepare(
                "SELECT COUNT(*) FROM {$table} WHERE status = 'completed' AND DATE(finished_at) = %s",
                current_time('Y-m-d')
            )
        ));

        return array(
            'queued'            => $queued,
            'processing'        => $processing,
            'completed_today'   => $completed_today,
            'worker'            => 'python',
        );
    }
}
