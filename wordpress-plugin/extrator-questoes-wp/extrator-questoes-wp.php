<?php
/**
 * Plugin Name: Extrator de Questões Pomaroli
 * Plugin URI: https://extrator.pomaroli.com.br
 * Description: Plugin oficial Extrator de Questões Pomaroli para extração automatizada de questões de concursos em lote (PDFs múltiplos) com autocorreção via Google Gemini IA e integração com o banco do WordPress. Inclui aplicativo visual 100% Tela Cheia com login integrado.
 * Version: 3.0.10
 * Author: Equipe Pomaroli
 * Text Domain: extrator-questoes-wp
 */

if (!defined('ABSPATH')) {
    exit; // Segurança contra acesso direto
}

class ExtratorQuestoesWP {

    private static $instance = null;

    public static function get_instance() {
        if (self::$instance === null) {
            self::$instance = new self();
        }
        return self::$instance;
    }

    public function __construct() {
        add_action('init', array($this, 'registrar_cpt_questoes'));
        add_action('admin_menu', array($this, 'adicionar_menu_admin'));
        add_action('admin_enqueue_scripts', array($this, 'carregar_scripts_admin'));
        add_action('wp_enqueue_scripts', array($this, 'carregar_scripts_frontend'));
        add_action('after_setup_theme', array($this, 'remover_admin_bar_nao_admins'));
        
        // Endpoints AJAX do WordPress
        add_action('wp_ajax_extrator_salvar_config', array($this, 'salvar_configuracoes'));
        add_action('wp_ajax_extrator_importar_banco', array($this, 'importar_questoes_banco'));
        add_action('wp_ajax_nopriv_extrator_importar_banco_auto', array($this, 'importar_banco_auto'));
        add_action('wp_ajax_extrator_importar_banco_auto', array($this, 'importar_banco_auto'));
        add_action('wp_ajax_nopriv_extrator_ajax_login', array($this, 'ajax_login_handler'));
        add_action('wp_ajax_extrator_ajax_login', array($this, 'ajax_login_handler'));

        // Endpoints de persistência de lotes (cache local no WordPress)
        add_action('wp_ajax_nopriv_extrator_salvar_lote_local', array($this, 'salvar_lote_local'));
        add_action('wp_ajax_extrator_salvar_lote_local', array($this, 'salvar_lote_local'));
        add_action('wp_ajax_nopriv_extrator_listar_lotes_locais', array($this, 'listar_lotes_locais'));
        add_action('wp_ajax_extrator_listar_lotes_locais', array($this, 'listar_lotes_locais'));
        add_action('wp_ajax_nopriv_extrator_carregar_lote_local', array($this, 'carregar_lote_local'));
        add_action('wp_ajax_extrator_carregar_lote_local', array($this, 'carregar_lote_local'));
        add_action('wp_ajax_nopriv_extrator_excluir_lote_local', array($this, 'excluir_lote_local'));
        add_action('wp_ajax_extrator_excluir_lote_local', array($this, 'excluir_lote_local'));

        // Shortcodes do WordPress
        add_shortcode('extrator_pomaroli', array($this, 'shortcode_interage_questoes_app'));
        add_shortcode('interage_questoes_app', array($this, 'shortcode_interage_questoes_app'));
        add_shortcode('extrator_visual', array($this, 'shortcode_interage_questoes_app'));
        add_shortcode('lista_questoes', array($this, 'shortcode_lista_questoes'));
        add_shortcode('banco_questoes', array($this, 'shortcode_lista_questoes'));
        add_shortcode('questao', array($this, 'shortcode_questao_unica'));

        // Colunas Personalizadas na tabela wp-admin/edit.php?post_type=questao
        add_filter('manage_questao_posts_columns', array($this, 'definir_colunas_questoes'));
        add_action('manage_questao_posts_custom_column', array($this, 'preencher_colunas_questoes'), 10, 2);
    }

    /**
     * Oculta a Admin Bar (barra preta superior do WordPress) para não-administradores
     */
    public function remover_admin_bar_nao_admins() {
        if (!current_user_can('manage_options')) {
            show_admin_bar(false);
        }
    }

    /**
     * Define as colunas personalizadas na tabela de listagem de Questões
     */
    public function definir_colunas_questoes($columns) {
        $novas_colunas = array();
        $novas_colunas['cb'] = $columns['cb'];
        $novas_colunas['title'] = 'Questão';
        $novas_colunas['banca'] = 'Banca';
        $novas_colunas['disciplina'] = 'Disciplina';
        $novas_colunas['gabarito'] = 'Gabarito';
        $novas_colunas['qualidade'] = 'Qualidade';
        $novas_colunas['date'] = 'Data';
        return $novas_colunas;
    }

    /**
     * Preenche o conteúdo das colunas personalizadas
     */
    public function preencher_colunas_questoes($column, $post_id) {
        switch ($column) {
            case 'banca':
                echo esc_html(get_post_meta($post_id, '_banca', true) ?: '-');
                break;
            case 'disciplina':
                echo esc_html(get_post_meta($post_id, '_disciplina', true) ?: '-');
                break;
            case 'gabarito':
                $gab = get_post_meta($post_id, '_gabarito', true);
                echo $gab ? '<strong style="color:#7c3aed; font-size:15px;">' . esc_html($gab) . '</strong>' : '-';
                break;
            case 'qualidade':
                $score = get_post_meta($post_id, '_qualidade_score', true);
                if ($score !== '') {
                    $cor = intval($score) >= 85 ? '#10b981' : '#f59e0b';
                    echo '<span style="color:' . $cor . '; font-weight:bold;">' . esc_html($score) . '%</span>';
                } else {
                    echo '-';
                }
                break;
        }
    }

