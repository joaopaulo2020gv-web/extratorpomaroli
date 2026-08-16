<?php
/**
 * Pomaroli_REST - Endpoints REST API para o dashboard do WordPress.
 *
 * Registra rotas REST under /wp-json/pomaroli/v1/
 * Inclui endpoints de administração e endpoints para o worker Python.
 */

if (!defined('ABSPATH')) {
    exit;
}

class Pomaroli_REST {

    const NAMESPACE = 'pomaroli/v1';
    private $db;
    private $auth;

    public function __construct() {
        $this->db   = Pomaroli_DB::get_instance();
        $this->auth = Pomaroli_Worker_Auth::get_instance();
        add_action('rest_api_init', array($this, 'register_routes'));
    }

    // =========================================================================
    // REGISTRO DAS ROTAS
    // =========================================================================

    public function register_routes() {

        // ---- JOBS (usuário logado) ----
        register_rest_route(self::NAMESPACE, '/jobs', array(
            array(
                'methods'             => 'GET',
                'callback'            => array($this, 'list_jobs'),
                'permission_callback' => array($this, 'is_user_logged_in'),
                'args'                => $this->list_jobs_args(),
            ),
            array(
                'methods'             => 'POST',
                'callback'            => array($this, 'create_job'),
                'permission_callback' => array($this, 'is_user_logged_in'),
                'args'                => $this->create_job_args(),
            ),
        ));

        register_rest_route(self::NAMESPACE, '/jobs/(?P<id>\d+)', array(
            array(
                'methods'             => 'GET',
                'callback'            => array($this, 'get_job'),
                'permission_callback' => array($this, 'is_user_logged_in'),
            ),
            array(
                'methods'             => array('DELETE', 'POST'),
                'callback'            => array($this, 'delete_job'),
                'permission_callback' => array($this, 'is_user_logged_in'),
            ),
            array(
                'methods'             => 'POST',
                'callback'            => array($this, 'update_job_status'),
                'permission_callback' => array($this, 'is_user_logged_in'),
            ),
        ));

        register_rest_route(self::NAMESPACE, '/jobs/(?P<id>\d+)/delete', array(
            'methods'             => array('POST', 'DELETE'),
            'callback'            => array($this, 'delete_job'),
            'permission_callback' => array($this, 'is_user_logged_in'),
        ));

        register_rest_route(self::NAMESPACE, '/jobs/(?P<id>\d+)/retry', array(
            'methods'             => 'POST',
            'callback'            => array($this, 'retry_job'),
            'permission_callback' => array($this, 'is_user_logged_in'),
        ));

        register_rest_route(self::NAMESPACE, '/jobs/(?P<id>\d+)/files', array(
            'methods'             => 'GET',
            'callback'            => array($this, 'get_job_files'),
            'permission_callback' => array($this, 'is_user_logged_in'),
        ));

        // ---- QUESTIONS (usuário logado) ----
        register_rest_route(self::NAMESPACE, '/questions', array(
            array(
                'methods'             => 'GET',
                'callback'            => array($this, 'list_questions'),
                'permission_callback' => array($this, 'is_user_logged_in'),
            ),
        ));

        register_rest_route(self::NAMESPACE, '/questions/(?P<id>\d+)', array(
            array(
                'methods'             => 'GET',
                'callback'            => array($this, 'get_question'),
                'permission_callback' => array($this, 'is_user_logged_in'),
            ),
            array(
                'methods'             => 'PUT',
                'callback'            => array($this, 'update_question'),
                'permission_callback' => array($this, 'is_user_logged_in'),
            ),
        ));

        register_rest_route(self::NAMESPACE, '/questions/(?P<id>\d+)/review', array(
            'methods'             => 'POST',
            'callback'            => array($this, 'review_question'),
            'permission_callback' => array($this, 'is_user_logged_in'),
        ));

        register_rest_route(self::NAMESPACE, '/questions/import-to-wp', array(
            'methods'             => 'POST',
            'callback'            => array($this, 'import_questions_to_wp'),
            'permission_callback' => array($this, 'is_user_logged_in'),
        ));

        // ---- STATS ----
        register_rest_route(self::NAMESPACE, '/stats', array(
            'methods'             => 'GET',
            'callback'            => array($this, 'get_stats'),
            'permission_callback' => array($this, 'is_user_logged_in'),
        ));

        // ---- SETTINGS ----
        register_rest_route(self::NAMESPACE, '/settings', array(
            array(
                'methods'             => 'GET',
                'callback'            => array($this, 'get_settings'),
                'permission_callback' => array($this, 'is_admin'),
            ),
            array(
                'methods'             => 'POST',
                'callback'            => array($this, 'save_settings'),
                'permission_callback' => array($this, 'is_admin'),
            ),
        ));

        // ---- LOGS ----
        register_rest_route(self::NAMESPACE, '/logs', array(
            'methods'             => 'GET',
            'callback'            => array($this, 'get_logs'),
            'permission_callback' => array($this, 'is_user_logged_in'),
        ));

        // ---- AI JOBS ----
        register_rest_route(self::NAMESPACE, '/ai-jobs', array(
            'methods'             => 'POST',
            'callback'            => array($this, 'create_ai_job'),
            'permission_callback' => array($this, 'is_user_logged_in'),
        ));

        register_rest_route(self::NAMESPACE, '/ai-jobs/(?P<id>\d+)', array(
            'methods'             => 'GET',
            'callback'            => array($this, 'get_ai_job'),
            'permission_callback' => array($this, 'is_user_logged_in'),
        ));

        // ---- UPLOAD LOCAL (usuário logado) ----
        register_rest_route(self::NAMESPACE, '/upload-local', array(
            'methods'             => 'POST',
            'callback'            => array($this, 'upload_local'),
            'permission_callback' => array($this, 'is_user_logged_in'),
        ));

        // ---- JOBS: PROCESS / CANCEL ----
        register_rest_route(self::NAMESPACE, '/jobs/(?P<id>\d+)/process', array(
            'methods'             => 'POST',
            'callback'            => array($this, 'process_job'),
            'permission_callback' => array($this, 'is_user_logged_in'),
        ));

        register_rest_route(self::NAMESPACE, '/jobs/(?P<id>\d+)/cancel', array(
            'methods'             => 'POST',
            'callback'            => array($this, 'cancel_job'),
            'permission_callback' => array($this, 'is_user_logged_in'),
        ));

        // ---- HEALTH ----
        register_rest_route(self::NAMESPACE, '/health', array(
            'methods'             => 'GET',
            'callback'            => array($this, 'health_check'),
            'permission_callback' => array($this, 'is_user_logged_in'),
        ));

        // ---- QUEUE STATUS ----
        register_rest_route(self::NAMESPACE, '/queue/status', array(
            'methods'             => 'GET',
            'callback'            => array($this, 'queue_status'),
            'permission_callback' => array($this, 'is_user_logged_in'),
        ));

        // ---- WORKER (autenticado via HMAC) ----
        register_rest_route(self::NAMESPACE, '/worker/update', array(
            'methods'             => 'POST',
            'callback'            => array($this, 'worker_update'),
            'permission_callback' => array($this, 'is_worker_authorized'),
        ));

        register_rest_route(self::NAMESPACE, '/worker/questions', array(
            'methods'             => 'POST',
            'callback'            => array($this, 'worker_save_questions'),
            'permission_callback' => array($this, 'is_worker_authorized'),
        ));

        register_rest_route(self::NAMESPACE, '/worker/complete', array(
            'methods'             => 'POST',
            'callback'            => array($this, 'worker_complete_job'),
            'permission_callback' => array($this, 'is_worker_authorized'),
        ));

        // ---- WORKER: NEXT JOB / CLAIM (autenticados via HMAC) ----
        register_rest_route(self::NAMESPACE, '/worker/next-job', array(
            'methods'             => 'GET',
            'callback'            => array($this, 'worker_next_job'),
            'permission_callback' => array($this, 'is_worker_authorized'),
        ));

        register_rest_route(self::NAMESPACE, '/worker/claim-job', array(
            'methods'             => 'POST',
            'callback'            => array($this, 'worker_claim_job'),
            'permission_callback' => array($this, 'is_worker_authorized'),
        ));

        // ---- WORKER: FILES (autenticado via HMAC) ----
        register_rest_route(self::NAMESPACE, '/worker/files/(?P<id>\d+)', array(
            'methods'             => 'GET',
            'callback'            => array($this, 'worker_get_files'),
            'permission_callback' => array($this, 'is_worker_authorized'),
        ));
    }

