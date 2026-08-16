<?php
/**
 * Pomaroli_DB - Gerenciamento de tabelas customizadas e CRUD para o Extrator de Questões.
 *
 * Cria e gerencia as tabelas:
 *  - wp_pomaroli_jobs
 *  - wp_pomaroli_files
 *  - wp_pomaroli_questions
 *  - wp_pomaroli_ai_jobs
 *  - wp_pomaroli_logs
 */

if (!defined('ABSPATH')) {
    exit;
}

class Pomaroli_DB {

    private static $instance = null;
    private $table_prefix;

    public static function get_instance() {
        if (self::$instance === null) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    private function __construct() {
        global $wpdb;
        $this->table_prefix = $wpdb->prefix . 'pomaroli_';
    }

    // =========================================================================
    // NOMES DAS TABELAS
    // =========================================================================

    public function table($name) {
        global $wpdb;
        return $wpdb->prefix . 'pomaroli_' . $name;
    }

    public function table_jobs()        { return $this->table('jobs'); }
    public function table_files()       { return $this->table('files'); }
    public function table_questions()   { return $this->table('questions'); }
    public function table_ai_jobs()     { return $this->table('ai_jobs'); }
    public function table_logs()        { return $this->table('logs'); }

    // =========================================================================
    // CRIAÇÃO DAS TABELAS
    // =========================================================================

    public function create_tables() {
        global $wpdb;
        $charset_collate = $wpdb->get_charset_collate();

        require_once(ABSPATH . 'wp-admin/includes/upgrade.php');

        // --- JOBS ---
        $table_jobs = $this->table_jobs();
        $sql_jobs = "CREATE TABLE {$table_jobs} (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            user_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
            batch_id_externo VARCHAR(64) DEFAULT '',
            status VARCHAR(32) NOT NULL DEFAULT 'queued',
            total_files INT UNSIGNED NOT NULL DEFAULT 0,
            processed_files INT UNSIGNED NOT NULL DEFAULT 0,
            total_questions INT UNSIGNED NOT NULL DEFAULT 0,
            processed_questions INT UNSIGNED NOT NULL DEFAULT 0,
            total_pages INT UNSIGNED NOT NULL DEFAULT 0,
            current_page INT UNSIGNED NOT NULL DEFAULT 0,
            progress TINYINT UNSIGNED NOT NULL DEFAULT 0,
            error_message TEXT,
            ai_provider VARCHAR(32) DEFAULT '',
            ai_model VARCHAR(128) DEFAULT '',
            use_ocr TINYINT(1) NOT NULL DEFAULT 0,
            use_ai_segmentation TINYINT(1) NOT NULL DEFAULT 0,
            wp_site_url VARCHAR(512) DEFAULT '',
            meta_json LONGTEXT,
            created_at DATETIME NULL,
            started_at DATETIME NULL,
            finished_at DATETIME NULL,
            updated_at DATETIME NULL,
            PRIMARY KEY  (id),
            KEY idx_user_id (user_id),
            KEY idx_status (status),
            KEY idx_batch_externo (batch_id_externo),
            KEY idx_created (created_at)
        ) {$charset_collate};";

        // --- FILES ---
        $table_files = $this->table_files();
        $sql_files = "CREATE TABLE {$table_files} (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            job_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
            file_index SMALLINT UNSIGNED NOT NULL DEFAULT 0,
            filename VARCHAR(255) NOT NULL DEFAULT '',
            file_path VARCHAR(1024) DEFAULT '',
            file_size BIGINT UNSIGNED NOT NULL DEFAULT 0,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            progress TINYINT UNSIGNED NOT NULL DEFAULT 0,
            pages INT UNSIGNED NOT NULL DEFAULT 0,
            current_page INT UNSIGNED NOT NULL DEFAULT 0,
            questions_found INT UNSIGNED NOT NULL DEFAULT 0,
            questions_processed INT UNSIGNED NOT NULL DEFAULT 0,
            error_message TEXT,
            meta_json LONGTEXT,
            created_at DATETIME NULL,
            updated_at DATETIME NULL,
            PRIMARY KEY  (id),
            KEY idx_job_id (job_id),
            KEY idx_status (status)
        ) {$charset_collate};";

