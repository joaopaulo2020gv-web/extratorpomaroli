<?php
/**
 * Pomaroli_Migrate - Migra dados do wp_options (extrator_lotes_cache) para as novas tabelas.
 */

if (!defined('ABSPATH')) {
    exit;
}

class Pomaroli_Migrate {

    const MIGRATION_KEY = 'pomaroli_migrated_v1';
    const OLD_CACHE_KEY = 'extrator_lotes_cache';

    private $db;

    public function __construct() {
        $this->db = Pomaroli_DB::get_instance();
    }

    /**
     * Verifica se a migração já foi concluída.
     */
    public function is_migrated() {
        return get_option(self::MIGRATION_KEY, false);
    }

    /**
     * Executa a migração completa dos dados antigos.
     */
    public function run_migration() {
        if ($this->is_migrated()) {
            return array('status' => 'already_migrated');
        }

        $old_cache = get_option(self::OLD_CACHE_KEY, array());
        if (empty($old_cache) || !is_array($old_cache)) {
            update_option(self::MIGRATION_KEY, true);
            return array('status' => 'no_data', 'message' => 'Nenhum dado antigo encontrado para migrar.');
        }

        $migrated = 0;
        $errors = array();

        foreach ($old_cache as $batch_id => $batch_data) {
            if (empty($batch_id) || !is_array($batch_data)) {
                continue;
            }

            // Verificar se o job já existe (evitar duplicatas)
            $existing = $this->db->get_job_by_batch_id($batch_id);
            if ($existing) {
                $migrated++;
                continue;
            }

            // Extrair dados do batch
            $user_id = $this->resolve_user_id($batch_data);
            $status = $this->map_status($batch_data['status'] ?? 'concluido');

            $job_id = $this->db->create_job(array(
                'user_id'           => $user_id,
                'batch_id_externo'  => $batch_id,
                'status'            => $status,
                'total_files'       => intval($batch_data['total_files'] ?? 0),
                'processed_files'   => intval($batch_data['processed_files'] ?? count($batch_data['files'] ?? array())),
                'total_questions'   => intval($batch_data['total_questions'] ?? 0),
                'total_pages'       => intval($batch_data['total_pages'] ?? 0),
                'progress'          => intval($batch_data['progress'] ?? 100),
                'ai_provider'       => sanitize_text_field($batch_data['api_provider'] ?? ''),
                'ai_model'          => sanitize_text_field($batch_data['ai_model'] ?? ''),
                'use_ocr'           => intval($batch_data['use_ocr'] ?? 0),
                'use_ai_segmentation' => intval($batch_data['use_ai_segmentation'] ?? 0),
                'wp_site_url'       => esc_url_raw($batch_data['wp_site_url'] ?? ''),
                'meta_json'         => wp_json_encode(array(
                    'auto_save'     => $batch_data['auto_save'] ?? false,
                    'tempo_estimado' => $batch_data['tempo_estimado'] ?? '',
                    'migrated_from' => 'wp_options',
                )),
                'started_at'        => $batch_data['started_at'] ?? null,
                'finished_at'       => $batch_data['finished_at'] ?? $batch_data['completed_at'] ?? null,
            ));

            if (!$job_id) {
                $errors[] = array('batch_id' => $batch_id, 'error' => 'Falha ao criar job');
                continue;
            }

            // Migrar arquivos
            $files = $batch_data['files'] ?? array();
            foreach ($files as $idx => $file_data) {
                $file_id = $this->db->create_file(array(
                    'job_id'        => $job_id,
                    'file_index'    => $idx,
                    'filename'      => $file_data['filename'] ?? ($file_data['nome'] ?? "arquivo_{$idx}.pdf"),
                    'file_path'     => $file_data['file_path'] ?? ($file_data['url'] ?? ''),
                    'file_size'     => intval($file_data['file_size'] ?? 0),
                    'status'        => $this->map_file_status($file_data['status'] ?? 'concluido'),
                    'pages'         => intval($file_data['pages'] ?? 0),
                    'questions_found' => intval($file_data['questions_found'] ?? 0),
                    'meta_json'     => wp_json_encode($file_data),
                ));
            }

            // Migrar questões
            $questions = $batch_data['questions'] ?? array();
            $questions_to_insert = array();
            foreach ($questions as $qidx => $q_data) {
                $questions_to_insert[] = array(
                    'job_id'           => $job_id,
                    'file_id'          => null, // Não temos referência exata ao arquivo
                    'question_number'  => intval($q_data['numero'] ?? ($qidx + 1)),
                    'question_data'    => $q_data,
                    'status'           => 'extraida',
                    'quality_score'    => null,
                    'quality_status'   => '',
                    'ai_reviewed'      => 0,
                    'review_status'    => 'pending',
                );
            }

            if (!empty($questions_to_insert)) {
                $this->db->create_questions_batch($questions_to_insert);
                $this->db->update_job($job_id, array(
                    'total_questions' => count($questions_to_insert),
                ));
            }

            $migrated++;
        }

        // Marcar migração como concluída
        update_option(self::MIGRATION_KEY, true);

        $this->db->log('info', "Migração concluída: {$migrated} lotes migrados, " . count($errors) . " erros", 0, null, array(
            'total_batches'  => count($old_cache),
            'migrated'       => $migrated,
            'errors'         => $errors,
        ));

        return array(
            'status'   => 'completed',
            'migrated' => $migrated,
            'errors'   => $errors,
        );
    }

    /**
     * Remove os dados antigos do wp_options após migração bem-sucedida.
     * Só remove se a migração foi 100% OK (sem erros).
     */
    public function cleanup_old_data($force = false) {
        if (!$this->is_migrated()) {
            return false;
        }

        $old_cache = get_option(self::OLD_CACHE_KEY, array());
        if (empty($old_cache)) {
            return true;
        }

        if ($force) {
            delete_option(self::OLD_CACHE_KEY);
            return true;
        }

        // Só limpar se não houve erros na migração
        return false;
    }

    /**
     * Tenta resolver o user_id a partir dos dados do batch.
     */
    private function resolve_user_id($batch_data) {
        if (!empty($batch_data['user_id'])) {
            return intval($batch_data['user_id']);
        }

        // Tentar encontrar o criador do lote
        if (!empty($batch_data['created_by'])) {
            $user = get_user_by('login', $batch_data['created_by']);
            if ($user) {
                return $user->ID;
            }
        }

        // Fallback: primeiro admin
        $admins = get_users(array('role' => 'administrator', 'number' => 1, 'fields' => 'ID'));
        return !empty($admins) ? $admins[0] : 1;
    }

    /**
     * Mapeia status antigo para novo formato.
     */
    private function map_status($old_status) {
        $map = array(
            'aguardando'  => 'queued',
            'aguardando_upload' => 'queued',
            'na_fila'     => 'queued',
            'processando' => 'processing',
            'concluido'   => 'completed',
            'concluído'   => 'completed',
            'finalizado'  => 'completed',
            'completo'    => 'completed',
            'erro'        => 'failed',
            'cancelado'   => 'cancelled',
        );
        return $map[$old_status] ?? 'queued';
    }

    /**
     * Mapeia status de arquivo antigo.
     */
    private function map_file_status($old_status) {
        $map = array(
            'pendente'    => 'pending',
            'processando' => 'processing',
            'concluido'   => 'completed',
            'concluído'   => 'completed',
            'erro'        => 'failed',
        );
        return $map[$old_status] ?? 'pending';
    }
}