    // =========================================================================
    // PERMISSION CALLBACKS
    // =========================================================================

    public function is_user_logged_in() {
        return is_user_logged_in();
    }

    public function is_admin() {
        return is_user_logged_in() && current_user_can('manage_options');
    }

    public function is_worker_authorized() {
        $validation = $this->auth->validate_worker_request();
        return !is_wp_error($validation);
    }

    // =========================================================================
    // JOBS - HANDLERS
    // =========================================================================

    public function list_jobs($request) {
        $user_id = get_current_user_id();
        $args = array(
            'status'   => $request->get_param('status') ?? '',
            'orderby'  => $request->get_param('orderby') ?? 'created_at',
            'order'    => $request->get_param('order') ?? 'DESC',
            'per_page' => intval($request->get_param('per_page') ?? 20),
            'page'     => intval($request->get_param('page') ?? 1),
        );
        $result = $this->db->list_jobs($user_id, $args);
        return rest_ensure_response($result);
    }

    public function create_job($request) {
        $user_id = get_current_user_id();
        $params = $request->get_json_params();

        $job_id = $this->db->create_job(array(
            'user_id'            => $user_id,
            'batch_id_externo'   => sanitize_text_field($params['batch_id_externo'] ?? ''),
            'status'             => sanitize_text_field($params['status'] ?? 'queued'),
            'total_files'        => intval($params['total_files'] ?? 0),
            'ai_provider'        => sanitize_text_field($params['ai_provider'] ?? ''),
            'ai_model'           => sanitize_text_field($params['ai_model'] ?? ''),
            'use_ocr'            => intval($params['use_ocr'] ?? 0),
            'use_ai_segmentation'=> intval($params['use_ai_segmentation'] ?? 0),
            'wp_site_url'        => esc_url_raw(home_url('/')),
            'meta_json'          => wp_json_encode($params['meta'] ?? array()),
        ));

        if (!$job_id) {
            return new WP_Error('create_failed', 'Falha ao criar job.', array('status' => 500));
        }

        // Criar registros de arquivos se fornecidos
        $files = $params['files'] ?? array();
        foreach ($files as $idx => $file_data) {
            $this->db->create_file(array(
                'job_id'     => $job_id,
                'file_index' => $idx,
                'filename'   => sanitize_file_name($file_data['filename'] ?? "arquivo_{$idx}.pdf"),
                'file_size'  => intval($file_data['file_size'] ?? 0),
                'status'     => 'pending',
            ));
        }

        $this->db->log('info', "Job criado via API", $user_id, $job_id);

        $job = $this->db->get_job($job_id);
        $response = rest_ensure_response($job);
        $response->set_status(201);
        return $response;
    }

