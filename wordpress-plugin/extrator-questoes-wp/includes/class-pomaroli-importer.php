<?php
/**
 * Pomaroli_Importer - Importação de questões extraídas para o WordPress.
 *
 * Converte dados do formato JSON do extrator para:
 *  - Posts do tipo 'questao' (CPT customizado)
 *  - Meta fields padronizados
 *  - Validação e sanitização
 */

if (!defined('ABSPATH')) {
    exit;
}

class Pomaroli_Importer {

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
    // REGISTRO DO CPT
    // =========================================================================

    /**
     * Registra o Custom Post Type 'questao'.
     */
    public function register_cpt() {
        $labels = array(
            'name'               => 'Questoes',
            'singular_name'      => 'Questao',
            'add_new'            => 'Adicionar Nova',
            'add_new_item'       => 'Adicionar Nova Questao',
            'edit_item'          => 'Editar Questao',
            'new_item'           => 'Nova Questao',
            'view_item'          => 'Ver Questao',
            'search_items'       => 'Buscar Questoes',
            'not_found'          => 'Nenhuma questao encontrada',
            'not_found_in_trash' => 'Nenhuma questao encontrada na lixeira',
            'menu_name'          => 'Questoes',
        );

        register_post_type('questao', array(
            'labels'       => $labels,
            'public'       => false,
            'show_ui'      => true,
            'show_in_menu' => false,
            'supports'     => array('title', 'editor', 'custom-fields'),
            'capability_type' => 'post',
            'map_meta_cap'    => true,
            'has_archive'     => false,
            'rewrite'         => false,
        ));
    }

    // =========================================================================
    // IMPORTAÇÃO
    // =========================================================================

    /**
     * Importa questões de um job para o WordPress.
     *
     * @param int $job_id ID do job.
     * @param array|null $question_ids IDs específicos para importar (null = todas).
     * @return array(array('imported' => int, 'errors' => array, 'total' => int)).
     */
    public function import_job($job_id, $question_ids = null) {
        $args = array(
            'job_id'    => $job_id,
            'per_page'  => 0,
            'user_id'   => get_current_user_id(),
        );

        if (!empty($question_ids)) {
            // Importar apenas IDs específicos
            $imported = 0;
            $errors = array();
            foreach ($question_ids as $qid) {
                $result = $this->import_single_question(intval($qid));
                if ($result === true) {
                    $imported++;
                } else {
                    $errors[] = array('id' => $qid, 'error' => $result);
                }
            }
            return array(
                'imported' => $imported,
                'errors'   => $errors,
                'total'    => count($question_ids),
            );
        }

        // Importar todas as questões do job
        $questions = $this->db->list_questions($args);
        $imported = 0;
        $errors = array();

        foreach ($questions['items'] as $q) {
            $result = $this->import_single_question($q->id);
            if ($result === true) {
                $imported++;
            } else {
                $errors[] = array('id' => $q->id, 'error' => $result);
            }
        }

        $this->db->log('info', "Importacao concluida: {$imported} questoes para job #{$job_id}", get_current_user_id(), $job_id, array(
            'imported' => $imported,
            'errors'   => count($errors),
        ));

        return array(
            'imported' => $imported,
            'errors'   => $errors,
            'total'    => $questions['total'],
        );
    }

    /**
     * Importa uma questão individual.
     *
     * @param int $question_id ID da questão no banco pomaroli.
     * @return true|string true em sucesso, string com erro.
     */
    public function import_single_question($question_id) {
        $question = $this->db->get_question($question_id);
        if (!$question) {
            return 'Questao nao encontrada.';
        }

        if ($question->imported_to_wp) {
            return 'Questao ja importada.';
        }

        $data = is_array($question->question_data) ? $question->question_data : json_decode($question->question_data, true);
        if (empty($data)) {
            return 'Dados da questao invalidos.';
        }

        // Determinar titulo
        $titulo = $this->_extrair_titulo($data, $question->question_number);

        // Determinar conteudo (enunciado)
        $conteudo = $this->_extrair_conteudo($data);

        // Meta fields
        $meta = $this->_extrair_meta($data, $question);

        $post_id = wp_insert_post(array(
            'post_title'   => sanitize_text_field($titulo),
            'post_type'    => 'questao',
            'post_status'  => 'draft',
            'post_content' => wp_kses_post($conteudo),
            'meta_input'   => $meta,
        ));

        if (is_wp_error($post_id)) {
            return $post_id->get_error_message();
        }

        // Marcar como importada
        $this->db->update_question($question_id, array(
            'imported_to_wp' => 1,
            'wp_post_id'     => $post_id,
        ));

        return true;
    }