    /**
     * Registra o Custom Post Type 'questao' no WordPress
     */
    public function registrar_cpt_questoes() {
        $labels = array(
            'name'               => 'Questões',
            'singular_name'      => 'Questão',
            'menu_name'          => 'Banco de Questões',
            'add_new'            => 'Nova Questão',
            'add_new_item'       => 'Adicionar Nova Questão',
            'edit_item'          => 'Editar Questão',
            'all_items'          => 'Todas as Questões',
            'search_items'       => 'Buscar Questões',
        );

        $args = array(
            'labels'             => $labels,
            'public'             => true,
            'has_archive'        => true,
            'menu_icon'          => 'dashicons-welcome-write-blog',
            'supports'           => array('title', 'editor', 'custom-fields'),
            'show_in_rest'       => true,
        );

        register_post_type('questao', $args);
    }

    /**
     * Adiciona a página de administração do Extrator
     */
    public function adicionar_menu_admin() {
        add_menu_page(
            'Extrator Pomaroli',
            'Extrator Pomaroli',
            'manage_options',
            'extrator-questoes-ai',
            array($this, 'renderizar_pagina_admin'),
            'dashicons-cloud-upload',
            30
        );
    }

    /**
     * Carrega CSS e JS no painel administrativo
     */
    public function carregar_scripts_admin($hook) {
        if ($hook !== 'toplevel_page_extrator-questoes-ai') {
            return;
        }

        wp_enqueue_style('extrator-admin-css', plugins_url('style.css', __FILE__), array(), '2.2.0');
        wp_enqueue_script('extrator-admin-js', plugins_url('admin.js', __FILE__), array('jquery'), '2.2.0', true);

        wp_localize_script('extrator-admin-js', 'extratorWPConfig', array(
            'ajaxurl'   => admin_url('admin-ajax.php'),
            'nonce'     => wp_create_nonce('extrator_nonce'),
            'apiUrl'    => get_option('extrator_api_url', 'http://127.0.0.1:5000'),
            'geminiKey' => get_option('extrator_gemini_api_key', '')
        ));
    }

    /**
     * Carrega CSS e JS no frontend para exibição interativa das questões
     */
    public function carregar_scripts_frontend() {
        wp_enqueue_style('extrator-frontend-css', plugins_url('frontend.css', __FILE__), array(), '2.2.0');
        wp_enqueue_script('extrator-frontend-js', plugins_url('frontend.js', __FILE__), array('jquery'), '2.2.0', true);
    }

    /**
     * Salva as configurações de API URL e Gemini API Key
     */
    public function salvar_configuracoes() {
        check_ajax_referer('extrator_nonce', 'nonce');

        if (!current_user_can('manage_options')) {
            wp_send_json_error(array('message' => 'Permissão negada.'));
        }

        $api_url = sanitize_text_field($_POST['api_url']);
        $gemini_key = sanitize_text_field($_POST['gemini_key']);

        update_option('extrator_api_url', rtrim($api_url, '/'));
        update_option('extrator_gemini_api_key', $gemini_key);

        wp_send_json_success(array('message' => 'Configurações salvas com sucesso!'));
    }

    /**
     * Importa questões extraídas diretamente no Banco de Dados do WordPress (CPT questao)
     */
    /**
     * Helper interno para salvar questões no CPT questao com prevenção contra duplicatas e log
     */
    private function processar_insercao_questoes($questoes) {
        $inseridos = 0;
        $duplicados = 0;

        foreach ($questoes as $q) {
            $enunciado = isset($q['Enunciado']) ? trim($q['Enunciado']) : '';
            $banca = isset($q['Banca']) ? $q['Banca'] : 'Concurso';
            $numero = isset($q['Numero']) ? $q['Numero'] : '';
            $titulo = "Questão #" . ($numero ?: ($inseridos + 1)) . " - " . $banca;

            // Checa duplicados no banco do WP por título e post_type=questao
            $duplicado = get_page_by_title(wp_strip_all_tags($titulo), OBJECT, 'questao');
            if ($duplicado) {
                $duplicados++;
                continue; // Pula inserção se a questão já foi cadastrada
            }

            $conteudo = $enunciado;
            if (isset($q['Texto_Associado']) && !empty($q['Texto_Associado'])) {
                $conteudo = "<div class='texto-associado'>" . $q['Texto_Associado'] . "</div><br>" . $conteudo;
            }

            $post_id = wp_insert_post(array(
                'post_title'   => wp_strip_all_tags($titulo),
                'post_content' => $conteudo,
                'post_status'  => 'publish',
                'post_type'    => 'questao',
            ));

            if ($post_id && !is_wp_error($post_id)) {
                $inseridos++;
                update_post_meta($post_id, '_opcao_a', isset($q['Opcao_A']) ? $q['Opcao_A'] : '');
                update_post_meta($post_id, '_opcao_b', isset($q['Opcao_B']) ? $q['Opcao_B'] : '');
                update_post_meta($post_id, '_opcao_c', isset($q['Opcao_C']) ? $q['Opcao_C'] : '');
                update_post_meta($post_id, '_opcao_d', isset($q['Opcao_D']) ? $q['Opcao_D'] : '');
                update_post_meta($post_id, '_opcao_e', isset($q['Opcao_E']) ? $q['Opcao_E'] : '');
                update_post_meta($post_id, '_gabarito', isset($q['Gabarito']) ? strtoupper($q['Gabarito']) : '');
                update_post_meta($post_id, '_banca', isset($q['Banca']) ? $q['Banca'] : '');
                update_post_meta($post_id, '_ano', isset($q['Ano']) ? $q['Ano'] : '');
                update_post_meta($post_id, '_cargo', isset($q['Cargo']) ? $q['Cargo'] : '');
                update_post_meta($post_id, '_disciplina', isset($q['Disciplina']) ? $q['Disciplina'] : '');
                update_post_meta($post_id, '_comentario', isset($q['Comentario']) ? $q['Comentario'] : '');
                if (isset($q['Qualidade']['score'])) {
                    update_post_meta($post_id, '_qualidade_score', $q['Qualidade']['score']);
                }
                if (!empty($q['Refinada_IA'])) {
                    update_post_meta($post_id, '_refinada_ia', '1');
                }
            }
        }

        $log = array(
            'timestamp'  => current_time('mysql'),
            'inseridos'  => $inseridos,
            'duplicados' => $duplicados,
            'total'      => count($questoes)
        );
        update_option('extrator_last_import_log', $log);

        return $log;
    }