    public function get_job($request) {
        $user_id = get_current_user_id();
        $job_id = intval($request['id']);
        $job = $this->db->get_job($job_id, $user_id);

        if (!$job) {
            return new WP_Error('not_found', 'Job não encontrado.', array('status' => 404));
        }

        $files = $this->db->get_files_by_job($job_id);
        $questions = $this->db->list_questions(array('job_id' => $job_id, 'per_page' => 0));
        $job->files = $files;
        $job->questions_count = $questions['total'];

        return rest_ensure_response($job);
    }

    public function delete_job($request) {
        $user_id = get_current_user_id();
        $job_id = intval($request['id']);
        $job = $this->db->get_job($job_id, $user_id);

        if (!$job && current_user_can('manage_options')) {
            $job = $this->db->get_job($job_id, null);
        }

        if (!$job) {
            return new WP_Error('not_found', 'Job não encontrado.', array('status' => 404));
        }

        if (in_array($job->status, array('processing')) && !current_user_can('manage_options')) {
            return new WP_Error('cannot_delete', 'Não é possível excluir job em processamento. Cancele primeiro.', array('status' => 409));
        }

        $this->db->delete_job($job_id, current_user_can('manage_options') ? null : $user_id);
        $this->db->log('info', "Job #{$job_id} excluído", $user_id, $job_id);

        return rest_ensure_response(array('deleted' => true, 'id' => $job_id, 'message' => 'Processamento excluído com sucesso.'));
    }

    public function update_job_status($request) {
        $user_id = get_current_user_id();
        $job_id = intval($request['id']);
        $params = $request->get_json_params();

        $job = $this->db->get_job($job_id, $user_id);
        if (!$job) {
            return new WP_Error('not_found', 'Job não encontrado.', array('status' => 404));
        }

        $update_data = array();
        if (isset($params['status'])) {
            $update_data['status'] = sanitize_text_field($params['status']);
        }

        if (!empty($update_data)) {
            $this->db->update_job($job_id, $update_data);
        }

        return rest_ensure_response($this->db->get_job($job_id));
    }

    public function retry_job($request) {
        $user_id = get_current_user_id();
        $job_id = intval($request['id']);

        $job = $this->db->get_job($job_id, $user_id);
        if (!$job) {
            return new WP_Error('not_found', 'Job não encontrado.', array('status' => 404));
        }

        if ($job->status !== 'failed') {
            return new WP_Error('not_failed', 'Só é possível reenfileirar jobs com erro.', array('status' => 409));
        }

        $this->db->update_job($job_id, array(
            'status'         => 'queued',
            'error_message'  => null,
            'updated_at'     => current_time('mysql'),
        ));

        $this->db->log('info', "Job #{$job_id} reenfileirado", $user_id, $job_id);

        return rest_ensure_response($this->db->get_job($job_id));
    }

    public function get_job_files($request) {
        $user_id = get_current_user_id();
        $job_id = intval($request['id']);

        $job = $this->db->get_job($job_id, $user_id);
        if (!$job) {
            return new WP_Error('not_found', 'Job não encontrado.', array('status' => 404));
        }

        $files = $this->db->get_files_by_job($job_id);
        return rest_ensure_response($files);
    }

    // =========================================================================
    // QUESTIONS - HANDLERS
    // =========================================================================

    public function list_questions($request) {
        $user_id = get_current_user_id();
        $args = array(
            'job_id'        => intval($request->get_param('job_id') ?? 0),
            'file_id'       => intval($request->get_param('file_id') ?? 0),
            'status'        => $request->get_param('status') ?? '',
            'review_status' => $request->get_param('review_status') ?? '',
            'search'        => $request->get_param('search') ?? '',
            'orderby'       => $request->get_param('orderby') ?? 'question_number',
            'order'         => $request->get_param('order') ?? 'ASC',
            'per_page'      => intval($request->get_param('per_page') ?? 50),
            'page'          => intval($request->get_param('page') ?? 1),
            'user_id'       => $user_id,
        );
        $result = $this->db->list_questions($args);
        return rest_ensure_response($result);
    }

    public function get_question($request) {
        $question_id = intval($request['id']);
        $question = $this->db->get_question($question_id);

        if (!$question) {
            return new WP_Error('not_found', 'Questão não encontrada.', array('status' => 404));
        }

        return rest_ensure_response($question);
    }

    public function update_question($request) {
        $question_id = intval($request['id']);
        $params = $request->get_json_params();

        $question = $this->db->get_question($question_id);
        if (!$question) {
            return new WP_Error('not_found', 'Questão não encontrada.', array('status' => 404));
        }

        $update = array();
        if (isset($params['question_data'])) {
            $update['question_data'] = $params['question_data'];
        }
        if (isset($params['status'])) {
            $update['status'] = sanitize_text_field($params['status']);
        }
        if (isset($params['quality_score'])) {
            $update['quality_score'] = intval($params['quality_score']);
        }
        if (isset($params['quality_status'])) {
            $update['quality_status'] = sanitize_text_field($params['quality_status']);
        }
        if (isset($params['review_status'])) {
            $update['review_status'] = sanitize_text_field($params['review_status']);
        }

        if (!empty($update)) {
            $this->db->update_question($question_id, $update);
        }

        return rest_ensure_response($this->db->get_question($question_id));
    }

