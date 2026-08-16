/**
 * PomaroliAPI — Camada de comunicação REST com o WordPress.
 * Fornece métodos para todas as operações do dashboard.
 * Upload e processamento são 100% WordPress (sem dependência de Python externo).
 */
const PomaroliAPI = (() => {
    const BASE = () => {
        let base = (window.APP_CONFIG && window.APP_CONFIG.restUrl) || window.WP_REST_URL || '/wp-json/pomaroli/v1/';
        return base.endsWith('/') ? base : base + '/';
    };
    const HEADERS = () => {
        const nonce = (window.APP_CONFIG && window.APP_CONFIG.restNonce) || window.WP_REST_NONCE || '';
        return {
            'Content-Type': 'application/json',
            ...(nonce ? { 'X-WP-Nonce': nonce } : {}),
        };
    };

    function _buildUrl(path, params = {}) {
        const cleanPath = (path || '').replace(/^\//, '');
        const full = BASE() + cleanPath;
        const url = full.startsWith('http://') || full.startsWith('https://')
            ? new URL(full)
            : new URL(full, window.location.origin);

        Object.entries(params).forEach(([k, v]) => {
            if (v !== '' && v !== null && v !== undefined) url.searchParams.set(k, v);
        });
        return url.toString();
    }

    // ---------- helpers ----------

    async function _get(path, params = {}) {
        const url = _buildUrl(path, params);
        const res = await fetch(url, { headers: HEADERS(), credentials: 'same-origin' });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ message: res.statusText }));
            throw new Error(err.message || `HTTP ${res.status}`);
        }
        return res.json();
    }

    async function _post(path, body = {}) {
        const url = _buildUrl(path);
        const res = await fetch(url, {
            method: 'POST',
            headers: HEADERS(),
            credentials: 'same-origin',
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ message: res.statusText }));
            throw new Error(err.message || `HTTP ${res.status}`);
        }
        return res.json();
    }

    async function _put(path, body = {}) {
        const url = _buildUrl(path);
        const res = await fetch(url, {
            method: 'PUT',
            headers: HEADERS(),
            credentials: 'same-origin',
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ message: res.statusText }));
            throw new Error(err.message || `HTTP ${res.status}`);
        }
        return res.json();
    }

    async function _delete(path) {
        const url = _buildUrl(path);
        const res = await fetch(url, {
            method: 'DELETE',
            headers: HEADERS(),
            credentials: 'same-origin',
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ message: res.statusText }));
            throw new Error(err.message || `HTTP ${res.status}`);
        }
        return res.json();
    }

    // ---------- JOBS ----------

    function listJobs(params = {}) {
        return _get('jobs', params);
    }

    function getJob(id) {
        return _get(`jobs/${id}`);
    }

    function createJob(data) {
        return _post('jobs', data);
    }

    function deleteJob(id) {
        return _post(`jobs/${id}/delete`);
    }

    function retryJob(id) {
        return _post(`jobs/${id}/retry`);
    }

    function getJobFiles(id) {
        return _get(`jobs/${id}/files`);
    }

    // ---------- QUESTIONS ----------

    function listQuestions(params = {}) {
        return _get('questions', params);
    }

    function getQuestion(id) {
        return _get(`questions/${id}`);
    }

    function updateQuestion(id, data) {
        return _put(`questions/${id}`, data);
    }

    function reviewQuestion(id, action, questionData = null) {
        const body = { action };
        if (questionData) body.question_data = questionData;
        return _post(`questions/${id}/review`, body);
    }

    function importQuestionsToWP(questionIds) {
        return _post('questions/import-to-wp', { question_ids: questionIds });
    }

    // ---------- STATS ----------

    function getStats() {
        return _get('stats');
    }

    // ---------- SETTINGS ----------

    function getSettings() {
        return _get('settings');
    }

    function saveSettings(data) {
        return _post('settings', data);
    }

    // ---------- LOGS ----------

    function getLogs(params = {}) {
        return _get('logs', params);
    }

    // ---------- AI JOBS ----------

    function createAIJob(data) {
        return _post('ai-jobs', data);
    }

    function getAIJob(id) {
        return _get(`ai-jobs/${id}`);
    }

    // ---------- AUTH CHECK ----------

    async function checkAuth() {
        try {
            const url = _buildUrl('stats');
            const res = await fetch(url, {
                headers: HEADERS(),
                credentials: 'same-origin',
            });
            return res.ok;
        } catch {
            return false;
        }
    }

    // ---------- UPLOAD LOCAL (WordPress nativo) ----------

    async function uploadLocal(files, options = {}) {
        const formData = new FormData();
        files.forEach(f => formData.append('files[]', f));

        if (options.use_ocr) formData.append('use_ocr', '1');
        if (options.autocorrect) formData.append('use_ai', '1');
        if (options.ai_provider) formData.append('ai_provider', options.ai_provider);
        if (options.ai_model) formData.append('ai_model', options.ai_model);

        const url = _buildUrl('upload-local');
        const nonce = (window.APP_CONFIG && window.APP_CONFIG.restNonce) || window.WP_REST_NONCE || '';
        const headers = {
            'Accept': 'application/json',
            ...(nonce ? { 'X-WP-Nonce': nonce } : {}),
        };

        const res = await fetch(url, {
            method: 'POST',
            headers: headers,
            credentials: 'same-origin',
            body: formData,
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ message: res.statusText }));
            throw new Error(err.message || `Upload falhou: HTTP ${res.status}`);
        }

        return res.json();
    }

    // ---------- QUEUE ----------

    function getQueueStatus() {
        return _get('queue/status');
    }

    // ---------- HEALTH ----------

    function getHealth() {
        return _get('health');
    }

    // ---------- PUBLIC API ----------

    return {
        listJobs,
        getJob,
        createJob,
        deleteJob,
        retryJob,
        getJobFiles,
        listQuestions,
        getQuestion,
        updateQuestion,
        reviewQuestion,
        importQuestionsToWP,
        getStats,
        getSettings,
        saveSettings,
        getLogs,
        createAIJob,
        getAIJob,
        checkAuth,
        uploadLocal,
        getQueueStatus,
        getHealth,
    };
})();