    /**
     * Importa questões extraídas diretamente no Banco de Dados do WordPress (CPT questao)
     */
    public function importar_questoes_banco() {
        check_ajax_referer('extrator_nonce', 'nonce');

        if (!current_user_can('manage_options')) {
            wp_send_json_error(array('message' => 'Permissão negada.'));
        }

        $questoes_json = isset($_POST['questoes']) ? wp_unslash($_POST['questoes']) : '';
        $questoes = json_decode($questoes_json, true);

        if (!is_array($questoes) || empty($questoes)) {
            wp_send_json_error(array('message' => 'Nenhuma questão válida enviada.'));
        }

        $log = $this->processar_insercao_questoes($questoes);

        $msg = "Sucesso! {$log['inseridos']} questões salvas no banco.";
        if ($log['duplicados'] > 0) {
            $msg .= " ({$log['duplicados']} já existiam e foram ignoradas)";
        }

        wp_send_json_success(array(
            'message' => $msg,
            'total'   => $log['inseridos']
        ));
    }

    /**
     * Endpoint chamado pelo Servidor em Nuvem (Render) para salvar questões automaticamente
     */
    public function importar_banco_auto() {
        $secret = isset($_POST['secret']) ? $_POST['secret'] : '';
        if ($secret !== 'extrator_pomaroli_secret_key_2026') {
            wp_send_json_error(array('message' => 'Secret token inválido.'));
        }

        $questoes_json = isset($_POST['questoes']) ? wp_unslash($_POST['questoes']) : '';
        $questoes = json_decode($questoes_json, true);

        if (!is_array($questoes) || empty($questoes)) {
            wp_send_json_error(array('message' => 'Nenhuma questão enviada.'));
        }

        $log = $this->processar_insercao_questoes($questoes);

        wp_send_json_success(array('message' => "Auto-salvamento: {$log['inseridos']} questões gravadas com sucesso no WordPress! ({$log['duplicados']} duplicadas ignoradas)"));
    }

    // =========================================================================
    // PERSISTÊNCIA LOCAL: Salvar/Carregar lotes no wp_options (sobrevive ao Render)
    // =========================================================================

    private function get_lotes_store_key() {
        return 'extrator_lotes_cache';
    }

    private function get_lotes_cache() {
        $raw = get_option($this->get_lotes_store_key(), '[]');
        $data = json_decode($raw, true);
        return is_array($data) ? $data : array();
    }

    private function save_lotes_cache($lotes) {
        update_option($this->get_lotes_store_key(), json_encode($lotes, JSON_UNESCAPED_UNICODE));
    }

    /**
     * Salva um lote completo (com questões) no wp_options
     * POST: batch_id, questoes (json), nome_arquivo, status
     */
    public function salvar_lote_local() {
        $secret = isset($_POST['secret']) ? sanitize_text_field($_POST['secret']) : '';
        if ($secret !== 'extrator_pomaroli_secret_key_2026') {
            wp_send_json_error(array('message' => 'Token inválido.'));
        }

        $batch_id = isset($_POST['batch_id']) ? sanitize_text_field($_POST['batch_id']) : '';
        $questoes_json = isset($_POST['questoes']) ? wp_unslash($_POST['questoes']) : '[]';
        $nome_arquivo = isset($_POST['nome_arquivo']) ? sanitize_text_field($_POST['nome_arquivo']) : '';
        $status = isset($_POST['status']) ? sanitize_text_field($_POST['status']) : 'concluido';

        if (empty($batch_id)) {
            wp_send_json_error(array('message' => 'batch_id obrigatório.'));
        }

        $questoes = json_decode($questoes_json, true);
        if (!is_array($questoes)) {
            $questoes = array();
        }

        $lotes = $this->get_lotes_cache();

        $lote_entry = array(
            'batch_id'     => $batch_id,
            'nome_arquivo' => $nome_arquivo,
            'status'       => $status,
            'total'        => count($questoes),
            'questoes'     => $questoes,
            'timestamp'    => current_time('mysql'),
        );

        $found = false;
        foreach ($lotes as $idx => $l) {
            if ($l['batch_id'] === $batch_id) {
                $lotes[$idx] = $lote_entry;
                $found = true;
                break;
            }
        }
        if (!$found) {
            array_unshift($lotes, $lote_entry);
        }

        if (count($lotes) > 50) {
            $lotes = array_slice($lotes, 0, 50);
        }

        $this->save_lotes_cache($lotes);

        wp_send_json_success(array(
            'message' => count($questoes) . ' questões salvas localmente no WordPress.',
            'batch_id' => $batch_id,
            'total' => count($questoes),
        ));
    }

    /**
     * Lista todos os lotes cacheados no WordPress (sem as questões, só resumo)
     */
    public function listar_lotes_locais() {
        $lotes = $this->get_lotes_cache();
        $lista = array();
        foreach ($lotes as $l) {
            $lista[] = array(
                'batch_id'     => $l['batch_id'],
                'nome_arquivo' => $l['nome_arquivo'],
                'status'       => $l['status'],
                'total'        => $l['total'],
                'timestamp'    => $l['timestamp'],
            );
        }
        wp_send_json_success(array('lotes' => $lista));
    }