    public function review_question($request) {
        $question_id = intval($request['id']);
        $params = $request->get_json_params();
        $action = sanitize_text_field($params['action'] ?? '');

        $question = $this->db->get_question($question_id);
        if (!$question) {
            return new WP_Error('not_found', 'Questão não encontrada.', array('status' => 404));
        }

        $update = array('ai_reviewed' => 1);
        switch ($action) {
            case 'aprovar':
                $update['review_status'] = 'aprovada';
                $update['status'] = 'revisada';
                break;
            case 'rejeitar':
                $update['review_status'] = 'rejeitada';
                $update['status'] = 'rejeitada';
                break;
            case 'editar':
                if (isset($params['question_data'])) {
                    $update['question_data'] = $params['question_data'];
                }
                $update['review_status'] = 'editada';
                $update['status'] = 'revisada';
                break;
            default:
                return new WP_Error('invalid_action', 'Ação inválida.', array('status' => 400));
        }

        $this->db->update_question($question_id, $update);
        return rest_ensure_response($this->db->get_question($question_id));
    }

    public function import_questions_to_wp($request) {
        $user_id = get_current_user_id();
        $params = $request->get_json_params();
        $question_ids = $params['question_ids'] ?? array();

        if (empty($question_ids)) {
            return new WP_Error('no_questions', 'Nenhuma questão selecionada.', array('status' => 400));
        }

        $imported = 0;
        $errors = array();

        foreach ($question_ids as $qid) {
            $question = $this->db->get_question(intval($qid));
            if (!$question || $question->imported_to_wp) {
                continue;
            }

            $data = is_array($question->question_data) ? $question->question_data : json_decode($question->question_data, true);
            if (empty($data)) {
                $errors[] = array('id' => $qid, 'error' => 'Dados da questão inválidos');
                continue;
            }

            $post_id = wp_insert_post(array(
                'post_title'  => sanitize_text_field($data['titulo'] ?? $data['questao'] ?? "Questão #{$question->question_number}"),
                'post_type'   => 'questao',
                'post_status' => 'draft',
                'post_content' => wp_kses_post($data['enunciado'] ?? $data['question'] ?? ''),
                'meta_input'  => array(
                    'questao_opcoes'   => wp_json_encode($data['opcoes'] ?? $data['options'] ?? array()),
                    'questao_resposta' => sanitize_text_field($data['resposta_correta'] ?? $data['correct_answer'] ?? ''),
                    'questao_banca'    => sanitize_text_field($data['banca'] ?? ''),
                    'questao_disciplina'=> sanitize_text_field($data['disciplina'] ?? $data['materia'] ?? ''),
                    'questao_ano'      => sanitize_text_field($data['ano'] ?? ''),
                    'questao_alternativas' => wp_json_encode($data['alternativas'] ?? array()),
                    'questao_dificuldade' => sanitize_text_field($data['dificuldade'] ?? ''),
                    'questao_comentario'  => wp_kses_post($data['comentario'] ?? $data['comment'] ?? ''),
                    'questao_fonte'       => sanitize_text_field($data['fonte'] ?? ''),
                    'questao_assunto'     => sanitize_text_field($data['assunto'] ?? $data['topico'] ?? ''),
                    'questao_qualidade'   => intval($data['quality_score'] ?? $question->quality_score ?? 0),
                    'questao_data_importacao' => current_time('mysql'),
                ),
            ));

            if (is_wp_error($post_id)) {
                $errors[] = array('id' => $qid, 'error' => $post_id->get_error_message());
                continue;
            }

            $this->db->update_question($qid, array(
                'imported_to_wp' => 1,
                'wp_post_id'     => $post_id,
            ));

            $imported++;
        }

        $this->db->log('info', "Importação concluída: {$imported} questões importadas para WP", $user_id, null, array(
            'imported' => $imported,
            'errors'   => count($errors),
        ));

        return rest_ensure_response(array(
            'imported' => $imported,
            'errors'   => $errors,
            'total'    => count($question_ids),
        ));
    }

    // =========================================================================
    // STATS - HANDLER
    // =========================================================================

    public function get_stats($request) {
        $user_id = get_current_user_id();
        $stats = $this->db->get_stats($user_id);
        return rest_ensure_response($stats);
    }

    // =========================================================================
    // SETTINGS - HANDLERS
    // =========================================================================

    public function get_settings($request) {
        $settings = array(
            'ai_provider'      => get_option('pomaroli_ai_provider', 'gemini'),
            'ai_model'         => get_option('pomaroli_ai_model', 'gemini-2.0-flash'),
            'api_url'          => get_option('pomaroli_api_url', ''),
            'ocr_enabled'      => get_option('pomaroli_ocr_enabled', false),
            'auto_save_enabled'=> get_option('pomaroli_auto_save', true),
            'ai_segmentation'  => get_option('pomaroli_ai_segmentation', true),
            'worker_status'    => $this->auth->get_status(),
            'db_version'       => $this->db->get_db_version(),
        );

        // Nunca expor API keys no frontend
        return rest_ensure_response($settings);
    }

