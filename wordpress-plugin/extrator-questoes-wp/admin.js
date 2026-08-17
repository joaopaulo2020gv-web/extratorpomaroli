jQuery(document).ready(function ($) {
    let selectedFiles = [];
    let currentJobId = localStorage.getItem('extrator_active_job_id') || null;
    let pollInterval = null;

    const dropzone = $('#dropzone-lote');
    const inputFiles = $('#input-pdf-files');
    const ulFiles = $('#ul-arquivos-selecionados');
    const countFilesSpan = $('#total-arquivos-count');
    const divFilesContainer = $('#lista-arquivos-selecionados');
    const btnStartBatch = $('#btn-iniciar-lote');

    const WP_REST = (window.location.origin + '/wp-json/pomaroli/v1').replace(/\/+$/, '');

    recuperarJobAtivo();

    $('#chk-usar-ocr').on('change', function () {
        $('#ocr-modelo-container').toggle($(this).is(':checked'));
    });

    dropzone.on('click', function () { inputFiles.click(); });
    dropzone.on('dragover dragenter', function (e) { e.preventDefault(); e.stopPropagation(); dropzone.addClass('drag-over'); });
    dropzone.on('dragleave drop', function (e) { e.preventDefault(); e.stopPropagation(); dropzone.removeClass('drag-over'); });
    dropzone.on('drop', function (e) { handleFilesSelection(e.originalEvent.dataTransfer.files); });
    inputFiles.on('change', function () { handleFilesSelection(this.files); });

    function handleFilesSelection(files) {
        if (!files || files.length === 0) return;
        for (let i = 0; i < files.length; i++) {
            if (files[i].type === 'application/pdf' || files[i].name.toLowerCase().endsWith('.pdf')) {
                if (!selectedFiles.some(f => f.name === files[i].name && f.size === files[i].size)) {
                    selectedFiles.push(files[i]);
                }
            }
        }
        renderSelectedFiles();
    }

    function renderSelectedFiles() {
        ulFiles.empty();
        countFilesSpan.text(selectedFiles.length);
        if (selectedFiles.length > 0) {
            divFilesContainer.show();
            btnStartBatch.prop('disabled', false);
            selectedFiles.forEach((file, index) => {
                ulFiles.append(`<li><span>📄 <strong>${file.name}</strong> (${(file.size / 1024 / 1024).toFixed(2)} MB)</span><button type="button" class="btn-remove-file" data-index="${index}">&times;</button></li>`);
            });
        } else {
            divFilesContainer.hide();
            btnStartBatch.prop('disabled', true);
        }
    }

    ulFiles.on('click', '.btn-remove-file', function () {
        selectedFiles.splice($(this).data('index'), 1);
        renderSelectedFiles();
    });

    // Upload para WordPress (não mais Python)
    $('#form-upload-lote').on('submit', function (e) {
        e.preventDefault();
        if (selectedFiles.length === 0) {
            alert('Selecione pelo menos um arquivo PDF.');
            return;
        }

        const formData = new FormData();
        selectedFiles.forEach(file => formData.append('files[]', file));
        formData.append('use_ocr', $('#chk-usar-ocr').is(':checked') ? '1' : '0');
        formData.append('use_ai', $('#chk-autocorrigir-ia').is(':checked') ? '1' : '0');
        formData.append('ai_provider', 'gemini');
        formData.append('ai_model', $('#config-ocr-model').val() || 'gemini-2.5-flash');

        btnStartBatch.prop('disabled', true).text('📤 Enviando PDFs para o WordPress...');
        $('#card-progresso-lote').show();
        $('#lote-status-badge').attr('class', 'badge-status pending').text('Enviando arquivos...');

        $.ajax({
            url: WP_REST + '/upload-local',
            type: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            timeout: 120000,
            success: function (response) {
                currentJobId = response.job ? response.job.id : null;
                if (currentJobId) {
                    localStorage.setItem('extrator_active_job_id', currentJobId);
                }

                $('#lote-id-tag').text('#' + (currentJobId || '?'));
                $('#lote-status-badge').attr('class', 'badge-status processing').text('Enfileirado para processamento');
                btnStartBatch.text('🚀 Iniciar Processamento em Lote');

                selectedFiles = [];
                renderSelectedFiles();

                startPollingJobStatus(currentJobId);
            },
            error: function (xhr) {
                let err = 'Erro ao enviar PDFs para o WordPress.';
                if (xhr.responseJSON && xhr.responseJSON.message) {
                    err = xhr.responseJSON.message;
                } else if (xhr.responseJSON && xhr.responseJSON.erro) {
                    err = xhr.responseJSON.erro;
                }
                alert('❌ ' + err);
                btnStartBatch.prop('disabled', false).text('🚀 Iniciar Processamento em Lote');
                $('#card-progresso-lote').hide();
            }
        });
    });

    function resetLoteUI() {
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = null;
        localStorage.removeItem('extrator_active_job_id');
        currentJobId = null;
        $('#card-progresso-lote').hide();
        $('#container-botao-importar').hide();
        $('#tbody-arquivos-lote').empty();
        $('#lote-progress-bar-inner').css('width', '0%').text('0%');
        $('#lote-resumo-texto').text('Processando 0 de 0 arquivos...');
        $('#lote-id-tag').text('#---');
    }

    $(document).on('click', '#btn-limpar-lote', function () {
        if (confirm('Deseja limpar o progresso do lote da tela?')) {
            resetLoteUI();
        }
    });

    function startPollingJobStatus(jobId) {
        if (pollInterval) clearInterval(pollInterval);
        $('#card-progresso-lote').show();
        $('#lote-id-tag').text('#' + jobId);

        function checkStatus() {
            $.ajax({
                url: WP_REST + '/jobs/' + jobId,
                type: 'GET',
                headers: { 'X-WP-Nonce': (window.APP_CONFIG || {}).restNonce || '' },
                credentials: 'same-origin',
                dataType: 'json',
                timeout: 15000,
                success: function (data) {
                    updateJobProgressUI(data);

                    if (data.status === 'completed' || data.status === 'failed' || data.status === 'cancelled') {
                        if (pollInterval) clearInterval(pollInterval);
                        if (data.status === 'completed') {
                            $('#lote-status-badge').attr('class', 'badge-status completed').text('✅ Lote Concluído!');
                        } else if (data.status === 'failed') {
                            $('#lote-status-badge').attr('class', 'badge-status error').text('❌ Erro no processamento');
                        } else {
                            $('#lote-status-badge').attr('class', 'badge-status error').text('⛔ Cancelado');
                        }
                    }
                },
                error: function (xhr) {
                    console.warn('[Job Polling] Falha ao consultar job:', xhr.status);
                }
            });
        }

        checkStatus();
        pollInterval = setInterval(checkStatus, 5000);
    }

    function recuperarJobAtivo() {
        if (currentJobId) {
            $.ajax({
                url: WP_REST + '/jobs/' + currentJobId,
                type: 'GET',
                headers: { 'X-WP-Nonce': (window.APP_CONFIG || {}).restNonce || '' },
                credentials: 'same-origin',
                dataType: 'json',
                timeout: 10000,
                success: function (data) {
                    startPollingJobStatus(currentJobId);
                },
                error: function (xhr) {
                    if (xhr.status === 404) {
                        localStorage.removeItem('extrator_active_job_id');
                        currentJobId = null;
                    }
                }
            });
            return;
        }
    }

    function updateJobProgressUI(data) {
        const totalFiles = data.total_files || 0;
        const processedFiles = data.processed_files || 0;
        const percent = data.progress || 0;
        const totalPages = data.total_pages || 0;
        const currentPage = data.current_page || 0;
        const totalQuestions = data.total_questions || 0;

        if (data.status === 'queued') {
            $('#lote-status-badge').attr('class', 'badge-status pending').text('⏳ Na Fila');
        } else if (data.status === 'processing') {
            $('#lote-status-badge').attr('class', 'badge-status processing').text(`⚙️ Processando (${processedFiles}/${totalFiles})`);
        } else if (data.status === 'completed') {
            $('#lote-status-badge').attr('class', 'badge-status completed').text('✅ Concluído!');
        } else if (data.status === 'failed') {
            $('#lote-status-badge').attr('class', 'badge-status error').text('❌ Erro');
        }

        $('#lote-progress-bar-inner').css('width', percent + '%').text(percent + '%');

        let resumeText = `${processedFiles} de ${totalFiles} arquivos`;
        if (totalPages > 0) {
            resumeText += ` | Página ${currentPage}/${totalPages}`;
        }
        resumeText += ` | ${totalQuestions} questões extraídas`;
        $('#lote-resumo-texto').text(resumeText);

        const tbody = $('#tbody-arquivos-lote');
        tbody.empty();

        if (data.files && data.files.length > 0) {
            data.files.forEach((file, index) => {
                let badgeClass = 'pending';
                let statusText = 'Na Fila';

                if (file.status === 'processing') {
                    badgeClass = 'processing';
                    statusText = '⚙️ Processando...';
                } else if (file.status === 'completed') {
                    badgeClass = 'completed';
                    statusText = '✅ Concluído';
                } else if (file.status === 'failed') {
                    badgeClass = 'error';
                    statusText = '❌ ' + (file.error_message || 'Erro');
                }

                tbody.append(`<tr>
                    <td><strong>${index + 1}</strong></td>
                    <td>📄 ${file.filename}</td>
                    <td><span class="badge-status ${badgeClass}">${statusText}</span></td>
                    <td><strong>${file.questions_found || 0}</strong> questões</td>
                    <td>${file.pages || 0} págs</td>
                </tr>`);
            });
        } else {
            tbody.append('<tr><td colspan="5" style="text-align:center; color:#888; padding:15px;">Aguardando processamento...</td></tr>');
        }
    }

    // Importar questões para o WP (via REST API)
    $('#btn-importar-wp').on('click', function () {
        if (!currentJobId) {
            alert('Nenhum job ativo para importar.');
            return;
        }

        const btn = $(this);
        btn.prop('disabled', true).text('💾 Importando...');

        $.ajax({
            url: WP_REST + '/questions/import-to-wp',
            type: 'POST',
            headers: { 'X-WP-Nonce': (window.APP_CONFIG || {}).restNonce || '' },
            credentials: 'same-origin',
            contentType: 'application/json',
            data: JSON.stringify({ job_id: currentJobId }),
            success: function (response) {
                alert('✅ ' + (response.imported || 0) + ' questões importadas!');
                btn.text('✅ Concluído!');
                setTimeout(() => window.location.reload(), 1500);
            },
            error: function (xhr) {
                alert('❌ Erro na importação.');
                btn.prop('disabled', false).text('💾 Importar Questões no WordPress');
            }
        });
    });

    // Salvar Configurações (Gemini Key, etc.)
    $('#form-config-extrator').on('submit', function (e) {
        e.preventDefault();
        const geminiKey = $('#config-gemini-key').val();
        const workerSecret = $('#config-worker-secret').val();
        const btn = $(this).find('button[type="submit"]');

        btn.prop('disabled', true).text('💾 Salvando...');

        $.ajax({
            url: (window.extratorWPConfig || {}).ajaxurl || '/wp-admin/admin-ajax.php',
            type: 'POST',
            data: {
                action: 'extrator_salvar_config',
                nonce: (window.extratorWPConfig || {}).nonce || '',
                gemini_key: geminiKey,
                worker_secret: workerSecret,
            },
            success: function (response) {
                btn.prop('disabled', false).text('Salvar Configurações');
                if (response.success) {
                    alert('✅ ' + (response.data.message || 'Configurações salvas com sucesso!'));
                } else {
                    alert('❌ ' + ((response.data && response.data.message) || 'Erro ao salvar configurações.'));
                }
            },
            error: function () {
                btn.prop('disabled', false).text('Salvar Configurações');
                alert('❌ Erro na comunicação com o servidor.');
            }
        });
    });
});