    /**
     * Carrega um lote específico com todas as questões
     * POST/GET: batch_id
     */
    public function carregar_lote_local() {
        $batch_id = isset($_POST['batch_id']) ? sanitize_text_field($_POST['batch_id']) : '';
        if (empty($batch_id)) {
            $batch_id = isset($_GET['batch_id']) ? sanitize_text_field($_GET['batch_id']) : '';
        }

        if (empty($batch_id)) {
            wp_send_json_error(array('message' => 'batch_id obrigatório.'));
        }

        $lotes = $this->get_lotes_cache();
        foreach ($lotes as $l) {
            if ($l['batch_id'] === $batch_id) {
                wp_send_json_success($l);
                return;
            }
        }

        wp_send_json_error(array('message' => 'Lote não encontrado.'));
    }

    /**
     * Exclui um lote do cache local
     * POST: batch_id
     */
    public function excluir_lote_local() {
        $batch_id = isset($_POST['batch_id']) ? sanitize_text_field($_POST['batch_id']) : '';
        if (empty($batch_id)) {
            wp_send_json_error(array('message' => 'batch_id obrigatório.'));
        }

        $lotes = $this->get_lotes_cache();
        $lotes = array_values(array_filter($lotes, function($l) use ($batch_id) {
            return $l['batch_id'] !== $batch_id;
        }));

        $this->save_lotes_cache($lotes);

        wp_send_json_success(array('message' => 'Lote removido.'));
    }


    /**
     * Handler de Login AJAX para autenticar usuários diretamente na tela do extrator
     */
    public function ajax_login_handler() {
        check_ajax_referer('extrator_login_nonce', 'security');

        $username = isset($_POST['username']) ? sanitize_text_field($_POST['username']) : '';
        $password = isset($_POST['password']) ? $_POST['password'] : '';

        if (empty($username) || empty($password)) {
            wp_send_json_error(array('message' => 'Por favor, preencha o usuário e a senha.'));
        }

        $creds = array(
            'user_login'    => $username,
            'user_password' => $password,
            'remember'      => true,
        );

        $user = wp_signon($creds, is_ssl());

        if (is_wp_error($user)) {
            wp_send_json_error(array('message' => 'Credenciais inválidas. Verifique seu usuário e senha.'));
        } else {
            wp_set_current_user($user->ID);
            wp_set_auth_cookie($user->ID, true);
            wp_send_json_success(array('message' => 'Login realizado com sucesso!'));
        }
    }

    /**
     * SHORTCODE PRINCIPAL: [interage_questoes_app] ou [extrator_visual]
     * Exibe a interface completa da aplicação visual InterageQuestões (Drag & Drop, Editor, Gabarito)
     * protegida por autenticação (apenas administradores ou usuário específico).
     * Se o usuário não estiver logado, exibe um formulário de login integrado.
     */
    public function shortcode_interage_questoes_app($atts) {
        $atts = shortcode_atts(array(
            'usuario'    => '',
            'usuario_id' => '',
            'api_url'    => '',
            'tela_cheia' => 'true',
        ), $atts, 'interage_questoes_app');

        // 1. Verificação de Acesso Privado (Libera para qualquer usuário logado no WordPress)
        $current_user = wp_get_current_user();
        $permitido = false;

        if (is_user_logged_in() && $current_user->exists()) {
            $permitido = true;
        }

        // Se houver filtro específico de usuario_id no shortcode
        if (!empty($atts['usuario_id'])) {
            $permitido = ($current_user->ID == intval($atts['usuario_id']));
        }

        // Se houver filtro específico de nome de usuário no shortcode
        if (!empty($atts['usuario'])) {
            $permitido = (strtolower($current_user->user_login) === strtolower($atts['usuario']));
        }

        if (!$permitido || !is_user_logged_in()) {
            ob_start();
            $top_offset = is_admin_bar_showing() ? '32px' : '0px';
            $mobile_top_offset = is_admin_bar_showing() ? '46px' : '0px';
            ?>
            <div class="extrator-login-screen">
                <style>
                    html, body {
                        margin: 0 !important;
                        padding: 0 !important;
                        overflow: hidden !important;
                        background: #0b0f19 !important;
                    }
                    /* Remove espaçamentos e barras do tema em Modo Tela Cheia */
                    header.site-header, footer.site-footer, .elementor-location-header, .elementor-location-footer, #masthead, #colophon, .sidebar, #secondary, .ast-container, #page, .site-content, article {
                        padding: 0 !important;
                        margin: 0 !important;
                        max-width: 100% !important;
                        width: 100% !important;
                    }
                    .extrator-login-screen {
                        position: fixed !important;
                        top: <?php echo $top_offset; ?> !important;
                        left: 0 !important;
                        right: 0 !important;
                        bottom: 0 !important;
                        width: 100vw !important;
                        height: calc(100vh - <?php echo $top_offset; ?>) !important;
                        z-index: 999999 !important;
                        display: flex !important;
                        align-items: center !important;
                        justify-content: center !important;
                        background: #0b0f19 !important;
                        background-image: 
                            radial-gradient(at 0% 0%, rgba(124, 58, 237, 0.25) 0px, transparent 50%),
                            radial-gradient(at 100% 100%, rgba(59, 130, 246, 0.2) 0px, transparent 50%) !important;
                        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
                        padding: 20px !important;
                        box-sizing: border-box !important;
                        margin: 0 !important;
                    }
                    @media screen and (max-width: 782px) {
                        .extrator-login-screen {
                            top: <?php echo $mobile_top_offset; ?> !important;
                            height: calc(100vh - <?php echo $mobile_top_offset; ?>) !important;
                        }
                    }
                    .extrator-login-card {
                        background: rgba(22, 27, 38, 0.92);
                        backdrop-filter: blur(16px);
                        border: 1px solid rgba(255, 255, 255, 0.12);
                        border-radius: 20px;
                        padding: 40px 36px;
                        width: 100%;
                        max-width: 440px;
                        box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8);
                        color: #ffffff;
                        text-align: center;
                    }
                    .extrator-login-card .logo-badge {
                        display: inline-block;
                        background: linear-gradient(135deg, #7c3aed 0%, #3b82f6 100%);
                        color: #ffffff;
                        font-size: 11px;
                        font-weight: 800;
                        text-transform: uppercase;
                        padding: 4px 14px;
                        border-radius: 20px;
                        margin-bottom: 16px;
                        letter-spacing: 0.5px;
                        box-shadow: 0 4px 12px rgba(124, 58, 237, 0.3);
                    }
                    .extrator-login-card h2 {
                        font-size: 23px;
                        font-weight: 800;
                        margin: 0 0 10px 0;
                        color: #ffffff;
                    }
                    .extrator-login-card p {
                        font-size: 14px;
                        color: #9ca3af;
                        margin-bottom: 28px;
                        line-height: 1.5;
                    }
                    .extrator-login-form .form-group {
                        margin-bottom: 20px;
                        text-align: left;
                    }
                    .extrator-login-form label {
                        display: block;
                        font-size: 12px;
                        font-weight: 700;
                        color: #d1d5db;
                        margin-bottom: 8px;
                        text-transform: uppercase;
                        letter-spacing: 0.5px;
                    }
                    .extrator-login-form input[type="text"],
                    .extrator-login-form input[type="password"] {
                        width: 100%;
                        background: rgba(11, 15, 25, 0.85);
                        border: 1px solid rgba(255, 255, 255, 0.15);
                        border-radius: 10px;
                        padding: 14px 16px;
                        color: #ffffff;
                        font-size: 15px;
                        box-sizing: border-box;
                        transition: all 0.2s ease;
                    }
                    .extrator-login-form input[type="text"]:focus,
                    .extrator-login-form input[type="password"]:focus {
                        border-color: #7c3aed;
                        box-shadow: 0 0 0 3px rgba(124, 58, 237, 0.25);
                        outline: none;
                    }
                    .extrator-login-btn {
                        width: 100%;
                        background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%);
                        color: #ffffff;
                        border: none;
                        border-radius: 10px;
                        padding: 15px;
                        font-size: 16px;
                        font-weight: 700;
                        cursor: pointer;
                        transition: transform 0.15s ease, box-shadow 0.2s ease;
                        margin-top: 10px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        gap: 8px;
                    }
                    .extrator-login-btn:hover {
                        transform: translateY(-2px);
                        box-shadow: 0 10px 25px rgba(124, 58, 237, 0.4);
                    }
                    .extrator-login-alert {
                        background: rgba(239, 68, 68, 0.2);
                        border: 1px solid #ef4444;
                        color: #fca5a5;
                        padding: 12px;
                        border-radius: 8px;
                        font-size: 13px;
                        margin-bottom: 20px;
                        display: none;
                        text-align: left;
                    }
                </style>