    public function save_settings($request) {
        $params = $request->get_json_params();
        $updated = array();

        $safe_fields = array(
            'ai_provider', 'ai_model', 'api_url',
            'ocr_enabled', 'auto_save_enabled', 'ai_segmentation',
        );

        foreach ($safe_fields as $field) {
            if (array_key_exists($field, $params)) {
                $value = $params[$field];
                if (is_bool($value)) {
                    update_option('pomaroli_' . $field, $value ? 1 : 0);
                } elseif (is_string($value)) {
                    update_option('pomaroli_' . $field, sanitize_text_field($value));
                } else {
                    update_option('pomaroli_' . $field, $value);
                }
                $updated[] = $field;
            }
        }

        $this->db->log('info', 'Configurações atualizadas: ' . implode(', ', $updated), get_current_user_id());

        return rest_ensure_response(array('updated' => $updated));
    }

    // =========================================================================
    // LOGS - HANDLER
    // =========================================================================

    public function get_logs($request) {
        $args = array(
            'job_id'   => intval($request->get_param('job_id') ?? 0),
            'user_id'  => intval($request->get_param('user_id') ?? get_current_user_id()),
            'level'    => $request->get_param('level') ?? '',
            'per_page' => intval($request->get_param('per_page') ?? 50),
            'page'     => intval($request->get_param('page') ?? 1),
        );
        $result = $this->db->get_logs($args);
        return rest_ensure_response($result);
    }

    // =========================================================================
    // AI JOBS - HANDLERS
    // =========================================================================

    public function create_ai_job($request) {
        $user_id = get_current_user_id();
        $params = $request->get_json_params();

        $ai_job_id = $this->db->create_ai_job(array(
            'user_id'         => $user_id,
            'job_id'          => $params['job_id'] ? intval($params['job_id']) : null,
            'total_questions' => intval($params['total_questions'] ?? 0),
            'operation_type'  => sanitize_text_field($params['operation_type'] ?? 'revisao'),
            'config_json'     => wp_json_encode($params['config'] ?? array()),
        ));

        if (!$ai_job_id) {
            return new WP_Error('create_failed', 'Falha ao criar job de IA.', array('status' => 500));
        }

        $response = rest_ensure_response($this->db->get_ai_job($ai_job_id));
        $response->set_status(201);
        return $response;
    }

    public function get_ai_job($request) {
        $ai_job_id = intval($request['id']);
        $ai_job = $this->db->get_ai_job($ai_job_id);

        if (!$ai_job) {
            return new WP_Error('not_found', 'Job de IA não encontrado.', array('status' => 404));
        }

        return rest_ensure_response($ai_job);
    }

    // =========================================================================
    // WORKER - HANDLERS (autenticados via HMAC)
    // =========================================================================

    public function worker_update($request) {
        $params = $request->get_json_params();
        $job_id = intval($params['job_id'] ?? 0);

        if (!$job_id) {
            return new WP_Error('missing_job_id', 'job_id é obrigatório.', array('status' => 400));
        }

        $job = $this->db->get_job($job_id);
        if (!$job) {
            return new WP_Error('not_found', 'Job não encontrado.', array('status' => 404));
        }

        $update = array();
        if (isset($params['status'])) {
            $update['status'] = sanitize_text_field($params['status']);
        }
        if (isset($params['progress'])) {
            $update['progress'] = min(100, max(0, intval($params['progress'])));
        }
        if (isset($params['total_files'])) {
            $update['total_files'] = intval($params['total_files']);
        }
        if (isset($params['processed_files'])) {
            $update['processed_files'] = intval($params['processed_files']);
        }
        if (isset($params['total_questions'])) {
            $update['total_questions'] = intval($params['total_questions']);
        }
        if (isset($params['processed_questions'])) {
            $update['processed_questions'] = intval($params['processed_questions']);
        }
        if (isset($params['total_pages'])) {
            $update['total_pages'] = intval($params['total_pages']);
        }
        if (isset($params['current_page'])) {
            $update['current_page'] = intval($params['current_page']);
        }
        if (isset($params['error_message'])) {
            $update['error_message'] = sanitize_text_field($params['error_message']);
        }

        // Status de início/fim
        if (isset($update['status'])) {
            if (in_array($update['status'], array('processing')) && !$job->started_at) {
                $update['started_at'] = current_time('mysql');
            }
            if (in_array($update['status'], array('completed', 'failed', 'cancelled'))) {
                $update['finished_at'] = current_time('mysql');
            }
        }

        $job_updated = true;
        $file_updated = true;

        if (!empty($update)) {
            $result = $this->db->update_job($job_id, $update);
            if ($result === false) {
                $job_updated = false;
            }
        }

        // Atualizar arquivo específico se fornecido
        $file_id = intval($params['file_id'] ?? 0);
        if ($file_id) {
            $file_update = array();
            if (isset($params['file_status'])) {
                $file_update['status'] = sanitize_text_field($params['file_status']);
            }
            if (isset($params['file_progress'])) {
                $file_update['progress'] = min(100, max(0, intval($params['file_progress'])));
            }
            if (isset($params['file_current_page'])) {
                $file_update['current_page'] = intval($params['file_current_page']);
            }
            if (isset($params['file_pages'])) {
                $file_update['pages'] = intval($params['file_pages']);
            }
            if (isset($params['file_questions_found'])) {
                $file_update['questions_found'] = intval($params['file_questions_found']);
            }
            if (!empty($file_update)) {
                $result = $this->db->update_file($file_id, $file_update);
                if ($result === false) {
                    $file_updated = false;
                }
            }
        }

        $worker_status = isset($params['status']) ? $params['status'] : '';

        if (!$job_updated || !$file_updated) {
            $this->db->log('error', "Worker update FAILED: status={$worker_status}", 0, $job_id, $params);
            return rest_ensure_response(array(
                'success' => false,
                'error'   => 'Falha ao atualizar progresso.',
            ));
        }

        $this->db->log('info', "Worker update: status={$worker_status}", 0, $job_id, $params);

        return rest_ensure_response(array('success' => true));
    }