    // =========================================================================
    // HELPERS
    // =========================================================================

    private function _extrair_titulo($data, $numero) {
        // Tentar vários campos possíveis para título
        $campos = array('titulo', 'title', 'questao', 'question');
        foreach ($campos as $campo) {
            if (!empty($data[$campo])) {
                return $data[$campo];
            }
        }
        return "Questao #{$numero}";
    }

    private function _extrair_conteudo($data) {
        $campos = array('enunciado', 'question', 'texto', 'text', 'conteudo');
        foreach ($campos as $campo) {
            if (!empty($data[$campo])) {
                return $data[$campo];
            }
        }
        return '';
    }

    private function _extrair_meta($data, $question) {
        $meta = array();

        // Opções/alternativas
        $opcoes = isset($data['opcoes']) ? $data['opcoes'] : (isset($data['options']) ? $data['options'] : array());
        $alternativas = isset($data['alternativas']) ? $data['alternativas'] : array();

        $meta['questao_opcoes'] = wp_json_encode($opcoes);
        $meta['questao_alternativas'] = wp_json_encode($alternativas);

        // Resposta correta
        $resposta = isset($data['resposta_correta']) ? $data['resposta_correta'] : (isset($data['correct_answer']) ? $data['correct_answer'] : '');
        $meta['questao_resposta'] = sanitize_text_field($resposta);

        // Classificações
        $meta['questao_banca'] = sanitize_text_field($data['banca'] ?? '');
        $meta['questao_disciplina'] = sanitize_text_field($data['disciplina'] ?? $data['materia'] ?? '');
        $meta['questao_ano'] = sanitize_text_field($data['ano'] ?? '');
        $meta['questao_dificuldade'] = sanitize_text_field($data['dificuldade'] ?? '');
        $meta['questao_fonte'] = sanitize_text_field($data['fonte'] ?? '');
        $meta['questao_assunto'] = sanitize_text_field($data['assunto'] ?? $data['topico'] ?? '');

        // Comentário
        $comentario = isset($data['comentario']) ? $data['comentario'] : (isset($data['comment']) ? $data['comment'] : '');
        $meta['questao_comentario'] = wp_kses_post($comentario);

        // Qualidade
        $quality = isset($data['Qualidade']) ? $data['Qualidade'] : array();
        $meta['questao_qualidade'] = isset($quality['score']) ? intval($quality['score']) : 0;
        $meta['questao_quality_status'] = isset($quality['status']) ? sanitize_text_field($quality['status']) : '';

        // Dados de importação
        $meta['questao_job_id'] = $question->job_id;
        $meta['questao_file_id'] = $question->file_id;
        $meta['questao_data_importacao'] = current_time('mysql');

        // Dados extras do JSON original
        $extras = array();
        $campos_extras = array('numero', 'questao_numero', 'prova', 'banca_prova', 'candidato', 'cargo');
        foreach ($campos_extras as $campo) {
            if (isset($data[$campo]) && !isset($meta['questao_' . $campo])) {
                $meta['questao_' . $campo] = sanitize_text_field($data[$campo]);
            }
        }

        return $meta;
    }

    // =========================================================================
    // IMPORTAÇÃO EM LOTE (BULK)
    // =========================================================================

    /**
     * Importa múltiplas questões de uma vez (mais eficiente).
     *
     * @param array $question_ids Array de IDs de questões.
     * @return array(array('imported' => int, 'errors' => array)).
     */
    public function import_bulk($question_ids) {
        $imported = 0;
        $errors = array();

        foreach ($question_ids as $qid) {
            $result = $this->import_single_question(intval($qid));
            if ($result === true) {
                $imported++;
            } else {
                $errors[] = array('id' => $qid, 'error' => $result);
            }
        }

        return array(
            'imported' => $imported,
            'errors'   => $errors,
        );
    }

    // =========================================================================
    // STATUS
    // =========================================================================

    /**
     * Retorna estatísticas de importação.
     */
    public function get_import_stats($job_id = null) {
        global $wpdb;
        $table = $this->db->table_questions();

        $where = "1=1";
        if ($job_id) {
            $where = $wpdb->prepare("job_id = %d", $job_id);
        }

        $total = intval($wpdb->get_var("SELECT COUNT(*) FROM {$table} WHERE {$where}"));
        $imported = intval($wpdb->get_var("SELECT COUNT(*) FROM {$table} WHERE {$where} AND imported_to_wp = 1"));
        $pending = $total - $imported;

        return array(
            'total'    => $total,
            'imported' => $imported,
            'pending'  => $pending,
        );
    }
}