                <div class="extrator-login-card">
                    <span class="logo-badge">Extrator Pomaroli v2.5</span>
                    <h2>🔒 Área de Login Privada</h2>
                    <p>Faça login com sua conta autorizada para acessar o <strong>Extrator de Questões Pomaroli</strong> e subir seus PDFs.</p>

                    <div id="extrator-login-error" class="extrator-login-alert"></div>

                    <form id="form-extrator-ajax-login" class="extrator-login-form">
                        <div class="form-group">
                            <label>Usuário ou E-mail:</label>
                            <input type="text" id="extrator-user-login" placeholder="Digite seu usuário" required autocomplete="username">
                        </div>
                        <div class="form-group">
                            <label>Senha:</label>
                            <input type="password" id="extrator-user-pass" placeholder="Digite sua senha" required autocomplete="current-password">
                        </div>
                        <button type="submit" id="btn-extrator-login" class="extrator-login-btn">
                            <span>Entrar e Acessar Extrator</span> 🚀
                        </button>
                    </form>
                </div>

                <script>
                if (typeof jQuery !== 'undefined') {
                    jQuery(document).ready(function($) {
                        $('#form-extrator-ajax-login').on('submit', function(e) {
                            e.preventDefault();
                            const btn = $('#btn-extrator-login');
                            const errorDiv = $('#extrator-login-error');
                            const username = $('#extrator-user-login').val();
                            const password = $('#extrator-user-pass').val();

                            btn.prop('disabled', true).html('<span>Autenticando...</span>');
                            errorDiv.hide();

                            $.post('<?php echo admin_url('admin-ajax.php'); ?>', {
                                action: 'extrator_ajax_login',
                                username: username,
                                password: password,
                                security: '<?php echo wp_create_nonce('extrator_login_nonce'); ?>'
                            }, function(response) {
                                if (response.success) {
                                    btn.html('<span>✅ Sucesso! Desbloqueando...</span>');
                                    setTimeout(function() {
                                        window.location.reload();
                                    }, 500);
                                } else {
                                    errorDiv.text(response.data ? response.data.message : 'Credenciais inválidas.').fadeIn();
                                    btn.prop('disabled', false).html('<span>Entrar e Acessar Extrator</span> 🚀');
                                }
                            }).fail(function() {
                                errorDiv.text('Erro ao conectar ao servidor do WordPress.').fadeIn();
                                btn.prop('disabled', false).html('<span>Entrar e Acessar Extrator</span> 🚀');
                            });
                        });
                    });
                }
                </script>
            </div>
            <?php
            return ob_get_clean();
        }

        $api_url = !empty($atts['api_url']) ? $atts['api_url'] : get_option('extrator_api_url', 'http://127.0.0.1:5000');
        $api_url = rtrim($api_url, '/');

        // Carrega o arquivo HTML do template InterageQuestões
        $template_path = plugin_dir_path(__FILE__) . 'index.html';
        if (!file_exists($template_path)) {
            $template_path = plugin_dir_path(__FILE__) . 'templates/index.html';
        }
        if (!file_exists($template_path)) {
            return '<div class="extrator-aviso">Arquivo de template visual (index.html) não localizado no plugin.</div>';
        }

        $html_content = file_get_contents($template_path);

        // Injeta a variável global da API no script do HTML
        $wp_ajax_url = admin_url('admin-ajax.php');
        $wp_nonce = wp_create_nonce('extrator_nonce');
        $injection = "<script>"
            . "window.API_BASE_URL = '" . esc_js($api_url) . "';"
            . "window.WP_AJAX_URL = '" . esc_js($wp_ajax_url) . "';"
            . "window.WP_NONCE = '" . esc_js($wp_nonce) . "';"
            . "window.WP_PERSIST_SECRET = 'extrator_pomaroli_secret_key_2026';"
            . "</script>";
        $html_content = str_replace('</head>', $injection . '</head>', $html_content);

        $tela_cheia = isset($atts['tela_cheia']) ? strtolower($atts['tela_cheia']) !== 'false' : true;

        ob_start();
        if ($tela_cheia):
            $top_offset = is_admin_bar_showing() ? '32px' : '0px';
            $mobile_top_offset = is_admin_bar_showing() ? '46px' : '0px';
            ?>
            <style>
                html, body {
                    margin: 0 !important;
                    padding: 0 !important;
                    overflow: hidden !important;
                    background: #0b0f19 !important;
                }
                /* Oculta cabeçalhos, rodapés, barras e sidebars do tema WordPress em Modo Tela Cheia */
                header.site-header, footer.site-footer, .elementor-location-header, .elementor-location-footer, #masthead, #colophon, .sidebar, #secondary, .ast-container, #page {
                    padding: 0 !important;
                    margin: 0 !important;
                    max-width: 100% !important;
                }
                .interage-app-fullscreen-overlay {
                    position: fixed !important;
                    top: <?php echo $top_offset; ?> !important;
                    left: 0 !important;
                    right: 0 !important;
                    bottom: 0 !important;
                    width: 100vw !important;
                    height: calc(100vh - <?php echo $top_offset; ?>) !important;
                    z-index: 999999 !important;
                    background: #0b0f19 !important;
                    margin: 0 !important;
                    padding: 0 !important;
                    border: none !important;
                }
                .interage-app-fullscreen-overlay iframe {
                    width: 100% !important;
                    height: 100% !important;
                    border: none !important;
                    background: #0b0f19 !important;
                    display: block !important;
                }
                @media screen and (max-width: 782px) {
                    .interage-app-fullscreen-overlay {
                        top: <?php echo $mobile_top_offset; ?> !important;
                        height: calc(100vh - <?php echo $mobile_top_offset; ?>) !important;
                    }
                }
            </style>
            <div class="interage-app-fullscreen-overlay">
                <iframe id="iframe-interage-app" srcdoc="<?php echo esc_attr($html_content); ?>"></iframe>
            </div>
            <?php
        else:
            ?>
            <div class="interage-app-wrapper" style="width: 100%; min-height: 920px; border-radius: 14px; overflow: hidden; box-shadow: 0 20px 50px rgba(0,0,0,0.6); background: #0b0f19;">
                <iframe id="iframe-interage-app" srcdoc="<?php echo esc_attr($html_content); ?>" style="width: 100%; height: 950px; border: none; background: #0b0f19;"></iframe>
            </div>
            <?php
        endif;
        return ob_get_clean();
    }

    /**
     * SHORTCODE: [lista_questoes] ou [banco_questoes]
     */
    public function shortcode_lista_questoes($atts) {
        $atts = shortcode_atts(array(
            'banca'      => '',
            'disciplina' => '',
            'limite'     => 10,
            'ordem'      => 'DESC',
        ), $atts, 'lista_questoes');

        $args = array(
            'post_type'      => 'questao',
            'post_status'    => 'publish',
            'posts_per_page' => intval($atts['limite']),
            'orderby'        => 'ID',
            'order'          => $atts['ordem'],
        );

        if (!empty($atts['banca'])) {
            $args['meta_query'][] = array(
                'key'     => '_banca',
                'value'   => $atts['banca'],
                'compare' => '='
            );
        }

        if (!empty($atts['disciplina'])) {
            $args['meta_query'][] = array(
                'key'     => '_disciplina',
                'value'   => $atts['disciplina'],
                'compare' => '='
            );
        }

        $query = new WP_Query($args);

        if (!$query->have_posts()) {
            return '<div class="extrator-aviso">Nenhuma questão encontrada com os filtros selecionados.</div>';
        }

        ob_start();
        echo '<div class="extrator-questoes-container">';

        while ($query->have_posts()) {
            $query->the_post();
            $post_id = get_the_ID();
            $gabarito = get_post_meta($post_id, '_gabarito', true);
            $banca = get_post_meta($post_id, '_banca', true);
            $ano = get_post_meta($post_id, '_ano', true);
            $disciplina = get_post_meta($post_id, '_disciplina', true);
            $comentario = get_post_meta($post_id, '_comentario', true);
            $refinada_ia = get_post_meta($post_id, '_refinada_ia', true);

            $opcoes = array(
                'A' => get_post_meta($post_id, '_opcao_a', true),
                'B' => get_post_meta($post_id, '_opcao_b', true),
                'C' => get_post_meta($post_id, '_opcao_c', true),
                'D' => get_post_meta($post_id, '_opcao_d', true),
                'E' => get_post_meta($post_id, '_opcao_e', true),
            );
            ?>
            <div class="questao-card" id="questao-card-<?php echo $post_id; ?>" data-gabarito="<?php echo esc_attr($gabarito); ?>">
                <div class="questao-card-header">
                    <span class="questao-title"><?php the_title(); ?></span>
                    <div class="questao-badges">
                        <?php if ($banca): ?><span class="badge-tag"><?php echo esc_html($banca); ?></span><?php endif; ?>
                        <?php if ($ano): ?><span class="badge-tag"><?php echo esc_html($ano); ?></span><?php endif; ?>
                        <?php if ($disciplina): ?><span class="badge-tag highlight"><?php echo esc_html($disciplina); ?></span><?php endif; ?>
                        <?php if ($refinada_ia): ?><span class="badge-ia" title="Corrigida por IA">✨ IA Clean</span><?php endif; ?>
                    </div>
                </div>

                <div class="questao-enunciado">
                    <?php the_content(); ?>
                </div>

                <div class="questao-alternativas">
                    <?php foreach ($opcoes as $letra => $texto): ?>
                        <?php if (!empty($texto)): ?>
                            <label class="alternativa-item">
                                <input type="radio" name="resposta_<?php echo $post_id; ?>" value="<?php echo $letra; ?>">
                                <span class="alternativa-letra"><?php echo $letra; ?></span>
                                <span class="alternativa-texto"><?php echo wp_kses_post($texto); ?></span>
                            </label>
                        <?php endif; ?>
                    <?php endforeach; ?>
                </div>

                <div class="questao-actions mt-15">
                    <button type="button" class="btn-responder-questao" data-id="<?php echo $post_id; ?>">Responder</button>
                    <?php if ($comentario): ?>
                        <button type="button" class="btn-toggle-comentario" data-id="<?php echo $post_id; ?>" style="display:none;">💡 Ver Comentário da IA</button>
                    <?php endif; ?>
                </div>

                <div class="questao-feedback" id="feedback-<?php echo $post_id; ?>" style="display:none;"></div>

                <?php if ($comentario): ?>
                    <div class="questao-comentario-box" id="comentario-<?php echo $post_id; ?>" style="display:none;">
                        <h4>💬 Comentário Didático da IA:</h4>
                        <div class="comentario-conteudo"><?php echo wp_kses_post($comentario); ?></div>
                    </div>
                <?php endif; ?>
            </div>
            <?php
        }

        echo '</div>';
        wp_reset_postdata();

        return ob_get_clean();
    }

    /**
     * SHORTCODE: [questao id="123"]
     */
    public function shortcode_questao_unica($atts) {
        $atts = shortcode_atts(array(
            'id' => 0,
        ), $atts, 'questao');

        if (empty($atts['id'])) {
            return '<div class="extrator-aviso">Por favor, informe o ID da questão: [questao id="123"]</div>';
        }

        return $this->shortcode_lista_questoes(array(
            'limite' => 1,
            'p'      => intval($atts['id'])
        ));
    }

    /**
     * Renderiza a interface de usuário do Plugin no Admin
     */
    public function renderizar_pagina_admin() {
        $api_url = get_option('extrator_api_url', 'http://127.0.0.1:5000');
        $gemini_key = get_option('extrator_gemini_api_key', '');
        ?>
        <div class="wrap extrator-wrap">
            <div class="extrator-header">
                <h1>⚡ Extrator de Questões AI <span class="badge-v2">v3.0.3 Multi-PDF & Tracking</span></h1>
                <p>Envie múltiplos arquivos PDF simultaneamente. O servidor em nuvem processará em segundo plano com autocorreção via Google Gemini (IA Grátis).</p>
            </div>

            <!-- CARD DE STATUS DO BANCO DE DADOS -->
            <?php
            $counts = wp_count_posts('questao');
            $total_questoes_wp = isset($counts->publish) ? $counts->publish : 0;
            $last_import_log = get_option('extrator_last_import_log', null);
            ?>
            <div class="extrator-card db-status-card" style="background: linear-gradient(135deg, #1e1b4b 0%, #312e81 100%); color: #fff; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.15);">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px;">
                    <div>
                        <h2 style="color: #a7f3d0; margin: 0 0 6px 0; font-size: 20px;">📚 Banco de Questões no WordPress</h2>
                        <p style="margin: 0; font-size: 14px; opacity: 0.95;">
                            Atualmente você possui <strong style="color: #6ee7b7; font-size: 18px;"><?php echo intval($total_questoes_wp); ?></strong> questões registradas e publicadas no banco do seu site.
                        </p>
                        <?php if ($last_import_log): ?>
                            <p style="margin: 6px 0 0 0; font-size: 12px; color: #cbd5e1;">
                                🕒 Último auto-salvamento: <strong><?php echo esc_html($last_import_log['timestamp']); ?></strong> — <?php echo intval($last_import_log['inseridos']); ?> gravadas<?php echo $last_import_log['duplicados'] > 0 ? " ({$last_import_log['duplicados']} duplicadas ignoradas)" : ''; ?> de <?php echo intval($last_import_log['total']); ?> questões recebidas.
                            </p>
                        <?php endif; ?>
                    </div>
                    <div>
                        <a href="<?php echo esc_url(admin_url('edit.php?post_type=questao')); ?>" class="button button-primary" style="background: #10b981; border-color: #059669; font-weight: bold; padding: 8px 18px; height: auto; font-size: 14px; text-decoration: none; display: inline-block;">
                            📋 Ver Banco de Questões (<?php echo intval($total_questoes_wp); ?>)
                        </a>
                    </div>
                </div>
            </div>

            <!-- CARD DE INSTRUÇÕES DE SHORTCODES -->

            <div class="extrator-card help-card">
                <h2>📌 Shortcodes Disponíveis para Páginas do WordPress</h2>
                <p>Copie e cole os shortcodes abaixo em qualquer página, post ou construtor visual (Elementor, Gutenberg, Divi):</p>
                <ul>
                    <li><code>[interage_questoes_app]</code> — Exibe a <strong>Interface Visual Completa (InterageQuestões)</strong> na sua página. Protegido automaticamente: apenas você (administrador) consegue ver e jogar PDFs!</li>
                    <li><code>[interage_questoes_app usuario="seu_usuario"]</code> — Restringe o acesso a um usuário específico pelo nome de login.</li>
                    <li><code>[lista_questoes limite="10"]</code> — Exibe um banco interativo de simulados para os estudantes responderem.</li>
                </ul>
            </div>

            <!-- CARD DE CONFIGURAÇÕES DE API -->
            <div class="extrator-card">
                <h2>⚙️ Configurações da API & IA</h2>
                <form id="form-config-extrator">
                    <div class="extrator-grid-2">
                        <div>
                            <label>URL do Servidor Python (Nuvem ou Local):</label>
                            <input type="url" id="config-api-url" class="regular-text" value="<?php echo esc_attr($api_url); ?>" placeholder="http://127.0.0.1:5000 ou https://seu-app.render.com" required>
                            <small>Servidor que executa a extração determinística e a fila assíncrona.</small>
                        </div>
                        <div>
                            <label>Chave da API do Google Gemini (IA Grátis):</label>
                            <input type="password" id="config-gemini-key" class="regular-text" value="<?php echo esc_attr($gemini_key); ?>" placeholder="AIzaSy...">
                            <small>Obtenha sua chave gratuita no <a href="https://aistudio.google.com/" target="_blank">Google AI Studio</a>.</small>
                        </div>
                    </div>
                    <button type="submit" class="button button-secondary mt-15">Salvar Configurações</button>
                </form>
            </div>

            <!-- CARD DE UPLOAD DE LOTES -->
            <div class="extrator-card">
                <h2>📁 Upload em Lote de Provas em PDF (Até 10+ Arquivos)</h2>
                <form id="form-upload-lote" enctype="multipart/form-data">
                    <div class="dropzone" id="dropzone-lote">
                        <div class="dropzone-icon">📄📄📄</div>
                        <h3>Arraste e solte os PDFs das provas aqui</h3>
                        <p>ou clique para selecionar múltiplos arquivos PDF do seu computador</p>
                        <input type="file" id="input-pdf-files" multiple accept="application/pdf" style="display:none;">
                    </div>

                    <div id="lista-arquivos-selecionados" class="arquivos-lista-container" style="display:none;">
                        <h4>Arquivos Selecionados (<span id="total-arquivos-count">0</span>):</h4>
                        <ul id="ul-arquivos-selecionados"></ul>
                    </div>

                    <div class="opcoes-ia-container">
                        <label class="switch-container">
                            <input type="checkbox" id="chk-autocorrigir-ia" checked>
                            <span class="slider"></span>
                            <strong>Ativar Autocorreção via Google Gemini (IA Grátis)</strong>
                            <small>(Corrige erros de OCR, pontuação, acentos e falta de espaço automaticamente em questões com nota < 85)</small>
                        </label>
                        <label class="switch-container" style="margin-top: 12px;">
                            <input type="checkbox" id="chk-usar-ocr">
                            <span class="slider"></span>
                            <strong>Forçar OCR via IA (PDFs Digitalizados / Escaneados)</strong>
                            <small>(Ative esta opção se o PDF for uma imagem escaneada sem texto selecionável. Usa a chave Gemini para ler o texto via Vision.)</small>
                        </label>
                        <div id="ocr-modelo-container" style="margin-top: 10px; display: none; padding: 12px; background: #f9f9f9; border-radius: 6px; border: 1px solid #ddd;">
                            <label style="font-weight: bold; display: block; margin-bottom: 5px;">Modelo de IA para OCR:</label>
                            <input type="text" id="config-ocr-model" class="regular-text" value="gemini-2.5-flash" placeholder="gemini-2.5-flash" style="width: 100%;">
                            <small>O modelo padrão é gemini-2.5-flash (gratuito). Não altere salvo se souber o que está fazendo.</small>
                        </div>
                    </div>

                    <div class="action-buttons">
                        <button type="submit" id="btn-iniciar-lote" class="button button-primary button-hero" disabled>
                            🚀 Iniciar Processamento em Lote
                        </button>
                    </div>
                </form>
            </div>

            <!-- CARD DE ACOMPANHAMENTO DO LOTE -->
            <div class="extrator-card" id="card-progresso-lote" style="display:none;">
                <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; margin-bottom: 12px; gap: 10px;">
                    <h2 style="margin:0;">📊 Progresso do Lote <span id="lote-id-tag" class="lote-tag">#---</span></h2>
                    <button type="button" id="btn-limpar-lote" class="button button-secondary" style="color: #ef4444; border-color: #fca5a5; background: #fff; font-weight: bold; cursor: pointer;">
                        🗑️ Limpar Progresso da Tela
                    </button>
                </div>
                <div class="lote-status-header">
                    <span id="lote-status-badge" class="badge-status pending">Enfileirado</span>
                    <span id="lote-resumo-texto">Processando 0 de 0 arquivos...</span>
                </div>

                <div class="progress-bar-outer mt-10">
                    <div id="lote-progress-bar-inner" class="progress-bar-inner" style="width: 0%;">0%</div>
                </div>

                <div class="tabela-arquivos-lote mt-20">
                    <table class="wp-list-table widefat fixed striped">
                        <thead>
                            <tr>
                                <th>#</th>
                                <th>Arquivo PDF</th>
                                <th>Status</th>
                                <th>Questões Extraídas</th>
                                <th>Autocorreção IA</th>
                            </tr>
                        </thead>
                        <tbody id="tbody-arquivos-lote">
                            <!-- Preenchido via JS -->
                        </tbody>
                    </table>
                </div>

                <div class="import-actions mt-20" id="container-botao-importar" style="display:none;">
                    <button type="button" id="btn-importar-wp" class="button button-primary button-hero">
                        💾 Importar Todas as Questões no Banco do WordPress
                    </button>
                </div>
            </div>
        </div>
        <?php
    }
}

// Inicializa o plugin
ExtratorQuestoesWP::get_instance();
