/**
 * PomaroliApp — SPA Router + Estado Global + Renderização das Páginas.
 */
const PomaroliApp = (() => {
    const $ = (sel, ctx = document) => ctx.querySelector(sel);
    const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];
    const tpl = (id) => document.getElementById(id);

    const app = $('#pomaroli-app');
    let currentPage = '';
    let pollTimers = {};

    // =========================================================================
    // UTILS & NOTIFICATIONS
    // =========================================================================

    const trackedJobStatuses = {};

    function playNotificationSound(type = 'success') {
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const now = ctx.currentTime;
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);

            if (type === 'success') {
                // Toque alegre de sucesso (dois tons: C5 -> G5)
                osc.type = 'sine';
                osc.frequency.setValueAtTime(523.25, now);
                osc.frequency.setValueAtTime(783.99, now + 0.12);
                gain.gain.setValueAtTime(0.2, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.5);
                osc.start(now);
                osc.stop(now + 0.5);
            } else {
                // Alerta de falha (dois tons graves)
                osc.type = 'triangle';
                osc.frequency.setValueAtTime(320, now);
                osc.frequency.setValueAtTime(220, now + 0.15);
                gain.gain.setValueAtTime(0.25, now);
                gain.gain.exponentialRampToValueAtTime(0.001, now + 0.6);
                osc.start(now);
                osc.stop(now + 0.6);
            }
        } catch (e) {
            // Web Audio não permitido ou sem suporte
        }
    }

    function requestNotificationPermission() {
        if ('Notification' in window && Notification.permission === 'default') {
            try {
                Notification.requestPermission();
            } catch (e) {}
        }
    }

    function showDesktopNotification(title, body) {
        if ('Notification' in window && Notification.permission === 'granted') {
            try {
                new Notification(title, {
                    body: body,
                    icon: 'https://extrator.pomaroli.com.br/wp-includes/images/w-logo-blue.png'
                });
            } catch(e) {}
        }
    }

    function checkJobStatusTransition(job) {
        const jId = String(job.id);
        const currentStatus = String(job.status || '').toLowerCase();
        const prevStatus = trackedJobStatuses[jId];

        // Se já conhecíamos o job como ativo e agora ele mudou
        if (prevStatus && ['queued', 'na_fila', 'aguardando', 'processing', 'processando', 'enviando', 'extraindo'].includes(prevStatus)) {
            if (['completed', 'concluido'].includes(currentStatus)) {
                const totalQ = job.total_questions || 0;
                playNotificationSound('success');
                toast(`🎉 Processamento #${job.id} Concluído! ${totalQ} questões extraídas com sucesso.`, 'success');
                showDesktopNotification('Extrator Pomaroli', `🎉 Processamento #${job.id} CONCLUÍDO! ${totalQ} questões foram extraídas com sucesso.`);
            } else if (['failed', 'erro', 'error'].includes(currentStatus)) {
                playNotificationSound('error');
                const errMsg = job.error_message || 'Falha durante o processamento do arquivo.';
                toast(`⚠️ Processamento #${job.id} com Erro: ${errMsg}`, 'error');
                showDesktopNotification('Extrator Pomaroli', `⚠️ Processamento #${job.id} Falhou: ${errMsg}`);
            }
        }

        // Atualiza estado conhecido
        trackedJobStatuses[jId] = currentStatus;
    }

    function toast(msg, type = 'info') {
        const c = $('#toast-container');
        if (!c) return;
        const el = document.createElement('div');
        el.className = `toast toast-${type}`;
        el.style.boxShadow = '0 8px 24px rgba(0,0,0,0.4)';
        el.style.fontSize = '14px';
        el.style.padding = '12px 18px';
        el.innerHTML = `<i class="fa-solid fa-${type === 'success' ? 'circle-check' : type === 'error' ? 'triangle-exclamation' : 'circle-info'}"></i> <span>${msg}</span>`;
        c.appendChild(el);
        setTimeout(() => el.remove(), 6000);
    }

    function confirmModal(message) {
        return new Promise((resolve) => {
            const overlay = document.getElementById('confirm-modal');
            const msgEl = document.getElementById('confirm-modal-message');
            const btnOk = document.getElementById('confirm-modal-ok');
            const btnCancel = document.getElementById('confirm-modal-cancel');

            if (!overlay) { resolve(confirm(message)); return; }

            msgEl.textContent = message;
            overlay.style.display = 'flex';

            function cleanup(result) {
                overlay.style.display = 'none';
                btnOk.removeEventListener('click', onOk);
                btnCancel.removeEventListener('click', onCancel);
                overlay.removeEventListener('click', onOverlay);
                resolve(result);
            }

            function onOk() { cleanup(true); }
            function onCancel() { cleanup(false); }
            function onOverlay(e) { if (e.target === overlay) cleanup(false); }

            btnOk.addEventListener('click', onOk);
            btnCancel.addEventListener('click', onCancel);
            overlay.addEventListener('click', onOverlay);
        });
    }

    function formatDate(d) {
        if (!d) return '--';
        const dt = new Date(d);
        return dt.toLocaleDateString('pt-BR') + ' ' + dt.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
    }

    function statusBadge(status, errorMsg = '') {
        const map = {
            queued:      { cls: 'amber',   icon: 'clock',               label: 'Na Fila' },
            na_fila:     { cls: 'amber',   icon: 'clock',               label: 'Na Fila' },
            aguardando:  { cls: 'amber',   icon: 'clock',               label: 'Aguardando' },
            enviando:    { cls: 'blue',    icon: 'cloud-arrow-up',      label: 'Enviando' },
            processing:  { cls: 'blue',    icon: 'spinner fa-spin',     label: 'Processando' },
            processando: { cls: 'blue',    icon: 'spinner fa-spin',     label: 'Processando' },
            extraindo:   { cls: 'blue',    icon: 'magnifying-glass',    label: 'Extraindo' },
            completed:   { cls: 'green',   icon: 'check-circle',        label: 'Concluído' },
            concluido:   { cls: 'green',   icon: 'check-circle',        label: 'Concluído' },
            failed:      { cls: 'red',     icon: 'triangle-exclamation', label: 'Erro' },
            erro:        { cls: 'red',     icon: 'triangle-exclamation', label: 'Erro' },
            error:       { cls: 'red',     icon: 'triangle-exclamation', label: 'Erro' },
            cancelled:   { cls: 'gray',    icon: 'ban',                 label: 'Cancelado' },
            cancelado:   { cls: 'gray',    icon: 'ban',                 label: 'Cancelado' },
            extraida:    { cls: 'blue',    icon: 'file-lines',          label: 'Extraída' },
            revisada:    { cls: 'green',   icon: 'check',               label: 'Revisada' },
            publicada:   { cls: 'purple',  icon: 'globe',               label: 'Publicada' },
            rejeitada:   { cls: 'red',     icon: 'xmark',               label: 'Rejeitada' },
            pendente:    { cls: 'amber',   icon: 'hourglass-half',      label: 'Pendente' },
            aprovada:    { cls: 'green',   icon: 'thumbs-up',           label: 'Aprovada' },
        };
        const s = map[status] || { cls: 'gray', icon: 'circle-question', label: status || 'Desconhecido' };
        let html = `<span class="badge badge-${s.cls}"><i class="fa-solid fa-${s.icon}"></i> ${s.label}</span>`;
        if (errorMsg && (s.cls === 'red' || status === 'failed' || status === 'erro')) {
            const cleanErr = String(errorMsg).replace(/"/g, '&quot;');
            html += ` <button type="button" class="btn btn-ghost btn-sm text-red" style="padding:2px 6px; font-size:11px;" onclick="alert('Detalhes do Erro:\\n\\n' + this.getAttribute('data-err'))" data-err="${cleanErr}" title="Ver detalhes do erro"><i class="fa-solid fa-circle-exclamation"></i> Ver Erro</button>`;
        }
        return html;
    }

    function progressHTML(pct) {
        return `
            <div style="display:flex;align-items:center;gap:8px;min-width:120px;">
                <div class="progress-bar" style="flex:1"><div class="progress-fill" style="width:${pct}%"></div></div>
                <span class="text-sm text-muted">${pct}%</span>
            </div>`;
    }

    function excerpt(text, len = 120) {
        if (!text) return '<span class="text-muted">--</span>';
        const clean = text.replace(/<[^>]+>/g, '').trim();
        return clean.length > len ? clean.substring(0, len) + '...' : clean;
    }

    // =========================================================================
    // ROUTER
    // =========================================================================

    function getRoute() {
        const hash = location.hash || '#/';
        const parts = hash.replace('#/', '').split('/');
        return { page: parts[0] || 'dashboard', params: parts.slice(1) };
    }

    function navigate(page) {
        location.hash = '#/' + page;
    }

    async function router() {
        const { page, params } = getRoute();

        if (currentPage === page && params.length === 0) return;
        currentPage = page;

        // Limpa polling anterior
        Object.values(pollTimers).forEach(clearInterval);
        pollTimers = {};

        // Atualiza nav
        $$('.nav-item').forEach(el => {
            el.classList.toggle('active', el.dataset.page === page);
        });

        // Atualiza título
        const titles = {
            dashboard: 'Dashboard',
            jobs: 'Processamentos',
            questions: 'Questões',
            'ai-review': 'Revisão IA',
            settings: 'Configurações',
        };
        const titleEl = $('#page-title');
        if (titleEl) titleEl.textContent = titles[page] || 'Dashboard';

        // Renderiza página
        const content = $('#main-content');
        if (!content) return;

        switch (page) {
            case 'dashboard':
                await renderDashboard(content);
                break;
            case 'jobs':
                if (params[0]) {
                    await renderJobDetail(content, params[0]);
                } else {
                    await renderJobs(content);
                }
                break;
            case 'questions':
                await renderQuestions(content);
                break;
            case 'ai-review':
                await renderAIReview(content);
                break;
            case 'settings':
                await renderSettings(content);
                break;
            default:
                await renderDashboard(content);
        }
    }

    // =========================================================================
    // RENDER: DASHBOARD
    // =========================================================================

    async function renderDashboard(container) {
        const t = tpl('tpl-page-dashboard');
        container.innerHTML = '';
        container.appendChild(t.content.cloneNode(true));

        async function loadDashboardData() {
            let hasActiveJobs = false;

            // Carrega stats
            try {
                const stats = await PomaroliAPI.getStats();
                const activeEl = $('#stat-active');
                const queuedEl = $('#stat-queued');
                const questionsEl = $('#stat-questions');
                const reviewEl = $('#stat-pending-review');

                if (activeEl) activeEl.textContent = stats.active_jobs || 0;
                if (queuedEl) queuedEl.textContent = stats.queued_jobs || 0;
                if (questionsEl) questionsEl.textContent = stats.total_questions || 0;

                const reviewPending = stats.questions?.revisao_pendente || 0;
                if (reviewEl) reviewEl.textContent = reviewPending;

                if ((stats.active_jobs || 0) > 0 || (stats.queued_jobs || 0) > 0) {
                    hasActiveJobs = true;
                }
            } catch (e) {
                console.error('Erro ao carregar stats:', e);
            }

            // Carrega jobs recentes
            try {
                const data = await PomaroliAPI.listJobs({ per_page: 8 });
                const tbody = $('#recent-jobs-body');
                if (!tbody) return;

                if (!data.items || data.items.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" class="text-muted text-center">Nenhum processamento encontrado. Clique em "Novo Upload" para começar.</td></tr>';
                } else {
                    data.items.forEach(j => checkJobStatusTransition(j));
                    tbody.innerHTML = data.items.map(j => {
                        const isFailed = j.status === 'failed' || j.status === 'erro' || j.status === 'error';
                        const isProcessing = ['queued', 'na_fila', 'processing', 'processando', 'enviando', 'extraindo'].includes(j.status);
                        if (isProcessing) hasActiveJobs = true;

                        return `
                            <tr>
                                <td><strong>#${j.id}</strong></td>
                                <td>${statusBadge(j.status, j.error_message)}</td>
                                <td>${j.processed_files || 0}/${j.total_files || 0}</td>
                                <td><strong>${j.total_questions || 0}</strong></td>
                                <td>${progressHTML(parseInt(j.progress) || 0)}</td>
                                <td class="text-sm text-muted">${formatDate(j.created_at)}</td>
                                <td style="white-space:nowrap;">
                                    <a href="#/jobs/${j.id}" class="btn btn-ghost btn-sm" title="Ver detalhes"><i class="fa-solid fa-eye"></i></a>
                                    ${isFailed ? `<button type="button" class="btn btn-ghost btn-sm text-amber btn-dash-retry" data-id="${j.id}" title="Tentar Novamente"><i class="fa-solid fa-rotate-right"></i></button>` : ''}
                                </td>
                            </tr>
                        `;
                    }).join('');

                    // Handler para retry rápido no dashboard
                    $$('.btn-dash-retry', tbody).forEach(btn => {
                        btn.addEventListener('click', async (e) => {
                            e.preventDefault();
                            const jId = btn.dataset.id;
                            try {
                                btn.disabled = true;
                                btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
                                await PomaroliAPI.retryJob(jId);
                                toast(`Processamento #${jId} reenfileirado!`, 'success');
                                loadDashboardData();
                            } catch (err) {
                                toast('Erro ao reenfileirar: ' + err.message, 'error');
                                btn.disabled = false;
                                btn.innerHTML = '<i class="fa-solid fa-rotate-right"></i>';
                            }
                        });
                    });
                }
            } catch (e) {
                console.error('Erro ao carregar jobs:', e);
            }

            // Carrega atividade
            try {
                const logs = await PomaroliAPI.getLogs({ per_page: 10 });
                const logContainer = $('#activity-log');
                if (logContainer) {
                    if (!logs.items || logs.items.length === 0) {
                        logContainer.innerHTML = '<div class="text-muted text-center">Nenhuma atividade registrada.</div>';
                    } else {
                        logContainer.innerHTML = logs.items.map(l => `
                            <div class="activity-item">
                                <div class="activity-dot ${l.level === 'error' ? 'error' : l.level === 'warning' ? 'warning' : 'info'}"></div>
                                <div>
                                    <div>${l.message}</div>
                                    <div class="activity-time">${formatDate(l.created_at)}</div>
                                </div>
                            </div>
                        `).join('');
                    }
                }
            } catch (e) {
                console.error('Erro ao carregar logs:', e);
            }

            // Auto-polling se houver jobs ativos
            if (hasActiveJobs && currentPage === 'dashboard') {
                if (!pollTimers['dashboard']) {
                    pollTimers['dashboard'] = setInterval(() => {
                        if (currentPage !== 'dashboard') {
                            clearInterval(pollTimers['dashboard']);
                            delete pollTimers['dashboard'];
                            return;
                        }
                        loadDashboardData();
                    }, 4000);
                }
            } else if (!hasActiveJobs && pollTimers['dashboard']) {
                clearInterval(pollTimers['dashboard']);
                delete pollTimers['dashboard'];
            }
        }

        await loadDashboardData();
    }

    // =========================================================================
    // RENDER: JOBS LIST
    // =========================================================================

    let jobsPage = 1;

    async function renderJobs(container) {
        const t = tpl('tpl-page-jobs');
        container.innerHTML = '';
        container.appendChild(t.content.cloneNode(true));

        const loadJobs = async (page = 1) => {
            jobsPage = page;
            const status = $('#jobs-filter-status')?.value || '';
            try {
                const data = await PomaroliAPI.listJobs({ page, per_page: 15, status });
                const tbody = $('#jobs-table-body');
                if (!data.items || data.items.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="8" class="text-muted text-center">Nenhum processamento encontrado.</td></tr>';
                    return;
                }
                tbody.innerHTML = data.items.map(j => `
                    <tr>
                        <td><strong>#${j.id}</strong></td>
                        <td class="text-sm truncate" title="${j.batch_id_externo || ''}">${j.batch_id_externo || '--'}</td>
                        <td>${statusBadge(j.status, j.error_message)}</td>
                        <td>${j.processed_files || 0}/${j.total_files || 0}</td>
                        <td>${j.total_questions || 0}</td>
                        <td>${progressHTML(parseInt(j.progress) || 0)}</td>
                        <td class="text-sm text-muted">${formatDate(j.created_at)}</td>
                        <td>
                            <div class="flex gap-8">
                                <a href="#/jobs/${j.id}" class="btn btn-ghost btn-sm" title="Detalhes"><i class="fa-solid fa-eye"></i></a>
                                <button class="btn btn-ghost btn-sm btn-delete-job" data-id="${j.id}" title="Excluir"><i class="fa-solid fa-trash"></i></button>
                            </div>
                        </td>
                    </tr>
                `).join('');

                // Pagination
                const pag = $('#jobs-pagination');
                if (data.total_pages > 1) {
                    let html = '';
                    html += `<button ${page <= 1 ? 'disabled' : ''} data-page="${page - 1}"><i class="fa-solid fa-chevron-left"></i></button>`;
                    for (let i = 1; i <= data.total_pages; i++) {
                        html += `<button class="${i === page ? 'active' : ''}" data-page="${i}">${i}</button>`;
                    }
                    html += `<button ${page >= data.total_pages ? 'disabled' : ''} data-page="${page + 1}"><i class="fa-solid fa-chevron-right"></i></button>`;
                    pag.innerHTML = html;
                    pag.querySelectorAll('button').forEach(btn => {
                        btn.addEventListener('click', () => loadJobs(parseInt(btn.dataset.page)));
                    });
                }

                // Delete handlers
                $$('.btn-delete-job').forEach(btn => {
                    btn.addEventListener('click', async () => {
                        const confirmed = await confirmModal('Tem certeza que deseja excluir este processamento? Esta ação não pode ser desfeita.');
                        if (!confirmed) return;
                        try {
                            await PomaroliAPI.deleteJob(btn.dataset.id);
                            toast('Processamento excluído com sucesso.', 'success');
                            loadJobs(jobsPage);
                        } catch (e) {
                            toast('Erro ao excluir: ' + e.message, 'error');
                        }
                    });
                });
            } catch (e) {
                console.error('Erro ao carregar jobs:', e);
                toast('Erro ao carregar processamentos.', 'error');
            }
        };

        $('#jobs-filter-status')?.addEventListener('change', () => loadJobs(1));
        loadJobs(1);
    }

    // =========================================================================
    // RENDER: JOB DETAIL
    // =========================================================================

    async function renderJobDetail(container, jobId) {
        const t = tpl('tpl-page-job-detail');
        container.innerHTML = '';
        container.appendChild(t.content.cloneNode(true));

        try {
            const job = await PomaroliAPI.getJob(jobId);
            $('#job-detail-title').textContent = `Processamento #${job.id}`;
            $('#jd-files').textContent = `${job.processed_files || 0}/${job.total_files || 0}`;
            $('#jd-questions').textContent = job.total_questions || 0;
            $('#jd-progress').textContent = `${parseInt(job.progress) || 0}%`;

            // Mostra/esconde botões de ação e alertas de erro
            const status = job.status;
            const isFailed = status === 'failed' || status === 'erro' || status === 'error';

            if (isFailed || job.error_message) {
                if ($('#jd-btn-retry')) $('#jd-btn-retry').style.display = '';
                if ($('#jd-btn-cancel')) $('#jd-btn-cancel').style.display = 'none';

                const errBox = document.createElement('div');
                errBox.style = 'background: rgba(239, 68, 68, 0.15); border: 1px solid #ef4444; color: #fca5a5; padding: 14px 18px; border-radius: 8px; margin-bottom: 20px; display: flex; align-items: flex-start; gap: 12px;';
                errBox.innerHTML = `
                    <i class="fa-solid fa-triangle-exclamation" style="color: #ef4444; font-size: 20px; margin-top: 2px;"></i>
                    <div style="flex: 1;">
                        <strong style="color: #f87171; font-size: 14px; display: block; margin-bottom: 4px;">Falha no Processamento:</strong>
                        <span style="font-size: 13px; color: #cbd5e1;">${job.error_message || 'Ocorreu um erro durante a execução do processamento deste arquivo.'}</span>
                    </div>
                `;
                const detailGrid = container.querySelector('.job-detail-grid') || container.firstElementChild;
                if (detailGrid) detailGrid.parentElement.insertBefore(errBox, detailGrid);
            } else if (['queued', 'na_fila', 'aguardando', 'processing', 'processando', 'enviando', 'extraindo'].includes(status)) {
                if ($('#jd-btn-cancel')) $('#jd-btn-cancel').style.display = '';
                if ($('#jd-btn-retry')) $('#jd-btn-retry').style.display = 'none';
            }

            // Retry
            $('#jd-btn-retry')?.addEventListener('click', async () => {
                try {
                    await PomaroliAPI.retryJob(jobId);
                    toast('Processamento reenfileirado!', 'success');
                    renderJobDetail(container, jobId);
                } catch (e) {
                    toast('Erro: ' + e.message, 'error');
                }
            });

            // Cancel
            $('#jd-btn-cancel')?.addEventListener('click', async () => {
                const confirmed = await confirmModal('Tem certeza que deseja cancelar este processamento?');
                if (!confirmed) return;
                try {
                    await PomaroliAPI.deleteJob(jobId);
                    toast('Processamento cancelado.', 'success');
                    navigate('jobs');
                } catch (e) {
                    toast('Erro ao cancelar: ' + e.message, 'error');
                }
            });

            // Files
            const files = job.files || [];
            const filesBody = $('#jd-files-body');
            if (files.length === 0) {
                filesBody.innerHTML = '<tr><td colspan="6" class="text-muted text-center">Nenhum arquivo.</td></tr>';
            } else {
                filesBody.innerHTML = files.map(f => `
                    <tr>
                        <td>${f.file_index + 1}</td>
                        <td>${f.filename}</td>
                        <td>${statusBadge(f.status)}</td>
                        <td>${f.pages || '--'}</td>
                        <td>${f.questions_found || 0}</td>
                        <td>${progressHTML(parseInt(f.progress) || 0)}</td>
                    </tr>
                `).join('');
            }

            // Questions
            const questionData = await PomaroliAPI.listQuestions({ job_id: jobId, per_page: 100 });
            const qList = $('#jd-questions-list');
            if (!questionData.items || questionData.items.length === 0) {
                qList.innerHTML = '<div class="text-muted text-center">Nenhuma questão extraída ainda.</div>';
            } else {
                qList.innerHTML = questionData.items.map(q => {
                    const data = typeof q.question_data === 'string' ? JSON.parse(q.question_data) : (q.question_data || {});
                    return `
                        <div class="question-card">
                            <div class="question-card-header">
                                <span class="question-card-number">#${q.question_number}</span>
                                <div class="question-card-badges">
                                    ${data.Banca ? `<span class="badge badge-gray">${data.Banca}</span>` : ''}
                                    ${data.Disciplina ? `<span class="badge badge-purple">${data.Disciplina}</span>` : ''}
                                    ${statusBadge(q.status)}
                                </div>
                            </div>
                            <div class="question-card-text">${excerpt(data.Enunciado || data.enunciado || '', 150)}</div>
                            <div class="question-card-actions">
                                <button class="btn btn-ghost btn-sm btn-edit-q" data-id="${q.id}">
                                    <i class="fa-solid fa-pen"></i> Editar
                                </button>
                                <span class="text-sm text-muted">${q.imported_to_wp ? '<i class="fa-solid fa-check-circle" style="color:var(--green)"></i> No WP' : ''}</span>
                            </div>
                        </div>
                    `;
                }).join('');

                // Edit handlers
                $$('.btn-edit-q', qList).forEach(btn => {
                    btn.addEventListener('click', () => openQuestionModal(btn.dataset.id));
                });
            }

            // Import button
            $('#jd-btn-import')?.addEventListener('click', async () => {
                if (!questionData.items || questionData.items.length === 0) {
                    toast('Nenhuma questão para importar.', 'error');
                    return;
                }
                const ids = questionData.items.filter(q => !q.imported_to_wp).map(q => q.id);
                if (ids.length === 0) {
                    toast('Todas as questões já foram importadas.', 'info');
                    return;
                }
                try {
                    const result = await PomaroliAPI.importQuestionsToWP(ids);
                    toast(`${result.imported} questões importadas com sucesso!`, 'success');
                    renderJobDetail(container, jobId);
                } catch (e) {
                    toast('Erro ao importar: ' + e.message, 'error');
                }
            });

            // Auto-refresh para jobs em processamento
            if (['processando', 'enviando', 'extraindo', 'na_fila', 'aguardando'].includes(status)) {
                pollTimers.jobDetail = setInterval(() => renderJobDetail(container, jobId), 5000);
            }

        } catch (e) {
            console.error('Erro ao carregar job:', e);
            container.innerHTML = `<div class="text-center mt-24"><p class="text-muted">Erro ao carregar processamento: ${e.message}</p><a href="#/jobs" class="btn btn-primary mt-12">Voltar</a></div>`;
        }
    }

    // =========================================================================
    // RENDER: QUESTIONS
    // =========================================================================

    let questionsPage = 1;

    async function renderQuestions(container) {
        const t = tpl('tpl-page-questions');
        container.innerHTML = '';
        container.appendChild(t.content.cloneNode(true));

        let selectedIds = new Set();

        const loadQuestions = async (page = 1) => {
            questionsPage = page;
            const search = $('#questions-search')?.value || '';
            const status = $('#questions-filter-status')?.value || '';
            const review = $('#questions-filter-review')?.value || '';

            try {
                const data = await PomaroliAPI.listQuestions({ page, per_page: 20, search, status, review_status: review });
                const tbody = $('#questions-table-body');
                if (!data.items || data.items.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="8" class="text-muted text-center">Nenhuma questão encontrada.</td></tr>';
                    return;
                }
                tbody.innerHTML = data.items.map(q => {
                    const d = typeof q.question_data === 'string' ? JSON.parse(q.question_data) : (q.question_data || {});
                    return `
                        <tr>
                            <td><input type="checkbox" class="q-select" data-id="${q.id}" ${selectedIds.has(q.id) ? 'checked' : ''}></td>
                            <td><strong>#${q.question_number}</strong></td>
                            <td class="truncate" title="${(d.Enunciado || '').replace(/"/g, '&quot;')}">${excerpt(d.Enunciado || '', 80)}</td>
                            <td>${d.Banca || '--'}</td>
                            <td>${d.Disciplina || '--'}</td>
                            <td>${statusBadge(q.status)}</td>
                            <td>${statusBadge(q.review_status)}</td>
                            <td>
                                <button class="btn btn-ghost btn-sm btn-edit-q" data-id="${q.id}"><i class="fa-solid fa-pen"></i></button>
                            </td>
                        </tr>
                    `;
                }).join('');

                // Select all
                $('#select-all-questions')?.addEventListener('change', (e) => {
                    $$('.q-select').forEach(cb => {
                        cb.checked = e.target.checked;
                        if (e.target.checked) selectedIds.add(parseInt(cb.dataset.id));
                        else selectedIds.delete(parseInt(cb.dataset.id));
                    });
                    updateImportBtn();
                });

                $$('.q-select').forEach(cb => {
                    cb.addEventListener('change', () => {
                        if (cb.checked) selectedIds.add(parseInt(cb.dataset.id));
                        else selectedIds.delete(parseInt(cb.dataset.id));
                        updateImportBtn();
                    });
                });

                $$('.btn-edit-q').forEach(btn => {
                    btn.addEventListener('click', () => openQuestionModal(btn.dataset.id));
                });

                // Pagination
                const pag = $('#questions-pagination');
                if (data.total_pages > 1) {
                    let html = `<button ${page <= 1 ? 'disabled' : ''} data-page="${page - 1}"><i class="fa-solid fa-chevron-left"></i></button>`;
                    for (let i = 1; i <= Math.min(data.total_pages, 10); i++) {
                        html += `<button class="${i === page ? 'active' : ''}" data-page="${i}">${i}</button>`;
                    }
                    html += `<button ${page >= data.total_pages ? 'disabled' : ''} data-page="${page + 1}"><i class="fa-solid fa-chevron-right"></i></button>`;
                    pag.innerHTML = html;
                    pag.querySelectorAll('button').forEach(btn => {
                        btn.addEventListener('click', () => loadQuestions(parseInt(btn.dataset.page)));
                    });
                }
            } catch (e) {
                console.error('Erro ao carregar questões:', e);
            }
        };

        const updateImportBtn = () => {
            const btn = $('#btn-import-selected');
            if (btn) btn.disabled = selectedIds.size === 0;
        };

        let searchTimer;
        $('#questions-search')?.addEventListener('input', () => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => loadQuestions(1), 400);
        });
        $('#questions-filter-status')?.addEventListener('change', () => loadQuestions(1));
        $('#questions-filter-review')?.addEventListener('change', () => loadQuestions(1));

        $('#btn-import-selected')?.addEventListener('click', async () => {
            if (selectedIds.size === 0) return;
            try {
                const result = await PomaroliAPI.importQuestionsToWP([...selectedIds]);
                toast(`${result.imported} questões importadas!`, 'success');
                selectedIds.clear();
                loadQuestions(questionsPage);
            } catch (e) {
                toast('Erro: ' + e.message, 'error');
            }
        });

        loadQuestions(1);
    }

    // =========================================================================
    // RENDER: AI REVIEW
    // =========================================================================

    async function renderAIReview(container) {
        const t = tpl('tpl-page-ai-review');
        container.innerHTML = '';
        container.appendChild(t.content.cloneNode(true));

        try {
            const data = await PomaroliAPI.listQuestions({ review_status: 'pendente', per_page: 50 });
            const stats = await PomaroliAPI.getStats();

            $('#ai-pending').textContent = stats.questions?.revisao_pendente || 0;

            const list = $('#ai-review-list');
            if (!data.items || data.items.length === 0) {
                list.innerHTML = '<div class="text-muted text-center">Nenhuma questão pendente de revisão.</div>';
                return;
            }

            list.innerHTML = data.items.map(q => {
                const d = typeof q.question_data === 'string' ? JSON.parse(q.question_data) : (q.question_data || {});
                return `
                    <div class="question-card">
                        <div class="question-card-header">
                            <span class="question-card-number">#${q.question_number}</span>
                            <div class="question-card-badges">
                                ${d.Banca ? `<span class="badge badge-gray">${d.Banca}</span>` : ''}
                                ${q.quality_score ? `<span class="badge badge-${q.quality_score >= 85 ? 'green' : 'amber'}">${q.quality_score}%</span>` : ''}
                            </div>
                        </div>
                        <div class="question-card-text">${excerpt(d.Enunciado || '', 150)}</div>
                        <div class="question-card-actions">
                            <button class="btn btn-success btn-sm btn-approve-q" data-id="${q.id}"><i class="fa-solid fa-check"></i> Aprovar</button>
                            <button class="btn btn-ghost btn-sm btn-edit-q" data-id="${q.id}"><i class="fa-solid fa-pen"></i> Editar</button>
                            <button class="btn btn-danger btn-sm btn-reject-q" data-id="${q.id}"><i class="fa-solid fa-xmark"></i> Rejeitar</button>
                        </div>
                    </div>
                `;
            }).join('');

            $$('.btn-approve-q').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try {
                        await PomaroliAPI.reviewQuestion(btn.dataset.id, 'aprovar');
                        toast('Questão aprovada!', 'success');
                        renderAIReview(container);
                    } catch (e) { toast('Erro: ' + e.message, 'error'); }
                });
            });

            $$('.btn-reject-q').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try {
                        await PomaroliAPI.reviewQuestion(btn.dataset.id, 'rejeitar');
                        toast('Questão rejeitada.', 'info');
                        renderAIReview(container);
                    } catch (e) { toast('Erro: ' + e.message, 'error'); }
                });
            });

            $$('.btn-edit-q').forEach(btn => {
                btn.addEventListener('click', () => openQuestionModal(btn.dataset.id));
            });

        } catch (e) {
            console.error('Erro ao carregar revisão IA:', e);
        }
    }

    // =========================================================================
    // RENDER: SETTINGS
    // =========================================================================

    async function renderSettings(container) {
        const t = tpl('tpl-page-settings');
        container.innerHTML = '';
        container.appendChild(t.content.cloneNode(true));

        try {
            const settings = await PomaroliAPI.getSettings();
            $('#set-ai-provider').value = settings.ai_provider || 'gemini';
            $('#set-ai-model').value = settings.ai_model || 'gemini-2.0-flash';
            $('#set-api-url').value = settings.api_url || '';
            $('#set-ocr').checked = !!settings.ocr_enabled;
            $('#set-auto-save').checked = settings.auto_save_enabled !== false;
            $('#set-db-version').textContent = settings.db_version || '--';

            const workerStatus = $('#set-worker-status');
            if (settings.worker_status?.has_secret) {
                workerStatus.innerHTML = `<span class="badge badge-green"><i class="fa-solid fa-check"></i> Configurado (${settings.worker_status.secret_length} chars)</span>`;
            } else {
                workerStatus.innerHTML = `<span class="badge badge-red"><i class="fa-solid fa-xmark"></i> Não configurado</span>`;
            }
        } catch (e) {
            console.error('Erro ao carregar configurações:', e);
        }

        $('#settings-form')?.addEventListener('submit', async (e) => {
            e.preventDefault();
            try {
                await PomaroliAPI.saveSettings({
                    ai_provider: $('#set-ai-provider').value,
                    ai_model: $('#set-ai-model').value,
                    api_url: $('#set-api-url').value,
                    ocr_enabled: $('#set-ocr').checked,
                    auto_save_enabled: $('#set-auto-save').checked,
                });
                toast('Configurações salvas!', 'success');
            } catch (e) {
                toast('Erro ao salvar: ' + e.message, 'error');
            }
        });
    }

    // =========================================================================
    // QUESTION MODAL
    // =========================================================================

    async function openQuestionModal(questionId) {
        try {
            const q = await PomaroliAPI.getQuestion(questionId);
            const d = typeof q.question_data === 'string' ? JSON.parse(q.question_data) : (q.question_data || {});

            // Remove modal anterior
            const existing = $('#question-modal');
            if (existing) existing.remove();

            const t = tpl('tpl-modal-question');
            document.body.appendChild(t.content.cloneNode(true));

            $('#modal-q-id').value = questionId;
            $('#modal-q-title').textContent = `Editar Questão #${q.question_number}`;
            $('#modal-q-enunciado').value = d.Enunciado || d.enunciado || '';
            $('#modal-q-banca').value = d.Banca || '';
            $('#modal-q-disciplina').value = d.Disciplina || d.materia || '';
            $('#modal-q-ano').value = d.Ano || '';
            $('#modal-q-gabarito').value = d.Gabarito || d.correct_answer || '';
            $('#modal-q-comentario').value = d.Comentario || d.comment || '';

            // Alternativas
            const altContainer = $('#modal-q-alternativas');
            const alternatives = d.Alternativas || d.alternativas || {};
            const labels = ['A', 'B', 'C', 'D', 'E'];
            altContainer.innerHTML = labels.map(l => `
                <div class="form-group">
                    <label>Alternativa ${l}</label>
                    <input type="text" class="form-input modal-alt" data-letter="${l}" value="${(alternatives[l] || d['Opcao_' + l] || '').replace(/"/g, '&quot;')}">
                </div>
            `).join('');

            // Close handlers
            $$('[data-close="question-modal"]').forEach(btn => {
                btn.addEventListener('click', () => $('#question-modal')?.remove());
            });
            $('#question-modal')?.addEventListener('click', (e) => {
                if (e.target === $('#question-modal')) $('#question-modal').remove();
            });

            const gatherData = () => {
                const alts = {};
                $$('.modal-alt').forEach(inp => { alts[inp.dataset.letter] = inp.value; });
                return {
                    Enunciado: $('#modal-q-enunciado').value,
                    Banca: $('#modal-q-banca').value,
                    Disciplina: $('#modal-q-disciplina').value,
                    Ano: $('#modal-q-ano').value,
                    Gabarito: $('#modal-q-gabarito').value.toUpperCase(),
                    Comentario: $('#modal-q-comentario').value,
                    Alternativas: alts,
                };
            };

            // Approve
            $('#modal-q-approve')?.addEventListener('click', async () => {
                try {
                    await PomaroliAPI.reviewQuestion(questionId, 'aprovar');
                    toast('Questão aprovada!', 'success');
                    $('#question-modal')?.remove();
                    currentPage = ''; // force re-render
                    router();
                } catch (e) { toast('Erro: ' + e.message, 'error'); }
            });

            // Edit
            $('#modal-q-edit')?.addEventListener('click', async () => {
                try {
                    const data = gatherData();
                    await PomaroliAPI.updateQuestion(questionId, { question_data: data, review_status: 'editada', status: 'revisada' });
                    await PomaroliAPI.reviewQuestion(questionId, 'editar', data);
                    toast('Questão salva!', 'success');
                    $('#question-modal')?.remove();
                    currentPage = '';
                    router();
                } catch (e) { toast('Erro: ' + e.message, 'error'); }
            });

            // Reject
            $('#modal-q-reject')?.addEventListener('click', async () => {
                try {
                    await PomaroliAPI.reviewQuestion(questionId, 'rejeitar');
                    toast('Questão rejeitada.', 'info');
                    $('#question-modal')?.remove();
                    currentPage = '';
                    router();
                } catch (e) { toast('Erro: ' + e.message, 'error'); }
            });

        } catch (e) {
            toast('Erro ao abrir questão: ' + e.message, 'error');
        }
    }

    // =========================================================================
    // UPLOAD MODAL
    // =========================================================================

    let uploadFiles = [];

    function openUploadModal() {
        requestNotificationPermission();
        const existing = $('#upload-modal');
        if (existing) existing.remove();

        const t = tpl('tpl-modal-upload');
        document.body.appendChild(t.content.cloneNode(true));
        uploadFiles = [];

        const dropzone = $('#upload-dropzone');
        const input = $('#upload-input');
        const fileList = $('#upload-file-list');
        const startBtn = $('#btn-start-upload');

        dropzone.addEventListener('click', () => input.click());
        dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('dragover'); });
        dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
            addFiles(e.dataTransfer.files);
        });
        input.addEventListener('change', () => addFiles(input.files));

        function addFiles(fileListInput) {
            for (const f of fileListInput) {
                if (f.type === 'application/pdf') uploadFiles.push(f);
            }
            renderFileList();
        }

        function renderFileList() {
            if (uploadFiles.length === 0) {
                fileList.innerHTML = '';
                startBtn.disabled = true;
                return;
            }
            startBtn.disabled = false;
            fileList.innerHTML = uploadFiles.map((f, i) => `
                <div class="upload-file-item">
                    <span class="file-name"><i class="fa-solid fa-file-pdf" style="color:var(--red);margin-right:6px"></i> ${f.name}</span>
                    <span class="file-size">${(f.size / 1024 / 1024).toFixed(1)} MB</span>
                    <button class="btn btn-ghost btn-sm btn-remove-file" data-idx="${i}"><i class="fa-solid fa-xmark"></i></button>
                </div>
            `).join('');

            $$('.btn-remove-file').forEach(btn => {
                btn.addEventListener('click', () => {
                    uploadFiles.splice(parseInt(btn.dataset.idx), 1);
                    renderFileList();
                });
            });
        }

        startBtn.addEventListener('click', async () => {
            if (uploadFiles.length === 0) return;

            const progress = $('#upload-progress');
            const progressFill = $('#upload-progress-fill');
            const progressText = $('#upload-progress-text');
            progress.style.display = '';
            startBtn.disabled = true;
            progressFill.style.width = '0%';
            progressText.textContent = 'Enviando...';

            try {
                const formData = new FormData();
                uploadFiles.forEach(f => formData.append('files[]', f));
                if ($('#upload-use-ocr')?.checked) formData.append('use_ocr', '1');
                if ($('#upload-autocorrect')?.checked) formData.append('use_ai', '1');

                const result = await new Promise((resolve, reject) => {
                    const xhr = new XMLHttpRequest();
                    const restBase = ((window.APP_CONFIG && window.APP_CONFIG.restUrl) || window.WP_REST_URL || '/wp-json/pomaroli/v1/').replace(/\/?$/, '/');
                    const nonce = (window.APP_CONFIG && window.APP_CONFIG.restNonce) || window.WP_REST_NONCE || '';
                    xhr.open('POST', restBase + 'upload-local');
                    if (nonce) xhr.setRequestHeader('X-WP-Nonce', nonce);

                    xhr.upload.addEventListener('progress', (e) => {
                        if (e.lengthComputable) {
                            const pct = Math.round((e.loaded / e.total) * 100);
                            progressFill.style.width = pct + '%';
                            progressText.textContent = pct + '%';
                        }
                    });

                    xhr.onload = function() {
                        if (xhr.status >= 200 && xhr.status < 300) {
                            resolve(JSON.parse(xhr.responseText));
                        } else {
                            try {
                                const err = JSON.parse(xhr.responseText);
                                reject(new Error(err.message || 'Upload failed'));
                            } catch {
                                reject(new Error('Upload failed: HTTP ' + xhr.status));
                            }
                        }
                    };

                    xhr.onerror = () => reject(new Error('Erro de rede'));
                    xhr.send(formData);
                });

                progressFill.style.width = '100%';
                progressText.textContent = '100%';

                const batchId = result.batch_id || 'N/A';
                const jobInfo = result.job ? ` (Job #${result.job.id})` : '';
                toast(`${result.files || uploadFiles.length} arquivo(s) enviado(s) e enfileirado(s)! Lote: ${batchId}${jobInfo}`, 'success');
                setTimeout(() => {
                    $('#upload-modal')?.remove();
                    currentPage = '';
                    router();
                }, 1000);
            } catch (e) {
                toast('Erro no upload: ' + e.message, 'error');
                startBtn.disabled = false;
                progress.style.display = 'none';
            }
        });

        // Close handlers
        $$('[data-close="upload-modal"]').forEach(btn => {
            btn.addEventListener('click', () => $('#upload-modal')?.remove());
        });
    }

    // =========================================================================
    // INIT
    // =========================================================================

    function init() {
        // Render shell
        const t = tpl('tpl-dashboard');
        app.innerHTML = '';
        app.appendChild(t.content.cloneNode(true));

        // Sidebar toggle
        $('#btn-toggle-sidebar')?.addEventListener('click', () => {
            $('#sidebar')?.classList.toggle('open');
        });

        // Logout
        $('#btn-logout')?.addEventListener('click', () => {
            document.cookie.split(';').forEach(c => {
                document.cookie = c.trim().split('=')[0] + '=;expires=Thu, 01 Jan 1970 00:00:00 UTC;path=/;';
            });
            window.location.reload();
        });

        // Upload buttons
        $('#btn-novo-upload')?.addEventListener('click', openUploadModal);
        $('#btn-novo-upload-jobs')?.addEventListener('click', openUploadModal);

        // Nav click handlers (hashchange unreliable in srcdoc iframes)
        $$('.nav-item').forEach(el => {
            el.addEventListener('click', (e) => {
                e.preventDefault();
                const page = el.dataset.page;
                if (page) navigate(page);
            });
        });

        // Router
        window.addEventListener('hashchange', () => {
            currentPage = '';
            router();
        });

        router();
    }

    // Expose
    return { init, toast };
})();