    public function worker_save_questions($request) {
        $params = $request->get_json_params();
        $job_id = intval($params['job_id'] ?? 0);
        $questions = $params['questions'] ?? array();

        if (!$job_id) {
            return new WP_Error('missing_job_id', 'job_id é obrigatório.', array('status' => 400));
        }

        $job = $this->db->get_job($job_id);
        if (!$job) {
            return new WP_Error('not_found', 'Job não encontrado.', array('status' => 404));
        }

        $result = $this->db->create_questions_batch($questions);
        $inserted = intval($result['inserted'] ?? 0);
        $failed = intval($result['failed'] ?? 0);
        $total = intval($result['total'] ?? count($questions));

        // Atualizar contagem no job (apenas inseridos bem-sucedidos)
        if ($inserted > 0) {
            $this->db->update_job($job_id, array(
                'total_questions' => $job->total_questions + $inserted,
            ));
        }

        $this->db->log('info', "Worker salvou {$inserted}/{$total} questões para job #{$job_id} (falhas: {$failed})", 0, $job_id);

        if ($failed > 0) {
            return rest_ensure_response(array(
                'success' => false,
                'inserted' => $inserted,
                'updated'  => intval($result['updated'] ?? 0),
                'failed'   => $failed,
                'total'    => $total,
                'error'    => "{$failed} questão(ões) falhou ao salvar.",
            ));
        }

        return rest_ensure_response(array(
            'success' => true,
            'inserted' => $inserted,
            'updated'  => intval($result['updated'] ?? 0),
            'failed'   => 0,
            'total'    => $total,
        ));
    }

    public function worker_complete_job($request) {
        $params = $request->get_json_params();
        $job_id = intval($params['job_id'] ?? 0);

        if (!$job_id) {
            return new WP_Error('missing_job_id', 'job_id é obrigatório.', array('status' => 400));
        }

        $job = $this->db->get_job($job_id);
        if (!$job) {
            return new WP_Error('not_found', 'Job não encontrado.', array('status' => 404));
        }

        $status = $params['success'] ? 'completed' : 'failed';
        $this->db->update_job($job_id, array(
            'status'           => $status,
            'finished_at'      => current_time('mysql'),
            'error_message'    => $params['error_message'] ?? null,
            'processed_files'  => intval($params['processed_files'] ?? $job->total_files),
            'total_questions'  => intval($params['total_questions'] ?? $job->total_questions),
        ));

        $this->db->log('info', "Job #{$job_id} finalizado: {$status}", 0, $job_id);

        // Notificar WordPress via callback se configurado
        $this->notify_wp_complete($job_id, $status, $params);

        return rest_ensure_response(array('ok' => true, 'status' => $status));
    }

    // =========================================================================
    // WORKER: NEXT JOB / CLAIM (Persistent Queue)
    // =========================================================================

    /**
     * Retorna o próximo job com status queued para processamento.
     * Chamado pelo Python worker via /worker/next-job.
     */
    public function worker_next_job($request) {
        global $wpdb;
        $table = $this->db->table_jobs();

        $job = $wpdb->get_row(
            "SELECT * FROM {$table} WHERE status = 'queued' ORDER BY created_at ASC LIMIT 1"
        );

        if (!$job) {
            return rest_ensure_response(array('job' => null, 'message' => 'Nenhum job na fila.'));
        }

        return rest_ensure_response(array('job' => $job));
    }

    /**
     * Marca um job como processing (claim).
     * Chamado pelo Python worker via /worker/claim-job.
     */
    public function worker_claim_job($request) {
        $params = $request->get_json_params();
        $job_id = intval($params['job_id'] ?? 0);

        if (!$job_id) {
            return new WP_Error('missing_job_id', 'job_id é obrigatório.', array('status' => 400));
        }

        $job = $this->db->get_job($job_id);
        if (!$job) {
            return new WP_Error('not_found', 'Job não encontrado.', array('status' => 404));
        }

        if ($job->status !== 'queued') {
            return new WP_Error('invalid_status', 'Job não pode ser claimado (status: ' . $job->status . ').', array('status' => 409));
        }

        $this->db->update_job($job_id, array(
            'status'     => 'processing',
            'started_at' => current_time('mysql'),
        ));

        $this->db->log('info', "Job #{$job_id} claimado pelo worker Python", 0, $job_id);

        return rest_ensure_response(array('ok' => true, 'message' => 'Job claimado com sucesso.'));
    }

    /**
     * Retorna os arquivos de um job (autenticado via HMAC).
     * Chamado pelo Python worker via /worker/files/{id}.
     */
    public function worker_get_files($request) {
        $job_id = intval($request['id']);

        $job = $this->db->get_job($job_id);
        if (!$job) {
            return new WP_Error('not_found', 'Job não encontrado.', array('status' => 404));
        }

        $files = $this->db->get_files_by_job($job_id);
        return rest_ensure_response(array('files' => $files));
    }