        // --- QUESTIONS ---
        $table_questions = $this->table_questions();
        $sql_questions = "CREATE TABLE {$table_questions} (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            job_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
            file_id BIGINT UNSIGNED DEFAULT 0,
            question_number INT UNSIGNED NOT NULL DEFAULT 0,
            question_data LONGTEXT NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'extracted',
            quality_score TINYINT UNSIGNED DEFAULT 0,
            quality_status VARCHAR(32) DEFAULT '',
            ai_reviewed TINYINT(1) NOT NULL DEFAULT 0,
            review_status VARCHAR(32) NOT NULL DEFAULT 'pending',
            imported_to_wp TINYINT(1) NOT NULL DEFAULT 0,
            wp_post_id BIGINT UNSIGNED DEFAULT 0,
            created_at DATETIME NULL,
            updated_at DATETIME NULL,
            PRIMARY KEY  (id),
            UNIQUE KEY idx_unique_question (job_id, file_id, question_number),
            KEY idx_job_id (job_id),
            KEY idx_file_id (file_id),
            KEY idx_status (status),
            KEY idx_review (review_status),
            KEY idx_imported (imported_to_wp)
        ) {$charset_collate};";

        // --- AI JOBS ---
        $table_ai_jobs = $this->table_ai_jobs();
        $sql_ai_jobs = "CREATE TABLE {$table_ai_jobs} (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            user_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
            job_id BIGINT UNSIGNED DEFAULT 0,
            status VARCHAR(32) NOT NULL DEFAULT 'queued',
            total_questions INT UNSIGNED NOT NULL DEFAULT 0,
            processed_questions INT UNSIGNED NOT NULL DEFAULT 0,
            operation_type VARCHAR(32) NOT NULL DEFAULT 'revisao',
            config_json TEXT,
            error_message TEXT,
            created_at DATETIME NULL,
            started_at DATETIME NULL,
            finished_at DATETIME NULL,
            updated_at DATETIME NULL,
            PRIMARY KEY  (id),
            KEY idx_user_id (user_id),
            KEY idx_status (status)
        ) {$charset_collate};";

        // --- LOGS ---
        $table_logs = $this->table_logs();
        $sql_logs = "CREATE TABLE {$table_logs} (
            id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            user_id BIGINT UNSIGNED NOT NULL DEFAULT 0,
            job_id BIGINT UNSIGNED DEFAULT 0,
            level VARCHAR(16) NOT NULL DEFAULT 'info',
            message TEXT NOT NULL,
            context_json TEXT,
            created_at DATETIME NULL,
            PRIMARY KEY  (id),
            KEY idx_user_id (user_id),
            KEY idx_job_id (job_id),
            KEY idx_level (level),
            KEY idx_created (created_at)
        ) {$charset_collate};";

        dbDelta($sql_jobs);
        dbDelta($sql_files);
        dbDelta($sql_questions);
        dbDelta($sql_ai_jobs);
        dbDelta($sql_logs);

        update_option('pomaroli_db_version', '1.0.0');
    }

    // =========================================================================
    // JOBS - CRUD
    // =========================================================================

    public function create_job($data) {
        global $wpdb;
        $insert = array(
            'user_id'           => intval($data['user_id']),
            'batch_id_externo'  => sanitize_text_field($data['batch_id_externo'] ?? ''),
            'status'            => sanitize_text_field($data['status'] ?? 'queued'),
            'total_files'       => intval($data['total_files'] ?? 0),
            'ai_provider'       => sanitize_text_field($data['ai_provider'] ?? ''),
            'ai_model'          => sanitize_text_field($data['ai_model'] ?? ''),
            'use_ocr'           => intval($data['use_ocr'] ?? 0),
            'use_ai_segmentation' => intval($data['use_ai_segmentation'] ?? 0),
            'wp_site_url'       => esc_url_raw($data['wp_site_url'] ?? ''),
            'meta_json'         => $data['meta_json'] ?? '{}',
            'created_at'        => current_time('mysql'),
            'updated_at'        => current_time('mysql'),
        );
        $wpdb->insert($this->table_jobs(), $insert);
        return $wpdb->insert_id;
    }

    public function get_job($job_id, $user_id = null) {
        global $wpdb;
        $where = $wpdb->prepare("id = %d", $job_id);
        if ($user_id !== null && !current_user_can('manage_options')) {
            $where .= $wpdb->prepare(" AND (user_id = %d OR user_id = 0)", $user_id);
        }
        return $wpdb->get_row("SELECT * FROM {$this->table_jobs()} WHERE {$where}");
    }

    public function get_job_by_batch_id($batch_id, $user_id = null) {
        global $wpdb;
        $where = $wpdb->prepare("batch_id_externo = %s", $batch_id);
        if ($user_id !== null) {
            $where .= $wpdb->prepare(" AND user_id = %d", $user_id);
        }
        return $wpdb->get_row("SELECT * FROM {$this->table_jobs()} WHERE {$where}");
    }

    public function update_job($job_id, $data) {
        global $wpdb;
        $update = array();
        $allowed = array(
            'status', 'batch_id_externo', 'total_files', 'processed_files',
            'total_questions', 'processed_questions', 'total_pages', 'current_page',
            'progress', 'error_message', 'ai_provider', 'ai_model',
            'use_ocr', 'use_ai_segmentation', 'wp_site_url', 'meta_json',
            'started_at', 'finished_at',
        );
        foreach ($allowed as $field) {
            if (array_key_exists($field, $data)) {
                $update[$field] = $data[$field];
            }
        }
        $update['updated_at'] = current_time('mysql');
        $wpdb->update($this->table_jobs(), $update, array('id' => $job_id));
        return $wpdb->rows_changed;
    }

    public function list_jobs($user_id, $args = array()) {
        global $wpdb;
        $defaults = array(
            'status'   => '',
            'orderby'  => 'created_at',
            'order'    => 'DESC',
            'per_page' => 20,
            'page'     => 1,
        );
        $args = wp_parse_args($args, $defaults);

        $where = '1=1';
        if (!current_user_can('manage_options')) {
            $where = $wpdb->prepare("(user_id = %d OR user_id = 0)", $user_id);
        }
        if (!empty($args['status'])) {
            $where .= $wpdb->prepare(" AND status = %s", $args['status']);
        }

        $allowed_orderby = array('created_at', 'updated_at', 'status', 'progress', 'total_questions');
        $orderby = in_array($args['orderby'], $allowed_orderby) ? $args['orderby'] : 'created_at';
        $order = strtoupper($args['order']) === 'ASC' ? 'ASC' : 'DESC';
        $offset = (max(1, $args['page']) - 1) * $args['per_page'];

        $total = $wpdb->get_var("SELECT COUNT(*) FROM {$this->table_jobs()} WHERE {$where}");
        $items = $wpdb->get_results(
            "SELECT * FROM {$this->table_jobs()} WHERE {$where} ORDER BY {$orderby} {$order} LIMIT {$args['per_page']} OFFSET {$offset}"
        );

        return array(
            'items'      => $items,
            'total'      => intval($total),
            'per_page'   => $args['per_page'],
            'page'       => $args['page'],
            'total_pages' => ceil($total / $args['per_page']),
        );
    }

    public function list_all_active_jobs($user_id = null) {
        global $wpdb;
        $where = "status IN ('queued', 'processing')";
        if ($user_id !== null) {
            $where .= $wpdb->prepare(" AND user_id = %d", $user_id);
        }
        return $wpdb->get_results("SELECT * FROM {$this->table_jobs()} WHERE {$where} ORDER BY created_at ASC");
    }

    public function delete_job($job_id, $user_id = null) {
        global $wpdb;
        $where = $wpdb->prepare("id = %d", $job_id);
        if ($user_id !== null && !current_user_can('manage_options')) {
            $where .= $wpdb->prepare(" AND (user_id = %d OR user_id = 0)", $user_id);
        }

        // Exclui questões vinculadas ao job
        $table_questions = $this->table_questions();
        $wpdb->query($wpdb->prepare("DELETE FROM {$table_questions} WHERE job_id = %d", $job_id));

        // Exclui arquivos vinculados ao job
        $table_files = $this->table_files();
        $wpdb->query($wpdb->prepare("DELETE FROM {$table_files} WHERE job_id = %d", $job_id));

        // Exclui o job
        $wpdb->query("DELETE FROM {$this->table_jobs()} WHERE {$where}");
        return $wpdb->rows_changed;
    }

    // =========================================================================
    // FILES - CRUD
    // =========================================================================

    public function create_file($data) {
        global $wpdb;
        $insert = array(
            'job_id'       => intval($data['job_id']),
            'file_index'   => intval($data['file_index'] ?? 0),
            'filename'     => sanitize_file_name($data['filename']),
            'file_path'    => sanitize_text_field($data['file_path'] ?? ''),
            'file_size'    => intval($data['file_size'] ?? 0),
            'status'       => sanitize_text_field($data['status'] ?? 'pending'),
            'created_at'   => current_time('mysql'),
            'updated_at'   => current_time('mysql'),
        );
        $wpdb->insert($this->table_files(), $insert);
        return $wpdb->insert_id;
    }

    public function get_file($file_id) {
        global $wpdb;
        return $wpdb->get_row($wpdb->prepare("SELECT * FROM {$this->table_files()} WHERE id = %d", $file_id));
    }

    public function update_file($file_id, $data) {
        global $wpdb;
        $update = array();
        $allowed = array(
            'status', 'progress', 'pages', 'current_page',
            'questions_found', 'questions_processed', 'error_message', 'meta_json',
        );
        foreach ($allowed as $field) {
            if (array_key_exists($field, $data)) {
                $update[$field] = $data[$field];
            }
        }
        $update['updated_at'] = current_time('mysql');
        $wpdb->update($this->table_files(), $update, array('id' => $file_id));
        return $wpdb->rows_changed;
    }

    public function get_files_by_job($job_id) {
        global $wpdb;
        return $wpdb->get_results(
            $wpdb->prepare("SELECT * FROM {$this->table_files()} WHERE job_id = %d ORDER BY file_index ASC", $job_id)
        );
    }

    public function delete_files_by_job($job_id) {
        global $wpdb;
        $wpdb->query($wpdb->prepare("DELETE FROM {$this->table_files()} WHERE job_id = %d", $job_id));
    }

    // =========================================================================
    // QUESTIONS - CRUD
    // =========================================================================

    public function create_question($data) {
        global $wpdb;
        $insert = array(
            'job_id'           => intval($data['job_id']),
            'file_id'          => $data['file_id'] ? intval($data['file_id']) : null,
            'question_number'  => intval($data['question_number'] ?? 0),
            'question_data'    => is_string($data['question_data']) ? $data['question_data'] : wp_json_encode($data['question_data']),
            'status'           => sanitize_text_field($data['status'] ?? 'extracted'),
            'quality_score'    => $data['quality_score'] !== null ? intval($data['quality_score']) : null,
            'quality_status'   => sanitize_text_field($data['quality_status'] ?? ''),
            'ai_reviewed'      => intval($data['ai_reviewed'] ?? 0),
            'review_status'    => sanitize_text_field($data['review_status'] ?? 'pending'),
            'created_at'       => current_time('mysql'),
            'updated_at'       => current_time('mysql'),
        );
        $wpdb->insert($this->table_questions(), $insert);
        return $wpdb->insert_id;
    }

    public function create_questions_batch($questions) {
        global $wpdb;
        $inserted = 0;
        $updated = 0;
        $failed = 0;
        $table = $this->table_questions();
        $now = current_time('mysql');

        foreach ($questions as $q) {
            $job_id = intval($q['job_id']);
            $file_id = $q['file_id'] ? intval($q['file_id']) : 0;
            $question_number = intval($q['question_number'] ?? 0);
            $question_data = is_string($q['question_data']) ? $q['question_data'] : wp_json_encode($q['question_data']);
            $status = sanitize_text_field($q['status'] ?? 'extracted');
            $quality_score = $q['quality_score'] !== null ? intval($q['quality_score']) : null;
            $quality_status = sanitize_text_field($q['quality_status'] ?? '');
            $ai_reviewed = intval($q['ai_reviewed'] ?? 0);
            $review_status = sanitize_text_field($q['review_status'] ?? 'pending');

            $result = $wpdb->query($wpdb->prepare(
                "INSERT INTO {$table} (job_id, file_id, question_number, question_data, status, quality_score, quality_status, ai_reviewed, review_status, created_at, updated_at)
                VALUES (%d, %d, %d, %s, %s, %d, %s, %d, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    question_data = VALUES(question_data),
                    status = VALUES(status),
                    quality_score = VALUES(quality_score),
                    quality_status = VALUES(quality_status),
                    ai_reviewed = VALUES(ai_reviewed),
                    review_status = VALUES(review_status),
                    updated_at = VALUES(updated_at)",
                $job_id, $file_id, $question_number, $question_data, $status,
                $quality_score, $quality_status, $ai_reviewed, $review_status, $now, $now
            ));

            if ($result !== false) {
                if ($wpdb->insert_id > 0) {
                    $inserted++;
                } else {
                    $updated++;
                }
            } else {
                $failed++;
            }
        }

        return array(
            'inserted' => $inserted,
            'updated'  => $updated,
            'failed'   => $failed,
            'total'    => count($questions),
        );
    }

    public function get_question($question_id) {
        global $wpdb;
        $row = $wpdb->get_row($wpdb->prepare(
            "SELECT * FROM {$this->table_questions()} WHERE id = %d", $question_id
        ));
        if ($row && is_string($row->question_data)) {
            $decoded = json_decode($row->question_data, true);
            if (is_array($decoded)) {
                $row->question_data = $decoded;
            }
        }
        return $row;
    }

    public function update_question($question_id, $data) {
        global $wpdb;
        $update = array();
        $allowed = array(
            'status', 'quality_score', 'quality_status', 'ai_reviewed',
            'review_status', 'imported_to_wp', 'wp_post_id', 'question_data',
        );
        foreach ($allowed as $field) {
            if (array_key_exists($field, $data)) {
                $val = $data[$field];
                if ($field === 'question_data' && is_array($val)) {
                    $val = wp_json_encode($val);
                }
                $update[$field] = $val;
            }
        }
        $update['updated_at'] = current_time('mysql');
        $wpdb->update($this->table_questions(), $update, array('id' => $question_id));
        return $wpdb->rows_changed;
    }

    public function list_questions($args = array()) {
        global $wpdb;
        $defaults = array(
            'job_id'     => 0,
            'file_id'    => 0,
            'status'     => '',
            'review_status' => '',
            'search'     => '',
            'orderby'    => 'question_number',
            'order'      => 'ASC',
            'per_page'   => 50,
            'page'       => 1,
            'user_id'    => 0,
        );
        $args = wp_parse_args($args, $defaults);

        $where_parts = array("1=1");
        $prepare_args = array();

        if ($args['job_id'] > 0) {
            $where_parts[] = $wpdb->prepare("q.job_id = %d", $args['job_id']);
        }
        if ($args['file_id'] > 0) {
            $where_parts[] = $wpdb->prepare("q.file_id = %d", $args['file_id']);
        }
        if (!empty($args['status'])) {
            $where_parts[] = $wpdb->prepare("q.status = %s", $args['status']);
        }
        if (!empty($args['review_status'])) {
            $where_parts[] = $wpdb->prepare("q.review_status = %s", $args['review_status']);
        }
        if (!empty($args['search'])) {
            $where_parts[] = $wpdb->prepare("q.question_data LIKE %s", '%' . $wpdb->esc_like($args['search']) . '%');
        }
        if ($args['user_id'] > 0) {
            $where_parts[] = $wpdb->prepare("j.user_id = %d", $args['user_id']);
        }

        $where = implode(' AND ', $where_parts);
        $table_q = $this->table_questions();
        $table_j = $this->table_jobs();

        $join = "FROM {$table_q} q";
        if ($args['user_id'] > 0 || !empty($args['search'])) {
            $join .= " INNER JOIN {$table_j} j ON q.job_id = j.id";
        }

        $allowed_orderby = array('id', 'question_number', 'quality_score', 'status', 'review_status', 'created_at');
        $orderby = in_array($args['orderby'], $allowed_orderby) ? "q.{$args['orderby']}" : 'q.question_number';
        $order = strtoupper($args['order']) === 'DESC' ? 'DESC' : 'ASC';
        $offset = (max(1, $args['page']) - 1) * $args['per_page'];

        $total = intval($wpdb->get_var("SELECT COUNT(*) {$join} WHERE {$where}"));

        $query = "SELECT q.* {$join} WHERE {$where} ORDER BY {$orderby} {$order} LIMIT {$args['per_page']} OFFSET {$offset}";
        $items = $wpdb->get_results($query);

        foreach ($items as &$item) {
            if (is_string($item->question_data)) {
                $decoded = json_decode($item->question_data, true);
                if (is_array($decoded)) {
                    $item->question_data = $decoded;
                }
            }
        }

        return array(
            'items'       => $items,
            'total'       => $total,
            'per_page'    => $args['per_page'],
            'page'        => $args['page'],
            'total_pages' => ceil($total / $args['per_page']),
        );
    }

    public function count_questions_by_status($user_id = null) {
        global $wpdb;
        $join = "";
        $where = "1=1";
        $prepare_args = array();

        if ($user_id !== null) {
            $join = " INNER JOIN {$this->table_jobs()} j ON q.job_id = j.id";
            $where = $wpdb->prepare("j.user_id = %d", $user_id);
        }

        $table_q = $this->table_questions();
        $rows = $wpdb->get_results(
            "SELECT q.status, q.review_status, COUNT(*) as cnt FROM {$table_q} q {$join} WHERE {$where} GROUP BY q.status, q.review_status"
        );

        $counts = array(
            'total'       => 0,
            'extracted'   => 0,
            'reviewed'    => 0,
            'published'   => 0,
            'aguardando_revisao' => 0,
            'revisao_pendente'   => 0,
        );

        foreach ($rows as $row) {
            $counts['total'] += intval($row->cnt);
            $status = $row->status;
            if (isset($counts[$status])) {
                $counts[$status] += intval($row->cnt);
            }
            if ($row->review_status === 'pending') {
                $counts['revisao_pendente'] += intval($row->cnt);
            }
            if ($row->review_status === 'aprovada') {
                $counts['aguardando_revisao'] += intval($row->cnt);
            }
        }

        return $counts;
    }

    public function delete_questions_by_job($job_id) {
        global $wpdb;
        $wpdb->query($wpdb->prepare("DELETE FROM {$this->table_questions()} WHERE job_id = %d", $job_id));
    }

    // =========================================================================
    // AI JOBS - CRUD
    // =========================================================================

    public function create_ai_job($data) {
        global $wpdb;
        $insert = array(
            'user_id'            => intval($data['user_id']),
            'job_id'             => $data['job_id'] ? intval($data['job_id']) : null,
            'status'             => sanitize_text_field($data['status'] ?? 'queued'),
            'total_questions'    => intval($data['total_questions'] ?? 0),
            'operation_type'     => sanitize_text_field($data['operation_type'] ?? 'revisao'),
            'config_json'        => $data['config_json'] ?? '{}',
            'created_at'         => current_time('mysql'),
            'updated_at'         => current_time('mysql'),
        );
        $wpdb->insert($this->table_ai_jobs(), $insert);
        return $wpdb->insert_id;
    }

    public function get_ai_job($ai_job_id) {
        global $wpdb;
        return $wpdb->get_row($wpdb->prepare("SELECT * FROM {$this->table_ai_jobs()} WHERE id = %d", $ai_job_id));
    }

    public function update_ai_job($ai_job_id, $data) {
        global $wpdb;
        $update = array();
        $allowed = array('status', 'processed_questions', 'error_message', 'started_at', 'finished_at');
        foreach ($allowed as $field) {
            if (array_key_exists($field, $data)) {
                $update[$field] = $data[$field];
            }
        }
        $update['updated_at'] = current_time('mysql');
        $wpdb->update($this->table_ai_jobs(), $update, array('id' => $ai_job_id));
        return $wpdb->rows_changed;
    }

    // =========================================================================
    // LOGS
    // =========================================================================

    public function log($level, $message, $user_id = 0, $job_id = null, $context = null) {
        global $wpdb;
        $wpdb->insert($this->table_logs(), array(
            'user_id'      => intval($user_id),
            'job_id'       => $job_id ? intval($job_id) : null,
            'level'        => sanitize_text_field($level),
            'message'      => $message,
            'context_json' => $context ? wp_json_encode($context) : null,
            'created_at'   => current_time('mysql'),
        ));
    }

    public function get_logs($args = array()) {
        global $wpdb;
        $defaults = array(
            'job_id'   => 0,
            'user_id'  => 0,
            'level'    => '',
            'per_page' => 50,
            'page'     => 1,
        );
        $args = wp_parse_args($args, $defaults);

        $where_parts = array("1=1");
        if ($args['job_id'] > 0) {
            $where_parts[] = $wpdb->prepare("job_id = %d", $args['job_id']);
        }
        if ($args['user_id'] > 0) {
            $where_parts[] = $wpdb->prepare("user_id = %d", $args['user_id']);
        }
        if (!empty($args['level'])) {
            $where_parts[] = $wpdb->prepare("level = %s", $args['level']);
        }
        $where = implode(' AND ', $where_parts);
        $offset = (max(1, $args['page']) - 1) * $args['per_page'];

        $total = intval($wpdb->get_var("SELECT COUNT(*) FROM {$this->table_logs()} WHERE {$where}"));
        $items = $wpdb->get_results(
            "SELECT * FROM {$this->table_logs()} WHERE {$where} ORDER BY created_at DESC LIMIT {$args['per_page']} OFFSET {$offset}"
        );

        return array(
            'items'  => $items,
            'total'  => $total,
            'page'   => $args['page'],
            'per_page' => $args['per_page'],
        );
    }

    // =========================================================================
    // ESTATÍSTICAS
    // =========================================================================

    public function get_stats($user_id = null) {
        global $wpdb;
        $table_j = $this->table_jobs();
        $table_f = $this->table_files();
        $table_q = $this->table_questions();

        $user_filter = "";
        $prepare_args = array();
        if ($user_id !== null) {
            $user_filter = $wpdb->prepare("WHERE j.user_id = %d", $user_id);
            $prepare_args[] = $user_id;
        }

        // Jobs por status
        $jobs_by_status = $wpdb->get_results(
            "SELECT status, COUNT(*) as cnt FROM {$table_j} j {$user_filter} GROUP BY status"
        );
        $stats_jobs = array();
        foreach ($jobs_by_status as $row) {
            $stats_jobs[$row->status] = intval($row->cnt);
        }

        // Files por status
        $file_filter = "";
        if ($user_id !== null) {
            $file_filter = $wpdb->prepare(
                "INNER JOIN {$table_j} j ON f.job_id = j.id WHERE j.user_id = %d", $user_id
            );
        }
        $files_by_status = $wpdb->get_results(
            "SELECT f.status, COUNT(*) as cnt FROM {$table_f} f {$file_filter} GROUP BY f.status"
        );
        $stats_files = array();
        foreach ($files_by_status as $row) {
            $stats_files[$row->status] = intval($row->cnt);
        }

        // Questions count
        $q_filter = "";
        if ($user_id !== null) {
            $q_filter = $wpdb->prepare(
                "INNER JOIN {$table_j} j ON q.job_id = j.id WHERE j.user_id = %d", $user_id
            );
        }
        $total_questions = intval($wpdb->get_var(
            "SELECT COUNT(*) FROM {$table_q} q {$q_filter}"
        ));

        // Active jobs (processing)
        $active_where = $user_filter;
        if (!empty($active_where)) {
            $active_where .= " AND status IN ('queued','processing')";
        } else {
            $active_where = "WHERE status IN ('queued','processing')";
        }
        $active_jobs = intval($wpdb->get_var(
            "SELECT COUNT(*) FROM {$table_j} j {$active_where}"
        ));

        // Queued jobs
        $queued_where = $user_filter;
        if (!empty($queued_where)) {
            $queued_where .= " AND status IN ('queued')";
        } else {
            $queued_where = "WHERE status IN ('queued')";
        }
        $queued_jobs = intval($wpdb->get_var(
            "SELECT COUNT(*) FROM {$table_j} j {$queued_where}"
        ));

        return array(
            'jobs'            => $stats_jobs,
            'files'           => $stats_files,
            'total_questions' => $total_questions,
            'active_jobs'     => $active_jobs,
            'queued_jobs'     => $queued_jobs,
        );
    }

    // =========================================================================
    // UTILIDADES
    // =========================================================================

    /**
     * Recupera jobs presos em 'processing' por mais de $timeout minutos.
     * Retorna array de jobs reenfileirados.
     */
    public function recover_stuck_jobs($timeout_minutes = 30) {
        global $wpdb;
        $table = $this->table_jobs();
        $timeout_date = gmdate('Y-m-d H:i:s', time() - ($timeout_minutes * 60));

        $stuck = $wpdb->get_results($wpdb->prepare(
            "SELECT * FROM {$table} WHERE status = 'processing' AND started_at IS NOT NULL AND started_at < %s ORDER BY started_at ASC",
            $timeout_date
        ));

        $recovered = array();
        foreach ($stuck as $job) {
            $this->update_job($job->id, array(
                'status'         => 'queued',
                'error_message'  => 'Auto-recovered: stuck in processing for ' . $timeout_minutes . 'min',
                'updated_at'     => current_time('mysql'),
            ));

            // Reset files em processing de volta para queued
            $files_table = $this->table_files();
            $wpdb->query($wpdb->prepare(
                "UPDATE {$files_table} SET status = 'queued', progress = 0 WHERE job_id = %d AND status = 'processing'",
                $job->id
            ));

            $this->log('warning', "Job #{$job->id} auto-recovered from stuck processing", 0, $job->id, array(
                'started_at' => $job->started_at,
                'timeout' => $timeout_minutes,
            ));

            $recovered[] = $job->id;
        }

        return $recovered;
    }

    public function table_exists($table_name) {
        global $wpdb;
        $full = $this->table($table_name);
        $result = $wpdb->get_var($wpdb->prepare("SHOW TABLES LIKE %s", $full));
        return ($result === $full);
    }

    public function get_db_version() {
        return get_option('pomaroli_db_version', '0');
    }
}