// =============================================================================
// BOOTSTRAP
// =============================================================================
document.addEventListener('DOMContentLoaded', () => {
    const app = document.getElementById('pomaroli-app');
    if (!app) {
        return; // Shortcode não presente nesta página
    }

    const config = window.APP_CONFIG || {};
    const userId = config.userId || window.WP_CURRENT_USER_ID || 0;

    if (userId > 0) {
        PomaroliApp.init();
    } else {
        const tpl = document.getElementById('tpl-login');
        if (!tpl) return;
        app.innerHTML = '';
        app.appendChild(tpl.content.cloneNode(true));

        const loginForm = document.getElementById('login-form');
        if (loginForm) {
            loginForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const user = document.getElementById('login-user').value;
                const pass = document.getElementById('login-pass').value;
                const errorDiv = document.getElementById('login-error');
                const btn = document.getElementById('login-btn');

                btn.disabled = true;
                btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Autenticando...';
                if (errorDiv) errorDiv.style.display = 'none';

                try {
                    const ajaxUrl = config.ajaxUrl || window.WP_AJAX_URL || '/wp-admin/admin-ajax.php';
                    const res = await fetch(ajaxUrl, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                        body: new URLSearchParams({
                            action: 'extrator_ajax_login',
                            username: user,
                            password: pass,
                            security: document.querySelector('[name="security"]')?.value || '',
                        }),
                    });
                    const data = await res.json();
                    if (data.success) {
                        btn.innerHTML = '<i class="fa-solid fa-check"></i> Sucesso!';
                        setTimeout(() => window.location.reload(), 500);
                    } else {
                        if (errorDiv) {
                            errorDiv.textContent = data.data?.message || 'Credenciais inválidas.';
                            errorDiv.style.display = '';
                        }
                        btn.disabled = false;
                        btn.innerHTML = '<i class="fa-solid fa-right-to-bracket"></i> Entrar';
                    }
                } catch {
                    if (errorDiv) {
                        errorDiv.textContent = 'Erro ao conectar ao servidor.';
                        errorDiv.style.display = '';
                    }
                    btn.disabled = false;
                    btn.innerHTML = '<i class="fa-solid fa-right-to-bracket"></i> Entrar';
                }
            });
        }
    }
});