    /**
     * Notifica o WordPress sobre a conclusão do job (callback).
     */
    private function notify_wp_complete($job_id, $status, $params) {
        $job = $this->db->get_job($job_id);
        if (!$job || empty($job->wp_site_url)) {
            return;
        }

        $callback_url = trailingslashit($job->wp_site_url) . 'wp-admin/admin-ajax.php';

        $payload = wp_json_encode(array(
            'action'    => 'pomaroli_job_completed',
            'job_id'    => $job_id,
            'status'    => $status,
            'questions' => intval($params['total_questions'] ?? 0),
        ));

        wp_remote_post($callback_url, array(
            'timeout' => 10,
            'body'    => $payload,
            'headers' => array('Content-Type' => 'application/json'),
        ));
    }

    // =========================================================================
    // UPLOAD LOCAL - HANDLER
    // =========================================================================

    /**
     * Upload de PDFs diretamente para o WordPress (sem Python).
     *
     * Aceita multipart/form-data com campo 'files[]' (múltiplos PDFs).
     * Cria job + files, salva PDFs em wp-content/uploads/pomaroli/{batch_id}/,
     * e enfileira para processamento.
     */
    public function upload_local($request) {
        $user_id = get_current_user_id();

        // Normalizar $_FILES para aceitar single, multiple e files[]
        $uploaded_files = $this->normalize_files($_FILES['files'] ?? array());

        if (empty($uploaded_files)) {
            return new WP_Error('no_files', 'Nenhum arquivo enviado.', array('status' => 400));
        }

        // Parametros
        $use_ocr = intval($_POST['use_ocr'] ?? 0);
        $use_ai = intval($_POST['use_ai'] ?? 0);
        $ai_provider = sanitize_text_field($_POST['ai_provider'] ?? 'gemini');
        $ai_model = sanitize_text_field($_POST['ai_model'] ?? 'gemini-2.5-flash');

        // Criar batch_id unico
        $batch_id = 'local_' . $user_id . '_' . time() . '_' . substr(md5(uniqid('', true)), 0, 8);

        // Criar diretorio de upload
        $upload_dir = wp_upload_dir();
        $batch_dir = $upload_dir['basedir'] . '/pomaroli/' . $batch_id;
        wp_mkdir_p($batch_dir);

        // Criar job
        $job_id = $this->db->create_job(array(
            'user_id'            => $user_id,
            'batch_id_externo'   => $batch_id,
            'status'             => 'queued',
            'total_files'        => count($uploaded_files),
            'ai_provider'        => $ai_provider,
            'ai_model'           => $ai_model,
            'use_ocr'            => $use_ocr,
            'use_ai_segmentation' => $use_ai,
            'wp_site_url'        => home_url('/'),
        ));

        if (!$job_id) {
            return new WP_Error('create_failed', 'Falha ao criar job.', array('status' => 500));
        }

        // Processar cada arquivo
        $files_salvos = 0;
        $erros = array();

        foreach ($uploaded_files as $idx => $file_info) {
            if ($file_info['error'] !== UPLOAD_ERR_OK) {
                $erros[] = array('index' => $idx, 'error' => 'Erro no upload: ' . $file_info['error']);
                continue;
            }

            // Validar tipo MIME
            $tipo = wp_check_filetype($file_info['name']);
            if ($tipo['type'] !== 'application/pdf') {
                $erros[] = array('index' => $idx, 'error' => 'Arquivo nao e PDF: ' . $file_info['name']);
                continue;
            }

            // Validar uploaded file
            if (!is_uploaded_file($file_info['tmp_name'])) {
                $erros[] = array('index' => $idx, 'error' => 'Arquivo nao foi upload valido.');
                continue;
            }

            // Salvar arquivo
            $filename = sanitize_file_name($file_info['name']);
            $destino = $batch_dir . '/' . $filename;
            $move_result = move_uploaded_file($file_info['tmp_name'], $destino);

            if (!$move_result) {
                $erros[] = array('index' => $idx, 'error' => 'Falha ao salvar: ' . $filename);
                continue;
            }

            // Criar registro de arquivo
            $file_id = $this->db->create_file(array(
                'job_id'     => $job_id,
                'file_index' => $idx,
                'filename'   => $filename,
                'file_path'  => $destino,
                'file_size'  => intval($file_info['size']),
                'status'     => 'pending',
            ));

            if (!$file_id) {
                $erros[] = array('index' => $idx, 'error' => 'Falha ao registrar arquivo no banco.');
                continue;
            }

            $files_salvos++;
        }

        if ($files_salvos === 0) {
            $this->db->update_job($job_id, array(
                'status'         => 'failed',
                'error_message'  => 'Nenhum arquivo valido foi salvo.',
                'finished_at'    => current_time('mysql'),
            ));
            return new WP_Error('upload_failed', 'Nenhum arquivo valido salvo.', array('status' => 400));
        }

        // Atualizar total_files real
        $this->db->update_job($job_id, array(
            'total_files' => $files_salvos,
        ));

        // Enfileirar para processamento
        $queue = Pomaroli_Queue::get_instance();
        $queue->enqueue($job_id);

        $this->db->log('info', "Upload local: {$files_salvos} arquivos, job #{$job_id} criado e enfileirado", $user_id, $job_id);

        // Buscar job atualizado
        $job = $this->db->get_job($job_id);

        $response = rest_ensure_response(array(
            'job'       => $job,
            'batch_id'  => $batch_id,
            'files'     => $files_salvos,
            'errors'    => $erros,
            'message'   => "{$files_salvos} arquivo(s) enviado(s) e enfileirado(s) para processamento.",
        ));
        $response->set_status(201);
        return $response;
    }

    /**
     * Normaliza $_FILES para aceitar single, multiple e files[] format.
     */
    private function normalize_files($files) {
        if (empty($files)) {
            return array();
        }

        $result = array();

        // Check if it's a single file (flat array with name, tmp_name, etc.)
        if (isset($files['name']) && is_string($files['name'])) {
            // Single file format: $_FILES['files'] = ['name' => 'file.pdf', 'tmp_name' => '/tmp/...']
            $result[] = array(
                'name'     => $files['name'],
                'type'     => $files['type'] ?? '',
                'tmp_name' => $files['tmp_name'] ?? '',
                'error'    => $files['error'] ?? UPLOAD_ERR_OK,
                'size'     => $files['size'] ?? 0,
            );
        } elseif (isset($files['name']) && is_array($files['name'])) {
            // Multiple files format: $_FILES['files'] = ['name' => ['file1.pdf', 'file2.pdf']]
            $count = count($files['name']);
            for ($i = 0; $i < $count; $i++) {
                $result[] = array(
                    'name'     => $files['name'][$i],
                    'type'     => $files['type'][$i] ?? '',
                    'tmp_name' => $files['tmp_name'][$i] ?? '',
                    'error'    => $files['error'][$i] ?? UPLOAD_ERR_OK,
                    'size'     => $files['size'][$i] ?? 0,
                );
            }
        }

        return $result;
    }

    // =========================================================================
    // PROCESS / CANCEL JOB - HANDLERS
    // =========================================================================

    /**
     * Dispara processamento manual de um job.
     */
    public function process_job($request) {
        $user_id = get_current_user_id();
        $job_id = intval($request['id']);

        $job = $this->db->get_job($job_id, $user_id);
        if (!$job) {
            return new WP_Error('not_found', 'Job nao encontrado.', array('status' => 404));
        }

        if (!in_array($job->status, array('queued', 'failed'))) {
            return new WP_Error('invalid_status', 'Job nao pode ser processado (status: ' . $job->status . ').', array('status' => 409));
        }

        $queue = Pomaroli_Queue::get_instance();
        $result = $queue->enqueue($job_id);

        if (!$result) {
            return new WP_Error('enqueue_failed', 'Falha ao enfileirar job.', array('status' => 500));
        }

        return rest_ensure_response(array('ok' => true, 'message' => 'Job enfileirado para processamento.'));
    }

    /**
     * Cancela um job em processamento.
     */
    public function cancel_job($request) {
        $user_id = get_current_user_id();
        $job_id = intval($request['id']);

        $job = $this->db->get_job($job_id, $user_id);
        if (!$job) {
            return new WP_Error('not_found', 'Job nao encontrado.', array('status' => 404));
        }

        $queue = Pomaroli_Queue::get_instance();
        $result = $queue->cancelar($job_id);

        if (!$result) {
            return new WP_Error('cancel_failed', 'Falha ao cancelar job.', array('status' => 500));
        }

        return rest_ensure_response(array('ok' => true, 'message' => 'Job cancelado.'));
    }

    // =========================================================================
    // HEALTH / QUEUE STATUS - HANDLERS
    // =========================================================================

    /**
     * Health check do plugin.
     */
    public function health_check($request) {
        $db = Pomaroli_DB::get_instance();

        $tables_ok = array(
            'jobs'      => $db->table_exists('jobs'),
            'files'     => $db->table_exists('files'),
            'questions' => $db->table_exists('questions'),
            'ai_jobs'   => $db->table_exists('ai_jobs'),
            'logs'      => $db->table_exists('logs'),
        );

        $all_ok = !in_array(false, $tables_ok);

        return rest_ensure_response(array(
            'version'     => '3.3.3',
            'php_version' => phpversion(),
            'tables'      => $tables_ok,
            'all_tables_ok' => $all_ok,
            'upload_dir_writable' => wp_is_writable(wp_upload_dir()['basedir']),
        ));
    }

    /**
     * Status da fila de processamento.
     */
    public function queue_status($request) {
        $queue = Pomaroli_Queue::get_instance();
        $status = $queue->get_queue_status();
        return rest_ensure_response($status);
    }

    // =========================================================================
    // ARG DEFINITIONS
    // =========================================================================

    private function list_jobs_args() {
        return array(
            'status'   => array('type' => 'string', 'default' => ''),
            'orderby'  => array('type' => 'string', 'default' => 'created_at'),
            'order'    => array('type' => 'string', 'default' => 'DESC'),
            'per_page' => array('type' => 'integer', 'default' => 20),
            'page'     => array('type' => 'integer', 'default' => 1),
        );
    }

    private function create_job_args() {
        return array(
            'batch_id_externo'    => array('type' => 'string', 'default' => ''),
            'status'              => array('type' => 'string', 'default' => 'queued'),
            'total_files'         => array('type' => 'integer', 'default' => 0),
            'ai_provider'         => array('type' => 'string', 'default' => ''),
            'ai_model'            => array('type' => 'string', 'default' => ''),
            'use_ocr'             => array('type' => 'boolean', 'default' => false),
            'use_ai_segmentation' => array('type' => 'boolean', 'default' => false),
            'files'               => array('type' => 'array', 'default' => array()),
            'meta'                => array('type' => 'object', 'default' => array()),
        );
    }
}
